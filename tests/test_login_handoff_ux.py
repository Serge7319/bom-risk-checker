"""Login handoff UX contracts under the auth-gate state machine."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")


class LoginHandoffGateUx(unittest.TestCase):
    def test_submit_stashes_for_authenticating_run(self):
        submit = AUTH[
            AUTH.find("def _submit_manual_login") : AUTH.find("def execute_password_login")
        ]
        self.assertIn("stash_pending_credentials", submit)
        self.assertIn('set_auth_gate_state("authenticating"', submit)

    def test_fail_login_sets_gate_login(self):
        self.assertIn('set_auth_gate_state(\n        "login"', BOOTSTRAP)
        self.assertIn('reason="login_handoff_failed"', BOOTSTRAP)

    def test_should_render_shell_retired(self):
        st = MagicMock()
        st.session_state = {}
        with patch.dict("sys.modules", {"streamlit": st}):
            import importlib
            import src.auth_bootstrap as bootstrap

            importlib.reload(bootstrap)
            self.assertFalse(bootstrap.should_render_authenticated_startup_shell())


if __name__ == "__main__":
    unittest.main()
