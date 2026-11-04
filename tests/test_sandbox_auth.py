"""Sandbox JWT auth: login, logout, expired/invalid tokens, membership workspace."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import (
    issue_expired_token_for_tests,
    reset_auth_store_for_tests,
    seed_demo_users,
)
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import SANDBOX_ACCOUNTS, SANDBOX_SEED_USERS

ROOT = Path(__file__).resolve().parents[1]
FLAT = ROOT / "tests/fixtures/synthetic_bom_25parts.csv"


@pytest.fixture()
def auth_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    store_path = tmp_path / "store.json"
    auth_path = tmp_path / "auth.json"
    reset_store_for_tests(store_path)
    reset_auth_store_for_tests(auth_path, accounts=SANDBOX_SEED_USERS)
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()
    return TestClient(app)


def test_login_issues_jwt_and_membership_workspace(auth_client: TestClient):
    email = "sandbox-a@cadivor.test"
    res = auth_client.post(
        "/auth/login",
        json={
            "email": email,
            "password": SANDBOX_ACCOUNTS[email]["password"],
            # Client attempt to pick another workspace must be ignored.
            "workspace_id": "ws-hijack",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["workspace_id"] == "ws-sandbox-a"
    assert body["workspace_id"] != "ws-hijack"
    assert body["mode"] == "sandbox-jwt"
    assert body["access_token"].count(".") == 2
    assert body["access_token"] != "cadivor-nextjs-smoke-token"

    me = auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["workspace_id"] == "ws-sandbox-a"
    assert me.json()["client_workspace_id_trusted"] is False


def test_invalid_credentials_and_invalid_token(auth_client: TestClient):
    bad = auth_client.post(
        "/auth/login",
        json={"email": "sandbox-a@cadivor.test", "password": "wrong"},
    )
    assert bad.status_code == 401

    missing = auth_client.get("/auth/me")
    assert missing.status_code == 401

    garbage = auth_client.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert garbage.status_code == 401


def test_expired_token_rejected(auth_client: TestClient):
    token = issue_expired_token_for_tests("sandbox-a@cadivor.test")
    res = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_logout_revokes_token(auth_client: TestClient):
    email = "sandbox-a@cadivor.test"
    login = auth_client.post(
        "/auth/login",
        json={"email": email, "password": SANDBOX_ACCOUNTS[email]["password"]},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert auth_client.get("/auth/me", headers=headers).status_code == 200
    out = auth_client.post("/auth/logout", headers=headers)
    assert out.status_code == 200
    assert auth_client.get("/auth/me", headers=headers).status_code == 401
    # Protected route also fails
    assert auth_client.get("/reports", headers=headers).status_code == 401


def test_smoke_login_removed(auth_client: TestClient):
    res = auth_client.post(
        "/auth/smoke-login",
        json={"email": "sandbox-a@cadivor.test", "password": "x"},
    )
    assert res.status_code == 410


def test_cross_workspace_with_jwt_auth(auth_client: TestClient):
    a = auth_client.post(
        "/auth/login",
        json={
            "email": "sandbox-a@cadivor.test",
            "password": SANDBOX_ACCOUNTS["sandbox-a@cadivor.test"]["password"],
        },
    ).json()
    b = auth_client.post(
        "/auth/login",
        json={
            "email": "sandbox-b@cadivor.test",
            "password": SANDBOX_ACCOUNTS["sandbox-b@cadivor.test"]["password"],
        },
    ).json()
    headers_a = {"Authorization": f"Bearer {a['access_token']}"}
    headers_b = {"Authorization": f"Bearer {b['access_token']}"}

    created = auth_client.post(
        "/boms/analyze",
        headers=headers_a,
        files={"file": ("synthetic_bom_25parts.csv", FLAT.read_bytes(), "text/csv")},
        data={"project_name": "OnlyA", "bom_name": "Bom", "revision": "A"},
    )
    assert created.status_code == 200
    assert created.json()["workspace_id"] == "ws-sandbox-a"
    aid = created.json()["analysis_id"]

    assert auth_client.get(f"/reports/{aid}", headers=headers_a).status_code == 200
    assert auth_client.get(f"/reports/{aid}", headers=headers_b).status_code == 404
    assert auth_client.get("/reports", headers=headers_b).json()["reports"] == []
    assert (
        auth_client.delete(f"/reports/{aid}", headers=headers_b).status_code == 404
    )


def test_health_reports_auth_mode(auth_client: TestClient):
    health = auth_client.get("/health").json()
    assert health["auth"]["mode"] == "sandbox-jwt-membership"
    assert health["auth"]["sandbox_only"] is True
    assert health["auth"]["production_auth"] is False
    assert health["auth"]["client_workspace_id_trusted"] is False
    assert health["auth"]["smoke_login_default"] is False
    assert health["auth_configured"] is True


def test_login_does_not_auto_seed_users(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without an explicit seed step, login must not create demo users."""
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json")  # no accounts=
    client = TestClient(app)
    email = "sandbox-a@cadivor.test"
    res = client.post(
        "/auth/login",
        json={"email": email, "password": SANDBOX_ACCOUNTS[email]["password"]},
    )
    assert res.status_code == 401


