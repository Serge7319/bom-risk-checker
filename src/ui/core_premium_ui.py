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
