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

    An established authenticated session always wins: ?auth=login must never
    redirect a valid logged-in user to the sign-in surface during internal
    navigation (e.g. browser Back to a cached ?auth=login URL).
    """
    from src.auth_state import AUTH_AUTHENTICATED

    # Guard 1: already fully authenticated — never re-apply login/signup intent.
    if st.session_state.get("cadivor_auth_status") == AUTH_AUTHENTICATED:
        # Consume and remove any stale auth query param so it cannot poison
        # future signed-out flows without affecting the current session.
        try:
            if "auth" in st.query_params:
                del st.query_params["auth"]
        except Exception:
            pass
        st.session_state["cadivor_auth_intent_applied"] = True
        return

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


AUTHENTICATED_STARTUP_SHELL_MESSAGE = "Preparing your workspace…"
AUTH_ENTRY_SHELL_MESSAGE = "Restoring your workspace…"
AUTH_ENTRY_SHELL_KEY = "cadivor_auth_entry_shell"
AUTH_ENTRY_SHELL_MESSAGE_KEY = "cadivor_auth_entry_shell_message"
# Run-scoped: auth_surface_host already painted the branded progress surface.
AUTH_PROGRESS_MOUNTED_KEY = "cadivor_auth_progress_mounted_run"
LOGIN_HANDOFF_ACTIVE_KEY = "cadivor_login_handoff_active"
LOGIN_HANDOFF_STAGE_KEY = "cadivor_login_handoff_stage"
LOGIN_HANDOFF_STARTED_AT_KEY = "cadivor_login_handoff_started_at"
LOGIN_HANDOFF_EMAIL_KEY = "cadivor_login_email_draft"
# Bound the branded post-login shell so a failed/hung profile init cannot
# leave users on an indefinite "Signing you in…" screen.
LOGIN_HANDOFF_TIMEOUT_SECONDS = 35.0
LOGIN_HANDOFF_STAGE_AUTHENTICATING = "authenticating"
LOGIN_HANDOFF_STAGE_INITIALIZING = "initializing"
LOGIN_HANDOFF_TIMEOUT_MESSAGE = (
    "Sign-in timed out while preparing your workspace. Please try again."
)


def login_handoff_active() -> bool:
    return bool(st.session_state.get(LOGIN_HANDOFF_ACTIVE_KEY))


def login_handoff_stage() -> str:
    return str(st.session_state.get(LOGIN_HANDOFF_STAGE_KEY) or "").strip()


def login_handoff_message() -> str:
    """Branded copy for the current bounded Login handoff stage."""
    if st.session_state.get(AUTH_ENTRY_SHELL_KEY) and not login_handoff_active():
        return str(
            st.session_state.get(AUTH_ENTRY_SHELL_MESSAGE_KEY)
            or AUTH_ENTRY_SHELL_MESSAGE
        )
    stage = login_handoff_stage()
    if stage == LOGIN_HANDOFF_STAGE_AUTHENTICATING:
        return "Signing you in…"
    if stage == LOGIN_HANDOFF_STAGE_INITIALIZING:
        return AUTHENTICATED_STARTUP_SHELL_MESSAGE
    if login_handoff_active():
        return AUTHENTICATED_STARTUP_SHELL_MESSAGE
    return "Signing you in…"


def mark_authenticated_entry_shell(
    message: str = AUTH_ENTRY_SHELL_MESSAGE,
) -> None:
    """Mark a branded shell while cookie/session restore loads the workspace."""
    st.session_state[AUTH_ENTRY_SHELL_KEY] = True
    st.session_state[AUTH_ENTRY_SHELL_MESSAGE_KEY] = str(
        message or AUTH_ENTRY_SHELL_MESSAGE
    )


def clear_authenticated_entry_shell() -> None:
    st.session_state.pop(AUTH_ENTRY_SHELL_KEY, None)
    st.session_state.pop(AUTH_ENTRY_SHELL_MESSAGE_KEY, None)


def auth_progress_surface_mounted() -> bool:
    """True when this script run already painted progress into auth_surface_host."""
    return bool(st.session_state.get(AUTH_PROGRESS_MOUNTED_KEY))


# Run-scoped host pointer (never session_state): login submit remounts via owner API.
_AUTH_SURFACE_HOST: Any | None = None
_AUTH_SURFACE_KIND_KEY = "cadivor_auth_surface_kind"


def bind_auth_surface_host(host: Any) -> None:
    """Remember the current script-run auth host for owner-only remounts."""
    global _AUTH_SURFACE_HOST
    _AUTH_SURFACE_HOST = host


def get_auth_surface_host() -> Any | None:
    return _AUTH_SURFACE_HOST


def mount_auth_progress_surface(host: Any, message: str | None = None) -> None:
    """Deprecated compatibility shim — redirects to the auth gate.

    Never paints the fake dashboard/topbar shell that caused blank production
    frames. The auth gate is the sole owner of boot/authenticating surfaces.
    """
    del host, message  # host.empty() paths are retired
    from src.auth_gate import paint_auth_gate, set_auth_gate_state

    set_auth_gate_state("authenticating", reason="legacy_mount_redirect")
    paint_auth_gate("authenticating")
    st.session_state[AUTH_PROGRESS_MOUNTED_KEY] = True
    st.session_state[_AUTH_SURFACE_KIND_KEY] = "progress"


def paint_auth_surface(host: Any, *, kind: str = "auto", message: str | None = None) -> None:
    """Deprecated compatibility shim — redirects to the auth gate."""
    del host
    from src.auth_gate import paint_auth_gate, set_auth_gate_state

    resolved = str(kind or "auto").strip().lower()
    if resolved == "auto":
        resolved = "authenticating" if _should_keep_auth_progress_mounted() else "boot"
    elif resolved == "progress":
        resolved = "authenticating"
    elif resolved not in {"boot", "authenticating", "login", "error"}:
        resolved = "boot"
    set_auth_gate_state(resolved, reason="legacy_paint_redirect")  # type: ignore[arg-type]
    paint_auth_gate(resolved)  # type: ignore[arg-type]
    st.session_state[AUTH_PROGRESS_MOUNTED_KEY] = True
    st.session_state[_AUTH_SURFACE_KIND_KEY] = resolved


def should_render_authenticated_startup_shell() -> bool:
    """Always False — competing startup shells are retired; auth gate owns paint."""
    return False


def render_startup_loading_shell(message: str = "Preparing your workspace…") -> None:
    """Deprecated — paints the auth-gate authenticating card (no fake topbar)."""
    from src.auth_gate import paint_auth_gate, set_auth_gate_state

    del message
    set_auth_gate_state("authenticating", reason="legacy_shell_redirect")
    paint_auth_gate("authenticating")
    st.session_state[AUTH_PROGRESS_MOUNTED_KEY] = True
    st.session_state[_AUTH_SURFACE_KIND_KEY] = "progress"


def _should_keep_auth_progress_mounted() -> bool:
    """Whether an in-flight handoff or restore must keep the progress surface."""
    if login_handoff_active():
        return True
    if st.session_state.get(AUTH_ENTRY_SHELL_KEY):
        return True
    if st.session_state.get("cadivor_force_signed_out"):
        return False
    if explicit_logout_pending():
        return False
    # Session tokens already present (same-tab restore / post-login continue).
    access = str(st.session_state.get("access_token") or "").strip()
    refresh = str(st.session_state.get("refresh_token") or "").strip()
    return bool(access and refresh)


def begin_login_handoff(stage: str = LOGIN_HANDOFF_STAGE_INITIALIZING) -> None:
    """Start a bounded branded Login→workspace handoff (idempotent if active)."""
    import time

    resolved = str(stage or LOGIN_HANDOFF_STAGE_INITIALIZING).strip()
    if resolved not in {
        LOGIN_HANDOFF_STAGE_AUTHENTICATING,
        LOGIN_HANDOFF_STAGE_INITIALIZING,
    }:
        resolved = LOGIN_HANDOFF_STAGE_INITIALIZING
    # One handoff only: never restart the timer or spawn a second bootstrap.
    if login_handoff_active():
        st.session_state[LOGIN_HANDOFF_STAGE_KEY] = resolved
        clear_authenticated_entry_shell()
        return
    st.session_state[LOGIN_HANDOFF_ACTIVE_KEY] = True
    st.session_state[LOGIN_HANDOFF_STAGE_KEY] = resolved
    st.session_state.setdefault(LOGIN_HANDOFF_STARTED_AT_KEY, time.monotonic())
    # Manual login owns the handoff shell; drop any cold-entry overlay.
    clear_authenticated_entry_shell()


def advance_login_handoff(stage: str) -> None:
    """Move an in-flight handoff to the next bounded stage."""
    if not login_handoff_active():
        begin_login_handoff(stage)
        return
    resolved = str(stage or "").strip()
    if resolved:
        st.session_state[LOGIN_HANDOFF_STAGE_KEY] = resolved


def clear_login_handoff() -> None:
    """End Login handoff and any cold authenticated entry shell."""
    st.session_state.pop(LOGIN_HANDOFF_ACTIVE_KEY, None)
    st.session_state.pop(LOGIN_HANDOFF_STAGE_KEY, None)
    st.session_state.pop(LOGIN_HANDOFF_STARTED_AT_KEY, None)
    clear_authenticated_entry_shell()
    st.session_state.pop(AUTH_PROGRESS_MOUNTED_KEY, None)
    st.session_state.pop(_AUTH_SURFACE_KIND_KEY, None)


def login_handoff_timed_out() -> bool:
    if not login_handoff_active():
        return False
    try:
        started = float(st.session_state.get(LOGIN_HANDOFF_STARTED_AT_KEY) or 0.0)
    except (TypeError, ValueError):
        started = 0.0
    if started <= 0.0:
        return False
    return (time.monotonic() - started) >= LOGIN_HANDOFF_TIMEOUT_SECONDS


def fail_login_handoff(
    *,
    message: str = LOGIN_HANDOFF_TIMEOUT_MESSAGE,
    email: str = "",
) -> None:
    """Clear handoff state and restore an enabled Login form with an error."""
    from src.auth_state import APP_LOGIN, AUTH_SIGNED_OUT
    from src.auth_gate import set_auth_gate_state

    draft = str(email or st.session_state.get(LOGIN_HANDOFF_EMAIL_KEY) or "").strip()
    clear_login_handoff()
    st.session_state.pop("cadivor_manual_login_in_progress", None)
    st.session_state["cadivor_auth_status"] = AUTH_SIGNED_OUT
    st.session_state["cadivor_root_state"] = APP_LOGIN
    st.session_state["cadivor_force_signed_out"] = True
    st.session_state["cadivor_auth_error"] = str(message or LOGIN_HANDOFF_TIMEOUT_MESSAGE)
    # Mirror into the atomic Login error channel so invalid-password (and other
    # Login failures) render inside the iframe, not only Streamlit session state.
    st.session_state["cadivor_atomic_login_error"] = str(
        message or LOGIN_HANDOFF_TIMEOUT_MESSAGE
    )
    try:
        epoch = int(st.session_state.get("cadivor_atomic_login_error_epoch") or 0)
    except (TypeError, ValueError):
        epoch = 0
    st.session_state["cadivor_atomic_login_error_epoch"] = epoch + 1
    if draft:
        st.session_state[LOGIN_HANDOFF_EMAIL_KEY] = draft
    set_auth_gate_state(
        "login",
        reason="login_handoff_failed",
        error_message=str(message or LOGIN_HANDOFF_TIMEOUT_MESSAGE),
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
    """Single auth gate: boot | login | authenticating | ready | error.

    Paints one complete branded surface before any network/hydration work can
    yield. Never uses an empty placeholder as the root auth surface. Returns only when
    the gate is ready so the authenticated runtime may mount.
    """
    try:
        _ensure_authenticated_or_stop_impl()
    except Exception as exc:
        # Streamlit control-flow exceptions must propagate.
        name = type(exc).__name__
        if name in {"RerunException", "StopException", "RerunData"}:
            raise
        # Never log tokens/passwords/email/profile — type + correlation only.
        try:
            from src.auth_diagnostics import log_auth_correlation
            from src.auth_gate import paint_auth_gate, set_auth_gate_state

            log_auth_correlation(
                "auth_gate_unexpected_exception",
                transition_reason=name[:80],
            )
            print(f"AUTH_GATE unexpected_exception type={name}", flush=True)
            set_auth_gate_state(
                "error",
                reason="unexpected_exception",
                error_message="Sign-in could not be completed. Please try again.",
            )
            paint_auth_gate("error")
            if st.button("Back to Login", key="auth_gate_unexpected_retry"):
                set_auth_gate_state("login", reason="unexpected_retry")
                st.rerun()
            st.stop()
        except Exception as nested:
            if type(nested).__name__ in {"RerunException", "StopException", "RerunData"}:
                raise
            st.stop()


def _ensure_authenticated_or_stop_impl() -> None:
    from src.auth_cookies import native_cookie_api_available, read_auth_cookie_tokens_with_source
    from src.auth_diagnostics import log_auth_bounce, log_auth_correlation
    from src.auth_gate import (
        get_auth_gate_state,
        has_pending_credentials,
        paint_auth_gate,
        pop_pending_credentials,
        resolve_initial_gate_state,
        set_auth_gate_state,
    )
    from src.performance_timing import emit_timing, timed_phase

    auth_status_in = str(st.session_state.get("cadivor_auth_status") or "unknown")
    log_startup_phase("bootstrap_begin")
    log_auth_restore("bootstrap_started")

    log_startup_phase("supabase_client")
    with timed_phase("auth.supabase_client", operation="init"):
        supabase = get_supabase_client()
    cookie_manager = None

    # Clear legacy empty-host progress flags — the gate owns paint now.
    st.session_state.pop(AUTH_PROGRESS_MOUNTED_KEY, None)
    st.session_state.pop(_AUTH_SURFACE_KIND_KEY, None)

    access = str(st.session_state.get("access_token") or "").strip()
    refresh = str(st.session_state.get("refresh_token") or "").strip()
    gate_state = resolve_initial_gate_state(
        force_signed_out=bool(st.session_state.get("cadivor_force_signed_out")),
        handoff_active=bool(login_handoff_active() or manual_login_in_flight()),
        has_tokens=bool(access and refresh),
        pending_credentials=has_pending_credentials(),
    )
    set_auth_gate_state(gate_state, reason="bootstrap_first_paint")
    # FIRST paint — before cookie I/O, resolve, or profile work.
    paint_auth_gate(gate_state)

    log_auth_correlation(
        "bootstrap_entry",
        cookie_manager=None,
        auth_status_in=auth_status_in,
        transition_reason=f"gate_{gate_state}",
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

    with timed_phase("auth.callback_apply", operation="resolve"):
        if signup_and_recovery_markers_conflict():
            reject_conflicting_auth_callbacks()
        else:
            apply_password_recovery_from_query(supabase)
            apply_signup_confirmation_from_query(supabase)

    if password_recovery_active() or signup_confirmation_surface_active():
        set_auth_gate_state("login", reason="recovery_or_signup_surface")
        paint_auth_gate("login")
        show_auth_ui(supabase, cookie_manager)
        st.stop()

    # Authenticating: process stashed credentials after the branded surface painted.
    if get_auth_gate_state() == "authenticating" and has_pending_credentials():
        email, password = pop_pending_credentials()
        try:
            from src.auth import execute_password_login

            ok = execute_password_login(supabase, cookie_manager, email, password)
            if ok:
                set_auth_gate_state("ready", reason="provider_login_success")
            else:
                set_auth_gate_state(
                    "login",
                    reason="provider_login_failed",
                    error_message=str(
                        st.session_state.get("cadivor_atomic_login_error")
                        or "Email or password is incorrect. Please try again."
                    ),
                )
                st.rerun()
        except Exception:
            fail_login_handoff(
                message="Sign-in could not be completed. Please try again.",
                email=email,
            )
            set_auth_gate_state(
                "error",
                reason="login_exception",
                error_message="Sign-in could not be completed. Please try again.",
            )
            paint_auth_gate("error")
            if st.button("Back to Login", key="auth_gate_error_retry"):
                set_auth_gate_state("login", reason="error_retry")
                st.rerun()
            st.stop()

    # After a successful authenticating transition, admit the app immediately.
    if get_auth_gate_state() == "ready" and (
        str(st.session_state.get("cadivor_auth_status") or "") == AUTH_AUTHENTICATED
    ):
        if cookie_manager is None:
            cookie_manager = get_auth_cookie_manager(mount=True)
        try:
            persist_session_auth_cookie(cookie_manager)
        except Exception:
            pass
        clear_login_handoff()
        try:
            from src.auth_gate import retire_auth_gate_overlays

            retire_auth_gate_overlays()
        except Exception:
            pass
        log_startup_phase("auth_boundary_passed")
        emit_timing(
            "auth.boundary",
            duration_ms=0.0,
            outcome="authenticated",
            route="authenticated",
            event="boundary",
        )
        return

    bootstrap_cookie_source = "skipped"
    if (
        get_auth_gate_state() in {"boot", "ready", "authenticating"}
        and not explicit_logout_pending()
        and not st.session_state.get("cadivor_force_signed_out")
        and not has_pending_credentials()
    ):
        if get_auth_gate_state() == "boot":
            paint_auth_gate("boot")
        with timed_phase("auth.cookie_read", operation="hydrate") as cookie_meta:
            _tokens, cookie_source = read_auth_cookie_tokens_with_source(cookie_manager=None)
            bootstrap_cookie_source = cookie_source
            log_auth_correlation(
                "after_cookie_hydration",
                cookie_manager=None,
                transition_reason="gate_boot_hydrate",
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
        transition_reason="bootstrap_cookie_read",
    )

    _restore_copilot_workflow_snapshot()

    if st.session_state.pop("cadivor_logout_requested", False):
        begin_logout(supabase, get_auth_cookie_manager(mount=True))
        if handle_explicit_logout_if_pending():
            set_auth_gate_state("login", reason="logout")
            paint_auth_gate("login")
            st.stop()

    # Hydration wait loops stay inside boot — never blank.
    if get_auth_gate_state() == "boot" and not login_handoff_active():
        if cookie_manager is None:
            cookie_manager = get_auth_cookie_manager(mount=False)
        if manager_fallback_hydration_pending(cookie_manager) or (
            not native_cookie_api_available()
            and auth_cookie_hydration_pending(
                cookie_manager or get_auth_cookie_manager(mount=True)
            )
        ):
            attempts = record_auth_hydration_attempt()
            if attempts >= _MAX_HYDRATION_ATTEMPTS:
                if manager_fallback_hydration_pending(cookie_manager):
                    finalize_manager_fallback_hydration_timeout(
                        cookie_manager or get_auth_cookie_manager(mount=True)
                    )
                else:
                    finalize_auth_cookie_hydration_timeout(
                        cookie_manager or get_auth_cookie_manager(mount=True)
                    )
            else:
                paint_auth_gate("boot")
                time.sleep(_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS)
                st.rerun()

    log_startup_phase("resolve_auth_state")
    with timed_phase("auth.resolve_auth_state", operation="validate") as resolve_meta:
        auth_status = resolve_auth_state(supabase, cookie_manager)
        resolve_meta["outcome"] = (
            "authenticated" if auth_status == AUTH_AUTHENTICATED else "signed_out"
        )
    log_auth_correlation(
        "after_resolve_auth_state",
        cookie_manager=cookie_manager,
        transition_reason=f"resolved_{auth_status}_gate_{get_auth_gate_state()}",
    )

    if auth_status == AUTH_AUTHENTICATED or get_auth_gate_state() == "ready":
        set_auth_gate_state("ready", reason="authenticated")
        if cookie_manager is None:
            cookie_manager = get_auth_cookie_manager(mount=True)
        persist_session_auth_cookie(cookie_manager)
        # Brief authenticating/boot surface already painted this run when needed.
        # Do not paint competing startup shells — runtime mounts next.
        clear_login_handoff()
        try:
            from src.auth_gate import retire_auth_gate_overlays

            retire_auth_gate_overlays()
        except Exception:
            pass
        log_startup_phase("auth_boundary_passed")
        emit_timing(
            "auth.boundary",
            duration_ms=0.0,
            outcome="authenticated",
            route="authenticated",
            event="boundary",
        )
        return

    # Signed-out / failed resolve → exclusive login surface.
    set_auth_gate_state("login", reason=f"resolved_{auth_status}")
    paint_auth_gate("login")
    show_auth_ui(supabase, cookie_manager)
    # If login submit stashed credentials, next run is authenticating.
    if has_pending_credentials():
        set_auth_gate_state("authenticating", reason="credentials_stashed")
        st.rerun()
    st.stop()


# NOTE: auth gate owns paint — do not reintroduce empty-placeholder root hosts here.
