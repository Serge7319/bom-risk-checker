"""Unauthenticated FastAPI surface for the Next.js free BOM audit."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from src.public_bom_stress_test import (
    MAX_BYTES,
    PUBLIC_BOM_LIMIT_MESSAGE,
    StressTestError,
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_public_bom_stress_status_requires_no_auth(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=True):
        response = client.get("/public/bom-stress/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["enabled"] is True
    assert payload["preview_rows"] == 5
    assert payload["max_rows"] == 30
    assert payload["max_bytes"] == MAX_BYTES


def test_public_bom_stress_status_reports_disabled_flag(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=False):
        response = client.get("/public/bom-stress/status")
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_public_bom_stress_audit_and_lead_fail_closed_when_disabled(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=False):
        audit = client.post(
            "/public/bom-stress/audit",
            files={"file": ("sample.csv", b"MPN,Qty\nLM358N,1\n", "text/csv")},
        )
        lead = client.post(
            "/public/bom-stress/lead",
            json={
                "report_id": "report-1",
                "email": "a@b.com",
                "accepted_terms": True,
            },
        )
    assert audit.status_code == 503
    assert lead.status_code == 503
    assert "being prepared" in audit.json()["detail"]


def test_public_bom_stress_audit_rejects_missing_file(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=True):
        response = client.post("/public/bom-stress/audit")
    assert response.status_code == 400
    assert "Missing file" in response.json()["detail"]


def test_public_bom_stress_audit_rejects_oversized_upload(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=True):
        response = client.post(
            "/public/bom-stress/audit",
            files={
                "file": (
                    "huge.csv",
                    b"MPN,Qty\n" + b"PART,1\n" + (b"x" * (MAX_BYTES + 1)),
                    "text/csv",
                )
            },
        )
    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]


def test_public_bom_stress_audit_rejects_row_limit_via_funnel(client: TestClient):
    bom = b"MPN,Qty\n" + b"".join(f"PART{i},1\n".encode() for i in range(31))
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.get_secret",
            side_effect=lambda key, required=False: "a" * 48
            if "HMAC" in str(key)
            else "",
        ),
    ):
        # Valid-looking HMAC so the request fails on row limits, not visitor forgery.
        import hashlib
        import hmac
        import time

        stamp = str(int(time.time()))
        ip = "203.0.113.10"
        sig = hmac.new(
            (b"a" * 48), f"v1|{stamp}|{ip}".encode(), hashlib.sha256
        ).hexdigest()
        header = f"v1;{stamp};{ip};{sig}"
        response = client.post(
            "/public/bom-stress/audit",
            files={"file": ("too-many.csv", bom, "text/csv")},
            headers={"X-Cadivor-Visitor": header},
        )
    assert response.status_code == 400
    assert "1–30" in response.json()["detail"] or "30" in response.json()["detail"]


def test_forged_visitor_header_cannot_bypass_rate_correlation(client: TestClient):
    """X-Cadivor-Visitor is HMAC-checked correlation data, not client-trusted identity."""
    import time

    stamp = str(int(time.time()))
    forged = f"v1;{stamp};203.0.113.10;{'0' * 64}"
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.get_secret",
            side_effect=lambda key, required=False: "a" * 48
            if "HMAC" in str(key)
            else "",
        ),
    ):
        response = client.post(
            "/public/bom-stress/audit",
            files={"file": ("sample.csv", b"MPN,Qty\nLM358N,1\n", "text/csv")},
            headers={"X-Cadivor-Visitor": forged},
        )
    assert response.status_code == 400
    assert "unavailable" in response.json()["detail"].lower()


def test_public_bom_stress_audit_returns_preview_only(client: TestClient):
    report = {
        "id": "report-1",
        "row_count": 6,
        "preview": [{"mpn": "LM358N", "risk": "Low"}],
        "remaining_count": 1,
        "remaining_high_risk": 0,
        "remaining_unverified": 0,
    }

    def fake_run(filename, payload, signed_header):
        assert filename.endswith(".csv")
        assert payload.startswith(b"MPN")
        assert signed_header == "v1;signed"
        return report

    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch("src.public_bom_stress_test.run_audit", side_effect=fake_run),
    ):
        response = client.post(
            "/public/bom-stress/audit",
            files={"file": ("sample.csv", b"MPN,Qty\nLM358N,1\n", "text/csv")},
            headers={"X-Cadivor-Visitor": "v1;signed"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["id"] == "report-1"
    assert payload["preview"][0]["mpn"] == "LM358N"
    assert payload["remaining_count"] == 1
    # Locked remaining rows must never appear in the anonymous response body.
    assert "results" not in payload
    assert "remaining_preview" not in payload
    assert set(payload) <= {
        "ok",
        "id",
        "row_count",
        "preview",
        "remaining_count",
        "remaining_high_risk",
        "remaining_unverified",
    }


def test_public_routes_do_not_expose_workspace_reports(client: TestClient):
    denied = client.get("/reports")
    assert denied.status_code in {401, 403}
    public = client.get("/public/bom-stress/status")
    assert public.status_code == 200


def test_public_bom_stress_audit_maps_daily_limit(client: TestClient):
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.run_audit",
            side_effect=StressTestError(PUBLIC_BOM_LIMIT_MESSAGE),
        ),
    ):
        response = client.post(
            "/public/bom-stress/audit",
            files={"file": ("sample.csv", b"MPN,Qty\nLM358N,1\n", "text/csv")},
        )
    assert response.status_code == 429
    assert response.json()["detail"] == PUBLIC_BOM_LIMIT_MESSAGE


def test_public_bom_stress_lead_requires_terms(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=True):
        response = client.post(
            "/public/bom-stress/lead",
            json={"report_id": "report-1", "email": "a@b.com", "accepted_terms": False},
        )
    assert response.status_code == 400
    assert "Terms" in response.json()["detail"]


def test_public_bom_stress_lead_sends_verification(client: TestClient):
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.capture_lead",
            return_value="engineer@company.com",
        ) as capture,
        patch("src.public_bom_stress_test.send_report_verification") as send,
    ):
        response = client.post(
            "/public/bom-stress/lead?utm_source=guide",
            json={
                "report_id": "report-1",
                "email": "engineer@company.com",
                "accepted_terms": True,
            },
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "email": "engineer@company.com"}
    capture.assert_called_once()
    assert capture.call_args.kwargs["source"] == "utm:guide"
    send.assert_called_once_with("engineer@company.com")


def test_public_audit_failure_logs_do_not_embed_bom_or_tokens(client: TestClient, caplog):
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.run_audit",
            side_effect=RuntimeError("boom"),
        ),
        caplog.at_level("ERROR"),
    ):
        response = client.post(
            "/public/bom-stress/audit",
            files={
                "file": (
                    "secret.csv",
                    b"MPN,Qty\nTOPSECRET-MPN,1\n",
                    "text/csv",
                )
            },
            headers={"Authorization": "Bearer super-secret-token"},
        )
    assert response.status_code == 503
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "public_bom_stress_audit_failed" in joined
    assert "TOPSECRET-MPN" not in joined
    assert "super-secret-token" not in joined
