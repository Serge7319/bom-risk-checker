"""Runtime auth/session diagnostics for Railway and Streamlit session forensics.

Logs structured events to stdout (Railway deploy logs). Never logs secrets,
token values, passwords, API keys, or cookie contents.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import streamlit as st

_DIAG_COOKIE_NAME = "cadivor_diag"
_FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "password",
        "api_key",
        "cookie",
        "cookie_value",
        "bom_auth",
        "user",
        "email",
    }
)

try:
    import extra_streamlit_components as stx
except Exception:
    stx = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_details(details: dict[str, Any]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in details.items():
        lowered = str(key).lower()
        if lowered in _FORBIDDEN_DETAIL_KEYS:
            continue
        if any(token in lowered for token in ("token", "password", "secret", "cookie")):
            continue
        safe[str(key)] = str(value)[:240]
    return safe


def log_runtime_diagnostic(event: str, **details: Any) -> None:
    """Emit one diagnostic line to Railway stdout and mirror to in-session debug log."""
    payload = _safe_details(details)
    parts = " ".join(f"{key}={value}" for key, value in sorted(payload.items()))
    line = f"[cadivor-diag] ts={_utc_now()} event={event}"
    if parts:
        line = f"{line} {parts}"
    print(line, flush=True)
    try:
        from src.auth_state import log_auth_diagnostic

        log_auth_diagnostic(event, **payload)
    except Exception:
        pass


def get_streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is not None and getattr(ctx, "session_id", None):
            return str(ctx.session_id)
    except Exception:
        pass
    return "unknown"


def get_process_id() -> int:
    return os.getpid()


def ensure_run_id() -> str:
    existing = st.session_state.get("cadivor_diag_run_id")
    if existing:
        return str(existing)
    run_id = str(uuid.uuid4())
    st.session_state["cadivor_diag_run_id"] = run_id
    return run_id


def ensure_streamlit_session_diagnostic_id() -> str:
    existing = st.session_state.get("cadivor_diag_session_id")
    if existing:
        return str(existing)
    session_diag_id = str(uuid.uuid4())
    st.session_state["cadivor_diag_session_id"] = session_diag_id
    return session_diag_id


def _parse_diag_cookie(raw: Any) -> tuple[str, str, str]:
    text = str(raw or "").strip()
    if not text:
        return "", "", ""
    parts = text.split("|", 2)
    browser_id = parts[0].strip() if len(parts) > 0 else ""
    last_streamlit_session = parts[1].strip() if len(parts) > 1 else ""
    last_process_id = parts[2].strip() if len(parts) > 2 else ""
    return browser_id, last_streamlit_session, last_process_id


def _format_diag_cookie(browser_id: str, streamlit_session_id: str, process_id: int) -> str:
    return f"{browser_id}|{streamlit_session_id}|{process_id}"


@st.cache_resource(show_spinner=False)
def get_diagnostic_cookie_manager() -> Any | None:
    if stx is None:
        return None
    try:
        return stx.CookieManager(key="cadivor_diag_cookie_manager")
    except Exception:
        return None


def sync_browser_diagnostic_state(
    *,
    streamlit_session_id: str,
    process_id: int,
) -> tuple[str, str]:
    """Return browser diagnostic id and classified session transition."""
    cookie_manager = get_diagnostic_cookie_manager()
    browser_id = ""
    last_streamlit_session = ""
    last_process_id = ""

    if cookie_manager is not None:
        try:
            raw = cookie_manager.get(cookie=_DIAG_COOKIE_NAME)
            browser_id, last_streamlit_session, last_process_id = _parse_diag_cookie(raw)
        except Exception:
            pass

    if not browser_id:
        browser_id = str(uuid.uuid4())

    transition = "first_observation"
    if last_streamlit_session and last_streamlit_session != streamlit_session_id:
        transition = "new_streamlit_session"
    elif last_process_id and last_process_id != str(process_id):
        transition = "new_process"
    elif last_streamlit_session == streamlit_session_id:
        transition = "normal_rerun"

    if cookie_manager is not None:
        try:
            cookie_manager.set(
                cookie=_DIAG_COOKIE_NAME,
                val=_format_diag_cookie(browser_id, streamlit_session_id, process_id),
                key="cadivor_diag_cookie_write",
            )
        except Exception:
            pass

    st.session_state["cadivor_diag_browser_id"] = browser_id
    st.session_state["cadivor_diag_transition"] = transition
    return browser_id, transition


def current_page_label() -> str:
    page = st.session_state.get("cadivor_route") or st.session_state.get("app_mode")
    if page:
        return str(page)
    try:
        query_page = st.query_params.get("page", "")
        if isinstance(query_page, list):
            query_page = query_page[0] if query_page else ""
        if query_page:
            return str(query_page)
    except Exception:
        pass
    return "unknown"


def auth_presence_fields() -> dict[str, Any]:
    auth_status = str(st.session_state.get("cadivor_auth_status") or "missing")
    return {
        "page": current_page_label(),
        "auth_status": auth_status if auth_status else "missing",
        "has_user": bool(st.session_state.get("user")),
        "has_access_token": bool(st.session_state.get("access_token")),
        "has_refresh_token": bool(st.session_state.get("refresh_token")),
        "has_copilot_snapshot": bool(st.session_state.get("cv48_auth_snapshot")),
        "copilot_inflight": bool(st.session_state.get("cv4801_followup_inflight")),
        "copilot_phase": str(st.session_state.get("cadivor_diag_copilot_phase") or "idle"),
        "explicit_logout_pending": bool(st.session_state.get("cadivor_explicit_logout")),
        "force_signed_out": bool(st.session_state.get("cadivor_force_signed_out")),
    }


def build_runtime_context(*, copilot_phase: str | None = None) -> dict[str, Any]:
    streamlit_session_id = get_streamlit_session_id()
    process_id = get_process_id()
    browser_id, transition = sync_browser_diagnostic_state(
        streamlit_session_id=streamlit_session_id,
        process_id=process_id,
    )
    if copilot_phase is not None:
        st.session_state["cadivor_diag_copilot_phase"] = copilot_phase
    context = {
        "browser_diag_id": browser_id,
        "streamlit_session_id": streamlit_session_id,
        "streamlit_session_diag_id": ensure_streamlit_session_diagnostic_id(),
        "process_id": process_id,
        "run_id": ensure_run_id(),
        "session_transition": transition,
        **auth_presence_fields(),
    }
    if copilot_phase is not None:
        context["copilot_phase"] = copilot_phase
    return context


def classify_auth_outcome(
    *,
    auth_status: str,
    transition: str,
    explicit_logout_pending: bool,
    force_signed_out: bool,
    has_access_token: bool,
    has_refresh_token: bool,
    has_user: bool,
    token_validation_failed: bool = False,
) -> str:
    if explicit_logout_pending or force_signed_out:
        return "explicit_logout"
    if token_validation_failed:
        return "token_validation_failure"
    if auth_status != "authenticated" and transition == "new_streamlit_session":
        return "new_streamlit_session"
    if auth_status != "authenticated" and transition == "new_process":
        return "new_process"
    if auth_status == "authenticated" and transition == "normal_rerun":
        return "normal_rerun"
    if auth_status != "authenticated" and has_access_token and has_refresh_token and not has_user:
        return "token_validation_failure"
    return transition if transition != "first_observation" else "unknown"


def log_bootstrap_diagnostic(*, stage: str, auth_status: str | None = None, **extra: Any) -> None:
    context = build_runtime_context()
    if auth_status is not None:
        context["resolved_auth_status"] = auth_status
    context["bootstrap_stage"] = stage
    context["probable_case"] = classify_auth_outcome(
        auth_status=str(auth_status or context.get("auth_status") or "missing"),
        transition=str(context.get("session_transition") or "unknown"),
        explicit_logout_pending=bool(context.get("explicit_logout_pending")),
        force_signed_out=bool(context.get("force_signed_out")),
        has_access_token=bool(context.get("has_access_token")),
        has_refresh_token=bool(context.get("has_refresh_token")),
        has_user=bool(context.get("has_user")),
        token_validation_failed=bool(extra.pop("token_validation_failed", False)),
    )
    context.update(extra)
    log_runtime_diagnostic("bootstrap", **context)


def log_copilot_diagnostic(*, phase: str, **extra: Any) -> None:
    context = build_runtime_context(copilot_phase=phase)
    context["probable_case"] = classify_auth_outcome(
        auth_status=str(context.get("auth_status") or "missing"),
        transition=str(context.get("session_transition") or "unknown"),
        explicit_logout_pending=bool(context.get("explicit_logout_pending")),
        force_signed_out=bool(context.get("force_signed_out")),
        has_access_token=bool(context.get("has_access_token")),
        has_refresh_token=bool(context.get("has_refresh_token")),
        has_user=bool(context.get("has_user")),
    )
    context.update(extra)
    log_runtime_diagnostic("copilot", **context)
