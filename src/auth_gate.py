"""Single Cadivor auth gate — mutually exclusive render states.

States:
  boot | login | authenticating | ready | error

Rules:
- Exactly one complete branded surface per non-ready script run.
- Never use an empty placeholder as the root auth surface.
- Never mount authenticated app chrome until state is ready.
- Never emit HTML/CSS/component markup as visible page text.
- Railway diagnostics: gate transitions with session_hash / script_run_id only.
"""
from __future__ import annotations

import html as html_lib
from typing import Literal

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
    # Unauthenticated default — never imply a session restore.
    return "login"


def set_auth_gate_state(
    state: AuthGateState,
    *,
    reason: str = "",
    error_message: str = "",
) -> None:
    """Set the gate state and emit a safe correlation line."""
    resolved = str(state or "login").strip().lower()
    if resolved not in _VALID_STATES:
        resolved = "login"
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


def _inject_gate_css(*, interactive: bool, show_progress: bool) -> None:
    """CSS-only injection — never mix style tags with card markup in one markdown."""
    if interactive:
        st.markdown(
            """
            <style id="cadivor-auth-gate-css">
            div.cv-auth-gate{
              display:none!important;visibility:hidden!important;pointer-events:none!important;
              opacity:0!important;z-index:-1!important
            }
            header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],
            section[data-testid="stSidebar"],[data-testid="collapsedControl"]{
              display:none!important;visibility:hidden!important;height:0!important
            }
            html,body,.stApp,[data-testid="stAppViewContainer"]{
              background:#F5F7FB!important;color:#0F172A!important
            }
            .main .block-container{
              max-width:480px!important;padding:clamp(28px,8vh,72px) 16px 40px!important;margin:0 auto!important
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        return

    progress_rules = ""
    if show_progress:
        progress_rules = """
        .cv-auth-gate-card[data-progress="1"]{
          padding-bottom:34px
        }
        .cv-auth-gate-card[data-progress="1"]:after{
          content:"";position:absolute;left:30px;right:30px;bottom:22px;height:4px;
          border-radius:999px;background:#E8EEF6;overflow:hidden
        }
        .cv-auth-gate-card[data-progress="1"]:before{
          content:"";position:absolute;left:30px;bottom:22px;height:4px;width:42%;
          border-radius:999px;background:#2563EB;z-index:1;
          animation:cv-auth-gate-progress 1.1s ease-in-out infinite
        }
        @keyframes cv-auth-gate-progress{
          0%{transform:translateX(0)}100%{transform:translateX(140%)}
        }
        """
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
          position:relative;width:min(440px,100%);padding:30px 30px 26px;border:1px solid #DCE4EE;
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
          margin:8px 0 0;color:#64748B!important;font-size:13px;line-height:1.45
        }}
        .cv-auth-gate-error{{
          margin:14px 0 0;padding:10px 12px;border-radius:12px;text-align:left;
          background:#FEF2F2;border:1px solid #FECACA;color:#991B1B;font-size:12px;
          line-height:1.45;font-weight:700
        }}
        {progress_rules}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_full_page_gate_surface(
    *,
    title: str,
    message: str,
    kind: AuthGateState,
    show_progress: bool = True,
    error_text: str = "",
) -> None:
    """Paint one complete branded gate surface (never bare top bar / raw HTML text).

    login / error: CSS chrome only — show_auth_ui owns the visible Login card.
    boot / authenticating: full-viewport Cadivor shell (session restore / sign-in).
    """
    safe_title = html_lib.escape(str(title or "Cadivor"))
    safe_message = html_lib.escape(str(message or "Please wait…"))
    safe_error = html_lib.escape(str(error_text or "").strip())
    safe_kind = html_lib.escape(str(kind or "login"))
    interactive = kind in {"login", "error"}

    try:
        _inject_gate_css(interactive=interactive, show_progress=show_progress and not interactive)
    except Exception:
        # Never fall back to dumping markup as plain text.
        pass

    if interactive:
        # Invisible state marker for tests/diagnostics — not a second visible card.
        try:
            st.markdown(
                f'<div data-testid="cadivor-auth-gate" data-auth-gate="{safe_kind}" '
                f'data-kind="{safe_kind}" aria-hidden="true" '
                f'style="position:absolute;width:1px;height:1px;margin:-1px;border:0;'
                f'padding:0;overflow:hidden;clip:rect(0,0,0,0)"></div>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass
        if kind == "error" and safe_error:
            try:
                st.error(str(error_text or "").strip())
            except Exception:
                pass
        return

    progress_attr = ' data-progress="1"' if show_progress else ""
    error_block = (
        f'<div class="cv-auth-gate-error" role="alert">{safe_error}</div>'
        if safe_error
        else ""
    )
    # Body markup is a separate markdown call from CSS to avoid Streamlit
    # escaping nested HTML as visible text.
    try:
        st.markdown(
            f'<div class="cv-auth-gate" data-kind="{safe_kind}" data-testid="cadivor-auth-gate" '
            f'data-auth-gate="{safe_kind}" role="status" aria-live="polite">'
            f'<div class="cv-auth-gate-card"{progress_attr}>'
            f'<div class="cv-auth-gate-mark">C</div>'
            f"<h1>{safe_title}</h1>"
            f"<p>{safe_message}</p>"
            f"{error_block}"
            f"</div></div>",
            unsafe_allow_html=True,
        )
    except Exception:
        # Plain-text fallback only — never dump HTML/CSS as visible text.
        plain_title = str(title or "Cadivor").strip() or "Cadivor"
        plain_message = str(message or "Please wait…").strip() or "Please wait…"
        try:
            st.write(plain_title)
            st.caption(plain_message)
            if error_text:
                st.error(str(error_text).strip())
        except Exception:
            pass


def retire_auth_gate_overlays() -> None:
    """Hide any leftover fixed gate overlays once the app is ready."""
    st.markdown(
        """
        <style id="cadivor-auth-gate-retire">
        div.cv-auth-gate,[data-testid="cadivor-auth-gate"]{
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
    # login: CSS chrome only — final Login card comes from show_auth_ui.
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
    """Deterministic first paint choice before any network I/O.

    Unauthenticated visitors go straight to login — never a boot flash.
    boot is reserved for an existing-session restore (tokens already present).
    """
    if pending_credentials or handoff_active:
        return "authenticating"
    if force_signed_out:
        return "login"
    if has_tokens:
        return "boot"
    return "login"
