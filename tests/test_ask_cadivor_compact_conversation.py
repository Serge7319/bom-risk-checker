"""Compact Ask Cadivor conversation: structure, deferred details, no brief recompute."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def write(self, *args, **kwargs):
        return None

    def update(self, **kwargs):
        return None


class AskCadivorCompactConversationTests(unittest.TestCase):
    def tearDown(self):
        restore_ask_cadivor_streamlit_modules()

    def test_concise_answer_labels_are_decision_first(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        assistant = importlib.import_module("src.components.engineering_assistant")
        html = assistant._build_concise_answer_html(
            headline="Review PC817 first.",
            answer_text="Lead time and supplier concentration dominate the risk.",
            reason_items=["Reason one", "Reason two"],
            action_items=["Step one", "Step two", "Step three", "Step four"],
        )
        self.assertIn("Recommended next action", html)
        self.assertIn("Why it matters", html)
        self.assertIn("Recommended next steps", html)
        self.assertIn("Cadivor answer", html)
        self.assertIn("cv72-compact-answer", html)
        self.assertNotIn("Direct answer", html)
        self.assertNotIn("Key engineering reasons", html)
        self.assertEqual(html.count("cv722-action-row"), 3)
        self.assertIn("_disclosure_is_open", ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8"))

    def test_scannable_reasons_lead_with_mpn_without_raw_fields(self) -> None:
        install_ask_cadivor_streamlit_stub()
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        assistant = importlib.import_module("src.components.engineering_assistant")
        reasons = assistant._concise_reason_items(
            "- **MAX32625ITK+** — relative-assessment priority; 26-week lead time; NRND; risk 88/100; 2 suppliers; stock 120\n"
            "- **TPS54331D** — medium composite risk; confirm supply before release; supplier count 1\n"
            "- **DRV8825** — End of Life lifecycle status requires attention; inventory 0",
            [],
        )
        self.assertEqual(len(reasons), 3)
        self.assertTrue(reasons[0].startswith("MAX32625ITK+:"))
        self.assertIn("26-week", reasons[0])
        self.assertIn("NRND", reasons[0])
        self.assertNotIn("relative-assessment", reasons[0].lower())
        self.assertNotIn("88/100", reasons[0])
        self.assertNotIn("suppliers", reasons[0].lower())
        self.assertNotIn("120", reasons[0])
        self.assertIn("TPS54331D:", reasons[1])
        self.assertIn("medium composite risk", reasons[1].lower())

    def test_default_response_omits_assessment_and_evidence(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        assistant = importlib.import_module("src.components.engineering_assistant")
        assessment_calls: list[dict] = []
        evidence_calls: list[str] = []

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_disclosure_is_open", return_value=False):
                with patch.object(
                    assistant,
                    "_build_engineering_assessment_html",
                    side_effect=lambda **kwargs: assessment_calls.append(kwargs) or "",
                ):
                    with patch.object(
                        assistant,
                        "_build_evidence_cards_html",
                        side_effect=lambda evidence: evidence_calls.append(evidence) or "",
                    ):
                        assistant._render_response(
                            question=PC817_QUESTION,
                            answer=PC817_ANSWER,
                            context=PC817_CONTEXT,
                        )

        html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
        self.assertIn("Recommended next action", html)
        self.assertIn("cv72-compact-answer", html)
        self.assertEqual(assessment_calls, [])
        self.assertEqual(evidence_calls, [])
        self.assertEqual(st.columns_calls, [])

    def test_expanding_details_builds_assessment_once(self) -> None:
        install_ask_cadivor_streamlit_stub()
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        assistant = importlib.import_module("src.components.engineering_assistant")
        assessment_calls: list[dict] = []

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(
                assistant,
                "_disclosure_is_open",
                side_effect=lambda label, **kwargs: label == "Engineering assessment",
            ):
                with patch.object(
                    assistant,
                    "_build_engineering_assessment_html",
                    side_effect=lambda **kwargs: assessment_calls.append(kwargs) or "<div>assessment</div>",
                ):
                    assistant._render_response(
                        question=PC817_QUESTION,
                        answer=PC817_ANSWER,
                        context=PC817_CONTEXT,
                    )

        self.assertEqual(len(assessment_calls), 1)
        self.assertEqual(assessment_calls[0].get("evidence"), "")

    def test_context_header_uses_spaced_chips(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        assistant = importlib.import_module("src.components.engineering_assistant")
        assistant._render_context_header(
            {
                "project_name": "Industrial Controller BOM",
                "summary": {
                    "health_score": 42,
                    "total_parts": 3,
                    "release_posture": "release_hold",
                },
            }
        )
        html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
        self.assertIn("Saved BOM", html)
        self.assertIn("Health 42", html)
        self.assertIn("3 parts", html)
        self.assertIn("Release hold recommended", html)
        self.assertIn("cv-assistant-meta-chip", html)
        self.assertNotIn("Health 423 parts", html)

    def test_new_question_does_not_rebuild_decision_brief(self) -> None:
        """Ask Cadivor must reuse the page-cached engineering context, not rebuild the brief."""
        brief_builder = MagicMock(return_value={"status": "should-not-run"})

        class _Ctx:
            def compact(self, max_components=15):
                return {
                    "analysis_id": "a-1",
                    "analysis": {"analysis_id": "a-1"},
                    "components": [],
                    "coverage": {"score": 70},
                }

        st = types.ModuleType("streamlit")
        st.session_state = {
            "cv41_pending_manual": "What should I review first?",
            "cv7142_ask_inflight": True,
            "cv35_question": "What should I review first?",
            "cadivor_active_analysis_tab": "Ask Cadivor",
        }
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
        st.button = MagicMock(return_value=False)
        st.caption = MagicMock()
        st.container = lambda **kwargs: _NullContext()
        st.rerun = MagicMock(side_effect=RuntimeError("rerun"))
        st.expander = lambda *args, **kwargs: _NullContext()
        st.toggle = MagicMock(return_value=False)
        components = types.ModuleType("streamlit.components.v1")
        components.html = MagicMock()
        sys.modules["streamlit"] = st
        sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
        sys.modules["streamlit.components.v1"] = components

        from tests.secrets_module_isolation import install_src_secrets_stub

        _secrets, restore_secrets = install_src_secrets_stub(
            get_secret=lambda key, default="": default,
            get_secret_bool=lambda key, default=False: default,
            ConfigurationError=RuntimeError,
        )
        self.addCleanup(restore_secrets)

        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
            if name.startswith("src.services.copilot_conversation"):
                sys.modules.pop(name, None)
            if name.startswith("src.services.engineering_ai"):
                sys.modules.pop(name, None)

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
        copilot.get_thread = lambda session, context: []
        copilot.append_turn = MagicMock(
            side_effect=lambda session, context, **kwargs: [
                {"question": kwargs["question"], "answer": kwargs["answer"]}
            ]
        )
        copilot.compact_history = lambda thread: []
        copilot.clear_thread = MagicMock()
        copilot.follow_up_suggestions = lambda *args, **kwargs: ["Follow-up A", "Follow-up B"]
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
        scriptrunner.get_script_run_ctx = lambda: types.SimpleNamespace(script_run_id="compact-test")
        runtime = types.ModuleType("streamlit.runtime")
        runtime.scriptrunner = scriptrunner
        sys.modules["streamlit.runtime"] = runtime
        sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner

        # Simulate the page-level brief builder that must stay idle on Ask questions.
        brief_mod = types.ModuleType("src.services.engineering_decision_brief")
        brief_mod.build_engineering_decision_brief = brief_builder
        sys.modules["src.services.engineering_decision_brief"] = brief_mod

        assistant = importlib.import_module("src.components.engineering_assistant")
        with patch.object(assistant, "_usage_banner"):
            with patch.object(assistant, "_render_prompt_chip_grid"):
                with patch.object(assistant, "_render_conversation_history"):
                    with patch.object(assistant, "_disclosure_is_open", return_value=False):
                        with patch.object(assistant, "_render_response", MagicMock()) as render_response:
                            with patch.object(assistant, "_render_pending_exchange"):
                                with patch.object(assistant, "_render_follow_ups"):
                                    for _ in range(4):
                                        try:
                                            assistant.render_engineering_assistant(
                                                current_user={"id": "user-1"},
                                                engineering_context=_Ctx(),
                                            )
                                            break
                                        except RuntimeError as exc:
                                            if str(exc) != "rerun":
                                                raise
                                            pending = (
                                                st.session_state.get("cv72_provider_armed")
                                                or st.session_state.get("cv41_pending_manual")
                                                or st.session_state.get("cv36_pending_followup")
                                            )
                                            if not pending:
                                                break

        brief_builder.assert_not_called()
        render_response.assert_called()
        source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        self.assertNotIn("build_engineering_decision_brief", source)
        self.assertIn("_FOLLOWUP_CHIP_LIMIT = 3", source)
        self.assertIn("Cadivor is reviewing this BOM", source)

    def test_followups_are_capped_and_formless(self) -> None:
        source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        self.assertIn("[:_FOLLOWUP_CHIP_LIMIT]", source)
        self.assertNotIn("cv47_custom_followup_form", source)
        self.assertNotIn('render_subsection_header("Continue the review"', source)
        self.assertIn("def _disclosure_is_open", source)
        self.assertNotIn("st.toggle(", source)

    def test_usage_banner_uses_middle_dot_separator(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        assistant = importlib.import_module("src.components.engineering_assistant")
        status = types.SimpleNamespace(
            is_admin=False,
            remaining=100,
            allowance=100,
            warning_level="normal",
            percent_used=0,
        )
        assistant._usage_banner(status)
        html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
        self.assertIn("<strong>AI usage</strong>", html)
        self.assertIn('class="cv35-usage-sep"', html)
        self.assertIn(" · ", html)
        self.assertIn("100 of 100 AI credits remaining this month", html)
        self.assertNotIn("AI usage</strong><span>100", html)
        css = (REPO_ROOT / "src/assets/css/ask_cadivor_v2.css").read_text(encoding="utf-8")
        self.assertIn(".cv35-usage-sep", css)
        self.assertIn("st-key-cv72_response_stage", css)
        self.assertIn("st-key-cv72_disc_", css)
        self.assertIn("st-key-cv72_prior_reviews", css)

    def test_pending_exchange_keeps_viewport_stable(self) -> None:
        source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        start = source.index("def _render_pending_exchange")
        end = source.index("\ndef _render_conversation_exchange", start)
        pending_fn = source[start:end]
        self.assertIn('st.session_state.pop("cv47_scroll_pending"', pending_fn)
        self.assertNotIn("scrollIntoView", pending_fn)
        self.assertIn('key="cv72_response_stage"', source)
        self.assertIn('key="cv72_prior_reviews"', source)
        self.assertIn("cv72_disc_", source)
        styles = (REPO_ROOT / "src/components/ask_cadivor_response_styles.py").read_text(encoding="utf-8")
        self.assertIn("max-width:1040px", styles)


if __name__ == "__main__":
    unittest.main()
