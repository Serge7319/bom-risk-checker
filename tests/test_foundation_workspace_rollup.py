"""Foundation milestone: persistence + nested BOM risk roll-up."""
from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from apps.api.bom_hierarchy import compute_effective_quantities, rollup_assemblies
from apps.api.main import SMOKE_EMAIL, SMOKE_PASSWORD, app
from apps.api.synthetic_analyze import analyze_upload, get_report
from apps.api.workspace_store import WorkspaceStore, reset_store_for_tests

ROOT = Path(__file__).resolve().parents[1]
NESTED = ROOT / "tests/fixtures/nested_bom_product.csv"
FLAT = ROOT / "tests/fixtures/synthetic_bom_25parts.csv"


def _auth(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/smoke-login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_nested_quantity_and_risk_rollup():
    parts = [
        {
            "MPN": "TOP",
            "Quantity": 1,
            "parent_mpn": None,
            "line_type": "assembly",
            "Risk Level": "Low",
        },
        {
            "MPN": "SUB",
            "Quantity": 2,
            "parent_mpn": "TOP",
            "line_type": "assembly",
            "Risk Level": "Low",
        },
        {
            "MPN": "LEAF-H",
            "Quantity": 3,
            "parent_mpn": "SUB",
            "line_type": "part",
            "Risk Level": "High",
            "Risk Reasons": "NRND",
        },
        {
            "MPN": "LEAF-L",
            "Quantity": 1,
            "parent_mpn": "SUB",
            "line_type": "part",
            "Risk Level": "Low",
        },
    ]
    qty = {row["MPN"]: row["effective_quantity"] for row in compute_effective_quantities(parts)}
    assert qty["TOP"] == 1
    assert qty["SUB"] == 2
    assert qty["LEAF-H"] == 6  # 1 * 2 * 3
    assert qty["LEAF-L"] == 2

    rolled = rollup_assemblies(parts)
    assert rolled["has_hierarchy"] is True
    assert rolled["top_level"]["mpn"] == "TOP"
    assert rolled["top_level"]["rolled_risk_level"] == "High"
    assert rolled["top_level"]["high_risk_leaves"] == 1
    assert any(c["mpn"] == "LEAF-H" for c in rolled["priority_contributors"])


def test_persistence_across_store_reload(tmp_path: Path):
    store_path = tmp_path / "workspace.json"
    reset_store_for_tests(store_path)
    report = analyze_upload(
        filename="nested_bom_product.csv",
        payload=NESTED.read_bytes(),
        workspace_id="ws-smoke-a",
        project_name="Alpha Line",
        bom_name="Main Board",
        revision="B",
    )
    analysis_id = report["id"]
    assert report["persisted"] is True
    assert report["hierarchy"]["has_hierarchy"] is True
    # Effective qty after MPN normalize (hyphens stripped): PSUASM=2, REG5V=2, CAP100U=8
    by_mpn = {p["MPN"]: p for p in report["parts"]}
    assert by_mpn["PSUASM"]["effective_quantity"] == 2
    assert by_mpn["REG5V"]["effective_quantity"] == 2
    assert by_mpn["CAP100U"]["effective_quantity"] == 8

    # Simulate process reload: new store instance reading same file.
    reloaded = WorkspaceStore(store_path)
    restored = reloaded.get_report(analysis_id, workspace_id="ws-smoke-a")
    assert restored is not None
    assert restored["project_name"].startswith("Alpha Line")
    assert restored["bom_name"] == "Main Board"
    assert restored["revision"] == "B"
    assert restored["id"] == analysis_id and restored.get("workspace_id") == "ws-smoke-a"

    home = reloaded.home_dashboard(workspace_id="ws-smoke-a")
    assert home["metrics"]["active_projects"] >= 1
    assert home["metrics"]["saved_analyses"] >= 1
    assert any(p["name"] == "Alpha Line" for p in home["projects"])


def test_api_upload_report_home_and_flat_compat(tmp_path: Path, monkeypatch):
    store_path = tmp_path / "api_workspace.json"
    reset_store_for_tests(store_path)
    monkeypatch.setenv("CADIVOR_MIGRATION_STORE", str(store_path))
    # Force module store to test path
    from apps.api import workspace_store as ws

    ws._STORE = WorkspaceStore(store_path)

    client = TestClient(app)
    headers = _auth(client)

    nested = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("nested_bom_product.csv", NESTED.read_bytes(), "text/csv")},
        data={
            "project_name": "Nest Project",
            "bom_name": "Nested Product",
            "revision": "A",
        },
    )
    assert nested.status_code == 200, nested.text
    body = nested.json()
    assert body["persisted"] is True
    assert body["has_hierarchy"] is True
    analysis_id = body["analysis_id"]

    report = client.get(f"/reports/{analysis_id}", headers=headers)
    assert report.status_code == 200
    payload = report.json()
    assert payload["hierarchy"]["has_hierarchy"] is True
    assert payload["hierarchy"]["top_level"]["mpn"] == "PRODTOP"
    assert len(payload["hierarchy"]["assemblies"]) >= 2

    home = client.get("/workspace/home", headers=headers)
    assert home.status_code == 200
    dash = home.json()
    assert dash["metrics"]["saved_analyses"] >= 1
    assert any(a["id"] == analysis_id for a in dash["recent_analyses"])

    projects = client.get("/projects", headers=headers)
    assert projects.status_code == 200
    assert any(p["name"] == "Nest Project" for p in projects.json()["projects"])

    # Flat BOM path still works
    flat = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FLAT.read_bytes(), "text/csv")},
        data={"project_name": "Flat Project", "bom_name": "Flat BOM", "revision": "A"},
    )
    assert flat.status_code == 200
    assert flat.json()["total_parts"] == 25
    assert flat.json().get("has_hierarchy") in {False, None}

    listing = client.get("/reports", headers=headers)
    assert listing.status_code == 200
    ids = {r["id"] for r in listing.json()["reports"]}
    assert analysis_id in ids
    assert flat.json()["analysis_id"] in ids
