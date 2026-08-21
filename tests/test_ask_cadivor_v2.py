"""Sprint 72.5 — Ask Cadivor premium conversational experience tests."""
from __future__ import annotations

import importlib
import inspect
import re
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ANALYSIS_DETAIL_PY = REPO_ROOT / "src/pages/analysis_detail.py"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

DS_V2_TOKENS = (
    "--cv-surface",
    "--cv-border",
    "--cv-text",
    "--cv-text-muted",
    "--cv-text-secondary",
    "--cv-primary",
    "--cv-primary-subtle",
    "--cv-primary-hover",
    "--cv-success",
    "--cv-success-bg",
    "--cv-warning",
    "--cv-warning-bg",
    "--cv-danger",
    "--cv-danger-bg",
    "--cv-page-max",
    "--cv-reading-max",
    "--cv-space-2",
    "--cv-space-3",
    "--cv-space-4",
    "--cv-radius-lg",
    "--cv-radius-md",
    "--cv-shadow-xs",
    "--cv-shadow-sm",
    "--cv-font-sm",
    "--cv-font-xs",
    "--cv-weight-semibold",
    "--cv-control-md",
)


def _install_streamlit_stub(session_state: dict | None = None, *, script_run_id: str = "run-a"):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    markdown_calls = []
    html_calls: list[str] = []
    st.markdown = lambda content, **kwargs: markdown_calls.append((content, kwargs))
    st.html = lambda content, **kwargs: html_calls.append(str(content))
    st.form = lambda *args, **kwargs: _NullContext()
    st.text_area = lambda label, key, **kwargs: st.session_state.get(key, "")
    st.form_submit_button = MagicMock(return_value=False)
    st.status = lambda *args, **kwargs: _NullContext()
    st.warning = MagicMock()
    st.info = MagicMock()
    st.success = MagicMock()
    st.caption = MagicMock()
    st.columns = MagicMock(
        side_effect=lambda spec, gap=None: [_NullContext() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))]
    )
    st.button = MagicMock(return_value=False)
    st.link_button = MagicMock()

    @contextmanager
    def _container(**kwargs):
        yield None

    st.container = _container

    class _Ctx:
        def __init__(self, run_id: str):
            self.script_run_id = run_id

    _ctx = _Ctx(script_run_id)

    def get_script_run_ctx():
        return _ctx

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = get_script_run_ctx
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner

    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st, markdown_calls, html_calls, _ctx


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **kwargs):
        return None


