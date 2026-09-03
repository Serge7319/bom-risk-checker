"""Regression coverage for consistent replacement evidence and approval decisions."""

import unittest

from src.alternative_classification import CLASS_VERIFIED_DIRECT
from src.alternative_reasoning import (
    VERIFIED_DIRECT_DISPOSITION,
    _normalize_package,
    build_alternative_reasoning,
)
from src.datasheet_comparison import build_datasheet_comparison


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


def _c0603_capacitor_comparison_rows():
    original = {
        "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
        "package": "0603",
        "mounting_style": "Surface Mount, MLCC",
        "capacitance": "0.1 µF",
        "tolerance": "±10%",
        "rated_voltage": "50V",
        "dielectric": "X7R",
        "temperature_coefficient": "X7R",
        "esr": "",
    }
    candidate = dict(original)
    comparison = build_datasheet_comparison(original, candidate)
    return comparison["rows"], comparison["counts"], original


class PassiveAlternativeDecisionTests(unittest.TestCase):
    def _capacitor_reason(self, **overrides):
        rows, counts, original = _c0603_capacitor_comparison_rows()
        candidate = {
            "Alternative Part": "C0603C104K5RAC3121",
            "Classification": CLASS_VERIFIED_DIRECT,
            "Comparison Family": "Capacitor",
            "Comparison Rows": rows,
            "Comparison Counts": counts,
            "Lifecycle": "Active",
            "Estimated Risk": "Low",
            "Stock": 50000,
            "Unit Price": 0.05,
        }
        candidate.update(overrides.pop("candidate", {}))
        kwargs = {
            "original_part": "C0603C104K5RACTU",
            "original_data": original,
            "candidate": candidate,
            "recommendation_score": 90,
            "compatibility_confidence": 94,
            "engineering_matches": [],
            "warnings": [],
            "stock_delta": "2× more stock",
            "price_delta": "10.0% lower cost",
            "comparison_family": "Capacitor",
            "classification": CLASS_VERIFIED_DIRECT,
            "comparison_rows": rows,
            "comparison_counts": counts,
        }
        kwargs.update(overrides)
        return build_alternative_reasoning(**kwargs)

    def test_c0603_verified_direct_shows_positive_disposition(self):
        result = self._capacitor_reason()
        self.assertEqual(result["disposition"], VERIFIED_DIRECT_DISPOSITION)
        self.assertEqual(result["disposition_tone"], "good")
        self.assertNotEqual(result["disposition"], "Not recommended as a drop-in replacement")

    def test_c0603_verified_direct_has_strong_confidence(self):
        result = self._capacitor_reason()
        self.assertGreaterEqual(result["decision_confidence"], 82)
        self.assertGreaterEqual(result["engineering_comparison_confidence"], 82)

    def test_sparse_capacitor_evidence_limits_engineering_confidence(self):
        rows, counts, original = _c0603_capacitor_comparison_rows()
        sparse_counts = {"Match": 1, "Different": 0, "Needs data": 7}
        sparse_rows = []
        for row in rows:
            updated = dict(row)
            if row["Attribute"] == "Package":
                updated["Status"] = "Match"
            else:
                updated["Status"] = "Needs data"
                updated["Candidate"] = "Not available"
            sparse_rows.append(updated)
        result = build_alternative_reasoning(
            original_part="C0603C104K5RACTU",
            original_data=original,
            candidate={
                "Alternative Part": "C0603C104K5RAC3121",
                "Classification": CLASS_VERIFIED_DIRECT,
                "Substitute Type": "Direct",
                "Stock": 50000,
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Unit Price": 0.05,
                "Engineering Evidence Summary": (
                    "Engineering evidence: incomplete — 1 confirmed match, "
                    "7 fields need verification"
                ),
                "Engineering Comparison Confidence": 42,
                "Supplier Relationship Confidence": 95,
                "Supplier Relationship Summary": (
                    "DigiKey substitute type: Direct"
                ),
            },
            recommendation_score=85,
            compatibility_confidence=42,
            engineering_matches=[],
            warnings=[],
            stock_delta="N/A",
            price_delta="N/A",
            comparison_family="Capacitor",
            classification=CLASS_VERIFIED_DIRECT,
            comparison_rows=sparse_rows,
            comparison_counts=sparse_counts,
        )
        self.assertEqual(result["disposition"], VERIFIED_DIRECT_DISPOSITION)
        self.assertLess(result["engineering_comparison_confidence"], 55)
        self.assertGreaterEqual(result["supplier_relationship_confidence"], 90)
        self.assertIn("incomplete", result["engineering_evidence_summary"].casefold())
        self.assertIn(
            "digikey substitute type: direct",
            str(result.get("supplier_relationship_summary") or "").casefold(),
        )
        combined = " ".join(
            result["confirmed_matches"] + result["verification_required"] + result["blockers"]
        ).casefold()
        self.assertNotIn("pin count", combined)

    def test_c0603_does_not_surface_ic_review_items(self):
        result = self._capacitor_reason()
        combined = " ".join(
            result["confirmed_matches"]
            + result["verification_required"]
            + result["blockers"]
            + result["expected_work"]
        ).casefold()
        for forbidden in (
            "pin count",
            "pin assignment",
            "architecture",
            "pinout",
            "supply voltage",
            "channel count",
        ):
            self.assertNotIn(forbidden, combined, msg=f"Unexpected IC term: {forbidden}")

    def test_c0603_esr_is_verification_not_blocker(self):
        result = self._capacitor_reason()
        self.assertEqual(result["hard_blocker_count"], 0)
        self.assertFalse(result["blockers"])
        esr_items = [
            item for item in result["verification_required"]
            if "esr" in item.casefold()
        ]
        self.assertEqual(len(esr_items), 1)
        self.assertIn("ESR was not available from the retrieved evidence", esr_items[0])
        self.assertIn("DC-bias", esr_items[0])

    def test_c0603_lists_matching_capacitor_fields(self):
        result = self._capacitor_reason()
        confirmed = " ".join(result["confirmed_matches"]).casefold()
        for field in (
            "package",
            "mounting",
            "capacitance",
            "tolerance",
            "rated voltage",
            "dielectric",
            "temperature characteristic",
        ):
            self.assertIn(field, confirmed, msg=f"Missing confirmed field: {field}")

    def test_capacitor_rated_voltage_difference_downgrades(self):
        rows, counts, original = _c0603_capacitor_comparison_rows()
        for row in rows:
            if row["Attribute"] == "Rated voltage":
                row["Status"] = "Different"
                row["Original"] = "50V"
                row["Candidate"] = "25V"
        counts = {"Match": 6, "Different": 1, "Needs data": 1}
        result = build_alternative_reasoning(
            original_part="C0603C104K5RACTU",
            original_data=original,
            candidate={
                "Alternative Part": "C0603C104K5RAC3121",
                "Classification": CLASS_VERIFIED_DIRECT,
                "Stock": 50000,
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Unit Price": 0.05,
            },
            recommendation_score=70,
            compatibility_confidence=55,
            engineering_matches=[],
            warnings=[],
            stock_delta="N/A",
            price_delta="N/A",
            comparison_family="Capacitor",
            classification=CLASS_VERIFIED_DIRECT,
            comparison_rows=rows,
            comparison_counts=counts,
        )
        self.assertEqual(result["hard_blocker_count"], 1)
        self.assertTrue(any("Rated voltage differs" in item for item in result["blockers"]))
        self.assertEqual(result["disposition"], "Not recommended as a drop-in replacement")

    def test_resistor_missing_dcr_is_verification_not_ic_checks(self):
        original = {
            "description": "Resistor 10k 0603",
            "package": "0603",
            "mounting_style": "Surface Mount",
            "resistance": "10 kOhms",
            "tolerance": "±1%",
            "power_rating": "0.1W",
            "temperature_coefficient": "100 ppm/°C",
            "rated_voltage": "50V",
        }
        candidate = dict(original)
        comparison = build_datasheet_comparison(original, candidate)
        result = build_alternative_reasoning(
            original_part="RC0603FR-0710KL",
            original_data=original,
            candidate={
                "Alternative Part": "RC0603FR-0710KL-B",
                "Classification": CLASS_VERIFIED_DIRECT,
                "Stock": 10000,
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Unit Price": 0.01,
            },
            recommendation_score=88,
            compatibility_confidence=90,
            engineering_matches=[],
            warnings=[],
            stock_delta="N/A",
            price_delta="N/A",
            comparison_family="Resistor",
            classification=CLASS_VERIFIED_DIRECT,
            comparison_rows=comparison["rows"],
            comparison_counts=comparison["counts"],
        )
        combined = " ".join(
            result["confirmed_matches"] + result["verification_required"] + result["blockers"]
        ).casefold()
        self.assertNotIn("pin count", combined)
        self.assertNotIn("architecture", combined)

    def test_inductor_missing_saturation_current_is_verification(self):
        original = {
            "description": "Inductor 4.7uH 0603",
            "package": "0603",
            "mounting_style": "Surface Mount",
            "inductance": "4.7 µH",
            "tolerance": "±20%",
            "dcr": "0.2 Ohms",
            "rated_current": "500 mA",
            "saturation_current": "",
        }
        candidate = dict(original)
        comparison = build_datasheet_comparison(original, candidate)
        result = build_alternative_reasoning(
            original_part="LQH32CN4R7M03L",
            original_data=original,
            candidate={
                "Alternative Part": "LQH32CN4R7M03L-B",
                "Classification": CLASS_VERIFIED_DIRECT,
                "Stock": 8000,
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Unit Price": 0.12,
            },
            recommendation_score=86,
            compatibility_confidence=88,
            engineering_matches=[],
            warnings=[],
            stock_delta="N/A",
            price_delta="N/A",
            comparison_family="Inductor",
            classification=CLASS_VERIFIED_DIRECT,
            comparison_rows=comparison["rows"],
            comparison_counts=comparison["counts"],
        )
        combined = " ".join(result["verification_required"]).casefold()
        self.assertNotIn("pin count", combined)
        sat_items = [
            item for item in result["verification_required"] if "saturation" in item.casefold()
        ]
        self.assertTrue(sat_items)


if __name__ == "__main__":
    unittest.main()
