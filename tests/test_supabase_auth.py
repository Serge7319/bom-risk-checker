"""Production Supabase Auth path for the Next migration API (mocked Auth client)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api import supabase_auth
from apps.api.main import app
from apps.api.sandbox_auth import get_auth_store, reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from src.services.user_provisioning import (
    UserProvisioningError,
    build_default_user_row,
)


class _FakeUser:
    def __init__(
        self,
        user_id: str,
        email: str,
        *,
        email_confirmed_at: str | None = "2026-11-01T12:00:00+00:00",
        user_metadata: dict | None = None,
        created_at: str | None = None,
    ) -> None:
        self.id = user_id
        self.email = email
        self.email_confirmed_at = email_confirmed_at
        self.user_metadata = user_metadata or {}
        self.created_at = created_at or "2026-01-01T00:00:00+00:00"


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
    billing_profiles: dict[str, dict] = {}

    def _fake_client(_url: str, _key: str, **_kwargs):
        postgrest = SimpleNamespace(auth=lambda _token: None)
        return SimpleNamespace(auth=fake, postgrest=postgrest)

    monkeypatch.setattr("supabase.create_client", _fake_client)

    def _ensure_profile(supabase, auth_user, **_kwargs):
        del supabase
        user_id = str(getattr(auth_user, "id", "") or "")
        existing = billing_profiles.get(user_id)
        if existing is not None:
            profile = dict(existing)
            metadata = getattr(auth_user, "user_metadata", {}) or {}
            intent = str(metadata.get("cadivor_signup_intent") or "").strip().lower()
            plan = str(profile.get("plan") or "").strip().lower()
            protected = any(
                str(profile.get(key) or "").strip()
                for key in (
                    "stripe_customer_id",
                    "stripe_subscription_id",
                    "stripe_price_id",
                    "stripe_subscription_status",
                    "plan_grandfather_source",
                )
            )
            if (
                plan == "starter"
                and intent in {"", "standard_trial"}
                and profile.get("trial_started_at") in (None, "")
                and profile.get("trial_ends_at") in (None, "")
                and not protected
            ):
                now = datetime.now(timezone.utc)
                profile.update(
                    {
                        "plan": "Trial",
                        "trial_started_at": now.isoformat(),
                        "trial_ends_at": (now + timedelta(days=14)).isoformat(),
                    }
                )
                billing_profiles[user_id] = dict(profile)
            return dict(profile), False
        row = build_default_user_row(auth_user)
        billing_profiles[user_id] = dict(row)
        return dict(row), True

    monkeypatch.setattr(
        "src.services.user_provisioning.ensure_user_profile",
        _ensure_profile,
    )

    def _billing_action(*, access_token: str, action: str, **_kwargs):
        user = fake._by_token.get(access_token)
        profile = billing_profiles.get(str(getattr(user, "id", "") or ""), {})
        if action == "entitlements":
            plan = str(profile.get("plan") or "Trial")
            started = profile.get("trial_started_at")
            ends = profile.get("trial_ends_at")
            if plan == "Trial" and ends:
                end_dt = datetime.fromisoformat(str(ends).replace("Z", "+00:00"))
                remaining = max(
                    0,
                    int(
                        (
                            end_dt - datetime.now(timezone.utc)
                        ).total_seconds()
                        // 86400
                    )
                    + 1,
                )
                return {
                    "ok": True,
                    "plan": "Trial",
                    "trial_started_at": started,
                    "trial_ends_at": ends,
                    "trial_status": "trialing",
                    "trial_days_remaining": remaining,
                }, 200
            if plan.lower() == "student":
                return {"ok": True, "plan": "Student"}, 200
            if str(profile.get("plan_grandfather_source") or "").strip():
                return {"ok": True, "plan": "Grandfathered beta"}, 200
            billing_status = str(
                profile.get("stripe_subscription_status") or ""
            ).strip().lower()
            if plan in {"Starter", "Professional", "Business", "Enterprise"} and (
                billing_status in {"active", "trialing"} or plan == "Enterprise"
            ):
                return {"ok": True, "plan": plan}, 200
            if plan == "Subscription inactive":
                return {"ok": True, "plan": "Subscription inactive"}, 200
            # Seeded fixture users without a provisioned billing row keep a
            # stable Trial snapshot so existing login tests stay deterministic.
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
    # Expose billing store for focused assertions.
    # Attached after client creation below.
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
    client.app.state.billing_profiles = billing_profiles
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
    # Existing paid billing row is preserved; membership plan is aligned to it.
    supabase_client.app.state.billing_profiles[user_id] = {
        "id": user_id,
        "email": "owner@cadivor.test",
        "plan": "Business",
        "stripe_subscription_status": "active",
        "stripe_customer_id": "cus_owner",
    }

    login = supabase_client.post(
        "/auth/login",
        json={"email": "owner@cadivor.test", "password": "owner-pass-123"},
    )

    assert login.status_code == 200
    assert login.json()["plan"] == "Business"
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
        lambda *_a, **_k: SimpleNamespace(
            auth=fake, postgrest=SimpleNamespace(auth=lambda _token: None)
        ),
    )
    owner = fake.users["owner@cadivor.test"]["user"]

    def _ensure_profile(supabase, auth_user, **_kwargs):
        del supabase
        return (
            {
                "id": str(getattr(auth_user, "id", "")),
                "email": str(getattr(auth_user, "email", "")),
                "plan": "Trial",
                "trial_started_at": "2026-11-01T12:00:00+00:00",
                "trial_ends_at": "2026-11-15T12:00:00+00:00",
            },
            False,
        )

    monkeypatch.setattr(
        "src.services.user_provisioning.ensure_user_profile",
        _ensure_profile,
    )
    monkeypatch.setattr(
        "apps.api.subscription_billing_service.request_action",
        lambda **_kwargs: (
            {
                "ok": True,
                "plan": "Trial",
                "trial_started_at": "2026-11-01T12:00:00+00:00",
                "trial_ends_at": "2026-11-15T12:00:00+00:00",
                "trial_status": "trialing",
                "trial_days_remaining": 8,
            },
            200,
        ),
    )
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
    assert payload["options"]["email_redirect_to"] == (
        "https://cadivor-next-web-prod-production.up.railway.app/login"
    )
    assert payload["options"]["data"]["workspace_name"] == "Acme Hardware"
    assert payload["options"]["data"]["cadivor_signup_intent"] == "standard_trial"
    user = fake.users["new@cadivor.test"]["user"]
    assert get_auth_store().membership_for_user(user.id) is None

    unverified = client.post(
        "/auth/login",
        json={"email": "new@cadivor.test", "password": "long-password-123"},
    )
    assert unverified.status_code == 403
    assert get_auth_store().membership_for_user(user.id) is None
    assert user.id not in client.app.state.billing_profiles

    user.email_confirmed_at = "2026-11-05T10:00:00+00:00"
    # Auth account may have been created well before the first verified sign-in.
    user.created_at = "2026-10-01T00:00:00+00:00"
    before = datetime.now(timezone.utc)
    login = client.post(
        "/auth/login",
        json={"email": "new@cadivor.test", "password": "long-password-123"},
    )
    after = datetime.now(timezone.utc)
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["workspace"] == "Acme Hardware"
    assert body["plan"] == "Trial"
    assert body["trial_status"] == "trialing"
    started = datetime.fromisoformat(body["trial_started_at"])
    ends = datetime.fromisoformat(body["trial_ends_at"])
    assert (ends - started).days == 14
    assert before - timedelta(seconds=2) <= started <= after + timedelta(seconds=2)
    assert started.date() != datetime.fromisoformat(user.created_at).date()

    billing = client.app.state.billing_profiles[user.id]
    assert billing["plan"] == "Trial"
    assert billing["trial_started_at"] == body["trial_started_at"]
    assert billing["trial_ends_at"] == body["trial_ends_at"]
    membership = get_auth_store().membership_for_user(user.id)
    assert membership is not None
    assert membership["trial_started_at"] == body["trial_started_at"]
    assert membership["trial_ends_at"] == body["trial_ends_at"]
    assert membership["subscription_status"] == "trialing"

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["trial_ends_at"] == body["trial_ends_at"]
    assert me.json()["plan"] == "Trial"

    again = client.post(
        "/auth/login",
        json={"email": "new@cadivor.test", "password": "long-password-123"},
    )
    assert again.status_code == 200
    assert again.json()["trial_started_at"] == body["trial_started_at"]
    assert again.json()["trial_ends_at"] == body["trial_ends_at"]
    assert again.json()["plan"] == "Trial"


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


def test_production_signup_redirect_uses_app_cadivor_login(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Password signup email_redirect_to must be the Next /login confirmation URL."""
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED", "1")
    monkeypatch.setenv(
        "CADIVOR_SIGNUP_REDIRECT_URL",
        "https://app.cadivor.com/login",
    )
    monkeypatch.setenv("CADIVOR_WEB_ORIGINS", "https://app.cadivor.com")
    response = supabase_client.post(
        "/auth/signup",
        json={
            "email": "prod-redirect@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Prod Redirect",
            "accepted_terms": True,
        },
    )
    assert response.status_code == 202, response.text
    payload = supabase_client.app.state.fake_auth.signup_payloads[-1]
    assert payload["options"]["email_redirect_to"] == "https://app.cadivor.com/login"


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


