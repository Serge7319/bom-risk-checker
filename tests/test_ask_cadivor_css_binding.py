"""Sprint 72.2.8 — Ask Cadivor production CSS/DOM binding tests."""
from __future__ import annotations

import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
PREMIUM_CSS = REPO_ROOT / "src/assets/css/premium.css"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"
STREAMLIT_HTML_CHUNK = (
    Path("/opt/anaconda3/lib/python3.12/site-packages/streamlit/static/static/js/2634.1249dc7a.chunk.js")
)


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
    markdown_calls: list[tuple[str, dict, str | None]] = []
    html_calls: list[str] = []

    def _markdown(content, **kwargs):
        markdown_calls.append((str(content), dict(kwargs), st._active_column))

    st.markdown = _markdown
    st.html = lambda content, **kwargs: html_calls.append(str(content))
    st.columns = lambda spec, gap=None: [
        _RecordingColumn("left", st),
        _RecordingColumn("right", st),
    ]
    st.container = lambda **kwargs: _NullContext()

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(script_run_id="css-binding-run")
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


CONTRACT_ROWS = (
    ("cv49-answer-card", ".cv49-answer-card", True),
    ("cv722-reason-row", ".cv722-reason-row", True),
    ("cv722-action-row", ".cv722-action-row", True),
    ("cv722-summary-strip", ".cv722-summary-strip", True),
    ("cv727-assessment-panel", ".cv727-assessment-panel", True),
    ("cv724-impact-grid", ".cv724-impact-grid", True),
    ("cv724-impact-cell", ".cv724-impact-cell", True),
    ("cv724-driver-grid", ".cv724-driver-grid", True),
    ("cv724-driver-cell", ".cv724-driver-cell", True),
    ("cv46-evidence-board", ".cv46-evidence-board", True),
    ("cv46-evidence-card", ".cv46-evidence-card", True),
)


class AskCadivorCssBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.premium_css = PREMIUM_CSS.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def test_stylesheet_injected_via_st_markdown_not_st_html(self) -> None:
        _install_streamlit_stub()
        assistant = _load_assistant()
        _, markdown_calls, html_calls = _install_streamlit_stub()
        assistant = _load_assistant()
        assistant._inject_ask_cadivor_v2_styles(force=True)
        stylesheet_markdown = [
            content for content, kwargs, _side in markdown_calls if "cadivor-ask-cadivor-v2-css" in content
        ]
        self.assertEqual(len(stylesheet_markdown), 1)
        self.assertTrue(stylesheet_markdown[0].startswith("<style id=\"cadivor-ask-cadivor-v2-css\">"))
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in call for call in html_calls))
        inject_block = self.assistant_source.split("def _inject_presentation_stylesheet", 1)[1].split("def _build_assessment_panel_html", 1)[0]
        self.assertIn("st.markdown(markup, unsafe_allow_html=True)", inject_block)
        self.assertNotIn("st.html(markup)", inject_block)

    def test_streamlit_html_sanitizer_strips_bare_style_tags(self) -> None:
        if not STREAMLIT_HTML_CHUNK.is_file():
            self.skipTest("Streamlit frontend chunk unavailable in this environment")
        chunk = STREAMLIT_HTML_CHUNK.read_text(encoding="utf-8")
        self.assertIn('data-testid":"stHtml"', chunk)
        self.assertIn("sanitize", chunk)
        self.assertIn("FORCE_BODY", chunk)
        self.assertIn("empty-html", chunk)

    def test_premium_css_hides_style_containers_without_invalidating_markdown_styles(self) -> None:
        self.assertIn('div[data-testid="stElementContainer"]:has(style)', self.premium_css)
        self.assertIn('div[data-testid="stMarkdownContainer"]:has(style:only-child)', self.premium_css)
        self.assertIn("display: none", self.premium_css.split(":has(style)", 1)[1])

    def test_stylesheet_injection_independent_from_response_render(self) -> None:
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
        stylesheet_calls = [
            content for content, _kwargs, _side in markdown_calls if "cadivor-ask-cadivor-v2-css" in content
        ]
        visible_calls = [
            content for content, _kwargs, _side in markdown_calls if "cadivor-ask-cadivor-v2-css" not in content
        ]
        self.assertEqual(len(stylesheet_calls), 1)
        self.assertTrue(all("<style" not in item.lower() for item in visible_calls))
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in call for call in html_calls))

    def test_dom_class_hierarchy_matches_727_selectors(self) -> None:
        assistant = _load_assistant()
        from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

        st, markdown_calls, _html_calls = _install_streamlit_stub()
        assistant = _load_assistant()
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        left = "\n".join(content for content, _kwargs, side in markdown_calls if side == "left")
        right = "\n".join(content for content, _kwargs, side in markdown_calls if side == "right")
        for class_name in (
            "cv49-answer-card",
            "cv722-reason-row",
            "cv722-action-row",
            "cv722-summary-strip",
        ):
            self.assertIn(class_name, left, class_name)
        for class_name in ("cv727-assessment-panel", "cv724-impact-grid", "cv724-driver-grid", "cv46-evidence-board", "cv46-evidence-card"):
            self.assertIn(class_name, right, class_name)

    def test_selector_contract_table(self) -> None:
        assistant = _load_assistant()
        from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

        st, markdown_calls, _html_calls = _install_streamlit_stub()
        assistant = _load_assistant()
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        html = "\n".join(content for content, _kwargs, _side in markdown_calls)
        for class_name, selector, _required in CONTRACT_ROWS:
            html_present = class_name in html
            css_present = selector in self.v2_css
            standalone_rule = bool(re.search(rf"(?<!\.){re.escape(selector[1:])}\s*\{{", self.v2_css))
            shell_only = bool(re.search(rf"\.cv-assistant-shell[^\{{{{]*{re.escape(selector[1:])}", self.v2_css))
            ancestry_ok = standalone_rule or ".st-key-cv727_decision_workspace" in self.v2_css or not shell_only
            self.assertTrue(html_present, f"{class_name} missing from rendered HTML")
            self.assertTrue(css_present, f"{selector} missing from ask_cadivor_v2.css")
            self.assertTrue(ancestry_ok, f"{selector} depends on removed shell-only ancestry")

    def test_provider_auth_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)
        self.assertNotIn("st.markdown(markup, unsafe_allow_html=True)", self.engineering_ai_source)


if __name__ == "__main__":
    unittest.main()
