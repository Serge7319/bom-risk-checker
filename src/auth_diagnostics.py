"""Safe correlation diagnostics for authentication bounce forensics (Sprint 71.9.3A).

Emits structured AUTH_CORRELATE logs for production forensics. Read-only with
respect to authentication decisions — never logs secrets or PII.
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
        from src.auth_cookies import _read_raw_auth_cookie

        return _read_raw_auth_cookie(cookie_manager) is not None
    except Exception:
        return False


def _hydration_pending(cookie_manager: Any) -> bool:
    try:
        from src.auth_cookies import auth_cookie_hydration_pending

        return bool(auth_cookie_hydration_pending(cookie_manager))
    except Exception:
        return False


def build_auth_correlation_fields(
    *,
    cookie_manager: Any = None,
    auth_status_in: str | None = None,
    transition_reason: str = "",
) -> dict[str, str]:
    status = auth_status_in
    if status is None:
        status = str(st.session_state.get("cadivor_auth_status") or "unknown")
    return {
        "session_hash": hash_session_id(),
        "script_run_id": str(current_script_run_id() or "unknown"),
        "auth_status_in": str(status),
        "has_user": str(bool(st.session_state.get("user") is not None)),
        "has_access_token": str(bool(st.session_state.get("access_token"))),
        "has_refresh_token": str(bool(st.session_state.get("refresh_token"))),
        "cookie_present": str(_cookie_present(cookie_manager)),
        "cookie_absent_flag": str(bool(st.session_state.get("cadivor_auth_cookie_absent"))),
        "hydration_pending": str(_hydration_pending(cookie_manager)),
        "force_signed_out": str(bool(st.session_state.get("cadivor_force_signed_out"))),
        "transition_reason": str(transition_reason or ""),
    }


def log_auth_correlation(
    checkpoint: str,
    *,
    cookie_manager: Any = None,
    auth_status_in: str | None = None,
    transition_reason: str = "",
) -> None:
    """Emit one correlated AUTH_CORRELATE line to stdout (never secrets)."""
    fields = build_auth_correlation_fields(
        cookie_manager=cookie_manager,
        auth_status_in=auth_status_in,
        transition_reason=transition_reason,
    )
    for key in fields:
        if key in _FORBIDDEN_FIELD_NAMES:
            raise ValueError(f"forbidden diagnostic field: {key}")
    safe_checkpoint = str(checkpoint).replace(" ", "_")
    parts = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    print(f"AUTH_CORRELATE checkpoint={safe_checkpoint} {parts}", flush=True)
