#!/usr/bin/env python3
"""Zero-credit full-path Ask Cadivor harness — Sprint 72.2.7.

Calls render_engineering_assistant() with a completed PC817 session state.
EngineeringAI is never invoked.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RecordingColumn:
    def __init__(self, side: str, st_module: types.ModuleType) -> None:
        self._side = side
        self._st = st_module

    def __enter__(self):
        self._st._active_column = self._side
        self._st.render_sequence.append(f"column_{self._side}_enter")
        return self

    def __exit__(self, *args):
        self._st._active_column = None
        return False


def install_full_path_streamlit_stub(*, session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = dict(session_state or {})
    st._active_column = None
    st.render_sequence: list[str] = []
    st.columns_calls: list[tuple[list[float], str | None]] = []
    st.container_calls: list[str] = []
    markdown_calls: list[tuple[str, dict]] = []
    html_calls: list[str] = []

    def _markdown(content, **kwargs):
        text = str(content)
        markdown_calls.append((text, dict(kwargs)))
        side = st._active_column or "root"
        st.render_sequence.append(f"markdown_{side}")
        if "cv50-exchange" in text:
            st.render_sequence.append("conversation_exchange")
        if "cv722-concise-answer" in text or "cv49-answer-card" in text:
            st.render_sequence.append("left_answer_card")
        if "cv722-summary-strip" in text:
            st.render_sequence.append("left_kpi_strip")
        if "cv727-assessment-panel" in text:
            st.render_sequence.append("right_assessment_panel")

    def _html(content, **kwargs):
        text = str(content)
        html_calls.append(text)
        if "<style" in text.lower():
            st.render_sequence.append("stylesheet_injection")

    def _columns(spec, gap=None):
        if isinstance(spec, (list, tuple)):
            ratio = list(spec)
        else:
            ratio = [1] * int(spec)
        st.columns_calls.append((ratio, gap))
        st.render_sequence.append("columns_created")
        if ratio == [0.85, 1.15]:
            return [_RecordingColumn("left", st), _RecordingColumn("right", st)]
        return [MagicMock() for _ in ratio]

    def _container(**kwargs):
        key = str(kwargs.get("key") or "")
        if key:
            st.container_calls.append(key)
            st.render_sequence.append(f"container_{key}")
        return _NullContext()

    st.markdown = _markdown
    st.html = _html
    st.columns = _columns
    st.container = _container
    st.expander = lambda *args, **kwargs: _NullContext()
    st.form = lambda *args, **kwargs: _NullContext()
    st.text_area = MagicMock(return_value="")
    st.caption = MagicMock()
    st.form_submit_button = MagicMock(return_value=False)
    st.button = MagicMock(return_value=False)
    st.info = MagicMock()
    st.warning = MagicMock()
    st.success = MagicMock()
    st.status = lambda *args, **kwargs: _NullContext()
    st.link_button = MagicMock()

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(script_run_id="full-path-run")
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    components.html = lambda content, **kwargs: html_calls.append(str(content))

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components

    import src.ui.navigation as navigation

    navigation.st = st
    return st, markdown_calls, html_calls


def run_full_path_harness() -> tuple[types.ModuleType, list[tuple[str, dict]], list[str]]:
    st, markdown_calls, html_calls = install_full_path_streamlit_stub(
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
    return st, markdown_calls, html_calls


def main() -> int:
    st, markdown_calls, _html_calls = run_full_path_harness()
    html = "\n".join(content for content, _kwargs in markdown_calls)
    checks = {
        "columns_ratio": any(call[0] == [0.85, 1.15] for call in st.columns_calls),
        "decision_workspace_container": "cv727_decision_workspace" in st.container_calls,
        "conversation_exchange": "conversation_exchange" in st.render_sequence,
        "left_answer_card": "left_answer_card" in st.render_sequence,
        "left_kpi_strip": "left_kpi_strip" in st.render_sequence,
        "right_assessment_panel": "right_assessment_panel" in st.render_sequence,
        "followups_after_columns": (
            "columns_created" in st.render_sequence
            and st.render_sequence.index("columns_created")
            < st.render_sequence.index("container_cv725_followups")
            if "container_cv725_followups" in st.render_sequence
            else "columns_created" in st.render_sequence
        ),
        "no_giant_cv725_grid": "cv725-decision-workspace" not in html,
        "no_details_wrapper": "<details" not in html.lower(),
        "no_openai_calls": st._blocked_ai_calls == 0,
        "no_fake_shell_wrapper": "<div class=\"cv-assistant-shell\">" not in html,
        "review_pc817_present": "Review PC817 first." in html,
        "evidence_separated": "cv46-evidence-component" in html,
    }

    print("=== Ask Cadivor full-path harness (render_engineering_assistant) ===")
    failed = False
    for name, ok in checks.items():
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        failed = failed or not ok
    print()
    if failed:
        print("Harness: FAILED")
        return 1
    print("Harness: PASS (zero OpenAI credits consumed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
