"""Production-smoke regressions for hierarchy qty, exports, monitoring, replacements."""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import load_workbook
from starlette.testclient import TestClient

from apps.api.bom_hierarchy import compute_effective_quantities, rollup_assemblies
from apps.api.legacy_supplier_workflow import find_replacements
from apps.api.main import app
from apps.api.monitoring_store import (
    list_alerts,
    persist_alerts,
    reset_monitoring_store_for_tests,
)
from apps.api.report_exports import build_csv, build_xlsx
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.synthetic_analyze import analyze_upload, get_report
from apps.api.workspace_store import WorkspaceStore, get_store, reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
    SMOKE_WORKSPACE_ID,
)

ROOT = Path(__file__).resolve().parents[1]
NESTED = ROOT / "tests/fixtures/nested_bom_product.csv"
FLAT = ROOT / "tests/fixtures/synthetic_bom_25parts.csv"


@pytest.fixture(autouse=True)
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    monkeypatch.setenv("CADIVOR_ANALYSIS_MODE", "synthetic-preview")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    reset_store_for_tests(tmp_path / "workspace.json")
    reset_monitoring_store_for_tests()
    from apps.api import workspace_store as ws

    ws._STORE = WorkspaceStore(tmp_path / "workspace.json")
    monkeypatch.setenv("CADIVOR_MIGRATION_STORE", str(tmp_path / "workspace.json"))


def _auth(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_effective_quantity_multiplies_every_parent_in_path():
    parts = [
        {"MPN": "PROD-TOP", "Quantity": 1, "parent_mpn": None, "line_type": "assembly"},
        {"MPN": "PSU-ASM", "Quantity": 2, "parent_mpn": "PROD-TOP", "line_type": "assembly"},
        {"MPN": "CAP-100U", "Quantity": 4, "parent_mpn": "PSU-ASM", "line_type": "part"},
        {"MPN": "LM358DR", "Quantity": 4, "parent_mpn": "PSU-ASM", "line_type": "part"},
    ]
    by_mpn = {row["MPN"]: row for row in compute_effective_quantities(parts)}
    assert by_mpn["CAP-100U"]["quantity_per_parent"] == 4
    assert by_mpn["LM358DR"]["quantity_per_parent"] == 4
    assert by_mpn["CAP-100U"]["effective_quantity"] == 8
    assert by_mpn["LM358DR"]["effective_quantity"] == 8
    assert by_mpn["PSU-ASM"]["effective_quantity"] == 2


def test_hyphenated_mpn_still_multiplies_when_parent_is_normalized():
    """Legacy rows keep display hyphens while parents may already be normalized."""
    parts = [
        {
            "MPN": "PROD-TOP",
            "Quantity": 1,
            "parent_mpn": None,
            "line_type": "assembly",
            "Risk Level": "Low",
        },
        {
            "MPN": "PSU-ASM",
            "Quantity": 2,
            "parent_mpn": "PRODTOP",
            "line_type": "assembly",
            "Risk Level": "Low",
        },
        {
            "MPN": "CAP-100U",
            "Quantity": 4,
            "parent_mpn": "PSUASM",
            "line_type": "part",
            "Risk Level": "Medium",
        },
    ]
    qty = {row["MPN"]: row["effective_quantity"] for row in compute_effective_quantities(parts)}
    assert qty["CAP-100U"] == 8


def test_needs_verification_is_not_zero_risk_in_assembly_rollup():
    parts = [
        {
            "MPN": "TOP",
            "Quantity": 1,
            "parent_mpn": None,
            "line_type": "assembly",
            "Risk Level": "Low",
        },
        {
            "MPN": "LEAF-NV",
            "Quantity": 1,
            "parent_mpn": "TOP",
            "line_type": "part",
            "Risk Level": "Needs verification",
            "evidence_source": "missing",
        },
        {
            "MPN": "LEAF-L",
            "Quantity": 1,
            "parent_mpn": "TOP",
            "line_type": "part",
            "Risk Level": "Low",
            "evidence_source": "synthetic-preview",
        },
    ]
    rolled = rollup_assemblies(parts)
    assert rolled["top_level"]["rolled_risk_level"] == "Needs verification"
    assert rolled["top_level"]["needs_verification_leaves"] == 1
    assert any(c["mpn"] == "LEAF-NV" for c in rolled["priority_contributors"])
    assert all(c["mpn"] != "LEAF-L" for c in rolled["priority_contributors"])


def test_nested_smoke_bom_quantities_rollups_exports_and_consumers():
    report = analyze_upload(
        filename="nested_bom_product.csv",
        payload=NESTED.read_bytes(),
        workspace_id=SMOKE_WORKSPACE_ID,
        project_name="Nested Smoke",
        bom_name="nested-product-hierarchy",
        revision="N1",
    )
    assert len(report["parts"]) == 8
    by_mpn = {p["MPN"]: p for p in report["parts"]}
    assert by_mpn["LM358DR"]["quantity_per_parent"] == 4
    assert by_mpn["CAP100U"]["quantity_per_parent"] == 4
    assert by_mpn["LM358DR"]["effective_quantity"] == 8
    assert by_mpn["CAP100U"]["effective_quantity"] == 8

    hierarchy = report["hierarchy"]
    assert hierarchy["has_hierarchy"] is True
    top = hierarchy["top_level"]
    assert str(top["mpn"]).upper().replace("-", "") == "PRODTOP"
    assert top["high_risk_leaves"] + top["medium_risk_leaves"] >= 1
    assert top["rolled_risk_level"].casefold() in {"high", "medium"}

    psu = next(a for a in hierarchy["assemblies"] if "PSU" in str(a["mpn"]).upper())
    assert psu["effective_quantity"] == 2
    assert psu["leaf_count"] == 3
    mcu = next(a for a in hierarchy["assemblies"] if "MCU" in str(a["mpn"]).upper())
    assert mcu["high_risk_leaves"] + mcu["medium_risk_leaves"] >= 1
    assert mcu["rolled_risk_level"].casefold() in {"high", "medium"}

    from apps.api.migration_tools import design_impact_payload, procurement_payload

    procurement = procurement_payload(
        workspace_id=SMOKE_WORKSPACE_ID, analysis_id=report["id"]
    )
    proc_by_mpn = {
        str(row.get("mpn") or row.get("MPN")): row
        for row in procurement.get("parts") or []
    }
    assert float(proc_by_mpn["LM358DR"]["quantity"]) == 8
    assert float(proc_by_mpn["CAP100U"]["quantity"]) == 8

    impact = design_impact_payload(
        workspace_id=SMOKE_WORKSPACE_ID,
        analysis_id=report["id"],
        selected_mpn="LM358DR",
    )
    intelligence = impact.get("intelligence") or {}
    total_quantity = intelligence.get("total_quantity")
    if total_quantity is None:
        summary = intelligence.get("summary") or {}
        total_quantity = summary.get("total_quantity") or summary.get("Total Quantity")
    affected = (
        intelligence.get("affected_projects")
        or intelligence.get("affected_boms")
        or intelligence.get("occurrences")
        or []
    )
    if total_quantity is None:
        total_quantity = sum(
            float(row.get("Quantity") or row.get("quantity") or 0)
            for row in affected
            if isinstance(row, dict)
        )
    assert float(total_quantity) == 8, intelligence.keys()

    csv_bytes = build_csv(report)
    rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))
    assert len(rows) == 8
    csv_by_mpn = {row["MPN"]: row for row in rows}
    assert float(csv_by_mpn["LM358DR"]["Effective Quantity"]) == 8
    assert float(csv_by_mpn["CAP100U"]["Effective Quantity"]) == 8
    assert float(csv_by_mpn["LM358DR"]["Quantity per Parent"]) == 4
    assert float(csv_by_mpn["CAP100U"]["Quantity per Parent"]) == 4

    xlsx_bytes = build_xlsx(report)
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as archive:
        assert "xl/workbook.xml" in archive.namelist()
    workbook = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    components = workbook["Components"]
    headers = [cell.value for cell in next(components.iter_rows(min_row=1, max_row=1))]
    eff_idx = headers.index("Effective Quantity")
    qpp_idx = headers.index("Quantity per Parent")
    mpn_idx = headers.index("MPN")
    xlsx_map = {}
    for row in components.iter_rows(min_row=2, values_only=True):
        if row[mpn_idx]:
            xlsx_map[str(row[mpn_idx])] = row
    assert float(xlsx_map["LM358DR"][eff_idx]) == 8
    assert float(xlsx_map["CAP100U"][eff_idx]) == 8
    assert float(xlsx_map["LM358DR"][qpp_idx]) == 4


