"""Supabase-native password recovery for Cadivor."""
from __future__ import annotations

import os
from typing import Any

import streamlit as st

from src.auth_state import APP_LOGIN, APP_PASSWORD_RECOVERY, APP_PASSWORD_RESET, log_auth_diagnostic

_RECOVERY_ACTIVE_KEY = "cadivor_password_recovery_active"
_RECOVERY_ERROR_KEY = "cadivor_password_recovery_error"
_RECOVERY_NOTICE_KEY = "cadivor_password_recovery_notice"
_RECOVERY_APPLIED_KEY = "cadivor_password_recovery_query_applied"
_RECOVERY_EXCHANGE_CONSUMED_KEY = "cadivor_password_recovery_exchange_consumed"
_RECOVERY_CALLBACK_MARKER = "cadivor_recovery"


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


def _recovery_callback_requested() -> bool:
    return _read_query_param(_RECOVERY_CALLBACK_MARKER).lower() in {"1", "true", "yes"}


def _recovery_credentials_in_query() -> bool:
    return bool(
        _read_query_param("token_hash")
        or _read_query_param("code")
    )


def _clear_recovery_query_params() -> None:
    for key in ("type", "token_hash", "code", _RECOVERY_CALLBACK_MARKER):
        try:
            if key in st.query_params:
                del st.query_params[key]
        except Exception:
            pass


def _commit_recovery_session(user: Any, access_token: str, refresh_token: str) -> None:
    st.session_state["user"] = user
    st.session_state["access_token"] = str(access_token)
    st.session_state["refresh_token"] = str(refresh_token)
    st.session_state[_RECOVERY_ACTIVE_KEY] = True
    st.session_state["cadivor_root_state"] = APP_PASSWORD_RECOVERY
    st.session_state["cadivor_auth_status"] = "signed_out"
    st.session_state.pop("cadivor_force_signed_out", None)
    log_auth_diagnostic("password_recovery_session_active")


def _activate_recovery_from_token_hash(supabase: Any, token_hash: str) -> bool:
    if not token_hash:
        return False
    try:
        session_response = supabase.auth.verify_otp(
            {"token_hash": token_hash, "type": "recovery"}
        )
    except Exception as exc:
        log_auth_diagnostic("password_recovery_token_verify_failed", error=type(exc).__name__)
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

    _commit_recovery_session(user, str(session.access_token), str(session.refresh_token))
    return True


def _activate_recovery_from_code(supabase: Any, auth_code: str) -> bool:
    if not auth_code:
        return False
    try:
        session_response = supabase.auth.exchange_code_for_session({"auth_code": auth_code})
    except Exception as exc:
        log_auth_diagnostic("password_recovery_code_exchange_failed", error=type(exc).__name__)
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

    _commit_recovery_session(user, str(session.access_token), str(session.refresh_token))
    return True


def _mark_recovery_exchange_consumed() -> None:
    st.session_state[_RECOVERY_EXCHANGE_CONSUMED_KEY] = True


def _recovery_exchange_already_consumed() -> bool:
    return bool(st.session_state.get(_RECOVERY_EXCHANGE_CONSUMED_KEY))


def _recovery_redirect_url(**params: str) -> str:
    try:
        from src.urls import app_url

        return app_url("", **params)
    except Exception:
        origin = str(os.getenv("CADIVOR_APP_ORIGIN", "https://app.cadivor.com")).rstrip("/")
        query = "&".join(f"{key}={value}" for key, value in params.items() if value)
        return f"{origin}/?{query}" if query else f"{origin}/"


def apply_password_recovery_from_query(supabase: Any) -> None:
    """Detect Supabase PKCE recovery callbacks from server-readable query params."""
    if st.session_state.get(_RECOVERY_APPLIED_KEY) and password_recovery_active():
        return

    if password_recovery_active() and _recovery_callback_requested():
        st.session_state[_RECOVERY_APPLIED_KEY] = True
        _clear_recovery_query_params()
        return

    token_hash = _read_query_param("token_hash")
    recovery_type = _read_query_param("type").lower()
    auth_code = _read_query_param("code")
    recovery_marker = _recovery_callback_requested()

    if _recovery_exchange_already_consumed() and _recovery_credentials_in_query():
        st.session_state[_RECOVERY_ERROR_KEY] = (
            "This password recovery link has already been used. "
            "Request a new reset email and try again."
        )
        _clear_recovery_query_params()
        return

    if token_hash and recovery_type == "recovery" and recovery_marker:
        if _activate_recovery_from_token_hash(supabase, token_hash):
            _mark_recovery_exchange_consumed()
            st.session_state[_RECOVERY_APPLIED_KEY] = True
            _clear_recovery_query_params()
        return

    if auth_code and recovery_marker:
        if _activate_recovery_from_code(supabase, auth_code):
            _mark_recovery_exchange_consumed()
            st.session_state[_RECOVERY_APPLIED_KEY] = True
            _clear_recovery_query_params()
        return


def request_password_reset_email(supabase: Any, email: str) -> str:
    """Request a Supabase recovery email without revealing account existence."""
    normalized = str(email or "").strip()
    if not normalized:
        return "Enter the email address associated with your Cadivor account."

    redirect_to = _recovery_redirect_url(**{_RECOVERY_CALLBACK_MARKER: "1"})
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
    st.session_state.pop(_RECOVERY_APPLIED_KEY, None)
    st.session_state.pop(_RECOVERY_EXCHANGE_CONSUMED_KEY, None)
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
