"""Signup / invite registration require terms acceptance and persist versions."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.invitation_email import MemoryEmailSink, set_email_sink
import apps.api.main as api_main
from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.team_store import reset_team_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from apps.api import legal_acceptance
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

ROOT = Path(__file__).resolve().parents[1]
INVITEE = "invite-terms@cadivor.test"
INVITEE_PASSWORD = "InviteePassword!12"


@pytest.fixture
def sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.setenv("CADIVOR_LEGAL_ACCEPTANCE_PATH", str(tmp_path / "legal.json"))
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    reset_team_store_for_tests(tmp_path / "team.json")
    legal_acceptance.reset_legal_acceptances_for_tests()
    api_main._THROTTLE.clear()
    messages = MemoryEmailSink()
    set_email_sink(messages)
    yield messages
    set_email_sink(None)


@pytest.fixture
def client(sink: MemoryEmailSink) -> TestClient:
    del sink
    return TestClient(app)


def test_auth_config_exposes_published_versions(client: TestClient):
    res = client.get("/auth/config")
    assert res.status_code == 200
    body = res.json()
    assert body["terms_version"] == legal_acceptance.TERMS_VERSION
    assert body["privacy_version"] == legal_acceptance.PRIVACY_VERSION
    assert body["terms_url"].endswith("/#/terms")
    assert body["privacy_url"].endswith("/#/privacy")


def test_signup_rejects_missing_and_false_acceptance(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import apps.api.supabase_auth as supabase_auth

    monkeypatch.setattr(api_main, "_use_supabase_auth", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup_enabled", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup", lambda *a, **k: None)

    missing = client.post(
        "/auth/signup",
        json={
            "email": "terms-missing@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Terms Lab",
        },
    )
    assert missing.status_code == 400
    assert "terms" in missing.json()["detail"].lower()

    falsey = client.post(
        "/auth/signup",
        json={
            "email": "terms-false@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Terms Lab",
            "accepted_terms": False,
        },
    )
    assert falsey.status_code == 400

    ok = client.post(
        "/auth/signup",
        json={
            "email": "terms-ok@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Terms Lab",
            "accepted_terms": True,
            "terms_version": legal_acceptance.TERMS_VERSION,
            "privacy_version": legal_acceptance.PRIVACY_VERSION,
        },
    )
    assert ok.status_code == 202, ok.text
    rows = legal_acceptance.list_acceptances(email="terms-ok@cadivor.test")
    assert len(rows) == 1
    assert rows[0]["terms_version"] == legal_acceptance.TERMS_VERSION
    assert rows[0]["privacy_version"] == legal_acceptance.PRIVACY_VERSION
    assert rows[0]["source"] == "signup"
    assert rows[0]["accepted_at"]


def test_invitation_register_requires_acceptance_and_persists(
    client: TestClient, sink: MemoryEmailSink
):
    owner = client.post(
        "/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD}
    )
    assert owner.status_code == 200, owner.text
    headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}
    invite = client.post(
        "/workspace/invitations",
        headers=headers,
        json={"email": INVITEE, "role": "engineer"},
    )
    assert invite.status_code in (200, 201), invite.text
    invite_token = str(sink.messages[-1]["invite_url"]).split("invite=", 1)[1]

    rejected = client.post(
        "/invitations/register",
        json={
            "token": invite_token,
            "email": INVITEE,
            "password": INVITEE_PASSWORD,
        },
    )
    assert rejected.status_code == 400

    rejected_false = client.post(
        "/invitations/register",
        json={
            "token": invite_token,
            "email": INVITEE,
            "password": INVITEE_PASSWORD,
            "accepted_terms": False,
        },
    )
    assert rejected_false.status_code == 400

    accepted = client.post(
        "/invitations/register",
        json={
            "token": invite_token,
            "email": INVITEE,
            "password": INVITEE_PASSWORD,
            "accepted_terms": True,
            "terms_version": legal_acceptance.TERMS_VERSION,
            "privacy_version": legal_acceptance.PRIVACY_VERSION,
        },
    )
    assert accepted.status_code == 200, accepted.text
    rows = legal_acceptance.list_acceptances(email=INVITEE)
    assert len(rows) == 1
    assert rows[0]["source"] == "invitation"
    assert rows[0]["terms_version"] == legal_acceptance.TERMS_VERSION
    assert rows[0]["accepted_at"]


def test_ui_login_cta_and_terms_checkbox_contract():
    login = (ROOT / "apps/web/src/app/login/page.tsx").read_text(encoding="utf-8")
    signup = (ROOT / "apps/web/src/app/signup/page.tsx").read_text(encoding="utf-8")
    terms = (ROOT / "apps/web/src/components/TermsAcceptance.tsx").read_text(
        encoding="utf-8"
    )
    legal = (ROOT / "apps/web/src/lib/legalTerms.ts").read_text(encoding="utf-8")
    marketing = (ROOT / "marketing-web/index.html").read_text(encoding="utf-8")

    assert "Create an account · Start a 14-day trial" in login
    assert "signupEnabled" in login
    assert "New teammates join through a workspace invitation link" in login
    assert "TermsAcceptance" in signup and "TermsAcceptance" in login
    assert "TERMS_URL" in terms and "PRIVACY_URL" in terms
    assert "https://www.cadivor.com/#/terms" in legal
    assert "https://www.cadivor.com/#/privacy" in legal
    assert "Pre-launch" not in legal
    assert "requires review by qualified counsel" not in legal
    assert "Use of the service" in legal
    assert "Information we collect" in legal
    assert "Users are responsible for authorized use of their accounts" in marketing
    assert "Users are responsible for authorized use of their accounts" in legal
    assert "Cadivor does not sell personal information" in marketing
    assert "Cadivor does not sell personal information" in legal
    assert "acceptedTerms" in signup
    assert re.search(r"type=\"checkbox\"", terms)


def test_migration_file_exists():
    path = ROOT / "supabase/migrations/20261107_legal_acceptances.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8")
    assert "migration_legal_acceptances" in sql
    assert "terms_version" in sql
    assert "privacy_version" in sql
    assert "accepted_at" in sql
