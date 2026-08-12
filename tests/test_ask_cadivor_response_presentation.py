"""Sprint 72.3.2 — Ask Cadivor self-contained HTML response presentation tests."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


class AskCadivorResponsePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def setUp(self) -> None:
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)

    def _render_pc817(self):
        st = install_ask_cadivor_streamlit_stub()
        assistant = __import__("src.components.engineering_assistant", fromlist=["*"])
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
        return assistant, html, left, right, st

    def test_answer_uses_self_contained_block_surface(self) -> None:
        _, html, _, _, _ = self._render_pc817()
        self.assertIn("cv722-concise-answer", html)
        self.assertGreaterEqual(len(re.findall(r"cv722-reason-row", html)), 3)

    def test_numbered_reason_and_action_badges(self) -> None:
        _, html, _, _, _ = self._render_pc817()
        self.assertRegex(html, r'cv722-list-index" aria-hidden="true"[^>]*>01')
        self.assertRegex(html, r'cv722-list-index" aria-hidden="true"[^>]*>02')
        self.assertRegex(html, r'cv722-list-index" aria-hidden="true"[^>]*>03')
        self.assertIn("Investigate alternative suppliers or parts for PC817", html)

    def test_decision_summary_kpi_labels(self) -> None:
        _, html, left, _, _ = self._render_pc817()
        for label in ("Status", "Priority component", "Confidence"):
            self.assertIn(label, left)
        self.assertIn("PC817", left)
        self.assertIn("56%", html)
        self.assertEqual(len(re.findall(r'class="cv722-summary-item', html)), 3)

    def test_shell_independent_css_contract(self) -> None:
        section = self.v2_css.split("Sprint 72.2.4", 1)[1]
        for selector in (
            ".cv50-exchange",
            ".cv722-reason-list",
            ".cv722-summary-strip",
            ".cv46-evidence-card-header",
        ):
            self.assertIn(selector, section)

    def test_assessment_visible_without_details_wrapper(self) -> None:
        _, html, _, right, _ = self._render_pc817()
        self.assertIn("cv727-assessment-panel", right)
        self.assertIn("Projected engineering impact", right)
        self.assertNotIn("<details", html.lower())

    def test_no_label_value_concatenation(self) -> None:
        _, html, _, _, _ = self._render_pc817()
        self.assertNotRegex(html, r"StatusReview")
        for bad in ("PC817Review", "BZX55C5V1Review", "DRV8825Review"):
            self.assertNotIn(bad, html)

    def test_no_direct_answer_duplication(self) -> None:
        _, html, _, _, _ = self._render_pc817()
        self.assertEqual(html.count("Review PC817 first."), 1)

    def test_timeline_remains_gated_for_generic_review(self) -> None:
        assistant, html, _, _, _ = self._render_pc817()
        self.assertFalse(
            assistant._should_render_workflow_timeline(
                PC817_QUESTION,
                detailed=False,
                workflow_text="",
                context=PC817_CONTEXT,
            )
        )
        self.assertNotIn("Priority timeline", html.lower())

    def test_mock_pc817_deterministic_render_contract(self) -> None:
        _, html, left, right, st = self._render_pc817()
        self.assertIn("Cadivor Answer", html)
        self.assertIn("Direct answer", left)
        self.assertIn("Key engineering reasons", left)
        self.assertIn("Recommended actions", left)
        self.assertIn("evidence breakdown", right.lower())
        self.assertTrue(any(call[0] == [0.85, 1.15] for call in st.columns_calls))
        self.assertEqual(len(re.findall(r'<article class="cv46-evidence-card"', html)), 3)

    def test_workflow_actions_use_border_containers(self) -> None:
        self.assertIn("st.container(border=True)", self.assistant_source)
        self.assertNotIn('st.container(key="cv725_workflow_actions")', self.assistant_source)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
