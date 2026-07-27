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
            f'''<article class="cvds-kpi cvds-tone-{tone}"><div class="cvds-kpi-top">
            <span class="cvds-kpi-label">{escape(str(item.get('label','')))}</span>
            <span class="cvds-kpi-icon">{escape(str(item.get('icon','•')))}</span></div>
            <strong>{escape(str(item.get('value','—')))}</strong>
            <small>{escape(str(item.get('note','')))}</small></article>'''
        )
    st.markdown(f'<div class="cvds-kpi-grid" style="--cvds-cols:{max(1, columns)}">{"".join(cards)}</div>', unsafe_allow_html=True)


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
    return f'<span class="cvds-badge cvds-badge-{escape(tone)}">{escape(label)}</span>'
