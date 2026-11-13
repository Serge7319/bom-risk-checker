"""Fixture/mock regressions for FR → Compare → Decision honesty (no live suppliers)."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from src.alternative_finder_state import (
    LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
    LABEL_VERIFIED_REPLACEMENTS,
    OUTCOME_SUCCESS,
    candidate_has_verified_fit,
    search_outcome_label,
)
from src.datasheet_comparison import build_datasheet_comparison, user_facing_comparison_rows
from src.parametric_compare import engineering_confidence_from_rows
from src.parts_compare import (
    FINDING_CATALOG_DIFFERENCE,
    FINDING_COMPATIBLE,
    FINDING_LISTING_AGREEMENT,
    FINDING_MATERIAL,
    FINDING_NEEDS_VERIFICATION,
    _customer_counts_from_assessments,
    _provenance_aware_evidence_status,
    _provenance_aware_evidence_summary,
    assess_compare_row,
    build_parts_comparison,
    primary_count_total,
)
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)
from tests.test_compare_parts import _cap, _verified_cap_datasheet


class OutcomeHonestyTests(unittest.TestCase):
    def test_compatible_with_qualification_required_is_not_verified(self):
        row = {
            "Classification": "Compatible",
            "fit": "supplier-listed candidate; qualification required",
        }
        self.assertFalse(candidate_has_verified_fit(row))
        self.assertEqual(
            search_outcome_label(OUTCOME_SUCCESS, candidates=[row]),
            LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
        )

    def test_not_qualified_fit_never_verified(self):
        row = {
            "classification": "Compatible",
            "fit": "not qualified — lifecycle evidence incomplete or conflicting",
        }
        self.assertFalse(candidate_has_verified_fit(row))
        self.assertEqual(
            search_outcome_label(OUTCOME_SUCCESS, candidates=[row]),
            LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
        )

    def test_compatible_alone_is_not_verified_without_authoritative_evidence(self):
        row = {"Classification": "Compatible", "fit": "compatible"}
        self.assertFalse(candidate_has_verified_fit(row))
        self.assertEqual(
            search_outcome_label(OUTCOME_SUCCESS, candidates=[row]),
            LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
        )

    def test_verified_fit_control_requires_authoritative_evidence(self):
        row = {
            "Classification": "Compatible",
            "fit": "compatible — datasheet-backed engineering review",
            "evidence_class": "manufacturer-datasheet",
            "authoritative_fit_evidence": True,
        }
        self.assertTrue(candidate_has_verified_fit(row))
        self.assertEqual(
            search_outcome_label(OUTCOME_SUCCESS, candidates=[row]),
            LABEL_VERIFIED_REPLACEMENTS,
        )


class CatalogRetainedCountReconcileTests(unittest.TestCase):
    """39→24 retained must not later become 0 when discovery_channel is missing."""

    def test_family_partition_refresh_defaults_missing_channel_to_catalog(self):
        from src.alternative_finder_search import refresh_catalog_retained_after_partition

        discovery = {
            "catalog_raw_count": 39,
            "catalog_retained_count": 24,
            "catalog_filter_summary": (
                "39 raw catalog matches → 24 retained after manufacturer filters"
            ),
            "providers": {
                "Mouser": {
                    "catalog": "ok",
                    "catalog_raw_count": 39,
                    "catalog_retained_count": 24,
                }
            },
        }
        # Simulate AF rows that lost discovery_channel after projection.
        displayed = [
            {
                "Alternative Part": f"LM358-ALT-{idx}",
                "Supplier": "Mouser",
            }
            for idx in range(24)
        ]
        discovery = refresh_catalog_retained_after_partition(discovery, displayed)

        self.assertEqual(int(discovery["catalog_retained_count"]), 24)
        self.assertEqual(
            int(discovery["providers"]["Mouser"]["catalog_retained_count"]),
            24,
        )
        summary = str(discovery["catalog_filter_summary"])
        self.assertIn("39 raw catalog matches → 24 retained", summary)
        # Must not report contradictory 0 retained after a prior 24.
        self.assertNotRegex(summary, r"39 raw catalog matches → 0 retained")
        self.assertEqual(summary.count("raw catalog matches →"), 1)

    def test_provider_retained_rematch_tolerates_supplier_label_aliases(self):
        """``Mouser Electronics`` rows must still count under providers['Mouser']."""
        from src.alternative_finder_search import refresh_catalog_retained_after_partition

        discovery = {
            "catalog_raw_count": 24,
            "catalog_retained_count": 24,
            "catalog_filter_summary": "24 raw catalog matches → 24 retained",
            "providers": {
                "Mouser": {
                    "catalog": "ok",
                    "catalog_raw_count": 24,
                    "catalog_retained_count": 24,
                }
            },
        }
        displayed = [
            {
                "Alternative Part": f"LM358-ALT-{idx}",
                "Supplier": "Mouser Electronics",
                "discovery_channel": "catalog",
            }
            for idx in range(24)
        ]
        discovery = refresh_catalog_retained_after_partition(discovery, displayed)
        self.assertEqual(int(discovery["catalog_retained_count"]), 24)
        self.assertEqual(
            int(discovery["providers"]["Mouser"]["catalog_retained_count"]),
            24,
        )
        self.assertNotEqual(
            int(discovery["providers"]["Mouser"]["catalog_retained_count"]),
            0,
        )

    def test_zero_retained_explicit_substitutions_are_honored(self):
        from src.alternative_finder_search import refresh_catalog_retained_after_partition

        discovery = {
            "catalog_raw_count": 0,
            "explicit_count": 2,
            "explicit_retained_count": 2,
            "providers": {
                "DigiKey": {
                    "substitutions": "ok",
                    "explicit_count": 2,
                    "explicit_raw_count": 2,
                    "explicit_retained_count": 2,
                }
            },
        }
        # Family partition dropped every explicit row.
        discovery = refresh_catalog_retained_after_partition(discovery, [])
        self.assertEqual(int(discovery["explicit_retained_count"]), 0)
        self.assertEqual(
            int(discovery["providers"]["DigiKey"]["explicit_retained_count"]),
            0,
        )

    def test_discovery_channel_preserved_on_salvage_rows(self):
        from src.alternative_engine import build_salvage_candidates_from_discovery

        discovery = {
            "candidates": [
                {
                    "manufacturer_part_number": "LM358ADR2G",
                    "manufacturer": "onsemi",
                    "source": "Mouser",
                    "description": "Dual op amp",
                    "discovery_channel": "catalog",
                    "primary_category": "Amplifiers",
                },
                {
                    "manufacturer_part_number": "LM358DR2G",
                    "manufacturer": "onsemi",
                    "source": "DigiKey",
                    "description": "Dual op amp",
                    "discovery_channel": "explicit",
                    "substitute_type": "Direct",
                    "evidence_type": "Distributor-listed substitute",
                },
            ]
        }
        rows = build_salvage_candidates_from_discovery(
            discovery,
            canonical_mpn="LM358DR",
            original_part_number="LM358DR",
        )
        by_mpn = {str(row.get("Alternative Part")): row for row in rows}
        self.assertEqual(by_mpn["LM358ADR2G"].get("discovery_channel"), "catalog")
        self.assertEqual(by_mpn["LM358DR2G"].get("discovery_channel"), "explicit")


class Lm358CompareProvenanceTests(unittest.TestCase):
    def _lm358_pair(self, *, with_catalog_sources: bool):
        original = {
            "manufacturer_part_number": "LM358DR",
            "manufacturer": "Texas Instruments",
            "description": "Dual operational amplifier",
            "architecture": "Operational Amplifier",
            "bandwidth_mhz": "0.7 MHz",
            "input_bias_na": "20 nA",
            "input_offset_mv": "3 mV",
            "lifecycle_status": "Active",
        }
        candidate = {
            "manufacturer_part_number": "LM358ADR2G",
            "manufacturer": "onsemi",
            "description": "Dual operational amplifier",
            "architecture": "Operational Amplifier",
            "bandwidth_mhz": "1.0 MHz",
            "input_bias_na": "45 nA",
            "input_offset_mv": "2 mV",
            "lifecycle_status": "Active",
        }
        if with_catalog_sources:
            original["source"] = "DigiKey"
            candidate["source"] = "Mouser"
            original["field_sources"] = {
                "architecture": "DigiKey",
                "bandwidth_mhz": "DigiKey",
                "input_bias_na": "DigiKey",
                "input_offset_mv": "DigiKey",
                "lifecycle_status": "DigiKey",
            }
            candidate["field_sources"] = {
                "architecture": "Mouser",
                "bandwidth_mhz": "Mouser",
                "input_bias_na": "Mouser",
                "input_offset_mv": "Mouser",
                "lifecycle_status": "Mouser",
            }
        return original, candidate

    def test_catalog_differences_are_catalog_reported_not_material(self):
        original, candidate = self._lm358_pair(with_catalog_sources=True)
        comparison = build_datasheet_comparison(original, candidate)
        offset = next(
            row for row in comparison["rows"] if row.get("Key") == "input_offset_mv"
        )
        self.assertEqual(offset["Status"], "Different")
        projected = user_facing_comparison_rows([offset])[0]
        self.assertEqual(projected["Assessment"], FINDING_CATALOG_DIFFERENCE)
        self.assertNotEqual(projected["Assessment"], FINDING_MATERIAL)

        full = build_parts_comparison(original, candidate, extract_linked_datasheets=False)
        self.assertNotEqual(full["finding"], FINDING_MATERIAL)
        self.assertNotEqual(full["finding"], FINDING_COMPATIBLE)
        summary = str(full.get("engineering_evidence_summary") or "")
        self.assertNotIn("confirmed matches", summary.casefold())
        # Customer counts come from Assessments, not raw Status Match buckets.
        self.assertEqual(int(full["counts"].get("compatible") or 0), 0)
        self.assertGreaterEqual(int(full["counts"].get("needs_data") or 0), 1)
        self.assertNotIn("catalog_difference", full["counts"])
        self.assertGreaterEqual(
            int((full["counts"].get("breakdown") or {}).get("catalog_difference") or 0),
            1,
        )
        self.assertEqual(primary_count_total(full["counts"]), len(full.get("rows") or []))
        # Customer status is provenance-derived; raw Status stays diagnostic.
        self.assertIn(
            full["engineering_evidence_status"],
            {"incomplete", "partial", "conflicts documented", "complete"},
        )
        self.assertIn(str(full["engineering_evidence_status"]), summary)
        self.assertIn("engineering_evidence_status_raw", full)
        # Raw numeric Status comparisons remain available internally.
        self.assertGreaterEqual(int(full["internal_status_counts"].get("Different") or 0), 1)
        self.assertEqual(
            int(full["count_aliases"].get("Different") or 0),
            int(full["internal_status_counts"].get("Different") or 0),
        )
        self.assertIn("fit unverified", summary.casefold())

    def test_provenance_summary_counts_catalog_diff_once_with_listing(self):
        """Catalog diffs fold into need-verification once; listings stay separate."""
        summary = _provenance_aware_evidence_summary(
            {
                "compatible": 0,
                "listing_agreement": 1,
                "material_difference": 0,
                "catalog_difference": 1,
                "needs_data": 0,
                "conflicting": 0,
            },
            engineering_status="complete",  # ignored — status comes from assessments
        )
        self.assertIn("incomplete", summary)  # not raw "complete"
        self.assertIn("0 verified matches", summary)
        self.assertIn("1 field need verification", summary)
        self.assertIn("1 catalog agreement", summary)
        self.assertIn("catalog-reported differences remain fit unverified", summary)
        # Need-verification total must equal folded catalog_diff (not double-counted).
        self.assertEqual(summary.count("need verification"), 1)
        self.assertNotRegex(summary, r"\d+ catalog-reported")

    def test_customer_counts_additive_with_nested_catalog_breakdown(self):
        assessments = {
            "compatible": 2,
            "listing_agreement": 1,
            "material_difference": 1,
            "catalog_difference": 2,
            "needs_data": 3,
            "conflicting": 0,
        }
        counts = _customer_counts_from_assessments(assessments)
        self.assertEqual(counts["needs_data"], 5)
        self.assertEqual(counts["breakdown"]["catalog_difference"], 2)
        self.assertNotIn("catalog_difference", counts)
        # Primary buckets sum to row total (2+1+1+5+0).
        self.assertEqual(primary_count_total(counts), 9)

    def test_mixed_evidence_counts_sum_to_row_total(self):
        """Mixed Compatible / listing / catalog-diff / needs rows stay additive."""
        original, candidate = self._lm358_pair(with_catalog_sources=True)
        mixed_rows = [
            {
                "Attribute": "Package",
                "Assessment": FINDING_COMPATIBLE,
                "Status": "Match",
            },
            {
                "Attribute": "Lifecycle",
                "Assessment": FINDING_LISTING_AGREEMENT,
                "Status": "Match",
            },
            {
                "Attribute": "Input offset",
                "Assessment": FINDING_CATALOG_DIFFERENCE,
                "Status": "Different",
            },
            {
                "Attribute": "Pinout",
                "Assessment": FINDING_NEEDS_VERIFICATION,
                "Status": "Needs data",
            },
            {
                "Attribute": "Supply current",
                "Assessment": FINDING_MATERIAL,
                "Status": "Different",
            },
        ]
        with patch(
            "src.parts_compare.user_facing_compare_rows",
            return_value=mixed_rows,
        ):
            full = build_parts_comparison(
                original, candidate, extract_linked_datasheets=False
            )
        counts = full["counts"]
        self.assertEqual(int(counts.get("compatible") or 0), 1)
        self.assertEqual(int(counts.get("listing_agreement") or 0), 1)
        self.assertEqual(int(counts.get("material_difference") or 0), 1)
        self.assertEqual(int(counts.get("needs_data") or 0), 2)  # catalog + pure needs
        self.assertEqual(
            int((counts.get("breakdown") or {}).get("catalog_difference") or 0), 1
        )
        self.assertNotIn("catalog_difference", counts)
        self.assertEqual(primary_count_total(counts), len(mixed_rows))
        self.assertEqual(primary_count_total(counts), len(full.get("rows") or []))
        summary = str(full.get("engineering_evidence_summary") or "")
        status = str(full.get("engineering_evidence_status") or "")
        self.assertEqual(status, "conflicts documented")  # material present
        self.assertIn(status, summary)
        self.assertNotIn("confirmed matches", summary.casefold())
        # Raw parametric status retained only as diagnostics.
        self.assertIn("engineering_evidence_status_raw", full)
        self.assertIn("internal_status_counts", full)

    def test_missing_sources_stay_needs_verification(self):
        original, candidate = self._lm358_pair(with_catalog_sources=False)
        comparison = build_datasheet_comparison(original, candidate)
        offset = next(
            row for row in comparison["rows"] if row.get("Key") == "input_offset_mv"
        )
        projected = user_facing_comparison_rows([offset])[0]
        self.assertEqual(projected["Assessment"], FINDING_NEEDS_VERIFICATION)

    def test_verified_datasheet_control_can_claim_material_or_compatible(self):
        assessment = assess_compare_row(
            status="Different",
            class_a="maximum",
            class_b="maximum",
            condition_a="@ 25C",
            condition_b="@ 25C",
            source_a="datasheet, p. 4",
            source_b="datasheet, p. 5",
        )
        self.assertEqual(assessment, FINDING_MATERIAL)

        listing = assess_compare_row(
            status="Match",
            class_a="typical",
            class_b="typical",
            condition_a="@ 25C",
            condition_b="@ 25C",
            source_a="DigiKey",
            source_b="Mouser",
        )
        self.assertEqual(listing, FINDING_LISTING_AGREEMENT)
        self.assertIn("fit unverified", listing.casefold())

        confidence = engineering_confidence_from_rows(
            [
                {"Status": "Match", "Attribute": "Package"},
                {"Status": "Listing agreement", "Attribute": "Lifecycle"},
                {"Status": "Needs data", "Attribute": "Pinout"},
            ]
        )
        summary = str(confidence["engineering_evidence_summary"])
        self.assertIn("parametric", summary.casefold())
        self.assertIn("Catalog values agree — fit unverified", summary)
        self.assertNotIn("confirmed matches", summary.casefold())


class UiHandoffContractTests(unittest.TestCase):
    def test_compare_parts_page_does_not_auto_attach_last_or_first_bom(self):
        page = (
            Path(__file__).resolve().parents[1]
            / "apps/web/src/app/compare-parts/page.tsx"
        ).read_text(encoding="utf-8")
        self.assertNotIn("preferredAnalysis = queryAnalysis || last", page)
        self.assertNotIn("analysisId || last?.analysis_id", page)
        self.assertNotIn("setAnalysisId(defaultAnalysis)", page)
        self.assertIn("Clear BOM", page)
        self.assertIn("No BOM — standalone compare", page)

    def test_compare_kpi_strip_surfaces_listing_agreements_not_attributes_align(self):
        """Banner/matrix catalog agreements must appear in the KPI strip."""
        page = (
            Path(__file__).resolve().parents[1]
            / "apps/web/src/app/compare-parts/page.tsx"
        ).read_text(encoding="utf-8")
        self.assertNotIn("attributes align", page)
        self.assertIn("evidenceCounts.listing_agreement", page)
        self.assertIn("catalog agreement", page)
        self.assertIn("verified match", page)
        self.assertIn("material difference", page)
        self.assertIn("need verification", page)

    def test_find_replacement_never_labels_unverified_qualified(self):
        page = (
            Path(__file__).resolve().parents[1]
            / "apps/web/src/app/find-replacement/page.tsx"
        ).read_text(encoding="utf-8")
        self.assertNotIn("Qualified alternatives", page)
        self.assertIn("candidateListHeading", page)
        self.assertIn("Supplier-listed candidates", page)
        self.assertIn("qualification required", page)


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


def test_standalone_compare_does_not_attach_latest_bom(_sandbox):
    client = TestClient(app)
    headers = _auth_headers(client)
    # Seed a saved analysis so a buggy use_latest_if_missing path would attach it.
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("bom.csv", b"MPN,Quantity\nLM358DR,1\n", "text/csv")},
    )
    assert analyze.status_code in {200, 201}
    body = analyze.json()
    latest_id = str(body.get("analysis_id") or body.get("id") or "")
    assert latest_id

    fixture_payload = {
        "ok": True,
        "status": "completed",
        "mode": "fixture-compare",
        "part_a": "LM358DR",
        "part_b": "LM358ADR2G",
        "finding": FINDING_NEEDS_VERIFICATION,
        "engineering_evidence_summary": (
            "Engineering evidence: partial — 1 parametric match, "
            "2 fields need verification"
        ),
        "counts": {
            "compatible": 1,
            "listing_agreement": 0,
            "material_difference": 0,
            "needs_data": 2,
            "conflicting": 0,
        },
        "rows": [],
        "analysis_id": None,
        "gap": "",
    }
    with patch(
        "apps.api.migration_tools.compare_parts_payload",
        return_value=fixture_payload,
    ) as mocked:
        res = client.post(
            "/tools/compare-parts",
            headers=headers,
            json={"part_a": "LM358DR", "part_b": "LM358ADR2G"},
        )
    assert res.status_code == 200
    # API must call compare without inventing the latest analysis_id.
    kwargs = mocked.call_args.kwargs if mocked.call_args else {}
    assert not kwargs.get("analysis_id")
    assert kwargs.get("use_latest_if_missing") is False
    payload = res.json()
    attached = str(payload.get("analysis_id") or "").strip()
    assert attached in {"", "None"} or attached != latest_id


def test_analysis_scoped_handoff_preserves_analysis_id(_sandbox):
    client = TestClient(app)
    headers = _auth_headers(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("bom.csv", b"MPN,Quantity\nLM358DR,1\n", "text/csv")},
    )
    assert analyze.status_code in {200, 201}
    analysis_id = str(analyze.json().get("analysis_id") or analyze.json().get("id") or "")
    assert analysis_id

    fixture_payload = {
        "ok": True,
        "status": "completed",
        "mode": "fixture-compare",
        "part_a": "LM358DR",
        "part_b": "LM358ADR2G",
        "finding": FINDING_NEEDS_VERIFICATION,
        "engineering_evidence_summary": "Engineering evidence: partial — fit unverified",
        "counts": {
            "compatible": 0,
            "listing_agreement": 1,
            "material_difference": 0,
            "needs_data": 2,
            "conflicting": 0,
        },
        "rows": [],
        "analysis_id": analysis_id,
        "gap": "",
    }
    with patch(
        "apps.api.migration_tools.compare_parts_payload",
        return_value=fixture_payload,
    ) as mocked:
        res = client.post(
            "/tools/compare-parts",
            headers=headers,
            json={
                "part_a": "LM358DR",
                "part_b": "LM358ADR2G",
                "analysis_id": analysis_id,
            },
        )
    assert res.status_code == 200
    kwargs = mocked.call_args.kwargs if mocked.call_args else {}
    assert str(kwargs.get("analysis_id") or "") == analysis_id
    assert kwargs.get("use_latest_if_missing") is False
    assert res.json().get("analysis_id") == analysis_id


def test_decision_record_persists_after_reload(_sandbox):
    original = _cap()
    candidate = _cap(mpn="ALT-CAP-0603")
    comparison = build_parts_comparison(
        original,
        candidate,
        datasheet_a=_verified_cap_datasheet(mpn=original["manufacturer_part_number"]),
        datasheet_b=_verified_cap_datasheet(mpn=candidate["manufacturer_part_number"]),
        extract_linked_datasheets=False,
    )
    assert comparison["finding"] == FINDING_COMPATIBLE

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
                "rationale": "Fixture verified-datasheet control; hold pending validation.",
                "validation_checks": [],
                "residual_risk": "medium",
            },
        )
    assert saved.status_code == 201, saved.text
    record = saved.json()["record"]
    record_id = record["id"]
    listed = client.get("/decision-records", headers=headers)
    assert listed.status_code == 200
    reloaded = [row for row in listed.json()["records"] if row["id"] == record_id]
    assert len(reloaded) == 1
    assert reloaded[0]["comparison_snapshot"]["finding"] == FINDING_COMPATIBLE
    assert reloaded[0]["part_b"] == candidate["manufacturer_part_number"]


if __name__ == "__main__":
    unittest.main()
