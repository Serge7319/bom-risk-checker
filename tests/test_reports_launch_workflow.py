"""Focused launch-readiness contracts for the customer Reports workflow."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "authenticated_runtime.py").read_text()
TREE = ast.parse(SOURCE)


class ReportsLaunchWorkflowTests(unittest.TestCase):
    def test_report_library_only_advertises_available_export_formats(self):
        start = SOURCE.index("first_template_data = [")
        end = SOURCE.index("second_template_cards = []", start)
        self.assertNotIn('"Excel"', SOURCE[start:end])
        self.assertIn('["PDF", "CSV"]', SOURCE[start:end])

    def test_report_library_explains_the_saved_bom_download_workflow(self):
        self.assertIn("Choose a saved BOM below, preview its evidence", SOURCE)

    def test_engineering_packages_offer_all_promised_pdf_downloads(self):
        for label in ("Risk Review · PDF", "Lifecycle Review · PDF", "Alternatives Review · PDF"):
            self.assertIn(f'"{label}"', SOURCE)

    def test_procurement_package_offers_sourcing_pdf_and_csv(self):
        self.assertIn('"Sourcing Review · PDF"', SOURCE)
        self.assertIn('"Sourcing Review · CSV"', SOURCE)

    def test_shared_report_downloads_record_history_before_rerender(self):
        shared_calls = []
        for node in ast.walk(TREE):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "download_button":
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            key = keywords.get("key")
            if not isinstance(key, ast.JoinedStr):
                continue
            if not any(isinstance(value, ast.Constant) and str(value.value).startswith("shared_") for value in key.values):
                continue
            shared_calls.append(keywords)
            self.assertIsInstance(keywords.get("on_click"), ast.Name)
            self.assertEqual(keywords["on_click"].id, "_record_session_report")
            self.assertIn("args", keywords)
        self.assertEqual(len(shared_calls), 12)

    def test_recording_a_download_preserves_onboarding_completion(self):
        start = SOURCE.index("def _record_session_report(")
        end = SOURCE.index('with st.expander("Executive reports"', start)
        self.assertIn("_mark_first_report_complete()", SOURCE[start:end])

    def test_pdf_downloads_use_existing_watermarked_report_bytes(self):
        for value in ("risk_report_pdf", "lifecycle_report_pdf", "alternatives_report_pdf", "sourcing_report_pdf"):
            self.assertIn(f"data={value}", SOURCE)


if __name__ == "__main__":
    unittest.main()
