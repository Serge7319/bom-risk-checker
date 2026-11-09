"""Regression: compare provenance, value classes, and assessment honesty."""
from __future__ import annotations

import unittest

from src.component_family_profiles import get_family_profile
from src.datasheet_comparison import build_datasheet_comparison, user_facing_comparison_rows
from src.parametric_compare import (
    classify_value_condition,
    compare_field_values,
    extract_test_condition,
)
from src.parts_compare import (
    FINDING_COMPATIBLE,
    FINDING_CONFLICTING,
    FINDING_MATERIAL,
    FINDING_NEEDS_VERIFICATION,
    map_status_to_assessment,
    user_facing_compare_rows,
)


class ValueConditionClassificationTests(unittest.TestCase):
    def test_classifies_typical_min_max_and_guaranteed(self):
        self.assertEqual(classify_value_condition("20 nA (typ)"), "typical")
        self.assertEqual(classify_value_condition("45 nA max"), "maximum")
        self.assertEqual(classify_value_condition("3 mV Min"), "minimum")
        self.assertEqual(classify_value_condition("Guaranteed 1.0 MHz"), "guaranteed")
        self.assertEqual(classify_value_condition("1.0 MHz"), "unknown")

    def test_incomparable_classes_need_verification(self):
        from src.component_family_profiles import FieldSpec, COMPARE_LIMIT_LE

        spec = FieldSpec(
            key="input_bias_na",
            label="Input bias",
            compare=COMPARE_LIMIT_LE,
            unit="A",
            value_role="max",
        )
        status, note = compare_field_values("20 nA (typ)", "45 nA max", spec)
        self.assertEqual(status, "Needs data")
        self.assertIn("typical", note)
        self.assertIn("maximum", note)
        self.assertEqual(map_status_to_assessment(status), FINDING_NEEDS_VERIFICATION)

    def test_extract_test_condition(self):
        self.assertIn("25", extract_test_condition("20 nA @ 25°C"))
        self.assertEqual(extract_test_condition(""), "Not stated")


