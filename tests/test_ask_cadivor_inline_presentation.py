"""Sprint 72.3.6 — Self-contained inline Ask Cadivor response presentation tests."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
RESPONSE_STYLES_PY = REPO_ROOT / "src/components/ask_cadivor_response_styles.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


def _render_pc817_html(*, block_css: bool = False) -> str:
    st = install_ask_cadivor_streamlit_stub()
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    patches = [
        patch.object(assistant, "_render_response_scroll_anchor"),
        patch.object(assistant, "_render_quick_actions"),
    ]
    if block_css:
        patches.append(
            patch(
                "src.ui.design_system_v2.load_ask_cadivor_v2_css",
                side_effect=OSError("simulated missing stylesheet"),
            )
        )
        patches.append(
            patch(
                "src.components.engineering_assistant._ask_runtime_css_metadata",
                return_value={
                    "css_path": "/missing/ask_cadivor_v2.css",
                    "css_exists": False,
                    "css_bytes": 0,
                    "css_sha256": "unknown",
                    "css_text": "",
                },
            )
        )

    from contextlib import ExitStack

    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        assistant._render_response(
            question=PC817_QUESTION,
            answer=PC817_ANSWER,
            context=PC817_CONTEXT,
        )
    return "\n".join(content for content, _kwargs, _side in st.markdown_calls)


class AskCadivorInlinePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _render_pc817_html()
        cls.html_without_css = _render_pc817_html(block_css=True)
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.styles_source = RESPONSE_STYLES_PY.read_text(encoding="utf-8")

    def test_reason_rows_have_inline_grid_and_border(self) -> None:
        rows = re.findall(r'<li class="cv722-reason-row" style="([^"]+)"', self.html)
        self.assertGreaterEqual(len(rows), 3)
        for style in rows:
            normalized = style.replace(" ", "")
            self.assertIn("display:grid", normalized)
            self.assertIn("border:1pxsolid", normalized)

    def test_action_rows_have_inline_accent_styles(self) -> None:
        rows = re.findall(r'<li class="cv722-action-row" style="([^"]+)"', self.html)
        self.assertGreaterEqual(len(rows), 3)
        for style in rows:
            self.assertIn("display:grid", style.replace(" ", ""))
            self.assertIn("#dbeafe", style)

    def test_summary_strip_has_inline_three_column_grid(self) -> None:
        match = re.search(r'class="cv722-summary-strip[^"]*"[^>]*style="([^"]+)"', self.html)
        self.assertIsNotNone(match)
        style = match.group(1).replace(" ", "")
        self.assertIn("grid-template-columns:repeat(3", style)
        self.assertEqual(len(re.findall(r'class="cv722-summary-item', self.html)), 3)

    def test_impact_and_driver_cells_have_inline_card_styles(self) -> None:
        self.assertEqual(self.html.count("cv724-impact-cell"), 4)
        self.assertGreaterEqual(self.html.count("cv724-driver-cell"), 1)
        for pattern in (r'class="cv724-impact-cell" style="([^"]+)"', r'class="cv724-driver-cell" style="([^"]+)"'):
            for style in re.findall(pattern, self.html):
                self.assertIn("border:1pxsolid", style.replace(" ", ""))

    def test_evidence_cards_have_inline_layout_and_separate_component_status(self) -> None:
        cards = re.findall(r'<article class="cv46-evidence-card" style="([^"]+)"', self.html)
        self.assertEqual(len(cards), 3)
        self.assertGreaterEqual(
            len(re.findall(r'<div class="cv46-evidence-component" style="', self.html)),
            3,
        )
        self.assertGreaterEqual(
            len(re.findall(r'<div class="cv46-evidence-status" style="', self.html)),
            3,
        )

    def test_assessment_panel_and_exchange_have_inline_shell_styles(self) -> None:
        self.assertRegex(self.html, r'class="cv50-exchange" style="[^"]*display:grid')
        self.assertRegex(self.html, r'class="cv727-assessment-panel" style="[^"]*display:grid')

    def test_no_style_tag_inside_response_surfaces(self) -> None:
        lowered = self.html.lower()
        self.assertNotIn("<style", lowered)

    def test_no_concatenated_review_strings(self) -> None:
        for token in ("PC817Review", "BZX55C5V1Review", "DRV8825Review"):
            self.assertNotIn(token, self.html)

    def test_native_column_ratio_preserved(self) -> None:
        self.assertIn("_DECISION_COLUMN_RATIO = [0.85, 1.15]", self.assistant_source)

    def test_static_style_helpers_have_no_dynamic_interpolation(self) -> None:
        self.assertNotIn("{", self.styles_source)
        self.assertNotIn("html.escape", self.styles_source)
        self.assertNotIn("f'", self.styles_source)

    def test_core_presentation_survives_missing_external_css(self) -> None:
        for marker in (
            'class="cv722-reason-row" style=',
            'class="cv722-action-row" style=',
            'class="cv722-summary-strip',
            'class="cv724-impact-cell" style=',
            'class="cv724-driver-cell" style=',
            'class="cv46-evidence-card" style=',
            'class="cv727-assessment-panel" style=',
        ):
            self.assertIn(marker, self.html_without_css)
        self.assertGreaterEqual(self.html_without_css.count("cv722-reason-row"), 3)
        self.assertGreaterEqual(self.html_without_css.count("cv722-action-row"), 3)
        self.assertEqual(self.html_without_css.count("cv724-impact-cell"), 4)
        self.assertEqual(len(re.findall(r'<article class="cv46-evidence-card"', self.html_without_css)), 3)
        self.assertEqual(self.html, self.html_without_css)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
