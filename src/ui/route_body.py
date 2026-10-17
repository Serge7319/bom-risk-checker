"""Single main-body host so route changes replace prior widgets in place.

Streamlit marks widgets from a previous route ``data-stale`` when a later
``app_mode`` branch paints at a different script position. A route change keeps
the Opening cover up until the destination body paints; same-page reruns keep
the existing content at normal opacity while Streamlit refreshes it.

Claim the shared ``st.empty()`` host once per run, enter its container so every
page paints into the same slot, then clear it on the next route. Calling
``empty()`` retires the previous route's widgets without CSS hiding and without
re-indenting every page branch. Route transitions keep the Opening cover until
the target route paints, including when session caches are warm.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import streamlit as st

ROUTE_BODY_HOST_STATE_KEY = "_cadivor_route_body_host"
ROUTE_BODY_ROUTE_STATE_KEY = "_cadivor_route_body_route"
ROUTE_BODY_CM_STATE_KEY = "_cadivor_route_body_cm"


def claim_authenticated_route_body(route: str = "") -> Any:
    """Claim the shared body slot, clearing only when the route changes."""
    exit_authenticated_route_body()
    route_key = str(route or "").strip()
    host = st.session_state.get(ROUTE_BODY_HOST_STATE_KEY)
    previous_route = str(
        st.session_state.get(ROUTE_BODY_ROUTE_STATE_KEY) or ""
    ).strip()
    if host is None:
        # A new placeholder is empty already. Avoid emitting an extra empty
        # delta before the first page widgets are painted.
        host = st.empty()
    elif previous_route != route_key:
        # Keep the mounted page visible while it refreshes. A real route hop
        # still retires the old widgets inside the transition-covered slot.
        host.empty()
    st.session_state[ROUTE_BODY_HOST_STATE_KEY] = host
    st.session_state[ROUTE_BODY_ROUTE_STATE_KEY] = route_key
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
