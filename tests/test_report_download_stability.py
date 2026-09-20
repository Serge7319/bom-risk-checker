"""Regression tests for non-rerunning Reports downloads."""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "src" / "authenticated_runtime.py"


class ReportDownloadStabilityTests(unittest.TestCase):
    def test_report_downloads_do_not_rerun_before_file_delivery(self) -> None:
        source = RUNTIME_PATH.read_text(encoding="utf-8")
        start = source.index("# ---------- Reports ----------")
        report_source = source[start:]
        self.assertNotIn("on_click=_mark_first_report_complete", report_source)
        self.assertIn('"on_click": "ignore"', report_source)
        helper_start = report_source.index("def _report_download_button(")
        helper_prefix = report_source[max(0, helper_start - 80):helper_start]
        self.assertNotIn("@st.fragment", helper_prefix)

    def test_report_download_controls_remain_download_buttons(self) -> None:
        source = RUNTIME_PATH.read_text(encoding="utf-8")
        start = source.index("# ---------- Reports ----------")
        report_source = source[start:]
        for key_fragment in (
            "report_center_executive_brief_",
            "report_center_executive_summary_",
            "report_center_executive_csv_",
            "report_center_risk_pdf_",
            "report_center_risk_csv_",
            "report_center_procurement_brief_",
            "report_center_sourcing_pdf_",
            "report_center_sourcing_csv_",
            "report_center_lifecycle_pdf_",
            "report_center_lifecycle_csv_",
            "report_center_alternatives_pdf_",
            "report_center_alternatives_csv_",
        ):
            self.assertIn(key_fragment, report_source)
        self.assertEqual(report_source.count('"key": f"report_center_'), 12)
        self.assertIn("_report_download_button(**download)", report_source)


if __name__ == "__main__":
    unittest.main()
