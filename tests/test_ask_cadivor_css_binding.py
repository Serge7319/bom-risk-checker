"""Sprint 72.2.9 — Ask Cadivor production CSS/DOM binding tests."""
from __future__ import annotations

import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
DESIGN_SYSTEM_V2_PY = REPO_ROOT / "src/ui/design_system_v2.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
PREMIUM_CSS = REPO_ROOT / "src/assets/css/premium.css"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"
STREAMLIT_HTML_CHUNK = (
    Path("/opt/anaconda3/lib/python3.12/site-packages/streamlit/static/static/js/2634.1249dc7a.chunk.js")
)

from tests.harness_ask_cadivor_stylesheet_loading import (
    _install_streamlit_stub,
    render_pc817_response_without_stylesheet,
    simulate_authenticated_app_css_stack,
)


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RecordingColumn:
    def __init__(self, side: str, st_module: types.ModuleType) -> None:
        self._side = side
        self._st = st_module

    def __enter__(self):
        self._st._active_column = self._side
        return self

    def __exit__(self, *args):
        self._st._active_column = None
        return False


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


CONTRACT_ROWS = (
    ("cv49-answer-card", ".cv49-answer-card", True),
    ("cv722-reason-row", ".cv722-reason-row", True),
    ("cv722-action-row", ".cv722-action-row", True),
    ("cv722-summary-strip", ".cv722-summary-strip", True),
    ("cv727-assessment-panel", ".cv727-assessment-panel", True),
    ("cv724-impact-grid", ".cv724-impact-grid", True),
    ("cv724-impact-cell", ".cv724-impact-cell", True),
    ("cv724-driver-grid", ".cv724-driver-grid", True),
    ("cv724-driver-cell", ".cv724-driver-cell", True),
    ("cv46-evidence-board", ".cv46-evidence-board", True),
    ("cv46-evidence-card", ".cv46-evidence-card", True),
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
        st = _install_streamlit_stub()
        simulate_authenticated_app_css_stack(st)
        stylesheet_markdown = [
            content for content, _kwargs, _side in st.markdown_calls if "cadivor-ask-cadivor-v2-css" in content
        ]
        self.assertEqual(len(stylesheet_markdown), 1)
        self.assertTrue(stylesheet_markdown[0].startswith("<style id='cadivor-ask-cadivor-v2-css'>"))
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in call for call in st.html_calls))
        inject_block = self.ds_v2_source.split("def inject_ask_cadivor_v2_css", 1)[1]
        self.assertIn("st.markdown(", inject_block)
        self.assertIn("unsafe_allow_html=True", inject_block)
        self.assertNotIn("st.html(", inject_block)

    def test_streamlit_html_sanitizer_strips_bare_style_tags(self) -> None:
        if not STREAMLIT_HTML_CHUNK.is_file():
            self.skipTest("Streamlit frontend chunk unavailable in this environment")
        chunk = STREAMLIT_HTML_CHUNK.read_text(encoding="utf-8")
        self.assertIn('data-testid":"stHtml"', chunk)
        self.assertIn("sanitize", chunk)
        self.assertIn("FORCE_BODY", chunk)
        self.assertIn("empty-html", chunk)

    def test_premium_css_hides_style_containers_without_invalidating_markdown_styles(self) -> None:
        self.assertIn('div[data-testid="stElementContainer"]:has(style)', self.premium_css)
        self.assertIn('div[data-testid="stMarkdownContainer"]:has(style:only-child)', self.premium_css)
        self.assertIn("display: none", self.premium_css.split(":has(style)", 1)[1])

    def test_response_renderer_does_not_inject_stylesheet(self) -> None:
        st = _install_streamlit_stub()
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
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in call for call in st.html_calls))

    def test_dom_class_hierarchy_matches_727_selectors(self) -> None:
        st = _install_streamlit_stub()
        simulate_authenticated_app_css_stack(st)
        render_pc817_response_without_stylesheet(st)
        left = "\n".join(content for content, _kwargs, side in st.markdown_calls if side == "left")
        right = "\n".join(content for content, _kwargs, side in st.markdown_calls if side == "right")
        for class_name in (
            "cv49-answer-card",
            "cv722-reason-row",
            "cv722-action-row",
            "cv722-summary-strip",
        ):
            self.assertIn(class_name, left, class_name)
        for class_name in ("cv727-assessment-panel", "cv724-impact-grid", "cv724-driver-grid", "cv46-evidence-board", "cv46-evidence-card"):
            self.assertIn(class_name, right, class_name)

    def test_selector_contract_table(self) -> None:
        st = _install_streamlit_stub()
        simulate_authenticated_app_css_stack(st)
        html, _response_calls = render_pc817_response_without_stylesheet(st)
        for class_name, selector, _required in CONTRACT_ROWS:
            html_present = class_name in html
            css_present = selector in self.v2_css
            standalone_rule = bool(re.search(rf"(?<!\.){re.escape(selector[1:])}\s*\{{", self.v2_css))
            shell_only = bool(re.search(rf"\.cv-assistant-shell[^\{{{{]*{re.escape(selector[1:])}", self.v2_css))
            ancestry_ok = standalone_rule or ".st-key-cv727_decision_workspace" in self.v2_css or not shell_only
            self.assertTrue(html_present, f"{class_name} missing from rendered HTML")
            self.assertTrue(css_present, f"{selector} missing from ask_cadivor_v2.css")
            self.assertTrue(ancestry_ok, f"{selector} depends on removed shell-only ancestry")

    def test_engineering_assistant_has_no_runtime_stylesheet_injection(self) -> None:
        self.assertNotIn("_inject_ask_cadivor_v2_styles", self.assistant_source)
        self.assertNotIn("_inject_presentation_stylesheet", self.assistant_source)

    def test_provider_auth_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)
        self.assertNotIn("st.markdown(markup, unsafe_allow_html=True)", self.engineering_ai_source)


if __name__ == "__main__":
    unittest.main()
