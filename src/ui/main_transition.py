"""Single main-content transition owner for authenticated Cadivor routes.

Continuity contract (login → first content, and every authenticated navigation):
first admission or explicitly blocking work gets a readable progress surface;
ordinary in-app navigation keeps a compact progress surface over the main
panel until the complete destination is ready. It never exposes the empty or
partially rendered workspace during a Streamlit rerun.

This module owns ONLY the main-panel loading surface. Foundation topbar and
sidebar must stay fully sharp and normal-opacity for the entire transition.
"""
from __future__ import annotations

import html
import time
from typing import Any, MutableMapping

import streamlit as st

PRESENTED_ROUTE_KEY = "cadivor_presented_route"
DELAY_ROUTE_BODY_REVEAL_KEY = "cadivor_delay_route_body_reveal"
MAIN_TRANSITION_ACTIVE_KEY = "cadivor_main_transition_active"
MAIN_TRANSITION_ROUTE_KEY = "cadivor_main_transition_route"
MAIN_TRANSITION_GEN_KEY = "cadivor_main_transition_gen"
MAIN_TRANSITION_KIND_KEY = "cadivor_main_transition_kind"
MAIN_TRANSITION_PREVIOUS_ROUTE_KEY = "cadivor_main_transition_previous_route"
OPENING_STARTED_AT_KEY = "cadivor_opening_started_at"
OPENING_ROUTE_KEY = "cadivor_opening_route"
BOM_ANALYSIS_TRANSITION_KEY = "cadivor_bom_analysis_transition"


def get_presented_route(session_state: MutableMapping[str, Any] | None = None) -> str:
    state = session_state if session_state is not None else st.session_state
    return str(state.get(PRESENTED_ROUTE_KEY) or "").strip()


def arm_main_transition(
    session_state: MutableMapping[str, Any],
    target_route: str,
    *,
    kind: str = "blocking",
    previous_route: str = "",
) -> None:
    """Arm a main-content transition before target chrome commits on the next run.

    Clears the previously presented route so stale body ownership cannot survive
    into the target-chrome run.
    """
    route = str(target_route or "").strip()
    if not route:
        return
    transition_kind = (
        "navigation"
        if str(kind or "").strip().casefold() == "navigation"
        else "blocking"
    )
    # Analysis handoffs can arm the same destination more than once while
    # Streamlit consumes an upload, submits the worker, and paints progress.
    # Keep that transition intact instead of resetting its body marker on each
    # intermediate rerun.
    already_armed = (
        bool(session_state.get(MAIN_TRANSITION_ACTIVE_KEY))
        and str(session_state.get(MAIN_TRANSITION_ROUTE_KEY) or "").strip() == route
    )
    if already_armed:
        session_state[DELAY_ROUTE_BODY_REVEAL_KEY] = True
        return
    prior = str(
        previous_route or session_state.get(PRESENTED_ROUTE_KEY) or ""
    ).strip()
    session_state.pop(PRESENTED_ROUTE_KEY, None)
    session_state[MAIN_TRANSITION_ACTIVE_KEY] = True
    session_state[MAIN_TRANSITION_ROUTE_KEY] = route
    session_state[MAIN_TRANSITION_KIND_KEY] = transition_kind
    session_state[MAIN_TRANSITION_PREVIOUS_ROUTE_KEY] = prior
    session_state[DELAY_ROUTE_BODY_REVEAL_KEY] = True


def arm_bom_analysis_transition(
    session_state: MutableMapping[str, Any],
    mode: str = "start",
) -> None:
    """Keep analysis progress on the page instead of covering the workspace.

    The progress card near the top of BOM Analyzer is the loading surface.
    A blocking full-workspace cover hides that card and recenters a second
    "Starting BOM analysis…" message.
    """
    normalized_mode = str(mode or "start").strip().casefold()
    if normalized_mode not in {"start", "rerun"}:
        normalized_mode = "start"
    session_state[BOM_ANALYSIS_TRANSITION_KEY] = normalized_mode
    session_state[MAIN_TRANSITION_ACTIVE_KEY] = False
    session_state[MAIN_TRANSITION_KIND_KEY] = ""
    session_state.pop(DELAY_ROUTE_BODY_REVEAL_KEY, None)
    session_state.pop(OPENING_STARTED_AT_KEY, None)
    session_state.pop(OPENING_ROUTE_KEY, None)


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


