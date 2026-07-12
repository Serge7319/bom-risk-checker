
"""Cadivor Milestone 10A.1 — Safe CSS Hotfix.

This replaces the original Milestone 10A stylesheet, whose selectors were too
broad and unintentionally changed spacing and button sizing across the app.

Keep the existing import and function call in streamlit_app.py:

    from src.ui.milestone10a import apply_milestone10a_design_system
    apply_milestone10a_design_system()

Only replace this file:
    src/ui/milestone10a.py
"""

from __future__ import annotations

import streamlit as st


def apply_milestone10a_design_system() -> None:
    """Apply a narrowly-scoped Cadivor polish layer without changing page layout."""
    st.markdown(
        r"""
<style id="cadivor-milestone-10a1-safe-hotfix">
/* ============================================================
   CADIVOR MILESTONE 10A.1 — SAFE, NARROWLY-SCOPED HOTFIX
   No global Streamlit column, vertical block, or button overrides.
   ============================================================ */

:root {
  --cv10-border: #E2E8F0;
  --cv10-border-strong: #CBD5E1;
  --cv10-surface: #FFFFFF;
  --cv10-surface-soft: #F8FAFC;
  --cv10-text: #0F172A;
  --cv10-muted: #64748B;
  --cv10-blue: #2563EB;
  --cv10-radius-sm: 12px;
  --cv10-radius-md: 16px;
  --cv10-shadow-sm: 0 8px 24px rgba(15,23,42,.045);
  --cv10-shadow-hover: 0 16px 36px rgba(15,23,42,.075);
}

/* ------------------------------------------------------------
   REMOVE SIDE EFFECTS FROM THE ORIGINAL 10A LAYER
   ------------------------------------------------------------ */

/* Restore normal Streamlit spacing. */
[data-testid="stVerticalBlock"] {
  gap: 1rem !important;
}

[data-testid="stHorizontalBlock"] {
  gap: 1rem !important;
  align-items: stretch !important;
}

/* Restore existing app button sizing and hierarchy. */
div.stButton > button,
div.stDownloadButton > button,
[data-testid="stLinkButton"] a {
  width: auto !important;
  min-height: 0 !important;
  padding: 0.25rem 0.75rem !important;
  border-radius: 0.5rem !important;
  font-size: inherit !important;
  font-weight: inherit !important;
  letter-spacing: normal !important;
  transform: none !important;
}

/* Do not force every action into a giant primary blue button. */
div.stButton > button:not([kind="primary"]),
div.stDownloadButton > button:not([kind="primary"]),
[data-testid="stLinkButton"] a {
  background: inherit !important;
  color: inherit !important;
  border-color: inherit !important;
  box-shadow: inherit !important;
}

div.stButton > button:hover,
div.stDownloadButton > button:hover,
[data-testid="stLinkButton"] a:hover {
  transform: none !important;
}

/* Restore framework-controlled card sizing. */
.card,
.kpi-card,
.brc-card,
.cadivor-metric-card,
.cv-report-card,
.cv-report-template,
.cv-analysis-card,
.cv-snapshot-item,
.cv-action-card,
.cv-insight-card {
  min-height: unset !important;
  height: auto !important;
  transform: none !important;
}

/* ------------------------------------------------------------
   SAFE POLISH — ONLY KNOWN CADIVOR CLASSES
   ------------------------------------------------------------ */

.cv-panel,
.cv-analysis-card,
.cv-action-card,
.cv-insight-card,
.cv-report-card,
.cv-report-template {
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-md) !important;
  background: var(--cv10-surface) !important;
  box-shadow: var(--cv10-shadow-sm) !important;
}

.cv-panel:hover,
.cv-action-card:hover,
.cv-insight-card:hover,
.cv-report-card:hover,
.cv-report-template:hover {
  border-color: #BFDBFE !important;
  box-shadow: var(--cv10-shadow-hover) !important;
}

/* KPI cards: visual alignment only, no page-wide grid manipulation. */
.cadivor-metric-card,
.cv-kpi-card,
.cv-report-kpi,
.cv-dashboard-kpi,
.cv-snapshot-item {
  box-sizing: border-box !important;
  min-height: 104px !important;
  height: 100% !important;
  padding: 16px 18px !important;
  margin: 0 !important;
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-md) !important;
  background: var(--cv10-surface) !important;
  box-shadow: var(--cv10-shadow-sm) !important;
}

/* Tighten only rows that actually contain known Cadivor KPI cards. */
[data-testid="stHorizontalBlock"]:has(.cadivor-metric-card),
[data-testid="stHorizontalBlock"]:has(.cv-kpi-card),
[data-testid="stHorizontalBlock"]:has(.cv-report-kpi),
[data-testid="stHorizontalBlock"]:has(.cv-dashboard-kpi) {
  gap: 12px !important;
}

[data-testid="stHorizontalBlock"]:has(.cadivor-metric-card) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.cv-kpi-card) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.cv-report-kpi) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.cv-dashboard-kpi) > [data-testid="column"] {
  padding: 0 !important;
  min-width: 0 !important;
}

/* Reports library: reduce excessive internal whitespace without changing rows. */
.cv-report-card,
.cv-report-template {
  padding: 18px !important;
  margin: 0 !important;
  min-height: 150px !important;
  height: 100% !important;
}

[data-testid="stHorizontalBlock"]:has(.cv-report-card),
[data-testid="stHorizontalBlock"]:has(.cv-report-template) {
  gap: 12px !important;
}

[data-testid="stHorizontalBlock"]:has(.cv-report-card) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.cv-report-template) > [data-testid="column"] {
  padding: 0 !important;
  min-width: 0 !important;
}

/* Known custom badges only. */
.cv-status-pill,
.cadivor-badge,
.cv-badge,
.cv-analysis-pill {
  display: inline-flex !important;
  align-items: center !important;
  gap: 6px !important;
  min-height: 24px !important;
  padding: 4px 9px !important;
  border-radius: 999px !important;
  font-size: 10px !important;
  font-weight: 800 !important;
  line-height: 1 !important;
  white-space: nowrap !important;
}

/* Keep custom empty states polished. */
.cv-empty-state,
.cadivor-empty-state,
.cv-analysis-empty {
  border: 1px dashed var(--cv10-border-strong) !important;
  border-radius: var(--cv10-radius-md) !important;
  background: rgba(255,255,255,.72) !important;
  padding: 24px !important;
  text-align: center !important;
  color: var(--cv10-muted) !important;
}

/* Light table treatment without changing table dimensions. */
[data-testid="stDataFrame"],
[data-testid="stTable"] {
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-md) !important;
  overflow: hidden !important;
  background: var(--cv10-surface) !important;
}

/* Inputs: border polish only. */
[data-baseweb="input"] > div,
[data-baseweb="select"] > div,
[data-baseweb="textarea"] > div {
  border-radius: var(--cv10-radius-sm) !important;
}

/* Expanders: visual polish only; no spacing or height overrides. */
[data-testid="stExpander"] {
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-sm) !important;
  overflow: hidden !important;
}

/* Responsive card heights only. */
@media (max-width: 760px) {
  .cadivor-metric-card,
  .cv-kpi-card,
  .cv-report-kpi,
  .cv-dashboard-kpi,
  .cv-snapshot-item {
    min-height: 92px !important;
  }

  .cv-report-card,
  .cv-report-template {
    min-height: 132px !important;
  }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str = "") -> None:
    """Render a consistent section header."""
    subtitle_html = f'<p class="cv-section-copy">{subtitle}</p>' if subtitle else ""
    st.markdown(
        f"""
        <div class="cv-section-header">
          <h2 class="cv-section-title">{title}</h2>
          {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_badge(label: str, tone: str = "muted") -> str:
    """Return badge HTML for custom Cadivor markup."""
    allowed = {"good", "success", "warn", "warning", "bad", "danger", "muted"}
    safe_tone = tone if tone in allowed else "muted"
    return f'<span class="cv-status-pill {safe_tone}">{label}</span>'
