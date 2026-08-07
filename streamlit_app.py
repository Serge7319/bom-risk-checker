"""Cadivor Streamlit entrypoint.

Startup order:
1. Minimal Streamlit configuration
2. Lightweight auth bootstrap (Supabase session + login/signup UI)
3. Authenticated runtime import only after auth succeeds
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Cadivor",
    page_icon="C",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style id="cadivor-root-chrome">
    header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
    }
    .stApp { background: #F6F8FB !important; }
    .main .block-container, [data-testid="stAppViewContainer"] .main .block-container {
        padding-top: 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

from src.auth_bootstrap import (
    ensure_authenticated_or_stop,
    log_startup_phase,
    render_startup_loading_shell,
)
from src.auth_diagnostics import log_bootstrap_diagnostic
from src.auth_state import handle_explicit_logout_if_pending

log_startup_phase("entrypoint_ready")
log_bootstrap_diagnostic(stage="entrypoint_ready")
if handle_explicit_logout_if_pending():
    st.stop()

ensure_authenticated_or_stop()

render_startup_loading_shell("Opening your engineering workspace…")
log_startup_phase("load_authenticated_runtime")
from src.authenticated_runtime import run_authenticated_app

run_authenticated_app()
log_startup_phase("authenticated_runtime_loaded")
