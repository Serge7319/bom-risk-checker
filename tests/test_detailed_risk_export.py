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
    detailed_risk_csv_bytes,
    detailed_risk_excel_bytes,
)


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

    assert workbook.sheetnames == ["Summary", "Component Details", "High Risk Parts"]
    summary = workbook["Summary"]
    assert summary["A1"].value == "Cadivor BOM Risk Report"
    assert summary["A4"].value == "Project / BOM"
    assert summary["B4"].value == "Flight Controller Rev B"
    assert summary["B5"].value == "flight-controller.csv"
    metrics = {row[0]: row[1] for row in summary.iter_rows(min_row=10, max_row=30, values_only=True)}
    assert metrics["Total components"] == 2
    assert metrics["Parts with matched supplier evidence"] == 2
    assert metrics["Risk assessed"] == 2
    assert metrics["Risk coverage"] == "100%"
    assert "Risk ratings are recorded for all 2 parts" in summary["A7"].value
    assert metrics["High risk"] == 1
    assert metrics["Low risk"] == 1
    assert metrics["Stock not reported"] == 1
    assert metrics["Stock coverage incomplete"] == 1
    assert metrics["Stock coverage unavailable"] == 0

    details = workbook["Component Details"]
    headers = [cell.value for cell in details[1]]
    assert "Evidence source" in headers
    assert "Lifecycle evidence" in headers
    assert "Supplier coverage" in headers
    assert not {"id", "user_id", "analysis_id", "workspace_id"}.intersection(headers)
    first = dict(zip(headers, [cell.value for cell in details[2]]))
    second = dict(zip(headers, [cell.value for cell in details[3]]))
    assert first["Stock"] == "Not reported"
    assert first["Description"] == "Dual operational amplifier"
    assert first["Evidence source"] == "—"
    assert first["Recorded supplier"] == "Mouser"
    assert first["Stock coverage"] == "Incomplete"
    assert "No stock available" not in first["Why"]
    assert "source-backed stock evidence was not saved" in first["Why"]
    assert "Mouser: Obsolete" in first["Lifecycle evidence"]
    assert second["Stock"] == 0
    assert second["Evidence source"] == "DigiKey"
    why_cell = details.cell(3, headers.index("Why") + 1)
    assert why_cell.data_type == "s"
    assert why_cell.value.startswith("'=HYPERLINK")
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
    assert rows[1]["Stock"] == "0"
    assert rows[1]["Evidence source"] == "DigiKey"
    assert rows[1]["Why"].startswith("'=")


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
                            "risk_score": None,
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
            for row in summary.iter_rows(min_row=10, max_row=30, values_only=True)
            if row[0]
        }
        self.assertIn("0 of 1 parts", summary["A7"].value)
        self.assertIn("not evidence of low risk", summary["A7"].value)
        self.assertEqual(metrics["Parts with matched supplier evidence"], 0)
        self.assertEqual(metrics["Risk assessed"], 0)
        self.assertEqual(metrics["Risk coverage"], "0%")
        self.assertIn("1 of 1 part(s) were not assessed", workbook["High Risk Parts"]["A2"].value)
        self.assertIn("not proof of low risk", workbook["High Risk Parts"]["A2"].value)

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

    def test_detailed_risk_page_delivers_the_customer_exports(self):
        from src.ui import ei_bom_report

        downloads = []
        fake_streamlit = types.ModuleType("streamlit")
        fake_streamlit.session_state = {"cadivor_show_detailed_risk": True}
        fake_streamlit.markdown = lambda *_args, **_kwargs: None
        fake_streamlit.container = lambda **_kwargs: nullcontext()
        fake_streamlit.button = lambda *_args, **_kwargs: False
        fake_streamlit.columns = lambda count: [nullcontext() for _ in range(count)]
        fake_streamlit.download_button = lambda label, **kwargs: downloads.append((label, kwargs))

        with patch.dict(sys.modules, {"streamlit": fake_streamlit}), patch.object(
            ei_bom_report, "render_detailed_risk_rows"
        ):
            ei_bom_report.render_engineering_intelligence_report(
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
        self.assertEqual(workbook.sheetnames, ["Summary", "Component Details", "High Risk Parts"])
        self.assertEqual(downloads[1][1]["file_name"], "cadivor-detailed-risk-report.csv")
        self.assertTrue(downloads[1][1]["data"].startswith(b"\xef\xbb\xbf"))

