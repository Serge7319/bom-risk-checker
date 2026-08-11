"""Sprint 72.3.1 — Streamlit render-sequence + native column workspace tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
PREMIUM_CSS = REPO_ROOT / "src/assets/css/premium.css"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


class AskCadivorStreamlitRenderSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.premium_css = PREMIUM_CSS.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")

    def test_assessment_panel_uses_native_renderer(self) -> None:
        self.assertIn("st.container(border=True)", self.assistant_source)
        self.assertIn("_render_native_assessment_column", self.assistant_source)
        self.assertNotIn('key="cv_assessment_panel"', self.assistant_source)

    def test_response_renderer_emits_no_stylesheet(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        assistant = _load_assistant()
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        self.assertTrue(all("<style" not in item.lower() for item, _kwargs, _side in st.markdown_calls))
        self.assertTrue(any(call[0] == [0.85, 1.15] for call in st.columns_calls))
        self.assertIn("reason_card", st.render_sequence)
        self.assertIn("impact_grid", st.render_sequence)

    def test_approved_workspace_content_preserved(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        assistant = _load_assistant()
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
        left = "\n".join(content for content, _kwargs, side in st.markdown_calls if side == "left")
        right = "\n".join(content for content, _kwargs, side in st.markdown_calls if side == "right")
        self.assertIn("Engineering Assessment", right)
        self.assertIn("Review PC817 first.", left)
        self.assertIn("PC817", html)
        self.assertIn(".cv46-evidence-card-header", self.v2_css)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
