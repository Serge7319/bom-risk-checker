
"""Cadivor Milestone 10A.2 — Report spacing and button visibility hotfix.

Replace:
    src/ui/milestone10a.py

Keep the existing import and call in streamlit_app.py.
"""

from __future__ import annotations

import streamlit as st


def apply_milestone10a_design_system() -> None:
    st.markdown(
        r"""
<style id="cadivor-milestone-10a2-hotfix">
:root {
  --cv10-border: #E2E8F0;
  --cv10-border-strong: #CBD5E1;
  --cv10-surface: #FFFFFF;
  --cv10-surface-soft: #F8FAFC;
  --cv10-text: #0F172A;
  --cv10-muted: #64748B;
  --cv10-blue: #2563EB;
  --cv10-blue-hover: #1D4ED8;
  --cv10-blue-soft: #EFF6FF;
  --cv10-disabled-bg: #F1F5F9;
  --cv10-disabled-text: #94A3B8;
  --cv10-radius-sm: 12px;
  --cv10-radius-md: 16px;
  --cv10-shadow-sm: 0 8px 24px rgba(15,23,42,.045);
  --cv10-shadow-hover: 0 16px 36px rgba(15,23,42,.075);
}

/* ------------------------------------------------------------
   FRAMEWORK SPACING
   ------------------------------------------------------------ */

[data-testid="stVerticalBlock"] {
  gap: 1rem !important;
}

[data-testid="stHorizontalBlock"] {
  gap: 1rem !important;
  align-items: stretch !important;
}

/* ------------------------------------------------------------
   BUTTONS
   ------------------------------------------------------------ */

/* Standard buttons keep their native Streamlit hierarchy. */
div.stButton > button,
[data-testid="stLinkButton"] a {
  width: auto !important;
  min-height: 0 !important;
  padding: 0.42rem 0.9rem !important;
  border-radius: 0.55rem !important;
  font-size: inherit !important;
  font-weight: 700 !important;
  letter-spacing: normal !important;
  transform: none !important;
}

/* Active download buttons are intentionally blue throughout Cadivor. */
div.stDownloadButton > button:not(:disabled) {
  width: auto !important;
  min-height: 0 !important;
  padding: 0.42rem 0.9rem !important;
  border-radius: 0.55rem !important;
  background: var(--cv10-blue) !important;
  border: 1px solid var(--cv10-blue) !important;
  color: #FFFFFF !important;
  font-weight: 700 !important;
  box-shadow: 0 8px 18px rgba(37,99,235,.16) !important;
  opacity: 1 !important;
}

div.stDownloadButton > button:not(:disabled):hover {
  background: var(--cv10-blue-hover) !important;
  border-color: var(--cv10-blue-hover) !important;
  color: #FFFFFF !important;
  box-shadow: 0 10px 22px rgba(37,99,235,.22) !important;
}

/* Disabled buttons remain clearly disabled but readable. */
div.stButton > button:disabled,
div.stDownloadButton > button:disabled {
  background: var(--cv10-disabled-bg) !important;
  border: 1px solid var(--cv10-border-strong) !important;
  color: var(--cv10-disabled-text) !important;
  opacity: 1 !important;
  box-shadow: none !important;
  cursor: not-allowed !important;
}

/* Preserve primary Streamlit buttons. */
div.stButton > button[kind="primary"]:not(:disabled) {
  background: var(--cv10-blue) !important;
  border-color: var(--cv10-blue) !important;
  color: #FFFFFF !important;
  box-shadow: 0 8px 18px rgba(37,99,235,.16) !important;
}

div.stButton > button[kind="primary"]:not(:disabled):hover {
  background: var(--cv10-blue-hover) !important;
  border-color: var(--cv10-blue-hover) !important;
  color: #FFFFFF !important;
}

/* Secondary actions stay visible on white backgrounds. */
div.stButton > button[kind="secondary"]:not(:disabled),
[data-testid="stLinkButton"] a {
  background: #FFFFFF !important;
  border: 1px solid #94A3B8 !important;
  color: var(--cv10-text) !important;
  box-shadow: none !important;
}

div.stButton > button[kind="secondary"]:not(:disabled):hover,
[data-testid="stLinkButton"] a:hover {
  border-color: var(--cv10-blue) !important;
  color: var(--cv10-blue) !important;
  background: var(--cv10-blue-soft) !important;
}

/* ------------------------------------------------------------
   CARDS
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

/* ------------------------------------------------------------
   REPORT PAGE COMPACTION
   ------------------------------------------------------------ */

/* Compact report library cards without forcing tall rows. */
.cv-report-card,
.cv-report-template {
  box-sizing: border-box !important;
  padding: 15px 16px !important;
  margin: 0 !important;
  min-height: 126px !important;
  height: 100% !important;
}

[data-testid="stHorizontalBlock"]:has(.cv-report-card),
[data-testid="stHorizontalBlock"]:has(.cv-report-template) {
  gap: 12px !important;
  margin-bottom: 0 !important;
}

[data-testid="stHorizontalBlock"]:has(.cv-report-card) > [data-testid="column"],
[data-testid="stHorizontalBlock"]:has(.cv-report-template) > [data-testid="column"] {
  padding: 0 !important;
  min-width: 0 !important;
}

/* Compact known report package and preview wrappers. */
.cv-report-builder,
.cv-report-package,
.cv-report-preview,
.cv-report-downloads,
.cv-report-history,
.cv-report-source-summary {
  margin-top: 0 !important;
  margin-bottom: 0 !important;
}

.cv-report-builder + .cv-report-package,
.cv-report-package + .cv-report-history,
.cv-report-preview + .cv-report-downloads {
  margin-top: 12px !important;
}

/* Rows containing report action/download groups should not create giant gaps. */
[data-testid="stHorizontalBlock"]:has(.cv-report-action),
[data-testid="stHorizontalBlock"]:has(.cv-report-download),
[data-testid="stHorizontalBlock"]:has(.cv-report-output) {
  gap: 12px !important;
  align-items: start !important;
}

.cv-report-action,
.cv-report-download,
.cv-report-output {
  margin: 0 !important;
  padding: 0 !important;
}

/* Reduce unnecessary white space inside report sections. */
.cv-report-section,
.cv-report-preview-panel,
.cv-report-decision-brief,
.cv-report-selected-summary {
  padding: 14px 16px !important;
  margin: 0 !important;
  border-radius: var(--cv10-radius-md) !important;
}

/* ------------------------------------------------------------
   OTHER SAFE POLISH
   ------------------------------------------------------------ */

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

[data-testid="stDataFrame"],
[data-testid="stTable"] {
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-md) !important;
  overflow: hidden !important;
  background: var(--cv10-surface) !important;
}

[data-baseweb="input"] > div,
[data-baseweb="select"] > div,
[data-baseweb="textarea"] > div {
  border-radius: var(--cv10-radius-sm) !important;
}

[data-testid="stExpander"] {
  border: 1px solid var(--cv10-border) !important;
  border-radius: var(--cv10-radius-sm) !important;
  overflow: hidden !important;
}

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
    min-height: 116px !important;
  }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str = "") -> None:
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
    allowed = {"good", "success", "warn", "warning", "bad", "danger", "muted"}
    safe_tone = tone if tone in allowed else "muted"
    return f'<span class="cv-status-pill {safe_tone}">{label}</span>'
