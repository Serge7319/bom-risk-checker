"""Invite create → sink email → register → membership/role persisted."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.invitation_email import MemoryEmailSink, set_email_sink
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
def email_sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    reset_team_store_for_tests(tmp_path / "team.json")
    sink = MemoryEmailSink()
    set_email_sink(sink)
    yield sink
    set_email_sink(None)


def _auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_invite_create_register_accept_persists_role(email_sink: MemoryEmailSink):
    client = TestClient(app)
    headers = _auth_headers(client)

    created = client.post(
        "/workspace/invitations",
        headers=headers,
        json={"email": "invitee@cadivor.test", "role": "engineer"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body.get("email_sent") is True
    assert body.get("invitation")
    assert email_sink.messages
    invite_url = str(email_sink.messages[-1]["invite_url"])
    assert "invite=" in invite_url
    token = invite_url.split("invite=", 1)[1]

    lookup = client.get(f"/invitations/lookup?token={token}")
    assert lookup.status_code == 200
    preview = lookup.json()
    assert preview["email"] == "invitee@cadivor.test"
    assert preview["role"] == "engineer"
    assert "workspace_id" not in preview

    inviter_ws = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    ).json()["workspace_id"]

    registered = client.post(
        "/invitations/register",
        json={
            "token": token,
            "email": "invitee@cadivor.test",
            "password": "InviteePassword!1",
        },
    )
    assert registered.status_code == 200, registered.text
    reg = registered.json()
    assert reg["ok"] is True
    assert reg["accepted"]
    assert reg["accepted"][0]["role"] == "engineer"
    assert reg["accepted"][0]["workspace_id"] == inviter_ws

    login = client.post(
        "/auth/login",
        json={"email": "invitee@cadivor.test", "password": "InviteePassword!1"},
    )
    assert login.status_code == 200, login.text
    session = login.json()
    assert session["workspace_id"] == inviter_ws

    members = client.get(
        "/workspace/members",
        headers={"Authorization": f"Bearer {session['access_token']}"},
    )
    assert members.status_code == 200
    rows = members.json().get("members") or []
    emails = {str(row.get("email") or "").lower() for row in rows}
    assert "invitee@cadivor.test" in emails


def test_profile_preferences_persist_after_refresh(email_sink: MemoryEmailSink):
    del email_sink  # fixture sets stores/sink
    client = TestClient(app)
    headers = _auth_headers(client)
    patched = client.patch(
        "/settings/profile",
        headers=headers,
        json={
            "full_name": "Parity Tester",
            "company_name": "Cadivor Lab",
            "job_title": "Engineer",
            "country": "US",
            "language": "en",
            "timezone": "America/New_York",
        },
    )
    assert patched.status_code == 200, patched.text
    prefs = client.patch(
        "/settings/preferences",
        headers=headers,
        json={
            "appearance": "light",
            "density": "compact",
            "default_units": "imperial",
            "default_currency": "USD",
            "monitoring_notifications": True,
            "notification_preferences": {
                "product_updates": True,
                "marketing_emails": False,
            },
        },
    )
    assert prefs.status_code == 200, prefs.text

    profile = client.get("/settings/profile", headers=headers).json()
    assert profile.get("full_name") == "Parity Tester"
    saved_prefs = client.get("/settings/preferences", headers=headers).json()
    assert saved_prefs.get("appearance") == "light"
