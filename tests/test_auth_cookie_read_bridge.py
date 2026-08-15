"""Static/logic tests for native context auth cookie read bridge and normalization."""
from __future__ import annotations

import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout
from urllib.parse import quote, unquote_plus


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

    class _NullContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _container(*args, **kwargs):
        return _NullContext()

    st.container = _container
    st.cache_resource = lambda **_kwargs: (lambda fn: fn)

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
    components = types.ModuleType("streamlit.components.v1")
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st


def _install_auth_modules(st, cookie_manager_cls=_FakeCookieManager):
    secrets = types.ModuleType("src.secrets")
    secrets.get_secret_bool = lambda key, default=False: default
    sys.modules["src.secrets"] = secrets

    for name in list(sys.modules):
        if name in {"src.auth_state", "src.auth_cookies"}:
            sys.modules.pop(name, None)

    import importlib

    auth_state = importlib.import_module("src.auth_state")

    stx = types.ModuleType("extra_streamlit_components")
    stx.CookieManager = cookie_manager_cls
    sys.modules["extra_streamlit_components"] = stx

    auth_cookies = importlib.import_module("src.auth_cookies")
    return auth_cookies, auth_state


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
            if name.startswith("src.auth_cookies") or name == "src.auth_state":
                sys.modules.pop(name, None)

    def _load(self, session_state=None, **kwargs):
        st = _install_streamlit_stub(session_state, **kwargs)
        auth_cookies, auth_state = _install_auth_modules(st)
        return st, auth_cookies, auth_state

    def test_fresh_manager_each_script_run_not_cross_run_singleton(self):
        session = {}
        st, auth_cookies, _auth_state = self._load(session)

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
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)
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
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {
            _AUTH_COOKIE_NAME: _valid_payload("mgr-access", "mgr-refresh")
        }

        raw = auth_cookies._read_raw_auth_cookie(manager)
        tokens = auth_cookies.parse_auth_cookie(raw)
        self.assertIsNotNone(tokens)
        self.assertEqual(tokens["access_token"], "mgr-access")

    def test_context_api_unavailable_falls_back_safely(self):
        st, auth_cookies, _auth_state = self._load({}, context_cookies=None)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {_AUTH_COOKIE_NAME: _valid_payload()}

        raw = auth_cookies._read_raw_auth_cookie(manager)
        self.assertIsNotNone(auth_cookies.parse_auth_cookie(raw))

    def test_context_api_exception_falls_back_safely(self):
        class _BrokenCookies:
            def get(self, _key, default=None):
                raise RuntimeError("context unavailable")

        st, auth_cookies, _auth_state = self._load({}, context_cookies=_BrokenCookies())
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {_AUTH_COOKIE_NAME: _valid_payload()}

        raw = auth_cookies._read_raw_auth_cookie(manager)
        self.assertIsNotNone(auth_cookies.parse_auth_cookie(raw))

    def test_malformed_context_cookie_fails_closed(self):
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: "not-json"})
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        raw = auth_cookies._read_raw_auth_cookie(manager)
        self.assertEqual(raw, "not-json")
        self.assertIsNone(auth_cookies.parse_auth_cookie(raw))
        self.assertFalse(auth_cookies.hydrate_session_from_auth_cookie(manager))
        self.assertTrue(st.session_state.get("cadivor_auth_cookie_absent"))

    def test_valid_context_cookie_readable_without_session_write(self):
        payload = _valid_payload("hydrate-access", "hydrate-refresh")
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: payload})
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)

        self.assertTrue(auth_cookies.hydrate_session_from_auth_cookie(None))
        tokens = auth_cookies.read_auth_cookie_tokens(None)
        self.assertEqual(tokens["access_token"], "hydrate-access")
        self.assertNotIn("access_token", st.session_state)
        self.assertNotIn("refresh_token", st.session_state)
        self.assertNotIn("cadivor_auth_cookie_absent", st.session_state)

    def test_context_cookie_on_run_one_bypasses_hydration_pending(self):
        payload = _valid_payload()
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: payload})
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))

    def test_cookie_state_visible_after_browser_hydration(self):
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())

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
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
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
        st, auth_cookies, _auth_state = self._load(session, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))
        self.assertTrue(session.get("cadivor_auth_cookie_absent"))

    def test_missing_cookie_not_hydration_pending_with_native_context(self):
        session = {}
        st, auth_cookies, _auth_state = self._load(session, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))

    def test_missing_cookie_eventually_not_hydration_pending_after_timeout(self):
        session = {}
        st, auth_cookies, _auth_state = self._load(session, context_cookies=None)
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies = {}

        for _ in range(auth_cookies._MAX_HYDRATION_ATTEMPTS):
            self.assertTrue(auth_cookies.auth_cookie_hydration_pending(manager))
            auth_cookies.record_auth_hydration_attempt()

        auth_cookies.finalize_auth_cookie_hydration_timeout(manager)
        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))
        self.assertTrue(session.get("cadivor_auth_cookie_absent"))

    def test_invalid_cookie_not_hydration_pending(self):
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {_AUTH_COOKIE_NAME: "not-json"}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))

    def test_existing_session_tokens_skip_hydration(self):
        session = {"access_token": "a", "refresh_token": "b", "user": object()}
        st, auth_cookies, _auth_state = self._load(session, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}

        self.assertFalse(auth_cookies.auth_cookie_hydration_pending(manager))
        self.assertFalse(auth_cookies.hydrate_session_from_auth_cookie(manager))

    def test_logout_clear_auth_cookie_unchanged(self):
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
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
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
        serialized = auth_cookies._serialize_auth_cookie_payload("acc", "ref")
        self.assertEqual(
            serialized,
            '{"access_token":"acc","refresh_token":"ref"}',
        )

    def test_diagnostics_never_log_token_values(self):
        payload = _valid_payload("secret-access-token", "secret-refresh-token")
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: payload})
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)
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

    def test_plain_json_string_direct_parse(self):
        _st, auth_cookies, auth_state = self._load({})
        payload = _valid_payload("plain-access", "plain-refresh")
        parsed, metadata = auth_state._parse_cookie_json_string(payload)
        self.assertEqual(parsed["access_token"], "plain-access")
        self.assertTrue(metadata["json_parse_direct"])
        self.assertFalse(metadata["url_decode_attempted"])
        self.assertIsNotNone(auth_cookies.parse_auth_cookie(payload))

    def test_percent_encoded_json_normalizes_once(self):
        _st, auth_cookies, auth_state = self._load({})
        payload = _valid_payload("enc-access", "enc-refresh")
        encoded = quote(payload, safe="")
        parsed, metadata = auth_state._parse_cookie_json_string(encoded)
        self.assertEqual(parsed["access_token"], "enc-access")
        self.assertFalse(metadata["json_parse_direct"])
        self.assertTrue(metadata["url_decode_attempted"])
        self.assertTrue(metadata["decoding_changed_value"])
        self.assertTrue(metadata["json_parse_after_url_decode"])
        tokens = auth_cookies.parse_auth_cookie(encoded)
        self.assertEqual(tokens["access_token"], "enc-access")

    def test_dict_input_unchanged(self):
        _st, auth_cookies, auth_state = self._load({})
        payload = {"access_token": "dict-access", "refresh_token": "dict-refresh"}
        self.assertEqual(auth_state.coerce_cookie(payload), payload)
        tokens = auth_cookies.parse_auth_cookie(payload)
        self.assertEqual(tokens["access_token"], "dict-access")

    def test_malformed_percent_encoded_garbage_fails_closed(self):
        _st, auth_cookies, auth_state = self._load({})
        garbage = quote("%ZZ-not-json-{{", safe="")
        self.assertIsNone(auth_state.coerce_cookie(garbage))
        self.assertIsNone(auth_cookies.parse_auth_cookie(garbage))

    def test_decoded_json_missing_access_token_fails_closed(self):
        _st, auth_cookies, _auth_state = self._load({})
        payload = quote(json.dumps({"refresh_token": "only-refresh"}), safe="")
        self.assertIsNone(auth_cookies.parse_auth_cookie(payload))

    def test_decoded_json_missing_refresh_token_fails_closed(self):
        _st, auth_cookies, _auth_state = self._load({})
        payload = quote(json.dumps({"access_token": "only-access"}), safe="")
        self.assertIsNone(auth_cookies.parse_auth_cookie(payload))

    def test_empty_access_or_refresh_token_fails_closed(self):
        _st, auth_cookies, _auth_state = self._load({})
        for body in (
            {"access_token": "", "refresh_token": "r"},
            {"access_token": "a", "refresh_token": ""},
            {"access_token": "   ", "refresh_token": "r"},
        ):
            payload = quote(json.dumps(body), safe="")
            self.assertIsNone(auth_cookies.parse_auth_cookie(payload))

    def test_literal_plus_preserved_not_unquote_plus(self):
        _st, auth_cookies, auth_state = self._load({})
        plus_token = "token+with+plus"
        payload = _valid_payload("access", plus_token)
        tokens = auth_cookies.parse_auth_cookie(payload)
        self.assertEqual(tokens["refresh_token"], plus_token)

        encoded = quote(payload, safe="")
        tokens = auth_cookies.parse_auth_cookie(encoded)
        self.assertEqual(tokens["refresh_token"], plus_token)
        # unquote_plus would turn literal "+" into space; unquote preserves it.
        self.assertEqual(unquote_plus("a+b"), "a b")
        self.assertEqual(auth_state.unquote("a+b"), "a+b")

    def test_double_encoded_value_single_decode_only(self):
        _st, auth_cookies, auth_state = self._load({})
        payload = _valid_payload("double-a", "double-r")
        double = quote(quote(payload, safe=""), safe="")
        parsed, metadata = auth_state._parse_cookie_json_string(double)
        self.assertIsNone(parsed)
        self.assertTrue(metadata["url_decode_attempted"])
        self.assertFalse(metadata["json_parse_after_url_decode"])
        self.assertIsNone(auth_cookies.parse_auth_cookie(double))

    def test_context_percent_encoded_cookie_readable_without_session_write(self):
        payload = _valid_payload("ctx-enc-access", "ctx-enc-refresh")
        encoded = quote(payload, safe="")
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: encoded})
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)

        self.assertTrue(auth_cookies.hydrate_session_from_auth_cookie(None))
        tokens = auth_cookies.read_auth_cookie_tokens(None)
        self.assertEqual(tokens["access_token"], "ctx-enc-access")
        self.assertNotIn("access_token", st.session_state)

    def test_no_cookie_path_fails_closed(self):
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager()
        manager.cookies = {}
        self.assertFalse(auth_cookies.hydrate_session_from_auth_cookie(manager))
        self.assertIsNone(auth_cookies.parse_auth_cookie(None))

    def test_percent_encoded_diagnostics_no_secrets(self):
        payload = _valid_payload("secret-a", "secret-r")
        encoded = quote(payload, safe="")
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: encoded})
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)
        manager = auth_cookies.get_auth_cookie_manager()

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            auth_cookies.hydrate_session_from_auth_cookie(manager)

        output = buffer.getvalue()
        self.assertIn("AUTH_COOKIE parse_attempt", output)
        self.assertIn("json_parse_after_url_decode=True", output)
        self.assertIn("url_decode_attempted=True", output)
        self.assertNotIn("secret-a", output)
        self.assertNotIn("secret-r", output)
        self.assertNotIn(payload, output)
        self.assertNotIn(encoded, output)


