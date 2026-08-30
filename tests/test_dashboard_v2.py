"""Sprint 72.3 — Dashboard premium experience tests."""
from __future__ import annotations

import ast
import inspect
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_V2_CSS = REPO_ROOT / "src" / "assets" / "css" / "dashboard_v2.css"
DASHBOARD_WORKSPACES = REPO_ROOT / "src" / "pages" / "dashboard_workspaces.py"
LIVING_WORKSPACE = REPO_ROOT / "src" / "living_workspace.py"
AUTHENTICATED_RUNTIME = REPO_ROOT / "src" / "authenticated_runtime.py"
DASHBOARD_PY = REPO_ROOT / "src" / "pages" / "dashboard.py"
ONBOARDING = REPO_ROOT / "src" / "components" / "onboarding.py"

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
    "--cv-space-3",
    "--cv-space-4",
    "--cv-space-5",
    "--cv-radius-lg",
    "--cv-radius-md",
    "--cv-shadow-xs",
    "--cv-shadow-sm",
    "--cv-font-sm",
    "--cv-font-xs",
    "--cv-weight-semibold",
    "--cv-control-sm",
)

DS_V2_CLASSES = (
    ".cv-page",
    ".cv-page-header",
    ".cv-page-title",
    ".cv-page-subtitle",
    ".cv-section-header",
    ".cv-section-title",
    ".cv-card",
    ".cv-card-interactive",
)


