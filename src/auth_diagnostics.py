"""Safe correlation diagnostics for authentication bounce forensics (Sprint 71.9.3A).

Emits structured AUTH_CORRELATE and AUTH_BOUNCE logs for production forensics.
Read-only with respect to authentication decisions — never logs secrets or PII.
"""
from __future__ import annotations

import hashlib
from typing import Any

import streamlit as st

_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "access_token",
        "refresh_token",
        "password",
        "api_key",
        "email",
        "cookie",
        "cookie_value",
        "val",
        "user",
        "session_id",
    }
)


def hash_session_id(session_id: str | None = None) -> str:
    """Return a stable 8-character non-secret hash of the Streamlit session ID."""
    raw = session_id if session_id is not None else _raw_session_id()
    if not raw:
        return "unknown"
    digest = hashlib.sha256(str(raw).encode("utf-8")).hexdigest()
    return digest[:8]


def _raw_session_id() -> str | None:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is None:
            return None
        session_id = getattr(ctx, "session_id", None)
        return str(session_id) if session_id is not None else None
    except Exception:
        return None


def current_script_run_id() -> str | None:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is None:
            return None
        run_id = getattr(ctx, "script_run_id", None)
        return str(run_id) if run_id is not None else str(id(ctx))
    except Exception:
        return None


def _cookie_present(cookie_manager: Any) -> bool:
    try:
        from src.auth_cookies import read_auth_cookie_tokens

        return read_auth_cookie_tokens(cookie_manager) is not None
    except Exception:
        return False


def _cookie_source(cookie_manager: Any = None) -> str:
    """Return the auth cookie read source without logging credentials."""
    try:
        from src.auth_cookies import read_auth_cookie_tokens_with_source

        _tokens, source = read_auth_cookie_tokens_with_source(cookie_manager)
        return str(source or "none")
    except Exception:
        return "unknown"


def _logout_marker_active(cookie_manager: Any = None) -> bool:
    """Return True when the browser logout suppression marker is active."""
    try:
        from src.auth_cookies import _logout_marker_active

        return bool(_logout_marker_active(cookie_manager))
    except Exception:
        return False


def _hydration_pending(cookie_manager: Any) -> bool:
    try:
        from src.auth_cookies import (
            auth_cookie_hydration_pending,
            manager_fallback_hydration_pending,
        )

        return bool(auth_cookie_hydration_pending(cookie_manager)) or bool(
            manager_fallback_hydration_pending(cookie_manager)
        )
    except Exception:
        return False


def _request_origin() -> str:
    """Return the current request hostname/origin when Streamlit exposes it safely."""
    try:
        context = getattr(st, "context", None)
        if context is None:
            return "unknown"
        headers = getattr(context, "headers", None)
        if headers is not None:
            host = headers.get("Host") or headers.get("host")
            if host:
                return str(host).split(",")[0].strip()[:120]
        url = getattr(context, "url", None)
        if url:
            from urllib.parse import urlparse

            parsed = urlparse(str(url))
            if parsed.netloc:
                return parsed.netloc[:120]
            if parsed.scheme and parsed.path:
                return f"{parsed.scheme}://{parsed.netloc or 'unknown'}"[:120]
    except Exception:
        pass
    return "unknown"


def _current_auth_status(auth_status: str | None = None) -> str:
    if auth_status is not None:
        return str(auth_status)
    return str(st.session_state.get("cadivor_auth_status") or "unknown")


