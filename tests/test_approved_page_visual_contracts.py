"""Regression checks for the approved Home and monitoring page layout."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APPROVED_PAGES = (ROOT / "src" / "ui" / "approved_pages.py").read_text(
    encoding="utf-8"
)
MONITORING_HOME_CSS = (
    ROOT / "src" / "assets" / "css" / "monitoring_home_alignment.css"
).read_text(encoding="utf-8")


class ApprovedPageVisualContractTests(unittest.TestCase):
    def test_home_analysis_button_tracks_average_health_card_edge(self):
        self.assertNotIn('left:-5px!important', APPROVED_PAGES)
        self.assertIn('justify-content: flex-end !important;', MONITORING_HOME_CSS)
        self.assertIn('st-key-approved_home_new_bom"] button', MONITORING_HOME_CSS)

    def test_monitoring_kpis_override_streamlit_column_sizing(self):
        self.assertIn(
            '.st-key-approved_monitoring_kpi_grid [data-testid="stHorizontalBlock"]{display:flex!important;flex-flow:row nowrap!important;justify-content:flex-start!important;',
            APPROVED_PAGES,
        )
        self.assertIn(
            '.st-key-approved_monitoring_kpi_grid [data-testid="column"]{box-sizing:border-box!important;display:flex!important;flex:1 1 0!important;width:0!important;max-width:none!important;',
            APPROVED_PAGES,
        )
        self.assertNotIn(
            '.st-key-approved_monitoring_kpi_grid [data-testid="stHorizontalBlock"]{display:grid!',
            APPROVED_PAGES,
        )

    def test_monitoring_category_buttons_have_seven_desktop_tracks(self):
        self.assertIn(
            '.st-key-approved_monitoring_category_row [data-testid="stHorizontalBlock"]{display:grid!important;grid-template-columns:1fr 1.35fr .95fr 1.28fr .95fr .95fr 1.05fr!important;',
            APPROVED_PAGES,
        )
        self.assertIn("st.columns(\n            [0.42, 8.45, 3.1],", APPROVED_PAGES)
        self.assertIn(
            '.st-key-approved_monitoring_filters [data-testid="stHorizontalBlock"]:has(.st-key-approved_monitoring_category_row){display:grid!important;grid-template-columns:42px minmax(0,1fr)!important;',
            APPROVED_PAGES,
        )

    def test_selected_monitoring_filter_uses_mockup_pill_treatment(self):
        self.assertIn(
            'st-key-approved_monitoring_filter_selected_',
            MONITORING_HOME_CSS,
        )
        monitoring_renderer = APPROVED_PAGES.split("def render_monitoring(", 1)[1]
        self.assertIn('selected_key = "selected_" if selected == category else ""', monitoring_renderer)
        self.assertIn('type="secondary"', monitoring_renderer)
        self.assertNotIn('type="primary" if selected == category', monitoring_renderer)

    def test_monitoring_uses_wide_canvas_and_card_shell(self):
        self.assertIn(
            '[data-testid="stMainBlockContainer"]:has(.st-key-approved_page_canvas_wide_render_monitoring)',
            MONITORING_HOME_CSS,
        )
        self.assertIn('max-width: 1760px !important;', MONITORING_HOME_CSS)
        self.assertIn('.st-key-approved_monitoring_alert_card {', MONITORING_HOME_CSS)


    def test_monitoring_period_has_no_overlapping_date_caption(self):
        monitoring_renderer = APPROVED_PAGES.split("def render_monitoring(", 1)[1]
        self.assertNotIn("cv-ap-monitoring-period-range", monitoring_renderer)
        self.assertNotIn("_alert_date_range_label", APPROVED_PAGES)

    def test_monitoring_filters_and_actions_match_mockup(self):
        self.assertIn(
            '.st-key-approved_monitoring_category_row [class*="st-key-approved_monitoring_filter_"] .stButton > button',
            MONITORING_HOME_CSS,
        )
        self.assertIn("border-radius: 999px !important;", MONITORING_HOME_CSS)
        self.assertIn(
            '[class*="st-key-approved_alert_action_"] .stButton > button',
            MONITORING_HOME_CSS,
        )
        self.assertIn("border: 1px solid #70a4ff !important;", MONITORING_HOME_CSS)

    def test_monitoring_alert_rows_use_matching_bounded_grid(self):
        self.assertIn(
            '[class*="st-key-approved_monitoring_alert_row_"] [data-testid="stHorizontalBlock"]',
            MONITORING_HOME_CSS,
        )
        self.assertIn(
            'grid-template-columns: .8fr 1.3fr 1.9fr 1.2fr 1.2fr .28fr !important;',
            MONITORING_HOME_CSS,
        )

if __name__ == "__main__":
    unittest.main()