def test_flat_bom_quantities_remain_identity():
    report = analyze_upload(
        filename="synthetic_bom_25parts.csv",
        payload=FLAT.read_bytes(),
        workspace_id=SMOKE_WORKSPACE_ID,
        project_name="Flat Smoke",
        bom_name="flat-synthetic-25",
        revision="F1",
    )
    assert report["total_parts"] == 25
    hierarchy = report.get("hierarchy")
    assert hierarchy in (None, {}) or not hierarchy.get("has_hierarchy")
    for part in report["parts"]:
        qty = float(part.get("Quantity") or part.get("quantity") or 0)
        assert float(part.get("effective_quantity") or qty) == qty


def test_monitoring_scoped_to_analysis_with_saved_provenance():
    client = TestClient(app)
    headers = _auth(client)

    nested = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("nested_bom_product.csv", NESTED.read_bytes(), "text/csv")},
        data={"project_name": "Nest", "bom_name": "Nested", "revision": "A"},
    )
    flat = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FLAT.read_bytes(), "text/csv")},
        data={"project_name": "Flat", "bom_name": "FlatBOM", "revision": "A"},
    )
    assert nested.status_code == 200 and flat.status_code == 200
    nested_id = nested.json()["analysis_id"]
    flat_id = flat.json()["analysis_id"]

    persist_alerts(
        SMOKE_WORKSPACE_ID,
        [
            {
                "id": "alert-foreign",
                "analysis_id": flat_id,
                "part_number": "XC3S400-4PQG208C",
                "alert_type": "Risk Signal",
                "severity": "High",
                "message": "foreign analysis alert",
                "evidence_source": "synthetic-preview-analysis",
            }
        ],
    )

    nested_report = get_report(nested_id, workspace_id=SMOKE_WORKSPACE_ID)
    assert nested_report is not None
    for part in nested_report["parts"]:
        if str(part.get("MPN") or "").upper().replace("-", "") == "REG5V":
            part["Lifecycle"] = "NRND"
            part["lifecycle_status"] = "NRND"
            part["Risk Level"] = "High"
            part["evidence_source"] = "live-authorized-supplier"
            part["evidence_class"] = "live-authorized-supplier"
            part["supplier_data_verified"] = True
            part["Source"] = "DigiKey"
    get_store().upsert_analysis_report(
        nested_report,
        workspace_id=SMOKE_WORKSPACE_ID,
        project_name=nested_report.get("project_name"),
        bom_name=nested_report.get("bom_name"),
        revision=nested_report.get("revision"),
    )

    monitoring = client.get(
        f"/tools/monitoring?analysis_id={nested_id}", headers=headers
    )
    assert monitoring.status_code == 200, monitoring.text
    body = monitoring.json()
    assert body["analysis_id"] == nested_id
    assert body["metrics"]["active_alerts"] == len(body["alerts"])
    assert body["alerts"], "expected alerts from nested analysis"
    assert all(str(a.get("analysis_id")) == nested_id for a in body["alerts"])
    assert all(str(a.get("analysis_id")) != flat_id for a in body["alerts"])

    live_alerts = [
        a
        for a in body["alerts"]
        if str(a.get("part_number") or "").upper().replace("-", "") == "REG5V"
    ]
    assert live_alerts
    for alert in live_alerts:
        evidence = str(alert.get("evidence_source") or "").casefold()
        assert evidence.startswith("live")
        assert "synthetic" not in evidence
        assert "synthetic analysis" not in str(alert.get("message") or "").casefold()

    # Read path must not persist; explicit refresh does.
    assert list_alerts(SMOKE_WORKSPACE_ID, analysis_id=nested_id) == []
    refreshed = client.post(
        "/tools/monitoring/refresh", headers=headers, params={"analysis_id": nested_id}
    )
    assert refreshed.status_code == 200, refreshed.text
    listed = list_alerts(SMOKE_WORKSPACE_ID, analysis_id=nested_id)
    assert listed
    assert all(str(a.get("analysis_id")) == nested_id for a in listed)


