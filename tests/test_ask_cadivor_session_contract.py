"""Ask Cadivor session/tab contract tests for Sprint 71.7."""
from __future__ import annotations

import ast
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
    st.html = MagicMock()
    st.columns = MagicMock(return_value=(MagicMock(), MagicMock()))
    st.button = MagicMock(return_value=False)
    st.caption = MagicMock()
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


class AskCadivorSessionContractTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)

    def tearDown(self):
        from tests.secrets_module_isolation import ensure_real_src_secrets_module

        ensure_real_src_secrets_module()

    def _load_assistant(self, session_state=None, query_params=None):
        st = _install_streamlit_stub(session_state, query_params)
        from tests.secrets_module_isolation import install_src_secrets_stub
        _secrets, restore_secrets = install_src_secrets_stub(
            get_secret=lambda key, default="": default,
            get_secret_bool=lambda key, default=False: default,
            ConfigurationError=RuntimeError,
        )
        self.addCleanup(restore_secrets)

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
            return_value=types.SimpleNamespace(can_use=True, remaining=10, limit=10)
        )
        ai_entitlements.consume_ai_credits = MagicMock()
        sys.modules["src.services.ai_entitlements"] = ai_entitlements

        copilot = types.ModuleType("src.services.copilot_conversation")
        copilot.get_thread = lambda session, context: []
        copilot.append_turn = lambda session, context, **kwargs: [{"question": "q", "answer": "a"}]
        copilot.compact_history = lambda thread: []
        copilot.clear_thread = MagicMock()
        copilot.follow_up_suggestions = lambda *args, **kwargs: []
        sys.modules["src.services.copilot_conversation"] = copilot

        engineering_ai = types.ModuleType("src.services.engineering_ai")

        class _Response:
            answer = "Review lifecycle risk first."
            provider = "openai"
            model = "gpt-test"
            grounded = True

        class _Error(RuntimeError):
            def __init__(self, message="", code=""):
                super().__init__(message)
                self.code = code

        class _EngineeringAI:
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                return _Response()

        engineering_ai.EngineeringAI = _EngineeringAI
        engineering_ai.EngineeringAIError = _Error
        engineering_ai.log_ai_config = lambda api: None
        sys.modules["src.services.engineering_ai"] = engineering_ai

        sys.modules.pop("src.components.engineering_assistant", None)
        import importlib

        assistant = importlib.import_module("src.components.engineering_assistant")
        return st, assistant

    def test_pin_ask_cadivor_tab_queues_pending_without_nav_mutation(self):
        st, assistant = self._load_assistant(query_params={})
        assistant._pin_ask_cadivor_tab(source="test", analysis_id="a-1")
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")
        self.assertEqual(st.query_params["analysis_tab"], "Ask Cadivor")
        self.assertEqual(st.session_state["cadivor_pending_analysis_section"], "Ask Cadivor")
        self.assertEqual(st.session_state["cadivor_pending_analysis_section_id"], "a-1")
        self.assertNotIn("cadivor_analysis_section_a-1", st.session_state)

    def test_queue_copilot_submission_pins_tab(self):
        st, assistant = self._load_assistant()
        sys.modules["streamlit"].rerun = MagicMock(side_effect=RuntimeError("rerun"))
        with self.assertRaises(RuntimeError):
            assistant._queue_copilot_submission("What should I review first?", submission_kind="manual")
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")

    def test_apply_copilot_query_pick_queues_submission(self):
        st, assistant = self._load_assistant(
            session_state={"cv35_question": "old stale question"},
            query_params={"cv35_pick": "0"},
        )
        sys.modules["streamlit"].rerun = MagicMock(side_effect=RuntimeError("rerun"))
        with self.assertRaises(RuntimeError):
            assistant._apply_copilot_query_picks(prompt_key="cv35_question")
        self.assertEqual(
            st.session_state["cv41_pending_manual"],
            assistant.SUGGESTIONS[0],
        )
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")
        self.assertNotIn("cv35_pick", st.query_params)

    def test_engineering_ai_ask_has_no_threadpool(self):
        _, assistant = self._load_assistant()
        source = inspect.getsource(assistant.render_engineering_assistant)
        tree = ast.parse(source)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("ThreadPoolExecutor", names)

    def test_fetch_validated_auth_pattern_not_in_assistant(self):
        _, assistant = self._load_assistant()
        for fn_name in ("_pin_ask_cadivor_tab", "_queue_copilot_submission", "_apply_copilot_query_picks"):
            source = inspect.getsource(getattr(assistant, fn_name))
            tree = ast.parse(source)
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            self.assertNotIn("ThreadPoolExecutor", names)

    def test_provider_failure_keeps_ask_tab_pinned(self):
        st, assistant = self._load_assistant(
            {
                "cv41_pending_manual": "What should I review first in this BOM?",
                "cadivor_active_analysis_tab": "Engineering Intelligence",
            }
        )

        class _FailingAI:
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                raise assistant.EngineeringAIError("provider down", code="unavailable")

        with patch.object(assistant, "EngineeringAI", _FailingAI):
            with patch.object(assistant, "_usage_banner"):
                with patch.object(assistant, "_render_prompt_chip_grid"):
                    with patch.object(assistant, "_render_conversation_history"):
                        with patch.object(assistant, "_render_error"):
                            assistant.render_engineering_assistant(
                                current_user={"id": "user-1"},
                                engineering_context={"analysis_id": "a-1", "analysis": {"analysis_id": "a-1"}},
                                selected_component=None,
                            )

        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")
        self.assertIsInstance(st.session_state.get("cv35_last_error"), assistant.EngineeringAIError)


if __name__ == "__main__":
    unittest.main()

def tearDownModule():
    from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules
    restore_ask_cadivor_streamlit_modules()

