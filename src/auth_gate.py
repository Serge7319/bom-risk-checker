"""Single Cadivor auth gate — mutually exclusive render states.

States:
  boot | login | authenticating | ready | error

Rules:
- Exactly one complete branded surface per non-ready script run.
- Never use an empty placeholder as the root auth surface.
- Never mount authenticated app chrome until state is ready.
- Railway diagnostics: gate transitions with session_hash / script_run_id only.
"""
from __future__ import annotations

from typing import Any, Literal

import streamlit as st

AuthGateState = Literal["boot", "login", "authenticating", "ready", "error"]

AUTH_GATE_STATE_KEY = "cadivor_auth_gate_state"
AUTH_GATE_ERROR_KEY = "cadivor_auth_gate_error"
AUTH_GATE_PENDING_EMAIL_KEY = "cadivor_auth_gate_pending_email"
AUTH_GATE_PENDING_PASSWORD_KEY = "cadivor_auth_gate_pending_password"

_VALID_STATES = frozenset({"boot", "login", "authenticating", "ready", "error"})


def get_auth_gate_state() -> AuthGateState:
    raw = str(st.session_state.get(AUTH_GATE_STATE_KEY) or "").strip().lower()
    if raw in _VALID_STATES:
        return raw  # type: ignore[return-value]
    return "boot"


def set_auth_gate_state(
    state: AuthGateState,
    *,
    reason: str = "",
    error_message: str = "",
) -> None:
    """Set the gate state and emit a safe correlation line."""
    resolved = str(state or "boot").strip().lower()
    if resolved not in _VALID_STATES:
        resolved = "boot"
    previous = get_auth_gate_state()
    st.session_state[AUTH_GATE_STATE_KEY] = resolved
    if resolved == "error":
        st.session_state[AUTH_GATE_ERROR_KEY] = str(
            error_message or "Sign-in could not be completed. Please try again."
        )
    elif resolved == "login" and error_message:
        st.session_state[AUTH_GATE_ERROR_KEY] = str(error_message)
    elif resolved in {"boot", "authenticating", "ready"}:
        st.session_state.pop(AUTH_GATE_ERROR_KEY, None)
    _log_gate_transition(previous, resolved, reason=reason)


def auth_gate_error_message() -> str:
    return str(st.session_state.get(AUTH_GATE_ERROR_KEY) or "").strip()


def stash_pending_credentials(email: str, password: str) -> None:
    """Hold credentials for the next authenticating run only (popped on use)."""
    st.session_state[AUTH_GATE_PENDING_EMAIL_KEY] = str(email or "").strip()
    st.session_state[AUTH_GATE_PENDING_PASSWORD_KEY] = str(password or "")


def pop_pending_credentials() -> tuple[str, str]:
    email = str(st.session_state.pop(AUTH_GATE_PENDING_EMAIL_KEY, "") or "").strip()
    password = str(st.session_state.pop(AUTH_GATE_PENDING_PASSWORD_KEY, "") or "")
    return email, password


def has_pending_credentials() -> bool:
    email = str(st.session_state.get(AUTH_GATE_PENDING_EMAIL_KEY) or "").strip()
    password = str(st.session_state.get(AUTH_GATE_PENDING_PASSWORD_KEY) or "")
    return bool(email and password)


def _log_gate_transition(previous: str, nxt: str, *, reason: str = "") -> None:
    try:
        from src.auth_diagnostics import (
            current_script_run_id,
            hash_session_id,
            log_auth_correlation,
        )

        log_auth_correlation(
            "auth_gate_transition",
            transition_reason=(
                f"from_{previous}_to_{nxt}"
                + (f"__{str(reason).strip()}" if reason else "")
            )[:180],
        )
        # Extra compact line for Railway scrapers.
        print(
            "AUTH_GATE "
            f"from={previous} to={nxt} "
            f"session_hash={hash_session_id()} "
            f"script_run_id={current_script_run_id() or 'unknown'} "
            f"reason={(reason or 'n/a').replace(' ', '_')[:80]}",
            flush=True,
        )
    except Exception:
        pass


