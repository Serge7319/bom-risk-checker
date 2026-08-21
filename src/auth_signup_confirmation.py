"""Secure Cadivor signup-confirmation callback (token-hash / type=email).

Isolated from password recovery. Never reads or promotes fragment tokens.
Never places access_token or refresh_token in query parameters.
"""
from __future__ import annotations

import os
from typing import Any

import streamlit as st

from src.auth_state import (
    APP_LOGIN,
    APP_SIGNUP,
    APP_SIGNUP_CONFIRMATION_INVALID,
    APP_SIGNUP_CONFIRMATION_SUCCESS,
    AUTH_SIGNED_OUT,
    SIGNUP_PENDING_EMAIL_KEY,
    log_auth_diagnostic,
)

# Query / marker contract
SIGNUP_CONFIRM_CALLBACK_MARKER = "cadivor_signup_confirm"
SIGNUP_CONFIRM_TYPE = "email"
_RECOVERY_CALLBACK_MARKER = "cadivor_recovery"

# Session-state keys (non-secret metadata only)
_APPLIED_KEY = "cadivor_signup_confirm_query_applied"
_EXCHANGE_CONSUMED_KEY = "cadivor_signup_confirm_exchange_consumed"
_SESSION_READY_KEY = "cadivor_signup_confirm_session_ready"
_RESULT_KIND_KEY = "cadivor_signup_confirm_result_kind"

RESULT_SESSION_READY = "session_ready"
RESULT_LOGIN_REQUIRED = "login_required"
RESULT_INVALID = "invalid"


def signup_confirmation_redirect_url() -> str:
    """Canonical email_redirect_to for sign_up options."""
    try:
        from src.urls import app_url

        return app_url("", **{SIGNUP_CONFIRM_CALLBACK_MARKER: "1"})
    except Exception:
        origin = str(os.getenv("CADIVOR_APP_ORIGIN", "https://app.cadivor.com")).rstrip("/")
        return f"{origin}/?{SIGNUP_CONFIRM_CALLBACK_MARKER}=1"


