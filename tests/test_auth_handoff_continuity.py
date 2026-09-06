"""Auth gate ownership contracts — replaces legacy auth_surface_host assertions."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
GATE = (ROOT / "src" / "auth_gate.py").read_text(encoding="utf-8")


class AuthGateOwnerContracts(unittest.TestCase):
    def test_gate_is_sole_bootstrap_painter(self):
        fn = BOOTSTRAP[
            BOOTSTRAP.find("def ensure_authenticated_or_stop") : BOOTSTRAP.find(
                "# NOTE: auth gate owns paint"
            )
        ]
        self.assertIn("paint_auth_gate(", fn)
        self.assertIn("set_auth_gate_state(", fn)
        self.assertNotIn("auth_surface_host = st.empty()", fn)
        self.assertNotIn("auth_surface_host.empty()", fn)
        self.assertNotIn("render_startup_loading_shell(", fn)
        self.assertNotIn("mount_auth_progress_surface(auth_surface_host)", fn)

    def test_login_submit_is_two_phase(self):
        submit = AUTH[
            AUTH.find("def _submit_manual_login") : AUTH.find("def execute_password_login")
        ]
        self.assertIn("stash_pending_credentials", submit)
        self.assertIn('set_auth_gate_state("authenticating"', submit)
        self.assertIn("st.rerun()", submit)
        self.assertNotIn("mount_auth_progress_surface", submit)
        self.assertNotIn("render_startup_loading_shell", submit)

    def test_entrypoint_never_paints_competing_shell(self):
        self.assertIn("ensure_authenticated_or_stop()", APP)
        self.assertNotIn("should_render_authenticated_startup_shell()", APP)
        self.assertNotIn("render_startup_loading_shell(", APP)

    def test_gate_surfaces_have_no_fake_topbar(self):
        self.assertIn("data-auth-gate=", GATE)
        self.assertIn("Restoring your session…", GATE)
        self.assertIn("Signing you in…", GATE)
        self.assertNotIn("cv-startup-shell-topbar", GATE)
        self.assertNotRegex(GATE, r"(?m)^\s*st\.empty\(\)")

    def test_legacy_shell_apis_redirect_to_gate(self):
        self.assertIn('set_auth_gate_state("authenticating", reason="legacy_mount_redirect")', BOOTSTRAP)
        self.assertIn("Always False — competing startup shells are retired", BOOTSTRAP)
        self.assertNotIn("cv-startup-shell-topbar", BOOTSTRAP)

    def test_signing_in_branch_uses_gate(self):
        block = AUTH[AUTH.find("if state == APP_SIGNING_IN:") : AUTH.find("if state in (APP_LOGIN, APP_SIGNUP):")]
        self.assertIn("paint_auth_gate(\"authenticating\")", block)
        self.assertNotIn("mount_auth_progress_surface", block)


if __name__ == "__main__":
    unittest.main()
