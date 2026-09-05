"""Sprint 71.9.3B — atomic auth restoration and deferred CookieManager tests."""
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


class _FakeUser:
    id = "user-123"
    email = "user@example.com"


class AuthAtomicRestoreTests(unittest.TestCase):
    def setUp(self):
        _FakeCookieManager.instances.clear()
        for name in list(sys.modules):
            if name.startswith("src.auth") or name == "extra_streamlit_components":
                sys.modules.pop(name, None)

    def _load(self, session_state=None, *, context_cookies=_FakeContextCookies()):
        st, restore_streamlit = _install_streamlit_stub(
            session_state or {}, context_cookies=context_cookies
        )
        self.addCleanup(restore_streamlit)
        auth_cookies, auth_state, restore_secrets = _install_auth_modules(st)
        self.addCleanup(restore_secrets)
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

    def test_native_context_restore_does_not_mount_cookie_manager_before_resolve(self):
        payload = _valid_payload("ctx-a", "ctx-r")
        context = _FakeContextCookies({"cadivor_auth": payload})
        st, auth_cookies, auth_state = self._load({}, context_cookies=context)
        supabase = self._mock_supabase()

        self.assertTrue(auth_cookies.native_context_cookies_available())
        self.assertIsNone(auth_cookies.get_auth_cookie_manager(mount=False))
        self.assertEqual(len(_FakeCookieManager.instances), 0)

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)
        self.assertEqual(st.session_state["access_token"], "fresh-access")
        self.assertEqual(st.session_state["refresh_token"], "fresh-refresh")
        # CookieManager must not mount during auth resolution; bootstrap persists after.
        self.assertEqual(len(_FakeCookieManager.instances), 0)

    def test_read_auth_cookie_tokens_does_not_write_session_state(self):
        payload = _valid_payload("read-a", "read-r")
        context = _FakeContextCookies({"cadivor_auth": payload})
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)

        tokens = auth_cookies.read_auth_cookie_tokens(cookie_manager=None)

        self.assertEqual(tokens, {"access_token": "read-a", "refresh_token": "read-r"})
        self.assertNotIn("access_token", st.session_state)
        self.assertNotIn("refresh_token", st.session_state)
        self.assertNotIn("user", st.session_state)

    def test_successful_restore_commits_user_and_tokens_together(self):
        payload = _valid_payload("cookie-a", "cookie-r")
        context = _FakeContextCookies({"cadivor_auth": payload})
        st, _auth_cookies, auth_state = self._load({}, context_cookies=context)
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)
        self.assertIn("access_token", st.session_state)
        self.assertIn("refresh_token", st.session_state)

    def test_failed_validation_commits_none(self):
        payload = _valid_payload("bad-a", "bad-r")
        context = _FakeContextCookies({"cadivor_auth": payload})
        st, auth_cookies, auth_state = self._load({}, context_cookies=context)
        supabase = self._mock_supabase(user=None)

        with patch.object(auth_cookies, "invalidate_corrupt_auth_cookie") as invalidate_mock:
            status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertNotIn("user", st.session_state)
        self.assertNotIn("access_token", st.session_state)
        self.assertNotIn("refresh_token", st.session_state)
        invalidate_mock.assert_called_once()

    def test_orphan_session_tokens_validate_instead_of_signing_out(self):
        st, _auth_cookies, auth_state = self._load(
            {
                "access_token": "orphan-a",
                "refresh_token": "orphan-r",
            },
            context_cookies=_FakeContextCookies(),
        )
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)
        self.assertEqual(st.session_state["access_token"], "fresh-access")

    def test_mark_authenticated_lazy_mounts_cookie_manager_for_write(self):
        st, auth_cookies, auth_state = self._load({}, context_cookies=_FakeContextCookies())
        user = _FakeUser()
        session = types.SimpleNamespace(access_token="login-a", refresh_token="login-r")

        auth_state.mark_authenticated(user, session, cookie_manager=None)

        self.assertEqual(len(_FakeCookieManager.instances), 1)
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        self.assertIsNotNone(manager)
        self.assertIn("cadivor_auth", manager.cookies)

    def test_logout_lazy_mounts_cookie_manager_for_delete(self):
        st, auth_cookies, auth_state = self._load(
            {"user": _FakeUser(), "access_token": "a", "refresh_token": "r"},
            context_cookies=_FakeContextCookies(),
        )
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies["cadivor_auth"] = _valid_payload()

        auth_state.begin_logout(MagicMock(), cookie_manager=None)

        self.assertTrue(st.session_state.get("cadivor_force_signed_out"))
        mounted = auth_cookies.get_auth_cookie_manager(mount=True)
        self.assertIsNotNone(mounted)

    def test_f5_restore_via_context_cookie(self):
        payload = _valid_payload("f5-a", "f5-r")
        context = _FakeContextCookies({"cadivor_auth": payload})
        st, _auth_cookies, auth_state = self._load({}, context_cookies=context)
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIsNotNone(st.session_state.get("user"))

    def test_invalid_expired_token_remains_fail_closed(self):
        st, auth_cookies, auth_state = self._load(
            {"access_token": "expired-a", "refresh_token": "expired-r"},
            context_cookies=_FakeContextCookies(),
        )
        supabase = self._mock_supabase(user=None)

        with patch.object(auth_cookies, "invalidate_corrupt_auth_cookie"):
            status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertNotIn("user", st.session_state)

    def test_context_absent_manager_valid_restores_authenticated(self):
        st, auth_cookies, auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies["cadivor_auth"] = _valid_payload("mgr-restore-a", "mgr-restore-r")
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)
        self.assertEqual(st.session_state["access_token"], "fresh-access")
        self.assertNotIn("mgr-restore-a", st.session_state["access_token"])

    def test_context_absent_manager_absent_remains_signed_out(self):
        st, auth_cookies, auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies = {}
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertNotIn("user", st.session_state)

    def test_context_malformed_manager_valid_restores_via_fallback(self):
        context = _FakeContextCookies({"cadivor_auth": "not-json"})
        st, auth_cookies, auth_state = self._load({}, context_cookies=context)
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies["cadivor_auth"] = _valid_payload("fallback-a", "fallback-r")
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)

    def test_manager_invalid_credentials_fail_closed(self):
        st, auth_cookies, auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies["cadivor_auth"] = _valid_payload("bad-a", "bad-r")
        supabase = self._mock_supabase(user=None)

        with patch.object(auth_cookies, "invalidate_corrupt_auth_cookie") as invalidate_mock:
            status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertNotIn("user", st.session_state)
        invalidate_mock.assert_called_once()

    def test_f5_restore_via_context_simulates_new_connection(self):
        payload = _valid_payload("cold-f5-a", "cold-f5-r")
        context = _FakeContextCookies({"cadivor_auth": payload})
        st, auth_cookies, auth_state = self._load({}, context_cookies=context)
        supabase = self._mock_supabase()

        self.assertEqual(len(_FakeCookieManager.instances), 0)
        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertEqual(len(_FakeCookieManager.instances), 0)


if __name__ == "__main__":
    unittest.main()
