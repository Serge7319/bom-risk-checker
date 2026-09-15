"""Sprint 72.3.2 — Self-contained HTML assessment recovery tests."""
from __future__ import annotations

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


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


class AskCadivorDesktopAssessmentRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")

    def _render_pc817(self, *, expand: bool = False):
        st = install_ask_cadivor_streamlit_stub()
        assistant = _load_assistant()
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                with patch.object(assistant, "_disclosure_is_open", return_value=bool(expand)):
                    assistant._render_response(
                        question=PC817_QUESTION,
                        answer=PC817_ANSWER,
                        context=PC817_CONTEXT,
                    )
        html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
        return html, st

    def test_assessment_available_when_expanded(self) -> None:
        collapsed, _ = self._render_pc817(expand=False)
        self.assertNotIn("cv727-assessment-panel", collapsed)
        html, _st = self._render_pc817(expand=True)
        self.assertIn("cv727-assessment-panel", html)
        self.assertIn("Engineering Assessment", html)
        self.assertNotIn("<details", html.lower())

    def test_response_markup_has_no_runtime_stylesheet(self) -> None:
        html, _ = self._render_pc817()
        self.assertNotIn("<style", html.lower())
        self.assertIn(".cv46-evidence-card-header", self.v2_css)

    def test_shell_independent_css_contract(self) -> None:
        section = self.v2_css.split("Sprint 72.2.4", 1)[1]
        self.assertIn(".cv50-exchange", section)
        self.assertIn(".cv46-evidence-card-header", section)

    def test_evidence_breakdown_structurally_separated(self) -> None:
        html, _ = self._render_pc817(expand=True)
        for component in ("PC817", "BZX55C5V1", "DRV8825"):
            self.assertIn(component, html)
        self.assertIn("evidence breakdown", html.lower())
        self.assertEqual(len(re.findall(r'<article class="cv46-evidence-card"', html)), 3)

    def test_native_workspace_is_single_column_compact(self) -> None:
        html, st = self._render_pc817(expand=False)
        self.assertEqual(st.columns_calls, [])
        self.assertIn("Review PC817 first.", html)
        self.assertIn("cv72-compact-answer", html)
        self.assertNotIn("projected engineering impact", html.lower())
        self.assertNotIn("cv725-decision-workspace", html)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
