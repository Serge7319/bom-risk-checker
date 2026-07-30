"""Sprint 61 root application controller.

Every Streamlit run selects exactly one top-level surface. Signed-out/auth
surfaces stop the script before authenticated workspace initialization begins.
"""
from __future__ import annotations

from typing import Any
import streamlit as st

from src.auth_state import APP_AUTHENTICATED, AUTH_AUTHENTICATED
from src.runtime.auth_controller import render_signed_out_surface, resolve_root_state


def enter_application(supabase: Any) -> bool:
    """Return True only when the authenticated workspace may render."""
    root_state, auth_status = resolve_root_state(supabase)

    if root_state != APP_AUTHENTICATED or auth_status != AUTH_AUTHENTICATED:
        render_signed_out_surface(supabase)
        st.stop()

    return True
