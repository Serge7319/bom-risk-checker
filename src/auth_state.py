"""Cadivor authentication state machine.

The application must resolve authentication before it renders either the public
marketing experience or the authenticated workspace.  This module intentionally
uses three explicit states so a late CookieManager/Supabase restoration can
never cause the marketing site to flash inside an authenticated workflow.
"""
from __future__ import annotations

import html
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote

import streamlit as st
import streamlit.components.v1 as components

from src.secrets import get_secret_bool

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

_LOGOUT_SURVIVOR_KEYS = frozenset(
    {
        "cadivor_auth_debug_log",
        "cadivor_logout_in_progress",
        "cadivor_explicit_logout",
        "cadivor_logout_committed",
        "cadivor_force_signed_out",
        "cadivor_auth_status",
        "cadivor_auth_resolved",
    }
)

_LOGOUT_T0: float | None = None


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


def log_auth_diagnostic(event: str, **details: Any) -> None:
    """Record auth/copilot diagnostics without logging secrets or token values."""
    safe_details = {
        key: value
        for key, value in details.items()
        if key not in {"access_token", "refresh_token", "password", "api_key"}
    }
    _log(event, **safe_details)


def _logout_timing_enabled() -> bool:
    return get_secret_bool("CADIVOR_LOGOUT_TIMING", default=False)


def log_logout_phase(label: str) -> None:
    """Record monotonic logout phase timing without exposing session contents."""
    global _LOGOUT_T0
    if _LOGOUT_T0 is None:
        _LOGOUT_T0 = time.perf_counter()
    elapsed_ms = int((time.perf_counter() - _LOGOUT_T0) * 1000)
    _log("logout_phase", phase=label, elapsed_ms=elapsed_ms)
    if _logout_timing_enabled():
        print(f"[cadivor-logout] {label}: {elapsed_ms}ms", flush=True)


def _parse_cookie_json_string(raw_cookie: str) -> tuple[dict[str, Any] | None, dict[str, bool]]:
    """Parse a cookie JSON string, normalizing percent-encoded context reads once."""
    metadata = {
        "json_parse_direct": False,
        "url_decode_attempted": False,
        "decoding_changed_value": False,
        "json_parse_after_url_decode": False,
    }
    text = str(raw_cookie).strip()
    if not text:
        return None, metadata

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            metadata["json_parse_direct"] = True
            return parsed, metadata
    except Exception:
        pass

    decoded = unquote(text)
    metadata["url_decode_attempted"] = True
    metadata["decoding_changed_value"] = decoded != text

    try:
        parsed = json.loads(decoded)
        if isinstance(parsed, dict):
            metadata["json_parse_after_url_decode"] = True
            return parsed, metadata
    except Exception:
        pass

    return None, metadata


def coerce_cookie(raw_cookie: Any) -> dict[str, Any] | None:
    if not raw_cookie:
        return None
    if isinstance(raw_cookie, dict):
        return raw_cookie
    if isinstance(raw_cookie, str):
        parsed, _ = _parse_cookie_json_string(raw_cookie)
        return parsed
    return None


def clear_auth_session(*, keep_status: bool = False) -> None:
    for key in _AUTH_KEYS:
        st.session_state.pop(key, None)
    st.session_state.pop("cadivor_cookie_write_pending", None)
    st.session_state.pop("cadivor_auth_transition", None)
    st.session_state.pop("cadivor_auth_restore_attempts", None)
    if not keep_status:
        st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT


def _clear_user_session_for_logout() -> None:
    """Remove auth tokens and user workspace state without a blind full wipe."""
    debug_log = list(st.session_state.get("cadivor_auth_debug_log") or [])[-50:]
    for key in list(st.session_state.keys()):
        if key in _LOGOUT_SURVIVOR_KEYS:
            continue
        st.session_state.pop(key, None)
    clear_auth_session(keep_status=True)
    st.session_state["cadivor_auth_debug_log"] = debug_log
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_force_signed_out"] = True
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state["cadivor_logout_in_progress"] = True
    st.session_state["cadivor_explicit_logout"] = True


