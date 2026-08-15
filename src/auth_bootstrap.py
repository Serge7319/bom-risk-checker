"""Minimal Cadivor authentication bootstrap.

This module must stay lightweight: no pandas, page modules, supplier APIs,
PDF/report stacks, or authenticated workspace imports. It resolves auth and
renders the login/signup shell before the heavy application runtime loads.
"""
from __future__ import annotations

import time
from typing import Any

import streamlit as st
from supabase import create_client

from src.auth import show_auth_ui
from src.auth_cookies import (
    _MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS,
    _MAX_HYDRATION_ATTEMPTS,
    auth_cookie_hydration_pending,
    finalize_auth_cookie_hydration_timeout,
    finalize_manager_fallback_hydration_timeout,
    get_auth_cookie_manager,
    hydrate_session_from_auth_cookie,
    log_auth_restore,
    manager_fallback_hydration_pending,
    persist_session_auth_cookie,
    record_auth_hydration_attempt,
)
from src.secrets import get_secret, get_secret_bool
from src.auth_state import (
    APP_LOGIN,
    APP_SIGNUP,
    APP_SIGNUP_CONFIRMATION_PENDING,
    AUTH_AUTHENTICATED,
    AUTH_SIGNING_IN,
    begin_logout,
    explicit_logout_pending,
    handle_explicit_logout_if_pending,
    log_auth_diagnostic,
    log_logout_phase,
    manual_login_in_flight,
    render_auth_boot,
    resolve_auth_state,
)

_STARTUP_T0 = time.perf_counter()
_STARTUP_PHASES: list[tuple[str, float]] = []


def _timing_enabled() -> bool:
    return get_secret_bool("CADIVOR_STARTUP_TIMING", default=False)


def log_startup_phase(label: str) -> None:
    elapsed = time.perf_counter() - _STARTUP_T0
    _STARTUP_PHASES.append((label, elapsed))
    if _timing_enabled():
        print(f"[cadivor-startup] {label}: {elapsed:.3f}s", flush=True)


def startup_phase_summary() -> str:
    return ", ".join(f"{label}={elapsed:.2f}s" for label, elapsed in _STARTUP_PHASES)


@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Any:
    url = get_secret("SUPABASE_URL", required=True)
    key = get_secret("SUPABASE_KEY", required=True)
    try:
        from supabase.lib.client_options import SyncClientOptions
        from supabase_auth import SyncMemoryStorage

        return create_client(
            url,
            key,
            options=SyncClientOptions(flow_type="pkce", storage=SyncMemoryStorage()),
        )
    except ImportError:
        # Test stubs may replace `supabase` with a non-package mock; library default is pkce.
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
    """Translate marketing auth links into the signed-out auth state once.

    Signup confirmation pending is sticky: login/signup query intent must not
    remount the credential form after a successful confirmation-required signup.
    """
    root_state = str(st.session_state.get("cadivor_root_state") or "")
    try:
        requested_auth = st.query_params.get("auth", "")
    except Exception:
        requested_auth = ""
    if isinstance(requested_auth, (list, tuple)):
        requested_auth = requested_auth[0] if requested_auth else ""
    requested_auth = str(requested_auth or "").strip().lower()

    if root_state == APP_SIGNUP_CONFIRMATION_PENDING:
        # Consume one-time intent without replacing the pending handoff surface.
        if requested_auth in {"login", "signup"}:
            st.session_state["cadivor_auth_intent_applied"] = True
            try:
                if "auth" in st.query_params:
                    del st.query_params["auth"]
            except Exception:
                pass
        return

    if st.session_state.get("cadivor_auth_intent_applied"):
        return
    if requested_auth == "login":
        st.session_state["cadivor_root_state"] = APP_LOGIN
        st.session_state["cadivor_auth_intent_applied"] = True
    elif requested_auth == "signup":
        st.session_state["cadivor_root_state"] = APP_SIGNUP
        st.session_state["cadivor_auth_intent_applied"] = True


AUTHENTICATED_STARTUP_SHELL_MESSAGE = "Loading your workspace…"


def should_render_authenticated_startup_shell() -> bool:
    """Render the full-screen startup shell only before the workspace first mounts."""
    from src.ui.core_premium_ui import authenticated_surface_ready

    return not authenticated_surface_ready()


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


