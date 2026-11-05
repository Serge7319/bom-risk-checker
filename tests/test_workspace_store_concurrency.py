"""Local preview store: concurrent writes + workspace isolation expectations."""
from __future__ import annotations

import threading
from pathlib import Path

from apps.api.workspace_store import WorkspaceStore


def test_concurrent_upserts_do_not_corrupt_json(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "store.json")
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            report = {
                "id": f"analysis-{i}",
                "filename": f"bom-{i}.csv",
                "created_at": f"2026-11-04T00:00:{i:02d}Z",
                "total_parts": 1,
                "health_score": 90,
                "health_status": "Healthy",
                "high_risk_count": 0,
                "medium_risk_count": 0,
                "low_risk_count": 1,
                "mode": "synthetic-preview",
                "parts": [{"MPN": f"P{i}", "Risk Level": "Low"}],
                "hierarchy": None,
            }
            store.upsert_analysis_report(
                report,
                project_name=f"Project-{i % 3}",
                bom_name=f"BOM-{i}",
                revision="A",
                workspace_id="smoke-workspace",
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    reloaded = WorkspaceStore(tmp_path / "store.json")
    assert len(reloaded.list_reports(workspace_id="smoke-workspace")) == 12
    # JSON still loadable / structurally intact
    assert reloaded.path.exists()


def test_home_dashboard_is_tenant_isolated(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "iso.json")
    for wid, name in (("ws-a", "Alpha"), ("ws-b", "Beta")):
        store.upsert_analysis_report(
            {
                "id": f"id-{wid}",
                "filename": f"{name}.csv",
                "created_at": "2026-11-04T01:00:00Z",
                "total_parts": 1,
                "health_score": 80,
                "health_status": "Healthy",
                "high_risk_count": 0,
                "medium_risk_count": 0,
                "low_risk_count": 1,
                "mode": "synthetic-preview",
                "parts": [],
            },
            project_name=name,
            bom_name=name,
            revision="A",
            workspace_id=wid,
        )
    home_a = store.home_dashboard(workspace_id="ws-a")
    home_b = store.home_dashboard(workspace_id="ws-b")
    assert {p["name"] for p in home_a["projects"]} == {"Alpha"}
    assert {p["name"] for p in home_b["projects"]} == {"Beta"}
    assert home_a["metrics"]["active_projects"] == 1
    assert home_b["metrics"]["active_projects"] == 1
