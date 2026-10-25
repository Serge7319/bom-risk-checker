"""Login handoff UX contracts under the auth-gate state machine."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
AUTH_GATE = (ROOT / "src" / "auth_gate.py").read_text(encoding="utf-8")


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

    def test_successful_login_keeps_handoff_until_runtime_workspace_load(self):
        ready_branch = BOOTSTRAP[
            BOOTSTRAP.find('if gate_state == "ready" and already_authenticated') :
            BOOTSTRAP.find("# FIRST paint for signed-out / restore / credential flows only.")
        ]
        self.assertIn("if shell_mounted:", ready_branch)
        self.assertIn("clear_login_handoff()", ready_branch)

        handoff_flow = BOOTSTRAP[
            BOOTSTRAP.find("# Authenticating: process stashed credentials") :
            BOOTSTRAP.find("bootstrap_cookie_source =")
        ]
        self.assertNotIn("clear_login_handoff()", handoff_flow)
        self.assertIn("progress_message=login_handoff_message()", handoff_flow)

    def test_authenticating_gate_uses_workspace_stage_message(self):
        gate_branch = AUTH_GATE[
            AUTH_GATE.find('if state == "authenticating":') :
            AUTH_GATE.find('if state == "error":')
        ]
        self.assertIn("login_handoff_message()", gate_branch)
        self.assertIn("resolved_progress_message", gate_branch)

        message_helper = BOOTSTRAP[
            BOOTSTRAP.find("def login_handoff_message()") :
            BOOTSTRAP.find("def mark_authenticated_entry_shell")
        ]
        self.assertIn("AUTH_AUTHENTICATED", message_helper)
        self.assertIn("AUTHENTICATED_STARTUP_SHELL_MESSAGE", message_helper)

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
