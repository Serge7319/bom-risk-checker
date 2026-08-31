import sys
import types
import unittest


sys.modules.setdefault("requests", types.SimpleNamespace())

from src.datasheet_comparison import (
    build_recommendation_score_breakdown,
    build_datasheet_comparison,
    build_pdf_field_evidence,
    infer_component_family,
)
from src.plans import get_plan


class DatasheetComparisonTests(unittest.TestCase):
    def test_capacitor_comparison_is_family_aware_and_marks_differences(self):
        original = {
            "description": "0.1 uF 50V X7R Ceramic Capacitor",
            "package": "0603",
            "capacitance": "0.1 uF",
            "rated_voltage": "50V",
            "dielectric": "X7R",
        }
        candidate = {
            "package": "0603",
            "capacitance": "0.1 uF",
            "rated_voltage": "25V",
            "dielectric": "X7R",
        }
        result = build_datasheet_comparison(original, candidate)
        statuses = {row["Attribute"]: row["Status"] for row in result["rows"]}
        self.assertEqual(result["family"], "Capacitor")
        self.assertEqual(statuses["Capacitance"], "Match")
        self.assertEqual(statuses["Rated voltage"], "Different")

    def test_transistor_and_inductor_get_different_engineering_checks(self):
        transistor = infer_component_family({"description": "N-Channel MOSFET 60V"})
        inductor = infer_component_family({"description": "Power Inductor 10 uH"})
        self.assertEqual(transistor, "Transistor / MOSFET")
        self.assertEqual(inductor, "Inductor")

    def test_missing_data_is_never_reported_as_a_match(self):
        result = build_datasheet_comparison(
            {"description": "Resistor", "package": "0603"},
            {"package": "0603"},
        )
        self.assertGreater(result["counts"]["Needs data"], 0)
        self.assertEqual(result["counts"]["Different"], 0)

    def test_pdf_evidence_includes_page_citations(self):
        original_pdf = {"pages": [{"page": 2, "text": "Capacitance: 0.1 uF\nRated Voltage: 50V"}]}
        candidate_pdf = {"pages": [{"page": 4, "text": "Capacitance: 0.1 uF\nRated Voltage: 25V"}]}
        rows = build_pdf_field_evidence(original_pdf, candidate_pdf, "Capacitor")
        values = {row["Attribute"]: row for row in rows}
        self.assertEqual(values["Capacitance"]["Status"], "Match")
        self.assertEqual(values["Rated voltage"]["Status"], "Different")
        self.assertEqual(values["Rated voltage"]["Source pages"], "p. 2 / p. 4")

    def test_pdf_evidence_is_a_professional_entitlement(self):
        self.assertFalse(get_plan("Starter")["datasheet_comparison"])
        self.assertTrue(get_plan("Professional")["datasheet_comparison"])
        self.assertTrue(get_plan("Business")["datasheet_comparison"])

    def test_close_match_scores_above_candidate_with_documented_differences(self):
        close = build_recommendation_score_breakdown(
            69, 95, {"Match": 8, "Different": 0, "Needs data": 1},
            is_explicit_substitute=False,
        )
        different = build_recommendation_score_breakdown(
            69, 70, {"Match": 4, "Different": 3, "Needs data": 2},
            is_explicit_substitute=False,
        )
        self.assertGreater(close["recommendation_score"], different["recommendation_score"])
        self.assertEqual(close["matches"], 8)
        self.assertEqual(different["differences"], 3)


    def test_supplier_listed_direct_substitute_is_not_penalized_for_missing_fields(self):
        score = build_recommendation_score_breakdown(
            60, 55, {"Match": 2, "Different": 0, "Needs data": 7},
            is_explicit_substitute=True,
        )
        self.assertGreaterEqual(score["recommendation_score"], 85)


if __name__ == "__main__":
    unittest.main()
