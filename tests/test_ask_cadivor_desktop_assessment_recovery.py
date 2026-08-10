"""Sprint 72.2.5.2 — Desktop assessment visibility + CSS binding recovery tests."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
PREVIEW_ARTIFACT = REPO_ROOT / "tests/artifacts/ask_cadivor_pc817_preview.html"


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _install_streamlit_stub():
    st = types.ModuleType("streamlit")
    st.session_state = {}
    markdown_calls: list[tuple[str, dict]] = []
    html_calls: list[str] = []

    st.markdown = lambda content, **kwargs: markdown_calls.append((str(content), dict(kwargs)))
    st.html = lambda content, **kwargs: html_calls.append(str(content))
    st.expander = lambda *args, **kwargs: _NullContext()
    st.columns = MagicMock(
        side_effect=lambda spec: [MagicMock() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))]
    )
    st.container = lambda **kwargs: _NullContext()

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(script_run_id="test-run")
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    components.html = lambda content, **kwargs: html_calls.append(str(content))

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st, markdown_calls, html_calls


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


class AskCadivorDesktopAssessmentRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")

    def _render_pc817(self) -> tuple[str, list[str], list[tuple[str, dict]]]:
        st, markdown_calls, html_calls = _install_streamlit_stub()
        assistant = _load_assistant()
        from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        html = "\n".join(content for content, _kwargs in markdown_calls)
        return html, html_calls, markdown_calls

    def test_normal_desktop_response_uses_open_details(self) -> None:
        html, _, _ = self._render_pc817()
        self.assertIn('class="cv725-assessment-details" open', html)
        self.assertNotRegex(html, r'class="cv725-assessment-details">\s*<summary')

    def test_stylesheet_injection_separate_from_workspace(self) -> None:
        html, html_calls, markdown_calls = self._render_pc817()
        workspace_markdown = next(
            (content for content, _kwargs in markdown_calls if "cv725-decision-workspace" in content),
            "",
        )
        self.assertTrue(any("cadivor-ask-cadivor-v2-css" in call for call in html_calls))
        self.assertNotIn("<style", workspace_markdown.lower())
        self.assertIn(".cv725-decision-workspace", self.v2_css)
        self.assertIn("cv725-decision-workspace", html)

    def test_css_injection_uses_st_html(self) -> None:
        _install_streamlit_stub()
        assistant = _load_assistant()
        _, _markdown_calls, html_calls = _install_streamlit_stub()
        assistant = _load_assistant()
        assistant._inject_ask_cadivor_v2_styles(force=True)
        self.assertTrue(any("cadivor-ask-cadivor-v2-css" in call for call in html_calls))

    def test_css_injection_does_not_use_parent_document_mutation(self) -> None:
        inject_block = self.assistant_source.split("def _inject_ask_cadivor_v2_styles", 1)[1].split("def _render_context_header", 1)[0]
        self.assertIn("_inject_presentation_stylesheet", inject_block)
        self.assertNotIn("window.parent.document", inject_block)

    def test_desktop_grid_rule_present(self) -> None:
        section = self.v2_css.split("Sprint 72.2.5", 1)[1]
        self.assertIn("grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr)", section)
        desktop_block = section.split("@media (min-width: 1025px)", 1)[1]
        self.assertIn(".cv725-assessment-summary", desktop_block)
        self.assertIn("display: none !important", desktop_block)

    def test_mobile_stack_rule_present(self) -> None:
        section = self.v2_css.split("Sprint 72.2.5", 1)[1]
        self.assertIn("@media (max-width: 1024px)", section)
        self.assertIn("grid-template-columns: 1fr", section)

    def test_preview_artifact_exists(self) -> None:
        self.assertTrue(PREVIEW_ARTIFACT.exists(), f"Missing preview artifact: {PREVIEW_ARTIFACT}")
        preview = PREVIEW_ARTIFACT.read_text(encoding="utf-8")
        self.assertIn("cv725-decision-workspace", preview)
        self.assertIn("ask_cadivor_v2.css", preview)
        self.assertIn('class="cv725-assessment-details" open', preview)

    def test_no_duplicate_direct_answer_in_primary_surface(self) -> None:
        html, _, _ = self._render_pc817()
        markup = html.split("</style>")[-1]
        self.assertEqual(markup.count("Review PC817 first."), 1)
        self.assertNotIn('class="cv722-direct-answer-text"', markup)

    def test_evidence_breakdown_structurally_separated(self) -> None:
        html, _, _ = self._render_pc817()
        for component in ("PC817", "BZX55C5V1", "DRV8825"):
            self.assertIn(f'class="cv46-evidence-component">{component}</span>', html)
        self.assertEqual(html.count('class="cv46-evidence-status">Review</span>'), 3)
        self.assertEqual(html.count('class="cv46-evidence-label">Evidence</div>'), 3)
        for bad in ("PC817Review", "BZX55C5V1Review", "DRV8825Review"):
            self.assertNotIn(bad, html)

    def test_supplementary_direct_answer_preserves_explanation(self) -> None:
        assistant = _load_assistant()
        headline = "Review PC817 first."
        long_form = (
            "Review PC817 first because it represents the most immediate lifecycle and sourcing exposure in this BOM."
        )
        supplementary = assistant._supplementary_direct_answer_text(headline, long_form)
        self.assertEqual(
            supplementary,
            "because it represents the most immediate lifecycle and sourcing exposure in this BOM.",
        )
        self.assertEqual(assistant._supplementary_direct_answer_text(headline, headline), "")

    def test_desktop_workspace_still_present(self) -> None:
        html, _, _ = self._render_pc817()
        self.assertIn("cv725-decision-workspace", html)
        self.assertIn("cv725-decision-primary", html)
        self.assertIn("cv725-decision-assessment", html)
        self.assertIn("cv724-impact-grid", html)


if __name__ == "__main__":
    unittest.main()
