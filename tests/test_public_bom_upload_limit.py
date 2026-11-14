"""Executable body-limit gate for the Next.js public BOM audit proxy."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIMIT_JS = ROOT / "apps/web/src/lib/publicBomUploadLimit.js"
PROXY_TS = ROOT / "apps/web/src/lib/publicBomProxy.ts"


class PublicBomUploadLimitTests(unittest.TestCase):
    def _eval_length(self, header):
        script = f"""
import {{ evaluatePublicBomAuditContentLength, MAX_PUBLIC_BOM_REQUEST_BYTES }} from {json.dumps(str(LIMIT_JS))};
const verdict = evaluatePublicBomAuditContentLength({json.dumps(header)});
console.log(JSON.stringify({{ verdict, MAX_PUBLIC_BOM_REQUEST_BYTES }}));
"""
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"node failed\nstdout={proc.stdout}\nstderr={proc.stderr}",
        )
        return json.loads(proc.stdout.strip())

    def _eval_stream(self, sizes, max_bytes=None):
        max_arg = "undefined" if max_bytes is None else str(max_bytes)
        script = f"""
import {{ readBodyWithByteLimit, MAX_PUBLIC_BOM_REQUEST_BYTES }} from {json.dumps(str(LIMIT_JS))};
const sizes = {json.dumps(sizes)};
const chunks = sizes.map((n) => new Uint8Array(n));
let i = 0;
const body = {{
  getReader() {{
    return {{
      async read() {{
        if (i >= chunks.length) return {{ done: true, value: undefined }};
        const value = chunks[i++];
        return {{ done: false, value }};
      }},
      async cancel() {{}}
    }};
  }}
}};
const verdict = await readBodyWithByteLimit(body, {max_arg});
console.log(JSON.stringify({{
  ok: verdict.ok,
  status: verdict.status || null,
  detail: verdict.detail || null,
  bytes: verdict.ok ? verdict.buffer.byteLength : null,
  MAX_PUBLIC_BOM_REQUEST_BYTES
}}));
"""
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"node failed\nstdout={proc.stdout}\nstderr={proc.stderr}",
        )
        return json.loads(proc.stdout.strip())

    def test_proxy_bounds_before_formdata_and_supports_missing_content_length(self):
        proxy = PROXY_TS.read_text()
        self.assertIn("readPublicBomAuditForm(request)", proxy)
        self.assertIn("readBodyWithByteLimit", proxy)
        self.assertIn("lengthVerdict.stream", proxy)
        self.assertNotIn("Content-Length is required", proxy)
        audit_fn = proxy[proxy.index("export async function proxyPublicBomAudit") :]
        self.assertLess(
            audit_fn.index("readPublicBomAuditForm(request)"),
            audit_fn.index('fetch(`${apiBase()}/public/bom-stress/audit`'),
        )

    def test_missing_content_length_defers_to_streaming(self):
        payload = self._eval_length(None)
        self.assertTrue(payload["verdict"]["ok"])
        self.assertTrue(payload["verdict"]["stream"])
        self.assertIsNone(payload["verdict"]["length"])

    def test_empty_content_length_defers_to_streaming(self):
        payload = self._eval_length("")
        self.assertTrue(payload["verdict"]["ok"])
        self.assertTrue(payload["verdict"]["stream"])

    def test_invalid_content_length_is_rejected(self):
        for raw in ("abc", "-1", "12.5", "1e6"):
            with self.subTest(raw=raw):
                payload = self._eval_length(raw)
                self.assertFalse(payload["verdict"]["ok"])
                self.assertEqual(payload["verdict"]["status"], 400)

    def test_oversized_content_length_is_rejected_before_buffering(self):
        max_bytes = self._eval_length("1")["MAX_PUBLIC_BOM_REQUEST_BYTES"]
        oversized = self._eval_length(str(max_bytes + 1))
        self.assertFalse(oversized["verdict"]["ok"])
        self.assertEqual(oversized["verdict"]["status"], 413)
        self.assertIn("1 MB", oversized["verdict"]["detail"])

    def test_within_limit_content_length_is_accepted(self):
        max_bytes = self._eval_length("1")["MAX_PUBLIC_BOM_REQUEST_BYTES"]
        payload = self._eval_length(str(max_bytes))
        self.assertTrue(payload["verdict"]["ok"])
        self.assertFalse(payload["verdict"]["stream"])
        self.assertEqual(payload["verdict"]["length"], max_bytes)

    def test_streaming_rejects_oversized_body_without_content_length(self):
        max_bytes = self._eval_length("1")["MAX_PUBLIC_BOM_REQUEST_BYTES"]
        result = self._eval_stream([max_bytes // 2, max_bytes // 2 + 2], max_bytes)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 413)

    def test_streaming_accepts_body_within_limit(self):
        result = self._eval_stream([100, 200, 300], 1000)
        self.assertTrue(result["ok"])
        self.assertEqual(result["bytes"], 600)


if __name__ == "__main__":
    unittest.main()
