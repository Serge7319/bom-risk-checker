from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from apps.api import marketing_analytics, marketing_leads
from apps.api.main import app


def test_demo_request_and_consent_analytics_are_recorded_without_sending_email(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    leads = marketing_leads.FileMarketingLeadStore(tmp_path / "leads.json")
    analytics = marketing_analytics._FileStore()
    marketing_leads.set_store_for_tests(leads)
    marketing_analytics.set_store_for_tests(analytics)

    from apps.api import main
    from src import email_delivery

    monkeypatch.setattr(email_delivery, "email_delivery_configured", lambda: False)
    with main._THROTTLE_LOCK:
        main._THROTTLE.clear()
    client = TestClient(app)
    try:
        contact = client.post(
            "/public/contact",
            json={
                "name": "Synthetic Demo Request",
                "email": "demo-test@example.invalid",
                "company": "Synthetic Test",
                "role": "Engineering",
                "topic": "demo",
                "message": "Synthetic test of the demo request path.",
                "consent": True,
                "source": "marketing-contact",
            },
        )
        assert contact.status_code == 202
        assert contact.json() == {
            "ok": True,
            "received": True,
            "notification_status": "not_configured",
        }
        assert len(leads._data["leads"]) == 1
        assert next(iter(leads._data["leads"].values()))["notification_status"] == "not_configured"

        event = client.post(
            "/public/analytics",
            json={
                "event": "demo_requested",
                "source": "marketing",
                "page": "/contact/",
                "session_id": str(uuid4()),
                "properties": {"intent": "demo", "location": "contact-form"},
            },
        )
        assert event.status_code == 202
        assert event.json() == {"ok": True, "accepted": True}
        summary = analytics.summary(30)
        demo_row = next(row for row in summary["rows"] if row["event"] == "demo_requested")
        assert demo_row["events"] == 1
        assert demo_row["sessions"] == 1
    finally:
        marketing_leads.set_store_for_tests(None)
        marketing_analytics.set_store_for_tests(None)
        with main._THROTTLE_LOCK:
            main._THROTTLE.clear()
