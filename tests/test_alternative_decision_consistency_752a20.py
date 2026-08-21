"""Regression coverage for consistent replacement evidence and approval decisions."""

import unittest

from src.alternative_reasoning import (
    _normalize_package,
    build_alternative_reasoning,
)


class AlternativeDecisionConsistencyTests(unittest.TestCase):
    def _reason(self, original_package, candidate_package, **overrides):
        candidate = {
            "Alternative Part": "LM358P",
            "Package": candidate_package,
            "Pin Count": 8,
            "Architecture": "Operational Amplifier",
            "Voltage Range": "3-32V",
            "Lifecycle": "Active",
            "Estimated Risk": "Low",
            "Stock": 51366,
            "Unit Price": 0.33,
        }
        candidate.update(overrides.pop("candidate", {}))
        kwargs = {
            "original_part": "LM358N",
            "original_data": {
                "package": original_package,
                "pin_count": 8,
                "architecture": "Operational Amplifier",
                "voltage_range": "3-32V",
            },
            "candidate": candidate,
            "recommendation_score": 87,
            "compatibility_confidence": 100,
            "engineering_matches": ["✓ Same package (DIP-8)"],
            "warnings": [],
            "stock_delta": "2× more stock",
            "price_delta": "72.0% lower cost",
        }
        kwargs.update(overrides)
        return build_alternative_reasoning(**kwargs)

    def test_supplier_aliases_share_the_same_normalized_package(self):
        self.assertEqual(_normalize_package('8-DIP (0.300", 7.62mm)'), "DIP-8")
        self.assertEqual(_normalize_package("PDIP-8"), "DIP-8")

    def test_equivalent_dip_aliases_do_not_create_a_false_blocker(self):
        result = self._reason('8-DIP (0.300", 7.62mm)', "PDIP-8")
        self.assertEqual(result["hard_blocker_count"], 0)
        self.assertFalse(result["blockers"])
        self.assertTrue(any("Package matches" in item for item in result["confirmed_matches"]))

    def test_equivalent_package_is_recommended_for_qualification(self):
        result = self._reason('8-DIP (0.300", 7.62mm)', "PDIP-8")
        self.assertEqual(result["disposition"], "Recommended for engineering qualification")
        self.assertEqual(result["disposition_tone"], "good")
        self.assertEqual(result["verification_count"], 0)

    def test_genuine_package_mismatch_remains_an_approval_blocker(self):
        result = self._reason("PDIP-8", "SOIC-8")
        self.assertEqual(result["hard_blocker_count"], 1)
        self.assertIn("Package differs", result["blockers"][0])
        self.assertEqual(result["disposition"], "Not recommended as a drop-in replacement")

    def test_missing_package_requires_verification_not_a_blocker(self):
        result = self._reason("", "PDIP-8")
        self.assertEqual(result["hard_blocker_count"], 0)
        self.assertTrue(any("package" in item.lower() for item in result["verification_required"]))

    def test_different_pin_count_still_blocks_approval(self):
        result = self._reason("DIP-8", "PDIP-8", candidate={"Pin Count": 14})
        self.assertTrue(any("Pin count differs" in item for item in result["blockers"]))

    def test_unavailable_stock_still_blocks_approval(self):
        result = self._reason("DIP-8", "PDIP-8", candidate={"Stock": 0})
        self.assertTrue(any("No confirmed stock" in item for item in result["blockers"]))

    def test_normalizer_preserves_distinct_package_families(self):
        self.assertEqual(_normalize_package("SOIC-8"), "SOIC-8")
        self.assertEqual(_normalize_package("SOT-223"), "SOT-223")
        self.assertNotEqual(_normalize_package("DIP-8"), _normalize_package("SOIC-8"))


if __name__ == "__main__":
    unittest.main()
