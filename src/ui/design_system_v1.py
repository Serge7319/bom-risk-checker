"""Cadivor Sprint 33 — Design System 1.0.

A final, non-destructive visual layer loaded after legacy milestone CSS.  It
standardizes typography, surfaces, controls, tables, navigation, badges,
empty states, and responsive behavior without changing application logic.
"""
from __future__ import annotations

from html import escape
from typing import Literal

import streamlit as st

Tone = Literal["info", "success", "warning", "danger", "neutral", "purple"]


def inject_design_system_v1() -> None:
    st.markdown(
        """
<style id="cadivor-design-system-v1">
:root {
  --cv-bg:#F5F7FB;
  --cv-surface:#FFFFFF;
  --cv-surface-soft:#F8FAFC;
  --cv-surface-blue:#F5F9FF;
  --cv-text:#0F172A;
  --cv-text-soft:#334155;
  --cv-muted:#64748B;
  --cv-border:#E2E8F0;
  --cv-border-strong:#CBD5E1;
  --cv-primary:#2563EB;
  --cv-primary-hover:#1D4ED8;
  --cv-success:#059669;
  --cv-warning:#D97706;
  --cv-danger:#DC2626;
  --cv-purple:#7C3AED;
  --cv-radius-control:12px;
  --cv-radius-card:18px;
  --cv-radius-panel:22px;
  --cv-shadow-xs:0 1px 2px rgba(15,23,42,.03);
  --cv-shadow-sm:0 8px 22px rgba(15,23,42,.045);
  --cv-shadow-md:0 16px 38px rgba(15,23,42,.07);
  --cv-shadow-lg:0 26px 64px rgba(15,23,42,.11);
  --cv-ease:cubic-bezier(.2,.8,.2,1);
}

html, body, .stApp, [class*="css"] {
  font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important;
  color:var(--cv-text)!important;
}
.stApp { background:var(--cv-bg)!important; }

/* Typography */
h1,h2,h3,h4,h5,h6 { color:var(--cv-text)!important; letter-spacing:-.035em!important; }
h1 { font-size:clamp(30px,2.2vw,42px)!important; line-height:1.08!important; font-weight:900!important; }
h2 { font-size:clamp(24px,1.65vw,32px)!important; line-height:1.14!important; font-weight:900!important; }
h3 { font-size:20px!important; line-height:1.25!important; font-weight:850!important; }
p,li { color:var(--cv-text-soft); line-height:1.58; }
label,[data-testid="stWidgetLabel"] { color:var(--cv-text-soft)!important; font-weight:750!important; font-size:13px!important; }
.cv-section-title,.cadivor-page-header h1 { font-weight:900!important; letter-spacing:-.035em!important; }
.cv-section-copy,.cadivor-page-header p { color:var(--cv-muted)!important; font-size:14px!important; line-height:1.55!important; }

/* Unified surfaces */
.cv-panel,.cv-metric,.cadivor-metric-card,.cv-action-card,.cv-insight-card,.cv-result-card,
.cv-command-card,.cv-command-hero,.cv-empty-state,.card,.kpi-card,.metric-card,
[data-testid="stMetric"],div[data-testid="stExpander"],div[data-testid="stPlotlyChart"] {
  border:1px solid var(--cv-border)!important;
  border-radius:var(--cv-radius-card)!important;
  background:var(--cv-surface)!important;
  box-shadow:var(--cv-shadow-sm)!important;
  transition:transform .18s var(--cv-ease),box-shadow .18s var(--cv-ease),border-color .18s var(--cv-ease)!important;
}
.cv-panel:hover,.cv-metric:hover,.cadivor-metric-card:hover,.cv-action-card:hover,.cv-insight-card:hover,.cv-result-card:hover {
  transform:translateY(-2px)!important;
  border-color:var(--cv-border-strong)!important;
  box-shadow:var(--cv-shadow-md)!important;
}
.cv-panel,.cv-command-card { padding:22px!important; }

/* KPI language */
.cv-metric,.cadivor-metric-card,[data-testid="stMetric"] { min-height:118px!important; padding:18px 20px!important; }
.cv-metric-label,.cadivor-metric-title,[data-testid="stMetric"] label {
  color:var(--cv-muted)!important; font-size:11px!important; font-weight:900!important;
  text-transform:uppercase!important; letter-spacing:.085em!important;
}
.cv-metric-value,.cadivor-metric-value,[data-testid="stMetricValue"] {
  color:var(--cv-text)!important; font-size:30px!important; line-height:1.1!important;
  font-weight:950!important; letter-spacing:-.045em!important;
}

/* Badges */
.cv-status-pill,.cadivor-badge,.cv-badge,[class*="badge"] {
  display:inline-flex!important; align-items:center!important; gap:6px!important;
  min-height:27px!important; padding:4px 10px!important; border-radius:999px!important;
  font-size:11px!important; line-height:1!important; font-weight:850!important;
  letter-spacing:.005em!important; border:1px solid #BFDBFE!important;
  background:#EFF6FF!important; color:#1D4ED8!important;
}
.cv-status-pill.success,.cv-status-pill.good,.cadivor-badge-success { background:#ECFDF5!important; border-color:#A7F3D0!important; color:#047857!important; }
.cv-status-pill.warning,.cv-status-pill.warn,.cadivor-badge-warning { background:#FFFBEB!important; border-color:#FDE68A!important; color:#B45309!important; }
.cv-status-pill.danger,.cv-status-pill.bad,.cadivor-badge-danger { background:#FEF2F2!important; border-color:#FECACA!important; color:#B91C1C!important; }
.cv-status-pill.muted,.cadivor-badge-muted { background:#F8FAFC!important; border-color:#E2E8F0!important; color:#64748B!important; }
.cv-status-pill.purple { background:#F5F3FF!important; border-color:#DDD6FE!important; color:#6D28D9!important; }

/* Buttons: primary, secondary, ghost, danger via Streamlit kinds/classes */
div.stButton>button,div.stDownloadButton>button,button[kind="primary"] {
  min-height:44px!important; border-radius:var(--cv-radius-control)!important;
  padding:.62rem 1.12rem!important; font-size:13px!important; font-weight:850!important;
  transition:transform .16s var(--cv-ease),box-shadow .16s var(--cv-ease),background .16s var(--cv-ease)!important;
}
div.stButton>button[kind="primary"],button[kind="primary"] {
  background:var(--cv-primary)!important; color:#fff!important; border:1px solid var(--cv-primary)!important;
  box-shadow:0 10px 22px rgba(37,99,235,.20)!important;
}
div.stButton>button[kind="secondary"],div.stDownloadButton>button {
  background:#fff!important; color:var(--cv-text)!important; border:1px solid var(--cv-border-strong)!important;
  box-shadow:var(--cv-shadow-xs)!important;
}
div.stButton>button:hover,div.stDownloadButton>button:hover { transform:translateY(-1px)!important; box-shadow:var(--cv-shadow-md)!important; }
div.stButton>button[kind="primary"]:hover,button[kind="primary"]:hover { background:var(--cv-primary-hover)!important; border-color:var(--cv-primary-hover)!important; }
div.stButton>button:focus-visible,div.stDownloadButton>button:focus-visible { outline:3px solid rgba(37,99,235,.18)!important; outline-offset:2px!important; }

/* Inputs */
input,textarea,[data-baseweb="select"]>div,[data-testid="stDateInput"]>div>div {
  min-height:42px!important; border:1px solid var(--cv-border-strong)!important;
  border-radius:var(--cv-radius-control)!important; background:#fff!important;
  color:var(--cv-text)!important; box-shadow:var(--cv-shadow-xs)!important;
}
textarea { min-height:104px!important; padding:12px 14px!important; }
input:focus,textarea:focus,[data-baseweb="select"]>div:focus-within {
  border-color:var(--cv-primary)!important; box-shadow:0 0 0 3px rgba(37,99,235,.12)!important;
}

/* Tables */
[data-testid="stDataFrame"],div[data-testid="stTable"] {
  border:1px solid var(--cv-border)!important; border-radius:16px!important;
  overflow:hidden!important; background:#fff!important; box-shadow:var(--cv-shadow-sm)!important;
}
[data-testid="stDataFrame"] [role="columnheader"] {
  min-height:44px!important; background:#F8FAFC!important; color:#475569!important;
  font-size:11px!important; font-weight:900!important; text-transform:uppercase!important;
  letter-spacing:.055em!important; border-bottom:1px solid var(--cv-border)!important;
}
[data-testid="stDataFrame"] [role="gridcell"] {
  min-height:42px!important; background:#fff!important; color:var(--cv-text-soft)!important;
  border-bottom:1px solid #EEF2F7!important;
}
[data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] { background:#F8FAFC!important; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
  gap:4px!important; padding:4px!important; border:1px solid var(--cv-border)!important;
  border-radius:14px!important; background:#fff!important; box-shadow:var(--cv-shadow-xs)!important;
}
.stTabs [data-baseweb="tab"] { min-height:38px!important; padding:7px 13px!important; border-radius:10px!important; color:var(--cv-muted)!important; font-weight:800!important; }
.stTabs [aria-selected="true"] { background:#EFF6FF!important; color:var(--cv-primary)!important; }

/* Expanders */
div[data-testid="stExpander"] { overflow:hidden!important; }
div[data-testid="stExpander"] details summary { min-height:46px!important; padding:0 14px!important; color:var(--cv-text)!important; font-weight:800!important; }
div[data-testid="stExpander"] details[open] summary { background:#F8FAFC!important; border-bottom:1px solid var(--cv-border)!important; }

/* Alerts and empty states */
[data-testid="stAlert"] { border-radius:14px!important; border-width:1px!important; box-shadow:var(--cv-shadow-xs)!important; }
.cv-empty-state { padding:38px 28px!important; }
.cv-empty-icon { width:48px!important; height:48px!important; border-radius:14px!important; }
.cv-empty-title { font-size:19px!important; font-weight:900!important; }

/* Navigation */
.cv-side-link {
  min-height:42px!important; padding:0 12px!important; border-radius:11px!important;
  color:#475569!important; font-size:13px!important; font-weight:780!important;
  transition:background .16s var(--cv-ease),color .16s var(--cv-ease),transform .16s var(--cv-ease)!important;
}
.cv-side-link>span { width:20px!important; color:#64748B!important; font-size:14px!important; }
.cv-side-link:hover { background:#F1F5F9!important; color:var(--cv-text)!important; transform:translateX(2px)!important; }
.cv-side-link.active { background:#EFF6FF!important; color:var(--cv-primary)!important; box-shadow:inset 0 0 0 1px #BFDBFE!important; }
.cv-side-link.active>span { color:var(--cv-primary)!important; }
.cadivor-search-pill { min-height:38px!important; border-radius:999px!important; border:1px solid var(--cv-border)!important; background:#F8FAFC!important; }

/* Page rhythm */
.cv-section-header,.cadivor-page-header { margin:0 0 18px!important; }
.cv-section-header+.cv-panel,.cadivor-page-header+.cv-panel { margin-top:0!important; }
div[data-testid="stHorizontalBlock"] { gap:16px!important; }
hr { border:0!important; border-top:1px solid var(--cv-border)!important; margin:24px 0!important; }

/* Focus and motion */
a:focus-visible,button:focus-visible,input:focus-visible,textarea:focus-visible { outline:3px solid rgba(37,99,235,.18)!important; outline-offset:2px!important; }
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { animation-duration:.01ms!important; animation-iteration-count:1!important; transition-duration:.01ms!important; scroll-behavior:auto!important; } }

/* Responsive */
@media(max-width:1200px) {
  .cv-metric-value,.cadivor-metric-value,[data-testid="stMetricValue"] { font-size:26px!important; }
  .cv-panel,.cv-command-card { padding:18px!important; }
}
@media(max-width:900px) {
  h1 { font-size:30px!important; }
  h2 { font-size:24px!important; }
  .cv-metric,.cadivor-metric-card,[data-testid="stMetric"] { min-height:100px!important; }
  .stTabs [data-baseweb="tab-list"] { overflow-x:auto!important; flex-wrap:nowrap!important; }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def badge_html(label: str, tone: Tone = "neutral") -> str:
    css_tone = "muted" if tone == "neutral" else tone
    return f'<span class="cv-status-pill {css_tone}">{escape(str(label))}</span>'


def section_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    eyebrow_html = f'<div class="cv-eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    subtitle_html = f'<p class="cv-section-copy">{escape(subtitle)}</p>' if subtitle else ""
    st.markdown(
        f'<div class="cv-section-header">{eyebrow_html}<h2 class="cv-section-title">{escape(title)}</h2>{subtitle_html}</div>',
        unsafe_allow_html=True,
    )


def empty_state(title: str, body: str, icon: str = "◇") -> None:
    st.markdown(
        f'<div class="cv-empty-state"><div class="cv-empty-icon">{escape(icon)}</div><div class="cv-empty-title">{escape(title)}</div><div class="cv-empty-body">{escape(body)}</div></div>',
        unsafe_allow_html=True,
    )
