"""Sprint 72.2.5.1 — Ask Cadivor HTML rendering boundary tests."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"


def _load_assistant():
    st = types.ModuleType("streamlit")
    st.session_state = {}
    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = types.ModuleType("streamlit.runtime")
    sys.modules["streamlit.runtime.scriptrunner"] = types.ModuleType("streamlit.runtime.scriptrunner")
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = types.ModuleType("streamlit.components.v1")
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


class AskCadivorHtmlRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant = _load_assistant()

    def test_indented_workspace_html_normalizes_to_column_zero(self) -> None:
        raw = self.assistant._build_decision_workspace_html(
            detailed=False,
            primary_html=self.assistant._build_concise_answer_html(
                headline="Review PC817 first.",
                answer_text="Review PC817 first.",
                reason_items=["PC817 has medium risk."],
                action_items=["Investigate alternative suppliers for PC817."],
            ),
            summary_html=self.assistant._build_decision_summary_html(
                status="Review required",
                tone="warning",
                priority_part="PC817",
                confidence_score=56,
                confidence_label="Medium",
            ),
            assessment_html='<div class="cv724-impact-grid"></div>',
        )
        self.assertTrue(raw.lstrip().startswith("<div") or raw.strip().startswith("<div"))
        self.assertRegex(raw, r"^\s{4,}<div class=\"cv725-decision-workspace\">")
        normalized = self.assistant._normalize_presentation_html(raw)
        self.assertTrue(normalized.startswith("<div class=\"cv725-decision-workspace\">"))
        self.assertNotRegex(normalized, r"^\s")

    def test_render_presentation_html_uses_unsafe_allow_html(self) -> None:
        markdown_calls: list[tuple[str, dict]] = []
        st = sys.modules["streamlit"]
        original = getattr(st, "markdown", None)
        st.markdown = lambda content, **kwargs: markdown_calls.append((str(content), dict(kwargs)))
        try:
            self.assistant._render_presentation_html(
                """
                <section class="cv49-answer-card cv722-concise-answer">
                  <div class="cv49-answer-kicker">Cadivor Answer</div>
                </section>
                """
            )
        finally:
            if original is not None:
                st.markdown = original
        self.assertEqual(len(markdown_calls), 1)
        content, kwargs = markdown_calls[0]
        self.assertTrue(content.startswith("<section class=\"cv49-answer-card"))
        self.assertTrue(kwargs.get("unsafe_allow_html"))

    def test_production_whitespace_regression(self) -> None:
        """Reproduce Sprint 72.2.5 production failure: indented HTML must not reach Streamlit raw."""
        indented = """
            <section class="cv49-answer-card cv722-concise-answer">
              <div class="cv49-answer-kicker">Cadivor Answer</div>
            </section>
            """
        normalized = self.assistant._normalize_presentation_html(indented)
        self.assertNotRegex(normalized, r"^\s")
        self.assertIn("cv722-concise-answer", normalized)
        self.assertNotIn("&lt;section", normalized)

    def test_decision_workspace_rendered_via_presentation_html(self) -> None:
        self.assertIn("_render_presentation_html(", self.assistant_source)
        self.assertIn("_build_decision_workspace_html(", self.assistant_source)
        self.assertIn("_normalize_presentation_html(", self.assistant_source)

    def test_desktop_css_contract_present(self) -> None:
        section = self.v2_css.split("Sprint 72.2.5", 1)[1]
        self.assertIn(".cv725-decision-workspace", section)
        self.assertIn("grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr)", section)
        self.assertIn("@media (min-width: 1025px)", section)
        self.assertIn("@media (max-width: 1024px)", section)


if __name__ == "__main__":
    unittest.main()
