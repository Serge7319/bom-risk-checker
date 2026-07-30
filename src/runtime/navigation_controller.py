"""Single-route authority for the authenticated Cadivor workspace."""
from __future__ import annotations

from typing import Iterable
import streamlit as st

DEFAULT_ROUTE = "Dashboard"
SPECIAL_ROUTES = {"Analysis Details", "Onboarding"}


def commit_route(route: str, *, allowed: Iterable[str]) -> str:
    allowed_routes = set(allowed) | SPECIAL_ROUTES
    resolved = str(route or DEFAULT_ROUTE).strip() or DEFAULT_ROUTE
    if resolved not in allowed_routes:
        resolved = DEFAULT_ROUTE
    st.session_state["cadivor_route"] = resolved
    # Compatibility mirror for page modules not yet migrated.
    st.session_state["app_mode"] = resolved
    st.session_state["cadivor_profile_menu_open"] = False
    return resolved


def resolve_route(*, allowed: Iterable[str]) -> str:
    """Resolve the committed route without reading browser query parameters."""
    route = st.session_state.get("cadivor_route") or st.session_state.get("app_mode")
    return commit_route(str(route or DEFAULT_ROUTE), allowed=allowed)


def navigate(route: str, *, allowed: Iterable[str]) -> None:
    commit_route(route, allowed=allowed)
