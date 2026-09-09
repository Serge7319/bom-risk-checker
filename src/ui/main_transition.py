"""Single main-content transition owner for authenticated Cadivor routes.

Continuity contract (login → first content, and every authenticated navigation):
every visible frame shows exactly one of:
- readable auth progress ("Signing you in…"),
- target-route shell plus in-main "Opening {route}…",
- distinctive content for that same target route.

This module owns ONLY the main-panel loading surface. Foundation topbar and
sidebar must stay fully sharp and normal-opacity for the entire transition.
"""
from __future__ import annotations

import html
from typing import Any, MutableMapping

import streamlit as st

PRESENTED_ROUTE_KEY = "cadivor_presented_route"
DELAY_ROUTE_BODY_REVEAL_KEY = "cadivor_delay_route_body_reveal"
MAIN_TRANSITION_ACTIVE_KEY = "cadivor_main_transition_active"
MAIN_TRANSITION_ROUTE_KEY = "cadivor_main_transition_route"
MAIN_TRANSITION_GEN_KEY = "cadivor_main_transition_gen"
# Opening is skipped when warm session caches make nav cheaper than this budget.
FAST_CACHED_NAV_OPENING_MS = 300


def get_presented_route(session_state: MutableMapping[str, Any] | None = None) -> str:
    state = session_state if session_state is not None else st.session_state
    return str(state.get(PRESENTED_ROUTE_KEY) or "").strip()


def arm_main_transition(
    session_state: MutableMapping[str, Any],
    target_route: str,
) -> None:
    """Arm a main-content transition before target chrome commits on the next run.

    Clears the previously presented route so stale body ownership cannot survive
    into the target-chrome run.
    """
    route = str(target_route or "").strip()
    if not route:
        return
    session_state.pop(PRESENTED_ROUTE_KEY, None)
    session_state[MAIN_TRANSITION_ACTIVE_KEY] = True
    session_state[MAIN_TRANSITION_ROUTE_KEY] = route
    session_state[DELAY_ROUTE_BODY_REVEAL_KEY] = True


def route_needs_main_transition(target_route: str, presented_route: str = "") -> bool:
    """True on first admit and whenever chrome moves to a different route."""
    target = str(target_route or "").strip()
    if not target:
        return False
    presented = str(presented_route or "").strip()
    if bool(st.session_state.get(MAIN_TRANSITION_ACTIVE_KEY)):
        armed = str(st.session_state.get(MAIN_TRANSITION_ROUTE_KEY) or "").strip()
        if not armed or armed == target:
            return True
    return (not presented) or (presented != target)


def warm_session_nav_ready(session_state: MutableMapping[str, Any] | None = None) -> bool:
    """True when ordinary nav can skip Opening (profile + admit already warm)."""
    state = session_state if session_state is not None else st.session_state
    user = state.get("user")
    user_id = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
    if not user_id:
        return False
    try:
        from src.services.authenticated_profile_cache import recent_verified_profile
        from src.services.workspace_admit_cache import warm_workspace_admit_ready

        if recent_verified_profile(state, user_id) is None:
            return False
        return warm_workspace_admit_ready(state, user_id)
    except Exception:
        return False


