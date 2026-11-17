"""BOM analyze must persist before clients can open detailed risk."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api.json_safe import json_safe
from apps.api.migration_tools import detailed_risk_payload
from apps.api.synthetic_analyze import (
    PersistenceVerifyError,
    analyze_upload,
    get_report,
)
from apps.api.workspace_store import reset_store_for_tests


ROOT = Path(__file__).resolve().parents[1]
WEB_BOM = ROOT / "apps/web/src/app/bom-analyzer/page.tsx"
WEB_RISK = ROOT / "apps/web/src/app/detailed-risk-report/page.tsx"
WEB_JOBS = ROOT / "apps/web/src/lib/bomAnalyzeJobs.ts"


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
