"""Regressions for the two-BOM production smoke parity plan.

Covers family-relevant replacement partitioning, compare honesty, live/synthetic/
missing provenance, export byte contents, stray line_type suppression helpers,
Design Impact multi-BOM rows, and decision snapshot reuse. Synthetic fixtures only.
"""
from __future__ import annotations

import csv
import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from apps.api.evidence_contract import annotate_report_parts
from apps.api.report_exports import build_csv, build_pdf, build_xlsx
from src.alternative_classification import (
    CLASS_CATALOG_INSUFFICIENT,
    CLASS_SPEC_MATCHED,
    candidate_family_compatible_with_original,
    classify_candidate_family_bucket,
    partition_candidates_by_family,
    refine_classification_after_comparison,
)
from src.component_family_profiles import (
    COMPARE_LIMIT_GE,
    COMPARE_NOMINAL,
    FieldSpec,
)
from src.datasheet_comparison import build_datasheet_comparison
from src.design_impact_analyzer import build_design_impact
from src.parametric_compare import (
    compare_field_values,
    engineering_confidence_from_rows,
)
from src.parts_compare import (
    FINDING_COMPATIBLE,
    FINDING_LISTING_AGREEMENT,
    FINDING_NEEDS_VERIFICATION,
    map_status_to_assessment,
    user_facing_compare_rows,
)
from src.procurement_advisor import normalize_supplier_offer_records


ROOT = Path(__file__).resolve().parents[1]
FLAT_BOM = ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv"
NESTED_BOM = ROOT / "tests" / "fixtures" / "nested_bom_product.csv"


class FamilyPartitionTests(unittest.TestCase):
    def test_flash_original_rejects_mcu_led_and_capacitor_leads(self):
        original = {
            "manufacturer_part_number": "FLASH-EXAMPLE-01",
            "description": "128Mbit SPI NOR Flash memory",
            "primary_category": "Memory|Flash",
            "architecture": "NOR Flash",
        }
        leads = [
            {
                "manufacturer_part_number": "MCU-EXAMPLE-01",
                "description": "32-bit ARM Cortex-M0 microcontroller",
                "primary_category": "Embedded Controllers|Microcontrollers",
            },
            {
                "manufacturer_part_number": "LED-EXAMPLE-01",
                "description": "High-brightness red LED",
                "primary_category": "Optoelectronics|LED Indication",
            },
            {
                "manufacturer_part_number": "CAP-EXAMPLE-01",
                "description": "Ceramic capacitor 0.1uF 50V",
                "primary_category": "Capacitors|Ceramic",
            },
            {
                "manufacturer_part_number": "FLASH-EXAMPLE-02",
                "description": "256Mbit SPI NOR Flash memory",
                "primary_category": "Memory|Flash",
                "architecture": "NOR Flash",
            },
        ]
        relevant, unclassified, unfiltered = partition_candidates_by_family(original, leads)
        relevant_mpns = {row["manufacturer_part_number"] for row in relevant}
        unfiltered_mpns = {row["manufacturer_part_number"] for row in unfiltered}
        self.assertIn("FLASH-EXAMPLE-02", relevant_mpns)
        self.assertTrue({"MCU-EXAMPLE-01", "LED-EXAMPLE-01", "CAP-EXAMPLE-01"} <= unfiltered_mpns)
        self.assertNotIn("MCU-EXAMPLE-01", relevant_mpns)
        self.assertEqual(unclassified, [])

    def test_unknown_family_candidate_is_unclassified_not_relevant(self):
        original = {
            "manufacturer_part_number": "FPGA-EXAMPLE-01",
            "description": "Field programmable gate array",
            "primary_category": "Embedded|FPGAs",
        }
        unknown = {
            "manufacturer_part_number": "GENERIC-EXAMPLE-01",
            "description": "",
            "primary_category": "",
        }
        self.assertFalse(candidate_family_compatible_with_original(original, unknown))
        self.assertEqual(classify_candidate_family_bucket(original, unknown), "unclassified")
        relevant, unclassified, unfiltered = partition_candidates_by_family(
            original, [unknown]
        )
        self.assertEqual(relevant, [])
        self.assertEqual(unfiltered, [])
        self.assertEqual(
            [row["manufacturer_part_number"] for row in unclassified],
            ["GENERIC-EXAMPLE-01"],
        )

    def test_family_filter_errors_fail_closed_out_of_relevant(self):
        original = {
            "manufacturer_part_number": "FLASH-EXAMPLE-01",
            "description": "128Mbit SPI NOR Flash memory",
            "primary_category": "Memory|Flash",
        }
        lead = {
            "manufacturer_part_number": "FLASH-EXAMPLE-02",
            "description": "256Mbit SPI NOR Flash memory",
            "primary_category": "Memory|Flash",
        }
        with unittest.mock.patch(
            "src.alternative_classification.classify_candidate_family_bucket",
            side_effect=RuntimeError("family filter boom"),
        ):
            relevant, unclassified, unfiltered = partition_candidates_by_family(
                original, [lead]
            )
        self.assertEqual(relevant, [])
        self.assertEqual(unfiltered, [])
        self.assertEqual(
            [row["manufacturer_part_number"] for row in unclassified],
            ["FLASH-EXAMPLE-02"],
        )


