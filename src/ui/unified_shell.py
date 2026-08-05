"""Cadivor authenticated application shell.

Launch foundation repair: one custom persistent navigation rail and one main
workspace offset. The native Streamlit sidebar is deliberately not used.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Callable

import streamlit as st


NAV_GROUPS = (
    ("Analyze", (
        ("Dashboard", "dashboard", "Dashboard"),
        ("BOM Analyzer", "bom", "BOM Analyzer"),
        ("Alternative Finder", "alternatives", "Alternative Finder"),
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
        ("Help", "help", "Help"),
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


def _escape(value: object) -> str:
    return html.escape(str(value or ""))


def _commit_navigation(page: str) -> None:
    """Commit the route before Streamlit performs the widget rerun.

    Using a widget callback avoids the former click -> rerun -> explicit rerun
    sequence that could briefly expose an incomplete/public render.
    """
    st.session_state["cadivor_route"] = page
    st.session_state["app_mode"] = page  # compatibility mirror
    st.session_state["cadivor_nav_params"] = {"page": page}
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
            <span class="cv-foundation-search" role="button" tabindex="0" aria-label="Open Search Cadivor command center">Search Cadivor <kbd>⌘K</kbd></span>
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
            st.button("Help center", key="cv_foundation_help", use_container_width=True, on_click=_commit_navigation, args=("Help",))
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
            <div class="cv-foundation-workspace" role="button" tabindex="0" aria-label="Current workspace">
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

        for group_name, rows in NAV_GROUPS:
            st.markdown(
                f'<div class="cv-foundation-nav-group">{_escape(group_name)}</div>',
                unsafe_allow_html=True,
            )
            for label, slug, destination in rows:
                button_type = "primary" if destination == current_page else "secondary"
                st.button(
                    label,
                    key=f"cv_foundation_nav_{slug}",
                    type=button_type,
                    use_container_width=True,
                    on_click=_commit_navigation,
                    args=(destination,),
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
