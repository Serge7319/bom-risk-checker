"""Ask Cadivor conversation stability — pairing, loading, scroll, and reruns."""
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
    st.success = MagicMock()
    st.html = MagicMock()
    st.columns = MagicMock(return_value=(MagicMock(), MagicMock()))
    st.columns.return_value[0].button = MagicMock(return_value=False)
    st.columns.return_value[1].button = MagicMock(return_value=False)
    st.button = MagicMock(return_value=False)
    st.caption = MagicMock()
    st.container = lambda **kwargs: _NullContext()
    st.rerun = MagicMock()
    st.expander = lambda *args, **kwargs: _NullContext()

    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st


class AskCadivorConversationStabilityTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
            if name.startswith("src.services.copilot_conversation"):
                sys.modules.pop(name, None)

    def tearDown(self):
        from tests.secrets_module_isolation import ensure_real_src_secrets_module
        from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules

        ensure_real_src_secrets_module()
        for name in list(sys.modules):
            if name == "streamlit" or name.startswith("streamlit."):
                sys.modules.pop(name, None)
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
            if name.startswith("src.services.copilot_conversation"):
                sys.modules.pop(name, None)
            if name.startswith("src.services.engineering_ai"):
                sys.modules.pop(name, None)
            if name in {
                "src.urls",
                "src.ui.navigation",
                "src.services.ai_entitlements",
            }:
                sys.modules.pop(name, None)
        restore_ask_cadivor_streamlit_modules()
        importlib.import_module("src.auth_state")
        importlib.import_module("src.auth_bootstrap")

    def _load_assistant(self, session_state=None, *, can_use: bool = True, real_append: bool = False):
        st = _install_streamlit_stub(session_state)
        from tests.secrets_module_isolation import install_src_secrets_stub

        _secrets, restore_secrets = install_src_secrets_stub(
            get_secret=lambda key, default="": default,
            get_secret_bool=lambda key, default=False: default,
            ConfigurationError=RuntimeError,
        )
        self.addCleanup(restore_secrets)

        import src.auth_state as auth_state_mod

        original_log = auth_state_mod.log_auth_diagnostic
        auth_state_mod.log_auth_diagnostic = lambda *args, **kwargs: None
        self.addCleanup(lambda: setattr(auth_state_mod, "log_auth_diagnostic", original_log))

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

        if real_append:
            # Keep the real conversation helpers for duplicate-turn coverage.
            sys.modules.pop("src.services.copilot_conversation", None)
        else:
            copilot = types.ModuleType("src.services.copilot_conversation")
            copilot.get_thread = lambda session, context: list(
                (session.get("cv36_threads") or {}).get("a-1") or []
            )

            def _append(session, context, **kwargs):
                threads = session.setdefault("cv36_threads", {})
                thread = list(threads.get("a-1") or [])
                thread.append(
                    {
                        "question": kwargs.get("question"),
                        "answer": kwargs.get("answer"),
                        "provider_connected": kwargs.get("provider_connected"),
                    }
                )
                threads["a-1"] = thread
                return list(thread)

            copilot.append_turn = MagicMock(side_effect=_append)
            copilot.compact_history = lambda thread: []
            copilot.clear_thread = MagicMock()
            copilot.follow_up_suggestions = lambda *args, **kwargs: []
            sys.modules["src.services.copilot_conversation"] = copilot

        engineering_ai = types.ModuleType("src.services.engineering_ai")

        class _WorkingAI:
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                return types.SimpleNamespace(answer="Answer body.", provider="openai")

        engineering_ai.EngineeringAI = _WorkingAI
        engineering_ai.EngineeringAIError = RuntimeError
        engineering_ai.log_ai_config = lambda api: None
        sys.modules["src.services.engineering_ai"] = engineering_ai

        scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
        scriptrunner.get_script_run_ctx = lambda: types.SimpleNamespace(script_run_id="stability-test")
        runtime = types.ModuleType("streamlit.runtime")
        runtime.scriptrunner = scriptrunner
        sys.modules["streamlit.runtime"] = runtime
        sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner

        assistant = importlib.import_module("src.components.engineering_assistant")
        return st, assistant

    def _render(self, assistant, **kwargs):
        with patch.object(assistant, "_usage_banner"):
            with patch.object(assistant, "_render_prompt_chip_grid"):
                with patch.object(assistant, "_render_conversation_history"):
                    with patch.object(assistant, "_render_follow_ups"):
                        assistant.render_engineering_assistant(
                            current_user={"id": "user-1"},
                            engineering_context={
                                "analysis_id": "a-1",
                                "analysis": {"analysis_id": "a-1"},
                            },
                            **kwargs,
                        )

    def test_typed_question_shows_one_pending_then_one_answer(self):
        question = "What should I review first in this BOM?"
        st, assistant = self._load_assistant(
            {
                "cv41_pending_manual": question,
                "cv7142_ask_inflight": True,
                "cv35_question": question,
                "cadivor_active_analysis_tab": "Ask Cadivor",
            }
        )
        pending_calls: list[str] = []
        rendered: list[dict] = []

        with patch.object(
            assistant,
            "_render_pending_exchange",
            side_effect=lambda **kwargs: pending_calls.append(kwargs["question"]),
        ):
            with patch.object(
                assistant,
                "_render_response",
                side_effect=lambda **kwargs: rendered.append(kwargs),
            ):
                self._render(assistant)

        self.assertEqual(pending_calls, [question])
        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0]["question"], question)
        self.assertEqual(rendered[0]["answer"], "Answer body.")
        self.assertNotIn("cv72_active_pending_question", st.session_state)
        self.assertNotIn("cv41_pending_manual", st.session_state)

    def test_suggested_question_uses_same_stable_flow(self):
        st, assistant = self._load_assistant({"cadivor_active_analysis_tab": "Ask Cadivor"})
        suggestion = assistant.SUGGESTIONS[0]
        assistant._queue_copilot_submission(suggestion, submission_kind="suggestion", analysis_id="a-1")

        self.assertEqual(st.session_state.get("cv41_pending_manual"), suggestion)
        self.assertEqual(st.session_state.get("cv72_active_pending_question"), suggestion)
        self.assertTrue(st.session_state.get("cv7142_ask_inflight"))
        self.assertTrue(st.session_state.get("cv47_scroll_pending"))
        # Prior review keys are not wiped on queue.
        st.session_state["cv35_last_question"] = "Prior"
        st.session_state["cv35_last_answer"] = "Prior answer"
        assistant._prepare_review_for_new_submission()
        self.assertEqual(st.session_state.get("cv35_last_question"), "Prior")
        self.assertEqual(st.session_state.get("cv35_last_answer"), "Prior answer")

    def test_delayed_answer_does_not_duplicate_messages(self):
        from src.services.copilot_conversation import append_turn, get_thread

        session: dict = {}
        context = {"analysis_id": "a-1", "analysis": {"analysis_id": "a-1"}}
        first = append_turn(
            session,
            context,
            question="Q1?",
            answer="A1",
            provider_connected=True,
        )
        second = append_turn(
            session,
            context,
            question="Q1?",
            answer="A1",
            provider_connected=True,
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(len(get_thread(session, context)), 1)

    def test_rerun_preserves_pairing_and_order(self):
        previous_q = "What should I review first?"
        previous_a = "Review STM32 first."
        followup = "What evidence would change this?"
        st, assistant = self._load_assistant(
            {
                "cv36_pending_followup": followup,
                "cv7142_ask_inflight": True,
                "cv35_question": followup,
                "cv35_last_question": previous_q,
                "cv35_last_answer": previous_a,
                "cadivor_active_analysis_tab": "Ask Cadivor",
                "cv36_threads": {
                    "a-1": [
                        {
                            "question": previous_q,
                            "answer": previous_a,
                            "provider_connected": True,
                        }
                    ]
                },
            }
        )
        rendered: list[dict] = []
        with patch.object(assistant, "_render_pending_exchange"):
            with patch.object(
                assistant,
                "_render_response",
                side_effect=lambda **kwargs: rendered.append(kwargs),
            ):
                self._render(assistant)

        self.assertGreaterEqual(len(rendered), 2)
        self.assertEqual(rendered[0]["question"], previous_q)
        self.assertEqual(rendered[0]["answer"], previous_a)
        self.assertFalse(rendered[0].get("auto_scroll"))
        self.assertEqual(rendered[-1]["question"], followup)
        self.assertEqual(st.session_state.get("cv35_last_question"), followup)
        self.assertTrue(st.session_state.get("cv35_last_answer"))

    def test_no_automatic_jump_away_from_active_item(self):
        source = (importlib.import_module("src.components.engineering_assistant").__file__)
        text = open(source, encoding="utf-8").read()
        self.assertIn("block: 'nearest'", text)
        self.assertIn("_render_pending_exchange", text)
        self.assertNotIn("new MutationObserver", text)
        self.assertNotIn("cv47-processing-anchor", text)
        # question_changed must not force scroll on ordinary reruns.
        self.assertNotIn(
            'question_changed = st.session_state.get("cv50_last_scrolled_question")',
            text,
        )


if __name__ == "__main__":
    unittest.main()
