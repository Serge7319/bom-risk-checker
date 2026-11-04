"""Store selection + schema contracts for sandbox Postgres persistence."""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.workspace_store import (
    PersistenceNotConfiguredError,
    describe_persistence,
    get_store,
    migration_database_url,
    reset_store_for_tests,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "apps/api/schema/sandbox_workspace.sql"


def test_schema_defines_workspace_scoped_tables():
    sql = SCHEMA.read_text(encoding="utf-8")
    for table in (
        "migration_projects",
        "migration_boms",
        "migration_revisions",
        "migration_analyses",
        "migration_reports",
    ):
        assert table in sql
    assert "workspace_id" in sql
    assert "ON DELETE CASCADE" in sql


def test_describe_persistence_never_uses_production_supabase(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SUPABASE_URL", "https://prod.example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    info = describe_persistence()
    assert info["backend"] == "local-file-preview"
    assert info["durable_across_redeploy"] is False
    assert migration_database_url() == ""


def test_railway_without_database_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", raising=False)
    # Clear singleton
    import apps.api.workspace_store as ws

    ws._STORE = None
    info = describe_persistence()
    assert info["backend"] == "unconfigured"
    assert info["durable_across_redeploy"] is False
    with pytest.raises(PersistenceNotConfiguredError):
        get_store()


def test_database_url_selects_postgres_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "CADIVOR_MIGRATION_DATABASE_URL", "postgresql://user:pass@localhost:5432/sandbox"
    )
    monkeypatch.delenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", raising=False)
    info = describe_persistence()
    assert info["backend"] == "postgres"
    assert info["durable_across_redeploy"] is True
    assert info["database_configured"] is True


def test_ephemeral_file_store_still_works_for_tests(tmp_path: Path):
    store = reset_store_for_tests(tmp_path / "t.json")
    assert store.backend == "file"
    assert store.durable_across_redeploy is False
    report = store.upsert_analysis_report(
        {
            "id": "a1",
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
        project_name="P",
        bom_name="B",
        revision="A",
    )
    assert store.delete_analysis(report["id"], workspace_id="ws-a") is True
    report2 = store.upsert_analysis_report(
        {
            "id": "a2",
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
        project_name="P2",
        bom_name="B2",
        revision="A",
    )
    from apps.api.workspace_store import WorkspaceAccessError

    with pytest.raises(WorkspaceAccessError):
        store.delete_analysis(report2["id"], workspace_id="ws-b")
