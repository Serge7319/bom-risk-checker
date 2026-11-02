"""Regression: temporary route-loading headings must clear before real titles."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


def _branch(start_marker: str, end_marker: str) -> str:
    start = RUNTIME.index(start_marker)
    end = RUNTIME.index(end_marker, start)
    return RUNTIME[start:end]


class RouteLoadingTitleHandoffTests(unittest.TestCase):
    def test_monitoring_clears_loading_hero_before_real_content(self):
        branch = _branch(
            'if app_mode == "Monitoring":',
            'if app_mode == "Supply Risk Scenario":',
        )
        self.assertIn("_monitoring_loading_placeholder = st.empty()", branch)
        self.assertIn('data-cadivor-destination-shell="Monitoring"', branch)
        clear_at = branch.index("_monitoring_loading_placeholder.empty()")
        # Cleared once after data resolution, before DataFrame / overview paint.
        overview_at = branch.index("render_monitoring(")
        self.assertLess(clear_at, overview_at)
        self.assertIn(
            'budget_seconds=6.0',
            branch,
        )
        # Timeout / error paths without a snapshot also clear before stop.
        self.assertGreaterEqual(branch.count("_monitoring_loading_placeholder.empty()"), 3)

    def test_design_impact_clears_loading_heading_before_canonical_title(self):
        branch = _branch(
            'if app_mode == "Design Impact Analyzer":',
            'if app_mode == "Portfolio Intelligence":',
        )
        self.assertIn("_impact_loading_placeholder = st.empty()", branch)
        self.assertIn('data-cadivor-destination-shell="Design Impact Analyzer"', branch)
        clear_at = branch.index("_impact_loading_placeholder.empty()")
        render_at = branch.index("render_design_impact(")
        self.assertLess(clear_at, render_at)

    def test_cost_optimization_clears_loading_heading_before_canonical_title(self):
        branch = _branch(
            "# ---------- Cost Optimization ----------",
            "# ---------- Design Impact Analyzer ----------",
        )
        self.assertIn("_cost_loading_placeholder = st.empty()", branch)
        self.assertIn('data-cadivor-destination-shell="Cost Optimization"', branch)
        clear_at = branch.index("_cost_loading_placeholder.empty()")
        render_at = branch.index("render_cost_optimization(")
        self.assertLess(clear_at, render_at)

    def test_supply_risk_clears_loading_heading_before_canonical_title(self):
        branch = _branch(
            "# ---------- Supply Risk Scenario ----------",
            "# ---------- Cost Optimization ----------",
        )
        self.assertIn("_supply_loading_placeholder = st.empty()", branch)
        self.assertIn('data-cadivor-destination-shell="Supply Risk Scenario"', branch)
        clear_at = branch.index("_supply_loading_placeholder.empty()")
        render_at = branch.index("render_supply_scenario_dashboard(")
        self.assertLess(clear_at, render_at)

    def test_analysis_details_handoff_hides_sibling_chrome_until_report(self):
        branch = _branch(
            'if app_mode == "Analysis Details":',
            'if app_mode == "Monitoring":',
        )
        self.assertIn(
            "body:has(.st-key-bom8_analysis_progress_card):not(:has(.cv-ei-report))",
            branch,
        )
        self.assertIn(
            "st-key-approved_page_canvas_standard_analysis_detail",
            branch.split("body:has(.st-key-bom8_analysis_progress_card):not(:has(.cv-ei-report))", 1)[1],
        )
        self.assertIn("width:calc(100% - 48px)!important", branch)
        self.assertIn("max-width:1440px!important", branch)
        self.assertIn("padding-top:30px!important", branch)

    def test_bom_analyzer_widens_form_progress_and_report_canvas(self):
        self.assertIn(
            "section[data-testid=\"stMain\"] [data-testid=\"stMainBlockContainer\"]:has(.st-key-approved_bom_upload_panel)",
            RUNTIME,
        )
        self.assertIn(
            "section[data-testid=\"stMain\"] [data-testid=\"stMainBlockContainer\"]:has(.st-key-approved_bom_title)",
            RUNTIME,
        )
        self.assertIn(
            "section[data-testid=\"stMain\"] [data-testid=\"stMainBlockContainer\"]:has(.cv-ei-report)",
            RUNTIME,
        )
        self.assertIn("width:calc(100% - 48px)!important", RUNTIME)

    def test_always_on_css_hides_details_chrome_during_saving(self):
        css = (ROOT / "src" / "assets" / "css" / "monitoring_home_alignment.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "body:has(.st-key-bom8_analysis_progress_card):not(:has(.cv-ei-report))",
            css,
        )
        self.assertIn("st-key-approved_page_canvas_standard_analysis_detail", css)
        self.assertIn("padding-top: 30px !important;", css)


if __name__ == "__main__":
    unittest.main()
