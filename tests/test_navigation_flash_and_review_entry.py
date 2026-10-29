"""Regression checks for visible BOM review entry and flash-free transitions."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BROWSER_BRIDGE = (
    ROOT / "src" / "components" / "browser_navigation" / "index.html"
).read_text(encoding="utf-8")
BOM_UPLOAD_FLOW = (ROOT / "src" / "bom_upload_flow.py").read_text(encoding="utf-8")
BOM_NAVIGATION = (ROOT / "src" / "ui" / "bom_navigation.py").read_text(encoding="utf-8")
APPROVED_PAGES = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
MAIN_TRANSITION = (ROOT / "src" / "ui" / "main_transition.py").read_text(encoding="utf-8")


class NavigationFlashAndReviewEntryTests(unittest.TestCase):
    def test_immediate_cover_starts_before_sidebar_and_report_tab_reruns(self):
        self.assertIn('doc.addEventListener("pointerdown", handleTransitionClick, true)', BROWSER_BRIDGE)
        self.assertIn('[class*="st-key-cv_foundation_navigation"]', BROWSER_BRIDGE)
        self.assertIn('[class*="st-key-cv_analysis_section_nav"]', BROWSER_BRIDGE)
        self.assertIn('id = "cadivor-instant-navigation-transition"', BROWSER_BRIDGE)
        self.assertIn(".cv-main-transition.cv-route-loading", BROWSER_BRIDGE)
        self.assertIn("data-cadivor-page-body-gen", BROWSER_BRIDGE)
        self.assertIn("min-width:190px!important", BROWSER_BRIDGE)
        self.assertIn("flex:0 0 32px!important", BROWSER_BRIDGE)
        self.assertIn('"Opening " + normalized + "…"', BROWSER_BRIDGE)

    def test_transition_chip_waits_for_a_new_server_generation(self):
        self.assertIn("function hasVisiblePythonCover(afterGeneration = \"\")", BROWSER_BRIDGE)
        self.assertIn("generation === afterGeneration", BROWSER_BRIDGE)
        self.assertIn("hasVisiblePythonCover(previousGeneration)", BROWSER_BRIDGE)

    def test_runtime_geometry_lock_survives_reruns_without_measuring_the_rail(self):
        self.assertIn('root.setAttribute("data-cadivor-shell-locked", "1")', BROWSER_BRIDGE)
        self.assertIn('[data-cadivor-signed-out-surface="1"]', BROWSER_BRIDGE)
        self.assertIn("html[data-cadivor-shell-locked='1']", BROWSER_BRIDGE)
        self.assertIn("var(--cv-foundation-rail,296px)", BROWSER_BRIDGE)
        self.assertNotIn("getBoundingClientRect().width", BROWSER_BRIDGE)
        self.assertNotIn("ResizeObserver", BROWSER_BRIDGE)
        self.assertIn("max-width:16px!important;max-height:16px!important", BROWSER_BRIDGE)

    def test_python_transition_also_clamps_sidebar_glyphs_while_rerendering(self):
        self.assertIn('body:has([data-cadivor-main-transition="1"])', MAIN_TRANSITION)
        self.assertIn("max-width:16px!important;max-height:16px!important", MAIN_TRANSITION)

    def test_old_transition_cover_cannot_release_a_new_navigation_chip(self):
        self.assertIn("cover.closest('[data-stale=\"true\"]')", BROWSER_BRIDGE)
        self.assertIn("body:has(#cadivor-instant-navigation-transition)", BROWSER_BRIDGE)

    def test_history_navigation_uses_a_nonblocking_chip(self):
        history = BROWSER_BRIDGE.split("function showHistoryTransition", 1)[1].split(
            "function finishHistoryTransition", 1
        )[0]
        self.assertIn("background: transparent !important", history)
        self.assertIn("pointer-events: none !important", history)
        self.assertNotIn("background: #F5F7FB", history)
        self.assertIn("Opening ${page}…", history)

    def test_new_analysis_arms_a_route_cover_before_the_form_rerenders(self):
        prepare = BOM_UPLOAD_FLOW.split(
            "def prepare_new_approved_bom_analysis", 1
        )[1].split("\n\ndef should_render_legacy_bom_workspace", 1)[0]
        self.assertIn("arm_main_transition(", prepare)
        self.assertIn('"BOM Analyzer"', prepare)
        self.assertIn('kind="navigation"', prepare)

    def test_saved_bom_review_is_a_visible_direct_parts_and_risk_action(self):
        actions = APPROVED_PAGES.split(
            "def _render_saved_bom_actions", 1
        )[1].split("\n\ndef _delete_saved_bom", 1)[0]
        self.assertIn('"Engineering Intelligence"', actions)
        self.assertNotIn('"Parts & Risk"', actions)
        self.assertIn('key=f"approved_{scope}_action_review_{row_key}"', actions)
        self.assertIn("_open_saved_bom_engineering_intelligence(target)", actions)
        self.assertIn("2.05", APPROVED_PAGES.split("home_widths =", 1)[1].split("\n", 1)[0])
        self.assertIn("2.05", APPROVED_PAGES.split("bom_widths =", 1)[1].split("\n", 1)[0])

    def test_saved_bom_tabs_and_more_routes_arm_transitions(self):
        self.assertIn("_arm_saved_bom_section_transition(state)", BOM_NAVIGATION)
        self.assertIn("navigate_to(route, _rerun=False, **params)", BOM_NAVIGATION)


if __name__ == "__main__":
    unittest.main()
