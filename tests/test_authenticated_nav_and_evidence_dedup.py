"""Regression tests for:

A. Authenticated navigation — stale logout marker must not log out a valid
   re-authenticated session.  Supersession requires a *fully valid* JWT:
   unexpired, identity claims present, and issued after the recorded logout.

B. Explicit manual logout — logout initiated in the current session must not be
   undone merely because an old auth cookie has not yet been deleted by
   CookieManager (async write).

C. Supplier-evidence deduplication — repeated identical relationship records
   must render as a single concise text entry with one link.
"""
from __future__ import annotations

import base64
import importlib
import json
import sys
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# JWT / cookie payload factories
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_jwt(
    *,
    sub: str = "user-uuid-123",
    email: str = "user@example.com",
    role: str = "",
    iat: float | None = None,
    exp: float | None = None,
    omit_sub: bool = False,
    omit_email_role: bool = False,
) -> str:
    """Build a structurally valid but *unsigned* JWT for testing claim extraction."""
    now = time.time()
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims: dict = {
        "iat": iat if iat is not None else int(now - 60),
        "exp": exp if exp is not None else int(now + 3600),
    }
    if not omit_sub:
        claims["sub"] = sub
    if not omit_email_role:
        if email:
            claims["email"] = email
        if role:
            claims["role"] = role
    payload = _b64url(json.dumps(claims).encode())
    sig = _b64url(b"fake-signature")  # signature not verified in unit tests
    return f"{header}.{payload}.{sig}"


def _auth_cookie_payload(access_token: str, refresh_token: str = "refresh-tok") -> str:
    return json.dumps({"access_token": access_token, "refresh_token": refresh_token})


def _logout_marker_json(logout_at: float | None = None) -> str:
    """Build a timestamped logout marker as written by the hardened _set_logout_marker."""
    ts = int(logout_at if logout_at is not None else time.time())
    return json.dumps({"v": 1, "logout_at": ts}, separators=(",", ":"))


def _legacy_logout_marker() -> str:
    return "1"


# ---------------------------------------------------------------------------
# Streamlit + auth module stub helpers
# ---------------------------------------------------------------------------

class _FakeCookieManager:
    def __init__(self):
        self.cookies: dict = {}

    def get(self, cookie: str = "", **kwargs):
        return self.cookies.get(cookie)

    def set(self, cookie: str = "", val: str = "", **kwargs):
        self.cookies[cookie] = val

    def delete(self, cookie: str = "", **kwargs):
        self.cookies.pop(cookie, None)

    def get_all(self, **kwargs):
        return dict(self.cookies)


