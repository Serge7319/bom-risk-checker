"""Sprint 72.3 — Ask Cadivor production CSS/DOM binding tests (native renderer)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
DESIGN_SYSTEM_V2_PY = REPO_ROOT / "src/ui/design_system_v2.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
PREMIUM_CSS = REPO_ROOT / "src/assets/css/premium.css"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION
from tests.harness_ask_cadivor_stylesheet_loading import (
    render_pc817_response_without_stylesheet,
    simulate_authenticated_app_css_stack,
)


class AskCadivorCssBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.ds_v2_source = DESIGN_SYSTEM_V2_PY.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.premium_css = PREMIUM_CSS.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def test_global_stylesheet_injected_via_st_markdown_not_st_html(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        simulate_authenticated_app_css_stack(st)
        stylesheet_markdown = [
            content for content, _kwargs, _side in st.markdown_calls if "cadivor-ask-cadivor-v2-css" in content
        ]
        self.assertEqual(len(stylesheet_markdown), 1)
        self.assertTrue(stylesheet_markdown[0].startswith("<style id='cadivor-ask-cadivor-v2-css'>"))
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in call for call in st.html_calls))

    def test_premium_css_hides_style_containers_without_invalidating_markdown_styles(self) -> None:
        self.assertIn('div[data-testid="stElementContainer"]:has(style)', self.premium_css)
        self.assertIn('div[data-testid="stMarkdownContainer"]:has(style:only-child)', self.premium_css)

    def test_response_renderer_does_not_inject_stylesheet(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        simulate_authenticated_app_css_stack(st)
        stylesheet_before = sum(
            1 for content, _kwargs, _side in st.markdown_calls if "cadivor-ask-cadivor-v2-css" in content
        )
        _, response_calls = render_pc817_response_without_stylesheet(st)
        stylesheet_after = sum(
            1 for content, _kwargs, _side in st.markdown_calls if "cadivor-ask-cadivor-v2-css" in content
        )
        self.assertEqual(stylesheet_before, 1)
        self.assertEqual(stylesheet_after, 1)
        self.assertTrue(all("<style" not in content.lower() for content, _kwargs, _side in response_calls))

    def test_native_workspace_structure(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        simulate_authenticated_app_css_stack(st)
        render_pc817_response_without_stylesheet(st)
        html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
        left = "\n".join(content for content, _kwargs, side in st.markdown_calls if side == "left")
        right = "\n".join(content for content, _kwargs, side in st.markdown_calls if side == "right")
        self.assertTrue(any(call[0] == [0.85, 1.15] for call in st.columns_calls))
        self.assertIn("cv722-concise-answer", html)
        self.assertIn("cv727-assessment-panel", right)
        self.assertIn("Review PC817 first.", left)
        self.assertIn("Engineering Assessment", right)
        self.assertIn("PC817", html)
        self.assertNotIn("st.container(key=", self.assistant_source)

    def test_engineering_assistant_has_no_runtime_stylesheet_injection(self) -> None:
        self.assertNotIn("_inject_ask_cadivor_v2_styles", self.assistant_source)
        self.assertNotIn("_inject_presentation_stylesheet", self.assistant_source)

    def test_provider_auth_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)


if __name__ == "__main__":
    unittest.main()

def tearDownModule():
    from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules
    restore_ask_cadivor_streamlit_modules()

