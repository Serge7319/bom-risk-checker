#!/usr/bin/env python3
"""Zero-credit full-path Ask Cadivor harness — Sprint 72.3 native renderer.

Calls render_engineering_assistant() with a completed PC817 session state.
EngineeringAI is never invoked.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


def install_full_path_streamlit_stub(*, session_state: dict | None = None):
    return install_ask_cadivor_streamlit_stub(session_state=session_state, script_run_id="full-path-run")


def run_full_path_harness() -> tuple[types.ModuleType, list[tuple[str, dict, str | None]], list[str]]:
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.ui.cadivor_design_system"):
            sys.modules.pop(mod_name, None)
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(mod_name, None)
    st = install_full_path_streamlit_stub(
        session_state={
            "cv35_last_answer": PC817_ANSWER,
            "cv35_last_question": PC817_QUESTION,
            "cv35_provider_connected": True,
            "cv35_question": "",
            "cadivor_active_analysis_tab": "Ask Cadivor",
        }
    )
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    context = MagicMock()
    context.compact.return_value = PC817_CONTEXT

    class _BlockedAI:
        ask_calls = 0

        def __init__(self, **kwargs):
            pass

        def ask(self, **kwargs):
            _BlockedAI.ask_calls += 1
            raise AssertionError("EngineeringAI.ask must not be called in full-path harness")

    _BlockedAI.ask_calls = 0
    usage = MagicMock(
        is_admin=False,
        remaining=100,
        allowance=200,
        warning_level="normal",
        can_use=True,
        percent_used=10,
    )

    with patch.object(assistant, "EngineeringAI", _BlockedAI):
        with patch.object(assistant, "get_ai_usage_status", return_value=usage):
            with patch.object(assistant, "get_thread", return_value=[]):
                with patch.object(assistant, "_render_response_scroll_anchor"):
                    with patch.object(assistant, "_apply_copilot_query_picks"):
                        assistant.render_engineering_assistant(
                            current_user={"id": "harness-user"},
                            engineering_context=context,
                        )

    st._blocked_ai_calls = _BlockedAI.ask_calls  # type: ignore[attr-defined]
    return st, st.markdown_calls, st.html_calls


def main() -> int:
    st, markdown_calls, _html_calls = run_full_path_harness()
    html = "\n".join(content for content, _kwargs, _side in markdown_calls)
    left = "\n".join(content for content, _kwargs, side in markdown_calls if side == "left")
    right = "\n".join(content for content, _kwargs, side in markdown_calls if side == "right")
    checks = {
        "columns_ratio": any(call[0] == [0.85, 1.15] for call in st.columns_calls),
        "conversation_exchange_html": "cv50-exchange" in html,
        "direct_answer_present": "Review PC817 first." in left,
        "three_reason_rows": html.count("cv722-reason-row") >= 3,
        "three_action_rows": html.count("cv722-action-row") >= 3,
        "three_evidence_cards": html.count("cv46-evidence-card") >= 3,
        "decision_summary_strip": len(re.findall(r'class="cv722-summary-item', html)) == 3,
        "impact_grid_four_cells": html.count("cv724-impact-cell") == 4,
        "followups_after_columns": (
            "columns_created" in st.render_sequence
            and (
                st.render_sequence.index("columns_created")
                < st.render_sequence.index("reason_card")
                if "reason_card" in st.render_sequence
                else True
            )
        ),
        "self_contained_block_surfaces": "cv722-concise-answer" in html and "cv727-assessment-panel" in html,
        "no_details_wrapper": "<details" not in html.lower(),
        "no_openai_calls": st._blocked_ai_calls == 0,
        "no_fake_shell_wrapper": "<div class=\"cv-assistant-shell\">" not in html,
        "review_pc817_present": "Review PC817 first." in html,
        "evidence_components_present": all(part in html for part in ("PC817", "BZX55C5V1", "DRV8825")),
        "no_concatenated_component_status": all(
            token not in html for token in ("PC817Review", "BZX55C5V1Review", "DRV8825Review")
        ),
        "no_keyed_container_calls_in_source": "st.container(key=" not in (
            REPO_ROOT / "src/components/engineering_assistant.py"
        ).read_text(encoding="utf-8"),
    }

    print("=== Ask Cadivor full-path harness (native renderer) ===")
    failed = False
    for name, ok in checks.items():
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        failed = failed or not ok
    print()
    restore_ask_cadivor_streamlit_modules()
    if failed:
        print("Harness: FAILED")
        return 1
    print("Harness: PASS (zero OpenAI credits consumed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