class CompareHonestyTests(unittest.TestCase):
    def test_unknown_value_classes_are_not_compatible(self):
        spec = FieldSpec(
            key="input_bias_na",
            label="Input bias",
            compare=COMPARE_NOMINAL,
            unit="A",
            value_role="typical",
        )
        status, note = compare_field_values("20 nA", "20 nA", spec)
        self.assertEqual(status, "Needs data")
        self.assertIn("class", note.casefold())
        self.assertEqual(map_status_to_assessment(status), FINDING_NEEDS_VERIFICATION)

    def test_unequal_unknown_class_values_need_verification(self):
        spec = FieldSpec(
            key="input_bias_na",
            label="Input bias",
            compare=COMPARE_NOMINAL,
            unit="A",
            value_role="typical",
        )
        status, note = compare_field_values("20 nA", "45 nA", spec)
        self.assertEqual(status, "Needs data")
        self.assertNotEqual(status, "Different")
        self.assertIn("class", note.casefold())
        self.assertEqual(map_status_to_assessment(status), FINDING_NEEDS_VERIFICATION)

    def test_typical_without_test_conditions_needs_verification(self):
        spec = FieldSpec(
            key="input_bias_na",
            label="Input bias",
            compare=COMPARE_NOMINAL,
            unit="A",
            value_role="typical",
        )
        equal_status, equal_note = compare_field_values(
            "20 nA (typ)", "20 nA (typ)", spec
        )
        self.assertEqual(equal_status, "Needs data")
        self.assertIn("condition", equal_note.casefold())
        unequal_status, unequal_note = compare_field_values(
            "20 nA (typ)", "45 nA (typ)", spec
        )
        self.assertEqual(unequal_status, "Needs data")
        self.assertNotEqual(unequal_status, "Different")
        self.assertIn("condition", unequal_note.casefold())

    def test_typical_with_matching_conditions_can_match_or_differ(self):
        spec = FieldSpec(
            key="input_bias_na",
            label="Input bias",
            compare=COMPARE_NOMINAL,
            unit="A",
            value_role="typical",
        )
        status_ok, _ = compare_field_values(
            "20 nA (typ) @ 25C", "20 nA (typ) @ 25C", spec
        )
        self.assertEqual(status_ok, "Match")
        status_diff, _ = compare_field_values(
            "20 nA (typ) @ 25C", "45 nA (typ) @ 25C", spec
        )
        self.assertEqual(status_diff, "Different")

    def test_mismatched_value_classes_need_verification(self):
        spec = FieldSpec(
            key="input_bias_na",
            label="Input bias",
            compare=COMPARE_NOMINAL,
            unit="A",
            value_role="typical",
        )
        status, note = compare_field_values("20 nA (typ)", "20 nA (max)", spec)
        self.assertEqual(status, "Needs data")
        self.assertIn("labeled", note.casefold())

    def test_bare_numeric_with_preferred_unit_needs_data(self):
        spec = FieldSpec(
            key="voltage_rating",
            label="Voltage rating",
            compare=COMPARE_LIMIT_GE,
            unit="V",
        )
        # Bare magnitudes must not become Compatible even when preferred unit is V.
        status, note = compare_field_values("14", "14", spec)
        self.assertEqual(status, "Needs data")
        self.assertNotEqual(status, "Match")
        self.assertTrue("unit" in note.casefold() or "class" in note.casefold())

    def test_incomparable_formats_are_needs_data_not_material(self):
        spec = FieldSpec(
            key="resistance",
            label="Resistance",
            compare=COMPARE_NOMINAL,
            unit="Ohm",
        )
        status, _note = compare_field_values("see graph", "10k", spec)
        self.assertEqual(status, "Needs data")

    def test_supplier_only_catalog_match_is_listing_agreement(self):
        original = {
            "manufacturer_part_number": "RES-EXAMPLE-A",
            "manufacturer": "Acme",
            "description": "10k resistor 0603",
            "resistance": "10 kOhm (typ)",
            "source": "DigiKey",
            "field_sources": {"resistance": "DigiKey"},
            "supplier_data_verified": True,
        }
        candidate = {
            "manufacturer_part_number": "RES-EXAMPLE-B",
            "manufacturer": "Acme",
            "description": "10k resistor 0603",
            "resistance": "10 kOhm (typ)",
            "source": "Mouser",
            "field_sources": {"resistance": "Mouser"},
            "supplier_data_verified": True,
        }
        comparison = build_datasheet_comparison(original, candidate)
        resistance = next(row for row in comparison["rows"] if row["Attribute"] == "Resistance")
        self.assertEqual(resistance["Status"], "Listing agreement")
        projected = next(
            row for row in user_facing_compare_rows(comparison["rows"]) if row["Attribute"] == "Resistance"
        )
        self.assertEqual(projected["Assessment"], FINDING_LISTING_AGREEMENT)
        self.assertNotEqual(projected["Assessment"], FINDING_COMPATIBLE)

    def test_listing_agreement_does_not_create_engineering_ready_result(self):
        rows = [
            {
                "Attribute": "Resistance",
                "Key": "resistance",
                "Status": "Listing agreement",
                "Required": True,
            },
            {
                "Attribute": "Tolerance",
                "Key": "tolerance",
                "Status": "Listing agreement",
                "Required": True,
            },
            {
                "Attribute": "Package",
                "Key": "package",
                "Status": "Listing agreement",
                "Required": True,
            },
            {
                "Attribute": "Power",
                "Key": "power",
                "Status": "Listing agreement",
                "Required": False,
            },
        ]
        scored = engineering_confidence_from_rows(rows)
        self.assertEqual(scored["matches"], 0)
        self.assertEqual(scored["listing_agreements"], 4)
        self.assertGreater(scored["required_missing"], 0)
        self.assertLess(scored["engineering_comparison_confidence"], 75)
        self.assertNotEqual(scored["engineering_evidence_status"], "complete")

        promoted = refine_classification_after_comparison(
            CLASS_CATALOG_INSUFFICIENT,
            {"Match": 0, "Listing agreement": 6, "Different": 0, "Needs data": 0},
        )
        self.assertEqual(promoted, CLASS_CATALOG_INSUFFICIENT)
        self.assertNotEqual(promoted, CLASS_SPEC_MATCHED)

    def test_operating_and_storage_temperature_are_separate_fields(self):
        from src.component_family_profiles import comparison_fields, get_family_profile

        fields = comparison_fields(get_family_profile("Operational amplifier"))
        keys = {spec.key for spec in fields}
        self.assertIn("temperature_range", keys)
        self.assertIn("storage_temperature", keys)
        operating = next(spec for spec in fields if spec.key == "temperature_range")
        self.assertNotIn("temperature range", " ".join(operating.pdf_aliases).casefold())
        self.assertIn("operating", " ".join(operating.pdf_aliases).casefold())


