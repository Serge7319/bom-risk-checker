"""Sprint 72.1 — Cadivor Design System v2 foundation tests."""
from __future__ import annotations

import importlib
import re
import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DS_V2_CSS = REPO_ROOT / "src" / "assets" / "css" / "cadivor_design_system_v2.css"

REQUIRED_TOKENS = (
    "--cv-bg",
    "--cv-bg-subtle",
    "--cv-surface",
    "--cv-surface-raised",
    "--cv-surface-muted",
    "--cv-border",
    "--cv-border-strong",
    "--cv-text",
    "--cv-text-secondary",
    "--cv-text-muted",
    "--cv-text-inverse",
    "--cv-primary",
    "--cv-primary-hover",
    "--cv-primary-subtle",
    "--cv-success",
    "--cv-success-bg",
    "--cv-warning",
    "--cv-warning-bg",
    "--cv-danger",
    "--cv-danger-bg",
    "--cv-info",
    "--cv-info-bg",
    "--cv-font-family",
    "--cv-font-xs",
    "--cv-font-sm",
    "--cv-font-md",
    "--cv-font-lg",
    "--cv-font-xl",
    "--cv-font-2xl",
    "--cv-font-3xl",
    "--cv-line-tight",
    "--cv-line-normal",
    "--cv-weight-regular",
    "--cv-weight-medium",
    "--cv-weight-semibold",
    "--cv-weight-bold",
    "--cv-space-1",
    "--cv-space-2",
    "--cv-space-3",
    "--cv-space-4",
    "--cv-space-5",
    "--cv-space-6",
    "--cv-space-8",
    "--cv-space-10",
    "--cv-space-12",
    "--cv-radius-sm",
    "--cv-radius-md",
    "--cv-radius-lg",
    "--cv-radius-xl",
    "--cv-radius-pill",
    "--cv-shadow-xs",
    "--cv-shadow-sm",
    "--cv-shadow-md",
    "--cv-shadow-lg",
    "--cv-control-sm",
    "--cv-control-md",
    "--cv-control-lg",
    "--cv-page-max",
    "--cv-content-max",
    "--cv-reading-max",
    "--cv-shell-gap",
)

REQUIRED_PRIMITIVES = (
    ".cv-page",
    ".cv-page-header",
    ".cv-page-title",
    ".cv-page-subtitle",
    ".cv-section",
    ".cv-section-header",
    ".cv-section-title",
    ".cv-section-subtitle",
    ".cv-card",
    ".cv-card-raised",
    ".cv-card-interactive",
    ".cv-card-header",
    ".cv-card-title",
    ".cv-card-body",
    ".cv-card-footer",
    ".cv-kpi-grid",
    ".cv-kpi-card",
    ".cv-kpi-label",
    ".cv-kpi-value",
    ".cv-kpi-meta",
    ".cv-btn",
    ".cv-btn-primary",
    ".cv-btn-secondary",
    ".cv-btn-ghost",
    ".cv-btn-danger",
    ".cv-btn-sm",
    ".cv-badge",
    ".cv-badge-neutral",
    ".cv-badge-success",
    ".cv-badge-warning",
    ".cv-badge-danger",
    ".cv-badge-info",
    ".cv-field",
    ".cv-label",
    ".cv-help",
    ".cv-input-shell",
    ".cv-table-shell",
    ".cv-empty-state",
    ".cv-loading-state",
    ".cv-inline-alert",
    ".cv-grid-4",
    ".cv-grid-3",
    ".cv-grid-2",
    ".cv-stack-responsive",
)

LEGACY_ALIASES = (
    "--cadivor-blue: var(--cv-primary)",
    "--cvds-blue: var(--cv-primary)",
    "--cv64-blue: var(--cv-primary)",
    "--radius-card: var(--cv-radius-sm)",
    "--control-height: var(--cv-control-md)",
)


def _install_streamlit_stub(session_state: dict | None = None, *, script_run_id: str = "run-a"):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    markdown_calls = []
    st.markdown = lambda content, **kwargs: markdown_calls.append((content, kwargs))
    st.error = lambda message: markdown_calls.append(("error", message))

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


