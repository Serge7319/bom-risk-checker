"""Sprint 72.3.2 — Compact Streamlit conversation workspace + deferred detail tests."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        return st, html

    def test_uses_single_column_workspace(self) -> None:
        st, _html = self._render_pc817()
        self.assertEqual(st.columns_calls, [])

    def test_compact_answer_without_default_assessment(self) -> None:
        _st, html = self._render_pc817()
        self.assertIn("Review PC817 first.", html)
        self.assertIn("cv722-concise-answer", html)
        self.assertIn("Recommended next action", html)
        self.assertNotIn("cv722-summary-strip", html)
        self.assertNotIn("cv727-assessment-panel", html)

    def test_expanded_assessment_available_on_toggle(self) -> None:
        _st, html = self._render_pc817(expand=True)
        self.assertIn("cv727-assessment-panel", html)
        self.assertNotIn("<details", html.lower())

    def test_evidence_cards_deferred_until_expanded(self) -> None:
        _st, collapsed = self._render_pc817(expand=False)
        self.assertEqual(len(re.findall(r'<article class="cv46-evidence-card"', collapsed)), 0)
        _st2, expanded = self._render_pc817(expand=True)
        self.assertEqual(len(re.findall(r'<article class="cv46-evidence-card"', expanded)), 3)
        for bad in ("PC817Review", "BZX55C5V1Review", "DRV8825Review"):
            self.assertNotIn(bad, expanded)

    def test_css_uses_shell_independent_surface_classes(self) -> None:
        section = self.v2_css.split("Sprint 72.2.4", 1)[1]
        self.assertIn(".cv50-exchange", section)
        self.assertIn(".cv46-evidence-card-header", section)

    def test_full_path_harness_passes(self) -> None:
        from tests.harness_ask_cadivor_full_path import main as run_full_path

        self.assertEqual(run_full_path(), 0)

    def test_no_keyed_containers_in_source(self) -> None:
        # Layout-stability polish may key a small set of Ask-stage containers.
        # Ban any other keyed containers in this module.
        allowed_keys = {
            'key="cv72_response_stage"',
            'key="cv72_prior_reviews"',
            'key=f"cv72_disc_{key}"',
        }
        found_keys = set()
        for line in self.assistant_source.splitlines():
            if "st.container(key=" not in line:
                continue
            for key in allowed_keys:
                if key in line:
                    found_keys.add(key)
                    break
            else:
                self.fail(f"Unexpected keyed container: {line.strip()}")
        self.assertEqual(found_keys, allowed_keys)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