class AskCadivorV2Tests(unittest.TestCase):
    def setUp(self):
        for mod in (
            "src.components.engineering_assistant",
            "src.pages.analysis_detail",
        ):
            sys.modules.pop(mod, None)

    def _load_assistant(self):
        return importlib.import_module("src.components.engineering_assistant")

    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.detail_source = ANALYSIS_DETAIL_PY.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def test_production_render_path_present(self) -> None:
        self.assertIn('if active_tab == "Ask Cadivor":', self.detail_source)
        self.assertIn("render_engineering_assistant(", self.detail_source)

    def test_suggested_prompt_flow_queues_submission(self) -> None:
        assistant = self._load_assistant()
        chip_source = inspect.getsource(assistant._render_prompt_chip_grid)
        select_source = inspect.getsource(assistant._select_initial_suggestion)
        self.assertIn("_select_initial_suggestion", chip_source)
        self.assertIn("_queue_copilot_submission", select_source)
        self.assertIn('submission_kind="suggestion"', select_source)
        self.assertIn("cv35_pick", self.assistant_source)

    def test_manual_submit_flow_unchanged(self) -> None:
        self.assertIn("_queue_copilot_submission", self.assistant_source)
        self.assertIn("cv41_engineering_question_form", self.assistant_source)
        self.assertIn("cv41_pending_manual", self.assistant_source)

    def test_follow_up_flow_unchanged(self) -> None:
        assistant = self._load_assistant()
        queue_source = inspect.getsource(assistant._queue_copilot_submission)
        follow_source = inspect.getsource(assistant._render_follow_ups)
        self.assertIn("_queue_copilot_submission", inspect.getsource(assistant._queue_follow_up))
        self.assertIn("cv36_pending_followup", queue_source)
        self.assertIn("follow_up_suggestions", follow_source)

    def test_pending_section_architecture_unchanged(self) -> None:
        self.assertIn("PENDING_ANALYSIS_SECTION_KEY", self.assistant_source)
        self.assertIn("PENDING_ANALYSIS_SECTION_ID_KEY", self.assistant_source)
        self.assertNotIn("cadivor_analysis_section_", self.assistant_source)

    def test_no_widget_backed_nav_key_mutation(self) -> None:
        assistant = self._load_assistant()
        pin_source = inspect.getsource(assistant._pin_ask_cadivor_tab)
        self.assertNotIn("cadivor_analysis_section_", pin_source)
        self.assertNotIn("st.radio", pin_source)

    def test_ds_v2_tokens_and_classes_used(self) -> None:
        for token in DS_V2_TOKENS:
            self.assertIn(token, self.v2_css)
        for cls in (
            ".cv-assistant-shell",
            ".cv-assistant-context-header",
            ".cv-assistant-usage",
            ".cv-assistant-section-label",
        ):
            self.assertIn(cls, self.v2_css)

    def test_no_new_root_namespace(self) -> None:
        self.assertNotRegex(self.v2_css, r":root\s*\{")

    def test_css_injected_once_per_script_run(self) -> None:
        st, markdown_calls, html_calls, _ctx = _install_streamlit_stub({})
        for name in ("src.ui.design_system_v2",):
            sys.modules.pop(name, None)
        from src.ui.design_system_v2 import inject_ask_cadivor_v2_css

        first = inject_ask_cadivor_v2_css()
        second = inject_ask_cadivor_v2_css()

        self.assertTrue(first)
        self.assertFalse(second)
        stylesheet_calls = [
            content for content, _kwargs in markdown_calls if "cadivor-ask-cadivor-v2-css" in content
        ]
        self.assertEqual(len(stylesheet_calls), 1)
        self.assertTrue(all("cadivor-ask-cadivor-v2-css" not in call for call in html_calls))
        components = sys.modules["streamlit.components.v1"]
        components.html.assert_not_called()
        self.assertEqual(st.session_state.get("_cadivor_ask_cadivor_v2_run_id"), "run-a")

    def test_css_reinjects_on_new_script_run(self) -> None:
        session = {}
        _install_streamlit_stub(session, script_run_id="run-a")
        for name in ("src.ui.design_system_v2",):
            sys.modules.pop(name, None)
        from src.ui.design_system_v2 import inject_ask_cadivor_v2_css

        self.assertTrue(inject_ask_cadivor_v2_css())
        self.assertFalse(inject_ask_cadivor_v2_css())

        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"
        sys.modules.pop("src.ui.design_system_v2", None)
        from src.ui.design_system_v2 import inject_ask_cadivor_v2_css as reinject

        self.assertTrue(reinject())

    def test_responsive_rules_exist(self) -> None:
        for width in ("1280px", "1024px", "768px"):
            self.assertIn(f"@media (max-width: {width})", self.v2_css)

    def test_engineering_ai_ask_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)
        self.assertNotIn("ask_cadivor_v2", self.engineering_ai_source)

    def test_entitlement_logic_untouched(self) -> None:
        self.assertIn("get_ai_usage_status", self.assistant_source)
        self.assertIn("consume_ai_credits", self.assistant_source)
        self.assertNotIn("is_admin = True", self.assistant_source)

    def test_inline_css_removed(self) -> None:
        self.assertNotIn("cadivor-engineering-assistant-43", self.assistant_source)
        self.assertNotIn("cv35-hero", self.assistant_source)
        self.assertNotIn("_inject_ask_cadivor_v2_styles", self.assistant_source)
        self.assertNotIn("ask_cadivor_v2.css", self.assistant_source)

    def test_context_header_and_containers_present(self) -> None:
        self.assertIn("_render_context_header", self.assistant_source)
        self.assertIn("st.container(border=True)", self.assistant_source)
        self.assertIn("_build_concise_answer_html", self.assistant_source)
        self.assertNotIn("st.container(key=", self.assistant_source)
        self.assertNotIn('<div class="cv-assistant-shell">', self.assistant_source)

    def test_protected_state_functions_present(self) -> None:
        assistant = self._load_assistant()
        for fn in (
            "_pin_ask_cadivor_tab",
            "_queue_copilot_submission",
            "_select_initial_suggestion",
            "_apply_copilot_query_picks",
            "_queue_follow_up",
            "_clear_followup_ui_state",
        ):
            self.assertTrue(callable(getattr(assistant, fn, None)), fn)

    @patch("src.components.engineering_assistant.get_ai_usage_status")
    @patch("src.components.engineering_assistant.get_thread", return_value=[])
    @patch("src.components.engineering_assistant._apply_copilot_query_picks")
    def test_render_does_not_inject_stylesheet(self, _apply, _thread, mock_usage) -> None:
        st, markdown_calls, html_calls, _ctx = _install_streamlit_stub({"cv35_question": ""})
        assistant = self._load_assistant()
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

