"""Evidence provenance across report, procurement, portfolio, and exports."""
from __future__ import annotations

import io
import unittest
import zipfile

from openpyxl import load_workbook

from unittest.mock import patch

from apps.api.evidence_contract import (
    annotate_report_parts,
    classify_part_evidence,
    evidence_mode_and_gap,
)
from apps.api.migration_tools import detailed_risk_payload
from apps.api.report_exports import build_csv, build_pdf, build_xlsx
from src.portfolio_intelligence import build_portfolio_intelligence
from src.procurement_advisor import build_procurement_advisor


class FieldProvenanceTests(unittest.TestCase):
    def test_live_identity_does_not_make_synthetic_price_appear_live(self):
        evidence = classify_part_evidence(
            {
                "MPN": "LIVE-SYN-PRICE",
                "manufacturer_part_number": "LIVE-SYN-PRICE",
                "Manufacturer": "Acme",
                "supplier_data_verified": True,
                "evidence_source": "live-authorized-supplier",
                "source": "DigiKey",
                "product_url": "https://www.digikey.com/product/LIVE-SYN-PRICE",
                "retrieved_at": "2026-11-01T12:00:00Z",
                "Lifecycle": "Active",
                "Unit Price": 0.42,
                "price_source": "synthetic-preview",
                "stock": 1000,
            }
        )
        self.assertEqual(evidence["evidence_class"], "live-authorized-supplier")
        fields = evidence["fields"]
        self.assertEqual(fields["identity"]["evidence_class"], "live-authorized-supplier")
        self.assertEqual(fields["price"]["evidence_class"], "synthetic-preview")
        self.assertEqual(fields["price"]["price_type"], "synthetic-estimate")
        self.assertIn("synthetic", (fields["price"].get("gap") or "").casefold())

    def test_live_offer_price_keeps_distinct_retrieval_and_type(self):
        evidence = classify_part_evidence(
            {
                "MPN": "LIVE-PRICE",
                "manufacturer_part_number": "LIVE-PRICE",
                "Manufacturer": "Acme",
                "supplier_data_verified": True,
                "evidence_source": "live-authorized-supplier",
                "source": "DigiKey",
                "product_url": "https://www.digikey.com/product/LIVE-PRICE",
                "retrieved_at": "2026-11-01T12:00:00Z",
                "Unit Price": 0.12,
                "supplier_offers": [
                    {
                        "supplier": "DigiKey",
                        "unit_price": 0.12,
                        "currency": "USD",
                        "price_break_quantity": 100,
                        "retrieved_at": "2026-11-01T12:05:00Z",
                    }
                ],
            }
        )
        price = evidence["fields"]["price"]
        self.assertEqual(price["evidence_class"], "live-authorized-supplier")
        self.assertEqual(price["price_type"], "quantity-break")
        self.assertEqual(price["retrieved_at"], "2026-11-01T12:05:00Z")

    def test_annotate_summary_counts_price_classes_separately(self):
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
                        "Unit Price": 1.0,
                        "price_source": "synthetic-preview",
                    },
                    {
                        "MPN": "MISS-1",
                        "manufacturer_part_number": "MISS-1",
                        "evidence_class": "missing",
                        "evidence_source": "missing",
                    },
                ],
            }
        )
        summary = report["evidence_summary"]
        self.assertEqual(summary["live_count"], 1)
        self.assertEqual(summary["synthetic_price_count"], 1)
        self.assertEqual(summary["missing_price_count"], 1)


class DetailedRiskBannerTests(unittest.TestCase):
    def test_mixed_row_evidence_does_not_force_synthetic_banner(self):
        mode, gap = evidence_mode_and_gap(
            live_count=1,
            synthetic_count=2,
            missing_count=0,
            configured_sources=1,
            analysis_mode="synthetic-preview",
        )
        self.assertEqual(mode, "mixed-evidence")
        self.assertIn("varies", (gap or "").casefold())

        report = {
            "id": "nested-mixed",
            "filename": "nested.csv",
            "mode": "synthetic-preview",
            "health_score": "Not scored",
            "parts": [
                {
                    "MPN": "LIVE-1",
                    "manufacturer_part_number": "LIVE-1",
                    "Manufacturer": "Acme",
                    "supplier_data_verified": True,
                    "evidence_source": "live-authorized-supplier",
                    "source": "DigiKey",
                    "product_url": "https://www.digikey.com/product/LIVE-1",
                    "retrieved_at": "2026-11-01T12:00:00Z",
                    "Risk Level": "Medium",
                    "Risk Score": 40,
                    "Unit Price": 0.5,
                    "price_source": "synthetic-preview",
                },
                {
                    "MPN": "SYN-1",
                    "manufacturer_part_number": "SYN-1",
                    "evidence_source": "synthetic-preview",
                    "source": "synthetic-preview",
                    "Risk Level": "Needs verification",
                },
            ],
        }
        with patch("apps.api.migration_tools._require_analysis", return_value=report):
            payload = detailed_risk_payload(workspace_id="ws-1", analysis_id="nested-mixed")
        self.assertEqual(payload["mode"], "mixed-evidence")
        self.assertEqual(payload["evidence_summary"]["live_count"], 1)
        self.assertNotIn("come from the synthetic analysis", str(payload.get("gap") or "").casefold())


