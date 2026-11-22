from __future__ import annotations

import csv
from io import BytesIO, StringIO
from contextlib import nullcontext
import sys
import types
import unittest
from unittest.mock import patch

from openpyxl import load_workbook

from src.ui.detailed_risk_export import (
    CSV_COLUMNS,
    component_rows,
    detailed_risk_csv_bytes,
    detailed_risk_excel_bytes,
    report_exposure_summary,
)
from tests.evidence_fixtures import live_supplier_part, retrieved_now


PARTS = [
    {
        "id": 927,
        "user_id": "private-user-id",
        "analysis_id": "private-analysis-id",
        "workspace_id": "private-workspace-id",
        "mpn": "LM358N",
        "description": "<p>Dual operational amplifier</p>",
        "manufacturer": "onsemi",
        "quantity": 6,
        "lifecycle_status": "Obsolete",
        "stock_available": 0,
        "stock_data_sources": [],
        "stock_data_complete": False,
        "supplier_count": 2,
        "supplier_coverage": "DigiKey and Mouser checked; count evidence incomplete",
        "primary_supplier": "Mouser",
        "risk_score": 100,
        "risk_level": "High",
        "risk_reasons": ["Saved lifecycle status is obsolete", "No stock available"],
        "lifecycle_evidence": [{"source": "Mouser", "status": "Obsolete", "retrieved_at": "2026-10-11"}],
        "lifecycle_conflict": False,
        "alternate_search_status": "Search incomplete: DigiKey unavailable",
        "unit_price": 0,
    },
    {
        "id": 928,
        "user_id": "private-user-id",
        "analysis_id": "private-analysis-id",
        "workspace_id": "private-workspace-id",
        "mpn": "C0603C104K5RACTU",
        "manufacturer": "KEMET",
        "quantity": 10,
        "lifecycle_status": "Active",
        "stock_available": 0,
        "stock_data_sources": [{"supplier": "DigiKey"}],
        "stock_data_complete": True,
        "lead_time_weeks": 8,
        "lead_time_source": "Mouser",
        "supplier_count": 3,
        "risk_score": 20,
        "risk_level": "Low",
        "risk_reasons": "=HYPERLINK(\"https://example.test\",\"Open\")",
        "lifecycle_evidence": [],
        "lifecycle_conflict": False,
        "alternate_search_status": "Search completed",
        "unit_price": 0.12,
    },
]


def _check_excel_export_has_summary_details_and_high_risk_views_without_private_ids():
    data = detailed_risk_excel_bytes(
        PARTS,
        bom_name="Flight Controller Rev B",
        source_filename="flight-controller.csv",
        analyzed_on="2026-10-11T12:33:31.741757+00:00",
    )
    workbook = load_workbook(BytesIO(data), data_only=False)

    assert workbook.sheetnames == ["Summary", "Component Details", "High Risk Parts", "Alternative Candidates"]
    summary = workbook["Summary"]
    assert summary["A1"].value == "Cadivor BOM Risk Report"
    assert summary["A4"].value == "Project / BOM"
    assert summary["B4"].value == "Flight Controller Rev B"
    assert summary["B5"].value == "flight-controller.csv"
    metrics = {row[0]: row[1] for row in summary.iter_rows(min_row=10, max_row=50, values_only=True)}
    assert metrics["Total components"] == 2
    assert metrics["Exact current supplier identity matches"] == 0
    assert metrics["Risk assessed"] == 0
    assert metrics["Risk coverage"] == "0%"
    assert "Risk was assessed for 0 of 2 parts" in summary["A7"].value
    assert metrics["High risk"] == 0
    assert metrics["Low risk"] == 0
    assert metrics["Stock not reported"] == 2
    assert metrics["Stock coverage incomplete"] == 0
    assert metrics["Stock coverage unavailable"] == 2

    details = workbook["Component Details"]
    headers = [cell.value for cell in details[1]]
    assert "Evidence source" in headers
    assert "Lifecycle evidence" in headers
    assert "Supplier coverage" in headers
    assert "Supplier product URL" in headers
    assert "Datasheet URL" in headers
    assert "Candidate MPNs" in headers
    assert not {"id", "user_id", "analysis_id", "workspace_id"}.intersection(headers)
    first = dict(zip(headers, [cell.value for cell in details[2]]))
    second = dict(zip(headers, [cell.value for cell in details[3]]))
    assert first["Stock"] == "Not reported"
    assert first["Description"] == "Dual operational amplifier"
    assert first["Evidence source"] == "—"
    assert first["Recorded supplier"] == "—"
    assert first["Stock coverage"] == "Unavailable"
    assert "No stock available" not in first["Why"]
    assert "lacks verified exact-part supplier provenance" in first["Why"]
    assert "Mouser: Obsolete" in first["Lifecycle evidence"]
    assert second["Stock"] == "Not reported"
    assert second["Evidence source"] == "—"
    why_cell = details.cell(3, headers.index("Why") + 1)
    assert why_cell.data_type == "s"
    assert not why_cell.value.startswith("=")
    assert "HYPERLINK" not in why_cell.value
    assert workbook["High Risk Parts"].max_row == 2

    exported_values = " ".join(str(cell.value) for sheet in workbook.worksheets for row in sheet for cell in row)
    for private_value in ("private-user-id", "private-analysis-id", "private-workspace-id"):
        assert private_value not in exported_values


