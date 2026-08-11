"""Cadivor Design System v2 — shared token + primitive foundation loader (Sprint 72.1)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_DS_V2_STYLE_ID = "cadivor-design-system-v2"
_DS_V2_RUN_KEY = "_cadivor_design_system_v2_run_id"
_DS_V2_CSS_FILENAME = "cadivor_design_system_v2.css"
_ASK_CADIVOR_V2_STYLE_ID = "cadivor-ask-cadivor-v2-css"
_ASK_CADIVOR_V2_RUN_KEY = "_cadivor_ask_cadivor_v2_run_id"
_ASK_CADIVOR_V2_CSS_FILENAME = "ask_cadivor_v2.css"


def _css_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "css" / _DS_V2_CSS_FILENAME


def _ask_cadivor_v2_css_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "css" / _ASK_CADIVOR_V2_CSS_FILENAME


def _current_script_run_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is None:
            return "__no_ctx__"
        run_id = getattr(ctx, "script_run_id", None)
        return str(run_id) if run_id is not None else str(id(ctx))
    except Exception:
        return "__unknown__"


def load_cadivor_design_system_v2_css() -> str:
    """Read DS v2 CSS from disk. Raises OSError when the foundation file is missing."""
    path = _css_path()
    if not path.is_file():
        raise OSError(f"Cadivor Design System v2 CSS not found: {path}")
    return path.read_text(encoding="utf-8")


def inject_cadivor_design_system_v2(*, force: bool = False) -> bool:
    """Inject the authoritative DS v2 stylesheet once per script run.

    Returns True when CSS was injected on this call, False when skipped as duplicate
    within the same script execution. Each Streamlit rerun emits DS v2 again.
    Has no auth, routing, or business-logic side effects.
    """
    run_id = _current_script_run_id()
    if not force and st.session_state.get(_DS_V2_RUN_KEY) == run_id:
        return False

    css = load_cadivor_design_system_v2_css()
    if not css.strip():
        st.error("Cadivor Design System v2 failed to load: stylesheet is empty.")
        return False

    st.markdown(
        f"<style id='{_DS_V2_STYLE_ID}'>{css}</style>",
        unsafe_allow_html=True,
    )
    st.session_state[_DS_V2_RUN_KEY] = run_id
    return True


def load_ask_cadivor_v2_css() -> str:
    """Read Ask Cadivor presentation CSS from disk."""
    path = _ask_cadivor_v2_css_path()
    if not path.is_file():
        raise OSError(f"Ask Cadivor v2 CSS not found: {path}")
    return path.read_text(encoding="utf-8")


def inject_ask_cadivor_v2_css(*, force: bool = False) -> bool:
    """Inject Ask Cadivor presentation CSS once per script run via the app shell.

    Uses the same st.markdown(<style>) path as premium.css and DS v2. Loaded at
    authenticated app initialization — not from the response renderer.
    """
    run_id = _current_script_run_id()
    if not force and st.session_state.get(_ASK_CADIVOR_V2_RUN_KEY) == run_id:
        return False

    css = load_ask_cadivor_v2_css()
    if not css.strip():
        return False

    st.markdown(
        f"<style id='{_ASK_CADIVOR_V2_STYLE_ID}'>{css}</style>",
        unsafe_allow_html=True,
    )
    st.session_state[_ASK_CADIVOR_V2_RUN_KEY] = run_id
    print(
        f"ASK_RENDER stylesheet_injected style_id={_ASK_CADIVOR_V2_STYLE_ID} via=global_app_shell",
        flush=True,
    )
    return True
