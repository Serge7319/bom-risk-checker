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
from src.ui.unified_shell import paint_authenticated_continuity_shell

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

# Mirror production order: continuity chrome (fixed, no skeleton) → durable shell
# → page content. Routes under test must start directly below the topbar.
_SMOKE_ROUTES = (
    "Dashboard",
    "Alternative Finder",
    "Compare Parts",
    "Design Impact",
)
page = str(st.session_state.get("cadivor_smoke_page") or "Dashboard").strip() or "Dashboard"
if page not in _SMOKE_ROUTES:
    page = "Dashboard"
    st.session_state["cadivor_smoke_page"] = page

paint_authenticated_continuity_shell(page=page)

st.markdown(
    f"""
    <div data-testid="cadivor-auth-ready" data-auth-gate="ready"
         class="cv-foundation-topbar"
         style="position:fixed;top:0;left:0;right:0;z-index:1000;padding:16px 24px;
                font-family:Inter,system-ui,sans-serif;background:#fff;
                border-bottom:1px solid #E2E8F0">
      <div style="font-size:18px;font-weight:900;color:#0F172A">Cadivor</div>
      <div style="margin-top:4px;color:#475569;font-size:12px">Mock workspace ready</div>
    </div>
    <div data-testid="cadivor-smoke-page" data-smoke-route="{page}"
         style="padding:88px 24px 24px;font-family:Inter,system-ui,sans-serif">
      <h1 data-testid="cadivor-page-heading"
          style="margin:0;font-size:28px;font-weight:950;color:#0F172A">{page}</h1>
      <p style="margin:10px 0 0;color:#64748B;font-size:14px">
        Smoke page content for {page}. No continuity skeleton may sit above this heading.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)
retire_auth_gate_overlays()

nav_cols = st.columns(4)
for col, route in zip(nav_cols, _SMOKE_ROUTES):
    with col:
        if st.button(f"Open {route}", key=f"smoke_nav_{route.replace(' ', '_').lower()}"):
            st.session_state["cadivor_smoke_page"] = route
            st.rerun()
