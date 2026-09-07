"""Production-path Streamlit entry for auth continuity browser smoke.

Uses the same entry sequence as streamlit_app.py (ensure_authenticated_or_stop →
run_authenticated_app) with real routing and unified_shell. Only the
authenticated session boundary and network IO are doubled — never a synthetic
ready HTML surface.

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

from tests.auth_gate_smoke_adapter import install_production_path_smoke_patches

install_production_path_smoke_patches()

from src.auth_bootstrap import ensure_authenticated_or_stop, log_startup_phase
from src.performance_timing import timed_phase

log_startup_phase("entrypoint_ready")
if st.session_state.pop("cadivor_logout_reload_pending", False):
    st.session_state.pop("cadivor_explicit_logout", None)
    st.session_state.pop("cadivor_logout_in_progress", None)
    # Drop the DI smoke session cookie before same-tab reload so logout cannot
    # silently re-admit (production clears real auth cookies in begin_logout).
    try:
        from tests.auth_gate_smoke_adapter import _clear_smoke_cookie

        _clear_smoke_cookie()
    except Exception:
        pass
    components.html(
        """<script>
        (function () {
          const view = window.top || window.parent || window;
          if (!view || !view.location) {
            return;
          }
          try {
            const clear = (doc) => {
              if (!doc) return;
              doc.cookie = "cadivor_auth_gate_smoke=; path=/; Max-Age=0; SameSite=Lax";
            };
            clear(view.document);
          } catch (error) {}
          view.location.replace(view.location.pathname + view.location.search);
        })();
        </script>""",
        height=0,
        width=0,
    )
    st.stop()

with timed_phase("startup.ensure_authenticated", operation="resolve"):
    ensure_authenticated_or_stop()

# Mirror production streamlit_app Login→shell bridge during runtime import.
if not st.session_state.get("cadivor_foundation_shell_mounted"):
    try:
        from src.auth_gate import paint_auth_gate
        from src.auth_state import AUTH_AUTHENTICATED

        if str(st.session_state.get("cadivor_auth_status") or "") == AUTH_AUTHENTICATED:
            paint_auth_gate("authenticating")
    except Exception:
        pass

log_startup_phase("load_authenticated_runtime")
with timed_phase("startup.authenticated_runtime_import", operation="import"):
    from src.authenticated_runtime import run_authenticated_app

with timed_phase("startup.run_authenticated_app", operation="render", route="authenticated"):
    run_authenticated_app()
log_startup_phase("authenticated_runtime_loaded")
