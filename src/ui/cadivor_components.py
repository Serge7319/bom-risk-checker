"""Cadivor Design System v1 reusable authenticated-workspace components."""
from __future__ import annotations
from html import escape
from typing import Iterable, Mapping, Sequence
import streamlit as st


def page_header(title: str, subtitle: str = "", eyebrow: str = "", actions: Sequence[tuple[str, str]] = ()) -> None:
    action_html = "".join(
        f'<span class="cvds-header-action cvds-{escape(kind)}">{escape(label)}</span>'
        for label, kind in actions
    )
    st.markdown(
        f'''<section class="cvds-page-header"><div class="cvds-page-copy">
        {f'<div class="cvds-eyebrow">{escape(eyebrow)}</div>' if eyebrow else ''}
        <h1>{escape(title)}</h1>{f'<p>{escape(subtitle)}</p>' if subtitle else ''}</div>
        {f'<div class="cvds-header-actions">{action_html}</div>' if action_html else ''}</section>''',
        unsafe_allow_html=True,
    )


def kpi_grid(items: Sequence[Mapping[str, object]], columns: int = 4) -> None:
    cards = []
    for item in items:
        tone = escape(str(item.get("tone", "neutral")))
        cards.append(
            f'''<article class="cv-kpi-card cv-kpi-tone-{tone} cvds-kpi cvds-tone-{tone}">
            <span class="cv-kpi-label cvds-kpi-label">{escape(str(item.get('label','')))}</span>
            <strong class="cv-kpi-value">{escape(str(item.get('value','—')))}</strong>
            <small class="cv-kpi-detail">{escape(str(item.get('note','')))}</small></article>'''
        )
    st.markdown(
        f'<div class="cv-kpi-grid cvds-kpi-grid" style="--cvds-cols:{max(1, columns)}">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    st.markdown(
        f'''<div class="cvds-section-header">{f'<span>{escape(eyebrow)}</span>' if eyebrow else ''}
        <h2>{escape(title)}</h2>{f'<p>{escape(subtitle)}</p>' if subtitle else ''}</div>''',
        unsafe_allow_html=True,
    )


def content_card(title: str = "", subtitle: str = "", tone: str = "default") -> None:
    st.markdown(
        f'''<div class="cvds-content-card cvds-card-{escape(tone)}">
        {f'<div class="cvds-card-heading"><h3>{escape(title)}</h3>{f"<p>{escape(subtitle)}</p>" if subtitle else ""}</div>' if title else ''}''',
        unsafe_allow_html=True,
    )


def end_card() -> None:
    st.markdown('</div>', unsafe_allow_html=True)


def empty_state(title: str, body: str, action: str = "", icon: str = "◇") -> None:
    st.markdown(
        f'''<div class="cvds-empty"><span class="cvds-empty-icon">{escape(icon)}</span>
        <h3>{escape(title)}</h3><p>{escape(body)}</p>
        {f'<span class="cvds-empty-action">{escape(action)}</span>' if action else ''}</div>''',
        unsafe_allow_html=True,
    )


def status_badge(label: str, tone: str = "neutral") -> str:
    from src.ui.core_premium_ui import status_badge as core_status_badge

    allowed = {
        "neutral", "success", "warning", "danger", "info", "approved", "active",
        "blocked", "high", "medium", "low", "monitoring", "qualified", "available",
        "pending", "draft", "eol", "nrnd", "recommended",
    }
    mapped = tone if tone in allowed else "neutral"
    return core_status_badge(label, mapped)  # type: ignore[arg-type]
