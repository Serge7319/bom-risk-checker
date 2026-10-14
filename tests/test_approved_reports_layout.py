"""Visual structure contracts for the approved Engineering Reports page."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APPROVED = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
CORE_UI = (ROOT / "src" / "ui" / "core_premium_ui.py").read_text(encoding="utf-8")
REPORTS = APPROVED[
    APPROVED.index("def render_reports_list("):
    APPROVED.index("\n\ndef render_simple_workspace(", APPROVED.index("def render_reports_list("))
]


class ApprovedReportsLayoutTests(unittest.TestCase):
    def test_report_templates_follow_the_mockup_cards(self) -> None:
        for label in (
            "Executive BOM Report",
            "Engineering Risk Review",
            "Sourcing Summary",
            "cv-ap-report-template-icon",
            "cv-ap-report-template-footer",
            "DOCX",
            "XLSX",
            "PPTX",
        ):
            self.assertIn(label, REPORTS)
        self.assertIn('lucide(icon_name, 26)', REPORTS)
        self.assertIn('"<section class=\'cv-ap-report-cards\'>" + "".join(cards)', REPORTS)
        self.assertNotIn("{''.join(cards)}", REPORTS)

    def test_recent_sources_have_a_shared_table_frame_and_mockup_columns(self) -> None:
        self.assertIn('key="approved_report_table"', REPORTS)
        for label in ("Name", "Source", "Last updated", "Health score", "High-risk parts", "Action"):
            self.assertIn(label, REPORTS)
        self.assertIn("st-key-approved_report_table{", REPORTS)
        self.assertIn("cv-ap-report-table-head", REPORTS)
        self.assertIn("grid-template-columns:2.05fr 1.1fr 1.1fr 1.15fr 1.1fr .65fr", REPORTS)
        self.assertIn(".cv-ap-report-dot.good", REPORTS)
        self.assertIn('internal_nav_button(', REPORTS)
        self.assertIn('"Analysis Details"', REPORTS)

    def test_missing_report_values_are_not_rendered_as_zero(self) -> None:
        self.assertIn('health_text = str(score) if score is not None else "—"', REPORTS)
        self.assertIn('if high_risk_raw is not None else "—"', REPORTS)

    def test_report_open_action_matches_the_mockup_link(self) -> None:
        self.assertIn('"Open >"', REPORTS)
        self.assertIn('type="tertiary"', REPORTS)
        self.assertIn('key=f"approved_report_action_{index}"', REPORTS)
        self.assertIn('id="cadivor-reports-table-final"', CORE_UI)
        self.assertIn('[class*="st-key-approved_report_action_"] button {', CORE_UI)
        self.assertIn('justify-content:flex-start!important', CORE_UI)
        self.assertIn('font-weight:400!important', CORE_UI)
        self.assertIn('border:0!important;border-color:transparent!important;border-radius:0!important;background:transparent!important', CORE_UI)
        self.assertNotIn('button::after', REPORTS)

    def test_reports_page_opens_at_the_mockup_heading_and_cards(self) -> None:
        self.assertIn("st.html(", REPORTS)
        self.assertIn("unsafe_allow_javascript=True", REPORTS)
        self.assertIn("resetReportsScroll", REPORTS)
        self.assertIn("canvas.scrollIntoView({block: 'start'", REPORTS)
        self.assertIn("Engineering reports", REPORTS)
        self.assertIn("Report templates", REPORTS)
        self.assertIn("Recent report sources", REPORTS)


if __name__ == "__main__":
    unittest.main()
