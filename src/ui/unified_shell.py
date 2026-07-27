"""Cadivor unified authenticated application shell.

Streamlit reruns the Python script for interactions, so the shell is rendered
deterministically on every authenticated run. All internal navigation stays
in session state; no browser navigation is used by the sidebar.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Callable, Iterable

import streamlit as st


NAV_GROUPS = (
    ("Analyze", (
        ("▦  Dashboard", "dashboard", "Dashboard"),
        ("◇  BOM Analyzer", "bom", "BOM Analyzer"),
        ("⇄  Alternative Finder", "alternatives", "Alternative Finder"),
        ("⌁  Design Impact", "impact", "Design Impact Analyzer"),
    )),
    ("Decide", (
        ("✓  Engineering Decisions", "decisions", "Engineering Decisions"),
        ("⌂  Procurement Advisor", "procurement", "Procurement Advisor"),
        ("$  Cost Optimization", "cost", "Cost Optimization"),
        ("△  Supply Scenario", "scenario", "Supply Risk Scenario"),
    )),
    ("Monitor", (
        ("◉  Monitoring", "monitoring", "Monitoring"),
        ("▤  Portfolio Intelligence", "portfolio", "Portfolio Intelligence"),
        ("▧  Reports", "reports", "Reports"),
    )),
    ("Workspace", (
        ("⚙  Settings", "settings", "Settings"),
        ("?  Help", "help", "Help"),
    )),
)


def _load_css() -> str:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "app_shell.css"
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def inject_unified_shell_css() -> None:
    css = _load_css()
    if css:
        st.markdown(f"<style id='cadivor-unified-shell-css'>{css}</style>", unsafe_allow_html=True)


def _escape(value) -> str:
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
    """Render the premium authenticated top bar and navigation rail."""
    inject_unified_shell_css()

    full_name = profile.get("full_name") or profile.get("email") or "Cadivor user"
    email = profile.get("email") or ""
    initials = profile.get("initials") or "C"
    secondary = profile.get("company") or profile.get("role_title") or plan_name

    # Static shell chrome. The interactive account menu is mounted separately
    # with a native Streamlit popover so it remains keyboard and touch friendly.
    st.markdown(
        f"""
        <div class="cv55-topbar" aria-label="Cadivor application header">
          <div class="cv55-topbar-brand">
            <span class="cv55-brand-mark">C</span>
            <span><strong>Cadivor</strong><small>Engineering Intelligence</small></span>
          </div>
          <div class="cv55-topbar-context">
            <strong>{_escape(current_page)}</strong>
            <button class="cadivor-search-pill cv55-search-trigger" type="button">Search Cadivor <kbd>⌘K</kbd></button>
          </div>
          <div class="cv552-profile-copy">
            <small>Workspace</small><strong>{_escape(full_name)}</strong><em>{_escape(secondary)}</em>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="cv552_profile_menu"):
        with st.popover(initials, use_container_width=False):
            st.markdown(
                f"""<div class="cv552-account-head"><b>{_escape(full_name)}</b><span>{_escape(email)}</span><small>{_escape(workspace_name)}</small></div>""",
                unsafe_allow_html=True,
            )
            if st.button("Profile & preferences", key="cv552_profile", use_container_width=True):
                navigate("Settings")
            if st.button("Workspace", key="cv552_workspace", use_container_width=True):
                navigate("Workspace")
            if st.button("Plan & billing", key="cv552_billing", use_container_width=True):
                navigate("Pricing")
            if st.button("Notifications", key="cv552_notifications", use_container_width=True):
                navigate("Notifications")
            if st.button("Help center", key="cv552_help", use_container_width=True):
                navigate("Help")
            st.divider()
            if st.button("Sign out", key="cv552_signout", type="secondary", use_container_width=True):
                request_logout()

    with st.container(key="cv55_navigation"):
        st.markdown(
            f"""
            <div class="cv55-workspace">
              <span>Workspace</span>
              <strong>{_escape(workspace_name or 'Cadivor Workspace')}</strong>
              <small>{_escape(plan_name)} plan</small>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for group_name, rows in NAV_GROUPS:
            st.markdown(f'<div class="cv55-nav-group">{group_name}</div>', unsafe_allow_html=True)
            for label, slug, destination in rows:
                kind = "primary" if destination == current_page else "secondary"
                if st.button(label, key=f"cv55_nav_{slug}", type=kind, use_container_width=True):
                    navigate(destination)

        st.markdown(
            f"""<div class="cv55-plan-card"><strong>{_escape(plan_name)}</strong><span>{_escape(usage_summary)}</span><span>{_escape(saved_summary)}</span></div>""",
            unsafe_allow_html=True,
        )
        if str(plan_name).lower() in {"starter", "free", "trial", "student"}:
            if st.button("Compare plans", key="cv55_compare_plans", use_container_width=True):
                navigate("Pricing")
        if st.button("＋ New BOM analysis", key="cv55_new_analysis", type="primary", use_container_width=True):
            clear_analysis()

