"""Regression: legacy-supplier analysis must flow evidence into saved reports/exports.

Reproduces the cadivor-report (2).xlsx failure mode — 10 parsed MPNs with missing
evidence must remain clearly unconfirmed, while verified supplier fixtures must
populate manufacturer/lifecycle/risk and appear in the mature XLSX sheets.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from openpyxl import load_workbook
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.report_exports import build_xlsx
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS, SMOKE_EMAIL, SMOKE_PASSWORD

ROOT = Path(__file__).resolve().parents[1]
BOM = ROOT / "tests/fixtures/radar_assembly_10parts.csv"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.setenv("CADIVOR_ANALYSIS_MODE", "legacy")
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


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _verified_part(mpn: str, *, manufacturer: str, lifecycle: str, stock: int, price: float, risk_hint: str = "Active") -> dict:
    return {
        "mpn": mpn,
        "manufacturer_part_number": mpn,
        "manufacturer": manufacturer,
        "description": f"{manufacturer} {mpn}",
        "lifecycle_status": lifecycle,
        "lifecycle_evidence": [f"Distributor catalog: {lifecycle}"],
        "stock_total": stock,
        "total_market_stock": stock,
        "stock_data_complete": True,
        "stock_data_sources": ["Mouser", "Digi-Key"],
        "supplier_count": 2,
        "supplier_data_verified": True,
        "unit_price": price,
        "unit_price_currency": "USD",
        "currency": "USD",
        "source": "Mouser",
        "product_detail_url": f"https://example.test/product/{mpn}",
        "datasheet_url": f"https://example.test/datasheet/{mpn}.pdf",
        "retrieved_at": "2026-11-07T12:00:00+00:00",
        "provider_health": {
            "has_verified_data": True,
            "configured_count": 2,
            "summary_message": "Verified authorized-distributor evidence available.",
        },
        "assessment_basis": risk_hint,
    }


def _missing_part(mpn: str) -> dict:
    return {
        "mpn": mpn,
        "manufacturer_part_number": mpn,
        "lifecycle_status": "Unknown",
        "stock_total": None,
        "total_market_stock": None,
        "supplier_count": None,
        "supplier_data_verified": False,
        "stock_data_complete": False,
        "provider_health": {
            "has_verified_data": False,
            "configured_count": 2,
            "summary_message": "Configured suppliers returned no exact-MPN match.",
        },
    }


def test_legacy_supplier_analysis_flows_verified_and_missing_evidence_into_export(client, monkeypatch):
    from apps.api import legacy_supplier_workflow
    from integrations import supplier_aggregator

    verified = {
        "LM358N": _verified_part(
            "LM358N", manufacturer="Texas Instruments", lifecycle="NRND", stock=120, price=0.42
        ),
        "TPS5430DDAR": _verified_part(
            "TPS5430DDAR",
            manufacturer="Texas Instruments",
            lifecycle="Active",
            stock=40,
            price=3.15,
        ),
        "W25Q64JVSSIQ": _verified_part(
            "W25Q64JVSSIQ",
            manufacturer="Winbond",
            lifecycle="Active",
            stock=5000,
            price=1.05,
        ),
    }

    def fake_get_best_part_data(mpn: str) -> dict:
        key = str(mpn or "").strip()
        if key in verified:
            return dict(verified[key])
        return _missing_part(key)

    monkeypatch.setattr(supplier_aggregator, "get_best_part_data", fake_get_best_part_data)
    monkeypatch.setattr(legacy_supplier_workflow, "production_analysis_enabled", lambda: True)
    # Avoid live alternative searches during the regression.
    monkeypatch.setattr(
        "src.alternative_engine.suggest_alternatives_v2",
        lambda *args, **kwargs: [],
    )

    headers = _login(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        data={
            "project_name": "Radar Controller",
            "bom_name": "Radar Assembly",
            "revision": "A",
        },
        files={"file": ("radar_assembly_10parts.csv", BOM.read_bytes(), "text/csv")},
    )
    assert analyze.status_code == 200, analyze.text
    body = analyze.json()
    assert body["mode"] == "legacy-supplier-engine"
    analysis_id = body["analysis_id"]

    report = client.get(f"/reports/{analysis_id}", headers=headers)
    assert report.status_code == 200, report.text
    payload = report.json()
    parts = {str(row.get("MPN") or row.get("mpn")): row for row in payload.get("parts") or []}
    assert len(parts) == 10

    # Verified fixture evidence must reach the saved report.
    lm358 = parts["LM358N"]
    assert lm358.get("Manufacturer") or lm358.get("manufacturer")
    assert "Texas Instruments" in str(lm358.get("Manufacturer") or lm358.get("manufacturer"))
    assert str(lm358.get("Lifecycle") or lm358.get("lifecycle_status")).upper() == "NRND"
    assert lm358.get("Risk Score") is not None or lm358.get("risk_score") is not None
    assert str(lm358.get("evidence_class") or "").startswith("live") or bool(
        lm358.get("Supplier Data Verified") or lm358.get("supplier_data_verified")
    )
    assert float(lm358.get("Stock") or lm358.get("stock") or 0) > 0

    # Missing evidence stays unconfirmed — never synthetic filler, never scored as Low.
    mcp = parts["MCP2551-I/SN"]
    assert str(mcp.get("Risk Level") or mcp.get("risk_level")).casefold() == "needs verification"
    assert mcp.get("Risk Score") in (None, "")
    assert str(mcp.get("evidence_class") or mcp.get("evidence_source") or "").casefold() in {
        "missing",
        "not recorded",
    }
    assert not (mcp.get("Supplier Data Verified") or mcp.get("supplier_data_verified"))

    # Health score must not treat unscored parts as a clean zero-risk BOM.
    needs = int(payload.get("needs_verification_count") or 0)
    assert needs >= 1
    if needs:
        assert payload.get("health_score") in (None, "")
        assert "verif" in str(payload.get("health_status") or "").casefold()

    workbook_bytes = build_xlsx(payload)
    workbook = load_workbook(io.BytesIO(workbook_bytes), data_only=False)
    sheet_names = set(workbook.sheetnames)
    assert "Summary" in sheet_names
    assert "Component Details" in sheet_names
    assert "High Risk Parts" in sheet_names
    assert "Alternative Candidates" in sheet_names

    summary_values = [
        str(value or "")
        for row in workbook["Summary"].iter_rows(values_only=True)
        for value in row
    ]
    joined = " | ".join(summary_values)
    assert "Needs verification" in joined
    assert "legacy-supplier-engine" in joined or "Evidence mode" in joined
    assert "unscored parts are not low risk" in joined.casefold()

    # Component Details must show the verified manufacturer and keep missing blanks unconfirmed.
    details = workbook["Component Details"]
    headers_row = [str(cell.value or "") for cell in next(details.iter_rows(min_row=1, max_row=1))]
    mpn_idx = headers_row.index("MPN")
    mfr_idx = headers_row.index("Manufacturer")
    risk_idx = headers_row.index("Risk")
    by_mpn = {}
    for row in details.iter_rows(min_row=2, values_only=True):
        mpn = str(row[mpn_idx] or "")
        by_mpn[mpn] = row
    assert "Texas Instruments" in str(by_mpn["LM358N"][mfr_idx])
    assert str(by_mpn["MCP2551-I/SN"][risk_idx]).casefold() in {"not assessed", "needs verification"}

    # Download path must serve the enriched workbook.
    export = client.get(f"/reports/{analysis_id}/export/xlsx", headers=headers)
    assert export.status_code == 200, export.text
    downloaded = load_workbook(io.BytesIO(export.content), data_only=False)
    assert "Component Details" in downloaded.sheetnames
    assert "High Risk Parts" in downloaded.sheetnames


def test_all_missing_evidence_does_not_present_zero_risk_as_healthy(client, monkeypatch):
    from apps.api import legacy_supplier_workflow
    from integrations import supplier_aggregator

    monkeypatch.setattr(
        supplier_aggregator,
        "get_best_part_data",
        lambda mpn: _missing_part(str(mpn or "").strip()),
    )
    monkeypatch.setattr(legacy_supplier_workflow, "production_analysis_enabled", lambda: True)
    monkeypatch.setattr("src.alternative_engine.suggest_alternatives_v2", lambda *a, **k: [])

    headers = _login(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        data={"project_name": "Radar Controller", "bom_name": "Radar Assembly", "revision": "A"},
        files={"file": ("radar_assembly_10parts.csv", BOM.read_bytes(), "text/csv")},
    )
    assert analyze.status_code == 200, analyze.text
    report = client.get(f"/reports/{analyze.json()['analysis_id']}", headers=headers).json()
    assert report["mode"] == "legacy-supplier-engine"
    assert int(report.get("needs_verification_count") or 0) == 10
    assert report.get("health_score") in (None, "")
    assert int(report.get("high_risk_count") or 0) == 0
    assert int(report.get("medium_risk_count") or 0) == 0
    assert int(report.get("low_risk_count") or 0) == 0

    workbook = load_workbook(io.BytesIO(build_xlsx(report)), data_only=False)
    joined = " | ".join(
        str(value or "")
        for row in workbook["Summary"].iter_rows(values_only=True)
        for value in row
    )
    assert "10 of 10" in joined or "Needs verification" in joined
    assert "not low risk" in joined.casefold()
    assert "Not scored" in joined or "evidence incomplete" in joined.casefold()
