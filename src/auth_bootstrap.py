"""Minimal Cadivor authentication bootstrap.

This module must stay lightweight: no pandas, page modules, supplier APIs,
PDF/report stacks, or authenticated workspace imports. It resolves auth and
renders the login/signup shell before the heavy application runtime loads.
"""
from __future__ import annotations

import os
import time
from typing import Any

import streamlit as st
from supabase import create_client

from src.auth import show_auth_ui
from src.auth_state import (
    APP_AUTHENTICATED,
    APP_LOGIN,
    APP_PUBLIC,
    APP_SIGNUP,
    AUTH_AUTHENTICATED,
    AUTH_SIGNED_OUT,
    begin_logout,
    resolve_auth_state,
)

_STARTUP_T0 = time.perf_counter()
_STARTUP_PHASES: list[tuple[str, float]] = []


def _timing_enabled() -> bool:
    env_flag = os.getenv("CADIVOR_STARTUP_TIMING", "").strip().lower()
    if env_flag in {"1", "true", "yes", "on"}:
        return True
    try:
        return bool(st.secrets.get("CADIVOR_STARTUP_TIMING", False))
    except Exception:
        return False


def log_startup_phase(label: str) -> None:
    elapsed = time.perf_counter() - _STARTUP_T0
    _STARTUP_PHASES.append((label, elapsed))
    if _timing_enabled():
        print(f"[cadivor-startup] {label}: {elapsed:.3f}s", flush=True)


def startup_phase_summary() -> str:
    return ", ".join(f"{label}={elapsed:.2f}s" for label, elapsed in _STARTUP_PHASES)


@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Any:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def qp_value(name: str, default: str = "") -> str:
    """Read internal session navigation first, then external query parameters."""
    try:
        nav_params = st.session_state.get("cadivor_nav_params") or {}
        if name in nav_params:
            value = nav_params.get(name, default)
            return value or default
    except Exception:
        pass
    try:
        value = st.query_params.get(name, default)
        if isinstance(value, list):
            return value[0] if value else default
        return value or default
    except Exception:
        return default


def apply_auth_intent_from_query() -> None:
    """Translate marketing auth links into the signed-out auth state once."""
    if st.session_state.get("cadivor_auth_intent_applied"):
        return
    try:
        requested_auth = st.query_params.get("auth", "")
    except Exception:
        requested_auth = ""
    if isinstance(requested_auth, (list, tuple)):
        requested_auth = requested_auth[0] if requested_auth else ""
    requested_auth = str(requested_auth or "").strip().lower()
    if requested_auth == "login":
        st.session_state["cadivor_root_state"] = APP_LOGIN
        st.session_state["cadivor_auth_intent_applied"] = True
    elif requested_auth == "signup":
        st.session_state["cadivor_root_state"] = APP_SIGNUP
        st.session_state["cadivor_auth_intent_applied"] = True


def render_startup_loading_shell(message: str = "Preparing your workspace…") -> None:
    """Minimal branded surface shown while the lightweight bootstrap runs."""
    safe_message = str(message or "Preparing your workspace…")
    st.markdown(
        f"""
        <style id="cadivor-startup-shell-css">
        header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],
        section[data-testid="stSidebar"],[data-testid="collapsedControl"]{{display:none!important}}
        html,body,.stApp,[data-testid="stAppViewContainer"]{{background:#F5F7FB!important;color:#0F172A!important}}
        .main .block-container{{max-width:none!important;padding:0!important;margin:0!important}}
        .cv-startup-shell{{min-height:100vh;display:grid;place-items:center;padding:32px;background:radial-gradient(circle at 50% 35%,#fff 0,#F7F9FC 42%,#EEF3F8 100%);font-family:Inter,system-ui,sans-serif}}
        .cv-startup-shell-card{{width:min(420px,calc(100vw - 40px));padding:30px 30px 26px;border:1px solid #DCE4EE;border-radius:22px;background:rgba(255,255,255,.96);box-shadow:0 24px 70px rgba(15,23,42,.10);text-align:center}}
        .cv-startup-shell-mark{{width:48px;height:48px;margin:0 auto 16px;border-radius:14px;display:grid;place-items:center;background:#2563EB;color:#fff;font-weight:900;font-size:22px;box-shadow:0 12px 26px rgba(37,99,235,.25)}}
        .cv-startup-shell-card h1{{margin:0;color:#0F172A!important;font-size:20px;letter-spacing:-.025em}}
        .cv-startup-shell-card p{{margin:8px 0 0;color:#64748B!important;font-size:13px}}
        </style>
        <div class="cv-startup-shell" role="status" aria-live="polite">
          <div class="cv-startup-shell-card">
            <div class="cv-startup-shell-mark">C</div>
            <h1>Cadivor</h1>
            <p>{safe_message}</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def ensure_authenticated_or_stop() -> None:
    """Resolve auth and render login/signup immediately for signed-out visitors."""
    log_startup_phase("bootstrap_begin")

    log_startup_phase("supabase_client")
    supabase = get_supabase_client()
    cookie_manager = None

    requested_page = str(qp_value("page", "") or "").strip()
    if requested_page:
        st.session_state["cadivor_requested_page"] = requested_page

    apply_auth_intent_from_query()

    followup_snapshot = st.session_state.get("cv48_auth_snapshot")
    if st.session_state.get("cv4801_followup_inflight") and isinstance(followup_snapshot, dict):
        for key, value in followup_snapshot.items():
            if value is not None and st.session_state.get(key) is None:
                st.session_state[key] = value

    if st.session_state.pop("cadivor_logout_requested", False):
        begin_logout(supabase, cookie_manager)

    log_startup_phase("resolve_auth_state")
    auth_status = resolve_auth_state(supabase, cookie_manager)
    root_state = str(
        st.session_state.get("cadivor_root_state")
        or (APP_AUTHENTICATED if auth_status == AUTH_AUTHENTICATED else APP_PUBLIC)
    )

    if auth_status == AUTH_SIGNED_OUT or root_state != APP_AUTHENTICATED:
        log_startup_phase("render_auth_ui")
        show_auth_ui(supabase, cookie_manager)
        if _timing_enabled():
            st.caption(f"Startup timing: {startup_phase_summary()}")
        st.stop()

    if auth_status != AUTH_AUTHENTICATED:
        render_startup_loading_shell("Restoring your secure workspace…")
        if _timing_enabled():
            st.caption(f"Startup timing: {startup_phase_summary()}")
        st.stop()

    log_startup_phase("auth_boundary_passed")
