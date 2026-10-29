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


class NavigationFlashAndReviewEntryTests(unittest.TestCase):
    def test_immediate_cover_starts_before_sidebar_and_report_tab_reruns(self):
        self.assertIn('doc.addEventListener("pointerdown", handleTransitionClick, true)', BROWSER_BRIDGE)
        self.assertIn('[class*="st-key-cv_foundation_navigation"]', BROWSER_BRIDGE)
        self.assertIn('[class*="st-key-cv_analysis_section_nav"]', BROWSER_BRIDGE)
        self.assertIn('id = "cadivor-instant-navigation-transition"', BROWSER_BRIDGE)
        self.assertIn(".cv-main-transition.cv-route-loading", BROWSER_BRIDGE)
        self.assertIn("data-cadivor-page-body-gen", BROWSER_BRIDGE)

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
