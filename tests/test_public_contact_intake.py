from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api import marketing_leads
from apps.api.main import app


@pytest.fixture
def contact_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    store = marketing_leads.FileMarketingLeadStore(tmp_path / "leads.json")
    marketing_leads.set_store_for_tests(store)
    from apps.api import main

    with main._THROTTLE_LOCK:
        main._THROTTLE.clear()
    try:
        yield TestClient(app), store
    finally:
        marketing_leads.set_store_for_tests(None)
        with main._THROTTLE_LOCK:
            main._THROTTLE.clear()


def _payload(**updates):
    body = {
        "name": "Jordan Engineer",
        "email": "jordan@example.com",
        "company": "Example Hardware",
        "role": "Hardware Engineering Lead",
        "team_size": "11–50",
        "bom_volume": "6–20 BOMs/month",
        "topic": "demo",
        "message": "We want to review release blockers across our controller BOMs.",
        "consent": True,
        "source": "pricing",
        "utm": {"utm_source": "newsletter", "untrusted": "drop me"},
    }
    return {**body, **updates}


def test_public_contact_persists_and_notifies_without_exposing_internal_id(
    contact_client, monkeypatch: pytest.MonkeyPatch
):
    client, store = contact_client
    sent: list[dict] = []

    from src import email_delivery

    monkeypatch.setattr(email_delivery, "email_delivery_configured", lambda: True)
    monkeypatch.setattr(marketing_leads, "send_contact_notification", sent.append)

    response = client.post("/public/contact", json=_payload())

    assert response.status_code == 201
    assert response.json() == {
        "ok": True,
        "received": True,
        "notification_status": "sent",
    }
    assert len(store._data["leads"]) == 1
    lead = next(iter(store._data["leads"].values()))
    assert lead["email"] == "jordan@example.com"
    assert lead["topic"] == "demo"
    assert lead["utm"] == {"utm_source": "newsletter"}
    assert lead["notification_status"] == "sent"
    assert sent[0]["message"] == _payload()["message"]
    assert "id" not in response.json()


def test_public_contact_saves_request_but_discloses_unconfigured_email(
    contact_client, monkeypatch: pytest.MonkeyPatch
):
    client, store = contact_client
    from src import email_delivery

    monkeypatch.setattr(email_delivery, "email_delivery_configured", lambda: False)
    monkeypatch.setattr(
        marketing_leads,
        "send_contact_notification",
        lambda _lead: pytest.fail("must not call the provider without configuration"),
    )

    response = client.post("/public/contact", json=_payload(topic="student"))

    assert response.status_code == 202
    assert response.json()["notification_status"] == "not_configured"
    lead = next(iter(store._data["leads"].values()))
    assert lead["topic"] == "student"
    assert lead["notification_status"] == "not_configured"


def test_public_contact_honeypot_is_accepted_without_saving(contact_client):
    client, store = contact_client

    response = client.post("/public/contact", json=_payload(website="bot-filled"))

    assert response.status_code == 201
    assert response.json()["received"] is True
    assert store._data["leads"] == {}


@pytest.mark.parametrize(
    ("updates", "status"),
    [
        ({"consent": False}, 400),
        ({"email": "not-an-email"}, 400),
        ({"message": "x" * 4001}, 400),
    ],
)
def test_public_contact_validates_required_consent_and_field_bounds(
    contact_client, updates, status
):
    client, store = contact_client

    response = client.post("/public/contact", json=_payload(**updates))

    assert response.status_code == status
    assert store._data["leads"] == {}
