"""Test-only Streamlit entrypoint for auth-gate browser smoke.

Never deploy. Production always uses streamlit_app.py with real Supabase auth.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(
    page_title="Cadivor Auth Smoke",
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

from tests.auth_gate_smoke_adapter import install_smoke_auth_patches

install_smoke_auth_patches()

from src.auth_bootstrap import ensure_authenticated_or_stop, log_startup_phase
from src.auth_gate import retire_auth_gate_overlays

log_startup_phase("smoke_entrypoint_ready")
if st.session_state.pop("cadivor_logout_reload_pending", False):
    components.html(
        """<script>
        (function () {
          const view = window.top || window.parent || window;
          if (!view || !view.location) { return; }
          view.location.replace(view.location.pathname + view.location.search);
        })();
        </script>""",
        height=0,
    )
    st.stop()

ensure_authenticated_or_stop()

# Gate returned ready — paint shell chrome BEFORE retiring the signing-in surface.
page = str(st.session_state.get("cadivor_smoke_page") or "Dashboard").strip() or "Dashboard"
st.markdown(
    f"""
    <div data-testid="cadivor-auth-ready" data-auth-gate="ready"
         class="cv-foundation-topbar" style="padding:24px;font-family:Inter,system-ui,sans-serif">
      <div style="font-size:18px;font-weight:900;color:#0F172A">Cadivor</div>
      <div style="margin-top:8px;color:#475569;font-size:13px">Mock workspace ready</div>
      <div style="margin-top:18px;font-size:22px;font-weight:900;color:#0F172A">{page}</div>
    </div>
    """,
    unsafe_allow_html=True,
)
retire_auth_gate_overlays()

col_a, col_b = st.columns(2)
with col_a:
    if st.button("Open Settings", key="smoke_nav_settings"):
        st.session_state["cadivor_smoke_page"] = "Settings"
        st.rerun()
with col_b:
    if st.button("Open Dashboard", key="smoke_nav_dashboard"):
        st.session_state["cadivor_smoke_page"] = "Dashboard"
        st.rerun()