class _DeferredHydrationCookieManager(_FakeCookieManager):
    """Return None until session marks browser cookie hydration complete."""

    session_state: dict | None = None

    def get(self, cookie: str):
        if cookie != _AUTH_COOKIE_NAME:
            return self.cookies.get(cookie)
        session = type(self).session_state
        if session is None or not session.get("_manager_hydration_complete"):
            return None
        return self.cookies.get(cookie)


class UnifiedAuthCookieReadTests(unittest.TestCase):
    """Sprint 71.10.2 — unified native context → CookieManager read authority."""

    def setUp(self):
        _FakeCookieManager.instances.clear()
        for name in list(sys.modules):
            if name.startswith("src.auth_cookies") or name == "src.auth_state":
                sys.modules.pop(name, None)

    def _load(self, session_state=None, **kwargs):
        st = _install_streamlit_stub(session_state, **kwargs)
        auth_cookies, auth_state = _install_auth_modules(st)
        return st, auth_cookies, auth_state

    def test_context_present_valid_cookie_skips_manager_mount(self):
        payload = _valid_payload("ctx-only-a", "ctx-only-r")
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: payload})
        _st, auth_cookies, _auth_state = self._load({}, context_cookies=context)

        tokens, source = auth_cookies.read_auth_cookie_tokens_with_source(None)

        self.assertEqual(tokens["access_token"], "ctx-only-a")
        self.assertEqual(source, "context")
        self.assertEqual(len(_FakeCookieManager.instances), 0)

    def test_context_absent_manager_valid_uses_manager_fallback(self):
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies = {_AUTH_COOKIE_NAME: _valid_payload("mgr-a", "mgr-r")}

        tokens, source = auth_cookies.read_auth_cookie_tokens_with_source(None)

        self.assertEqual(tokens["access_token"], "mgr-a")
        self.assertEqual(source, "manager_fallback")
        self.assertEqual(len(_FakeCookieManager.instances), 1)
        self.assertNotIn("access_token", st.session_state)

    def test_context_absent_manager_absent_returns_none(self):
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies = {}

        tokens, source = auth_cookies.read_auth_cookie_tokens_with_source(None)

        self.assertIsNone(tokens)
        self.assertEqual(source, "none")
        self.assertNotIn("access_token", st.session_state)

    def test_context_malformed_manager_valid_uses_manager_fallback(self):
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: "not-json"})
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies = {_AUTH_COOKIE_NAME: _valid_payload("mgr-a", "mgr-r")}

        tokens, source = auth_cookies.read_auth_cookie_tokens_with_source(None)

        self.assertEqual(tokens["access_token"], "mgr-a")
        self.assertEqual(source, "manager_fallback")
        self.assertNotIn("access_token", st.session_state)

    def test_context_invalid_manager_absent_fails_closed(self):
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: "not-json"})
        st, auth_cookies, _auth_state = self._load({}, context_cookies=context)
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies = {}

        tokens, source = auth_cookies.read_auth_cookie_tokens_with_source(None)

        self.assertIsNone(tokens)
        self.assertEqual(source, "none")

    def test_cookie_source_diagnostics_never_log_secrets(self):
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: _valid_payload("diag-a", "diag-r")})
        _st, auth_cookies, _auth_state = self._load({}, context_cookies=context)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            auth_cookies.read_auth_cookie_tokens_with_source(None)

        output = buffer.getvalue()
        self.assertIn("AUTH_COOKIE cookie_source cookie_source=context", output)
        self.assertNotIn("diag-a", output)
        self.assertNotIn("diag-r", output)

    def test_native_cookie_api_available_does_not_imply_cookie_present(self):
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies = {}

        self.assertTrue(auth_cookies.native_cookie_api_available())
        tokens, source = auth_cookies.read_auth_cookie_tokens_with_source(None)
        self.assertIsNone(tokens)
        self.assertEqual(source, "none")