def should_paint_opening_overlay(
    *,
    needs_transition: bool,
    session_state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Paint Opening only for slow/cold work — not routine warm cached nav."""
    if not needs_transition:
        return False
    state = session_state if session_state is not None else st.session_state
    # First admit (no foundation shell yet) always needs a continuity surface.
    if not state.get("cadivor_foundation_shell_mounted"):
        return True
    if warm_session_nav_ready(state):
        # Budget documented for metrics; warm path is treated as < FAST_CACHED_NAV_OPENING_MS.
        state["cadivor_last_nav_opening_skipped_ms"] = FAST_CACHED_NAV_OPENING_MS
        return False
    return True


def _next_transition_gen() -> int:
    try:
        current = int(st.session_state.get(MAIN_TRANSITION_GEN_KEY) or 0)
    except (TypeError, ValueError):
        current = 0
    nxt = current + 1
    st.session_state[MAIN_TRANSITION_GEN_KEY] = nxt
    return nxt


def inject_main_transition_css(transition_gen: int) -> None:
    """Inject the sole transition-owner stylesheet for this generation."""
    gen = int(transition_gen)
    st.markdown(
        f"""
        <style id="cadivor-main-transition-css"
               data-cadivor-transition-style-host="cadivor-main-transition-style"
               data-cadivor-transition-gen="{gen}">
        /*
          Main-panel owner only: below topbar, right of sidebar.
          Never cover foundation chrome. Never apply filter/blur/opacity to chrome.
        */
        .cv-main-transition.cv-route-loading{{
          box-sizing:border-box!important;
          position:fixed!important;
          left:var(--cv-foundation-rail,228px)!important;
          right:0!important;
          top:var(--cv-foundation-top,64px)!important;
          bottom:0!important;
          width:auto!important;
          max-width:none!important;
          min-width:0!important;
          min-height:calc(100vh - var(--cv-foundation-top,64px))!important;
          min-height:calc(100dvh - var(--cv-foundation-top,64px))!important;
          height:auto!important;
          /* Below foundation chrome; profile menu stays above at 1000010. */
          z-index:999990!important;
          margin:0!important;border-radius:0!important;border:0!important;
          padding:0!important;
          background:#F5F7FB!important;
          box-shadow:none!important;
          font-family:Inter,system-ui,sans-serif!important;
          overflow:auto!important;
          opacity:1!important;
          visibility:visible!important;
          pointer-events:auto!important;
          display:flex!important;
          align-items:center!important;
          justify-content:center!important;
          filter:none!important;
          backdrop-filter:none!important;
          -webkit-backdrop-filter:none!important;
          transform:none!important;
          height:calc(100vh - var(--cv-foundation-top,64px))!important;
          height:calc(100dvh - var(--cv-foundation-top,64px))!important
        }}
        .cv-main-transition.cv-route-loading .cv-main-transition-card{{
          box-sizing:border-box;width:min(420px,calc(100% - 48px));
          padding:28px 28px 24px;border:1px solid #D6E3F5;border-radius:18px;
          background:#FFFFFF;
          box-shadow:0 12px 28px rgba(15,23,42,.06);
          text-align:center
        }}
        .cv-main-transition.cv-route-loading .cv-main-transition-mark{{
          width:40px;height:40px;margin:0 auto 14px;border-radius:12px;
          display:grid;place-items:center;
          background:linear-gradient(145deg,#2563EB,#1D4ED8);
          color:#fff;font-size:18px;font-weight:850;letter-spacing:-.02em
        }}
        .cv-main-transition.cv-route-loading strong{{
          display:block;color:#0F172A;font-size:18px;font-weight:850;
          letter-spacing:-.02em;margin:0 0 6px
        }}
        .cv-main-transition.cv-route-loading p{{
          margin:0 0 16px;color:#64748B;font-size:13px;line-height:1.45;font-weight:650
        }}
        .cv-main-transition.cv-route-loading .cv-main-transition-progress{{
          height:4px;border-radius:999px;background:#E8EEF7;overflow:hidden
        }}
        .cv-main-transition.cv-route-loading .cv-main-transition-progress>i{{
          display:block;height:100%;width:42%;border-radius:999px;background:#2563EB;
          animation:cv-main-transition-progress 1.1s ease-in-out infinite
        }}
        @keyframes cv-main-transition-progress{{
          0%{{transform:translateX(-120%)}}
          100%{{transform:translateX(280%)}}
        }}
        body:has([data-cadivor-main-transition="1"]) .cv-foundation-topbar,
        body:has([data-cadivor-main-transition="1"]) .cv-foundation-topbar *,
        body:has([data-cadivor-main-transition="1"])
          [class*="st-key-cv_foundation_navigation"],
        body:has([data-cadivor-main-transition="1"])
          [class*="st-key-cv_foundation_navigation"] *,
        body:has([data-cadivor-main-transition="1"])
          [class*="st-key-cv_foundation_nav_"],
        body:has([data-cadivor-main-transition="1"])
          [class*="st-key-cv_foundation_nav_"] *,
        body:has([data-cadivor-main-transition="1"])
          [class*="st-key-cv_foundation_profile"],
        body:has([data-cadivor-main-transition="1"])
          [data-testid="stElementContainer"]:has([data-cadivor-topbar-flow-host="1"]),
        body:has([data-cadivor-main-transition="1"])
          [data-testid="stElementContainer"][data-stale="true"]:has(.cv-foundation-topbar),
        body:has([data-cadivor-main-transition="1"])
          [data-testid="stElementContainer"][data-stale="true"]:has(
            [class*="st-key-cv_foundation_navigation"]
          ),
        body:has([data-cadivor-main-transition="1"])
          [data-stale="true"][class*="st-key-cv_foundation_navigation"]{{
          opacity:1!important;
          filter:none!important;
          backdrop-filter:none!important;
          -webkit-backdrop-filter:none!important
        }}
        /* Drop only explicit stale duplicate rails/topbars. */
        body:has([data-cadivor-main-transition="1"]):has(
          [class*="st-key-cv_foundation_navigation"]:not([data-stale="true"])
        )
          [data-stale="true"][class*="st-key-cv_foundation_navigation"],
        body:has([data-cadivor-main-transition="1"]):has(
          [data-testid="stElementContainer"][data-stale="false"]
            [data-cadivor-topbar-flow-host="1"]
        )
          [data-testid="stElementContainer"][data-stale="true"]:has(
            [data-cadivor-topbar-flow-host="1"]
          ){{
          display:none!important;visibility:hidden!important;pointer-events:none!important;
          opacity:0!important;height:0!important;overflow:hidden!important
        }}
        /*
          Active transition wrappers: zero in-flow height; fixed Opening still paints.
          Do not apply height:0 to the Opening node itself.
        */
        [class*="st-key-cadivor_main_transition_owner"],
        div[data-testid="stElementContainer"]:has(
          [data-cadivor-transition-host="cadivor-main-transition"]
        ):not(:has([data-cadivor-topbar-flow-host])),
        div[data-testid="stElementContainer"]:has(
          [class*="st-key-cadivor_main_transition_owner"]
        ){{
          height:0!important;min-height:0!important;max-height:0!important;
          margin:0!important;padding:0!important;border:0!important;
          overflow:visible!important;transform:none!important;filter:none!important
        }}
        /* Style inject ElementContainer only — keep <style> active. */
        div[data-testid="stElementContainer"]:has(
          style#cadivor-main-transition-css
        ),
        div[data-testid="stElementContainer"]:has(
          [data-cadivor-transition-style-host="cadivor-main-transition-style"]
        ){{
          height:0!important;min-height:0!important;max-height:0!important;
          margin:0!important;padding:0!important;border:0!important;
          overflow:hidden!important
        }}
        /*
          After reveal: collapse ONLY this transition generation's owner/wrappers.
          pointer-events:none so no leftover overlay intercepts the account menu.
          Never target shared st-key alone (stale gen CSS would hide the next Opening).
        */
        body:has([data-cadivor-page-body][data-cadivor-transition-gen="{gen}"])
          [data-cadivor-main-transition="1"][data-cadivor-transition-gen="{gen}"],
        body:has([data-cadivor-page-body][data-cadivor-transition-gen="{gen}"])
          [data-cadivor-transition-host="cadivor-main-transition"][data-cadivor-transition-gen="{gen}"],
        body:has([data-cadivor-page-body][data-cadivor-transition-gen="{gen}"])
          div[data-testid="stElementContainer"]:has(
            [data-cadivor-main-transition="1"][data-cadivor-transition-gen="{gen}"]
          ):not(:has([data-cadivor-topbar-flow-host])):not(:has([class*="st-key-cv_foundation_"])){{
          display:none!important;visibility:hidden!important;pointer-events:none!important;
          opacity:0!important;z-index:-1!important;
          height:0!important;min-height:0!important;max-height:0!important;
          margin:0!important;padding:0!important;border:0!important;overflow:hidden!important
        }}
        @media (max-width:1100px){{
          .cv-main-transition.cv-route-loading{{left:0!important}}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def route_loading_markup(target_route: str, transition_gen: int) -> str:
    """Return the in-main target-route loading HTML (no nested <style>)."""
    safe_route = html.escape(str(target_route or "").strip() or "workspace")
    gen = int(transition_gen)
    return f"""
        <div data-cadivor-transition-host="cadivor-main-transition"
             data-cadivor-transition-gen="{gen}"
             data-testid="cadivor-main-transition-host">
        <div class="cv-main-transition cv-route-loading"
             data-cadivor-main-transition="1"
             data-cadivor-route-loading="{safe_route}"
             data-cadivor-transition-gen="{gen}"
             data-testid="cadivor-route-loading"
             role="status" aria-live="polite">
          <div class="cv-main-transition-card">
            <div class="cv-main-transition-mark" aria-hidden="true">C</div>
            <strong>Opening {safe_route}…</strong>
            <p>Preparing this page in your Cadivor workspace.</p>
            <div class="cv-main-transition-progress" aria-hidden="true"><i></i></div>
          </div>
        </div>
        </div>
        """


def prepare_main_transition(target_route: str) -> int:
    """Arm session keys + stylesheet; return the transition generation."""
    route = str(target_route or "").strip()
    if not route:
        return int(st.session_state.get(MAIN_TRANSITION_GEN_KEY) or 0)
    gen = _next_transition_gen()
    inject_main_transition_css(gen)
    st.session_state[MAIN_TRANSITION_ACTIVE_KEY] = True
    st.session_state[MAIN_TRANSITION_ROUTE_KEY] = route
    st.session_state[DELAY_ROUTE_BODY_REVEAL_KEY] = True
    return gen


def _paint_main_transition_markup(route: str, gen: int) -> None:
    markup = route_loading_markup(route, gen)
    container = getattr(st, "container", None)
    owner_key = f"cadivor_main_transition_owner_{int(gen)}"
    if callable(container):
        try:
            with container(key=owner_key):
                st.markdown(markup, unsafe_allow_html=True)
            return
        except TypeError:
            with container():
                st.markdown(markup, unsafe_allow_html=True)
            return
    st.markdown(markup, unsafe_allow_html=True)


def paint_prepared_main_transition(target_route: str) -> None:
    """Paint Opening… for an already-prepared generation (no gen bump)."""
    route = str(target_route or "").strip()
    if not route:
        return
    try:
        gen = int(st.session_state.get(MAIN_TRANSITION_GEN_KEY) or 0)
    except (TypeError, ValueError):
        gen = 0
    if gen <= 0:
        gen = prepare_main_transition(route)
    else:
        inject_main_transition_css(gen)
        st.session_state[MAIN_TRANSITION_ACTIVE_KEY] = True
        st.session_state[MAIN_TRANSITION_ROUTE_KEY] = route
        st.session_state[DELAY_ROUTE_BODY_REVEAL_KEY] = True
    _paint_main_transition_markup(route, gen)


def mount_main_transition_loading(target_route: str, *, paint_markup: bool = False) -> None:
    """Prepare the main-content transition; optionally paint the owner markup.

    Prefer prepare-then-``paint_prepared_main_transition`` after foundation chrome
    so Opening… never shares a Streamlit host with the topbar.
    """
    route = str(target_route or "").strip()
    if not route:
        return
    gen = prepare_main_transition(route)
    if paint_markup:
        _paint_main_transition_markup(route, gen)


def reveal_main_transition(route: str = "") -> None:
    """Reveal distinctive target content and collapse the main transition owner."""
    safe_route = str(
        route or st.session_state.get(MAIN_TRANSITION_ROUTE_KEY) or get_presented_route() or ""
    ).strip()
    if safe_route:
        st.session_state[PRESENTED_ROUTE_KEY] = safe_route
    st.session_state[MAIN_TRANSITION_ACTIVE_KEY] = False
    st.session_state.pop(DELAY_ROUTE_BODY_REVEAL_KEY, None)
    escaped = html.escape(safe_route or "1")
    try:
        gen = int(st.session_state.get(MAIN_TRANSITION_GEN_KEY) or 0)
    except (TypeError, ValueError):
        gen = 0
    try:
        st.markdown(
            f'<div data-cadivor-page-body="{escaped}" '
            f'data-cadivor-transition-gen="{gen}" aria-hidden="true" '
            'style="position:absolute;width:1px;height:1px;margin:-1px;border:0;'
            'padding:0;overflow:hidden;clip:rect(0,0,0,0)"></div>',
            unsafe_allow_html=True,
        )
    except Exception:
        pass