def test_production_runtime_fails_closed_even_with_sandbox_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Sandbox secret + seed accounts must not work as production auth."""
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "leaked-sandbox-secret-should-not-work")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.delenv("CADIVOR_ALLOW_SANDBOX_JWT", raising=False)
    monkeypatch.delenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", raising=False)
    reset_store_for_tests(tmp_path / "prod_store.json")
    # Do not call reset_auth_store_for_tests — it clears production env.
    from apps.api import sandbox_auth as sa

    sa._STORE = None
    sa._SEEDED = False
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["auth"]["mode"] == "blocked-production"
    assert health["auth_configured"] is False
    login = client.post(
        "/auth/login",
        json={
            "email": "sandbox-a@cadivor.test",
            "password": SANDBOX_ACCOUNTS["sandbox-a@cadivor.test"]["password"],
        },
    )
    assert login.status_code == 503
    assert "fail closed" in login.json()["detail"].lower() or "disabled" in login.json()[
        "detail"
    ].lower()


def test_production_blocks_even_when_allow_sandbox_jwt_and_secret_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """CADIVOR_ALLOW_SANDBOX_JWT=1 must not override production fail-closed."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "leaked-sandbox-secret-should-not-work")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    reset_store_for_tests(tmp_path / "prod_allow_store.json")
    from apps.api import sandbox_auth as sa

    sa._STORE = None
    sa._SEEDED = False
    assert sa.is_production_runtime() is True
    assert sa.sandbox_jwt_permitted() is False
    assert sa.auth_configured() is False
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["auth"]["mode"] == "blocked-production"
    assert health["auth"]["sandbox_jwt_permitted"] is False
    assert health["auth_configured"] is False
    login = client.post(
        "/auth/login",
        json={
            "email": "sandbox-a@cadivor.test",
            "password": SANDBOX_ACCOUNTS["sandbox-a@cadivor.test"]["password"],
        },
    )
    assert login.status_code == 503
    with pytest.raises(sa.AuthNotConfiguredError):
        seed_demo_users(SANDBOX_SEED_USERS)


def test_missing_sandbox_secret_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Sandbox env without CADIVOR_SANDBOX_AUTH_SECRET must not issue tokens."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("CADIVOR_SANDBOX_AUTH_SECRET", raising=False)
    monkeypatch.delenv("CADIVOR_ALLOW_SANDBOX_JWT", raising=False)
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    reset_store_for_tests(tmp_path / "no_secret_store.json")
    from apps.api import sandbox_auth as sa

    sa._STORE = None
    sa._SEEDED = False
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["auth_configured"] is False
    assert health["auth"]["sandbox_only"] is True
    assert health["auth"]["production_auth"] is False
    login = client.post(
        "/auth/login",
        json={
            "email": "sandbox-a@cadivor.test",
            "password": SANDBOX_ACCOUNTS["sandbox-a@cadivor.test"]["password"],
        },
    )
    assert login.status_code == 503
