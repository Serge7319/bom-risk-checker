"""Sprint 72.3.2 — Native Streamlit decision workspace + HTML surface tests."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


class AskCadivorNativeWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def _render_pc817(self):
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
        return st, html, left, right

    def test_uses_native_columns_ratio(self) -> None:
        st, _html, _left, _right = self._render_pc817()
        ratio, gap = st.columns_calls[0]
        self.assertEqual(ratio, [0.85, 1.15])
        self.assertEqual(gap, "large")

    def test_left_column_contains_answer_and_summary(self) -> None:
        _st, html, left, _right = self._render_pc817()
        self.assertIn("Review PC817 first.", left)
        self.assertIn("cv722-summary-strip", left)
        self.assertIn("cv722-concise-answer", left)
        self.assertEqual(len(re.findall(r'class="cv722-summary-item', html)), 3)

    def test_right_column_contains_assessment_without_details(self) -> None:
        _st, html, _left, _right = self._render_pc817()
        self.assertIn("Engineering Assessment", html)
        self.assertIn("cv727-assessment-panel", _right)
        self.assertNotIn("<details", html.lower())

    def test_evidence_cards_separated(self) -> None:
        _st, html, _left, _right = self._render_pc817()
        self.assertEqual(len(re.findall(r'<article class="cv46-evidence-card"', html)), 3)
        for bad in ("PC817Review", "BZX55C5V1Review", "DRV8825Review"):
            self.assertNotIn(bad, html)

    def test_css_uses_shell_independent_surface_classes(self) -> None:
        section = self.v2_css.split("Sprint 72.2.4", 1)[1]
        self.assertIn(".cv50-exchange", section)
        self.assertIn(".cv46-evidence-card-header", section)

    def test_full_path_harness_passes(self) -> None:
        from tests.harness_ask_cadivor_full_path import main as run_full_path

        self.assertEqual(run_full_path(), 0)

    def test_no_keyed_containers_in_source(self) -> None:
        self.assertNotIn("st.container(key=", self.assistant_source)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
