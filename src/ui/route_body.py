"""Single main-body host so route changes replace prior widgets in place.

Streamlit marks widgets from a previous route ``data-stale`` when a later
``app_mode`` branch paints at a different script position. A route change keeps
the Opening cover up until the destination body paints; same-page reruns keep
the existing content at normal opacity while Streamlit refreshes it.

Use one keyed ``st.container`` as the stable body slot, claimed by the unified
shell before route-dependent controls are painted. Its position matters as
much as its key: claiming it after a variable number of controls lets stale
Home content survive above the destination. Route transitions keep the Opening
cover until the target route paints, including when session caches are warm.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import streamlit as st

ROUTE_BODY_HOST_STATE_KEY = "_cadivor_route_body_host"
ROUTE_BODY_ROUTE_STATE_KEY = "_cadivor_route_body_route"
ROUTE_BODY_CM_STATE_KEY = "_cadivor_route_body_cm"
ROUTE_BODY_CM_RUN_STATE_KEY = "_cadivor_route_body_cm_run_id"
ROUTE_BODY_CONTAINER_KEY = "cadivor_authenticated_route_body"
ROUTE_BODY_CLAIM_RUN_STATE_KEY = "_cadivor_route_body_claim_run_id"


def _current_script_run_id() -> str | None:
    """Return Streamlit's run id without requiring an active app context."""
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import (
            get_script_run_ctx,
        )

        ctx = get_script_run_ctx()
    except Exception:
        return None
    if ctx is None:
        return None
    run_id = getattr(ctx, "script_run_id", None)
    return str(run_id) if run_id else None


def claim_authenticated_route_body(route: str = "") -> Any:
    """Claim the single keyed container at the shell's fixed script position.

    The shell claims it before rendering route-specific menu controls. The
    runtime calls this helper again later for backwards compatibility; that
    second call is a no-op in the same script run.
    """
    route_key = str(route or "").strip()
    current_run_id = _current_script_run_id()
    existing_host = st.session_state.get(ROUTE_BODY_HOST_STATE_KEY)
    existing_route = str(
        st.session_state.get(ROUTE_BODY_ROUTE_STATE_KEY) or ""
    ).strip()
    existing_run_id = st.session_state.get(ROUTE_BODY_CLAIM_RUN_STATE_KEY)
    # The shell claims the host at its fixed, route-independent position. The
    # runtime keeps its existing claim call for compatibility; make that later
    # call idempotent within this run so it cannot move the host down the page.
    if (
        existing_host is not None
        and current_run_id
        and existing_run_id == current_run_id
        and existing_route == route_key
    ):
        return existing_host

    exit_authenticated_route_body()
    # Recreate the DeltaGenerator on this run; the key keeps its browser block
    # identity stable while avoiding a stale cursor from a prior run.
    host = st.container(key=ROUTE_BODY_CONTAINER_KEY)
    st.session_state[ROUTE_BODY_HOST_STATE_KEY] = host
    st.session_state[ROUTE_BODY_ROUTE_STATE_KEY] = route_key
    st.session_state[ROUTE_BODY_CLAIM_RUN_STATE_KEY] = current_run_id
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
    # Enter the keyed block itself; nesting a new container here would create
    # another child block on each rerun and reintroduce duplicate content.
    cm = host
    cm.__enter__()
    st.session_state[ROUTE_BODY_CM_STATE_KEY] = cm
    st.session_state[ROUTE_BODY_CM_RUN_STATE_KEY] = _current_script_run_id()


def exit_authenticated_route_body() -> None:
    """Pop the shared body container if it is active."""
    cm = st.session_state.pop(ROUTE_BODY_CM_STATE_KEY, None)
    cm_run_id = st.session_state.pop(ROUTE_BODY_CM_RUN_STATE_KEY, None)
    if cm is None:
        return
    current_run_id = _current_script_run_id()
    # A callback that calls st.rerun() skips normal unwinding. The prior run's
    # container context does not belong to the next script execution; discard
    # it instead of popping the new run's Streamlit container stack.
    if cm_run_id and current_run_id and cm_run_id != current_run_id:
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
    with host:
        yield host
