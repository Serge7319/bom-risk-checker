"""Presentation regressions for Direct vs engineering readiness and user columns."""

from pathlib import Path
import unittest

from src.alternative_classification import (
    SUITABILITY_PREFERRED,
    SUITABILITY_SUPPLIER_VALIDATE,
    build_supplier_relationship_evidence,
    format_engineering_compatibility_headline,
    resolve_presentation_suitability,
)
from src.component_family_profiles import FAMILY_PROFILES
from src.datasheet_comparison import (
    INTERNAL_COMPARISON_METADATA_COLUMNS,
    USER_FACING_COMPARISON_COLUMNS,
    build_datasheet_comparison,
    build_pdf_field_evidence,
    user_facing_comparison_rows,
    user_facing_pdf_evidence_rows,
)


RUNTIME_SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
).read_text(encoding="utf-8")


def _bjt_sparse_pair():
    original = {
        "description": "Transistor NPN 40V 0.2A SOT-23",
        "device_type": "NPN",
        "package": "SOT-23",
        "collector_emitter_voltage": "40V",
        "collector_current": "",
        "dc_current_gain": "",
        "power_dissipation": "",
        "transition_frequency": "",
        "vce_saturation": "",
        "collector_cutoff_current": "",
        "operating_temperature": "",
        "pin_count": "",
        "mounting_style": "Surface Mount",
        "pinout": "",
    }
    candidate = dict(original)
    candidate["collector_emitter_voltage"] = ""
    candidate["device_type"] = "NPN"
    return original, candidate


def _bjt_full_pair():
    original = {
        "description": "Transistor NPN 40V 0.2A SOT-23",
        "device_type": "NPN",
        "package": "SOT-23",
        "collector_emitter_voltage": "40V",
        "collector_current": "0.2A",
        "dc_current_gain": "100",
        "power_dissipation": "0.35W",
        "transition_frequency": "300MHz",
        "vce_saturation": "0.2V",
        "collector_cutoff_current": "50nA",
        "operating_temperature": "-55 to 150C",
        "pin_count": "3",
        "mounting_style": "Surface Mount",
        "pinout": "1=B 2=E 3=C",
    }
    return original, dict(original)


def _passive_pair():
    original = {
        "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
        "package": "0603",
        "mounting_style": "Surface Mount, MLCC",
        "capacitance": "0.1 µF",
        "tolerance": "±10%",
        "rated_voltage": "50V",
        "dielectric": "X7R",
        "temperature_coefficient": "X7R",
        "esr": "0.1 Ohm",
    }
    return original, dict(original)


def _mcu_pair():
    original = {
        "description": "MCU 8-Bit AVR ATMEGA328P",
        "architecture": "AVR",
        "package": "PDIP-28",
        "pin_count": "28",
        "voltage_range": "1.8-5.5V",
        "memory_size": "32KB Flash",
        "frequency_mhz": "20MHz",
        "io_count": "23",
        "peripherals": "UART SPI I2C",
        "pinout": "ATMEGA328P pinout",
        "mounting_style": "Through Hole",
    }
    return original, dict(original)


