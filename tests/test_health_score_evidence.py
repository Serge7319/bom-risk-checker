from __future__ import annotations

import unittest

import pandas as pd

from src.health_score import (
    calculate_bom_health_score,
    generate_executive_summary,
    normalize_saved_health_score,
)
from src.engineering_overview import build_engineering_overview


class HealthScoreEvidenceTests(unittest.TestCase):
    def test_saved_score_parser_preserves_zero_and_missing_as_distinct(self):
        self.assertEqual(normalize_saved_health_score(0), 0)
        self.assertEqual(normalize_saved_health_score("82"), 82)
        self.assertIsNone(normalize_saved_health_score(None))
        self.assertIsNone(normalize_saved_health_score(""))
        self.assertIsNone(normalize_saved_health_score("NaN"))

    def test_saved_project_with_missing_health_is_not_shown_as_zero(self):
        overview = build_engineering_overview(
            analyses=[{"id": "a1", "health_score": None}],
            parts=[],
            alerts=[],
            decisions=[],
            procurement={},
        )
        self.assertIsNone(overview["projects"][0]["health"])
        self.assertEqual(overview["projects"][0]["status"], "Needs verification")

    def test_overall_health_is_withheld_when_any_component_needs_verification(self):
        result = calculate_bom_health_score(pd.DataFrame([
            {"Risk Score": 10, "Risk Level": "Low", "Supplier Data Verified": True},
            {"Risk Score": None, "Risk Level": "Needs verification", "Supplier Data Verified": False},
        ]))
        self.assertIsNone(result["health_score"])
        self.assertEqual(result["health_status"], "Needs verification")
        self.assertEqual(result["needs_verification_count"], 1)
        self.assertEqual(result["assessment_coverage"], 0.5)

    def test_complete_evidence_gets_a_health_score(self):
        result = calculate_bom_health_score(pd.DataFrame([
            {"Risk Score": 10, "Risk Level": "Low", "Supplier Data Verified": True},
            {"Risk Score": 30, "Risk Level": "Medium", "Supplier Data Verified": True},
        ]))
        self.assertEqual(result["health_score"], 80)
        self.assertEqual(result["assessment_coverage"], 1.0)

    def test_overall_health_is_withheld_when_supplier_stock_coverage_is_partial(self):
        result = calculate_bom_health_score(pd.DataFrame([
            {
                "Risk Score": 0,
                "Risk Level": "Low",
                "Supplier Data Verified": True,
                "Stock Data Complete": False,
            },
        ]))
        self.assertIsNone(result["health_score"])
        self.assertEqual(result["health_status"], "Needs verification")
        self.assertEqual(result["needs_verification_count"], 1)

    def test_executive_summary_does_not_count_unknown_stock_as_stockout(self):
        rows = pd.DataFrame([
            {"Risk Level": "Needs verification", "Lifecycle Status": "Unknown", "Stock Available": None, "Supplier Data Verified": False},
            {"Risk Level": "High", "Lifecycle Status": "Active", "Stock Available": 0, "Supplier Data Verified": True},
        ])
        summary = generate_executive_summary(rows)
        self.assertIn("1 components have a confirmed zero on-hand stock report.", summary)
        self.assertIn("1 components need supplier evidence verification.", summary)


if __name__ == "__main__":
    unittest.main()