class OpAmpAndFamilyProvenanceTests(unittest.TestCase):
    def test_general_family_display_is_short(self):
        self.assertEqual(get_family_profile("General electronic component").display_name, "General")

    def test_input_offset_unit_is_not_volts(self):
        profile = get_family_profile("Operational amplifier")
        offset = next(spec for spec in profile.fields if spec.key == "input_offset_mv")
        self.assertNotEqual(offset.unit, "V")
        self.assertEqual(offset.unit, "mV")

    def test_amplifier_type_is_separate_from_architecture(self):
        profile = get_family_profile("Operational amplifier")
        keys = {spec.key for spec in profile.fields}
        self.assertIn("amplifier_type", keys)
        architecture = next(spec for spec in profile.fields if spec.key == "architecture")
        self.assertNotIn("Amplifier Type", architecture.digikey_params)

    def test_lm358_suffix_variants_keep_exact_mpns_and_sources(self):
        original = {
            "manufacturer_part_number": "LM358N",
            "manufacturer": "Texas Instruments",
            "description": "Dual operational amplifier",
            "architecture": "Operational amplifier",
            "channel_count": 2,
            "voltage_range": "3 V ~ 32 V",
            "bandwidth_mhz": "1.1 MHz (typ)",
            "input_bias_na": "20 nA (typ)",
            "source": "DigiKey",
            "field_sources": {
                "architecture": "DigiKey",
                "channel_count": "DigiKey",
                "voltage_range": "DigiKey",
                "bandwidth_mhz": "DigiKey",
                "input_bias_na": "DigiKey",
            },
            "supplier_data_verified": True,
        }
        candidate = {
            "manufacturer_part_number": "LM358P",
            "manufacturer": "Texas Instruments",
            "description": "Dual operational amplifier",
            "architecture": "Operational amplifier",
            "channel_count": 2,
            "voltage_range": "3 V ~ 32 V",
            "bandwidth_mhz": "1.1 MHz max",
            "input_bias_na": "45 nA max",
            "source": "Mouser",
            "field_sources": {
                "architecture": "Mouser",
                "channel_count": "Mouser",
                "voltage_range": "Mouser",
                "bandwidth_mhz": "Mouser",
                "input_bias_na": "Mouser",
            },
            "supplier_data_verified": True,
        }
        comparison = build_datasheet_comparison(original, candidate)
        rows = {row["Attribute"]: row for row in comparison["rows"]}
        bias = rows["Input bias"]
        self.assertEqual(bias["Part A MPN"], "LM358N")
        self.assertEqual(bias["Part B MPN"], "LM358P")
        self.assertEqual(bias["Part A source"], "DigiKey")
        self.assertEqual(bias["Part B source"], "Mouser")
        self.assertEqual(bias["Part A value class"], "typical")
        self.assertEqual(bias["Part B value class"], "maximum")
        self.assertEqual(bias["Status"], "Needs data")

        projected = user_facing_compare_rows(comparison["rows"])
        bias_proj = next(row for row in projected if row["Attribute"] == "Input bias")
        self.assertEqual(bias_proj["Assessment"], FINDING_NEEDS_VERIFICATION)
        self.assertEqual(bias_proj["Part A MPN"], "LM358N")
        self.assertEqual(bias_proj["Part B MPN"], "LM358P")

    def test_missing_evidence_is_never_compatible(self):
        original = {
            "manufacturer_part_number": "NE555P",
            "manufacturer": "Texas Instruments",
            "description": "Precision timer IC",
            "architecture": "555 timer",
            "source": "DigiKey",
            "field_sources": {"architecture": "DigiKey"},
        }
        candidate = {
            "manufacturer_part_number": "LM555CN/NOPB",
            "manufacturer": "Texas Instruments",
            "description": "Precision timer IC",
            "architecture": "555 timer",
            "source": "Mouser",
            "field_sources": {"architecture": "Mouser"},
        }
        comparison = build_datasheet_comparison(original, candidate)
        for row in user_facing_compare_rows(comparison["rows"]):
            if str(row["Part A"]).startswith("Not stated") or str(row["Part B"]).startswith("Not stated"):
                self.assertEqual(row["Assessment"], FINDING_NEEDS_VERIFICATION)
                self.assertNotEqual(row["Assessment"], FINDING_COMPATIBLE)

    def test_conflicting_lifecycle_records_surface_as_conflicting_evidence(self):
        original = {
            "manufacturer_part_number": "CRCW060310K0FKEA",
            "manufacturer": "Vishay",
            "description": "10k resistor",
            "resistance": "10 kOhm",
            "lifecycle_status": "Active",
            "lifecycle_conflict": True,
            "lifecycle_evidence": [
                {"source": "DigiKey", "status": "Active"},
                {"source": "Mouser", "status": "NRND"},
            ],
            "source": "DigiKey",
            "field_sources": {"resistance": "DigiKey", "lifecycle_status": "DigiKey"},
        }
        candidate = {
            "manufacturer_part_number": "RC0603FR-0710KL",
            "manufacturer": "Yageo",
            "description": "10k resistor",
            "resistance": "10 kOhm",
            "lifecycle_status": "Active",
            "source": "Mouser",
            "field_sources": {"resistance": "Mouser", "lifecycle_status": "Mouser"},
        }
        comparison = build_datasheet_comparison(original, candidate)
        lifecycle = next(
            row for row in comparison["rows"] if row["Attribute"] == "Lifecycle"
        )
        self.assertEqual(lifecycle["Status"], "Conflicting")
        projected = user_facing_comparison_rows([lifecycle])[0]
        self.assertEqual(projected["Assessment"], FINDING_CONFLICTING)

    def test_different_manufacturers_do_not_borrow_values(self):
        original = {
            "manufacturer_part_number": "ABC-1",
            "manufacturer": "Acme",
            "description": "10k resistor",
            "resistance": "10 kOhm",
            "source": "DigiKey",
            "field_sources": {"resistance": "DigiKey"},
        }
        candidate = {
            "manufacturer_part_number": "XYZ-1",
            "manufacturer": "OtherCo",
            "description": "10k resistor",
            # Intentionally empty — must stay Needs verification, not filled from Acme.
            "resistance": "",
            "source": "Mouser",
            "field_sources": {},
        }
        comparison = build_datasheet_comparison(original, candidate)
        resistance = next(
            row for row in user_facing_compare_rows(comparison["rows"])
            if row["Attribute"] == "Resistance"
        )
        self.assertEqual(resistance["Assessment"], FINDING_NEEDS_VERIFICATION)
        self.assertNotEqual(resistance["Part A"], resistance["Part B"])

    def test_assessment_mapping_covers_conflicting_and_material(self):
        self.assertEqual(map_status_to_assessment("Match"), FINDING_COMPATIBLE)
        self.assertEqual(map_status_to_assessment("Different"), FINDING_MATERIAL)
        self.assertEqual(map_status_to_assessment("Conflicting"), FINDING_CONFLICTING)
        self.assertEqual(map_status_to_assessment("Needs data"), FINDING_NEEDS_VERIFICATION)


class DigiKeyOverwriteGuardTests(unittest.TestCase):
    def test_parametric_skip_keys_protect_architecture_and_bandwidth(self):
        import inspect
        from integrations import digikey_client

        source = inspect.getsource(digikey_client)
        self.assertIn('"architecture"', source)
        self.assertIn('"bandwidth_mhz"', source)
        self.assertIn("amplifier_type", source)


if __name__ == "__main__":
    unittest.main()
