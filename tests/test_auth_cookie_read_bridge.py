"""Static/logic tests for Sprint 71.6.6 native context auth cookie read bridge."""
from __future__ import annotations

import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout


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


class _FakeContextCookies(dict):
    """Dict-like stand-in for Streamlit 1.60 ``st.context.cookies``."""

    def get(self, key, default=None):
        return super().get(key, default)


def _install_streamlit_stub(
    session_state: dict | None = None,
    *,
    context_cookies: dict | None | object = _FakeContextCookies(),
):
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

    if context_cookies is not _FakeContextCookies():
        if context_cookies is None:
            st.context = None
        else:
            st.context = types.SimpleNamespace(cookies=context_cookies)

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
    auth_state.log_auth_diagnostic = lambda *args, **kwargs: None
    sys.modules["src.auth_state"] = auth_state

    stx = types.ModuleType("extra_streamlit_components")
    stx.CookieManager = cookie_manager_cls
    sys.modules["extra_streamlit_components"] = stx

    sys.modules.pop("src.auth_cookies", None)
    import importlib

    return importlib.import_module("src.auth_cookies")


def _valid_payload(
    access: str = "dummy-access",
    refresh: str = "dummy-refresh",
) -> str:
    return json.dumps({"access_token": access, "refresh_token": refresh})


