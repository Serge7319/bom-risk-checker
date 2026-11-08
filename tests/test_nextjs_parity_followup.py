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
    assert body.get("analysis_id") in (None, "")
    assert not body.get("context_unavailable")
    for cand in body["candidates"]:
        assert cand["fit"] == "unable_to_confirm"
        assert cand["missing_evidence"]


def test_find_replacement_standalone_am29f010_with_no_saved_report():
    """Standalone flash MPN must search without requiring a saved BOM report."""
    client = TestClient(app)
    headers = _auth_headers(client)
    res = client.post(
        "/tools/find-replacement",
        headers=headers,
        json={"mpn": "AM29F010B-70EC"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert "report not found" not in str(body).lower()
    assert body.get("bom_context") is None
    assert body.get("analysis_id") in (None, "")
    assert body["requested_mpn"] == "AM29F010B-70EC"
    # Offline catalog may not list this legacy flash — either candidates or
    # honest unable_to_confirm is fine; never invent compatibility.
    assert body["outcome"] in {"candidates_found", "unable_to_confirm", "failure"}
    if body["outcome"] != "candidates_found":
        assert body.get("candidates") in ([], None) or body["candidates"] == []


def test_find_replacement_ignores_stale_analysis_id():
    """Stale/localStorage analysis IDs must not 404 or invent BOM context."""
    client = TestClient(app)
    headers = _auth_headers(client)
    res = client.post(
        "/tools/find-replacement",
        headers=headers,
        json={
            "mpn": "LM358DR",
            "analysis_id": "analysis-stale-does-not-exist",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["bom_context"] is None
    assert body.get("analysis_id") in (None, "")
    assert body.get("context_unavailable")
    assert "standalone" in str(body["context_unavailable"]).lower()
    assert body["outcome"] == "candidates_found"
    assert len(body["candidates"]) >= 1


def test_find_replacement_bom_row_preserves_only_that_bom_context():
    from apps.api.synthetic_analyze import get_report

    client = TestClient(app)
    headers = _auth_headers(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
        data={"project_name": "Parity", "bom_name": "RowContext"},
    )
    assert analyze.status_code == 200
    payload = analyze.json()
    analysis_id = payload["analysis_id"]
    workspace_id = payload["workspace_id"]
    report = get_report(analysis_id, workspace_id=workspace_id)
    assert report is not None
    parts = report.get("parts") or []
    assert parts
    mpn = str(parts[0].get("MPN") or parts[0].get("mpn") or "").strip()
    assert mpn

    res = client.post(
        "/tools/find-replacement",
        headers=headers,
        json={"mpn": mpn, "analysis_id": analysis_id},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["bom_context"] is not None
    assert body["bom_context"]["analysis_id"] == analysis_id
    assert body["analysis_id"] == analysis_id
    assert str(body["bom_context"]["part"].get("MPN") or "").strip() == mpn
    assert not body.get("context_unavailable")


def test_find_replacement_inaccessible_analysis_id_is_tenant_safe():
    """Foreign/deleted analysis IDs must not leak another workspace's report."""
    from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS

    client = TestClient(app)
    headers_a = _auth_headers(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers_a,
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
        data={"project_name": "Parity", "bom_name": "TenantA"},
    )
    assert analyze.status_code == 200
    foreign_id = analyze.json()["analysis_id"]

    other = SANDBOX_SEED_USERS[1]
    login_b = client.post(
        "/auth/login",
        json={"email": other["email"], "password": other["password"]},
    )
    assert login_b.status_code == 200
    headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    res = client.post(
        "/tools/find-replacement",
        headers=headers_b,
        json={"mpn": "LM358DR", "analysis_id": foreign_id},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["bom_context"] is None
    assert body.get("analysis_id") in (None, "")
    assert body.get("context_unavailable")
    assert "tenanta" not in str(body).lower()
    assert body.get("bom_context") is None
    assert foreign_id not in str(body.get("original") or {})
    assert body["outcome"] == "candidates_found"


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
            assert assessment == "Needs verification"


def _force_report_risk_profile(report, *, high=0, medium=0, low=None, elevate_first=False):
    parts = list(report.get("parts") or [])
    if low is None:
        low = len(parts)
    for idx, part in enumerate(parts):
        if elevate_first and idx == 0:
            part["Risk Level"] = "High"
            part["risk_level"] = "High"
            part["Risk Score"] = 88
            part["risk_score"] = 88
            part["lifecycle_status"] = "NRND"
            part["Lifecycle"] = "NRND"
            part["supplier_count"] = 1
            part["stock_available"] = 0
            part["lead_time_weeks"] = 20
        elif elevate_first and idx == 1:
            part["Risk Level"] = "Medium"
            part["risk_level"] = "Medium"
            part["Risk Score"] = 55
            part["risk_score"] = 55
            part["lifecycle_status"] = "Active"
            part["Lifecycle"] = "Active"
            part["supplier_count"] = 1
            part["stock_available"] = 5
            part["lead_time_weeks"] = 12
        else:
            part["Risk Level"] = "Low"
            part["risk_level"] = "Low"
            part["Risk Score"] = 12
            part["risk_score"] = 12
            part["lifecycle_status"] = "Active"
            part["Lifecycle"] = "Active"
            part.pop("supplier_count", None)
            part.pop("Supplier Count", None)
            part.pop("lead_time_weeks", None)
            part.pop("stock_available", None)
        part.setdefault("Source", "synthetic-preview")
        part.setdefault("source", "synthetic-preview")
    report["parts"] = parts
    report["high_risk_count"] = high
    report["medium_risk_count"] = medium
    report["low_risk_count"] = low
    return report


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
    _force_report_risk_profile(report, high=0, medium=0, low=len(report.get("parts") or []))
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
    answer = str(body.get("answer") or "")
    lower = answer.lower()
    assert body["ok"] is True
    assert "0 priority" in lower
    assert "does not support ranking" in lower or "not support ranking" in lower
    assert "first engineering review priority" not in lower
    assert "only 0 recorded source" not in lower
    assert "100/100" not in lower
    assert "#1 " not in answer and "#1\n" not in answer
    assert "ranked first" not in lower
    # Generic Component Risk wording must also avoid inventing a first priority.
    res2 = client.post(
        "/tools/ask-cadivor",
        headers=headers,
        json={
            "analysis_id": analysis_id,
            "question": "What are the engineering priorities for this BOM?",
        },
    )
    assert res2.status_code == 200
    answer2 = str(res2.json().get("answer") or "")
    lower2 = answer2.lower()
    assert "0 priority" in lower2
    assert "first engineering review priority" not in lower2
    assert "#1 " not in answer2
    # Unranked inventory only when the user asks to see parts.
    listed = client.post(
        "/tools/ask-cadivor",
        headers=headers,
        json={
            "analysis_id": analysis_id,
            "question": "List the parts in this BOM without ranking them.",
        },
    )
    assert listed.status_code == 200
    listed_answer = str(listed.json().get("answer") or "")
    assert "unranked" in listed_answer.lower()
    assert "#1 " not in listed_answer


def test_ask_cadivor_keeps_ranked_priorities_when_risks_differ():
    from apps.api.synthetic_analyze import get_report
    from apps.api.workspace_store import get_store

    client = TestClient(app)
    headers = _auth_headers(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
        data={"project_name": "Parity", "bom_name": "Differentiated"},
    )
    assert analyze.status_code == 200
    payload = analyze.json()
    analysis_id = payload["analysis_id"]
    workspace_id = payload["workspace_id"]
    report = get_report(analysis_id, workspace_id=workspace_id)
    assert report is not None
    _force_report_risk_profile(
        report,
        high=1,
        medium=1,
        low=max(0, len(report.get("parts") or []) - 2),
        elevate_first=True,
    )
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
    answer = str(body.get("answer") or "")
    lower = answer.lower()
    assert body["ok"] is True
    assert "first engineering review priority" in lower
    assert "#1 " in answer
    assert "0 priority risks" not in lower
    assert "review **" in lower or "review **" in answer.lower()


def test_ask_cadivor_high_medium_question_does_not_rank_zero_priority_report():
    from apps.api.synthetic_analyze import get_report
    from apps.api.workspace_store import get_store

    client = TestClient(app)
    headers = _auth_headers(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
        data={"project_name": "Parity", "bom_name": "EvidenceConfidenceZeroPriority"},
    )
    assert analyze.status_code == 200
    payload = analyze.json()
    analysis_id = payload["analysis_id"]
    workspace_id = payload["workspace_id"]
    report = get_report(analysis_id, workspace_id=workspace_id)
    assert report is not None
    _force_report_risk_profile(report, high=0, medium=0, low=len(report.get("parts") or []))
    get_store().upsert_analysis_report(report, workspace_id=workspace_id)

    res = client.post(
        "/tools/ask-cadivor",
        headers=headers,
        json={
            "analysis_id": analysis_id,
            "question": (
                "Does this synthetic BOM contain any high- or medium-priority risks? "
                "Summarize only what is supported by the saved evidence."
            ),
        },
    )
    assert res.status_code == 200
    answer = str(res.json().get("answer") or "")
    lower = answer.lower()
    assert "0 priority risks" in lower
    assert "does not support ranking" in lower
    assert "first engineering review priority" not in lower
    assert "ranked first" not in lower
    assert "#1 " not in answer and "#1\\n" not in answer
