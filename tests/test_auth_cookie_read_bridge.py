"""Static/logic tests for Sprint 71.6.4 auth cookie read-bridge fix."""
from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class _FakeCookieManager:
    """Minimal CookieManager stand-in matching extra-streamlit-components behavior."""

    instances: list["_FakeCookieManager"] = []
    component_key = "cadivor_auth_cookie_manager"

    def __init__(self, key: str = "init"):
        type(self).instances.append(self)
        self.key = key
        self.cookies: dict = {}

    def get(self, cookie: str):
        return self.cookies.get(cookie)

    def get_all(self, key: str = "get_all"):
        return dict(self.cookies)

    def set(self, **kwargs):
        name = kwargs.get("cookie")
        if name:
            self.cookies[name] = kwargs.get("val")

    def delete(self, **kwargs):
        self.cookies.pop(kwargs.get("cookie"), None)


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}

    class _Ctx:
        def __init__(self):
            self.script_run_id = "run-a"

    _ctx = _Ctx()

    def get_script_run_ctx():
        return _ctx

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = get_script_run_ctx
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    return st


def _install_auth_modules(st, cookie_manager_cls=_FakeCookieManager):
    secrets = types.ModuleType("src.secrets")
    secrets.get_secret_bool = lambda key, default=False: default
    sys.modules["src.secrets"] = secrets

    auth_state = types.ModuleType("src.auth_state")

    def coerce_cookie(raw):
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return None

    auth_state.coerce_cookie = coerce_cookie
    sys.modules["src.auth_state"] = auth_state

    stx = types.ModuleType("extra_streamlit_components")
    stx.CookieManager = cookie_manager_cls
    sys.modules["extra_streamlit_components"] = stx

    sys.modules.pop("src.auth_cookies", None)
    import importlib

    return importlib.import_module("src.auth_cookies")


class AuthCookieReadBridgeTests(unittest.TestCase):
    def setUp(self):
        _FakeCookieManager.instances.clear()
        for name in list(sys.modules):
            if name.startswith("src.auth_cookies"):
                sys.modules.pop(name, None)

    def test_fresh_manager_each_script_run_not_cross_run_singleton(self):
        session = {}
        st = _install_streamlit_stub(session)
        auth_cookies = _install_auth_modules(st)

        first = auth_cookies.get_auth_cookie_manager()
        self.assertIsInstance(first, _FakeCookieManager)
        self.assertEqual(len(_FakeCookieManager.instances), 1)

        # Same script run: second call reuses instance (no duplicate component key).
        second = auth_cookies.get_auth_cookie_manager()
        self.assertIs(first, second)
        self.assertEqual(len(_FakeCookieManager.instances), 1)

        # New Streamlit script run: new manager instance.
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"
        third = auth_cookies.get_auth_cookie_manager()
        self.assertIsInstance(third, _FakeCookieManager)
        self.assertIsNot(first, third)
        self.assertEqual(len(_FakeCookieManager.instances), 2)
        self.assertEqual(third.key, _FakeCookieManager.component_key)
        self.assertEqual(session[auth_cookies._AUTH_COOKIE_MANAGER_RUN_ID_KEY], "run-b")

    def test_cookie_state_visible_after_browser_hydration(self):
        st = _install_streamlit_stub({})
        auth_cookies = _install_auth_modules(st)

        run1_manager = auth_cookies.get_auth_cookie_manager()
        run1_manager.cookies = {}
        st.session_state.clear()
        st.session_state.update(
            {
                auth_cookies._AUTH_COOKIE_MANAGER_RUN_ID_KEY: "run-a",
                auth_cookies._AUTH_COOKIE_MANAGER_INSTANCE_KEY: run1_manager,
            }
        )

        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"
        run2_manager = auth_cookies.get_auth_cookie_manager()
        payload = json.dumps(
            {"access_token": "dummy-access", "refresh_token": "dummy-refresh"}
        )
        run2_manager.cookies = {auth_cookies.AUTH_COOKIE_NAME: payload}

        raw = auth_cookies._read_raw_auth_cookie(run2_manager)
        tokens = auth_cookies.parse_auth_cookie(raw)
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens["access_token"], "dummy-access")

    def test_hydration_attempts_terminate_fail_closed(self):
        session = {"cadivor_auth_restore_attempts": 6, "cadivor_auth_cookie_absent": True}
        st = _install_streamlit_stub(session)
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))
        self.assertTrue(session.get("cadivor_auth_cookie_absent"))

    def test_missing_cookie_eventually_not_hydration_pending_after_timeout(self):
        session = {}
        st = _install_streamlit_stub(session)
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        for _ in range(auth_cookies._MAX_HYDRATION_ATTEMPTS):
            self.assertTrue(auth_cookies.auth_cookie_hydration_pending(manager))
            auth_cookies.record_auth_hydration_attempt()

        auth_cookies.finalize_auth_cookie_hydration_timeout(manager)
        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))
        self.assertTrue(session.get("cadivor_auth_cookie_absent"))

    def test_invalid_cookie_not_hydration_pending(self):
        st = _install_streamlit_stub({})
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {auth_cookies.AUTH_COOKIE_NAME: "not-json"}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))

    def test_existing_session_tokens_skip_hydration(self):
        session = {"access_token": "a", "refresh_token": "b", "user": object()}
        st = _install_streamlit_stub(session)
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))
        self.assertFalse(auth_cookies.hydrate_session_from_auth_cookie(manager))

    def test_serialize_payload_unchanged(self):
        st = _install_streamlit_stub({})
        auth_cookies = _install_auth_modules(st)
        serialized = auth_cookies._serialize_auth_cookie_payload("acc", "ref")
        self.assertEqual(
            serialized,
            '{"access_token":"acc","refresh_token":"ref"}',
        )


if __name__ == "__main__":
    unittest.main()