def mark_authenticated(user: Any, session: Any, cookie_manager: Any = None) -> None:
    """Commit a successful Supabase login as one atomic session-state change."""
    st.session_state["user"] = user
    st.session_state["access_token"] = session.access_token
    st.session_state["refresh_token"] = session.refresh_token
    st.session_state["cadivor_auth_status"] = AUTH_AUTHENTICATED
    st.session_state["cadivor_root_state"] = APP_AUTHENTICATED
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state.pop("cadivor_force_signed_out", None)
    st.session_state.pop("cadivor_auth_restore_attempts", None)
    st.session_state.pop("cadivor_auth_cookie_absent", None)
    st.session_state.pop("cadivor_auth_ui_was_shown", None)
    st.session_state.pop("cadivor_logout_in_progress", None)
    st.session_state.pop("cadivor_explicit_logout", None)
    st.session_state.pop("cadivor_logout_committed", None)

    requested = str(st.session_state.pop("cadivor_requested_page", "") or "").strip()
    route = requested or "Dashboard"
    st.session_state["cadivor_route"] = route
    st.session_state["app_mode"] = route
    _log("authenticated", page=st.session_state["app_mode"])
    try:
        from src.auth_cookies import persist_session_auth_cookie

        persist_session_auth_cookie(cookie_manager)
    except Exception:
        pass


def mark_signed_out(reason: str = "signed_out") -> None:
    clear_auth_session(keep_status=True)
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state.setdefault("cadivor_root_state", APP_PUBLIC)
    st.session_state["cadivor_auth_resolved"] = True
    st.session_state["cadivor_force_signed_out"] = True
    _log("signed_out", reason=reason)


def _remote_sign_out(supabase: Any) -> None:
    log_logout_phase("remote_supabase_signout_started")
    try:
        supabase.auth.sign_out()
        log_logout_phase("remote_supabase_signout_completed")
    except Exception as exc:
        log_logout_phase("remote_supabase_signout_failed")
        _log("logout_sign_out_failed", error=type(exc).__name__)


def begin_logout(supabase: Any, cookie_manager: Any) -> None:
    """Mark explicit logout, clear local auth, and defer redirect to bootstrap."""
    if st.session_state.get("cadivor_logout_committed"):
        return

    global _LOGOUT_T0
    _LOGOUT_T0 = time.perf_counter()
    log_logout_phase("signout_click_received")

    st.session_state["cadivor_logout_in_progress"] = True
    st.session_state["cadivor_explicit_logout"] = True

    log_logout_phase("local_session_clear_started")
    _clear_user_session_for_logout()
    log_logout_phase("local_session_clear_completed")

    try:
        from src.auth_cookies import clear_auth_cookie

        clear_auth_cookie(cookie_manager)
        log_logout_phase("auth_cookie_cleared")
    except Exception:
        log_logout_phase("auth_cookie_clear_failed")

    try:
        ThreadPoolExecutor(max_workers=1).submit(_remote_sign_out, supabase)
    except Exception:
        log_logout_phase("remote_supabase_signout_failed")
        _log("logout_sign_out_failed", error="executor")

    try:
        st.query_params.clear()
    except Exception:
        pass
    st.session_state["cadivor_logout_committed"] = True
    _log("logout_committed")


def explicit_logout_pending() -> bool:
    return bool(st.session_state.get("cadivor_explicit_logout"))


