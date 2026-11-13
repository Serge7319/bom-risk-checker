"""Signed snapshot tokens must bind exact BOM / workspace analysis scope."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api.comparison_snapshot_trust import (
    analysis_scopes_match,
    attach_snapshot_token,
    issue_snapshot_token,
    materialize_snapshot_for_reuse,
    verify_multi_candidate_snapshot,
)
from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

SECRET = "test-snapshot-scope-secret-key"


@pytest.fixture()
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", SECRET)
    monkeypatch.setenv("CADIVOR_COMPARISON_SNAPSHOT_SECRET", SECRET)
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


def _auth(client: TestClient) -> tuple[dict[str, str], str, str]:
    res = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200
    body = res.json()
    token = body["access_token"]
    workspace_id = str(body.get("workspace_id") or "")
    user_id = str(body.get("user_id") or "")
    if not workspace_id or not user_id:
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        payload = me.json()
        workspace_id = workspace_id or str(payload.get("workspace_id") or "")
        user_id = user_id or str(payload.get("user_id") or "")
    assert workspace_id and user_id
    return {"Authorization": f"Bearer {token}"}, workspace_id, user_id


def _pairwise(
    *,
    part_b: str,
    manufacturer_b: str,
    analysis_id: str | None,
    workspace_id: str,
    user_id: str,
) -> dict:
    payload = {
        "ok": True,
        "part_a": "LM358N",
        "part_b": part_b,
        "analysis_id": analysis_id,
        "manufacturer_a": "Texas Instruments",
        "manufacturer_b": manufacturer_b,
        "finding": "Needs verification",
        "engineering_evidence_summary": "scope token fixture",
        "engineering_evidence_status": "incomplete",
        "counts": {"compatible": 0, "listing_agreement": 0, "material_difference": 0, "needs_data": 1, "conflicting": 0},
        "rows": [],
        "part_cards": {
            "a": {"mpn": "LM358N", "manufacturer": "Texas Instruments"},
            "b": {"mpn": part_b, "manufacturer": manufacturer_b},
        },
        "source_a": "DigiKey",
        "source_b": "Mouser",
        "evidence_sources": {},
        "datasheet_identity": {},
        "package_dimension_evidence": {},
        "review_warnings": [],
        "gap": "",
        "family": "Operational amplifier",
        "family_mismatch": False,
        "mode": "legacy-supplier-engine",
    }
    return attach_snapshot_token(payload, workspace_id=workspace_id, user_id=user_id or None)


def test_analysis_scopes_match_treats_null_and_empty_as_workspace():
    assert analysis_scopes_match(None, "", None)
    assert analysis_scopes_match("bom-1", "bom-1", "bom-1")
    assert not analysis_scopes_match(None, "bom-1")
    assert not analysis_scopes_match("bom-1", None)
    assert not analysis_scopes_match("bom-1", "bom-2")


def test_bom_token_does_not_verify_as_workspace(_sandbox):
    client = TestClient(app)
    headers, workspace_id, user_id = _auth(client)
    assert workspace_id
    bom = _pairwise(
        part_b="LM358AN/NOPB",
        manufacturer_b="Texas Instruments",
        analysis_id="fixture-bom-analysis-1",
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert bom.get("snapshot_token")
    assert (
        materialize_snapshot_for_reuse(
            bom,
            workspace_id=workspace_id,
            user_id=user_id or None,
            analysis_id="fixture-bom-analysis-1",
            part_a="LM358N",
            part_b="LM358AN/NOPB",
        )
        is not None
    )
    assert (
        materialize_snapshot_for_reuse(
            bom,
            workspace_id=workspace_id,
            user_id=user_id or None,
            analysis_id=None,
            part_a="LM358N",
            part_b="LM358AN/NOPB",
        )
        is None
    )


def test_workspace_token_does_not_verify_as_bom(_sandbox):
    client = TestClient(app)
    headers, workspace_id, user_id = _auth(client)
    workspace = _pairwise(
        part_b="LM358DT",
        manufacturer_b="STMicroelectronics",
        analysis_id=None,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert (
        materialize_snapshot_for_reuse(
            workspace,
            workspace_id=workspace_id,
            user_id=user_id or None,
            analysis_id=None,
            part_a="LM358N",
            part_b="LM358DT",
        )
        is not None
    )
    assert (
        materialize_snapshot_for_reuse(
            workspace,
            workspace_id=workspace_id,
            user_id=user_id or None,
            analysis_id="fixture-bom-analysis-1",
            part_a="LM358N",
            part_b="LM358DT",
        )
        is None
    )


def test_multi_scope_switch_directions_require_matching_tokens(_sandbox):
    client = TestClient(app)
    headers, workspace_id, user_id = _auth(client)
    candidates = [
        ("LM358AN/NOPB", "Texas Instruments"),
        ("LM358DT", "STMicroelectronics"),
        ("LM358DR2G", "onsemi"),
    ]

    def build_multi(analysis_id: str | None) -> dict:
        snaps = [
            _pairwise(
                part_b=mpn,
                manufacturer_b=brand,
                analysis_id=analysis_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            for mpn, brand in candidates
        ]
        return {
            "ok": True,
            "part_a": "LM358N",
            "part_b": candidates[0][0],
            "analysis_id": analysis_id,
            "manufacturer_a": "Texas Instruments",
            "manufacturer_b": candidates[0][1],
            "multi_candidate_mpns": [mpn for mpn, _ in candidates],
            "multi_candidate_manufacturers": {mpn: brand for mpn, brand in candidates},
            "candidate_snapshots": snaps,
        }

    bom_multi = build_multi("fixture-bom-analysis-1")
    workspace_multi = build_multi(None)

    assert verify_multi_candidate_snapshot(
        bom_multi,
        workspace_id=workspace_id,
        user_id=user_id or None,
        analysis_id="fixture-bom-analysis-1",
        part_a="LM358N",
        part_b="LM358AN/NOPB",
    )
    # BOM → workspace must fail closed.
    assert not verify_multi_candidate_snapshot(
        bom_multi,
        workspace_id=workspace_id,
        user_id=user_id or None,
        analysis_id=None,
        part_a="LM358N",
        part_b="LM358AN/NOPB",
    )
    assert verify_multi_candidate_snapshot(
        workspace_multi,
        workspace_id=workspace_id,
        user_id=user_id or None,
        analysis_id=None,
        part_a="LM358N",
        part_b="LM358AN/NOPB",
    )
    # Workspace → BOM must fail closed.
    assert not verify_multi_candidate_snapshot(
        workspace_multi,
        workspace_id=workspace_id,
        user_id=user_id or None,
        analysis_id="fixture-bom-analysis-1",
        part_a="LM358N",
        part_b="LM358AN/NOPB",
    )


def test_decision_api_returns_refresh_required_for_stale_multi_tokens(_sandbox):
    client = TestClient(app)
    headers, workspace_id, user_id = _auth(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("bom.csv", b"MPN,Quantity\nLM358N,1\n", "text/csv")},
    )
    assert analyze.status_code in {200, 201}
    bom_id = str(analyze.json().get("analysis_id") or analyze.json().get("id") or "")
    assert bom_id
    # Tokens signed for workspace, but decision requests BOM scope.
    snaps = [
        _pairwise(
            part_b=mpn,
            manufacturer_b=brand,
            analysis_id=None,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        for mpn, brand in (
            ("LM358AN/NOPB", "Texas Instruments"),
            ("LM358DT", "STMicroelectronics"),
        )
    ]
    snapshot = {
        "ok": True,
        "part_a": "LM358N",
        "part_b": "LM358AN/NOPB",
        "analysis_id": None,
        "candidate_snapshots": snaps,
        "multi_candidate_mpns": ["LM358AN/NOPB", "LM358DT"],
        "multi_candidate_manufacturers": {
            "LM358AN/NOPB": "Texas Instruments",
            "LM358DT": "STMicroelectronics",
        },
    }
    with patch("apps.api.migration_tools.compare_parts_payload") as mocked:
        res = client.post(
            "/decision-records",
            headers=headers,
            json={
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
                "analysis_id": bom_id,
                "decision": "hold_for_review",
                "reviewer": SMOKE_EMAIL,
                "rationale": "Stale multi tokens must not save primary-only.",
                "comparison_snapshot": snapshot,
            },
        )
    assert res.status_code == 409, res.text
    body = res.json()
    assert body.get("code") == "comparison_refresh_required"
    assert "Re-compare every candidate" in str(body.get("detail") or "")
    mocked.assert_not_called()


def test_issue_snapshot_token_binds_aid_claim(_sandbox):
    token = issue_snapshot_token(
        workspace_id="ws",
        user_id="user",
        analysis_id="bom-9",
        part_a="A",
        part_b="B",
        snapshot={
            "finding": "Needs verification",
            "rows": [],
            "counts": {},
            "part_cards": {},
            "manufacturer_a": "",
            "manufacturer_b": "",
        },
    )
    assert token and "." in token