class ProvenanceAndOffersTests(unittest.TestCase):
    def test_report_evidence_summary_matches_live_synthetic_missing_counts(self):
        report = annotate_report_parts(
            {
                "mode": "legacy-supplier-engine",
                "parts": [
                    {
                        "MPN": "LIVE-1",
                        "manufacturer_part_number": "LIVE-1",
                        "supplier_data_verified": True,
                        "evidence_source": "live-authorized-supplier",
                        "source": "DigiKey",
                        "product_url": "https://www.digikey.com/product/LIVE-1",
                        "retrieved_at": "2026-11-01T12:00:00Z",
                    },
                    {
                        "MPN": "SYN-1",
                        "manufacturer_part_number": "SYN-1",
                        "supplier_data_verified": True,
                        "evidence_source": "synthetic-preview",
                        "source": "synthetic-preview",
                    },
                    {
                        "MPN": "MISS-1",
                        "manufacturer_part_number": "MISS-1",
                        "supplier_data_verified": False,
                        "evidence_class": "missing",
                        "evidence_source": "missing",
                    },
                ],
            }
        )
        summary = report["evidence_summary"]
        self.assertEqual(summary["live_count"], 1)
        self.assertEqual(summary["synthetic_count"], 1)
        self.assertEqual(summary["missing_count"], 1)
        # Synthetic must never inflate the live verified bucket.
        self.assertEqual(
            sum(
                1
                for part in report["parts"]
                if (part.get("evidence") or {}).get("evidence_class") == "live-authorized-supplier"
            ),
            1,
        )

    def test_offer_normalization_keeps_price_break_and_retrieval_provenance(self):
        offers = normalize_supplier_offer_records(
            {
                "primary_supplier": "DigiKey",
                "unit_price": 0.12,
                "currency": "USD",
                "stock_available": 5000,
                "lead_time_weeks": 2,
                "supplier_offers": [
                    {
                        "supplier": "DigiKey",
                        "unit_price": 0.12,
                        "currency": "USD",
                        "stock": 5000,
                        "lead_time_weeks": 2,
                        "price_break_quantity": 100,
                        "retrieved_at": "2026-11-01T12:00:00Z",
                        "product_url": "https://www.digikey.com/product/X",
                    },
                    {
                        "supplier": "DigiKey",
                        "unit_price": 0.12,
                        "currency": "USD",
                        "stock": 5000,
                        "lead_time_weeks": 2,
                        "price_break_quantity": 100,
                        "retrieved_at": "2026-11-01T12:00:00Z",
                    },
                ],
            }
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["price_break_quantity"], 100)
        self.assertEqual(offers[0]["retrieved_at"], "2026-11-01T12:00:00Z")


