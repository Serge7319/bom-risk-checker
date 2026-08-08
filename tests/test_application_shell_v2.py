"""Sprint 72.2 — Application shell premium refinement tests."""
from __future__ import annotations

import ast
import inspect
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_SHELL_CSS = REPO_ROOT / "src" / "assets" / "css" / "app_shell.css"
NAV_RECOVERY_CSS = REPO_ROOT / "src" / "assets" / "css" / "navigation_recovery.css"
UNIFIED_SHELL = REPO_ROOT / "src" / "ui" / "unified_shell.py"
NAVIGATION_PY = REPO_ROOT / "src" / "ui" / "navigation.py"
AUTHENTICATED_RUNTIME = REPO_ROOT / "src" / "authenticated_runtime.py"

EXPECTED_NAV_OPTIONS = [
    "Dashboard",
    "BOM Analyzer",
    "Alternative Finder",
    "Monitoring",
    "Engineering Decisions",
    "Procurement Advisor",
    "Portfolio Intelligence",
    "Design Impact Analyzer",
    "Cost Optimization",
    "Supply Risk Scenario",
    "Reports",
    "Pricing",
    "Settings",
    "Workspace",
    "Notifications",
    "Help",
    "About",
]

EXPECTED_NAV_DESTINATIONS = [
    "Dashboard",
    "BOM Analyzer",
    "Alternative Finder",
    "Design Impact Analyzer",
    "Engineering Decisions",
    "Procurement Advisor",
    "Cost Optimization",
    "Supply Risk Scenario",
    "Monitoring",
    "Portfolio Intelligence",
    "Reports",
    "Settings",
    "Help",
]

SHELL_DS_V2_TOKENS = (
    "--cv-bg",
    "--cv-shell-gap",
    "--cv-primary",
    "--cv-primary-subtle",
    "--cv-primary-hover",
    "--cv-surface",
    "--cv-border",
    "--cv-text",
    "--cv-text-muted",
    "--cv-text-secondary",
    "--cv-text-inverse",
    "--cv-page-max",
    "--cv-space-3",
    "--cv-space-4",
    "--cv-radius-md",
    "--cv-radius-lg",
    "--cv-shadow-xs",
    "--cv-shadow-sm",
    "--cv-shadow-lg",
    "--cv-weight-semibold",
    "--cv-control-sm",
    "--cv-control-md",
    "--cv-danger",
    "--cv-danger-bg",
)


class ApplicationShellV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app_shell_css = APP_SHELL_CSS.read_text(encoding="utf-8")
        cls.nav_recovery_css = NAV_RECOVERY_CSS.read_text(encoding="utf-8")
        cls.unified_shell_source = UNIFIED_SHELL.read_text(encoding="utf-8")
        cls.navigation_source = NAVIGATION_PY.read_text(encoding="utf-8")
        cls.runtime_source = AUTHENTICATED_RUNTIME.read_text(encoding="utf-8")

    def test_app_shell_css_uses_ds_v2_tokens(self) -> None:
        missing = [token for token in SHELL_DS_V2_TOKENS if token not in self.app_shell_css]
        self.assertFalse(missing, f"app_shell.css missing DS v2 tokens: {missing}")

    def test_navigation_recovery_uses_ds_v2_tokens(self) -> None:
        for token in ("--cv-primary", "--cv-foundation-rail-active-bg", "--cv-font-sm", "--cv-weight-semibold"):
            self.assertIn(token, self.nav_recovery_css, f"navigation_recovery.css should reference {token}")

    def test_foundation_vars_bridge_to_ds_v2(self) -> None:
        self.assertIn("--cv-foundation-bg:var(--cv-bg", self.app_shell_css)
        self.assertIn("--cv-foundation-gutter:var(--cv-shell-gap", self.app_shell_css)
        self.assertIn("--cv-foundation-rail-active-accent:var(--cv-primary", self.app_shell_css)

    def test_main_content_uses_page_max_and_shell_gap(self) -> None:
        self.assertIn("max-width:var(--cv-page-max", self.app_shell_css)
        self.assertIn("var(--cv-foundation-gutter)", self.app_shell_css)

    def test_nav_options_route_ids_unchanged(self) -> None:
        match = re.search(r"NAV_OPTIONS\s*=\s*\[(.*?)\]", self.runtime_source, re.S)
        self.assertIsNotNone(match)
        parsed = ast.literal_eval("[" + match.group(1) + "]")
        self.assertEqual(parsed, EXPECTED_NAV_OPTIONS)

    def test_nav_groups_destinations_unchanged(self) -> None:
        from src.ui.unified_shell import NAV_GROUPS

        destinations = [destination for _, rows in NAV_GROUPS for _, _, destination in rows]
        self.assertEqual(destinations, EXPECTED_NAV_DESTINATIONS)

    def test_nav_groups_render_all_four_groups(self) -> None:
        from src.ui.unified_shell import NAV_GROUPS

        group_names = [name for name, _ in NAV_GROUPS]
        self.assertEqual(group_names, ["Analyze", "Decide", "Monitor", "Workspace"])
        self.assertEqual(len(NAV_GROUPS), 4)

    def test_commit_navigation_logic_unchanged(self) -> None:
        from src.ui import unified_shell

        source = inspect.getsource(unified_shell._commit_navigation)
        self.assertIn('st.session_state["cadivor_route"] = page', source)
        self.assertIn('st.session_state["app_mode"] = page', source)
        self.assertIn('st.session_state["cadivor_nav_params"] = {"page": page}', source)
        self.assertNotIn("navigate_to", source)

    def test_navigate_to_behavior_unchanged(self) -> None:
        source = inspect.getsource(__import__("src.ui.navigation", fromlist=["navigate_to"]).navigate_to)
        self.assertIn('st.session_state["cadivor_route"] = page', source)
        self.assertIn('st.session_state["app_mode"] = page', source)
        self.assertIn("st.rerun()", source)

    def test_logout_callback_still_requests_logout(self) -> None:
        self.assertIn("request_logout()", self.unified_shell_source)
        self.assertIn('st.session_state["cadivor_explicit_logout"] = True', self.unified_shell_source)
        self.assertIn('key="cv_foundation_signout"', self.unified_shell_source)

    def test_profile_dropdown_container_present(self) -> None:
        self.assertIn('key="cv_foundation_profile_menu"', self.unified_shell_source)
        self.assertIn("st.popover", self.unified_shell_source)

    def test_search_chip_wired_to_command_center(self) -> None:
        self.assertIn("cv-foundation-search", self.unified_shell_source)
        self.assertIn("cadivor-search-pill", self.unified_shell_source)
        command_center = (REPO_ROOT / "src" / "components" / "command_center.py").read_text(encoding="utf-8")
        self.assertIn(".cv-foundation-search", command_center)

    def test_workspace_not_decorative_button(self) -> None:
        self.assertNotIn('cv-foundation-workspace" role="button"', self.unified_shell_source)

    def test_responsive_breakpoints_present(self) -> None:
        for width in ("1280px", "1100px", "1024px", "768px"):
            self.assertIn(f"max-width:{width}", self.app_shell_css)

    def test_active_nav_uses_primary_tokens(self) -> None:
        self.assertIn("--cv-foundation-rail-active-bg", self.app_shell_css)
        self.assertIn("--cv-foundation-rail-active-accent", self.app_shell_css)
        self.assertIn(":focus-visible", self.app_shell_css)


if __name__ == "__main__":
    unittest.main()
