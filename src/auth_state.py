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

AUTH_UNKNOWN = "unknown"
AUTH_SIGNED_OUT = "signed_out"
AUTH_AUTHENTICATED = "authenticated"
AUTH_LOGGING_OUT = "logging_out"

_AUTH_KEYS = ("user", "access_token", "refresh_token")
_MAX_RESTORE_ATTEMPTS = 3
_RESTORE_DELAY_SECONDS = 0.08


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
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state.pop("cadivor_force_signed_out", None)
    st.session_state.pop("cadivor_auth_restore_attempts", None)
    st.session_state.pop("cadivor_auth_ui_was_shown", None)

    requested = str(st.session_state.pop("cadivor_requested_page", "") or "").strip()
    st.session_state["app_mode"] = requested or "Dashboard"
    st.session_state["cadivor_cookie_write_pending"] = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
    }
    _log("authenticated", page=st.session_state["app_mode"])


def mark_signed_out(reason: str = "signed_out") -> None:
    clear_auth_session(keep_status=True)
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state["cadivor_force_signed_out"] = True
    _log("signed_out", reason=reason)



def begin_logout(supabase: Any, cookie_manager: Any) -> None:
    """Commit logout as one explicit, idempotent transition.

    The local authenticated state is removed before any public or login UI can
    render. Cookie clearing is attempted in the same run, and the signed-out
    guard prevents a delayed CookieManager value from restoring the user.
    """
    if st.session_state.get("cadivor_auth_status") == AUTH_LOGGING_OUT:
        return
    st.session_state["cadivor_auth_status"] = AUTH_LOGGING_OUT
    st.session_state["cadivor_auth_resolved"] = False
    st.session_state["cadivor_force_signed_out"] = True
    st.session_state["cadivor_logout_in_progress"] = True
    _log("logout_started")
    try:
        supabase.auth.sign_out()
    except Exception as exc:
        _log("supabase_logout_warning", error=type(exc).__name__)
    try:
        if cookie_manager:
            cookie_manager.set(cookie="bom_auth", val={}, key="s552_zero_bom_auth")
            cookie_manager.delete(cookie="bom_auth", key="s552_delete_bom_auth")
    except Exception as exc:
        _log("cookie_logout_warning", error=type(exc).__name__)

    # Preserve only diagnostic records; authenticated and workspace state must
    # not survive the logout boundary.
    records = list(st.session_state.get("cadivor_auth_debug_log") or [])[-50:]
    for key in list(st.session_state.keys()):
        if key != "cadivor_auth_debug_log":
            st.session_state.pop(key, None)
    st.session_state["cadivor_auth_debug_log"] = records
    st.session_state["cadivor_force_signed_out"] = True
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state["cadivor_public_after_logout"] = True
    _log("logout_committed")

def render_auth_boot() -> None:
    """Neutral non-blocking-looking boot surface used only while auth is unknown."""
    st.markdown(
        """
        <style id="cadivor-auth-boot-css">
        header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"]{
            display:none!important;visibility:hidden!important;height:0!important;
        }
        .stApp{background:#07162f!important;}
        .main .block-container{max-width:none!important;padding:0!important;margin:0!important;}
        .cv-auth-boot{min-height:100vh;display:grid;place-items:center;background:
          radial-gradient(circle at 75% 25%,rgba(37,99,235,.22),transparent 36%),
          linear-gradient(135deg,#06142c 0%,#0a2249 100%);font-family:Inter,system-ui,sans-serif;}
        .cv-auth-boot-card{display:flex;align-items:center;gap:14px;color:#fff;padding:18px 22px;
          border:1px solid rgba(148,163,184,.22);border-radius:18px;background:rgba(7,22,47,.72);
          box-shadow:0 24px 80px rgba(2,8,23,.34);backdrop-filter:blur(12px)}
        .cv-auth-boot-mark{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;
          background:linear-gradient(145deg,#3b82f6,#1d4ed8);font-weight:900;font-size:20px;}
        .cv-auth-boot-copy strong{display:block;font-size:15px;letter-spacing:-.01em;}
        .cv-auth-boot-copy span{display:block;color:#a9bad3;font-size:12px;margin-top:3px;}
        .cv-auth-pulse{width:7px;height:7px;border-radius:50%;background:#60a5fa;margin-left:8px;
          box-shadow:0 0 0 0 rgba(96,165,250,.6);animation:cvpulse 1.35s infinite;}
        @keyframes cvpulse{70%{box-shadow:0 0 0 10px rgba(96,165,250,0)}100%{box-shadow:0 0 0 0 rgba(96,165,250,0)}}
        </style>
        <div class="cv-auth-boot">
          <div class="cv-auth-boot-card">
            <div class="cv-auth-boot-mark">C</div>
            <div class="cv-auth-boot-copy"><strong>Cadivor</strong><span>Securing your workspace session…</span></div>
            <div class="cv-auth-pulse"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
        st.session_state["cadivor_auth_resolved"] = True
        return AUTH_AUTHENTICATED

    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if access_token and refresh_token:
        if _validate_tokens(supabase, access_token, refresh_token):
            return AUTH_AUTHENTICATED
        clear_auth_session(keep_status=True)

    # CookieManager hydrates asynchronously in Streamlit Cloud. During this short
    # UNKNOWN period, show only the neutral boot surface—never public marketing.
    raw_cookie = None
    try:
        raw_cookie = cookie_manager.get(cookie="bom_auth") if cookie_manager else None
    except Exception as exc:
        _log("cookie_read_failed", error=type(exc).__name__)

    auth_cookie = coerce_cookie(raw_cookie)
    if auth_cookie and auth_cookie.get("access_token") and auth_cookie.get("refresh_token"):
        if _validate_tokens(
            supabase,
            str(auth_cookie["access_token"]),
            str(auth_cookie["refresh_token"]),
        ):
            return AUTH_AUTHENTICATED
        # Invalid cookie must not be retried on every run.
        try:
            if cookie_manager:
                cookie_manager.set(cookie="bom_auth", val={}, key="invalidate_bom_auth")
        except Exception:
            pass
        clear_auth_session(keep_status=True)
        st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
        st.session_state["cadivor_auth_resolved"] = True
        return AUTH_SIGNED_OUT

    attempts = int(st.session_state.get("cadivor_auth_restore_attempts", 0))
    if status == AUTH_UNKNOWN and attempts < _MAX_RESTORE_ATTEMPTS:
        st.session_state["cadivor_auth_restore_attempts"] = attempts + 1
        _log("restore_wait", attempt=attempts + 1)
        render_auth_boot()
        time.sleep(_RESTORE_DELAY_SECONDS)
        st.rerun()

    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state.pop("cadivor_auth_restore_attempts", None)
    _log("resolved_signed_out")
    return AUTH_SIGNED_OUT
