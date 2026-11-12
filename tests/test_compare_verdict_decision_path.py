"""Compare Parts verdict honesty + replacement → compare → decision persistence."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from src.component_family_profiles import COMPARE_LIMIT_GE, COMPARE_LIMIT_LE, FieldSpec
from src.parametric_compare import compare_field_values
from src.parts_compare import (
    FINDING_COMPATIBLE,
    FINDING_LISTING_AGREEMENT,
    FINDING_MATERIAL,
    FINDING_NEEDS_VERIFICATION,
    assess_compare_row,
    build_parts_comparison,
)
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)


def _auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


class ParametricVerdictHonestyTests(unittest.TestCase):
    def test_known_unequal_and_equal_values_without_family_markers(self):
        # Parametric engine compares known magnitudes even when family is unknown.
        voltage_spec = FieldSpec(
            key="rated_voltage",
            label="Rated voltage",
            compare=COMPARE_LIMIT_GE,
            unit="V",
            value_role="max",
        )
        offset_spec = FieldSpec(
            key="input_offset_mv",
            label="Input offset",
            compare=COMPARE_LIMIT_LE,
            unit="mV",
            value_role="max",
        )
        self.assertEqual(compare_field_values("50V", "25V", voltage_spec)[0], "Different")
        self.assertEqual(compare_field_values("50V", "50V", voltage_spec)[0], "Match")
        self.assertEqual(compare_field_values("3 mV", "2 mV", offset_spec)[0], "Different")
        self.assertEqual(compare_field_values("3", "3", offset_spec)[0], "Match")

        # Arbitrary MPNs with no family markers still Match equal package evidence.
        equal = build_parts_comparison(
            {
                "manufacturer_part_number": "USER-MPN-A2",
                "package": "0603",
                "datasheet_url": "https://example.com/a.pdf",
            },
            {
                "manufacturer_part_number": "USER-MPN-B2",
                "package": "0603",
                "datasheet_url": "https://example.com/b.pdf",
            },
        )
        self.assertEqual(equal["family"], "General electronic component")
        package = next(row for row in equal["rows"] if row["Attribute"] == "Package")
        self.assertEqual(package["Assessment"], FINDING_COMPATIBLE)

    def test_catalog_only_match_is_listing_or_needs_verification_not_compatible(self):
        comparison = build_parts_comparison(
            {
                "manufacturer_part_number": "CAT-A",
                "description": "Ceramic capacitor",
                "capacitance": "0.1uF",
                "rated_voltage": "50V",
                "package": "0603",
                "source": "DigiKey",
                "field_sources": {
                    "capacitance": "DigiKey",
                    "rated_voltage": "DigiKey",
                    "package": "DigiKey",
                },
            },
            {
                "manufacturer_part_number": "CAT-B",
                "description": "Ceramic capacitor",
                "capacitance": "0.1uF",
                "rated_voltage": "50V",
                "package": "0603",
                "source": "DigiKey",
                "field_sources": {
                    "capacitance": "DigiKey",
                    "rated_voltage": "DigiKey",
                    "package": "DigiKey",
                },
            },
        )
        self.assertNotEqual(comparison["finding"], FINDING_COMPATIBLE)
        assessments = {row["Assessment"] for row in comparison["rows"] if row.get("Part A")}
        self.assertTrue(
            assessments.issubset(
                {
                    FINDING_LISTING_AGREEMENT,
                    FINDING_NEEDS_VERIFICATION,
                    FINDING_MATERIAL,
                }
            )
        )
        self.assertNotIn(FINDING_COMPATIBLE, assessments)

    def test_am29_cross_family_lead_never_promotes_to_compatible(self):
        """AM29F010B-70EC vs a resistor lead stays Material / Needs verification.

        Official Am29F010B docs and Microchip AN S72014 note SST39SF010A as a
        related 1 Mb device, but TSOP footprint and sector/software behavior
        differ. Without manufacturer-verified fit evidence for the entered
        suffix, cross-family catalog leads must not become Compatible.
        """
        comparison = build_parts_comparison(
            {
                "manufacturer_part_number": "AM29F010B-70EC",
                "manufacturer": "AMD",
                "description": "1 Mb NOR flash memory",
            },
            {
                "manufacturer_part_number": "RC0603FR-0710KL",
                "manufacturer": "Yageo",
                "description": "Thick film resistor 10k",
                "resistance": "10k",
            },
        )
        self.assertTrue(comparison["family_mismatch"])
        self.assertEqual(comparison["finding"], FINDING_MATERIAL)
        self.assertNotEqual(comparison["finding"], FINDING_COMPATIBLE)
        # Forced Match with catalog / missing provenance stays non-Compatible.
        catalog_assessment = assess_compare_row(
            status="Match",
            source_a="DigiKey catalog",
            source_b="DigiKey catalog",
        )
        self.assertIn(
            catalog_assessment,
            {FINDING_LISTING_AGREEMENT, FINDING_NEEDS_VERIFICATION},
        )
        self.assertNotEqual(catalog_assessment, FINDING_COMPATIBLE)
        self.assertEqual(
            assess_compare_row(
                status="Match",
                source_a="Not stated",
                source_b="Not stated",
            ),
            FINDING_NEEDS_VERIFICATION,
        )


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


def test_replacement_candidate_compare_decision_persists_after_reload(_sandbox):
    """Fixture path: replacement candidate → compare → decision record → reload."""
    original = {
        "manufacturer_part_number": "C0603C104K5RACTU",
        "manufacturer": "KEMET",
        "description": "Ceramic capacitor",
        "package": "0603",
        "mounting_style": "SMD",
        "capacitance": "0.1uF",
        "rated_voltage": "50V",
        "dielectric": "X7R",
        "tolerance": "10%",
        "lifecycle_status": "Active",
        "datasheet_url": "https://example.com/original-cap.pdf",
    }
    candidate = {
        "manufacturer_part_number": "ALT-CAP-0603",
        "manufacturer": "KEMET",
        "description": "Ceramic capacitor",
        "package": "0603",
        "mounting_style": "SMD",
        "capacitance": "0.1uF",
        "rated_voltage": "50V",
        "dielectric": "X7R",
        "tolerance": "10%",
        "lifecycle_status": "Active",
        "datasheet_url": "https://example.com/alt-cap.pdf",
    }
    comparison = build_parts_comparison(original, candidate)
    self_assert_compatible = comparison["finding"] == FINDING_COMPATIBLE
    assert self_assert_compatible

    fixture_compare_payload = {
        "ok": True,
        "status": "completed",
        "mode": "fixture-compare",
        "part_a": original["manufacturer_part_number"],
        "part_b": candidate["manufacturer_part_number"],
        "finding": comparison["finding"],
        "engineering_evidence_summary": comparison.get("engineering_evidence_summary") or "",
        "engineering_evidence_status": comparison.get("engineering_evidence_status") or "",
        "counts": comparison["counts"],
        "family": comparison.get("family"),
        "family_mismatch": comparison.get("family_mismatch"),
        "rows": comparison["rows"],
        "part_cards": {"a": comparison.get("part_a"), "b": comparison.get("part_b")},
        "evidence_sources": comparison.get("evidence_sources") or {},
        "datasheet_identity": comparison.get("datasheet_identity") or {},
        "gap": "",
    }

    client = TestClient(app)
    headers = _auth_headers(client)

    with patch(
        "apps.api.migration_tools.compare_parts_payload",
        return_value=fixture_compare_payload,
    ):
        saved = client.post(
            "/decision-records",
            headers=headers,
            json={
                "part_a": original["manufacturer_part_number"],
                "part_b": candidate["manufacturer_part_number"],
                "decision": "hold_for_review",
                "reviewer": "Fixture reviewer",
                "rationale": (
                    "Recorded from a fixture replacement candidate comparison; "
                    "hold pending board-level validation."
                ),
                "validation_checks": [],
                "residual_risk": "medium",
            },
        )
    assert saved.status_code == 201, saved.text
    record = saved.json()["record"]
    record_id = record["id"]
    assert record["part_a"] == original["manufacturer_part_number"]
    assert record["part_b"] == candidate["manufacturer_part_number"]
    assert record["comparison_snapshot"]["finding"] == FINDING_COMPATIBLE
    assert record["qualification_status"] == "not-qualified-by-cadivor"

    listed = client.get("/decision-records", headers=headers)
    assert listed.status_code == 200
    reloaded = [row for row in listed.json()["records"] if row["id"] == record_id]
    assert len(reloaded) == 1
    assert reloaded[0]["comparison_snapshot"]["finding"] == FINDING_COMPATIBLE
    assert reloaded[0]["part_b"] == candidate["manufacturer_part_number"]
    assert reloaded[0]["decision"] == "hold_for_review"


if __name__ == "__main__":
    unittest.main()
