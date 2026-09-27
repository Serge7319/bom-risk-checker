from __future__ import annotations

import unittest

from src.alternative_candidate_intelligence import build_alternative_candidate_insight


class AlternativeCandidateIntelligenceTests(unittest.TestCase):
    def test_names_mismatches_and_missing_evidence(self):
        insight = build_alternative_candidate_insight({
            "Recommendation Score": 81,
            "Engineering Comparison Confidence": 68,
            "Supplier Relationship Confidence": 94,
            "Lifecycle": "Active",
            "Stock": 1250,
            "Engineering Evidence Summary": "Five fields agree; two need review.",
            "Comparison Rows": [
                {"Attribute": "Package", "Status": "Different", "Original": "DIP-8", "Candidate": "SOIC-8"},
                {"Attribute": "Supply voltage", "Status": "Needs data"},
                {"Attribute": "Channel count", "Status": "Match"},
            ],
        })
        self.assertEqual(insight["score"], 81)
        self.assertEqual(insight["stock_label"], "1,250")
        self.assertIn("Package differs", insight["verification_gaps"][0])
        self.assertTrue(any("supply voltage" in item for item in insight["verification_gaps"]))
        self.assertNotIn("Channel count", " ".join(insight["verification_gaps"]))

    def test_unknown_lifecycle_and_stock_become_actions(self):
        insight = build_alternative_candidate_insight({
            "Recommendation Score": 60, "Lifecycle": "Unknown", "Stock": 0,
        })
        self.assertIn("Confirm the manufacturer lifecycle status.", insight["verification_gaps"])
        self.assertIn("Confirm procurable stock before qualification.", insight["verification_gaps"])
        self.assertEqual(insight["stock_label"], "No confirmed stock")


if __name__ == "__main__":
    unittest.main()
