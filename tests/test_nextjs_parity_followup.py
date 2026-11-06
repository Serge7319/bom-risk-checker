"""Follow-up parity coverage: replacement, Ask Cadivor, LM358 vs NE555 compare."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from src.parts_compare import FINDING_MATERIAL
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/synthetic_bom_25parts.csv"


@pytest.fixture(autouse=True)
def _sandbox_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()


def _auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_compare_lm358_vs_ne555_is_material_difference():
    client = TestClient(app)
    headers = _auth_headers(client)
    res = client.post(
        "/tools/compare-parts",
        headers=headers,
        json={"part_a": "LM358DR", "part_b": "NE555P"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["family_mismatch"] is True
    assert body["finding"] == FINDING_MATERIAL
    assert "compatible" not in str(body["finding"]).lower()
    assert "migration" not in str(body.get("gap") or "").lower()
    assert "streamlit" not in str(body.get("gap") or "").lower()


def test_find_replacement_standalone_without_bom():
    client = TestClient(app)
    headers = _auth_headers(client)
    res = client.post(
        "/tools/find-replacement",
        headers=headers,
        json={"mpn": "LM358DR"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["outcome"] == "candidates_found"
    assert len(body["candidates"]) >= 1
    assert body["bom_context"] is None
    for cand in body["candidates"]:
        assert cand["fit"] == "unable_to_confirm"
        assert cand["missing_evidence"]


def test_find_replacement_unknown_is_unable_to_confirm():
    client = TestClient(app)
    headers = _auth_headers(client)
    res = client.post(
        "/tools/find-replacement",
        headers=headers,
        json={"mpn": "ZZZ-NO-SUCH-PART-999"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"] == "unable_to_confirm"
    assert body["candidates"] == []
    assert "unable to confirm" in str(body["gap"]).lower()


def test_ask_cadivor_on_saved_report():
    client = TestClient(app)
    headers = _auth_headers(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert analyze.status_code == 200
    analysis_id = analyze.json()["analysis_id"]
    res = client.post(
        "/tools/ask-cadivor",
        headers=headers,
        json={
            "analysis_id": analysis_id,
            "question": "What should we review before release?",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["answer"]
    assert body["grounded"] is True

def test_compare_lm358_vs_ne555_identity_and_unable_to_confirm():
    client = TestClient(app)
    headers = _auth_headers(client)
    res = client.post(
        "/tools/compare-parts",
        headers=headers,
        json={"part_a": "LM358DR", "part_b": "NE555P"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["family_mismatch"] is True
    assert body["finding"] == FINDING_MATERIAL
    cards = body.get("part_cards") or {}
    a = cards.get("a") or {}
    b = cards.get("b") or {}
    assert a.get("manufacturer") == "Texas Instruments"
    assert b.get("manufacturer") == "Texas Instruments"
    assert a.get("family") == "Operational amplifier"
    assert b.get("family") == "Timer IC"
    assert "oscillator" not in str(b.get("family") or "").lower()
    assert "crystal" not in str(b.get("family") or "").lower()
    for row in body.get("rows") or []:
        assessment = str(row.get("Assessment") or "")
        assert "needs data" not in assessment.lower()
        if str(row.get("Attribute") or "").lower() in {"package", "pin count", "pins"}:
            assert assessment == "Unable to confirm"


def test_ask_cadivor_respects_low_risk_report_fields(tmp_path, monkeypatch):
    from apps.api.synthetic_analyze import get_report
    from apps.api.workspace_store import get_store

    client = TestClient(app)
    headers = _auth_headers(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
        data={"project_name": "Parity", "bom_name": "LowRisk"},
    )
    assert analyze.status_code == 200
    payload = analyze.json()
    analysis_id = payload["analysis_id"]
    workspace_id = payload["workspace_id"]
    report = get_report(analysis_id, workspace_id=workspace_id)
    assert report is not None
    for part in report.get("parts") or []:
        part["Risk Level"] = "Low"
        part["risk_level"] = "Low"
        part["Risk Score"] = 12
        part["risk_score"] = 12
        part.pop("supplier_count", None)
        part.pop("Supplier Count", None)
        part.pop("lead_time_weeks", None)
    report["high_risk_count"] = 0
    report["medium_risk_count"] = 0
    report["low_risk_count"] = len(report.get("parts") or [])
    get_store().upsert_analysis_report(report, workspace_id=workspace_id)
    res = client.post(
        "/tools/ask-cadivor",
        headers=headers,
        json={
            "analysis_id": analysis_id,
            "question": "What should I review first in this BOM?",
        },
    )
    assert res.status_code == 200
    body = res.json()
    answer = str(body.get("answer") or "").lower()
    assert body["ok"] is True
    assert "0 priority" in answer
    assert "only 0 recorded source" not in answer
    assert "100/100" not in answer
