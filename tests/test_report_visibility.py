import asyncio
import json
from pathlib import Path

from apps.api.report_visibility import (
    customer_visible_analyses,
    customer_visible_projects,
    is_internal_test_fixture_analysis,
)


def test_only_explicit_fixture_metadata_marks_an_analysis_internal():
    fixtures = [
        {"id": "explicit", "internal_test_fixture": True},
        {"id": "legacy-explicit", "is_test_fixture": True},
    ]

    assert all(is_internal_test_fixture_analysis(row) for row in fixtures)


def test_customer_names_and_filenames_do_not_hide_a_saved_analysis():
    row = {
        "id": "customer-test-bom",
        "project_name": "Drone_02",
        "bom_name": "cadivor_test_bom_10_parts",
        "filename": "cadivor_test_bom_10_parts.csv",
        "revision": "A",
    }

    assert not is_internal_test_fixture_analysis(row)
    assert customer_visible_analyses([row], production=True) == [row]


def test_real_work_analysis_and_smoke_detector_names_are_not_hidden():
    real_reports = [
        {"id": "real", "project_name": "Radar X-Band", "bom_name": "Power Supply"},
        {"id": "detector", "project_name": "Smoke Detector Controller", "bom_name": "rev A"},
        {"id": "qa-project", "project_name": "QA Controller Validation"},
        {"id": "synthetic-project", "project_name": "Synthetic Preview Assembly"},
        {"id": "supplier-estimate", "project_name": "Pump Controller", "mode": "synthetic-preview"},
    ]

    assert not any(is_internal_test_fixture_analysis(row) for row in real_reports)


def test_fixture_filter_applies_only_to_production_customer_lists():
    rows = [
        {"id": "fixture", "project_name": "Synthetic Smoke Test", "internal_test_fixture": True},
        {"id": "customer", "project_name": "Motor Controller"},
    ]

    assert [row["id"] for row in customer_visible_analyses(rows, production=True)] == ["customer"]
    assert customer_visible_analyses(rows, production=False) == rows


def test_project_summaries_hide_fixtures_and_restore_last_visible_revision():
    reports = [
        {
            "id": "fixture-new",
            "bom_id": "bom-real",
            "project_id": "project-real",
            "project_name": "Motor Controller",
            "bom_name": "Power Board",
            "filename": "Synthetic_Smoke_Run.csv",
            "internal_test_fixture": True,
        },
        {
            "id": "customer-old",
            "bom_id": "bom-real",
            "project_id": "project-real",
            "project_name": "Motor Controller",
            "bom_name": "Power Board",
            "health_score": 82,
            "high_risk_count": 1,
        },
        {
            "id": "fixture-only",
            "bom_id": "bom-test",
            "project_id": "project-test",
            "project_name": "Synthetic Smoke Test",
            "bom_name": "QA BOM",
            "internal_test_fixture": True,
        },
    ]
    projects = [
        {
            "id": "project-real",
            "name": "Motor Controller",
            "boms": [
                {
                    "id": "bom-real",
                    "name": "Power Board",
                    "latest_analysis_id": "fixture-new",
                }
            ],
        },
        {
            "id": "project-test",
            "name": "Synthetic Smoke Test",
            "internal_test_fixture": True,
            "boms": [
                {
                    "id": "bom-test",
                    "name": "QA BOM",
                    "latest_analysis_id": "fixture-only",
                    "internal_test_fixture": True,
                }
            ],
        },
    ]

    visible = customer_visible_projects(projects, reports, production=True)

    assert [project["id"] for project in visible] == ["project-real"]
    assert visible[0]["bom_count"] == 1
    assert visible[0]["boms"][0]["latest_analysis_id"] == "customer-old"
    assert visible[0]["boms"][0]["health_score"] == 82


def test_customer_visible_projects_are_unchanged_outside_production():
    projects = [{"id": "fixture", "name": "Synthetic Smoke Test", "boms": []}]

    assert customer_visible_projects(projects, [], production=False) == projects


