#!/usr/bin/env python3
"""Zero-credit first-click suggestion harness — Sprint 72.2.8.

Simulates: suggestion button -> queue -> rerun -> execute -> render.
EngineeringAI is never invoked on the click run.
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


def install_first_click_streamlit_stub(*, session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = dict(session_state or {})
    st._active_column = None
    st.rerun_calls = 0
    st.render_runs: list[str] = []
    markdown_calls: list[tuple[str, dict]] = []

    def _markdown(content, **kwargs):
        markdown_calls.append((str(content), dict(kwargs)))

    def _rerun():
        st.rerun_calls += 1
        raise RuntimeError("rerun")

    def _columns(spec, gap=None):
        count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [_RecordingColumn("left" if i == 0 else "right", st) for i in range(count)]

    st.markdown = _markdown
    st.html = MagicMock()
    st.rerun = _rerun
    st.columns = _columns
    st.container = lambda **kwargs: _NullContext()
    st.form = lambda *args, **kwargs: _NullContext()
    st.text_area = MagicMock(side_effect=lambda label, key, **kwargs: st.session_state.get(key, ""))
    st.caption = MagicMock()
    st.form_submit_button = MagicMock(return_value=False)
    st.button = MagicMock(return_value=False)
    st.info = MagicMock()
    st.warning = MagicMock()
    st.success = MagicMock()
    st.status = lambda *args, **kwargs: _StatusContext()
    st.link_button = MagicMock()

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(script_run_id="first-click-run")
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
    return st, markdown_calls


def _install_assistant_import_stubs() -> None:
    secrets = types.ModuleType("src.secrets")
    secrets.get_secret = lambda key, default="": default
    sys.modules["src.secrets"] = secrets

    auth_state = types.ModuleType("src.auth_state")
    auth_state.log_auth_diagnostic = lambda *args, **kwargs: None
    sys.modules["src.auth_state"] = auth_state

    urls = types.ModuleType("src.urls")
    urls.internal_app_href = lambda *args, **kwargs: "?"
    sys.modules["src.urls"] = urls

    navigation = types.ModuleType("src.ui.navigation")
    navigation.alternative_finder_href = lambda *a, **k: "?"
    navigation.internal_nav_button = MagicMock()
    navigation.ALTERNATIVE_FINDER_PAGE = "Alternative Finder"
    sys.modules["src.ui.navigation"] = navigation

    ai_entitlements = types.ModuleType("src.services.ai_entitlements")
    ai_entitlements.get_ai_usage_status = MagicMock(
        return_value=types.SimpleNamespace(
            can_use=True,
            remaining=10,
            allowance=10,
            warning_level="normal",
            is_admin=False,
        )
    )
    ai_entitlements.consume_ai_credits = MagicMock()
    sys.modules["src.services.ai_entitlements"] = ai_entitlements

    copilot = types.ModuleType("src.services.copilot_conversation")
    copilot.append_turn = MagicMock(return_value=[])
    copilot.clear_thread = MagicMock()
    copilot.compact_history = MagicMock(return_value=[])
    copilot.follow_up_suggestions = MagicMock(return_value=[])
    copilot.get_thread = MagicMock(return_value=[])
    sys.modules["src.services.copilot_conversation"] = copilot

    engineering_ai = types.ModuleType("src.services.engineering_ai")

    class _Error(RuntimeError):
        def __init__(self, message="", code=""):
            super().__init__(message)
            self.code = code

    engineering_ai.EngineeringAIError = _Error
    engineering_ai.log_ai_config = lambda api: None
    sys.modules["src.services.engineering_ai"] = engineering_ai


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


def simulate_suggestion_click_run(*, assistant, analysis_id: str = "harness-a1") -> list[str]:
    log_buffer = io.StringIO()
    with redirect_stdout(log_buffer):
        try:
            assistant._select_initial_suggestion(
                assistant.SUGGESTIONS[0],
                index=0,
                prompt_key="cv35_question",
                analysis_id=analysis_id,
            )
        except RuntimeError as exc:
            if "rerun" not in str(exc):
                raise
    return log_buffer.getvalue().splitlines()


def simulate_post_rerun_execution(*, assistant, markdown_calls: list) -> tuple[list[str], int]:
    log_buffer = io.StringIO()
    suggestion = assistant.SUGGESTIONS[0]
    st, _markdown_calls = install_first_click_streamlit_stub(
        session_state={
            "cv41_pending_manual": suggestion,
            "cv7142_ask_inflight": True,
            "cv35_question": suggestion,
            "cadivor_active_analysis_tab": "Ask Cadivor",
        }
    )
    assistant.st = st
    import src.ui.navigation as navigation

    navigation.st = st

    class _BlockedAI:
        configured = True
        ask_calls = 0

        def __init__(self, **kwargs):
            pass

        def ask(self, **kwargs):
            _BlockedAI.ask_calls += 1
            return types.SimpleNamespace(answer="Review PC817 first.", provider="openai")

    _BlockedAI.ask_calls = 0
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
        "analysis": {"analysis_id": "harness-a1"},
        "summary": {"health_score": 93},
        "components": [{"part_number": "PC817", "risk_score": 40}],
        "coverage": {"score": 56},
    }

    with redirect_stdout(log_buffer):
        with patch.object(assistant, "EngineeringAI", _BlockedAI):
            with patch.object(assistant, "get_ai_usage_status", return_value=usage):
                with patch.object(assistant, "get_thread", return_value=[]):
                    with patch.object(assistant, "_render_response_scroll_anchor"):
                        with patch.object(assistant, "_apply_copilot_query_picks"):
                            assistant.render_engineering_assistant(
                                current_user={"id": "harness-user"},
                                engineering_context=context,
                            )
    return log_buffer.getvalue().splitlines(), _BlockedAI.ask_calls


def main() -> int:
    install_first_click_streamlit_stub(
        session_state={
            "cv35_question": "",
            "cadivor_active_analysis_tab": "Ask Cadivor",
        }
    )
    assistant = _load_assistant()
    click_logs = simulate_suggestion_click_run(assistant=assistant)
    exec_logs, ask_calls = simulate_post_rerun_execution(assistant=assistant, markdown_calls=[])

    all_logs = "\n".join(click_logs + exec_logs)
    checks = {
        "suggestion_clicked": "ASK_CADIVOR suggestion_clicked" in all_logs,
        "question_queued": "ASK_CADIVOR question_queued" in all_logs,
        "rerun_requested": "ASK_CADIVOR rerun_requested" in all_logs,
        "queued_question_detected": "ASK_CADIVOR queued_question_detected" in all_logs,
        "execution_started": "ASK_CADIVOR execution_started" in all_logs,
        "execution_completed": "ASK_CADIVOR execution_completed" in all_logs,
        "response_committed": "ASK_CADIVOR response_committed" in all_logs,
        "response_entered": "ASK_RENDER response_entered" in all_logs,
        "workspace_columns_requested": "ASK_RENDER workspace_columns_requested" in all_logs,
        "workspace_left_column_entered": "ASK_RENDER workspace_left_column_entered" in all_logs,
        "workspace_right_column_entered": "ASK_RENDER workspace_right_column_entered" in all_logs,
        "followups_rendered": "ASK_RENDER followups_rendered" in all_logs,
        "single_openai_call_on_post_rerun": ask_calls == 1,
        "no_openai_on_click_run": "execution_started" not in "\n".join(click_logs),
    }

    print("=== Ask Cadivor first-click harness ===")
    failed = False
    for name, ok in checks.items():
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        failed = failed or not ok
    print()
    if failed:
        print("Harness: FAILED")
        return 1
    print("Harness: PASS (zero OpenAI credits on click run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
