"""Cadivor authenticated application shell with a grouped product navigation rail."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Callable

import streamlit as st

from src.ui.approved_shell_nav import shared_nav_groups
from src.ui.navigation import (
    inject_nav_scroll_reset_if_needed,
    navigate_to,
    return_to_saved_bom_list,
)


NAV_GROUPS = (
    ("", (
        ("Home", "dashboard", "Dashboard"),
        ("BOM Analysis", "bom", "BOM Analyzer"),
        ("Parts Intelligence", "portfolio", "Portfolio Intelligence"),
        ("Suppliers", "suppliers", "Procurement Advisor"),
        ("Reports", "reports", "Reports"),
    )),
    ("Library", (
        ("Saved BOMs", "saved-boms", "BOM Analyzer"),
        ("Watchlist", "watchlist", "Monitoring"),
        ("Engineering Decisions", "decisions", "Engineering Decisions"),
    )),
    ("Admin", (
        ("Workspace Settings", "settings", "Settings"),
        ("Resources", "help", "Help"),
    )),
    ("Decision Tools", (
        ("Find a replacement", "alternatives", "Alternative Finder"),
        ("Compare parts", "compare", "Compare Parts"),
        ("Datasheet Q&A", "datasheet-qa", "Datasheet Q&A"),
        ("Design Impact", "impact", "Design Impact Analyzer"),
        ("Cost Optimization", "cost", "Cost Optimization"),
        ("Supply Scenario", "scenario", "Supply Risk Scenario"),
    )),
)

ROUTE_DISPLAY = {
    "Dashboard": "Home",
    "BOM Analyzer": "BOM Analysis",
    "Engineering Decisions": "Engineering Decisions",
    "Monitoring": "Watchlist",
    "Reports": "Reports",
    "Analysis Details": "Engineering Decision Brief",
    "Alternative Finder": "Find a replacement",
    "Compare Parts": "Compare parts",
    "Datasheet Q&A": "Datasheet Q&A",
    "Design Impact Analyzer": "Design Impact",
    "Procurement Advisor": "Suppliers",
    "Cost Optimization": "Cost Optimization",
    "Supply Risk Scenario": "Supply Scenario",
    "Portfolio Intelligence": "Parts Intelligence",
    "Pricing": "Compare plans",
    "Single BOM Report": "One full BOM report",
    "Settings": "Settings",
}


def one_time_report_nav_rows(
    *, is_admin: bool, plan_name: str, offer_enabled: bool
) -> tuple[tuple[str, str, str], ...]:
    """Show the one-time option only when this account can actually buy it."""
    if (
        is_admin
        or not offer_enabled
        or str(plan_name).strip().casefold() not in {"trial expired", "subscription inactive"}
    ):
        return ()
    return (("One-time report", "single-report", "Single BOM Report"),)


def workspace_nav_rows(*, is_admin: bool) -> tuple[tuple[str, str, str], ...]:
    """Admin destinations for the persistent authenticated rail.

    Admin Console is injected only when ``is_admin`` is true (from
    ``public.users.role`` via the authenticated runtime). Non-admins never
    receive the Admin Console destination.
    """
    rows = next(group for name, group in NAV_GROUPS if name == "Admin")
    if is_admin:
        return rows + (("Admin Console", "admin", "Admin Console"),)
    return tuple(row for row in rows if row[2] == "Settings")


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
        /* Session-safe nav buttons (replace hard-reload <a href>). */
        [class*="st-key-cv_foundation_nav_"] button{
          display:flex!important;align-items:center!important;justify-content:flex-start!important;
          width:100%!important;min-height:36px!important;padding:0 12px!important;border-radius:8px!important;
          border:0!important;box-shadow:none!important;background:transparent!important;
          color:#dbeafe!important;font:650 13px/1.1 Inter,system-ui,sans-serif!important
        }
        [class*="st-key-cv_foundation_nav_"] button:hover{
          background:rgba(71,112,190,.28)!important;color:#fff!important
        }
        [class*="st-key-cv_foundation_nav_"] button[kind="primary"],
        [class*="st-key-cv_foundation_nav_"] button[data-testid="baseButton-primary"]{
          background:#173c81!important;color:#fff!important
        }
        </style>
        """ + _approved_shell_css(),
        unsafe_allow_html=True,
    )


