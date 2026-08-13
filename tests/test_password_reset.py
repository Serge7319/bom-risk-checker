"""Sprint 74 — password recovery tests."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub


class PasswordResetTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.rerun = MagicMock()
        self.st.error = MagicMock()
        self.st.success = MagicMock()

    def _load_auth_recovery(self):
        sys.modules.pop("src.auth_recovery", None)
        return importlib.import_module("src.auth_recovery")

    def test_request_password_reset_returns_generic_message(self):
        recovery = self._load_auth_recovery()
        supabase = MagicMock()
        message = recovery.request_password_reset_email(supabase, "user@example.com")
        self.assertIn("If an account exists", message)
        supabase.auth.reset_password_for_email.assert_called_once()

    def test_request_password_reset_does_not_reveal_missing_email(self):
        recovery = self._load_auth_recovery()
        supabase = MagicMock()
        message = recovery.request_password_reset_email(supabase, "")
        self.assertIn("Enter the email address", message)
        supabase.auth.reset_password_for_email.assert_not_called()

    def test_password_mismatch_is_rejected(self):
        recovery = self._load_auth_recovery()
        self.st.session_state["cadivor_password_recovery_active"] = True
        supabase = MagicMock()
        success, message = recovery.complete_password_recovery(
            supabase,
            "password123",
            "different123",
        )
        self.assertFalse(success)
        self.assertIn("do not match", message.lower())
        supabase.auth.update_user.assert_not_called()

    def test_successful_password_update_clears_recovery_state(self):
        recovery = self._load_auth_recovery()
        self.st.session_state["cadivor_password_recovery_active"] = True
        self.st.session_state["user"] = types.SimpleNamespace(id="user-1")
        self.st.session_state["access_token"] = "access"
        self.st.session_state["refresh_token"] = "refresh"
        supabase = MagicMock()
        success, message = recovery.complete_password_recovery(
            supabase,
            "newpassword123",
            "newpassword123",
        )
        self.assertTrue(success)
        self.assertIn("updated", message.lower())
        self.assertNotIn("cadivor_password_recovery_active", self.st.session_state)
        self.assertNotIn("access_token", self.st.session_state)
        supabase.auth.update_user.assert_called_once_with({"password": "newpassword123"})

    def test_invalid_recovery_session_is_rejected(self):
        recovery = self._load_auth_recovery()
        supabase = MagicMock()
        success, message = recovery.complete_password_recovery(
            supabase,
            "newpassword123",
            "newpassword123",
        )
        self.assertFalse(success)
        self.assertIn("not active", message.lower())

    def test_recovery_query_activation_sets_recovery_mode(self):
        recovery = self._load_auth_recovery()
        self.st.query_params = {
            "type": "recovery",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
        }
        supabase = MagicMock()
        session = types.SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            user=types.SimpleNamespace(id="user-1", email="user@example.com"),
        )
        supabase.auth.set_session.return_value = types.SimpleNamespace(
            session=session,
            user=session.user,
        )
        recovery.apply_password_recovery_from_query(supabase)
        self.assertTrue(recovery.password_recovery_active())
        self.assertEqual(self.st.session_state["cadivor_root_state"], "password_recovery")


if __name__ == "__main__":
    unittest.main()