class ManagerFallbackHydrationTests(unittest.TestCase):
    """Sprint 71.10.2B — bounded manager fallback hydration."""

    def setUp(self):
        _FakeCookieManager.instances.clear()
        _DeferredHydrationCookieManager.instances.clear()
        _DeferredHydrationCookieManager.session_state = None
        for name in list(sys.modules):
            if name.startswith("src.auth_cookies") or name == "src.auth_state":
                sys.modules.pop(name, None)

    def _load(self, session_state=None, *, manager_cls=_DeferredHydrationCookieManager, **kwargs):
        session = session_state if session_state is not None else {}
        st = _install_streamlit_stub(session, **kwargs)
        manager_cls.session_state = st.session_state
        auth_cookies, auth_state = _install_auth_modules(st, cookie_manager_cls=manager_cls)
        return st, auth_cookies, auth_state

    def _mock_supabase(self):
        supabase = types.ModuleType("supabase")
        user = types.SimpleNamespace(id="user-123")
        fresh_session = types.SimpleNamespace(
            access_token="fresh-access",
            refresh_token="fresh-refresh",
        )

        class _Auth:
            @staticmethod
            def set_session(access_token, refresh_token):
                return types.SimpleNamespace(session=fresh_session)

            @staticmethod
            def get_user():
                return types.SimpleNamespace(user=user)

        supabase.auth = _Auth()
        return supabase

    def test_first_manager_miss_marks_fallback_hydration_pending(self):
        st, auth_cookies, _auth_state = self._load({}, context_cookies=_FakeContextCookies())
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies[_AUTH_COOKIE_NAME] = _valid_payload("delayed-a", "delayed-r")

        tokens, source = auth_cookies.read_auth_cookie_tokens_with_source(None)

        self.assertIsNone(tokens)
        self.assertEqual(source, "none")
        self.assertTrue(st.session_state.get("cadivor_manager_fallback_attempted"))
        self.assertTrue(auth_cookies.manager_fallback_hydration_pending(None))

    def test_second_run_manager_hydration_restores(self):
        st, auth_cookies, auth_state = self._load(
            {
                "cadivor_manager_fallback_attempted": True,
                "cadivor_auth_restore_attempts": 1,
            },
            context_cookies=_FakeContextCookies(),
        )
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"
        st.session_state["_manager_hydration_complete"] = True
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies[_AUTH_COOKIE_NAME] = _valid_payload("delayed-a", "delayed-r")
        supabase = self._mock_supabase()

        tokens, source = auth_cookies.read_auth_cookie_tokens_with_source(None)
        self.assertEqual(source, "manager_fallback")
        self.assertFalse(auth_cookies.manager_fallback_hydration_pending(None))
        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertIn("user", st.session_state)
        self.assertFalse(st.session_state.get("cadivor_manager_fallback_attempted"))

    def test_malformed_context_second_run_manager_restore(self):
        context = _FakeContextCookies({_AUTH_COOKIE_NAME: "not-json"})
        st, auth_cookies, auth_state = self._load(
            {
                "cadivor_manager_fallback_attempted": True,
                "cadivor_auth_restore_attempts": 1,
            },
            context_cookies=context,
        )
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"
        st.session_state["_manager_hydration_complete"] = True
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies[_AUTH_COOKIE_NAME] = _valid_payload("fallback-a", "fallback-r")
        supabase = self._mock_supabase()

        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)

        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        self.assertNotIn("fallback-a", st.session_state.get("access_token", ""))

    def test_max_attempts_fail_closed(self):
        st, auth_cookies, _auth_state = self._load(
            {
                "cadivor_manager_fallback_attempted": True,
                "cadivor_auth_restore_attempts": 6,
            },
            context_cookies=_FakeContextCookies(),
        )
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies = {}

        self.assertFalse(auth_cookies.manager_fallback_hydration_pending(None))

    def test_logout_marker_blocks_fallback_hydration(self):
        st, auth_cookies, _auth_state = self._load(
            {"cadivor_manager_fallback_attempted": True},
            context_cookies=_FakeContextCookies(),
        )
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies[auth_cookies.AUTH_LOGOUT_COOKIE_NAME] = "1"

        self.assertFalse(auth_cookies.manager_fallback_hydration_pending(None))

    def test_force_signed_out_blocks_fallback_hydration(self):
        st, auth_cookies, _auth_state = self._load(
            {
                "cadivor_manager_fallback_attempted": True,
                "cadivor_force_signed_out": True,
            },
            context_cookies=_FakeContextCookies(),
        )

        self.assertFalse(auth_cookies.manager_fallback_hydration_pending(None))

    def test_manual_login_blocks_fallback_hydration(self):
        st, auth_cookies, _auth_state = self._load(
            {
                "cadivor_manager_fallback_attempted": True,
                "cadivor_manual_login_in_progress": True,
            },
            context_cookies=_FakeContextCookies(),
        )

        self.assertFalse(auth_cookies.manager_fallback_hydration_pending(None))

    def test_finalize_timeout_clears_fallback_flag(self):
        st, auth_cookies, _auth_state = self._load(
            {"cadivor_manager_fallback_attempted": True},
            context_cookies=_FakeContextCookies(),
        )
        manager = auth_cookies.get_auth_cookie_manager(mount=True)

        auth_cookies.finalize_manager_fallback_hydration_timeout(manager)

        self.assertFalse(st.session_state.get("cadivor_manager_fallback_attempted"))
        self.assertTrue(st.session_state.get("cadivor_auth_cookie_absent"))

    def test_hydration_success_emits_safe_log(self):
        st, auth_cookies, _auth_state = self._load(
            {
                "cadivor_manager_fallback_attempted": True,
                "cadivor_auth_restore_attempts": 1,
            },
            context_cookies=_FakeContextCookies(),
        )
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"
        st.session_state["_manager_hydration_complete"] = True
        manager = auth_cookies.get_auth_cookie_manager(mount=True)
        manager.cookies[_AUTH_COOKIE_NAME] = _valid_payload("log-a", "log-r")

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            auth_cookies.read_auth_cookie_tokens_with_source(None)

        output = buffer.getvalue()
        self.assertIn("AUTH_RESTORE manager_fallback_hydration_success", output)
        self.assertNotIn("log-a", output)
        self.assertNotIn("log-r", output)


if __name__ == "__main__":
    unittest.main()
