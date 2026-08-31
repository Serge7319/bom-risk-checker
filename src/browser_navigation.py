"""Browser Back/Forward bridge for Cadivor's single-page Streamlit runtime."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components


_COMPONENT_DIR = Path(__file__).resolve().parent / "components" / "browser_navigation"
_browser_navigation_component = components.declare_component(
    "cadivor_browser_navigation",
    path=str(_COMPONENT_DIR),
)


def consume_browser_navigation_event() -> dict[str, Any] | None:
    """Return a browser Back/Forward event, if one occurred.

    Streamlit's server script does not automatically rerun when Chrome restores
    a prior URL with Back or Forward.  The companion zero-height component
    listens in the host page and sends one value only when that URL changes.
    """
    value = _browser_navigation_component(
        key="cadivor_browser_navigation_bridge",
        default=None,
    )
    return value if isinstance(value, dict) else None
