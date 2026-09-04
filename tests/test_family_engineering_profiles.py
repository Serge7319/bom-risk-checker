"""Cross-family engineering comparison foundation regressions."""
from __future__ import annotations

import unittest

from src.alternative_engine import (
    apply_supplier_enrichment_to_candidate,
    calculate_drop_in_confidence,
)
from src.alternative_reasoning import build_alternative_reasoning
from src.component_family_profiles import (
    FAMILY_PROFILES,
    digikey_parametric_map,
    get_family_profile,
    infer_family_id,
)
from src.datasheet_comparison import (
    build_datasheet_comparison,
    build_engineering_evidence_assessment,
    build_recommendation_score_breakdown,
    infer_component_family,
)
from src.parametric_compare import compare_field_values, parse_numeric_with_unit
from src.component_family_profiles import FieldSpec, COMPARE_LIMIT_GE, COMPARE_NOMINAL


class FamilyProfileRegistryTests(unittest.TestCase):
    REQUIRED_FAMILIES = {
        "Capacitor", "Resistor", "Inductor", "Diode / protection",
        "Bipolar transistor", "MOSFET", "Regulator", "Operational amplifier",
        "Logic / interface IC", "MCU / processor", "FPGA / CPLD",
        "Connector / electromechanical", "Relay", "Switch",
        "Oscillator / crystal", "Sensor", "Transformer",
    }

    def test_all_required_families_registered(self):
        for family in self.REQUIRED_FAMILIES:
            self.assertIn(family, FAMILY_PROFILES)
            profile = FAMILY_PROFILES[family]
            self.assertTrue(profile.fields or family == "General electronic component")

    def test_inference_covers_representative_parts(self):
        cases = {
            "Capacitor": {"description": "Ceramic capacitor 0.1uF"},
            "Resistor": {"description": "Thick film resistor 10k"},
            "Inductor": {"description": "Power inductor 10uH"},
            "Diode / protection": {"description": "Schottky diode 40V"},
            "Bipolar transistor": {"description": "NPN transistor MMBT3904LT1G"},
            "MOSFET": {"description": "N-Channel MOSFET 60V"},
            "Regulator": {"description": "LDO voltage regulator 3.3V"},
            "Operational amplifier": {"description": "Operational amplifier rail-to-rail"},
            "MCU / processor": {"description": "ARM Cortex-M microcontroller"},
            "FPGA / CPLD": {"description": "Artix-7 FPGA"},
            "Connector / electromechanical": {"description": "Board-to-board connector header"},
        }
        for family, part in cases.items():
            self.assertEqual(infer_family_id(part), family)
            self.assertEqual(infer_component_family(part), family)

    def test_digikey_map_includes_bjt_and_mosfet_keys(self):
        mapping = digikey_parametric_map()
        self.assertIn("collector_emitter_voltage", mapping)
        self.assertIn("dc_current_gain", mapping)
        self.assertIn("rds_on", mapping)
        self.assertIn("drain_source_voltage", mapping)
        self.assertIn("logic_resources", mapping)


class ParametricCompareTests(unittest.TestCase):
    def test_unit_normalization_and_limit_direction(self):
        self.assertAlmostEqual(parse_numeric_with_unit("0.1uF", preferred_unit="F")[0], 1e-7)
        self.assertAlmostEqual(parse_numeric_with_unit("100nF", preferred_unit="F")[0], 1e-7)
        ge = FieldSpec("rated_voltage", "Rated voltage", compare=COMPARE_LIMIT_GE, unit="V")
        self.assertEqual(compare_field_values("50V", "100V", ge)[0], "Match")
        self.assertEqual(compare_field_values("50V", "25V", ge)[0], "Different")
        nom = FieldSpec("capacitance", "Capacitance", compare=COMPARE_NOMINAL, unit="F")
        self.assertEqual(compare_field_values("0.1 uF", "100nF", nom)[0], "Match")

    def test_missing_data_never_matches(self):
        ge = FieldSpec("vceo", "VCEO", compare=COMPARE_LIMIT_GE, unit="V", required=True)
        self.assertEqual(compare_field_values("40V", "", ge)[0], "Needs data")
        self.assertEqual(compare_field_values("", "40V", ge)[0], "Needs data")


