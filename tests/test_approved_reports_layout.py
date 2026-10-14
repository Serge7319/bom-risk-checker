"""Visual structure contracts for the approved Engineering Reports page."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APPROVED = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
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

    def test_recent_sources_have_a_shared_table_frame_and_mockup_columns(self) -> None:
        self.assertIn('key="approved_report_table"', REPORTS)
        self.assertIn('key="approved_report_head"', REPORTS)
        for label in ("Name", "Source", "Last updated", "Health score", "High-risk parts", "Action"):
            self.assertIn(label, REPORTS)
        self.assertIn("st-key-approved_report_table{", REPORTS)
        self.assertIn(".cv-ap-report-dot.good", REPORTS)
        self.assertIn('internal_nav_button(', REPORTS)
        self.assertIn('"Analysis Details"', REPORTS)

    def test_missing_report_values_are_not_rendered_as_zero(self) -> None:
        self.assertIn('health_text = str(score) if score is not None else "—"', REPORTS)
        self.assertIn('if high_risk_raw is not None else "—"', REPORTS)

    def test_report_open_action_matches_the_mockup_link(self) -> None:
        self.assertIn('[class*="st-key-approved_report_open_"] button{', REPORTS)
        self.assertIn('type="secondary"', REPORTS)
        self.assertIn('content:"›"', REPORTS)


if __name__ == "__main__":
    unittest.main()
