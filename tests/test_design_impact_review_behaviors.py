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
                "total_quantity": 14,
            }
        )

        self.assertEqual(len(metrics), 4)
        self.assertIn("Unique saved project names", metrics[0].detail)
        self.assertEqual(metrics[0].href, "#impact-affected-projects")
        self.assertEqual(metrics[1].value, "5")
        self.assertIn("Distinct saved analyses", metrics[1].detail)
        self.assertEqual(metrics[2].value, "82/100")
        self.assertIn("not a failure probability", metrics[2].detail)
        self.assertEqual(metrics[2].href, "#impact-score-drivers")
        self.assertIn("Sum of this part's quantities", metrics[3].detail)
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
