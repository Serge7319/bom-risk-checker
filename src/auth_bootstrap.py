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
    APP_SIGNUP_CONFIRMATION_SUCCESS,
    APP_SIGNUP_CONFIRMATION_INVALID,
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
    try:
        from src.performance_timing import timing_enabled

        return timing_enabled()
    except Exception:
        return get_secret_bool("CADIVOR_STARTUP_TIMING", default=False)


def log_startup_phase(label: str) -> None:
    elapsed = time.perf_counter() - _STARTUP_T0
    _STARTUP_PHASES.append((label, elapsed))
    if _timing_enabled():
        print(f"[cadivor-startup] {label}: {elapsed:.3f}s", flush=True)
        try:
            from src.performance_timing import emit_timing

            # Milestone only (cumulative elapsed) — distinct from duration spans.
            emit_timing(
                f"startup.milestone.{label}",
                duration_ms=round(elapsed * 1000.0, 1),
                outcome="success",
                event="milestone",
            )
        except Exception:
            pass


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

    Signup confirmation pending/result surfaces are sticky: login/signup query
    intent must not remount the credential form after a confirmation-required
    signup or a confirmation callback result.
    """
    root_state = str(st.session_state.get("cadivor_root_state") or "")
    try:
        requested_auth = st.query_params.get("auth", "")
    except Exception:
        requested_auth = ""
    if isinstance(requested_auth, (list, tuple)):
        requested_auth = requested_auth[0] if requested_auth else ""
    requested_auth = str(requested_auth or "").strip().lower()

    if root_state in {
        APP_SIGNUP_CONFIRMATION_PENDING,
        APP_SIGNUP_CONFIRMATION_SUCCESS,
        APP_SIGNUP_CONFIRMATION_INVALID,
    }:
        # Consume one-time intent without replacing the confirmation surface.
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
    """Render lightweight workspace chrome while the authenticated app initializes."""
    safe_message = str(message or "Preparing your workspace…")
    st.markdown(
        f"""
        <style id="cadivor-startup-shell-css">
        header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],
        section[data-testid="stSidebar"],[data-testid="collapsedControl"]{{display:none!important}}
        html,body,.stApp,[data-testid="stAppViewContainer"]{{background:#F5F7FB!important;color:#0F172A!important}}
        .main .block-container{{max-width:none!important;padding:0!important;margin:0!important}}
        /* Keep the handoff shell as an opaque, non-interactive viewport overlay.
           Streamlit marks old elements stale before the replacement tree has
           finished painting; the narrow stale rule prevents that framework
           fade. The real shell marker then retires this overlay. */
        .cv-startup-shell{{position:fixed;inset:0;z-index:900;min-height:100vh;background:#F5F7FB;font-family:Inter,system-ui,sans-serif;color:#0F172A;opacity:1;pointer-events:none;transition:opacity .16s ease}}
        [data-stale]:has(.cv-startup-shell),
        [data-stale]:has(.cv-startup-shell) .cv-startup-shell{{opacity:1!important}}
        [data-testid="stAppViewContainer"]:has(.cv-foundation-topbar) .cv-startup-shell{{opacity:0!important}}
        .cv-startup-shell-topbar{{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;border-bottom:1px solid #E2E8F0;background:#FFFFFF}}
        .cv-startup-shell-brand{{display:flex;align-items:center;gap:11px;font-size:17px;font-weight:900;letter-spacing:-.025em}}
        .cv-startup-shell-mark{{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;background:#2563EB;color:#FFFFFF;font-weight:950;font-size:16px;box-shadow:0 8px 18px rgba(37,99,235,.22)}}
        .cv-startup-shell-status{{display:flex;align-items:center;gap:9px;color:#64748B;font-size:12px;font-weight:750}}
        .cv-startup-shell-status i{{width:8px;height:8px;border-radius:999px;background:#2563EB;box-shadow:0 0 0 4px rgba(37,99,235,.10);animation:cv-shell-pulse 1.35s ease-in-out infinite}}
        .cv-startup-shell-body{{display:grid;grid-template-columns:176px minmax(0,1fr);min-height:calc(100vh - 64px)}}
        .cv-startup-shell-nav{{padding:20px 12px;background:#0B1F3A;border-right:1px solid #173154;color:#DCE8F7}}
        .cv-startup-shell-nav-title{{padding:0 10px 16px;color:#FFFFFF;font-size:10px;font-weight:900;letter-spacing:.12em;text-transform:uppercase}}
        .cv-startup-shell-nav-item{{height:36px;display:flex;align-items:center;gap:9px;margin:3px 0;padding:0 10px;border-radius:9px;color:#AFC2DA;font-size:11px;font-weight:750}}
        .cv-startup-shell-nav-item.active{{background:#173E78;color:#FFFFFF}}
        .cv-startup-shell-nav-item b{{width:8px;height:8px;border:1.5px solid currentColor;border-radius:3px;opacity:.9}}
        .cv-startup-shell-main{{padding:34px 32px;overflow:hidden}}
        .cv-startup-shell-heading{{width:min(360px,55%);height:25px;border-radius:8px;background:#DCE5F0;margin-bottom:12px}}
        .cv-startup-shell-copy{{width:min(560px,78%);height:12px;border-radius:999px;background:#E5EBF3;margin-bottom:28px}}
        .cv-startup-shell-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}}
        .cv-startup-shell-tile{{height:92px;border:1px solid #E1E7EF;border-radius:14px;background:#FFFFFF;box-shadow:0 8px 20px rgba(15,23,42,.035)}}
        .cv-startup-shell-panel{{height:250px;border:1px solid #E1E7EF;border-radius:16px;background:#FFFFFF;box-shadow:0 10px 28px rgba(15,23,42,.04)}}
        .cv-startup-shell-tile,.cv-startup-shell-panel,.cv-startup-shell-heading,.cv-startup-shell-copy{{position:relative;overflow:hidden}}
        .cv-startup-shell-tile:after,.cv-startup-shell-panel:after,.cv-startup-shell-heading:after,.cv-startup-shell-copy:after{{content:"";position:absolute;inset:0;transform:translateX(-100%);background:linear-gradient(90deg,transparent,rgba(255,255,255,.72),transparent);animation:cv-shell-shimmer 1.5s infinite}}
        @keyframes cv-shell-shimmer{{100%{{transform:translateX(100%)}}}}
        @keyframes cv-shell-pulse{{0%,100%{{opacity:.45}}50%{{opacity:1}}}}
        @media(max-width:760px){{
          .cv-startup-shell-body{{grid-template-columns:64px minmax(0,1fr)}}
          .cv-startup-shell-nav{{padding:18px 8px}}
          .cv-startup-shell-nav-title,.cv-startup-shell-nav-item span{{display:none}}
          .cv-startup-shell-nav-item{{justify-content:center;padding:0}}
          .cv-startup-shell-main{{padding:24px 16px}}
          .cv-startup-shell-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}
        }}
        </style>
        <div class="cv-startup-shell" role="status" aria-live="polite">
          <div class="cv-startup-shell-topbar">
            <div class="cv-startup-shell-brand"><div class="cv-startup-shell-mark">C</div><span>Cadivor</span></div>
            <div class="cv-startup-shell-status"><i></i><span>{safe_message}</span></div>
          </div>
          <div class="cv-startup-shell-body">
            <aside class="cv-startup-shell-nav" aria-hidden="true">
              <div class="cv-startup-shell-nav-title">Workspace</div>
              <div class="cv-startup-shell-nav-item active"><b></b><span>Dashboard</span></div>
              <div class="cv-startup-shell-nav-item"><b></b><span>BOM Analyzer</span></div>
              <div class="cv-startup-shell-nav-item"><b></b><span>Alternative Finder</span></div>
              <div class="cv-startup-shell-nav-item"><b></b><span>Design Impact</span></div>
            </aside>
            <main class="cv-startup-shell-main" aria-hidden="true">
              <div class="cv-startup-shell-heading"></div>
              <div class="cv-startup-shell-copy"></div>
              <div class="cv-startup-shell-grid">
                <div class="cv-startup-shell-tile"></div><div class="cv-startup-shell-tile"></div>
                <div class="cv-startup-shell-tile"></div><div class="cv-startup-shell-tile"></div>
              </div>
              <div class="cv-startup-shell-panel"></div>
            </main>
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
    from src.performance_timing import emit_timing, timed_phase

    auth_status_in = str(st.session_state.get("cadivor_auth_status") or "unknown")
    log_startup_phase("bootstrap_begin")
    log_auth_restore("bootstrap_started")

    log_startup_phase("supabase_client")
    with timed_phase("auth.supabase_client", operation="init"):
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

    with timed_phase("auth.intent_apply", operation="resolve"):
        apply_auth_intent_from_query()

    from src.auth_recovery import apply_password_recovery_from_query, password_recovery_active
    from src.auth_signup_confirmation import (
        apply_signup_confirmation_from_query,
        reject_conflicting_auth_callbacks,
        signup_and_recovery_markers_conflict,
        signup_confirmation_surface_active,
    )

    # Deterministic marker precedence: never guess when both markers appear.
    with timed_phase("auth.callback_apply", operation="resolve"):
        if signup_and_recovery_markers_conflict():
            reject_conflicting_auth_callbacks()
        else:
            apply_password_recovery_from_query(supabase)
            apply_signup_confirmation_from_query(supabase)

    if password_recovery_active():
        log_startup_phase("render_password_recovery_ui")
        _render_t0 = time.perf_counter()
        with auth_surface_host.container():
            show_auth_ui(supabase, cookie_manager)
        emit_timing(
            "auth.render_signed_out",
            duration_ms=round((time.perf_counter() - _render_t0) * 1000.0, 1),
            outcome="stopped",
            route="password_recovery",
            operation="render",
        )
        if _timing_enabled():
            st.caption(f"Startup timing: {startup_phase_summary()}")
        emit_timing(
            "auth.boundary",
            duration_ms=0.0,
            outcome="stopped",
            route="password_recovery",
            event="boundary",
        )
        st.stop()

    if signup_confirmation_surface_active():
        log_startup_phase("render_signup_confirmation_ui")
        _render_t0 = time.perf_counter()
        with auth_surface_host.container():
            show_auth_ui(supabase, cookie_manager)
        emit_timing(
            "auth.render_signed_out",
            duration_ms=round((time.perf_counter() - _render_t0) * 1000.0, 1),
            outcome="stopped",
            route="signup_confirmation",
            operation="render",
        )
        if _timing_enabled():
            st.caption(f"Startup timing: {startup_phase_summary()}")
        emit_timing(
            "auth.boundary",
            duration_ms=0.0,
            outcome="stopped",
            route="signup_confirmation",
            event="boundary",
        )
        st.stop()

    bootstrap_cookie_source = "skipped"
    if (
        not manual_login_in_flight()
        and not explicit_logout_pending()
        and not st.session_state.get("cadivor_force_signed_out")
    ):
        with timed_phase("auth.cookie_read", operation="hydrate") as cookie_meta:
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
            cookie_meta["outcome"] = "success" if hydrated else "empty"
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
            emit_timing(
                "auth.boundary",
                duration_ms=0.0,
                outcome="redirected",
                event="boundary",
            )
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
                with timed_phase(
                    "auth.cookie_hydration",
                    operation="hydrate",
                    attempt=attempts,
                    max_attempts=_MAX_HYDRATION_ATTEMPTS,
                    outcome_on_success="settled",
                ):
                    finalize_manager_fallback_hydration_timeout(cookie_manager)
            else:
                _hyd_t0 = time.perf_counter()
                with auth_surface_host.container():
                    render_auth_boot()
                log_auth_restore("manager_fallback_hydration_rerun", attempt=attempts)
                time.sleep(_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS)
                emit_timing(
                    "auth.cookie_hydration",
                    duration_ms=round((time.perf_counter() - _hyd_t0) * 1000.0, 1),
                    outcome="continue",
                    operation="hydrate",
                    attempt=attempts,
                    max_attempts=_MAX_HYDRATION_ATTEMPTS,
                )
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
                    with timed_phase(
                        "auth.cookie_hydration",
                        operation="hydrate",
                        attempt=attempts,
                        max_attempts=_MAX_HYDRATION_ATTEMPTS,
                        outcome_on_success="settled",
                    ):
                        finalize_auth_cookie_hydration_timeout(cookie_manager)
                else:
                    _hyd_t0 = time.perf_counter()
                    with auth_surface_host.container():
                        render_auth_boot()
                    log_auth_restore("hydration_wait_rerun", attempt=attempts)
                    time.sleep(_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS)
                    emit_timing(
                        "auth.cookie_hydration",
                        duration_ms=round((time.perf_counter() - _hyd_t0) * 1000.0, 1),
                        outcome="continue",
                        operation="hydrate",
                        attempt=attempts,
                        max_attempts=_MAX_HYDRATION_ATTEMPTS,
                    )
                    st.rerun()

    log_startup_phase("resolve_auth_state")
    log_auth_restore("validation_started")
    log_auth_correlation(
        "before_resolve_auth_state",
        cookie_manager=cookie_manager,
        transition_reason="pre_resolve",
    )
    with timed_phase("auth.resolve_auth_state", operation="validate") as resolve_meta:
        auth_status = resolve_auth_state(supabase, cookie_manager)
        resolve_meta["outcome"] = (
            "authenticated" if auth_status == AUTH_AUTHENTICATED else "signed_out"
        )
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
        _render_t0 = time.perf_counter()
        with auth_surface_host.container():
            show_auth_ui(supabase, cookie_manager)
        emit_timing(
            "auth.render_signed_out",
            duration_ms=round((time.perf_counter() - _render_t0) * 1000.0, 1),
            outcome="stopped",
            route="signed_out",
            operation="render",
        )
        if _timing_enabled():
            st.caption(f"Startup timing: {startup_phase_summary()}")
        emit_timing(
            "auth.boundary",
            duration_ms=0.0,
            outcome="signed_out",
            route="signed_out",
            event="boundary",
        )
        st.stop()

    # Authenticated workspace: clear the auth surface so no boot/card height remains.
    auth_surface_host.empty()

    if cookie_manager is None:
        cookie_manager = get_auth_cookie_manager(mount=True)
    persist_session_auth_cookie(cookie_manager)
    log_startup_phase("auth_boundary_passed")
    log_auth_restore("restoration_complete", auth_status=auth_status)
    emit_timing(
        "auth.boundary",
        duration_ms=0.0,
        outcome="authenticated",
        route="authenticated",
        event="boundary",
    )
