"""Sprint 72.2.8.1 — Pending-question preservation across reruns."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def update(self, **kwargs):
        return None


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = dict(session_state or {})
    st.query_params = {}
    st.form = lambda *args, **kwargs: _NullContext()
    st.text_area = lambda label, key, **kwargs: st.session_state.get(key, "")
    st.form_submit_button = MagicMock(return_value=False)
    st.status = lambda *args, **kwargs: _NullContext()
    st.markdown = MagicMock()
    st.warning = MagicMock()
    st.info = MagicMock()
    st.html = MagicMock()
    st.columns = MagicMock(return_value=(MagicMock(), MagicMock()))
    st.button = MagicMock(return_value=False)
    st.caption = MagicMock()
    st.container = lambda **kwargs: _NullContext()

    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st


class AskCadivorPendingPreservationTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)

    def _load_assistant(self, session_state=None, *, can_use: bool = True):
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
                can_use=can_use,
                remaining=10 if can_use else 0,
                allowance=10,
                warning_level="normal" if can_use else "exhausted",
                is_admin=False,
            )
        )
        ai_entitlements.consume_ai_credits = MagicMock()
        sys.modules["src.services.ai_entitlements"] = ai_entitlements

        copilot = types.ModuleType("src.services.copilot_conversation")
        copilot.get_thread = lambda session, context: []
        copilot.append_turn = MagicMock(return_value=[])
        copilot.compact_history = lambda thread: []
        copilot.clear_thread = MagicMock()
        copilot.follow_up_suggestions = lambda *args, **kwargs: []
        sys.modules["src.services.copilot_conversation"] = copilot

        engineering_ai = types.ModuleType("src.services.engineering_ai")

        class _BlockedAI:
            configured = True
            ask_calls = 0

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                _BlockedAI.ask_calls += 1
                return types.SimpleNamespace(answer="blocked", provider="openai")

        engineering_ai.EngineeringAI = _BlockedAI
        engineering_ai.EngineeringAIError = RuntimeError
        engineering_ai.log_ai_config = lambda api: None
        sys.modules["src.services.engineering_ai"] = engineering_ai

        scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
        scriptrunner.get_script_run_ctx = lambda: types.SimpleNamespace(script_run_id="pending-test")
        runtime = types.ModuleType("streamlit.runtime")
        runtime.scriptrunner = scriptrunner
        sys.modules["streamlit.runtime"] = runtime
        sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner

        assistant = importlib.import_module("src.components.engineering_assistant")
        return st, assistant

    def test_pending_manual_preserved_when_credits_unavailable(self):
        suggestion = "What should I review first in this BOM?"
        st, assistant = self._load_assistant(
            {
                "cv41_pending_manual": suggestion,
                "cv7142_ask_inflight": True,
                "cv35_question": suggestion,
                "cadivor_active_analysis_tab": "Ask Cadivor",
            },
            can_use=False,
        )

        class _BlockedAI:
            configured = True
            ask_calls = 0

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                _BlockedAI.ask_calls += 1
                return types.SimpleNamespace(answer="should not run", provider="openai")

        with patch.object(assistant, "EngineeringAI", _BlockedAI):
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

        self.assertEqual(st.session_state.get("cv41_pending_manual"), suggestion)
        self.assertEqual(_BlockedAI.ask_calls, 0)

    def test_pending_manual_consumed_only_when_execution_starts(self):
        suggestion = "What should I review first in this BOM?"
        st, assistant = self._load_assistant(
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
                return types.SimpleNamespace(answer="Review PC817 first.", provider="openai")

        with patch.object(assistant, "EngineeringAI", _WorkingAI):
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

        self.assertNotIn("cv41_pending_manual", st.session_state)
        self.assertEqual(_WorkingAI.ask_calls, 1)
        self.assertTrue(st.session_state.get("cv35_last_answer"))
        self.assertNotIn("cv7142_ask_inflight", st.session_state)


    def test_queue_retains_completed_review_while_followup_is_processing(self):
        previous_question = "What should I review first?"
        previous_answer = "Review STM32F103C8T6 first."
        st, assistant = self._load_assistant(
            {
                "cv35_last_question": previous_question,
                "cv35_last_answer": previous_answer,
                "cv35_last_error": RuntimeError("stale error"),
                "cv36_followup_options": ["Why?"],
            }
        )
        st.rerun = MagicMock()

        assistant._queue_follow_up("What evidence would change this recommendation?", analysis_id="a-1")

        self.assertEqual(st.session_state.get("cv35_last_question"), previous_question)
        self.assertEqual(st.session_state.get("cv35_last_answer"), previous_answer)
        self.assertNotIn("cv35_last_error", st.session_state)
        self.assertNotIn("cv36_followup_options", st.session_state)
        self.assertTrue(st.session_state.get("cv7142_ask_inflight"))

    def test_pending_followup_renders_completed_review_before_new_result(self):
        previous_question = "What should I review first?"
        previous_answer = "Review STM32F103C8T6 first."
        followup = "What evidence would change this recommendation?"
        st, assistant = self._load_assistant(
            {
                "cv36_pending_followup": followup,
                "cv7142_ask_inflight": True,
                "cv35_question": followup,
                "cv35_last_question": previous_question,
                "cv35_last_answer": previous_answer,
                "cadivor_active_analysis_tab": "Ask Cadivor",
            }
        )

        class _WorkingAI:
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                return types.SimpleNamespace(answer="A shorter lead time would change it.", provider="openai")

        rendered: list[dict] = []
        with patch.object(assistant, "EngineeringAI", _WorkingAI):
            with patch.object(assistant, "_usage_banner"):
                with patch.object(assistant, "_render_prompt_chip_grid"):
                    with patch.object(assistant, "_render_conversation_history"):
                        with patch.object(assistant, "_render_response", side_effect=lambda **kwargs: rendered.append(kwargs)):
                            assistant.render_engineering_assistant(
                                current_user={"id": "user-1"},
                                engineering_context={"analysis_id": "a-1", "analysis": {"analysis_id": "a-1"}},
                            )

        self.assertGreaterEqual(len(rendered), 2)
        self.assertEqual(rendered[0]["question"], previous_question)
        self.assertEqual(rendered[0]["answer"], previous_answer)
        self.assertFalse(rendered[0]["auto_scroll"])
        self.assertEqual(rendered[-1]["question"], followup)
        self.assertEqual(rendered[-1]["answer"], "A shorter lead time would change it.")


class AskCadivorStaleInflightRecoveryTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)

    def _load_assistant(self, session_state: dict):
        st = _install_streamlit_stub(session_state)
        sys.modules.pop("src.components.engineering_assistant", None)
        assistant = importlib.import_module("src.components.engineering_assistant")
        assistant.st = st
        return st, assistant

    def test_pending_exists_inflight_not_cleared(self):
        st, assistant = self._load_assistant(
            {
                "cv7142_ask_inflight": True,
                "cv41_pending_manual": "What should I review first in this BOM?",
            }
        )
        assistant._recover_stale_copilot_inflight()
        self.assertTrue(st.session_state.get("cv7142_ask_inflight"))
        self.assertEqual(
            st.session_state.get("cv41_pending_manual"),
            "What should I review first in this BOM?",
        )

    def test_pending_in_snapshot_inflight_not_cleared(self):
        st, assistant = self._load_assistant(
            {
                "cv7142_ask_inflight": True,
                "cv4801_followup_inflight": True,
                "cv48_copilot_snapshot": {
                    "cv41_pending_manual": "What should I review first in this BOM?",
                    "cv7142_ask_inflight": True,
                },
            }
        )
        assistant._recover_stale_copilot_inflight()
        self.assertTrue(st.session_state.get("cv7142_ask_inflight"))
        self.assertTrue(st.session_state.get("cv4801_followup_inflight"))

    def test_followup_pending_inflight_not_cleared(self):
        st, assistant = self._load_assistant(
            {
                "cv7142_ask_inflight": True,
                "cv36_pending_followup": "Why is PC817 ranked first?",
            }
        )
        assistant._recover_stale_copilot_inflight()
        self.assertTrue(st.session_state.get("cv7142_ask_inflight"))
        self.assertEqual(
            st.session_state.get("cv36_pending_followup"),
            "Why is PC817 ranked first?",
        )

    def test_orphaned_inflight_is_recovered(self):
        st, assistant = self._load_assistant(
            {
                "cv7142_ask_inflight": True,
                "cv4801_followup_inflight": True,
                "cv48_copilot_snapshot": {"cadivor_active_analysis_tab": "Ask Cadivor"},
            }
        )
        assistant._recover_stale_copilot_inflight()
        self.assertNotIn("cv7142_ask_inflight", st.session_state)
        self.assertNotIn("cv4801_followup_inflight", st.session_state)


if __name__ == "__main__":
    unittest.main()

def tearDownModule():
    from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules
    restore_ask_cadivor_streamlit_modules()

