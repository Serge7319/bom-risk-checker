"""Sprint 72.2.4 — Ask Cadivor production presentation recovery tests."""
from __future__ import annotations

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

from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION, render_pc817_harness


def _install_streamlit_stub():
    st = types.ModuleType("streamlit")
    st.session_state = {}
    markdown_calls: list[tuple[str, dict]] = []
    html_calls: list[str] = []
    expander_calls: list[tuple[tuple, dict]] = []

    st.markdown = lambda content, **kwargs: markdown_calls.append((content, kwargs))
    st.html = lambda content, **kwargs: html_calls.append(str(content))
    st.expander = lambda *args, **kwargs: (expander_calls.append((args, kwargs)) or _NullContext())
    st.columns = MagicMock(
        side_effect=lambda spec, gap=None: [_NullContext() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))]
    )
    st.container = lambda **kwargs: _NullContext()

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(script_run_id="run-a")
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    components.html = lambda content, **kwargs: html_calls.append(str(content))

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st, markdown_calls, html_calls, expander_calls


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AskCadivorPresentationRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")
        cls.harness_html = render_pc817_harness()

    def setUp(self) -> None:
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)

    def _load_assistant(self):
        import src.components.engineering_assistant as assistant

        return assistant

    def _render(self, *, question: str = PC817_QUESTION, answer: str = PC817_ANSWER):
        st_stub, markdown_calls, html_calls, expander_calls = _install_streamlit_stub()
        assistant = self._load_assistant()
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(question=question, answer=answer, context=PC817_CONTEXT)
        html = "\n".join(content for content, _kwargs in markdown_calls if isinstance(content, str))
        return assistant, html, html_calls, expander_calls

    def test_question_label_and_question_are_separate(self) -> None:
        html = self.harness_html
        self.assertIn("cv50-you-asked-label", html)
        self.assertIn("cv50-you-asked-question", html)
        self.assertRegex(
            html,
            r'class="cv50-you-asked-label">You asked</div>\s*<div class="cv50-you-asked-question">',
        )

    def test_direct_answer_in_primary_surface(self) -> None:
        html = self.harness_html
        self.assertIn("cv722-direct-answer-title", html)
        self.assertIn("Review PC817 first.", html)

    def test_single_numbering_for_reasons(self) -> None:
        html = self.harness_html
        self.assertNotIn('<ol class="cv722-reason-list">', html)
        self.assertIn('<ul class="cv722-reason-list">', html)
        self.assertNotRegex(html, r">\s*1\s*</div>\s*<div class=\"cv722-row-body\"><p>1")

    def test_single_numbering_for_actions(self) -> None:
        html = self.harness_html
        self.assertNotIn('<ol class="cv722-action-list">', html)
        self.assertIn('<ul class="cv722-action-list">', html)

    def test_kpi_semantic_block_elements(self) -> None:
        html = self.harness_html
        self.assertRegex(html, r'class="cv722-summary-label">Status</div>')
        self.assertRegex(html, r'class="cv722-summary-value">[^<]+</div>')
        self.assertRegex(html, r'class="cv722-summary-note">[^<]+</div>')

    def test_kpi_css_shell_independent(self) -> None:
        block = self.v2_css.split("Sprint 72.2.4", 1)[1]
        for selector in (".cv722-summary-strip", ".cv722-summary-label", ".cv724-impact-grid"):
            self.assertIn(selector, block)
            rule = block.split(selector, 1)[1].split("}", 1)[0]
            self.assertNotIn(".cv-assistant-shell", rule)

    def test_impact_cells_use_block_semantics(self) -> None:
        _, html, _, _ = self._render()
        self.assertIn("cv724-impact-cell", html)
        self.assertRegex(html, r'class="cv39-impact-label">[^<]+</div>')
        self.assertRegex(html, r'class="cv39-impact-value">[^<]+</div>')
        self.assertRegex(html, r'class="cv39-impact-note">[^<]+</div>')

    def test_confidence_driver_cells_separate(self) -> None:
        assistant = self._load_assistant()
        cell = assistant._html_confidence_driver("Verified", "Lifecycle recorded for 15/15", "Raises confidence")
        self.assertIn("cv724-driver-cell", cell)
        self.assertIn('class="cv46-driver-label">Verified</div>', cell)
        self.assertNotRegex(cell, r"VerifiedLifecycle")

    def test_css_injected_via_st_html(self) -> None:
        _st_stub, _markdown_calls, html_calls, _ = _install_streamlit_stub()
        assistant = self._load_assistant()
        assistant._inject_ask_cadivor_v2_styles(force=True)
        self.assertTrue(any("cadivor-ask-cadivor-v2-css" in call for call in html_calls))

    def test_workflow_actions_compact_container(self) -> None:
        self.assertIn("cv724-workflow-actions", self.assistant_source)
        self.assertIn('key="cv725_workflow_actions"', self.assistant_source)
        self.assertIn(".st-key-cv727_decision_workspace", self.v2_css)

    def test_followups_separated_panel(self) -> None:
        self.assertIn("cv723-followups-panel", self.assistant_source)
        self.assertIn('key="cv725_followups"', self.assistant_source)

    def test_normal_question_assessment_visible_without_details(self) -> None:
        _, html, _, expander_calls = self._render()
        self.assertEqual(len(expander_calls), 0)
        self.assertIn("cv727-assessment-panel", html)
        self.assertNotIn("<details", html.lower())

    def test_detailed_question_keeps_assessment_visible(self) -> None:
        _, html, _, expander_calls = self._render(question="Give me a comprehensive analysis of this BOM.")
        self.assertEqual(len(expander_calls), 0)
        self.assertIn("cv727-assessment-panel", html)

    def test_native_decision_workspace_present(self) -> None:
        html = self.harness_html
        self.assertIn("cv727-assessment-panel", html)
        self.assertIn("cv722-concise-answer", html)
        self.assertIn("cv722-summary-strip", html)
        self.assertIn("Sprint 72.2.7", self.v2_css)
        self.assertNotIn("cv725-decision-workspace", html)

    def test_no_duplicate_direct_answer_in_assessment(self) -> None:
        html = self.harness_html
        self.assertIn("cv724-impact-grid", html)
        markup = html.split("</style>")[-1]
        assessment = markup.split("cv727-assessment-panel", 1)[1]
        self.assertNotIn('class="cv722-direct-answer-text"', assessment)
        self.assertEqual(markup.count("Review PC817 first."), 1)

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

    def test_no_split_article_wrapper(self) -> None:
        self.assertNotIn('<article class="cv-assistant-response">', self.assistant_source)

    def test_responsive_breakpoints_present(self) -> None:
        section = self.v2_css.split("Sprint 72.2.4", 1)[1]
        for width in ("1024px", "768px", "390px"):
            self.assertIn(f"@media (max-width: {width})", section)

    def test_harness_runs_without_openai(self) -> None:
        self.assertIn("Review PC817 first.", self.harness_html)
        self.assertNotIn("EngineeringAI.ask", self.harness_html)


if __name__ == "__main__":
    unittest.main()
