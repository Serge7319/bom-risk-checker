"""Sprint 72.1 — Ask Cadivor response readability tests."""
from __future__ import annotations

import inspect
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

ORPHAN_CLASSES = (
    ".cv39-decision-grid",
    ".cv39-progress-wrap",
    ".cv39-progress",
    ".cv47-ranking-board",
    ".cv47-ranking-row",
    ".cv39-timeline-step",
    ".cv46-evidence-metric",
    ".cv46-evidence-metrics",
    ".cv46-empty-evidence",
    ".cv46-confidence-drivers",
)

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


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    markdown_calls: list[tuple[str, dict]] = []
    st.markdown = lambda content, **kwargs: markdown_calls.append((content, kwargs))
    st.columns = MagicMock(
        side_effect=lambda spec, gap=None: [_NullContext() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))]
    )
    st.form = lambda *args, **kwargs: _NullContext()
    st.text_area = lambda label, key, **kwargs: st.session_state.get(key, "")
    st.form_submit_button = MagicMock(return_value=False)
    st.status = lambda *args, **kwargs: _NullContext()
    st.warning = MagicMock()
    st.info = MagicMock()
    st.caption = MagicMock()
    st.button = MagicMock(return_value=False)
    st.link_button = MagicMock()
    st.expander = lambda *args, **kwargs: _NullContext()
    st.container = lambda **kwargs: _NullContext()
    sys.modules["streamlit"] = st
    return st, markdown_calls


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


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

    def test_orphan_class_css_exists(self) -> None:
        for selector in ORPHAN_CLASSES:
            self.assertIn(selector, self.v2_css, f"missing CSS for {selector}")

    def test_preline_css_preserves_line_breaks(self) -> None:
        self.assertIn(".cv-assistant-preline", self.v2_css)
        block = self.v2_css.split(".cv-assistant-preline", 1)[1].split("}", 1)[0]
        self.assertIn("white-space: pre-line", block)

    def test_response_wrapper_css_exists(self) -> None:
        self.assertIn(".cv-assistant-response", self.v2_css)
        block = self.v2_css.split(".cv-assistant-response", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid", block)
        self.assertIn("gap:", block)

    def test_concise_list_css_exists(self) -> None:
        self.assertIn(".cv722-reason-list", self.v2_css)
        self.assertIn(".cv722-action-list", self.v2_css)

    def test_existing_renderer_class_names_remain(self) -> None:
        for class_name in (
            "cv49-answer-card",
            "cv722-concise-answer",
            "cv722-summary-strip",
            "cv727-assessment-panel",
            "cv724-impact-cell",
            "cv46-evidence-board",
            "cv47-ranking-board",
            "cv39-timeline-step",
        ):
            self.assertIn(class_name, self.assistant_source)

    def test_response_wrapper_present_in_renderer(self) -> None:
        self.assertNotIn('<article class="cv-assistant-response">', self.assistant_source)
        self.assertIn("_render_response(", self.assistant_source)

    def test_preline_class_used_on_answer_text(self) -> None:
        self.assertIn('class="cv-assistant-preline"', self.assistant_source)
        self.assertIn("_render_conversational_answer", self.assistant_source)

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

    def test_render_response_preserves_newlines_in_html(self) -> None:
        st_stub, markdown_calls = _install_streamlit_stub()
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

        def _columns(spec, gap=None):
            count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
            return [_NullContext() for _ in range(count)]

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                with patch.object(st_stub, "columns", side_effect=_columns):
                    assistant._render_response(
                        question="What should I review first?",
                        answer=sample_answer,
                        context=context,
                    )
        markdown_html = "\n".join(
            content for content, _kwargs in markdown_calls if isinstance(content, str)
        )
        self.assertIn("cv-assistant-preline", markdown_html)
        self.assertIn("First paragraph line one.", markdown_html)
        self.assertNotIn('<article class="cv-assistant-response">', markdown_html)

    def test_plain_markdown_still_strips_bold_without_parser(self) -> None:
        assistant = self._load_assistant()
        self.assertEqual(
            assistant._plain_markdown("**Priority.** Review supplier evidence."),
            "Priority. Review supplier evidence.",
        )
        self.assertNotIn("def _format_engineering_prose", inspect.getsource(assistant))


if __name__ == "__main__":
    unittest.main()
