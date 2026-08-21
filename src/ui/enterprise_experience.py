"""Sprint 58 enterprise product-experience primitives.

This module is presentation-only. It deliberately contains no authentication,
routing, supplier, analysis, entitlement, persistence, or recommendation logic.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st


def inject_enterprise_experience_css() -> None:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "enterprise_experience.css"
    try:
        css = path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f'<style id="cadivor-sprint-58">{css}</style>', unsafe_allow_html=True)


def operation_status(title: str, detail: str) -> None:
    """Render a content-area operation status without obscuring the app shell."""
    st.markdown(
        f'''<div class="cv58-operation" role="status" aria-live="polite">
        <span class="cv58-operation-spinner"></span>
        <div><strong>{escape(title)}</strong><small>{escape(detail)}</small></div>
        </div>''',
        unsafe_allow_html=True,
    )
