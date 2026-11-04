"""Production Supabase Auth path for the Next migration API (mocked Auth client)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests


class _FakeUser:
    def __init__(self, user_id: str, email: str) -> None:
        self.id = user_id
        self.email = email


class _FakeSession:
    def __init__(self, token: str) -> None:
        self.access_token = token
        self.expires_in = 3600


class _FakeAuth:
    def __init__(self) -> None:
        self.users = {
            "owner@cadivor.test": {
                "password": "owner-pass-123",
                "user": _FakeUser("11111111-1111-1111-1111-111111111111", "owner@cadivor.test"),
                "token": "supabase-access-token-owner",
            },
            "other@cadivor.test": {
                "password": "other-pass-123",
                "user": _FakeUser("22222222-2222-2222-2222-222222222222", "other@cadivor.test"),
                "token": "supabase-access-token-other",
            },
        }
        self._by_token = {
            row["token"]: row["user"] for row in self.users.values()
        }

    def sign_in_with_password(self, payload: dict):
        email = str(payload.get("email") or "").strip().lower()
        password = str(payload.get("password") or "")
        row = self.users.get(email)
        if not row or row["password"] != password:
            raise RuntimeError("Invalid login credentials")
        return SimpleNamespace(session=_FakeSession(row["token"]), user=row["user"])

    def get_user(self, token: str):
        user = self._by_token.get(token)
        if not user:
            raise RuntimeError("Invalid JWT")
        return SimpleNamespace(user=user)

    def sign_out(self):
        return None


@pytest.fixture()
def supabase_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store_path = tmp_path / "store.json"
    auth_path = tmp_path / "auth.json"
    # reset_auth_store_for_tests clears production flags — set those after.
    reset_store_for_tests(store_path)
    reset_auth_store_for_tests(auth_path, accounts=[])
    monkeypatch.setenv("CADIVOR_FORCE_PRODUCTION_AUTH", "1")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "public-anon-key-for-tests")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("CADIVOR_SANDBOX_AUTH_SECRET", raising=False)
    monkeypatch.delenv("CADIVOR_ALLOW_SANDBOX_JWT", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)

    fake = _FakeAuth()

    def _fake_client(_url: str, _key: str, **_kwargs):
        return SimpleNamespace(auth=fake)

    monkeypatch.setattr("supabase.create_client", _fake_client)
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()
    return TestClient(app)


def test_production_runtime_reports_missing_supabase_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=[])
    # Must set production flags AFTER reset_auth_store_for_tests (it clears them).
    monkeypatch.setenv("CADIVOR_FORCE_PRODUCTION_AUTH", "1")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["production_runtime"] is True
    assert health["sandbox_jwt_permitted"] is False
    assert "SUPABASE_URL" in health["auth"]["missing_config_vars"]
    assert "SUPABASE_KEY" in health["auth"]["missing_config_vars"]
    login = client.post(
        "/auth/login", json={"email": "a@b.co", "password": "x"}
    )
    assert login.status_code == 503
    assert "SUPABASE_URL" in login.json()["missing_config_vars"]


def test_supabase_login_membership_reload_logout_and_isolation(
    supabase_client: TestClient,
):
    hijack = supabase_client.post(
        "/auth/login",
        json={
            "email": "owner@cadivor.test",
            "password": "owner-pass-123",
            "workspace_id": "ws-hijack",
        },
    )
    assert hijack.status_code == 200
    body = hijack.json()
    assert body["mode"] == "supabase-jwt"
    assert body["workspace_id"].startswith("ws-next-prod-test-")
    assert body["workspace_id"] != "ws-hijack"
    token = body["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = supabase_client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["workspace_id"] == body["workspace_id"]
    assert me.json()["mode"] == "supabase-jwt"

    # Synthetic analyze + persistence in owner workspace
    flat = Path(__file__).resolve().parents[1] / "tests/fixtures/synthetic_bom_25parts.csv"
    nested = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/nested_bom_product.csv"
    )
    analyze = supabase_client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("bom.csv", flat.read_bytes(), "text/csv")},
        data={
            "project_name": "Next Prod Test",
            "bom_name": "Main",
            "revision": "A",
        },
    )
    assert analyze.status_code == 200, analyze.text
    analysis_id = analyze.json()["analysis_id"]

    # Reload / saved report retrieval
    saved = supabase_client.get(f"/reports/{analysis_id}", headers=headers)
    assert saved.status_code == 200
    assert saved.json()["id"] == analysis_id

    if nested.exists():
        nested_res = supabase_client.post(
            "/boms/analyze",
            headers=headers,
            files={"file": ("nested.csv", nested.read_bytes(), "text/csv")},
            data={
                "project_name": "Next Prod Test",
                "bom_name": "Nested",
                "revision": "A",
            },
        )
        assert nested_res.status_code == 200
        assert nested_res.json().get("has_hierarchy") in {True, False}

    # Cross-workspace: second owner cannot read first owner's report
    other = supabase_client.post(
        "/auth/login",
        json={"email": "other@cadivor.test", "password": "other-pass-123"},
    )
    assert other.status_code == 200
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert other.json()["workspace_id"] != body["workspace_id"]
    denied = supabase_client.get(f"/reports/{analysis_id}", headers=other_headers)
    assert denied.status_code == 404

    # Logout revokes token for this API
    out = supabase_client.post("/auth/logout", headers=headers)
    assert out.status_code == 200
    assert supabase_client.get("/auth/me", headers=headers).status_code == 401


def test_sandbox_hs256_blocked_when_production_runtime_forced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=[])
    monkeypatch.setenv("CADIVOR_FORCE_PRODUCTION_AUTH", "1")
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "should-not-matter")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "public-anon-key-for-tests")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)

    fake = _FakeAuth()
    monkeypatch.setattr(
        "supabase.create_client",
        lambda *_a, **_k: SimpleNamespace(auth=fake),
    )
    client = TestClient(app)
    # Production path uses Supabase, not HS256 — even with sandbox secret set.
    res = client.post(
        "/auth/login",
        json={"email": "owner@cadivor.test", "password": "owner-pass-123"},
    )
    assert res.status_code == 200
    assert res.json()["mode"] == "supabase-jwt"
    health = client.get("/health").json()
    assert health["sandbox_jwt_permitted"] is False
    assert health["auth_path"] == "supabase"