class FamilyMatrixTests(unittest.TestCase):
    def _attrs(self, result):
        return {row["Attribute"] for row in result["rows"]}

    def test_capacitor_matrix_no_pin_or_architecture(self):
        result = build_datasheet_comparison(
            {"description": "Ceramic capacitor", "package": "0603", "capacitance": "0.1uF", "rated_voltage": "50V"},
            {"description": "Ceramic capacitor", "package": "0603", "capacitance": "0.1uF", "rated_voltage": "50V"},
        )
        attrs = self._attrs(result)
        self.assertEqual(result["family"], "Capacitor")
        self.assertIn("Capacitance", attrs)
        self.assertNotIn("Pin count", attrs)
        self.assertNotIn("Architecture", attrs)

    def test_resistor_and_inductor_matrices(self):
        resistor = build_datasheet_comparison(
            {"description": "Resistor", "resistance": "10k", "power_rating": "0.1W"},
            {"description": "Resistor", "resistance": "10k", "power_rating": "0.125W"},
        )
        self.assertEqual(resistor["family"], "Resistor")
        statuses = {r["Attribute"]: r["Status"] for r in resistor["rows"]}
        self.assertEqual(statuses["Power rating"], "Match")
        inductor = build_datasheet_comparison(
            {"description": "Inductor", "inductance": "10uH", "saturation_current": "1A"},
            {"description": "Inductor", "inductance": "10uH", "saturation_current": "0.5A"},
        )
        self.assertEqual(inductor["family"], "Inductor")
        statuses = {r["Attribute"]: r["Status"] for r in inductor["rows"]}
        self.assertEqual(statuses["Saturation current"], "Different")

    def test_diode_matrix(self):
        result = build_datasheet_comparison(
            {"description": "Schottky diode", "reverse_voltage": "40V", "forward_current": "1A", "device_type": "Schottky"},
            {"description": "Schottky diode", "reverse_voltage": "60V", "forward_current": "1A", "device_type": "Schottky"},
        )
        self.assertEqual(result["family"], "Diode / protection")
        statuses = {r["Attribute"]: r["Status"] for r in result["rows"]}
        self.assertEqual(statuses["Reverse voltage"], "Match")

    def test_bjt_matrix_includes_electricals_not_architecture(self):
        original = {
            "description": "NPN transistor MMBT3904LT1G",
            "package": "TO-236-3, SC-59, SOT-23-3",
            "pin_count": 3,
            "mounting_style": "Surface Mount",
            "device_type": "NPN",
            "collector_emitter_voltage": "40V",
            "collector_current": "200mA",
            "dc_current_gain": "100 @ 10mA, 1V",
            "power_dissipation": "300mW",
            "transition_frequency": "300MHz",
            "vce_saturation": "300mV",
            "temperature_range": "-55°C ~ 150°C",
        }
        candidate = dict(original)
        candidate["description"] = "NPN transistor MMBT3904-7-F"
        result = build_datasheet_comparison(original, candidate)
        self.assertEqual(result["family"], "Bipolar transistor")
        attrs = self._attrs(result)
        self.assertIn("VCEO", attrs)
        self.assertIn("IC max", attrs)
        self.assertIn("hFE", attrs)
        self.assertIn("Power dissipation", attrs)
        self.assertIn("Transition frequency", attrs)
        self.assertIn("VCE(sat)", attrs)
        self.assertIn("Pinout / footprint", attrs)
        self.assertNotIn("Architecture", attrs)
        statuses = {r["Attribute"]: r["Status"] for r in result["rows"]}
        self.assertEqual(statuses["VCEO"], "Match")
        self.assertEqual(statuses["Pinout / footprint"], "Needs data")

    def test_mmbt3904_direct_plus_package_pins_not_high_engineering_score(self):
        original = {
            "description": "NPN transistor MMBT3904LT1G",
            "manufacturer_part_number": "MMBT3904LT1G",
            "package": "SOT-23-3",
            "pin_count": 3,
            "mounting_style": "SMD",
        }
        candidate = {
            "description": "NPN transistor MMBT3904-7-F",
            "manufacturer_part_number": "MMBT3904-7-F",
            "package": "SOT-23-3",
            "pin_count": 3,
            "mounting_style": "SMD",
            "Classification": "Verified direct substitute",
            "Substitute Type": "Direct",
        }
        comparison = build_datasheet_comparison(original, candidate)
        assessment = build_engineering_evidence_assessment(
            comparison["counts"],
            classification="Verified direct substitute",
            substitute_type="Direct",
            comparison_rows=comparison["rows"],
            family=comparison["family"],
            supplier_relationship_evidence=[{
                "supplier": "DigiKey",
                "substitute_type": "Direct",
                "summary": "DigiKey relationship: Direct.",
                "original_mpn": "MMBT3904LT1G",
                "candidate_mpn": "MMBT3904-7-F",
            }],
        )
        self.assertEqual(assessment["supplier_relationship_confidence"], 95)
        self.assertLess(assessment["engineering_comparison_confidence"], 55)
        self.assertIn("incomplete", assessment["engineering_evidence_summary"])
        score = build_recommendation_score_breakdown(
            70,
            assessment["engineering_comparison_confidence"],
            comparison["counts"],
            is_explicit_substitute=True,
        )
        # Direct must not floor recommendation when electrical evidence is sparse.
        self.assertLess(score["recommendation_score"], 85)
        enriched = apply_supplier_enrichment_to_candidate(
            original_data=original,
            candidate={
                **candidate,
                "Alternative Part": "MMBT3904-7-F",
                "Recommendation Score": 70,
                "Classification": "Verified direct substitute",
                "Substitute Type": "Direct",
                "Supplier Relationship Evidence": [{
                    "supplier": "DigiKey",
                    "substitute_type": "Direct",
                    "summary": "DigiKey relationship: Direct.",
                    "original_mpn": "MMBT3904LT1G",
                    "candidate_mpn": "MMBT3904-7-F",
                }],
            },
            candidate_supplier_data=candidate,
            canonical_part_number="MMBT3904LT1G",
        )
        self.assertLess(int(enriched["Drop-In Confidence"]), 55)
        self.assertLess(int(enriched["Engineering Comparison Confidence"]), 55)
        reasoning = build_alternative_reasoning(
            original_part="MMBT3904LT1G",
            original_data=original,
            candidate=enriched,
            recommendation_score=int(enriched["Recommendation Score"]),
            compatibility_confidence=int(enriched["Drop-In Confidence"]),
            engineering_matches=[],
            warnings=[],
            stock_delta="0",
            price_delta="0",
            comparison_family=enriched.get("Comparison Family"),
            classification=enriched.get("Classification"),
            comparison_rows=enriched.get("Comparison Rows"),
            comparison_counts=enriched.get("Comparison Counts"),
        )
        joined = " ".join(reasoning.get("verification_required", []) + reasoning.get("blockers", []))
        self.assertTrue(
            any(token in joined for token in ("VCEO", "IC max", "hFE", "Power dissipation", "Pinout")),
            joined,
        )
        self.assertNotIn("architecture", joined.casefold())

    def test_mosfet_matrix(self):
        result = build_datasheet_comparison(
            {
                "description": "N-Channel MOSFET",
                "device_type": "N-Channel",
                "drain_source_voltage": "60V",
                "continuous_drain_current": "5A",
                "rds_on": "50mOhm",
            },
            {
                "description": "N-Channel MOSFET",
                "device_type": "N-Channel",
                "drain_source_voltage": "60V",
                "continuous_drain_current": "5A",
                "rds_on": "40mOhm",
            },
        )
        self.assertEqual(result["family"], "MOSFET")
        statuses = {r["Attribute"]: r["Status"] for r in result["rows"]}
        self.assertEqual(statuses["RDS(on)"], "Match")
        self.assertIn("VDS", self._attrs(result))

    def test_regulator_analog_mcu_fpga_connector(self):
        regulator = build_datasheet_comparison(
            {"description": "LDO regulator", "output_voltage": "3.3V", "rated_current": "500mA", "architecture": "LDO"},
            {"description": "LDO regulator", "output_voltage": "3.3V", "rated_current": "1A", "architecture": "LDO"},
        )
        self.assertEqual(regulator["family"], "Regulator")
        analog = build_datasheet_comparison(
            {"description": "Operational amplifier", "channel_count": 2, "voltage_range": "2.7V to 5.5V"},
            {"description": "Operational amplifier", "channel_count": 2, "voltage_range": "2.7V to 5.5V"},
        )
        self.assertEqual(analog["family"], "Operational amplifier")
        mcu = build_datasheet_comparison(
            {"description": "ARM Cortex-M microcontroller", "architecture": "Cortex-M4", "frequency_mhz": 80},
            {"description": "ARM Cortex-M microcontroller", "architecture": "Cortex-M4", "frequency_mhz": 80},
        )
        self.assertEqual(mcu["family"], "MCU / processor")
        self.assertIn("Pinout / configuration compatibility", self._attrs(mcu))
        fpga = build_datasheet_comparison(
            {"description": "Artix-7 FPGA", "architecture": "Artix-7", "logic_resources": "33280", "io_count": "250"},
            {"description": "Artix-7 FPGA", "architecture": "Artix-7", "logic_resources": "33280", "io_count": "250"},
        )
        self.assertEqual(fpga["family"], "FPGA / CPLD")
        self.assertIn("Logic resources", self._attrs(fpga))
        connector = build_datasheet_comparison(
            {"description": "Board connector header", "positions": "10", "pitch": "2.54mm", "mating_style": "Header"},
            {"description": "Board connector header", "positions": "10", "pitch": "2.54mm", "mating_style": "Header"},
        )
        self.assertEqual(connector["family"], "Connector / electromechanical")
        self.assertNotIn("Pin count", self._attrs(connector))


if __name__ == "__main__":
    unittest.main()