def test_trial_signup_login_allows_analysis_and_saved_report(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED", "1")
    monkeypatch.setenv(
        "CADIVOR_SIGNUP_REDIRECT_URL",
        "https://app.cadivor.com/login",
    )
    monkeypatch.setenv("CADIVOR_WEB_ORIGINS", "https://app.cadivor.com")
    client = supabase_client
    assert (
        client.post(
            "/auth/signup",
            json={
                "email": "trial-analyze@cadivor.test",
                "password": "long-password-123",
                "workspace_name": "Trial Analyze",
                "accepted_terms": True,
            },
        ).status_code
        == 202
    )
    fake = client.app.state.fake_auth
    user = fake.users["trial-analyze@cadivor.test"]["user"]
    user.email_confirmed_at = "2026-11-13T12:00:00+00:00"
    login = client.post(
        "/auth/login",
        json={
            "email": "trial-analyze@cadivor.test",
            "password": "long-password-123",
        },
    )
    assert login.status_code == 200, login.text
    assert login.json()["plan"] == "Trial"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    analyzed = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("bom.csv", b"MPN,Quantity\nLM358DR,1\n", "text/csv")},
    )
    assert analyzed.status_code == 200, analyzed.text
    analysis_id = analyzed.json()["analysis_id"]
    saved = client.get(f"/reports/{analysis_id}", headers=headers)
    assert saved.status_code == 200
    assert saved.json()["analysis_id"] == analysis_id