class AlternativeFinderPresentationTests(unittest.TestCase):
    def test_direct_relationship_label_is_exact(self):
        evidence = build_supplier_relationship_evidence(
            supplier="DigiKey",
            original_mpn="MMBT3904",
            candidate_mpn="MMBT3904-7-F",
            substitute_type="Direct",
        )
        self.assertEqual(evidence["summary"], "DigiKey relationship: Direct.")

    def test_sparse_direct_bjt_separates_relationship_and_engineering(self):
        original, candidate = _bjt_sparse_pair()
        comparison = build_datasheet_comparison(original, candidate)
        headline = format_engineering_compatibility_headline(
            engineering_status="incomplete",
            engineering_confidence=35,
            comparison_rows=comparison["rows"],
        )
        suitability = resolve_presentation_suitability(
            SUITABILITY_PREFERRED,
            engineering_status="incomplete",
            engineering_confidence=35,
            comparison_rows=comparison["rows"],
        )
        self.assertEqual(
            headline,
            "Engineering compatibility: Incomplete — validation required.",
        )
        self.assertEqual(suitability, SUITABILITY_SUPPLIER_VALIDATE)
        self.assertNotEqual(suitability, SUITABILITY_PREFERRED)
        labels = " ".join(row["Attribute"].casefold() for row in comparison["rows"])
        for field in (
            "polarity",
            "vceo",
            "ic max",
            "hfe",
            "power dissipation",
            "transition",
            "vce(sat)",
            "leakage",
            "package",
            "pin",
            "mounting",
            "pinout",
        ):
            self.assertTrue(
                any(field in row["Attribute"].casefold() for row in comparison["rows"]),
                msg=f"Missing BJT field containing {field}; have: {labels}",
            )
        self.assertTrue(
            any(row["Status"] == "Needs data" for row in comparison["rows"])
        )

    def test_fully_evidenced_bjt_can_remain_preferred(self):
        original, candidate = _bjt_full_pair()
        comparison = build_datasheet_comparison(original, candidate)
        suitability = resolve_presentation_suitability(
            SUITABILITY_PREFERRED,
            engineering_status="complete",
            engineering_confidence=90,
            comparison_rows=comparison["rows"],
        )
        self.assertEqual(suitability, SUITABILITY_PREFERRED)
        headline = format_engineering_compatibility_headline(
            engineering_status="complete",
            engineering_confidence=90,
            comparison_rows=comparison["rows"],
        )
        self.assertIn("Ready for focused validation", headline)

    def test_user_facing_tables_omit_internal_metadata(self):
        for builder in (_bjt_sparse_pair, _passive_pair, _mcu_pair):
            with self.subTest(family=builder.__name__):
                original, candidate = builder()
                comparison = build_datasheet_comparison(original, candidate)
                user_rows = user_facing_comparison_rows(comparison["rows"])
                self.assertTrue(user_rows)
                for row in user_rows:
                    self.assertEqual(
                        list(row.keys()),
                        list(USER_FACING_COMPARISON_COLUMNS),
                    )
                    for meta in INTERNAL_COMPARISON_METADATA_COLUMNS:
                        self.assertNotIn(meta, row)
                # Raw builder may still retain metadata for diagnostics.
                raw = comparison["rows"][0]
                for meta in INTERNAL_COMPARISON_METADATA_COLUMNS:
                    self.assertIn(meta, raw)

        pdf_rows = build_pdf_field_evidence(
            {"pages": [{"page": 1, "text": "Capacitance: 0.1 uF"}]},
            {"pages": [{"page": 1, "text": "Capacitance: 0.1 uF"}]},
            "Capacitor",
        )
        user_pdf = user_facing_pdf_evidence_rows(pdf_rows)
        for row in user_pdf:
            for meta in ("Key", "Required", "CompareMode", "ValueRole"):
                self.assertNotIn(meta, row)

    def test_runtime_wires_presentation_guards(self):
        self.assertIn("resolve_presentation_suitability(", RUNTIME_SOURCE)
        self.assertIn("format_engineering_compatibility_headline(", RUNTIME_SOURCE)
        self.assertIn("user_facing_comparison_rows(", RUNTIME_SOURCE)
        self.assertIn("user_facing_pdf_evidence_rows(", RUNTIME_SOURCE)
        self.assertIn("Developer comparison diagnostics", RUNTIME_SOURCE)
        self.assertIn("SUITABILITY_SUPPLIER_VALIDATE", RUNTIME_SOURCE)
        self.assertIn(
            "Engineering compatibility: Incomplete — validation required.",
            Path(__file__).resolve().parents[1]
            .joinpath("src/alternative_classification.py")
            .read_text(encoding="utf-8"),
        )

    def test_fpga_profile_fields_remain_visible_in_comparison(self):
        profile = FAMILY_PROFILES["FPGA / CPLD"]
        labels = [field.label for field in profile.fields]
        self.assertTrue(labels)
        original = {field.key: "example" for field in profile.fields}
        comparison = build_datasheet_comparison(original, dict(original))
        user_rows = user_facing_comparison_rows(comparison["rows"])
        self.assertEqual(
            [row["Attribute"] for row in user_rows],
            [row["Attribute"] for row in comparison["rows"]],
        )


