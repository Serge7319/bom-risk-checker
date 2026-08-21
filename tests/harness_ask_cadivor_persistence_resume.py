#!/usr/bin/env python3
"""Sprint 72.4 — Two-session Ask Cadivor persistence/resume harness.

SESSION A:
  queue question -> execute AI stub once -> response committed -> durable write

Destroy session_state (fresh Streamlit session).

SESSION B:
  same user + analysis_id -> render Ask Cadivor -> restore persisted exchange
  without calling AI.
"""
from __future__ import annotations

import io
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.copilot_conversation_store_stub import InMemoryCopilotStore
from tests.harness_ask_cadivor_three_run import StatefulStreamlitRun, _load_assistant


QUESTION = "What should I review first in this BOM?"
ANSWER = (
    "### Engineering Assessment\n"
    "Review PC817 first because it drives the highest lifecycle exposure.\n"
    "### Follow-up questions\n"
    "- Why is PC817 ranked first?\n"
)
ANALYSIS_A = "harness-a1"
ANALYSIS_B = "harness-a2"
USER_A = "harness-user-a"
USER_B = "harness-user-b"
WORKSPACE = "harness-workspace"


def _engineering_context(*, analysis_id: str) -> MagicMock:
    context = MagicMock()
    context.compact.return_value = {
        "analysis": {
            "analysis_id": analysis_id,
            "workspace_id": WORKSPACE,
        },
        "analysis_id": analysis_id,
        "workspace_id": WORKSPACE,
        "summary": {"health_score": 93, "total_parts": 12, "release_posture": "Engineering review"},
        "components": [{"part_number": "PC817", "risk_score": 40}],
        "coverage": {"score": 56},
        "decisions": [],
    }
    return context


def _usage_status():
    return types.SimpleNamespace(
        is_admin=False,
        remaining=100,
        allowance=200,
        warning_level="normal",
        can_use=True,
        percent_used=10,
    )


class _RecordingAI:
    ask_calls = 0

    configured = True

    def __init__(self, **kwargs):
        pass

    def ask(self, **kwargs):
        _RecordingAI.ask_calls += 1
        return types.SimpleNamespace(answer=ANSWER, provider="openai")


def _render_assistant(
    *,
    session_state: dict,
    store: InMemoryCopilotStore,
    analysis_id: str,
    user_id: str,
) -> tuple[list[str], int]:
    run = StatefulStreamlitRun(session_state=session_state)
    assistant = _load_assistant()
    run.bind_assistant(assistant)
    _RecordingAI.ask_calls = 0
    log_buffer = io.StringIO()
    with redirect_stdout(log_buffer):
        with patch.object(assistant, "_copilot_supabase_client", return_value=store):
            with patch.object(assistant, "EngineeringAI", _RecordingAI):
                with patch.object(assistant, "get_ai_usage_status", return_value=_usage_status()):
                    with patch.object(assistant, "_render_response_scroll_anchor"):
                        with patch.object(assistant, "_apply_copilot_query_picks"):
                            with patch.object(assistant.components, "html", MagicMock()):
                                assistant.render_engineering_assistant(
                                    current_user={"id": user_id},
                                    engineering_context=_engineering_context(analysis_id=analysis_id),
                                )
    return log_buffer.getvalue().splitlines(), _RecordingAI.ask_calls


def main() -> int:
    store = InMemoryCopilotStore()
    session_a: dict = {
        "cv41_pending_manual": QUESTION,
        "cv7142_ask_inflight": True,
        "cv35_question": QUESTION,
        "cadivor_active_analysis_tab": "Ask Cadivor",
        f"cadivor_analysis_section_{ANALYSIS_A}": "Ask Cadivor",
        "cadivor_active_analysis_id": ANALYSIS_A,
        "analysis_id": ANALYSIS_A,
        "active_workspace_id": WORKSPACE,
    }

    logs_a, ai_a = _render_assistant(
        session_state=session_a,
        store=store,
        analysis_id=ANALYSIS_A,
        user_id=USER_A,
    )
    persisted = store.rows.get((USER_A, ANALYSIS_A), {}).get("thread") or []
    session_b: dict = {
        "cadivor_active_analysis_tab": "Ask Cadivor",
        f"cadivor_analysis_section_{ANALYSIS_A}": "Ask Cadivor",
        "cadivor_active_analysis_id": ANALYSIS_A,
        "analysis_id": ANALYSIS_A,
        "active_workspace_id": WORKSPACE,
    }
    logs_b, ai_b = _render_assistant(
        session_state=session_b,
        store=store,
        analysis_id=ANALYSIS_A,
        user_id=USER_A,
    )

    session_other_analysis: dict = {
        "cadivor_active_analysis_tab": "Ask Cadivor",
        f"cadivor_analysis_section_{ANALYSIS_B}": "Ask Cadivor",
        "cadivor_active_analysis_id": ANALYSIS_B,
        "analysis_id": ANALYSIS_B,
        "active_workspace_id": WORKSPACE,
    }
    _, ai_other_analysis = _render_assistant(
        session_state=session_other_analysis,
        store=store,
        analysis_id=ANALYSIS_B,
        user_id=USER_A,
    )

    session_other_user: dict = {
        "cadivor_active_analysis_tab": "Ask Cadivor",
        f"cadivor_analysis_section_{ANALYSIS_A}": "Ask Cadivor",
        "cadivor_active_analysis_id": ANALYSIS_A,
        "analysis_id": ANALYSIS_A,
        "active_workspace_id": WORKSPACE,
    }
    _, ai_other_user = _render_assistant(
        session_state=session_other_user,
        store=store,
        analysis_id=ANALYSIS_A,
        user_id=USER_B,
    )

    combined_a = "\n".join(logs_a)
    combined_b = "\n".join(logs_b)
    checks = {
        "session_a_response_committed": "ASK_CADIVOR response_committed" in combined_a,
        "session_a_persisted_question": any(
            str(turn.get("question") or "") == QUESTION for turn in persisted
        ),
        "session_a_persisted_answer": any(
            str(turn.get("answer") or "").startswith("### Engineering Assessment")
            for turn in persisted
        ),
        "session_a_ai_calls_1": ai_a == 1,
        "session_b_ai_calls_0": ai_b == 0,
        "session_b_answer_restored": bool(str(session_b.get("cv35_last_answer") or "").strip()),
        "session_b_question_restored": str(session_b.get("cv35_last_question") or "") == QUESTION,
        "session_b_response_rendered": "ASK_RENDER response_entered" in combined_b,
        "session_b_no_execution_started": "ASK_CADIVOR execution_started" not in combined_b,
        "cross_analysis_isolated": ai_other_analysis == 0
        and not str(session_other_analysis.get("cv35_last_answer") or "").strip(),
        "cross_user_isolated": ai_other_user == 0
        and not str(session_other_user.get("cv35_last_answer") or "").strip(),
        "total_ai_calls_1": ai_a + ai_b + ai_other_analysis + ai_other_user == 1,
    }

    print("=== Ask Cadivor two-session persistence harness ===")
    failed = False
    for name, ok in checks.items():
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        failed = failed or not ok
    print()
    print(f"Session A AI stub calls: {ai_a}")
    print(f"Session B AI stub calls: {ai_b}")
    print(f"Total AI stub calls: {ai_a + ai_b + ai_other_analysis + ai_other_user}")
    if failed:
        print("Harness: FAILED")
        return 1
    print("Harness: PASS (zero real OpenAI credits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
