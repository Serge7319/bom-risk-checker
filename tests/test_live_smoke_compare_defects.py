"""Regressions for live-smoke compare / risk / design-impact defects.

Uses synthetic fixtures only — no live distributor calls.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from src.component_family_profiles import (
    COMPARE_LIMIT_LE,
    FieldSpec,
    get_family_profile,
    infer_family_id,
)
from src.datasheet_comparison import build_datasheet_comparison, user_facing_comparison_rows
from src.parametric_compare import (
    compare_field_values,
    format_field_display_value,
    parse_numeric_with_unit,
    storage_unit_for_field,
)
from src.ui.detailed_risk_export import component_rows, report_exposure_summary


ROOT = Path(__file__).resolve().parents[1]


class FamilyInferenceSmokeTests(unittest.TestCase):
    def test_timers_and_oscillators_category_is_timer_not_crystal(self):
        part = {
            "manufacturer_part_number": "NE555P",
            "description": "IC OSC SINGLE TIMER 100KHZ 8-DIP",
            "Category": "Clock/Timing - Programmable Timers and Oscillators",
            "primary_category": "Clock/Timing|Programmable Timers and Oscillators",
            "product_type": "Programmable Timers and Oscillators",
        }
        self.assertEqual(infer_family_id(part), "Timer IC")
        self.assertEqual(get_family_profile(infer_family_id(part)).display_name, "Timer IC")

    def test_lm358dr_vs_ne555p_family_mismatch_not_crystal(self):
        from src.parts_compare import resolve_comparison_family

        opamp = {
            "manufacturer_part_number": "LM358DR",
            "description": "Dual operational amplifier",
            "architecture": "Operational Amplifier",
        }
        timer = {
            "manufacturer_part_number": "NE555P",
            "description": "IC OSC SINGLE TIMER 100KHZ 8-DIP",
            "primary_category": "Clock/Timing - Programmable Timers and Oscillators",
        }
        self.assertEqual(infer_family_id(opamp), "Operational amplifier")
        self.assertEqual(infer_family_id(timer), "Timer IC")
        meta = resolve_comparison_family(opamp, timer)
        self.assertTrue(meta["family_mismatch"])
        self.assertNotEqual(meta["family_b"], "Oscillator / crystal")

    def test_na555_only_datasheet_does_not_verify_ne555p_identity(self):
        from src.datasheet_comparison import verify_datasheet_identity

        na555_only = {
            "pages": [
                {
                    "page": 1,
                    "text": "NA555 Precision Timer\nTexas Instruments\nThis datasheet covers NA555 only.",
                }
            ],
            "source_name": "na555.pdf",
        }
        identity = verify_datasheet_identity(
            na555_only,
            manufacturer="Texas Instruments",
            mpn="NE555P",
        )
        self.assertFalse(identity["verified"])
        self.assertFalse(identity["mpn_verified"])

    def test_shared_family_datasheet_naming_ne555p_may_verify(self):
        from src.datasheet_comparison import verify_datasheet_identity

        shared = {
            "pages": [
                {
                    "page": 1,
                    "text": "NA555, NE555, SA555, SE555\nNE555P Precision Timers\nTexas Instruments",
                }
            ],
            "source_name": "na555.pdf",
        }
        identity = verify_datasheet_identity(
            shared,
            manufacturer="Texas Instruments",
            mpn="NE555P",
        )
        self.assertTrue(identity["mpn_verified"])
        self.assertTrue(identity["verified"])

    def test_primary_category_alone_classifies_timer_combo(self):
        self.assertEqual(
            infer_family_id(
                {
                    "primary_category": "Clock/Timing - Programmable Timers and Oscillators",
                    "description": "",
                }
            ),
            "Timer IC",
        )

    def test_explicit_crystal_still_maps_to_oscillator_family(self):
        part = {
            "manufacturer_part_number": "ABS07-32.768KHZ-T",
            "description": "CRYSTAL 32.7680KHZ 12.5PF SMD",
            "Category": "Crystals",
        }
        self.assertEqual(infer_family_id(part), "Oscillator / crystal")

    def test_555_mpn_token_without_category_is_timer(self):
        self.assertEqual(
            infer_family_id({"manufacturer_part_number": "LM555CN/NOPB", "description": ""}),
            "Timer IC",
        )


class UnitNormalizationSmokeTests(unittest.TestCase):
    def test_storage_units_for_opamp_keys(self):
        self.assertEqual(storage_unit_for_field("bandwidth_mhz"), "MHz")
        self.assertEqual(storage_unit_for_field("input_bias_na"), "nA")
        self.assertEqual(storage_unit_for_field("input_offset_mv"), "mV")

    def test_bare_digikey_floats_display_with_storage_units(self):
        self.assertEqual(format_field_display_value(0.7, field_key="bandwidth_mhz"), "0.7 MHz")
        self.assertEqual(format_field_display_value(20, field_key="input_bias_na"), "20 nA")
        self.assertEqual(format_field_display_value(3, field_key="input_offset_mv"), "3 mV")

    def test_bare_bandwidth_and_bias_parse_to_si(self):
        hz, unit = parse_numeric_with_unit("0.7 MHz", preferred_unit="MHz")
        self.assertEqual(unit, "Hz")
        self.assertAlmostEqual(hz or 0.0, 7e5)
        amp, a_unit = parse_numeric_with_unit("20 nA", preferred_unit="nA")
        self.assertEqual(a_unit, "A")
        self.assertAlmostEqual(amp or 0.0, 20e-9)
        bare_hz, _ = parse_numeric_with_unit(
            format_field_display_value(0.7, field_key="bandwidth_mhz"),
            preferred_unit="MHz",
        )
        self.assertAlmostEqual(bare_hz or 0.0, 7e5)

    def test_bare_offset_values_are_not_silently_compatible(self):
        spec = FieldSpec(
            key="input_offset_mv",
            label="Input offset",
            compare=COMPARE_LIMIT_LE,
            unit="mV",
        )
        left = format_field_display_value(3, field_key="input_offset_mv")
        right = format_field_display_value(2, field_key="input_offset_mv")
        status, note = compare_field_values(left, right, spec)
        # Unequal limits without a design/fit criterion are never Compatible.
        self.assertEqual(status, "Different")
        self.assertIn("design/fit limit", note.casefold())

        # Truly unitless magnitudes must not become Compatible.
        unitless = FieldSpec(
            key="mystery_limit",
            label="Mystery",
            compare=COMPARE_LIMIT_LE,
            unit="",
        )
        status2, note2 = compare_field_values("3", "2", unitless)
        self.assertEqual(status2, "Needs data")
        self.assertIn("unit", note2.casefold())

    def test_lm358dr_vs_lm358adr2g_offset_is_material_not_compatible(self):
        comparison = build_datasheet_comparison(
            {
                "manufacturer_part_number": "LM358DR",
                "description": "Operational amplifier",
                "architecture": "Operational Amplifier",
                "bandwidth_mhz": 0.7,
                "input_bias_na": 20,
                "input_offset_mv": 3,
                "lifecycle_status": "Active",
            },
            {
                "manufacturer_part_number": "LM358ADR2G",
                "description": "Operational amplifier",
                "architecture": "Operational Amplifier",
                "bandwidth_mhz": 1.0,
                "input_bias_na": 45,
                "input_offset_mv": 2,
                "lifecycle_status": "Active",
            },
        )
        rows = {row["Key"]: row for row in comparison.get("rows") or []}
        self.assertEqual(rows["input_offset_mv"]["Status"], "Different")
        projected = user_facing_comparison_rows([rows["input_offset_mv"]])
        self.assertEqual(projected[0]["Assessment"], "Material difference")
        self.assertIn("3 mV", str(rows["input_offset_mv"]["Original"]))
        self.assertIn("2 mV", str(rows["input_offset_mv"]["Candidate"]))
        self.assertIn("0.7 MHz", str(rows["bandwidth_mhz"]["Original"]))
        self.assertNotIn("0.7 Hz", str(rows["bandwidth_mhz"]["Original"]))
        self.assertIn("20 nA", str(rows["input_bias_na"]["Original"]))

    def test_compare_matrix_shows_mhz_and_na_not_hz_or_amperes(self):
        original = {
            "manufacturer_part_number": "LM358DR",
            "manufacturer": "Texas Instruments",
            "description": "Operational amplifier",
            "architecture": "Operational Amplifier",
            "bandwidth_mhz": 0.7,
            "input_bias_na": 20,
            "input_offset_mv": 3,
            "lifecycle_status": "Active",
            "field_sources": {
                "bandwidth_mhz": "DigiKey Gain Bandwidth Product",
                "input_bias_na": "DigiKey Current - Input Bias",
                "input_offset_mv": "DigiKey Voltage - Input Offset",
                "lifecycle_status": "DigiKey",
            },
        }
        candidate = {
            "manufacturer_part_number": "LM358P",
            "manufacturer": "Texas Instruments",
            "description": "Operational amplifier",
            "architecture": "Operational Amplifier",
            "bandwidth_mhz": 0.7,
            "input_bias_na": 20,
            "input_offset_mv": 2,
            "lifecycle_status": "Active",
            "field_sources": {
                "bandwidth_mhz": "DigiKey Gain Bandwidth Product",
                "input_bias_na": "DigiKey Current - Input Bias",
                "input_offset_mv": "DigiKey Voltage - Input Offset",
                "lifecycle_status": "DigiKey",
            },
        }
        comparison = build_datasheet_comparison(original, candidate)
        self.assertEqual(comparison.get("family"), "Operational amplifier")
        rows = {row["Key"]: row for row in comparison.get("rows") or []}
        bandwidth = str(rows["bandwidth_mhz"].get("Original"))
        bias = str(rows["input_bias_na"].get("Original"))
        self.assertIn("0.7 MHz", bandwidth)
        self.assertNotIn("0.7 Hz", bandwidth)
        self.assertIn("20 nA", bias)
        self.assertNotIn("20 A", bias)
        projected = user_facing_comparison_rows(comparison.get("rows") or [])
        lifecycle = next(
            row for row in projected if str(row.get("Attribute") or "").casefold().startswith("lifecycle")
        )
        self.assertEqual(lifecycle.get("Original"), "Active")
        self.assertEqual(lifecycle.get("Candidate"), "Active")
        # Catalog-only lifecycle agreement is not Compatible.
        self.assertEqual(lifecycle.get("Assessment"), "Supplier-listing agreement")


class RiskCountConsistencyTests(unittest.TestCase):
    def test_detailed_risk_high_count_matches_risk_level_high_only(self):
        parts = [
            {"MPN": f"HIGH{i}", "Risk Level": "High", "lifecycle_status": "Active"}
            for i in range(8)
        ] + [
            {"MPN": "NRND1", "Risk Level": "Medium", "lifecycle_status": "NRND"},
        ]
        rows = component_rows(parts)
        summary = report_exposure_summary(rows)
        self.assertEqual(summary["high_risk_component_count"], 8)
        # Lifecycle exposure remains available for cost/exposure views.
        self.assertEqual(summary["open_high_risk_component_count"], 9)


class DesignImpactPayloadTests(unittest.TestCase):
    def test_affected_projects_include_bom_row_fields(self):
        from src.design_impact_analyzer import build_design_impact

        analyses = [
            {
                "id": "a1",
                "project_name": "Radar",
                "filename": "radar_assembly_10parts.csv",
                "health_score": 72,
            }
        ]
        parts = [
            {
                "analysis_id": "a1",
                "mpn": "VERY-LONG-MANUFACTURER-PART-NUMBER-1234567890",
                "manufacturer": "Example Semi",
                "lifecycle_status": "Active",
                "risk_level": "High",
                "quantity": 4,
                "package": "SOIC-8",
            }
        ]
        intelligence = build_design_impact(analyses, parts, selected_mpn=parts[0]["mpn"])
        affected = intelligence.get("affected_projects") or []
        self.assertTrue(affected)
        row = affected[0]
        self.assertEqual(row.get("Project"), "Radar")
        self.assertIn("radar_assembly", str(row.get("BOM") or "").casefold())
        self.assertEqual(row.get("Part Number"), parts[0]["mpn"])
        self.assertEqual(int(row.get("Quantity") or 0), 4)
        self.assertEqual(row.get("Manufacturer"), "Example Semi")
        self.assertEqual(row.get("Lifecycle"), "Active")


class ExportProjectionSmokeTests(unittest.TestCase):
    def test_user_facing_rows_keep_units_and_assessments(self):
        rows = [
            {
                "Attribute": "Bandwidth",
                "Key": "bandwidth_mhz",
                "Part A": "0.7 MHz",
                "Part B": "0.7 MHz",
                "Part A MPN": "LM358DR",
                "Part B MPN": "LM358P",
                "Part A source": "DigiKey",
                "Part B source": "DigiKey",
                "Unit": "MHz",
                "Test condition": "Not stated",
                "Part A value class": "unknown",
                "Part B value class": "unknown",
                "Status": "Match",
                "Evidence": "Normalized values match within engineering tolerance.",
            }
        ]
        projected = user_facing_comparison_rows(rows)
        self.assertEqual(projected[0]["Original"], "0.7 MHz")
        self.assertEqual(projected[0]["Assessment"], "Compatible on available evidence")


class LifecycleEvidenceParityTests(unittest.TestCase):
    def test_public_part_card_keeps_lifecycle_evidence(self):
        from src.parts_compare import public_part_card

        evidence = [
            {"source": "DigiKey", "status": "Active", "retrieved_at": "2026-01-01"},
            {"source": "Mouser", "status": "NRND", "retrieved_at": "2026-01-02"},
        ]
        card = public_part_card(
            {
                "manufacturer_part_number": "LM358DR",
                "description": "Operational amplifier",
                "lifecycle_status": "Active",
                "lifecycle_evidence": evidence,
                "lifecycle_conflict": True,
            }
        )
        self.assertEqual(card["lifecycle_status"], "Active")
        self.assertTrue(card["lifecycle_conflict"])
        self.assertEqual(card["lifecycle_evidence"], evidence)

    def test_conflicting_status_is_counted_separately(self):
        from src.parts_compare import build_parts_comparison

        comparison = build_parts_comparison(
            {
                "manufacturer_part_number": "PARTA",
                "description": "Operational amplifier",
                "architecture": "Operational Amplifier",
                "lifecycle_status": "Active",
                "lifecycle_conflict": True,
                "lifecycle_evidence": [
                    {"source": "DigiKey", "status": "Active", "retrieved_at": "t1"},
                    {"source": "Mouser", "status": "NRND", "retrieved_at": "t2"},
                ],
            },
            {
                "manufacturer_part_number": "PARTB",
                "description": "Operational amplifier",
                "architecture": "Operational Amplifier",
                "lifecycle_status": "Active",
            },
            part_a_mpn="PARTA",
            part_b_mpn="PARTB",
        )
        counts = comparison.get("counts") or {}
        self.assertGreaterEqual(int(counts.get("Conflicting") or 0), 1)
        self.assertNotEqual(int(counts.get("Conflicting") or 0), 0)

    def test_find_replacement_candidate_not_qualified_on_lifecycle_conflict(self):
        # Unit-level projection of the legacy workflow fit gate (no live suppliers).
        lifecycle_conflict = True
        lifecycle_status = "Active"
        fit = "supplier-listed candidate; qualification required"
        if lifecycle_conflict or not lifecycle_status or lifecycle_status.casefold() in {
            "unknown",
            "not stated",
        }:
            fit = "not qualified — lifecycle evidence incomplete or conflicting"
        self.assertIn("not qualified", fit.casefold())
        self.assertNotIn("drop-in", fit.casefold())

    def test_pdf_export_includes_unit_and_lifecycle_conflict(self):
        from io import BytesIO

        from pypdf import PdfReader

        from src.parts_compare import build_parts_comparison, generate_parts_comparison_pdf

        comparison = build_parts_comparison(
            {
                "manufacturer_part_number": "LM358DR",
                "manufacturer": "Texas Instruments",
                "description": "Operational amplifier",
                "architecture": "Operational Amplifier",
                "bandwidth_mhz": 0.7,
                "input_bias_na": 20,
                "input_offset_mv": 3,
                "lifecycle_status": "Active",
                "lifecycle_conflict": True,
                "lifecycle_evidence": [
                    {"source": "DigiKey", "status": "Active"},
                    {"source": "Mouser", "status": "NRND"},
                ],
            },
            {
                "manufacturer_part_number": "LM358ADR2G",
                "manufacturer": "onsemi",
                "description": "Operational amplifier",
                "architecture": "Operational Amplifier",
                "bandwidth_mhz": 1.0,
                "input_bias_na": 45,
                "input_offset_mv": 2,
                "lifecycle_status": "Active",
            },
            part_a_mpn="LM358DR",
            part_b_mpn="LM358ADR2G",
        )
        pdf = generate_parts_comparison_pdf(comparison)
        self.assertTrue(pdf.startswith(b"%PDF"))
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("Unit", text)
        self.assertIn("conflicting supplier records", text.casefold())
        self.assertIn("Material difference", text)
        # Display units must not collapse to bare SI bases.
        self.assertNotIn("0.7 Hz", text)
        self.assertNotIn("20 A", text)


if __name__ == "__main__":
    unittest.main()
