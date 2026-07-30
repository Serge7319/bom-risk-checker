"""Single authority for Cadivor authentication transitions."""
from __future__ import annotations

from typing import Any
import streamlit as st

from src.auth import show_auth_ui
from src.auth_state import (
    APP_AUTHENTICATED,
    APP_PUBLIC,
    AUTH_AUTHENTICATED,
    AUTH_SIGNED_OUT,
    begin_logout,
    resolve_auth_state,
)


def initialize_auth_state() -> None:
    """Initialize the minimum stable auth state without rendering UI."""
    st.session_state.setdefault("cadivor_root_state", APP_PUBLIC)
    st.session_state.setdefault("cadivor_auth_status", AUTH_SIGNED_OUT)
    st.session_state.setdefault("cadivor_public_route", "home")
    st.session_state.setdefault("cadivor_profile_menu_open", False)


def resolve_root_state(supabase: Any) -> tuple[str, str]:
    """Resolve one root state and one auth status for the current run."""
    initialize_auth_state()
    auth_status = resolve_auth_state(supabase, None)
    root_state = str(st.session_state.get("cadivor_root_state") or APP_PUBLIC)

    if auth_status == AUTH_AUTHENTICATED:
        root_state = APP_AUTHENTICATED
        st.session_state["cadivor_root_state"] = root_state
    elif root_state == APP_AUTHENTICATED:
        root_state = APP_PUBLIC
        st.session_state["cadivor_root_state"] = root_state

    return root_state, auth_status


def render_signed_out_surface(supabase: Any) -> None:
    """Render exactly one public/login/signup/signing-in surface."""
    show_auth_ui(supabase, None)


def logout(supabase: Any | None = None) -> None:
    """Commit logout locally. The button rerun is the only rerun."""
    st.session_state["cadivor_profile_menu_open"] = False
    st.session_state.pop("cadivor_route_transition", None)
    st.session_state.pop("cadivor_nav_params", None)
    begin_logout(supabase, None)
