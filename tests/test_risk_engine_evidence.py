from __future__ import annotations

import unittest

from src.risk_engine import calculate_risk


class RiskEngineEvidenceTests(unittest.TestCase):
    def test_missing_supplier_fields_do_not_become_low_risk_or_stockout(self):
        result = calculate_risk({
            "lifecycle_status": "Unknown",
            "stock_total": None,
            "total_market_stock": None,
            "supplier_count": None,
            "lead_time_weeks": None,
            "has_alternates": False,
        })
        self.assertIsNone(result["risk_score"])
        self.assertEqual(result["risk_level"], "Needs verification")
        self.assertEqual(result["risk_reasons"], [])

    def test_explicit_zero_inventory_is_scored_but_missing_inventory_is_not(self):
        missing = calculate_risk({"quantity": 2, "stock_total": None})
        zero = calculate_risk({
            "quantity": 2,
            "stock_total": 0,
            "supplier_count": 1,
            "provider_health": {"configured_count": 3, "failed_count": 0},
        })
        self.assertNotIn("No on-hand stock was reported across matched suppliers", missing["risk_reasons"])
        self.assertIn("No on-hand stock was reported across matched suppliers", zero["risk_reasons"])
        self.assertEqual(zero["risk_level"], "High")

    def test_partial_zero_inventory_is_not_scored_as_a_stockout(self):
        result = calculate_risk({
            "quantity": 2,
            "total_market_stock": 0,
            "stock_data_complete": False,
            "supplier_count": 2,
        })
        self.assertNotIn("No on-hand stock was reported across matched suppliers", result["risk_reasons"])
        self.assertIn("Reported inventory is partial and cannot confirm BOM coverage", result["risk_reasons"])
        self.assertEqual(result["risk_level"], "Needs verification")
        self.assertIsNone(result["risk_score"])

    def test_supplier_concentration_waits_for_sufficient_source_coverage(self):
        incomplete = calculate_risk({
            "supplier_count": 1,
            "provider_health": {"configured_count": 3, "failed_count": 1},
        })
        single_configured = calculate_risk({
            "supplier_count": 1,
            "provider_health": {"configured_count": 1, "failed_count": 0},
        })
        verified_single_source = calculate_risk({
            "supplier_count": 1,
            "provider_health": {"configured_count": 3, "failed_count": 0},
        })
        self.assertNotIn("Only one checked supplier lists this part", incomplete["risk_reasons"])
        self.assertNotIn("Only one checked supplier lists this part", single_configured["risk_reasons"])
        self.assertIn("Only one checked supplier lists this part", verified_single_source["risk_reasons"])

    def test_alternate_absence_is_not_scored_without_search_evidence(self):
        result = calculate_risk({
            "lifecycle_status": "Active",
            "stock_total": 1000,
            "supplier_count": 3,
            "has_alternates": False,
        })
        self.assertEqual(result["risk_level"], "Low")
        self.assertFalse(any("alternate" in reason.lower() for reason in result["risk_reasons"]))

    def test_lifecycle_conflict_is_flagged_without_claiming_obsolete(self):
        result = calculate_risk({
            "lifecycle_status": "Conflicting supplier data",
            "lifecycle_conflict": True,
        })
        self.assertEqual(result["risk_level"], "Medium")
        self.assertTrue(any("conflict" in reason.lower() for reason in result["risk_reasons"]))
        self.assertFalse(any("obsolete" in reason.lower() for reason in result["risk_reasons"]))

    def test_qualified_variant_note_is_visible_without_changing_the_score(self):
        note = "Evidence uses manufacturer-listed order code PCF8574P,112."
        baseline = calculate_risk({"lifecycle_status": "Active", "stock_total": 300})
        with_note = calculate_risk({
            "lifecycle_status": "Active",
            "stock_total": 300,
            "assessment_basis_note": note,
        })

        self.assertEqual(with_note["risk_score"], baseline["risk_score"])
        self.assertEqual(with_note["risk_level"], baseline["risk_level"])
        self.assertIn(note, with_note["risk_reasons"])

    def test_long_lead_time_is_not_double_counted(self):
        result = calculate_risk({"lifecycle_status": "Active", "lead_time_weeks": 20})
        self.assertEqual(result["risk_score"], 15)
        self.assertEqual(len(result["risk_reasons"]), 1)


if __name__ == "__main__":
    unittest.main()