class DashboardV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard_v2_css = DASHBOARD_V2_CSS.read_text(encoding="utf-8")
        cls.workspaces_source = DASHBOARD_WORKSPACES.read_text(encoding="utf-8")
        cls.living_source = LIVING_WORKSPACE.read_text(encoding="utf-8")
        cls.runtime_source = AUTHENTICATED_RUNTIME.read_text(encoding="utf-8")
        cls.dashboard_py_source = DASHBOARD_PY.read_text(encoding="utf-8")
        cls.onboarding_source = ONBOARDING.read_text(encoding="utf-8")

    def test_dashboard_v2_css_exists_and_uses_ds_v2_tokens(self) -> None:
        self.assertTrue(DASHBOARD_V2_CSS.is_file())
        missing = [token for token in DS_V2_TOKENS if token not in self.dashboard_v2_css]
        self.assertFalse(missing, f"dashboard_v2.css missing tokens: {missing}")

    def test_no_competing_root_namespace_in_dashboard_v2_css(self) -> None:
        self.assertNotRegex(self.dashboard_v2_css, r":root\s*\{")

    def test_dashboard_production_render_path_in_runtime(self) -> None:
        self.assertIn('if app_mode == "Dashboard":', self.runtime_source)
        self.assertIn("inject_dashboard_workspace_styles()", self.runtime_source)
        self.assertIn("render_dashboard_page_heading()", self.runtime_source)
        self.assertIn("render_dashboard_workspace_navigation(", self.runtime_source)
        self.assertIn("render_engineering_overview_workspace(", self.runtime_source)
        self.assertIn("render_portfolio_intelligence_workspace(", self.runtime_source)

    def test_legacy_render_dashboard_not_used_in_production_entry(self) -> None:
        streamlit_app = (REPO_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertNotIn("render_dashboard(", streamlit_app)
        self.assertIn("def render_dashboard(", self.dashboard_py_source)

    def test_dashboard_v2_styles_injected_from_workspaces(self) -> None:
        self.assertIn("_inject_dashboard_v2_styles", self.workspaces_source)
        self.assertIn("dashboard_v2.css", self.workspaces_source)

    def test_workspace_tab_focus_is_keyboard_only(self) -> None:
        design_css = (REPO_ROOT / "src" / "assets" / "css" / "cadivor_design_system.css").read_text(
            encoding="utf-8"
        )
        workspace_focus_rule = design_css.split(
            'div[data-testid="stVerticalBlock"]:has(.cv672-dashboard-workspace-root) [data-testid="stRadio"] label:has(input:focus-visible)'
        )[1].split('div[data-testid="stVerticalBlock"]:has(.cv672-dashboard-workspace-root) [data-testid="stRadio"] label:has(input:checked)')[0]
        self.assertIn("outline: 2px solid #2563eb", workspace_focus_rule)
        self.assertNotIn(
            'div[data-testid="stVerticalBlock"]:has(.cv672-dashboard-workspace-root) [data-testid="stRadio"] label:focus-within',
            design_css,
        )

    def test_workspace_navigation_uses_clean_underline_links(self) -> None:
        self.assertIn(".cv672-dashboard-nav__link", self.dashboard_v2_css)
        active_rule = self.dashboard_v2_css.split(".cv672-dashboard-nav__link--active {")[1].split("}", 1)[0]
        self.assertIn("border-bottom-color: #2563eb", active_rule)
        self.assertNotIn("background:", active_rule)

    def test_page_header_uses_ds_v2_primitives(self) -> None:
        for cls in ("cv-page", "cv-page-header", "cv-page-title", "cv-page-subtitle"):
            self.assertIn(cls, self.workspaces_source)

    def test_workspace_section_header_uses_ds_v2_section_classes(self) -> None:
        self.assertIn("cv-section-header", self.workspaces_source)
        self.assertIn("cv-section-title", self.workspaces_source)
        self.assertIn("cv-section-subtitle", self.workspaces_source)

    def test_kpi_structure_present(self) -> None:
        self.assertIn("render_kpi_row_safe", self.workspaces_source)
        self.assertIn("render_kpi_row_safe", self.living_source)
        self.assertIn("MetricCard", self.workspaces_source)
        self.assertIn(".cv64-metric-grid", self.dashboard_v2_css)

    def test_current_working_bom_present(self) -> None:
        self.assertIn("Current working BOM", self.workspaces_source)
        self.assertIn("cv6723-bom-strip", self.workspaces_source)
        self.assertIn("Continue analysis", self.workspaces_source)
        self.assertIn("cv-dashboard-bom-card", self.workspaces_source)

    def test_recent_analyses_present(self) -> None:
        self.assertIn("Recent engineering activity", self.workspaces_source)
        self.assertIn("_render_activity_cards", self.workspaces_source)
        self.assertIn("cv6723-activity-card", self.workspaces_source)

    def test_quick_actions_present(self) -> None:
        self.assertIn("cv6723-quick-actions", self.living_source)
        self.assertIn("Engineering Decisions", self.living_source)
        self.assertIn("Monitoring", self.living_source)

    def test_onboarding_empty_state_present(self) -> None:
        self.assertIn("render_first_run_dashboard", self.onboarding_source)
        self.assertIn("Upload my first BOM", self.onboarding_source)
        self.assertIn('if app_mode == "Dashboard":', self.runtime_source)
        self.assertIn("render_first_run_dashboard(", self.runtime_source)

    def test_responsive_rules_exist(self) -> None:
        for width in ("1280px", "1024px", "768px"):
            self.assertRegex(self.dashboard_v2_css, rf"max-width:\s*{re.escape(width)}")

    def test_navigate_to_unchanged(self) -> None:
        from src.ui import navigation

        source = inspect.getsource(navigation.navigate_to)
        self.assertIn('st.session_state["cadivor_route"] = page', source)
        self.assertIn("st.rerun()", source)

    def test_dashboard_data_functions_unchanged_signatures(self) -> None:
        from src.living_workspace import compute_dashboard_summary_metrics
        from src.pages.dashboard_workspaces import build_portfolio_dashboard_context

        metrics_sig = inspect.signature(compute_dashboard_summary_metrics)
        ctx_sig = inspect.signature(build_portfolio_dashboard_context)
        self.assertIn("overview", metrics_sig.parameters)
        self.assertIn("analysis_data", ctx_sig.parameters)

    def test_dashboard_route_unchanged(self) -> None:
        match = re.search(r"NAV_OPTIONS\s*=\s*\[(.*?)\]", self.runtime_source, re.S)
        self.assertIsNotNone(match)
        parsed = ast.literal_eval("[" + match.group(1) + "]")
        self.assertIn("Dashboard", parsed)
        self.assertEqual(parsed[0], "Dashboard")


if __name__ == "__main__":
    unittest.main()
