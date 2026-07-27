"""Sprint 56 — Executive Workspace primitives.

This module is presentation-only. It intentionally contains no routing,
authentication, database, entitlement, analysis, monitoring, or recommendation
logic. Components render deterministic HTML/CSS inside the authenticated canvas.
"""
from __future__ import annotations

from contextlib import contextmanager
from html import escape
from pathlib import Path
from typing import Iterator, Mapping, Sequence

import streamlit as st


_PAGE_META: dict[str, tuple[str, str]] = {
    "Dashboard": ("Executive workspace", "Engineering health, exposure, decisions, and monitored change."),
    "BOM Analyzer": ("Analyze", "Upload, validate, and review the active bill of materials."),
    "Analysis Details": ("Analyze", "Review engineering evidence and the active analysis context."),
    "Alternative Finder": ("Analyze", "Compare qualified replacement options and recommendation evidence."),
    "Design Impact Analyzer": ("Analyze", "Understand design consequences before approving a component change."),
    "Engineering Intelligence": ("Analyze", "Explore engineering risk, evidence, and production readiness."),
    "Ask Cadivor": ("Analyze", "Continue the evidence-grounded engineering review conversation."),
    "Engineering Decisions": ("Decide", "Prioritize approvals, owners, evidence, and unresolved actions."),
    "Procurement Advisor": ("Decide", "Convert component risk into focused supplier and sourcing actions."),
    "Cost Optimization": ("Decide", "Identify defensible savings without hiding engineering tradeoffs."),
    "Supply Risk Scenario": ("Decide", "Test supply-chain scenarios against the active engineering baseline."),
    "Monitoring": ("Monitor", "Review lifecycle, inventory, supplier, and evidence changes."),
    "Portfolio Intelligence": ("Monitor", "Compare engineering health and exposure across the portfolio."),
    "Reports": ("Monitor", "Generate and retrieve decision-ready engineering reports."),
    "Pricing": ("Workspace", "Review plan capabilities, usage, and upgrade options."),
    "Settings": ("Workspace", "Manage account preferences and workspace defaults."),
    "Workspace": ("Workspace", "Manage collaboration, organization context, and operating settings."),
    "Notifications": ("Workspace", "Review workspace and monitoring notifications."),
    "Help": ("Workspace", "Find guidance for Cadivor workflows and engineering reviews."),
}


def inject_executive_workspace_css() -> None:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "executive_workspace.css"
    try:
        css = path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f'<style id="cadivor-sprint-56">{css}</style>', unsafe_allow_html=True)


def render_page_context(page: str) -> None:
    """Render a restrained, universal authenticated-page context row."""
    eyebrow, description = _PAGE_META.get(page, ("Cadivor", "Engineering decision intelligence workspace."))
    st.markdown(
        f'''<div class="cv56-page-context" data-page="{escape(page)}">
        <div><span>{escape(eyebrow)}</span><strong>{escape(page)}</strong></div>
        <p>{escape(description)}</p></div>''',
        unsafe_allow_html=True,
    )


def page_header(
    title: str,
    description: str = "",
    *,
    eyebrow: str = "",
    badges: Sequence[tuple[str, str]] = (),
) -> None:
    badge_html = "".join(
        f'<span class="cv56-badge cv56-{escape(tone)}">{escape(label)}</span>' for label, tone in badges
    )
    st.markdown(
        f'''<header class="cv56-page-header">
        <div class="cv56-page-header-copy">{f'<span class="cv56-eyebrow">{escape(eyebrow)}</span>' if eyebrow else ''}
        <h1>{escape(title)}</h1>{f'<p>{escape(description)}</p>' if description else ''}</div>
        {f'<div class="cv56-header-badges">{badge_html}</div>' if badge_html else ''}</header>''',
        unsafe_allow_html=True,
    )


def executive_kpi_grid(items: Sequence[Mapping[str, object]], columns: int = 4) -> None:
    cards: list[str] = []
    for item in items:
        tone = escape(str(item.get("tone", "neutral")))
        icon = escape(str(item.get("icon", "")))
        cards.append(
            f'''<article class="cv56-kpi cv56-kpi-{tone}">
            <div class="cv56-kpi-head"><span>{escape(str(item.get('label', '')))}</span>{f'<i>{icon}</i>' if icon else ''}</div>
            <strong>{escape(str(item.get('value', '—')))}</strong>
            <small>{escape(str(item.get('note', '')))}</small></article>'''
        )
    st.markdown(
        f'<div class="cv56-kpi-grid" style="--cv56-kpi-columns:{max(1, min(columns, 6))}">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


@contextmanager
def page_shell(*, width: str = "standard") -> Iterator[None]:
    st.markdown(f'<div class="cv56-page-shell cv56-width-{escape(width)}">', unsafe_allow_html=True)
    try:
        yield
    finally:
        st.markdown('</div>', unsafe_allow_html=True)


@contextmanager
def content_card(title: str = "", description: str = "", *, major: bool = False) -> Iterator[None]:
    modifier = " cv56-card-major" if major else ""
    heading = ""
    if title:
        heading = f'<div class="cv56-card-heading"><h3>{escape(title)}</h3>{f"<p>{escape(description)}</p>" if description else ""}</div>'
    st.markdown(f'<section class="cv56-card{modifier}">{heading}', unsafe_allow_html=True)
    try:
        yield
    finally:
        st.markdown('</section>', unsafe_allow_html=True)


def status_badge(label: str, tone: str = "neutral") -> str:
    return f'<span class="cv56-badge cv56-{escape(tone)}">{escape(label)}</span>'


def empty_state(title: str, body: str, icon: str = "◇") -> None:
    st.markdown(
        f'<div class="cv56-empty"><i>{escape(icon)}</i><h3>{escape(title)}</h3><p>{escape(body)}</p></div>',
        unsafe_allow_html=True,
    )


def content_skeleton(*, kpis: int = 4, panels: int = 2) -> None:
    kpi_html = ''.join('<span class="cv56-skeleton cv56-skeleton-kpi"></span>' for _ in range(max(0, kpis)))
    panel_html = ''.join('<span class="cv56-skeleton cv56-skeleton-panel"></span>' for _ in range(max(0, panels)))
    st.markdown(
        f'<div class="cv56-skeleton-page"><span class="cv56-skeleton cv56-skeleton-title"></span><div class="cv56-skeleton-kpis">{kpi_html}</div>{panel_html}</div>',
        unsafe_allow_html=True,
    )
