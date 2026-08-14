"""Sprint 74.2B.2 — security-safe signup confirmation handoff copy and actions."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub


class SignupConfirmationSafeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.markdown = MagicMock()
        self.st.button = MagicMock(return_value=False)
        self.st.success = MagicMock()
        self.st.error = MagicMock()
        self.st.rerun = MagicMock()
        self.st.warning = MagicMock()
        self.st.query_params = {}
        for mod in ("src.auth", "src.auth_state", "src.auth_recovery"):
            sys.modules.pop(mod, None)

    def _load_auth(self):
        return importlib.import_module("src.auth")

    def _load_state(self):
        return importlib.import_module("src.auth_state")

    def _click(self, key: str):
        def _button(label, key=None, **kwargs):
            return key == key_name

        key_name = key
        self.st.button.side_effect = _button

    def _render_bodies(self, auth) -> str:
        bodies: list[str] = []

        def capture(body, **kwargs):
            bodies.append(str(body))

        self.st.markdown.side_effect = capture
        auth._render_signup_confirmation_pending()
        return "\n".join(bodies)

    def test_safe_handoff_copy_required_and_forbidden_phrases(self):
        auth = self._load_auth()
        state = self._load_state()
        self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY] = "user@example.com"
        joined = self._render_bodies(auth)

        self.assertIn("Signup request received", joined)
        self.assertIn("Check your email", joined)
        self.assertIn("If this address is eligible for account creation", joined)
        self.assertIn("Already have a Cadivor account? Sign in or reset your password.", joined)
        self.assertIn("We’ve received your signup request for:", joined)
        self.assertIn("user@example.com", joined)

        self.assertNotIn("Confirmation email sent", joined)
        self.assertNotIn("We sent a confirmation link", joined)
        self.assertNotIn("This email is already registered", joined)
        self.assertNotIn("Account already exists", joined)
        self.assertNotIn("Email confirmation required", joined)
        self.assertNotRegex(joined, r"(?i)we (have )?sent (a |the )?confirmation")
        self.assertNotRegex(joined, r"(?i)confirmation email sent")

    def test_new_and_obfuscated_existing_shapes_share_generic_pending_surface(self):
        auth = self._load_auth()
        state = self._load_state()

        shapes = [
            # True new-user style: user present, no session.
            types.SimpleNamespace(user=object(), session=None),
            # Obfuscated / fake-success style often used for existing confirmed emails:
            # user-like object present without usable authenticated session tokens.
            types.SimpleNamespace(
                user=types.SimpleNamespace(id="fake-or-existing", email="existing@example.com"),
                session=None,
            ),
            types.SimpleNamespace(
                user=types.SimpleNamespace(
                    id="existing",
                    email="existing@example.com",
                    email_confirmed_at="2024-01-01T00:00:00Z",
                ),
                session=types.SimpleNamespace(access_token="", refresh_token="", user=None),
            ),
        ]

        rendered: list[str] = []
        for response in shapes:
            for mod in ("src.auth", "src.auth_state", "src.auth_recovery"):
                sys.modules.pop(mod, None)
            self.st = _install_streamlit_stub({})
            self.st.markdown = MagicMock()
            self.st.button = MagicMock(return_value=False)
            self.st.rerun = MagicMock()
            self.st.query_params = {}
            auth = self._load_auth()
            state = self._load_state()
            supabase = MagicMock()
            supabase.auth.sign_up.return_value = response
            with patch.object(auth, "begin_manual_login"), patch.object(
                auth, "render_auth_transition"
            ), patch.object(auth, "_log_manual_login_event"):
                auth._submit_manual_signup(supabase, MagicMock(), "shared@example.com", "pw")
            self.assertEqual(
                self.st.session_state["cadivor_root_state"],
                state.APP_SIGNUP_CONFIRMATION_PENDING,
            )
            self.assertEqual(
                self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY],
                "shared@example.com",
            )
            rendered.append(self._render_bodies(auth))

        # Same generic outcome language for every confirmation_pending shape.
        for body in rendered:
            self.assertIn("Signup request received", body)
            self.assertIn("If this address is eligible for account creation", body)
            self.assertNotIn("Confirmation email sent", body)
            self.assertNotIn("Account already exists", body)
            self.assertNotIn("This email is already registered", body)
        self.assertEqual(
            {b.replace("shared@example.com", "EMAIL") for b in rendered},
            {rendered[0].replace("shared@example.com", "EMAIL")},
        )

    def test_return_to_login_action_state(self):
        auth = self._load_auth()
        state = self._load_state()
        self.st.session_state["cadivor_root_state"] = state.APP_SIGNUP_CONFIRMATION_PENDING
        self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY] = "pending@example.com"
        self.st.session_state["cadivor_signup_password"] = "secret"
        self.st.session_state["cadivor_auth_password"] = "secret"
        self._click("cadivor_return_to_login_from_signup_pending")

        auth._render_signup_confirmation_pending()

        self.assertEqual(self.st.session_state["cadivor_root_state"], state.APP_LOGIN)
        self.assertNotEqual(self.st.session_state["cadivor_root_state"], state.APP_SIGNUP)
        self.assertNotIn(state.SIGNUP_PENDING_EMAIL_KEY, self.st.session_state)
        self.assertNotIn("cadivor_signup_password", self.st.session_state)
        self.assertNotIn("cadivor_auth_password", self.st.session_state)
        self.st.rerun.assert_called_once()

    def test_reset_password_routes_to_existing_reset_request_without_sending(self):
        auth = self._load_auth()
        state = self._load_state()
        self.st.session_state["cadivor_root_state"] = state.APP_SIGNUP_CONFIRMATION_PENDING
        self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY] = "pending@example.com"
        self.st.session_state["cadivor_signup_password"] = "secret"
        self._click("cadivor_reset_password_from_signup_pending")

        with patch.object(auth, "_auth_recovery") as recovery_factory:
            recovery = MagicMock()
            recovery_factory.return_value = recovery
            auth._render_signup_confirmation_pending()
            recovery.begin_password_reset_request.assert_called_once()
            recovery.request_password_reset_email.assert_not_called()

        self.assertNotIn(state.SIGNUP_PENDING_EMAIL_KEY, self.st.session_state)
        self.assertNotIn("cadivor_signup_password", self.st.session_state)
        # begin_password_reset_request sets APP_PASSWORD_RESET when not mocked away;
        # with MagicMock it won't set state — call the real transition path once more.
        for mod in ("src.auth", "src.auth_state", "src.auth_recovery"):
            sys.modules.pop(mod, None)
        self.st = _install_streamlit_stub({})
        self.st.markdown = MagicMock()
        self.st.button = MagicMock(return_value=False)
        self.st.rerun = MagicMock()
        self.st.query_params = {}
        auth = self._load_auth()
        state = self._load_state()
        self.st.session_state["cadivor_root_state"] = state.APP_SIGNUP_CONFIRMATION_PENDING
        self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY] = "pending@example.com"
        self._click("cadivor_reset_password_from_signup_pending")
        auth._render_signup_confirmation_pending()
        self.assertEqual(self.st.session_state["cadivor_root_state"], state.APP_PASSWORD_RESET)
        self.assertNotIn(state.SIGNUP_PENDING_EMAIL_KEY, self.st.session_state)
        self.st.rerun.assert_called_once()

    def test_use_different_email_returns_to_create_account_without_query_email(self):
        auth = self._load_auth()
        state = self._load_state()
        self.st.session_state["cadivor_root_state"] = state.APP_SIGNUP_CONFIRMATION_PENDING
        self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY] = "old@example.com"
        self.st.session_state["cadivor_signup_password"] = "secret"
        self.st.query_params["email"] = "old@example.com"
        self.st.query_params["auth"] = "signup"
        self._click("cadivor_use_different_email_from_signup_pending")

        auth._render_signup_confirmation_pending()

        self.assertEqual(self.st.session_state["cadivor_root_state"], state.APP_SIGNUP)
        self.assertNotIn(state.SIGNUP_PENDING_EMAIL_KEY, self.st.session_state)
        self.assertNotIn("cadivor_signup_password", self.st.session_state)
        self.assertNotIn("email", self.st.query_params)
        for key, value in list(self.st.query_params.items()):
            self.assertNotIn("old@example.com", str(key))
            self.assertNotIn("old@example.com", str(value))
        self.st.rerun.assert_called_once()

    def test_authenticated_signup_path_unchanged(self):
        auth = self._load_auth()
        state = self._load_state()
        user = types.SimpleNamespace(
            email_confirmed_at="2024-01-01T00:00:00Z",
            email="live@cadivor.com",
        )
        session = types.SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            user=user,
        )
        supabase = MagicMock()
        supabase.auth.sign_up.return_value = types.SimpleNamespace(user=user, session=session)
        with patch.object(auth, "begin_manual_login"), patch.object(
            auth, "render_auth_transition"
        ), patch.object(auth, "_log_manual_login_event"), patch.object(
            auth, "mark_authenticated"
        ) as mark_auth:
            auth._submit_manual_signup(supabase, MagicMock(), "live@cadivor.com", "secret")
        mark_auth.assert_called_once()
        self.assertNotEqual(
            self.st.session_state.get("cadivor_root_state"),
            state.APP_SIGNUP_CONFIRMATION_PENDING,
        )

    def test_no_admin_or_existence_lookup_helpers_introduced(self):
        auth = self._load_auth()
        from pathlib import Path

        source = Path(auth.__file__).read_text(encoding="utf-8")
        # Pending surface and exit helpers must not call admin/service-role lookups.
        pending_region = source[
            source.index("def _clear_signup_confirmation_pending") : source.index(
                "def _render_back_to_marketing_link"
            )
        ]
        forbidden = (
            "get_user_by_email",
            "list_users",
            "admin.",
            "service_role",
            "getUser(",
            "auth.admin",
        )
        for needle in forbidden:
            self.assertNotIn(needle, pending_region)


if __name__ == "__main__":
    unittest.main()