class ReplacementCandidateDecisionTests(unittest.TestCase):
    def test_detail_shows_package_conflict_and_does_not_qualify_catalog_candidate(self):
        from src.ui.approved_pages import _candidate_detail_html

        original = {
            "manufacturer_part_number": "LM358DGKRG4",
            "manufacturer": "Texas Instruments",
            "description": "Operational Amplifiers - Op Amps Dual General-Purpose Op Amp",
            "package": '8-TSSOP, 8-MSOP (0.118", 3.00mm Width)',
            "pin_count": 8,
            "mounting_style": "Surface Mount",
            "voltage_range": "3 V ~ 30 V",
            "temperature_range": "0°C ~ 70°C",
            "channel_count": 2,
            "input_bias_na": "20 nA",
            "architecture": "Operational Amplifier",
            "lifecycle_status": "End of Life",
            "stock_total": 685,
            "unit_price": 0.2,
            "source": "Mouser",
            "lead_time_weeks": None,
            "product_detail_url": "https://www.mouser.com/ProductDetail/LM358DGKRG4",
            "field_sources": {
                "package": "DigiKey",
                "mounting_style": "DigiKey",
                "voltage_range": "DigiKey",
                "temperature_range": "DigiKey",
                "channel_count": "DigiKey",
                "lifecycle_status": "Mouser",
                "stock_total": "Mouser",
            },
        }
        row = {
            "Alternative Part": "LM358DR2G",
            "Manufacturer": "onsemi",
            "description": "IC OP AMP 2CH 8-SOIC",
            "architecture": "Standard (General Purpose)",
            "package": '8-SOIC (0.154", 3.90mm Width)',
            "pin_count": 8,
            "mounting_style": "Surface Mount",
            "voltage_range": "3 V ~ 32 V",
            "temperature_range": "0°C ~ 70°C",
            "channel_count": 2,
            "input_bias_na": "45 nA",
            "Lifecycle": "Active",
            "Stock": 36121,
            "unit_price": 0.25,
            "lead_time_weeks": 13,
            "Supplier": "DigiKey",
            "Classification": "Catalog candidate — insufficient evidence for compatibility",
            "Recommendation": "Catalog discovery only; insufficient evidence for compatibility.",
            "Product URL": "https://www.digikey.com/en/products/detail/onsemi/LM358DR2G/123",
            "Datasheet URL": "https://www.onsemi.com/pdf/datasheet/lm358-d.pdf",
            "field_sources": {
                "package": "DigiKey",
                "mounting_style": "DigiKey",
                "voltage_range": "DigiKey",
                "channel_count": "DigiKey",
                "lead_time_weeks": "DigiKey",
            },
        }
        html_text = _candidate_detail_html(row, original)
        self.assertIn("8-SOIC", html_text)
        self.assertIn("Surface Mount", html_text)
        self.assertIn("3 V ~ 32 V", html_text)
        self.assertIn("Known conflict", html_text)
        self.assertIn("Compatibility is not verified", html_text)
        package = html_text.split("Package", 1)[1].split("Pin count", 1)[0]
        self.assertIn("8-TSSOP", package)
        self.assertIn("Known conflict", package)
        voltage = html_text.split("Supply voltage", 1)[1].split("Bandwidth", 1)[0]
        self.assertIn("3 V ~ 30 V", voltage)
        self.assertIn("3 V ~ 32 V", voltage)
        self.assertIn("Needs review", voltage)
        self.assertIn("wider maximum", voltage)
        self.assertNotIn("Known conflict", voltage)
        bias = html_text.split("Input bias", 1)[1].split("Pinout", 1)[0]
        self.assertIn("20 nA", bias)
        self.assertIn("45 nA", bias)
        self.assertIn("Needs review", bias)
        self.assertIn("higher input bias", bias)
        self.assertIn("not a confirmed design-limit conflict", bias)
        self.assertNotIn("Known conflict", bias)
        self.assertIn("Pinout was not in either supplier record", html_text)
        self.assertNotIn("qualified", html_text.casefold())
        self.assertIn("Moderate lead time risk", html_text)
        self.assertIn("Lead time is between 8 and 16 weeks", html_text)
        self.assertIn("https://www.onsemi.com/pdf/datasheet/lm358-d.pdf", html_text)
        self.assertIn("Pinout was not in either supplier record", html_text)
        self.assertNotIn(">Not recorded<", html_text)

    def test_missing_attribute_stays_unknown_and_links_out(self):
        from src.ui.approved_pages import _candidate_detail_html

        original = {
            "manufacturer_part_number": "LM358DGKRG4",
            "description": "Operational Amplifiers - Op Amps",
            "source": "Mouser",
            "product_detail_url": "https://www.mouser.com/ProductDetail/LM358DGKRG4",
        }
        row = {
            "Alternative Part": "LM358DR2G",
            "description": "IC OP AMP 2CH 8-SOIC",
            "Classification": "Catalog candidate — insufficient evidence for compatibility",
            "Supplier": "DigiKey",
            "Product URL": "https://www.digikey.com/en/products/detail/onsemi/LM358DR2G/123",
        }
        html_text = _candidate_detail_html(row, original)
        self.assertIn("Unknown", html_text)
        self.assertIn("was not in either supplier record", html_text)
        self.assertIn("https://www.digikey.com/en/products/detail/onsemi/LM358DR2G/123", html_text)
        self.assertNotIn("qualified", html_text.casefold())


