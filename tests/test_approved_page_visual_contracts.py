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
            'section[data-testid="stMain"] .st-key-approved_monitoring_filters .stButton:not(.st-key-cv_foundation_navigation .stButton):not(.st-key-cv_analysis_section_nav .stButton):not(.st-key-cv_analysis_section_nav *):not([class*="st-key-cadivor_bom_tab_"]):not(.st-key-cv_saved_bom_nav_more .stButton)>button[data-testid="stBaseButton-primary"]:not(:disabled){border:1px solid #6ea2ff!important;border-radius:999px!important;background:#edf5ff!important;color:#2563eb!important;',
            APPROVED_PAGES,
        )
        self.assertIn(
            'section[data-testid="stMain"] .st-key-approved_monitoring_filters .stButton:not(.st-key-cv_foundation_navigation .stButton):not(.st-key-cv_analysis_section_nav .stButton):not(.st-key-cv_analysis_section_nav *):not([class*="st-key-cadivor_bom_tab_"]):not(.st-key-cv_saved_bom_nav_more .stButton)>button[data-testid="stBaseButton-secondary"]:not(:disabled){border:1px solid #dce4ef!important;border-radius:999px!important;background:#fff!important;color:#52647b!important;',
            APPROVED_PAGES,
        )


if __name__ == "__main__":
    unittest.main()
