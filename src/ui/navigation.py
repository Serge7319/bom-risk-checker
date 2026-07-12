"""Cadivor internal same-tab navigation helpers."""
from __future__ import annotations

from typing import Any

import streamlit as st


def navigate_to(page: str, **params: Any) -> None:
    """Navigate to an internal Cadivor page in the current browser tab."""
    st.session_state["pending_app_mode"] = page
    try:
        st.query_params["page"] = page
        for key, value in params.items():
            if value is None or str(value).strip() == "":
                try:
                    del st.query_params[key]
                except Exception:
                    pass
            else:
                st.query_params[key] = str(value)
    except Exception:
        pass
    st.rerun()


def internal_nav_button(
    label: str,
    page: str,
    *,
    key: str,
    use_container_width: bool = False,
    type: str = "secondary",
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