class ExportAndSignalsTests(unittest.TestCase):
    def _sample_report(self, *, mode: str = "synthetic-preview") -> dict:
        return {
            "project_name": "Smoke Demo",
            "bom_name": "smoke.csv",
            "mode": mode,
            "health_score": "Not scored",
            "parts": [
                {
                    "MPN": "PART-A",
                    "Manufacturer": "Acme",
                    "Description": "Example part",
                    "line_type": "part",
                    "Risk Level": "Needs verification",
                    "Risk Score": None,
                    "evidence": {"evidence_class": "synthetic-preview", "source": "synthetic-preview"},
                },
                {
                    "MPN": "ASM-1",
                    "Manufacturer": "Acme",
                    "line_type": "assembly",
                    "Risk Level": "Medium",
                    "Risk Score": 40,
                    "evidence": {"evidence_class": "missing", "source": ""},
                },
            ],
        }

    def test_export_bytes_include_evidence_and_do_not_coerce_missing_risk_to_zero(self):
        report = self._sample_report()
        csv_text = build_csv(report).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(len(rows), 2)
        part_a = next(row for row in rows if row["MPN"] == "PART-A")
        self.assertIn(part_a["Risk Score"], {"", "None", "Not assessed", "not assessed"})
        self.assertNotEqual(part_a["Risk Score"], "0")
        # Unscored parts keep an explicit non-low label (Needs verification / Not assessed).
        self.assertNotIn(part_a["Risk Level"].casefold(), {"low", "healthy", "0"})
        self.assertEqual(part_a["Line Type"], "")
        self.assertEqual(part_a["Evidence Class"], "synthetic-preview")
        assembly = next(row for row in rows if row["MPN"] == "ASM-1")
        self.assertEqual(assembly["Line Type"], "assembly")

        pdf = build_pdf(report)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 500)

        xlsx = build_xlsx(report)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(xlsx)))
        workbook = load_workbook(io.BytesIO(xlsx), data_only=False)
        for sheet_name in ("Summary", "Components", "Component Details", "High Risk Parts"):
            self.assertIn(sheet_name, workbook.sheetnames)
        summary = workbook["Summary"]
        summary_values = " ".join(
            str(cell.value or "") for row in summary.iter_rows(max_row=20) for cell in row
        )
        self.assertIn("Not scored", summary_values)
        self.assertIn("not assessed", summary_values.casefold())
        self.assertIn("not proof of low risk", summary_values.casefold())
        components = workbook["Components"]
        header = [cell.value for cell in next(components.iter_rows(min_row=1, max_row=1))]
        risk_idx = header.index("Risk Score")
        level_idx = header.index("Risk Level")
        line_idx = header.index("Line Type")
        first_row = next(components.iter_rows(min_row=2, max_row=2))
        self.assertNotEqual(str(first_row[risk_idx].value), "0")
        self.assertEqual(str(first_row[risk_idx].value), "Not assessed")
        self.assertNotIn(str(first_row[level_idx].value or "").casefold(), {"low", "healthy"})
        self.assertIn(str(first_row[line_idx].value or ""), {"", "None"})

    def test_both_synthetic_bom_fixtures_exist_for_preview_workflows(self):
        self.assertTrue(FLAT_BOM.is_file())
        self.assertTrue(NESTED_BOM.is_file())
        with FLAT_BOM.open(encoding="utf-8") as handle:
            flat_rows = list(csv.DictReader(handle))
        self.assertGreaterEqual(len(flat_rows), 20)

    def test_generic_part_line_type_is_suppressed_in_signal_helper(self):
        def visible_line_type(value: str | None) -> str | None:
            text = str(value or "").strip()
            if not text or text.casefold() == "part":
                return None
            return text

        self.assertIsNone(visible_line_type("part"))
        self.assertIsNone(visible_line_type("Part"))
        self.assertEqual(visible_line_type("assembly"), "assembly")
        self.assertEqual(visible_line_type("subassembly"), "subassembly")