def should_paint_opening_overlay(
    *,
    needs_transition: bool,
    target_route: str = "",
    session_state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Keep one transition owner until the destination body is ready.

    The owner renders as a compact main-panel progress surface for in-app
    navigation, and as a full loading card for first admission or blocking work.
    """
    del target_route, session_state
    return bool(needs_transition)


def _next_transition_gen() -> int:
    try:
        current = int(st.session_state.get(MAIN_TRANSITION_GEN_KEY) or 0)
    except (TypeError, ValueError):
        current = 0
    # Session state is cleared at logout, but Streamlit may retain the old
    # page-body marker in the browser DOM until the next auth surface replaces
    # it. A small counter would restart at 1 and could collide with that stale
    # marker, causing the fresh Opening layer to hide itself immediately.
    # Wall-clock nanoseconds provide a browser-DOM-unique generation even after
    # logout, session reset, or a user switch; retain monotonicity within a run.
    nxt = max(current + 1, time.time_ns())
    st.session_state[MAIN_TRANSITION_GEN_KEY] = nxt
    return nxt


def inject_main_transition_css(transition_gen: int) -> None:
    """Inject the sole transition-owner stylesheet for this generation."""
    gen = int(transition_gen)
    st.markdown(
        f"""
        <style id="cadivor-main-transition-css-{gen}"
               data-cadivor-layout-style="true"
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
          right:auto!important;
          top:var(--cv-foundation-top,64px)!important;
          bottom:0!important;
          width:calc(100vw - var(--cv-foundation-rail,228px))!important;
          max-width:none!important;
          min-width:0!important;
          min-height:calc(100vh - var(--cv-foundation-top,64px))!important;
          min-height:calc(100dvh - var(--cv-foundation-top,64px))!important;
          height:auto!important;
          /* Above in-page menus/popovers so outgoing controls cannot flash
             over the destination loader. Persistent rail and topbar sit outside
             this main-panel surface and remain available. */
          z-index:2147483000!important;
          margin:0!important;border-radius:0!important;border:0!important;
          padding:0!important;
          background:#F5F7FB!important;
          box-shadow:none!important;
          font-family:Inter,system-ui,sans-serif!important;
          overflow:hidden!important;
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
          isolation:isolate!important;
          clip-path:inset(0)!important;
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
        /* Route changes keep the shell and the workspace width. The status
           chip sits at the top of the workspace and does not paint an opaque
           mask over the page. Hiding every new element until the body marker
           left a blank workspace for the whole rerun. */
        .cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"]{{
          box-sizing:border-box!important;position:fixed!important;
          left:calc(var(--cv-foundation-rail,296px) + 28px)!important;
          right:auto!important;bottom:auto!important;
          top:calc(var(--cv-foundation-top,64px) + 16px)!important;
          width:auto!important;height:auto!important;
          min-height:0!important;max-height:none!important;
          margin:0!important;padding:0!important;border:0!important;border-radius:0!important;
          display:flex!important;align-items:flex-start!important;justify-content:flex-start!important;
          background:transparent!important;overflow:visible!important;
          box-shadow:none!important;pointer-events:none!important;opacity:1!important;
          visibility:visible!important;z-index:2147483000!important;clip-path:none!important
        }}
        @media(max-width:700px){{
          .cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"]{{
            left:16px!important
          }}
        }}
        .cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"] .cv-main-transition-card{{
          display:flex!important;align-items:center!important;gap:12px!important;
          box-sizing:border-box!important;width:auto!important;min-width:190px!important;
          padding:14px 18px!important;border:1px solid #E4EAF3!important;border-radius:14px!important;
          background:#FFFFFF!important;box-shadow:0 8px 24px rgba(15,23,42,.06)!important;
          color:#334155!important;font-size:13px!important;font-weight:650!important;
          text-align:left!important
        }}
        .cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"] .cv-main-transition-mark{{
          box-sizing:border-box!important;display:grid!important;place-items:center!important;
          flex:0 0 32px!important;width:32px!important;height:32px!important;
          margin:0!important;border-radius:9px!important;
          background:#2563EB!important;color:#FFFFFF!important;
          font-size:15px!important;font-weight:850!important;letter-spacing:-.02em!important
        }}
        .cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"] .cv-main-transition-label{{
          flex:1 1 auto!important;min-width:0!important;white-space:nowrap!important
        }}
        .cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"] .cv-main-transition-progress{{
          position:relative!important;left:auto!important;right:auto!important;top:auto!important;
          display:block!important;flex:0 0 44px!important;width:44px!important;height:3px!important;
          margin:0!important;border-radius:999px!important;background:#E8EEF7!important;overflow:hidden!important
        }}
        .cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"] .cv-main-transition-progress>i{{
          display:block!important;width:42%!important;height:3px!important;border-radius:999px!important;
          background:#2563EB!important;animation:cv-main-transition-progress 1.1s ease-in-out infinite
        }}
        @keyframes cv-main-transition-progress{{
          0%{{transform:translateX(-120%)}}
          100%{{transform:translateX(280%)}}
        }}
        /* Keep rail glyphs at their normal size while route styles and the
           destination DOM are being swapped during a Streamlit rerun. */
        body:has([data-cadivor-main-transition="1"])
          [class*="st-key-cv_foundation_navigation"] .stButton>button::before{{
          box-sizing:border-box!important;flex:0 0 16px!important;width:16px!important;
          height:16px!important;max-width:16px!important;max-height:16px!important;
          background-size:16px 16px!important
        }}
        body:has([data-cadivor-main-transition="1"])
          [class*="st-key-cv_foundation_navigation"] .stButton>button svg{{
          box-sizing:border-box!important;flex:0 0 16px!important;width:16px!important;
          height:16px!important;max-width:16px!important;max-height:16px!important
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
          [class*="st-key-cv_foundation_navigation"]:not([data-stale="true"])
        )
          [data-stale="true"]:has([class*="st-key-cv_foundation_nav_"]),
        body:has([data-cadivor-main-transition="1"]):has(
          [class*="st-key-cv_foundation_navigation"]:not([data-stale="true"])
        )
          [data-stale="true"] [class*="st-key-cv_foundation_nav_"],
        body:has([data-cadivor-main-transition="1"]):has(
          [class*="st-key-cv_foundation_navigation"]:not([data-stale="true"])
        )
          [data-stale="true"]:has(.cv-foundation-nav-group),
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
        /* Freeze stale controls while a route is changing, but retain the
           previous page visually until the destination body is ready. */
        body:has([data-cadivor-main-transition="1"])
          section[data-testid="stMain"] [data-stale="true"]:not(
            :has([data-cadivor-transition-host])
          ):not(:has([class*="st-key-cv_foundation_"])){{
          visibility:visible!important;opacity:1!important;filter:none!important;
          pointer-events:none!important
        }}
        /* Only after the destination body marker arrives may the old route
           wrappers be removed. This prevents a blank frame during reruns. */
        body:has([data-cadivor-page-body-gen="{gen}"])
          section[data-testid="stMain"] [data-stale="true"]:not(
            :has([data-cadivor-transition-host])
          ):not(:has([data-cadivor-topbar-flow-host])):not(
            :has([class*="st-key-cv_foundation_"])
          ){{
          display:none!important;visibility:hidden!important;opacity:0!important;
          pointer-events:none!important
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
          overflow:visible!important;transform:none!important;filter:none!important;
          perspective:none!important;contain:none!important
        }}
        /* st.html paints directly into the app DOM. Keep its ancestry from
           becoming a containing block for the fixed, viewport-sized cover. */
        body:has([data-cadivor-transition-host="cadivor-main-transition"])
          section[data-testid="stMain"],
        body:has([data-cadivor-transition-host="cadivor-main-transition"])
          section[data-testid="stMain"] [data-testid="stMainBlockContainer"],
        body:has([data-cadivor-transition-host="cadivor-main-transition"])
          section[data-testid="stMain"] [data-testid="stVerticalBlock"]:has(
            [data-cadivor-transition-host="cadivor-main-transition"]
          ){{
          transform:none!important;filter:none!important;perspective:none!important;
          contain:none!important
        }}
        /* Style inject ElementContainer only — keep <style> active. */
        div[data-testid="stElementContainer"]:has(
          style[id^="cadivor-main-transition-css-"]
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
        /* Retire this generation only after its body is ready and navigation scroll has settled.
           Older route owners remain generation-scoped so stale CSS cannot release a new cover. */
        [data-stale="true"] .cv-main-transition.cv-route-loading:not([data-cadivor-transition-gen="{gen}"]),
        [data-stale="true"][data-cadivor-main-transition="1"]:not([data-cadivor-transition-gen="{gen}"]),
        body:has([data-cadivor-page-body-gen="{gen}"][data-cadivor-page-body-release-gen="{gen}"])
          .cv-main-transition.cv-route-loading[data-cadivor-transition-gen="{gen}"] {{
          display:none!important;visibility:hidden!important;pointer-events:none!important;
          opacity:0!important;z-index:-1!important
        }}
        body:not(:has([data-cadivor-page-body-gen="{gen}"]))
          [data-cadivor-main-transition="1"][data-cadivor-transition-gen="{gen}"]:not([data-cadivor-transition-kind="navigation"]) {{
          pointer-events:auto!important
        }}
        body:has([data-cadivor-page-body-gen="{gen}"][data-cadivor-page-body-release-gen="{gen}"])
          [data-cadivor-main-transition="1"][data-cadivor-transition-gen="{gen}"],
        body:has([data-cadivor-page-body-gen="{gen}"][data-cadivor-page-body-release-gen="{gen}"])
          [data-cadivor-transition-host="cadivor-main-transition"][data-cadivor-transition-gen="{gen}"],
        body:has([data-cadivor-page-body-gen="{gen}"][data-cadivor-page-body-release-gen="{gen}"])
          div[data-testid="stElementContainer"]:has(
            [data-cadivor-main-transition="1"][data-cadivor-transition-gen="{gen}"]
          ):not(:has([data-cadivor-topbar-flow-host])):not(:has([class*="st-key-cv_foundation_"])){{
          display:none!important;visibility:hidden!important;pointer-events:none!important;
          opacity:0!important;z-index:-1!important;
          height:0!important;min-height:0!important;max-height:0!important;
          margin:0!important;padding:0!important;border:0!important;overflow:hidden!important
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    # Keep each stylesheet's selectors generation-scoped and let Streamlit's
    # React tree retire stale style hosts. An async script that toggles
    # CSSStyleSheet.disabled can run after a later generation is mounted and
    # disable the current transition stylesheet, leaving its cover visible.


def route_loading_markup(target_route: str, transition_gen: int) -> str:
    """Return the in-main target-route loading HTML (no nested <style>)."""
    safe_route = html.escape(str(target_route or "").strip() or "workspace")
    gen = int(transition_gen)
    transition_kind = str(
        st.session_state.get(MAIN_TRANSITION_KIND_KEY) or "blocking"
    ).strip().casefold()
    if transition_kind not in {"navigation", "blocking"}:
        transition_kind = "blocking"
    if transition_kind == "navigation":
        # Give the route cover its complete viewport geometry inline. The
        # shared stylesheet still refines it, but a slow stylesheet delta can
        # no longer expose the outgoing or partially mounted page.
        return f"""
        <div data-cadivor-transition-host="cadivor-main-transition"
             data-cadivor-transition-gen="{gen}"
             data-cadivor-transition-kind="navigation"
             data-testid="cadivor-main-transition-host">
          <div class="cv-main-transition cv-route-loading"
               data-cadivor-main-transition="1"
               data-cadivor-route-loading="{safe_route}"
               data-cadivor-transition-kind="navigation"
               data-cadivor-transition-gen="{gen}"
               data-testid="cadivor-route-loading"
               style="box-sizing:border-box;position:fixed;left:calc(var(--cv-foundation-rail,296px) + 28px);top:calc(var(--cv-foundation-top,64px) + 16px);right:auto;bottom:auto;width:auto;height:auto;z-index:2147483000;display:flex;align-items:flex-start;justify-content:flex-start;margin:0;padding:0;background:transparent;overflow:visible;pointer-events:none;font-family:Inter,system-ui,sans-serif"
               role="status" aria-label="Opening {safe_route}" aria-live="polite">
            <div class="cv-main-transition-card"
                 style="box-sizing:border-box;display:flex;align-items:center;gap:12px;min-width:190px;padding:14px 18px;border:1px solid #E4EAF3;border-radius:14px;background:#FFFFFF;box-shadow:0 8px 24px rgba(15,23,42,.06);color:#334155;font-size:13px;font-weight:650;text-align:left">
              <span class="cv-main-transition-mark" aria-hidden="true"
                   style="box-sizing:border-box;display:grid;place-items:center;flex:0 0 32px;width:32px;height:32px;margin:0;border-radius:9px;background:#2563EB;color:#FFFFFF;font-size:15px;font-weight:850;letter-spacing:-.02em">C</span>
              <span class="cv-main-transition-label">Opening {safe_route}…</span>
              <div class="cv-main-transition-progress" aria-hidden="true"
                   style="position:relative;display:block;flex:0 0 44px;width:44px;height:3px;margin:0;border-radius:999px;background:#E8EEF7;overflow:hidden">
                <i style="display:block;width:42%;height:3px;border-radius:999px;background:#2563EB"></i>
              </div>
            </div>
          </div>
        </div>
        """
    mode = str(st.session_state.get(BOM_ANALYSIS_TRANSITION_KEY) or "").strip().casefold()
    if safe_route == "BOM Analyzer" and mode in {"start", "rerun"}:
        # Analysis progress stays in the page card. Do not paint the
        # full-workspace cover for the start or rerun handoff.
        return ""
    title = f"Opening {safe_route}…"
    description = "Preparing this page in your Cadivor workspace."
    return f"""
        <div data-cadivor-transition-host="cadivor-main-transition"
             data-cadivor-transition-gen="{gen}"
             data-cadivor-transition-kind="blocking"
             data-testid="cadivor-main-transition-host">
        <div class="cv-main-transition cv-route-loading"
             data-cadivor-main-transition="1"
             data-cadivor-route-loading="{safe_route}"
             data-cadivor-transition-kind="blocking"
             data-cadivor-transition-gen="{gen}"
             data-testid="cadivor-route-loading"
             style="box-sizing:border-box;position:fixed;left:var(--cv-foundation-rail,0px);right:0;top:var(--cv-foundation-top,64px);bottom:0;width:calc(100vw - var(--cv-foundation-rail,0px));height:calc(100dvh - var(--cv-foundation-top,64px));min-height:calc(100vh - var(--cv-foundation-top,64px));z-index:2147483000;display:flex;align-items:center;justify-content:center;margin:0;padding:0;background:#F5F7FB;overflow:hidden;font-family:Inter,system-ui,sans-serif"
             role="status" aria-live="polite">
          <div class="cv-main-transition-card"
               style="box-sizing:border-box;width:min(420px,calc(100% - 48px));padding:28px 28px 24px;border:1px solid #D6E3F5;border-radius:18px;background:#FFFFFF;box-shadow:0 12px 28px rgba(15,23,42,.06);text-align:center">
            <div class="cv-main-transition-mark" aria-hidden="true"
                 style="width:40px;height:40px;margin:0 auto 14px;border-radius:12px;display:grid;place-items:center;background:#2563EB;color:#FFFFFF;font-size:18px;font-weight:850;letter-spacing:-.02em">C</div>
            <strong style="display:block;color:#0F172A;font-size:18px;font-weight:850;letter-spacing:-.02em;margin:0 0 6px">{title}</strong>
            <p style="margin:0 0 16px;color:#64748B;font-size:13px;line-height:1.45;font-weight:650">{description}</p>
            <div class="cv-main-transition-progress" aria-hidden="true"
                 style="height:4px;border-radius:999px;background:#E8EEF7;overflow:hidden"><i style="display:block;height:100%;width:42%;border-radius:999px;background:#2563EB"></i></div>
          </div>
        </div>
        </div>
        """


def mark_opening_started(route: str) -> None:
    """Record when Opening became the visible frame. Route only; no user data."""
    st.session_state[OPENING_STARTED_AT_KEY] = time.perf_counter()
    st.session_state[OPENING_ROUTE_KEY] = str(route or "").strip()


def _infer_unarmed_transition_kind(target_route: str, presented_route: str) -> str:
    """Use the compact navigation cover when an existing route changes unarmed."""
    target = str(target_route or "").strip()
    presented = str(presented_route or "").strip()
    if target and presented and target != presented:
        return "navigation"
    return ""


def prepare_main_transition(target_route: str) -> int:
    """Arm session keys + stylesheet; reuse an active transition generation."""
    route = str(target_route or "").strip()
    if not route:
        return int(st.session_state.get(MAIN_TRANSITION_GEN_KEY) or 0)
    state = st.session_state
    try:
        current_gen = int(state.get(MAIN_TRANSITION_GEN_KEY) or 0)
    except (TypeError, ValueError):
        current_gen = 0
    same_open_transition = (
        bool(state.get(MAIN_TRANSITION_ACTIVE_KEY))
        and str(state.get(MAIN_TRANSITION_ROUTE_KEY) or "").strip() == route
        and str(state.get(OPENING_ROUTE_KEY) or "").strip() == route
        and state.get(OPENING_STARTED_AT_KEY) is not None
        and current_gen > 0
    )
    if same_open_transition:
        # The shell runs again during upload parsing and worker setup. Replacing
        # the CSS generation before its successor paints briefly exposes the
        # stale route body; one generation must own the entire handoff.
        inject_main_transition_css(current_gen)
        state[MAIN_TRANSITION_ACTIVE_KEY] = True
        state[MAIN_TRANSITION_ROUTE_KEY] = route
        state[DELAY_ROUTE_BODY_REVEAL_KEY] = True
        return current_gen

    if not state.get(MAIN_TRANSITION_ACTIVE_KEY):
        previous_route = get_presented_route(state)
        inferred_kind = _infer_unarmed_transition_kind(route, previous_route)
        if inferred_kind:
            state[MAIN_TRANSITION_KIND_KEY] = inferred_kind
            state[MAIN_TRANSITION_PREVIOUS_ROUTE_KEY] = previous_route

    mark_opening_started(route)
    gen = _next_transition_gen()
    inject_main_transition_css(gen)
    state[MAIN_TRANSITION_ACTIVE_KEY] = True
    state[MAIN_TRANSITION_ROUTE_KEY] = route
    state[DELAY_ROUTE_BODY_REVEAL_KEY] = True
    return gen


def _paint_main_transition_markup(route: str, gen: int) -> None:
    """Paint the route cover in the app DOM without an asynchronous iframe.

    ``components.html`` mounts an iframe and runs its script only after the
    iframe handshake. During that delay Streamlit can mark the outgoing route
    stale and begin replacing its widgets before the cover exists. ``st.html``
    inserts this static HTML directly into the app DOM, so the cover and its
    inline fallback styles arrive in the same Streamlit delta.
    """
    markup = route_loading_markup(route, gen)
    if str(markup or "").strip():
        st.html(route_loading_markup(route, gen))


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
        # The application shell prepares this stylesheet before rendering the
        # unified shell. Re-injecting it here (and in the shell itself) creates
        # duplicate style hosts on every Streamlit rerun, which can briefly
        # expose the outgoing page while the browser replaces those hosts.
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


def should_defer_navigation_reveal(
    session_state: MutableMapping[str, Any],
    *,
    force: bool = False,
) -> bool:
    """Keep a navigation cover until the destination renderer finishes.

    Early reveal calls identify a distinctive page body, but Streamlit emits
    subsequent widgets as the script continues. During navigation, defer those
    calls so the user sees one stable loading surface until the route reaches
    its final page stop. Blocking and first-admission flows keep their existing
    early-reveal behavior.
    """
    if force:
        return False
    return bool(
        session_state.get(DELAY_ROUTE_BODY_REVEAL_KEY)
        and str(session_state.get(MAIN_TRANSITION_KIND_KEY) or "").strip().casefold()
        == "navigation"
    )


def reveal_main_transition(route: str = "") -> None:
    """Reveal distinctive target content and collapse the main transition owner."""
    transition_kind = str(
        st.session_state.get(MAIN_TRANSITION_KIND_KEY) or ""
    ).strip().casefold()
    safe_route = str(
        route or st.session_state.get(MAIN_TRANSITION_ROUTE_KEY) or get_presented_route() or ""
    ).strip()
    if safe_route:
        st.session_state[PRESENTED_ROUTE_KEY] = safe_route
    st.session_state[MAIN_TRANSITION_ACTIVE_KEY] = False
    st.session_state[MAIN_TRANSITION_KIND_KEY] = ""
    st.session_state.pop(MAIN_TRANSITION_PREVIOUS_ROUTE_KEY, None)
    st.session_state.pop(DELAY_ROUTE_BODY_REVEAL_KEY, None)
    st.session_state.pop(BOM_ANALYSIS_TRANSITION_KEY, None)
    try:
        started = st.session_state.pop(OPENING_STARTED_AT_KEY, None)
        logged_route = st.session_state.pop(OPENING_ROUTE_KEY, None) or safe_route
        if started is not None:
            from src.performance_timing import log_opening_reveal

            log_opening_reveal(
                logged_route or safe_route,
                (time.perf_counter() - float(started)) * 1000.0,
            )
    except Exception:
        pass
    escaped = html.escape(safe_route or "1")
    try:
        gen = int(st.session_state.get(MAIN_TRANSITION_GEN_KEY) or 0)
    except (TypeError, ValueError):
        gen = 0
    release_attr = (
        f'data-cadivor-page-body-release-gen="{gen}" '
        if transition_kind != "navigation"
        else ""
    )
    try:
        # st.html inserts this marker directly into the application document.
        # Keep the ready signal as a real DOM node instead of a JavaScript
        # body mutation: the release selector can then observe it synchronously
        # even when inline scripts are delayed or blocked by the browser.
        # Its generation guard prevents an older route from dismissing a newer
        # transition cover.
        st.html(
            f'<div data-cadivor-page-body="{escaped}" '
            f'data-cadivor-page-body-gen="{gen}" '
            f'{release_attr}'
            f'data-cadivor-transition-gen="{gen}" aria-hidden="true" '
            'style="position:absolute;width:1px;height:1px;margin:-1px;border:0;'
            'padding:0;overflow:hidden;clip:rect(0,0,0,0)"></div>'
        )
    except Exception:
        pass