def test_plan_usage_counts_unique_customer_boms_and_excludes_production_fixtures(monkeypatch):
    from apps.api import plan_limits

    class Store:
        def list_reports(self, *, workspace_id):
            assert workspace_id == "w"
            return [
                {"id": "a1", "bom_id": "bom-1", "created_at": "2026-11-04T12:00:00Z"},
                {"id": "a2", "bom_id": "bom-1", "created_at": "2026-11-05T12:00:00Z"},
                {"id": "a3", "bom_id": "bom-2", "created_at": "2026-11-06T12:00:00Z"},
                {
                    "id": "qa",
                    "bom_id": "bom-qa",
                    "project_name": "Synthetic Smoke Test",
                    "created_at": "2026-11-07T12:00:00Z",
                    "internal_test_fixture": True,
                },
            ]

    monkeypatch.setattr(plan_limits, "get_store", lambda: Store())
    monkeypatch.setattr(plan_limits, "is_production_runtime", lambda: True)
    monkeypatch.setattr(plan_limits, "_month_key", lambda: "2026-11")

    snapshot = plan_limits.usage_snapshot("w", {"plan": "Professional"})

    assert snapshot["usage"]["saved_boms"] == 2
    assert snapshot["usage"]["analyses_this_month"] == 3


def test_production_reports_endpoint_hides_internal_fixture_rows(monkeypatch):
    from apps.api import main

    rows = [
        {
            "id": "fixture",
            "project_name": "Cadivor Synthetic E2E QA Test",
            "internal_test_fixture": True,
        },
        {"id": "customer", "project_name": "Motor Controller"},
        {
            "id": "customer-test-bom",
            "project_name": "Drone_02",
            "bom_name": "cadivor_test_bom_10_parts",
            "filename": "cadivor_test_bom_10_parts.csv",
            "revision": "A",
        },
    ]
    monkeypatch.setattr(main, "_auth_context", lambda _request: ({"workspace_id": "w"}, None))
    monkeypatch.setattr(main, "describe_persistence", lambda: {"backend": "postgres"})
    monkeypatch.setattr(main, "list_reports", lambda *, workspace_id: rows)
    monkeypatch.setattr(main, "is_production_runtime", lambda: True)

    response = asyncio.run(main.reports_list(None))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert [row["id"] for row in payload["reports"]] == ["customer", "customer-test-bom"]
    assert payload["mode"] == "workspace-reports"


def test_production_home_uses_production_visibility(monkeypatch):
    from apps.api import main

    class Store:
        def home_dashboard(self, *, workspace_id, production):
            assert workspace_id == "w"
            assert production is True
            return {"ok": True, "mode": "workspace-home", "metrics": {}}

    monkeypatch.setattr(main, "_auth_context", lambda _request: ({"workspace_id": "w"}, None))
    monkeypatch.setattr(main, "get_store", lambda: Store())
    monkeypatch.setattr(main, "list_reports_with_parts", lambda *, workspace_id: ([], []))
    monkeypatch.setattr(main, "is_production_runtime", lambda: True)

    response = asyncio.run(main.workspace_home(None))

    assert response.status_code == 200
    assert json.loads(response.body)["mode"] == "workspace-home"


def test_production_direct_report_route_hides_internal_fixture(monkeypatch):
    from types import SimpleNamespace

    from apps.api import main

    monkeypatch.setattr(main, "_auth_context", lambda _request: ({"workspace_id": "w"}, None))
    monkeypatch.setattr(
        main,
        "get_report",
        lambda *_args, **_kwargs: {
            "id": "qa",
            "project_name": "Synthetic Smoke Test",
            "internal_test_fixture": True,
        },
    )
    monkeypatch.setattr(main, "is_production_runtime", lambda: True)

    response = asyncio.run(
        main.reports_get(SimpleNamespace(path_params={"analysis_id": "qa"}))
    )

    assert response.status_code == 404


