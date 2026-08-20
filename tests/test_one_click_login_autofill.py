"""Regression coverage for one-click explicit Login submission."""
from __future__ import annotations

import importlib
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_auth_mode_card_shell import _install_auth_ui_stub


REPO = Path(__file__).resolve().parents[1]
AUTH_PATH = REPO / "src" / "auth.py"


class OneClickLoginWidgetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AUTH_PATH.read_text(encoding="utf-8")

    def test_login_inputs_have_stable_keys(self):
        self.assertIn('AUTH_EMAIL_WIDGET_KEY = "cadivor_auth_email"', self.source)
        self.assertIn('AUTH_PASSWORD_WIDGET_KEY = "cadivor_auth_password"', self.source)
        self.assertIn("key=AUTH_EMAIL_WIDGET_KEY", self.source)
        self.assertIn("key=AUTH_PASSWORD_WIDGET_KEY", self.source)

    def test_login_inputs_use_browser_login_autocomplete(self):
        self.assertIn('autocomplete="email"', self.source)
        self.assertIn('autocomplete="current-password"', self.source)

    def test_login_uses_one_native_form_and_explicit_submit(self):
        self.assertIn('with st.form("cadivor_login_form"', self.source)
        self.assertIn("submit = st.form_submit_button(", self.source)
        self.assertIn('key="cadivor_login_submit"', self.source)

    def test_no_automatic_password_submission_or_browser_replay(self):
        for removed in (
            "AUTH_LOGIN_SUBMIT_REQUESTED_KEY",
            "_request_manual_login_submit",
            "on_change=",
            "_install_login_pointerdown_bridge",
            "cadivorCommitThenSubmit",
            'addEventListener("pointerdown"',
        ):
            self.assertNotIn(removed, self.source)

    def test_fix_does_not_add_transport_or_sensitive_submit_state(self):
        self.assertNotIn("cadivor_auth_submission", self.source)
        self.assertNotIn("ThreadPoolExecutor", self.source)
        self.assertNotIn("httpx.Client", self.source)

    def test_non_submit_rerun_never_calls_provider(self):
        st = _install_auth_ui_stub({})
        auth = importlib.import_module("src.auth")
        st.session_state[auth.AUTH_MODE_WIDGET_KEY] = auth.AUTH_MODE_LOGIN
        st.text_input.side_effect = ["engineer@example.com", "typed-password"]
        st.form_submit_button.return_value = False
        st.button.return_value = False
        supabase = MagicMock()

        auth._render_auth_page(supabase, MagicMock(), auth.AUTH_MODE_LOGIN)

        supabase.auth.sign_in_with_password.assert_not_called()

    def test_one_explicit_submit_calls_existing_provider_once(self):
        st = _install_auth_ui_stub({})
        auth = importlib.import_module("src.auth")
        state = importlib.import_module("src.auth_state")
        st.session_state[auth.AUTH_MODE_WIDGET_KEY] = auth.AUTH_MODE_LOGIN
        st.text_input.side_effect = ["engineer@example.com", "correct-password"]
        st.form_submit_button.return_value = True

        user = MagicMock()
        session = MagicMock()
        response = MagicMock(user=user, session=session)
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.return_value = response
        cookie_manager = MagicMock()

        with (
            patch.object(auth, "begin_manual_login"),
            patch.object(auth, "render_auth_transition"),
            patch.object(auth, "mark_authenticated") as mark_authenticated,
        ):
            auth._render_auth_page(
                supabase=supabase,
                cookie_manager=cookie_manager,
                initial_mode=auth.AUTH_MODE_LOGIN,
            )

        supabase.auth.sign_in_with_password.assert_called_once_with(
            {
                "email": "engineer@example.com",
                "password": "correct-password",
            }
        )
        mark_authenticated.assert_called_once_with(user, session, cookie_manager)
        st.rerun.assert_called_once()
        self.assertEqual(st.session_state["cadivor_root_state"], state.APP_SIGNING_IN)


if __name__ == "__main__":
    unittest.main()