def _approved_shell_css() -> str:
    return """
        <style id="cadivor-approved-shell">
        :root{--cv-foundation-rail:296px;--cv-foundation-top:8px;--cv-foundation-bg:#f8fafc}
        .cv-foundation-topbar{display:none!important}
        .st-key-cv_foundation_navigation{
          top:0!important;height:100vh!important;background:#f8fafc!important;
          border-right:1px solid #e6edf5!important;padding:18px 12px 24px!important
        }
        .cv-approved-brand,.cv-foundation-sidebar-brand{display:flex;align-items:center;gap:10px;padding:4px 8px 14px}
        .cv-approved-brand strong,.cv-foundation-sidebar-brand strong{display:block;color:#0f172a;font-size:16px;letter-spacing:-.02em}
        .cv-approved-brand small,.cv-foundation-sidebar-brand small{display:block;color:#94a3b8;font-size:9px;letter-spacing:.08em;font-weight:700}
        .cv-approved-brand-mark,.cv-foundation-brand-mark{width:32px;height:32px;border-radius:10px;background:#2563eb;color:#fff;display:inline-flex;align-items:center;justify-content:center;font-weight:800}
        .cv-foundation-workspace{background:#fff!important;border:1px solid #e6edf5!important;border-radius:12px!important}
        .cv-foundation-plan-card,.st-key-cv_foundation_new_analysis,.st-key-cv_foundation_compare_plans{display:none!important}
        section[data-testid="stMain"] .st-key-cv_foundation_navigation .stButton>button,
        section[data-testid="stMain"] .st-key-cv_foundation_navigation .stButton>button[kind="secondary"]{
          color:#334155!important;background:transparent!important;border-color:transparent!important;
          border-radius:10px!important;min-height:36px!important;font-weight:650!important
        }
        section[data-testid="stMain"] .st-key-cv_foundation_navigation .stButton>button[kind="primary"],
        section[data-testid="stMain"] .st-key-cv_foundation_navigation .stButton>button[kind="primary"]:hover{
          background:#e8eefc!important;color:#1d4ed8!important;border-color:transparent!important;box-shadow:none!important
        }
        section[data-testid="stMain"] .st-key-cv_foundation_navigation .stButton>button[kind="primary"] p{color:#1d4ed8!important}
        .cv-foundation-nav-group{color:#94a3b8!important;letter-spacing:.12em!important}
        .st-key-cv_foundation_top_navigation{
          display:block!important;visibility:visible!important;position:relative!important;
          top:auto!important;left:auto!important;right:auto!important;bottom:auto!important;
          height:auto!important;min-height:64px!important;max-height:none!important;
          width:100%!important;min-width:100%!important;max-width:none!important;
          margin:0!important;padding:8px 18px 4px!important;overflow:visible!important;
          background:#fff!important;border:0!important;border-bottom:1px solid #e6edf5!important;
          box-shadow:none!important;z-index:40!important
        }
        .st-key-cv_foundation_top_navigation [data-testid="stHorizontalBlock"]{
          display:flex!important;flex-direction:row!important;flex-wrap:nowrap!important;
          align-items:center!important;width:100%!important;gap:6px!important
        }
        .st-key-cv_foundation_top_navigation [data-testid="stColumn"],
        .st-key-cv_foundation_top_navigation [data-testid="column"]{
          flex:0 1 auto!important;width:auto!important;min-width:0!important
        }
        .st-key-cv_foundation_top_navigation [data-testid="stHorizontalBlock"] > div:last-child{
          flex:1 1 220px!important;margin-left:auto!important
        }
        .st-key-cv_foundation_top_navigation .stButton{width:auto!important;margin:0!important}
        .st-key-cv_foundation_top_navigation .stButton>button,
        .st-key-cv_foundation_top_navigation .stButton>button[kind="secondary"],
        .st-key-cv_foundation_top_navigation .stButton>button[kind="primary"],
        .st-key-cv_foundation_top_navigation button[data-testid="stBaseButton-primary"],
        .st-key-cv_foundation_top_navigation button[data-testid="stBaseButton-secondary"]{
          width:auto!important;min-height:36px!important;padding:8px 8px 10px!important;border:0!important;
          border-radius:0!important;background:transparent!important;color:#334155!important;
          font-weight:650!important;box-shadow:none!important;white-space:nowrap!important
        }
        .st-key-cv_foundation_top_navigation .stButton>button::before{display:none!important;content:none!important}
        .st-key-cv_foundation_top_navigation .st-key-cv_foundation_nav_ei button,
        .st-key-cv_foundation_top_navigation .stButton>button[kind="primary"]{
          color:#1d4ed8!important;background:transparent!important;border-radius:0!important;
          box-shadow:inset 0 -2px 0 #2563eb!important
        }
        .st-key-cv_foundation_top_navigation .stButton>button p{color:inherit!important;white-space:nowrap!important}
        .st-key-cv_ei_report_tabs [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;justify-content:flex-end!important}
        .st-key-cv_ei_report_tabs .stButton>button,
        .st-key-cv_ei_report_tabs button{
          background:transparent!important;border:0!important;border-radius:0!important;
          box-shadow:none!important;color:#64748b!important;min-height:0!important;height:auto!important;
          padding:2px 10px 4px!important;line-height:1.15!important;white-space:nowrap!important
        }
        .st-key-cv_ei_report_tabs .stButton>button[kind="primary"],
        .st-key-cv_ei_report_tabs button[data-testid="stBaseButton-primary"]{
          color:#1d4ed8!important;background:transparent!important;box-shadow:inset 0 -2px 0 #2563eb!important
        }
        body:has(.st-key-cv_foundation_top_navigation):not(:has(.st-key-cv_foundation_navigation)) section[data-testid="stMain"]{
          margin-left:0!important;width:100%!important;max-width:none!important
        }
        html body section[data-testid="stMain"] .st-key-cv_foundation_top_navigation div[data-testid="stHorizontalBlock"]{
          display:flex!important;flex-direction:row!important;flex-wrap:nowrap!important;
          align-items:center!important;width:100%!important;gap:8px!important
        }
        html body section[data-testid="stMain"] .st-key-cv_foundation_top_navigation div[data-testid="stHorizontalBlock"] > div{
          flex:0 0 auto!important;width:auto!important;min-width:0!important;max-width:none!important
        }
        html body section[data-testid="stMain"] .st-key-cv_foundation_top_navigation div[data-testid="stHorizontalBlock"] > div:last-child{
          flex:0 0 240px!important;width:240px!important;max-width:240px!important;margin-left:auto!important
        }
        html body section[data-testid="stMain"] .st-key-cv_foundation_top_navigation button{
          background:transparent!important;border:0!important;border-radius:0!important;
          box-shadow:none!important;color:#334155!important;padding:8px 8px 10px!important
        }
        html body section[data-testid="stMain"] .st-key-cv_foundation_top_navigation .st-key-cv_foundation_nav_ei button{
          color:#1d4ed8!important;background:transparent!important;box-shadow:inset 0 -2px 0 #2563eb!important
        }
        html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs div[data-testid="stHorizontalBlock"]{
          display:flex!important;flex-wrap:nowrap!important;justify-content:flex-end!important;gap:4px!important
        }
        html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs div[data-testid="stHorizontalBlock"] > div{
          flex:0 0 auto!important;width:auto!important;max-width:none!important
        }
        html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs button{
          background:transparent!important;border:0!important;border-radius:0!important;box-shadow:none!important;
          color:#64748b!important;min-height:0!important;height:auto!important;min-width:0!important;
          padding:2px 10px 4px!important;line-height:1.15!important;white-space:nowrap!important
        }
        html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs button[kind="primary"],
        html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs button[data-testid="stBaseButton-primary"]{
          color:#1d4ed8!important;background:transparent!important;box-shadow:inset 0 -2px 0 #2563eb!important
        }
        .st-key-cv_foundation_navigation{width:296px!important;min-width:296px!important;max-width:296px!important}
        section[data-testid="stMain"] .st-key-cv_foundation_navigation .stButton>button::before{
          content:""!important;display:block!important;flex:0 0 20px!important;
          width:20px!important;height:20px!important;margin-right:10px!important;opacity:1!important;
          background-repeat:no-repeat!important;background-position:center!important;background-size:20px 20px!important
        }
        section[data-testid="stMain"] .st-key-cv_foundation_navigation .stButton>button[kind="primary"]::before{
          filter:brightness(0) saturate(100%) invert(27%) sepia(98%) saturate(1800%) hue-rotate(213deg) brightness(95%) contrast(95%)!important
        }
        section[data-testid="stMain"] .st-key-cv_foundation_nav_saved-boms button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_boms button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_projects button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M3 7h6l2 2h10v10H3z'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_integrations button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_workspace-settings button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_preferences button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_team button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_members button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Ccircle cx='12' cy='12' r='3'/%3E%3Cpath d='M12 3v2M12 19v2M3 12h2M19 12h2'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_compare button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_parts-library button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_datasheet-qa button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_document-analysis button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_watchlists button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_saved-searches button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_component-search button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_parts-database button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_shared button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_suppliers button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_risk-monitor button::before,
        section[data-testid="stMain"] .st-key-cv_foundation_nav_reports-templates button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Ccircle cx='11' cy='11' r='6'/%3E%3Cpath d='m16 16 4 4'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_home button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M4 11 12 4l8 7'/%3E%3Cpath d='M6 10v9h12v-9'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_bom-analyzer button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M3 7h6l2 2h10v10H3z'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_engineering-decisions button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M8 4h8l1 3H7z'/%3E%3Cpath d='M7 7h10v13H7z'/%3E%3Cpath d='m9 13 2 2 4-4'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_monitoring button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M6 16V10a6 6 0 0 1 12 0v6'/%3E%3Cpath d='M5 16h14v2H5z'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_find-replacement button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Ccircle cx='11' cy='11' r='6'/%3E%3Cpath d='m16 16 4 4'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_reports button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M6 3h9l4 4v14H6z'/%3E%3Cpath d='M15 3v5h5M9 13h6M9 17h6'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_compare-parts button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M4 5h6v14H4zM14 5h6v14h-6z'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_procurement button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M4 6h16l-1.5 9h-13z'/%3E%3Cpath d='M8 6 7 3H4M9 20h.01M17 20h.01'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_design-impact button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Ccircle cx='6' cy='12' r='2.2'/%3E%3Ccircle cx='18' cy='6' r='2.2'/%3E%3Ccircle cx='18' cy='18' r='2.2'/%3E%3Cpath d='M8 12h6M16 8l-6 3M16 16l-6-3'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_cost button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M12 3v18M16 7.5c0-1.5-1.5-2.5-4-2.5s-4 1-4 2.5 1.6 2.4 4 2.8 4 1.2 4 2.7-1.5 2.5-4 2.5-4-1-4-2.5'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_supply-scenario button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M3 8h11v8H3zM14 11h4l3 3v2h-7z'/%3E%3Ccircle cx='7' cy='18' r='1.4'/%3E%3Ccircle cx='17' cy='18' r='1.4'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_settings button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Ccircle cx='12' cy='12' r='3'/%3E%3Cpath d='M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_portfolio button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_detailed-risk button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M12 4 3 19h18z'/%3E%3Cpath d='M12 9v5M12 17h.01'/%3E%3C/svg%3E")!important}
        section[data-testid="stMain"] .st-key-cv_foundation_nav_engineering-intelligence button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%23334155' stroke-width='1.8'%3E%3Cpath d='M4 19V9M10 19V5M16 19v-7M22 19H2'/%3E%3C/svg%3E")!important}
        body:has(.cv-ei-report) [class*="st-key-cv_analysis_section_nav"]{
          display:none!important;height:0!important;overflow:hidden!important
        }
        </style>
    """


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
              <strong>Cadivor</strong><small>Engineering Decision Intelligence</small>
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


