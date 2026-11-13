"""FR → Compare manufacturer identity handoff regressions (no live suppliers)."""
from __future__ import annotations

import io
import json
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
    FINDING_NEEDS_VERIFICATION,
    lookup_part_for_compare,
    public_part_card,
    run_compare_parts,
)
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)


def _ti_lm358n() -> dict:
    return {
        "manufacturer_part_number": "LM358N",
        "manufacturer": "Texas Instruments",
        "description": "Dual op amp",
        "package": "PDIP-8",
        "lifecycle_status": "Active",
        "supplier_data_verified": True,
        "input_offset_mv": "3 mV",
        "source": "DigiKey",
    }


def _onsemi_lm358n() -> dict:
    return {
        "manufacturer_part_number": "LM358N",
        "manufacturer": "onsemi",
        "description": "Dual op amp",
        "package": "PDIP-8",
        "lifecycle_status": "Active",
        "supplier_data_verified": True,
        "input_offset_mv": "7 mV",
        "source": "Mouser",
    }


def _ti_candidate() -> dict:
    return {
        "manufacturer_part_number": "LM358AN/NOPB",
        "manufacturer": "Texas Instruments",
        "description": "Dual op amp",
        "package": "PDIP-8",
        "lifecycle_status": "Active",
        "supplier_data_verified": True,
        "input_offset_mv": "2 mV",
        "source": "DigiKey",
    }


class LookupIdentityConstraintTests(unittest.TestCase):
    def test_ti_constraint_never_consumes_onsemi_lm358n(self):
        with patch(
            "integrations.supplier_aggregator.get_best_part_data",
            return_value=_onsemi_lm358n(),
        ):
            part = lookup_part_for_compare("LM358N", manufacturer="Texas Instruments")
        self.assertEqual(part.get("identity_status"), "unresolved")
        self.assertFalse(part.get("identity_verified"))
        self.assertEqual(part.get("manufacturer"), "")
        self.assertNotEqual(part.get("manufacturer"), "onsemi")
        self.assertNotIn("input_offset_mv", part)
        card = public_part_card(part)
        self.assertEqual(card.get("manufacturer"), "")
        self.assertFalse(card.get("found"))

    def test_onsemi_constraint_keeps_onsemi(self):
        with patch(
            "integrations.supplier_aggregator.get_best_part_data",
            return_value=_onsemi_lm358n(),
        ):
            part = lookup_part_for_compare("LM358N", manufacturer="onsemi")
        self.assertEqual(part.get("identity_status"), "verified")
        self.assertTrue(part.get("identity_verified"))
        self.assertEqual(part.get("manufacturer"), "onsemi")
        self.assertEqual(part.get("input_offset_mv"), "7 mV")

    def test_ambiguous_standalone_lm358n_without_manufacturer(self):
        with patch(
            "integrations.supplier_aggregator.get_best_part_data",
            return_value=_onsemi_lm358n(),
        ):
            part = lookup_part_for_compare("LM358N", manufacturer="")
        self.assertEqual(part.get("identity_status"), "ambiguous")
        self.assertEqual(part.get("manufacturer"), "")
        self.assertGreaterEqual(len(part.get("identity_choices") or []), 2)

    def test_brand_mismatch_compare_never_compatible(self):
        with patch(
            "integrations.supplier_aggregator.get_best_part_data",
            side_effect=lambda mpn, manufacturer="": (
                _ti_candidate()
                if str(mpn).upper().startswith("LM358AN")
                else _onsemi_lm358n()
            ),
        ):
            result = run_compare_parts(
                "LM358N",
                "LM358AN/NOPB",
                manufacturer_a="Texas Instruments",
                manufacturer_b="Texas Instruments",
                extract_linked_datasheets=False,
            )
        comparison = result["comparison"]
        self.assertTrue(result.get("identity_blocked"))
        self.assertEqual(comparison.get("finding"), FINDING_NEEDS_VERIFICATION)
        self.assertNotEqual(comparison.get("finding"), FINDING_COMPATIBLE)
        self.assertEqual(comparison.get("rows"), [])
        card_a = comparison["part_a"]
        self.assertEqual(card_a.get("manufacturer"), "")
        self.assertIn(card_a.get("identity_status"), {"unresolved", "ambiguous"})

    def test_candidate_brand_independent_of_part_a(self):
        with patch(
            "integrations.supplier_aggregator.get_best_part_data",
            side_effect=lambda mpn, manufacturer="": (
                _ti_lm358n()
                if str(mpn).upper() == "LM358N"
                else {
                    "manufacturer_part_number": "LM358ADR2G",
                    "manufacturer": "onsemi",
                    "description": "Dual op amp",
                    "package": "SOIC-8",
                    "lifecycle_status": "Active",
                    "supplier_data_verified": True,
                    "input_offset_mv": "2 mV",
                }
            ),
        ):
            result = run_compare_parts(
                "LM358N",
                "LM358ADR2G",
                manufacturer_a="Texas Instruments",
                manufacturer_b="onsemi",
                extract_linked_datasheets=False,
            )
        comparison = result["comparison"]
        self.assertFalse(result.get("identity_blocked"))
        self.assertEqual(comparison["part_a"].get("manufacturer"), "Texas Instruments")
        self.assertEqual(comparison["part_b"].get("manufacturer"), "onsemi")
        self.assertEqual(result.get("manufacturer_a"), "Texas Instruments")
        self.assertEqual(result.get("manufacturer_b"), "onsemi")


