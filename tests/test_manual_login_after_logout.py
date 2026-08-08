"""Sprint 71.9.6 — manual login after explicit logout lifecycle tests."""
from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import (
    _FakeContextCookies,
    _FakeCookieManager,
    _install_auth_modules,
    _install_streamlit_stub,
    _valid_payload,
)

AUTH_LOGOUT_COOKIE_NAME = "cadivor_auth_logout"


class _FakeUser:
    id = "user-123"
    email = "user@example.com"


class ManualLoginAfterLogoutTests(unittest.TestCase):
    def setUp(self):
        _FakeCookieManager.instances.clear()
        for name in list(sys.modules):
            if name.startswith("src.auth"):
                sys.modules.pop(name, None)

    def _load(self, session_state=None, *, context_cookies=None):
        st = _install_streamlit_stub(
            session_state or {},
            context_cookies=context_cookies if context_cookies is not None else _FakeContextCookies(),
        )
        auth_cookies, auth_state = _install_auth_modules(st)
        return st, auth_cookies, auth_state

    def _mock_supabase(self, *, user=_FakeUser()):
        supabase = MagicMock()
        fresh_session = types.SimpleNamespace(
            access_token="fresh-access",
            refresh_token="fresh-refresh",
        )
        supabase.auth.set_session.return_value = types.SimpleNamespace(session=fresh_session)
        supabase.auth.get_user.return_value = types.SimpleNamespace(user=user)
        return supabase

    def test_explicit_logout_f5_remains_signed_out(self):
        context = _FakeContextCookies({AUTH_LOGOUT_COOKIE_NAME: "1"})
        st, auth_cookies, auth_state = self._load(
            {"cadivor_force_signed_out": True},
            context_cookies=context,
        )
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertNotIn("user", st.session_state)
        self.assertTrue(auth_cookies.logout_blocks_auth_restore(None))

    def test_explicit_logout_without_credentials_remains_signed_out(self):
        st, _auth_cookies, auth_state = self._load({"cadivor_force_signed_out": True})
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertNotIn("user", st.session_state)

    def test_begin_manual_login_clears_logout_suppression_before_sign_in(self):
        manager = _FakeCookieManager()
        manager.cookies[AUTH_LOGOUT_COOKIE_NAME] = "1"
        st, auth_cookies, auth_state = self._load(
            {
                "cadivor_force_signed_out": True,
                "cadivor_explicit_logout": True,
                "cadivor_logout_committed": True,
            }
        )

        auth_state.begin_manual_login(cookie_manager=manager)

        self.assertFalse(st.session_state.get("cadivor_force_signed_out"))
        self.assertFalse(st.session_state.get("cadivor_explicit_logout"))
        self.assertTrue(st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertFalse(auth_cookies.logout_blocks_auth_restore(manager))

    def test_manual_login_submit_state_is_signing_in_without_force_signed_out(self):
        manager = _FakeCookieManager()
        st, _auth_cookies, auth_state = self._load({"cadivor_force_signed_out": True})

        auth_state.begin_manual_login(cookie_manager=manager)
        st.session_state["cadivor_auth_status"] = auth_state.AUTH_SIGNING_IN

        self.assertEqual(st.session_state["cadivor_auth_status"], auth_state.AUTH_SIGNING_IN)
        self.assertFalse(st.session_state.get("cadivor_force_signed_out"))
        self.assertTrue(st.session_state.get("cadivor_manual_login_in_progress"))

    def test_resolve_during_manual_login_does_not_apply_logout_marker(self):
        context = _FakeContextCookies({AUTH_LOGOUT_COOKIE_NAME: "1"})
        st, _auth_cookies, auth_state = self._load(
            {"cadivor_manual_login_in_progress": True},
            context_cookies=context,
        )
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertNotIn("user", st.session_state)
        self.assertTrue(st.session_state.get("cadivor_manual_login_in_progress"))

    def test_valid_manual_login_commits_authenticated_session(self):
        manager = _FakeCookieManager()
        st, auth_cookies, auth_state = self._load({"cadivor_force_signed_out": True})
        user = _FakeUser()
        session = types.SimpleNamespace(access_token="new-a", refresh_token="new-r")

        auth_state.begin_manual_login(cookie_manager=manager)
        auth_state.mark_authenticated(user, session, cookie_manager=manager)

        self.assertEqual(st.session_state["cadivor_auth_status"], auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)
        self.assertFalse(st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertFalse(st.session_state.get("cadivor_force_signed_out"))
        self.assertIn("cadivor_auth", manager.cookies)

    def test_failed_manual_login_rearms_signed_out_protection(self):
        manager = _FakeCookieManager()
        st, auth_cookies, auth_state = self._load({"cadivor_manual_login_in_progress": True})

        auth_state.finish_manual_login_failed(cookie_manager=manager)

        self.assertFalse(st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertTrue(st.session_state.get("cadivor_force_signed_out"))
        self.assertEqual(st.session_state["cadivor_auth_status"], auth_state.AUTH_SIGNED_OUT)
        self.assertTrue(auth_cookies.logout_blocks_auth_restore(manager))

    def test_failed_manual_login_does_not_restore_old_auth_cookie(self):
        payload = _valid_payload("old-a", "old-r")
        context = _FakeContextCookies({"cadivor_auth": payload})
        st, auth_cookies, auth_state = self._load(
            {"cadivor_manual_login_in_progress": True},
            context_cookies=context,
        )

        tokens = auth_cookies.read_auth_cookie_tokens(cookie_manager=None)

        self.assertIsNone(tokens)

    def test_f5_after_successful_manual_login_restores_authenticated_session(self):
        payload = _valid_payload("restored-a", "restored-r")
        context = _FakeContextCookies({"cadivor_auth": payload})
        st, _auth_cookies, auth_state = self._load(
            {
                "user": _FakeUser(),
                "access_token": "restored-a",
                "refresh_token": "restored-r",
            },
            context_cookies=context,
        )
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)

    def test_auth_submit_calls_begin_manual_login(self):
        source = open(
            __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "auth.py",
            encoding="utf-8",
        ).read()
        self.assertIn("begin_manual_login(cookie_manager)", source)
        self.assertLess(
            source.index("begin_manual_login(cookie_manager)"),
            source.index('st.session_state["cadivor_auth_status"] = "signing_in"'),
        )


if __name__ == "__main__":
    unittest.main()
