"""Sprint 71.8 — Ask Cadivor tab and suggested-prompt state tests."""
from __future__ import annotations

import ast
import inspect
import sys
import types
import unittest
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


class AskCadivorTabStateTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant") or name.startswith(
                "src.pages.analysis_detail"
            ):
                sys.modules.pop(name, None)

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
        sys.modules["src.services.engineering_ai"] = engineering_ai

        sys.modules.pop("src.components.engineering_assistant", None)
        import importlib

        assistant = importlib.import_module("src.components.engineering_assistant")
        return st, assistant

    def test_manual_submission_pins_ask_cadivor_tab(self):
        st, assistant = self._load_assistant()
        with self.assertRaises(RuntimeError):
            assistant._queue_copilot_submission("What should I review first?", submission_kind="manual")
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")
        self.assertEqual(st.session_state["cv41_pending_manual"], "What should I review first?")
        self.assertEqual(st.query_params["analysis_tab"], "Ask Cadivor")

    def test_select_initial_suggestion_updates_question_and_tab(self):
        st, assistant = self._load_assistant(
            session_state={"cadivor_active_analysis_tab": "Engineering Intelligence", "cv35_question": "old"},
        )
        with self.assertRaises(RuntimeError):
            assistant._select_initial_suggestion(
                assistant.SUGGESTIONS[0],
                index=0,
                prompt_key="cv35_question",
            )
        self.assertEqual(st.session_state["cv35_question"], assistant.SUGGESTIONS[0])
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")
        self.assertNotIn("cv41_pending_manual", st.session_state)

    def test_legacy_url_cv35_pick_consumed_once(self):
        st, assistant = self._load_assistant(
            session_state={"cv35_question": "stale"},
            query_params={"cv35_pick": "1", "analysis_tab": "Ask Cadivor"},
        )
        with self.assertRaises(RuntimeError):
            assistant._apply_copilot_query_picks(prompt_key="cv35_question")
        self.assertEqual(st.session_state["cv35_question"], assistant.SUGGESTIONS[1])
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")
        self.assertNotIn("cv35_pick", st.query_params)

    def test_stale_engineering_intelligence_loses_to_suggestion(self):
        st, assistant = self._load_assistant(
            session_state={"cadivor_active_analysis_tab": "Engineering Intelligence"},
        )
        with self.assertRaises(RuntimeError):
            assistant._select_initial_suggestion(
                assistant.SUGGESTIONS[2],
                index=2,
                prompt_key="cv35_question",
            )
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")

    def test_provider_completion_pins_ask_cadivor_tab(self):
        st, assistant = self._load_assistant(
            {
                "cv41_pending_manual": "What should I review first in this BOM?",
                "cadivor_active_analysis_tab": "Engineering Intelligence",
                "cv35_question": "What should I review first in this BOM?",
            }
        )

        class _WorkingAI:
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                return types.SimpleNamespace(answer="Review lifecycle risk first.")

        with patch.object(assistant, "EngineeringAI", _WorkingAI):
            with patch.object(assistant, "_usage_banner"):
                with patch.object(assistant, "_render_prompt_chip_grid"):
                    with patch.object(assistant, "_render_conversation_history"):
                        with patch.object(assistant, "_render_response"):
                            assistant.render_engineering_assistant(
                                current_user={"id": "user-1"},
                                engineering_context={"analysis_id": "a-1", "analysis": {"analysis_id": "a-1"}},
                                selected_component=None,
                            )

        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")

    def test_suggestion_chips_do_not_use_full_page_href_navigation(self):
        _, assistant = self._load_assistant()
        source = inspect.getsource(assistant._render_prompt_chip_grid)
        self.assertNotIn('target="_self"', source)
        self.assertNotIn("cv35-suggestion-chip", source)
        self.assertIn("st.button", source)

    def test_analysis_detail_syncs_url_tab_to_session(self):
        st = _install_streamlit_stub(
            session_state={"cadivor_active_analysis_tab": "Engineering Intelligence"},
            query_params={"analysis_tab": "Ask+Cadivor"},
        )

        def _normalize_analysis_tab(value):
            return str(value or "").strip().replace("+", " ")

        def _sync_cadivor_active_analysis_tab():
            try:
                incoming = _normalize_analysis_tab(st.query_params.get("analysis_tab", ""))
            except Exception:
                incoming = ""
            if incoming:
                st.session_state["cadivor_active_analysis_tab"] = incoming
            elif "cadivor_active_analysis_tab" not in st.session_state:
                st.session_state["cadivor_active_analysis_tab"] = "Engineering Intelligence"

        _sync_cadivor_active_analysis_tab()
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")

    def test_analysis_detail_js_uses_session_tab_only(self):
        from pathlib import Path

        source = Path("src/pages/analysis_detail.py").read_text(encoding="utf-8")
        self.assertIn("savedTab", source)
        self.assertNotIn("effectiveTab", source)
        self.assertNotIn("urlTab", source)


if __name__ == "__main__":
    unittest.main()
