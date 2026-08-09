"""Sprint 71.4.3 — Ask Cadivor premium response presentation tests."""
from __future__ import annotations

import importlib
import inspect
import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

REPO_ROOT = importlib.import_module("pathlib").Path(__file__).resolve().parents[1]
ASK_CADIVOR_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    markdown_calls: list[tuple[str, dict]] = []
    st.markdown = lambda content, **kwargs: markdown_calls.append((content, kwargs))
    st.html = MagicMock()
    st.columns = MagicMock(return_value=(MagicMock(), MagicMock()))
    st.caption = MagicMock()
    st.button = MagicMock(return_value=False)

    @contextmanager
    def _container(**kwargs):
        yield None

    st.container = _container

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda suppress_warning=False: types.SimpleNamespace(script_run_id="run-test")
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = types.ModuleType("streamlit.components.v1")
    return st, markdown_calls


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class AskCadivorResponsePresentationTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("src.components.engineering_assistant", None)

    def _install_import_stubs(self) -> None:
        secrets = types.ModuleType("src.secrets")
        secrets.get_secret = lambda key, default="": default
        sys.modules["src.secrets"] = secrets
        urls = types.ModuleType("src.urls")
        urls.internal_app_href = lambda *args, **kwargs: "?"
        sys.modules["src.urls"] = urls
        navigation = types.ModuleType("src.ui.navigation")
        navigation.alternative_finder_href = lambda *a, **k: "?"
        navigation.internal_nav_button = MagicMock()
        navigation.ALTERNATIVE_FINDER_PAGE = "Alternative Finder"
        sys.modules["src.ui.navigation"] = navigation

    def _load_assistant(self):
        self._install_import_stubs()
        return importlib.import_module("src.components.engineering_assistant")

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = ASK_CADIVOR_CSS.read_text(encoding="utf-8")
        cls.source = (REPO_ROOT / "src/components/engineering_assistant.py").read_text(encoding="utf-8")

    def test_format_engineering_prose_renders_bullets_and_bold(self):
        _install_streamlit_stub()
        assistant = self._load_assistant()
        html_out = assistant._format_engineering_prose(
            "**Recommendation.**\n\n- Review lifecycle risk first.\n- Validate supplier coverage.",
            context={"components": [{"part_number": "LM358"}]},
        )
        self.assertIn("<strong>Recommendation.</strong>", html_out)
        self.assertIn("<ul class=\"cv-assistant-prose-list\">", html_out)
        self.assertIn("Review lifecycle risk first.", html_out)

    def test_render_response_uses_premium_wrapper(self):
        _, markdown_calls = _install_streamlit_stub()
        assistant = self._load_assistant()
        sample_answer = (
            "## Direct Answer\n\n**Not ready yet.** Close evidence gaps first.\n\n"
            "## Evidence\n\n- **LM358** — lifecycle risk elevated\n\n"
            "## Confidence\n\nMedium. 62% based on saved records.\n\n"
            "## Recommended Actions\n\n- Validate datasheet evidence\n"
        )
        context = {
            "components": [{"part_number": "LM358", "risk_score": 88}],
            "coverage": {"score": 62},
            "summary": {"health_score": 71, "release_posture": "review"},
            "analysis": {},
        }
        assistant._render_response(
            question="Is this BOM ready for production release?",
            answer=sample_answer,
            context=context,
            auto_scroll=False,
        )
        rendered = "\n".join(content for content, _kwargs in markdown_calls if isinstance(content, str))
        self.assertIn("cv-assistant-response", rendered)
        self.assertIn("cv-assistant-executive-card", rendered)
        self.assertIn("cv-assistant-prose", rendered)
        self.assertIn("Executive answer", rendered)

    def test_scroll_helpers_prefer_st_html(self):
        _install_streamlit_stub()
        assistant = self._load_assistant()
        self.assertIn("_render_html_scroll", self.source)
        self.assertIn("st.html", inspect.getsource(assistant._render_html_scroll))

    def test_premium_css_tokens_present(self):
        for token in (
            ".cv-assistant-response",
            ".cv-assistant-prose",
            ".cv-assistant-section-card",
            ".cv-assistant-part",
            ".cv-assistant-followup-divider",
            "--cv-reading-max",
        ):
            self.assertIn(token, self.css)

    def test_one_click_and_duplicate_paths_untouched(self):
        self.assertIn("_queue_copilot_submission", self.source)
        self.assertIn("_block_duplicate_submission", self.source)
        self.assertIn("cv7142_ask_inflight", self.source)

    def test_engineering_ai_ask_not_modified(self):
        ai_source = (REPO_ROOT / "src/services/engineering_ai.py").read_text(encoding="utf-8")
        self.assertNotIn("cv-assistant-response", ai_source)


if __name__ == "__main__":
    unittest.main()