class TechnicalFindingLabelTests(unittest.TestCase):
    def test_wider_supply_range_covers_the_original_span(self):
        from src.parametric_compare import supply_range_finding

        status, note = supply_range_finding("3 V ~ 30 V", "3 V ~ 32 V")
        self.assertEqual(status, "Needs review")
        self.assertIn("covers the original range", note)
        self.assertIn("wider maximum", note)

    def test_narrower_supply_range_does_not_cover(self):
        from src.parametric_compare import supply_range_finding

        status, note = supply_range_finding("3 V ~ 32 V", "3 V ~ 30 V")
        self.assertEqual(status, "Different")
        self.assertIn("does not cover", note)

    def test_higher_bias_without_a_design_limit_stays_a_review(self):
        from src.parametric_compare import bias_condition_finding

        status, note = bias_condition_finding("20 nA", "45 nA")
        self.assertEqual(status, "Needs review")
        self.assertIn("higher input bias", note)
        self.assertIn("typical or maximum", note)
        self.assertIn("not a confirmed design-limit conflict", note)

    def test_higher_bias_over_an_explicit_design_limit_is_a_conflict(self):
        from src.parametric_compare import bias_condition_finding

        status, note = bias_condition_finding("20 nA", "45 nA", design_limit="30 nA")
        self.assertEqual(status, "Different")
        self.assertIn("explicit design limit", note)
        self.assertIn("30 nA", note)

    def test_bias_inside_an_explicit_design_limit_is_not_a_conflict(self):
        from src.parametric_compare import bias_condition_finding

        status, note = bias_condition_finding("20 nA", "45 nA", design_limit="50 nA")
        self.assertEqual(status, "Needs review")
        self.assertIn("not a confirmed design-limit conflict", note)


if __name__ == "__main__":
    unittest.main()
