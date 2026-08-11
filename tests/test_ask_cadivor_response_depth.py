"""Sprint 72.3 — Ask Cadivor concise response depth tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub

SAMPLE_ANSWER = (
    "### Intent\nGeneral Engineering Review\n\n"
    "### Direct Answer\n**First engineering review priority.** Review **U0** first because lifecycle exposure is highest.\n\n"
    "### Evidence\n"
    "- **U0** — lifecycle: Active; risk 90/100\n"
    "- **U1** — supplier concentration\n"
    "- **U2** — long lead time\n"
    "- **U3** — should not appear in concise surface\n\n"
    "### Recommended Actions\n"
    "Validate U0. Assign an owner. Secure a second source. Record the decision."
)

SAMPLE_CONTEXT = {
    "analysis": {"analysis_id": "a-1", "project_name": "Demo BOM"},
    "summary": {"health_score": 93, "release_posture": "focused_review"},
    "components": [
        {"part_number": "U0", "risk_score": 90, "supplier_count": 1, "stock_available": 10, "lead_time_weeks": 8},
        {"part_number": "U1", "risk_score": 80, "supplier_count": 1},
    ],
    "monitoring": [],
    "alternatives": [],
    "decisions": [],
    "coverage": {"score": 72},
}


class AskCadivorResponseDepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def setUp(self) -> None:
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)

    def _load_assistant(self):
        import src.components.engineering_assistant as assistant

        return assistant

    def _render(self, *, question: str, answer: str = SAMPLE_ANSWER, context: dict | None = None):
        st = install_ask_cadivor_streamlit_stub()
        assistant = self._load_assistant()
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=question,
                    answer=answer,
                    context=context or SAMPLE_CONTEXT,
                )
        html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
        return assistant, html, st

    def test_normal_question_uses_concise_response_depth(self) -> None:
        _, html, _st = self._render(question="What should I review first in this BOM?")
        self.assertIn("cv50-exchange", html)
        self.assertIn("cv722-concise-answer", html)
        self.assertNotIn("<details", html.lower())

    def test_direct_answer_visible_outside_expander(self) -> None:
        _, html, _ = self._render(question="What should I review first in this BOM?")
        self.assertIn("Review U0 first because lifecycle exposure is highest.", html)

    def test_concise_reasons_capped_at_three(self) -> None:
        assistant = self._load_assistant()
        reasons = assistant._concise_reason_items(
            "- **U0** — one\n- **U1** — two\n- **U2** — three\n- **U3** — four",
            [],
        )
        self.assertEqual(len(reasons), 3)

    def test_concise_actions_capped_at_three(self) -> None:
        assistant = self._load_assistant()
        actions = assistant._concise_action_items(
            "Validate U0. Assign an owner. Secure a second source. Record the decision."
        )
        self.assertEqual(len(actions), 3)

    def test_full_assessment_visible_for_normal_questions(self) -> None:
        _, html, st = self._render(question="What should I review first in this BOM?")
        self.assertIn("Engineering Assessment", html)

    def test_detailed_question_keeps_assessment_visible(self) -> None:
        _, html, st = self._render(question="Give me a comprehensive analysis of this BOM.")
        self.assertIn("Engineering Assessment", html)

    def test_direct_answer_not_duplicated_in_detailed_assessment(self) -> None:
        _, html, _ = self._render(question="What should I review first in this BOM?")
        self.assertEqual(html.count("Review U0 first because lifecycle exposure is highest."), 1)

    def test_evidence_not_rendered_three_times(self) -> None:
        _, html, _ = self._render(question="What should I review first in this BOM?")
        self.assertIn("key engineering reasons", html.lower())
        self.assertIn("evidence breakdown", html.lower())

    def test_confidence_not_duplicated_in_full_assessment(self) -> None:
        _, html, _ = self._render(question="What should I review first in this BOM?")
        self.assertIn("72%", html)
        self.assertNotIn("Evidence confidence", html)

    def test_timeline_not_synthesized_for_normal_review_question(self) -> None:
        assistant, html, _ = self._render(question="What should I review first in this BOM?")
        self.assertFalse(
            assistant._should_render_workflow_timeline(
                "What should I review first in this BOM?",
                detailed=False,
                workflow_text="",
                context=SAMPLE_CONTEXT,
            )
        )
        self.assertNotIn("Priority Timeline", html)

    def test_workflow_oriented_question_can_render_timeline(self) -> None:
        assistant, html, _ = self._render(question="What workflow steps should the engineering owner take next?")
        self.assertTrue(
            assistant._should_render_workflow_timeline(
                "What workflow steps should the engineering owner take next?",
                detailed=False,
                workflow_text="",
                context=SAMPLE_CONTEXT,
            )
        )
        self.assertIn("priority timeline", html.lower())

    def test_wants_detailed_response_shared_helper(self) -> None:
        self.assertIn("copilot_response_depth", self.assistant_source)
        self.assertIn("wants_detailed_response", self.assistant_source)

    def test_follow_up_and_history_helpers_remain(self) -> None:
        for marker in ("_render_follow_ups", "_render_conversation_history", "follow_up_suggestions"):
            self.assertIn(marker, self.assistant_source)

    def test_one_click_and_prompt_clear_paths_remain(self) -> None:
        for marker in (
            "_queue_copilot_submission",
            "_apply_deferred_prompt_clear",
            "_schedule_prompt_clear_on_next_run",
            "cv7142_ask_inflight",
            "_block_duplicate_submission",
        ):
            self.assertIn(marker, self.assistant_source)

    def test_no_sprint_7143_helpers(self) -> None:
        for helper in (
            "_format_engineering_prose",
            "_inline_engineering_format",
            "_render_structured_answer_sections",
        ):
            self.assertNotIn(f"def {helper}", self.assistant_source)

    def test_engineering_ai_ask_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)

    def test_arbitrary_html_stripped_from_native_markdown(self) -> None:
        assistant = self._load_assistant()
        evil = '<img src=x onerror=alert(1)>'
        self.assertNotIn("<img", assistant._plain_markdown(evil))


class AskCadivorResponseDepthIntegrationMarkers(unittest.TestCase):
    def test_render_response_uses_native_decision_workspace(self) -> None:
        source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        self.assertIn("_DECISION_COLUMN_RATIO", source)
        self.assertIn("st.columns(_DECISION_COLUMN_RATIO", source)
        self.assertIn("_render_decision_workspace", source)
        self.assertIn("_render_native_answer_column", source)
        self.assertIn("_render_native_assessment_column", source)
        self.assertIn("_normalize_action_items", source)
        self.assertNotIn("_build_decision_workspace_html", source)


if __name__ == "__main__":
    unittest.main()

def tearDownModule():
    from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules
    restore_ask_cadivor_streamlit_modules()

