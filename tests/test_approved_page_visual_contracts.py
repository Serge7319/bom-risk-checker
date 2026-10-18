"""Regression checks for the approved Home and monitoring page layout."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APPROVED_PAGES = (ROOT / "src" / "ui" / "approved_pages.py").read_text(
    encoding="utf-8"
)


class ApprovedPageVisualContractTests(unittest.TestCase):
    def test_home_analysis_button_tracks_average_health_card_edge(self):
        self.assertIn(
            'left:-5px!important',
            APPROVED_PAGES.split("Align the Home CTA with the left edge", 1)[1].split(".cv-ap-home-kpi", 1)[0],
        )

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

    def test_monitoring_category_buttons_stay_in_one_row_at_laptop_width(self):
        responsive_rules = APPROVED_PAGES.split("@media(max-width:1200px)", 1)[1].split(
            "@media(max-width:900px)", 1
        )[0]
        self.assertIn("flex-flow:row nowrap!important", responsive_rules)
        self.assertNotIn("grid-template-columns:repeat(4", responsive_rules)


if __name__ == "__main__":
    unittest.main()