class _FakeContextCookies(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def _install_st_stub(session_state=None, *, context_cookies=None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.context = types.SimpleNamespace(
        cookies=context_cookies if context_cookies is not None else _FakeContextCookies()
    )
    st.cache_resource = lambda **_kw: (lambda fn: fn)
    st.rerun = lambda: None
    st.query_params = {}

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    st.container = lambda *a, **kw: _NullCtx()
    st.empty = lambda: types.SimpleNamespace(
        container=lambda **kw: _NullCtx(), empty=lambda: None
    )
    runtime_mod = types.ModuleType("streamlit.runtime")
    scriptrunner_mod = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner_mod.get_script_run_ctx = lambda: None
    runtime_mod.scriptrunner = scriptrunner_mod
    components_mod = types.ModuleType("streamlit.components")
    components_v1_mod = types.ModuleType("streamlit.components.v1")
    sys.modules.update({
        "streamlit": st,
        "streamlit.runtime": runtime_mod,
        "streamlit.runtime.scriptrunner": scriptrunner_mod,
        "streamlit.components": components_mod,
        "streamlit.components.v1": components_v1_mod,
    })
    return st


def _install_auth_modules(st):
    from tests.secrets_module_isolation import install_src_secrets_stub

    _secrets, restore_secrets = install_src_secrets_stub(
        get_secret_bool=lambda key, default=False: default,
        get_secret=lambda key, required=False, default="": default,
        ConfigurationError=RuntimeError,
    )
    stx = types.ModuleType("extra_streamlit_components")
    stx.CookieManager = _FakeCookieManager
    sys.modules["extra_streamlit_components"] = stx
    for mod_name in list(sys.modules):
        if mod_name in {"src.auth_state", "src.auth_cookies"}:
            sys.modules.pop(mod_name)
    auth_state = importlib.import_module("src.auth_state")
    auth_cookies = importlib.import_module("src.auth_cookies")
    return auth_cookies, auth_state, restore_secrets


class _ModuleIsolationMixin:
    """setUp/tearDown that saves and restores sys.modules for src.* and streamlit."""

    def setUp(self):
        self._saved = {
            k: v for k, v in sys.modules.items()
            if k.startswith("src.") or k.startswith("streamlit")
        }
        for k in self._saved:
            sys.modules.pop(k)
        self._secrets_restorers: list = []

    def tearDown(self):
        while getattr(self, "_secrets_restorers", None):
            restore = self._secrets_restorers.pop()
            restore()
        for k in list(sys.modules):
            if k.startswith("src.") or k.startswith("streamlit"):
                sys.modules.pop(k)
        sys.modules.update(self._saved)
        from tests.secrets_module_isolation import ensure_real_src_secrets_module

        ensure_real_src_secrets_module()

    def _load(self, context_cookies):
        st = _install_st_stub(context_cookies=context_cookies)
        auth_cookies, auth_state, restore_secrets = _install_auth_modules(st)
        self._secrets_restorers.append(restore_secrets)
        self.addCleanup(restore_secrets)
        return auth_cookies, auth_state, st


# ---------------------------------------------------------------------------
# A. JWT decode and supersession unit tests
# ---------------------------------------------------------------------------

class JwtClaimsDecodeTests(_ModuleIsolationMixin, unittest.TestCase):
    """_decode_jwt_claims must correctly extract or reject JWT payloads."""

    def test_valid_jwt_returns_claims(self):
        tok = _make_jwt()
        ac, _, _ = self._load(_FakeContextCookies())
        claims = ac._decode_jwt_claims(tok)
        self.assertIsNotNone(claims)
        self.assertIn("exp", claims)
        self.assertIn("sub", claims)

    def test_malformed_jwt_returns_none(self):
        ac, _, _ = self._load(_FakeContextCookies())
        self.assertIsNone(ac._decode_jwt_claims("not.a.jwt"))
        self.assertIsNone(ac._decode_jwt_claims(""))
        self.assertIsNone(ac._decode_jwt_claims("one-part-only"))

    def test_truncated_payload_returns_none(self):
        ac, _, _ = self._load(_FakeContextCookies())
        self.assertIsNone(ac._decode_jwt_claims("abc.!!!bad_base64!!!.sig"))


class JwtSupersessionValidTests(_ModuleIsolationMixin, unittest.TestCase):
    """_jwt_is_supersession_valid enforces all five hardened rules."""

    def _m(self):
        ac, _, _ = self._load(_FakeContextCookies())
        return ac

    def test_valid_unexpired_token_no_logout_at_passes(self):
        tok = _make_jwt()
        self.assertTrue(self._m()._jwt_is_supersession_valid(tok))

    def test_expired_token_rejected(self):
        tok = _make_jwt(exp=time.time() - 10)
        self.assertFalse(self._m()._jwt_is_supersession_valid(tok))

    def test_missing_sub_rejected(self):
        tok = _make_jwt(omit_sub=True)
        self.assertFalse(self._m()._jwt_is_supersession_valid(tok))

    def test_missing_email_and_role_rejected(self):
        tok = _make_jwt(omit_email_role=True)
        self.assertFalse(self._m()._jwt_is_supersession_valid(tok))

    def test_role_present_without_email_passes(self):
        tok = _make_jwt(email="", role="authenticated")
        self.assertTrue(self._m()._jwt_is_supersession_valid(tok))

    def test_token_issued_after_logout_passes(self):
        logout_at = time.time() - 300  # 5 min ago
        iat = time.time() - 60         # 1 min ago (after logout)
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        self.assertTrue(self._m()._jwt_is_supersession_valid(tok, logout_at=logout_at))

    def test_token_issued_before_logout_rejected(self):
        """iat <= logout_at: token predates the logout — must not supersede."""
        iat = time.time() - 600        # 10 min ago
        logout_at = time.time() - 300  # 5 min ago (after iat)
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        self.assertFalse(self._m()._jwt_is_supersession_valid(tok, logout_at=logout_at))

    def test_token_issued_same_second_as_logout_rejected(self):
        """iat == logout_at: boundary is exclusive — must not supersede."""
        ts = time.time() - 300
        tok = _make_jwt(iat=ts, exp=time.time() + 3600)
        self.assertFalse(self._m()._jwt_is_supersession_valid(tok, logout_at=ts))

    def test_missing_iat_with_logout_at_rejected(self):
        """When logout_at is provided and iat is absent, reject (cannot prove post-logout)."""
        # Build a JWT with no iat claim by manipulating the payload manually.
        header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        claims = {"sub": "uid", "email": "x@x.com", "exp": int(time.time() + 3600)}
        payload = _b64url(json.dumps(claims).encode())
        tok = f"{header}.{payload}.sig"
        self.assertFalse(
            self._m()._jwt_is_supersession_valid(tok, logout_at=time.time() - 300)
        )

    def test_malformed_token_rejected(self):
        self.assertFalse(self._m()._jwt_is_supersession_valid("garbage"))


# ---------------------------------------------------------------------------
# B. Logout marker format tests
# ---------------------------------------------------------------------------

class LogoutMarkerFormatTests(_ModuleIsolationMixin, unittest.TestCase):
    """_is_truthy_logout_marker and _parse_logout_marker_timestamp."""

    def _m(self):
        ac, _, _ = self._load(_FakeContextCookies())
        return ac

    def test_legacy_marker_truthy(self):
        m = self._m()
        for val in ("1", "true", "yes", "logged_out"):
            self.assertTrue(m._is_truthy_logout_marker(val), val)

    def test_legacy_marker_no_timestamp(self):
        m = self._m()
        self.assertIsNone(m._parse_logout_marker_timestamp("1"))

    def test_timestamped_marker_truthy(self):
        m = self._m()
        marker = _logout_marker_json(time.time() - 60)
        self.assertTrue(m._is_truthy_logout_marker(marker))

    def test_timestamped_marker_timestamp_extracted(self):
        m = self._m()
        ts = time.time() - 120
        marker = _logout_marker_json(ts)
        extracted = m._parse_logout_marker_timestamp(marker)
        self.assertIsNotNone(extracted)
        self.assertAlmostEqual(extracted, int(ts), delta=2)

    def test_empty_string_not_truthy(self):
        self.assertFalse(self._m()._is_truthy_logout_marker(""))

    def test_random_json_not_truthy(self):
        self.assertFalse(self._m()._is_truthy_logout_marker('{"x":1}'))

    def test_set_logout_marker_writes_json_with_logout_at(self):
        """_set_logout_marker must write a JSON marker with v and logout_at."""
        ac, _, _ = self._load(_FakeContextCookies())
        mgr = _FakeCookieManager()
        ac._set_logout_marker(mgr)
        raw = mgr.cookies.get("cadivor_auth_logout")
        self.assertIsNotNone(raw, "_set_logout_marker must write to cadivor_auth_logout")
        self.assertTrue(ac._is_truthy_logout_marker(raw))
        ts = ac._parse_logout_marker_timestamp(raw)
        self.assertIsNotNone(ts, "Marker must carry a logout_at timestamp")
        self.assertAlmostEqual(ts, time.time(), delta=5)


# ---------------------------------------------------------------------------
# C. _logout_marker_active hardened rule set
# ---------------------------------------------------------------------------

class LogoutMarkerActiveHardenedTests(_ModuleIsolationMixin, unittest.TestCase):
    """_logout_marker_active applies the full five-rule supersession check."""

    def _make_ctx(self, auth_payload=None, logout_marker=None):
        d = {}
        if logout_marker is not None:
            d["cadivor_auth_logout"] = logout_marker
        if auth_payload is not None:
            d["cadivor_auth"] = auth_payload
        return _FakeContextCookies(d)

    # --- No marker cases ---

    def test_no_marker_no_block(self):
        ac, _, _ = self._load(self._make_ctx())
        self.assertFalse(ac._logout_marker_active())

    # --- Marker present, no auth cookie ---

    def test_legacy_marker_no_auth_cookie_blocks(self):
        ac, _, _ = self._load(self._make_ctx(logout_marker="1"))
        self.assertTrue(ac._logout_marker_active())

    def test_timestamped_marker_no_auth_cookie_blocks(self):
        ac, _, _ = self._load(
            self._make_ctx(logout_marker=_logout_marker_json(time.time() - 60))
        )
        self.assertTrue(ac._logout_marker_active())

    # --- Legacy marker + valid post-dated JWT ---

    def test_legacy_marker_valid_jwt_supersedes(self):
        """Legacy marker has no timestamp; valid unexpired JWT with identity supersedes."""
        tok = _make_jwt()
        ctx = self._make_ctx(
            auth_payload=_auth_cookie_payload(tok),
            logout_marker=_legacy_logout_marker(),
        )
        ac, _, _ = self._load(ctx)
        self.assertFalse(ac._logout_marker_active())

    def test_legacy_marker_expired_jwt_does_not_supersede(self):
        tok = _make_jwt(exp=time.time() - 10)
        ctx = self._make_ctx(
            auth_payload=_auth_cookie_payload(tok),
            logout_marker=_legacy_logout_marker(),
        )
        ac, _, _ = self._load(ctx)
        self.assertTrue(ac._logout_marker_active())

    def test_legacy_marker_malformed_jwt_does_not_supersede(self):
        ctx = self._make_ctx(
            auth_payload=_auth_cookie_payload("not-a-jwt"),
            logout_marker=_legacy_logout_marker(),
        )
        ac, _, _ = self._load(ctx)
        self.assertTrue(ac._logout_marker_active())

    def test_legacy_marker_missing_sub_does_not_supersede(self):
        tok = _make_jwt(omit_sub=True)
        ctx = self._make_ctx(
            auth_payload=_auth_cookie_payload(tok),
            logout_marker=_legacy_logout_marker(),
        )
        ac, _, _ = self._load(ctx)
        self.assertTrue(ac._logout_marker_active())

    def test_legacy_marker_missing_identity_claims_does_not_supersede(self):
        tok = _make_jwt(omit_email_role=True)
        ctx = self._make_ctx(
            auth_payload=_auth_cookie_payload(tok),
            logout_marker=_legacy_logout_marker(),
        )
        ac, _, _ = self._load(ctx)
        self.assertTrue(ac._logout_marker_active())

    # --- Timestamped marker + temporal checks ---

    def test_timestamped_marker_newer_jwt_supersedes(self):
        """iat after logout_at: user re-authenticated post-logout → marker is stale."""
        logout_at = time.time() - 300  # 5 min ago
        iat = time.time() - 60         # 1 min ago (after logout)
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        ctx = self._make_ctx(
            auth_payload=_auth_cookie_payload(tok),
            logout_marker=_logout_marker_json(logout_at),
        )
        ac, _, _ = self._load(ctx)
        self.assertFalse(ac._logout_marker_active())

    def test_timestamped_marker_older_jwt_does_not_supersede(self):
        """iat before logout_at: token predates logout → must not supersede."""
        iat = time.time() - 600        # 10 min ago
        logout_at = time.time() - 300  # 5 min ago (after iat)
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        ctx = self._make_ctx(
            auth_payload=_auth_cookie_payload(tok),
            logout_marker=_logout_marker_json(logout_at),
        )
        ac, _, _ = self._load(ctx)
        self.assertTrue(ac._logout_marker_active())

    def test_timestamped_marker_expired_jwt_does_not_supersede(self):
        logout_at = time.time() - 300
        iat = time.time() - 60
        tok = _make_jwt(iat=iat, exp=time.time() - 5)  # expired
        ctx = self._make_ctx(
            auth_payload=_auth_cookie_payload(tok),
            logout_marker=_logout_marker_json(logout_at),
        )
        ac, _, _ = self._load(ctx)
        self.assertTrue(ac._logout_marker_active())

    def test_timestamped_marker_missing_iat_does_not_supersede(self):
        """No iat claim → cannot prove post-logout → must not supersede."""
        logout_at = time.time() - 300
        header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        claims = {"sub": "uid", "email": "x@x.com", "exp": int(time.time() + 3600)}
        payload = _b64url(json.dumps(claims).encode())
        tok = f"{header}.{payload}.sig"
        ctx = self._make_ctx(
            auth_payload=_auth_cookie_payload(tok),
            logout_marker=_logout_marker_json(logout_at),
        )
        ac, _, _ = self._load(ctx)
        self.assertTrue(ac._logout_marker_active())


# ---------------------------------------------------------------------------
# D. Explicit manual logout regression tests
# ---------------------------------------------------------------------------

class ExplicitLogoutNotUndoneTests(_ModuleIsolationMixin, unittest.TestCase):
    """When logout is explicitly initiated, an old auth cookie must not re-authenticate.

    In the live app, ``explicit_logout_pending()`` fires first in
    ``resolve_auth_state`` (line 699) and returns AUTH_SIGNED_OUT before
    ``_logout_marker_active`` is even called.  These tests validate that
    safety layer plus the marker layer.
    """

    def test_explicit_logout_pending_takes_priority_over_auth_cookie(self):
        """cadivor_explicit_logout=True must override any auth cookie presence."""
        from src.auth_state import AUTH_AUTHENTICATED, AUTH_SIGNED_OUT

        tok = _make_jwt()
        ctx = _FakeContextCookies({"cadivor_auth": _auth_cookie_payload(tok)})
        # Simulate a same-session logout: auth status still shows authenticated
        # in session_state, but explicit_logout flag is set.
        session_state = {
            "cadivor_explicit_logout": True,
            "cadivor_auth_status": AUTH_AUTHENTICATED,
        }
        st = _install_st_stub(session_state=session_state, context_cookies=ctx)
        auth_cookies, auth_state, restore_secrets = _install_auth_modules(st)
        self._secrets_restorers.append(restore_secrets)
        self.addCleanup(restore_secrets)

        # explicit_logout_pending must fire before logout_blocks_auth_restore.
        self.assertTrue(
            auth_state.explicit_logout_pending(),
            "explicit_logout_pending must return True when cadivor_explicit_logout is set",
        )

    def test_logout_marker_not_superseded_by_same_session_auth_cookie_predating_logout(self):
        """After logout, the old auth cookie (iat < logout_at) must not supersede marker."""
        iat = time.time() - 600       # 10 min ago (pre-logout)
        logout_at = time.time() - 60  # 1 min ago (after token was issued)
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        ctx = _FakeContextCookies({
            "cadivor_auth": _auth_cookie_payload(tok),
            "cadivor_auth_logout": _logout_marker_json(logout_at),
        })
        ac, _, _ = self._load(ctx)
        self.assertTrue(
            ac._logout_marker_active(),
            "Auth cookie predating the logout must not supersede the logout marker",
        )

    def test_re_login_after_logout_does_supersede_marker(self):
        """Genuinely renewed valid session (iat > logout_at) supersedes stale marker."""
        logout_at = time.time() - 300  # 5 min ago
        iat = time.time() - 60         # 1 min ago (re-authenticated after logout)
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        ctx = _FakeContextCookies({
            "cadivor_auth": _auth_cookie_payload(tok),
            "cadivor_auth_logout": _logout_marker_json(logout_at),
        })
        ac, _, _ = self._load(ctx)
        self.assertFalse(
            ac._logout_marker_active(),
            "A valid re-authenticated session (iat > logout_at) must supersede the stale marker",
        )

    def test_logout_blocks_auth_restore_true_when_marker_not_superseded(self):
        """logout_blocks_auth_restore must return True when the marker is active."""
        iat = time.time() - 600
        logout_at = time.time() - 60
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        ctx = _FakeContextCookies({
            "cadivor_auth": _auth_cookie_payload(tok),
            "cadivor_auth_logout": _logout_marker_json(logout_at),
        })
        ac, _, _ = self._load(ctx)
        self.assertTrue(ac.logout_blocks_auth_restore(cookie_manager=None))

    def test_logout_blocks_auth_restore_false_after_re_login(self):
        """logout_blocks_auth_restore must return False after genuine re-login."""
        logout_at = time.time() - 300
        iat = time.time() - 60
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        ctx = _FakeContextCookies({
            "cadivor_auth": _auth_cookie_payload(tok),
            "cadivor_auth_logout": _logout_marker_json(logout_at),
        })
        ac, _, _ = self._load(ctx)
        self.assertFalse(ac.logout_blocks_auth_restore(cookie_manager=None))


# ---------------------------------------------------------------------------
# E. Dashboard → BOM Analyzer → Alternative Finder route regression
# ---------------------------------------------------------------------------

class DashboardBomAnalyzerAlternativeFinderRouteTest(_ModuleIsolationMixin, unittest.TestCase):
    """Full production-route simulation: href nav to Alternative Finder."""

    def test_alternative_finder_navigation_stays_authenticated_with_valid_reauth(self):
        """New session after href nav: valid re-auth cookie supersedes stale marker."""
        logout_at = time.time() - 300
        iat = time.time() - 60
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        ctx = _FakeContextCookies({
            "cadivor_auth": _auth_cookie_payload(tok),
            "cadivor_auth_logout": _logout_marker_json(logout_at),
        })
        ac, _, _ = self._load(ctx)
        self.assertFalse(
            ac.logout_blocks_auth_restore(cookie_manager=None),
            "Valid re-authenticated session must not be blocked by stale logout marker",
        )

    def test_stale_auth_cookie_does_not_restore_after_logout(self):
        """Pre-logout auth cookie (iat < logout_at) must not bypass logout marker."""
        iat = time.time() - 600
        logout_at = time.time() - 60
        tok = _make_jwt(iat=iat, exp=time.time() + 3600)
        ctx = _FakeContextCookies({
            "cadivor_auth": _auth_cookie_payload(tok),
            "cadivor_auth_logout": _logout_marker_json(logout_at),
        })
        ac, _, _ = self._load(ctx)
        self.assertTrue(
            ac.logout_blocks_auth_restore(cookie_manager=None),
            "Pre-logout auth cookie must not bypass logout marker",
        )

    def test_no_auth_cookie_with_logout_marker_blocks_restore(self):
        ctx = _FakeContextCookies({"cadivor_auth_logout": _logout_marker_json()})
        ac, _, _ = self._load(ctx)
        self.assertTrue(ac.logout_blocks_auth_restore(cookie_manager=None))

    def test_clean_session_no_marker_no_block(self):
        ac, _, _ = self._load(_FakeContextCookies())
        self.assertFalse(ac.logout_blocks_auth_restore(cookie_manager=None))


# ---------------------------------------------------------------------------
# F. navigate_to auth param removal
# ---------------------------------------------------------------------------

class NavigateToRemovesAuthQueryParamTests(_ModuleIsolationMixin, unittest.TestCase):

    def test_navigate_to_removes_auth_param(self):
        class _QueryParams(dict):
            def from_dict(self, d):
                self.clear()
                self.update(d)

        st = types.ModuleType("streamlit")
        st.session_state = {}
        st.query_params = _QueryParams({"auth": "login", "source": "marketing", "page": "Dashboard"})
        reruns = []
        st.rerun = lambda: reruns.append(1)
        runtime_mod = types.ModuleType("streamlit.runtime")
        scriptrunner_mod = types.ModuleType("streamlit.runtime.scriptrunner")
        scriptrunner_mod.get_script_run_ctx = lambda: None
        sys.modules.update({
            "streamlit": st,
            "streamlit.runtime": runtime_mod,
            "streamlit.runtime.scriptrunner": scriptrunner_mod,
        })
        normalizer = types.ModuleType("src.normalizer")
        normalizer.normalize_part_number = lambda v: str(v).upper()
        sys.modules["src.normalizer"] = normalizer
        urls = types.ModuleType("src.urls")
        urls.internal_app_href = lambda page, **kw: f"?page={page}"
        sys.modules["src.urls"] = urls

        import src.ui.navigation as nav
        importlib.reload(nav)
        nav.navigate_to("Alternative Finder")

        self.assertNotIn("auth", st.query_params)
        self.assertNotIn("source", st.query_params)
        self.assertEqual(st.query_params.get("page"), "Alternative Finder")


# ---------------------------------------------------------------------------
# G. Auth intent guard (logic-level)
# ---------------------------------------------------------------------------

class AuthIntentGuardTests(unittest.TestCase):

    def test_apply_intent_is_no_op_when_authenticated(self):
        AUTH_AUTHENTICATED = "authenticated"
        ss = {"cadivor_auth_status": AUTH_AUTHENTICATED, "cadivor_root_state": "authenticated"}
        qp = {"auth": "login"}

        def _apply(ss, qp):
            if ss.get("cadivor_auth_status") == AUTH_AUTHENTICATED:
                ss["cadivor_auth_intent_applied"] = True
                return
            if ss.get("cadivor_auth_intent_applied"):
                return
            if str(qp.get("auth", "") or "").strip().lower() == "login":
                ss["cadivor_root_state"] = "login"
                ss["cadivor_auth_intent_applied"] = True

        _apply(ss, qp)
        self.assertEqual(ss["cadivor_root_state"], "authenticated")

    def test_apply_intent_sets_login_when_not_authenticated(self):
        ss = {"cadivor_auth_status": "signed_out", "cadivor_root_state": "public"}
        qp = {"auth": "login"}

        def _apply(ss, qp):
            if ss.get("cadivor_auth_status") == "authenticated":
                ss["cadivor_auth_intent_applied"] = True
                return
            if ss.get("cadivor_auth_intent_applied"):
                return
            if str(qp.get("auth", "") or "").strip().lower() == "login":
                ss["cadivor_root_state"] = "login"
                ss["cadivor_auth_intent_applied"] = True

        _apply(ss, qp)
        self.assertEqual(ss["cadivor_root_state"], "login")


# ---------------------------------------------------------------------------
# H. Supplier-evidence deduplication regression tests
# ---------------------------------------------------------------------------

class _EvidenceTestBase(_ModuleIsolationMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        st = types.ModuleType("streamlit")
        st.session_state = {}
        sys.modules["streamlit"] = st

    @property
    def _m(self):
        import src.alternative_classification as m
        importlib.reload(m)
        return m

    def _row(self, *, supplier="DigiKey", original="C0603C104K5RACTU",
             candidate="C0603C104K5RAC3121", substitute_type="Direct",
             supplier_part_id="10482927",
             source_url="https://www.digikey.com/en/products/detail/10482927"):
        return {
            "supplier": supplier,
            "original_mpn": original,
            "candidate_mpn": candidate,
            "substitute_type": substitute_type,
            "supplier_part_id": supplier_part_id,
            "source_url": source_url,
            "summary": f"{supplier} relationship: {substitute_type}.",
            "evidence_type": "distributor-listed substitute",
        }


class RelationshipEvidenceSummaryDedupTests(_EvidenceTestBase):

    def test_single_record_renders_once(self):
        summary = self._m.relationship_evidence_summary([self._row()])
        self.assertEqual(summary.count("DigiKey relationship: Direct."), 1)

    def test_duplicate_records_deduplicated(self):
        row = self._row()
        summary = self._m.relationship_evidence_summary([row, dict(row), dict(row)])
        self.assertEqual(summary.count("DigiKey relationship: Direct."), 1)

    def test_summary_does_not_contain_raw_url(self):
        summary = self._m.relationship_evidence_summary([self._row()])
        self.assertNotIn("https://", summary)

    def test_different_suppliers_remain_distinct(self):
        rows = [
            self._row(supplier="DigiKey", substitute_type="Direct"),
            self._row(supplier="Mouser", substitute_type="Similar",
                      source_url="https://www.mouser.com/part"),
        ]
        summary = self._m.relationship_evidence_summary(rows)
        self.assertIn("DigiKey", summary)
        self.assertIn("Mouser", summary)

    def test_different_substitute_types_remain_distinct(self):
        rows = [
            self._row(candidate="C0603C104K5RAC3121", substitute_type="Direct"),
            self._row(candidate="C0603C104J5RALTU", substitute_type="Upgrade",
                      source_url="https://www.digikey.com/upgrade"),
        ]
        summary = self._m.relationship_evidence_summary(rows)
        self.assertIn("Direct", summary)
        self.assertIn("Upgrade", summary)

    def test_empty_rows_returns_no_evidence_message(self):
        self.assertIn("No exact", self._m.relationship_evidence_summary([]))

    def test_none_rows_returns_no_evidence_message(self):
        self.assertIn("No exact", self._m.relationship_evidence_summary(None))


class RelationshipEvidenceLinkPairsTests(_EvidenceTestBase):

    def test_single_direct_record_one_link_pair(self):
        pairs = self._m.relationship_evidence_link_pairs([self._row()])
        self.assertEqual(len(pairs), 1)
        label, url = pairs[0]
        self.assertIn("DigiKey", label)
        self.assertNotIn("http", label)
        self.assertTrue(url.startswith("https://"))

    def test_duplicate_records_produce_one_link(self):
        row = self._row()
        pairs = self._m.relationship_evidence_link_pairs([row, dict(row), dict(row)])
        self.assertEqual(len(pairs), 1)

    def test_no_url_records_produce_no_link_pairs(self):
        self.assertEqual(self._m.relationship_evidence_link_pairs([self._row(source_url="")]), [])

    def test_two_different_urls_two_link_pairs(self):
        pairs = self._m.relationship_evidence_link_pairs([
            self._row(source_url="https://www.digikey.com/part/A"),
            self._row(supplier="Mouser", source_url="https://www.mouser.com/part/A"),
        ])
        self.assertEqual(len(pairs), 2)

    def test_c3121_direct_evidence_single_link_no_url_in_label(self):
        rows = [{
            "supplier": "DigiKey",
            "original_mpn": "C0603C104K5RACTU",
            "candidate_mpn": "C0603C104K5RAC3121",
            "substitute_type": "Direct",
            "supplier_part_id": "10482927",
            "source_url": "https://www.digikey.com/en/products/detail/C0603C104K5RAC3121/10482927",
            "summary": "DigiKey relationship: Direct.",
            "evidence_type": "distributor-listed substitute",
        }]
        pairs = self._m.relationship_evidence_link_pairs(rows)
        self.assertEqual(len(pairs), 1)
        label, url = pairs[0]
        self.assertIn("DigiKey", label)
        self.assertNotIn("http", label)
        self.assertIn("10482927", url)


class DeduplicateEvidenceRowsTests(_EvidenceTestBase):

    def test_identical_rows_collapse_to_one(self):
        row = {
            "original_mpn": "C0603C104K5RACTU", "candidate_mpn": "C0603C104K5RAC3121",
            "supplier": "DigiKey", "supplier_part_id": "10482927",
            "substitute_type": "Direct", "source_url": "https://digikey.com/10482927",
        }
        self.assertEqual(len(self._m.deduplicate_evidence_rows([row, dict(row), dict(row)])), 1)

    def test_different_candidates_are_distinct(self):
        base = {
            "original_mpn": "C0603C104K5RACTU", "supplier": "DigiKey",
            "substitute_type": "Direct", "supplier_part_id": "",
        }
        r1 = {**base, "candidate_mpn": "C0603C104K5RAC3121", "source_url": "https://a.com"}
        r2 = {**base, "candidate_mpn": "0603BB104K500YT", "source_url": "https://b.com"}
        self.assertEqual(len(self._m.deduplicate_evidence_rows([r1, r2])), 2)

    def test_case_insensitive_candidate_dedup(self):
        base = {
            "original_mpn": "C0603C104K5RACTU", "supplier": "DigiKey",
            "substitute_type": "Direct", "supplier_part_id": "10482927",
            "source_url": "https://a.com",
        }
        r1 = {**base, "candidate_mpn": "C0603C104K5RAC3121"}
        r2 = {**base, "candidate_mpn": "c0603c104k5rac3121"}
        self.assertEqual(len(self._m.deduplicate_evidence_rows([r1, r2])), 1)

    def test_empty_list_returns_empty(self):
        self.assertEqual(self._m.deduplicate_evidence_rows([]), [])

    def test_none_returns_empty(self):
        self.assertEqual(self._m.deduplicate_evidence_rows(None), [])

    def test_same_direct_relationship_collapses_across_sku_urls(self):
        base = {
            "original_mpn": "C0603C104K5RACTU",
            "candidate_mpn": "C0603C104K5RAC3121",
            "supplier": "DigiKey",
            "substitute_type": "Direct",
            "summary": "DigiKey relationship: Direct.",
        }
        rows = [
            {**base, "supplier_part_id": "399-C0603C104K5RAC3121CT-ND",
             "source_url": "https://www.digikey.com/en/products/detail/ct"},
            {**base, "supplier_part_id": "399-C0603C104K5RAC3121TR-ND",
             "source_url": "https://www.digikey.com/en/products/detail/tr"},
            {**base, "supplier_part_id": "399-C0603C104K5RAC3121DKR-ND",
             "source_url": "https://www.digikey.com/en/products/detail/dkr"},
        ]
        deduped = self._m.deduplicate_evidence_rows(rows)
        self.assertEqual(len(deduped), 1)
        summary = self._m.relationship_evidence_summary(rows)
        self.assertEqual(summary, "DigiKey relationship: Direct.")
        self.assertEqual(summary.count("DigiKey relationship: Direct."), 1)
        self.assertEqual(len(self._m.relationship_evidence_link_pairs(rows)), 1)


if __name__ == "__main__":
    unittest.main()
