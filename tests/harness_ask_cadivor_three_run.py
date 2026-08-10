#!/usr/bin/env python3
"""Sprint 72.2.8.1 — Stateful three-run Ask Cadivor suggestion harness.

Models production Streamlit behavior across separate script runs with one
shared session_state object:

RUN 1 — suggestion click → queue → rerun requested (no AI)
RUN 2 — auth restore → tab restore → pending consumed → AI once → render
RUN 3 — idle rerun → answer persists, no second AI call
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


class _StatusContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def update(self, **kwargs):
        return None


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
        return self

    def __exit__(self, *args):
        self._st._active_column = None
        return False

    def columns(self, spec, gap=None):
        count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [MagicMock() for _ in range(count)]


class StatefulStreamlitRun:
    """One script run with shared session_state persisted across reruns."""

    run_id: int = 0

    def __init__(self, *, session_state: dict, query_params: dict | None = None) -> None:
        StatefulStreamlitRun.run_id += 1
        self.id = StatefulStreamlitRun.run_id
        self.session_state = session_state
        self.query_params = dict(query_params or {})
        self.markdown_calls: list[tuple[str, dict]] = []
        self.button_clicks: dict[str, bool] = {}
        self.st = self._build_st()

    def _build_st(self) -> types.ModuleType:
        st = types.ModuleType("streamlit")
        st.session_state = self.session_state
        st.query_params = self.query_params
        st._active_column = None
        st.rerun_calls = 0
        run = self

        def _markdown(content, **kwargs):
            run.markdown_calls.append((str(content), dict(kwargs)))

        def _rerun():
            st.rerun_calls += 1
            raise RuntimeError("rerun")

        def _columns(spec, gap=None):
            count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
            return [_RecordingColumn("left" if i == 0 else "right", st) for i in range(count)]

        def _button(label, key=None, **kwargs):
            return bool(run.button_clicks.get(str(key), False))

        st.markdown = _markdown
        st.html = MagicMock()
        st.rerun = _rerun
        st.columns = _columns
        st.container = lambda **kwargs: _NullContext()
        st.form = lambda *args, **kwargs: _NullContext()
        st.text_area = MagicMock(
            side_effect=lambda label, key, **kwargs: st.session_state.get(key, "")
        )
        st.caption = MagicMock()
        st.form_submit_button = MagicMock(return_value=False)
        st.button = _button
        st.info = MagicMock()
        st.warning = MagicMock()
        st.success = MagicMock()
        st.status = lambda *args, **kwargs: _StatusContext()
        st.link_button = MagicMock()
        st.radio = lambda *args, **kwargs: st.session_state.get(
            kwargs.get("key"), args[1][0] if len(args) > 1 else ""
        )

        scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
        scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(
            script_run_id=f"three-run-{run.id}"
        )
        runtime = types.ModuleType("streamlit.runtime")
        runtime.scriptrunner = scriptrunner
        components = types.ModuleType("streamlit.components.v1")
        components.html = MagicMock()

        sys.modules["streamlit"] = st
        sys.modules["streamlit.runtime"] = runtime
        sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
        sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
        sys.modules["streamlit.components.v1"] = components

        import src.ui.navigation as navigation

        navigation.st = st
        return st

    def bind_assistant(self, assistant) -> None:
        assistant.st = self.st


def simulate_auth_restore(session_state: dict) -> list[str]:
    """Mirror auth_bootstrap copilot snapshot restore without heavy imports."""
    log_buffer = io.StringIO()
    lines: list[str] = []

    def _emit(event: str, **details):
        parts = [f"ASK_CADIVOR {event}"] + [f"{k}={v}" for k, v in details.items()]
        line = " ".join(parts)
        lines.append(line)
        print(line, flush=True)

    _emit("script_run_auth_restore")
    copilot_snapshot = session_state.get("cv48_copilot_snapshot") or {}
    copilot_inflight = bool(session_state.get("cv4801_followup_inflight"))
    if not copilot_inflight or not isinstance(copilot_snapshot, dict) or not copilot_snapshot:
        _emit(
            "auth_restore",
            restored=False,
            inflight=copilot_inflight,
            snapshot_keys=len(copilot_snapshot) if isinstance(copilot_snapshot, dict) else 0,
        )
        return lines

    restored_keys: list[str] = []
    for key, value in copilot_snapshot.items():
        if not key or value is None:
            continue
        if session_state.get(key) is None:
            session_state[key] = value
            restored_keys.append(str(key))
    _emit(
        "auth_restore",
        restored=bool(restored_keys),
        inflight=copilot_inflight,
        snapshot_keys=len(copilot_snapshot),
        restored_keys=",".join(restored_keys) if restored_keys else "",
    )
    return lines


def simulate_analysis_tab_restore(session_state: dict, *, analysis_id: str) -> str:
    st = types.ModuleType("streamlit")
    st.session_state = session_state
    st.query_params = {}
    sys.modules["streamlit"] = st

    for name in list(sys.modules):
        if name == "src.pages.analysis_detail":
            sys.modules.pop(name, None)

    from tests.test_analysis_section_navigation import _install_analysis_detail_import_stubs

    _install_analysis_detail_import_stubs()
    import src.pages.analysis_detail as detail

    detail.st = st
    detail._consume_pending_analysis_section(analysis_id=analysis_id)
    nav_key = detail._analysis_section_nav_key(analysis_id)
    if nav_key not in st.session_state:
        st.session_state[nav_key] = st.session_state.get("cadivor_active_analysis_tab", "Ask Cadivor")
    return str(st.session_state.get("cadivor_active_analysis_tab") or "")


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


def _blocked_ai_factory():
    class _BlockedAI:
        configured = True
        ask_calls = 0

        def __init__(self, **kwargs):
            pass

        def ask(self, **kwargs):
            _BlockedAI.ask_calls += 1
            return types.SimpleNamespace(answer="Review PC817 first.", provider="openai")

    _BlockedAI.ask_calls = 0
    return _BlockedAI


def run_assistant_render(*, assistant, run: StatefulStreamlitRun, analysis_id: str = "harness-a1") -> tuple[list[str], int]:
    log_buffer = io.StringIO()
    run.bind_assistant(assistant)
    ai_cls = _blocked_ai_factory()
    usage = types.SimpleNamespace(
        is_admin=False,
        remaining=100,
        allowance=200,
        warning_level="normal",
        can_use=True,
        percent_used=10,
    )
    context = MagicMock()
    context.compact.return_value = {
        "analysis": {"analysis_id": analysis_id},
        "analysis_id": analysis_id,
        "summary": {"health_score": 93},
        "components": [{"part_number": "PC817", "risk_score": 40}],
        "coverage": {"score": 56},
    }

    with redirect_stdout(log_buffer):
        with patch.object(assistant, "EngineeringAI", ai_cls):
            with patch.object(assistant, "get_ai_usage_status", return_value=usage):
                with patch.object(assistant, "get_thread", return_value=[]):
                    with patch.object(assistant, "_render_response_scroll_anchor"):
                        with patch.object(assistant, "_apply_copilot_query_picks"):
                            with patch.object(assistant.components, "html", MagicMock()):
                                assistant.render_engineering_assistant(
                                    current_user={"id": "harness-user"},
                                    engineering_context=context,
                                )
    return log_buffer.getvalue().splitlines(), ai_cls.ask_calls


def main() -> int:
    StatefulStreamlitRun.run_id = 0
    analysis_id = "harness-a1"
    suggestion = "What should I review first in this BOM?"
    session_state: dict = {
        "cv35_question": "",
        "cadivor_active_analysis_tab": "Ask Cadivor",
        f"cadivor_analysis_section_{analysis_id}": "Ask Cadivor",
        "cadivor_active_analysis_id": analysis_id,
        "analysis_id": analysis_id,
    }

    assistant = _load_assistant()
    all_logs: list[str] = []

    # RUN 1 — suggestion click (queue only, no render execution path)
    run1 = StatefulStreamlitRun(session_state=session_state)
    run1.bind_assistant(assistant)
    log_buffer = io.StringIO()
    with redirect_stdout(log_buffer):
        try:
            assistant._select_initial_suggestion(
                suggestion,
                index=0,
                prompt_key="cv35_question",
                analysis_id=analysis_id,
            )
        except RuntimeError as exc:
            if "rerun" not in str(exc):
                raise
    run1_logs = log_buffer.getvalue().splitlines()
    all_logs.extend(run1_logs)

    run1_pending = session_state.get("cv41_pending_manual")
    run1_snapshot = session_state.get("cv48_copilot_snapshot")
    run1_inflight = session_state.get("cv7142_ask_inflight")

    # RUN 2 — post-rerun restoration + execution
    auth_logs = simulate_auth_restore(session_state)
    all_logs.extend(auth_logs)
    active_tab = simulate_analysis_tab_restore(session_state, analysis_id=analysis_id)
    run2 = StatefulStreamlitRun(session_state=session_state)
    run2_logs, ask_calls_run2 = run_assistant_render(
        assistant=assistant, run=run2, analysis_id=analysis_id
    )
    all_logs.extend(run2_logs)

    # RUN 3 — idle rerun
    run3 = StatefulStreamlitRun(session_state=session_state)
    run3_logs, ask_calls_run3 = run_assistant_render(
        assistant=assistant, run=run3, analysis_id=analysis_id
    )
    all_logs.extend(run3_logs)

    combined = "\n".join(all_logs)
    checks = {
        "run1_suggestion_clicked": "ASK_CADIVOR suggestion_clicked" in combined,
        "run1_question_queued": "ASK_CADIVOR question_queued" in combined,
        "run1_rerun_requested": "ASK_CADIVOR rerun_requested" in combined,
        "run1_pending_survives": run1_pending == suggestion,
        "run1_snapshot_armed": isinstance(run1_snapshot, dict) and bool(run1_snapshot),
        "run1_inflight_set": bool(run1_inflight),
        "run2_auth_restore_ran": "ASK_CADIVOR script_run_auth_restore" in combined,
        "run2_tab_is_ask_cadivor": active_tab == "Ask Cadivor",
        "run2_queued_question_detected": "ASK_CADIVOR queued_question_detected" in combined,
        "run2_execution_started": "ASK_CADIVOR execution_started" in combined,
        "run2_response_committed": "ASK_CADIVOR response_committed" in combined,
        "run2_response_entered": "ASK_RENDER response_entered" in combined,
        "run2_answer_before_render": "ASK_CADIVOR last_answer_present_before_render present=True" in combined,
        "run2_single_ai_call": ask_calls_run2 == 1,
        "run3_no_second_ai_call": ask_calls_run3 == 0,
        "run3_answer_persisted": bool(str(session_state.get("cv35_last_answer") or "").strip()),
        "run3_pending_absent": "cv41_pending_manual" not in session_state,
        "run3_inflight_false": not session_state.get("cv7142_ask_inflight"),
        "run1_no_ai_call": "ASK_CADIVOR execution_started" not in "\n".join(run1_logs),
    }

    print("=== Ask Cadivor three-run stateful harness ===")
    failed = False
    for name, ok in checks.items():
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        failed = failed or not ok
    print()
    if failed:
        print("Harness: FAILED")
        return 1
    print("Harness: PASS (zero real OpenAI credits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
