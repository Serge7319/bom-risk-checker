"""UI workflow stage + account-scoped analyze job contracts (Node strip-types)."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "helpers" / "bom_workflow_node_runner.mjs"


class BomWorkflowGuideStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RUNNER.exists():
            raise unittest.SkipTest("workflow node runner missing")
        node = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if node.returncode != 0:
            raise unittest.SkipTest("node unavailable")

    def _run(self, suite: str) -> dict:
        env = os.environ.copy()
        env["NODE_OPTIONS"] = "--experimental-strip-types"
        proc = subprocess.run(
            ["node", "--experimental-strip-types", str(RUNNER), suite],
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
                f"node runner did not return JSON (exit={proc.returncode}): "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r} err={exc}"
            )
        if proc.returncode != 0 or not payload.get("ok"):
            self.fail(payload.get("error") or f"runner failed: {payload}")
        return payload

    def test_workflow_states_initial_validating_ready_analyzing_success_error(self):
        payload = self._run("workflow")
        for expected in ("initial", "validating", "ready", "analyzing", "success", "error"):
            self.assertIn(expected, payload["cases"])

    def test_account_switch_while_analyze_job_running(self):
        payload = self._run("jobs")
        self.assertIn("account-switch-in-flight", payload["cases"])

    def test_same_user_workspace_isolation_for_jobs_and_drafts(self):
        payload = self._run("workspace")
        self.assertIn("workspace-switch-same-user", payload["cases"])

    def test_file_identity_distinguishes_same_meta_different_bytes(self):
        payload = self._run("identity")
        self.assertIn("content-identity-same-meta-different-bytes", payload["cases"])


if __name__ == "__main__":
    unittest.main()
