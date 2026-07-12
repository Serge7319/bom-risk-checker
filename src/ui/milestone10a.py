
"""Cadivor Milestone 10A — Professional Design System & UX Polish.

This module is intentionally additive. It standardizes spacing, cards, buttons,
tabs, tables, badges, inputs, expanders, responsive behavior, and empty states
without replacing existing page logic.

Install:
    from src.ui.milestone10a import apply_milestone10a_design_system
    apply_milestone10a_design_system()

Call it once after the existing Cadivor shell/design CSS is injected.
"""

from __future__ import annotations

import streamlit as st


def apply_milestone10a_design_system() -> None:
    """Apply Cadivor's Milestone 10A global visual standards."""
    st.markdown(
        r"""
<style id="cadivor-milestone-10a-design-system">
/* ============================================================
   CADIVOR MILESTONE 10A — PROFESSIONAL DESIGN SYSTEM
   Additive override layer. Existing feature logic is unchanged.
   ============================================================ */

:root {
  --cv10-bg: #F6F8FB;
  --cv10-surface: #FFFFFF;
  --cv10-surface-soft: #F8FAFC;
  --cv10-surface-blue: #F4F8FF;
  --cv10-text: #0F172A;
  --cv10-text-secondary: #334155;
  --cv10-muted: #64748B;
  --cv10-subtle: #94A3B8;
  --cv10-border: #E2E8F0;
  --cv10-border-strong: #CBD5E1;
  --cv10-blue: #2563EB;
  --cv10-blue-dark: #1D4ED8;
  --cv10-green: #16A34A;
  --cv10-amber: #D97706;
  --cv10-red: #DC2626;

  --cv10-radius-xs: 9px;
  --cv10-radius-sm: 12px;
  --cv10-radius-md: 16px;
  --cv10-radius-lg: 20px;
  --cv10-radius-xl: 24px;

  --cv10-space-1: 4px;
  --cv10-space-2: 8px;
  --cv10-space-3: 12px;
  --cv10-space-4: 16px;
  --cv10-space-5: 20px;
  --cv10-space-6: 24px;
  --cv10-space-7: 32px;
  --cv10-space-8: 40px;

  --cv10-shadow-xs: 0 1px 2px rgba(15,23,42,.04);
  --cv10-shadow-sm: 0 8px 24px rgba(15,23,42,.045);
  --cv10-shadow-md: 0 16px 40px rgba(15,23,42,.065);
  --cv10-shadow-hover: 0 20px 44px rgba(15,23,42,.09);
}

/* ---------- Global rhythm ---------- */
html, body, .stApp, [data-testid="stAppViewContainer"] {
  background: var(--cv10-bg) !important;
  color: var(--cv10-text) !important;
}

[data-testid="stMainBlockContainer"] > div,
.main .block-container > div {
  gap: 0 !important;
}

[data-testid="stVerticalBlock"] {
  gap: var(--cv10-space-4) !important;
}

[data-testid="stHorizontalBlock"] {
  gap: 12px !important;
  align-items: stretch !important;
}

.element-container {
  margin-bottom: 0 !important;
}

hr {
  margin: var(--cv10-space-7) 0 !important;
  border-color: var(--cv10-border) !important;
}

/* ---------- Typography ---------- */
h1, h2, h3, h4, h5, h6 {
  color: var(--cv10-text) !important;
  letter-spacing: -.035em !important;
  font-weight: 900 !important;
}

h1 { line-height: 1.02 !important; }
h2 { line-height: 1.08 !important; }
h3 { line-height: 1.15 !important; }

p, label, .stCaptionContainer, [data-testid="stMarkdownContainer"] li {
  color: var(--cv10-text-secondary);
}

small, .cv-panel-copy, .cadivor-page-header p, .cv-subtitle {
  color: var(--cv10-muted) !important;
}

/* ---------- Standard surfaces ---------- */
.cv-panel,
.card,
.kpi-card,
.brc-card,
.cadivor-metric-card,
.cv-report-card,
.cv-report-template,
.cv-analysis-card,
.cv-snapshot-item,
.cv-action-card,
.cv-insight-card,
[data-testid="stForm"],
[data-testid="stExpander"] {
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-md) !important;
  background: var(--cv10-surface) !important;
  box-shadow: var(--cv10-shadow-sm) !important;
  box-sizing: border-box !important;
}

.cv-panel,
.card,
.brc-card,
.cv-analysis-card,
.cv-action-card,
.cv-insight-card {
  padding: var(--cv10-space-5) !important;
}

.cv-panel:hover,
.card:hover,
.cv-report-card:hover,
.cv-report-template:hover,
.cv-action-card:hover {
  border-color: #BFDBFE !important;
  box-shadow: var(--cv10-shadow-hover) !important;
  transform: translateY(-1px);
}

.cv-panel,
.card,
.cv-report-card,
.cv-report-template,
.cv-action-card {
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease;
}

/* ---------- KPI grids: fixes excessive spacing ---------- */
/* Existing HTML grids */
.cv-kpi-grid,
.cv-dashboard-kpis,
.cv-report-kpis,
.cv-metric-grid,
.cv-snapshot-grid,
.cv-portfolio-kpis,
.cv-dashboard-stats,
.cv-analysis-summary {
  display: grid !important;
  grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
  gap: 12px !important;
  align-items: stretch !important;
  width: 100% !important;
}

/* Streamlit column rows frequently used for KPI cards */
[data-testid="stHorizontalBlock"]:has(.cadivor-metric-card),
[data-testid="stHorizontalBlock"]:has(.kpi-card),
[data-testid="stHorizontalBlock"]:has(.cv-kpi-card),
[data-testid="stHorizontalBlock"]:has(.cv-report-kpi),
[data-testid="stHorizontalBlock"]:has(.cv-dashboard-kpi) {
  gap: 12px !important;
}

[data-testid="stHorizontalBlock"]:has(.cadivor-metric-card) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.kpi-card) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.cv-kpi-card) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.cv-report-kpi) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.cv-dashboard-kpi) > [data-testid="column"] {
  padding: 0 !important;
  min-width: 0 !important;
}

/* Card dimensions */
.cadivor-metric-card,
.kpi-card,
.cv-kpi-card,
.cv-report-kpi,
.cv-dashboard-kpi,
.cv-snapshot-item {
  height: 100% !important;
  min-height: 112px !important;
  padding: 18px 20px !important;
  display: flex !important;
  flex-direction: column !important;
  justify-content: center !important;
  margin: 0 !important;
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-md) !important;
  background: var(--cv10-surface) !important;
  box-shadow: var(--cv10-shadow-sm) !important;
}

.cadivor-metric-title,
.cv-kpi-label,
.cv-report-kpi span,
.cv-dashboard-kpi span,
.cv-snapshot-item span {
  color: var(--cv10-muted) !important;
  font-size: 10px !important;
  font-weight: 900 !important;
  letter-spacing: .09em !important;
  text-transform: uppercase !important;
  margin-bottom: 7px !important;
}

.cadivor-metric-value,
.cv-kpi-value,
.cv-report-kpi strong,
.cv-dashboard-kpi strong,
.cv-snapshot-item strong {
  color: var(--cv10-text) !important;
  font-size: 25px !important;
  font-weight: 950 !important;
  line-height: 1 !important;
}

/* ---------- Reports page cards ---------- */
.cv-report-library,
.cv-report-template-grid,
.cv-report-card-grid {
  display: grid !important;
  grid-template-columns: repeat(6, minmax(0, 1fr)) !important;
  gap: 12px !important;
}

.cv-report-library > *,
.cv-report-template-grid > *,
.cv-report-card-grid > * {
  grid-column: span 2 !important;
}

.cv-report-library > *:nth-child(n+4),
.cv-report-template-grid > *:nth-child(n+4),
.cv-report-card-grid > *:nth-child(n+4) {
  grid-column: span 3 !important;
}

.cv-report-card,
.cv-report-template {
  min-height: 168px !important;
  padding: 18px !important;
  display: flex !important;
  flex-direction: column !important;
  justify-content: space-between !important;
  margin: 0 !important;
}

/* Broad fallback for the five report-library cards rendered through columns. */
[data-testid="stHorizontalBlock"]:has(.cv-report-card),
[data-testid="stHorizontalBlock"]:has(.cv-report-template) {
  gap: 12px !important;
}

[data-testid="stHorizontalBlock"]:has(.cv-report-card) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.cv-report-template) > [data-testid="column"] {
  padding: 0 !important;
}

/* ---------- Buttons ---------- */
div.stButton > button,
div.stDownloadButton > button,
[data-testid="stLinkButton"] a {
  min-height: 42px !important;
  border-radius: var(--cv10-radius-sm) !important;
  padding: 0 18px !important;
  font-size: 13px !important;
  font-weight: 850 !important;
  letter-spacing: -.01em !important;
  border: 1px solid var(--cv10-blue) !important;
  background: var(--cv10-blue) !important;
  color: #FFFFFF !important;
  box-shadow: 0 9px 20px rgba(37,99,235,.16) !important;
  transition: transform .14s ease, box-shadow .14s ease, background .14s ease !important;
}

div.stButton > button:hover,
div.stDownloadButton > button:hover,
[data-testid="stLinkButton"] a:hover {
  background: var(--cv10-blue-dark) !important;
  border-color: var(--cv10-blue-dark) !important;
  color: #FFFFFF !important;
  box-shadow: 0 13px 25px rgba(37,99,235,.22) !important;
  transform: translateY(-1px);
}

div.stButton > button:active,
div.stDownloadButton > button:active {
  transform: translateY(0);
}

div.stButton > button:disabled,
div.stDownloadButton > button:disabled {
  background: #E2E8F0 !important;
  border-color: #E2E8F0 !important;
  color: #94A3B8 !important;
  box-shadow: none !important;
}

/* Secondary and danger helpers for custom HTML. */
.cv-btn-secondary {
  background: #FFFFFF !important;
  color: var(--cv10-blue) !important;
  border: 1px solid #BFDBFE !important;
  box-shadow: none !important;
}
.cv-btn-danger {
  background: var(--cv10-red) !important;
  border-color: var(--cv10-red) !important;
  color: #FFFFFF !important;
}

/* ---------- Inputs ---------- */
[data-baseweb="input"] > div,
[data-baseweb="select"] > div,
[data-baseweb="textarea"] > div,
[data-testid="stFileUploaderDropzone"] {
  border-radius: var(--cv10-radius-sm) !important;
  border-color: var(--cv10-border-strong) !important;
  background: #FFFFFF !important;
  box-shadow: var(--cv10-shadow-xs) !important;
}

[data-baseweb="input"] > div:focus-within,
[data-baseweb="select"] > div:focus-within,
[data-baseweb="textarea"] > div:focus-within {
  border-color: #60A5FA !important;
  box-shadow: 0 0 0 3px rgba(37,99,235,.10) !important;
}

/* ---------- Tabs ---------- */
[data-baseweb="tab-list"] {
  gap: 4px !important;
  border-bottom: 1px solid var(--cv10-border) !important;
}

[data-baseweb="tab"] {
  min-height: 42px !important;
  padding: 10px 12px !important;
  color: var(--cv10-muted) !important;
  font-size: 13px !important;
  font-weight: 800 !important;
}

[aria-selected="true"][data-baseweb="tab"] {
  color: var(--cv10-blue) !important;
}

/* ---------- Expanders ---------- */
[data-testid="stExpander"] {
  overflow: hidden !important;
  box-shadow: none !important;
}

[data-testid="stExpander"] details > summary {
  min-height: 48px !important;
  padding: 0 16px !important;
  font-size: 13px !important;
  font-weight: 850 !important;
}

[data-testid="stExpander"] details[open] > summary {
  border-bottom: 1px solid var(--cv10-border) !important;
}

/* ---------- Tables and dataframes ---------- */
[data-testid="stDataFrame"],
[data-testid="stTable"] {
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-md) !important;
  overflow: hidden !important;
  background: #FFFFFF !important;
  box-shadow: var(--cv10-shadow-sm) !important;
}

/* Streamlit data editor / dataframe toolbar */
[data-testid="stDataFrame"] [role="columnheader"] {
  background: #F8FAFC !important;
  color: var(--cv10-muted) !important;
  font-weight: 850 !important;
}

/* HTML tables */
[data-testid="stMarkdownContainer"] table {
  width: 100% !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
  overflow: hidden !important;
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-md) !important;
  background: #FFFFFF !important;
}

[data-testid="stMarkdownContainer"] th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #F8FAFC !important;
  color: var(--cv10-muted) !important;
  font-size: 11px !important;
  font-weight: 900 !important;
  letter-spacing: .02em;
}

[data-testid="stMarkdownContainer"] th,
[data-testid="stMarkdownContainer"] td {
  padding: 11px 12px !important;
  border-bottom: 1px solid #EEF2F7 !important;
}

[data-testid="stMarkdownContainer"] tbody tr:hover td {
  background: #F8FBFF !important;
}

/* ---------- Alerts ---------- */
[data-testid="stAlert"] {
  border-radius: var(--cv10-radius-md) !important;
  border-width: 1px !important;
  box-shadow: none !important;
}

/* ---------- Badges / status pills ---------- */
.cv-status-pill,
.cadivor-badge,
.cv-badge,
.cv-analysis-pill {
  display: inline-flex !important;
  align-items: center !important;
  gap: 6px !important;
  min-height: 26px !important;
  padding: 4px 9px !important;
  border-radius: 999px !important;
  font-size: 10px !important;
  font-weight: 900 !important;
  line-height: 1 !important;
  white-space: nowrap !important;
}

.cv-status-pill.good,
.cv-status-pill.success,
.cv-badge.good,
.cadivor-badge-success {
  color: #047857 !important;
  background: #ECFDF5 !important;
  border: 1px solid #A7F3D0 !important;
}
.cv-status-pill.warn,
.cv-status-pill.warning,
.cv-badge.warn,
.cadivor-badge-warning {
  color: #B45309 !important;
  background: #FFFBEB !important;
  border: 1px solid #FDE68A !important;
}
.cv-status-pill.bad,
.cv-status-pill.danger,
.cv-badge.bad,
.cadivor-badge-danger {
  color: #B91C1C !important;
  background: #FEF2F2 !important;
  border: 1px solid #FECACA !important;
}
.cv-status-pill.muted,
.cv-badge.muted {
  color: #475569 !important;
  background: #F8FAFC !important;
  border: 1px solid #CBD5E1 !important;
}

/* ---------- Empty states ---------- */
.cv-empty-state,
.cadivor-empty-state,
.cv-analysis-empty {
  border: 1px dashed #CBD5E1 !important;
  border-radius: var(--cv10-radius-md) !important;
  background: rgba(255,255,255,.72) !important;
  padding: 30px 24px !important;
  text-align: center !important;
  color: var(--cv10-muted) !important;
}

/* ---------- Section spacing ---------- */
.cv-section,
.cv-page-section,
.cv-report-section,
.cv-dashboard-section {
  margin-top: var(--cv10-space-7) !important;
}

.cv-panel-title,
.cv-section-title {
  margin-top: 0 !important;
  margin-bottom: 6px !important;
}

.cv-panel-copy,
.cv-section-copy {
  margin-top: 0 !important;
  margin-bottom: 14px !important;
}

/* Avoid giant blank gaps created by nested markdown wrappers. */
[data-testid="stMarkdownContainer"] > :first-child {
  margin-top: 0 !important;
}
[data-testid="stMarkdownContainer"] > :last-child {
  margin-bottom: 0 !important;
}

/* ---------- Responsive ---------- */
@media (max-width: 1280px) {
  .cv-kpi-grid,
  .cv-dashboard-kpis,
  .cv-report-kpis,
  .cv-metric-grid,
  .cv-snapshot-grid,
  .cv-portfolio-kpis,
  .cv-dashboard-stats,
  .cv-analysis-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
  }

  .cv-report-library,
  .cv-report-template-grid,
  .cv-report-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
  }

  .cv-report-library > *,
  .cv-report-template-grid > *,
  .cv-report-card-grid > *,
  .cv-report-library > *:nth-child(n+4),
  .cv-report-template-grid > *:nth-child(n+4),
  .cv-report-card-grid > *:nth-child(n+4) {
    grid-column: span 1 !important;
  }
}

@media (max-width: 760px) {
  [data-testid="stHorizontalBlock"] {
    gap: 10px !important;
  }

  .cv-kpi-grid,
  .cv-dashboard-kpis,
  .cv-report-kpis,
  .cv-metric-grid,
  .cv-snapshot-grid,
  .cv-portfolio-kpis,
  .cv-dashboard-stats,
  .cv-analysis-summary,
  .cv-report-library,
  .cv-report-template-grid,
  .cv-report-card-grid {
    grid-template-columns: 1fr !important;
  }

  .cadivor-metric-card,
  .kpi-card,
  .cv-kpi-card,
  .cv-report-kpi,
  .cv-dashboard-kpi,
  .cv-snapshot-item {
    min-height: 96px !important;
  }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str = "") -> None:
    """Render a consistent Milestone 10A section header."""
    safe_title = str(title or "")
    safe_subtitle = str(subtitle or "")
    st.markdown(
        f"""
        <div class="cv-section-header">
          <h2 class="cv-section-title">{safe_title}</h2>
          {f'<p class="cv-section-copy">{safe_subtitle}</p>' if safe_subtitle else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_badge(label: str, tone: str = "muted") -> str:
    """Return reusable badge HTML for custom page markup."""
    tone = tone if tone in {"good", "success", "warn", "warning", "bad", "danger", "muted"} else "muted"
    return f'<span class="cv-status-pill {tone}">{label}</span>'