def _open_rail_item(destination: str, mode: str = "") -> None:
    """Open a shared-rail destination. Intelligence modes stay on Analysis Details."""
    if mode == "detailed":
        st.session_state["cadivor_show_detailed_risk"] = True
        st.session_state["cadivor_active_analysis_tab"] = "Engineering Intelligence"
    elif mode == "intelligence":
        st.session_state["cadivor_show_detailed_risk"] = False
        st.session_state["cadivor_active_analysis_tab"] = "Engineering Intelligence"
    else:
        st.session_state["cadivor_show_detailed_risk"] = False
    _commit_navigation(destination)


def _commit_navigation(page: str, *, arm_opening: bool = True) -> None:
    """Commit the route before Streamlit performs the widget rerun.

    Using a widget callback avoids the former click -> rerun -> explicit rerun
    sequence that could briefly expose an incomplete/public render.
    """
    if page == "BOM Analyzer":
        st.session_state["cadivor_show_detailed_risk"] = False
        return_to_saved_bom_list(_rerun=False, arm_opening=arm_opening)
    else:
        if page == "Analysis Details":
            analysis_id = str(
                st.session_state.get("cadivor_active_analysis_id")
                or st.session_state.get("analysis_id")
                or ""
            ).strip()
            if analysis_id:
                navigate_to(
                    page,
                    _rerun=False,
                    arm_opening=arm_opening,
                    analysis_id=analysis_id,
                )
                st.session_state.pop("cadivor_route_transition", None)
                st.session_state["cadivor_profile_menu_open"] = False
                return
        navigate_to(page, _rerun=False, arm_opening=arm_opening)
    st.session_state.pop("cadivor_route_transition", None)
    st.session_state["cadivor_profile_menu_open"] = False


