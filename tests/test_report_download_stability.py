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
        self.assertEqual(report_source.count('on_click="ignore"'), 8)

    def test_report_download_controls_remain_download_buttons(self) -> None:
        source = RUNTIME_PATH.read_text(encoding="utf-8")
        start = source.index("# ---------- Reports ----------")
        report_source = source[start:]
        for label in (
            "AI Executive Brief · PDF",
            "Executive Summary · PDF",
            "Executive Data · CSV",
            "Risk Review · CSV",
            "Lifecycle Review · CSV",
            "Alternatives Review · CSV",
            "AI Procurement Brief · PDF",
            "Sourcing Review · CSV",
        ):
            position = report_source.index(f'"{label}"')
            window = report_source[max(0, position - 120): position + 320]
            self.assertIn("st.download_button(", window)


if __name__ == "__main__":
    unittest.main()
