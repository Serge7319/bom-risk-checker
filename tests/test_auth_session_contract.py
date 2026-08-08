"""Session-state contract tests for Sprint 71.6.10 main-thread auth commit."""
from __future__ import annotations

import ast
import inspect
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = {}

    components = types.ModuleType("streamlit.components.v1")
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st


def _install_auth_state(st):
    secrets = types.ModuleType("src.secrets")
    secrets.get_secret_bool = lambda key, default=False: default
    sys.modules["src.secrets"] = secrets

    auth_cookies = types.ModuleType("src.auth_cookies")

    def _noop(*args, **kwargs):
        return None

    auth_cookies.log_auth_restore = _noop
    auth_cookies.persist_session_auth_cookie = _noop
    auth_cookies.clear_auth_cookie = _noop
    auth_cookies.native_context_cookies_available = lambda: False
    auth_cookies.read_auth_cookie_tokens = lambda cookie_manager=None: None
    auth_cookies.get_auth_cookie_manager = lambda mount=True: None
    auth_cookies.logout_blocks_auth_restore = lambda cookie_manager=None: False
    auth_cookies.invalidate_corrupt_auth_cookie = _noop
    sys.modules["src.auth_cookies"] = auth_cookies

    sys.modules.pop("src.auth_state", None)
    import importlib

    return importlib.import_module("src.auth_state")


class _FakeUser:
    id = "user-123"
    email = "user@example.com"


class _FakeSession:
    access_token = "access-main"
    refresh_token = "refresh-main"


class _InlineExecutor:
    """Run submitted work immediately for deterministic tests."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args, **kwargs):
        result = fn(*args, **kwargs)

        class _Future:
            def result(self, timeout=None):
                return result

        return _Future()


class AuthSessionContractTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name in {"src.auth_state", "src.auth_cookies"}:
                sys.modules.pop(name, None)

    def _load(self, session_state=None):
        st = _install_streamlit_stub(session_state)
        auth_state = _install_auth_state(st)
        return st, auth_state

    def _mock_supabase(self, *, user=_FakeUser(), fresh_tokens=("fresh-access", "fresh-refresh")):
        supabase = MagicMock()
        fresh_session = types.SimpleNamespace(
            access_token=fresh_tokens[0],
            refresh_token=fresh_tokens[1],
        )
        supabase.auth.set_session.return_value = types.SimpleNamespace(session=fresh_session)
        supabase.auth.get_user.return_value = types.SimpleNamespace(user=user)
        return supabase

    def test_fetch_validated_auth_does_not_reference_session_state(self):
        st, auth_state = self._load()
        source = inspect.getsource(auth_state._fetch_validated_auth)
        tree = ast.parse(source)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("st", names)
        self.assertNotIn("session_state", names)

    def test_validate_tokens_commits_user_on_main_thread(self):
        st, auth_state = self._load({})
        user = _FakeUser()
        supabase = self._mock_supabase(user=user)

        ok = auth_state._validate_tokens(
            supabase,
            "cookie-access",
            "cookie-refresh",
            cookie_manager=None,
        )

        self.assertTrue(ok)
        self.assertIn("user", st.session_state)
        self.assertIs(st.session_state["user"], user)
        self.assertEqual(st.session_state["access_token"], "fresh-access")
        self.assertEqual(st.session_state["refresh_token"], "fresh-refresh")
        self.assertEqual(st.session_state["cadivor_auth_status"], auth_state.AUTH_AUTHENTICATED)
        self.assertTrue(st.session_state["cadivor_auth_resolved"])

    def test_validate_tokens_failure_leaves_no_user(self):
        st, auth_state = self._load({})
        supabase = self._mock_supabase(user=None)

        ok = auth_state._validate_tokens(
            supabase,
            "cookie-access",
            "cookie-refresh",
            cookie_manager=None,
        )

        self.assertFalse(ok)
        self.assertNotIn("user", st.session_state)

    def test_cookie_restore_via_resolve_auth_state_sets_user(self):
        session = {
            "access_token": "cookie-access",
            "refresh_token": "cookie-refresh",
        }
        st, auth_state = self._load(session)
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_AUTHENTICATED)

    def test_mark_authenticated_sets_user_and_tokens(self):
        st, auth_state = self._load({})
        user = _FakeUser()
        session = _FakeSession()

        auth_state.mark_authenticated(user, session, cookie_manager=None)

        self.assertIs(st.session_state["user"], user)
        self.assertEqual(st.session_state["access_token"], "access-main")
        self.assertEqual(st.session_state["refresh_token"], "refresh-main")
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_AUTHENTICATED)
        self.assertEqual(st.session_state["cadivor_route"], "Dashboard")
        self.assertEqual(st.session_state["app_mode"], "Dashboard")

    def test_logout_clears_user(self):
        st, auth_state = self._load(
            {
                "user": _FakeUser(),
                "access_token": "a",
                "refresh_token": "r",
            }
        )
        auth_state.clear_auth_session()
        self.assertNotIn("user", st.session_state)
        self.assertNotIn("access_token", st.session_state)
        self.assertNotIn("refresh_token", st.session_state)


if __name__ == "__main__":
    unittest.main()
