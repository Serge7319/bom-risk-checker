"""Decision BOM scope + multi-candidate manufacturer visibility regressions."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from src.parts_compare import (
    FINDING_COMPATIBLE,
    FINDING_LISTING_AGREEMENT,
    FINDING_NEEDS_VERIFICATION,
    assess_compare_row,
)
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

ROOT = Path(__file__).resolve().parents[1]
COMPARE_PAGE = ROOT / "apps/web/src/app/compare-parts/page.tsx"
MULTI_COMPARE = ROOT / "apps/web/src/lib/multiCompare.ts"
FIND_REPLACEMENT = ROOT / "apps/web/src/app/find-replacement/page.tsx"


class UiContractTests(unittest.TestCase):
    def test_decision_bom_scope_has_explicit_workspace_option(self):
        page = COMPARE_PAGE.read_text(encoding="utf-8")
        self.assertIn('data-testid="decision-bom-scope"', page)
        self.assertIn("No BOM — workspace-level decision", page)
        self.assertIn("setDecisionAnalysisId(analysisId.trim())", page)
        self.assertIn("scopedAnalysisId", page)
        # Must not prefer stale result.analysis_id when opening the dialog.
        self.assertNotIn(
            'setDecisionAnalysisId(String(result?.analysis_id || analysisId || ""))',
            page,
        )

    def test_multi_compare_headings_include_manufacturer_helpers(self):
        multi = MULTI_COMPARE.read_text(encoding="utf-8")
        self.assertIn("formatCandidateHeading", multi)
        self.assertIn("multi_candidate_manufacturers", multi)
        self.assertIn("manufacturer?: string", multi)
        page = COMPARE_PAGE.read_text(encoding="utf-8")
        self.assertIn("formatCandidateHeading", page)
        self.assertIn("data-testid={`multi-col-${column.mpn}`}", page)

    def test_find_replacement_multi_handoff_carries_per_candidate_brands(self):
        page = FIND_REPLACEMENT.read_text(encoding="utf-8")
        self.assertIn("manufacturerB: selectedCandidates", page)
        self.assertIn("manufacturerForCandidate", page)


class MultiCompareHelperTests(unittest.TestCase):
    """Node-free contract: TypeScript helpers encode TI / ST / onsemi brands."""

    def test_typescript_snapshot_preserves_three_brands(self):
        source = MULTI_COMPARE.read_text(encoding="utf-8")
        self.assertIn("multi_candidate_manufacturers", source)
        self.assertIn("result.manufacturer_b = brand", source)
        self.assertIn("cardB.manufacturer = brand", source)
        # Headings and evidence surfaces include manufacturer.
        self.assertIn("Candidate · ${mpn} · ${brand}", source)
        self.assertIn("formatCandidateHeading(column.mpn, brand)", source)


class CatalogNeverCompatibleTests(unittest.TestCase):
    def test_catalog_only_match_is_listing_agreement_not_compatible(self):
        assessment = assess_compare_row(
            status="Match",
            source_a="DigiKey catalog listing",
            source_b="Mouser catalog listing",
            class_a="nominal",
            class_b="nominal",
            condition_a="25C",
            condition_b="25C",
        )
        self.assertNotEqual(assessment, FINDING_COMPATIBLE)
        self.assertEqual(assessment, FINDING_LISTING_AGREEMENT)


@pytest.fixture()
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def _compare_fixture(*, part_b: str, manufacturer_b: str, analysis_id: str | None = None) -> dict:
    return {
        "ok": True,
        "status": "completed",
        "part_a": "LM358N",
        "part_b": part_b,
        "manufacturer_a": "Texas Instruments",
        "manufacturer_b": manufacturer_b,
        "analysis_id": analysis_id,
        "finding": FINDING_NEEDS_VERIFICATION,
        "engineering_evidence_summary": "identity preserved",
        "engineering_evidence_status": "incomplete",
        "counts": {
            "compatible": 0,
            "listing_agreement": 1,
            "material_difference": 0,
            "needs_data": 1,
            "conflicting": 0,
            "breakdown": {"catalog_difference": 0},
        },
        "rows": [
            {
                "Attribute": "Package",
                "Part A": "PDIP-8",
                "Part B": "SOIC-8",
                "Assessment": "Catalog values agree — fit unverified",
            }
        ],
        "part_cards": {
            "a": {
                "mpn": "LM358N",
                "manufacturer": "Texas Instruments",
                "identity_verified": True,
                "found": True,
            },
            "b": {
                "mpn": part_b,
                "manufacturer": manufacturer_b,
                "identity_verified": True,
                "found": True,
            },
        },
        "gap": "",
    }


def test_workspace_level_decision_saves_null_analysis_id(_sandbox, monkeypatch):
    monkeypatch.setenv("CADIVOR_ALLOW_PRODUCTION_ANALYSIS", "0")
    client = TestClient(app)
    headers = _auth_headers(client)
    # Seed a saved BOM so the UI would previously look like the first BOM was selected.
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("bom.csv", b"MPN,Quantity\nLM358N,1\n", "text/csv")},
    )
    assert analyze.status_code in {200, 201}
    bom_id = str(analyze.json().get("analysis_id") or analyze.json().get("id") or "")
    assert bom_id

    snapshot = _compare_fixture(part_b="LM358AN/NOPB", manufacturer_b="Texas Instruments")
    with patch(
        "apps.api.migration_tools.compare_parts_payload",
        return_value={**snapshot, "analysis_id": None},
    ):
        create = client.post(
            "/decision-records",
            headers=headers,
            json={
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
                "analysis_id": None,
                "decision": "hold_for_review",
                "reviewer": SMOKE_EMAIL,
                "rationale": "Workspace-level decision must stay unscoped.",
                "comparison_snapshot": {**snapshot, "analysis_id": None},
            },
        )
    assert create.status_code in {200, 201}, create.text
    record = create.json()["record"]
    assert record.get("analysis_id") in {None, ""}
    assert record.get("manufacturer_a") == "Texas Instruments"
    assert record.get("manufacturer_b") == "Texas Instruments"

    listed = client.get("/decision-records", headers=headers)
    assert listed.status_code == 200
    rows = listed.json().get("records") or []
    match = next(row for row in rows if row.get("part_b") == "LM358AN/NOPB")
    assert match.get("analysis_id") in {None, ""}


def test_bom_scoped_decision_keeps_exact_analysis_id(_sandbox, monkeypatch):
    monkeypatch.setenv("CADIVOR_ALLOW_PRODUCTION_ANALYSIS", "0")
    client = TestClient(app)
    headers = _auth_headers(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("bom.csv", b"MPN,Quantity\nLM358N,1\n", "text/csv")},
    )
    assert analyze.status_code in {200, 201}
    analysis_id = str(analyze.json().get("analysis_id") or analyze.json().get("id") or "")
    snapshot = _compare_fixture(
        part_b="LM358AN/NOPB",
        manufacturer_b="Texas Instruments",
        analysis_id=analysis_id,
    )
    with patch(
        "apps.api.migration_tools.compare_parts_payload",
        return_value=snapshot,
    ):
        create = client.post(
            "/decision-records",
            headers=headers,
            json={
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
                "analysis_id": analysis_id,
                "decision": "hold_for_review",
                "reviewer": SMOKE_EMAIL,
                "rationale": "BOM-scoped decision must keep this exact analysis_id.",
                "comparison_snapshot": snapshot,
            },
        )
    assert create.status_code in {200, 201}, create.text
    record = create.json()["record"]
    assert record.get("analysis_id") == analysis_id


def test_multi_candidate_manufacturers_persist_independently(_sandbox, monkeypatch):
    monkeypatch.setenv("CADIVOR_ALLOW_PRODUCTION_ANALYSIS", "0")
    client = TestClient(app)
    headers = _auth_headers(client)

    candidates = [
        ("LM358AN/NOPB", "Texas Instruments"),
        ("LM358DT", "STMicroelectronics"),
        ("LM358DR2G", "onsemi"),
    ]
    candidate_snapshots = [
        _compare_fixture(part_b=mpn, manufacturer_b=brand) for mpn, brand in candidates
    ]
    multi_brands = {mpn: brand for mpn, brand in candidates}
    snapshot = {
        **candidate_snapshots[0],
        "multi_candidate_mpns": [mpn for mpn, _ in candidates],
        "multi_candidate_manufacturers": multi_brands,
        "candidate_snapshots": candidate_snapshots,
        "analysis_id": None,
    }
    with (
        patch(
            "apps.api.main.materialize_snapshot_for_reuse",
            return_value={**snapshot, "ok": True},
        ),
        patch(
            "apps.api.migration_tools.compare_parts_payload",
            return_value=candidate_snapshots[0],
        ),
    ):
        create = client.post(
            "/decision-records",
            headers=headers,
            json={
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
                "analysis_id": None,
                "decision": "hold_for_review",
                "reviewer": SMOKE_EMAIL,
                "rationale": "Multi TI/ST/onsemi identities must reload intact.",
                "comparison_snapshot": snapshot,
            },
        )
    assert create.status_code in {200, 201}, create.text
    record = create.json()["record"]
    snap = record.get("comparison_snapshot") or {}
    brands = snap.get("multi_candidate_manufacturers") or {}
    assert brands.get("LM358AN/NOPB") == "Texas Instruments"
    assert brands.get("LM358DT") == "STMicroelectronics"
    assert brands.get("LM358DR2G") == "onsemi"
    for entry in snap.get("candidate_snapshots") or []:
        mpn = entry.get("part_b")
        assert entry.get("manufacturer_b") == multi_brands[mpn]


def test_am29_identity_review_only_contract_still_present():
    tools = (ROOT / "apps/api/migration_tools.py").read_text(encoding="utf-8")
    page = FIND_REPLACEMENT.read_text(encoding="utf-8")
    assert "identity_review_only" in tools or "identityReviewOnly" in page
    assert "identityReviewOnly" in page
    assert re.search(r"cross-family", page, re.I)


def test_rebuild_multi_source_includes_manufacturers():
    from apps.api.comparison_snapshot_trust import rebuild_multi_source_records

    records = rebuild_multi_source_records(
        "LM358N",
        [
            {
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
                "source_a": "DigiKey",
                "source_b": "DigiKey",
                "rows": [],
                "part_cards": {
                    "a": {"manufacturer": "Texas Instruments"},
                    "b": {"manufacturer": "Texas Instruments"},
                },
            },
            {
                "part_a": "LM358N",
                "part_b": "LM358DT",
                "manufacturer_b": "STMicroelectronics",
                "source_b": "Mouser",
                "rows": [],
                "part_cards": {"b": {"manufacturer": "STMicroelectronics"}},
            },
            {
                "part_a": "LM358N",
                "part_b": "LM358DR2G",
                "manufacturer_b": "onsemi",
                "source_b": "Mouser",
                "rows": [],
                "part_cards": {"b": {"manufacturer": "onsemi"}},
            },
        ],
    )
    labels = " ".join(row.get("side") or "" for row in records)
    assert "LM358AN/NOPB" in labels and "Texas Instruments" in labels
    assert "LM358DT" in labels and "STMicroelectronics" in labels
    assert "LM358DR2G" in labels and "onsemi" in labels


if __name__ == "__main__":
    unittest.main()
