"""Sprint 72.3.2 — Self-contained HTML surface structural guards."""
from __future__ import annotations

import re
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"

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


class AskCadivorDomSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _render_pc817_html()
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")

    def test_three_reason_rows_in_single_surface(self) -> None:
        self.assertGreaterEqual(self.html.count("cv722-reason-row"), 3)

    def test_three_action_rows_in_single_surface(self) -> None:
        self.assertGreaterEqual(self.html.count("cv722-action-row"), 3)

    def test_decision_summary_has_three_cells(self) -> None:
        self.assertIn('data-field="status"', self.html)
        self.assertIn('data-field="priority"', self.html)
        self.assertIn('data-field="confidence"', self.html)
        self.assertEqual(len(re.findall(r'class="cv722-summary-item', self.html)), 3)

    def test_impact_grid_has_four_cells(self) -> None:
        self.assertEqual(self.html.count("cv724-impact-cell"), 4)

    def test_evidence_board_has_three_cards(self) -> None:
        self.assertEqual(len(re.findall(r'<article class="cv46-evidence-card"', self.html)), 3)
        self.assertIn("cv46-evidence-board", self.html)

    def test_component_and_status_are_separate_elements(self) -> None:
        self.assertGreaterEqual(self.html.count("cv46-evidence-component"), 3)
        self.assertGreaterEqual(self.html.count("cv46-evidence-status"), 3)

    def test_no_concatenated_component_status_text(self) -> None:
        for token in ("PC817Review", "BZX55C5V1Review", "DRV8825Review"):
            self.assertNotIn(token, self.html)

    def test_conversation_exchange_badges_are_separate(self) -> None:
        self.assertIn("cv50-exchange-badges", self.html)
        self.assertIn('class="cv50-type', self.html)
        self.assertIn('class="cv50-saved"', self.html)
        self.assertNotIn("Recommendation✓Review auto-saved", self.html)

    def test_native_columns_ratio_preserved_in_source(self) -> None:
        self.assertIn("_DECISION_COLUMN_RATIO = [0.85, 1.15]", self.assistant_source)

    def test_shell_independent_css_contract_on_disk(self) -> None:
        for selector in (
            ".cv50-exchange",
            ".cv722-reason-list",
            ".cv722-summary-strip",
            ".cv724-impact-grid",
            ".cv46-evidence-card-header",
        ):
            self.assertIn(selector, self.v2_css)

    def test_no_fragmented_cv731_surfaces_in_output(self) -> None:
        self.assertNotIn("cv731-reason-card", self.html)
        self.assertNotIn("cv731-evidence-card", self.html)

    def test_answer_and_assessment_use_block_builders(self) -> None:
        self.assertIn("_build_concise_answer_html", self.assistant_source)
        self.assertIn("_build_assessment_panel_html", self.assistant_source)
        self.assertIsNone(re.search(r"st\.container\(\s*key\s*=", self.assistant_source))


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
