"""Settings service-readiness endpoint reports email/scheduler/connector state."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

import apps.api.main as api_main
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
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    reset_team_store_for_tests(tmp_path / "team.json")
    api_main._THROTTLE.clear()
    return TestClient(app)


def _token(client: TestClient) -> str:
    res = client.post("/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def test_service_readiness_reports_actual_flags(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    token = _token(client)
    monkeypatch.setenv("CADIVOR_MONITORING_EMAIL_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_MONITORING_SCHEDULER_ENABLED", "1")
    res = client.get(
        "/integrations/service-readiness",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["monitoring_email"]["status"] == "ready"
    assert body["monitoring_email"]["enabled"] is True
    assert body["scheduler"]["status"] == "ready"
    assert body["connectors"]["ready_count"] >= 1
    assert body["connectors"]["status"] in {"ready", "partial"}
    assert isinstance(body["connectors"]["connectors"], list)


def test_service_readiness_not_connected_when_flags_off(client: TestClient):
    token = _token(client)
    res = client.get(
        "/integrations/service-readiness",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["monitoring_email"]["status"] == "not_connected"
    assert body["scheduler"]["status"] == "not_connected"