def _restore_copilot_workflow_snapshot() -> None:
    """Restore in-flight copilot workflow keys across reruns in the same session."""
    print("ASK_CADIVOR script_run_auth_restore", flush=True)
    copilot_snapshot = st.session_state.get("cv48_copilot_snapshot") or {}
    copilot_inflight = bool(st.session_state.get("cv4801_followup_inflight"))
    if (
        not copilot_inflight
        or not isinstance(copilot_snapshot, dict)
        or not copilot_snapshot
        or explicit_logout_pending()
        or st.session_state.get("cadivor_force_signed_out")
    ):
        _log_ask_cadivor_auth_restore(
            restored=False,
            inflight=copilot_inflight,
            snapshot_keys=len(copilot_snapshot) if isinstance(copilot_snapshot, dict) else 0,
        )
        return
    restored_keys: list[str] = []
    try:
        for key, value in copilot_snapshot.items():
            if not key or value is None:
                continue
            if st.session_state.get(key) is None:
                st.session_state[key] = value
                restored_keys.append(str(key))
    except Exception as exc:
        log_auth_diagnostic("copilot_workflow_snapshot_restore_failed", error=type(exc).__name__)
    else:
        if restored_keys:
            log_auth_diagnostic(
                "copilot_workflow_snapshot_restored",
                keys=",".join(restored_keys),
                key_count=len(restored_keys),
            )
        _log_ask_cadivor_auth_restore(
            restored=bool(restored_keys),
            inflight=copilot_inflight,
            snapshot_keys=len(copilot_snapshot),
            restored_keys=",".join(restored_keys) if restored_keys else "",
        )


def _log_ask_cadivor_auth_restore(**details: Any) -> None:
    parts = ["ASK_CADIVOR auth_restore"]
    for key, value in details.items():
        parts.append(f"{key}={value}")
    print(" ".join(parts), flush=True)


