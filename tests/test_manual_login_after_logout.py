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
        st, restore_streamlit = _install_streamlit_stub(
            session_state or {},
            context_cookies=context_cookies if context_cookies is not None else _FakeContextCookies(),
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

    def test_resolve_during_manual_login_preserves_signing_in(self):
        context = _FakeContextCookies({AUTH_LOGOUT_COOKIE_NAME: "1"})
        st, _auth_cookies, auth_state = self._load(
            {
                "cadivor_manual_login_in_progress": True,
                "cadivor_root_state": "signing_in",
            },
            context_cookies=context,
        )
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNING_IN)
        self.assertEqual(st.session_state["cadivor_auth_status"], auth_state.AUTH_SIGNING_IN)
        self.assertNotIn("user", st.session_state)
        self.assertFalse(st.session_state.get("cadivor_auth_resolved"))

    def test_resolve_without_manual_login_flag_returns_signed_out(self):
        st, _auth_cookies, auth_state = self._load({})
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertEqual(st.session_state["cadivor_auth_status"], auth_state.AUTH_SIGNED_OUT)

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

    def test_successful_login_removes_marketing_auth_query_parameters(self):
        manager = _FakeCookieManager()
        st, _auth_cookies, auth_state = self._load({})
        st.query_params = {"auth": "login", "source": "marketing", "page": "Reports"}

        auth_state.mark_authenticated(
            _FakeUser(),
            types.SimpleNamespace(access_token="new-a", refresh_token="new-r"),
            cookie_manager=manager,
        )

        self.assertNotIn("auth", st.query_params)
        self.assertNotIn("source", st.query_params)
        self.assertEqual(st.query_params["page"], "Reports")

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

    def test_stale_logout_marker_does_not_clear_authenticated_session(self):
        """Production regression: stale native context marker after manual login."""
        manager = _FakeCookieManager()
        context = _FakeContextCookies({AUTH_LOGOUT_COOKIE_NAME: "1"})
        st, auth_cookies, auth_state = self._load(
            {"cadivor_force_signed_out": True},
            context_cookies=context,
        )
        user = _FakeUser()
        session = types.SimpleNamespace(access_token="new-a", refresh_token="new-r")
        supabase = self._mock_supabase()

        auth_state.begin_manual_login(cookie_manager=manager)
        auth_state.mark_authenticated(user, session, cookie_manager=manager)
        self.assertFalse(st.session_state.get("cadivor_manual_login_in_progress"))

        status = auth_state.resolve_auth_state(supabase, cookie_manager=manager)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIs(st.session_state["user"], user)
        self.assertEqual(st.session_state["access_token"], "new-a")
        self.assertEqual(st.session_state["refresh_token"], "new-r")
        self.assertTrue(auth_cookies.logout_blocks_auth_restore(manager))

    def test_stale_logout_marker_without_user_remains_signed_out(self):
        context = _FakeContextCookies({AUTH_LOGOUT_COOKIE_NAME: "1"})
        st, _auth_cookies, auth_state = self._load({}, context_cookies=context)
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertNotIn("user", st.session_state)
        self.assertTrue(st.session_state.get("cadivor_force_signed_out"))

    def test_explicit_logout_clears_authenticated_session(self):
        st, auth_cookies, auth_state = self._load(
            {
                "user": _FakeUser(),
                "access_token": "live-a",
                "refresh_token": "live-r",
                "cadivor_auth_status": "authenticated",
            }
        )
        supabase = self._mock_supabase()
        manager = _FakeCookieManager()

        auth_state.begin_logout(supabase, cookie_manager=manager)

        self.assertNotIn("user", st.session_state)
        self.assertNotIn("access_token", st.session_state)
        self.assertNotIn("refresh_token", st.session_state)
        self.assertTrue(st.session_state.get("cadivor_force_signed_out"))

    def test_logout_manual_login_subsequent_rerun_stays_authenticated(self):
        manager = _FakeCookieManager()
        context = _FakeContextCookies({AUTH_LOGOUT_COOKIE_NAME: "1"})
        st, _auth_cookies, auth_state = self._load(
            {"cadivor_force_signed_out": True},
            context_cookies=context,
        )
        user = _FakeUser()
        session = types.SimpleNamespace(access_token="post-a", refresh_token="post-r")
        supabase = self._mock_supabase()

        auth_state.begin_manual_login(cookie_manager=manager)
        auth_state.mark_authenticated(user, session, cookie_manager=manager)

        for _ in range(2):
            status = auth_state.resolve_auth_state(supabase, cookie_manager=manager)
            self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)

        self.assertIs(st.session_state["user"], user)
        self.assertEqual(st.session_state["access_token"], "post-a")

    def test_logout_manual_login_f5_restores_authenticated_session(self):
        payload = _valid_payload("f5-a", "f5-r")
        context = _FakeContextCookies({"cadivor_auth": payload})
        st, _auth_cookies, auth_state = self._load({}, context_cookies=context)
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)
        self.assertEqual(st.session_state["access_token"], "fresh-access")

    def test_stale_logout_marker_ignored_emits_diagnostic(self):
        manager = _FakeCookieManager()
        context = _FakeContextCookies({AUTH_LOGOUT_COOKIE_NAME: "1"})
        st, _auth_cookies, auth_state = self._load(
            {
                "user": _FakeUser(),
                "access_token": "diag-a",
                "refresh_token": "diag-r",
                "cadivor_auth_status": "authenticated",
            },
            context_cookies=context,
        )
        supabase = self._mock_supabase()

        auth_diagnostics = types.ModuleType("src.auth_diagnostics")
        correlation_calls = []
        auth_diagnostics.log_auth_correlation = lambda checkpoint, **kwargs: correlation_calls.append(
            (checkpoint, kwargs.get("transition_reason"))
        )
        auth_diagnostics.log_auth_bounce = lambda event, **kwargs: None
        sys.modules["src.auth_diagnostics"] = auth_diagnostics

        status = auth_state.resolve_auth_state(supabase, cookie_manager=manager)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn(("stale_logout_marker_ignored", "authenticated_session"), correlation_calls)

    def test_auth_submit_uses_atomic_login_helpers(self):
        source = (
            __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "auth.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_submit_manual_login(", source)
        self.assertIn("_submit_manual_signup(", source)
        self.assertNotIn("cadivor_auth_submission", source)

    def test_manual_login_in_flight_helper(self):
        st, _auth_cookies, auth_state = self._load(
            {"cadivor_manual_login_in_progress": True}
        )
        self.assertTrue(auth_state.manual_login_in_flight())
        st.session_state.pop("cadivor_manual_login_in_progress")
        self.assertFalse(auth_state.manual_login_in_flight())

    def test_bootstrap_routes_signing_in_without_auth_boundary_failed(self):
        bootstrap_source = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "src"
            / "auth_bootstrap.py"
        ).read_text(encoding="utf-8")
        self.assertIn("manual_login_in_flight", bootstrap_source)
        self.assertIn('auth_ui_reason = "manual_login_in_flight"', bootstrap_source)
        self.assertIn("if auth_status == AUTH_SIGNING_IN:", bootstrap_source)

    def test_bootstrap_skips_hydration_rerun_during_manual_login(self):
        bootstrap_source = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "src"
            / "auth_bootstrap.py"
        ).read_text(encoding="utf-8")
        self.assertIn("not manual_login_in_flight()", bootstrap_source)
        self.assertIn("hydration_wait_rerun", bootstrap_source)

    def test_bootstrap_routes_signing_in_to_show_auth_ui_without_boundary_failed(self):
        st, restore_streamlit = _install_streamlit_stub(
            {
                "cadivor_manual_login_in_progress": True,
                "cadivor_root_state": "signing_in",
            }
        )
        self.addCleanup(restore_streamlit)

        def cache_resource(**kwargs):
            def decorator(fn):
                return fn
            return decorator

        st.cache_resource = cache_resource
        st.stop = MagicMock()
        st.caption = MagicMock()
        auth_cookies, auth_state, restore_secrets = _install_auth_modules(st)
        self.addCleanup(restore_secrets)

        from tests.secrets_module_isolation import install_src_secrets_stub
        _secrets, restore_secrets = install_src_secrets_stub(
            get_secret=lambda key, required=False, default=None: "test-secret",
            get_secret_bool=lambda key, default=False: default,
            ConfigurationError=RuntimeError,
        )
        self.addCleanup(restore_secrets)

        auth_diagnostics = types.ModuleType("src.auth_diagnostics")
        correlation_calls = []
        auth_diagnostics.log_auth_correlation = lambda checkpoint, **kwargs: correlation_calls.append(
            (checkpoint, kwargs.get("transition_reason"))
        )
        auth_diagnostics.log_auth_bounce = lambda event, **kwargs: None
        sys.modules["src.auth_diagnostics"] = auth_diagnostics

        auth = types.ModuleType("src.auth")
        auth.show_auth_ui = MagicMock()
        sys.modules["src.auth"] = auth

        supabase_mod = types.ModuleType("supabase")
        supabase_mod.create_client = MagicMock(return_value=MagicMock(name="supabase"))
        sys.modules["supabase"] = supabase_mod

        auth_cookies.native_context_cookies_available = lambda: False
        auth_cookies.auth_cookie_hydration_pending = lambda cookie_manager=None: True
        auth_cookies.get_auth_cookie_manager = lambda mount=True: _FakeCookieManager()
        auth_cookies.hydrate_session_from_auth_cookie = lambda cookie_manager=None: False
        auth_cookies.log_auth_restore = MagicMock()
        auth_cookies.read_auth_cookie_tokens = lambda cookie_manager=None: None
        auth_cookies.record_auth_hydration_attempt = lambda: 1
        sys.modules["src.auth_cookies"] = auth_cookies

        sys.modules.pop("src.auth_bootstrap", None)
        import importlib

        bootstrap = importlib.import_module("src.auth_bootstrap")

        with patch.object(st, "stop", side_effect=RuntimeError("stop")):
            try:
                bootstrap.ensure_authenticated_or_stop()
            except RuntimeError:
                pass

        auth.show_auth_ui.assert_called_once()
        boundary_failed = [
            call
            for call in auth_cookies.log_auth_restore.call_args_list
            if call.args and call.args[0] == "auth_boundary_failed"
        ]
        self.assertEqual(boundary_failed, [])
        self.assertIn(
            ("before_show_auth_ui", "manual_login_in_flight"),
            correlation_calls,
        )


if __name__ == "__main__":
    unittest.main()