class UiHandoffContractTests(unittest.TestCase):
    def test_find_replacement_compare_href_carries_manufacturers(self):
        page = (
            Path(__file__).resolve().parents[1]
            / "apps/web/src/app/find-replacement/page.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("manufacturer_a", page)
        self.assertIn("manufacturer_b", page)
        self.assertIn("manufacturerA: compareManufacturerA", page)
        self.assertIn("manufacturerB:", page)

    def test_compare_page_reads_and_submits_manufacturers(self):
        page = (
            Path(__file__).resolve().parents[1]
            / "apps/web/src/app/compare-parts/page.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("manufacturer_a", page)
        self.assertIn("manufacturerA", page)
        self.assertIn("manufacturerB", page)
        api = (
            Path(__file__).resolve().parents[1] / "apps/web/src/lib/api.ts"
        ).read_text(encoding="utf-8")
        self.assertIn("manufacturer_a", api)
        self.assertIn("manufacturer_b", api)


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


def test_compare_json_and_multipart_preserve_manufacturers(_sandbox, monkeypatch):
    monkeypatch.setenv("CADIVOR_ALLOW_PRODUCTION_ANALYSIS", "0")
    client = TestClient(app)
    headers = _auth_headers(client)

    fixture = {
        "ok": True,
        "status": "completed",
        "part_a": "LM358N",
        "part_b": "LM358AN/NOPB",
        "manufacturer_a": "Texas Instruments",
        "manufacturer_b": "Texas Instruments",
        "finding": FINDING_NEEDS_VERIFICATION,
        "engineering_evidence_summary": "identity preserved",
        "counts": {"compatible": 0, "needs_data": 1, "listing_agreement": 0,
                   "material_difference": 0, "conflicting": 0,
                   "breakdown": {"catalog_difference": 0}},
        "rows": [],
        "part_cards": {
            "a": {"mpn": "LM358N", "manufacturer": "Texas Instruments",
                  "identity_verified": True, "found": True},
            "b": {"mpn": "LM358AN/NOPB", "manufacturer": "Texas Instruments",
                  "identity_verified": True, "found": True},
        },
        "analysis_id": None,
        "gap": "",
    }

    with patch(
        "apps.api.migration_tools.compare_parts_payload",
        return_value=fixture,
    ) as mocked:
        json_res = client.post(
            "/tools/compare-parts",
            headers=headers,
            json={
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
            },
        )
        assert json_res.status_code == 200
        kwargs = mocked.call_args.kwargs
        assert kwargs.get("manufacturer_a") == "Texas Instruments"
        assert kwargs.get("manufacturer_b") == "Texas Instruments"

        # Force multipart/form-data (urlencoded `data=` alone is not multipart).
        pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        multi = client.post(
            "/tools/compare-parts",
            headers=headers,
            data={
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
                "analysis_id": "",
            },
            files={
                "datasheet_a": ("blank.pdf", pdf_bytes, "application/pdf"),
            },
        )
        assert multi.status_code == 200, multi.text
        kwargs2 = mocked.call_args.kwargs
        assert kwargs2.get("manufacturer_a") == "Texas Instruments"
        assert kwargs2.get("manufacturer_b") == "Texas Instruments"

        # Multi-candidate JSON compare keeps Part A identity while Part B brands
        # stay independent (second candidate may omit manufacturer_b).
        multi_cand = client.post(
            "/tools/compare-parts",
            headers=headers,
            json={
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
            },
        )
        assert multi_cand.status_code == 200
        assert mocked.call_args.kwargs.get("manufacturer_a") == "Texas Instruments"


def test_decision_persistence_keeps_manufacturer_identity(_sandbox, monkeypatch):
    monkeypatch.setenv("CADIVOR_ALLOW_PRODUCTION_ANALYSIS", "0")
    client = TestClient(app)
    headers = _auth_headers(client)

    snapshot = {
        "ok": True,
        "finding": FINDING_NEEDS_VERIFICATION,
        "manufacturer_a": "Texas Instruments",
        "manufacturer_b": "Texas Instruments",
        "part_cards": {
            "a": {"mpn": "LM358N", "manufacturer": "Texas Instruments"},
            "b": {"mpn": "LM358AN/NOPB", "manufacturer": "Texas Instruments"},
        },
        "rows": [],
        "counts": {},
        "engineering_evidence_summary": "TI handoff",
        "engineering_evidence_status": "incomplete",
        "gap": "",
    }
    with patch(
        "apps.api.migration_tools.compare_parts_payload",
        return_value={**snapshot, "part_a": "LM358N", "part_b": "LM358AN/NOPB"},
    ):
        create = client.post(
            "/decision-records",
            headers=headers,
            json={
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
                "decision": "hold_for_review",
                "reviewer": SMOKE_EMAIL,
                "rationale": "Identity handoff regression",
                "comparison_snapshot": snapshot,
            },
        )
    assert create.status_code in {200, 201}
    record = create.json()["record"]
    assert record.get("manufacturer_a") == "Texas Instruments"
    assert record.get("manufacturer_b") == "Texas Instruments"
    snap = record.get("comparison_snapshot") or {}
    assert snap.get("manufacturer_a") == "Texas Instruments"
    assert (snap.get("part_cards") or {}).get("a", {}).get("manufacturer") == (
        "Texas Instruments"
    )

    listed = client.get("/decision-records", headers=headers)
    assert listed.status_code == 200
    rows = listed.json().get("records") or []
    assert any(
        row.get("part_a") == "LM358N"
        and row.get("manufacturer_a") == "Texas Instruments"
        for row in rows
    )


def test_bom_scoped_handoff_forwards_manufacturers(_sandbox, monkeypatch):
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
    assert analysis_id

    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "status": "completed",
            "part_a": "LM358N",
            "part_b": "LM358AN/NOPB",
            "manufacturer_a": kwargs.get("manufacturer_a"),
            "manufacturer_b": kwargs.get("manufacturer_b"),
            "analysis_id": analysis_id,
            "finding": FINDING_NEEDS_VERIFICATION,
            "engineering_evidence_summary": "bom scoped",
            "counts": {},
            "rows": [],
            "part_cards": {
                "a": {"mpn": "LM358N", "manufacturer": "Texas Instruments"},
                "b": {"mpn": "LM358AN/NOPB", "manufacturer": "Texas Instruments"},
            },
            "gap": "",
        }

    with patch("apps.api.migration_tools.compare_parts_payload", side_effect=_capture):
        res = client.post(
            "/tools/compare-parts",
            headers=headers,
            json={
                "part_a": "LM358N",
                "part_b": "LM358AN/NOPB",
                "analysis_id": analysis_id,
                "manufacturer_a": "Texas Instruments",
                "manufacturer_b": "Texas Instruments",
            },
        )
    assert res.status_code == 200
    assert captured.get("analysis_id") == analysis_id
    assert captured.get("manufacturer_a") == "Texas Instruments"
    assert captured.get("manufacturer_b") == "Texas Instruments"
    assert res.json().get("manufacturer_a") == "Texas Instruments"


if __name__ == "__main__":
    unittest.main()
