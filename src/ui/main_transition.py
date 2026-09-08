"""Single main-content transition owner for authenticated Cadivor routes.

Continuity contract (login → first content, and every authenticated navigation):
every visible frame shows exactly one of:
- readable auth progress ("Signing you in…"),
- target-route shell plus in-main "Opening {route}…",
- distinctive content for that same target route.

This module owns the in-main loading slot. It replaces the previous strategy of
embedding loading beside the topbar and concealing prior bodies with large
per-route CSS selector lists.
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
        <style id="cadivor-main-transition-css">
        /* Fixed main-canvas owner. Sized like the auth gate (min-height:100vh)
           so Streamlit transform/containing-block ancestors cannot collapse it
           to a zero-height box (top/bottom alone did that in production).
           Sit just under foundation chrome (rail/topbar ~999999/1000000). */
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
          z-index:999990!important;
          margin:0!important;border-radius:0!important;border:0!important;
          padding:28px 36px!important;
          background:#F5F7FB!important;
          box-shadow:none!important;
          font-family:Inter,system-ui,sans-serif!important;
          overflow:auto!important;
          opacity:1!important;
          visibility:visible!important;
          pointer-events:auto!important;
          display:block!important
        }}
        .cv-main-transition.cv-route-loading strong{{
          display:block;color:#0F172A;font-size:18px;font-weight:850;
          letter-spacing:-.02em;margin:0 0 6px
        }}
        .cv-main-transition.cv-route-loading p{{
          margin:0;color:#64748B;font-size:13px;line-height:1.45;font-weight:650
        }}
        .cv-main-transition.cv-route-loading .cv-main-transition-card{{
          box-sizing:border-box;width:100%;max-width:720px;
          padding:22px 24px;border:1px solid #D6E3F5;border-radius:18px;
          background:linear-gradient(180deg,#FFFFFF 0%,#F7FAFF 100%);
          box-shadow:0 12px 28px rgba(15,23,42,.05)
        }}
        /* Collapse ONLY this generation once its matching page-body marker is
           present. Leftover markers/Openings from prior Streamlit runs must not
           hide the newly mounted owner. */
        body:has([data-cadivor-page-body][data-cadivor-transition-gen="{gen}"])
          [data-cadivor-main-transition="1"][data-cadivor-transition-gen="{gen}"],
        body:has([data-cadivor-page-body][data-cadivor-transition-gen="{gen}"])
          div[data-testid="stElementContainer"]:has(
            [data-cadivor-main-transition="1"][data-cadivor-transition-gen="{gen}"]
          ):not(:has(.cv-foundation-topbar)),
        body:has([data-cadivor-page-body][data-cadivor-transition-gen="{gen}"])
          [class*="st-key-cadivor_main_transition_owner"]{{
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
        <div class="cv-main-transition cv-route-loading"
             data-cadivor-main-transition="1"
             data-cadivor-route-loading="{safe_route}"
             data-cadivor-transition-gen="{gen}"
             data-testid="cadivor-route-loading"
             role="status" aria-live="polite">
          <div class="cv-main-transition-card">
            <strong>Opening {safe_route}…</strong>
            <p>Preparing this page in your Cadivor workspace.</p>
          </div>
        </div>
        """


def prepare_main_transition(target_route: str) -> int:
    """Arm session keys + stylesheet; return the transition generation.

    Markup is painted by the foundation shell (same markdown host as the fixed
    topbar) so ``position:fixed`` shares a stacking context that already works
    for chrome. A separate Streamlit block under main content can collapse to a
    zero-size containing block during mid-session navigations.
    """
    route = str(target_route or "").strip()
    if not route:
        return int(st.session_state.get(MAIN_TRANSITION_GEN_KEY) or 0)
    gen = _next_transition_gen()
    inject_main_transition_css(gen)
    st.session_state[MAIN_TRANSITION_ACTIVE_KEY] = True
    st.session_state[MAIN_TRANSITION_ROUTE_KEY] = route
    st.session_state[DELAY_ROUTE_BODY_REVEAL_KEY] = True
    return gen


def mount_main_transition_loading(target_route: str, *, paint_markup: bool = False) -> None:
    """Prepare the main-content transition; optionally paint a fallback owner.

    Prefer ``paint_markup=False`` and let ``render_unified_shell`` embed the
    Opening… overlay beside the topbar. ``paint_markup=True`` remains for
    call sites / tests that do not go through the shell.
    """
    route = str(target_route or "").strip()
    if not route:
        return
    gen = prepare_main_transition(route)
    if not paint_markup:
        return
    markup = route_loading_markup(route, gen)
    container = getattr(st, "container", None)
    if callable(container):
        try:
            with container(key="cadivor_main_transition_owner"):
                st.markdown(markup, unsafe_allow_html=True)
            return
        except TypeError:
            with container():
                st.markdown(markup, unsafe_allow_html=True)
            return
    st.markdown(markup, unsafe_allow_html=True)


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
