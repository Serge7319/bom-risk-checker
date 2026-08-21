"""Sprint 71.4.2 — Ask Cadivor one-click suggested-question tests."""
from __future__ import annotations

import importlib
import inspect
import sys
import types
import unittest
from contextlib import contextmanager
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


class AskCadivorOneClickSuggestionTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("src.components.engineering_assistant", None)

    def _load_assistant(self, session_state=None, query_params=None):
        st = _install_streamlit_stub(session_state, query_params)
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

        scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
        scriptrunner.get_script_run_ctx = lambda: types.SimpleNamespace(script_run_id="run-test")
        runtime = types.ModuleType("streamlit.runtime")
        runtime.scriptrunner = scriptrunner
        sys.modules["streamlit.runtime"] = runtime
        sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner

        assistant = importlib.import_module("src.components.engineering_assistant")
        return st, assistant

    def test_suggestion_uses_same_queue_path_as_manual(self):
        _, assistant = self._load_assistant()
        select_source = inspect.getsource(assistant._select_initial_suggestion)
        queue_source = inspect.getsource(assistant._queue_copilot_submission)
        self.assertIn("_queue_copilot_submission", select_source)
        self.assertIn('"suggestion"', select_source)
        self.assertIn("cv41_pending_manual", queue_source)

    def test_duplicate_submission_blocked_while_inflight(self):
        st, assistant = self._load_assistant(
            {
                "cv7142_ask_inflight": True,
                "cv41_pending_manual": "What should I review first in this BOM?",
            }
        )
        assistant._queue_copilot_submission(
            "Explain the highest component risks.",
            submission_kind="suggestion",
            analysis_id="a-1",
        )
        self.assertEqual(
            st.session_state["cv41_pending_manual"],
            "What should I review first in this BOM?",
        )

    def test_queued_suggestion_executes_on_next_render(self):
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

        class _WorkingAI:
            configured = True
            ask_calls = 0

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                _WorkingAI.ask_calls += 1
                return types.SimpleNamespace(answer="Start with lifecycle risk.")

        _WorkingAI.ask_calls = 0
        with patch.object(assistant, "EngineeringAI", _WorkingAI):
            with patch.object(assistant, "_usage_banner"):
                with patch.object(assistant, "_render_prompt_chip_grid") as grid:
                    with patch.object(assistant, "_render_conversation_history"):
                        with patch.object(assistant, "_render_response"):
                            assistant.render_engineering_assistant(
                                current_user={"id": "user-1"},
                                engineering_context={"analysis_id": "a-1", "analysis": {"analysis_id": "a-1"}},
                            )
                    grid.assert_called_once()
                    self.assertTrue(grid.call_args.kwargs.get("disabled"))

        self.assertEqual(_WorkingAI.ask_calls, 1)
        self.assertEqual(st.session_state["cv35_last_question"], suggestion)
        self.assertNotIn("cv7142_ask_inflight", st.session_state)
        self.assertTrue(st.session_state.get(assistant._CLEAR_PROMPT_ON_NEXT_RUN_KEY))

    def test_processing_label_and_disabled_controls_present(self):
        _, assistant = self._load_assistant()
        source = inspect.getsource(assistant.render_engineering_assistant)
        self.assertIn("_COPILOT_PROCESSING_LABEL", source)
        self.assertIn("disabled=actions_disabled", source)
        self.assertIn("execution_started", source)
        self.assertIn("execution_completed", source)
        self.assertIn("duplicate_submission_blocked", inspect.getsource(assistant._block_duplicate_submission))

    def test_no_second_ai_execution_path(self):
        _, assistant = self._load_assistant()
        tree = inspect.getsource(assistant.render_engineering_assistant)
        self.assertEqual(tree.count("api.ask("), 1)


if __name__ == "__main__":
    unittest.main()

def tearDownModule():
    from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules
    restore_ask_cadivor_streamlit_modules()

