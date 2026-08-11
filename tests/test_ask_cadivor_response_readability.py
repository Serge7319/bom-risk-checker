"""Sprint 72.3 — Ask Cadivor native response readability tests."""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub

REVIVED_7143_HELPERS = (
    "_format_engineering_prose",
    "_inline_engineering_format",
    "_render_structured_answer_sections",
    "_render_response_section_card",
    "_section_variant",
    "_profile_consumed_sections",
    "_emphasize_part_numbers",
    "_known_part_numbers",
)


class AskCadivorResponseReadabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def _load_assistant(self):
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        import src.components.engineering_assistant as assistant

        return assistant

    def test_shell_independent_css_exists(self) -> None:
        section = self.v2_css.split("Sprint 72.2.4", 1)[1]
        for selector in (
            ".cv50-exchange",
            ".cv722-reason-list",
            ".cv722-summary-strip",
            ".cv46-evidence-card-header",
        ):
            self.assertIn(selector, section)

    def test_production_renderer_uses_native_workspace(self) -> None:
        self.assertIn("_render_native_answer_column", self.assistant_source)
        self.assertIn("_render_native_assessment_column", self.assistant_source)
        self.assertIn("_render_decision_workspace", self.assistant_source)
        self.assertNotIn("_build_decision_workspace_html", self.assistant_source)

    def test_sprint_7143_formatter_helpers_not_present(self) -> None:
        for helper in REVIVED_7143_HELPERS:
            self.assertNotIn(f"def {helper}", self.assistant_source)

    def test_engineering_ai_ask_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)
        self.assertNotIn("cv-assistant-preline", self.engineering_ai_source)

    def test_queue_and_prompt_clear_paths_untouched(self) -> None:
        for marker in (
            "_queue_copilot_submission",
            "_CLEAR_PROMPT_ON_NEXT_RUN_KEY",
            "_apply_deferred_prompt_clear",
            "_schedule_prompt_clear_on_next_run",
            "cv7142_ask_inflight",
            "st.rerun()",
        ):
            self.assertIn(marker, self.assistant_source)

    def test_render_response_preserves_readable_text(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        assistant = self._load_assistant()
        sample_answer = (
            "### Executive Summary\n"
            "First paragraph line one.\n"
            "Second paragraph line two.\n\n"
            "### Evidence\n"
            "- **U1** — lifecycle risk\n"
        )
        context = {
            "analysis": {"analysis_id": "a1"},
            "components": [{"part_number": "U1", "risk_score": 90}],
            "coverage": {"score": 72},
        }
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question="What should I review first?",
                    answer=sample_answer,
                    context=context,
                )
        markdown_html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
        self.assertIn("First paragraph line one.", markdown_html)
        self.assertNotIn('<article class="cv-assistant-response">', markdown_html)
        self.assertNotIn("<style", markdown_html.lower())

    def test_plain_markdown_still_strips_bold_without_parser(self) -> None:
        assistant = self._load_assistant()
        self.assertEqual(
            assistant._plain_markdown("**Priority.** Review supplier evidence."),
            "Priority. Review supplier evidence.",
        )
        self.assertNotIn("def _format_engineering_prose", inspect.getsource(assistant))


if __name__ == "__main__":
    unittest.main()

def tearDownModule():
    from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules
    restore_ask_cadivor_streamlit_modules()

