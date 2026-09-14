"""Browser Back/Forward bridge for Cadivor's single-page Streamlit runtime."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

_COMPONENT_DIR = Path(__file__).resolve().parent / "components" / "browser_navigation"


@lru_cache(maxsize=1)
def _declared_component():
    """Declare only when a ScriptRunContext exists so Streamlit registers the path.

    Import-time ``declare_component`` skips registry registration (no ctx), which
    leaves the iframe URL 404'ing and Back/Forward never emitting a value.
    """
    import streamlit.components.v1 as components

    return components.declare_component(
        "cadivor_browser_navigation_v4",
        path=str(_COMPONENT_DIR),
    )


def consume_browser_navigation_event() -> dict[str, Any] | None:
    """Return a browser Back/Forward event, if one occurred.

    Streamlit's server script does not automatically rerun when Chrome restores
    a prior query-only URL with Back or Forward (its popstate handler only
    reacts to multipage pathname changes). The companion zero-height component
    installs a durable parent-window listener and sends one value when the
    address bar changes so Python can restore the route without pushing history.
    """
    try:
        component = _declared_component()
    except (ImportError, AttributeError):
        # Unit-test Streamlit stubs do not expose the components package.
        return None
    # Re-register on every consume so a cached declare from a ctx-less import
    # path cannot leave the asset unregistered for the running server.
    try:
        from streamlit.runtime import get_instance
        from streamlit.runtime.scriptrunner_utils.script_run_context import (
            get_script_run_ctx,
        )

        if get_script_run_ctx() is not None:
            get_instance().component_registry.register_component(component)
    except Exception:
        pass
    value = component(
        key="cadivor_browser_navigation_bridge_v4",
        default=None,
    )
    return value if isinstance(value, dict) else None
