"""Cadivor internal same-tab navigation helpers."""
from __future__ import annotations

from typing import Any

import streamlit as st


def navigate_to(page: str, **params: Any) -> None:
    """Navigate without a browser reload or a new Streamlit session.

    Internal navigation is intentionally session-state driven. Query strings are
    still accepted for external/deep links, but ordinary clicks must not force
    CookieManager and Supabase authentication to hydrate again.
    """
    # One authoritative route value. Legacy app_mode remains mirrored only for
    # compatibility with older page modules.
    st.session_state["cadivor_route"] = page
    st.session_state["app_mode"] = page
    nav_params = {"page": page}
    for key, value in params.items():
        if value is not None and str(value).strip() != "":
            nav_params[key] = str(value)
    st.session_state["cadivor_nav_params"] = nav_params
    st.rerun()


def internal_nav_button(
    label: str,
    page: str,
    *,
    key: str,
    use_container_width: bool = False,
    type: str = "primary",
    disabled: bool = False,
    **params: Any,
) -> bool:
    """Render a button that keeps navigation inside the current Cadivor tab."""
    clicked = st.button(
        label,
        key=key,
        use_container_width=use_container_width,
        type=type,
        disabled=disabled,
    )
    if clicked:
        navigate_to(page, **params)
    return clicked
