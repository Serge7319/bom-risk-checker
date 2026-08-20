"""Sprint 75.2B.11 — durable Login provider/session handoff tests."""
from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

from tests.test_manual_login_atomic import ManualLoginAtomicTests


class LoginHandoff752B11Tests(unittest.TestCase):
    def setUp(self):
        self.helper = ManualLoginAtomicTests(
            methodName="test_login_submit_calls_sign_in_in_same_script_run"
        )
        self.helper.setUp()

    def tearDown(self):
        self.helper.doCleanups()

    def _load_auth(self):
        return self.helper._load_auth()

    def test_provider_exception_uses_safe_copy_and_one_rerun(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = RuntimeError(
            "raw provider body with secret-token"
        )
        events = []

        with patch.object(auth, "_log_manual_login_event", side_effect=lambda event, *_: events.append(event)):
            auth._submit_manual_login(
                supabase, MagicMock(), "user@example.com", "password-value"
            )

        supabase.auth.sign_in_with_password.assert_called_once()
        st.rerun.assert_called_once_with()
        st.error.assert_not_called()
        self.assertEqual(st.session_state["cadivor_root_state"], auth.APP_LOGIN)
        self.assertEqual(
            st.session_state["cadivor_auth_error"],
            auth.MANUAL_LOGIN_FAILURE_MESSAGE,
        )
        self.assertNotIn("secret-token", str(st.session_state))
        self.assertEqual(
            events,
            ["manual_login_provider_started", "manual_login_provider_exception"],
        )

    def test_no_session_rebuilds_login_without_second_provider_call(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=types.SimpleNamespace(id="u"),
            session=None,
        )

        auth._submit_manual_login(
            supabase, MagicMock(), "user@example.com", "password-value"
        )

        supabase.auth.sign_in_with_password.assert_called_once()
        st.rerun.assert_called_once_with()
        self.assertEqual(
            st.session_state["cadivor_auth_error"],
            auth.MANUAL_LOGIN_NO_SESSION_MESSAGE,
        )
        self.assertFalse(
            st.session_state.get("cadivor_manual_login_in_progress", False)
        )

    def test_blank_tokens_are_an_unusable_session(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=types.SimpleNamespace(id="u"),
            session=types.SimpleNamespace(access_token="", refresh_token=""),
        )

        with patch.object(auth, "mark_authenticated") as mark_mock:
            auth._submit_manual_login(
                supabase, MagicMock(), "user@example.com", "password-value"
            )

        mark_mock.assert_not_called()
        st.rerun.assert_called_once_with()
        self.assertEqual(st.session_state["cadivor_root_state"], auth.APP_LOGIN)

    def test_success_logs_ready_then_commit_before_single_rerun(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        session = types.SimpleNamespace(access_token="access", refresh_token="refresh")
        user = types.SimpleNamespace(id="u")
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=user,
            session=session,
        )
        order = []

        with (
            patch.object(
                auth,
                "_log_manual_login_event",
                side_effect=lambda event, *_: order.append(event),
            ),
            patch.object(
                auth,
                "mark_authenticated",
                side_effect=lambda *_: order.append("mark_authenticated"),
            ),
        ):
            auth.st.rerun = lambda: order.append("rerun")
            auth._submit_manual_login(
                supabase, MagicMock(), "user@example.com", "password-value"
            )

        self.assertEqual(
            order,
            [
                "manual_login_provider_started",
                "manual_login_provider_completed",
                "manual_login_provider_session_ready",
                "mark_authenticated",
                "manual_login_session_committed",
                "rerun",
            ],
        )
        supabase.auth.sign_in_with_password.assert_called_once()

    def test_login_failure_never_renders_raw_exception_in_same_run(self):
        _st, auth, _auth_state = self._load_auth()
        source = open(auth.__file__, encoding="utf-8").read()
        self.assertNotIn('f"Authentication failed: {error}"', source)
        self.assertIn("_fail_manual_login_and_rerun(", source)
        self.assertIn("manual_login_provider_no_session", source)


if __name__ == "__main__":
    unittest.main()