def test_production_direct_report_route_keeps_user_test_bom_visible(monkeypatch):
    from apps.api import main

    report = {
        "id": "customer-test-bom",
        "project_name": "Drone_02",
        "bom_name": "cadivor_test_bom_10_parts",
        "filename": "cadivor_test_bom_10_parts.csv",
        "revision": "A",
    }
    monkeypatch.setattr(main, "get_report", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(main, "is_production_runtime", lambda: True)

    assert main._get_visible_report("customer-test-bom", workspace_id="w") is report


def test_missing_or_hidden_monitoring_analysis_returns_empty_workspace_state(monkeypatch):
    from apps.api import migration_tools

    monkeypatch.setattr(migration_tools, "_require_analysis", lambda *_args, **_kwargs: None)

    payload = migration_tools.monitoring_payload(
        workspace_id="w", analysis_id="hidden-qa-analysis"
    )

    assert payload["analysis_id"] is None
    assert payload["mode"] == "workspace-monitoring"
    assert payload["alerts"] == []


def test_procurement_page_does_not_show_empty_synthetic_preview_counter():
    source = (
        Path(__file__).resolve().parents[1]
        / "apps/web/src/app/procurement/page.tsx"
    ).read_text(encoding="utf-8")

    assert "synthetic/preview:" not in source
    assert "const sourcingBadge = partsTotal" in source
    assert "{sourcingBadge ? (" in source
    assert "Synthetic estimates:" in source


def test_bom_analyzer_does_not_restore_local_internal_test_draft_or_advertise_demo_data():
    root = Path(__file__).resolve().parents[1]
    page = (root / "apps/web/src/app/bom-analyzer/page.tsx").read_text(encoding="utf-8")
    draft = (root / "apps/web/src/lib/bomDraft.ts").read_text(encoding="utf-8")

    assert "isInternalTestDraft(meta)" in page
    assert "A test-only draft was not loaded." in page
    assert "synthetic sample BOM data" not in page
    assert "export function isInternalTestDraft" in draft


def test_cadivor_brand_is_a_real_home_link_on_workspace_and_auth_screens():
    root = Path(__file__).resolve().parents[1]
    shell = (root / "apps/web/src/components/Shell.tsx").read_text(encoding="utf-8")
    brand = (root / "apps/web/src/components/BrandLink.tsx").read_text(encoding="utf-8")
    login = (root / "apps/web/src/app/login/page.tsx").read_text(encoding="utf-8")
    signup = (root / "apps/web/src/app/signup/page.tsx").read_text(encoding="utf-8")
    reset = (root / "apps/web/src/app/reset-password/page.tsx").read_text(encoding="utf-8")

    assert '<BrandLink href="/" ariaLabel="Cadivor workspace home" />' in shell
    assert 'href="https://www.cadivor.com/"' in login
    assert 'href="https://www.cadivor.com/"' in signup
    assert 'href="https://www.cadivor.com/"' in reset
    assert 'aria-label={ariaLabel}' in brand


def test_monitoring_page_clears_stale_hidden_analysis_selection():
    page = (
        Path(__file__).resolve().parents[1]
        / "apps/web/src/app/monitoring/page.tsx"
    ).read_text(encoding="utf-8")

    assert 'const visibleAnalysisId = String(payload.analysis_id || "").trim();' in page
    assert "setActiveAnalysisId(visibleAnalysisId);" in page
    assert "if (visibleAnalysisId)" in page


def test_settings_compliance_summary_renders_fields_instead_of_object_string():
    page = (
        Path(__file__).resolve().parents[1]
        / "apps/web/src/app/settings/page.tsx"
    ).read_text(encoding="utf-8")

    assert "const complianceSummary = asRecord(compliance?.summary);" in page
    assert '["Evidence linked", complianceSummary.evidence_linked]' in page
    assert "String(value).slice(0, 120)" in page
    assert "Object.entries(compliance || {})" not in page
