"""Sprint 72.2.5.3 — Streamlit render-sequence + :has(style) container hiding tests."""
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


def _install_streamlit_stub():
    st = types.ModuleType("streamlit")
    st.session_state = {}
    markdown_calls: list[tuple[str, dict]] = []
    html_calls: list[str] = []
    render_sequence: list[str] = []

    def _markdown(content, **kwargs):
        text = str(content)
        markdown_calls.append((text, dict(kwargs)))
        if "cv50-exchange" in text:
            render_sequence.append("conversation_exchange")
        if "cv725-decision-workspace" in text:
            render_sequence.append("decision_workspace")

    def _html(content, **kwargs):
        text = str(content)
        html_calls.append(text)
        if "<style" in text.lower():
            render_sequence.append("stylesheet_injection")

    st.markdown = _markdown
    st.html = _html
    st.expander = lambda *args, **kwargs: _NullContext()
    st.columns = MagicMock(
        side_effect=lambda spec: [MagicMock() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))]
    )
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
    return markdown_calls, html_calls, render_sequence


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

    def test_workspace_html_contains_no_style_tag(self) -> None:
        assistant = _load_assistant()
        workspace = assistant._build_decision_workspace_html(
            primary_html='<section class="cv722-concise-answer"></section>',
            summary_html='<section class="cv722-summary-strip"></section>',
            assessment_html='<div class="cv724-impact-grid"></div>',
        )
        normalized = assistant._normalize_presentation_html(workspace)
        self.assertIn("cv725-decision-workspace", normalized)
        self.assertNotIn("<style", normalized.lower())

    def test_stylesheet_injection_separate_from_workspace_render(self) -> None:
        markdown_calls, html_calls, render_sequence = _install_streamlit_stub()
        assistant = _load_assistant()
        from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        workspace_calls = [content for content, _kwargs in markdown_calls if "cv725-decision-workspace" in content]
        self.assertTrue(html_calls, "Expected stylesheet injection via st.html")
        self.assertTrue(any("cadivor-ask-cadivor-v2-css" in call for call in html_calls))
        self.assertTrue(workspace_calls, "Expected decision workspace markdown render")
        self.assertTrue(all("<style" not in call.lower() for call in workspace_calls))
        self.assertIn("stylesheet_injection", render_sequence)
        self.assertIn("conversation_exchange", render_sequence)
        self.assertIn("decision_workspace", render_sequence)
        stylesheet_index = render_sequence.index("stylesheet_injection")
        workspace_index = render_sequence.index("decision_workspace")
        exchange_index = render_sequence.index("conversation_exchange")
        self.assertLess(stylesheet_index, workspace_index)
        self.assertLess(exchange_index, workspace_index)

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
        self.assertIn("workspace_html_built", events)
        self.assertIn("workspace_render_requested", events)
        self.assertIn("workspace_render_completed", events)
        built = next(details for event, details in logged if event == "workspace_html_built")
        self.assertTrue(built["has_workspace"])
        self.assertFalse(built["has_style_tag"])
        self.assertGreater(built["html_len"], 500)

    def test_approved_workspace_content_preserved(self) -> None:
        markdown_calls, _html_calls, _render_sequence = _install_streamlit_stub()
        assistant = _load_assistant()
        from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        html = "\n".join(content for content, _kwargs in markdown_calls)
        self.assertIn("cv725-decision-workspace", html)
        self.assertIn("cv725-decision-primary", html)
        self.assertIn("cv725-decision-assessment", html)
        self.assertIn("Review PC817 first.", html)
        self.assertIn("cv46-evidence-component", html)
        self.assertNotIn("PC817Review", html)
        self.assertEqual(html.count("Review PC817 first."), 1)
        self.assertIn(".cv725-decision-workspace", self.v2_css)


if __name__ == "__main__":
    unittest.main()
