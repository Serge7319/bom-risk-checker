"""UI presentation contracts for Find a replacement empty/candidate states."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "helpers" / "find_replacement_presentation_runner.mjs"


class FindReplacementPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RUNNER.exists():
            raise unittest.SkipTest("presentation runner missing")
        node = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if node.returncode != 0:
            raise unittest.SkipTest("node unavailable")

    def _run(self) -> dict:
        env = os.environ.copy()
        env["NODE_OPTIONS"] = "--experimental-strip-types"
        proc = subprocess.run(
            ["node", "--experimental-strip-types", str(RUNNER)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        raw = (proc.stdout or "").strip().splitlines()
        payload_line = raw[-1] if raw else ""
        try:
            payload = json.loads(payload_line)
        except json.JSONDecodeError as exc:
            self.fail(
                f"runner did not return JSON (exit={proc.returncode}): "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r} err={exc}"
            )
        if proc.returncode != 0 or not payload.get("ok"):
            self.fail(payload.get("error") or f"runner failed: {payload}")
        return payload

    def test_no_provider_empty_state_and_candidate_rendering(self):
        payload = self._run()
        for expected in (
            "redacts-credentials",
            "provider-status-distinctions",
            "no-provider-empty-state",
            "returned-candidate-rendering",
        ):
            self.assertIn(expected, payload["cases"])


if __name__ == "__main__":
    unittest.main()
