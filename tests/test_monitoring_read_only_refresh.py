"""Acceptance E: monitoring GET is read-only; refresh is explicit and scoped.

Also proves the scheduler dry-run path never reaches email delivery.
No live scheduler, supplier, or email transport is used.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api import migration_tools, monitoring_scheduler, monitoring_store
from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

WS = "ws-monitoring-test"


def _report(analysis_id: str = "an-1", **overrides):
    report = {
        "id": analysis_id,
        "workspace_id": WS,
        "mode": "synthetic-preview",
        "filename": "bom.csv",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_parts": 3,
        "parts": [
            {"MPN": "AAA111", "Risk Level": "High", "Lifecycle": "Active"},
            {"MPN": "BBB222", "Risk Level": "Low", "Lifecycle": "NRND"},
            {
                "MPN": "CCC333",
                "Risk Level": "Medium",
                "Lifecycle": "Active",
                "provider_health": {
                    "has_verified_data": False,
                    "failed_sources": ["Newark"],
                    "summary_message": "Newark timed out.",
                },
            },
        ],
    }
    report.update(overrides)
    return report


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    monkeypatch.delenv("CADIVOR_MONITORING_EMAIL_ENABLED", raising=False)
    monkeypatch.delenv("CADIVOR_MONITORING_SCHEDULER_ENABLED", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    monitoring_store.reset_monitoring_store_for_tests()
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()


@pytest.fixture
def saved_report(monkeypatch: pytest.MonkeyPatch):
    reports = {"an-1": _report("an-1"), "an-2": _report("an-2")}
    monkeypatch.setattr(
        migration_tools,
        "_require_analysis",
        lambda analysis_id, *, workspace_id: reports.get(analysis_id or "an-1"),
    )
    monkeypatch.setattr(
        migration_tools,
        "list_reports",
        lambda *, workspace_id: [{"id": key} for key in reports],
    )
    monkeypatch.setattr(
        migration_tools,
        "get_report",
        lambda analysis_id, *, workspace_id: reports.get(analysis_id),
    )
    return reports


def _forbid_writes(monkeypatch: pytest.MonkeyPatch):
    def boom(*args, **kwargs):
        raise AssertionError("monitoring read path attempted a write")

    monkeypatch.setattr(monitoring_store, "persist_alerts", boom)
    monkeypatch.setattr(monitoring_store, "record_refresh", boom)


def test_monitoring_payload_never_persists_or_records_refresh(
    saved_report, monkeypatch: pytest.MonkeyPatch
):
    _forbid_writes(monkeypatch)
    first = migration_tools.monitoring_payload(workspace_id=WS, analysis_id="an-1")
    second = migration_tools.monitoring_payload(workspace_id=WS, analysis_id="an-1")
    assert first["read_only"] is True
    assert len(first["alerts"]) == 3  # AAA111 risk, BBB222 lifecycle, CCC333 risk
    assert all(a["persisted"] is False for a in first["alerts"])
    assert first["metrics"]["unpersisted_alerts"] == 3
    assert first["refresh"] is None
    assert first["freshness"]["never_refreshed"] is True
    assert first["freshness"]["stale"] is True
    assert first["freshness"]["live_supplier_refresh"] is False
    assert [a["part_number"] for a in first["alerts"]] == [
        a["part_number"] for a in second["alerts"]
    ]


def test_get_route_leaves_store_untouched(saved_report):
    client = TestClient(app)
    login = client.post(
        "/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    ws = login.json().get("workspace_id") or login.json().get("user", {}).get("workspace_id")
    res = client.get("/tools/monitoring", headers=headers, params={"analysis_id": "an-1"})
    assert res.status_code == 200, res.text
    assert res.json()["read_only"] is True
    alerts = client.get("/tools/monitoring/alerts", headers=headers).json()
    assert alerts["alerts"] == []
    assert alerts["refresh_history"] == []
    assert ws is None or monitoring_store.list_alerts(ws) == []


def test_explicit_refresh_persists_and_reads_back_with_provenance(saved_report):
    result = migration_tools.monitoring_refresh_payload(workspace_id=WS, analysis_id="an-1")
    assert result["scope"] == "analysis"
    assert result["analysis_id"] == "an-1"
    assert result["live_supplier_refresh"] is False
    assert result["refresh"]["scope"] == "analysis"

    view = migration_tools.monitoring_payload(workspace_id=WS, analysis_id="an-1")
    assert view["metrics"]["unpersisted_alerts"] == 0
    assert all(a["persisted"] and a.get("id") for a in view["alerts"])
    assert view["freshness"]["never_refreshed"] is False
    assert view["freshness"]["stale"] is False
    assert view["refresh"]["id"] == result["refresh"]["id"]
    # The other analysis is not touched by a scoped refresh.
    assert monitoring_store.list_alerts(WS, analysis_id="an-2") == []


def test_per_part_refresh_only_touches_selected_part(saved_report):
    result = migration_tools.monitoring_refresh_payload(
        workspace_id=WS, analysis_id="an-1", part_number="aaa111"
    )
    assert result["scope"] == "part"
    assert result["part_number"] == "aaa111"
    assert {a["part_number"] for a in result["alerts"]} == {"AAA111"}
    stored = monitoring_store.list_alerts(WS, analysis_id="an-1")
    assert {a["part_number"] for a in stored} == {"AAA111"}
    assert monitoring_store.list_refresh_history(WS)[0]["part_number"] == "aaa111"

    with pytest.raises(ValueError):
        migration_tools.monitoring_refresh_payload(
            workspace_id=WS, analysis_id="an-1", part_number="NOPE"
        )


def test_refresh_requires_analysis_or_explicit_portfolio(saved_report):
    with pytest.raises(ValueError):
        migration_tools.monitoring_refresh_payload(workspace_id=WS)
    with pytest.raises(ValueError):
        migration_tools.monitoring_refresh_payload(
            workspace_id=WS, analysis_id="an-1", portfolio=True
        )
    result = migration_tools.monitoring_refresh_payload(workspace_id=WS, portfolio=True)
    assert result["scope"] == "portfolio"
    assert "Portfolio-wide" in result["scope_label"]
    assert set(result["analysis_ids"]) == {"an-1", "an-2"}
    assert {a["analysis_id"] for a in result["alerts"]} == {"an-1", "an-2"}


def test_refresh_route_requires_scope(saved_report):
    client = TestClient(app)
    login = client.post(
        "/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    missing = client.post("/tools/monitoring/refresh", headers=headers)
    assert missing.status_code == 400
    conflicting = client.post(
        "/tools/monitoring/refresh",
        headers=headers,
        params={"scope": "portfolio", "analysis_id": "an-1"},
    )
    assert conflicting.status_code == 400


def test_stale_and_provider_failure_are_surfaced(saved_report, monkeypatch):
    migration_tools.monitoring_refresh_payload(workspace_id=WS, analysis_id="an-1")
    old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    monkeypatch.setattr(
        monitoring_store,
        "list_refresh_history",
        lambda workspace_id: [
            {"id": "r", "analysis_id": "an-1", "ran_at": old, "scope": "analysis"}
        ],
    )
    view = migration_tools.monitoring_payload(workspace_id=WS, analysis_id="an-1")
    assert view["freshness"]["stale"] is True
    assert view["freshness"]["stale_reason"] == "refresh_older_than_threshold"
    assert view["freshness"]["last_refresh_at"] == old
    status = {row["part_number"]: row for row in view["part_status"]}
    assert status["CCC333"]["provider_failure"] is True
    assert status["CCC333"]["failed_sources"] == ["Newark"]
    assert status["AAA111"]["provider_failure"] is False
    assert view["metrics"]["provider_failures"] == 1


def _forbid_email(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def no_deliver(*args, **kwargs):
        calls.append("deliver_alert_email")
        raise AssertionError("alert email delivery must not run")

    def no_send(*args, **kwargs):
        calls.append("send_transactional_email")
        raise AssertionError("transactional email must not be sent")

    monkeypatch.setattr(monitoring_store, "deliver_alert_email", no_deliver)
    import src.email_delivery as email_delivery

    monkeypatch.setattr(email_delivery, "send_transactional_email", no_send)
    return calls


def test_scheduler_dry_run_sends_no_email_and_writes_nothing(
    saved_report, monkeypatch: pytest.MonkeyPatch
):
    monitoring_store.update_preferences(WS, {"email_alerts": True})
    # Even with delivery fully "enabled", dry-run must not reach delivery.
    monkeypatch.setenv("CADIVOR_MONITORING_EMAIL_ENABLED", "1")
    calls = _forbid_email(monkeypatch)
    _forbid_writes(monkeypatch)

    result = monitoring_scheduler.run_workspace_refresh(
        WS, analysis_id="an-1", dry_run=True
    )

    assert result["dry_run"] is True
    assert result["persisted"] is False
    assert result["notifications"] == []
    assert result["alert_count"] == 3
    assert calls == []
    assert monitoring_store.recorded_emails() == []


def test_scheduler_refresh_with_email_disabled_never_sends(
    saved_report, monkeypatch: pytest.MonkeyPatch
):
    monitoring_store.update_preferences(WS, {"email_alerts": True})
    calls = _forbid_email(monkeypatch)  # delivery flag is off in this test

    result = monitoring_scheduler.run_workspace_refresh(WS, analysis_id="an-1")

    assert result["persisted"] is True
    assert result["email_delivery_enabled"] is False
    assert result["notifications"] == []
    assert calls == []
    assert result["live_supplier_refresh"] is False
