"""Sprint 74.2B.1 — durable signup confirmation handoff lifecycle tests."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub


def _unconfirmed_user(**overrides):
    payload = {
        "id": "user-1",
        "email": "new@cadivor.com",
        "aud": "authenticated",
        "app_metadata": {},
        "user_metadata": {},
        "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "email_confirmed_at": None,
        "identities": [],
    }
    payload.update(overrides)
    return types.SimpleNamespace(**payload)


def _confirmed_user(**overrides):
    return _unconfirmed_user(
        email_confirmed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        identities=[{"identity_id": "id-1"}],
        **overrides,
    )


def _usable_session(user):
    return types.SimpleNamespace(
        access_token="access-token-value",
        refresh_token="refresh-token-value",
        expires_in=3600,
        token_type="bearer",
        user=user,
    )


class SignupResponseShapeTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.error = MagicMock()
        self.st.rerun = MagicMock()
        sys.modules.pop("src.auth", None)
        self.auth = importlib.import_module("src.auth")

    def test_bare_unconfirmed_user_session_none_is_pending(self):
        user = _unconfirmed_user()
        kind, out_user, session = self.auth.classify_signup_auth_response(
            types.SimpleNamespace(user=user, session=None)
        )
        self.assertEqual(kind, "confirmation_pending")
        self.assertIs(out_user, user)
        self.assertIsNone(session)

    def test_identities_empty_without_session_is_pending(self):
        user = _unconfirmed_user(identities=[])
        kind, _, _ = self.auth.classify_signup_auth_response(
            types.SimpleNamespace(user=user, session=None)
        )
        self.assertEqual(kind, "confirmation_pending")

    def test_session_with_empty_tokens_is_pending(self):
        user = _unconfirmed_user()
        session = types.SimpleNamespace(access_token="", refresh_token="", user=user)
        kind, _, _ = self.auth.classify_signup_auth_response(
            types.SimpleNamespace(user=user, session=session)
        )
        self.assertEqual(kind, "confirmation_pending")

    def test_session_with_missing_tokens_is_pending(self):
        user = _unconfirmed_user()
        session = types.SimpleNamespace(user=user)
        kind, _, _ = self.auth.classify_signup_auth_response(
            types.SimpleNamespace(user=user, session=session)
        )
        self.assertEqual(kind, "confirmation_pending")

    def test_unconfirmed_user_with_session_like_object_is_pending(self):
        user = _unconfirmed_user()
        session = _usable_session(user)
        kind, _, _ = self.auth.classify_signup_auth_response(
            types.SimpleNamespace(user=user, session=session)
        )
        self.assertEqual(kind, "confirmation_pending")

    def test_confirmed_user_with_valid_session_is_authenticated(self):
        user = _confirmed_user()
        session = _usable_session(user)
        kind, out_user, out_session = self.auth.classify_signup_auth_response(
            types.SimpleNamespace(user=user, session=session)
        )
        self.assertEqual(kind, "authenticated")
        self.assertIs(out_user, user)
        self.assertIs(out_session, session)

    def test_realistic_full_auth_response_fixture_is_authenticated(self):
        user = _confirmed_user(email="live@cadivor.com")
        session = _usable_session(user)
        response = types.SimpleNamespace(user=user, session=session)
        kind, _, _ = self.auth.classify_signup_auth_response(response)
        self.assertEqual(kind, "authenticated")

    def test_dictionary_like_unconfirmed_fixture_is_pending(self):
        user = {"id": "u1", "email": "a@b.com", "email_confirmed_at": None}
        response = {"user": user, "session": None}
        kind, out_user, session = self.auth.classify_signup_auth_response(response)
        self.assertEqual(kind, "confirmation_pending")
        self.assertEqual(out_user["email"], "a@b.com")
        self.assertIsNone(session)

    def test_unexpected_response_without_user_or_session_is_unusable(self):
        kind, user, session = self.auth.classify_signup_auth_response(types.SimpleNamespace())
        self.assertEqual(kind, "unusable")
        self.assertIsNone(user)
        self.assertIsNone(session)

    def test_userless_success_response_enters_safe_pending_handoff(self):
        state = importlib.import_module("src.auth_state")
        supabase = MagicMock()
        supabase.auth.sign_up.return_value = types.SimpleNamespace(user=None, session=None)
        with patch.object(self.auth, "begin_manual_login"), patch.object(
            self.auth, "render_auth_transition"
        ), patch.object(self.auth, "_log_manual_login_event"), patch.object(
            self.auth, "finish_manual_login_failed"
        ) as finish_failed:
            self.auth._submit_manual_signup(supabase, MagicMock(), "x@cadivor.com", "secret")
        finish_failed.assert_not_called()
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            state.APP_SIGNUP_CONFIRMATION_PENDING,
        )
        self.assertEqual(
            self.st.session_state[state.SIGNUP_PENDING_EMAIL_KEY],
            "x@cadivor.com",
        )
        self.assertTrue(self.rerun_requested)
        self.st.error.assert_not_called()


class SignupConfirmationLifecycleTests(unittest.TestCase):
    """Multi-run bootstrap fidelity: submit → rerun → intent → show_auth_ui."""

    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.markdown = MagicMock()
        self.st.button = MagicMock(return_value=False)
        self.st.success = MagicMock()
        self.st.error = MagicMock()
        self.st.warning = MagicMock()
        self.st.cache_resource = lambda **_kwargs: (lambda fn: fn)
        self.st.query_params = {}
        self.rerun_requested = False

        def _rerun():
            self.rerun_requested = True

        self.st.rerun = _rerun
        for mod in ("src.auth", "src.auth_state", "src.auth_bootstrap", "src.auth_recovery"):
            sys.modules.pop(mod, None)
        self.auth = importlib.import_module("src.auth")
        self.state = importlib.import_module("src.auth_state")
        self.bootstrap = importlib.import_module("src.auth_bootstrap")

    def _run_signup_submit(self, response):
        supabase = MagicMock()
        supabase.auth.sign_up.return_value = response
        with patch.object(self.auth, "begin_manual_login"), patch.object(
            self.auth, "render_auth_transition"
        ), patch.object(self.auth, "_log_manual_login_event"):
            self.auth._submit_manual_signup(supabase, MagicMock(), "new@cadivor.com", "secret-password")
        self.assertTrue(self.rerun_requested)
        self.assertNotIn("password", self.st.session_state)
        self.assertNotIn("cadivor_signup_password", self.st.session_state)

    def _run2_bootstrap_and_show(self, *, auth_query: str | None):
        self.st.query_params = {}
        if auth_query:
            self.st.query_params["auth"] = auth_query
        # Simulate post-rerun: pending already written by run 1.
        self.bootstrap.apply_auth_intent_from_query()
        with patch.object(self.auth, "_auth_css"), patch.object(
            self.auth, "inject_core_premium_ui_auth"
        ), patch.object(self.auth, "_render_signup_confirmation_pending") as pending, patch.object(
            self.auth, "_render_auth_page"
        ) as login_form, patch.object(self.auth, "_render_password_recovery_form") as recovery_form, patch.object(
            self.auth, "_auth_recovery"
        ) as recovery_factory:
            recovery_factory.return_value.password_recovery_active.return_value = False
            recovery_factory.return_value._RECOVERY_NOTICE_KEY = "cadivor_recovery_notice"
            self.auth.show_auth_ui(MagicMock(), None)
        return pending, login_form, recovery_form

    def test_auth_signup_query_cannot_overwrite_pending(self):
        user = _unconfirmed_user()
        self._run_signup_submit(types.SimpleNamespace(user=user, session=None))
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP_CONFIRMATION_PENDING)
        # Pretend intent was never applied so production overwrite path is armed.
        self.st.session_state.pop("cadivor_auth_intent_applied", None)
        pending, login_form, recovery_form = self._run2_bootstrap_and_show(auth_query="signup")
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP_CONFIRMATION_PENDING)
        pending.assert_called_once()
        login_form.assert_not_called()
        recovery_form.assert_not_called()

    def test_auth_login_query_cannot_overwrite_pending(self):
        user = _unconfirmed_user()
        self._run_signup_submit(types.SimpleNamespace(user=user, session=None))
        self.st.session_state.pop("cadivor_auth_intent_applied", None)
        pending, login_form, _recovery = self._run2_bootstrap_and_show(auth_query="login")
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP_CONFIRMATION_PENDING)
        pending.assert_called_once()
        login_form.assert_not_called()

    def test_no_query_preserves_pending(self):
        user = _unconfirmed_user()
        self._run_signup_submit(types.SimpleNamespace(user=user, session=None))
        pending, login_form, _recovery = self._run2_bootstrap_and_show(auth_query=None)
        pending.assert_called_once()
        login_form.assert_not_called()

    def test_pending_renders_check_your_email_copy(self):
        self.st.session_state[self.state.SIGNUP_PENDING_EMAIL_KEY] = "new@cadivor.com"
        bodies: list[str] = []

        def capture(body, **kwargs):
            bodies.append(str(body))

        self.st.markdown.side_effect = capture
        self.auth._render_signup_confirmation_pending()
        joined = "\n".join(bodies)
        self.assertIn("Check your email", joined)
        self.assertIn("new@cadivor.com", joined)
        self.assertIn("Signup request received", joined)
        self.assertIn("Next step", joined)
        self.assertIn("If this address is eligible for account creation", joined)
        self.assertNotIn("Confirmation email sent", joined)
        self.assertNotIn("Email confirmation required", joined)

    def test_signing_in_normalization_does_not_bypass_pending(self):
        self.st.session_state["cadivor_root_state"] = self.state.APP_SIGNUP_CONFIRMATION_PENDING
        self.st.session_state[self.state.SIGNUP_PENDING_EMAIL_KEY] = "new@cadivor.com"
        # Even if a stale signing_in flag exists, root pending must win.
        self.st.session_state["cadivor_auth_status"] = self.state.AUTH_SIGNING_IN
        pending, login_form, _recovery = self._run2_bootstrap_and_show(auth_query="signup")
        pending.assert_called_once()
        login_form.assert_not_called()
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP_CONFIRMATION_PENDING)

    def test_return_to_login_clears_pending_intentionally(self):
        self.st.session_state["cadivor_root_state"] = self.state.APP_SIGNUP_CONFIRMATION_PENDING
        self.st.session_state[self.state.SIGNUP_PENDING_EMAIL_KEY] = "new@cadivor.com"
        self.st.session_state["cadivor_signup_password"] = "should-clear"
        self.rerun_requested = False

        def _button(label, key=None, **kwargs):
            return key == "cadivor_return_to_login_from_signup_pending"

        self.st.button.side_effect = _button
        self.auth._render_signup_confirmation_pending()
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_LOGIN)
        self.assertNotIn(self.state.SIGNUP_PENDING_EMAIL_KEY, self.st.session_state)
        self.assertNotIn("cadivor_signup_password", self.st.session_state)
        self.assertTrue(self.rerun_requested)

    def test_empty_token_session_enters_pending_not_authenticated(self):
        user = _unconfirmed_user()
        session = types.SimpleNamespace(access_token="", refresh_token="", user=user)
        self._run_signup_submit(types.SimpleNamespace(user=user, session=session))
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP_CONFIRMATION_PENDING)

    def test_recovery_state_remains_unchanged(self):
        self.st.session_state["cadivor_root_state"] = self.state.APP_PASSWORD_RECOVERY
        self.st.session_state[self.state.SIGNUP_PENDING_EMAIL_KEY] = "should-not-win@cadivor.com"
        with patch.object(self.auth, "_auth_css"), patch.object(
            self.auth, "inject_core_premium_ui_auth"
        ), patch.object(self.auth, "_render_signup_confirmation_pending") as pending, patch.object(
            self.auth, "_render_auth_page"
        ) as login_form, patch.object(self.auth, "_render_password_recovery_form") as recovery_form, patch.object(
            self.auth, "_auth_recovery"
        ) as recovery_factory:
            recovery_factory.return_value.password_recovery_active.return_value = True
            self.auth.show_auth_ui(MagicMock(), None)
        recovery_form.assert_called_once()
        pending.assert_not_called()
        login_form.assert_not_called()


if __name__ == "__main__":
    unittest.main()
