"""Roadmap gate coverage for the Next.js migration API (synthetic / mocked)."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from apps.api.monitoring_store import reset_monitoring_store_for_tests, recorded_emails
from apps.api import evidence_contract
from apps.api import supplier_lookup
from apps.api import connectors
from apps.api import compliance_packs
from apps.api import billing_prep
from apps.api import plan_limits
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/synthetic_bom_25parts.csv"


@pytest.fixture(autouse=True)
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    monkeypatch.delenv("CADIVOR_MIGRATION_SUPPLIER_LIVE", raising=False)
    monkeypatch.delenv("CADIVOR_MONITORING_EMAIL_ENABLED", raising=False)
    monkeypatch.delenv("CADIVOR_MIGRATION_STRIPE_CHECKOUT_ENABLED", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    reset_monitoring_store_for_tests()
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()


def _auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post("/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD})
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _analyze(client: TestClient, headers: dict[str, str]) -> str:
    with FIXTURE.open("rb") as handle:
        res = client.post(
            "/boms/analyze",
            headers=headers,
            files={"file": ("synthetic_bom_25parts.csv", handle, "text/csv")},
        )
    assert res.status_code == 200, res.text
    return res.json()["analysis_id"]


def test_health_lists_roadmap_capabilities():
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert "plan-limits" in body["foundation"]
    assert "supplier-lookup" in body["tools"]
    assert body["suppliers_live"] is False
    assert body["stripe_checkout_enabled"] is False
    assert body["monitoring_email_enabled"] is False


def test_evidence_contract_separates_synthetic_from_live():
    synthetic = evidence_contract.classify_part_evidence(
        {"MPN": "RES10K", "Unit Price": 0.1, "evidence_source": "synthetic-preview"}
    )
    assert synthetic["evidence_class"] == evidence_contract.EVIDENCE_SYNTHETIC
    assert synthetic["synthetic"] is True

    live = evidence_contract.classify_part_evidence(
        {
            "MPN": "RES10K",
            "manufacturer_part_number": "RES10K",
            "source": "DigiKey",
            "evidence_source": "live-authorized-supplier",
            "product_url": "https://example.test/RES10K",
            "supplier_data_verified": True,
            "provider_status": "AVAILABLE",
            "retrieved_at": "2026-11-05T12:00:00+00:00",
        }
    )
    assert live["evidence_class"] == evidence_contract.EVIDENCE_LIVE
    assert live["identity_verified"] is True
    assert live["source_url"].startswith("https://")


def test_supplier_lookup_mock_exact_match_and_miss():
    hit = supplier_lookup.lookup_exact_part("RES10K")
    assert hit["ok"] is True
    assert hit["evidence_class"] == evidence_contract.EVIDENCE_SYNTHETIC
    assert hit["match"]["identity_verified"] is True
    assert hit["match"]["source_url"]
    assert hit["match"]["retrieved_at"]
    assert hit["match"]["units"]["currency"] == "USD"
    assert hit["live_lookups_enabled"] is False

    miss = supplier_lookup.lookup_exact_part("NO-SUCH-PART")
    assert miss["evidence_class"] == evidence_contract.EVIDENCE_MISSING


def test_supplier_lookup_route_requires_auth_and_returns_mock():
    client = TestClient(app)
    denied = client.post("/tools/supplier-lookup", json={"mpn": "RES10K"})
    assert denied.status_code == 401
    headers = _auth_headers(client)
    res = client.post("/tools/supplier-lookup", headers=headers, json={"mpn": "RES10K"})
    assert res.status_code == 200
    body = res.json()
    assert body["match"]["source_url"]
    assert body["synthetic"] is True


def test_report_includes_evidence_summary():
    client = TestClient(app)
    headers = _auth_headers(client)
    analysis_id = _analyze(client, headers)
    res = client.get(f"/reports/{analysis_id}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert "evidence_summary" in body
    assert body["evidence_summary"]["live_lookups_enabled"] is False
    assert body["parts"]
    assert "evidence" in body["parts"][0]


def test_monitoring_persists_alerts_and_preferences_with_mock_email():
    client = TestClient(app)
    headers = _auth_headers(client)
    analysis_id = _analyze(client, headers)
    mon = client.get("/tools/monitoring", headers=headers, params={"analysis_id": analysis_id})
    assert mon.status_code == 200
    payload = mon.json()
    assert payload["ok"] is True
    assert "preferences" in payload
    assert payload["refresh"]["scheduled"] is False

    prefs = client.put(
        "/tools/monitoring/preferences",
        headers=headers,
        json={"email_alerts": True, "lifecycle": True},
    )
    assert prefs.status_code == 200
    assert prefs.json()["preferences"]["email_alerts"] is True

    alerts = client.get("/tools/monitoring/alerts", headers=headers)
    assert alerts.status_code == 200
    rows = alerts.json()["alerts"]
    if rows:
        ack = client.post(
            "/tools/monitoring/acknowledge",
            headers=headers,
            json={"alert_id": rows[0]["id"]},
        )
        assert ack.status_code == 200
        assert ack.json()["alert"]["acknowledged"] is True

        notify = client.post(
            "/tools/monitoring/notify",
            headers=headers,
            json={"alert_id": rows[0]["id"]},
        )
        assert notify.status_code == 200
        body = notify.json()
        assert body["mock_recorded"] is True
        assert body["delivered"] is False
        assert recorded_emails()


def test_plan_usage_and_billing_prep():
    client = TestClient(app)
    headers = _auth_headers(client)
    usage = client.get("/plan/usage", headers=headers)
    assert usage.status_code == 200
    body = usage.json()
    assert body["enforced"] is True
    assert "limits" in body

    billing = client.get("/billing/status", headers=headers)
    assert billing.status_code == 200
    assert billing.json()["checkout_enabled"] is False
    assert billing.json()["charges_created"] is False
    assert billing.json()["stripe_mode"] == "unavailable"

    prep = client.post(
        "/billing/checkout-prep",
        headers=headers,
        json={"plan": "starter"},
    )
    assert prep.status_code == 409
    assert prep.json()["code"] == "checkout_disabled"
    assert prep.json()["prepared"]["plan"] == "Starter"


def test_billing_blocks_live_stripe_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_example")
    status = billing_prep.billing_status()
    assert status["stripe_mode"] == "live-blocked"
    assert status["checkout_enabled"] is False


def test_connectors_groundwork_and_sync():
    client = TestClient(app)
    headers = _auth_headers(client)
    listing = client.get("/integrations/connectors", headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    # CSV/generic imports are file workflows, not live vendor readiness.
    assert body.get("file_workflow_count", 0) >= 1
    assert body.get("live_ready_count", body["ready_count"]) == 0
    assert body["ready_count"] == 0
    assert body["blocked_count"] >= 1

    sync = client.post(
        "/integrations/connectors/sync",
        headers=headers,
        json={
            "connector_id": "plm.generic_bom_csv",
            "rows": [{"MPN": "RES10K", "Manufacturer": "Mock", "Quantity": 2}],
        },
    )
    assert sync.status_code == 200
    assert sync.json()["records"][0]["mpn"] == "RES10K"

    blocked = client.post(
        "/integrations/connectors/sync",
        headers=headers,
        json={"connector_id": "plm.arena_or_propel", "rows": [{"MPN": "X"}]},
    )
    assert blocked.status_code == 400
    assert "decision" in (blocked.json().get("gap") or "").lower() or blocked.json()["ok"] is False


def test_compliance_packs_label_missing_evidence():
    client = TestClient(app)
    headers = _auth_headers(client)
    analysis_id = _analyze(client, headers)
    for pack in ("rohs", "reach", "conflict_minerals", "audit"):
        res = client.get(f"/compliance/{pack}", headers=headers, params={"analysis_id": analysis_id})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is True
        if pack == "audit":
            assert body["compliance_claimed"] is False
        else:
            assert body["summary"]["compliance_claimed"] is False
            assert body["summary"]["missing_evidence"] >= 1


def test_plan_limits_module_blocks_expired_trial():
    snap_ctx = {"plan": "Trial", "trial_status": "trial_expired"}
    # usage_snapshot itself should resolve expired plan
    # Store must exist from fixture
    from apps.api.workspace_store import get_store

    # Create a fake workspace usage path via smoke login workspace
    client = TestClient(app)
    headers = _auth_headers(client)
    me = client.get("/auth/me", headers=headers).json()
    wid = me["workspace_id"]
    with pytest.raises(plan_limits.PlanLimitError):
        plan_limits.assert_analysis_allowed(workspace_id=wid, ctx=snap_ctx, part_count=5)


def test_connector_registry_unit():
    payload = connectors.connector_status_payload()
    assert payload.get("file_workflow_count", 0) >= 1
    assert payload.get("live_ready_count", payload["ready_count"]) == 0
    assert payload["ready_count"] == 0
    result = connectors.sync_generic_bom_csv(
        [{"mpn": "CAP100U", "quantity": 3}],
        connector_id="cad.altium_or_solidworks",
    )
    assert result.ok is True
    assert result.records[0]["mpn"] == "CAP100U"


def test_compliance_unit_never_claims_without_source():
    pack = compliance_packs.build_pack(
        {"id": "a1", "parts": [{"MPN": "RES10K", "evidence_source": "synthetic-preview"}]},
        "rohs",
    )
    assert pack["summary"]["compliance_claimed"] is False
    assert pack["records"][0]["status"] == "missing_evidence"


def test_monitoring_refresh_on_demand():
    client = TestClient(app)
    headers = _auth_headers(client)
    analysis_id = _analyze(client, headers)
    res = client.post(
        "/tools/monitoring/refresh",
        headers=headers,
        params={"analysis_id": analysis_id},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["scheduler_enabled"] is False
