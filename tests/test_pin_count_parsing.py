"""Regression coverage for conservative pin/lead/ball-count parsing."""
from __future__ import annotations

import unittest

from integrations.digikey_client import extract_pin_count as digikey_extract_pin_count
from integrations.digikey_client import normalize_digikey_product
from integrations.mouser_client import extract_pin_count as mouser_extract_pin_count
from integrations.mouser_client import normalize_mouser_part
from integrations.pin_count import (
    effective_pin_count,
    parse_pin_count_from_text,
    resolve_pin_count,
    sanitize_stored_pin_count,
)
from src.alternative_engine import calculate_drop_in_confidence
from src.datasheet_comparison import build_datasheet_comparison


class PinCountParsingTests(unittest.TestCase):
    def test_mmbt3904_package_string_never_yields_236(self):
        package = "TO-236-3, SC-59, SOT-23-3"
        self.assertEqual(parse_pin_count_from_text(package), 3)
        self.assertNotEqual(parse_pin_count_from_text(package), 236)
        self.assertEqual(
            resolve_pin_count(package_text=package),
            3,
        )

    def test_outline_only_codes_are_not_pin_counts(self):
        self.assertEqual(parse_pin_count_from_text("TO-236"), 0)
        self.assertEqual(parse_pin_count_from_text("SC-59"), 0)
        self.assertEqual(parse_pin_count_from_text("SOT-23"), 0)
        self.assertNotIn(parse_pin_count_from_text("TO-236"), {236, 59})
        self.assertNotIn(parse_pin_count_from_text("SC-59"), {236, 59})

    def test_unambiguous_package_suffixes(self):
        self.assertEqual(parse_pin_count_from_text("SOT-23-3"), 3)
        self.assertEqual(parse_pin_count_from_text("SOT-23-5"), 5)
        self.assertEqual(parse_pin_count_from_text("SOIC-8"), 8)
        self.assertEqual(parse_pin_count_from_text("QFN-32"), 32)
        self.assertEqual(parse_pin_count_from_text("LQFP-64"), 64)

    def test_passive_packages_never_become_pin_counts(self):
        self.assertEqual(parse_pin_count_from_text("0603"), 0)
        self.assertEqual(parse_pin_count_from_text("0402"), 0)
        self.assertEqual(parse_pin_count_from_text("0805"), 0)
        self.assertEqual(parse_pin_count_from_text("1608 Metric"), 0)
        self.assertEqual(parse_pin_count_from_text("1608"), 0)

    def test_explicit_supplier_field_preferred_over_package(self):
        self.assertEqual(
            resolve_pin_count(
                explicit_count_text="256",
                package_text="FBGA",
            ),
            256,
        )
        self.assertEqual(
            resolve_pin_count(
                explicit_count_text="3 Pins",
                package_text="TO-236",
            ),
            3,
        )

    def test_fpga_bga_without_count_needs_data(self):
        self.assertEqual(parse_pin_count_from_text("FBGA"), 0)
        self.assertEqual(parse_pin_count_from_text("BGA"), 0)
        self.assertEqual(parse_pin_count_from_text("FBGA-484"), 484)

    def test_bare_integer_only_when_allowed(self):
        self.assertEqual(parse_pin_count_from_text("32", allow_bare_integer=True), 32)
        self.assertEqual(parse_pin_count_from_text("32", allow_bare_integer=False), 0)
        self.assertEqual(parse_pin_count_from_text("236", allow_bare_integer=False), 0)

    def test_sanitize_rejects_stale_outline_counts(self):
        self.assertEqual(
            sanitize_stored_pin_count(236, package_text="TO-236-3, SC-59, SOT-23-3"),
            3,
        )
        self.assertEqual(
            sanitize_stored_pin_count(236, package_text="TO-236"),
            0,
        )
        self.assertEqual(
            sanitize_stored_pin_count(59, package_text="SC-59"),
            0,
        )
        self.assertEqual(
            sanitize_stored_pin_count(603, package_text="0603"),
            0,
        )

    def test_digikey_normalize_uses_conservative_package_fallback(self):
        product = {
            "Manufacturer": {"Name": "onsemi"},
            "ManufacturerPartNumber": "MMBT3904LT1G",
            "QuantityAvailable": 1000,
            "Parameters": [
                {
                    "ParameterText": "Package / Case",
                    "ValueText": "TO-236-3, SC-59, SOT-23-3",
                },
                {
                    "ParameterText": "Supplier Device Package",
                    "ValueText": "SOT-23-3",
                },
            ],
            "Description": {"ProductDescription": "Transistor BJT NPN 40V"},
        }
        result = normalize_digikey_product(product)
        self.assertEqual(result["pin_count"], 3)
        self.assertNotEqual(result["pin_count"], 236)

    def test_digikey_explicit_number_of_pins_wins(self):
        product = {
            "Manufacturer": {"Name": "Xilinx"},
            "ManufacturerPartNumber": "XC7A35T-1CPG236C",
            "QuantityAvailable": 50,
            "Parameters": [
                {"ParameterText": "Number of Pins", "ValueText": "238"},
                {"ParameterText": "Package / Case", "ValueText": "FBGA"},
            ],
            "Description": {"ProductDescription": "FPGA Artix-7"},
        }
        result = normalize_digikey_product(product)
        self.assertEqual(result["pin_count"], 238)

    def test_mouser_does_not_treat_package_attribute_as_raw_digits(self):
        part = {
            "Manufacturer": "Diodes Incorporated",
            "ManufacturerPartNumber": "MMBT3904-7-F",
            "Availability": "1000 In Stock",
            "ProductAttributes": [
                {"AttributeName": "Package / Case", "AttributeValue": "TO-236-3, SC-59, SOT-23-3"},
                {"AttributeName": "Package", "AttributeValue": "SOT-23-3"},
            ],
            "Description": "Transistor BJT NPN",
        }
        result = normalize_mouser_part(part)
        self.assertEqual(result["pin_count"], 3)
        self.assertNotEqual(result["pin_count"], 236)

    def test_client_extract_helpers_reject_passives_and_outlines(self):
        self.assertEqual(digikey_extract_pin_count("0603"), 0)
        self.assertEqual(mouser_extract_pin_count("0603"), 0)
        self.assertEqual(digikey_extract_pin_count("TO-236"), 0)
        self.assertEqual(mouser_extract_pin_count("TO-236"), 0)
        self.assertEqual(digikey_extract_pin_count("8"), 8)
        self.assertEqual(mouser_extract_pin_count("8"), 8)

    def test_bogus_236_cannot_create_comparison_match(self):
        original = {
            "description": "NPN transistor MMBT3904LT1G",
            "package": "TO-236-3, SC-59, SOT-23-3",
            "pin_count": 236,
            "mounting_style": "Surface Mount",
        }
        candidate = {
            "description": "NPN transistor MMBT3904-7-F",
            "package": "TO-236-3, SC-59, SOT-23-3",
            "pin_count": 236,
            "mounting_style": "Surface Mount",
        }
        comparison = build_datasheet_comparison(original, candidate)
        pin_row = next(row for row in comparison["rows"] if row["Attribute"] == "Pin count")
        self.assertEqual(pin_row["Original"], "3")
        self.assertEqual(pin_row["Candidate"], "3")
        self.assertEqual(pin_row["Status"], "Match")

        ambiguous = {
            "description": "NPN transistor",
            "package": "TO-236",
            "pin_count": 236,
            "mounting_style": "Surface Mount",
        }
        needs_data = build_datasheet_comparison(ambiguous, ambiguous)
        pin_row = next(row for row in needs_data["rows"] if row["Attribute"] == "Pin count")
        self.assertEqual(pin_row["Status"], "Needs data")
        self.assertNotIn("236", pin_row["Original"])
        self.assertNotIn("236", pin_row["Candidate"])

    def test_bogus_236_does_not_award_compatibility_score(self):
        original = {
            "Architecture": "BJT",
            "Package": "TO-236",
            "Pin Count": 236,
            "pin_count": 236,
            "package": "TO-236",
        }
        candidate = {
            "Architecture": "BJT",
            "Package": "TO-236",
            "Pin Count": 236,
            "pin_count": 236,
            "package": "TO-236",
        }
        score_with_bogus = calculate_drop_in_confidence(original, candidate)
        original_ok = dict(original)
        original_ok["Pin Count"] = 0
        original_ok["pin_count"] = 0
        candidate_ok = dict(candidate)
        candidate_ok["Pin Count"] = 0
        candidate_ok["pin_count"] = 0
        score_without = calculate_drop_in_confidence(original_ok, candidate_ok)
        self.assertEqual(score_with_bogus, score_without)
        # Matching bogus 236 must not beat a true 3-pin match by inventing pins.
        true_match = calculate_drop_in_confidence(
            {
                "Architecture": "BJT",
                "Package": "SOT-23-3",
                "Pin Count": 3,
                "pin_count": 3,
                "package": "SOT-23-3",
            },
            {
                "Architecture": "BJT",
                "Package": "SOT-23-3",
                "Pin Count": 3,
                "pin_count": 3,
                "package": "SOT-23-3",
            },
        )
        self.assertGreater(true_match, score_with_bogus)

    def test_microcontroller_qfn_and_passive_isolation(self):
        mcu = {
            "description": "ARM Cortex-M microcontroller",
            "package": "QFN-32",
            "pin_count": 0,
        }
        self.assertEqual(effective_pin_count(mcu), 32)
        passive = {
            "description": "Ceramic capacitor 0.1uF",
            "package": "0603",
            "pin_count": 603,
        }
        self.assertEqual(effective_pin_count(passive), 0)
        comparison = build_datasheet_comparison(passive, passive)
        attributes = {row["Attribute"] for row in comparison["rows"]}
        self.assertNotIn("Pin count", attributes)


if __name__ == "__main__":
    unittest.main()
