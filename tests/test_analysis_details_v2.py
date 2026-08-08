"""Sprint 72.4 — Analysis Details premium experience tests."""
from __future__ import annotations

import importlib
import inspect
import re
import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DETAIL_V2_CSS = REPO_ROOT / "src/assets/css/analysis_detail_v2.css"
ANALYSIS_DETAIL_PY = REPO_ROOT / "src/pages/analysis_detail.py"
AUTHENTICATED_RUNTIME = REPO_ROOT / "src/authenticated_runtime.py"

EXPECTED_SECTIONS = (
    "Engineering Intelligence",
    "Overview",
    "Intelligence",
    "Components",
    "Alternatives",
    "Discussions",
    "Timeline",
    "Reports",
    "Ask Cadivor",
)

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
    "--cv-control-sm",
)


def _install_streamlit_stub(session_state: dict | None = None, *, script_run_id: str = "run-a"):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    markdown_calls = []
    st.markdown = lambda content, **kwargs: markdown_calls.append((content, kwargs))

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

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    return st, markdown_calls, _ctx


class AnalysisDetailsV2Tests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("src.pages.analysis_detail", None)

    def _load_detail(self):
        return importlib.import_module("src.pages.analysis_detail")
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_css = ANALYSIS_DETAIL_V2_CSS.read_text(encoding="utf-8")
        cls.detail_source = ANALYSIS_DETAIL_PY.read_text(encoding="utf-8")
        cls.runtime_source = AUTHENTICATED_RUNTIME.read_text(encoding="utf-8")

    def test_production_render_path_exists(self) -> None:
        self.assertIn('if app_mode == "Analysis Details":', self.runtime_source)
        self.assertIn("render_analysis_detail(", self.runtime_source)

    def test_all_nine_sections_defined(self) -> None:
        from src.pages import analysis_detail

        self.assertEqual(analysis_detail.ANALYSIS_SECTIONS, EXPECTED_SECTIONS)
        self.assertEqual(len(EXPECTED_SECTIONS), 9)

    def test_all_nine_sections_have_render_branches(self) -> None:
        for section in EXPECTED_SECTIONS:
            self.assertIn(f'if active_tab == "{section}":', self.detail_source)

    def test_navigation_state_functions_unchanged(self) -> None:
        from src.pages import analysis_detail

        consume = inspect.getsource(analysis_detail._consume_pending_analysis_section)
        sync = inspect.getsource(analysis_detail._sync_cadivor_active_analysis_tab)
        commit = inspect.getsource(analysis_detail._commit_analysis_section_selection)
        render_nav = inspect.getsource(analysis_detail._render_analysis_section_navigation)

        self.assertIn("PENDING_ANALYSIS_SECTION_KEY", consume)
        self.assertIn("cadivor_active_analysis_tab", sync)
        self.assertIn('st.query_params["analysis_tab"]', commit)
        self.assertIn("st.radio", render_nav)
        self.assertIn("_commit_analysis_section_selection", render_nav)

    def test_pending_section_architecture_present(self) -> None:
        self.assertIn("PENDING_ANALYSIS_SECTION_KEY", self.detail_source)
        self.assertIn("PENDING_ANALYSIS_SECTION_ID_KEY", self.detail_source)
        self.assertIn("_consume_pending_analysis_section", self.detail_source)

    def test_deep_link_tab_normalization_present(self) -> None:
        self.assertIn("def _normalize_analysis_tab", self.detail_source)
        self.assertIn('replace("+", " ")', self.detail_source)

    def test_ask_cadivor_section_boundary_intact(self) -> None:
        self.assertIn('if active_tab == "Ask Cadivor":', self.detail_source)
        self.assertIn("render_engineering_assistant", self.detail_source)

    def test_v2_css_injected(self) -> None:
        self.assertIn("_inject_analysis_detail_v2_styles", self.detail_source)
        self.assertIn("analysis_detail_v2.css", self.detail_source)
        self.assertIn("_cadivor_analysis_detail_v2_run_id", self.detail_source)
        self.assertNotIn("_cadivor_analysis_detail_v2_styles", self.detail_source)

    def test_loader_injects_once_per_script_run(self) -> None:
        st, markdown_calls, _ctx = _install_streamlit_stub({})
        detail = self._load_detail()

        first = detail._inject_analysis_detail_v2_styles()
        second = detail._inject_analysis_detail_v2_styles()

        self.assertTrue(first)
        self.assertFalse(second)
        style_calls = [
            content for content, _kwargs in markdown_calls if isinstance(content, str) and "<style" in content
        ]
        self.assertEqual(len(style_calls), 1)
        self.assertIn("cadivor-analysis-detail-v2-css", style_calls[0])
        self.assertEqual(st.session_state.get("_cadivor_analysis_detail_v2_run_id"), "run-a")

    def test_loader_reinjects_on_new_script_run(self) -> None:
        session = {}
        _install_streamlit_stub(session, script_run_id="run-a")
        detail = self._load_detail()

        self.assertTrue(detail._inject_analysis_detail_v2_styles())
        self.assertFalse(detail._inject_analysis_detail_v2_styles())

        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"

        sys.modules.pop("src.pages.analysis_detail", None)
        detail = self._load_detail()

        self.assertTrue(detail._inject_analysis_detail_v2_styles())
        self.assertFalse(detail._inject_analysis_detail_v2_styles())
        self.assertEqual(session.get("_cadivor_analysis_detail_v2_run_id"), "run-b")

    def test_v2_css_uses_ds_v2_tokens(self) -> None:
        missing = [token for token in DS_V2_TOKENS if token not in self.v2_css]
        self.assertFalse(missing, f"analysis_detail_v2.css missing tokens: {missing}")

    def test_no_competing_root_namespace(self) -> None:
        self.assertNotRegex(self.v2_css, r":root\s*\{")

    def test_page_header_uses_ds_v2_primitives(self) -> None:
        for cls in ("cv-page", "cv-page-header", "cv-page-title", "cv-page-subtitle", "cv-badge"):
            self.assertIn(cls, self.detail_source)

    def test_section_header_uses_ds_v2_classes(self) -> None:
        self.assertIn("cv-section-header", self.detail_source)
        self.assertIn("cv-section-title", self.detail_source)
        self.assertIn("cv-section-subtitle", self.detail_source)

    def test_responsive_rules_exist(self) -> None:
        for width in ("1280px", "1024px", "768px"):
            self.assertRegex(self.v2_css, rf"max-width:\s*{re.escape(width)}")

    def test_component_risk_helpers_unchanged(self) -> None:
        from src.pages import analysis_detail

        for fn_name in ("_risk_label", "_health_class", "_part_value"):
            self.assertTrue(callable(getattr(analysis_detail, fn_name)))

    def test_reports_and_alternatives_branches_reachable(self) -> None:
        self.assertIn('if active_tab == "Reports":', self.detail_source)
        self.assertIn('if active_tab == "Alternatives":', self.detail_source)


if __name__ == "__main__":
    unittest.main()
