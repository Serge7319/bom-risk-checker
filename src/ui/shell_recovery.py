"""Sprint 58.1 authenticated-shell recovery.

This module is presentation-only. It establishes one final layout contract after
all legacy design layers have loaded.
"""
from __future__ import annotations

from pathlib import Path
import streamlit as st


def inject_shell_recovery_css() -> None:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "shell_recovery.css"
    try:
        css = path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f'<style id="cadivor-sprint-58-1">{css}</style>', unsafe_allow_html=True)
