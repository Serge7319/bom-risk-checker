"""Login handoff UX regressions: one-click submit, progress state, no blank gap."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_manual_login_atomic import ManualLoginAtomicTests


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src" / "components" / "atomic_login" / "index.html").read_text(
    encoding="utf-8"
)
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


class LoginHandoffUxTests(unittest.TestCase):
    def setUp(self):
        self.helper = ManualLoginAtomicTests(
            methodName="test_login_submit_calls_sign_in_in_same_script_run"
        )
        self.helper.setUp()

    def tearDown(self):
        self.helper.doCleanups()

    def _load_auth(self, session_state=None):
        return self.helper._load_auth(session_state)

    def test_one_click_submit_consumes_request_id_once(self):
        self.assertIn("request_id != consumed_id", AUTH)
        self.assertIn('AUTH_ATOMIC_LOGIN_CONSUMED_KEY] = request_id', AUTH)
        self.assertIn("submitted = true", HTML)
        self.assertIn("if (submitted || button.disabled) return", HTML)

    def test_enter_submit_uses_native_form_submit(self):
        self.assertIn('<form id="login"', HTML)
        self.assertIn('form.addEventListener("submit"', HTML)
        self.assertIn('type="submit"', HTML)
        self.assertIn("event.preventDefault()", HTML)

    def test_in_flight_duplicate_suppression_disables_controls(self):
        self.assertIn("button.disabled = Boolean(isBusy) || submitted", HTML)
        self.assertIn("email.disabled = Boolean(isBusy)", HTML)
        self.assertIn("password.disabled = Boolean(isBusy)", HTML)
        self.assertIn("disabled=login_in_flight", AUTH)
        self.assertIn('cadivor_login_handoff_active', AUTH)

    def test_successful_handoff_keeps_branded_surface_not_blank(self):
        self.assertIn("Signing you in…", AUTH)
        self.assertIn("LOGIN_HANDOFF_ACTIVE_KEY", BOOTSTRAP)
        self.assertIn("should_render_authenticated_startup_shell()", BOOTSTRAP)
        self.assertIn(
            "if not should_render_authenticated_startup_shell():\n"
            "        auth_surface_host.empty()",
            BOOTSTRAP,
        )
        self.assertIn("render_auth_transition(AUTHENTICATED_STARTUP_SHELL_MESSAGE)", BOOTSTRAP)
        self.assertIn("clear_login_handoff()", RUNTIME)
        self.assertIn('AUTHENTICATED_STARTUP_SHELL_MESSAGE = "Signing you in…"', BOOTSTRAP)

        st, auth, auth_state = self._load_auth()
        transitions = []

        with patch.object(
            auth,
            "render_auth_transition",
            side_effect=lambda message="": transitions.append(str(message)),
        ):
            auth._submit_manual_login(
                MagicMock(
                    auth=MagicMock(
                        sign_in_with_password=MagicMock(
                            return_value=types.SimpleNamespace(
                                user=types.SimpleNamespace(id="u1"),
                                session=types.SimpleNamespace(
                                    access_token="access",
                                    refresh_token="refresh",
                                ),
                            )
                        )
                    )
                ),
                MagicMock(),
                "user@example.com",
                "password-value",
            )

        self.assertIn("Signing you in…", transitions)
        self.assertTrue(st.session_state.get("cadivor_login_handoff_active"))
        st.rerun.assert_called_once_with()

    def test_failed_login_returns_form_with_error_and_email(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = RuntimeError("denied")

        auth._submit_manual_login(
            supabase, MagicMock(), "keepme@example.com", "password-value"
        )

        self.assertEqual(st.session_state["cadivor_root_state"], auth.APP_LOGIN)
        self.assertEqual(
            st.session_state["cadivor_auth_error"],
            auth.MANUAL_LOGIN_FAILURE_MESSAGE,
        )
        self.assertEqual(
            st.session_state["cadivor_login_email_draft"],
            "keepme@example.com",
        )
        self.assertFalse(st.session_state.get("cadivor_login_handoff_active", False))
        self.assertIn("prefill_email=draft_email", AUTH)
        self.assertIn("error_message=", AUTH)
        self.assertIn("args.prefill_email", HTML)
        self.assertIn("args.error_message", HTML)

    def test_signing_in_state_does_not_reset_to_login_form(self):
        self.assertIn("if state == APP_SIGNING_IN:", AUTH)
        block = AUTH[
            AUTH.index("if state == APP_SIGNING_IN:") : AUTH.index(
                "if state in (APP_LOGIN, APP_SIGNUP):"
            )
        ]
        self.assertIn('render_auth_transition("Signing you in…")', block)
        self.assertIn("return", block)
        self.assertNotIn('cadivor_root_state"] = APP_LOGIN', block)


if __name__ == "__main__":
    unittest.main()