def ensure_authenticated_or_stop() -> None:
    """Resolve auth and render login/signup immediately for signed-out visitors."""
    from src.auth_cookies import native_cookie_api_available, read_auth_cookie_tokens_with_source
    from src.auth_diagnostics import log_auth_bounce, log_auth_correlation

    auth_status_in = str(st.session_state.get("cadivor_auth_status") or "unknown")
    log_startup_phase("bootstrap_begin")
    log_auth_restore("bootstrap_started")

    log_startup_phase("supabase_client")
    supabase = get_supabase_client()
    cookie_manager = None

    # One stable authentication surface slot for this script run.
    # Created before CookieManager mount / hydration so boot and signed-out UI
    # replace each other in the same Streamlit delta position instead of
    # stacking as top-level siblings during stale-element transitions.
    # Do not store this DeltaGenerator in session_state.
    auth_surface_host = st.empty()

    log_auth_correlation(
        "bootstrap_entry",
        cookie_manager=None,
        auth_status_in=auth_status_in,
        transition_reason="bootstrap_entry",
    )
    log_auth_restore(
        "cookie_component_initialized",
        cookie_manager_ready=False,
        native_cookie_api_available=native_cookie_api_available(),
    )

    requested_page = str(qp_value("page", "") or "").strip()
    if requested_page:
        st.session_state["cadivor_requested_page"] = requested_page

    apply_auth_intent_from_query()

    from src.auth_recovery import apply_password_recovery_from_query, password_recovery_active

    apply_password_recovery_from_query(supabase)
    if password_recovery_active():
        log_startup_phase("render_password_recovery_ui")
        with auth_surface_host.container():
            show_auth_ui(supabase, cookie_manager)
        if _timing_enabled():
            st.caption(f"Startup timing: {startup_phase_summary()}")
        st.stop()

    bootstrap_cookie_source = "skipped"
    if (
        not manual_login_in_flight()
        and not explicit_logout_pending()
        and not st.session_state.get("cadivor_force_signed_out")
    ):
        _tokens, cookie_source = read_auth_cookie_tokens_with_source(cookie_manager=None)
        bootstrap_cookie_source = cookie_source
        if cookie_source == "context":
            hydration_reason = "native_context_restore_started"
        elif cookie_source == "manager_fallback":
            hydration_reason = "manager_fallback_restore_started"
        else:
            hydration_reason = "native_context_cookie_absent"
        log_auth_correlation(
            "after_cookie_hydration",
            cookie_manager=None,
            transition_reason=hydration_reason,
            cookie_source=cookie_source,
        )
        hydrated = hydrate_session_from_auth_cookie(cookie_manager)
        log_auth_restore(
            "cookie_read_ready",
            credential_present=hydrated,
            cookie_source=cookie_source,
            cookie_absent=bool(st.session_state.get("cadivor_auth_cookie_absent")),
        )
    log_auth_bounce(
        "cookie_read",
        cookie_manager=None,
        auth_status=auth_status_in,
        cookie_source=bootstrap_cookie_source,
        transition_reason=(
            "bootstrap_cookie_read_complete"
            if bootstrap_cookie_source != "skipped"
            else "bootstrap_cookie_read_skipped"
        ),
    )

    _restore_copilot_workflow_snapshot()

    if st.session_state.pop("cadivor_logout_requested", False):
        begin_logout(supabase, get_auth_cookie_manager(mount=True))
        if handle_explicit_logout_if_pending():
            log_startup_phase("logout_redirect")
            auth_surface_host.empty()
            st.stop()

    if not manual_login_in_flight():
        if cookie_manager is None:
            cookie_manager = get_auth_cookie_manager(mount=False)
        if manager_fallback_hydration_pending(cookie_manager):
            if cookie_manager is None:
                cookie_manager = get_auth_cookie_manager(mount=True)
            attempts = record_auth_hydration_attempt()
            log_auth_restore(
                "manager_fallback_hydration_pending",
                attempt=attempts,
                max_attempts=_MAX_HYDRATION_ATTEMPTS,
            )
            if attempts >= _MAX_HYDRATION_ATTEMPTS:
                finalize_manager_fallback_hydration_timeout(cookie_manager)
            else:
                with auth_surface_host.container():
                    render_auth_boot()
                log_auth_restore("manager_fallback_hydration_rerun", attempt=attempts)
                time.sleep(_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS)
                st.rerun()
        elif not native_cookie_api_available():
            if cookie_manager is None:
                cookie_manager = get_auth_cookie_manager(mount=True)
            if auth_cookie_hydration_pending(cookie_manager):
                attempts = record_auth_hydration_attempt()
                log_auth_restore(
                    "hydration_pending",
                    attempt=attempts,
                    max_attempts=_MAX_HYDRATION_ATTEMPTS,
                )
                if attempts >= _MAX_HYDRATION_ATTEMPTS:
                    finalize_auth_cookie_hydration_timeout(cookie_manager)
                else:
                    with auth_surface_host.container():
                        render_auth_boot()
                    log_auth_restore("hydration_wait_rerun", attempt=attempts)
                    time.sleep(_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS)
                    st.rerun()

    log_startup_phase("resolve_auth_state")
    log_auth_restore("validation_started")
    log_auth_correlation(
        "before_resolve_auth_state",
        cookie_manager=cookie_manager,
        transition_reason="pre_resolve",
    )
    auth_status = resolve_auth_state(supabase, cookie_manager)
    log_auth_correlation(
        "after_resolve_auth_state",
        cookie_manager=cookie_manager,
        transition_reason=f"resolved_{auth_status}",
    )
    log_auth_restore(
        "validation_complete",
        auth_status=auth_status,
        has_user=bool(st.session_state.get("user")),
    )
    if auth_status != AUTH_AUTHENTICATED:
        if auth_status == AUTH_SIGNING_IN:
            auth_ui_reason = "manual_login_in_flight"
        else:
            log_auth_restore("auth_boundary_failed", reason=f"resolved_{auth_status}")
            auth_ui_reason = "auth_boundary_failed"
        log_startup_phase("render_auth_ui")
        log_auth_correlation(
            "before_show_auth_ui",
            cookie_manager=cookie_manager,
            auth_status_in=auth_status,
            transition_reason=auth_ui_reason,
        )
        log_auth_bounce(
            "login_boundary_reached",
            cookie_manager=cookie_manager,
            auth_status=auth_status,
            transition_reason=auth_ui_reason,
        )
        with auth_surface_host.container():
            show_auth_ui(supabase, cookie_manager)
        if _timing_enabled():
            st.caption(f"Startup timing: {startup_phase_summary()}")
        st.stop()

    # Authenticated workspace: clear the auth surface so no boot/card height remains.
    auth_surface_host.empty()

    if cookie_manager is None:
        cookie_manager = get_auth_cookie_manager(mount=True)
    persist_session_auth_cookie(cookie_manager)
    log_startup_phase("auth_boundary_passed")
    log_auth_restore("restoration_complete", auth_status=auth_status)
