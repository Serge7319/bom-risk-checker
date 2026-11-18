"""API tests for the workspace-scoped Next.js report downloads."""
from __future__ import annotations

import csv
import io
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest
from openpyxl import load_workbook
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.evidence_contract import annotate_report_parts
from apps.api.report_exports import (
    COMPONENT_COLUMNS,
    build_csv,
    build_pdf,
    build_report_export,
    build_xlsx,
    safe_download_stem,
)
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS, SMOKE_EMAIL, SMOKE_PASSWORD

ROOT = Path(__file__).resolve().parents[1]
CSV_FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    from apps.api import synthetic_analyze

    synthetic_analyze._REPORTS.clear()
    with TestClient(app) as test_client:
        yield test_client
    synthetic_analyze._REPORTS.clear()


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _create_report(client: TestClient, token: str) -> str:
    with CSV_FIXTURE.open("rb") as source:
        response = client.post(
            "/boms/analyze",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("motor controller rev C.csv", source, "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()["analysis_id"]


@pytest.mark.parametrize(
    ("file_format", "content_type"),
    [
        ("pdf", "application/pdf"),
        ("csv", "text/csv"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ],
)
def test_saved_report_exports_are_downloadable_and_workspace_scoped(
    client: TestClient, file_format: str, content_type: str
):
    token = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    analysis_id = _create_report(client, token)

    response = client.get(
        f"/reports/{analysis_id}/export/{file_format}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(content_type)
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "motor-controller-rev-C-risk-report" in response.headers["content-disposition"]

    if file_format == "pdf":
        assert response.content.startswith(b"%PDF-")
    elif file_format == "csv":
        text = response.content.decode("utf-8-sig")
        parsed = list(csv.DictReader(io.StringIO(text)))
        assert len(parsed) == 25
        assert {"MPN", "Risk Level", "Evidence Class", "Parent MPN"}.issubset(parsed[0])
        assert parsed[0]["Evidence Class"] == "synthetic-preview"
    else:
        assert zipfile.is_zipfile(io.BytesIO(response.content))

    other_token = _login(client, "sandbox-b@cadivor.test", "CadivorSandbox!b")
    denied = client.get(
        f"/reports/{analysis_id}/export/{file_format}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert denied.status_code == 404


def test_report_export_requires_auth_and_rejects_unknown_format(client: TestClient):
    token = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    analysis_id = _create_report(client, token)

    assert client.get(f"/reports/{analysis_id}/export/pdf").status_code == 401
    unsupported = client.get(
        f"/reports/{analysis_id}/export/docx",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unsupported.status_code == 400
    assert "PDF, Excel, or CSV" in unsupported.json()["detail"]


def test_exports_preserve_synthetic_label_and_neutralize_formula_cells():
    report = {
        "project_name": "Demo",
        "bom_name": "demo.csv",
        "mode": "synthetic-preview",
        "parts": [
            {
                "MPN": "=1+1",
                "Manufacturer": "Example",
                "Risk Level": "Low",
                "source": "synthetic-preview",
            }
        ],
    }
    csv_text = build_csv(report).decode("utf-8-sig")
    assert "'=1+1" in csv_text
    assert "synthetic-preview" in csv_text

    workbook_bytes, media_type, extension = build_report_export(report, "xlsx")
    assert media_type.startswith("application/vnd.openxmlformats-officedocument")
    assert extension == "xlsx"
    assert zipfile.is_zipfile(io.BytesIO(workbook_bytes))
    workbook = load_workbook(io.BytesIO(workbook_bytes), data_only=False)
    cell = workbook["Components"]["A2"]
    assert cell.data_type == "s"
    assert cell.value == "'=1+1"


def test_xlsx_keeps_quantities_risk_stock_and_price_numeric():
    report = {
        "project_name": "Numeric export",
        "bom_name": "numeric.csv",
        "mode": "live",
        "health_score": 81,
        "parts": [
            {
                "MPN": "R-1",
                "Manufacturer": "Example",
                "quantity_per_parent": 2,
                "effective_quantity": 6,
                "Risk Score": 25,
                "Stock": 1200,
                "Unit Price": 0.125,
                "Currency": "USD",
            }
        ],
    }
    workbook = load_workbook(io.BytesIO(build_xlsx(report)), data_only=False)
    components = workbook["Components"]
    columns = {cell.value: cell.column for cell in components[1]}
    expected = {
        "Quantity per Parent": 2,
        "Effective Quantity": 6,
        "Risk Score": 25,
        "Stock": 1200,
        "Unit Price": 0.125,
    }
    for field, value in expected.items():
        cell = components.cell(row=2, column=columns[field])
        assert cell.data_type == "n"
        assert cell.value == value
    assert components.column_dimensions["A"].width == 24
    assert components.column_dimensions["C"].width == 44

    summary = {row[0].value: row[1] for row in workbook["Summary"].iter_rows(min_row=4)}
    assert summary["Health score"].data_type == "n"
    assert summary["Health score"].value == 81
    assert summary["Total components"].data_type == "n"
    assert summary["Total components"].value == 1


def test_report_summaries_keep_unverified_parts_out_of_low_risk_counts():
    report = {
        "project_name": "Verification check",
        "bom_name": "verification.csv",
        "mode": "live",
        "total_parts": 2,
        "summary_message": "Supplier evidence is incomplete for one component.",
        "high_risk_count": 0,
        "medium_risk_count": 0,
        "low_risk_count": 1,
        "parts": [
            {"MPN": "PART-UNKNOWN", "Risk Level": "Needs verification", "Risk Score": 0},
            {"MPN": "PART-LOW", "Risk Level": "Low", "Risk Score": 18},
        ],
    }

    workbook = load_workbook(io.BytesIO(build_xlsx(report)), data_only=True)
    summary_text = " ".join(
        str(cell.value or "")
        for row in workbook["Summary"].iter_rows()
        for cell in row
    )
    summary_facts = {
        row[0].value: row[1].value
        for row in workbook["Summary"].iter_rows(min_row=4)
        if row[0].value
    }
    assert "Executive summary" in summary_text
    assert "Supplier evidence is incomplete" in summary_text
    assert summary_facts["Risk not assessed"] == 1
    assert summary_facts["Low risk"] == 1

    pdf_text, _ = _pdf_text(build_pdf(report))
    normalized = _normalized(pdf_text)
    assert _normalized("Executive summary") in normalized
    assert _normalized("Supplier evidence is incomplete") in normalized
    assert _normalized("1 needs verification") in normalized


def test_report_exports_reconcile_saved_counts_from_visible_rows():
    report = {
        "project_name": "Reconciliation check",
        "bom_name": "reconciliation.csv",
        "mode": "live",
        "total_parts": 2,
        "high_risk_count": 0,
        "medium_risk_count": 0,
        "low_risk_count": 2,
        "parts": [
            {"MPN": "PART-HIGH", "Risk Level": "High"},
            {"MPN": "PART-LOW", "Risk Level": "Low", "Risk Score": 16},
        ],
    }

    workbook = load_workbook(io.BytesIO(build_xlsx(report)), data_only=True)
    summary = {
        row[0].value: row[1].value
        for row in workbook["Summary"].iter_rows(min_row=4)
        if row[0].value
    }
    assert summary["Risk assessed"] == 2
    assert summary["Risk not assessed"] == 0
    assert summary["High risk"] == 1
    assert summary["Low risk"] == 1

    pdf_text, _ = _pdf_text(build_pdf(report))
    assert _normalized("High / medium / low: 1 / 0 / 1") in _normalized(pdf_text)


def test_exports_hide_opaque_record_references_from_names_and_summary():
    opaque_reference = "faf64399-Ofsd7-......"
    report = {
        "project_name": opaque_reference,
        "bom_name": f"controller {opaque_reference}.csv",
        "mode": "live",
        "health_status": opaque_reference,
        "summary_message": f"Review this saved analysis: {opaque_reference}",
        "parts": [
            {
                "MPN": "PART-1",
                "Risk Level": "Needs verification",
                "Risk Reasons": f"Review source record {opaque_reference}.",
            }
        ],
    }

    csv_text = build_csv(report).decode("utf-8-sig")
    workbook = load_workbook(io.BytesIO(build_xlsx(report)), data_only=True)
    workbook_text = " ".join(
        str(cell.value or "")
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
    )
    pdf_text = _normalized(_pdf_text(build_pdf(report))[0])

    assert opaque_reference not in csv_text
    assert opaque_reference not in workbook_text
    assert opaque_reference not in pdf_text
    assert "Engineering workspace" in workbook_text
    assert "controller record reference.csv" in workbook_text
    assert safe_download_stem({"bom_name": opaque_reference}) == "cadivor-report-risk-report"


# ---------------------------------------------------------------------------
# Acceptance D2 — PDF / Excel / CSV parity against the *saved* BOM
# ---------------------------------------------------------------------------
UTF8_BOM = b"\xef\xbb\xbf"
# Latin-1/WinAnsi + common engineering symbols that the PDF base-14 font can draw.
_MANUFACTURERS = (
    "Texas Instruments",
    "Würth Elektronik",
    "Murata Électronique",
    "STMicroelectronics",
    "Bourns, Inc.",
)
_DESCRIPTIONS = (
    "10 k\u03a9 \u00b11% 0603",
    "Op-amp \u00b5-power",
    'Cap, 100nF "X7R" \u00abAEC\u00bb',
    "Ferrite bead 600\u03a9 @100MHz",
    "Plain ASCII resistor",
)
_PART_COUNT = 60


def _parity_bom() -> tuple[bytes, dict[str, dict[str, object]]]:
    """UTF-8-with-BOM CSV with mapped headers, duplicates and a formula-looking MPN."""
    rows: list[tuple[str, str, str, int]] = []
    for index in range(_PART_COUNT):
        rows.append(
            (
                f"PN-{index:04d}-X",
                _MANUFACTURERS[index % len(_MANUFACTURERS)],
                _DESCRIPTIONS[index % len(_DESCRIPTIONS)],
                index + 1,
            )
        )
    rows.append(("=CMD|x", "Formula Corp", "formula-looking MPN", 1))
    # Exact duplicate lines must aggregate into ONE row with summed quantity.
    rows.append(("PN-0003-X", _MANUFACTURERS[3 % len(_MANUFACTURERS)], _DESCRIPTIONS[3 % len(_DESCRIPTIONS)], 7))
    rows.append(("PN-0059-X", _MANUFACTURERS[59 % len(_MANUFACTURERS)], _DESCRIPTIONS[59 % len(_DESCRIPTIONS)], 2))

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["Part Number", "Manufacturer", "Description", "Qty"])
    writer.writerows(rows)
    payload = UTF8_BOM + buffer.getvalue().encode("utf-8")

    expected: dict[str, dict[str, object]] = {}
    for mpn, manufacturer, description, quantity in rows:
        entry = expected.setdefault(
            mpn, {"manufacturer": manufacturer, "description": description, "qty": 0}
        )
        entry["qty"] = int(entry["qty"]) + quantity
    return payload, expected


def _upload_parity_bom(client: TestClient, token: str) -> tuple[str, dict[str, dict[str, object]]]:
    payload, expected = _parity_bom()
    response = client.post(
        "/boms/analyze",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("parity bom \u00e9.csv", payload, "text/csv")},
        data={"project_name": "Parity Project", "bom_name": "Parity BOM", "revision": "C"},
    )
    assert response.status_code == 200, response.text
    return response.json()["analysis_id"], expected


def _xlsx_rows(content: bytes, sheet: str) -> tuple[list[str], list[dict[str, object]]]:
    workbook = load_workbook(io.BytesIO(content), data_only=False)
    rows = list(workbook[sheet].iter_rows(values_only=True))
    header = [str(value) for value in rows[0]]
    body = [
        {header[i]: ("" if value is None else value) for i, value in enumerate(row)}
        for row in rows[1:]
    ]
    return header, body


def _normalized(text: str) -> str:
    """Whitespace-free NFKC (PDF extraction maps U+03A9 to the canonical-equivalent U+2126)."""
    return "".join(unicodedata.normalize("NFKC", text).split())


def _pdf_text(content: bytes) -> tuple[str, int]:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages), len(reader.pages)


def test_csv_xlsx_pdf_row_and_field_parity_against_saved_bom(client: TestClient):
    token = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    analysis_id, expected = _upload_parity_bom(client, token)
    headers = {"Authorization": f"Bearer {token}"}

    saved = client.get(f"/reports/{analysis_id}", headers=headers).json()
    saved_parts = saved["parts"]
    saved_mpns = [str(part["MPN"]) for part in saved_parts]
    # Saved BOM == uploaded BOM: aggregated, no duplicate, no missing row.
    assert len(saved_mpns) == len(set(saved_mpns)) == len(expected) == _PART_COUNT + 1
    assert set(saved_mpns) == set(expected)
    assert saved["total_parts"] == len(expected)
    for part in saved_parts:
        want = expected[str(part["MPN"])]
        assert part["Manufacturer"] == want["manufacturer"]
        assert part["Description"] == want["description"]
        assert int(part["Quantity"]) == want["qty"]
    assert int(next(p for p in saved_parts if p["MPN"] == "PN-0003-X")["Quantity"]) == 4 + 7

    annotated = annotate_report_parts(saved)["parts"]

    exports = {}
    for file_format in ("csv", "xlsx", "pdf"):
        response = client.get(f"/reports/{analysis_id}/export/{file_format}", headers=headers)
        assert response.status_code == 200, response.text
        exports[file_format] = response.content

    # ---- CSV: bytes + UTF-8 BOM behavior ----
    raw_csv = exports["csv"]
    assert raw_csv.startswith(UTF8_BOM), "Excel needs a UTF-8 BOM to detect UTF-8"
    assert not raw_csv[len(UTF8_BOM):].startswith(UTF8_BOM), "BOM must not be doubled"
    assert UTF8_BOM not in raw_csv[len(UTF8_BOM):]
    raw_csv.decode("utf-8")  # strict: no mojibake / invalid bytes
    text = raw_csv.decode("utf-8-sig")
    assert not text.startswith("\ufeff")
    csv_rows = list(csv.DictReader(io.StringIO(text, newline="")))
    metadata_columns = ["Project", "BOM", "Revision", "Analyzed At"]
    assert list(csv_rows[0]) == [*metadata_columns, *COMPONENT_COLUMNS]
    assert len(csv_rows) == len(saved_parts)
    assert [row["MPN"].lstrip("'") for row in csv_rows] == saved_mpns  # order + no dupes
    assert len({row["MPN"] for row in csv_rows}) == len(csv_rows)

    # ---- XLSX ----
    header, xlsx_rows = _xlsx_rows(exports["xlsx"], "Components")
    assert header == list(COMPONENT_COLUMNS)
    assert len(xlsx_rows) == len(saved_parts)
    _, detail_rows = _xlsx_rows(exports["xlsx"], "Component Details")
    assert [row["MPN"].lstrip("'") for row in detail_rows] == saved_mpns
    workbook = load_workbook(io.BytesIO(exports["xlsx"]))
    summary = {
        str(row[0]): row[1] for row in workbook["Summary"].iter_rows(min_row=4, values_only=True) if row[0]
    }
    assert int(summary["Total components"]) == len(saved_parts)
    assert summary["Project"] == saved["project_name"]
    assert saved["project_name"].startswith("Parity Project")
    assert summary["BOM"] == "Parity BOM"
    assert summary["Revision"] == "C"

    # ---- field-exact parity: CSV == XLSX == saved report (+ evidence envelope) ----
    for index, (part, csv_row, xlsx_row) in enumerate(zip(annotated, csv_rows, xlsx_rows)):
        mpn = str(part["MPN"])
        evidence = part["evidence"]
        assert csv_row["Project"] == saved["project_name"]
        assert csv_row["BOM"] == "Parity BOM"
        assert csv_row["Revision"] == "C"
        for column in COMPONENT_COLUMNS:
            xlsx_value = xlsx_row[column]
            if column in {
                "Quantity per Parent",
                "Effective Quantity",
                "Risk Score",
                "Stock",
                "Unit Price",
            }:
                try:
                    same_value = Decimal(csv_row[column]) == Decimal(str(xlsx_value))
                except (InvalidOperation, ValueError):
                    same_value = csv_row[column] == str(xlsx_value)
                assert same_value, (
                    f"row {index} {mpn!r} column {column!r}: "
                    f"csv={csv_row[column]!r} xlsx={xlsx_value!r}"
                )
            else:
                assert csv_row[column] == str(xlsx_value), (
                    f"row {index} {mpn!r} column {column!r}: "
                    f"csv={csv_row[column]!r} xlsx={xlsx_value!r}"
                )
        # Exact part / source fields straight from the saved report.
        assert csv_row["MPN"].lstrip("'") == mpn
        assert csv_row["Manufacturer"] == part["Manufacturer"]
        assert csv_row["Description"] == part["Description"]
        assert csv_row["Effective Quantity"] == str(part["Quantity"])
        assert csv_row["Quantity per Parent"] == str(part["Quantity"])
        assert csv_row["Evidence Class"] == evidence["evidence_class"] == "synthetic-preview"
        assert csv_row["Evidence Source"] == evidence["source"] == "synthetic-preview"
        assert csv_row["Identity Source"] == evidence["fields"]["identity"]["source"]
        assert csv_row["Price Source"] == evidence["fields"]["price"]["source"]
        assert csv_row["Price Type"] == evidence["fields"]["price"]["price_type"]
        assert csv_row["Risk Level"] == str(part["Risk Level"])
        assert csv_row["Risk Score"] == str(part["Risk Score"])
        assert csv_row["Lifecycle"] == str(part["Lifecycle"])
        assert csv_row["Stock"] == str(part["Stock"])
        assert csv_row["Unit Price"] == str(part["Unit Price"])
    # Spreadsheet-injection guard keeps the MPN text visible but inert.
    formula = next(row for row in csv_rows if row["MPN"].lstrip("'") == "=CMD|x")
    assert formula["MPN"] == "'=CMD|x"

    # ---- PDF: every saved row exactly once, summary counts match ----
    pdf_bytes = exports["pdf"]
    assert pdf_bytes.startswith(b"%PDF-") and b"%%EOF" in pdf_bytes[-1024:]
    pdf_text, pages = _pdf_text(pdf_bytes)
    assert pages >= 2, "60+ rows must paginate rather than truncate"
    flat = _normalized(pdf_text)
    assert f"Components:{len(saved_parts)}" in flat
    assert _normalized(f"Project: {saved['project_name']}") in flat
    assert "BOM:ParityBOM" in flat and "Revision:C" in flat
    for part in saved_parts:
        mpn = _normalized(str(part["MPN"]))
        assert flat.count(mpn) == 1, f"{part['MPN']!r} appears {flat.count(mpn)}x in PDF"
        label = _normalized(f"{part['Manufacturer']} · {part['Description']}")
        assert label in flat, f"manufacturer/description for {part['MPN']!r} missing from PDF"
    assert "Nocomponentrowsarepresent" not in flat

    # Same saved BOM through the builders directly must match the HTTP bytes' rows.
    direct_rows = list(
        csv.DictReader(io.StringIO(build_csv(annotate_report_parts(saved)).decode("utf-8-sig"), newline=""))
    )
    assert [row["MPN"] for row in direct_rows] == [row["MPN"] for row in csv_rows]


def test_csv_and_legacy_csv_agree_on_saved_bom_rows(client: TestClient):
    """The older /export.csv route must not silently drop or duplicate saved rows."""
    token = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    analysis_id, expected = _upload_parity_bom(client, token)
    headers = {"Authorization": f"Bearer {token}"}
    modern = client.get(f"/reports/{analysis_id}/export/csv", headers=headers).content
    legacy = client.get(f"/reports/{analysis_id}/export.csv", headers=headers).content
    modern_mpns = [r["MPN"].lstrip("'") for r in csv.DictReader(io.StringIO(modern.decode("utf-8-sig"), newline=""))]
    legacy_rows = list(csv.DictReader(io.StringIO(legacy.decode("utf-8-sig"), newline="")))
    assert len(legacy_rows) == len(modern_mpns) == len(expected)
    assert sorted(r["MPN"].lstrip("'") for r in legacy_rows) == sorted(modern_mpns)
    assert len({r["MPN"] for r in legacy_rows}) == len(legacy_rows)


def test_exports_are_identical_after_reload_of_the_saved_bom(client: TestClient, tmp_path: Path):
    """Deterministic CSV bytes and equal XLSX/PDF rows after a simulated restart."""
    from apps.api import synthetic_analyze, workspace_store

    token = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    analysis_id, _ = _upload_parity_bom(client, token)
    headers = {"Authorization": f"Bearer {token}"}
    before = {f: client.get(f"/reports/{analysis_id}/export/{f}", headers=headers).content for f in ("csv", "xlsx", "pdf")}

    synthetic_analyze._REPORTS.clear()
    workspace_store._STORE = workspace_store.WorkspaceStore(tmp_path / "store.json")  # reload from disk
    token = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    headers = {"Authorization": f"Bearer {token}"}
    after = {f: client.get(f"/reports/{analysis_id}/export/{f}", headers=headers).content for f in ("csv", "xlsx", "pdf")}

    assert after["csv"] == before["csv"], "CSV bytes must be reproducible from the saved report"
    assert _xlsx_rows(after["xlsx"], "Components") == _xlsx_rows(before["xlsx"], "Components")
    assert _normalized(_pdf_text(after["pdf"])[0]) == _normalized(_pdf_text(before["pdf"])[0])


def test_empty_saved_report_exports_headers_only_without_phantom_rows():
    report = {"project_name": "Empty", "bom_name": "empty.csv", "mode": "synthetic-preview", "parts": []}
    raw = build_csv(report)
    assert raw.startswith(UTF8_BOM)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    assert rows == []
    header, body = _xlsx_rows(build_xlsx(report), "Components")
    assert header == list(COMPONENT_COLUMNS) and body == []
    text, _ = _pdf_text(build_pdf(report))
    assert "Components: 0" in text
    assert _normalized("No component rows are present in this report.") in _normalized(text)


def test_pdf_and_csv_keep_unicode_manufacturer_names_for_latin_scripts():
    report = {
        "project_name": "Unicode",
        "bom_name": "u.csv",
        "mode": "synthetic-preview",
        "parts": [
            {
                "MPN": "R-1",
                "Manufacturer": "Würth Elektronik",
                "Description": "10 k\u03a9 \u00b11% \u00abX7R\u00bb",
                "Quantity": 2,
                "source": "synthetic-preview",
            }
        ],
    }
    csv_row = next(csv.DictReader(io.StringIO(build_csv(report).decode("utf-8-sig"), newline="")))
    assert csv_row["Manufacturer"] == "Würth Elektronik"
    assert csv_row["Description"] == "10 k\u03a9 \u00b11% \u00abX7R\u00bb"
    flat = _normalized(_pdf_text(build_pdf(report))[0])
    assert _normalized("Würth Elektronik · 10 k\u03a9 \u00b11% \u00abX7R\u00bb") in flat


def test_pdf_preserves_cjk_manufacturer_glyphs():
    report = {
        "project_name": "CJK",
        "bom_name": "cjk.csv",
        "mode": "synthetic-preview",
        "parts": [{"MPN": "R-1", "Manufacturer": "\u6751\u7530\u88fd\u4f5c\u6240 Murata", "Quantity": 1}],
    }
    # CSV/XLSX preserve it exactly (this part of parity holds).
    csv_row = next(csv.DictReader(io.StringIO(build_csv(report).decode("utf-8-sig"), newline="")))
    assert csv_row["Manufacturer"] == "\u6751\u7530\u88fd\u4f5c\u6240 Murata"
    _, xlsx_body = _xlsx_rows(build_xlsx(report), "Components")
    assert xlsx_body[0]["Manufacturer"] == "\u6751\u7530\u88fd\u4f5c\u6240 Murata"
    text, _ = _pdf_text(build_pdf(report))
    assert "\u6751\u7530" in text
