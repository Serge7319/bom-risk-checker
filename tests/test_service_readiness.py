"""Settings service-readiness endpoint reports operational capability."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient

import apps.api.main as api_main
from apps.api import billing_prep
from apps.api import monitoring_store
from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.team_store import reset_team_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    monkeypatch.delenv("CADIVOR_MONITORING_EMAIL_ENABLED", raising=False)
    monkeypatch.delenv("CADIVOR_MONITORING_SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("CADIVOR_MONITORING_CRON_TOKEN", raising=False)
    monkeypatch.delenv("CADIVOR_MIGRATION_STRIPE_CHECKOUT_ENABLED", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    reset_team_store_for_tests(tmp_path / "team.json")
    monitoring_store.reset_email_sink_for_tests()
    api_main._THROTTLE.clear()
    return TestClient(app)


def _token(client: TestClient) -> str:
    res = client.post("/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _readiness(client: TestClient) -> dict:
    token = _token(client)
    res = client.get(
        "/integrations/service-readiness",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert "error" not in body
    return body


def test_service_readiness_unknown_when_supabase_billing_status_unavailable(
    client: TestClient,
):
    body = _readiness(client)
    assert body["monitoring_email"]["status"] == "not_connected"
    assert body["scheduler"]["status"] == "not_connected"
    assert body["billing_checkout"]["status"] == "unknown"
    assert body["billing_checkout"]["enabled"] is False

def test_monitoring_email_enabled_without_transport_is_not_ready(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_MONITORING_EMAIL_ENABLED", "1")
    monkeypatch.setattr(monitoring_store, "_configured_email_transport", lambda: False)
    monitoring_store.set_default_email_sink(None)

    body = _readiness(client)
    assert body["monitoring_email"]["enabled"] is True
    assert body["monitoring_email"]["transport_ready"] is False
    assert body["monitoring_email"]["status"] == "not_connected"

    # Matches deliver_alert_email when prefs allow email but no sink/transport is wired.
    monitoring_store.update_preferences("ws-test", {"email_alerts": True})
    result = monitoring_store.deliver_alert_email(
        "ws-test",
        {"id": "a1", "part_number": "ABC", "alert_type": "lifecycle"},
    )
    assert result["delivered"] is False
    assert result["reason"] == "no_sink_configured"


def test_monitoring_email_ready_when_transport_sink_present(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_MONITORING_EMAIL_ENABLED", "1")
    monitoring_store.set_default_email_sink(lambda payload: None)
    try:
        body = _readiness(client)
        assert body["monitoring_email"]["status"] == "ready"
        assert body["monitoring_email"]["transport_ready"] is True
    finally:
        monitoring_store.set_default_email_sink(None)


def test_scheduler_enabled_without_cron_token_is_partial(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_MONITORING_SCHEDULER_ENABLED", "1")
    monkeypatch.delenv("CADIVOR_MONITORING_CRON_TOKEN", raising=False)
    body = _readiness(client)
    assert body["scheduler"]["enabled"] is True
    assert body["scheduler"]["cron_token_configured"] is False
    assert body["scheduler"]["status"] == "partial"


def test_scheduler_with_token_stays_partial_without_verified_schedule(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_MONITORING_SCHEDULER_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_MONITORING_CRON_TOKEN", "cron-secret")
    body = _readiness(client)
    assert body["scheduler"]["cron_token_configured"] is True
    assert body["scheduler"]["status"] == "partial"


def test_service_readiness_uses_the_supabase_checkout_used_by_settings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_MIGRATION_STRIPE_CHECKOUT_ENABLED", "1")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_readiness_probe")
    assert billing_prep.checkout_enabled() is True
    probe = billing_prep.prepare_checkout_intent(
        workspace_id="ws",
        plan_token=next(iter(billing_prep.CHECKOUT_PLAN_TOKENS.values())),
        user_id="user",
    )
    assert probe.get("code") == "not_implemented"

    request_action = Mock(
        return_value=(
            {
                "ok": True,
                "checkout_enabled": True,
                "stripe_mode": "test",
                "can_manage_billing": True,
                "plans": [
                    {"name": "Starter", "enabled": True},
                    {"name": "Professional", "enabled": True},
                    {"name": "Business", "enabled": True},
                ],
            },
            200,
        )
    )
    monkeypatch.setattr(
        api_main.subscription_billing_service, "request_action", request_action
    )
    body = _readiness(client)
    billing = body["billing_checkout"]
    assert billing["enabled"] is True
    assert billing["status"] == "ready"
    assert billing["stripe_mode"] == "test"
    assert billing["enabled_plan_count"] == 3
    assert billing["can_manage_billing"] is True
    request_action.assert_called_once()
    assert request_action.call_args.kwargs["action"] == "status"


def test_service_readiness_is_partial_when_only_existing_portal_is_available(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        api_main.subscription_billing_service,
        "request_action",
        Mock(
            return_value=(
                {
                    "ok": True,
                    "checkout_enabled": False,
                    "stripe_mode": "live",
                    "can_manage_billing": True,
                    "plans": [],
                },
                200,
            )
        ),
    )
    billing = _readiness(client)["billing_checkout"]
    assert billing["status"] == "partial"
    assert billing["enabled"] is False
    assert billing["can_manage_billing"] is True


def test_service_readiness_marks_unexpected_billing_response_unknown(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        api_main.subscription_billing_service,
        "request_action",
        Mock(return_value=({"ok": False}, 503)),
    )
    billing = _readiness(client)["billing_checkout"]
    assert billing["status"] == "unknown"
    assert billing["enabled"] is False

def test_service_readiness_error_omits_exception_string(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    token = _token(client)

    def boom():
        raise RuntimeError("secret-internal-failure-detail")

    monkeypatch.setattr(
        "apps.api.connectors.connector_status_payload",
        boom,
    )
    res = client.get(
        "/integrations/service-readiness",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 503
    body = res.json()
    assert body["ok"] is False
    assert "error" not in body
    assert "secret-internal-failure-detail" not in res.text
    assert body["detail"] == "Service readiness could not be determined."
    assert body["monitoring_email"]["status"] == "unknown"


def test_settings_copy_is_customer_facing():
    settings = Path("apps/web/src/app/settings/page.tsx").read_text(encoding="utf-8")
    assert "These notes stay in Settings instead of repeating across Home and Reports." not in settings
    assert "CSV file workflows are listed separately from live design-tool or vendor integrations" in settings
    assert "Live design-tool / vendor connectors" in settings
    assert "Design-tool connectors" not in settings or "Live design-tool / vendor connectors" in settings

def test_service_readiness_labels_and_descriptions_stack_without_overlap():
    settings = Path("apps/web/src/app/settings/page.tsx").read_text(encoding="utf-8")
    css = Path("apps/web/src/app/globals.css").read_text(encoding="utf-8")

    assert 'className="cv-action-list cv-service-readiness-list"' in settings
    assert 'className="cv-service-readiness-copy"' in settings
    assert ".cv-service-readiness-copy{display:flex" in css.replace(" ", "")
    assert "overflow-wrap:anywhere" in css
    assert "@media(max-width:640px){.cv-service-readiness-list li" in css.replace(" ", "")


def test_csv_file_workflows_do_not_make_live_connectors_ready(client):
    body = _readiness(client)
    connectors = body["connectors"]
    assert connectors["file_workflow_count"] >= 1
    assert connectors["live_ready_count"] == 0
    assert connectors["ready_count"] == 0
    assert connectors["status"] == "not_connected"
    kinds = {
        str(row.get("kind") or row.get("status") or "")
        for row in (connectors.get("connectors") or [])
    }
    assert "file_workflow" in kinds
    # No CSV row should claim live ready status.
    for row in connectors.get("connectors") or []:
        if row.get("kind") == "file_workflow" or row.get("status") == "file_workflow":
            assert row.get("status") != "ready"