def render_full_page_gate_surface(
    *,
    title: str,
    message: str,
    kind: AuthGateState,
    show_progress: bool = True,
    error_text: str = "",
) -> None:
    """Paint one complete branded gate surface (never a bare top bar).

    boot / authenticating: opaque full-viewport card (no widgets underneath).
    login / error: in-flow branded chrome so Streamlit form/recovery stay visible.
    """
    safe_title = str(title or "Cadivor")
    safe_message = str(message or "Please wait…")
    safe_error = str(error_text or "").strip()
    progress_html = (
        '<div class="cv-auth-gate-progress" aria-hidden="true"></div>'
        if show_progress
        else ""
    )
    error_html = (
        f'<div class="cv-auth-gate-error" role="alert">{safe_error}</div>'
        if safe_error
        else ""
    )
    interactive = kind in {"login", "error"}
    if interactive:
        st.markdown(
            f"""
            <style id="cadivor-auth-gate-css">
            /* Neutralize leftover fixed boot/authenticating overlays from prior paints. */
            div.cv-auth-gate{{
              display:none!important;visibility:hidden!important;pointer-events:none!important;
              opacity:0!important;z-index:-1!important
            }}
            header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],
            section[data-testid="stSidebar"],[data-testid="collapsedControl"]{{
              display:none!important;visibility:hidden!important;height:0!important
            }}
            html,body,.stApp,[data-testid="stAppViewContainer"]{{
              background:#F5F7FB!important;color:#0F172A!important
            }}
            .main .block-container{{
              max-width:480px!important;padding:clamp(28px,8vh,72px) 16px 40px!important;margin:0 auto!important
            }}
            .cv-auth-gate-inline{{
              text-align:center;font-family:Inter,system-ui,sans-serif;margin:0 0 8px
            }}
            .cv-auth-gate-inline .cv-auth-gate-mark{{
              width:48px;height:48px;margin:0 auto 12px;border-radius:14px;display:grid;
              place-items:center;background:#2563EB;color:#fff;font-weight:900;font-size:22px;
              box-shadow:0 12px 26px rgba(37,99,235,.25)
            }}
            .cv-auth-gate-inline h1{{
              margin:0;color:#0F172A!important;font-size:20px;letter-spacing:-.025em
            }}
            .cv-auth-gate-inline p{{
              margin:8px 0 0;color:#64748B!important;font-size:13px;line-height:1.45
            }}
            .cv-auth-gate-error{{
              margin:12px auto 0;max-width:440px;padding:10px 12px;border-radius:12px;text-align:left;
              background:#FEF2F2;border:1px solid #FECACA;color:#991B1B;font-size:12px;
              line-height:1.45;font-weight:700
            }}
            </style>
            <div class="cv-auth-gate-inline" data-testid="cadivor-auth-gate"
                 data-auth-gate="{kind}" data-kind="{kind}" role="status" aria-live="polite">
              <div class="cv-auth-gate-mark">C</div>
              <h1>{safe_title}</h1>
              <p>{safe_message}</p>
              {error_html}
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
        <style id="cadivor-auth-gate-css">
        header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],
        section[data-testid="stSidebar"],[data-testid="collapsedControl"]{{
          display:none!important;visibility:hidden!important;height:0!important
        }}
        html,body,.stApp,[data-testid="stAppViewContainer"]{{
          background:#F5F7FB!important;color:#0F172A!important
        }}
        .main .block-container{{max-width:none!important;padding:0!important;margin:0!important}}
        .cv-auth-gate{{
          position:fixed;inset:0;z-index:1200;min-height:100vh;min-height:100dvh;
          display:grid;place-items:center;padding:24px;box-sizing:border-box;
          background:radial-gradient(circle at 50% 32%,#FFFFFF 0%,#F7F9FC 44%,#EEF3F8 100%);
          font-family:Inter,system-ui,sans-serif;pointer-events:auto
        }}
        .cv-auth-gate-card{{
          width:min(440px,100%);padding:30px 30px 26px;border:1px solid #DCE4EE;
          border-radius:22px;background:rgba(255,255,255,.97);
          box-shadow:0 24px 70px rgba(15,23,42,.10);text-align:center
        }}
        .cv-auth-gate-mark{{
          width:48px;height:48px;margin:0 auto 16px;border-radius:14px;display:grid;
          place-items:center;background:#2563EB;color:#fff;font-weight:900;font-size:22px;
          box-shadow:0 12px 26px rgba(37,99,235,.25)
        }}
        .cv-auth-gate-card h1{{
          margin:0;color:#0F172A!important;font-size:20px;letter-spacing:-.025em
        }}
        .cv-auth-gate-card p{{
          margin:8px 0 18px;color:#64748B!important;font-size:13px;line-height:1.45
        }}
        .cv-auth-gate-progress{{
          height:4px;border-radius:999px;background:#E8EEF6;overflow:hidden;position:relative
        }}
        .cv-auth-gate-progress:after{{
          content:"";position:absolute;left:0;top:0;bottom:0;width:42%;border-radius:inherit;background:#2563EB;
          animation:cv-auth-gate-progress 1.1s ease-in-out infinite
        }}
        .cv-auth-gate-error{{
          margin:0 0 14px;padding:10px 12px;border-radius:12px;text-align:left;
          background:#FEF2F2;border:1px solid #FECACA;color:#991B1B;font-size:12px;
          line-height:1.45;font-weight:700
        }}
        @keyframes cv-auth-gate-progress{{
          0%{{transform:translateX(-110%)}}100%{{transform:translateX(340%)}}
        }}
        </style>
        <div class="cv-auth-gate" data-kind="{kind}" data-testid="cadivor-auth-gate"
             data-auth-gate="{kind}" role="status" aria-live="polite">
          <div class="cv-auth-gate-card">
            <div class="cv-auth-gate-mark">C</div>
            <h1>{safe_title}</h1>
            <p>{safe_message}</p>
            {error_html}
            {progress_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def retire_auth_gate_overlays() -> None:
    """Hide any leftover fixed gate overlays once the app is ready."""
    st.markdown(
        """
        <style id="cadivor-auth-gate-retire">
        div.cv-auth-gate,div.cv-auth-gate-inline,[data-testid="cadivor-auth-gate"]{
          display:none!important;visibility:hidden!important;pointer-events:none!important
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def paint_auth_gate(state: AuthGateState) -> None:
    """Render the exclusive surface for the current gate state (except ready)."""
    if state == "ready":
        return
    if state == "boot":
        render_full_page_gate_surface(
            title="Cadivor",
            message="Restoring your session…",
            kind="boot",
            show_progress=True,
        )
        return
    if state == "authenticating":
        render_full_page_gate_surface(
            title="Cadivor",
            message="Signing you in…",
            kind="authenticating",
            show_progress=True,
        )
        return
    if state == "error":
        render_full_page_gate_surface(
            title="Cadivor",
            message="We could not complete sign-in.",
            kind="error",
            show_progress=False,
            error_text=auth_gate_error_message()
            or "Please try again or contact support.",
        )
        return
    # login: outer branded frame; login form widgets render after this marker.
    render_full_page_gate_surface(
        title="Cadivor",
        message="Sign in to continue to your engineering workspace.",
        kind="login",
        show_progress=False,
        error_text=auth_gate_error_message(),
    )


def resolve_initial_gate_state(
    *,
    force_signed_out: bool = False,
    handoff_active: bool = False,
    has_tokens: bool = False,
    pending_credentials: bool = False,
) -> AuthGateState:
    """Deterministic first paint choice before any network I/O."""
    if pending_credentials or handoff_active:
        return "authenticating"
    if force_signed_out:
        return "login"
    if has_tokens:
        return "boot"
    current = get_auth_gate_state()
    if current in {"login", "error", "authenticating", "boot"}:
        return current
    return "boot"

