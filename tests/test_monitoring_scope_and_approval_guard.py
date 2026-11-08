"""Monitoring selected-analysis scope + approve-alternate conflict guard."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api import monitoring_store
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
    monkeypatch.delenv("CADIVOR_MONITORING_SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("CADIVOR_MONITORING_EMAIL_ENABLED", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    monitoring_store.reset_monitoring_store_for_tests()
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()


def _auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _analyze_csv(client: TestClient, headers: dict[str, str], name: str, csv_bytes: bytes) -> str:
    response = client.post(
        "/boms/analyze",
        headers=headers,
        data={"bom_name": name, "project_name": "Scope test", "revision": "A"},
        files={"file": (name, csv_bytes, "text/csv")},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["analysis_id"])


def test_selected_analysis_monitoring_excludes_other_analyses():
    client = TestClient(app)
    headers = _auth_headers(client)
    # Use the 25-part fixture so synthetic risk/lifecycle signals are present.
    bom = FIXTURE.read_bytes()

    first = _analyze_csv(client, headers, "first.csv", bom)
    second = _analyze_csv(client, headers, "second.csv", bom)
    assert first != second

    # Warm both analyses into workspace alert history.
    first_warm = client.get(f"/tools/monitoring?analysis_id={first}", headers=headers)
    second_warm = client.get(f"/tools/monitoring?analysis_id={second}", headers=headers)
    assert first_warm.status_code == 200, first_warm.text
    assert second_warm.status_code == 200, second_warm.text
    assert first_warm.json()["alerts"], "fixture should produce monitoring alerts"
    assert second_warm.json()["alerts"], "fixture should produce monitoring alerts"

    scoped = client.get(f"/tools/monitoring?analysis_id={first}", headers=headers)
    assert scoped.status_code == 200, scoped.text
    payload = scoped.json()
    assert payload["analysis_id"] == first
    alerts = payload["alerts"]
    assert alerts, "expected derived alerts for the selected analysis"
    assert all(str(alert.get("analysis_id")) == first for alert in alerts)
    assert payload["metrics"]["active_alerts"] == len(alerts)
    assert payload["metrics"]["lifecycle_changes"] == len(
        {
            str(alert.get("part_number") or "")
            for alert in alerts
            if "lifecycle" in str(alert.get("alert_type") or "").lower()
            and str(alert.get("part_number") or "").strip()
        }
    )
    assert payload["metrics"]["engineering_priority_risk"] == len(
        [alert for alert in alerts if "risk" in str(alert.get("alert_type") or "").lower()]
    )


def _fixture_parts_four_lifecycle_four_risk() -> list[dict]:
    parts = []
    for index in range(4):
        parts.append(
            {
                "MPN": f"LIFE-{index}",
                "Lifecycle": "NRND",
                "lifecycle_status": "NRND",
                "Risk Level": "Low",
                "risk_level": "Low",
            }
        )
    for index in range(4):
        parts.append(
            {
                "MPN": f"RISK-{index}",
                "Lifecycle": "Active",
                "lifecycle_status": "Active",
                "Risk Level": "High" if index < 2 else "Medium",
                "risk_level": "High" if index < 2 else "Medium",
                "Risk Reasons": "fixture risk",
            }
        )
    return parts


def test_monitoring_kpi_counts_match_four_lifecycle_and_four_risk_alerts(monkeypatch):
    from apps.api import migration_tools

    analysis_id = "analysis-kpi-4x4"
    workspace_id = "workspace-kpi"
    report = {
        "id": analysis_id,
        "mode": "synthetic-preview",
        "filename": "kpi.csv",
        "total_parts": 8,
        "high_risk_count": 2,
        "medium_risk_count": 2,
        "low_risk_count": 4,
        "parts": _fixture_parts_four_lifecycle_four_risk(),
        "workspace_id": workspace_id,
    }
    # Seed an older analysis into durable history so the filter must exclude it.
    monitoring_store.persist_alerts(
        workspace_id,
        [
            {
                "id": "alert-old-1",
                "analysis_id": "analysis-older",
                "part_number": "OLD-PART",
                "alert_type": "Risk Signal",
                "severity": "High",
                "alert_message": "stale",
                "evidence_source": "synthetic-preview-analysis",
            }
        ],
    )
    monkeypatch.setattr(
        migration_tools, "_require_analysis", lambda *args, **kwargs: report
    )

    payload = migration_tools.monitoring_payload(
        workspace_id=workspace_id, analysis_id=analysis_id
    )
    assert payload["metrics"]["lifecycle_changes"] == 4
    assert payload["metrics"]["risk_signals"] == 4
    assert payload["metrics"]["engineering_priority_risk"] == 4
    assert payload["metrics"]["active_alerts"] == 8
    assert len(payload["alerts"]) == 8
    assert payload["metrics"]["active_alerts"] == len(payload["alerts"])
    assert all(str(row.get("analysis_id")) == analysis_id for row in payload["alerts"])
    assert all(str(row.get("part_number")) != "OLD-PART" for row in payload["alerts"])
    lifecycle_rows = [
        row for row in payload["alerts"] if "lifecycle" in str(row.get("alert_type") or "").lower()
    ]
    risk_rows = [
        row for row in payload["alerts"] if "risk" in str(row.get("alert_type") or "").lower()
    ]
    assert len(lifecycle_rows) == 4
    assert len(risk_rows) == 4
    assert len({row["part_number"] for row in lifecycle_rows}) == 4


def test_monitoring_provenance_labels_follow_report_mode(monkeypatch):
    from apps.api import migration_tools

    analysis_id = "analysis-provenance"
    workspace_id = "workspace-provenance"
    parts = [
        {
            "MPN": "NRNDPART",
            "Lifecycle": "NRND",
            "lifecycle_status": "NRND",
            "Risk Level": "Low",
            "risk_level": "Low",
        }
    ]
    report = {
        "id": analysis_id,
        "mode": "synthetic-preview",
        "filename": "provenance.csv",
        "total_parts": 1,
        "parts": parts,
        "workspace_id": workspace_id,
    }
    monkeypatch.setattr(
        migration_tools, "_require_analysis", lambda *args, **kwargs: report
    )

    synthetic = migration_tools.monitoring_payload(
        workspace_id=workspace_id, analysis_id=analysis_id
    )
    assert synthetic["mode"] == "synthetic-preview"
    assert all("synthetic" in str(row.get("evidence_source") or "").lower() for row in synthetic["alerts"])
    assert all("synthetic analysis" in str(row.get("alert_message") or "").lower() for row in synthetic["alerts"])
    assert "Scheduled supplier refresh and real alert email remain disabled" in synthetic["gap"]
    assert synthetic["service_status"]["scheduled_refresh_and_email_enabled"] is False

    report["mode"] = "legacy-supplier-engine"
    real = migration_tools.monitoring_payload(
        workspace_id=workspace_id, analysis_id=analysis_id
    )
    assert real["mode"] == "legacy-supplier-engine"
    assert real["alerts"]
    assert all("synthetic" not in str(row.get("evidence_source") or "").lower() for row in real["alerts"])
    assert all("synthetic analysis" not in str(row.get("alert_message") or "").lower() for row in real["alerts"])
    assert all("saved analysis" in str(row.get("alert_message") or "").lower() for row in real["alerts"])


def _approval_checks() -> list[str]:
    return [
        "manufacturer_datasheet_reviewed",
        "package_pinout_verified",
        "electrical_limits_verified",
    ]


def _mcp2551_conflict_comparison(**overrides):
    payload = {
        "ok": True,
        "status": "completed",
        "mode": "legacy-supplier-engine",
        "analysis_id": None,
        "part_a": "MCP2551-I/SN",
        "part_b": "SN65HVD230DR",
        "finding": "Material difference",
        "counts": {"compatible": 1, "material_difference": 1, "needs_data": 2},
        "unknown_attributes": ["Pinout / footprint", "Package"],
        "rows": [
            {
                "Attribute": "Supply voltage",
                "Part A": "4.5–5.5 V",
                "Part B": "3–3.6 V",
                "Assessment": "Material difference",
                "Required": True,
                "Evidence": "Datasheet supply ranges differ.",
            },
            {
                "Attribute": "Pinout / footprint",
                "Part A": "Unable to confirm",
                "Part B": "Unable to confirm",
                "Assessment": "Unable to confirm",
                "Required": True,
                "Evidence": "No exact-MPN pinout citation.",
            },
            {
                "Attribute": "Package",
                "Part A": "Unable to confirm",
                "Part B": "Unable to confirm",
                "Assessment": "Unable to confirm",
                "Required": True,
                "Evidence": "Package not confirmed.",
            },
        ],
        "engineering_evidence_summary": "Material supply-voltage difference with unknown required fit fields.",
        "engineering_evidence_status": "unverified",
        "family": "Interface / transceiver",
        "family_mismatch": False,
        "part_cards": {},
        "source_a": "manufacturer-datasheet",
        "source_b": "manufacturer-datasheet",
        "evidence_sources": {},
        "gap": "Material difference including supply voltage.",
    }
    payload.update(overrides)
    return payload


def test_approval_conflict_summary_detects_mcp2551_case():
    from apps.api.migration_tools import approval_conflict_summary

    conflicts = approval_conflict_summary(_mcp2551_conflict_comparison())
    assert conflicts["has_conflicts"] is True
    assert any("Supply voltage" == row["attribute"] for row in conflicts["material_differences"])
    assert any("4.5" in row["part_a"] and "3" in row["part_b"] for row in conflicts["material_differences"])
    assert {row["attribute"] for row in conflicts["unknown_required_fields"]} >= {
        "Pinout / footprint",
        "Package",
    }


def test_api_rejects_conflicting_approval_without_ack_or_override(monkeypatch):
    from apps.api import migration_tools

    monkeypatch.setattr(
        migration_tools,
        "compare_parts_payload",
        lambda **kwargs: _mcp2551_conflict_comparison(analysis_id=kwargs.get("analysis_id")),
    )
    client = TestClient(app)
    headers = _auth_headers(client)
    base = {
        "part_a": "MCP2551-I/SN",
        "part_b": "SN65HVD230DR",
        "decision": "approve_alternate",
        "reviewer": "Engineering reviewer",
        "rationale": "Approve alternate / Low residual risk for board spin.",
        "validation_checks": _approval_checks(),
        "residual_risk": "low",
    }

    missing_ack = client.post("/decision-records", headers=headers, json=base)
    assert missing_ack.status_code == 400, missing_ack.text
    assert "acknowledge" in missing_ack.json()["detail"].lower()
    assert missing_ack.json()["approval_conflicts"]["has_conflicts"] is True

    missing_override = client.post(
        "/decision-records",
        headers=headers,
        json={**base, "conflict_acknowledgement": True},
    )
    assert missing_override.status_code == 400, missing_override.text
    assert "override rationale" in missing_override.json()["detail"].lower()

    missing_risk = client.post(
        "/decision-records",
        headers=headers,
        json={
            **base,
            "residual_risk": "unknown",
            "conflict_acknowledgement": True,
            "override_rationale": "Board already validated at 3.3 V rail.",
        },
    )
    assert missing_risk.status_code == 400, missing_risk.text
    assert "residual-risk" in missing_risk.json()["detail"].lower()


def test_api_accepts_acknowledged_conflicting_approval_and_persists_override(monkeypatch):
    from apps.api import migration_tools

    monkeypatch.setattr(
        migration_tools,
        "compare_parts_payload",
        lambda **kwargs: _mcp2551_conflict_comparison(analysis_id=kwargs.get("analysis_id")),
    )
    client = TestClient(app)
    headers = _auth_headers(client)
    payload = {
        "part_a": "MCP2551-I/SN",
        "part_b": "SN65HVD230DR",
        "decision": "approve_alternate",
        "reviewer": "Engineering reviewer",
        "rationale": "Approve alternate after bench validation on 3.3 V design.",
        "validation_checks": _approval_checks(),
        "residual_risk": "low",
        "conflict_acknowledgement": True,
        "override_rationale": (
            "Supply rails are 3.3 V only; MCP2551 5 V requirement does not apply to this board. "
            "Pinout confirmed on prototype."
        ),
    }
    saved = client.post("/decision-records", headers=headers, json=payload)
    assert saved.status_code == 201, saved.text
    record = saved.json()["record"]
    assert record["decision"] == "approve_alternate"
    assert record["residual_risk"] == "low"
    assert record["conflict_acknowledgement"] is True
    assert "3.3 V" in record["override_rationale"]
    assert record["approval_conflicts"]["has_conflicts"] is True
    assert record["qualification_status"] == "not-qualified-by-cadivor"
    assert "did not automatically qualify" in record["qualification_note"].lower()
    assert record["comparison_snapshot"]["finding"] == "Material difference"

    # Multipart path must accept the same acknowledgement fields.
    # Include an empty files entry so TestClient encodes multipart/form-data
    # (data= alone becomes urlencoded and is rejected by this route).
    multipart = client.post(
        "/decision-records",
        headers=headers,
        data={
            "part_a": "MCP2551-I/SN",
            "part_b": "SN65HVD230DR",
            "decision": "approve_alternate",
            "reviewer": "Engineering reviewer",
            "rationale": "Multipart override approval.",
            "validation_checks": '["manufacturer_datasheet_reviewed","package_pinout_verified","electrical_limits_verified"]',
            "residual_risk": "medium",
            "conflict_acknowledgement": "true",
            "override_rationale": "Multipart override documents the 4.5–5.5 V vs 3–3.6 V conflict.",
        },
        files={"_multipart": (None, "")},
    )
    assert multipart.status_code == 201, multipart.text
    assert multipart.json()["record"]["conflict_acknowledgement"] is True
    assert "4.5" in multipart.json()["record"]["override_rationale"]


def test_no_conflict_approval_still_requires_existing_validation(monkeypatch):
    from apps.api import migration_tools

    clean = {
        "ok": True,
        "status": "completed",
        "mode": "synthetic-preview",
        "analysis_id": None,
        "part_a": "PART-A",
        "part_b": "PART-B",
        "finding": "Compatible on available evidence",
        "counts": {"compatible": 4, "material_difference": 0, "needs_data": 0},
        "unknown_attributes": [],
        "rows": [
            {
                "Attribute": "Package",
                "Part A": "SOIC-8",
                "Part B": "SOIC-8",
                "Assessment": "Compatible",
                "Required": True,
            }
        ],
        "engineering_evidence_summary": "No material conflicts on available evidence.",
        "engineering_evidence_status": "unverified",
        "family": "General",
        "family_mismatch": False,
        "part_cards": {},
        "source_a": "synthetic-preview",
        "source_b": "synthetic-preview",
        "evidence_sources": {},
        "gap": "",
    }
    monkeypatch.setattr(migration_tools, "compare_parts_payload", lambda **kwargs: clean)

    client = TestClient(app)
    headers = _auth_headers(client)
    blocked = client.post(
        "/decision-records",
        headers=headers,
        json={
            "part_a": "PART-A",
            "part_b": "PART-B",
            "decision": "approve_alternate",
            "reviewer": "Engineering reviewer",
            "rationale": "Looks compatible.",
            "validation_checks": [],
            "residual_risk": "low",
        },
    )
    assert blocked.status_code == 400
    assert "manufacturer datasheet" in blocked.json()["detail"].lower()

    accepted = client.post(
        "/decision-records",
        headers=headers,
        json={
            "part_a": "PART-A",
            "part_b": "PART-B",
            "decision": "approve_alternate",
            "reviewer": "Engineering reviewer",
            "rationale": "Compatible on available evidence after datasheet review.",
            "validation_checks": _approval_checks(),
            "residual_risk": "low",
        },
    )
    assert accepted.status_code == 201, accepted.text
    record = accepted.json()["record"]
    assert record["conflict_acknowledgement"] is False
    assert record.get("override_rationale") in {None, ""}
    assert record["qualification_status"] == "not-qualified-by-cadivor"
