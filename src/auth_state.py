"""Cadivor authentication state machine.

The application must resolve authentication before it renders either the public
marketing experience or the authenticated workspace.  This module intentionally
uses three explicit states so a late CookieManager/Supabase restoration can
never cause the marketing site to flash inside an authenticated workflow.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

AUTH_UNKNOWN = "unknown"
AUTH_SIGNED_OUT = "signed_out"
AUTH_AUTHENTICATED = "authenticated"
AUTH_LOGGING_OUT = "logging_out"
AUTH_SIGNING_IN = "signing_in"

APP_PUBLIC = "public"
APP_LOGIN = "login"
APP_SIGNUP = "signup"
APP_SIGNING_IN = "signing_in"
APP_AUTHENTICATED = "authenticated"

_AUTH_KEYS = ("user", "access_token", "refresh_token")
_MAX_RESTORE_ATTEMPTS = 1
_RESTORE_DELAY_SECONDS = 0.0


def _log(event: str, **details: Any) -> None:
    """Keep a small in-session transition log for beta diagnostics."""
    record = {
        "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
        **{key: str(value)[:240] for key, value in details.items()},
    }
    records = list(st.session_state.get("cadivor_auth_debug_log") or [])
    records.append(record)
    st.session_state["cadivor_auth_debug_log"] = records[-50:]


def coerce_cookie(raw_cookie: Any) -> dict[str, Any] | None:
    if not raw_cookie:
        return None
    if isinstance(raw_cookie, dict):
        return raw_cookie
    if isinstance(raw_cookie, str):
        try:
            parsed = json.loads(raw_cookie)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def clear_auth_session(*, keep_status: bool = False) -> None:
    for key in _AUTH_KEYS:
        st.session_state.pop(key, None)
    st.session_state.pop("cadivor_cookie_write_pending", None)
    st.session_state.pop("cadivor_auth_transition", None)
    st.session_state.pop("cadivor_auth_restore_attempts", None)
    if not keep_status:
        st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT


def mark_authenticated(user: Any, session: Any) -> None:
    """Commit a successful Supabase login as one atomic session-state change."""
    st.session_state["user"] = user
    st.session_state["access_token"] = session.access_token
    st.session_state["refresh_token"] = session.refresh_token
    st.session_state["cadivor_auth_status"] = AUTH_AUTHENTICATED
    st.session_state["cadivor_root_state"] = APP_AUTHENTICATED
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state.pop("cadivor_force_signed_out", None)
    st.session_state.pop("cadivor_auth_restore_attempts", None)
    st.session_state.pop("cadivor_auth_ui_was_shown", None)

    requested = str(st.session_state.pop("cadivor_requested_page", "") or "").strip()
    route = requested or "Dashboard"
    st.session_state["cadivor_route"] = route
    st.session_state["app_mode"] = route
    _log("authenticated", page=st.session_state["app_mode"])


def mark_signed_out(reason: str = "signed_out") -> None:
    clear_auth_session(keep_status=True)
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state.setdefault("cadivor_root_state", APP_PUBLIC)
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state["cadivor_force_signed_out"] = True
    _log("signed_out", reason=reason)



def begin_logout(supabase: Any, cookie_manager: Any) -> None:
    """Commit logout in one local state change.

    The widget rerun caused by the Sign out button is the only rerun used. No
    browser navigation, query parameter, cookie component, or second rerun is
    allowed to participate.
    """
    records = list(st.session_state.get("cadivor_auth_debug_log") or [])[-50:]
    for key in list(st.session_state.keys()):
        if key != "cadivor_auth_debug_log":
            st.session_state.pop(key, None)
    st.session_state["cadivor_auth_debug_log"] = records
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_root_state"] = APP_PUBLIC
    st.session_state["cadivor_public_route"] = "home"
    st.session_state["cadivor_profile_menu_open"] = False
    st.session_state["cadivor_auth_resolved"] = True
    # Remove stale login/public destinations before the signed-out surface is
    # selected. This prevents logout from reopening Login or retaining a lower
    # marketing route on the next run.
    try:
        st.query_params.clear()
        st.query_params["public"] = "home"
    except Exception:
        pass
    _log("logout_committed")

def finalize_logout_cookie(cookie_manager: Any) -> None:
    """Compatibility no-op.

    Cookie cleanup is no longer performed by a browser component. The local
    force-signed-out guard is authoritative for the active Streamlit session.
    """
    st.session_state.pop("cadivor_cookie_clear_pending", None)

def render_auth_transition(message: str = "Preparing Cadivor") -> None:
    """Render one light branded transition surface for auth changes."""
    safe_message = str(message or "Preparing Cadivor")
    st.markdown(
        f"""
        <style id="cadivor-auth-transition-css">
        header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],
        section[data-testid="stSidebar"],[data-testid="collapsedControl"]{{display:none!important}}
        html,body,.stApp,[data-testid="stAppViewContainer"]{{background:#F5F7FB!important;color:#0F172A!important}}
        .main .block-container{{max-width:none!important;padding:0!important;margin:0!important}}
        .cv-auth-transition{{min-height:100vh;display:grid;place-items:center;padding:32px;background:radial-gradient(circle at 50% 35%,#fff 0,#F7F9FC 42%,#EEF3F8 100%);font-family:Inter,system-ui,sans-serif}}
        .cv-auth-transition-card{{width:min(420px,calc(100vw - 40px));padding:30px 30px 26px;border:1px solid #DCE4EE;border-radius:22px;background:rgba(255,255,255,.96);box-shadow:0 24px 70px rgba(15,23,42,.10);text-align:center}}
        .cv-auth-transition-mark{{width:48px;height:48px;margin:0 auto 16px;border-radius:14px;display:grid;place-items:center;background:#2563EB;color:#fff;font-weight:900;font-size:22px;box-shadow:0 12px 26px rgba(37,99,235,.25)}}
        .cv-auth-transition-card h1{{margin:0;color:#0F172A!important;font-size:20px;letter-spacing:-.025em}}
        .cv-auth-transition-card p{{margin:8px 0 18px;color:#64748B!important;font-size:13px}}
        .cv-auth-progress{{height:4px;border-radius:999px;background:#E8EEF6;overflow:hidden}}
        .cv-auth-progress span{{display:block;width:42%;height:100%;border-radius:inherit;background:#2563EB;animation:cv-auth-progress 1.1s ease-in-out infinite}}
        @keyframes cv-auth-progress{{0%{{transform:translateX(-110%)}}100%{{transform:translateX(340%)}}}}
        </style>
        <div class="cv-auth-transition" role="status" aria-live="polite">
          <div class="cv-auth-transition-card">
            <div class="cv-auth-transition-mark">C</div>
            <h1>Cadivor</h1>
            <p>{safe_message}</p>
            <div class="cv-auth-progress"><span></span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_auth_boot() -> None:
    """Use the same neutral branded surface while a saved session is restored."""
    render_auth_transition("Restoring your secure workspace…")


def _validate_tokens(supabase: Any, access_token: str, refresh_token: str) -> bool:
    try:
        session_response = supabase.auth.set_session(access_token, refresh_token)
        user_response = supabase.auth.get_user()
        user = getattr(user_response, "user", None)
        if user is None:
            return False
        st.session_state["user"] = user
        # set_session can rotate tokens; retain fresh values when available.
        fresh_session = getattr(session_response, "session", None)
        if fresh_session:
            st.session_state["access_token"] = fresh_session.access_token
            st.session_state["refresh_token"] = fresh_session.refresh_token
        else:
            st.session_state["access_token"] = access_token
            st.session_state["refresh_token"] = refresh_token
        st.session_state["cadivor_auth_status"] = AUTH_AUTHENTICATED
        st.session_state["cadivor_auth_resolved"] = True
        st.session_state.pop("cadivor_auth_restore_attempts", None)
        _log("restored")
        return True
    except Exception as exc:
        _log("restore_failed", error=type(exc).__name__)
        return False


def resolve_auth_state(supabase: Any, cookie_manager: Any) -> str:
    """Resolve UNKNOWN -> SIGNED_OUT/AUTHENTICATED before either shell renders."""
    status = str(st.session_state.get("cadivor_auth_status") or AUTH_UNKNOWN)

    if st.session_state.get("cadivor_force_signed_out"):
        clear_auth_session(keep_status=True)
        st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
        return AUTH_SIGNED_OUT

    if st.session_state.get("user") is not None:
        st.session_state["cadivor_auth_status"] = AUTH_AUTHENTICATED
        st.session_state["cadivor_root_state"] = APP_AUTHENTICATED
        st.session_state["cadivor_auth_resolved"] = True
        return AUTH_AUTHENTICATED

    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if access_token and refresh_token:
        if _validate_tokens(supabase, access_token, refresh_token):
            return AUTH_AUTHENTICATED
        clear_auth_session(keep_status=True)

    # No asynchronous cookie component participates in auth resolution.
    # A fresh browser connection resolves to signed out immediately; the active
    # Supabase session remains available through Streamlit session state.
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state.pop("cadivor_auth_restore_attempts", None)
    _log("resolved_signed_out")
    return AUTH_SIGNED_OUT
