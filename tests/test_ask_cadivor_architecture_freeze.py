"""Sprint 72.3.7 — Architecture freeze regression for production-proven Ask Cadivor."""
from __future__ import annotations

import re
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
RESPONSE_STYLES_PY = REPO_ROOT / "src/components/ask_cadivor_response_styles.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

FROZEN_STYLE_CONSTANTS = (
    "CV50_EXCHANGE_STYLE",
    "CV49_ANSWER_CARD_STYLE",
    "CV722_REASON_ROW_STYLE",
    "CV722_ACTION_ROW_STYLE",
    "CV722_SUMMARY_STRIP_STYLE",
    "CV727_ASSESSMENT_PANEL_STYLE",
    "CV724_IMPACT_GRID_STYLE",
    "CV724_DRIVER_GRID_STYLE",
    "CV46_EVIDENCE_BOARD_STYLE",
    "CV46_EVIDENCE_CARD_STYLE",
)


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

    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        assistant._render_response(
            question=PC817_QUESTION,
            answer=PC817_ANSWER,
            context=PC817_CONTEXT,
        )
    return "\n".join(content for content, _kwargs, _side in st.markdown_calls)


class AskCadivorArchitectureFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _render_pc817_html()
        cls.html_without_css = _render_pc817_html(block_css=True)
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.styles_source = RESPONSE_STYLES_PY.read_text(encoding="utf-8")

    def test_decision_column_ratio_frozen(self) -> None:
        self.assertIn("_DECISION_COLUMN_RATIO = [0.85, 1.15]", self.assistant_source)

    def test_critical_style_constants_exist(self) -> None:
        for name in FROZEN_STYLE_CONSTANTS:
            self.assertIn(name, self.styles_source)

    def test_core_surfaces_use_inline_presentation_styles(self) -> None:
        for marker in (
            'class="cv50-exchange" style=',
            'class="cv49-answer-card cv722-concise-answer" style=',
            'class="cv722-reason-row" style=',
            'class="cv722-action-row" style=',
            'class="cv722-summary-strip',
            'class="cv727-assessment-panel" style=',
            'class="cv724-impact-grid" style=',
            'class="cv724-driver-grid',
            'class="cv46-evidence-board" style=',
            'class="cv46-evidence-card" style=',
        ):
            self.assertIn(marker, self.html)

    def test_no_dynamic_content_in_style_helpers(self) -> None:
        self.assertNotIn("{", self.styles_source)
        self.assertNotIn("html.escape", self.styles_source)

    def test_structured_reason_and_action_rows(self) -> None:
        self.assertGreaterEqual(self.html.count("cv722-reason-row"), 3)
        self.assertGreaterEqual(self.html.count("cv722-action-row"), 3)

    def test_structured_decision_summary(self) -> None:
        self.assertEqual(len(re.findall(r'class="cv722-summary-item', self.html)), 3)

    def test_structured_impact_and_confidence_metrics(self) -> None:
        self.assertEqual(self.html.count("cv724-impact-cell"), 4)
        self.assertGreaterEqual(self.html.count("cv724-driver-cell"), 1)

    def test_structured_evidence_cards(self) -> None:
        self.assertEqual(len(re.findall(r'<article class="cv46-evidence-card"', self.html)), 3)

    def test_component_and_status_are_separate_block_elements(self) -> None:
        self.assertGreaterEqual(
            len(re.findall(r'<div class="cv46-evidence-component"(?: style="[^"]*")?>', self.html)),
            3,
        )
        self.assertGreaterEqual(
            len(re.findall(r'<div class="cv46-evidence-status"(?: style="[^"]*")?>', self.html)),
            3,
        )

    def test_no_giant_html_workspace_shell(self) -> None:
        self.assertNotIn("cv725-decision-workspace", self.html)

    def test_no_embedded_style_tag_in_response_surfaces(self) -> None:
        self.assertNotIn("<style", self.html.lower())

    def test_no_details_or_expander_wrappers(self) -> None:
        lowered = self.html.lower()
        self.assertNotIn("<details", lowered)
        self.assertNotIn("stexpander", lowered)

    def test_core_presentation_usable_without_external_css(self) -> None:
        self.assertEqual(self.html, self.html_without_css)
        self.assertGreaterEqual(self.html_without_css.count('style="'), 20)

    def test_no_concatenated_review_strings(self) -> None:
        for token in ("PC817Review", "BZX55C5V1Review", "DRV8825Review"):
            self.assertNotIn(token, self.html)

    def test_ask_runtime_diagnostics_retained(self) -> None:
        self.assertIn("_log_ask_runtime_identity", self.assistant_source)
        self.assertIn("_log_ask_runtime_surface", self.assistant_source)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
