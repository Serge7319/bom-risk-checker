"""Single main-body host so route changes replace prior widgets in place.

Streamlit marks widgets from a previous route ``data-stale`` when a later
``app_mode`` branch paints at a different script position. Warm in-session
navigation skips Opening, so those stale controls stay visible (for example
disabled ``Back to BOMs`` rows on Alerts & Monitoring).

Claim the shared ``st.empty()`` host once per run, enter its container so every
page paints into the same slot, then clear it on the next route. Calling
``empty()`` retires the previous route's widgets without CSS hiding and without
re-indenting every page branch.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import streamlit as st

ROUTE_BODY_HOST_STATE_KEY = "_cadivor_route_body_host"
ROUTE_BODY_ROUTE_STATE_KEY = "_cadivor_route_body_route"
ROUTE_BODY_CM_STATE_KEY = "_cadivor_route_body_cm"


def claim_authenticated_route_body(route: str = "") -> Any:
    """Claim the shared main-body slot and clear any prior-route widgets."""
    exit_authenticated_route_body()
    host = st.empty()
    host.empty()
    st.session_state[ROUTE_BODY_HOST_STATE_KEY] = host
    st.session_state[ROUTE_BODY_ROUTE_STATE_KEY] = str(route or "").strip()
    return host


def enter_authenticated_route_body(route: str = "") -> None:
    """Push the shared body container so subsequent widgets paint into it."""
    host = st.session_state.get(ROUTE_BODY_HOST_STATE_KEY)
    if host is None:
        host = claim_authenticated_route_body(route)
    elif route:
        st.session_state[ROUTE_BODY_ROUTE_STATE_KEY] = str(route).strip()
    if st.session_state.get(ROUTE_BODY_CM_STATE_KEY) is not None:
        return
    cm = host.container()
    cm.__enter__()
    st.session_state[ROUTE_BODY_CM_STATE_KEY] = cm


def exit_authenticated_route_body() -> None:
    """Pop the shared body container if it is active."""
    cm = st.session_state.pop(ROUTE_BODY_CM_STATE_KEY, None)
    if cm is None:
        return
    try:
        cm.__exit__(None, None, None)
    except Exception:
        pass


@contextmanager
def authenticated_route_body(route: str = "") -> Iterator[Any]:
    """Compatibility helper for tests: paint into the shared body host."""
    host = st.session_state.get(ROUTE_BODY_HOST_STATE_KEY)
    if host is None:
        host = claim_authenticated_route_body(route)
    elif route:
        st.session_state[ROUTE_BODY_ROUTE_STATE_KEY] = str(route).strip()
    with host.container():
        yield host