def _check_csv_export_matches_stress_free_audit_columns_and_marks_unknown_stock():
    payload = detailed_risk_csv_bytes(PARTS)
    assert payload.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))
    assert tuple(rows[0].keys()) == CSV_COLUMNS
    assert rows[0]["MPN"] == "LM358N"
    assert rows[0]["Stock"] == "Not reported"
    assert rows[0]["Evidence source"] == "—"
    assert rows[1]["Stock"] == "Not reported"
    assert rows[1]["Evidence source"] == "—"
    assert not rows[1]["Why"].startswith("=")
    assert "HYPERLINK" not in rows[1]["Why"]


class DetailedRiskExportTests(unittest.TestCase):
    def test_excel_export_has_customer_facing_summary_and_details(self):
        _check_excel_export_has_summary_details_and_high_risk_views_without_private_ids()

    def test_csv_export_matches_stress_free_audit_columns(self):
        _check_csv_export_matches_stress_free_audit_columns_and_marks_unknown_stock()

    def test_unassessed_parts_are_explained_in_summary_and_empty_high_risk_sheet(self):
        workbook = load_workbook(
            BytesIO(
                detailed_risk_excel_bytes(
                    [
                        {
                            "mpn": "CON-USB",
                            "risk_level": "Needs verification",
                            "risk_score": 0,
                            "supplier_coverage": "No configured supplier returned a matching part record.",
                        }
                    ],
                    bom_name="Connector test",
                )
            ),
            data_only=True,
        )

        summary = workbook["Summary"]
        metrics = {
            row[0]: row[1]
            for row in summary.iter_rows(min_row=10, max_row=50, values_only=True)
            if row[0]
        }
        self.assertIn("0 of 1 parts", summary["A7"].value)
        self.assertIn("not evidence of low risk", summary["A7"].value)
        self.assertIn("These counts can refer to the same part", summary["A7"].value)
        self.assertNotIn("1 were not risk-rated and 1", summary["A7"].value)
        self.assertEqual(metrics["Exact current supplier identity matches"], 0)
        self.assertEqual(metrics["Risk assessed"], 0)
        self.assertEqual(metrics["Risk coverage"], "0%")
        detail = workbook["Component Details"]
        detail_headers = {cell.value: cell.column_letter for cell in detail[1]}
        self.assertEqual(detail[f'{detail_headers["Risk"]}2'].value, "Not assessed")
        self.assertEqual(detail[f'{detail_headers["Risk score"]}2'].value, "Not assessed")
        self.assertIn(
            "Verify the manufacturer part number and rerun",
            detail[f'{detail_headers["Why"]}2'].value,
        )
        self.assertEqual(detail[f'{detail_headers["Risk"]}2'].fill.fgColor.rgb[-6:], "E2E8F0")
        self.assertIn("1 of 1 part(s) were not assessed", workbook["High Risk Parts"]["A2"].value)
        self.assertIn("not proof of low risk", workbook["High Risk Parts"]["A2"].value)

    def test_zero_score_without_supplier_match_is_not_a_low_risk_rating(self):
        row = component_rows(
            [{
                "mpn": "CON-USB",
                "risk_level": "Needs verification",
                "risk_score": 0,
                "supplier_count": 0,
                "supplier_coverage": "No configured supplier returned a matching part record.",
            }]
        )[0]
        self.assertEqual(row["Risk"], "Not assessed")
        self.assertEqual(row["Risk score"], "Not assessed")
        self.assertIn("Supplier concentration is not assessed", row["Why"])

    def test_legacy_kicad_fields_are_cleaned_and_supplier_coverage_and_links_survive(self):
        timestamp = retrieved_now()
        row = component_rows([{
            "mpn": "BoardText(value=2N3904, position=Vector2(27000000, 61000000), layer=BL_F_Fab)",
            "manufacturer": "BoardText(value=onsemi, position=Vector2(27000000, 61000000), layer=BL_F_Fab)",
            "manufacturer_part_number": "2N3904",
            "source": "Mouser",
            "identity_source": "live-authorized-supplier",
            "supplier_data_verified": True,
            "provider_status": "AVAILABLE",
            "retrieved_at": timestamp,
            "product_url": "https://www.mouser.com/ProductDetail/2N3904",
            "Lifecycle": "Active",
            "Stock": 120,
            "stock_data_complete": True,
            "stock_data_sources": ["Mouser"],
            "risk_level": "Needs verification",
            "risk_score": 0,
            "supplier_count": 1,
            "Supplier Sources Checked": "2/2 supplier queries responded; 1 exact match, 1 no match, 0 unavailable",
            "Supplier Query Details": [
                {"source": "Mouser", "status": "AVAILABLE", "label": "Exact MPN and manufacturer match"},
                {"source": "DigiKey", "status": "PART_NOT_FOUND", "label": "No exact MPN match returned"},
            ],
            "stock_evidence": [{
                "source": "Mouser",
                "mpn": "2N3904",
                "stock": 120,
                "product_url": "https://www.mouser.com/ProductDetail/2N3904",
                "retrieved_at": timestamp,
            }],
            "lifecycle_evidence": [{
                "source": "Mouser",
                "mpn": "2N3904",
                "status": "Active",
                "product_url": "https://www.mouser.com/ProductDetail/2N3904",
                "retrieved_at": timestamp,
            }],
        }])[0]

        self.assertEqual(row["MPN"], "2N3904")
        self.assertEqual(row["Manufacturer"], "onsemi")
        self.assertIn("2/2 supplier queries responded", row["supplier_sources_checked"])
        self.assertEqual(len(row["supplier_query_details"]), 2)
        self.assertEqual(row["supplier_links"][0]["source"], "Mouser")
        self.assertEqual(row["supplier_links"][0]["url"], "https://www.mouser.com/ProductDetail/2N3904")
        self.assertEqual(row["Supplier product URL"], "https://www.mouser.com/ProductDetail/2N3904")
        self.assertEqual(row["Lifecycle"], "Active")
        self.assertEqual(row["Stock"], 120)

    def test_related_legacy_catalog_lead_is_explained_without_rating_original(self):
        row = component_rows([{
            "mpn": "PCF8574P",
            "risk_level": "Needs verification",
            "risk_score": 0,
            "supplier_count": 0,
            "alternate_search_status": (
                "No exact supplier match. Legacy route Philips Semiconductors → NXP "
                "found related catalog lead(s) for review only: PCF8574P,112 (DigiKey). "
                "orderable package variant; verify the package and ordering suffix; "
                "no candidate stock, price, or lifecycle is attributed to PCF8574P.; "
                "Candidates returned"
            ),
        }])[0]

        self.assertEqual(row["Risk"], "Not assessed")
        self.assertIn("PCF8574P,112 (DigiKey)", row["Why"])
        self.assertIn("the part remains unassessed", row["Why"].casefold())

    def test_export_does_not_link_a_source_url_on_another_distributor_domain(self):
        timestamp = retrieved_now()
        part = live_supplier_part(
            "LM317DCYR", lifecycle="Active", stock=20, quantity=2,
            unit_price=None, sources=("DigiKey",), retrieved_at=timestamp,
        )
        part["product_url"] = "https://www.mouser.com/ProductDetail/LM317DCYR"
        rows = component_rows([part])
        self.assertEqual(rows[0]["Supplier product URL"], "—")
        self.assertEqual(rows[0]["supplier_links"], [])

    def test_cost_exposure_and_longest_lead_time_use_recorded_evidence_only(self):
        timestamp = retrieved_now()
        parts = [
            live_supplier_part(
                "LM358N", lifecycle="Obsolete", stock=0, quantity=10,
                unit_price=2.0, sources=("Mouser",), retrieved_at=timestamp,
            ),
            live_supplier_part(
                "1N4148", lifecycle="Active", stock=2000, quantity=50,
                unit_price=0.5, sources=("DigiKey",), retrieved_at=timestamp,
            ),
            live_supplier_part(
                "UNPRICED-CURRENCY", lifecycle="Active", stock=100, quantity=4,
                unit_price=None, sources=("Newark",), retrieved_at=timestamp,
            ),
        ]
        parts[0]["description"] = "Recommended Alt LM358DR2G"
        parts[1]["supplier_offers"][0]["currency"] = "EUR"
        parts[1]["unit_price_currency"] = "EUR"
        for row, source, lead in zip(parts[:2], ("Mouser", "DigiKey"), (3, 62)):
            row.update({
                "lead_time_weeks": lead,
                "lead_time_source": source,
                "lead_time_evidence": [{
                    "source": source,
                    "mpn": row["MPN"],
                    "weeks": lead,
                    "product_url": row["product_url"],
                    "retrieved_at": timestamp,
                }],
            })
        # A saved amount without a source quote, currency, quantity break, and
        # retrieval date remains visible only as an unverified record.
        parts[2]["unit_price"] = 1.25
        parts[2]["Unit Price"] = 1.25
        rows = component_rows(parts)

        self.assertEqual(rows[0]["Extended cost"], 20)
        self.assertEqual(rows[0]["Unit price currency"], "USD")
        self.assertEqual(rows[0]["Description-mentioned alternatives"], "LM358DR2G")
        self.assertEqual(rows[2]["Extended cost"], "—")
        self.assertEqual(rows[2]["Unit price currency"], "Not reported")

        workbook = load_workbook(
            BytesIO(detailed_risk_excel_bytes(parts, bom_name="Exposure test")),
            data_only=True,
        )
        metrics = {
            row[0]: row[1]
            for row in workbook["Summary"].iter_rows(min_row=10, max_row=50, values_only=True)
            if row[0]
        }
        self.assertEqual(metrics["Extended BOM amount by recorded currency"], "EUR 25.00; USD 20.00")
        self.assertEqual(
            metrics["Priced high-risk / lifecycle extended cost by currency"],
            "USD 20.00",
        )
        self.assertEqual(metrics["High-risk / lifecycle rows without extended cost"], 0)
        self.assertEqual(metrics["Priced high-risk rows missing currency"], 0)
        self.assertEqual(metrics["Longest reported part lead time"], "62 weeks — 1N4148 (DigiKey)")
        self.assertEqual(metrics["Components with lead-time data"], 2)
        summary_text = " ".join(str(cell.value) for row in workbook["Summary"] for cell in row if cell.value)
        self.assertIn("not a forecast of project delay", summary_text)
        self.assertIn("not a confirmed or approved cross", summary_text)
        self.assertIn("not total exposure", summary_text)

    def test_candidate_and_source_evidence_are_saved_in_the_export_without_certifying_fit(self):
        timestamp = retrieved_now()
        parts = [{
            "mpn": "LM317DCYR",
            "description": "Adjustable voltage regulator",
            "manufacturer": "Texas Instruments",
            "manufacturer_part_number": "LM317DCYR",
            "source": "DigiKey",
            "identity_source": "live-authorized-supplier",
            "supplier_data_verified": True,
            "provider_status": "AVAILABLE",
            "retrieved_at": timestamp,
            "lifecycle_status": "Active",
            "product_url": "https://www.digikey.com/en/products/detail/ti/LM317DCYR/123",
            "datasheet_url": "https://www.ti.com/lit/ds/symlink/lm317.pdf",
            "sourcing_updated_at": timestamp,
            "alternate_search_status": "Candidates returned",
            "alternate_candidates": [{
                "Alternative Part": "LM317BS-TR",
                "Manufacturer": "STMicroelectronics",
                "Supplier": "DigiKey",
                "Classification": "Supplier-listed similar",
                "Evidence Type": "Catalog search",
                "package": "SOT-223",
                "pin_count": 3,
                "Lifecycle": "Active",
                "Product URL": "https://www.digikey.com/en/products/detail/stmicroelectronics/LM317BS-TR/456",
                "Datasheet URL": "https://www.st.com/resource/en/datasheet/lm317bs.pdf",
                "Retrieved At": timestamp,
            }],
        }]

        rows = component_rows(parts)
        self.assertEqual(rows[0]["Candidate MPNs"], "LM317BS-TR")
        self.assertEqual(rows[0]["Supplier product URL"], "https://www.digikey.com/en/products/detail/ti/LM317DCYR/123")
        self.assertEqual(rows[0]["Datasheet URL"], "https://www.ti.com/lit/ds/symlink/lm317.pdf")

        workbook = load_workbook(BytesIO(detailed_risk_excel_bytes(parts, bom_name="Regulator")))
        self.assertEqual(workbook.sheetnames[-1], "Alternative Candidates")
        sheet = workbook["Alternative Candidates"]
        headers = [cell.value for cell in sheet[4]]
        candidate = dict(zip(headers, [cell.value for cell in sheet[5]]))
        self.assertEqual(candidate["Source MPN"], "LM317DCYR")
        self.assertEqual(candidate["Candidate MPN"], "LM317BS-TR")
        self.assertEqual(candidate["Relationship label"], "Supplier-listed similar")
        self.assertIn("not established", candidate["Approval status"])
        self.assertEqual(sheet.cell(5, headers.index("Supplier product URL") + 1).hyperlink.target,
                         "https://www.digikey.com/en/products/detail/stmicroelectronics/LM317BS-TR/456")
        details_headers = [cell.value for cell in workbook["Component Details"][1]]
        supplier_url_column = details_headers.index("Supplier product URL") + 1
        self.assertEqual(
            workbook["Component Details"].cell(2, supplier_url_column).hyperlink.target,
            "https://www.digikey.com/en/products/detail/ti/LM317DCYR/123",
        )
        summary_text = " ".join(
            str(cell.value) for row in workbook["Summary"] for cell in row if cell.value
        )
        self.assertIn("26+ weeks +30", summary_text)
        self.assertIn("60–100 High", summary_text)
        workbook.close()

        csv_rows = list(csv.DictReader(StringIO(
            detailed_risk_csv_bytes(parts).decode("utf-8-sig")
        )))
        self.assertEqual(csv_rows[0]["Candidate MPNs"], "LM317BS-TR")
        self.assertEqual(csv_rows[0]["Risk score"], "Not assessed")
        self.assertEqual(csv_rows[0]["Datasheet URL"], "https://www.ti.com/lit/ds/symlink/lm317.pdf")

    def test_saved_unit_price_needs_fresh_matching_supplier_offer_for_financial_rollup(self):
        legacy_parts = [{
            "mpn": "BC547B",
            "quantity": 150,
            "unit_price": 0.13,
            "unit_price_currency": "USD",
            "primary_supplier": "DigiKey",
            "risk_level": "Low",
            "lifecycle_status": "Active",
        }]
        legacy_row = component_rows(legacy_parts)[0]
        self.assertEqual(legacy_row["Unit price currency"], "Not reported")
        self.assertEqual(legacy_row["Extended cost"], "—")

        parts = [live_supplier_part(
            "BC547B", quantity=150, unit_price=0.13, sources=("DigiKey",)
        )]
        rows = component_rows(parts)
        self.assertEqual(rows[0]["Unit price currency"], "USD")
        self.assertEqual(rows[0]["Extended cost"], 19.5)

        workbook = load_workbook(
            BytesIO(detailed_risk_excel_bytes(parts, bom_name="Currency rollup test")),
            data_only=True,
        )
        metrics = {
            row[0]: row[1]
            for row in workbook["Summary"].iter_rows(min_row=10, max_row=50, values_only=True)
            if row[0]
        }
        self.assertEqual(metrics["Extended BOM amount by recorded currency"], "USD 19.50")
        self.assertEqual(metrics["Priced components missing currency"], 0)

    def test_approved_alternatives_are_included_in_both_downloads(self):
        approval = {
            "original_part": "LM358N",
            "alternative_part": "LM358DR2G",
            "decision": "Approved",
            "project_name": "Flight Controller Rev B",
            "engineer_name": "Engineer",
            "engineering_note": "Reviewed against the datasheet",
        }
        excel = load_workbook(
            BytesIO(
                detailed_risk_excel_bytes(
                    PARTS,
                    bom_name="Flight Controller Rev B",
                    approved_alternatives=[approval],
                )
            ),
            data_only=True,
        )
        details = excel["Component Details"]
        headers = [cell.value for cell in details[1]]
        first = dict(zip(headers, [cell.value for cell in details[2]]))
        self.assertEqual(first["Approved alternatives"], "LM358DR2G")

        rows = list(
            csv.DictReader(
                StringIO(
                    detailed_risk_csv_bytes(PARTS, [approval]).decode("utf-8-sig")
                )
            )
        )
        self.assertEqual(rows[0]["Approved alternatives"], "LM358DR2G")

    def test_approved_alternative_updates_mitigation_and_open_cost_without_erasing_source_risk(self):
        parts = [live_supplier_part(
            "MC68HC11E1CFNE2",
            quantity=4,
            unit_price=3.5,
            lifecycle="Obsolete",
            stock=0,
        )]
        approval = {
            "original_part": "MC68HC11E1CFNE2",
            "alternative_part": "MC68HC11E1CFNE3",
            "decision": "Approved",
            "engineer_name": "Engineer",
            "project_name": "Controller",
        }

        row = component_rows(parts, [approval])[0]
        self.assertEqual(row["Risk"], "High")
        self.assertEqual(row["Risk score"], 100)
        self.assertEqual(row["Mitigation status"], "Approved alternative (BOM update pending)")
        self.assertEqual(row["Approved alternatives"], "MC68HC11E1CFNE3")

        exposure = report_exposure_summary([row])
        self.assertEqual(exposure["gross_high_risk_amount_by_currency"], "USD 14.00")
        self.assertEqual(exposure["approved_high_risk_amount_by_currency"], "USD 14.00")
        self.assertEqual(exposure["high_risk_amount_by_currency"], "Not available from recorded currency data")

        exported = list(csv.DictReader(StringIO(
            detailed_risk_csv_bytes(parts, [approval]).decode("utf-8-sig")
        )))[0]
        self.assertEqual(exported["Mitigation status"], "Approved alternative (BOM update pending)")
        self.assertEqual(exported["Approved alternatives"], "MC68HC11E1CFNE3")

        workbook = load_workbook(BytesIO(detailed_risk_excel_bytes(
            parts,
            bom_name="Controller",
            approved_alternatives=[approval],
        )), data_only=True)
        summary = {
            values[0]: values[1]
            for values in workbook["Summary"].iter_rows(min_row=10, max_row=60, values_only=True)
            if values[0]
        }
        details = workbook["Component Details"]
        headers = [cell.value for cell in details[1]]
        saved = dict(zip(headers, [cell.value for cell in details[2]]))
        self.assertEqual(summary["Priced high-risk / lifecycle extended cost by currency"], "Not available from recorded currency data")
        self.assertEqual(summary["Gross priced high-risk / lifecycle extended cost by currency"], "USD 14.00")
        self.assertEqual(saved["Risk"], "High")
        self.assertEqual(saved["Mitigation status"], "Approved alternative (BOM update pending)")
        self.assertEqual(saved["Approved alternatives"], "MC68HC11E1CFNE3")

    def test_detailed_risk_page_delivers_the_customer_exports(self):
        from src.ui import ei_bom_report

        downloads = []
        fake_streamlit = types.ModuleType("streamlit")
        fake_streamlit.session_state = {"cadivor_show_detailed_risk": True}
        fake_streamlit.markdown = lambda *_args, **_kwargs: None
        fake_streamlit.html = lambda *_args, **_kwargs: None
        fake_streamlit.container = lambda **_kwargs: nullcontext()
        fake_streamlit.button = lambda *_args, **_kwargs: False
        fake_streamlit.columns = lambda count: [nullcontext() for _ in range(count)]
        fake_streamlit.download_button = lambda label, **kwargs: downloads.append((label, kwargs))

        with patch.dict(sys.modules, {"streamlit": fake_streamlit}), patch.object(
            ei_bom_report, "render_detailed_risk_rows"
        ):
            renderer = getattr(
                ei_bom_report.render_engineering_intelligence_report,
                "__wrapped__",
                ei_bom_report.render_engineering_intelligence_report,
            )
            renderer(
                analysis={
                    "id": "private-analysis-id",
                    "project_name": "Flight Controller Rev B",
                    "filename": "flight-controller.csv",
                    "created_at": "2026-10-11T12:33:00+00:00",
                },
                parts=PARTS,
                alternatives=[],
                health_score=72,
            )

        self.assertEqual([item[0] for item in downloads], ["Download Excel Report", "Download CSV Audit"])
        self.assertEqual(downloads[0][1]["file_name"], "cadivor-detailed-risk-report.xlsx")
        workbook = load_workbook(BytesIO(downloads[0][1]["data"]), data_only=True)
        self.assertEqual(workbook.sheetnames, ["Summary", "Component Details", "High Risk Parts", "Alternative Candidates"])
        self.assertEqual(downloads[1][1]["file_name"], "cadivor-detailed-risk-report.csv")
        self.assertTrue(downloads[1][1]["data"].startswith(b"\xef\xbb\xbf"))

