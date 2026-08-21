"""Sprint 60 premium product reset.

A final, authenticated-only visual authority rendered after page content so
legacy page-local CSS cannot override the product system.
"""
from pathlib import Path
import streamlit as st


def inject_premium_product_reset() -> None:
    path = Path(__file__).resolve().parents[1] / "assets" / "css" / "premium_product_reset.css"
    try:
        css = path.read_text(encoding="utf-8")
    except Exception:
        return
    st.markdown(f"<style id='cadivor-premium-product-reset'>{css}</style>", unsafe_allow_html=True)
