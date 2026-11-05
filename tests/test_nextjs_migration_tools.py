"""API coverage for Next.js migration tool routes (sandbox / synthetic)."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/synthetic_bom_25parts.csv"


@pytest.fixture(autouse=True)
def _sandbox_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()


def _auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_migration_tools_vertical_slice():
    client = TestClient(app)
    headers = _auth_headers(client)

    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert analyze.status_code == 200
    analysis_id = analyze.json()["analysis_id"]

    reports = client.get("/reports", headers=headers)
    assert reports.status_code == 200
    assert any(r["id"] == analysis_id for r in reports.json()["reports"])

    monitoring = client.get(
        f"/tools/monitoring?analysis_id={analysis_id}", headers=headers
    )
    assert monitoring.status_code == 200
    body = monitoring.json()
    assert body["ok"] is True
    assert body["metrics"]["monitored_parts"] == 25
    assert "Supabase" in body["gap"] or "monitor" in body["gap"].lower()

    report = client.get(f"/reports/{analysis_id}", headers=headers).json()
    part_a = report["parts"][0]["MPN"]
    part_b = report["parts"][1]["MPN"]
    compare = client.post(
        "/tools/compare-parts",
        headers=headers,
        json={"part_a": part_a, "part_b": part_b, "analysis_id": analysis_id},
    )
    assert compare.status_code == 200
    cmp_body = compare.json()
    assert cmp_body["ok"] is True
    assert len(cmp_body["rows"]) >= 1
    assert "supplier" in cmp_body["gap"].lower() or "synthetic" in cmp_body["gap"].lower()

    for path in (
        f"/tools/procurement?analysis_id={analysis_id}",
        f"/tools/design-impact?analysis_id={analysis_id}",
        f"/tools/cost-optimization?analysis_id={analysis_id}&build_quantity=100",
        f"/tools/detailed-risk?analysis_id={analysis_id}",
        "/tools/portfolio",
    ):
        res = client.get(path, headers=headers)
        assert res.status_code == 200, path
        assert res.json().get("ok") is True

    supply = client.post(
        "/tools/supply-risk",
        headers=headers,
        json={
            "analysis_id": analysis_id,
            "build_quantity": 100,
            "stock_reduction_percent": 25,
        },
    )
    assert supply.status_code == 200
    assert supply.json()["ok"] is True

    health = client.get("/health")
    assert health.status_code == 200
    assert "monitoring" in health.json()["tools"]
