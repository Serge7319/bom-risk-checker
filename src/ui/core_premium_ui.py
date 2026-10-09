"""Cadivor Core Application — Premium UI stabilization layer.

Stage 1 foundation: semantic tokens, buttons, links, tables, KPIs, badges,
page shell, tabs, forms, and auth-shell polish. Loaded last so scoped rules
win without altering application logic.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Literal, Mapping, Sequence

import streamlit as st

BadgeTone = Literal[
    "neutral",
    "success",
    "warning",
    "danger",
    "info",
    "approved",
    "active",
    "blocked",
    "high",
    "medium",
    "low",
    "monitoring",
    "qualified",
    "available",
    "pending",
    "draft",
    "eol",
    "nrnd",
    "recommended",
]

_BADGE_CLASS = {
    "neutral": "cvds-badge-neutral",
    "success": "cvds-badge-success",
    "warning": "cvds-badge-warning",
    "danger": "cvds-badge-danger",
    "info": "cvds-badge-info",
    "approved": "cv-badge-approved",
    "active": "cv-badge-active",
    "blocked": "cv-badge-blocked",
    "high": "cv-badge-high",
    "medium": "cv-badge-medium",
    "low": "cv-badge-slate",
    "monitoring": "cv-badge-monitoring",
    "qualified": "cv-badge-qualified",
    "available": "cv-badge-available",
    "pending": "cv-badge-pending",
    "draft": "cv-badge-draft",
    "eol": "cv-badge-eol",
    "nrnd": "cv-badge-nrnd",
    "recommended": "cv-badge-recommended",
}


def _load_css(filename: str = "core_premium_ui.css") -> str:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def inject_core_premium_ui() -> None:
    """Inject the final authenticated-workspace premium UI layer."""
    css = _load_css()
    if css:
        st.markdown(
            f"<style id='cadivor-core-premium-ui'>{css}</style>",
            unsafe_allow_html=True,
        )


def inject_core_premium_ui_auth() -> None:
    """Auth routes use the dedicated auth stylesheet only."""
    return


def stop_authenticated_page() -> None:
    """Inject late CSS polish on authenticated pages, then halt the script."""
    if st.session_state.get("_cadivor_authenticated_surface_ready"):
        inject_workspace_geometry_final()
    st.stop()


def inject_navigation_recovery_css() -> None:
    """Restore foundation navigation after late global button/KPI styles."""
    css = _load_css("navigation_recovery.css")
    if css.strip():
        st.markdown(
            f"<style id='cadivor-navigation-recovery'>{css}</style>",
            unsafe_allow_html=True,
        )


def inject_workspace_geometry_final() -> None:
    """Final authenticated-workspace geometry and premium polish authority.

    Must run after page-level CSS so large displays use the full workspace
    width, shell chrome does not reserve vertical space in the main column,
    and late component polish wins over page-inline styles.
    """
    from src.ui.cadivor_design_system import inject_cadivor_design_system

    css_chunks = [
        _load_css("core_premium_ui_final.css"),
        _load_css("laptop_kpi_table_pass.css"),
        _load_css("executive_ux.css"),
        _load_css("premium_recovery.css"),
    ]
    combined = "\n".join(chunk for chunk in css_chunks if chunk.strip())
    if combined.strip():
        st.markdown(
            f"<style id='cadivor-core-premium-ui-final'>{combined}</style>",
            unsafe_allow_html=True,
        )
    inject_cadivor_design_system()
    inject_navigation_recovery_css()
    from src.ui.sprint71_polish import inject_sprint71_polish

    inject_sprint71_polish()
    # Re-assert compact inset + flex-gap chrome collapse after late polish CSS.
    st.markdown(
        """
        <style id="cadivor-compact-content-inset">
        section[data-testid="stMain"] [data-testid="stMainBlockContainer"],
        section[data-testid="stMain"] .main .block-container {
          padding-top: calc(var(--cv-foundation-top, 64px) + 24px) !important;
          padding-bottom: calc(84px + env(safe-area-inset-bottom, 0px)) !important;
        }
        @media (max-width: 1080px) {
          section[data-testid="stMain"] [data-testid="stMainBlockContainer"],
          section[data-testid="stMain"] .main .block-container {
            padding-bottom: calc(64px + env(safe-area-inset-bottom, 0px)) !important;
          }
        }
        @media (max-width: 768px) {
          section[data-testid="stMain"] [data-testid="stMainBlockContainer"],
          section[data-testid="stMain"] .main .block-container {
            padding-top: calc(var(--cv-foundation-top, 64px) + 16px + env(safe-area-inset-top, 0px)) !important;
          }
        }
        @media (max-width: 640px) {
          section[data-testid="stMain"] [data-testid="stMainBlockContainer"],
          section[data-testid="stMain"] .main .block-container {
            padding-bottom: calc(56px + env(safe-area-inset-bottom, 0px)) !important;
          }
        }
        /* Root flex siblings only — removes Streamlit row-gap above route content. */
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-cv_foundation_navigation"]),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-cv_foundation_profile_trigger"]),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-cv_foundation_profile_panel"]),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-cadivor_main_transition_owner"]),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has([data-cadivor-topbar-flow-host="1"]),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(.cv-foundation-topbar),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has([data-cadivor-route-root="1"]):not(:has(.cv-page)):not(:has(.cv-page-header)):not(:has(.cv64-section)):not(:has(h1)),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has([data-cadivor-page-content="1"]):not(:has(.cv-page)):not(:has(.cv-page-header)):not(:has(.cv64-section)):not(:has(h1)),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has([data-cadivor-page-body]):not(:has(.cv-page)):not(:has(.cv-page-header)):not(:has(.cv64-section)):not(:has(h1)),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(.cv64-page-shell):not(:has(.cv64-section)):not(:has(.cv-customer-hero)):not(:has(.cv-page-header)):not(:has(h1)):not(:has([class*="st-key-af62_hero"])),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(> [data-testid="stIFrame"]),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(style#cadivor-core-premium-ui-final),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(style#cadivor-saved-bom-nav),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(style#cadivor-compact-content-inset),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(style#cadivor-main-transition-css),
        section[data-testid="stMain"] [data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has([data-cadivor-transition-style-host]) {
          position: absolute !important;
          left: 0 !important;
          top: 0 !important;
          width: 0 !important;
          height: 0 !important;
          min-height: 0 !important;
          max-height: 0 !important;
          margin: 0 !important;
          padding: 0 !important;
          border: 0 !important;
          overflow: visible !important;
          flex: 0 0 auto !important;
          pointer-events: none !important;
        }
        section[data-testid="stMain"] [class*="st-key-cv_foundation_navigation"],
        section[data-testid="stMain"] [class*="st-key-cv_foundation_navigation"] *,
        section[data-testid="stMain"] [class*="st-key-cv_foundation_profile_trigger"],
        section[data-testid="stMain"] [class*="st-key-cv_foundation_profile_trigger"] *,
        section[data-testid="stMain"] [class*="st-key-cv_foundation_profile_panel"],
        section[data-testid="stMain"] [class*="st-key-cv_foundation_profile_panel"] *,
        section[data-testid="stMain"] .cv-foundation-topbar,
        section[data-testid="stMain"] .cv-foundation-topbar * {
          pointer-events: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    from src.ui.bom_navigation import inject_saved_bom_nav_css

    inject_saved_bom_nav_css()
    visual_refresh_css = _load_css("dashboard_visual_refresh.css")
    if visual_refresh_css.strip():
        st.markdown(
            f"<style id='cadivor-dashboard-visual-refresh'>{visual_refresh_css}</style>",
            unsafe_allow_html=True,
        )
    _inject_approved_visual_overrides()


def _inject_approved_visual_overrides() -> None:
    """Win over the late pill-button rules for the approved mockup chrome."""
    tab = str(st.session_state.get("cadivor_ei_report_tab") or "BOM Risk")
    active_slug = tab.casefold().replace(" ", "-").replace("&", "and")
    beat = (
        ":not(.st-key-cv_foundation_navigation .stButton)"
        ":not(.st-key-cv_analysis_section_nav .stButton)"
        ":not(.st-key-cv_analysis_section_nav *)"
        ":not([class*='st-key-cadivor_bom_tab_'])"
        ":not(.st-key-cv_saved_bom_nav_more .stButton)"
        "> button:not([kind='primary']):not(:disabled)"
    )
    st.markdown(
        f"""
        <style id="cadivor-approved-visual-overrides">
        html body section[data-testid="stMain"] .st-key-cv_foundation_top_navigation .stButton{beat},
        html body section[data-testid="stMain"] .st-key-cv_foundation_top_navigation .stButton{beat} *,
        html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs .stButton{beat},
        html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs .stButton{beat} * {{
          background:transparent !important;background-color:transparent !important;
          border:0 !important;border-width:0 !important;border-style:none !important;
          border-radius:0 !important;box-shadow:none !important;
          min-width:0 !important;min-height:0 !important;width:auto !important;height:auto !important;
          padding:8px 10px 10px !important;color:#334155 !important;font-weight:650 !important
        }}
        html body section[data-testid="stMain"] .st-key-cv_foundation_top_navigation .st-key-cv_foundation_nav_ei .stButton{beat} {{
          color:#1d4ed8 !important;background:transparent !important;background-color:transparent !important;
          border:0 !important;border-bottom:2px solid #2563eb !important;border-radius:0 !important;box-shadow:none !important
        }}
        html body section[data-testid="stMain"] .st-key-cv_foundation_top_navigation .st-key-cv_foundation_nav_ei .stButton{beat} * {{
          color:#1d4ed8 !important;background:transparent !important;border:0 !important;box-shadow:none !important
        }}
        html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs [class*="st-key-ei_tab_{active_slug}"] .stButton{beat} {{
          color:#1d4ed8 !important;background:transparent !important;background-color:transparent !important;
          border:0 !important;border-bottom:2px solid #2563eb !important;border-radius:0 !important;box-shadow:none !important
        }}
        html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs [class*="st-key-ei_tab_{active_slug}"] .stButton{beat} * {{
          color:#1d4ed8 !important;background:transparent !important;border:0 !important;box-shadow:none !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-approved_home_menu_"] button,
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_menu_"] button,
        html body section[data-testid="stMain"] [class*="st-key-approved_report_menu_"] button,
        html body section[data-testid="stMain"] [class*="st-key-approved_decision_menu_"] button {{
          min-width:28px !important;width:28px !important;max-width:28px !important;
          min-height:28px !important;height:28px !important;padding:0 !important;
          border:0 !important;border-width:0 !important;border-style:none !important;
          border-radius:6px !important;background:transparent !important;background-color:transparent !important;
          box-shadow:none !important;color:#64748b !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-approved_decision_review_"] .stButton:not(.st-key-cv_foundation_navigation .stButton):not(.st-key-cv_analysis_section_nav .stButton):not(.st-key-cv_analysis_section_nav *):not([class*="st-key-cadivor_bom_tab_"]):not(.st-key-cv_saved_bom_nav_more .stButton) > button[kind="primary"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_row_open_"] .stButton:not(.st-key-cv_foundation_navigation .stButton):not(.st-key-cv_analysis_section_nav .stButton):not(.st-key-cv_analysis_section_nav *):not([class*="st-key-cadivor_bom_tab_"]):not(.st-key-cv_saved_bom_nav_more .stButton) > button[kind="primary"] {{
          min-width:0 !important;width:auto !important;min-height:32px !important;height:32px !important;
          padding:0 12px !important;border-radius:8px !important;font-size:13px !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-cv_risk_open_"] {{
          background:#f8fafc !important;border-left:3px solid #2563eb !important;border-radius:12px !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-cv_risk_expand_"] .stButton > button {{
          min-width:0 !important;width:auto !important;min-height:36px !important;height:auto !important;
          padding:6px 10px !important;border-radius:8px !important;font-size:13px !important;
          justify-content:flex-start !important;text-align:left !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_title"] [data-testid="stHorizontalBlock"] {{
          align-items:center !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_title"] [data-testid="stColumn"]:last-child {{
          display:flex !important;justify-content:flex-end !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_file_"] .stButton{beat},
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_file_"] .stButton{beat} * {{
          background:transparent !important;background-color:transparent !important;
          border:0 !important;border-width:0 !important;border-style:none !important;
          border-radius:0 !important;box-shadow:none !important;
          min-width:0 !important;min-height:0 !important;width:auto !important;height:auto !important;
          padding:0 !important;color:#2563eb !important;font-weight:650 !important;text-align:left !important
        }}
        /* The rail is position:fixed, so every authenticated page must reserve the
           same width. This beats earlier rules that reset the main column to the
           viewport edge while the rail stays on top of it. */
        @media (min-width: 701px) {{
          html body:has(.st-key-cv_foundation_navigation) {{
            --cv-foundation-rail: 296px;
          }}
          html body:has(.st-key-cv_foundation_navigation) .st-key-cv_foundation_navigation {{
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            bottom: 0 !important;
            width: var(--cv-foundation-rail) !important;
            min-width: var(--cv-foundation-rail) !important;
            max-width: var(--cv-foundation-rail) !important;
            height: 100vh !important;
            z-index: 999999 !important;
          }}
          html body:has(.st-key-cv_foundation_navigation) section[data-testid="stMain"],
          html body:has(.st-key-cv_foundation_navigation) [data-testid="stMain"] {{
            margin-left: var(--cv-foundation-rail) !important;
            width: calc(100% - var(--cv-foundation-rail)) !important;
            max-width: none !important;
            box-sizing: border-box !important;
          }}
        }}
        html body section[data-testid="stMain"] [class*="st-key-approved_home_row_"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_row_"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_row_"],
        html body section[data-testid="stMain"] [class*="st-key-approved_home_head"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_head"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_head"] {{
          margin:0 !important;padding:0 !important;min-height:0 !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-approved_home_row_"] [data-testid="stVerticalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_row_"] [data-testid="stVerticalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_row_"] [data-testid="stVerticalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_home_head"] [data-testid="stVerticalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_head"] [data-testid="stVerticalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_head"] [data-testid="stVerticalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_home_row_"] [data-testid="stHorizontalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_row_"] [data-testid="stHorizontalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_row_"] [data-testid="stHorizontalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_home_head"] [data-testid="stHorizontalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_head"] [data-testid="stHorizontalBlock"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_head"] [data-testid="stHorizontalBlock"] {{
          gap:0 !important;min-height:0 !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-approved_home_row_"] [data-testid="stElementContainer"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_row_"] [data-testid="stElementContainer"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_row_"] [data-testid="stElementContainer"],
        html body section[data-testid="stMain"] [class*="st-key-approved_home_head"] [data-testid="stElementContainer"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_head"] [data-testid="stElementContainer"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_head"] [data-testid="stElementContainer"],
        html body section[data-testid="stMain"] [class*="st-key-approved_home_row_"] [data-testid="stColumn"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_row_"] [data-testid="stColumn"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_row_"] [data-testid="stColumn"],
        html body section[data-testid="stMain"] [class*="st-key-approved_home_head"] [data-testid="stColumn"],
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_head"] [data-testid="stColumn"],
        html body section[data-testid="stMain"] [class*="st-key-approved_report_head"] [data-testid="stColumn"] {{
          margin:0 !important;padding:1px 8px !important;min-height:0 !important
        }}
        html body section[data-testid="stMain"] [class*="st-key-approved_home_row_"] [data-testid="stMarkdownContainer"] p,
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_row_"] [data-testid="stMarkdownContainer"] p,
        html body section[data-testid="stMain"] [class*="st-key-approved_report_row_"] [data-testid="stMarkdownContainer"] p,
        html body section[data-testid="stMain"] [class*="st-key-approved_home_head"] [data-testid="stMarkdownContainer"] p,
        html body section[data-testid="stMain"] [class*="st-key-approved_bom_head"] [data-testid="stMarkdownContainer"] p,
        html body section[data-testid="stMain"] [class*="st-key-approved_report_head"] [data-testid="stMarkdownContainer"] p {{
          margin:0 !important;line-height:1.2 !important;font-size:13px !important
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def authenticated_surface_ready() -> bool:
    """True after the authenticated workspace shell has initialized this session."""
    return bool(st.session_state.get("_cadivor_authenticated_surface_ready"))


def mark_authenticated_surface_ready() -> None:
    """Call once the authenticated shell/stylesheet stack is mounted."""
    st.session_state["_cadivor_authenticated_surface_ready"] = True
    from src.ui.cadivor_design_system import inject_cadivor_design_system

    inject_cadivor_design_system()
    inject_navigation_recovery_css()
    from src.ui.sprint71_polish import inject_sprint71_polish

    inject_sprint71_polish()


def page_shell(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    """Standard Cadivor page shell opener."""
    eyebrow_html = f'<div class="cvds-eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    subtitle_html = f'<p class="cv-core-page-copy">{escape(subtitle)}</p>' if subtitle else ""
    st.markdown(
        f'<section class="cv-core-page-shell">{eyebrow_html}<h1>{escape(title)}</h1>{subtitle_html}',
        unsafe_allow_html=True,
    )


def close_page_shell() -> None:
    st.markdown("</section>", unsafe_allow_html=True)


def status_badge(label: str, tone: BadgeTone = "neutral") -> str:
    css_class = _BADGE_CLASS.get(tone, "cvds-badge-neutral")
    return f'<span class="cv-status-pill {css_class}">{escape(str(label))}</span>'


def empty_state(title: str, body: str, icon: str = "◇") -> None:
    st.markdown(
        f'<div class="cv-core-empty"><div class="cvds-empty-icon">{escape(icon)}</div>'
        f'<h3>{escape(title)}</h3><p>{escape(body)}</p></div>',
        unsafe_allow_html=True,
    )


def kpi_row(items: Sequence[Mapping[str, object]], columns: int = 4) -> None:
    """Render a normalized KPI row using the shared premium pattern."""
    cards = []
    for item in items:
        tone = escape(str(item.get("tone", "info")))
        detail = escape(str(item.get("note", "")))
        cards.append(
            f'<article class="cv-kpi-card cv-kpi-tone-{tone} cvds-kpi cvds-tone-{tone}">'
            f'<span class="cv-kpi-label cvds-kpi-label">{escape(str(item.get("label", "")))}</span>'
            f'<strong class="cv-kpi-value">{escape(str(item.get("value", "—")))}</strong>'
            f'<small class="cv-kpi-detail">{detail}</small>'
            f"</article>"
        )
    st.markdown(
        f'<div class="cv-kpi-grid cvds-kpi-grid" style="--cvds-cols:{max(1, columns)}">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
