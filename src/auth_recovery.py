"""Supabase-native password recovery for Cadivor."""
from __future__ import annotations

import os
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from src.auth_state import APP_LOGIN, APP_PASSWORD_RECOVERY, APP_PASSWORD_RESET, log_auth_diagnostic

_RECOVERY_ACTIVE_KEY = "cadivor_password_recovery_active"
_RECOVERY_ERROR_KEY = "cadivor_password_recovery_error"
_RECOVERY_NOTICE_KEY = "cadivor_password_recovery_notice"
_RECOVERY_APPLIED_KEY = "cadivor_password_recovery_query_applied"
_HASH_BRIDGE_RUN_KEY = "cadivor_password_recovery_hash_bridge_run"


def password_recovery_active() -> bool:
    return bool(st.session_state.get(_RECOVERY_ACTIVE_KEY))


def password_reset_request_active() -> bool:
    return str(st.session_state.get("cadivor_root_state") or "") == APP_PASSWORD_RESET


def begin_password_reset_request() -> None:
    st.session_state["cadivor_root_state"] = APP_PASSWORD_RESET
    st.session_state.pop(_RECOVERY_ACTIVE_KEY, None)


def cancel_password_reset_request() -> None:
    st.session_state["cadivor_root_state"] = APP_LOGIN
    st.session_state.pop(_RECOVERY_ERROR_KEY, None)
    st.session_state.pop(_RECOVERY_NOTICE_KEY, None)


def _read_query_param(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
    except Exception:
        return ""
    if isinstance(value, (list, tuple)):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def _clear_recovery_query_params() -> None:
    for key in ("type", "access_token", "refresh_token", "code", "cadivor_recovery"):
        try:
            if key in st.query_params:
                del st.query_params[key]
        except Exception:
            pass


def _activate_recovery_session(supabase: Any, access_token: str, refresh_token: str) -> bool:
    if not access_token or not refresh_token:
        return False
    try:
        session_response = supabase.auth.set_session(access_token, refresh_token)
    except Exception as exc:
        log_auth_diagnostic("password_recovery_session_failed", error=type(exc).__name__)
        st.session_state[_RECOVERY_ERROR_KEY] = (
            "This password recovery link is invalid or has expired. "
            "Request a new reset email and try again."
        )
        return False

    session = getattr(session_response, "session", None)
    user = getattr(session_response, "user", None) or getattr(session, "user", None)
    if session is None or user is None:
        st.session_state[_RECOVERY_ERROR_KEY] = (
            "This password recovery link is invalid or has expired. "
            "Request a new reset email and try again."
        )
        return False

    st.session_state["user"] = user
    st.session_state["access_token"] = str(session.access_token)
    st.session_state["refresh_token"] = str(session.refresh_token)
    st.session_state[_RECOVERY_ACTIVE_KEY] = True
    st.session_state["cadivor_root_state"] = APP_PASSWORD_RECOVERY
    st.session_state["cadivor_auth_status"] = "signed_out"
    st.session_state.pop("cadivor_force_signed_out", None)
    log_auth_diagnostic("password_recovery_session_active")
    return True


def _recovery_redirect_url(**params: str) -> str:
    try:
        from src.urls import app_url

        return app_url("", **params)
    except Exception:
        origin = str(os.getenv("CADIVOR_APP_ORIGIN", "https://app.cadivor.com")).rstrip("/")
        query = "&".join(f"{key}={value}" for key, value in params.items() if value)
        return f"{origin}/?{query}" if query else f"{origin}/"


def render_recovery_hash_bridge() -> None:
    """Read Supabase recovery tokens from the URL hash once per session."""
    if st.session_state.get(_HASH_BRIDGE_RUN_KEY):
        return
    st.session_state[_HASH_BRIDGE_RUN_KEY] = True
    redirect_target = _recovery_redirect_url(cadivor_recovery="1")
    try:
        components.html(
            f"""
            <script>
            (function () {{
              try {{
                const hash = window.location.hash ? window.location.hash.substring(1) : "";
                if (!hash) return;
                const params = new URLSearchParams(hash);
                if (params.get("type") !== "recovery") return;
                const accessToken = params.get("access_token") || "";
                const refreshToken = params.get("refresh_token") || "";
                if (!accessToken || !refreshToken) return;
                const target = new URL({redirect_target!r});
                target.searchParams.set("type", "recovery");
                target.searchParams.set("access_token", accessToken);
                target.searchParams.set("refresh_token", refreshToken);
                window.location.replace(target.toString());
              }} catch (err) {{
                /* no-op */
              }}
            }})();
            </script>
            """,
            height=0,
            width=0,
        )
    except Exception:
        pass


def apply_password_recovery_from_query(supabase: Any) -> None:
    """Detect recovery tokens from Supabase redirect links."""
    if st.session_state.get(_RECOVERY_APPLIED_KEY) and password_recovery_active():
        return

    render_recovery_hash_bridge()

    recovery_type = _read_query_param("type").lower()
    access_token = _read_query_param("access_token")
    refresh_token = _read_query_param("refresh_token")
    recovery_flag = _read_query_param("cadivor_recovery").lower()

    if recovery_type == "recovery" and access_token and refresh_token:
        if _activate_recovery_session(supabase, access_token, refresh_token):
            st.session_state[_RECOVERY_APPLIED_KEY] = True
            _clear_recovery_query_params()
        return

    if recovery_flag == "1" and password_recovery_active():
        st.session_state[_RECOVERY_APPLIED_KEY] = True
        _clear_recovery_query_params()


def request_password_reset_email(supabase: Any, email: str) -> str:
    """Request a Supabase recovery email without revealing account existence."""
    normalized = str(email or "").strip()
    if not normalized:
        return "Enter the email address associated with your Cadivor account."

    redirect_to = _recovery_redirect_url()
    try:
        supabase.auth.reset_password_for_email(
            normalized,
            {"redirect_to": redirect_to},
        )
    except Exception as exc:
        log_auth_diagnostic("password_reset_request_failed", error=type(exc).__name__)
    return (
        "If an account exists for that email address, Cadivor will send password "
        "recovery instructions shortly."
    )


def complete_password_recovery(
    supabase: Any,
    password: str,
    confirm_password: str,
    *,
    cookie_manager: Any = None,
) -> tuple[bool, str]:
    if not password_recovery_active():
        return False, "Password recovery is not active."

    if not password or not confirm_password:
        return False, "Enter and confirm your new password."

    if password != confirm_password:
        return False, "Passwords do not match."

    if len(password) < 8:
        return False, "Password must be at least 8 characters."

    try:
        supabase.auth.update_user({"password": password})
    except Exception as exc:
        log_auth_diagnostic("password_recovery_update_failed", error=type(exc).__name__)
        return False, (
            "Cadivor could not update your password. "
            "The recovery link may have expired; request a new reset email."
        )

    st.session_state.pop(_RECOVERY_ACTIVE_KEY, None)
    st.session_state.pop("user", None)
    st.session_state.pop("access_token", None)
    st.session_state.pop("refresh_token", None)
    st.session_state["cadivor_root_state"] = APP_LOGIN
    st.session_state["cadivor_auth_status"] = "signed_out"
    st.session_state[_RECOVERY_NOTICE_KEY] = (
        "Your password was updated. Sign in with your new password."
    )

    try:
        from src.auth_cookies import invalidate_corrupt_auth_cookie

        invalidate_corrupt_auth_cookie(cookie_manager, reason="password_recovery_complete")
    except Exception:
        pass

    log_auth_diagnostic("password_recovery_complete")
    return True, st.session_state[_RECOVERY_NOTICE_KEY]
