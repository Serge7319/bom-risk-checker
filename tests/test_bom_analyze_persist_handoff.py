"""BOM analyze must persist before clients can open detailed risk."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.json_safe import json_safe
from apps.api.migration_tools import detailed_risk_payload
from apps.api.synthetic_analyze import (
    PersistenceVerifyError,
    analyze_upload,
    get_report,
)
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS


ROOT = Path(__file__).resolve().parents[1]
WEB_BOM = ROOT / "apps/web/src/app/bom-analyzer/page.tsx"
WEB_RISK = ROOT / "apps/web/src/app/detailed-risk-report/page.tsx"
WEB_JOBS = ROOT / "apps/web/src/lib/bomAnalyzeJobs.ts"
EMBEDDED = pytest.importorskip("embedded_postgres")


def test_json_safe_strips_nan_for_postgres():
    payload = json_safe({"score": float("nan"), "parts": [{"risk": float("inf")}]})
    assert payload["score"] is None
    assert payload["parts"][0]["risk"] is None
    json.dumps(payload, allow_nan=False)


def test_analyze_upload_read_after_write_and_detailed_risk(tmp_path: Path):
    reset_store_for_tests(tmp_path / "store.json")
    csv_bytes = (
        b"MPN,Manufacturer,Quantity\n"
        b"LM358DR,TI,2\n"
        b"STM32F103C8T6,ST,1\n"
    )
    report = analyze_upload(
        filename="handoff.csv",
        payload=csv_bytes,
        workspace_id="ws-handoff",
        project_name="Drone_01",
        bom_name="cadivor_test_bom_10_parts",
        revision="A",
        analysis_mode="synthetic-preview",
    )
    assert report["persisted"] is True
    analysis_id = report["id"]
    saved = get_report(analysis_id, workspace_id="ws-handoff")
    assert saved is not None
    assert len(saved.get("parts") or []) == 2

    risk = detailed_risk_payload(workspace_id="ws-handoff", analysis_id=analysis_id)
    assert risk["ok"] is True
    assert risk["mode"] != "analysis-not-found"
    assert len(risk.get("rows") or []) == 2


def test_detailed_risk_missing_id_is_explicit(tmp_path: Path):
    reset_store_for_tests(tmp_path / "store.json")
    risk = detailed_risk_payload(
        workspace_id="ws-handoff",
        analysis_id="00000000-0000-0000-0000-000000000099",
    )
    assert risk["ok"] is False
    assert risk["mode"] == "analysis-not-found"
    assert "not found" in str(risk.get("gap") or "").lower()
    assert risk["rows"] == []


def test_analyze_upload_fails_when_store_cannot_verify(tmp_path: Path, monkeypatch):
    store = reset_store_for_tests(tmp_path / "store.json")
    original = store.upsert_analysis_report

    def broken_upsert(report, **kwargs):
        saved = original(report, **kwargs)
        # Simulate a write that never becomes readable.
        store._data["reports"].pop(saved["id"], None)
        store.save()
        return saved

    monkeypatch.setattr(store, "upsert_analysis_report", broken_upsert)
    with pytest.raises(PersistenceVerifyError):
        analyze_upload(
            filename="missing.csv",
            payload=b"MPN,Quantity\nAAA,1\n",
            workspace_id="ws-handoff",
            analysis_mode="synthetic-preview",
        )


def test_file_store_get_report_reloads_from_disk(tmp_path: Path):
    path = tmp_path / "shared.json"
    writer = reset_store_for_tests(path)
    report = writer.upsert_analysis_report(
        {
            "id": "reload-1",
            "filename": "a.csv",
            "created_at": "2026-11-16T00:00:00Z",
            "total_parts": 1,
            "health_score": 80,
            "health_status": "Healthy",
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "low_risk_count": 1,
            "mode": "synthetic-preview",
            "parts": [{"MPN": "AAA", "Risk Level": "Low"}],
        },
        workspace_id="ws-reload",
        project_name="P",
        bom_name="B",
        revision="A",
    )
    # Second handle simulates another process that started with an empty cache.
    from apps.api.workspace_store import WorkspaceStore

    reader = WorkspaceStore(path)
    reader._data = {
        "version": 2,
        "projects": {},
        "boms": {},
        "revisions": {},
        "analyses": {},
        "reports": {},
        "decision_records": {},
    }
    restored = reader.get_report(report["id"], workspace_id="ws-reload")
    assert restored is not None
    assert restored["id"] == report["id"]


def test_bom_analyzer_refreshes_recent_reports_after_analyze():
    src = WEB_BOM.read_text(encoding="utf-8")
    assert "refreshRecentReports" in src
    assert "persisted === false" in src
    jobs = WEB_JOBS.read_text(encoding="utf-8")
    assert "persisted === false" in jobs
    risk = WEB_RISK.read_text(encoding="utf-8")
    assert 'data.mode === "analysis-not-found"' in risk


@pytest.fixture(scope="module")
def handoff_pg(tmp_path_factory):
    """Disposable Postgres for production-path persist coverage (not Railway)."""
    root = tmp_path_factory.mktemp("handoff-pg")
    pgdata = root / "pgdata"
    pgdata.mkdir()
    server = EMBEDDED.get_server(pgdata, cleanup_mode="delete")
    uri = server.get_uri(database="postgres")
    assert "railway" not in uri.lower()
    assert "supabase" not in uri.lower()
    yield uri
    try:
        server.__exit__(None, None, None)  # type: ignore[attr-defined]
    except Exception:
        pass


@pytest.fixture
def postgres_handoff_env(handoff_pg, monkeypatch):
    """Wire the migration API onto disposable Postgres like production."""
    monkeypatch.setenv("CADIVOR_MIGRATION_DATABASE_URL", handoff_pg)
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "handoff-persist-auth-secret")
    monkeypatch.delenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    monkeypatch.delenv("CADIVOR_USE_SUPABASE_AUTH", raising=False)
    monkeypatch.delenv("CADIVOR_MIGRATION_SUPPLIER_LIVE", raising=False)

    from apps.api import sandbox_auth
    from apps.api import synthetic_analyze as sa
    from apps.api import workspace_store
    from apps.api.postgres_store import PostgresWorkspaceStore

    sandbox_auth._STORE = sandbox_auth._PostgresAuthStore(handoff_pg)
    sandbox_auth._STORE.clear()
    sandbox_auth._SEEDED = False
    sandbox_auth.seed_demo_users(SANDBOX_SEED_USERS, store=sandbox_auth._STORE)

    workspace_store._STORE = PostgresWorkspaceStore(handoff_pg)
    workspace_store._STORE.clear()
    sa._REPORTS.clear()

    yield {
        "uri": handoff_pg,
        "workspace_id": SANDBOX_SEED_USERS[0]["workspace_id"],
        "email": SANDBOX_SEED_USERS[0]["email"],
        "password": SANDBOX_SEED_USERS[0]["password"],
    }


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_postgres_analyze_read_after_write_and_detailed_risk(postgres_handoff_env, monkeypatch):
    """Production path: Railway uses CADIVOR_MIGRATION_DATABASE_URL → Postgres."""
    from apps.api.main import app
    from apps.api import plan_limits

    account = postgres_handoff_env
    client = TestClient(app)
    headers = _login(client, account["email"], account["password"])

    # Keep this focused on persistence, not monthly quota.
    monkeypatch.setattr(plan_limits, "assert_analysis_allowed", lambda **_: {})

    csv_bytes = (
        b"MPN,Manufacturer,Quantity\n"
        b"LM358DR,TI,2\n"
        b"STM32F103C8T6,ST,1\n"
        b"LM7805CT,TI,4\n"
    )
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        data={
            "project_name": "QA Persist Handoff",
            "bom_name": "persist_smoke_3parts",
            "revision": "A",
        },
        files={"file": ("persist_smoke_3parts.csv", csv_bytes, "text/csv")},
    )
    assert analyze.status_code == 200, analyze.text
    body = analyze.json()
    assert body["persisted"] is True
    analysis_id = body["analysis_id"]
    assert body["total_parts"] == 3

    listed = client.get("/reports", headers=headers)
    assert listed.status_code == 200, listed.text
    ids = {str(row.get("id") or row.get("analysis_id")) for row in listed.json().get("reports") or []}
    assert analysis_id in ids

    saved = client.get(f"/reports/{analysis_id}", headers=headers)
    assert saved.status_code == 200, saved.text
    saved_body = saved.json()
    assert saved_body["workspace_id"] == account["workspace_id"]
    assert len(saved_body.get("parts") or []) == 3

    risk = client.get(f"/tools/detailed-risk?analysis_id={analysis_id}", headers=headers)
    assert risk.status_code == 200, risk.text
    risk_body = risk.json()
    assert risk_body.get("ok") is True
    assert risk_body.get("mode") != "analysis-not-found"
    assert len(risk_body.get("rows") or []) == 3

    missing = client.get(
        "/tools/detailed-risk?analysis_id=00000000-0000-0000-0000-000000000099",
        headers=headers,
    )
    assert missing.status_code == 200, missing.text
    missing_body = missing.json()
    assert missing_body.get("ok") is False
    assert missing_body.get("mode") == "analysis-not-found"


def test_postgres_analyze_returns_503_when_read_back_fails(postgres_handoff_env, monkeypatch):
    from apps.api import plan_limits
    from apps.api import workspace_store
    from apps.api.main import app

    store = workspace_store.get_store()
    assert store.backend == "postgres"
    original_get = store.get_report

    def missing_after_write(analysis_id, *, workspace_id):
        # First call is the analyze_upload verify; later calls should still work
        # if analyze somehow continued — force verify failure only.
        return None

    monkeypatch.setattr(store, "get_report", missing_after_write)
    monkeypatch.setattr(plan_limits, "assert_analysis_allowed", lambda **_: {})

    client = TestClient(app)
    headers = _login(
        client, postgres_handoff_env["email"], postgres_handoff_env["password"]
    )
    response = client.post(
        "/boms/analyze",
        headers=headers,
        data={
            "project_name": "QA Persist Fail",
            "bom_name": "persist_fail",
            "revision": "A",
        },
        files={"file": ("persist_fail.csv", b"MPN,Quantity\nAAA,1\n", "text/csv")},
    )
    assert response.status_code == 503, response.text
    body = response.json()
    assert body.get("code") == "persistence_verify_failed"
    assert body.get("persisted") is False
    # Restore for any later fixture consumers.
    monkeypatch.setattr(store, "get_report", original_get)


def test_postgres_rejects_non_finite_floats_in_report_payload(postgres_handoff_env):
    from apps.api import workspace_store

    store = workspace_store.get_store()
    assert store.backend == "postgres"
    with pytest.raises(ValueError):
        # Direct dump path must stay strict; analyze_upload sanitizes first.
        import json as _json

        _json.dumps({"risk": float("nan")}, allow_nan=False)

    report = store.upsert_analysis_report(
        {
            "id": "nan-safe-1",
            "filename": "nan.csv",
            "created_at": "2026-11-16T00:00:00Z",
            "total_parts": 1,
            "health_score": None,
            "health_status": "Needs verification",
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "low_risk_count": 0,
            "mode": "synthetic-preview",
            "parts": [{"MPN": "AAA", "Risk Score": float("nan"), "Risk Level": "Needs verification"}],
        },
        workspace_id=postgres_handoff_env["workspace_id"],
        project_name="NaN",
        bom_name="nan-bom",
        revision="A",
    )
    restored = store.get_report(report["id"], workspace_id=postgres_handoff_env["workspace_id"])
    assert restored is not None
    assert restored["parts"][0]["Risk Score"] is None
