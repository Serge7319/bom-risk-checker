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


def _load_css() -> str:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "core_premium_ui.css"
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
    """Inject shared tokens and auth-shell polish on signed-out routes."""
    inject_core_premium_ui()


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
        cards.append(
            f'<article class="cvds-kpi cvds-tone-{tone}">'
            f'<span class="cvds-kpi-label">{escape(str(item.get("label", "")))}</span>'
            f'<strong>{escape(str(item.get("value", "—")))}</strong>'
            f'<small>{escape(str(item.get("note", "")))}</small>'
            f"</article>"
        )
    st.markdown(
        f'<div class="cvds-kpi-grid" style="--cvds-cols:{max(1, columns)}">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
