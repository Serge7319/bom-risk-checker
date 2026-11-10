"""Acceptance regressions for the Nov 10 production-smoke evidence follow-up."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apps.api.bom_hierarchy import attach_hierarchy_fields
from apps.api.migration_tools import procurement_payload
from apps.api.synthetic_analyze import analyze_upload, get_report
from apps.api.workspace_store import reset_store_for_tests
from src.component_family_profiles import (
    COMPARE_LIMIT_LE,
    FieldSpec,
    get_family_profile,
)
from src.datasheet_comparison import build_datasheet_comparison
from src.parametric_compare import compare_field_values, supply_range_finding
from src.parts_compare import FINDING_COMPATIBLE, FINDING_LISTING_AGREEMENT, map_status_to_assessment


ROOT = Path(__file__).resolve().parents[1]
WEB_COMPARE = ROOT / "apps" / "web" / "src" / "app" / "compare-parts" / "page.tsx"
WEB_PROCUREMENT = ROOT / "apps" / "web" / "src" / "app" / "procurement" / "page.tsx"
WEB_REPLACEMENT = ROOT / "apps" / "web" / "src" / "app" / "find-replacement" / "page.tsx"
MULTI_COMPARE = ROOT / "apps" / "web" / "src" / "lib" / "multiCompare.ts"


class UnknownClassAndRangeNormalizationTests(unittest.TestCase):
    def test_production_limit_field_unknown_class_needs_data(self):
        profile = get_family_profile("Operational amplifier")
        bias = next(field for field in profile.fields if field.key == "input_bias_na")
        self.assertEqual(bias.compare, COMPARE_LIMIT_LE)
        self.assertEqual(str(bias.value_role or "").casefold(), "max")
        status, note = compare_field_values("20 nA", "45 nA", bias)
        self.assertEqual(status, "Needs data")
        self.assertIn("class", note.casefold())
        self.assertNotEqual(status, "Different")
        self.assertNotEqual(map_status_to_assessment(status), FINDING_COMPATIBLE)

    def test_equal_supply_spans_with_alternate_punctuation_match(self):
        status, note = supply_range_finding("3 V ~ 32 V", "3V to 32V")
        self.assertEqual(status, "Match")
        self.assertIn("equivalent", note.casefold())

        voltage = FieldSpec(
            key="voltage_range",
            label="Supply voltage",
            compare="exact",
            unit="V",
            value_role="range",
        )
        field_status, field_note = compare_field_values("3 V ~ 32 V", "3V to 32V", voltage)
        self.assertEqual(field_status, "Match")
        self.assertIn("equivalent", field_note.casefold())

    def test_catalog_mounting_match_is_listing_agreement(self):
        original = {
            "manufacturer_part_number": "LM358DR",
            "architecture": "Operational Amplifier",
            "package": "8-SOIC",
            "pin_count": 8,
            "mounting_style": "Surface Mount",
            "lifecycle_status": "Active",
            "source": "DigiKey",
        }
        candidate = {
            "manufacturer_part_number": "LM358DR2G",
            "architecture": "Operational Amplifier",
            "package": "8-SOIC",
            "pin_count": 8,
            "mounting_style": "SMT",
            "lifecycle_status": "Active",
            "source": "Mouser",
        }
        comparison = build_datasheet_comparison(original, candidate)
        by_attr = {row["Attribute"]: row for row in comparison["rows"]}
        self.assertIn("Mounting", by_attr)
        self.assertEqual(by_attr["Mounting"]["Status"], "Listing agreement")
        self.assertEqual(
            map_status_to_assessment(by_attr["Mounting"]["Status"]),
            FINDING_LISTING_AGREEMENT,
        )
        self.assertNotEqual(
            map_status_to_assessment(by_attr["Mounting"]["Status"]),
            FINDING_COMPATIBLE,
        )


class MultiAlternateSourceRecordTests(unittest.TestCase):
    def test_multi_compare_helpers_and_page_render_source_records(self):
        multi_src = MULTI_COMPARE.read_text(encoding="utf-8")
        page_src = WEB_COMPARE.read_text(encoding="utf-8")
        self.assertIn("buildMultiSourceRecords", multi_src)
        self.assertIn("buildMultiDecisionSnapshot", multi_src)
        self.assertIn("multi_source_records", multi_src)
        self.assertIn("candidate_snapshots", multi_src)
        self.assertIn("buildMultiSourceRecords", page_src)
        self.assertIn('data-testid="multi-source-records"', page_src)
        self.assertIn("Field-level evidence", page_src)


class ProcurementAnalysisSelectionTests(unittest.TestCase):
    def test_flat_and_nested_analyses_do_not_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            reset_store_for_tests(Path(tmp) / "store.json")
            flat_csv = (ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv").read_bytes()
            nested_csv = (ROOT / "tests" / "fixtures" / "nested_bom_product.csv").read_bytes()
            flat = analyze_upload(
                filename="flat.csv",
                payload=flat_csv,
                workspace_id="ws-procure",
                project_name="Flat Project",
                bom_name="flat-bom",
                revision="F1",
            )
            nested = analyze_upload(
                filename="nested.csv",
                payload=nested_csv,
                workspace_id="ws-procure",
                project_name="Nested Project",
                bom_name="nested-bom",
                revision="N1",
            )
            flat_id = str(flat["id"])
            nested_id = str(nested["id"])

            flat_payload = procurement_payload(workspace_id="ws-procure", analysis_id=flat_id)
            nested_payload = procurement_payload(workspace_id="ws-procure", analysis_id=nested_id)

            self.assertEqual(flat_payload["analysis_id"], flat_id)
            self.assertEqual(nested_payload["analysis_id"], nested_id)
            self.assertIn("Flat Project", str(flat_payload.get("project_name") or ""))
            self.assertIn("Nested Project", str(nested_payload.get("project_name") or ""))
            self.assertEqual(flat_payload.get("bom_name"), "flat-bom")
            self.assertEqual(nested_payload.get("bom_name"), "nested-bom")
            self.assertEqual(flat_payload.get("revision"), "F1")
            self.assertEqual(nested_payload.get("revision"), "N1")

            flat_mpns = {str(row.get("mpn") or "") for row in flat_payload.get("parts") or []}
            nested_mpns = {str(row.get("mpn") or "") for row in nested_payload.get("parts") or []}
            self.assertTrue(any("XC3S400" in mpn for mpn in flat_mpns))
            self.assertFalse(any("XC3S400" in mpn for mpn in nested_mpns))
            self.assertTrue(any(mpn in nested_mpns for mpn in ("PROD-TOP", "STM32F103")))
            self.assertFalse(any(mpn in flat_mpns for mpn in ("PROD-TOP", "PSU-ASM")))
            # Shared catalog MPNs (e.g. LM358DR) may appear in both fixtures, but
            # payloads remain scoped to the selected analysis_id / BOM context.

            missing = procurement_payload(workspace_id="ws-procure", analysis_id="does-not-exist")
            self.assertFalse(missing.get("ok"))
            self.assertEqual(missing.get("mode"), "analysis-not-found")

    def test_procurement_page_honors_analysis_id_and_selector(self):
        src = WEB_PROCUREMENT.read_text(encoding="utf-8")
        self.assertIn('searchParams.get("analysis_id")', src)
        self.assertIn('aria-label="Sourcing BOM context"', src)
        self.assertIn('data-testid="procurement-context"', src)
        self.assertIn("Select a saved analysis", src)
        self.assertIn("listReports", src)


class ReplacementProviderOutcomeTests(unittest.TestCase):
    def test_replacement_page_renders_provider_outcomes(self):
        src = WEB_REPLACEMENT.read_text(encoding="utf-8")
        self.assertIn('data-testid="replacement-provider-status"', src)
        self.assertIn("Not configured", src)
        self.assertIn("Timed out", src)
        self.assertIn("Returned", src)
        self.assertIn("providerOutcomeLabel", src)


class ExactMpnDisplayTests(unittest.TestCase):
    def test_parent_mpn_keeps_bom_hyphens_for_display(self):
        fields = attach_hierarchy_fields({"parent_mpn": "PROD-TOP", "line_type": "part"})
        self.assertEqual(fields["Parent MPN"], "PROD-TOP")
        self.assertEqual(fields["parent_mpn_display"], "PROD-TOP")
        self.assertEqual(fields["parent_mpn"], "PRODTOP")

    def test_synthetic_analyze_prefers_raw_mpn_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            reset_store_for_tests(Path(tmp) / "store.json")
            csv_bytes = b"MPN,Quantity,parent_mpn,line_type\nPROD-TOP,1,,assembly\nPSU-ASM,2,PROD-TOP,assembly\n"
            report = analyze_upload(
                filename="hyphen.csv",
                payload=csv_bytes,
                workspace_id="ws-mpn",
                project_name="Hyphen Project",
                bom_name="hyphen-bom",
            )
            saved = get_report(report["id"], workspace_id="ws-mpn")
            self.assertIsNotNone(saved)
            by_mpn = {
                str(row.get("MPN") or row.get("mpn") or ""): row
                for row in (saved or {}).get("parts") or []
            }
            self.assertIn("PROD-TOP", by_mpn)
            self.assertIn("PSU-ASM", by_mpn)
            child = by_mpn["PSU-ASM"]
            self.assertEqual(child.get("Parent MPN") or child.get("parent_mpn_display"), "PROD-TOP")


if __name__ == "__main__":
    unittest.main()