def render_external_logout_redirect() -> None:
    """Redirect the browser to the external marketing homepage after sign-out.

    Streamlit renders ``components.html`` inside a sandboxed iframe. Navigation
    must therefore target ``window.top`` (or ``window.parent``) so the address bar
    leaves the Streamlit app origin. The visible fallback link is rendered in the
    main Streamlit document and remains available if script navigation is blocked.
    """
    from src.urls import marketing_url

    target = marketing_url("/")
    target_json = json.dumps(target)
    safe_href = html.escape(target, quote=True)
    log_logout_phase("redirect_rendered")
    st.markdown(
        f"""
        <style id="cadivor-logout-redirect-css">
        header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],
        section[data-testid="stSidebar"],[data-testid="collapsedControl"]{{display:none!important}}
        html,body,.stApp,[data-testid="stAppViewContainer"]{{background:#F5F7FB!important}}
        .main .block-container{{max-width:none!important;padding:0!important;margin:0!important}}
        .cv-logout-redirect{{min-height:100vh;display:grid;place-items:center;padding:32px;font-family:Inter,system-ui,sans-serif;text-align:center;color:#64748B}}
        .cv-logout-redirect a{{color:#2563EB;font-weight:700;text-decoration:none}}
        .cv-logout-redirect a:hover{{text-decoration:underline}}
        </style>
        <div class="cv-logout-redirect" role="status" aria-live="polite">
          <p>Signing you out…</p>
          <p><a href="{safe_href}" target="_self">Return to Cadivor</a></p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        f"""<script>
        (() => {{
          const target = {target_json};
          const replaceLocation = (view) => {{
            if (!view || !view.location) {{
              return false;
            }}
            view.location.replace(target);
            return true;
          }};
          try {{
            if (replaceLocation(window.top)) {{
              return;
            }}
          }} catch (error) {{}}
          try {{
            if (replaceLocation(window.parent)) {{
              return;
            }}
          }} catch (error) {{}}
          replaceLocation(window);
        }})();
        </script>""",
        height=0,
        width=0,
    )


def handle_explicit_logout_if_pending() -> bool:
    """Render the external redirect and return True when logout is in progress."""
    if not explicit_logout_pending():
        return False
    render_external_logout_redirect()
    return True


def finalize_logout_cookie(cookie_manager: Any) -> None:
    """Ensure durable browser auth is cleared after explicit logout."""
    st.session_state.pop("cadivor_cookie_clear_pending", None)
    try:
        from src.auth_cookies import clear_auth_cookie

        clear_auth_cookie(cookie_manager)
    except Exception:
        pass


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


_RESTORE_TIMEOUT_SECONDS = 5.0


def _validate_tokens(
    supabase: Any,
    access_token: str,
    refresh_token: str,
    cookie_manager: Any = None,
) -> bool:
    def _restore() -> bool:
        try:
            session_response = supabase.auth.set_session(access_token, refresh_token)
            user_response = supabase.auth.get_user()
            user = getattr(user_response, "user", None)
            if user is None:
                return False
            st.session_state["user"] = user
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
            st.session_state.pop("cadivor_auth_cookie_absent", None)
            _log("restored")
            try:
                from src.auth_cookies import log_auth_restore, persist_session_auth_cookie

                log_auth_restore("validation_success")
                persist_session_auth_cookie(cookie_manager)
            except Exception:
                pass
            return True
        except Exception as exc:
            _log("restore_failed", error=type(exc).__name__)
            try:
                from src.auth_cookies import log_auth_restore

                log_auth_restore("validation_failed", error=type(exc).__name__)
            except Exception:
                pass
            return False

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_restore)
        try:
            return bool(future.result(timeout=_RESTORE_TIMEOUT_SECONDS))
        except FuturesTimeoutError:
            _log("restore_failed", error="timeout")
            try:
                from src.auth_cookies import log_auth_restore

                log_auth_restore("validation_failed", error="timeout")
            except Exception:
                pass
            return False


def resolve_auth_state(supabase: Any, cookie_manager: Any) -> str:
    """Resolve UNKNOWN -> SIGNED_OUT/AUTHENTICATED before either shell renders."""
    if explicit_logout_pending():
        return AUTH_SIGNED_OUT

    try:
        from src.auth_cookies import logout_blocks_auth_restore

        if logout_blocks_auth_restore(cookie_manager):
            clear_auth_session(keep_status=True)
            st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
            st.session_state["cadivor_force_signed_out"] = True
            return AUTH_SIGNED_OUT
    except Exception:
        pass

    if st.session_state.get("cadivor_force_signed_out"):
        clear_auth_session(keep_status=True)
        st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
        return AUTH_SIGNED_OUT

    if st.session_state.get("user") is not None:
        st.session_state["cadivor_auth_status"] = AUTH_AUTHENTICATED
        st.session_state["cadivor_root_state"] = APP_AUTHENTICATED
        st.session_state["cadivor_auth_resolved"] = True
        try:
            from src.auth_cookies import persist_session_auth_cookie

            persist_session_auth_cookie(cookie_manager)
        except Exception:
            pass
        return AUTH_AUTHENTICATED

    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if access_token and refresh_token:
        if _validate_tokens(supabase, access_token, refresh_token, cookie_manager):
            st.session_state["cadivor_root_state"] = APP_AUTHENTICATED
            return AUTH_AUTHENTICATED
        clear_auth_session(keep_status=True)
        try:
            from src.auth_cookies import invalidate_corrupt_auth_cookie, log_auth_restore

            log_auth_restore("validation_failed", reason="token_validation_failed")
            invalidate_corrupt_auth_cookie(cookie_manager, reason="token_validation_failed")
        except Exception:
            pass

    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_auth_resolved"] = True
    _log("resolved_signed_out")
    return AUTH_SIGNED_OUT
