"""Sprint 72.2.9 — production-equivalent Ask Cadivor stylesheet loading tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTHENTICATED_RUNTIME_PY = REPO_ROOT / "src/authenticated_runtime.py"
DESIGN_SYSTEM_V1_PY = REPO_ROOT / "src/ui/design_system_v1.py"
DESIGN_SYSTEM_V2_PY = REPO_ROOT / "src/ui/design_system_v2.py"
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"

from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION
from tests.harness_ask_cadivor_stylesheet_loading import (
    _install_streamlit_stub,
    render_pc817_response_without_stylesheet,
    simulate_authenticated_app_css_stack,
)


class AskCadivorStylesheetLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_source = AUTHENTICATED_RUNTIME_PY.read_text(encoding="utf-8")
        cls.ds_v1_source = DESIGN_SYSTEM_V1_PY.read_text(encoding="utf-8")
        cls.ds_v2_source = DESIGN_SYSTEM_V2_PY.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.ask_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")

    def test_authenticated_runtime_calls_global_design_system_stack(self) -> None:
        self.assertIn("inject_premium_css()", self.runtime_source)
        self.assertIn("inject_design_system_v1()", self.runtime_source)
        premium_idx = self.runtime_source.index("inject_premium_css()")
        ds_idx = self.runtime_source.index("inject_design_system_v1()")
        self.assertLess(premium_idx, ds_idx)

    def test_design_system_v1_wires_ask_cadivor_css(self) -> None:
        self.assertIn("inject_ask_cadivor_v2_css", self.ds_v1_source)
        self.assertIn("inject_cadivor_design_system_v2", self.ds_v1_source)

    def test_ask_cadivor_css_uses_same_markdown_style_path_as_ds_v2(self) -> None:
        ds_block = self.ds_v2_source.split("def inject_cadivor_design_system_v2", 1)[1].split("def load_ask_cadivor_v2_css", 1)[0]
        ask_block = self.ds_v2_source.split("def inject_ask_cadivor_v2_css", 1)[1]
        self.assertIn('st.markdown(\n        f"<style id=\'{_DS_V2_STYLE_ID}\'>{css}</style>",', ds_block)
        self.assertIn('st.markdown(\n        f"<style id=\'{_ASK_CADIVOR_V2_STYLE_ID}\'>{css}</style>",', ask_block)
        self.assertIn("unsafe_allow_html=True", ask_block)

    def test_engineering_assistant_does_not_inject_stylesheet(self) -> None:
        self.assertNotIn("_inject_ask_cadivor_v2_styles", self.assistant_source)
        self.assertNotIn("_inject_presentation_stylesheet", self.assistant_source)
        self.assertNotIn("ask_cadivor_v2.css", self.assistant_source)

    def test_app_shell_loads_ask_css_once_per_run(self) -> None:
        st = _install_streamlit_stub()
        simulate_authenticated_app_css_stack(st)
        simulate_authenticated_app_css_stack(st)
        ask_calls = [
            content for content, _kwargs, _side in st.markdown_calls if "cadivor-ask-cadivor-v2-css" in content
        ]
        self.assertEqual(len(ask_calls), 1)
        self.assertIn(self.ask_css.strip(), ask_calls[0])

    def test_response_renderer_emits_style_free_markup(self) -> None:
        st = _install_streamlit_stub()
        simulate_authenticated_app_css_stack(st)
        html, response_calls = render_pc817_response_without_stylesheet(st)
        self.assertTrue(all("<style" not in content.lower() for content, _kwargs, _side in response_calls))
        self.assertIn("Review PC817 first.", html)
        self.assertIn("cv722-concise-answer", html)
        self.assertIn("cv722-reason-row", html)

    def test_css_injected_once_per_script_run_via_design_system_v2(self) -> None:
        st = _install_streamlit_stub()
        for name in ("src.ui.design_system_v2",):
            sys.modules.pop(name, None)
        from src.ui.design_system_v2 import inject_ask_cadivor_v2_css

        self.assertTrue(inject_ask_cadivor_v2_css())
        self.assertFalse(inject_ask_cadivor_v2_css())

        st.script_ctx.script_run_id = "stylesheet-run-b"
        sys.modules.pop("src.ui.design_system_v2", None)
        from src.ui.design_system_v2 import inject_ask_cadivor_v2_css as reinject

        self.assertTrue(reinject())

    def test_render_engineering_assistant_does_not_inject_stylesheet(self) -> None:
        from tests.test_ask_cadivor_v2 import _install_streamlit_stub as install_assistant_stub

        st, markdown_calls, html_calls, _ctx = install_assistant_stub({"cv35_question": ""})
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        import src.components.engineering_assistant as assistant
        from unittest.mock import MagicMock

        with patch.object(assistant, "get_ai_usage_status") as mock_usage:
            with patch.object(assistant, "get_thread", return_value=[]):
                with patch.object(assistant, "_apply_copilot_query_picks"):
                    mock_usage.return_value = MagicMock(
                        is_admin=False,
                        remaining=100,
                        allowance=200,
                        warning_level="normal",
                        can_use=True,
                        percent_used=10,
                    )
                    context = MagicMock()
                    context.compact.return_value = {
                        "project_name": "Demo BOM",
                        "summary": {"health_score": 82, "total_parts": 14, "release_posture": "Review"},
                    }
                    assistant.render_engineering_assistant(
                        current_user={"id": "u1"},
                        engineering_context=context,
                    )
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in content for content, _kwargs in markdown_calls))
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in call for call in html_calls))


if __name__ == "__main__":
    unittest.main()

def tearDownModule():
    from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules
    restore_ask_cadivor_streamlit_modules()

