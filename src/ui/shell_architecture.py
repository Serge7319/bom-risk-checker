"""Sprint 59 authoritative authenticated shell architecture."""
from __future__ import annotations
from pathlib import Path
import streamlit as st


def inject_shell_architecture_css() -> None:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "shell_architecture.css"
    try:
        css = path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f'<style id="cadivor-shell-architecture-s59">{css}</style>', unsafe_allow_html=True)