def _open_plan_and_billing() -> None:
    """Account billing lives on Settings → Billing, not the pricing catalog."""
    st.session_state["settings_active_tab"] = "Billing"
    _commit_navigation("Settings", arm_opening=False)


def _open_compare_plans() -> None:
    """In-session Pricing hop. Does not discard session or arm Opening."""
    _commit_navigation("Pricing", arm_opening=False)


def _toggle_profile_menu() -> None:
    """Open or close the account panel without relying on a client popover.

    The foundation shell is fixed outside Streamlit's normal document flow.
    ``st.popover`` can lose its trigger in that layout after a rerun, which made
    the only Sign out path unreachable.  A normal keyed button gives Streamlit
    an unambiguous click callback; the panel is rendered on the following run.
    """
    st.session_state["cadivor_profile_menu_open"] = not bool(
        st.session_state.get("cadivor_profile_menu_open")
    )


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
    route_loading: str = "",
) -> None:
    """Render exactly one top bar and one custom fixed navigation rail.

    When ``route_loading`` is set, paint Opening in a dedicated Streamlit host
    after the topbar (never co-located). Topbar markdown uses a stable flow-host
    marker so only that wrapper is zeroed in-flow while the fixed topbar stays
    visible.
    """
    inject_unified_shell_css()

    full_name = profile.get("full_name") or profile.get("email") or "Cadivor user"
    email = profile.get("email") or ""
    initials = profile.get("initials") or "C"
    secondary = profile.get("company") or profile.get("role_title") or plan_name

    loading_route = str(route_loading or "").strip()
    if loading_route:
        from src.ui.main_transition import (
            MAIN_TRANSITION_GEN_KEY,
            inject_main_transition_css,
            prepare_main_transition,
        )

        try:
            gen = int(st.session_state.get(MAIN_TRANSITION_GEN_KEY) or 0)
        except (TypeError, ValueError):
            gen = 0
        if gen <= 0:
            prepare_main_transition(loading_route)
        else:
            inject_main_transition_css(gen)

    if loading_route:
        from src.ui.main_transition import paint_prepared_main_transition

        paint_prepared_main_transition(loading_route)

    # The account menu is part of the persistent shell, not route content.
    # Keep it available while a route is opening so sign-out and account actions
    # never require a second page click after login or navigation.
    with st.container(key="cv_foundation_profile_trigger"):
        st.button(
            initials,
            key="cv_foundation_profile_menu",
            help="Open account menu",
            on_click=_toggle_profile_menu,
        )

    if st.session_state.get("cadivor_profile_menu_open"):
        with st.container(key="cv_foundation_profile_panel"):
            st.markdown(
                f"""<div class="cv-foundation-account-head"><b>{_escape(full_name)}</b><span>{_escape(email)}</span><small>{_escape(workspace_name)}</small></div>""",
                unsafe_allow_html=True,
            )
            st.markdown('<div class="cv-profile-menu-group">Account</div>', unsafe_allow_html=True)
            st.button("Profile & preferences", key="cv_foundation_profile", use_container_width=True, on_click=_commit_navigation, args=("Settings",))
            st.button("Plan & billing", key="cv_foundation_billing", use_container_width=True, on_click=_open_plan_and_billing)
            st.markdown('<div class="cv-profile-menu-group">Workspace</div>', unsafe_allow_html=True)
            st.button("Workspace settings", key="cv_foundation_workspace", use_container_width=True, on_click=_commit_navigation, args=("Settings",))
            if is_admin:
                st.button("Resources", key="cv_foundation_help", use_container_width=True, on_click=_commit_navigation, args=("Help",))
            st.divider()

            def _commit_signout() -> None:
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

    detailed_risk = bool(st.session_state.get("cadivor_show_detailed_risk"))

    with st.container(key="cv_foundation_navigation"):
        st.markdown(
            """
            <div class="cv-foundation-sidebar-brand">
              <span class="cv-foundation-brand-mark">C</span>
              <span class="cv-foundation-brand-copy"><strong>Cadivor</strong><small>ENGINEERING INTELLIGENCE</small></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="cv-foundation-workspace" aria-label="Current workspace">
              <span class="cv-foundation-workspace-mark" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><path d="M4 20V7l8-4 8 4v13M9 20v-5h6v5M8 10h.01M16 10h.01"/></svg></span>
              <span class="cv-foundation-workspace-copy">
                <small>Workspace</small>
                <strong>{_escape(workspace_name or 'Cadivor Workspace')}</strong>
                <em>Subscription · {_escape(plan_name)}</em>
              </span>
              <span class="cv-foundation-workspace-chevron" aria-hidden="true">⌄</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        report_nav_rows = ()
        if not is_admin and str(plan_name).strip().casefold() in {
            "trial expired", "subscription inactive"
        }:
            from src.one_time_bom import enabled as one_time_report_enabled

            report_nav_rows = one_time_report_nav_rows(
                is_admin=is_admin,
                plan_name=plan_name,
                offer_enabled=one_time_report_enabled(),
            )

        source_groups = shared_nav_groups()
        for group_name, configured_rows in source_groups:
            rows = configured_rows
            if group_name == "Workspace" and report_nav_rows:
                rows = rows + report_nav_rows
            if group_name == "Intelligence" and is_admin:
                rows = rows + (("Admin Console", "admin", "Admin Console"),)
            if group_name:
                st.markdown(
                    f'<div class="cv-foundation-nav-group">{_escape(group_name)}</div>',
                    unsafe_allow_html=True,
                )
            for label, slug, destination in rows:
                # Session navigation only — raw ?page= hrefs hard-reload the app and
                # briefly clear the authenticated shell (blank white/black frames).
                if label == "Detailed Risk Report":
                    is_active = current_page == "Analysis Details" and detailed_risk
                    mode = "detailed"
                elif label == "Engineering Intelligence":
                    is_active = current_page == "Analysis Details" and not detailed_risk
                    mode = "intelligence"
                else:
                    is_active = destination == current_page
                    mode = ""
                st.button(
                    label,
                    key=f"cv_foundation_nav_{slug}",
                    use_container_width=True,
                    type="primary" if is_active else "secondary",
                    on_click=_open_rail_item,
                    args=(destination, mode),
                )

    # After chrome paints: reset scroll only when sidebar navigation changed pages.
    inject_nav_scroll_reset_if_needed()
