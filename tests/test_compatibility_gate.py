import unittest

from src.compatibility_gate import (
    CRITICAL_FIRMWARE_WARNING,
    CRITICAL_PHYSICAL_WARNING,
    assess_part_compatibility,
    comparison_row_part_values,
    package_document_conflicts,
)


class CompatibilityGateTests(unittest.TestCase):
    def test_manufacturer_package_alias_with_same_family_and_pins_is_reviewed_not_false_blocked(self):
        self.assertFalse(
            package_document_conflicts(
                '8-PowerSOIC (0.154", 3.90mm Width)',
                "8-Pin HSOIC With Thermal Pad (Top View)",
            )
        )

    def test_manufacturer_package_family_or_explicit_dimension_mismatch_blocks(self):
        self.assertTrue(package_document_conflicts("SOIC-8", "TSSOP-8"))
        self.assertTrue(
            package_document_conflicts(
                '8-PowerSOIC (3.90mm Width)',
                "8-Pin HSOIC, body width 4.9 mm",
            )
        )

    def test_mc68hc11_vs_w77ic32a25pl_is_blocked_as_physical_and_isa_mismatch(self):
        original = {
            "manufacturer_part_number": "MC68HC11E1CFNE2",
            "package": "52-LCC (J-Lead)",
            "pin_count": 52,
            "architecture": "HC11 (Motorola core)",
        }
        candidate = {
            "manufacturer_part_number": "W77IC32A25PL",
            "package": "44-LCC (J-Lead)",
            "pin_count": 44,
            "architecture": "8051 Turbo-51 core",
        }

        result = assess_part_compatibility(original, candidate)

        self.assertTrue(result["package_mismatch"])
        self.assertTrue(result["pin_count_mismatch"])
        self.assertTrue(result["architecture_mismatch"])
        self.assertTrue(result["blocked_from_drop_in_approval"])
        self.assertEqual(result["drop_in_status"], "Not a drop-in replacement")
        self.assertEqual(
            result["critical_warnings"],
            [CRITICAL_PHYSICAL_WARNING, CRITICAL_FIRMWARE_WARNING],
        )

    def test_pin_count_is_extracted_from_lcc_package_when_separate_field_is_missing(self):
        result = assess_part_compatibility(
            {"package": "52-LCC (J-Lead)", "architecture": "HC11"},
            {"package": "44-LCC (J-Lead)", "architecture": "8051"},
        )

        self.assertEqual(result["source_pin_count"], 52)
        self.assertEqual(result["candidate_pin_count"], 44)
        self.assertTrue(result["pin_count_mismatch"])

    def test_processor_mismatch_is_not_downgraded_to_supplier_category_review(self):
        result = assess_part_compatibility(
            {
                "manufacturer_part_number": "MC68HC11E1CFNE2",
                "description": "8-bit microcontroller",
                "package": "52-LCC (J-Lead)",
                "pin_count": 52,
            },
            {
                "manufacturer_part_number": "W77IC32A25PL",
                "description": "Turbo-51 microcontroller",
                "package": "52-LCC (J-Lead)",
                "pin_count": 52,
                "architecture": "8051",
            },
        )

        self.assertTrue(result["architecture_mismatch"])
        self.assertIn(CRITICAL_FIRMWARE_WARNING, result["critical_warnings"])

    def test_avr_to_arm_is_critical_but_arm_core_revision_alone_is_not_an_isa_change(self):
        avr_to_arm = assess_part_compatibility(
            {"description": "AVR microcontroller", "architecture": "AVR"},
            {"description": "ARM microcontroller", "architecture": "ARM Cortex-M4"},
        )
        m3_to_m4 = assess_part_compatibility(
            {"description": "ARM Cortex-M3 microcontroller", "architecture": "ARM Cortex-M3"},
            {"description": "ARM Cortex-M4 microcontroller", "architecture": "ARM Cortex-M4"},
        )

        self.assertTrue(avr_to_arm["architecture_mismatch"])
        self.assertIn(CRITICAL_FIRMWARE_WARNING, avr_to_arm["critical_warnings"])
        self.assertFalse(m3_to_m4["architecture_mismatch"])

    def test_missing_package_or_pin_evidence_requires_review_instead_of_approval(self):
        result = assess_part_compatibility(
            {"manufacturer_part_number": "MC68HC11E1CFNE2"},
            {"manufacturer_part_number": "W77IC32A25PL"},
        )

        self.assertTrue(result["requires_acknowledgement"])
        self.assertFalse(result["blocked_from_drop_in_approval"])
        self.assertEqual(
            result["drop_in_status"],
            "Not verified — engineering review required",
        )

    def test_non_processor_function_labels_do_not_trigger_an_isa_mismatch(self):
        result = assess_part_compatibility(
            {
                "manufacturer_part_number": "LM358DGKRG4",
                "description": "Dual operational amplifier",
                "package": "8-TSSOP",
                "pin_count": 8,
                "architecture": "Operational Amplifier",
            },
            {
                "manufacturer_part_number": "LM358DR2G",
                "description": "Dual operational amplifier",
                "package": "8-SOIC",
                "pin_count": 8,
                "architecture": "Standard (General Purpose)",
            },
        )

        self.assertFalse(result["architecture_mismatch"])
        self.assertNotIn(CRITICAL_FIRMWARE_WARNING, result["critical_warnings"])
        self.assertTrue(result["package_mismatch"])

    def test_ambiguous_passive_size_codes_are_not_assumed_to_match(self):
        result = assess_part_compatibility(
            {"package": "0402", "pin_count": 2},
            {"package": "1005", "pin_count": 2},
        )

        self.assertTrue(result["package_mismatch"])

    def test_compare_matrix_package_pin_count_and_architecture_fields_are_read(self):
        rows = [
            {"Attribute": "Package", "Part A": "52-LCC", "Part B": "44-LCC"},
            {"Attribute": "Pin count", "Part A": "52", "Part B": "44"},
            {
                "Attribute": "Device family / architecture",
                "Part A": "HC11",
                "Part B": "8051",
            },
        ]

        source = {
            "manufacturer_part_number": "MC68HC11E1CFNE2",
            **comparison_row_part_values(rows, "Part A"),
        }
        candidate = {
            "manufacturer_part_number": "W77IC32A25PL",
            **comparison_row_part_values(rows, "Part B"),
        }
        assessment = assess_part_compatibility(source, candidate)

        self.assertEqual(source["pin_count"], "52")
        self.assertEqual(candidate["pin_count"], "44")
        self.assertTrue(assessment["physical_mismatch"])
        self.assertTrue(assessment["architecture_mismatch"])
        self.assertIn(CRITICAL_PHYSICAL_WARNING, assessment["critical_warnings"])
        self.assertIn(CRITICAL_FIRMWARE_WARNING, assessment["critical_warnings"])


if __name__ == "__main__":
    unittest.main()
