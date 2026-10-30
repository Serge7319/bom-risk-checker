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
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


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

    def test_transition_cover_waits_for_the_destination_release_marker(self):
        self.assertIn("function hasReleasedDestination(previousGeneration = \"\")", BROWSER_BRIDGE)
        self.assertIn("data-cadivor-page-body-release-gen", BROWSER_BRIDGE)
        self.assertIn("releasedGeneration === generation", BROWSER_BRIDGE)
        self.assertNotIn("hasVisiblePythonCover", BROWSER_BRIDGE)

    def test_route_transition_never_clones_the_outgoing_page_or_open_menus(self):
        self.assertNotIn("captureTransitionSnapshot", BROWSER_BRIDGE)
        self.assertNotIn("source.cloneNode(true)", BROWSER_BRIDGE)
        self.assertNotIn("data-cadivor-transition-snapshot", BROWSER_BRIDGE)
        self.assertIn("function showImmediateCover(label)", BROWSER_BRIDGE)
        self.assertIn("const pythonCover = Array.from(doc.querySelectorAll(", BROWSER_BRIDGE)
        self.assertIn("if (pythonCover) {", BROWSER_BRIDGE)
        self.assertIn("cover.remove();", BROWSER_BRIDGE)
        self.assertIn("hasReleasedDestination(previousGeneration)", BROWSER_BRIDGE)

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
        self.assertIn("!marker.closest('[data-stale=\"true\"]')", BROWSER_BRIDGE)
        self.assertIn("body:has(#cadivor-instant-navigation-transition)", BROWSER_BRIDGE)

    def test_history_navigation_covers_the_outgoing_workspace(self):
        history = BROWSER_BRIDGE.split("function showHistoryTransition", 1)[1].split(
            "function finishHistoryTransition", 1
        )[0]
        self.assertIn("background: #F5F7FB !important", history)
        self.assertIn("pointer-events: auto !important", history)
        self.assertIn("Opening ${page}…", history)

    def test_immediate_cover_masks_the_workspace_until_safe_handoff(self):
        style = BROWSER_BRIDGE.split(
            "#cadivor-instant-navigation-transition{", 1
        )[1].split("}',", 1)[0]
        release = BROWSER_BRIDGE.split("function queueReleaseCheck()", 1)[1].split(
            "function installStyle()", 1
        )[0]
        self.assertIn("left:var(--cv-foundation-rail,296px)", style)
        self.assertIn("right:0", style)
        self.assertIn("background:#F5F7FB", style)
        self.assertIn("pointer-events:auto", style)
        self.assertNotIn("background:transparent", style)
        self.assertIn("hasReleasedDestination(previousGeneration)", release)
        self.assertIn("if (pythonCover)", release)
        self.assertIn("cover.remove()", release)
        self.assertNotIn("currentGeneration !== previousGeneration", release)

    def test_bom_progress_slot_precedes_the_full_width_upload_form(self):
        status_slot = RUNTIME.index("bom_analysis_status_slot = st.empty()")
        upload_slot = RUNTIME.index("bom_new_analysis_slot = st.empty()")
        workspace_layout = RUNTIME.split(".st-key-bom9_workspace_grid{margin-top:2px;}", 1)[1].split(
            "div[data-testid=\"stVerticalBlockBorderWrapper\"]:has(.bom9-upload-marker)", 1
        )[0]
        self.assertLess(status_slot, upload_slot)
        self.assertIn("display:grid!important", workspace_layout)
        self.assertIn("grid-template-columns:minmax(0,1fr)!important", workspace_layout)
        self.assertIn("width:100%!important", workspace_layout)

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