def _read_query_param(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
    except Exception:
        return ""
    if isinstance(value, (list, tuple)):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def signup_confirmation_callback_requested() -> bool:
    return _read_query_param(SIGNUP_CONFIRM_CALLBACK_MARKER).lower() in {"1", "true", "yes"}


def _recovery_callback_requested() -> bool:
    return _read_query_param(_RECOVERY_CALLBACK_MARKER).lower() in {"1", "true", "yes"}


def signup_and_recovery_markers_conflict() -> bool:
    return signup_confirmation_callback_requested() and _recovery_callback_requested()


def signup_confirmation_surface_active() -> bool:
    state = str(st.session_state.get("cadivor_root_state") or "")
    return state in {
        APP_SIGNUP_CONFIRMATION_SUCCESS,
        APP_SIGNUP_CONFIRMATION_INVALID,
    }


def signup_confirmation_session_ready() -> bool:
    return bool(st.session_state.get(_SESSION_READY_KEY)) and bool(
        st.session_state.get("access_token")
    ) and bool(st.session_state.get("refresh_token")) and st.session_state.get("user") is not None


def signup_confirmation_result_kind() -> str:
    return str(st.session_state.get(_RESULT_KIND_KEY) or RESULT_INVALID)


def _response_get(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _nonempty_token(value: Any) -> bool:
    return bool(str(value or "").strip())


def _clear_signup_confirm_query_params() -> None:
    for key in (
        SIGNUP_CONFIRM_CALLBACK_MARKER,
        "token_hash",
        "type",
        "error",
        "error_code",
        "error_description",
    ):
        try:
            if key in st.query_params:
                del st.query_params[key]
        except Exception:
            pass


def _clear_conflicting_callback_query_params() -> None:
    _clear_signup_confirm_query_params()
    for key in (_RECOVERY_CALLBACK_MARKER, "code"):
        try:
            if key in st.query_params:
                del st.query_params[key]
        except Exception:
            pass


def _mark_exchange_consumed() -> None:
    st.session_state[_EXCHANGE_CONSUMED_KEY] = True


def _exchange_already_consumed() -> bool:
    return bool(st.session_state.get(_EXCHANGE_CONSUMED_KEY))


def _enter_invalid_result() -> None:
    st.session_state.pop(_SESSION_READY_KEY, None)
    st.session_state[_RESULT_KIND_KEY] = RESULT_INVALID
    st.session_state["cadivor_root_state"] = APP_SIGNUP_CONFIRMATION_INVALID
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_intent_applied"] = True
    st.session_state.pop(SIGNUP_PENDING_EMAIL_KEY, None)
    st.session_state[_APPLIED_KEY] = True


def _enter_success_login_required() -> None:
    st.session_state.pop(_SESSION_READY_KEY, None)
    # Do not retain unverified credentials on the login-required path.
    st.session_state.pop("access_token", None)
    st.session_state.pop("refresh_token", None)
    st.session_state.pop("user", None)
    st.session_state[_RESULT_KIND_KEY] = RESULT_LOGIN_REQUIRED
    st.session_state["cadivor_root_state"] = APP_SIGNUP_CONFIRMATION_SUCCESS
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_intent_applied"] = True
    st.session_state.pop(SIGNUP_PENDING_EMAIL_KEY, None)
    st.session_state[_APPLIED_KEY] = True


def _enter_success_session_ready(user: Any, access_token: str, refresh_token: str) -> None:
    # Hold tokens for Continue → workspace, but remain signed-out until CTA.
    # Mirrors recovery: credentials present without AUTH_AUTHENTICATED workspace entry.
    st.session_state["user"] = user
    st.session_state["access_token"] = str(access_token)
    st.session_state["refresh_token"] = str(refresh_token)
    st.session_state[_SESSION_READY_KEY] = True
    st.session_state[_RESULT_KIND_KEY] = RESULT_SESSION_READY
    st.session_state["cadivor_root_state"] = APP_SIGNUP_CONFIRMATION_SUCCESS
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_intent_applied"] = True
    st.session_state.pop("cadivor_force_signed_out", None)
    st.session_state.pop(SIGNUP_PENDING_EMAIL_KEY, None)
    st.session_state[_APPLIED_KEY] = True
    log_auth_diagnostic("signup_confirmation_session_ready")


def classify_signup_confirmation_response(response: Any) -> str:
    """Classify verify_otp AuthResponse for signup confirmation.

    Returns one of: session_ready | login_required | invalid
    """
    if response is None:
        return RESULT_INVALID

    user = _response_get(response, "user")
    session = _response_get(response, "session")
    if user is None and session is not None:
        user = _response_get(session, "user")

    access_token = _response_get(session, "access_token") if session is not None else None
    refresh_token = _response_get(session, "refresh_token") if session is not None else None
    usable = (
        session is not None
        and user is not None
        and _nonempty_token(access_token)
        and _nonempty_token(refresh_token)
    )
    if usable:
        return RESULT_SESSION_READY
    if user is not None:
        return RESULT_LOGIN_REQUIRED
    return RESULT_INVALID


def reject_conflicting_auth_callbacks() -> None:
    """Conflicting recovery + signup markers → safe rejection; never guess."""
    log_auth_diagnostic("signup_confirmation_conflicting_markers")
    _enter_invalid_result()
    _mark_exchange_consumed()
    _clear_conflicting_callback_query_params()


def _callback_credentials_in_query() -> bool:
    return bool(_read_query_param("token_hash") or _read_query_param("code"))


def _malformed_signup_callback() -> bool:
    """Marker present but shape is not the authorized token_hash + type=email contract."""
    if not signup_confirmation_callback_requested():
        return False
    token_hash = _read_query_param("token_hash")
    callback_type = _read_query_param("type").lower()
    # Explicitly reject token query promotion shapes.
    if _read_query_param("access_token") or _read_query_param("refresh_token"):
        return True
    if not token_hash or callback_type != SIGNUP_CONFIRM_TYPE:
        return True
    return False


def _activate_from_token_hash(supabase: Any, token_hash: str) -> str:
    """Verify OTP and return result kind. Never logs token values."""
    try:
        session_response = supabase.auth.verify_otp(
            {"token_hash": token_hash, "type": SIGNUP_CONFIRM_TYPE}
        )
    except Exception as exc:
        log_auth_diagnostic(
            "signup_confirmation_token_verify_failed",
            error=type(exc).__name__,
        )
        _enter_invalid_result()
        return RESULT_INVALID

    kind = classify_signup_confirmation_response(session_response)
    if kind == RESULT_SESSION_READY:
        session = _response_get(session_response, "session")
        user = _response_get(session_response, "user") or _response_get(session, "user")
        _enter_success_session_ready(
            user,
            str(_response_get(session, "access_token")),
            str(_response_get(session, "refresh_token")),
        )
        return kind
    if kind == RESULT_LOGIN_REQUIRED:
        _enter_success_login_required()
        return kind
    _enter_invalid_result()
    return RESULT_INVALID


def apply_signup_confirmation_from_query(supabase: Any) -> None:
    """Detect and consume Cadivor-owned signup confirmation callbacks."""
    if signup_and_recovery_markers_conflict():
        # Caller should prefer reject_conflicting_auth_callbacks; defensive fallback.
        reject_conflicting_auth_callbacks()
        return

    if st.session_state.get(_APPLIED_KEY) and signup_confirmation_surface_active():
        if signup_confirmation_callback_requested() or _callback_credentials_in_query():
            _clear_signup_confirm_query_params()
        return

    if not signup_confirmation_callback_requested():
        return

    # Marker present: this is a signup-confirmation attempt (never silent Login).
    if _exchange_already_consumed() and (
        _callback_credentials_in_query() or signup_confirmation_callback_requested()
    ):
        _enter_invalid_result()
        _clear_signup_confirm_query_params()
        return

    if _malformed_signup_callback():
        log_auth_diagnostic("signup_confirmation_malformed_callback")
        _enter_invalid_result()
        _mark_exchange_consumed()
        _clear_signup_confirm_query_params()
        return

    token_hash = _read_query_param("token_hash")
    # Drop token_hash from URL before/around verification outcome handling.
    # Verification uses the local variable only.
    kind = _activate_from_token_hash(supabase, token_hash)
    _mark_exchange_consumed()
    _clear_signup_confirm_query_params()
    if kind == RESULT_INVALID:
        log_auth_diagnostic("signup_confirmation_unavailable")


def clear_signup_confirmation_result() -> None:
    """Clear confirmation result metadata after leaving the surface."""
    st.session_state.pop(_APPLIED_KEY, None)
    st.session_state.pop(_SESSION_READY_KEY, None)
    st.session_state.pop(_RESULT_KIND_KEY, None)
    # Keep _EXCHANGE_CONSUMED_KEY so email-link replay stays safe in-session.


def continue_signup_confirmation_to_workspace(cookie_manager: Any = None) -> None:
    """Promote a verified usable session into the normal authenticated boundary."""
    if not signup_confirmation_session_ready():
        return
    user = st.session_state.get("user")
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    session = type(
        "_SignupConfirmSession",
        (),
        {
            "access_token": str(access_token),
            "refresh_token": str(refresh_token),
            "user": user,
        },
    )()
    from src.auth_state import mark_authenticated

    clear_signup_confirmation_result()
    mark_authenticated(user, session, cookie_manager)
    st.rerun()


def continue_signup_confirmation_to_login() -> None:
    clear_signup_confirmation_result()
    st.session_state.pop("access_token", None)
    st.session_state.pop("refresh_token", None)
    st.session_state.pop("user", None)
    st.session_state["cadivor_root_state"] = APP_LOGIN
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_mode"] = "Login"
    st.rerun()


def exit_signup_confirmation_invalid_to_login() -> None:
    clear_signup_confirmation_result()
    st.session_state["cadivor_root_state"] = APP_LOGIN
    st.session_state["cadivor_auth_mode"] = "Login"
    st.rerun()


def exit_signup_confirmation_invalid_to_signup() -> None:
    clear_signup_confirmation_result()
    st.session_state["cadivor_root_state"] = APP_SIGNUP
    st.session_state["cadivor_auth_intent_applied"] = True
    st.session_state["cadivor_auth_mode"] = "Create Account"
    st.rerun()
