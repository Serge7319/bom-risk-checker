"""Focused behavior tests for Design Impact review cues and portfolio disclosure."""
from __future__ import annotations

import unittest

from src.design_impact_analyzer import _design_impact_kpis, _impact_details_scroll_script
from src.portfolio_intelligence import high_risk_components_disclosure


class DesignImpactReviewBehaviorTests(unittest.TestCase):
    def test_kpis_explain_the_measure_and_link_to_evidence(self):
        metrics = _design_impact_kpis(
            {
                "project_count": 3,
                "affected_bom_count": 5,
                "impact_score": 82,
                "minimum_stock": 120,
                "minimum_sources": 3,
                "engineering_hours": 6,
                "price_currency": "USD",
            }
        )

        self.assertEqual(len(metrics), 5)
        self.assertIn("Unique saved projects", metrics[0].detail)
        self.assertEqual(metrics[0].href, "#impact-affected-projects")
        self.assertEqual(metrics[1].value, "82/100")
        self.assertIn("not a failure probability", metrics[1].detail)
        self.assertEqual(metrics[1].href, "#impact-key-factors")
        self.assertEqual(metrics[2].value, "120")
        self.assertEqual(metrics[3].value, "3")
        self.assertEqual(metrics[4].value, "6 hrs")
        self.assertTrue(all(metric.action_label for metric in metrics))

    def test_component_selection_scroll_targets_the_assessment(self):
        script = _impact_details_scroll_script()

        self.assertIn('getElementById("design-impact-review-details")', script)
        self.assertIn('scrollIntoView({ behavior: "smooth", block: "start" })', script)
        self.assertIn("[0, 100, 320, 700, 1200]", script)

    def test_at_risk_component_details_omit_the_duplicate_score(self):
        disclosure = high_risk_components_disclosure(
            1,
            [
                {
                    "Part Number": "MCP2551-I/SN",
                    "Manufacturer": "Microchip Technology",
                    "Risk Level": "High",
                    "Risk Score": 100,
                    "Quantity": 2,
                }
            ],
        )

        self.assertIn("MCP2551-I/SN", disclosure)
        self.assertIn("High", disclosure)
        self.assertIn("Qty 2", disclosure)
        self.assertNotIn("100/100", disclosure)
        self.assertNotIn("Risk Score", disclosure)


if __name__ == "__main__":
    unittest.main()
