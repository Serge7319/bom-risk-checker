"""Cadivor Streamlit entrypoint.

Startup order:
1. Minimal Streamlit configuration
2. Lightweight auth bootstrap (Supabase session + login/signup UI)
3. Authenticated runtime import only after auth succeeds
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

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
    AUTHENTICATED_STARTUP_SHELL_MESSAGE,
    ensure_authenticated_or_stop,
    log_startup_phase,
    render_startup_loading_shell,
    should_render_authenticated_startup_shell,
)

log_startup_phase("entrypoint_ready")
if st.session_state.pop("cadivor_logout_reload_pending", False):
    st.session_state.pop("cadivor_explicit_logout", None)
    st.session_state.pop("cadivor_logout_in_progress", None)
    components.html(
        """<script>
        (function () {
          const view = window.top || window.parent || window;
          if (!view || !view.location) {
            return;
          }
          view.location.replace(view.location.pathname + view.location.search);
        })();
        </script>""",
        height=0,
        width=0,
    )
    st.stop()

ensure_authenticated_or_stop()

if should_render_authenticated_startup_shell():
    render_startup_loading_shell(AUTHENTICATED_STARTUP_SHELL_MESSAGE)
log_startup_phase("load_authenticated_runtime")
from src.authenticated_runtime import run_authenticated_app

run_authenticated_app()
log_startup_phase("authenticated_runtime_loaded")
