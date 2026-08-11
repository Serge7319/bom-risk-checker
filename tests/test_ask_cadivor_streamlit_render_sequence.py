"""Sprint 72.2.7 — Streamlit render-sequence + native column workspace tests."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
PREMIUM_CSS = REPO_ROOT / "src/assets/css/premium.css"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"


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


def _install_streamlit_stub():
    st = types.ModuleType("streamlit")
    st.session_state = {}
    st._active_column = None
    st.columns_calls: list[tuple[list[float], str | None]] = []
    markdown_calls: list[tuple[str, dict, str | None]] = []
    html_calls: list[str] = []

    def _markdown(content, **kwargs):
        markdown_calls.append((str(content), dict(kwargs), st._active_column))

    def _html(content, **kwargs):
        html_calls.append(str(content))
        if "<style" in str(content).lower():
            st.render_sequence.append("stylesheet_injection")

    def _columns(spec, gap=None):
        ratio = list(spec) if isinstance(spec, (list, tuple)) else [1] * int(spec)
        st.columns_calls.append((ratio, gap))
        st.render_sequence.append("columns_created")
        return [_RecordingColumn("left", st), _RecordingColumn("right", st)]

    st.render_sequence: list[str] = []
    st.markdown = _markdown
    st.html = _html
    st.columns = _columns
    st.container = lambda **kwargs: _NullContext()

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(script_run_id="render-seq-run")
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    components.html = lambda content, **kwargs: html_calls.append(str(content))

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st, markdown_calls, html_calls


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


class AskCadivorStreamlitRenderSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.premium_css = PREMIUM_CSS.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")

    def test_premium_css_hides_style_containing_containers(self) -> None:
        self.assertIn('div[data-testid="stElementContainer"]:has(style)', self.premium_css)
        block = self.premium_css.split('div[data-testid="stElementContainer"]:has(style)', 1)[1].split("}", 1)[0]
        self.assertIn("display: none", block)

    def test_assessment_panel_contains_no_style_tag(self) -> None:
        assistant = _load_assistant()
        panel = assistant._build_assessment_panel_html('<div class="cv724-impact-grid"></div>')
        normalized = assistant._normalize_presentation_html(panel)
        self.assertIn("cv727-assessment-panel", normalized)
        self.assertNotIn("<style", normalized.lower())
        self.assertNotIn("<details", normalized.lower())

    def test_response_renderer_emits_no_stylesheet(self) -> None:
        st, markdown_calls, html_calls = _install_streamlit_stub()
        assistant = _load_assistant()
        from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        visible = [content for content, _kwargs, _side in markdown_calls]
        self.assertTrue(all("<style" not in item.lower() for item in visible))
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in call for call in html_calls))
        self.assertTrue(any(call[0] == [0.85, 1.15] for call in st.columns_calls))

    def test_render_sequence_logging_contract(self) -> None:
        _install_streamlit_stub()
        assistant = _load_assistant()
        from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

        logged: list[tuple[str, dict]] = []

        def _capture(event: str, **details):
            logged.append((event, details))

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                with patch.object(assistant, "_log_ask_render", side_effect=_capture):
                    assistant._render_response(
                        question=PC817_QUESTION,
                        answer=PC817_ANSWER,
                        context=PC817_CONTEXT,
                    )
        events = [event for event, _details in logged]
        self.assertEqual(events[0], "response_entered")
        self.assertIn("exchange_rendered", events)
        self.assertIn("workspace_shell_ready", events)
        self.assertIn("workspace_columns_requested", events)
        self.assertIn("workspace_left_column_entered", events)
        self.assertIn("workspace_right_column_entered", events)
        self.assertIn("workspace_render_completed", events)
        ready = next(details for event, details in logged if event == "workspace_shell_ready")
        self.assertTrue(ready["has_assessment_panel"])
        self.assertFalse(ready["has_style_tag"])

    def test_approved_workspace_content_preserved(self) -> None:
        st, markdown_calls, _html_calls = _install_streamlit_stub()
        assistant = _load_assistant()
        from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        html = "\n".join(content for content, _kwargs, _side in markdown_calls)
        left = "\n".join(content for content, _kwargs, side in markdown_calls if side == "left")
        right = "\n".join(content for content, _kwargs, side in markdown_calls if side == "right")
        self.assertNotIn("cv725-decision-workspace", html)
        self.assertIn("cv727-assessment-panel", right)
        self.assertIn("cv722-concise-answer", left)
        self.assertIn("Review PC817 first.", html)
        self.assertIn("cv46-evidence-component", right)
        self.assertNotIn("PC817Review", html)
        self.assertEqual(html.count("Review PC817 first."), 1)
        self.assertIn(".cv727-assessment-panel", self.v2_css)


if __name__ == "__main__":
    unittest.main()
