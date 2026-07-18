"""Cadivor dashboard page renderer.

This module was extracted from streamlit_app.py as part of the Enterprise
Architecture Refactor. It preserves the existing Dashboard UI and behavior while
moving the dashboard into its own page module.
"""

from datetime import datetime, timezone
import html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def render_dashboard(
    *,
    current_user,
    supabase,
    load_analysis_history,
    load_alternative_history,
    render_global_search_panel,
    light_plotly_layout,
    empty_state,
    get_user_profile,
    _qp_value,
    workspace_id=None,
    workspace_name=None,
):
    """Render the Cadivor Dashboard page."""

    st.markdown(
        """
        <style>

        /* Dashboard-specific styling only. Layout shell is defined globally above. */
        .main .block-container, [data-testid="stMainBlockContainer"] { padding-left:calc(var(--cv-sidebar-width) + 24px)!important; padding-right:24px!important; max-width:none!important; }
        .cv-side-brand { display:flex; align-items:center; gap:12px; margin-bottom:22px; }
        .cv-side-logo { width:38px; height:38px; border-radius:12px; background:#2563EB; color:#fff!important; display:flex; align-items:center; justify-content:center; font-weight:950; box-shadow:0 12px 24px rgba(37,99,235,.25); }
        .cv-side-name { color:#0F172A!important; font-size:20px; font-weight:950; line-height:1; }
        .cv-side-sub { color:#64748B!important; font-size:10px; font-weight:800; margin-top:4px; letter-spacing:.04em; text-transform:uppercase; }
        .cv-side-user { display:flex; gap:12px; align-items:center; padding:13px; border:1px solid #E5E7EB; border-radius:16px; background:#F8FAFC; margin-bottom:22px; }
        .cv-side-avatar { width:38px; height:38px; border-radius:50%; background:#EFF6FF; color:#2563EB!important; border:1px solid #BFDBFE; display:flex; align-items:center; justify-content:center; font-weight:950; flex:0 0 auto; }
        .cv-side-user strong { display:block; color:#0F172A!important; font-size:14px; font-weight:950; line-height:1.2; }
        .cv-side-user small { display:block; color:#64748B!important; font-size:11px; font-weight:700; line-height:1.35; max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .cv-side-section { color:#94A3B8!important; font-size:11px; font-weight:900; text-transform:uppercase; letter-spacing:.09em; margin:18px 8px 8px; }
    .cv-side-section.first { margin-top:8px; }
        .cv-side-nav { display:flex; flex-direction:column; gap:4px; }
        .cv-side-link { display:flex; align-items:center; gap:10px; padding:10px 11px; border-radius:12px; color:#334155!important; text-decoration:none!important; font-size:13px; font-weight:800; border:1px solid transparent; }
        .cv-side-link span { width:22px; text-align:center; color:#64748B!important; font-size:15px; }
        .cv-side-link:hover { background:#F8FAFC; color:#0F172A!important; transform:translateX(2px); transition:all .16s ease; }
        .cv-side-link.active { background:#EFF6FF; border-color:#BFDBFE; color:#2563EB!important; }
        .cv-side-link.active span { color:#2563EB!important; }
        .cv-side-plan { border:1px solid #E5E7EB; border-radius:16px; background:#FFFFFF; padding:14px; display:flex; flex-direction:column; gap:7px; }
        .cv-side-plan strong { color:#0F172A!important; font-size:18px; font-weight:950; }
        .cv-side-plan span { color:#64748B!important; font-size:12px; font-weight:750; }
        .cv-side-footer { margin-top:20px; display:grid; gap:8px; }
        .cv-side-footer a { padding:10px 12px; border-radius:12px; text-decoration:none!important; color:#334155!important; font-weight:850; font-size:13px; background:#F8FAFC; border:1px solid #E5E7EB; }
        .cv-side-footer a:last-child { color:#DC2626!important; }
        .cadivor-topbar {
            margin-top: 0;
            margin-bottom: 22px;
            padding: 12px 18px;
            background: rgba(255,255,255,.97);
            border: 1px solid #E5E7EB;
            border-radius: 18px;
            box-shadow: 0 12px 32px rgba(15,23,42,.055);
            display: grid;
            grid-template-columns: 280px 1fr auto;
            align-items: center;
            gap: 22px;
            width: 100%;
        }
        .cadivor-brand { display:flex; align-items:center; gap:14px; min-width:260px; }
        .cadivor-logo-mark {
            width: 46px; height: 46px; border-radius: 14px;
            display:flex; align-items:center; justify-content:center;
            background:#2563EB; color:#FFFFFF!important; font-weight:900; font-size:22px;
            box-shadow:0 12px 22px rgba(37,99,235,.22);
        }
        .cadivor-logo-text { color:#0F172A!important; font-size:22px; font-weight:950; line-height:1; letter-spacing:-.02em; }
        .cadivor-logo-subtitle { color:#64748B!important; font-size:11.5px; font-weight:800; margin-top:4px; letter-spacing:.02em; }
        .cadivor-topbar-center { color:#0F172A!important; font-size:15px; font-weight:850; justify-self:start; }
        .cadivor-user { display:flex; align-items:center; gap:12px; justify-content:flex-end; min-width:280px; }
        .cadivor-user-label { color:#94A3B8!important; font-size:10px; font-weight:850; text-transform:uppercase; letter-spacing:.08em; text-align:right; }
        .cadivor-user-email { color:#64748B!important; font-size:12px; font-weight:700; max-width:230px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .cadivor-user-name { color:#0F172A!important; font-size:15px; font-weight:900; text-align:right; line-height:1.15; }
        .cadivor-user-company { color:#64748B!important; font-size:12px; font-weight:700; text-align:right; margin-top:2px; }
        .cadivor-avatar { width:44px; height:44px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:#EFF6FF; color:#2563EB!important; font-weight:950; border:1px solid #BFDBFE; overflow:hidden; }
        .cadivor-avatar img { width:100%; height:100%; object-fit:cover; display:block; }

        .cv-dashboard-header {
            display:flex; align-items:flex-start; justify-content:space-between; gap:24px;
            margin: 2px 0 14px 0;
        }
        .cv-eyebrow {
            display:inline-flex; align-items:center; gap:8px;
            padding:7px 11px; border-radius:999px;
            background:#EFF6FF; color:#2563EB!important;
            font-size:11px; font-weight:900; letter-spacing:.08em; text-transform:uppercase;
            margin-bottom:10px;
        }
        .cv-title { font-size:40px; line-height:1.05; font-weight:950; color:#0F172A!important; letter-spacing:-.045em; margin:0 0 8px 0; }
        .cv-subtitle { color:#64748B!important; font-size:15px; line-height:1.55; max-width:760px; margin:0; }
        .cv-action-row { display:flex; gap:10px; justify-content:flex-end; align-items:center; padding-top:8px; }
        .cv-action-row-label { color:#94A3B8!important; font-size:11px; font-weight:900; letter-spacing:.08em; text-transform:uppercase; text-align:right; padding-top:0; margin-bottom:8px; }
        .cv-quick-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:16px; padding:14px; box-shadow:0 14px 32px rgba(15,23,42,.055); display:grid; gap:8px; }
        .cv-quick-copy { color:#64748B!important; font-size:12px; font-weight:700; margin-bottom:2px; text-align:right; }
    .cv-quick-button { display:block; text-align:center; text-decoration:none!important; background:#2563EB; color:#FFFFFF!important; border-radius:10px; padding:11px 14px; font-weight:850; box-shadow:0 12px 24px rgba(37,99,235,.20); }
    .cv-quick-button:hover { background:#1D4ED8; color:#FFFFFF!important; transform:translateY(-1px); transition:all .16s ease; }
    .cv-quick-button.secondary { background:#F8FAFC; color:#2563EB!important; border:1px solid #BFDBFE; box-shadow:none; }
    .cv-quick-button.secondary:hover { background:#EFF6FF; color:#1D4ED8!important; }
        .cv-action-row div.stButton > button { min-width:132px!important; width:auto!important; }

        .cv-metric {
            background:#FFFFFF; border:1px solid #E5E7EB; border-radius:16px;
            padding:18px 18px 16px 18px; box-shadow:0 14px 32px rgba(15,23,42,.055);
            min-height:118px; position:relative; overflow:hidden;
        }
        .cv-metric:before { content:""; position:absolute; inset:0 0 auto 0; height:3px; background:#2563EB; opacity:.88; }
        .cv-metric.cv-danger:before { background:#DC2626; }
        .cv-metric.cv-warning:before { background:#F59E0B; }
        .cv-metric.cv-success:before { background:#16A34A; }
        .cv-metric-top { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:12px; }
        .cv-metric-label { color:#64748B!important; font-size:12px; font-weight:850; letter-spacing:.035em; text-transform:uppercase; }
        .cv-metric-icon { width:32px; height:32px; border-radius:10px; display:flex; align-items:center; justify-content:center; background:#F8FAFC; border:1px solid #E5E7EB; font-size:16px; }
        .cv-metric-value { color:#0F172A!important; font-size:38px; line-height:1; font-weight:950; letter-spacing:-.04em; margin-bottom:8px; }
        .cv-metric-note { color:#64748B!important; font-size:13px; font-weight:700; }
        .cv-badge { display:inline-flex; padding:5px 9px; border-radius:999px; font-size:11px; font-weight:850; border:1px solid #BFDBFE; color:#2563EB!important; background:#EFF6FF; }
        .cv-badge.success { color:#047857!important; background:#ECFDF5; border-color:#A7F3D0; }
        .cv-badge.warning { color:#B45309!important; background:#FFFBEB; border-color:#FDE68A; }
        .cv-badge.danger { color:#B91C1C!important; background:#FEF2F2; border-color:#FECACA; }

        .cv-panel {
            background:#FFFFFF; border:1px solid #E5E7EB; border-radius:16px;
            padding:18px; box-shadow:0 14px 32px rgba(15,23,42,.055); margin-top:16px;
        }
        .cv-panel-title { color:#0F172A!important; font-size:18px; font-weight:950; letter-spacing:-.025em; margin-bottom:4px; }
        .cv-panel-copy { color:#64748B!important; font-size:13px; margin-bottom:14px; }
        .cv-snapshot-main { color:#0F172A!important; font-size:22px; font-weight:900; line-height:1.2; margin:10px 0 12px; }
        .cv-snapshot-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
        .cv-snapshot-item { background:#F8FAFC; border:1px solid #E5E7EB; border-radius:12px; padding:12px; }
        .cv-snapshot-item span { color:#64748B!important; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.05em; display:block; margin-bottom:7px; }
        .cv-snapshot-item strong { color:#0F172A!important; font-size:22px; font-weight:950; }
        .cv-actions-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:16px; }
        .cv-action-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:15px; padding:16px; box-shadow:0 12px 28px rgba(15,23,42,.045); }
        .cv-action-icon { width:34px; height:34px; border-radius:11px; display:flex; align-items:center; justify-content:center; background:#EFF6FF; color:#2563EB!important; font-weight:900; margin-bottom:10px; }
        .cv-action-title { color:#0F172A!important; font-size:14px; font-weight:900; margin-bottom:4px; }
        .cv-action-copy { color:#64748B!important; font-size:12px; line-height:1.45; }
        .cv-section-spacer { margin-top:36px; }
        @media(max-width:1000px){ .cv-app-sidebar{position:relative;width:auto;height:auto;box-shadow:none;border-right:0;border-bottom:1px solid #E5E7EB;} .main .block-container{padding-left:1rem!important;padding-right:1rem!important;} .cv-dashboard-header{display:block;} .cv-action-row{justify-content:flex-start;padding-top:14px;} .cv-actions-grid{grid-template-columns:1fr 1fr;} }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Cadivor v3.0 dashboard polish overrides: shell rhythm, KPI hierarchy, and table finish.
    st.markdown(
        """
        <style>
        :root { --cv-topbar-height: 64px!important; --cv-sidebar-width: 284px!important; }

        /* Keep Streamlit chrome suppressed without showing native navigation during reruns. */
        header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
        [data-testid="stStatusWidget"], .stDeployButton, [data-testid="collapsedControl"],
        [data-testid="stSidebar"], section[data-testid="stSidebar"], div[data-testid="stSidebarNav"] {
            display:none!important; visibility:hidden!important; width:0!important; height:0!important; min-height:0!important;
        }

        /* Enterprise shell alignment. */
        .cadivor-topbar {
            position:fixed!important; top:0!important; left:0!important; right:0!important; z-index:999998!important;
            height:var(--cv-topbar-height)!important; min-height:var(--cv-topbar-height)!important;
            margin:0!important; padding:0 20px!important; border-radius:0!important; border:0!important;
            border-bottom:1px solid #E5E7EB!important; box-shadow:0 12px 28px rgba(15,23,42,.045)!important;
            background:rgba(255,255,255,.985)!important;
            grid-template-columns: var(--cv-sidebar-width) minmax(360px,1fr) auto!important;
        }
        .cadivor-brand { min-width:0!important; gap:12px!important; }
        .cadivor-logo-mark { width:40px!important; height:40px!important; border-radius:12px!important; font-size:20px!important; }
        .cadivor-logo-text { font-size:22px!important; }
        .cadivor-logo-subtitle { font-size:9.5px!important; letter-spacing:.16em!important; text-transform:uppercase!important; }
        .cadivor-topbar-center { display:flex!important; align-items:center!important; gap:16px!important; min-width:0!important; }
        .cadivor-current-page { min-width:132px!important; font-size:14px!important; font-weight:950!important; }
        .cadivor-search-pill {
            max-width:360px!important; height:36px!important; background:#F8FAFC!important;
            border:1px solid #E2E8F0!important; color:#94A3B8!important; font-size:12px!important;
        }
        .cadivor-top-icon { width:32px!important; height:32px!important; box-shadow:none!important; }
        .cadivor-user { min-width:260px!important; }
        .cadivor-user-label { font-size:9.5px!important; }
        .cadivor-user-name { font-size:14px!important; }
        .cadivor-user-company { font-size:11px!important; }
        .cadivor-avatar { width:38px!important; height:38px!important; }

        .cv-app-sidebar {
            position:fixed!important; top:var(--cv-topbar-height)!important; left:0!important; bottom:0!important;
            height:calc(100vh - var(--cv-topbar-height))!important; width:var(--cv-sidebar-width)!important;
            padding:22px 16px 18px!important; z-index:999997!important;
            box-shadow:14px 0 34px rgba(15,23,42,.035)!important;
        }

        [data-testid="stAppViewContainer"] > .main, [data-testid="stMain"] > div,
        .main .block-container, [data-testid="stMainBlockContainer"] {
            padding-top:calc(var(--cv-topbar-height) + 12px)!important;
            padding-left:calc(var(--cv-sidebar-width) + 22px)!important;
            padding-right:22px!important; padding-bottom:56px!important; max-width:none!important; width:100%!important;
        }

        /* Dashboard rhythm: less wasted vertical space, more premium hierarchy. */
        .cv-dashboard-header { margin-top:0!important; margin-bottom:12px!important; align-items:flex-end!important; }
        .cv-eyebrow { margin-bottom:9px!important; padding:6px 10px!important; font-size:10.5px!important; }
        .cv-title { font-size:36px!important; line-height:1.04!important; margin-bottom:10px!important; letter-spacing:-.045em!important; }
        .cv-subtitle { max-width:760px!important; font-size:14px!important; line-height:1.55!important; }
        .cv-quick-mini { max-width:340px!important; padding-top:0!important; margin-top:0!important; }
        .cv-quick-mini .cv-action-row-label { margin-bottom:7px!important; }
        .cv-mini-buttons { display:grid!important; grid-template-columns:1fr 1fr!important; gap:10px!important; }
        .cv-quick-mini .cv-quick-button { min-width:0!important; padding:10px 15px!important; border-radius:12px!important; }

        .cv-metric { min-height:112px!important; padding:18px 18px 16px!important; border-radius:17px!important; transition:transform .16s ease, box-shadow .16s ease!important; }
        .cv-metric:hover { transform:translateY(-2px)!important; box-shadow:0 20px 42px rgba(15,23,42,.075)!important; }
        .cv-metric-label { font-size:11px!important; letter-spacing:.06em!important; }
        .cv-metric-icon { width:31px!important; height:31px!important; border-radius:10px!important; }
        .cv-metric-value { font-size:42px!important; line-height:.95!important; margin-bottom:9px!important; }
        .cv-metric-note { font-size:12px!important; font-weight:850!important; }

        .cv-panel-title { font-size:18px!important; margin-bottom:3px!important; }
        .cv-panel-copy { font-size:12.5px!important; margin-bottom:12px!important; }
        div[data-testid="stPlotlyChart"] {
            background:#FFFFFF!important; border:1px solid #E5E7EB!important; border-radius:17px!important;
            box-shadow:0 14px 32px rgba(15,23,42,.045)!important; padding:10px!important;
        }
        .js-plotly-plot { border-radius:14px!important; overflow:hidden!important; }

        .cv-panel { border-radius:17px!important; padding:19px!important; }
        .cv-snapshot-grid { gap:11px!important; }
        .cv-snapshot-item { border-radius:14px!important; }

        /* Dataframes: softer enterprise table treatment. */
        [data-testid="stDataFrame"] {
            border-radius:16px!important; border:1px solid #E5E7EB!important; overflow:hidden!important;
            box-shadow:0 14px 34px rgba(15,23,42,.045)!important; background:#FFFFFF!important;
        }
        [data-testid="stDataFrame"] [role="columnheader"] {
            background:#F8FAFC!important; color:#64748B!important; font-size:12px!important; font-weight:900!important;
        }
        [data-testid="stDataFrame"] [role="gridcell"] {
            background:#FFFFFF!important; color:#0F172A!important; border-bottom:1px solid #EEF2F7!important;
        }
        [data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] { background:#F8FAFC!important; }

        .cv-actions-grid { gap:14px!important; }
        .cv-action-card { border-radius:17px!important; transition:transform .16s ease, box-shadow .16s ease!important; }
        .cv-action-card:hover { transform:translateY(-2px)!important; box-shadow:0 18px 38px rgba(15,23,42,.07)!important; }

        @media(max-width:1100px){
            .cadivor-topbar{position:relative!important;grid-template-columns:1fr!important;height:auto!important;min-height:70px!important;padding:12px 16px!important;}
            .cadivor-topbar-center{display:none!important;}
            .cv-app-sidebar{position:relative!important;top:auto!important;width:auto!important;height:auto!important;}
            .main .block-container,[data-testid="stMainBlockContainer"]{padding:1rem!important;}
            .cv-dashboard-header{display:block!important;}
            .cv-quick-mini{margin-left:0!important;margin-top:16px!important;max-width:none!important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Milestone 4.14 — Dashboard Polish: page-content only.
    # Does not alter the fixed shell, sidebar, or topbar.
    st.markdown(
        """
        <style>
        /* M4.14 Dashboard Polish — content layer only */
        .cv-command-hero {
            border-radius:22px!important;
            border:1px solid rgba(147,197,253,.88)!important;
            background:
                radial-gradient(circle at 86% 12%, rgba(37,99,235,.10), transparent 34%),
                linear-gradient(135deg, rgba(255,255,255,.98), rgba(239,246,255,.86))!important;
            box-shadow:0 24px 58px rgba(15,23,42,.075)!important;
        }
        .cv-command-hero:hover {
            box-shadow:0 28px 68px rgba(15,23,42,.095)!important;
            transform:translateY(-1px)!important;
            transition:box-shadow .18s ease, transform .18s ease!important;
        }
        .cv-title {
            color:#0B1220!important;
            text-wrap:balance!important;
        }
        .cv-subtitle { color:#475569!important; }

        .cv-insight-card {
            border-radius:18px!important;
            background:rgba(255,255,255,.96)!important;
            border:1px solid rgba(226,232,240,.95)!important;
            box-shadow:0 18px 42px rgba(15,23,42,.060)!important;
            transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease!important;
        }
        .cv-insight-card:hover {
            transform:translateY(-2px)!important;
            box-shadow:0 24px 52px rgba(15,23,42,.085)!important;
            border-color:#BFDBFE!important;
        }
        .cv-insight-title { font-size:13px!important; letter-spacing:-.01em!important; }
        .cv-insight-copy { color:#475569!important; font-size:12px!important; }

        .cv-metric {
            background:
                linear-gradient(180deg,#FFFFFF 0%,#FFFFFF 62%,#F8FAFC 100%)!important;
            border-color:#E2E8F0!important;
            border-radius:20px!important;
            box-shadow:0 18px 46px rgba(15,23,42,.065)!important;
        }
        .cv-metric:before { height:4px!important; }
        .cv-metric:hover {
            transform:translateY(-3px)!important;
            box-shadow:0 28px 60px rgba(15,23,42,.095)!important;
            border-color:#CBD5E1!important;
        }
        .cv-metric-label { color:#64748B!important; font-size:10.5px!important; letter-spacing:.085em!important; }
        .cv-metric-icon {
            background:#F8FAFC!important;
            border-color:#E2E8F0!important;
            box-shadow:inset 0 1px 0 rgba(255,255,255,.85)!important;
        }
        .cv-metric-value {
            font-size:44px!important;
            letter-spacing:-.055em!important;
            color:#071126!important;
        }
        .cv-metric-note { color:#475569!important; }

        .cv-panel-title {
            font-size:19px!important;
            line-height:1.12!important;
            color:#0B1220!important;
            letter-spacing:-.035em!important;
        }
        .cv-panel-copy { color:#52647A!important; line-height:1.45!important; }
        div[data-testid="stPlotlyChart"] {
            border-radius:20px!important;
            border-color:#E2E8F0!important;
            box-shadow:0 18px 46px rgba(15,23,42,.060)!important;
            padding:14px!important;
            transition:transform .16s ease, box-shadow .16s ease!important;
        }
        div[data-testid="stPlotlyChart"]:hover {
            transform:translateY(-2px)!important;
            box-shadow:0 24px 58px rgba(15,23,42,.080)!important;
        }

        .cv-panel {
            border-radius:20px!important;
            border-color:#E2E8F0!important;
            box-shadow:0 18px 46px rgba(15,23,42,.060)!important;
        }
        .cv-snapshot-main {
            font-size:24px!important;
            letter-spacing:-.035em!important;
            color:#071126!important;
        }
        .cv-snapshot-item {
            background:linear-gradient(180deg,#FFFFFF,#F8FAFC)!important;
            border-color:#E2E8F0!important;
            box-shadow:inset 0 1px 0 rgba(255,255,255,.78)!important;
        }
        .cv-snapshot-item span { color:#64748B!important; letter-spacing:.07em!important; }

        [data-testid="stDataFrame"] {
            border-radius:18px!important;
            border-color:#E2E8F0!important;
            box-shadow:0 18px 46px rgba(15,23,42,.055)!important;
        }
        [data-testid="stDataFrame"] [role="columnheader"] {
            background:#F8FAFC!important;
            color:#475569!important;
            text-transform:uppercase!important;
            letter-spacing:.04em!important;
            font-size:11px!important;
        }
        [data-testid="stDataFrame"] [role="gridcell"] {
            font-size:12px!important;
        }

        .cv-result-card {
            border-radius:17px!important;
            border-color:#E2E8F0!important;
            box-shadow:0 14px 34px rgba(15,23,42,.045)!important;
            transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease!important;
        }
        .cv-result-card:hover {
            transform:translateY(-2px)!important;
            border-color:#BFDBFE!important;
            box-shadow:0 22px 48px rgba(15,23,42,.075)!important;
        }
        .cv-result-title { color:#0B1220!important; letter-spacing:-.015em!important; }
        .cv-result-meta { color:#52647A!important; }

        .cv-actions-grid { gap:16px!important; }
        .cv-action-card {
            min-height:116px!important;
            border-radius:20px!important;
            background:linear-gradient(180deg,#FFFFFF,#F8FAFC)!important;
            border-color:#E2E8F0!important;
            box-shadow:0 18px 46px rgba(15,23,42,.055)!important;
            transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease!important;
        }
        .cv-action-card:hover {
            transform:translateY(-3px)!important;
            box-shadow:0 28px 62px rgba(15,23,42,.085)!important;
            border-color:#BFDBFE!important;
        }
        .cv-action-icon {
            background:#EFF6FF!important;
            color:#2563EB!important;
            border:1px solid #DBEAFE!important;
        }
        .cv-action-title { font-size:13px!important; letter-spacing:-.01em!important; }
        .cv-action-copy { color:#52647A!important; }

        .cv-section-spacer { margin-top:28px!important; }
        .cv-status-pill { font-weight:950!important; letter-spacing:-.005em!important; }

        @media(max-width:1200px){
            .cv-actions-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;}
            .cv-title{font-size:31px!important;}
        }
        @media(max-width:760px){
            .cv-actions-grid{grid-template-columns:1fr!important;}
            .cv-metric-value{font-size:36px!important;}
        }

        /* Milestone 23.2 — Portfolio trends and health history */
        .cv232-trend-summary{
            border:1px solid #BFDBFE;background:linear-gradient(135deg,#FFFFFF,#EFF6FF);
            border-radius:18px;padding:16px 18px;margin:4px 0 14px;
            color:#334155!important;font-size:12.5px;font-weight:760;line-height:1.55;
        }
        .cv232-trend-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 16px;}
        .cv232-trend-card{
            background:#fff;
            border:1px solid #E2E8F0;
            border-radius:17px;
            padding:15px 16px;
            box-shadow:0 12px 30px rgba(15,23,42,.045);
            transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
        }
        .cv232-trend-card:hover{
            transform:translateY(-2px);
            border-color:#BFDBFE;
            box-shadow:0 16px 34px rgba(37,99,235,.08);
        }
        .cv232-trend-card.good{background:#F0FDF4;border-color:#BBF7D0}.cv232-trend-card.bad{background:#FEF2F2;border-color:#FECACA}.cv232-trend-card.warn{background:#FFFBEB;border-color:#FDE68A}
        .cv232-trend-label{color:#64748B!important;font-size:10px;font-weight:950;text-transform:uppercase;letter-spacing:.08em;}
        .cv232-trend-value{color:#0F172A!important;font-size:25px;font-weight:980;line-height:1;margin-top:7px;letter-spacing:-.04em;}
        .cv232-trend-note{color:#64748B!important;font-size:10px;font-weight:750;line-height:1.3;margin-top:5px;}
        .cv232-project-list{display:grid;gap:9px;}
        .cv232-project-row{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;background:#fff;border:1px solid #E2E8F0;border-radius:16px;padding:13px 14px;box-shadow:0 9px 24px rgba(15,23,42,.035);}
        .cv232-project-name{color:#0F172A!important;font-size:13px;font-weight:950;margin-bottom:4px;}
        .cv232-project-copy{color:#64748B!important;font-size:11.5px;font-weight:750;line-height:1.4;}
        .cv232-project-delta{border-radius:999px;padding:6px 9px;font-size:11px;font-weight:950;white-space:nowrap;}
        .cv232-project-delta.good{color:#047857!important;background:#ECFDF5;border:1px solid #A7F3D0}.cv232-project-delta.bad{color:#B91C1C!important;background:#FEF2F2;border:1px solid #FECACA}
        @media(max-width:950px){.cv232-trend-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}

        /* Milestone 23.1 — Engineering timeline and recent activity */
        .cv231-summary-grid{
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:12px;
            margin:12px 0 18px;
        }
        .cv231-summary-card{
            border:1px solid #E2E8F0;
            background:#FFFFFF;
            border-radius:16px;
            padding:15px 16px;
            box-shadow:0 10px 24px rgba(15,23,42,.04);
        }
        .cv231-summary-label{
            color:#64748B!important;
            font-size:10.5px;
            font-weight:900;
            letter-spacing:.07em;
            text-transform:uppercase;
        }
        .cv231-summary-value{
            color:#0F172A!important;
            font-size:29px;
            line-height:1;
            font-weight:950;
            letter-spacing:-.04em;
            margin-top:10px;
        }
        .cv231-summary-note{
            color:#64748B!important;
            font-size:10.5px;
            font-weight:700;
            line-height:1.35;
            margin-top:7px;
        }
        .cv231-activity-card{
            border:1px solid #E2E8F0;
            background:#FFFFFF;
            border-radius:17px;
            padding:15px 16px;
            margin:0 0 10px;
            box-shadow:0 10px 26px rgba(15,23,42,.04);
            transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
        }
        .cv231-activity-card:hover{
            transform:translateY(-2px);
            border-color:#BFDBFE;
            box-shadow:0 15px 34px rgba(37,99,235,.08);
        }
        .cv231-activity-top{
            display:flex;
            justify-content:space-between;
            align-items:flex-start;
            gap:14px;
        }
        .cv231-activity-type{
            color:#2563EB!important;
            font-size:10px;
            font-weight:950;
            letter-spacing:.08em;
            text-transform:uppercase;
        }
        .cv231-activity-time{
            color:#64748B!important;
            font-size:10.5px;
            font-weight:750;
            white-space:nowrap;
        }
        .cv231-activity-title{
            color:#0F172A!important;
            font-size:14px;
            font-weight:950;
            line-height:1.3;
            margin-top:7px;
        }
        .cv231-activity-copy{
            color:#64748B!important;
            font-size:11.5px;
            font-weight:680;
            line-height:1.45;
            margin-top:5px;
        }
        .cv231-activity-link{
            display:inline-flex;
            margin-top:10px;
            color:#2563EB!important;
            font-size:11px;
            font-weight:900;
            text-decoration:none!important;
        }
        .cv231-empty{
            border:1px dashed #CBD5E1;
            background:#F8FAFC;
            border-radius:16px;
            padding:22px;
            color:#64748B!important;
            font-size:12px;
            font-weight:700;
            text-align:center;
        }
        @media(max-width:950px){
            .cv231-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Milestone 24.3A — final executive visual redesign.
    st.markdown(
        """
        <style id="cadivor-m243a-executive-visuals">
          .cv243-summary{
            display:grid;
            grid-template-columns:minmax(190px,.42fr) minmax(0,1.58fr);
            gap:14px;
            align-items:stretch;
            border:1px solid #DBEAFE;
            background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 100%);
            border-radius:18px;
            padding:16px;
            margin:4px 0 14px;
            box-shadow:0 6px 18px rgba(15,23,42,.06);
          }
          .cv243-summary-score{
            border:1px solid #E2E8F0;
            background:#FFFFFF;
            border-radius:15px;
            padding:15px;
            display:flex;
            flex-direction:column;
            justify-content:center;
          }
          .cv243-summary-label{
            color:#64748B!important;
            font-size:10px;
            font-weight:950;
            letter-spacing:.09em;
            text-transform:uppercase;
          }
          .cv243-summary-value{
            display:flex;
            align-items:center;
            gap:8px;
            margin-top:9px;
            color:#0F172A!important;
            font-size:32px;
            line-height:1;
            font-weight:950;
            letter-spacing:-.045em;
          }
          .cv243-summary-value.bad{color:#B91C1C!important;}
          .cv243-summary-value.good{color:#047857!important;}
          .cv243-summary-copy{
            display:grid;
            grid-template-columns:1fr 1fr;
            gap:14px;
            align-content:center;
          }
          .cv243-summary-copy strong{
            display:block;
            color:#0F172A!important;
            font-size:11px;
            font-weight:950;
            letter-spacing:.06em;
            text-transform:uppercase;
            margin-bottom:7px;
          }
          .cv243-summary-copy p{
            color:#475569!important;
            font-size:12px;
            font-weight:720;
            line-height:1.48;
            margin:0;
          }
          .cv243-driver-list{
            display:grid;
            gap:5px;
          }
          .cv243-driver{
            display:flex;
            gap:7px;
            align-items:flex-start;
            color:#475569!important;
            font-size:11.5px;
            font-weight:720;
            line-height:1.4;
          }
          .cv243-driver::before{
            content:"";
            width:6px;
            height:6px;
            margin-top:5px;
            flex:0 0 auto;
            border-radius:999px;
            background:#F59E0B;
          }
          .cv232-trend-grid{
            gap:10px!important;
            margin-bottom:18px!important;
          }
          .cv232-trend-card{
            position:relative;
            min-height:102px!important;
            padding:13px 14px!important;
            border-radius:18px!important;
            box-shadow:0 6px 18px rgba(15,23,42,.06)!important;
            overflow:hidden;
          }
          .cv232-trend-card::after{
            content:"";
            position:absolute;
            inset:0 0 auto 0;
            height:3px;
            background:#94A3B8;
          }
          .cv232-trend-card.good::after{background:#16A34A;}
          .cv232-trend-card.bad::after{background:#DC2626;}
          .cv232-trend-card.warn::after{background:#F59E0B;}
          .cv243-kpi-top{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:10px;
          }
          .cv243-kpi-icon{
            width:28px;
            height:28px;
            border-radius:9px;
            display:flex;
            align-items:center;
            justify-content:center;
            background:#F8FAFC;
            border:1px solid #E2E8F0;
            color:#64748B!important;
            font-size:15px;
            font-weight:950;
          }
          .cv232-trend-value{
            font-size:30px!important;
            margin-top:9px!important;
          }
          .cv232-trend-note{
            font-size:10.5px!important;
          }
          .cv243-health-status{
            display:inline-flex;
            align-items:center;
            gap:6px;
            color:#047857!important;
            font-size:10.5px;
            font-weight:900;
          }
          .cv243-health-status::before{
            content:"";
            width:8px;
            height:8px;
            border-radius:999px;
            background:#22C55E;
            box-shadow:0 0 0 4px rgba(34,197,94,.12);
          }
          .cv243-health-status.warn{
            color:#A16207!important;
          }
          .cv243-health-status.warn::before{
            background:#F59E0B;
            box-shadow:0 0 0 4px rgba(245,158,11,.14);
          }
          .cv243-health-status.bad{
            color:#B91C1C!important;
          }
          .cv243-health-status.bad::before{
            background:#EF4444;
            box-shadow:0 0 0 4px rgba(239,68,68,.14);
          }
          .cv243-project-badge{
            display:inline-flex;
            align-items:center;
            gap:6px;
            padding:6px 9px;
            border-radius:999px;
            background:#ECFDF5;
            border:1px solid #A7F3D0;
            color:#047857!important;
            font-size:9.5px;
            font-weight:950;
            letter-spacing:.06em;
            text-transform:uppercase;
          }
          .cv243-project-badge::before{
            content:"";
            width:7px;
            height:7px;
            border-radius:999px;
            background:#22C55E;
          }
          .cv241-project-grid{
            grid-template-columns:repeat(3,minmax(0,1fr))!important;
            gap:8px!important;
            margin:11px 0!important;
          }
          .cv241-project-stat{
            border-radius:12px!important;
            padding:9px 10px!important;
          }
          .cv241-project-stat.alert{
            background:#FFFBEB!important;
            border-color:#FDE68A!important;
          }
          .cv241-project-stat.alert strong{color:#A16207!important;}
          .cv241-project-stat.risk{
            background:#FEF2F2!important;
            border-color:#FECACA!important;
          }
          .cv241-project-stat.risk strong{color:#B91C1C!important;}
          .cv241-project-stat.saved{
            background:#EFF6FF!important;
            border-color:#BFDBFE!important;
          }
          .cv241-project-stat.saved strong{color:#1D4ED8!important;}
          .cv-6b-project-link{
            min-height:40px!important;
            font-size:11.5px!important;
          }
          div[data-testid="stPlotlyChart"]{
            border-radius:18px!important;
            border:1px solid #E2E8F0!important;
            box-shadow:0 6px 18px rgba(15,23,42,.06)!important;
            padding:8px!important;
          }
          .cv-v4-section-title{
            font-size:21px!important;
            font-weight:950!important;
          }
          .cv-v4-section-meta{
            font-size:11.5px!important;
          }
          @media(max-width:900px){
            .cv243-summary{grid-template-columns:1fr;}
            .cv243-summary-copy{grid-template-columns:1fr;}
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Load dashboard data once for this page.
    analysis_response = (
        supabase.table("analyses")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .execute()
    )

    analysis_data = analysis_response.data or []
    total_analyses = len(analysis_data)

    if analysis_data:
        avg_health_score = int(
            sum(item.get("health_score", 0) or 0 for item in analysis_data)
            / max(1, total_analyses)
        )
        total_high_risk = sum(item.get("high_risk_count", 0) or 0 for item in analysis_data)
        total_medium_risk = sum(item.get("medium_risk_count", 0) or 0 for item in analysis_data)
        total_low_risk = sum(item.get("low_risk_count", 0) or 0 for item in analysis_data)
        total_components = sum(item.get("total_parts", 0) or 0 for item in analysis_data)
        latest_analysis = analysis_data[0]
    else:
        avg_health_score = 0
        total_high_risk = 0
        total_medium_risk = 0
        total_low_risk = 0
        total_components = 0
        latest_analysis = None

    try:
        alternative_history = load_alternative_history(current_user["id"])
        alternatives_found = len(alternative_history)
    except Exception:
        alternative_history = []
        alternatives_found = 0

    try:
        alert_history = (
            supabase.table("monitor_alerts")
            .select("*")
            .eq("user_id", current_user["id"])
            .order("created_at", desc=True)
            .limit(25)
            .execute()
        )
        alert_data = alert_history.data or []
    except Exception:
        alert_data = []

    alert_count = len(alert_data)
    high_alert_count = sum(1 for item in alert_data if "high" in str(item.get("severity", "")).lower())

    if avg_health_score >= 80:
        health_badge = "Healthy Portfolio"
        health_kind = "success"
    elif avg_health_score >= 55:
        health_badge = "Review Recommended"
        health_kind = "warning"
    elif avg_health_score > 0:
        health_badge = "Critical Review"
        health_kind = "danger"
    else:
        health_badge = "No Data Yet"
        health_kind = ""

    profile = get_user_profile(current_user)
    user_email = profile["email"]
    user_name = profile["full_name"].split()[0] if profile.get("full_name") else "there"
    _hour = datetime.now().hour if "datetime" in globals() else 12
    if _hour < 12:
        greeting_prefix = "Good morning"
    elif _hour < 17:
        greeting_prefix = "Good afternoon"
    else:
        greeting_prefix = "Good evening"

    def _metric(label, value, note, icon="•", kind=""):
        kind_class = f" cv-{kind}" if kind else ""
        st.markdown(
            f"""
            <div class="cv-metric{kind_class}">
                <div class="cv-metric-top">
                    <div class="cv-metric-label">{label}</div>
                    <div class="cv-metric-icon">{icon}</div>
                </div>
                <div class="cv-metric-value">{value}</div>
                <div class="cv-metric-note">{note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------
    # Cadivor Dashboard v4 — Engineering Command Center
    # Dashboard-content only. Does not touch shell/topbar/sidebar.
    # ------------------------------------------------------------------
    def _lucide_icon(name, size=18):
        icons = {
            "shield": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.68 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1z'/><path d='m9 12 2 2 4-4'/></svg>""",
            "alert": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='m21.73 18-8-14a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3'/><path d='M12 9v4'/><path d='M12 17h.01'/></svg>""",
            "activity": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M22 12h-4l-3 9L9 3l-3 9H2'/></svg>""",
            "replace": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='m16 3 4 4-4 4'/><path d='M20 7H8a4 4 0 0 0-4 4v1'/><path d='m8 21-4-4 4-4'/><path d='M4 17h12a4 4 0 0 0 4-4v-1'/></svg>""",
            "sparkles": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M9.93 2.25 8.5 7.5 3.25 8.93 8.5 10.36l1.43 5.25 1.43-5.25 5.25-1.43-5.25-1.43z'/><path d='M19 14.5 18.25 17 16 17.75l2.25.75L19 21l.75-2.5L22 17.75 19.75 17z'/></svg>""",
            "file": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z'/><path d='M14 2v4a2 2 0 0 0 2 2h4'/><path d='M10 9H8'/><path d='M16 13H8'/><path d='M16 17H8'/></svg>""",
            "clock": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><path d='M12 6v6l4 2'/></svg>""",
            "arrow": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M5 12h14'/><path d='m12 5 7 7-7 7'/></svg>""",
            "boxes": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z'/><path d='m3.3 7 8.7 5 8.7-5'/><path d='M12 22V12'/></svg>""",
            "bell": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M10.27 21a2 2 0 0 0 3.46 0'/><path d='M3.26 15.33A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.67C19.41 13.8 18 12.17 18 8A6 6 0 0 0 6 8c0 4.17-1.41 5.8-2.74 7.33'/></svg>""",
            "chart": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 3v18h18'/><path d='m7 16 4-5 4 3 5-7'/></svg>""",
            "folder": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z'/></svg>""",
        }
        return icons.get(name, icons["sparkles"]).format(s=size)

    def _fmt_date(value):
        if not value:
            return "—"
        try:
            return pd.to_datetime(value).strftime("%b %d")
        except Exception:
            return str(value)[:10]

    def _relative_date(value):
        if not value:
            return "recently"
        try:
            dt = pd.to_datetime(value, errors="coerce")
            if pd.isna(dt):
                return str(value)[:10]
            days = max(0, (pd.Timestamp.utcnow().tz_localize(None) - dt.tz_localize(None)).days)
            if days == 0:
                return "today"
            if days == 1:
                return "yesterday"
            if days < 7:
                return f"{days} days ago"
            return dt.strftime("%b %d")
        except Exception:
            return str(value)[:10]

    def _health_class(value):
        try:
            value = int(value or 0)
        except Exception:
            value = 0
        return "good" if value >= 80 else "warn" if value >= 55 else "bad"

    prev_health = None
    if analysis_data and len(analysis_data) >= 2:
        try:
            prev_health = int(analysis_data[1].get("health_score", 0) or 0)
        except Exception:
            prev_health = None
    health_delta = (avg_health_score - prev_health) if prev_health is not None else 0
    health_delta_label = f"{health_delta:+d}" if prev_health is not None else "—"
    trend_word = "improved" if health_delta >= 0 else "declined"
    latest_project = (latest_analysis or {}).get("project_name") or (latest_analysis or {}).get("filename") or "No saved BOM yet"
    latest_parts = int((latest_analysis or {}).get("total_parts", 0) or 0)
    latest_health = int((latest_analysis or {}).get("health_score", avg_health_score) or 0)
    latest_high_risk = int((latest_analysis or {}).get("high_risk_count", 0) or 0)
    latest_medium_risk = int((latest_analysis or {}).get("medium_risk_count", 0) or 0)
    latest_date = _fmt_date((latest_analysis or {}).get("created_at", ""))

    top_alert = alert_data[0] if alert_data else None
    top_alert_part = top_alert.get("part_number", "No active alert") if top_alert else "No active alert"
    top_alert_msg = top_alert.get("alert_message", "No supplier or lifecycle alerts require immediate action.") if top_alert else "No supplier or lifecycle alerts require immediate action."
    next_action_title = "Review high-risk components" if total_high_risk else "Run next BOM analysis"
    next_action_copy = f"{total_high_risk} components need engineering review before the next release." if total_high_risk else "Upload another BOM to keep the workspace intelligence current."

    # Milestone 23.2 — Portfolio trend calculations from saved analysis history.
    trend_records = []
    for item in analysis_data[:30]:
        created_at = pd.to_datetime(item.get("created_at"), errors="coerce", utc=True)
        if pd.isna(created_at):
            continue
        trend_records.append(
            {
                "created_at": created_at,
                "project": str(
                    item.get("project_name")
                    or item.get("filename")
                    or item.get("source_filename")
                    or "Saved BOM"
                ),
                "health": int(item.get("health_score", 0) or 0),
                "high_risk": int(item.get("high_risk_count", 0) or 0),
                "medium_risk": int(item.get("medium_risk_count", 0) or 0),
            }
        )

    trend_records.sort(key=lambda row: row["created_at"])
    latest_trend = trend_records[-1] if trend_records else None
    previous_trend = trend_records[-2] if len(trend_records) >= 2 else None
    trend_health_change = (
        latest_trend["health"] - previous_trend["health"]
        if latest_trend and previous_trend else 0
    )
    trend_high_risk_change = (
        latest_trend["high_risk"] - previous_trend["high_risk"]
        if latest_trend and previous_trend else 0
    )

    project_history = {}
    for row in trend_records:
        project_history.setdefault(row["project"], []).append(row)

    declining_projects = []
    improving_projects = []
    for project_name, records in project_history.items():
        if len(records) < 2:
            continue
        earlier, current = records[-2], records[-1]
        health_change = current["health"] - earlier["health"]
        risk_change = current["high_risk"] - earlier["high_risk"]
        movement = {
            "project": project_name,
            "health_change": health_change,
            "risk_change": risk_change,
            "current_health": current["health"],
        }
        if health_change < 0 or risk_change > 0:
            declining_projects.append(movement)
        elif health_change > 0 or risk_change < 0:
            improving_projects.append(movement)

    declining_projects.sort(key=lambda row: (row["health_change"], -row["risk_change"]))
    improving_projects.sort(key=lambda row: (-row["health_change"], row["risk_change"]))

    # Milestone 23.1 — Build a unified recent engineering activity feed.
    def _activity_datetime(value):
        fallback = pd.Timestamp("1970-01-01", tz="UTC")
        if not value:
            return fallback
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        return fallback if pd.isna(parsed) else parsed

    def _activity_relative(value):
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(parsed):
            return "Recently"
        now = pd.Timestamp.now(tz="UTC")
        seconds = max(0, int((now - parsed).total_seconds()))
        if seconds < 60:
            return "Just now"
        if seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = seconds // 86400
        if days == 1:
            return "Yesterday"
        if days < 7:
            return f"{days} days ago"
        return parsed.strftime("%b %d, %Y")

    recent_activity = []

    for item in analysis_data[:12]:
        project_name = (
            item.get("project_name")
            or item.get("filename")
            or item.get("source_filename")
            or "Saved BOM analysis"
        )
        analysis_id = str(item.get("id") or "")
        health = int(item.get("health_score", 0) or 0)
        parts = int(item.get("total_parts", 0) or 0)
        recent_activity.append(
            {
                "category": "Analyses",
                "type": "BOM Analysis",
                "title": str(project_name),
                "copy": f"Analysis completed with health {health}/100 across {parts} component record(s).",
                "created_at": item.get("created_at"),
                "href": (
                    f"?page=Analysis%20Details&analysis_id={html.escape(analysis_id, quote=True)}"
                    if analysis_id
                    else "?page=BOM%20Analyzer"
                ),
                "action": "Open project",
            }
        )

    for item in alert_data[:16]:
        part_number = item.get("part_number") or item.get("mpn") or "Monitored component"
        alert_type = item.get("alert_type") or item.get("change_type") or "Monitoring alert"
        message = (
            item.get("alert_message")
            or item.get("message")
            or item.get("description")
            or "A monitored component changed."
        )
        recent_activity.append(
            {
                "category": "Monitoring",
                "type": str(alert_type),
                "title": str(part_number),
                "copy": str(message),
                "created_at": item.get("created_at") or item.get("detected_at"),
                "href": "?page=Monitoring",
                "action": "Review alert",
            }
        )

    for item in alternative_history[:10]:
        original = (
            item.get("original_part")
            or item.get("original_mpn")
            or item.get("part_number")
            or "Component"
        )
        candidate = (
            item.get("alternative_part")
            or item.get("candidate_mpn")
            or item.get("recommended_part")
            or "replacement candidate"
        )
        recent_activity.append(
            {
                "category": "Replacements",
                "type": "Replacement Review",
                "title": str(original),
                "copy": f"Replacement candidate {candidate} was recorded for engineering review.",
                "created_at": item.get("created_at") or item.get("updated_at"),
                "href": "?page=Alternative%20Finder",
                "action": "Open replacement",
            }
        )

    recent_activity.sort(
        key=lambda event: _activity_datetime(event.get("created_at")),
        reverse=True,
    )

    # Milestone 24.2 — Collapse consecutive duplicate events so repeated saves
    # do not crowd the executive activity feed.
    grouped_activity = []
    for event in recent_activity:
        signature = (
            str(event.get("category") or ""),
            str(event.get("type") or ""),
            str(event.get("title") or ""),
            str(event.get("copy") or ""),
        )
        if grouped_activity and grouped_activity[-1].get("_signature") == signature:
            grouped_activity[-1]["repeat_count"] += 1
            continue
        grouped_event = dict(event)
        grouped_event["repeat_count"] = 1
        grouped_event["_signature"] = signature
        grouped_activity.append(grouped_event)
    recent_activity = grouped_activity

    st.markdown(
        """
        <style id="cadivor-dashboard-v4-command-center">
        .cv-v4-eyebrow{display:flex;align-items:center;gap:8px;color:#64748B!important;font-size:11px;font-weight:950;text-transform:uppercase;letter-spacing:.11em;margin:0 0 12px 0;}
        .cv-v4-eyebrow svg{color:#2563EB;}
        .cv-v4-command{background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 54%,#EEF6FF 100%);border:1px solid #BFDBFE;border-radius:24px;padding:22px 26px 24px;box-shadow:0 28px 70px rgba(15,23,42,.075);margin-bottom:16px;position:relative;overflow:hidden;}
        .cv-v4-command:after{content:"";position:absolute;right:-120px;top:-160px;width:360px;height:360px;background:radial-gradient(circle,rgba(37,99,235,.13),rgba(37,99,235,0) 68%);pointer-events:none;}
        .cv-v4-command-grid{display:grid;grid-template-columns:1.08fr .92fr;gap:22px;align-items:center;position:relative;z-index:1;}
        .cv-v4-kicker{display:inline-flex;align-items:center;gap:8px;padding:7px 11px;border-radius:999px;background:#EFF6FF;border:1px solid #DBEAFE;color:#2563EB!important;font-size:10.5px;font-weight:950;text-transform:uppercase;letter-spacing:.10em;margin-bottom:12px;}
        .cv-v4-title{color:#0B1220!important;font-size:34px;font-weight:980;letter-spacing:-.055em;line-height:1.04;margin:0 0 8px;}
        .cv-v4-copy{color:#52647A!important;font-size:13.5px;font-weight:750;line-height:1.55;margin:0 0 16px;max-width:780px;}
        .cv-v4-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
        .cv-v4-btn{display:inline-flex;align-items:center;gap:8px;border-radius:12px;padding:11px 15px;text-decoration:none!important;font-weight:950;font-size:12.5px;border:1px solid #2563EB;background:#2563EB;color:#fff!important;box-shadow:0 16px 34px rgba(37,99,235,.22);}
        .cv-v4-btn.secondary{background:#fff;color:#2563EB!important;border-color:#BFDBFE;box-shadow:none;}
        .cv-v4-brief{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
        .cv-v4-brief-card{background:rgba(255,255,255,.88);border:1px solid #E2E8F0;border-radius:18px;padding:14px 15px;box-shadow:0 14px 34px rgba(15,23,42,.045);}
        .cv-v4-brief-card strong{display:block;color:#0B1220!important;font-size:24px;font-weight:980;letter-spacing:-.045em;line-height:1;margin-bottom:5px;}
        .cv-v4-brief-card span{display:block;color:#64748B!important;font-size:10.5px;font-weight:950;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;}
        .cv-v4-brief-card small{display:block;color:#334155!important;font-size:12px;font-weight:850;line-height:1.3;}
        .cv-v4-insights{display:grid;grid-template-columns:1.15fr 1fr 1fr;gap:12px;margin:0 0 16px;}
        .cv-v4-insight{background:#fff;border:1px solid #E2E8F0;border-radius:20px;padding:18px;box-shadow:0 16px 42px rgba(15,23,42,.055);display:grid;grid-template-columns:46px 1fr;gap:14px;align-items:flex-start;min-height:134px;}
        .cv-v4-insight:hover,.cv-v4-action:hover,.cv-v4-analysis-row:hover{transform:translateY(-2px);box-shadow:0 24px 58px rgba(15,23,42,.085);border-color:#BFDBFE;transition:all .16s ease;}
        .cv-v4-icon{width:44px;height:44px;border-radius:15px;display:flex;align-items:center;justify-content:center;border:1px solid #DBEAFE;background:#EFF6FF;color:#2563EB;}
        .cv-v4-icon.danger{background:#FEF2F2;border-color:#FECACA;color:#DC2626}.cv-v4-icon.warning{background:#FFFBEB;border-color:#FDE68A;color:#B45309}.cv-v4-icon.success{background:#ECFDF5;border-color:#A7F3D0;color:#047857}
        .cv-v4-label{color:#64748B!important;font-size:10.5px;font-weight:950;text-transform:uppercase;letter-spacing:.11em;margin-bottom:7px;}
        .cv-v4-headline{color:#0B1220!important;font-size:16px;font-weight:980;letter-spacing:-.025em;line-height:1.15;margin-bottom:8px;}
        .cv-v4-text{color:#475569!important;font-size:12.5px;font-weight:760;line-height:1.45;}
        .cv-v4-pill{display:inline-flex;align-items:center;border-radius:999px;padding:6px 10px;background:#F8FAFC;border:1px solid #E2E8F0;color:#334155!important;font-size:11px;font-weight:950;margin-top:10px;}
        .cv-v4-metrics{display:grid;grid-template-columns:1.15fr repeat(3,1fr);gap:12px;margin-bottom:20px;}
        .cv-v4-metric{background:#fff;border:1px solid #E2E8F0;border-radius:20px;padding:18px;box-shadow:0 16px 42px rgba(15,23,42,.052);min-height:138px;position:relative;overflow:hidden;}
        .cv-v4-metric.primary{background:linear-gradient(135deg,#FFFFFF,#F8FBFF);border-color:#BFDBFE;}
        .cv-v4-metric .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.cv-v4-metric .name{color:#64748B!important;font-size:10.5px;font-weight:950;text-transform:uppercase;letter-spacing:.10em}.cv-v4-metric .icon{color:#2563EB;background:#EFF6FF;border:1px solid #DBEAFE;border-radius:13px;width:36px;height:36px;display:flex;align-items:center;justify-content:center}.cv-v4-metric .value{color:#0B1220!important;font-size:40px;font-weight:980;letter-spacing:-.05em;line-height:1;margin-bottom:8px}.cv-v4-metric .note{color:#334155!important;font-size:12px;font-weight:850;line-height:1.35}.cv-v4-metric .delta{color:#047857!important;background:#ECFDF5;border:1px solid #A7F3D0;border-radius:999px;padding:4px 8px;font-size:11px;font-weight:950;display:inline-flex;margin-top:10px}.cv-v4-metric .delta.bad{color:#B91C1C!important;background:#FEF2F2;border-color:#FECACA;}
        .cv-panel-title{letter-spacing:-.035em!important}.cv-panel-copy{color:#64748B!important;font-weight:700!important;}
        .cv-v4-section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin:4px 0 12px;}.cv-v4-section-title{color:#0B1220!important;font-size:19px;font-weight:980;letter-spacing:-.04em;line-height:1.05}.cv-v4-section-meta{color:#64748B!important;font-size:12px;font-weight:780;margin-top:5px;}.cv-v4-chip{border:1px solid #DBEAFE;background:#EFF6FF;color:#2563EB!important;border-radius:999px;padding:7px 10px;font-size:11px;font-weight:950;white-space:nowrap;}
        .cv-v4-analysis-list{display:grid;gap:8px}.cv-v4-analysis-row{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;background:#fff;border:1px solid #E2E8F0;border-radius:17px;padding:13px 14px;box-shadow:0 10px 26px rgba(15,23,42,.04)}.cv-v4-analysis-title{color:#0B1220!important;font-size:13px;font-weight:980;margin-bottom:4px}.cv-v4-analysis-meta{color:#64748B!important;font-size:11.5px;font-weight:800}.cv-v4-row-pills{display:flex;gap:8px;align-items:center}.cv-v4-score{border-radius:999px;padding:6px 9px;font-size:11px;font-weight:950;border:1px solid #A7F3D0;background:#ECFDF5;color:#047857!important}.cv-v4-score.warn{border-color:#FDE68A;background:#FFFBEB;color:#B45309!important}.cv-v4-score.bad{border-color:#FECACA;background:#FEF2F2;color:#B91C1C!important}.cv-v4-open{color:#2563EB!important;font-size:12px;font-weight:950;text-decoration:none!important;}
        .cv-v4-snapshot{background:#fff;border:1px solid #E2E8F0;border-radius:22px;padding:20px;box-shadow:0 18px 46px rgba(15,23,42,.055)}.cv-v4-snapshot-title{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:16px}.cv-v4-project{color:#0B1220!important;font-size:22px;font-weight:980;letter-spacing:-.045em;line-height:1.15}.cv-v4-snapshot-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.cv-v4-snapshot-cell{border:1px solid #E2E8F0;background:linear-gradient(180deg,#FFFFFF,#F8FAFC);border-radius:16px;padding:13px}.cv-v4-snapshot-cell span{display:block;color:#64748B!important;font-size:10.5px;font-weight:950;text-transform:uppercase;letter-spacing:.08em;margin-bottom:7px}.cv-v4-snapshot-cell strong{color:#0B1220!important;font-size:23px;font-weight:980;}
        .cv-v4-action-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.cv-v4-action{background:linear-gradient(180deg,#FFFFFF,#F8FAFC);border:1px solid #E2E8F0;border-radius:20px;padding:18px;text-decoration:none!important;color:inherit!important;box-shadow:0 16px 42px rgba(15,23,42,.052);min-height:142px}.cv-v4-action .icon{width:38px;height:38px;border-radius:13px;display:flex;align-items:center;justify-content:center;background:#EFF6FF;border:1px solid #DBEAFE;color:#2563EB;margin-bottom:14px}.cv-v4-action .title{color:#0B1220!important;font-size:14px;font-weight:980;margin-bottom:6px}.cv-v4-action .copy{color:#52647A!important;font-size:12px;font-weight:760;line-height:1.45;margin-bottom:10px}.cv-v4-action .meta{color:#2563EB!important;font-size:11px;font-weight:950;}
        /* Milestone 6.0A — premium, calm dashboard intelligence */
        /* Milestone 6.0B.4 — target visual implementation and chart repair */
        .cv-6b-kpi-strip{
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:14px;
            margin:8px 0 34px;
        }
        .cv-6b-kpi{
            display:grid;
            grid-template-columns:48px minmax(0,1fr);
            gap:14px;
            align-items:start;
            min-width:0;
            min-height:154px;
            padding:18px;
            color:inherit!important;
            text-decoration:none!important;
            background:#FFFFFF;
            border:1px solid #E2E8F0;
            border-radius:18px;
            box-shadow:0 12px 30px rgba(15,23,42,.045);
            transition:background .16s ease, transform .16s ease, border-color .16s ease, box-shadow .16s ease;
        }
        .cv-6b-kpi:hover{
            background:#F8FBFF;
            border-color:#BFDBFE;
            box-shadow:0 16px 36px rgba(37,99,235,.08);
            transform:translateY(-2px);
        }
        .cv-6b-kpi-icon{
            width:46px;
            height:46px;
            border-radius:14px;
            display:flex;
            align-items:center;
            justify-content:center;
            background:#EFF6FF;
            border:1px solid #BFDBFE;
            color:#2563EB!important;
            margin-top:1px;
        }
        .cv-6b-kpi-copy{min-width:0;}
        .cv-6b-kpi.warn .cv-6b-kpi-icon{
            background:#FFF7ED;
            border-color:#FED7AA;
            color:#C2410C!important;
        }
        .cv-6b-kpi.danger .cv-6b-kpi-icon{
            background:#FEF2F2;
            border-color:#FECACA;
            color:#B91C1C!important;
        }
        .cv-6b-kpi span{
            display:block;
            color:#64748B!important;
            font-size:10px;
            font-weight:950;
            letter-spacing:.09em;
            text-transform:uppercase;
            margin-bottom:5px;
        }
        .cv-6b-kpi strong{
            color:#0B1220!important;
            font-size:25px;
            line-height:1;
            font-weight:980;
            letter-spacing:-.035em;
        }
        .cv-6b-kpi small{
            display:block;
            color:#64748B!important;
            font-size:10.5px;
            font-weight:760;
            margin-top:6px;
            line-height:1.35;
        }
        .cv-6b-main-grid{
            display:grid;
            grid-template-columns:minmax(0,1.55fr) minmax(310px,.7fr);
            gap:16px;
            align-items:stretch;
            margin-bottom:18px;
        }
        .cv-6b-panel{
            background:#FFFFFF;
            border:1px solid #E2E8F0;
            border-radius:20px;
            padding:20px;
            box-shadow:0 16px 42px rgba(15,23,42,.05);
        }
        .cv-6b-project-panel{
            min-height:268px;
            display:flex;
            flex-direction:column;
            transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
        }
        .cv-6b-project-panel:hover{
            transform:translateY(-2px);
            border-color:#BFDBFE;
            box-shadow:0 18px 44px rgba(37,99,235,.09);
        }
        .cv241-project-grid{
            display:grid;
            grid-template-columns:repeat(3,minmax(0,1fr));
            gap:9px;
            margin:12px 0;
        }
        .cv241-project-stat{
            background:#F8FAFC;
            border:1px solid #E2E8F0;
            border-radius:13px;
            padding:10px 11px;
            min-width:0;
        }
        .cv241-project-stat span{
            display:block;
            color:#64748B!important;
            font-size:9px;
            font-weight:950;
            letter-spacing:.07em;
            text-transform:uppercase;
            margin-bottom:5px;
        }
        .cv241-project-stat strong{
            display:block;
            color:#0F172A!important;
            font-size:19px;
            font-weight:980;
            line-height:1;
        }
        .cv241-status-line{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:10px;
            color:#64748B!important;
            font-size:10.5px;
            font-weight:760;
            margin:2px 0 11px;
        }
        .cv241-status-dot{
            display:inline-flex;
            align-items:center;
            gap:6px;
        }
        .cv241-status-dot::before{
            content:"";
            width:8px;
            height:8px;
            border-radius:999px;
            background:#22C55E;
            box-shadow:0 0 0 4px rgba(34,197,94,.12);
        }
        .cv242-status-note{
            display:inline-flex;
            align-items:center;
            gap:8px;
            width:auto;
            max-width:100%;
            padding:9px 12px;
            margin-top:8px;
            border:1px solid #BBF7D0;
            border-radius:12px;
            background:#F0FDF4;
            color:#166534!important;
            font-size:10.5px;
            font-weight:850;
            line-height:1.35;
        }
        .cv242-status-note::before{
            content:"✓";
            display:inline-grid;
            place-items:center;
            width:18px;
            height:18px;
            border-radius:999px;
            background:#DCFCE7;
            color:#15803D;
            font-size:11px;
            font-weight:950;
            flex:0 0 auto;
        }
        .cv242-repeat-badge{
            display:inline-flex;
            align-items:center;
            border-radius:999px;
            padding:3px 7px;
            margin-left:7px;
            background:#EFF6FF;
            border:1px solid #BFDBFE;
            color:#2563EB!important;
            font-size:9px;
            font-weight:950;
            vertical-align:middle;
        }
        .cv-6b-trend-chart-anchor + div [data-testid="stPlotlyChart"],
        .cv-6b-trend-chart-anchor ~ div [data-testid="stPlotlyChart"]{
            height:230px!important;
            min-height:230px!important;
            background:#FFFFFF!important;
            border:1px solid #E2E8F0!important;
            border-radius:20px!important;
            box-shadow:0 16px 42px rgba(15,23,42,.05)!important;
            padding:10px!important;
            overflow:hidden!important;
        }
        .cv-6b-trend-chart-anchor + div [data-testid="stPlotlyChart"] > div,
        .cv-6b-trend-chart-anchor ~ div [data-testid="stPlotlyChart"] > div,
        .cv-6b-trend-chart-anchor ~ div .js-plotly-plot,
        .cv-6b-trend-chart-anchor ~ div .plot-container,
        .cv-6b-trend-chart-anchor ~ div .svg-container{
            height:100%!important;
            border-radius:16px!important;
            overflow:hidden!important;
        }
        .cv-6b-project-panel .cv-6b-project-link{
            margin-top:auto;
        }
        .cv-6b-column-heading{
            min-height:54px;
            display:flex;
            align-items:flex-end;
            justify-content:space-between;
            gap:14px;
            margin-bottom:8px;
        }
        .cv-6b-column-heading > div{
            min-width:0;
            text-align:left;
        }
        .cv-6b-project-head{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:14px;
            margin-bottom:16px;
        }
        .cv-6b-project-title{
            color:#0B1220!important;
            font-size:21px;
            line-height:1.2;
            font-weight:980;
            letter-spacing:-.035em;
            margin-top:4px;
        }
        .cv-6b-project-meta{
            display:grid;
            grid-template-columns:repeat(2,minmax(0,1fr));
            gap:10px;
            margin-bottom:15px;
        }
        .cv-6b-project-stat{
            background:#F8FAFC;
            border:1px solid #E2E8F0;
            border-radius:14px;
            padding:12px;
        }
        .cv-6b-project-stat span{
            display:block;
            color:#64748B!important;
            font-size:9.5px;
            font-weight:950;
            text-transform:uppercase;
            letter-spacing:.08em;
            margin-bottom:5px;
        }
        .cv-6b-project-stat strong{
            color:#0B1220!important;
            font-size:21px;
            font-weight:980;
        }
        .cv-6b-project-link{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            padding:11px 13px;
            border-radius:13px;
            background:#EFF6FF;
            border:1px solid #BFDBFE;
            color:#2563EB!important;
            text-decoration:none!important;
            font-size:12px;
            font-weight:900;
        }
        .cv-6b-project-link:hover{
            background:#DBEAFE;
            transform:translateY(-1px);
            transition:all .16s ease;
        }
        .cv-6b-shortcuts{
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:10px;
            margin-bottom:4px;
        }
        .cv-6b-shortcut{
            display:grid;
            grid-template-columns:40px minmax(0,1fr) auto;
            align-items:center;
            gap:12px;
            min-height:72px;
            padding:14px;
            background:#FFFFFF;
            border:1px solid #E2E8F0;
            border-radius:16px;
            color:inherit!important;
            text-decoration:none!important;
            box-shadow:0 10px 28px rgba(15,23,42,.035);
        }
        .cv-6b-shortcut:hover{
            border-color:#BFDBFE;
            background:#F8FBFF;
            transform:translateY(-1px);
            transition:all .16s ease;
        }
        .cv-6b-shortcut strong{
            display:block;
            color:#0B1220!important;
            font-size:12px;
            font-weight:950;
            margin-bottom:3px;
        }
        .cv-6b-shortcut span{
            display:block;
            color:#64748B!important;
            font-size:10.5px;
            font-weight:760;
            line-height:1.35;
        }
        .cv-6b-shortcut-icon{
            width:38px;height:38px;border-radius:12px;display:flex;align-items:center;justify-content:center;
            background:#EFF6FF;border:1px solid #BFDBFE;color:#2563EB!important;
        }
        .cv-6b-shortcut-icon.green{background:#ECFDF5;border-color:#A7F3D0;color:#16A34A!important;}
        .cv-6b-shortcut-icon.purple{background:#F5F3FF;border-color:#DDD6FE;color:#7C3AED!important;}
        .cv-6b-shortcut-icon.amber{background:#FFFBEB;border-color:#FDE68A;color:#D97706!important;}
        .cv-6b-arrow{
            color:#2563EB!important;
            font-size:15px;
            font-weight:950;
            flex:0 0 auto;
        }
        @media(max-width:1100px){
            .cv-6b-main-grid{grid-template-columns:1fr;}
            .cv-6b-shortcuts{grid-template-columns:repeat(2,minmax(0,1fr));}
        }
        @media(max-width:760px){
            .cv-6b-kpi-strip{grid-template-columns:repeat(2,minmax(0,1fr));}
            
            .cv-6b-shortcuts{grid-template-columns:1fr;}
        }

        .cv-6a-command{padding:24px 26px!important;margin-bottom:18px!important;}
        .cv-6a-command .cv-v4-command-grid{grid-template-columns:minmax(0,1.25fr) minmax(360px,.75fr)!important;gap:24px!important;}
        .cv-6a-command .cv-v4-title{font-size:36px!important;max-width:760px!important;}
        .cv-6a-command .cv-v4-copy{max-width:720px!important;margin-bottom:18px!important;}
        .cv-6a-command .cv-v4-brief{grid-template-columns:repeat(2,minmax(0,1fr))!important;}
        .cv-6a-command .cv-v4-brief-card{padding:15px 16px!important;min-height:92px!important;}
        .cv-6a-command .cv-v4-brief-card strong{font-size:27px!important;}
        .cv-6a-briefing{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(340px,.85fr);gap:14px;margin-bottom:18px;}
        .cv-6a-focus,.cv-6a-actions-card{background:#fff;border:1px solid #E2E8F0;border-radius:20px;padding:20px;box-shadow:0 16px 42px rgba(15,23,42,.052);}
        .cv-6a-focus{display:grid;grid-template-columns:48px 1fr;gap:15px;align-items:start;}
        .cv-6a-focus-icon{width:46px;height:46px;border-radius:15px;display:flex;align-items:center;justify-content:center;background:#FEF2F2;border:1px solid #FECACA;color:#B91C1C;}
        .cv-6a-label{color:#64748B!important;font-size:10.5px;font-weight:950;text-transform:uppercase;letter-spacing:.09em;margin-bottom:6px;}
        .cv-6a-headline{color:#0B1220!important;font-size:20px;font-weight:980;letter-spacing:-.035em;line-height:1.2;margin-bottom:7px;}
        .cv-6a-text{color:#52647A!important;font-size:12.5px;font-weight:760;line-height:1.55;}
        .cv-6a-actions-card{display:grid;gap:10px;}
        .cv-6a-action-row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:11px 12px;border:1px solid #E2E8F0;border-radius:14px;background:#F8FAFC;text-decoration:none!important;}
        .cv-6a-action-row:hover{border-color:#BFDBFE;background:#EFF6FF;transform:translateY(-1px);transition:all .16s ease;}
        .cv-6a-action-row strong{display:block;color:#0B1220!important;font-size:12.5px;font-weight:950;margin-bottom:3px;}
        .cv-6a-action-row span{display:block;color:#64748B!important;font-size:11px;font-weight:760;}
        .cv-6a-action-arrow{color:#2563EB!important;font-weight:950;font-size:14px;}
        .cv-v4-metrics{grid-template-columns:1.15fr repeat(3,1fr)!important;gap:12px!important;margin-bottom:18px!important;}
        .cv-v4-metric{min-height:124px!important;padding:17px!important;}
        .cv-v4-metric .value{font-size:36px!important;}
        @media(max-width:1180px){.cv-v4-command-grid,.cv-v4-insights,.cv-v4-metrics,.cv-6a-briefing{grid-template-columns:1fr!important}.cv-v4-action-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        div[data-testid="stHorizontalBlock"]:has(.cv231-activity-card) > div{min-width:0!important;}
        @media(max-width:760px){.cv-v4-action-grid,.cv-v4-brief{grid-template-columns:1fr!important}.cv-v4-analysis-row{grid-template-columns:1fr}.cv-v4-row-pills{justify-content:flex-start}.cv-v4-title{font-size:28px}.cv-6a-command .cv-v4-brief{grid-template-columns:1fr!important}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <section class="cv-v4-command cv-6a-command">
          <div class="cv-v4-command-grid">
            <div>
              <div class="cv-v4-kicker">{_lucide_icon('sparkles',14)} Engineering Command Center</div>
              <h1 class="cv-v4-title">{greeting_prefix}, {html.escape(user_name)}.</h1>
              <p class="cv-v4-copy">Your portfolio has <strong>{total_high_risk} high-risk components</strong> and <strong>{alert_count} active supplier alerts</strong>. Start with the most important engineering decision, then move into the detailed workspace only when needed.</p>
              <div class="cv-v4-actions">
                <a class="cv-v4-btn" href="?page=BOM%20Analyzer" target="_self">Analyze New BOM {_lucide_icon('arrow',14)}</a>
                <a class="cv-v4-btn secondary" href="?page=Alternative%20Finder" target="_self">Replacement Finder</a>
              </div>
            </div>
            <div class="cv-v4-brief">
              <div class="cv-v4-brief-card"><span>Portfolio Health</span><strong>{avg_health_score}</strong><small>{health_badge} • {health_delta_label} vs previous</small></div>
              <div class="cv-v4-brief-card"><span>High Risk</span><strong>{total_high_risk}</strong><small>Components requiring review</small></div>
              <div class="cv-v4-brief-card"><span>Supplier Alerts</span><strong>{alert_count}</strong><small>{high_alert_count} high severity</small></div>
              <div class="cv-v4-brief-card"><span>Saved Analyses</span><strong>{total_analyses}</strong><small>Engineering records available</small></div>
            </div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if _qp_value("focus", "") == "search":
        render_global_search_panel(current_user["id"])

    st.markdown(f'<div class="cv-v4-eyebrow">{_lucide_icon("sparkles",15)} Today\'s Engineering Brief</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="cv-6a-briefing">
          <div class="cv-6a-focus">
            <div class="cv-6a-focus-icon">{_lucide_icon('alert',20)}</div>
            <div>
              <div class="cv-6a-label">Primary Engineering Priority</div>
              <div class="cv-6a-headline">{html.escape(next_action_title)}</div>
              <div class="cv-6a-text">{html.escape(next_action_copy)} Portfolio health has {trend_word} by {abs(health_delta)} points compared with the previous saved analysis.</div>
            </div>
          </div>
          <div class="cv-6a-actions-card">
            <a class="cv-6a-action-row" href="?page=Monitoring" target="_self">
              <div><strong>Review supplier alerts</strong><span>{alert_count} active • {high_alert_count} high severity</span></div>
              <div class="cv-6a-action-arrow">→</div>
            </a>
            <a class="cv-6a-action-row" href="?page=Alternative%20Finder" target="_self">
              <div><strong>Validate replacements</strong><span>{alternatives_found} saved candidate records</span></div>
              <div class="cv-6a-action-arrow">→</div>
            </a>
            <a class="cv-6a-action-row" href="?page=Reports" target="_self">
              <div><strong>Generate engineering report</strong><span>PDF and CSV reporting workspace</span></div>
              <div class="cv-6a-action-arrow">→</div>
            </a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="cv-v4-section-head">
          <div>
            <div class="cv-v4-section-title">Portfolio Snapshot</div>
            <div class="cv-v4-section-meta">Only the essential signals needed to decide where to go next.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="cv-6b-kpi-strip">
          <a class="cv-6b-kpi" href="?page=Reports" target="_self" title="Open portfolio analyses and reports">
            <div class="cv-6b-kpi-icon">{_lucide_icon('shield',23)}</div>
            <div class="cv-6b-kpi-copy">
              <span>Portfolio Health</span>
              <strong>{avg_health_score}</strong>
              <small style="color:#DC2626!important;">{health_delta_label} vs previous</small>
              <small style="color:#2563EB!important;margin-top:14px;">View details →</small>
            </div>
          </a>
          <a class="cv-6b-kpi warn" href="?page=BOM%20Analyzer" target="_self" title="Open BOM analyses requiring review">
            <div class="cv-6b-kpi-icon">{_lucide_icon('alert',23)}</div>
            <div class="cv-6b-kpi-copy">
              <span>High Risk</span>
              <strong>{total_high_risk}</strong>
              <small>Components requiring review</small>
              <small style="color:#2563EB!important;margin-top:14px;">Open analyzer →</small>
            </div>
          </a>
          <a class="cv-6b-kpi danger" href="?page=Monitoring" target="_self" title="Open supplier and lifecycle monitoring">
            <div class="cv-6b-kpi-icon">{_lucide_icon('bell',23)}</div>
            <div class="cv-6b-kpi-copy">
              <span>Supplier Alerts</span>
              <strong>{alert_count}</strong>
              <small>{high_alert_count} high severity</small>
              <small style="color:#2563EB!important;margin-top:14px;">Review alerts →</small>
            </div>
          </a>
          <a class="cv-6b-kpi" href="?page=Reports" target="_self" title="Open saved analyses and report sources">
            <div class="cv-6b-kpi-icon">{_lucide_icon('file',23)}</div>
            <div class="cv-6b-kpi-copy">
              <span>Saved Analyses</span>
              <strong>{total_analyses}</strong>
              <small>Engineering records available</small>
              <small style="color:#2563EB!important;margin-top:14px;">Open reports →</small>
            </div>
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Milestone 24.1 — Put executive signals before supporting charts.
    if latest_trend and previous_trend:
        health_direction = (
            "improved"
            if trend_health_change > 0
            else "declined"
            if trend_health_change < 0
            else "held steady"
        )
        risk_direction = (
            "increased"
            if trend_high_risk_change > 0
            else "decreased"
            if trend_high_risk_change < 0
            else "did not change"
        )
        trend_summary = (
            f"Portfolio health {health_direction} by {abs(trend_health_change)} point(s), "
            f"while high-risk component exposure {risk_direction} by "
            f"{abs(trend_high_risk_change)} compared with the previous saved analysis."
        )
    elif latest_trend:
        trend_summary = (
            "One saved analysis is available. Save another analysis to begin "
            "measuring portfolio movement."
        )
    else:
        trend_summary = (
            "No saved analysis history is available yet. Analyze and save a BOM "
            "to begin tracking trends."
        )

    recent_alerts_7d = 0
    now_utc = pd.Timestamp.now(tz="UTC")
    for alert in alert_data:
        alert_time = pd.to_datetime(
            alert.get("created_at") or alert.get("detected_at"),
            errors="coerce",
            utc=True,
        )
        if not pd.isna(alert_time) and (now_utc - alert_time).days <= 7:
            recent_alerts_7d += 1

    st.markdown(
        """
        <div class="cv-v4-section-head" style="margin-top:14px;">
          <div>
            <div class="cv-v4-section-title">Executive Analytics</div>
            <div class="cv-v4-section-meta">The latest portfolio movement and areas needing attention.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    health_change_class = (
        "good" if trend_health_change > 0
        else "bad" if trend_health_change < 0
        else ""
    )
    health_change_icon = (
        "↑" if trend_health_change > 0
        else "↓" if trend_health_change < 0
        else "→"
    )
    risk_change_icon = (
        "↓" if trend_high_risk_change < 0
        else "↑" if trend_high_risk_change > 0
        else "→"
    )
    primary_driver_1 = (
        f"{recent_alerts_7d} monitoring alert(s) were recorded in the last seven days."
        if recent_alerts_7d
        else "No new monitoring alerts were recorded in the last seven days."
    )
    primary_driver_2 = (
        f"{len(declining_projects)} saved project(s) are moving in the wrong direction."
        if declining_projects
        else "No saved project is currently trending downward."
    )
    primary_driver_3 = (
        f"High-risk exposure changed by {trend_high_risk_change:+d} compared with the previous analysis."
    )

    st.markdown(
        f"""
        <section class="cv243-summary">
          <div class="cv243-summary-score">
            <div class="cv243-summary-label">Portfolio Health Change</div>
            <div class="cv243-summary-value {health_change_class}">
              <span>{health_change_icon}</span>
              <span>{trend_health_change:+d}</span>
            </div>
            <div class="cv232-trend-note" style="margin-top:8px;">
              Latest saved analysis versus previous
            </div>
          </div>
          <div class="cv243-summary-copy">
            <div>
              <strong>Primary Drivers</strong>
              <div class="cv243-driver-list">
                <div class="cv243-driver">{html.escape(primary_driver_1)}</div>
                <div class="cv243-driver">{html.escape(primary_driver_2)}</div>
                <div class="cv243-driver">{html.escape(primary_driver_3)}</div>
              </div>
            </div>
            <div>
              <strong>Recommended Action</strong>
              <p>{html.escape(next_action_copy)}</p>
              <p style="margin-top:7px;color:#2563EB!important;font-weight:900;">
                {html.escape(next_action_title)}
              </p>
            </div>
          </div>
        </section>

        <section class="cv232-trend-grid">
          <div class="cv232-trend-card {health_change_class}">
            <div class="cv243-kpi-top">
              <div class="cv232-trend-label">Health Change</div>
              <div class="cv243-kpi-icon">{health_change_icon}</div>
            </div>
            <div class="cv232-trend-value">{trend_health_change:+d}</div>
            <div class="cv232-trend-note">Versus previous analysis</div>
          </div>
          <div class="cv232-trend-card {'good' if trend_high_risk_change < 0 else 'bad' if trend_high_risk_change > 0 else ''}">
            <div class="cv243-kpi-top">
              <div class="cv232-trend-label">High-Risk Change</div>
              <div class="cv243-kpi-icon">{risk_change_icon}</div>
            </div>
            <div class="cv232-trend-value">{trend_high_risk_change:+d}</div>
            <div class="cv232-trend-note">Fewer high-risk records is better</div>
          </div>
          <div class="cv232-trend-card {'warn' if recent_alerts_7d else ''}">
            <div class="cv243-kpi-top">
              <div class="cv232-trend-label">Recent Alerts</div>
              <div class="cv243-kpi-icon">!</div>
            </div>
            <div class="cv232-trend-value">{recent_alerts_7d}</div>
            <div class="cv232-trend-note">Last seven days</div>
          </div>
          <div class="cv232-trend-card {'bad' if declining_projects else 'good'}">
            <div class="cv243-kpi-top">
              <div class="cv232-trend-label">Projects Declining</div>
              <div class="cv243-kpi-icon">◆</div>
            </div>
            <div class="cv232-trend-value">{len(declining_projects)}</div>
            <div class="cv232-trend-note">Need management attention</div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    trend_col, project_col = st.columns([1.35, 0.78], gap="small")

    with trend_col:
        st.markdown(
            f"""
            <div class="cv-v4-section-head cv-6b-column-heading">
              <div>
                <div class="cv-v4-section-title">Portfolio Health</div>
                <div class="cv-v4-section-meta">Latest 7 recorded days • {health_delta_label} vs previous</div>
              </div>
              <a class="cv-v4-chip" href="?page=Reports" target="_self" style="text-decoration:none!important;">Open analyses →</a>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if analysis_data and len(analysis_data) >= 2:
            trend_df = pd.DataFrame(analysis_data)
            trend_df["created_at"] = pd.to_datetime(
                trend_df["created_at"], errors="coerce", utc=True
            )
            trend_df["health_score"] = pd.to_numeric(
                trend_df["health_score"], errors="coerce"
            )
            trend_df = trend_df.dropna(
                subset=["created_at", "health_score"]
            ).sort_values("created_at")

            # Use one point per day so several analyses saved close together do not
            # create vertical jumps or misleading spline loops.
            trend_df["Date"] = trend_df["created_at"].dt.floor("D")
            daily_health = (
                trend_df.groupby("Date", as_index=False)
                .agg(
                    Health_Score=("health_score", "mean"),
                    Analyses=("health_score", "size"),
                )
                .sort_values("Date")
            )
            daily_health["Health_Score"] = daily_health["Health_Score"].round(1)
            full_daily_health = daily_health.copy()
            daily_health = daily_health.tail(7).reset_index(drop=True)

            health_values = daily_health["Health_Score"].dropna()
            health_min = (
                max(0, float(health_values.min()) - 3)
                if not health_values.empty else 0
            )
            health_max = (
                min(100, float(health_values.max()) + 3)
                if not health_values.empty else 100
            )
            if health_max - health_min < 10:
                midpoint = (health_max + health_min) / 2
                health_min = max(0, midpoint - 5)
                health_max = min(100, midpoint + 5)

            fig = go.Figure()

            # A hidden baseline makes the fill subtle and limits it to the visible
            # health range instead of painting the entire chart down to zero.
            fig.add_trace(
                go.Scatter(
                    x=daily_health["Date"],
                    y=[health_min] * len(daily_health),
                    mode="lines",
                    line={"width": 0},
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=daily_health["Date"],
                    y=daily_health["Health_Score"],
                    customdata=daily_health[["Analyses"]],
                    mode="lines+markers",
                    name="Portfolio Health",
                    line={"color": "#2563EB", "width": 3, "shape": "linear"},
                    marker={
                        "size": 5,
                        "color": "#FFFFFF",
                        "line": {"color": "#2563EB", "width": 2},
                    },
                    fill="tonexty",
                    fillcolor="rgba(37, 99, 235, 0.075)",
                    hovertemplate=(
                        "<b>%{x|%b %d, %Y}</b>"
                        "<br>Daily average health: %{y:.1f}/100"
                        "<br>Saved analyses: %{customdata[0]}"
                        "<extra></extra>"
                    ),
                )
            )
            fig.update_yaxes(
                range=[health_min, health_max],
                title=None,
                tickfont={"color": "#64748B"},
                gridcolor="#EEF2F7",
                zeroline=False,
            )
            fig.update_xaxes(
                title=None,
                tickmode="array",
                tickvals=daily_health["Date"].tolist(),
                ticktext=[value.strftime("%b %d") for value in daily_health["Date"]],
                tickfont={"color": "#64748B"},
                gridcolor="#F4F7FA",
                showline=False,
            )
            fig.update_layout(
                hovermode="x unified",
                margin={"l": 4, "r": 6, "t": 4, "b": 2},
                showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.markdown(
                '<div class="cv-6b-trend-chart-anchor"></div>',
                unsafe_allow_html=True,
            )
            st.plotly_chart(
                light_plotly_layout(fig, height=205),
                use_container_width=True,
                config={
                    "displayModeBar": False,
                    "scrollZoom": False,
                    "responsive": True,
                },
            )
        else:
            st.info("Run at least two BOM analyses to generate a portfolio health trend.")

    with project_col:
        latest_analysis_id = ""
        if analysis_data:
            latest_analysis_id = str(analysis_data[0].get("id") or "")
        project_href = (
            f"?page=Analysis%20Details&analysis_id={html.escape(latest_analysis_id, quote=True)}"
            if latest_analysis_id
            else "?page=BOM%20Analyzer"
        )
        st.markdown(
            """
            <div class="cv-6b-column-heading">
              <div>
                <div class="cv-v4-section-title">Current Working BOM</div>
                <div class="cv-v4-section-meta">Continue the most recently saved engineering review.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="cv-6b-panel cv-6b-project-panel">
              <div class="cv-6b-project-head">
                <div>
                  <div class="cv243-project-badge">Active Review</div>
                  <div class="cv-6b-project-title" style="margin-top:10px;">
                    {html.escape(str(latest_project))}
                  </div>
                </div>
                <div class="cv-v4-icon">{_lucide_icon('file',18)}</div>
              </div>
              <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:3px;">
                <div class="cv243-health-status {'bad' if latest_health < 55 else 'warn' if latest_health < 80 else ''}">
                  {'Critical' if latest_health < 55 else 'Needs Review' if latest_health < 80 else 'Healthy'} · {latest_health}/100
                </div>
                <div class="cv-v4-text">Updated {html.escape(str(latest_date))}</div>
              </div>
              <div class="cv241-project-grid">
                <div class="cv241-project-stat"><span>Components</span><strong>{latest_parts}</strong></div>
                <div class="cv241-project-stat risk"><span>High Risk</span><strong>{latest_high_risk}</strong></div>
                <div class="cv241-project-stat"><span>Medium Risk</span><strong>{latest_medium_risk}</strong></div>
                <div class="cv241-project-stat alert"><span>Workspace Alerts</span><strong>{alert_count}</strong></div>
                <div class="cv241-project-stat saved"><span>Saved Candidates</span><strong>{alternatives_found}</strong></div>
                <div class="cv241-project-stat"><span>Portfolio Health</span><strong>{avg_health_score}</strong></div>
              </div>
              <a class="cv-6b-project-link" href="{project_href}" target="_self">
                <span>Continue Engineering Review</span><span>→</span>
              </a>
            </div>
            """,
            unsafe_allow_html=True,
        )

    analytics_col, activity_col = st.columns([1.08, 0.92], gap="medium")

    with analytics_col:
        st.markdown(
            """
            <div class="cv-v4-section-head cv-6b-column-heading">
              <div>
                <div class="cv-v4-section-title">Risk Movement</div>
                <div class="cv-v4-section-meta">High- and medium-risk movement over the latest recorded days.</div>
              </div>
              <a class="cv-v4-chip" href="?page=Monitoring" target="_self" style="text-decoration:none!important;">Open monitoring →</a>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if len(trend_records) >= 2:
            risk_df = pd.DataFrame(trend_records)
            risk_df["created_at"] = pd.to_datetime(
                risk_df["created_at"], errors="coerce", utc=True
            )
            risk_df["high_risk"] = pd.to_numeric(
                risk_df["high_risk"], errors="coerce"
            ).fillna(0)
            risk_df["medium_risk"] = pd.to_numeric(
                risk_df["medium_risk"], errors="coerce"
            ).fillna(0)
            risk_df = risk_df.dropna(subset=["created_at"]).sort_values("created_at")
            risk_df["Date"] = risk_df["created_at"].dt.floor("D")

            daily_risk = (
                risk_df.groupby("Date", as_index=False)
                .agg(
                    High_Risk=("high_risk", "mean"),
                    Medium_Risk=("medium_risk", "mean"),
                    Analyses=("high_risk", "size"),
                )
                .sort_values("Date")
                .tail(7)
                .reset_index(drop=True)
            )
            daily_risk["High_Risk"] = daily_risk["High_Risk"].round(1)
            daily_risk["Medium_Risk"] = daily_risk["Medium_Risk"].round(1)

            risk_max = max(
                1.0,
                float(
                    max(
                        daily_risk["High_Risk"].max(),
                        daily_risk["Medium_Risk"].max(),
                    )
                ),
            )

            risk_fig = go.Figure()
            risk_fig.add_trace(
                go.Scatter(
                    x=daily_risk["Date"],
                    y=daily_risk["Medium_Risk"],
                    customdata=daily_risk[["Analyses"]],
                    mode="lines+markers",
                    name="Medium Risk",
                    line={"color": "#F59E0B", "width": 2, "shape": "linear"},
                    marker={
                        "size": 4,
                        "color": "#FFFFFF",
                        "line": {"color": "#F59E0B", "width": 1.7},
                    },
                    hovertemplate=(
                        "<b>%{x|%b %d}</b>"
                        "<br>Average medium-risk: %{y:.1f}"
                        "<br>Saved analyses: %{customdata[0]}"
                        "<extra></extra>"
                    ),
                )
            )
            risk_fig.add_trace(
                go.Scatter(
                    x=daily_risk["Date"],
                    y=daily_risk["High_Risk"],
                    customdata=daily_risk[["Analyses"]],
                    mode="lines+markers",
                    name="High Risk",
                    line={"color": "#DC2626", "width": 2, "shape": "linear"},
                    marker={
                        "size": 4,
                        "color": "#FFFFFF",
                        "line": {"color": "#DC2626", "width": 1.7},
                    },
                    hovertemplate=(
                        "<b>%{x|%b %d}</b>"
                        "<br>Average high-risk: %{y:.1f}"
                        "<br>Saved analyses: %{customdata[0]}"
                        "<extra></extra>"
                    ),
                )
            )
            risk_fig.update_yaxes(
                range=[0, risk_max + max(1, risk_max * 0.25)],
                title=None,
                dtick=1 if risk_max <= 8 else None,
                gridcolor="#EEF2F7",
                zeroline=False,
            )
            risk_fig.update_xaxes(
                title=None,
                tickmode="array",
                tickvals=daily_risk["Date"].tolist(),
                ticktext=[value.strftime("%b %d") for value in daily_risk["Date"]],
                gridcolor="rgba(148,163,184,0.10)",
                showline=False,
            )
            risk_fig.update_layout(
                hovermode="x unified",
                legend={
                    "orientation": "h",
                    "yanchor": "bottom",
                    "y": 1.03,
                    "xanchor": "right",
                    "x": 1,
                    "font": {"size": 10},
                },
                margin={"l": 3, "r": 5, "t": 25, "b": 2},
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(
                light_plotly_layout(risk_fig, height=180),
                use_container_width=True,
                config={
                    "displayModeBar": False,
                    "scrollZoom": False,
                    "responsive": True,
                },
            )
        else:
            st.info("Save at least two BOM analyses to display risk movement.")

        if declining_projects:
            st.markdown(
                """
                <div class="cv-v4-section-head" style="margin-top:8px;">
                  <div>
                    <div class="cv-v4-section-title" style="font-size:17px;">Projects Requiring Attention</div>
                    <div class="cv-v4-section-meta">Only projects moving in the wrong direction are shown.</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            for project in declining_projects[:3]:
                project_name = html.escape(str(project.get("project_name") or "Saved BOM"))
                health_change = int(project.get("health_change", 0) or 0)
                risk_change = int(project.get("high_risk_change", 0) or 0)
                explanation_parts = []
                if health_change < 0:
                    explanation_parts.append(f"health {health_change:+d}")
                if risk_change > 0:
                    explanation_parts.append(f"high-risk {risk_change:+d}")
                explanation = " • ".join(explanation_parts) or "Recorded risk increased"
                st.markdown(
                    f"""
                    <div class="cv231-activity-card" style="padding:12px 14px;">
                      <div class="cv231-activity-type">Needs Attention</div>
                      <div class="cv231-activity-title">{project_name}</div>
                      <div class="cv231-activity-copy">{html.escape(explanation)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="cv242-status-note">No saved projects are currently trending downward.</div>',
                unsafe_allow_html=True,
            )

    with activity_col:
        st.markdown(
            """
            <div class="cv-v4-section-head cv-6b-column-heading">
              <div>
                <div class="cv-v4-section-title">Recent Activity</div>
                <div class="cv-v4-section-meta">Repeated identical events are grouped for a cleaner review.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        visible_activity = recent_activity[:4]
        if visible_activity:
            for event in visible_activity:
                st.markdown(
                    f"""
                    <section class="cv231-activity-card" style="padding:12px 14px;margin-bottom:9px;">
                      <div class="cv231-activity-top">
                        <div class="cv231-activity-type">{html.escape(str(event['type']))}</div>
                        <div class="cv231-activity-time">{html.escape(_activity_relative(event.get('created_at')))}</div>
                      </div>
                      <div class="cv231-activity-title">
                        {html.escape(str(event['title']))}
                        {f'<span class="cv242-repeat-badge">{event.get("repeat_count", 1)} repeated</span>' if event.get("repeat_count", 1) > 1 else ''}
                      </div>
                      <div class="cv231-activity-copy">{html.escape(str(event['copy']))}</div>
                      <a class="cv231-activity-link" href="{event['href']}" target="_self">
                        {html.escape(str(event['action']))} →
                      </a>
                    </section>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="cv231-empty">No recent engineering activity is recorded.</div>',
                unsafe_allow_html=True,
            )

        if len(recent_activity) > 4:
            with st.expander(
                f"View complete activity history ({len(recent_activity)})",
                expanded=False,
            ):
                activity_rows = pd.DataFrame(
                    [
                        {
                            "When": _activity_relative(event.get("created_at")),
                            "Type": event["type"],
                            "Item": event["title"],
                            "Activity": (
                                f'{event["copy"]} (Repeated {event.get("repeat_count", 1)} times)'
                                if event.get("repeat_count", 1) > 1
                                else event["copy"]
                            ),
                        }
                        for event in recent_activity
                    ]
                )
                st.dataframe(
                    activity_rows,
                    use_container_width=True,
                    hide_index=True,
                    height=min(420, 38 + len(activity_rows) * 34),
                )

    st.markdown(
        """
        <div class="cv-v4-section-head" style="margin-top:18px;">
          <div>
            <div class="cv-v4-section-title">Workspace Shortcuts</div>
            <div class="cv-v4-section-meta">Detailed information remains available in the page designed for it.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="cv-6b-shortcuts">
          <a class="cv-6b-shortcut" href="?page=Monitoring" target="_self">
            <div class="cv-6b-shortcut-icon green">{_lucide_icon('chart',20)}</div>
            <div><strong>Monitoring</strong><span>{alert_count} active supplier and lifecycle alerts</span></div>
            <div class="cv-6b-arrow">→</div>
          </a>
          <a class="cv-6b-shortcut" href="?page=Reports" target="_self">
            <div class="cv-6b-shortcut-icon">{_lucide_icon('file',20)}</div>
            <div><strong>Reports</strong><span>Saved analyses, PDFs, and engineering exports</span></div>
            <div class="cv-6b-arrow">→</div>
          </a>
          <a class="cv-6b-shortcut" href="?page=Alternative%20Finder" target="_self">
            <div class="cv-6b-shortcut-icon purple">{_lucide_icon('replace',20)}</div>
            <div><strong>Alternative Finder</strong><span>{alternatives_found} saved replacement candidates</span></div>
            <div class="cv-6b-arrow">→</div>
          </a>
          <a class="cv-6b-shortcut" href="?page=Workspace" target="_self">
            <div class="cv-6b-shortcut-icon amber">{_lucide_icon('folder',20)}</div>
            <div><strong>Workspace</strong><span>Usage, plan, and workspace management</span></div>
            <div class="cv-6b-arrow">→</div>
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.stop()

    # ---------- Monitoring ----------