_AUTH_COOKIE_NAME = "cadivor_auth"
_AUTH_COOKIE_LEGACY_NAME = "bom_auth"


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

        second = auth_cookies.get_auth_cookie_manager()
        self.assertIs(first, second)
        self.assertEqual(len(_FakeCookieManager.instances), 1)

        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"
        third = auth_cookies.get_auth_cookie_manager()
        self.assertIsInstance(third, _FakeCookieManager)
        self.assertIsNot(first, third)
        self.assertEqual(len(_FakeCookieManager.instances), 2)
        self.assertEqual(third.key, _FakeCookieManager.component_key)
        self.assertEqual(session[auth_cookies._AUTH_COOKIE_MANAGER_RUN_ID_KEY], "run-b")

    def test_context_cookie_present_native_read_wins(self):
        payload = _valid_payload("ctx-access", "ctx-refresh")
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: payload})
        st = _install_streamlit_stub({}, context_cookies=context)
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {
            _AUTH_COOKIE_NAME: _valid_payload("mgr-access", "mgr-refresh")
        }

        raw = auth_cookies._read_raw_auth_cookie(manager)
        tokens = auth_cookies.parse_auth_cookie(raw)
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens["access_token"], "ctx-access")
        self.assertEqual(tokens["refresh_token"], "ctx-refresh")

    def test_context_absent_falls_back_to_cookie_manager(self):
        st = _install_streamlit_stub({}, context_cookies=_FakeContextCookies())
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {
            _AUTH_COOKIE_NAME: _valid_payload("mgr-access", "mgr-refresh")
        }

        raw = auth_cookies._read_raw_auth_cookie(manager)
        tokens = auth_cookies.parse_auth_cookie(raw)
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens["access_token"], "mgr-access")

    def test_context_api_unavailable_falls_back_safely(self):
        st = _install_streamlit_stub({}, context_cookies=None)
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {_AUTH_COOKIE_NAME: _valid_payload()}

        raw = auth_cookies._read_raw_auth_cookie(manager)
        self.assertIsNotNone(auth_cookies.parse_auth_cookie(raw))

    def test_context_api_exception_falls_back_safely(self):
        class _BrokenCookies:
            def get(self, _key, default=None):
                raise RuntimeError("context unavailable")

        st = _install_streamlit_stub({}, context_cookies=_BrokenCookies())
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {_AUTH_COOKIE_NAME: _valid_payload()}

        raw = auth_cookies._read_raw_auth_cookie(manager)
        self.assertIsNotNone(auth_cookies.parse_auth_cookie(raw))

    def test_malformed_context_cookie_fails_closed(self):
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: "not-json"})
        st = _install_streamlit_stub({}, context_cookies=context)
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        raw = auth_cookies._read_raw_auth_cookie(manager)
        self.assertEqual(raw, "not-json")
        self.assertIsNone(auth_cookies.parse_auth_cookie(raw))
        self.assertFalse(auth_cookies.hydrate_session_from_auth_cookie(manager))
        self.assertTrue(st.session_state.get("cadivor_auth_cookie_absent"))

    def test_valid_context_cookie_hydrates_session_state(self):
        payload = _valid_payload("hydrate-access", "hydrate-refresh")
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: payload})
        st = _install_streamlit_stub({}, context_cookies=context)
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()

        self.assertTrue(auth_cookies.hydrate_session_from_auth_cookie(manager))
        self.assertEqual(st.session_state["access_token"], "hydrate-access")
        self.assertEqual(st.session_state["refresh_token"], "hydrate-refresh")
        self.assertNotIn("cadivor_auth_cookie_absent", st.session_state)

    def test_context_cookie_on_run_one_bypasses_hydration_pending(self):
        payload = _valid_payload()
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: payload})
        st = _install_streamlit_stub({}, context_cookies=context)
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))

    def test_cookie_state_visible_after_browser_hydration(self):
        st = _install_streamlit_stub({}, context_cookies=_FakeContextCookies())
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
        run2_manager.cookies = {_AUTH_COOKIE_NAME: _valid_payload()}

        raw = auth_cookies._read_raw_auth_cookie(run2_manager)
        tokens = auth_cookies.parse_auth_cookie(raw)
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens["access_token"], "dummy-access")

    def test_legacy_bom_auth_manager_fallback(self):
        st = _install_streamlit_stub({}, context_cookies=_FakeContextCookies())
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {
            _AUTH_COOKIE_LEGACY_NAME: _valid_payload("legacy-access", "legacy-refresh")
        }

        raw = auth_cookies._read_raw_auth_cookie(manager)
        tokens = auth_cookies.parse_auth_cookie(raw)
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens["access_token"], "legacy-access")

    def test_hydration_attempts_terminate_fail_closed(self):
        session = {"cadivor_auth_restore_attempts": 6, "cadivor_auth_cookie_absent": True}
        st = _install_streamlit_stub(session, context_cookies=_FakeContextCookies())
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))
        self.assertTrue(session.get("cadivor_auth_cookie_absent"))

    def test_missing_cookie_eventually_not_hydration_pending_after_timeout(self):
        session = {}
        st = _install_streamlit_stub(session, context_cookies=_FakeContextCookies())
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
        st = _install_streamlit_stub({}, context_cookies=_FakeContextCookies())
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {_AUTH_COOKIE_NAME: "not-json"}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))

    def test_existing_session_tokens_skip_hydration(self):
        session = {"access_token": "a", "refresh_token": "b", "user": object()}
        st = _install_streamlit_stub(session, context_cookies=_FakeContextCookies())
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))
        self.assertFalse(auth_cookies.hydrate_session_from_auth_cookie(manager))

    def test_logout_clear_auth_cookie_unchanged(self):
        st = _install_streamlit_stub({}, context_cookies=_FakeContextCookies())
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {
            _AUTH_COOKIE_NAME: _valid_payload(),
            _AUTH_COOKIE_LEGACY_NAME: _valid_payload("legacy-a", "legacy-r"),
        }

        auth_cookies.clear_auth_cookie(manager)
        self.assertIn(_AUTH_COOKIE_NAME, manager.cookies)
        self.assertIn(_AUTH_COOKIE_LEGACY_NAME, manager.cookies)
        self.assertFalse(str(manager.cookies[_AUTH_COOKIE_NAME]).strip())
        self.assertFalse(str(manager.cookies[_AUTH_COOKIE_LEGACY_NAME]).strip())
        self.assertTrue(st.session_state.get("cadivor_auth_cookie_absent"))

    def test_serialize_payload_unchanged(self):
        st = _install_streamlit_stub({}, context_cookies=_FakeContextCookies())
        auth_cookies = _install_auth_modules(st)
        serialized = auth_cookies._serialize_auth_cookie_payload("acc", "ref")
        self.assertEqual(
            serialized,
            '{"access_token":"acc","refresh_token":"ref"}',
        )

    def test_diagnostics_never_log_token_values(self):
        payload = _valid_payload("secret-access-token", "secret-refresh-token")
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: payload})
        st = _install_streamlit_stub({}, context_cookies=context)
        auth_cookies = _install_auth_modules(st)
        manager = auth_cookies.get_auth_cookie_manager()

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            auth_cookies.hydrate_session_from_auth_cookie(manager)

        output = buffer.getvalue()
        self.assertIn("AUTH_COOKIE context_available available=True", output)
        self.assertIn("AUTH_COOKIE context_read_present present=True", output)
        self.assertIn("AUTH_COOKIE parse_valid valid=True", output)
        self.assertNotIn("secret-access-token", output)
        self.assertNotIn("secret-refresh-token", output)
        self.assertNotIn(payload, output)


if __name__ == "__main__":
    unittest.main()
