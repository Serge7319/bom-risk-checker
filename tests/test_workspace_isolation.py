"""Prove one workspace cannot list or read another workspace's records."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import WorkspaceAccessError, reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import SANDBOX_ACCOUNTS, SANDBOX_SEED_USERS
from tests.two_user_isolation_suite import (
    PREFERENCES_A,
    PREFERENCES_B,
    assert_denied_for_other_user,
    assert_other_user_only_sees_own,
    assert_owner_still_has_everything,
    assert_unauthenticated_denied,
    seed_workspace,
)

ROOT = Path(__file__).resolve().parents[1]
FLAT = ROOT / "tests/fixtures/synthetic_bom_25parts.csv"
NESTED = ROOT / "tests/fixtures/nested_bom_product.csv"


def _login(client: TestClient, email: str) -> dict[str, str]:
    account = SANDBOX_ACCOUNTS[email]
    res = client.post(
        "/auth/login",
        json={"email": email, "password": account["password"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["workspace_id"] == account["workspace_id"]
    assert body["access_token"].count(".") == 2
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture()
def isolated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store_path = tmp_path / "iso_store.json"
    auth_path = tmp_path / "iso_auth.json"
    monkeypatch.setenv("CADIVOR_MIGRATION_STORE", str(store_path))
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(store_path)
    reset_auth_store_for_tests(auth_path, accounts=SANDBOX_SEED_USERS)
    from apps.api import workspace_store as ws
    from apps.api import synthetic_analyze as sa

    ws._STORE = reset_store_for_tests(store_path)
    sa._REPORTS.clear()
    return TestClient(app)


def test_cross_workspace_cannot_see_or_open_analysis(isolated_client: TestClient):
    client = isolated_client
    headers_a = _login(client, "sandbox-a@cadivor.test")
    headers_b = _login(client, "sandbox-b@cadivor.test")

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
    assert created.json()["workspace_id"] == "ws-sandbox-a"

    own = client.get(f"/reports/{analysis_id}", headers=headers_a)
    assert own.status_code == 200
    assert own.json()["workspace_id"] == "ws-sandbox-a"

    other = client.get(f"/reports/{analysis_id}", headers=headers_b)
    assert other.status_code == 404

    home_b = client.get("/workspace/home", headers=headers_b).json()
    assert home_b["workspace_id"] == "ws-sandbox-b"
    assert home_b["metrics"]["saved_analyses"] == 0
    assert all(p["name"] != "Alpha Only" for p in home_b.get("projects") or [])

    projects_b = client.get("/projects", headers=headers_b).json()
    assert projects_b["projects"] == []

    reports_b = client.get("/reports", headers=headers_b).json()
    assert reports_b["reports"] == []

    mon = client.get(
        f"/tools/monitoring?analysis_id={analysis_id}", headers=headers_b
    )
    assert mon.status_code == 404

    home_a = client.get("/workspace/home", headers=headers_a).json()
    assert home_a["metrics"]["saved_analyses"] == 1
    assert any(p["name"] == "Alpha Only" for p in home_a["projects"])


def test_each_workspace_only_lists_own_analyses(isolated_client: TestClient):
    client = isolated_client
    headers_a = _login(client, "sandbox-a@cadivor.test")
    headers_b = _login(client, "sandbox-b@cadivor.test")

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
    headers_a = _login(client, "sandbox-a@cadivor.test")
    headers_b = _login(client, "sandbox-b@cadivor.test")

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

    rename = client.patch(
        f"/projects/{project_id}",
        headers=headers_b,
        json={"name": "Hijacked"},
    )
    assert rename.status_code == 404

    own_rename = client.patch(
        f"/projects/{project_id}",
        headers=headers_a,
        json={"name": "GuardMe Renamed"},
    )
    assert own_rename.status_code == 200
    assert own_rename.json()["project"]["name"] == "GuardMe Renamed"

    assert (
        client.delete(f"/reports/{analysis_id}", headers=headers_b).status_code == 404
    )
    assert client.delete(f"/projects/{project_id}", headers=headers_b).status_code == 404

    assert client.get(f"/reports/{analysis_id}", headers=headers_a).status_code == 200
    assert client.get(f"/reports/{analysis_id}", headers=headers_b).status_code == 404
    assert client.get("/projects", headers=headers_b).json()["projects"] == []

    assert (
        client.delete(f"/reports/{analysis_id}", headers=headers_a).status_code == 200
    )
    assert client.get(f"/reports/{analysis_id}", headers=headers_a).status_code == 404

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


def test_two_user_matrix_workspaces_boms_reports_decisions_monitoring(
    isolated_client: TestClient,
):
    """Acceptance D3 (file-backed disposable auth/store): allow + deny matrix.

    Monitoring GET is read-only, so seeding persists alerts through
    ``POST /tools/monitoring/refresh`` and User B can never trigger that
    write against User A's analysis.
    """
    client = isolated_client
    headers_a = _login(client, "sandbox-a@cadivor.test")
    headers_b = _login(client, "sandbox-b@cadivor.test")

    seeded_a = seed_workspace(client, headers_a, owner="A", preferences=PREFERENCES_A)
    seeded_b = seed_workspace(client, headers_b, owner="B", preferences=PREFERENCES_B)
    assert seeded_a["workspace_id"] == "ws-sandbox-a"
    assert seeded_b["workspace_id"] == "ws-sandbox-b"
    assert seeded_a["analysis_id"] != seeded_b["analysis_id"]

    # B -> A denied on every list/read/download/export/update/delete surface.
    denied_b = assert_denied_for_other_user(client, headers_b, seeded_a)
    # A -> B denied symmetrically.
    denied_a = assert_denied_for_other_user(client, headers_a, seeded_b)
    assert len(denied_b) == len(denied_a) >= 30

    assert_unauthenticated_denied(client, seeded_a)

    # Allowed: each owner still has complete, unmodified data.
    assert_owner_still_has_everything(client, headers_a, seeded_a)
    allowed_b = assert_other_user_only_sees_own(client, headers_b, seeded_b)
    assert len(allowed_b) >= 12

    # B's own deletions never touched A.
    assert_owner_still_has_everything(client, headers_a, seeded_a)
