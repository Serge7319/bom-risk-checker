"""Regression contracts for production follow-up defects.

These are code/fixture contracts. Live Streamlit transition samples are recorded
separately under .evidence/ when the local 1.60 app is exercised.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProdFollowupDefectRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transition = (ROOT / "src/ui/main_transition.py").read_text(encoding="utf-8")
        cls.nav = (ROOT / "src/components/browser_navigation/index.html").read_text(encoding="utf-8")
        cls.approved = (ROOT / "src/ui/approved_pages.py").read_text(encoding="utf-8")
        cls.runtime = (ROOT / "src/authenticated_runtime.py").read_text(encoding="utf-8")
        cls.evidence = (ROOT / "src/compare_evidence_search.py").read_text(encoding="utf-8")
        cls.parts = (ROOT / "src/parts_compare.py").read_text(encoding="utf-8")

    def test_shell_lock_stays_during_navigation_remount(self):
        self.assertIn(
            "Keep the workspace width stable while Streamlit remounts the rail",
            self.nav,
        )
        self.assertIn(
            "body:has(#cadivor-instant-navigation-transition) section[data-testid='stMain']:not([data-stale='true'])",
            self.nav,
        )

    def test_navigation_cover_does_not_double_apply_rail_inset(self):
        nav_css = self.transition.split(
            '.cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"]{{',
            1,
        )[1].split("}}", 1)[0]
        self.assertIn("left:0!important", nav_css)
        self.assertIn("right:0!important", nav_css)
        self.assertIn("top:0!important", nav_css)
        self.assertIn("width:auto!important", nav_css)
        self.assertNotIn("left:var(--cv-foundation-rail,228px)!important", nav_css)
        self.assertIn("left:0;right:0;top:0;bottom:0;width:auto", self.transition)
        self.assertIn('pythonCover.style.setProperty("visibility", "hidden", "important")', self.nav)
        self.assertNotIn("cover.remove();", self.nav.split("if (pythonCover)", 1)[1].split("const previousGeneration", 1)[0])

    def test_bom_analyze_helper_uses_separated_top_aligned_tracks(self):
        self.assertIn("[0.22, 0.78], gap=\"medium\", vertical_alignment=\"top\"", self.approved)
        self.assertIn(
            ".st-key-approved_bom_submit_row [data-testid=\"column\"]:first-child{flex:0 0 168px!important",
            self.approved,
        )
        self.assertIn("align-items:flex-start!important", self.approved)

    def test_home_actions_fit_without_forced_1240px_scroll(self):
        self.assertNotIn("min-width:1240px!important", self.approved)
        self.assertIn("grid-template-columns:2.0fr 1.15fr .7fr .75fr .9fr 1.0fr 1.7fr!important", self.approved)
        self.assertIn("home_widths = [2.0, 1.15, 0.7, 0.75, 0.9, 1.0, 1.7]", self.approved)
        self.assertIn("position:sticky!important;right:0!important", self.approved)
        # Keep a single Engineering Intelligence CTA path (button, not duplicated menu item).
        home_actions = self.approved.split("def _render_saved_bom_actions", 1)[1].split("def _delete_saved_bom", 1)[0]
        # One visible CTA plus the session/tab wiring for that same destination.
        self.assertGreaterEqual(home_actions.count('"Engineering Intelligence"'), 1)
        self.assertNotIn('"Open Engineering Intelligence"', home_actions)
        menu_items = [
            line for line in home_actions.splitlines()
            if "Engineering Intelligence" in line and ("st.button" in line or "popover" in line.lower() or "menu" in line.lower())
        ]
        # The overflow menu must not reintroduce a second Engineering Intelligence item.
        self.assertLessEqual(len(menu_items), 1)

    def test_procurement_decision_support_matches_section_heading_scale(self):
        branch = self.runtime.split('if app_mode == "Procurement Advisor":', 1)[1].split(
            'if app_mode == "Engineering Decisions":', 1
        )[0]
        self.assertIn("DECISION SUPPORT", branch)
        self.assertIn("<h2>Next steps</h2>", branch)
        self.assertIn("font-size:26px!important;font-weight:800!important;line-height:1.2!important", branch)
        self.assertIn(".st-key-cv_pa_next_steps [data-testid=\"stMarkdownContainer\"] h2", branch)
        from src.procurement_advisor import _supplier_coverage_copy
        coverage, detail, row_summary = _supplier_coverage_copy(2, [{"supplier": "DigiKey"}])
        self.assertEqual(coverage, "2 recorded sources")
        self.assertEqual(row_summary, "1 saved offer row shown")
        self.assertIn(row_summary, detail)

    def test_compare_reuses_digikey_supplier_record_and_skips_public_html(self):
        self.assertIn("supplier_record: Mapping[str, Any] | None = None", self.evidence)
        self.assertIn("skip_public_html = digikey_verified", self.evidence)
        self.assertIn("supplier_record=part", self.parts)
        self.assertIn("DigiKey product listing", self.evidence)
        self.assertNotIn('"page": "DigiKey API"', self.evidence)

    def test_monitoring_focused_handoff_uses_one_component_hierarchy(self):
        branch = self.runtime.split('if app_mode == "Monitoring":', 1)[1].split(
            'if app_mode == "Supply Risk Scenario":', 1
        )[0]
        self.assertIn('snapshot_eyebrow = "Component monitoring"', branch)
        self.assertIn('workspace_eyebrow = "Filtered component view"', branch)
        self.assertIn("if focused_monitor_part:", branch)
        self.assertIn('include_header=True', branch.split('if monitor_view == "overview":', 1)[1].split("monitoring_snapshot", 1)[0])
        # Overview keeps equal-width KPI contract elsewhere; focused path keeps component context.
        self.assertIn("value=focused_monitor_part", branch)


    def test_digikey_supplier_record_reuse_executes(self):
        from src.compare_evidence_search import _try_digikey_api_exact_mpn
        record = {
            "source": "DigiKey",
            "manufacturer_part_number": "LM358DR",
            "manufacturer": "Texas Instruments",
            "product_detail_url": "https://www.digikey.com/en/products/detail/example/1",
        }
        status, doc = _try_digikey_api_exact_mpn(
            mpn="LM358DR",
            manufacturer="Texas Instruments",
            supplier_record=record,
        )
        self.assertTrue(status.get("identity_verified"))
        self.assertEqual(doc.get("source_name"), "DigiKey product listing")
        self.assertNotIn("API", str(doc.get("source_name") or ""))

    def test_new_bom_force_releases_opening_when_upload_form_ready(self):
        self.assertIn("_upload_form_ready", self.runtime)
        self.assertIn("force=_upload_form_ready", self.runtime)
        self.assertIn("_prefer_upload_form", self.runtime)
        reveal_fn = self.transition.split("def reveal_main_transition", 1)[1].split(
            "\ndef ", 1
        )[0]
        self.assertIn('data-cadivor-page-body-release-gen="{gen}"', reveal_fn)
        self.assertNotIn('if transition_kind != "navigation"', reveal_fn)

    def test_digikey_token_cache_helper_parses(self):
        source = (ROOT / "integrations/digikey_client.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertIn("get_digikey_access_token", names)
        self.assertIn("_DIGIKEY_TOKEN_LOCK", source)
        self.assertIn("_DIGIKEY_CACHED_TOKEN", source)


if __name__ == "__main__":
    unittest.main()
