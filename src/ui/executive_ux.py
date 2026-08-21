"""Sprint 57 presentation primitives for Cadivor's executive UX.

Presentation only: no routing, authentication, persistence, analysis, supplier,
entitlement, recommendation, report, or monitoring logic lives here.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Mapping, Sequence

import streamlit as st


def inject_executive_ux_css() -> None:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "executive_ux.css"
    try:
        css = path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f'<style id="cadivor-sprint-57">{css}</style>', unsafe_allow_html=True)


def workflow_steps(steps: Sequence[str], active: int = 1) -> None:
    active = max(1, min(active, len(steps))) if steps else 1
    markup = []
    for index, label in enumerate(steps, start=1):
        state = "complete" if index < active else "active" if index == active else "pending"
        markup.append(
            f'<div class="cv57-step cv57-step-{state}"><i>{index}</i><span>{escape(label)}</span></div>'
        )
    st.markdown(f'<div class="cv57-workflow">{"".join(markup)}</div>', unsafe_allow_html=True)


def signal_grid(items: Sequence[Mapping[str, object]]) -> None:
    cards = []
    for item in items:
        tone = escape(str(item.get("tone", "neutral")))
        cards.append(
            '<article class="cv57-signal cv57-signal-' + tone + '">'
            f'<span>{escape(str(item.get("label", "")))}</span>'
            f'<strong>{escape(str(item.get("value", "—")))}</strong>'
            f'<small>{escape(str(item.get("note", "")))}</small>'
            '</article>'
        )
    st.markdown(f'<div class="cv57-signal-grid">{"".join(cards)}</div>', unsafe_allow_html=True)
