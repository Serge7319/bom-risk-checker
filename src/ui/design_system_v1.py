"""Cadivor Sprint 33 — Design System 1.0.

A final, non-destructive visual layer loaded after legacy milestone CSS.  It
standardizes typography, surfaces, controls, tables, navigation, badges,
empty states, and responsive behavior without changing application logic.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Literal

import streamlit as st

Tone = Literal["info", "success", "warning", "danger", "neutral", "purple"]


def inject_design_system_v1() -> None:
    """Load the authoritative Cadivor Design System v1 stylesheet last."""
    css_path = Path(__file__).resolve().parents[1] / "assets" / "css" / "design_system_v1.css"
    try:
        css = css_path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style id=\"cadivor-design-system-v1\">{css}</style>", unsafe_allow_html=True)


def badge_html(label: str, tone: Tone = "neutral") -> str:
    css_tone = "muted" if tone == "neutral" else tone
    return f'<span class="cv-status-pill {css_tone}">{escape(str(label))}</span>'


def section_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    eyebrow_html = f'<div class="cv-eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    subtitle_html = f'<p class="cv-section-copy">{escape(subtitle)}</p>' if subtitle else ""
    st.markdown(
        f'<div class="cv-section-header">{eyebrow_html}<h2 class="cv-section-title">{escape(title)}</h2>{subtitle_html}</div>',
        unsafe_allow_html=True,
    )


def empty_state(title: str, body: str, icon: str = "◇") -> None:
    st.markdown(
        f'<div class="cv-empty-state"><div class="cv-empty-icon">{escape(icon)}</div><div class="cv-empty-title">{escape(title)}</div><div class="cv-empty-body">{escape(body)}</div></div>',
        unsafe_allow_html=True,
    )
