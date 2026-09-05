"""Idle-session recovery for authenticated workspace profile loading."""
from __future__ import annotations

import base64
import json
import sys
import time
import types
import unittest
from unittest.mock import MagicMock, patch


def _jwt(exp_offset_seconds: int, *, sub: str = "user-1") -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": "user@example.com",
        "role": "authenticated",
        "iat": now - 10,
        "exp": now + int(exp_offset_seconds),
    }
    segment = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"hdr.{segment}.sig"


_STUBBED_MODULES: dict[str, object | None] = {}


def _install_streamlit(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = {}
    st.rerun = MagicMock(side_effect=RuntimeError("rerun"))
    st.warning = MagicMock()
    st.error = MagicMock()
    st.caption = MagicMock()
    st.button = MagicMock(return_value=False)
    st.success = MagicMock()
    st.stop = MagicMock(side_effect=SystemExit("stop"))
    st.markdown = MagicMock()
    st.cache_resource = lambda **kwargs: (lambda fn: fn)
    st.cache_data = lambda **kwargs: (lambda fn: fn)
    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()
    components.declare_component = MagicMock(
        return_value=MagicMock(return_value=None)
    )
    for name in (
        "streamlit",
        "streamlit.components",
        "streamlit.components.v1",
    ):
        if name not in _STUBBED_MODULES:
            _STUBBED_MODULES[name] = sys.modules.get(name)
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st


def _purge_auth_modules():
    for name in list(sys.modules):
        if name.startswith("src.auth") or name in {
            "src.authenticated_runtime",
            "src.auth_idle_recovery",
            "src.auth_cookies",
            "src.auth_state",
            "src.auth_diagnostics",
            "src.browser_navigation",
        }:
            sys.modules.pop(name, None)
    for name, previous in list(_STUBBED_MODULES.items()):
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    _STUBBED_MODULES.clear()


class IdleRecoveryHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _purge_auth_modules()
        _install_streamlit()

    @classmethod
    def tearDownClass(cls):
        _purge_auth_modules()

    def test_access_token_freshness(self):
        from src.auth_idle_recovery import access_token_is_fresh

        self.assertTrue(access_token_is_fresh(_jwt(3600), skew_seconds=90))
        self.assertFalse(access_token_is_fresh(_jwt(-10), skew_seconds=90))
        self.assertFalse(access_token_is_fresh(_jwt(30), skew_seconds=90))

    def test_auth_rejection_markers(self):
        from src.auth_idle_recovery import is_auth_rejection_error

        self.assertTrue(is_auth_rejection_error(RuntimeError("JWT expired")))
        self.assertTrue(is_auth_rejection_error("401 Unauthorized"))
        self.assertFalse(is_auth_rejection_error(RuntimeError("connection reset")))


class IdleRecoverySessionTests(unittest.TestCase):
    def setUp(self):
        _purge_auth_modules()
        self.st = _install_streamlit(
            {
                "user": types.SimpleNamespace(id="user-1", email="user@example.com"),
                "access_token": _jwt(-30),
                "refresh_token": "refresh-1",
                "cadivor_auth_status": "authenticated",
                "app_mode": "Pricing",
                "cadivor_route": "Pricing",
            }
        )
        self.st.query_params = {"page": "Pricing"}

    def tearDown(self):
        _purge_auth_modules()

    def test_refresh_success_commits_new_tokens(self):
        from src import auth_idle_recovery as recovery

        user = types.SimpleNamespace(id="user-1", email="user@example.com")
        session = types.SimpleNamespace(
            access_token=_jwt(3600),
            refresh_token="refresh-2",
            user=user,
        )
        supabase = MagicMock()
        supabase.auth.refresh_session.return_value = types.SimpleNamespace(
            session=session,
            user=user,
        )

        outcome, got_user, access, refresh = recovery.refresh_authenticated_session(
            supabase,
            access_token=self.st.session_state["access_token"],
            refresh_token="refresh-1",
            force=False,
        )
        self.assertEqual(outcome, "refreshed")
        self.assertEqual(got_user, user)
        self.assertEqual(refresh, "refresh-2")
        self.assertTrue(recovery.access_token_is_fresh(access))

    def test_refresh_failure_is_invalid(self):
        from src import auth_idle_recovery as recovery

        supabase = MagicMock()
        supabase.auth.refresh_session.side_effect = Exception("Invalid Refresh Token")
        outcome, user, access, refresh = recovery.refresh_authenticated_session(
            supabase,
            access_token=_jwt(-30),
            refresh_token="bad",
            force=True,
        )
        self.assertEqual(outcome, "invalid")
        self.assertIsNone(user)
        self.assertEqual(access, "")

    def test_enter_session_expired_preserves_pricing_and_shows_notice(self):
        from src import auth_idle_recovery as recovery
        from src.auth_state import APP_LOGIN, AUTH_SIGNED_OUT

        with patch("src.auth_cookies.clear_auth_cookie", MagicMock()), patch(
            "src.auth_cookies.get_auth_cookie_manager", MagicMock(return_value=MagicMock())
        ):
            with self.assertRaises(RuntimeError):
                recovery.enter_session_expired_recovery(reason="token_invalid")

        self.assertEqual(self.st.session_state["cadivor_root_state"], APP_LOGIN)
        self.assertEqual(self.st.session_state["cadivor_auth_status"], AUTH_SIGNED_OUT)
        self.assertEqual(self.st.session_state["cadivor_requested_page"], "Pricing")
        self.assertEqual(
            self.st.session_state[recovery.SESSION_EXPIRED_NOTICE_KEY],
            recovery.SESSION_EXPIRED_NOTICE,
        )
        self.assertNotIn("access_token", self.st.session_state)
        self.assertNotIn("user", self.st.session_state)


class LoadWorkspaceProfileIdleRecoveryTests(unittest.TestCase):
    def setUp(self):
        _purge_auth_modules()
        self.st = _install_streamlit(
            {
                "user": types.SimpleNamespace(id="user-1", email="user@example.com"),
                "access_token": _jwt(3600),
                "refresh_token": "refresh-1",
                "cadivor_auth_status": "authenticated",
                "app_mode": "Pricing",
            }
        )
        from src import auth_idle_recovery as recovery

        self.recovery = recovery
        self.supabase = MagicMock()
        self.transport_error = type("TransportError", (Exception,), {})

    def tearDown(self):
        _purge_auth_modules()

    def _load(self, *, read_profile, ensure_profile=None, recent=None, remember=None):
        return self.recovery.load_workspace_profile(
            supabase=self.supabase,
            session_state=self.st.session_state,
            cookie_manager=MagicMock(),
            read_profile=read_profile,
            ensure_profile=ensure_profile or MagicMock(),
            recent_profile=recent or (lambda *_a, **_k: None),
            remember_profile=remember or (lambda _s, profile: dict(profile)),
            transport_error_type=self.transport_error,
        )

    def test_valid_active_session_returns_profile(self):
        profile = {"id": "user-1", "email": "user@example.com", "plan": "Trial"}
        with patch.object(
            self.recovery,
            "refresh_authenticated_session",
            return_value=("fresh", self.st.session_state["user"], _jwt(3600), "refresh-1"),
        ):
            loaded = self._load(
                read_profile=lambda _uid: types.SimpleNamespace(data=[profile]),
                ensure_profile=MagicMock(side_effect=AssertionError("no provision")),
            )
        self.assertEqual(loaded["id"], "user-1")

    def test_expired_session_refreshed_then_profile_retried(self):
        user = self.st.session_state["user"]
        self.st.session_state["access_token"] = _jwt(-20)
        profile = {"id": "user-1", "email": "user@example.com", "plan": "Trial"}
        ensure = MagicMock(side_effect=AssertionError("no provision"))
        with patch.object(
            self.recovery,
            "refresh_authenticated_session",
            return_value=("refreshed", user, _jwt(3600), "refresh-2"),
        ) as refresh_mock, patch.object(
            self.recovery, "commit_refreshed_workspace_session"
        ) as commit_mock:
            loaded = self._load(
                read_profile=lambda _uid: types.SimpleNamespace(data=[profile]),
                ensure_profile=ensure,
            )
        self.assertEqual(loaded["id"], "user-1")
        refresh_mock.assert_called()
        commit_mock.assert_called()
        ensure.assert_not_called()

    def test_refresh_failure_routes_to_branded_sign_in(self):
        self.st.session_state["access_token"] = _jwt(-20)
        with patch.object(
            self.recovery,
            "refresh_authenticated_session",
            return_value=("invalid", None, "", ""),
        ), patch.object(
            self.recovery,
            "enter_session_expired_recovery",
            side_effect=RuntimeError("signed-out-recovery"),
        ) as recover:
            with self.assertRaisesRegex(RuntimeError, "signed-out-recovery"):
                self._load(read_profile=lambda _uid: types.SimpleNamespace(data=[]))
        self.assertEqual(recover.call_args.kwargs.get("reason"), "token_invalid")

    def test_transient_profile_failure_keeps_session_and_offers_retry(self):
        with patch.object(
            self.recovery,
            "refresh_authenticated_session",
            return_value=("fresh", self.st.session_state["user"], _jwt(3600), "refresh-1"),
        ), patch.object(
            self.recovery,
            "render_retryable_profile_error",
            side_effect=SystemExit("retry-ui"),
        ) as retry_ui, patch.object(
            self.recovery, "enter_session_expired_recovery"
        ) as recover:
            with self.assertRaises(SystemExit):
                self._load(
                    read_profile=MagicMock(side_effect=self.transport_error("down")),
                    ensure_profile=MagicMock(side_effect=AssertionError("no provision")),
                )
        recover.assert_not_called()
        retry_ui.assert_called()
        self.assertIn("access_token", self.st.session_state)
        self.assertIsNotNone(self.st.session_state.get("user"))

    def test_empty_profile_after_unavailable_refresh_does_not_provision(self):
        ensure = MagicMock(side_effect=AssertionError("no provision"))
        with patch.object(
            self.recovery,
            "refresh_authenticated_session",
            side_effect=[
                ("fresh", self.st.session_state["user"], _jwt(3600), "refresh-1"),
                ("unavailable", None, _jwt(3600), "refresh-1"),
            ],
        ), patch.object(
            self.recovery,
            "render_retryable_profile_error",
            side_effect=SystemExit("retry-ui"),
        ):
            with self.assertRaises(SystemExit):
                self._load(
                    read_profile=lambda _uid: types.SimpleNamespace(data=[]),
                    ensure_profile=ensure,
                )
        ensure.assert_not_called()

    def test_authenticated_navigation_preserves_pricing_after_idle_recovery(self):
        self.st.session_state["app_mode"] = "Pricing"
        with patch("src.auth_cookies.clear_auth_cookie", MagicMock()), patch(
            "src.auth_cookies.get_auth_cookie_manager", MagicMock(return_value=MagicMock())
        ):
            with self.assertRaises(RuntimeError):
                self.recovery.enter_session_expired_recovery(reason="idle")
        self.assertEqual(self.st.session_state.get("cadivor_requested_page"), "Pricing")


if __name__ == "__main__":
    unittest.main()
