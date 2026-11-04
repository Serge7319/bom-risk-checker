"""Synthetic migration API — no Stripe, email, or live suppliers."""
from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from apps.api.main import SMOKE_EMAIL, SMOKE_PASSWORD, SMOKE_TOKEN, app

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv"


def test_health_and_synthetic_bom_flow():
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["ok"] is True
    assert health["suppliers"] == "disabled"
    assert health["stripe"] == "disabled"
    assert health["email"] == "disabled"

    bad = client.post(
        "/auth/smoke-login",
        json={"email": "nope@example.com", "password": "x"},
    )
    assert bad.status_code == 401

    login = client.post(
        "/auth/smoke-login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert token == SMOKE_TOKEN

    with CSV.open("rb") as handle:
        analyze = client.post(
            "/boms/analyze",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("synthetic_bom_25parts.csv", handle, "text/csv")},
        )
    assert analyze.status_code == 200, analyze.text
    body = analyze.json()
    assert body["total_parts"] == 25
    assert body["health_score"] is not None
    assert body["mode"] == "synthetic-preview"

    report = client.get(
        f"/reports/{body['analysis_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert report.status_code == 200
    payload = report.json()
    assert payload["total_parts"] == 25
    assert len(payload["parts"]) == 25