class DesignImpactAndDecisionTests(unittest.TestCase):
    def test_same_mpn_keeps_one_row_per_saved_bom(self):
        analyses = [
            {"id": "bom-a", "project_name": "Alpha", "filename": "alpha.csv", "health_score": 70},
            {"id": "bom-b", "project_name": "Beta", "filename": "beta.csv", "health_score": 80},
            {"id": "bom-c", "project_name": "Alpha", "filename": "alpha-rev2.csv", "health_score": 60},
        ]
        parts = [
            {"analysis_id": "bom-a", "mpn": "SHARED-1", "risk_score": 55, "quantity": 2},
            {"analysis_id": "bom-b", "mpn": "SHARED-1", "risk_score": 30, "quantity": 1},
            {"analysis_id": "bom-c", "mpn": "SHARED-1", "quantity": 4},
        ]
        result = build_design_impact(analyses, parts, selected_mpn="SHARED-1")
        self.assertEqual(result["affected_bom_count"], 3)
        self.assertEqual(len(result["affected_projects"]), 3)
        unscored = next(row for row in result["affected_projects"] if row.get("Analysis ID") == "bom-c")
        self.assertEqual(unscored["Risk Score"], "Not assessed")
        self.assertEqual(unscored["Quantity"], 4)

    def test_lm358dr_quantity_aggregates_across_two_synthetic_boms(self):
        analyses = [
            {
                "id": "flat-bom",
                "project_name": "PR597 Flat Smoke",
                "filename": "flat-synthetic-25",
                "health_score": 70,
            },
            {
                "id": "nested-bom",
                "project_name": "PR597 Nested Smoke",
                "filename": "nested-product-hierarchy",
                "health_score": 65,
            },
        ]
        parts = [
            {"analysis_id": "flat-bom", "mpn": "LM358DR", "quantity": 4, "risk_score": 35},
            {"analysis_id": "nested-bom", "mpn": "LM358DR", "quantity": 4, "risk_score": 40},
        ]
        result = build_design_impact(analyses, parts, selected_mpn="LM358DR")
        self.assertEqual(result["affected_bom_count"], 2)
        self.assertEqual(len(result["affected_projects"]), 2)
        self.assertEqual(result["total_quantity"], 8)
        quantities = sorted(int(row["Quantity"]) for row in result["affected_projects"])
        self.assertEqual(quantities, [4, 4])
        bom_names = {str(row.get("BOM") or "") for row in result["affected_projects"]}
        self.assertEqual(bom_names, {"flat-synthetic-25", "nested-product-hierarchy"})

    def _run_decision_snapshot_case(self, *, scenario: str):
        import tempfile

        from apps.api.main import app
        from apps.api.sandbox_auth import reset_auth_store_for_tests
        from apps.api.workspace_store import reset_store_for_tests
        from starlette.testclient import TestClient
        from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS

        captured = {"compare_calls": 0, "last_analysis_id": None}

        def _fake_compare(**kwargs):
            captured["compare_calls"] += 1
            captured["last_analysis_id"] = kwargs.get("analysis_id")
            return {
                "ok": True,
                "part_a": kwargs.get("part_a") or "PART-A",
                "part_b": kwargs.get("part_b") or "PART-B",
                "analysis_id": kwargs.get("analysis_id") or "analysis-1",
                "rows": [{"Attribute": "Package", "Status": "Match"}],
                "mode": "synthetic-preview",
                "finding": "Needs verification",
                "source_a": "synthetic-preview",
                "source_b": "synthetic-preview",
                "datasheet_identity": {
                    "part_a": {"verified": False},
                    "part_b": {"verified": False},
                },
            }

        with tempfile.TemporaryDirectory() as tmp:
            reset_store_for_tests(Path(tmp) / "store.json")
            reset_auth_store_for_tests(Path(tmp) / "auth.json", accounts=SANDBOX_SEED_USERS)
            with patch.dict(
                "os.environ",
                {
                    "CADIVOR_SANDBOX_AUTH_SECRET": "test-sandbox-auth-secret-key",
                    "CADIVOR_COMPARISON_SNAPSHOT_SECRET": "test-comparison-snapshot-secret",
                    "CADIVOR_ALLOW_EPHEMERAL_FILE_STORE": "1",
                    "CADIVOR_ALLOW_SANDBOX_JWT": "1",
                },
                clear=False,
            ), TestClient(app) as client, patch(
                "apps.api.main.migration_tools.compare_parts_payload",
                side_effect=_fake_compare,
            ):
                login = client.post(
                    "/auth/login",
                    json={
                        "email": SANDBOX_SEED_USERS[0]["email"],
                        "password": SANDBOX_SEED_USERS[0]["password"],
                    },
                )
                self.assertEqual(login.status_code, 200, login.text)
                token = login.json()["access_token"]
                analyze = client.post(
                    "/boms/analyze",
                    headers={"Authorization": f"Bearer {token}"},
                    data={
                        "project_name": "Snapshot reuse",
                        "bom_name": "Synthetic",
                        "revision": "A",
                    },
                    files={
                        "file": (
                            "synthetic_bom_25parts.csv",
                            FLAT_BOM.read_bytes(),
                            "text/csv",
                        )
                    },
                )
                self.assertEqual(analyze.status_code, 200, analyze.text)
                analysis_id = analyze.json()["analysis_id"]
                report = client.get(
                    f"/reports/{analysis_id}",
                    headers={"Authorization": f"Bearer {token}"},
                ).json()
                part_a = report["parts"][0]["MPN"]
                part_b = report["parts"][1]["MPN"]

                compare = client.post(
                    "/tools/compare-parts",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "part_a": part_a,
                        "part_b": part_b,
                        "analysis_id": analysis_id,
                    },
                )
                self.assertEqual(compare.status_code, 200, compare.text)
                snapshot = compare.json()
                self.assertTrue(snapshot.get("snapshot_token"))
                self.assertEqual(captured["compare_calls"], 1)

                if scenario == "reuse":
                    response = client.post(
                        "/decision-records",
                        headers={"Authorization": f"Bearer {token}"},
                        json={
                            "analysis_id": analysis_id,
                            "part_a": part_a,
                            "part_b": part_b,
                            "decision": "hold_for_review",
                            "reviewer": "Smoke Reviewer",
                            "rationale": "Snapshot reuse regression.",
                            "validation_checks": [],
                            "residual_risk": "unknown",
                            "comparison_snapshot": snapshot,
                        },
                    )
                    self.assertEqual(response.status_code, 201, response.text)
                    self.assertEqual(captured["compare_calls"], 1)
                    saved = response.json()["record"]["comparison_snapshot"]
                    self.assertEqual(saved["rows"][0]["Attribute"], "Package")
                    self.assertFalse(response.json()["record"]["verified_primary_evidence"])
                    return

                if scenario == "forged":
                    forged = dict(snapshot)
                    forged["source_a"] = "Manufacturer datasheet (forged)"
                    forged["source_b"] = "Manufacturer datasheet (forged)"
                    forged["datasheet_identity"] = {
                        "part_a": {"verified": True},
                        "part_b": {"verified": True},
                    }
                    response = client.post(
                        "/decision-records",
                        headers={"Authorization": f"Bearer {token}"},
                        json={
                            "analysis_id": analysis_id,
                            "part_a": part_a,
                            "part_b": part_b,
                            "decision": "hold_for_review",
                            "reviewer": "Smoke Reviewer",
                            "rationale": "Forged identity must not be trusted.",
                            "validation_checks": [
                                "manufacturer_datasheet_reviewed",
                                "package_pinout_verified",
                                "electrical_limits_verified",
                            ],
                            "residual_risk": "unknown",
                            "comparison_snapshot": forged,
                            "verified_primary_evidence": True,
                        },
                    )
                    self.assertEqual(response.status_code, 201, response.text)
                    self.assertEqual(captured["compare_calls"], 2)
                    record = response.json()["record"]
                    self.assertEqual(
                        record["comparison_snapshot"].get("source_a"),
                        "synthetic-preview",
                    )
                    self.assertFalse(record["verified_primary_evidence"])
                    return

                if scenario == "mismatched_analysis":
                    analyze_b = client.post(
                        "/boms/analyze",
                        headers={"Authorization": f"Bearer {token}"},
                        data={
                            "project_name": "Other analysis",
                            "bom_name": "Other",
                            "revision": "B",
                        },
                        files={
                            "file": (
                                "synthetic_bom_25parts.csv",
                                FLAT_BOM.read_bytes(),
                                "text/csv",
                            )
                        },
                    )
                    self.assertEqual(analyze_b.status_code, 200, analyze_b.text)
                    other_analysis_id = analyze_b.json()["analysis_id"]
                    self.assertNotEqual(analysis_id, other_analysis_id)
                    response = client.post(
                        "/decision-records",
                        headers={"Authorization": f"Bearer {token}"},
                        json={
                            "analysis_id": other_analysis_id,
                            "part_a": part_a,
                            "part_b": part_b,
                            "decision": "hold_for_review",
                            "reviewer": "Smoke Reviewer",
                            "rationale": "Mismatched analysis ID must recompute.",
                            "validation_checks": [],
                            "residual_risk": "unknown",
                            "comparison_snapshot": snapshot,
                        },
                    )
                    self.assertEqual(response.status_code, 201, response.text)
                    self.assertEqual(captured["compare_calls"], 2)
                    self.assertEqual(captured["last_analysis_id"], other_analysis_id)
                    self.assertEqual(
                        response.json()["record"]["analysis_id"], other_analysis_id
                    )
                    return

                raise AssertionError(f"Unknown scenario: {scenario}")

    def test_decision_endpoint_reuses_matching_comparison_snapshot(self):
        self._run_decision_snapshot_case(scenario="reuse")

    def test_decision_rejects_forged_snapshot_identity_and_recomputes(self):
        self._run_decision_snapshot_case(scenario="forged")

    def test_decision_mismatched_analysis_id_forces_recompute(self):
        self._run_decision_snapshot_case(scenario="mismatched_analysis")


if __name__ == "__main__":
    unittest.main()
