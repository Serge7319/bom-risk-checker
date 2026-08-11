"""Sprint 72.3.4 — Browser-neutral Ask Cadivor DOM contract."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


def _render_pc817_html() -> str:
    st = install_ask_cadivor_streamlit_stub()
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    with patch.object(assistant, "_render_response_scroll_anchor"):
        with patch.object(assistant, "_render_quick_actions"):
            assistant._render_response(
                question=PC817_QUESTION,
                answer=PC817_ANSWER,
                context=PC817_CONTEXT,
            )
    return "\n".join(content for content, _kwargs, _side in st.markdown_calls)


class AskCadivorBrowserNeutralContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _render_pc817_html()
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")

    def test_three_reason_cards(self) -> None:
        self.assertGreaterEqual(self.html.count("cv722-reason-row"), 3)

    def test_three_action_cards(self) -> None:
        self.assertGreaterEqual(self.html.count("cv722-action-row"), 3)

    def test_three_decision_summary_cells(self) -> None:
        self.assertEqual(len(re.findall(r'class="cv722-summary-item', self.html)), 3)
        for field in ("status", "priority", "confidence"):
            self.assertIn(f'data-field="{field}"', self.html)

    def test_four_impact_cards(self) -> None:
        self.assertEqual(self.html.count("cv724-impact-cell"), 4)

    def test_confidence_driver_cards_present(self) -> None:
        self.assertIn("cv722-confidence-drivers-only", self.html)
        self.assertGreaterEqual(self.html.count("cv724-driver-cell"), 1)

    def test_three_evidence_cards(self) -> None:
        self.assertEqual(len(re.findall(r'<article class="cv46-evidence-card"', self.html)), 3)

    def test_component_and_status_are_block_elements(self) -> None:
        self.assertGreaterEqual(
            len(re.findall(r'<div class="cv46-evidence-component">', self.html)),
            3,
        )
        self.assertGreaterEqual(
            len(re.findall(r'<div class="cv46-evidence-status">', self.html)),
            3,
        )
        self.assertNotRegex(self.html, r'<span class="cv46-evidence-component"')
        self.assertNotRegex(self.html, r'<span class="cv46-evidence-status"')

    def test_exchange_badges_are_block_elements(self) -> None:
        self.assertIn('<div class="cv50-you-asked-label">', self.html)
        self.assertIn('<div class="cv50-you-asked-question">', self.html)
        self.assertRegex(self.html, r'<div class="cv50-type cv50-type--')
        self.assertIn('<div class="cv50-saved">', self.html)

    def test_no_concatenated_pc817_review_strings(self) -> None:
        for token in ("PC817Review", "BZX55C5V1Review", "DRV8825Review"):
            self.assertNotIn(token, self.html)
        self.assertNotIn("Recommendation✓Review auto-saved", self.html)

    def test_evidence_metric_builder_uses_separate_label_text(self) -> None:
        self.assertIn("_html_evidence_metric", self.assistant_source)
        self.assertIn("cv46-evidence-metric-label-text", self.assistant_source)

    def test_native_column_ratio_preserved(self) -> None:
        self.assertIn("_DECISION_COLUMN_RATIO = [0.85, 1.15]", self.assistant_source)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
