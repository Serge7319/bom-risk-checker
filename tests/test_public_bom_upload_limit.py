"""Executable Content-Length gate for the Next.js public BOM audit proxy."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIMIT_JS = ROOT / "apps/web/src/lib/publicBomUploadLimit.js"
PROXY_TS = ROOT / "apps/web/src/lib/publicBomProxy.ts"


class PublicBomUploadLimitTests(unittest.TestCase):
    def _eval(self, header):
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

    def test_proxy_rejects_before_formdata_buffering(self):
        proxy = PROXY_TS.read_text()
        self.assertIn("rejectOversizedPublicBomAudit(request)", proxy)
        self.assertLess(
            proxy.index("rejectOversizedPublicBomAudit(request)"),
            proxy.index("await request.formData()"),
        )
        self.assertIn("evaluatePublicBomAuditContentLength", proxy)

    def test_missing_content_length_is_rejected(self):
        payload = self._eval(None)
        self.assertFalse(payload["verdict"]["ok"])
        self.assertEqual(payload["verdict"]["status"], 411)

    def test_empty_content_length_is_rejected(self):
        payload = self._eval("")
        self.assertFalse(payload["verdict"]["ok"])
        self.assertEqual(payload["verdict"]["status"], 411)

    def test_invalid_content_length_is_rejected(self):
        for raw in ("abc", "-1", "12.5", "1e6"):
            with self.subTest(raw=raw):
                payload = self._eval(raw)
                self.assertFalse(payload["verdict"]["ok"])
                self.assertEqual(payload["verdict"]["status"], 400)

    def test_oversized_content_length_is_rejected_before_buffering(self):
        max_bytes = self._eval("1")["MAX_PUBLIC_BOM_REQUEST_BYTES"]
        oversized = self._eval(str(max_bytes + 1))
        self.assertFalse(oversized["verdict"]["ok"])
        self.assertEqual(oversized["verdict"]["status"], 413)
        self.assertIn("1 MB", oversized["verdict"]["detail"])

    def test_within_limit_content_length_is_accepted(self):
        max_bytes = self._eval("1")["MAX_PUBLIC_BOM_REQUEST_BYTES"]
        payload = self._eval(str(max_bytes))
        self.assertTrue(payload["verdict"]["ok"])
        self.assertEqual(payload["verdict"]["length"], max_bytes)


if __name__ == "__main__":
    unittest.main()
