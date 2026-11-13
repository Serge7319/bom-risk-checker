"""Hold for review saves exactly one record under the correct BOM, with no approval."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import get_store, reset_store_for_tests
from src.parts_compare import FINDING_NEEDS_VERIFICATION
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

BOM_CSV = b"MPN,Quantity\nLM358N,1\n"


def _compare_payload(analysis_id: str) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "completed",
        "part_a": "LM358N",
        "part_b": "LM358AN/NOPB",
        "manufacturer_a": "Texas Instruments",
        "manufacturer_b": "Texas Instruments",
        "analysis_id": analysis_id,
        "finding": FINDING_NEEDS_VERIFICATION,
        "engineering_evidence_summary": "catalog evidence only",
        "engineering_evidence_status": "incomplete",
        "counts": {
            "compatible": 0,
            "listing_agreement": 1,
            "material_difference": 0,
            "needs_data": 0,
            "conflicting": 0,
            "breakdown": {"catalog_difference": 0},
        },
        "rows": [
            {
                "Attribute": "Package",
                "Part A": "PDIP-8",
                "Part B": "PDIP-8",
                "Assessment": "Catalog values agree — fit unverified",
            }
        ],
        "part_cards": {"a": {"mpn": "LM358N"}, "b": {"mpn": "LM358AN/NOPB"}},
        "gap": "",
    }


def _analyze(client: TestClient, headers: dict[str, str], *, bom_name: str) -> str:
    res = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": (f"{bom_name}.csv", BOM_CSV, "text/csv")},
        data={"project_name": "Hold Scope", "bom_name": bom_name},
    )
    assert res.status_code in {200, 201}, res.text
    body = res.json()
    analysis_id = str(body.get("analysis_id") or body.get("id") or "")
    assert analysis_id
    return analysis_id


def assert_single_hold_for_review_under_bom(
    client: TestClient, headers: dict[str, str]
) -> dict[str, Any]:
    """Shared by the file-store and disposable-Postgres (Railway store) tests."""
    analysis_a = _analyze(client, headers, bom_name="Hold BOM A")
    analysis_b = _analyze(client, headers, bom_name="Hold BOM B")
    assert analysis_a != analysis_b

    before = client.get("/decision-records", headers=headers).json()["records"]
    baseline_ids = {row["id"] for row in before}

    with patch(
        "apps.api.migration_tools.compare_parts_payload",
        return_value=_compare_payload(analysis_b),
    ):
        created = client.post(
            "/decision-records",
            headers=headers,
            json={
                "analysis_id": analysis_b,
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
                "decision": "hold_for_review",
                "reviewer": SMOKE_EMAIL,
                "rationale": "Hold until the exact datasheet limits are verified.",
                "validation_checks": [],
                "residual_risk": "medium",
            },
        )
    assert created.status_code == 201, created.text
    record = created.json()["record"]
    assert record["decision"] == "hold_for_review"
    assert record["analysis_id"] == analysis_b
    assert record["bom_name"] == "Hold BOM B"
    assert record["verified_primary_evidence"] is False
    assert record["qualification_status"] == "not-qualified-by-cadivor"

    # Exactly one new record workspace-wide, scoped to BOM B and not BOM A.
    after = client.get("/decision-records", headers=headers).json()["records"]
    new_rows = [row for row in after if row["id"] not in baseline_ids]
    assert [row["id"] for row in new_rows] == [record["id"]]
    scoped_a = client.get(f"/decision-records?analysis_id={analysis_a}", headers=headers)
    assert scoped_a.status_code == 200
    assert scoped_a.json()["records"] == []
    scoped_b = client.get(f"/decision-records?analysis_id={analysis_b}", headers=headers)
    assert scoped_b.status_code == 200
    reopened = scoped_b.json()["records"]
    assert len(reopened) == 1

    # Reopen equals the saved record.
    assert reopened[0] == record
    assert reopened[0]["comparison_snapshot"]["finding"] == FINDING_NEEDS_VERIFICATION

    # No approval was created by holding for review.
    assert all(row["decision"] == "hold_for_review" for row in reopened)
    assert not any(
        row.get("decision") in {"approve_alternate", "conditional_approval"} for row in after
    )
    return record


@pytest.fixture()
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_PRODUCTION_ANALYSIS", "0")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()


def test_hold_for_review_saves_one_record_under_correct_bom(_sandbox):
    client = TestClient(app)
    res = client.post("/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD})
    assert res.status_code == 200
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    record = assert_single_hold_for_review_under_bom(client, headers)

    # File store: nothing approval-shaped was written alongside the decision.
    data = getattr(get_store(), "_data", {})
    assert not any("approv" in str(key).casefold() for key in data)
    assert len(data.get("decision_records", {})) == 1
    assert record["id"] in data["decision_records"]
