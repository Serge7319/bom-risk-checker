"""Cadivor authenticated application shell.

Launch foundation repair: one custom persistent navigation rail and one main
workspace offset. The native Streamlit sidebar is deliberately not used.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Callable

import streamlit as st

from src.urls import internal_app_href
from src.ui.navigation import navigate_to


NAV_GROUPS = (
    ("Analyze", (
        ("Dashboard", "dashboard", "Dashboard"),
        ("BOM Analyzer", "bom", "BOM Analyzer"),
        ("Alternative Finder", "alternatives", "Alternative Finder"),
        ("Compare Parts", "compare", "Compare Parts"),
        ("Datasheet Q&A", "datasheet-qa", "Datasheet Q&A"),
        ("Design Impact", "impact", "Design Impact Analyzer"),
    )),
    ("Decide", (
        ("Engineering Decisions", "decisions", "Engineering Decisions"),
        ("Procurement Advisor", "procurement", "Procurement Advisor"),
        ("Cost Optimization", "cost", "Cost Optimization"),
        ("Supply Scenario", "scenario", "Supply Risk Scenario"),
    )),
    ("Monitor", (
        ("Monitoring", "monitoring", "Monitoring"),
        ("Portfolio Intelligence", "portfolio", "Portfolio Intelligence"),
        ("Reports", "reports", "Reports"),
    )),
    ("Workspace", (
        ("Settings", "settings", "Settings"),
        ("Resources", "help", "Help"),
    )),
)


def _load_css() -> str:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "app_shell.css"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def inject_unified_shell_css() -> None:
    css = _load_css()
    if css:
        st.markdown(
            f"<style id='cadivor-foundation-repair-css'>{css}</style>",
            unsafe_allow_html=True,
        )
    st.markdown(
        """
        <style id="cadivor-native-navigation-links">
        .cv-native-nav-button{display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;min-width:132px;max-width:100%;min-height:38px;padding:0 14px;border-radius:8px;background:#2563eb;color:#fff!important;font:700 13px/1.1 Inter,system-ui,sans-serif;white-space:nowrap;text-decoration:none!important;box-shadow:0 7px 16px rgba(37,99,235,.18)}
        .cv-native-nav-button:hover{background:#1d4ed8;color:#fff!important;text-decoration:none!important}.cv-native-nav-button--wide{display:inline-flex;width:auto;min-width:160px}.cv-native-nav-button--secondary{background:#fff;color:#1e3a5f!important;border:1px solid #b8c8df;box-shadow:none}.cv-native-nav-button--secondary:hover{background:#f4f8ff;color:#1e3a5f!important}
        .cv-foundation-nav-link{display:flex;align-items:center;width:100%;min-height:36px;padding:0 12px;border-radius:8px;color:#dbeafe!important;font:650 13px/1.1 Inter,system-ui,sans-serif;text-decoration:none!important}.cv-foundation-nav-link:hover{background:rgba(71,112,190,.28);color:#fff!important;text-decoration:none!important}.cv-foundation-nav-link.is-active{background:#173c81;color:#fff!important}
        </style>
        """,
        unsafe_allow_html=True,
    )


def paint_authenticated_continuity_shell(*, page: str = "Dashboard") -> None:
    """Paint fixed Cadivor topbar chrome during auth→runtime handoff only.

    Must never reserve vertical space in the main document flow and must never
    insert a global page skeleton. The durable ``render_unified_shell`` topbar
    replaces this chrome; continuity hosts collapse once it is present.
    """
    inject_unified_shell_css()
    safe_page = html.escape(str(page or "Dashboard").strip() or "Dashboard")
    st.markdown(
        f"""
        <div class="cv-foundation-topbar cv-foundation-continuity"
             data-testid="cadivor-continuity-shell"
             aria-label="Cadivor application header">
          <div class="cv-foundation-brand">
            <span class="cv-foundation-brand-mark">C</span>
            <span class="cv-foundation-brand-copy">
              <strong>Cadivor</strong><small>Engineering Intelligence</small>
            </span>
          </div>
          <div class="cv-foundation-page-context">
            <strong>{safe_page}</strong>
          </div>
        </div>
        <style id="cadivor-continuity-shell-css">
        /* Continuity topbar is fixed chrome only — its Streamlit host must not
           push page content downward. */
        div[data-testid="stElementContainer"]:has(.cv-foundation-continuity),
        div[data-testid="stElementContainer"]:has([data-testid="cadivor-continuity-shell"]),
        div.element-container:has(.cv-foundation-continuity){{
          height:0!important;min-height:0!important;max-height:0!important;
          margin:0!important;padding:0!important;border:0!important;
          overflow:hidden!important;opacity:1
        }}
        /* Once durable shell exists, remove continuity entirely. */
        body:has(.cv-foundation-topbar:not(.cv-foundation-continuity)) .cv-foundation-continuity,
        body:has(.cv-foundation-topbar:not(.cv-foundation-continuity)) [data-testid="cadivor-continuity-shell"]{{
          display:none!important;visibility:hidden!important;pointer-events:none!important;
          height:0!important;overflow:hidden!important
        }}
        body:has(.cv-foundation-topbar:not(.cv-foundation-continuity))
          div[data-testid="stElementContainer"]:has(.cv-foundation-continuity),
        body:has(.cv-foundation-topbar:not(.cv-foundation-continuity))
          div[data-testid="stElementContainer"]:has([data-testid="cadivor-continuity-shell"]),
        body:has(.cv-foundation-topbar:not(.cv-foundation-continuity))
          div.element-container:has(.cv-foundation-continuity){{
          display:none!important;height:0!important;min-height:0!important;
          margin:0!important;padding:0!important;overflow:hidden!important
        }}
        /* Never leave a stray global skeleton band above page titles. */
        body:has(.cv-foundation-topbar:not(.cv-foundation-continuity)) .cv56-skeleton-page,
        body:has(.cv-foundation-topbar:not(.cv-foundation-continuity))
          div[data-testid="stElementContainer"]:has(.cv56-skeleton-page){{
          display:none!important;height:0!important;min-height:0!important;
          margin:0!important;padding:0!important;overflow:hidden!important
        }}
        html,body,.stApp,[data-testid="stAppViewContainer"]{{
          background:#F5F7FB!important
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _escape(value: object) -> str:
    return html.escape(str(value or ""))


def _commit_navigation(page: str) -> None:
    """Commit the route before Streamlit performs the widget rerun.

    Using a widget callback avoids the former click -> rerun -> explicit rerun
    sequence that could briefly expose an incomplete/public render.
    """
    navigate_to(page, _rerun=False)
    st.session_state.pop("cadivor_route_transition", None)
    st.session_state["cadivor_profile_menu_open"] = False


def render_unified_shell(
    *,
    current_page: str,
    profile: dict,
    workspace_name: str,
    plan_name: str,
    usage_summary: str,
    saved_summary: str,
    is_admin: bool,
    navigate: Callable[..., None],
    clear_analysis: Callable[[], None],
    request_logout: Callable[[], None],
) -> None:
    """Render exactly one top bar and one custom fixed navigation rail."""
    inject_unified_shell_css()

    full_name = profile.get("full_name") or profile.get("email") or "Cadivor user"
    email = profile.get("email") or ""
    initials = profile.get("initials") or "C"
    secondary = profile.get("company") or profile.get("role_title") or plan_name

    st.markdown(
        f"""
        <div class="cv-foundation-topbar" aria-label="Cadivor application header">
          <div class="cv-foundation-brand">
            <span class="cv-foundation-brand-mark">C</span>
            <span class="cv-foundation-brand-copy">
              <strong>Cadivor</strong><small>Engineering Intelligence</small>
            </span>
          </div>
          <div class="cv-foundation-page-context">
            <strong>{_escape(current_page)}</strong>
            <span class="cv-foundation-search cadivor-search-pill" role="button" tabindex="0" aria-label="Open Search Cadivor command center">Search Cadivor <kbd>⌘K</kbd></span>
          </div>
          <div class="cv-foundation-profile-copy">
            <small>Workspace</small><strong>{_escape(full_name)}</strong><em>{_escape(secondary)}</em>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="cv_foundation_profile_menu"):
        with st.popover(initials, use_container_width=False):
            st.markdown(
                f"""<div class="cv-foundation-account-head"><b>{_escape(full_name)}</b><span>{_escape(email)}</span><small>{_escape(workspace_name)}</small></div>""",
                unsafe_allow_html=True,
            )
            st.markdown('<div class="cv-profile-menu-group">Account</div>', unsafe_allow_html=True)
            st.button("Profile & preferences", key="cv_foundation_profile", use_container_width=True, on_click=_commit_navigation, args=("Settings",))
            st.button("Plan & billing", key="cv_foundation_billing", use_container_width=True, on_click=_commit_navigation, args=("Pricing",))
            st.markdown('<div class="cv-profile-menu-group">Workspace</div>', unsafe_allow_html=True)
            st.button("Workspace settings", key="cv_foundation_workspace", use_container_width=True, on_click=_commit_navigation, args=("Settings",))
            if is_admin:
                st.button("Resources", key="cv_foundation_help", use_container_width=True, on_click=_commit_navigation, args=("Help",))
            st.divider()
            def _commit_signout() -> None:
                # Streamlit runs on_click callbacks before the widget rerun.  By
                # committing logout here, the first click cannot be consumed by
                # the popover closing before authentication state changes.
                if st.session_state.get("cadivor_logout_in_progress"):
                    return
                st.session_state["cadivor_logout_in_progress"] = True
                st.session_state["cadivor_explicit_logout"] = True
                st.session_state["cadivor_profile_menu_open"] = False
                request_logout()

            st.button(
                "Sign out",
                key="cv_foundation_signout",
                type="secondary",
                use_container_width=True,
                disabled=bool(st.session_state.get("cadivor_logout_in_progress")),
                on_click=_commit_signout,
            )

    with st.container(key="cv_foundation_navigation"):
        st.markdown(
            f"""
            <div class="cv-foundation-workspace" aria-label="Current workspace">
              <span class="cv-foundation-workspace-mark">{_escape((workspace_name or 'C')[:1].upper())}</span>
              <span class="cv-foundation-workspace-copy">
                <small>Workspace</small>
                <strong>{_escape(workspace_name or 'Cadivor Workspace')}</strong>
                <em>{_escape(plan_name)} plan</em>
              </span>
              <span class="cv-foundation-workspace-chevron" aria-hidden="true">⌄</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for group_name, configured_rows in NAV_GROUPS:
            rows = configured_rows
            if group_name == "Workspace" and is_admin:
                rows = (("Admin Console", "admin", "Admin Console"),) + rows
            elif group_name == "Workspace":
                rows = tuple(row for row in rows if row[2] != "Help")
            st.markdown(
                f'<div class="cv-foundation-nav-group">{_escape(group_name)}</div>',
                unsafe_allow_html=True,
            )
            for label, slug, destination in rows:
                active_class = " is-active" if destination == current_page else ""
                st.html(
                    f'<a class="cv-foundation-nav-link{active_class}" '
                    f'href="{html.escape(internal_app_href(destination), quote=True)}" '
                    f'target="_self">{_escape(label)}</a>'
                )

        st.markdown(
            f"""<div class="cv-foundation-plan-card"><strong>{_escape(plan_name)}</strong><span>{_escape(usage_summary)}</span><span>{_escape(saved_summary)}</span></div>""",
            unsafe_allow_html=True,
        )
        if str(plan_name).lower() in {"starter", "free", "trial", "student"}:
            st.button("Compare plans", key="cv_foundation_compare_plans", use_container_width=True, on_click=_commit_navigation, args=("Pricing",))
        if st.button(
            "＋ New BOM analysis",
            key="cv_foundation_new_analysis",
            type="primary",
            use_container_width=True,
        ):
            clear_analysis()
