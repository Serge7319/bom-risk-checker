"""Browser-persistent Supabase session cookies for Cadivor.

Persists the minimum credentials required to restore authentication across new
Streamlit server sessions. Never logs token values or passwords.

Limitation: extra-streamlit-components CookieManager sets cookies via a Streamlit
component iframe (document.cookie). These are NOT HttpOnly and are readable by
page JavaScript in the browser. Minimize exposure by keeping cookie Path=/,
Secure on HTTPS hosts, and clearing on logout.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

from src.auth_state import coerce_cookie
from src.secrets import get_secret_bool

AUTH_COOKIE_NAME = "cadivor_auth"
AUTH_LOGOUT_COOKIE_NAME = "cadivor_auth_logout"
AUTH_COOKIE_LEGACY_NAME = "bom_auth"
_AUTH_COOKIE_MANAGER_KEY = "_cadivor_auth_cookie_manager_widget"
_MAX_HYDRATION_ATTEMPTS = 6
_COOKIE_TTL_DAYS = 7


def log_auth_restore(event: str, **details: Any) -> None:
    """Emit safe restoration state names to stdout (never secrets)."""
    safe = {str(key): str(value) for key, value in details.items()}
    parts = " ".join(f"{key}={value}" for key, value in sorted(safe.items()))
    line = f"AUTH_RESTORE {event}"
    if parts:
        line = f"{line} {parts}"
    print(line, flush=True)


def log_auth_cookie(event: str, **details: Any) -> None:
    """Emit safe auth-cookie diagnostics to stdout (never secrets)."""
    safe = {str(key): str(value) for key, value in details.items()}
    parts = " ".join(f"{key}={value}" for key, value in sorted(safe.items()))
    line = f"AUTH_COOKIE {event}"
    if parts:
        line = f"{line} {parts}"
    print(line, flush=True)

try:
    import extra_streamlit_components as stx
except Exception:
    stx = None


def auth_cookies_enabled() -> bool:
    """Allow disabling browser auth persistence (local tests only)."""
    return get_secret_bool("CADIVOR_AUTH_COOKIE_ENABLED", default=True)


def cookie_secure_flag() -> bool:
    """Use Secure cookies on HTTPS production hosts."""
    return get_secret_bool("CADIVOR_COOKIE_SECURE", default=True)


def get_auth_cookie_manager() -> Any | None:
    """Return one auth CookieManager widget for this Streamlit session (not cached)."""
    if not auth_cookies_enabled() or stx is None:
        return None
    if _AUTH_COOKIE_MANAGER_KEY not in st.session_state:
        try:
            st.session_state[_AUTH_COOKIE_MANAGER_KEY] = stx.CookieManager(
                key="cadivor_auth_cookie_manager",
            )
        except Exception:
            st.session_state[_AUTH_COOKIE_MANAGER_KEY] = None
    return st.session_state.get(_AUTH_COOKIE_MANAGER_KEY)


def _read_raw_auth_cookie(cookie_manager: Any) -> Any:
    if cookie_manager is None:
        log_auth_cookie("read_present", present=False)
        return None
    for name in (AUTH_COOKIE_NAME, AUTH_COOKIE_LEGACY_NAME):
        try:
            raw = cookie_manager.get(cookie=name)
            if raw is not None:
                log_auth_cookie("read_present", present=True, cookie_name=name)
                return raw
        except Exception:
            continue
    log_auth_cookie("read_present", present=False)
    return None


def _serialize_auth_cookie_payload(access_token: str, refresh_token: str) -> str:
    """Serialize the minimum Supabase restore payload for CookieManager.set()."""
    payload = {
        "access_token": str(access_token),
        "refresh_token": str(refresh_token),
    }
    return json.dumps(payload, separators=(",", ":"))


def _logout_marker_active(cookie_manager: Any) -> bool:
    if cookie_manager is None:
        return False
    try:
        raw = cookie_manager.get(cookie=AUTH_LOGOUT_COOKIE_NAME)
    except Exception:
        return False
    if raw is None:
        return False
    text = str(raw).strip().lower()
    return text in {"1", "true", "yes", "logged_out"}


def _set_logout_marker(cookie_manager: Any) -> None:
    if cookie_manager is None:
        return
    try:
        cookie_manager.set(
            cookie=AUTH_LOGOUT_COOKIE_NAME,
            val="1",
            key="cadivor_set_auth_logout_marker",
            path="/",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            secure=cookie_secure_flag() or None,
        )
    except TypeError:
        try:
            cookie_manager.set(
                cookie=AUTH_LOGOUT_COOKIE_NAME,
                val="1",
                key="cadivor_set_auth_logout_marker",
            )
        except Exception:
            pass
    except Exception:
        pass


def _clear_logout_marker(cookie_manager: Any) -> None:
    if cookie_manager is None:
        return
    try:
        cookie_manager.delete(cookie=AUTH_LOGOUT_COOKIE_NAME, key="cadivor_delete_logout_marker")
    except Exception:
        pass
    try:
        cookie_manager.set(
            cookie=AUTH_LOGOUT_COOKIE_NAME,
            val="",
            key="cadivor_clear_logout_marker",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    except Exception:
        pass


def parse_auth_cookie(raw: Any) -> dict[str, str] | None:
    """Return access/refresh tokens from a cookie payload without logging values."""
    parsed = coerce_cookie(raw)
    if not isinstance(parsed, dict):
        return None
    access_token = str(parsed.get("access_token") or "").strip()
    refresh_token = str(parsed.get("refresh_token") or "").strip()
    if not access_token or not refresh_token:
        return None
    return {"access_token": access_token, "refresh_token": refresh_token}


def hydrate_session_from_auth_cookie(cookie_manager: Any) -> bool:
    """Load tokens from the browser cookie into session_state when missing.

    Returns True when tokens were copied into session_state on this call.
    """
    if cookie_manager is None or not auth_cookies_enabled():
        return False
    if st.session_state.get("access_token") and st.session_state.get("refresh_token"):
        return False
    if st.session_state.get("cadivor_force_signed_out") or st.session_state.get(
        "cadivor_explicit_logout"
    ):
        return False
    if _logout_marker_active(cookie_manager):
        st.session_state["cadivor_auth_cookie_absent"] = True
        return False

    raw = _read_raw_auth_cookie(cookie_manager)
    if raw is None:
        log_auth_cookie("parse_valid", valid=False)
        return False

    tokens = parse_auth_cookie(raw)
    log_auth_cookie("parse_valid", valid=tokens is not None)
    if tokens is None:
        st.session_state["cadivor_auth_cookie_absent"] = True
        return False

    st.session_state["access_token"] = tokens["access_token"]
    st.session_state["refresh_token"] = tokens["refresh_token"]
    st.session_state.pop("cadivor_auth_cookie_absent", None)
    st.session_state["cadivor_auth_restore_attempts"] = 0
    return True


def auth_cookie_hydration_pending(cookie_manager: Any) -> bool:
    """True while CookieManager may still be loading the auth cookie."""
    if cookie_manager is None or not auth_cookies_enabled():
        return False
    if st.session_state.get("cadivor_force_signed_out") or st.session_state.get(
        "cadivor_explicit_logout"
    ):
        return False
    if _logout_marker_active(cookie_manager):
        return False
    if st.session_state.get("user") is not None:
        return False
    if st.session_state.get("access_token") and st.session_state.get("refresh_token"):
        return False
    if st.session_state.get("cadivor_auth_cookie_absent"):
        return False

    attempts = int(st.session_state.get("cadivor_auth_restore_attempts") or 0)
    if attempts >= _MAX_HYDRATION_ATTEMPTS:
        return False

    raw = _read_raw_auth_cookie(cookie_manager)
    if raw is not None and parse_auth_cookie(raw) is None:
        return False
    return raw is None


def finalize_auth_cookie_hydration_timeout(cookie_manager: Any) -> None:
    """Mark cookie hydration complete with no credential (fail-closed)."""
    st.session_state["cadivor_auth_cookie_absent"] = True
    st.session_state["cadivor_auth_restore_attempts"] = _MAX_HYDRATION_ATTEMPTS
    log_auth_restore(
        "fallback_signed_out",
        reason="hydration_timeout",
        cookie_manager_ready=cookie_manager is not None,
    )


def record_auth_hydration_attempt() -> int:
    attempts = int(st.session_state.get("cadivor_auth_restore_attempts") or 0) + 1
    st.session_state["cadivor_auth_restore_attempts"] = attempts
    return attempts


def persist_session_auth_cookie(cookie_manager: Any) -> None:
    """Write current Supabase tokens to the browser auth cookie."""
    if cookie_manager is None or not auth_cookies_enabled():
        return
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if not access_token or not refresh_token:
        return
    if not st.session_state.get("user"):
        return

    serialized = _serialize_auth_cookie_payload(
        str(access_token),
        str(refresh_token),
    )
    expires_at = datetime.now(timezone.utc) + timedelta(days=_COOKIE_TTL_DAYS)
    set_kwargs: dict[str, Any] = {
        "cookie": AUTH_COOKIE_NAME,
        "val": serialized,
        "key": "cadivor_persist_auth_cookie",
        "path": "/",
        "expires_at": expires_at,
        "same_site": "lax",
    }
    if cookie_secure_flag():
        set_kwargs["secure"] = True

    log_auth_cookie("write_requested", cookie_name=AUTH_COOKIE_NAME)
    try:
        cookie_manager.set(**set_kwargs)
    except TypeError:
        try:
            cookie_manager.set(
                cookie=AUTH_COOKIE_NAME,
                val=serialized,
                expires_at=expires_at,
                key="cadivor_persist_auth_cookie",
            )
        except Exception as fallback_exc:
            log_auth_cookie("write_failed", exception_type=type(fallback_exc).__name__)
            return
    except Exception as exc:
        log_auth_cookie("write_failed", exception_type=type(exc).__name__)
        return
    log_auth_cookie("write_succeeded", cookie_name=AUTH_COOKIE_NAME)
    _clear_logout_marker(cookie_manager)


def clear_auth_cookie(cookie_manager: Any) -> None:
    """Remove durable browser auth so future Streamlit sessions stay signed out."""
    if cookie_manager is None:
        return
    st.session_state["cadivor_auth_cookie_absent"] = True
    _set_logout_marker(cookie_manager)
    for name in (AUTH_COOKIE_NAME, AUTH_COOKIE_LEGACY_NAME):
        try:
            cookie_manager.delete(cookie=name, key=f"cadivor_delete_auth_cookie_{name}")
        except Exception:
            pass
        try:
            cookie_manager.set(
                cookie=name,
                val="",
                key=f"cadivor_clear_auth_cookie_{name}",
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        except Exception:
            pass


def logout_blocks_auth_restore(cookie_manager: Any) -> bool:
    """True when an explicit browser logout marker prevents session restoration."""
    return _logout_marker_active(cookie_manager)


def invalidate_corrupt_auth_cookie(cookie_manager: Any, *, reason: str) -> None:
    """Drop invalid cookie data and record a safe diagnostic reason."""
    from src.auth_state import log_auth_diagnostic

    log_auth_diagnostic("auth_cookie_invalid", reason=reason)
    clear_auth_cookie(cookie_manager)
