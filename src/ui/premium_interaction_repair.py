"""Premium interaction CSS injector."""
from __future__ import annotations
from pathlib import Path
import streamlit as st


def inject_premium_interaction_css() -> None:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "premium_interactions.css"
    try:
        css = path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style id='cadivor-premium-interaction-css'>{css}</style>", unsafe_allow_html=True)
