"""Sprint 71 — Premium performance and polish utilities."""
from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

from src.ui.executive_workspace import content_skeleton, inject_executive_workspace_css

_POLISH_CSS_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "css" / "sprint71_polish.css"
)
_POLISH_INJECTED = "_cv71_polish_css_injected"


def inject_sprint71_polish() -> None:
    """Load Sprint 71 polish CSS and skeleton styles once per session."""
    if st.session_state.get(_POLISH_INJECTED):
        return
    inject_executive_workspace_css()
    try:
        css = _POLISH_CSS_PATH.read_text(encoding="utf-8")
    except OSError:
        css = ""
    if css.strip():
        st.markdown(f'<style id="cadivor-sprint71-polish">{css}</style>', unsafe_allow_html=True)
    st.session_state[_POLISH_INJECTED] = True


def render_page_skeleton(*, kpis: int = 4, panels: int = 2) -> None:
    """Render a shimmer skeleton while heavyweight workspace content prepares."""
    content_skeleton(kpis=kpis, panels=panels)


def premium_empty_state(
    title: str,
    body: str,
    *,
    icon: str = "layers",
    actions: tuple[str, ...] = (),
) -> str:
    """Return premium empty-state markup for HTML surfaces."""
    action_html = ""
    if actions:
        chips = "".join(
            f'<span class="cv71-empty-action">{escape(label)}</span>' for label in actions
        )
        action_html = f'<div class="cv71-empty-actions">{chips}</div>'
    return (
        f'<section class="cv71-empty-state" role="status">'
        f'<div class="cv71-empty-icon" aria-hidden="true">{escape(icon[:1].upper())}</div>'
        f"<h3>{escape(title)}</h3>"
        f"<p>{escape(body)}</p>"
        f"{action_html}"
        f"</section>"
    )
