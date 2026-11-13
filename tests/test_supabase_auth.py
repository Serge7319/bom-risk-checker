"""Production Supabase Auth path for the Next migration API (mocked Auth client)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from apps.api import supabase_auth
from apps.api.main import app
from apps.api.sandbox_auth import get_auth_store, reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests


class _FakeUser:
    def __init__(
        self,
        user_id: str,
        email: str,
        *,
        email_confirmed_at: str | None = "2026-11-01T12:00:00+00:00",
        user_metadata: dict | None = None,
    ) -> None:
        self.id = user_id
        self.email = email
        self.email_confirmed_at = email_confirmed_at
        self.user_metadata = user_metadata or {}


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
        self.signup_payloads = []

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

    def sign_up(self, payload: dict):
        self.signup_payloads.append(payload)
        email = payload["email"]
        user = _FakeUser(
            "33333333-3333-3333-3333-333333333333",
            email,
            email_confirmed_at=None,
            user_metadata=payload.get("options", {}).get("data", {}),
        )
        self.users[email] = {
            "password": payload["password"],
            "user": user,
            "token": "supabase-access-token-new",
        }
        self._by_token["supabase-access-token-new"] = user
        return SimpleNamespace(user=user, session=None)

    def sign_out(self):
        return None


@pytest.fixture()
def supabase_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store_path = tmp_path / "store.json"
    auth_path = tmp_path / "auth.json"
    # reset_auth_store_for_tests clears production flags — set those after.
    reset_store_for_tests(store_path)
    reset_auth_store_for_tests(auth_path, accounts=[])
    with supabase_auth._ENTITLEMENT_CACHE_LOCK:
        supabase_auth._ENTITLEMENT_CACHE.clear()
    monkeypatch.setenv("CADIVOR_FORCE_PRODUCTION_AUTH", "1")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "public-anon-key-for-tests")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("CADIVOR_SANDBOX_AUTH_SECRET", raising=False)
    monkeypatch.delenv("CADIVOR_ALLOW_SANDBOX_JWT", raising=False)
    monkeypatch.delenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", raising=False)
    monkeypatch.delenv("CADIVOR_SIGNUP_REDIRECT_URL", raising=False)
    monkeypatch.delenv("CADIVOR_SIGNUP_CAPTCHA_REQUIRED", raising=False)
    monkeypatch.delenv("CADIVOR_WEB_ORIGINS", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)

    fake = _FakeAuth()

    def _fake_client(_url: str, _key: str, **_kwargs):
        return SimpleNamespace(auth=fake)

    monkeypatch.setattr("supabase.create_client", _fake_client)
    def _billing_action(*, access_token: str, action: str, **_kwargs):
        if action == "entitlements":
            return {
                "ok": True,
                "plan": "Trial",
                "trial_started_at": "2026-11-01T12:00:00+00:00",
                "trial_ends_at": "2026-11-15T12:00:00+00:00",
                "trial_status": "trialing",
                "trial_days_remaining": 8,
            }, 200
        if action == "status":
            return {
                "ok": True,
                "checkout_enabled": False,
                "stripe_mode": "unconfigured",
                "charges_created": False,
                "has_active_subscription": False,
                "can_manage_billing": False,
                "plans": [],
            }, 200
        return {"ok": False, "detail": "not available"}, 409

    monkeypatch.setattr(
        "apps.api.subscription_billing_service.request_action",
        _billing_action,
    )
    for account in fake.users.values():
        user = account["user"]
        supabase_auth.ensure_owner_membership(
            user_id=user.id,
            email=user.email,
            workspace_name=supabase_auth.user_workspace_name(user),
            allow_create=True,
        )
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()
    client = TestClient(app)
    client.app.state.fake_auth = fake
    return client


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

    exported = supabase_client.get(
        f"/reports/{analysis_id}/export.csv", headers=headers
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert exported.content.startswith(b"\xef\xbb\xbf")
    assert "MPN,Qty,Lifecycle" in exported.content.decode("utf-8-sig")

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
    denied_export = supabase_client.get(
        f"/reports/{analysis_id}/export.csv", headers=other_headers
    )
    assert denied_export.status_code == 404

    # Logout revokes token for this API
    out = supabase_client.post("/auth/logout", headers=headers)
    assert out.status_code == 200
    assert supabase_client.get("/auth/me", headers=headers).status_code == 401


def test_entitlement_snapshot_is_authoritative_and_login_does_not_reset_membership(
    supabase_client: TestClient,
):
    store = get_auth_store()
    user_id = "11111111-1111-1111-1111-111111111111"
    store._data["users"][user_id]["plan"] = "Business"
    store._data["memberships"][user_id]["role"] = "engineer"
    store.save()

    login = supabase_client.post(
        "/auth/login",
        json={"email": "owner@cadivor.test", "password": "owner-pass-123"},
    )

    assert login.status_code == 200
    assert login.json()["plan"] == "Trial"
    assert store._data["users"][user_id]["plan"] == "Business"
    assert store._data["memberships"][user_id]["role"] == "engineer"


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
    owner = fake.users["owner@cadivor.test"]["user"]
    supabase_auth.ensure_owner_membership(
        user_id=owner.id,
        email=owner.email,
        workspace_name=supabase_auth.user_workspace_name(owner),
        allow_create=True,
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


def test_self_serve_signup_is_disabled_by_default(supabase_client: TestClient):
    config = supabase_client.get("/auth/config")
    assert config.status_code == 200
    body = config.json()
    assert body["signup_enabled"] is False
    assert body["trial_length_days"] == 14
    assert body["invitations_enabled"] is True
    assert "terms_version" in body
    assert "privacy_version" in body
    response = supabase_client.post(
        "/auth/signup",
        json={
            "email": "new@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "New workspace",
            "accepted_terms": True,
        },
    )
    assert response.status_code == 503
    assert supabase_client.app.state.fake_auth.signup_payloads == []


def test_unprovisioned_supabase_account_cannot_enter_when_signup_is_closed(
    supabase_client: TestClient,
):
    fake = supabase_client.app.state.fake_auth
    email = "uninvited@cadivor.test"
    user = _FakeUser(
        "44444444-4444-4444-4444-444444444444",
        email,
    )
    token = "supabase-access-token-uninvited"
    fake.users[email] = {
        "password": "uninvited-pass-123",
        "user": user,
        "token": token,
    }
    fake._by_token[token] = user

    login = supabase_client.post(
        "/auth/login",
        json={"email": email, "password": "uninvited-pass-123"},
    )
    assert login.status_code == 403
    assert "not provisioned" in login.json()["detail"].lower()
    assert get_auth_store().membership_for_user(user.id) is None

    bearer = supabase_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert bearer.status_code == 403
    assert get_auth_store().membership_for_user(user.id) is None


def test_verified_signup_provisions_workspace_and_starts_trial_once(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED", "1")
    monkeypatch.setenv(
        "CADIVOR_SIGNUP_REDIRECT_URL",
        "https://cadivor-next-web-prod-production.up.railway.app/login",
    )
    monkeypatch.setenv(
        "CADIVOR_WEB_ORIGINS",
        "https://cadivor-next-web-prod-production.up.railway.app",
    )
    client = supabase_client
    config = client.get("/auth/config")
    assert config.json()["signup_enabled"] is True
    rejected = client.post(
        "/auth/signup",
        json={
            "email": "new@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Acme Hardware",
        },
    )
    assert rejected.status_code == 400
    assert "terms" in rejected.json()["detail"].lower()
    response = client.post(
        "/auth/signup",
        json={
            "email": "new@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Acme Hardware",
            "accepted_terms": True,
        },
    )
    assert response.status_code == 202
    assert response.json()["accepted"] is True
    fake = client.app.state.fake_auth
    payload = fake.signup_payloads[0]
    assert payload["options"]["email_redirect_to"].endswith("/login")
    assert payload["options"]["data"]["workspace_name"] == "Acme Hardware"
    user = fake.users["new@cadivor.test"]["user"]
    assert get_auth_store().membership_for_user(user.id) is None

    unverified = client.post(
        "/auth/login",
        json={"email": "new@cadivor.test", "password": "long-password-123"},
    )
    assert unverified.status_code == 403
    assert get_auth_store().membership_for_user(user.id) is None

    user.email_confirmed_at = "2026-11-05T10:00:00+00:00"
    login = client.post(
        "/auth/login",
        json={"email": "new@cadivor.test", "password": "long-password-123"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["workspace"] == "Acme Hardware"
    assert body["trial_status"] == "trialing"
    started = datetime.fromisoformat(body["trial_started_at"])
    ends = datetime.fromisoformat(body["trial_ends_at"])
    assert (ends - started).days == 14

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["trial_ends_at"] == body["trial_ends_at"]

    again = client.post(
        "/auth/login",
        json={"email": "new@cadivor.test", "password": "long-password-123"},
    )
    assert again.status_code == 200
    assert again.json()["trial_started_at"] == body["trial_started_at"]
    assert again.json()["trial_ends_at"] == body["trial_ends_at"]


def test_signup_redirect_must_be_allowlisted_https(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_REDIRECT_URL", "http://attacker.example/login")
    monkeypatch.setenv(
        "CADIVOR_WEB_ORIGINS",
        "https://cadivor-next-web-prod-production.up.railway.app",
    )
    assert supabase_client.get("/auth/config").json()["signup_enabled"] is False
    response = supabase_client.post(
        "/auth/signup",
        json={
            "email": "new@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Acme",
            "accepted_terms": True,
        },
    )
    assert response.status_code == 503
    assert supabase_client.app.state.fake_auth.signup_payloads == []


def test_expired_trial_is_read_only_for_new_bom_analysis(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch,
):
    def _expired_entitlement(*, action: str, **_kwargs):
        if action == "entitlements":
            return {
                "ok": True,
                "plan": "Trial expired",
                "trial_started_at": "2025-12-18T12:00:00+00:00",
                "trial_ends_at": "2026-01-01T12:00:00+00:00",
                "trial_status": "trial_expired",
                "trial_days_remaining": 0,
            }, 200
        return {"ok": True, "charges_created": False}, 200

    monkeypatch.setattr(
        "apps.api.subscription_billing_service.request_action",
        _expired_entitlement,
    )
    login = supabase_client.post(
        "/auth/login",
        json={"email": "owner@cadivor.test", "password": "owner-pass-123"},
    )
    assert login.status_code == 200
    body = login.json()
    store = get_auth_store()
    store._data["memberships"][body["user_id"]]["trial_ends_at"] = "2025-01-01T00:00:00+00:00"
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    denied = supabase_client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("bom.csv", b"MPN,Quantity\nLM358DR,1\n", "text/csv")},
    )
    assert denied.status_code == 402
    assert denied.json()["code"] == "one_time_report_required"
    assert denied.json()["one_time_report"]["href"] == "/single-bom-report"
    assert supabase_client.get("/reports", headers=headers).status_code == 200



def test_signup_requires_explicit_email_and_abuse_protection_acknowledgments(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    monkeypatch.setenv(
        "CADIVOR_SIGNUP_REDIRECT_URL",
        "https://cadivor-next-web-prod-production.up.railway.app/login",
    )
    monkeypatch.setenv(
        "CADIVOR_WEB_ORIGINS",
        "https://cadivor-next-web-prod-production.up.railway.app",
    )
    assert supabase_client.get("/auth/config").json()["signup_enabled"] is False
    response = supabase_client.post(
        "/auth/signup",
        json={
            "email": "new@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Acme",
            "accepted_terms": True,
        },
    )
    assert response.status_code == 503
    assert supabase_client.app.state.fake_auth.signup_payloads == []


def test_decision_scope_and_snapshot_token_suites_in_ci() -> None:
    """Ensure decision-scope suites run in the AF regression pytest step."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_comparison_snapshot_scope_tokens.py",
            "tests/test_fr_compare_decision_scope_multi_mfr.py",
            "-q",
        ],
        cwd=root,
        check=False,
    )
    assert completed.returncode == 0
