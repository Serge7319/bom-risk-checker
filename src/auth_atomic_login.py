"""Atomic browser Login component for one-event credential submission."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any


_COMPONENT_DIR = Path(__file__).resolve().parent / "components" / "atomic_login"


@lru_cache(maxsize=1)
def _declared_component():
    import streamlit.components.v1 as components

    return components.declare_component(
        "cadivor_atomic_login",
        path=str(_COMPONENT_DIR),
    )


def render_atomic_login(
    *,
    key: str,
    disabled: bool = False,
    submit_label: str = "Login",
) -> Any:
    """Render Login and return one atomic submit payload, or None.

    The component never writes credentials to browser storage, query params,
    logs, or Python session state. Its value is consumed immediately by
    src.auth; only the non-sensitive request id is retained for replay
    protection.
    """
    try:
        component = _declared_component()
    except (ImportError, AttributeError):
        # Unit-test Streamlit stubs do not expose the components package.
        return None
    label = str(submit_label or "Login").strip() or "Login"
    return component(
        disabled=bool(disabled),
        submit_label=label,
        default=None,
        key=key,
    )