class PortfolioAndProcurementCopyTests(unittest.TestCase):
    def test_project_health_preserves_not_scored(self):
        intelligence = build_portfolio_intelligence(
            [
                {
                    "id": "a1",
                    "project_name": "Demo",
                    "filename": "demo.csv",
                    "health_score": "Not scored",
                    "high_risk_count": 2,
                    "total_parts": 10,
                },
                {
                    "id": "a2",
                    "project_name": "Live",
                    "filename": "live.csv",
                    "health_score": 88,
                    "high_risk_count": 0,
                    "total_parts": 4,
                },
            ],
            [],
            [],
        )
        health_values = [row["Health"] for row in intelligence["project_health"]]
        self.assertIn("Not scored", health_values)
        self.assertNotIn(0, health_values)

    def test_unmatched_parts_recommend_authorized_source_check(self):
        advisor = build_procurement_advisor(
            analyses=[{"id": "a1"}],
            parts=[
                {
                    "mpn": "UNKNOWN-1",
                    "MPN": "UNKNOWN-1",
                    "quantity": 10,
                    "supplier_data_verified": False,
                }
            ],
        )
        recommendations = [row["Recommendation"] for row in advisor["recommendations"]]
        self.assertTrue(recommendations)
        self.assertIn("Check an authorized source", recommendations)
        self.assertNotIn("Complete sourcing data", recommendations)


class ExportProvenanceTests(unittest.TestCase):
    def test_exports_include_assembly_rollup_and_field_provenance(self):
        report = annotate_report_parts(
            {
                "project_name": "Nested Demo",
                "bom_name": "nested.csv",
                "mode": "legacy-supplier-engine",
                "health_score": "Not scored",
                "hierarchy": {
                    "has_hierarchy": True,
                    "assemblies": [
                        {
                            "mpn": "ASM-1",
                            "description": "Power assembly",
                            "parent_mpn": None,
                            "line_type": "assembly",
                            "quantity_per_parent": 1,
                            "effective_quantity": 1,
                            "rolled_risk_level": "High",
                            "leaf_count": 2,
                            "high_risk_leaves": 1,
                            "medium_risk_leaves": 0,
                            "needs_verification_leaves": 1,
                            "contributors": [
                                {
                                    "mpn": "LIVE-1",
                                    "risk_level": "High",
                                    "evidence_source": "live-authorized-supplier",
                                }
                            ],
                        }
                    ],
                },
                "parts": [
                    {
                        "MPN": "LIVE-1",
                        "manufacturer_part_number": "LIVE-1",
                        "Manufacturer": "Acme",
                        "supplier_data_verified": True,
                        "evidence_source": "live-authorized-supplier",
                        "source": "DigiKey",
                        "product_url": "https://www.digikey.com/product/LIVE-1",
                        "retrieved_at": "2026-11-01T12:00:00Z",
                        "Unit Price": 0.5,
                        "price_source": "synthetic-preview",
                        "Risk Level": "High",
                        "Risk Score": 70,
                    }
                ],
            }
        )
        csv_text = build_csv(report).decode("utf-8-sig")
        self.assertIn("Price Source", csv_text)
        self.assertIn("Price Type", csv_text)
        self.assertIn("Identity Source", csv_text)
        self.assertIn("synthetic-preview", csv_text)

        xlsx = build_xlsx(report)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(xlsx)))
        workbook = load_workbook(io.BytesIO(xlsx), data_only=False)
        self.assertIn("Assemblies", workbook.sheetnames)
        assemblies = workbook["Assemblies"]
        assembly_header = [cell.value for cell in next(assemblies.iter_rows(min_row=1, max_row=1))]
        self.assertIn("Rolled Risk", assembly_header)
        self.assertIn("Contributor Evidence", assembly_header)
        assembly_values = " ".join(
            str(cell.value or "") for row in assemblies.iter_rows(min_row=2, max_row=3) for cell in row
        )
        self.assertIn("ASM-1", assembly_values)
        self.assertIn("live-authorized-supplier", assembly_values)

        summary_values = " ".join(
            str(cell.value or "") for row in workbook["Summary"].iter_rows(max_row=20) for cell in row
        )
        self.assertIn("Not scored", summary_values)

        pdf = build_pdf(report)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 500)


if __name__ == "__main__":
    unittest.main()
