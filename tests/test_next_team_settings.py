"""Team/invitation guardrails and settings persistence (sandbox auth, email sink)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.invitation_email import MemoryEmailSink, set_email_sink
import apps.api.main as api_main
from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.team_store import get_team_store, reset_team_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

INVITEE = "newhire@cadivor.test"
INVITEE_PASSWORD = "NewHirePassword!12"


@pytest.fixture
def sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    reset_team_store_for_tests(tmp_path / "team.json")
    api_main._THROTTLE.clear()
    messages = MemoryEmailSink()
    set_email_sink(messages)
    yield messages
    set_email_sink(None)


@pytest.fixture
def client(sink: MemoryEmailSink) -> TestClient:
    del sink
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


def _headers(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def _invite(client: TestClient, headers: dict, email: str = INVITEE, role: str = "engineer"):
    return client.post(
        "/workspace/invitations", headers=headers, json={"email": email, "role": role}
    )


def _token(sink: MemoryEmailSink) -> str:
    return str(sink.messages[-1]["invite_url"]).split("invite=", 1)[1]


def test_invite_requires_authentication(client: TestClient):
    res = client.post("/workspace/invitations", json={"email": INVITEE, "role": "viewer"})
    assert res.status_code in (401, 403)


def test_invite_role_must_be_assignable(client: TestClient):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    res = _invite(client, _headers(owner), role="owner")
    assert res.status_code == 400


def test_duplicate_pending_invite_conflicts(client: TestClient):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    assert _invite(client, _headers(owner)).status_code == 201
    assert _invite(client, _headers(owner)).status_code == 409


def test_cancelled_invite_cannot_be_used(client: TestClient, sink: MemoryEmailSink):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    headers = _headers(owner)
    created = _invite(client, headers).json()
    token = _token(sink)
    invite_id = created["invitation"]["id"]
    assert client.delete(f"/workspace/invitations/{invite_id}", headers=headers).status_code == 200

    assert client.get(f"/invitations/lookup?token={token}").status_code == 404
    res = client.post(
        "/invitations/register",
        json={"token": token, "email": INVITEE, "password": INVITEE_PASSWORD},
    )
    assert res.status_code == 404


def test_expired_invite_is_not_accepted(client: TestClient, sink: MemoryEmailSink):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    created = _invite(client, _headers(owner)).json()
    token = _token(sink)
    team = get_team_store()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    team.update_invite(created["invitation"]["id"], {"expires_at": past})

    assert client.get(f"/invitations/lookup?token={token}").status_code == 404
    res = client.post(
        "/invitations/register",
        json={"token": token, "email": INVITEE, "password": INVITEE_PASSWORD},
    )
    assert res.status_code == 404


def test_register_requires_invited_email(client: TestClient, sink: MemoryEmailSink):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    _invite(client, _headers(owner))
    res = client.post(
        "/invitations/register",
        json={
            "token": _token(sink),
            "email": "someone-else@cadivor.test",
            "password": INVITEE_PASSWORD,
        },
    )
    assert res.status_code == 400


def test_browser_supplied_workspace_and_role_are_ignored(
    client: TestClient, sink: MemoryEmailSink
):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    _invite(client, _headers(owner), role="viewer")
    res = client.post(
        "/invitations/register",
        json={
            "token": _token(sink),
            "email": INVITEE,
            "password": INVITEE_PASSWORD,
            "role": "owner",
            "workspace_id": "attacker-workspace",
        },
    )
    assert res.status_code == 200, res.text
    accepted = res.json()["accepted"][0]
    assert accepted["role"] == "viewer"
    assert accepted["workspace_id"] == owner["workspace_id"]


def test_token_is_single_use(client: TestClient, sink: MemoryEmailSink):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    _invite(client, _headers(owner))
    token = _token(sink)
    body = {"token": token, "email": INVITEE, "password": INVITEE_PASSWORD}
    assert client.post("/invitations/register", json=body).status_code == 200
    assert client.post("/invitations/register", json=body).status_code == 404


def test_invited_engineer_cannot_manage_team(client: TestClient, sink: MemoryEmailSink):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    _invite(client, _headers(owner), role="engineer")
    client.post(
        "/invitations/register",
        json={"token": _token(sink), "email": INVITEE, "password": INVITEE_PASSWORD},
    )
    member = _login(client, INVITEE, INVITEE_PASSWORD)
    listed = client.get("/workspace/invitations", headers=_headers(member))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body.get("can_manage") is False
    assert body.get("invitations") == []
    res = client.post(
        "/workspace/invitations",
        headers=_headers(member),
        json={"email": "third@cadivor.test", "role": "viewer"},
    )
    assert res.status_code == 403


def test_settings_profile_patch_persists_for_member(client: TestClient, sink: MemoryEmailSink):
    """Settings UI uses /settings/profile; persistence must not depend on admin invite APIs."""
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    _invite(client, _headers(owner), role="engineer")
    client.post(
        "/invitations/register",
        json={"token": _token(sink), "email": INVITEE, "password": INVITEE_PASSWORD},
    )
    member = _login(client, INVITEE, INVITEE_PASSWORD)
    headers = _headers(member)
    saved = client.patch(
        "/settings/profile",
        headers=headers,
        json={
            "full_name": "Manda Example",
            "company_name": "Cadivor Lab",
            "job_title": "Component Engineer",
            "country": "United States",
            "language": "en",
            "timezone": "America/New_York",
        },
    )
    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert payload.get("full_name") == "Manda Example" or (
        (payload.get("profile") or {}).get("full_name") == "Manda Example"
    )
    again = client.get("/settings/profile", headers=headers)
    assert again.status_code == 200, again.text
    profile = again.json()
    row = profile.get("profile") if isinstance(profile.get("profile"), dict) else profile
    assert row["full_name"] == "Manda Example"
    assert row["company_name"] == "Cadivor Lab"
    assert row["job_title"] == "Component Engineer"
    assert row["country"] == "United States"
    assert row["timezone"] == "America/New_York"
    assert str(row["email"]).lower() == INVITEE.lower()


def test_resend_rotates_token(client: TestClient, sink: MemoryEmailSink):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    headers = _headers(owner)
    created = _invite(client, headers).json()
    first = _token(sink)
    team = get_team_store()
    # Skip the resend cool-down so the rotation itself is what is under test.
    team.update_invite(
        created["invitation"]["id"],
        {"last_sent_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()},
    )
    res = client.post(
        f"/workspace/invitations/{created['invitation']['id']}/resend", headers=headers
    )
    assert res.status_code == 200, res.text
    second = _token(sink)
    assert first != second
    assert client.get(f"/invitations/lookup?token={first}").status_code == 404
    assert client.get(f"/invitations/lookup?token={second}").status_code == 200


def test_workspace_settings_admin_only_and_persist(client: TestClient, sink: MemoryEmailSink):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    headers = _headers(owner)
    saved = client.patch(
        "/workspace/settings",
        headers=headers,
        json={"name": "Parity Lab", "timezone": "Europe/Berlin", "default_units": "metric"},
    )
    assert saved.status_code == 200, saved.text
    again = client.get("/workspace/settings", headers=headers).json()
    assert "Parity Lab" in str(again)
    assert "Europe/Berlin" in str(again)

    _invite(client, headers, role="viewer")
    client.post(
        "/invitations/register",
        json={"token": _token(sink), "email": INVITEE, "password": INVITEE_PASSWORD},
    )
    member = _login(client, INVITEE, INVITEE_PASSWORD)
    denied = client.patch(
        "/workspace/settings", headers=_headers(member), json={"name": "Hijacked"}
    )
    assert denied.status_code == 403


def test_profile_rejects_invalid_timezone_and_never_changes_email(client: TestClient):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    headers = _headers(owner)
    bad = client.patch("/profile", headers=headers, json={"timezone": "Mars/Olympus"})
    assert bad.status_code == 400
    # Email is Auth-managed: an edit attempt is refused outright.
    refused = client.patch("/profile", headers=headers, json={"email": "evil@cadivor.test"})
    assert refused.status_code == 400
    ok = client.patch("/profile", headers=headers, json={"full_name": "Pat Example"})
    assert ok.status_code == 200, ok.text
    profile = client.get("/profile", headers=headers).json()
    assert profile["full_name"] == "Pat Example"
    assert str(profile["email"]).lower() == SMOKE_EMAIL.lower()


def test_notification_preferences_round_trip(client: TestClient):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    headers = _headers(owner)
    res = client.patch(
        "/preferences",
        headers=headers,
        json={
            "monitoring_notifications": False,
            "notification_preferences": {"team_activity": False, "marketing_emails": True},
        },
    )
    assert res.status_code == 200, res.text
    prefs = client.get("/preferences", headers=headers).json()
    assert prefs["monitoring_notifications"] is False
    assert prefs["notification_preferences"]["team_activity"] is False
    assert prefs["notification_preferences"]["marketing_emails"] is True


def test_security_status_marks_two_factor_as_planned(client: TestClient):
    owner = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    res = client.get("/security/status", headers=_headers(owner))
    assert res.status_code == 200, res.text
    assert res.json()["two_factor"]["status"] == "planned"
