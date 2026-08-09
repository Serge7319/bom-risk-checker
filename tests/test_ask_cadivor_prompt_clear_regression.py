"""Sprint 71.4.4C — Ask Cadivor deferred prompt-clear regression tests."""
from __future__ import annotations

import importlib
import inspect
import io
import sys
import types
import unittest
from contextlib import contextmanager, redirect_stdout
from unittest.mock import MagicMock, patch


def _install_streamlit_stub(session_state: dict | None = None, query_params: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = query_params if query_params is not None else {}
    st.form = lambda *args, **kwargs: _NullContext()
    st.text_area = lambda label, key, **kwargs: st.session_state.get(key, "")
    st.form_submit_button = MagicMock(return_value=False)
    st.status = lambda *args, **kwargs: _NullContext()
    st.markdown = MagicMock()
    st.warning = MagicMock()
    st.info = MagicMock()
    st.success = MagicMock()
    st.caption = MagicMock()
    st.columns = MagicMock(return_value=(MagicMock(), MagicMock()))
    st.button = MagicMock(return_value=False)
    st.rerun = MagicMock(side_effect=RuntimeError("rerun"))

    @contextmanager
    def _container(**kwargs):
        yield None

    st.container = _container

    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **kwargs):
        return None


class AskCadivorPromptClearRegressionTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("src.components.engineering_assistant", None)

    def _load_assistant(self, session_state=None):
        st = _install_streamlit_stub(session_state)
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
        copilot.append_turn = MagicMock(return_value=[{"question": "q", "answer": "a"}])
        copilot.clear_thread = MagicMock()
        copilot.compact_history = MagicMock(return_value=[])
        copilot.follow_up_suggestions = MagicMock(return_value=[])
        copilot.get_thread = MagicMock(return_value=[])
        sys.modules["src.services.copilot_conversation"] = copilot

        scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
        scriptrunner.get_script_run_ctx = lambda: types.SimpleNamespace(script_run_id="run-test")
        runtime = types.ModuleType("streamlit.runtime")
        runtime.scriptrunner = scriptrunner
        sys.modules["streamlit.runtime"] = runtime
        sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner

        assistant = importlib.import_module("src.components.engineering_assistant")
        return st, assistant

    def test_deferred_clear_runs_before_text_area_not_after(self):
        _, assistant = self._load_assistant()
        source = inspect.getsource(assistant.render_engineering_assistant)
        text_area_idx = source.index("st.text_area(")
        post_widget = source[text_area_idx:]
        self.assertNotIn('st.session_state[prompt_key] = ""', post_widget)
        clear_idx = source.index("_apply_deferred_prompt_clear(prompt_key)")
        self.assertLess(clear_idx, text_area_idx)

    def test_apply_deferred_prompt_clear_clears_before_widget_mount(self):
        st, assistant = self._load_assistant(
            {
                "cv7144_clear_prompt_on_next_run": True,
                "cv35_question": "What should I review first in this BOM?",
            }
        )
        assistant._apply_deferred_prompt_clear("cv35_question")
        self.assertEqual(st.session_state["cv35_question"], "")
        self.assertNotIn(assistant._CLEAR_PROMPT_ON_NEXT_RUN_KEY, st.session_state)

    def test_successful_fallback_execution_schedules_clear_without_failure_logs(self):
        st, assistant = self._load_assistant()
        suggestion = assistant.SUGGESTIONS[0]
        st.session_state.update(
            {
                "cv41_pending_manual": suggestion,
                "cv7142_ask_inflight": True,
                "cv35_question": suggestion,
                "cadivor_active_analysis_tab": "Ask Cadivor",
            }
        )

        class _FallbackAI:
            configured = False

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                return types.SimpleNamespace(answer="Grounded fallback assessment.")

        events: list[str] = []
        stdout = io.StringIO()
        with patch.object(assistant, "EngineeringAI", _FallbackAI):
            with patch.object(assistant, "_usage_banner"):
                with patch.object(assistant, "_render_prompt_chip_grid"):
                    with patch.object(assistant, "_render_conversation_history"):
                        with patch.object(assistant, "_render_response"):
                            with redirect_stdout(stdout):
                                assistant.render_engineering_assistant(
                                    current_user={"id": "user-1"},
                                    engineering_context={
                                        "analysis_id": "a-1",
                                        "analysis": {"analysis_id": "a-1"},
                                    },
                                )
        output = stdout.getvalue()
        for line in output.splitlines():
            if line.startswith("ASK_CADIVOR "):
                events.append(line.split(" ", 2)[1])

        self.assertIn("execution_started", events)
        self.assertIn("execution_completed", events)
        self.assertIn("response_committed", events)
        self.assertNotIn("provider_failed", events)
        self.assertNotIn("execution_failed", events)
        self.assertTrue(st.session_state.get(assistant._CLEAR_PROMPT_ON_NEXT_RUN_KEY))
        self.assertEqual(st.session_state["cv35_last_question"], suggestion)

    def test_next_run_applies_scheduled_clear_before_text_area(self):
        st, assistant = self._load_assistant(
            {
                "cv7144_clear_prompt_on_next_run": True,
                "cv35_question": "stale prompt text",
            }
        )
        with patch.object(assistant, "_usage_banner"):
            with patch.object(assistant, "_render_prompt_chip_grid"):
                with patch.object(assistant, "_render_conversation_history"):
                    with patch.object(assistant, "_render_response"):
                        assistant.render_engineering_assistant(
                            current_user={"id": "user-1"},
                            engineering_context={
                                "analysis_id": "a-1",
                                "analysis": {"analysis_id": "a-1"},
                            },
                        )
        self.assertEqual(st.session_state["cv35_question"], "")
        self.assertNotIn(assistant._CLEAR_PROMPT_ON_NEXT_RUN_KEY, st.session_state)

    def test_engineering_ai_error_still_logs_provider_failed(self):
        _, assistant = self._load_assistant()
        source = inspect.getsource(assistant.render_engineering_assistant)
        self.assertIn('except EngineeringAIError as exc:\n                _log_ask_cadivor("provider_failed"', source)
        self.assertIn('_log_ask_cadivor("execution_failed"', source)


if __name__ == "__main__":
    unittest.main()
