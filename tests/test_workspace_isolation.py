"""Prove one workspace cannot list or read another workspace's records."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import SMOKE_ACCOUNTS, app
from apps.api.workspace_store import WorkspaceAccessError, reset_store_for_tests

ROOT = Path(__file__).resolve().parents[1]
FLAT = ROOT / "tests/fixtures/synthetic_bom_25parts.csv"
NESTED = ROOT / "tests/fixtures/nested_bom_product.csv"


def _login(client: TestClient, email: str) -> dict[str, str]:
    account = SMOKE_ACCOUNTS[email]
    res = client.post(
        "/auth/smoke-login",
        json={"email": email, "password": account["password"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["workspace_id"] == account["workspace_id"]
    assert body["access_token"] == account["access_token"]
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture()
def isolated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store_path = tmp_path / "iso_store.json"
    monkeypatch.setenv("CADIVOR_MIGRATION_STORE", str(store_path))
    reset_store_for_tests(store_path)
    from apps.api import workspace_store as ws
    from apps.api import synthetic_analyze as sa

    ws._STORE = reset_store_for_tests(store_path)
    sa._REPORTS.clear()
    return TestClient(app)


def test_cross_workspace_cannot_see_or_open_analysis(isolated_client: TestClient):
    client = isolated_client
    headers_a = _login(client, "auth-smoke@cadivor.test")
    headers_b = _login(client, "auth-smoke-b@cadivor.test")

    created = client.post(
        "/boms/analyze",
        headers=headers_a,
        files={"file": ("nested_bom_product.csv", NESTED.read_bytes(), "text/csv")},
        data={
            "project_name": "Alpha Only",
            "bom_name": "Secret BOM",
            "revision": "A",
        },
    )
    assert created.status_code == 200
    analysis_id = created.json()["analysis_id"]
    assert created.json()["workspace_id"] == "ws-smoke-a"

    # Owner can read
    own = client.get(f"/reports/{analysis_id}", headers=headers_a)
    assert own.status_code == 200
    assert own.json()["workspace_id"] == "ws-smoke-a"

    # Other workspace: report GET rejected
    other = client.get(f"/reports/{analysis_id}", headers=headers_b)
    assert other.status_code == 404

    # Other workspace home/projects/reports must not include Alpha
    home_b = client.get("/workspace/home", headers=headers_b).json()
    assert home_b["workspace_id"] == "ws-smoke-b"
    assert home_b["metrics"]["saved_analyses"] == 0
    assert all(p["name"] != "Alpha Only" for p in home_b.get("projects") or [])

    projects_b = client.get("/projects", headers=headers_b).json()
    assert projects_b["projects"] == []

    reports_b = client.get("/reports", headers=headers_b).json()
    assert reports_b["reports"] == []

    # Tools with foreign analysis_id are rejected
    mon = client.get(
        f"/tools/monitoring?analysis_id={analysis_id}", headers=headers_b
    )
    assert mon.status_code == 404

    # Workspace A still sees its data
    home_a = client.get("/workspace/home", headers=headers_a).json()
    assert home_a["metrics"]["saved_analyses"] == 1
    assert any(p["name"] == "Alpha Only" for p in home_a["projects"])


def test_each_workspace_only_lists_own_analyses(isolated_client: TestClient):
    client = isolated_client
    headers_a = _login(client, "auth-smoke@cadivor.test")
    headers_b = _login(client, "auth-smoke-b@cadivor.test")

    a = client.post(
        "/boms/analyze",
        headers=headers_a,
        files={"file": ("synthetic_bom_25parts.csv", FLAT.read_bytes(), "text/csv")},
        data={"project_name": "ProjA", "bom_name": "BomA", "revision": "A"},
    )
    b = client.post(
        "/boms/analyze",
        headers=headers_b,
        files={"file": ("synthetic_bom_25parts.csv", FLAT.read_bytes(), "text/csv")},
        data={"project_name": "ProjB", "bom_name": "BomB", "revision": "A"},
    )
    assert a.status_code == 200 and b.status_code == 200
    id_a, id_b = a.json()["analysis_id"], b.json()["analysis_id"]

    reports_a = {r["id"] for r in client.get("/reports", headers=headers_a).json()["reports"]}
    reports_b = {r["id"] for r in client.get("/reports", headers=headers_b).json()["reports"]}
    assert reports_a == {id_a}
    assert reports_b == {id_b}
    assert id_a not in reports_b and id_b not in reports_a

    assert client.get(f"/reports/{id_b}", headers=headers_a).status_code == 404
    assert client.get(f"/reports/{id_a}", headers=headers_b).status_code == 404


def test_store_raises_on_cross_workspace_get(tmp_path: Path):
    store = reset_store_for_tests(tmp_path / "store.json")
    report = store.upsert_analysis_report(
        {
            "id": "ana-1",
            "filename": "x.csv",
            "created_at": "2026-11-04T00:00:00Z",
            "total_parts": 1,
            "health_score": 90,
            "health_status": "Healthy",
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "low_risk_count": 1,
            "mode": "synthetic-preview",
            "parts": [],
        },
        workspace_id="ws-a",
        project_name="OnlyA",
        bom_name="Bom",
        revision="A",
    )
    assert store.get_report(report["id"], workspace_id="ws-a") is not None
    with pytest.raises(WorkspaceAccessError):
        store.get_report(report["id"], workspace_id="ws-b")
    assert store.list_projects(workspace_id="ws-b") == []
    assert store.home_dashboard(workspace_id="ws-b")["metrics"]["saved_analyses"] == 0


def test_cross_workspace_cannot_update_or_delete(isolated_client: TestClient):
    client = isolated_client
    headers_a = _login(client, "auth-smoke@cadivor.test")
    headers_b = _login(client, "auth-smoke-b@cadivor.test")

    created = client.post(
        "/boms/analyze",
        headers=headers_a,
        files={"file": ("synthetic_bom_25parts.csv", FLAT.read_bytes(), "text/csv")},
        data={"project_name": "GuardMe", "bom_name": "Private", "revision": "A"},
    )
    assert created.status_code == 200
    body = created.json()
    analysis_id = body["analysis_id"]
    project_id = body["project_id"]

    # Foreign workspace cannot rename project
    rename = client.patch(
        f"/projects/{project_id}",
        headers=headers_b,
        json={"name": "Hijacked"},
    )
    assert rename.status_code == 404

    # Owner rename works
    own_rename = client.patch(
        f"/projects/{project_id}",
        headers=headers_a,
        json={"name": "GuardMe Renamed"},
    )
    assert own_rename.status_code == 200
    assert own_rename.json()["project"]["name"] == "GuardMe Renamed"

    # Foreign workspace cannot delete analysis or project
    assert (
        client.delete(f"/reports/{analysis_id}", headers=headers_b).status_code == 404
    )
    assert client.delete(f"/projects/{project_id}", headers=headers_b).status_code == 404

    # Owner still sees data; foreign still sees nothing
    assert client.get(f"/reports/{analysis_id}", headers=headers_a).status_code == 200
    assert client.get(f"/reports/{analysis_id}", headers=headers_b).status_code == 404
    assert client.get("/projects", headers=headers_b).json()["projects"] == []

    # Owner delete analysis removes it for owner only
    assert (
        client.delete(f"/reports/{analysis_id}", headers=headers_a).status_code == 200
    )
    assert client.get(f"/reports/{analysis_id}", headers=headers_a).status_code == 404

    # Create again then owner deletes project (cascades)
    created2 = client.post(
        "/boms/analyze",
        headers=headers_a,
        files={"file": ("synthetic_bom_25parts.csv", FLAT.read_bytes(), "text/csv")},
        data={"project_name": "GuardMe Renamed", "bom_name": "Private2", "revision": "A"},
    )
    assert created2.status_code == 200
    project_id2 = created2.json()["project_id"]
    assert client.delete(f"/projects/{project_id2}", headers=headers_a).status_code == 200
    assert client.get("/projects", headers=headers_a).json()["projects"] == []
    assert client.get("/projects", headers=headers_b).json()["projects"] == []
