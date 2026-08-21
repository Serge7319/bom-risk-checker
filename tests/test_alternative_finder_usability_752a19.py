"""Regression coverage for the Alternative Finder launch-usability contract."""

from pathlib import Path
import unittest


RUNTIME_SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
).read_text(encoding="utf-8")


class AlternativeFinderUsabilityTests(unittest.TestCase):
    def test_replacement_workflow_has_clear_ordered_steps(self):
        for heading in (
            "1. Search the original component",
            "2. Review the recommended replacement",
            "3. Compare the original and replacement",
            "4. Record the engineering decision",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, RUNTIME_SOURCE)

    def test_recommendation_metrics_use_readable_type(self):
        self.assertIn("font-size:11px!important;", RUNTIME_SOURCE)
        self.assertIn("font-size:16px!important;", RUNTIME_SOURCE)
        self.assertIn("font-size:13px!important;", RUNTIME_SOURCE)

    def test_result_grids_adapt_to_narrow_viewports(self):
        for breakpoint in ("1180px", "720px", "460px"):
            with self.subTest(breakpoint=breakpoint):
                self.assertIn("@media(max-width:" + breakpoint + ")", RUNTIME_SOURCE)

    def test_recommendation_explains_verification_requirements(self):
        self.assertIn("Why Cadivor recommends this part", RUNTIME_SOURCE)
        self.assertIn("before approving a replacement", RUNTIME_SOURCE)

    def test_supplier_failure_does_not_expose_exception_types(self):
        self.assertNotIn('type(lookup_error).__name__', RUNTIME_SOURCE)
        self.assertNotIn('type(search_error).__name__', RUNTIME_SOURCE)
        self.assertIn("Please try again in a moment.", RUNTIME_SOURCE)

    def test_decision_failure_does_not_expose_database_internals(self):
        self.assertNotIn("Apply the included ", RUNTIME_SOURCE)
        self.assertNotIn("Database message: {db_error}", RUNTIME_SOURCE)
        self.assertNotIn("Could not archive the decision: {archive_error}", RUNTIME_SOURCE)


if __name__ == "__main__":
    unittest.main()
