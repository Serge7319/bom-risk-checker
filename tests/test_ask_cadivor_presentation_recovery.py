"""Sprint 72.3.2 — Ask Cadivor self-contained HTML presentation recovery tests."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION, render_pc817_harness


class AskCadivorPresentationRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")
        cls.harness_html, cls.harness_st = render_pc817_harness()

    def setUp(self) -> None:
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)

    def _load_assistant(self):
        import src.components.engineering_assistant as assistant

        return assistant

    def _render(self, *, question: str = PC817_QUESTION, answer: str = PC817_ANSWER):
        st = install_ask_cadivor_streamlit_stub()
        assistant = self._load_assistant()
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(question=question, answer=answer, context=PC817_CONTEXT)
        html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
        return assistant, html, st

    def test_question_and_exchange_native(self) -> None:
        self.assertIn(PC817_QUESTION, self.harness_html)
        self.assertIn("cv50-exchange", self.harness_html)
        self.assertIn("You asked", self.harness_html)
        self.assertIn("cv50-type", self.harness_html)
        self.assertIn("cv50-saved", self.harness_html)

    def test_direct_answer_in_primary_surface(self) -> None:
        self.assertIn("Review PC817 first.", self.harness_html)
        self.assertIn("direct_answer", self.harness_st.render_sequence)

    def test_single_numbering_for_reasons(self) -> None:
        self.assertGreaterEqual(self.harness_html.count("cv722-reason-row"), 3)
        self.assertRegex(self.harness_html, r'cv722-list-index" aria-hidden="true"[^>]*>01')
        self.assertNotIn("1. 1", self.harness_html)

    def test_single_numbering_for_actions(self) -> None:
        self.assertGreaterEqual(self.harness_html.count("cv722-action-row"), 3)
        self.assertRegex(self.harness_html, r'cv722-list-index" aria-hidden="true"[^>]*>03')

    def test_decision_summary_and_impact_surfaces_present(self) -> None:
        self.assertIn("decision_summary", self.harness_st.render_sequence)
        self.assertIn("impact_grid", self.harness_st.render_sequence)
        self.assertIn("cv722-summary-strip", self.harness_html)
        self.assertEqual(self.harness_html.count("cv724-impact-cell"), 4)

    def test_shell_independent_css_present(self) -> None:
        section = self.v2_css.split("Sprint 72.2.4", 1)[1]
        for key in (
            ".cv50-exchange",
            ".cv722-reason-list",
            ".cv722-summary-strip",
            ".cv46-evidence-card-header",
        ):
            self.assertIn(key, section)

    def test_impact_uses_self_contained_grid(self) -> None:
        _, html, st = self._render()
        self.assertIn("Projected engineering impact", html)
        self.assertIn("impact_grid", st.render_sequence)

    def test_confidence_driver_helper_still_available(self) -> None:
        assistant = self._load_assistant()
        cell = assistant._html_confidence_driver("Verified", "Lifecycle recorded for 15/15", "Raises confidence")
        self.assertIn("cv724-driver-cell", cell)

    def test_css_injected_via_global_app_shell(self) -> None:
        from tests.harness_ask_cadivor_stylesheet_loading import _install_streamlit_stub, simulate_authenticated_app_css_stack

        st = _install_streamlit_stub()
        simulate_authenticated_app_css_stack(st)
        self.assertTrue(
            any("cadivor-ask-cadivor-v2-css" in content for content, _kwargs, _side in st.markdown_calls)
        )
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in call for call in st.html_calls))

    def test_workflow_actions_use_border_containers(self) -> None:
        self.assertIn("st.container(border=True)", self.assistant_source)
        self.assertNotIn('st.container(key="cv725_workflow_actions")', self.assistant_source)

    def test_followups_use_border_container(self) -> None:
        self.assertIn("Continue the review", self.assistant_source)
        self.assertNotIn('st.container(key="cv725_followups")', self.assistant_source)

    def test_normal_question_assessment_visible_without_details(self) -> None:
        _, html, _st = self._render()
        self.assertIn("cv727-assessment-panel", html)
        self.assertIn("Engineering Assessment", html)
        self.assertNotIn("<details", html.lower())

    def test_detailed_question_keeps_assessment_visible(self) -> None:
        _, html, _st = self._render(question="Give me a comprehensive analysis of this BOM.")
        self.assertIn("Engineering Assessment", html)
        self.assertIn("cv727-assessment-panel", html)

    def test_native_decision_workspace_present(self) -> None:
        self.assertTrue(any(call[0] == [0.85, 1.15] for call in self.harness_st.columns_calls))
        self.assertIn("cv722-concise-answer", self.harness_html)
        self.assertNotIn("cv725-decision-workspace", self.harness_html)

    def test_no_duplicate_direct_answer_in_assessment(self) -> None:
        right = "\n".join(content for content, _kwargs, side in self.harness_st.markdown_calls if side == "right")
        self.assertEqual(self.harness_html.count("Review PC817 first."), 1)
        self.assertNotIn("Review PC817 first.", right)

    def test_no_sprint_7143_helpers(self) -> None:
        for helper in ("_format_engineering_prose", "_inline_engineering_format", "_render_structured_answer_sections"):
            self.assertNotIn(f"def {helper}", self.assistant_source)

    def test_dynamic_text_escaped(self) -> None:
        assistant = self._load_assistant()
        evil = '<script>alert(1)</script>'
        row = assistant._html_list_row(1, evil, variant="reason")
        self.assertNotIn("<script>", row)
        self.assertIn("&lt;script&gt;", row)

    def test_engineering_ai_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)
        self.assertNotIn("cv724-impact-grid", self.engineering_ai_source)

    def test_auth_paths_untouched(self) -> None:
        for marker in ("_queue_copilot_submission", "_apply_deferred_prompt_clear", "cv7142_ask_inflight"):
            self.assertIn(marker, self.assistant_source)

    def test_no_giant_html_card_shell_in_production_path(self) -> None:
        self.assertIn("_render_native_answer_column", self.assistant_source)
        self.assertIn("_render_native_assessment_column", self.assistant_source)
        self.assertIn("_build_concise_answer_html", self.assistant_source)
        self.assertNotIn("_render_presentation_html(primary_html)", self.assistant_source)

    def test_responsive_breakpoints_present(self) -> None:
        section = self.v2_css.split("Sprint 72.2.4", 1)[1]
        for width in ("1024px", "768px"):
            self.assertIn(f"@media (max-width: {width})", section)

    def test_harness_runs_without_openai(self) -> None:
        self.assertIn("Review PC817 first.", self.harness_html)
        self.assertNotIn("EngineeringAI.ask", self.harness_html)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
