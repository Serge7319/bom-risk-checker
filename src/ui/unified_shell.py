"""Cadivor authenticated application shell.

Foundation recovery: navigation is rendered in Streamlit's native sidebar so
it participates in layout instead of floating above the workspace. The top bar
is presentation-only; page content remains in the main region.
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
            f"<style id='cadivor-foundation-shell-css'>{css}</style>",
            unsafe_allow_html=True,
        )


def _escape(value: object) -> str:
    return html.escape(str(value or ""))


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
    """Render one top bar plus one native sidebar navigation shell."""
    full_name = profile.get("full_name") or profile.get("email") or "Cadivor user"
    email = profile.get("email") or ""
    initials = profile.get("initials") or "C"
    secondary = profile.get("company") or profile.get("role_title") or plan_name

    st.markdown(
        f"""
        <div class="cv-shell-topbar" aria-label="Cadivor application header">
          <div class="cv-shell-brand">
            <span class="cv-shell-brand-mark">C</span>
            <span class="cv-shell-brand-copy"><strong>Cadivor</strong><small>Engineering Intelligence</small></span>
          </div>
          <div class="cv-shell-page-context">
            <strong>{_escape(current_page)}</strong>
            <span class="cv-shell-search">Search Cadivor <kbd>⌘K</kbd></span>
          </div>
          <div class="cv-shell-profile-copy">
            <small>Workspace</small><strong>{_escape(full_name)}</strong><em>{_escape(secondary)}</em>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="cv_shell_profile_menu"):
        with st.popover(initials, use_container_width=False):
            st.markdown(
                f"""<div class="cv-shell-account-head"><b>{_escape(full_name)}</b><span>{_escape(email)}</span><small>{_escape(workspace_name)}</small></div>""",
                unsafe_allow_html=True,
            )
            if st.button("Profile & preferences", key="cv_shell_profile", use_container_width=True):
                navigate("Settings")
            if st.button("Workspace", key="cv_shell_workspace", use_container_width=True):
                navigate("Workspace")
            if st.button("Plan & billing", key="cv_shell_billing", use_container_width=True):
                navigate("Pricing")
            if st.button("Notifications", key="cv_shell_notifications", use_container_width=True):
                navigate("Notifications")
            if st.button("Help center", key="cv_shell_help", use_container_width=True):
                navigate("Help")
            st.divider()
            st.button(
                "Sign out",
                key="cv_shell_signout",
                type="secondary",
                use_container_width=True,
                on_click=request_logout,
            )

    with st.sidebar:
        st.markdown(
            f"""
            <div class="cv-shell-workspace">
              <span>Workspace</span>
              <strong>{_escape(workspace_name or 'Cadivor Workspace')}</strong>
              <small>{_escape(plan_name)} plan</small>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for group_name, rows in NAV_GROUPS:
            st.markdown(f'<div class="cv-shell-nav-group">{group_name}</div>', unsafe_allow_html=True)
            for label, slug, destination in rows:
                active = destination == current_page
                button_type = "primary" if active else "secondary"
                if st.button(
                    label,
                    key=f"cv_shell_nav_{slug}",
                    type=button_type,
                    use_container_width=True,
                ):
                    navigate(destination)

        st.markdown(
            f"""<div class="cv-shell-plan-card"><strong>{_escape(plan_name)}</strong><span>{_escape(usage_summary)}</span><span>{_escape(saved_summary)}</span></div>""",
            unsafe_allow_html=True,
        )
        if str(plan_name).lower() in {"starter", "free", "trial", "student"}:
            if st.button("Compare plans", key="cv_shell_compare_plans", use_container_width=True):
                navigate("Pricing")
        if st.button(
            "＋ New BOM analysis",
            key="cv_shell_new_analysis",
            type="primary",
            use_container_width=True,
        ):
            clear_analysis()