def test_one_time_report_signup_does_not_receive_trial(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED", "1")
    monkeypatch.setenv(
        "CADIVOR_SIGNUP_REDIRECT_URL", "https://app.cadivor.com/login"
    )
    monkeypatch.setenv("CADIVOR_WEB_ORIGINS", "https://app.cadivor.com")
    client = supabase_client
    fake = client.app.state.fake_auth
    user = _FakeUser(
        "44444444-4444-4444-4444-444444444444",
        "report-only@cadivor.test",
        email_confirmed_at="2026-11-13T12:00:00+00:00",
        user_metadata={"cadivor_signup_intent": "one_time_report"},
    )
    fake.users["report-only@cadivor.test"] = {
        "password": "long-password-123",
        "user": user,
        "token": "supabase-access-token-report",
    }
    fake._by_token["supabase-access-token-report"] = user
    login = client.post(
        "/auth/login",
        json={"email": "report-only@cadivor.test", "password": "long-password-123"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["plan"] == "Subscription inactive"
    assert "trial_status" not in body or body.get("trial_status") in {
        None,
        "trial_expired",
    }
    billing = client.app.state.billing_profiles[user.id]
    assert billing["plan"] == "Subscription inactive"
    membership = get_auth_store().membership_for_user(user.id)
    assert membership["subscription_status"] == "inactive"


def test_paid_student_and_grandfathered_plans_are_preserved_on_signin(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED", "1")
    monkeypatch.setenv(
        "CADIVOR_SIGNUP_REDIRECT_URL", "https://app.cadivor.com/login"
    )
    monkeypatch.setenv("CADIVOR_WEB_ORIGINS", "https://app.cadivor.com")
    client = supabase_client
    fake = client.app.state.fake_auth
    cases = [
        (
            "paid@cadivor.test",
            "55555555-5555-5555-5555-555555555555",
            {
                "id": "55555555-5555-5555-5555-555555555555",
                "email": "paid@cadivor.test",
                "plan": "Professional",
                "stripe_subscription_status": "active",
                "stripe_customer_id": "cus_paid",
            },
            "Professional",
        ),
        (
            "student@cadivor.test",
            "66666666-6666-6666-6666-666666666666",
            {
                "id": "66666666-6666-6666-6666-666666666666",
                "email": "student@cadivor.test",
                "plan": "Student",
            },
            "Student",
        ),
        (
            "gf@cadivor.test",
            "77777777-7777-7777-7777-777777777777",
            {
                "id": "77777777-7777-7777-7777-777777777777",
                "email": "gf@cadivor.test",
                "plan": "Starter",
                "plan_grandfather_source": "beta",
            },
            "Grandfathered beta",
        ),
    ]
    for email, user_id, profile, expected_plan in cases:
        user = _FakeUser(
            user_id,
            email,
            email_confirmed_at="2026-01-01T00:00:00+00:00",
            user_metadata={"cadivor_signup_intent": "standard_trial"},
        )
        token = f"supabase-access-token-{email}"
        fake.users[email] = {"password": "long-password-123", "user": user, "token": token}
        fake._by_token[token] = user
        client.app.state.billing_profiles[user_id] = dict(profile)
        login = client.post(
            "/auth/login",
            json={"email": email, "password": "long-password-123"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["plan"] == expected_plan
        assert client.app.state.billing_profiles[user_id]["plan"] == profile["plan"]


def test_broken_flow_starter_receives_full_trial_from_signin_not_created_at(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED", "1")
    monkeypatch.setenv(
        "CADIVOR_SIGNUP_REDIRECT_URL", "https://app.cadivor.com/login"
    )
    monkeypatch.setenv("CADIVOR_WEB_ORIGINS", "https://app.cadivor.com")
    client = supabase_client
    fake = client.app.state.fake_auth
    created_at = "2026-10-01T00:00:00+00:00"
    user = _FakeUser(
        "88888888-8888-8888-8888-888888888888",
        "broken-starter@cadivor.test",
        email_confirmed_at="2026-11-13T12:00:00+00:00",
        user_metadata={"cadivor_signup_intent": "standard_trial"},
        created_at=created_at,
    )
    token = "supabase-access-token-broken-starter"
    fake.users["broken-starter@cadivor.test"] = {
        "password": "long-password-123",
        "user": user,
        "token": token,
    }
    fake._by_token[token] = user
    client.app.state.billing_profiles[user.id] = {
        "id": user.id,
        "email": user.email,
        "plan": "Starter",
        "trial_started_at": None,
        "trial_ends_at": None,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "stripe_price_id": None,
        "stripe_subscription_status": None,
        "plan_grandfather_source": None,
    }
    before = datetime.now(timezone.utc)
    login = client.post(
        "/auth/login",
        json={
            "email": "broken-starter@cadivor.test",
            "password": "long-password-123",
        },
    )
    after = datetime.now(timezone.utc)
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["plan"] == "Trial"
    started = datetime.fromisoformat(body["trial_started_at"])
    ends = datetime.fromisoformat(body["trial_ends_at"])
    assert (ends - started).days == 14
    assert before - timedelta(seconds=2) <= started <= after + timedelta(seconds=2)
    assert started.date() != datetime.fromisoformat(created_at).date()
    billing = client.app.state.billing_profiles[user.id]
    assert billing["trial_started_at"] == body["trial_started_at"]
    membership = get_auth_store().membership_for_user(user.id)
    assert membership["trial_started_at"] == body["trial_started_at"]
    assert membership["trial_ends_at"] == body["trial_ends_at"]

    again = client.post(
        "/auth/login",
        json={
            "email": "broken-starter@cadivor.test",
            "password": "long-password-123",
        },
    )
    assert again.status_code == 200
    assert again.json()["trial_started_at"] == body["trial_started_at"]
    assert again.json()["trial_ends_at"] == body["trial_ends_at"]


def test_bearer_requests_do_not_provision_trial(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    client = supabase_client
    fake = client.app.state.fake_auth
    user = _FakeUser(
        "99999999-9999-9999-9999-999999999999",
        "bearer-only@cadivor.test",
        email_confirmed_at="2026-11-13T12:00:00+00:00",
        user_metadata={"cadivor_signup_intent": "standard_trial"},
    )
    token = "supabase-access-token-bearer-only"
    fake.users["bearer-only@cadivor.test"] = {
        "password": "long-password-123",
        "user": user,
        "token": token,
    }
    fake._by_token[token] = user
    # Membership exists (e.g. invite path) but billing was never provisioned.
    supabase_auth.ensure_owner_membership(
        user_id=user.id,
        email=user.email,
        workspace_name="Bearer Only",
        allow_create=True,
    )
    assert user.id not in client.app.state.billing_profiles
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert user.id not in client.app.state.billing_profiles


def test_provisioning_failure_on_signin_is_clear_and_retryable(
    supabase_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CADIVOR_SELF_SERVE_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED", "1")
    monkeypatch.setenv("CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED", "1")
    monkeypatch.setenv(
        "CADIVOR_SIGNUP_REDIRECT_URL", "https://app.cadivor.com/login"
    )
    monkeypatch.setenv("CADIVOR_WEB_ORIGINS", "https://app.cadivor.com")
    client = supabase_client
    fake = client.app.state.fake_auth
    user = _FakeUser(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "provision-fail@cadivor.test",
        email_confirmed_at="2026-11-13T12:00:00+00:00",
        user_metadata={"cadivor_signup_intent": "standard_trial"},
    )
    token = "supabase-access-token-provision-fail"
    fake.users["provision-fail@cadivor.test"] = {
        "password": "long-password-123",
        "user": user,
        "token": token,
    }
    fake._by_token[token] = user

    with patch(
        "src.services.user_provisioning.ensure_user_profile",
        side_effect=UserProvisioningError(
            "Could not start the Cadivor trial. Sign in again in a moment."
        ),
    ):
        failed = client.post(
            "/auth/login",
            json={
                "email": "provision-fail@cadivor.test",
                "password": "long-password-123",
            },
        )
    assert failed.status_code == 503
    assert "sign in again" in failed.json()["detail"].lower()

    # Retry succeeds once provisioning recovers.
    recovered = client.post(
        "/auth/login",
        json={
            "email": "provision-fail@cadivor.test",
            "password": "long-password-123",
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["plan"] == "Trial"


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