class CadivorDesignSystemV2Tests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("src.ui.design_system_v2", None)

    def _load_v2(self):
        return importlib.import_module("src.ui.design_system_v2")

    def test_css_has_single_root_block(self):
        css = DS_V2_CSS.read_text(encoding="utf-8")
        self.assertEqual(css.count(":root {"), 1)
        self.assertEqual(css.count(":root{"), 0)

    def test_required_semantic_tokens_exist(self):
        css = DS_V2_CSS.read_text(encoding="utf-8")
        for token in REQUIRED_TOKENS:
            self.assertIn(token, css, msg=f"missing token {token}")

    def test_legacy_aliases_reference_v2_tokens(self):
        css = DS_V2_CSS.read_text(encoding="utf-8")
        for alias in LEGACY_ALIASES:
            self.assertIn(alias, css, msg=f"missing alias {alias}")

    def test_primitive_classes_exist(self):
        css = DS_V2_CSS.read_text(encoding="utf-8")
        for primitive in REQUIRED_PRIMITIVES:
            self.assertIn(primitive, css, msg=f"missing primitive {primitive}")

    def test_responsive_breakpoints_exist(self):
        css = DS_V2_CSS.read_text(encoding="utf-8")
        for breakpoint in ("1280px", "1024px", "768px"):
            self.assertIn(f"max-width: {breakpoint}", css)

    def test_streamlit_selectors_scoped_to_main(self):
        css = DS_V2_CSS.read_text(encoding="utf-8")
        self.assertIn('section[data-testid="stMain"] .stButton > button', css)
        self.assertNotRegex(
            css,
            r"^\.stButton",
            msg="Streamlit button selectors must not be global",
        )

    def test_loader_injects_once_per_script_run(self):
        st, markdown_calls, _ctx = _install_streamlit_stub({})
        ds_v2 = self._load_v2()

        first = ds_v2.inject_cadivor_design_system_v2()
        second = ds_v2.inject_cadivor_design_system_v2()

        self.assertTrue(first)
        self.assertFalse(second)
        style_calls = [
            content for content, _kwargs in markdown_calls if isinstance(content, str) and "<style" in content
        ]
        self.assertEqual(len(style_calls), 1)
        self.assertIn("cadivor-design-system-v2", style_calls[0])
        self.assertEqual(st.session_state.get("_cadivor_design_system_v2_run_id"), "run-a")
        self.assertNotIn("_cadivor_design_system_v2_injected", st.session_state)

    def test_loader_reinjects_on_new_script_run(self):
        session = {}
        _install_streamlit_stub(session, script_run_id="run-a")
        ds_v2 = self._load_v2()

        self.assertTrue(ds_v2.inject_cadivor_design_system_v2())
        self.assertFalse(ds_v2.inject_cadivor_design_system_v2())

        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"
        markdown_calls = []
        sys.modules["streamlit"].markdown = lambda content, **kwargs: markdown_calls.append(
            (content, kwargs)
        )

        self.assertTrue(ds_v2.inject_cadivor_design_system_v2())
        self.assertFalse(ds_v2.inject_cadivor_design_system_v2())
        self.assertEqual(session.get("_cadivor_design_system_v2_run_id"), "run-b")
        style_calls = [
            content for content, _kwargs in markdown_calls if isinstance(content, str) and "<style" in content
        ]
        self.assertEqual(len(style_calls), 1)

    def test_authenticated_stack_reinjects_v2_each_run(self):
        session = {}
        _install_streamlit_stub(session, script_run_id="run-a")
        sys.modules.pop("src.ui.design_system_v1", None)
        design_system_v1 = importlib.import_module("src.ui.design_system_v1")

        run_a_calls = []
        sys.modules["streamlit"].markdown = lambda content, **kwargs: run_a_calls.append(
            (content, kwargs)
        )
        design_system_v1.inject_design_system_v1()
        run_a_v2 = [
            content
            for content, _kwargs in run_a_calls
            if isinstance(content, str) and "cadivor-design-system-v2" in content
        ]
        self.assertEqual(len(run_a_v2), 1)

        from streamlit.runtime.scriptrunner import get_script_run_ctx

        get_script_run_ctx().script_run_id = "run-b"
        run_b_calls = []
        sys.modules["streamlit"].markdown = lambda content, **kwargs: run_b_calls.append(
            (content, kwargs)
        )
        design_system_v1.inject_design_system_v1()
        run_b_v2 = [
            content
            for content, _kwargs in run_b_calls
            if isinstance(content, str) and "cadivor-design-system-v2" in content
        ]
        self.assertEqual(len(run_b_v2), 1)
        self.assertEqual(session.get("_cadivor_design_system_v2_run_id"), "run-b")

    def test_loader_does_not_touch_auth_routing_keys(self):
        session = {
            "cadivor_auth_status": "authenticated",
            "cadivor_route": "Dashboard",
            "cadivor_active_analysis_tab": "Overview",
        }
        before = dict(session)
        _install_streamlit_stub(session)
        ds_v2 = self._load_v2()
        ds_v2.inject_cadivor_design_system_v2()
        self.assertEqual(session["cadivor_auth_status"], before["cadivor_auth_status"])
        self.assertEqual(session["cadivor_route"], before["cadivor_route"])
        self.assertEqual(
            session["cadivor_active_analysis_tab"],
            before["cadivor_active_analysis_tab"],
        )
        self.assertNotIn("cadivor_pending_analysis_section", session)

    def test_core_premium_ui_does_not_call_v2_loader(self):
        source = (REPO_ROOT / "src" / "ui" / "core_premium_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("inject_cadivor_design_system_v2", source)

    def test_design_system_v1_calls_v2_loader_first(self):
        source = (REPO_ROOT / "src" / "ui" / "design_system_v1.py").read_text(encoding="utf-8")
        self.assertIn("inject_cadivor_design_system_v2", source)
        self.assertLess(
            source.index("inject_cadivor_design_system_v2"),
            source.index("design_system_v1.css"),
        )

    def test_protected_auth_files_unmodified(self):
        auth_state = (REPO_ROOT / "src" / "auth_state.py").read_text(encoding="utf-8")
        auth_bootstrap = (REPO_ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        auth_cookies = (REPO_ROOT / "src" / "auth_cookies.py").read_text(encoding="utf-8")
        self.assertNotIn("design_system_v2", auth_state)
        self.assertNotIn("design_system_v2", auth_bootstrap)
        self.assertNotIn("design_system_v2", auth_cookies)

    def test_load_css_reads_file(self):
        ds_v2 = self._load_v2()
        css = ds_v2.load_cadivor_design_system_v2_css()
        self.assertIn("--cv-primary:", css)
        self.assertGreater(len(css), 1000)


if __name__ == "__main__":
    unittest.main()