def test_find_replacements_dedupes_canonical_mpn_and_flags_lifecycle_conflicts(monkeypatch):
    def fake_search(state, mpn):
        state["alternative_finder_result"] = {
            "original_data": {
                "manufacturer_part_number": mpn,
                "description": "op amp",
                "Category": "Amplifier",
                "supplier_data_verified": True,
            },
            "candidates": [
                {
                    "Alternative Part": "LM358DR",
                    "Manufacturer": "TI",
                    "Classification": "Same family",
                    "Lifecycle": "Active",
                    "Supplier": "DigiKey",
                    "Source Identity Verified": True,
                    "Category": "Amplifier",
                    "description": "op amp",
                    "Product URL": "https://example.test/dk/LM358DR",
                },
                {
                    "Alternative Part": "LM-358-DR",
                    "Manufacturer": "TI",
                    "Classification": "Same family",
                    "Lifecycle": "NRND",
                    "Supplier": "Mouser",
                    "Source Identity Verified": True,
                    "Category": "Amplifier",
                    "description": "op amp",
                    "Product URL": "https://example.test/mouser/LM358DR",
                },
            ],
            "discovery_metadata": {
                "unclassified_leads": [
                    {
                        "Alternative Part": "LM358DR",
                        "Manufacturer": "TI",
                        "Lifecycle": "Active",
                        "Supplier": "Newark",
                        "Category": "Amplifier",
                        "description": "op amp",
                    }
                ],
                "unfiltered_leads": [],
                "providers": {},
            },
        }
        return {"status": "ok", "search_outcome": "candidates_found"}

    monkeypatch.setattr(
        "src.alternative_finder_search.run_alternative_finder_search",
        fake_search,
    )
    result = find_replacements("LM358ADR2G")
    all_rows = (
        list(result.get("candidates") or [])
        + list(result.get("unclassified_leads") or [])
        + list(result.get("unfiltered_leads") or [])
    )
    keys = [str(row.get("mpn") or "").upper().replace("-", "") for row in all_rows]
    assert keys.count("LM358DR") == 1
    winner = next(
        row
        for row in all_rows
        if str(row.get("mpn") or "").upper().replace("-", "") == "LM358DR"
    )
    assert winner.get("lifecycle_conflict") is True
    offers = winner.get("supplier_offers") or []
    assert len(offers) >= 2
    sources = {str(offer.get("source") or "") for offer in offers}
    assert sources & {"DigiKey", "Mouser", "Newark"}