def build_auth_correlation_fields(
    *,
    cookie_manager: Any = None,
    auth_status_in: str | None = None,
    transition_reason: str = "",
    cookie_source: str | None = None,
) -> dict[str, str]:
    status = _current_auth_status(auth_status_in)
    resolved_cookie_source = (
        str(cookie_source) if cookie_source is not None else _cookie_source(cookie_manager)
    )
    return {
        "session_hash": hash_session_id(),
        "script_run_id": str(current_script_run_id() or "unknown"),
        "auth_status_in": status,
        "has_user": str(bool(st.session_state.get("user") is not None)),
        "has_access_token": str(bool(st.session_state.get("access_token"))),
        "has_refresh_token": str(bool(st.session_state.get("refresh_token"))),
        "cookie_source": resolved_cookie_source,
        "cookie_present": str(_cookie_present(cookie_manager)),
        "cookie_absent_flag": str(bool(st.session_state.get("cadivor_auth_cookie_absent"))),
        "logout_marker_active": str(_logout_marker_active(cookie_manager)),
        "hydration_pending": str(_hydration_pending(cookie_manager)),
        "force_signed_out": str(bool(st.session_state.get("cadivor_force_signed_out"))),
        "request_origin": _request_origin(),
        "transition_reason": str(transition_reason or ""),
    }


def build_auth_bounce_fields(
    *,
    cookie_manager: Any = None,
    auth_status: str | None = None,
    transition_reason: str = "",
    cookie_source: str | None = None,
) -> dict[str, str]:
    """Build shared AUTH_BOUNCE field set for bounce-proof instrumentation."""
    status = _current_auth_status(auth_status)
    resolved_cookie_source = (
        str(cookie_source) if cookie_source is not None else _cookie_source(cookie_manager)
    )
    return {
        "session_hash": hash_session_id(),
        "script_run_id": str(current_script_run_id() or "unknown"),
        "cookie_source": resolved_cookie_source,
        "cookie_present": str(_cookie_present(cookie_manager)),
        "cookie_absent_flag": str(bool(st.session_state.get("cadivor_auth_cookie_absent"))),
        "logout_marker_active": str(_logout_marker_active(cookie_manager)),
        "has_user": str(bool(st.session_state.get("user") is not None)),
        "has_access_token": str(bool(st.session_state.get("access_token"))),
        "has_refresh_token": str(bool(st.session_state.get("refresh_token"))),
        "auth_status": status,
        "force_signed_out": str(bool(st.session_state.get("cadivor_force_signed_out"))),
        "hydration_pending": str(_hydration_pending(cookie_manager)),
        "request_origin": _request_origin(),
        "transition_reason": str(transition_reason or ""),
    }


def _validate_diagnostic_fields(fields: dict[str, str]) -> None:
    for key in fields:
        if key in _FORBIDDEN_FIELD_NAMES:
            raise ValueError(f"forbidden diagnostic field: {key}")


def _emit_diagnostic_line(prefix: str, label: str, fields: dict[str, str]) -> None:
    _validate_diagnostic_fields(fields)
    safe_label = str(label).replace(" ", "_")
    parts = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    print(f"{prefix} {safe_label} {parts}", flush=True)


def log_auth_correlation(
    checkpoint: str,
    *,
    cookie_manager: Any = None,
    auth_status_in: str | None = None,
    transition_reason: str = "",
    cookie_source: str | None = None,
) -> None:
    """Emit one correlated AUTH_CORRELATE line to stdout (never secrets)."""
    fields = build_auth_correlation_fields(
        cookie_manager=cookie_manager,
        auth_status_in=auth_status_in,
        transition_reason=transition_reason,
        cookie_source=cookie_source,
    )
    _emit_diagnostic_line("AUTH_CORRELATE", f"checkpoint={checkpoint}", fields)


def log_auth_bounce(
    event: str,
    *,
    cookie_manager: Any = None,
    auth_status: str | None = None,
    transition_reason: str = "",
    cookie_source: str | None = None,
) -> None:
    """Emit one AUTH_BOUNCE line for login/runtime transition forensics."""
    fields = build_auth_bounce_fields(
        cookie_manager=cookie_manager,
        auth_status=auth_status,
        transition_reason=transition_reason,
        cookie_source=cookie_source,
    )
    _emit_diagnostic_line("AUTH_BOUNCE", event, fields)
