"""Final launch consistency authority for authenticated Cadivor routes."""
from pathlib import Path
import streamlit as st


def inject_workspace_consistency_css() -> None:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "workspace_consistency.css"
    try:
        css = path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style id='cadivor-workspace-consistency'>{css}</style>", unsafe_allow_html=True)
