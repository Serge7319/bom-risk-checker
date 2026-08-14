"""Sprint 74.2B — signup confirmation handoff tests."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub


class SignupConfirmationPendingTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.markdown = MagicMock()
        self.st.button = MagicMock(return_value=False)
        self.st.success = MagicMock()
        self.st.error = MagicMock()
        self.st.rerun = MagicMock()
        self.st.warning = MagicMock()
        for mod in ("src.auth", "src.auth_state", "src.auth_recovery"):
            sys.modules.pop(mod, None)

    def _load_auth(self):
        return importlib.import_module("src.auth")

    def _load_state(self):
        return importlib.import_module("src.auth_state")

    def test_successful_signup_without_session_enters_pending_state(self):
        auth = self._load_auth()
        state = self._load_state()
        supabase = MagicMock()
        supabase.auth.sign_up.return_value = types.SimpleNamespace(user=object(), session=None)

        with patch.object(auth, "begin_manual_login"), patch.object(auth, "render_auth_transition"), patch.object(
            auth, "_log_manual_login_event"
        ):
            auth._submit_manual_signup(supabase, MagicMock(), "new@cadivor.com", "secret-password")

        self.assertEqual(self.st.session_state["cadivor_root_state"], state.APP_SIGNUP_CONFIRMATION_PENDING)
        self.assertEqual(self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY], "new@cadivor.com")
        self.assertEqual(self.st.session_state["cadivor_auth_status"], state.AUTH_SIGNED_OUT)
        self.assertNotIn("password", self.st.session_state)
        self.assertNotIn("cadivor_signup_password", self.st.session_state)
        self.assertNotIn("cadivor_auth_password", self.st.session_state)
        self.assertNotIn("cadivor_auth_notice", self.st.session_state)
        self.st.rerun.assert_called_once()
        self.st.success.assert_not_called()

    def test_signup_failure_does_not_enter_pending_state(self):
        auth = self._load_auth()
        state = self._load_state()
        supabase = MagicMock()
        supabase.auth.sign_up.side_effect = Exception("User already registered")

        with patch.object(auth, "begin_manual_login"), patch.object(auth, "render_auth_transition"), patch.object(
            auth, "_log_manual_login_event"
        ), patch.object(auth, "finish_manual_login_failed") as finish_failed:
            auth._submit_manual_signup(supabase, MagicMock(), "dup@cadivor.com", "secret-password")

        finish_failed.assert_called_once()
        self.assertEqual(self.st.session_state["cadivor_root_state"], state.APP_LOGIN)
        self.assertNotEqual(
            self.st.session_state.get("cadivor_root_state"),
            state.APP_SIGNUP_CONFIRMATION_PENDING,
        )
        self.assertNotIn(state.SIGNUP_PENDING_EMAIL_KEY, self.st.session_state)
        self.assertIn("Account creation failed", self.st.session_state.get("cadivor_auth_error", ""))

    def test_signup_with_session_preserves_authenticated_flow(self):
        auth = self._load_auth()
        state = self._load_state()
        supabase = MagicMock()
        user = types.SimpleNamespace(email_confirmed_at="2024-01-01T00:00:00Z", email="live@cadivor.com")
        session = types.SimpleNamespace(access_token="access-token", refresh_token="refresh-token", user=user)
        supabase.auth.sign_up.return_value = types.SimpleNamespace(user=user, session=session)

        with patch.object(auth, "begin_manual_login"), patch.object(auth, "render_auth_transition"), patch.object(
            auth, "_log_manual_login_event"
        ), patch.object(auth, "mark_authenticated") as mark_auth:
            auth._submit_manual_signup(supabase, MagicMock(), "live@cadivor.com", "secret-password")

        mark_auth.assert_called_once()
        self.assertNotEqual(
            self.st.session_state.get("cadivor_root_state"),
            state.APP_SIGNUP_CONFIRMATION_PENDING,
        )
        self.assertNotIn(state.SIGNUP_PENDING_EMAIL_KEY, self.st.session_state)
        self.st.rerun.assert_called_once()

    def test_pending_state_renders_check_your_email_and_suppresses_login_form(self):
        auth = self._load_auth()
        state = self._load_state()
        self.st.session_state["cadivor_root_state"] = state.APP_SIGNUP_CONFIRMATION_PENDING
        self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY] = "pending@cadivor.com"

        with patch.object(auth, "_auth_css"), patch.object(auth, "inject_core_premium_ui_auth"), patch.object(
            auth, "_render_signup_confirmation_pending"
        ) as pending, patch.object(auth, "_render_auth_page") as login_form, patch.object(
            auth, "_render_password_recovery_form"
        ) as recovery_form, patch.object(auth, "_auth_recovery") as recovery_factory:
            recovery_factory.return_value.password_recovery_active.return_value = False
            auth.show_auth_ui(MagicMock(), None)

        pending.assert_called_once()
        login_form.assert_not_called()
        recovery_form.assert_not_called()

    def test_pending_surface_shows_email_and_required_copy(self):
        auth = self._load_auth()
        state = self._load_state()
        self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY] = "pending@cadivor.com"
        bodies: list[str] = []

        def capture_markdown(body, **kwargs):
            bodies.append(str(body))

        self.st.markdown.side_effect = capture_markdown
        auth._render_signup_confirmation_pending()
        joined = "\n".join(bodies)
        self.assertIn("Check your email", joined)
        self.assertIn("pending@cadivor.com", joined)
        self.assertIn("Email confirmation required", joined)
        self.assertIn("Confirm my email", joined)
        self.assertIn("spam or promotions folder", joined)
        self.assertNotIn("secret-password", joined)
        self.assertNotIn("cadivor_auth_form", joined)

    def test_return_to_login_clears_pending_and_does_not_restore_password(self):
        auth = self._load_auth()
        state = self._load_state()
        self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY] = "pending@cadivor.com"
        self.st.session_state["cadivor_signup_password"] = "should-not-survive"
        self.st.session_state["cadivor_root_state"] = state.APP_SIGNUP_CONFIRMATION_PENDING
        self.st.button.return_value = True

        auth._render_signup_confirmation_pending()

        self.assertEqual(self.st.session_state["cadivor_root_state"], state.APP_LOGIN)
        self.assertNotIn(state.SIGNUP_PENDING_EMAIL_KEY, self.st.session_state)
        self.assertNotIn("cadivor_signup_password", self.st.session_state)
        self.st.rerun.assert_called_once()

    def test_normal_login_does_not_render_confirmation_pending_controls(self):
        auth = self._load_auth()
        self.st.session_state["cadivor_root_state"] = "login"

        with patch.object(auth, "_auth_css"), patch.object(auth, "inject_core_premium_ui_auth"), patch.object(
            auth, "_render_signup_confirmation_pending"
        ) as pending, patch.object(auth, "_render_auth_page") as login_form, patch.object(
            auth, "_render_password_recovery_form"
        ) as recovery_form, patch.object(auth, "_auth_recovery") as recovery_factory:
            recovery_factory.return_value.password_recovery_active.return_value = False
            recovery_factory.return_value._RECOVERY_NOTICE_KEY = "cadivor_recovery_notice"
            auth.show_auth_ui(MagicMock(), None)

        login_form.assert_called_once()
        pending.assert_not_called()
        recovery_form.assert_not_called()

    def test_recovery_state_remains_unaffected(self):
        auth = self._load_auth()
        state = self._load_state()
        self.st.session_state["cadivor_root_state"] = state.APP_PASSWORD_RECOVERY
        self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY] = "should-not-win@cadivor.com"

        with patch.object(auth, "_auth_css"), patch.object(auth, "inject_core_premium_ui_auth"), patch.object(
            auth, "_render_signup_confirmation_pending"
        ) as pending, patch.object(auth, "_render_auth_page") as login_form, patch.object(
            auth, "_render_password_recovery_form"
        ) as recovery_form, patch.object(auth, "_auth_recovery") as recovery_factory:
            recovery_factory.return_value.password_recovery_active.return_value = True
            auth.show_auth_ui(MagicMock(), None)

        recovery_form.assert_called_once()
        pending.assert_not_called()
        login_form.assert_not_called()


if __name__ == "__main__":
    unittest.main()
