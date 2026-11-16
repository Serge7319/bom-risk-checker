import asyncio
import json
from pathlib import Path

from apps.api.report_visibility import (
    customer_visible_analyses,
    is_internal_test_fixture_analysis,
)


def test_explicitly_named_qa_and_demo_analyses_are_internal_fixtures():
    fixtures = [
        {"project_name": "PR620 Synthetic Intake Smoke", "bom_name": "Demo Controller BOM"},
        {"project_name": "PR603 Production Nested Smoke 2026-11-11", "revision": "QA-603-NESTED"},
        {"project_name": "Cadivor Synthetic E2E QA Test"},
        {"project_name": "Demo Product Line", "bom_name": "Test_BOM2"},
    ]

    assert all(is_internal_test_fixture_analysis(row) for row in fixtures)


def test_real_work_analysis_and_smoke_detector_names_are_not_hidden():
    real_reports = [
        {"id": "real", "project_name": "Radar X-Band", "bom_name": "Power Supply"},
        {"id": "detector", "project_name": "Smoke Detector Controller", "bom_name": "rev A"},
        {"id": "supplier-estimate", "project_name": "Pump Controller", "mode": "synthetic-preview"},
    ]

    assert not any(is_internal_test_fixture_analysis(row) for row in real_reports)


def test_fixture_filter_applies_only_to_production_customer_lists():
    rows = [
        {"id": "fixture", "project_name": "Synthetic Smoke Test"},
        {"id": "customer", "project_name": "Motor Controller"},
    ]

    assert [row["id"] for row in customer_visible_analyses(rows, production=True)] == ["customer"]
    assert customer_visible_analyses(rows, production=False) == rows


def test_production_reports_endpoint_hides_internal_fixture_rows(monkeypatch):
    from apps.api import main

    rows = [
        {"id": "fixture", "project_name": "Cadivor Synthetic E2E QA Test"},
        {"id": "customer", "project_name": "Motor Controller"},
    ]
    monkeypatch.setattr(main, "_auth_context", lambda _request: ({"workspace_id": "w"}, None))
    monkeypatch.setattr(main, "describe_persistence", lambda: {"backend": "postgres"})
    monkeypatch.setattr(main, "list_reports", lambda *, workspace_id: rows)
    monkeypatch.setattr(main, "is_production_runtime", lambda: True)

    response = asyncio.run(main.reports_list(None))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert [row["id"] for row in payload["reports"]] == ["customer"]
    assert payload["mode"] == "workspace-reports"


def test_procurement_page_does_not_show_empty_synthetic_preview_counter():
    source = (
        Path(__file__).resolve().parents[1]
        / "apps/web/src/app/procurement/page.tsx"
    ).read_text(encoding="utf-8")

    assert "synthetic/preview:" not in source
    assert "const sourcingBadge = partsTotal" in source
    assert "{sourcingBadge ? (" in source
    assert "Synthetic estimates:" in source
