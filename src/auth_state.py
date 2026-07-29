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
    """Complete logout locally in one deterministic state transition.

    Logout must never wait for a network request or enter the ordinary page
    transition pipeline.  Removing the local tokens and installing the
    force-signed-out guard is sufficient to end the authenticated browser
    session immediately.  Cookie cleanup is deferred to the signed-out render,
    where it cannot hold the authenticated shell on screen.
    """
    if st.session_state.get("cadivor_auth_status") == AUTH_SIGNED_OUT and st.session_state.get("cadivor_force_signed_out"):
        return

    records = list(st.session_state.get("cadivor_auth_debug_log") or [])[-50:]
    _log("logout_started")

    # Clear every authenticated/workspace value atomically.  Do not call
    # supabase.auth.sign_out() here: a slow remote response previously left the
    # user trapped behind the "Opening Sign out" transition surface.
    for key in list(st.session_state.keys()):
        if key != "cadivor_auth_debug_log":
            st.session_state.pop(key, None)

    st.session_state["cadivor_auth_debug_log"] = records
    st.session_state["cadivor_force_signed_out"] = True
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state["cadivor_public_after_logout"] = True
    st.session_state["cadivor_cookie_clear_pending"] = True
    _log("logout_committed")


def finalize_logout_cookie(cookie_manager: Any) -> None:
    """Best-effort cookie cleanup after the signed-out state is committed."""
    if not st.session_state.pop("cadivor_cookie_clear_pending", False):
        return
    try:
        if cookie_manager:
            cookie_manager.set(cookie="bom_auth", val={}, key="shell_zero_bom_auth")
            cookie_manager.delete(cookie="bom_auth", key="shell_delete_bom_auth")
    except Exception as exc:
        _log("cookie_logout_warning", error=type(exc).__name__)

def render_auth_boot() -> None:
    """Render a neutral light workspace skeleton while authentication resolves."""
    st.markdown(
        """
        <style id="cadivor-auth-boot-css">
        header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"]{
            display:none!important;visibility:hidden!important;height:0!important;
        }
        .stApp{background:#F4F7FB!important;}
        .main .block-container{max-width:none!important;padding:0!important;margin:0!important;}
        .cv-auth-boot{min-height:100vh;background:#F4F7FB;font-family:Inter,system-ui,sans-serif;color:#0F172A;}
        .cv-auth-top{height:64px;background:#fff;border-bottom:1px solid #E2E8F0;display:flex;align-items:center;padding:0 22px;gap:12px;}
        .cv-auth-mark{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:#2563EB;color:#fff;font-weight:900;}
        .cv-auth-brand strong{display:block;font-size:15px;line-height:1.1}.cv-auth-brand span{display:block;color:#64748B;font-size:10px;margin-top:3px;letter-spacing:.08em;text-transform:uppercase}
        .cv-auth-body{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:calc(100vh - 64px)}
        .cv-auth-rail{background:#0B1F3A;padding:22px 16px}.cv-auth-rail-line{height:36px;border-radius:9px;background:rgba(255,255,255,.08);margin-bottom:8px}.cv-auth-rail-line.active{background:rgba(96,165,250,.22)}
        .cv-auth-canvas{padding:26px 30px;max-width:1440px;width:100%;box-sizing:border-box}.cv-auth-title{width:260px;height:22px;border-radius:7px;background:#DCE4EE;margin-bottom:10px}.cv-auth-copy{width:min(560px,70%);height:12px;border-radius:6px;background:#E7EDF4;margin-bottom:24px}
        .cv-auth-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}.cv-auth-card{height:102px;border-radius:15px;background:#fff;border:1px solid #E2E8F0;position:relative;overflow:hidden}.cv-auth-panel{height:260px;border-radius:17px;background:#fff;border:1px solid #E2E8F0;position:relative;overflow:hidden}
        .cv-auth-card:after,.cv-auth-panel:after{content:"";position:absolute;inset:0;transform:translateX(-100%);background:linear-gradient(90deg,transparent,rgba(226,232,240,.55),transparent);animation:cv-auth-shimmer 1.35s infinite}
        .cv-auth-status{position:fixed;right:22px;bottom:20px;display:flex;align-items:center;gap:9px;background:#fff;border:1px solid #E2E8F0;border-radius:12px;padding:10px 13px;box-shadow:0 12px 30px rgba(15,23,42,.08);font-size:12px;font-weight:750;color:#475569}.cv-auth-dot{width:7px;height:7px;border-radius:50%;background:#2563EB;animation:cv-auth-pulse 1.2s infinite}
        @keyframes cv-auth-shimmer{100%{transform:translateX(100%)}}@keyframes cv-auth-pulse{50%{opacity:.35}}
        @media(max-width:900px){.cv-auth-body{grid-template-columns:1fr}.cv-auth-rail{display:none}.cv-auth-kpis{grid-template-columns:repeat(2,1fr)}}
        </style>
        <div class="cv-auth-boot">
          <div class="cv-auth-top"><div class="cv-auth-mark">C</div><div class="cv-auth-brand"><strong>Cadivor</strong><span>Engineering Intelligence</span></div></div>
          <div class="cv-auth-body">
            <aside class="cv-auth-rail"><div class="cv-auth-rail-line active"></div><div class="cv-auth-rail-line"></div><div class="cv-auth-rail-line"></div><div class="cv-auth-rail-line"></div><div class="cv-auth-rail-line"></div></aside>
            <main class="cv-auth-canvas"><div class="cv-auth-title"></div><div class="cv-auth-copy"></div><div class="cv-auth-kpis"><div class="cv-auth-card"></div><div class="cv-auth-card"></div><div class="cv-auth-card"></div><div class="cv-auth-card"></div></div><div class="cv-auth-panel"></div></main>
          </div>
          <div class="cv-auth-status"><span class="cv-auth-dot"></span>Restoring your secure workspace</div>
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
