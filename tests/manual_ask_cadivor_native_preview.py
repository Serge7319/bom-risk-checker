#!/usr/bin/env python3
"""Manual zero-credit Streamlit preview for Ask Cadivor native UI — Sprint 72.3.

Launch:
    streamlit run tests/manual_ask_cadivor_native_preview.py

Uses the production native renderer with static PC817 data.
Does not initialize EngineeringAI or make network calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import streamlit as st

from src.ui.design_system_v1 import inject_design_system_v1
from src.ui.framework import inject_premium_css
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


def main() -> None:
    st.set_page_config(page_title="Ask Cadivor Native Preview", layout="wide")
    inject_premium_css()
    inject_design_system_v1()

    st.title("Ask Cadivor Native UI Preview")
    st.caption("Sprint 72.3 — zero-credit PC817 scenario using the production native Streamlit renderer.")

    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    with patch.object(assistant, "_render_response_scroll_anchor"):
        with patch.object(assistant, "_render_quick_actions"):
            assistant._render_response(
                question=PC817_QUESTION,
                answer=PC817_ANSWER,
                context=PC817_CONTEXT,
            )


if __name__ == "__main__":
    main()
