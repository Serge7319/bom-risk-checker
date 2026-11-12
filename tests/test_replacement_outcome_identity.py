"""Focused replacement follow-up: search outcome honesty + manufacturer identity."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from apps.api.manufacturer_identity import (
    identity_ambiguity_payload,
    lineage_identity_choices,
    manufacturer_canonical,
    manufacturers_match,
)
from src.alternative_finder_state import (
    OUTCOME_CATALOG_LEADS_ONLY,
    OUTCOME_FAILURE,
    OUTCOME_NO_RESULTS,
    OUTCOME_PARTIAL_SUCCESS,
    OUTCOME_PARTIAL_SUPPLIER,
    OUTCOME_SUCCESS,
    resolve_search_outcome,
    search_outcome_label,
)


class SearchOutcomeAggregationTests(unittest.TestCase):
    def test_valid_zero_results_is_not_provider_failure(self):
        outcome = resolve_search_outcome(
            [],
            discovery={
                "providers": {
                    "Newark": {"catalog": "ok", "catalog_count": 0},
                    "Mouser": {"catalog": "ok", "catalog_count": 0},
                },
                "catalog_count": 0,
            },
        )
        self.assertEqual(outcome, OUTCOME_NO_RESULTS)
        self.assertEqual(search_outcome_label(outcome), "No results")

    def test_newark_zero_with_mouser_leads_is_catalog_leads_only(self):
        outcome = resolve_search_outcome(
            [],
            has_incomplete_evidence=True,
            discovery={
                "providers": {
                    "Newark": {"catalog": "ok", "catalog_count": 0, "lookup": "available"},
                    "Mouser": {"catalog": "ok", "catalog_count": 17, "lookup": "available"},
                },
                "unclassified_leads": [{"Alternative Part": "AM29-LEAD-1"}],
                "unfiltered_leads": [{"Alternative Part": "AM29-LEAD-2"}],
                "catalog_count": 17,
            },
        )
        self.assertEqual(outcome, OUTCOME_CATALOG_LEADS_ONLY)
        self.assertEqual(
            search_outcome_label(outcome),
            "No verified replacement; catalog leads available",
        )

    def test_true_provider_error_with_sibling_leads_is_partial_supplier(self):
        outcome = resolve_search_outcome(
            [],
            discovery={
                "providers": {
                    "Newark": {"catalog": "error", "message": "timeout"},
                    "Mouser": {"catalog": "ok", "catalog_count": 5},
                },
                "unclassified_leads": [{"Alternative Part": "LEAD-A"}],
            },
        )
        self.assertEqual(outcome, OUTCOME_PARTIAL_SUPPLIER)
        self.assertEqual(search_outcome_label(outcome), "Partial supplier results")

    def test_total_provider_failure_is_failure(self):
        outcome = resolve_search_outcome(
            [],
            discovery={
                "providers": {
                    "Newark": {"catalog": "error"},
                    "Mouser": {"catalog": "timeout"},
                    "DigiKey": {"catalog": "error"},
                },
                "catalog_count": 0,
            },
        )
        self.assertEqual(outcome, OUTCOME_FAILURE)
        self.assertEqual(search_outcome_label(outcome), "Search failed")

    def test_verified_candidates_remain_success(self):
        outcome = resolve_search_outcome(
            [{"Alternative Part": "MC7805"}],
            discovery={"providers": {"DigiKey": {"substitutions": "ok"}}},
        )
        self.assertEqual(outcome, OUTCOME_SUCCESS)

    def test_incomplete_verified_path_remains_partial_success(self):
        outcome = resolve_search_outcome(
            [{"Alternative Part": "DHT22"}],
            has_incomplete_evidence=True,
            discovery={"providers": {"Mouser": {"catalog": "ok", "catalog_count": 1}}},
        )
        self.assertEqual(outcome, OUTCOME_PARTIAL_SUCCESS)


class ManufacturerIdentityAliasTests(unittest.TestCase):
    def test_amd_and_advanced_micro_devices_alias(self):
        self.assertEqual(manufacturer_canonical("AMD"), "advanced micro devices")
        self.assertEqual(
            manufacturer_canonical("Advanced Micro Devices"),
            "advanced micro devices",
        )
        self.assertTrue(manufacturers_match("AMD", "Advanced Micro Devices"))

    def test_am29_lineage_matches_amd_to_infineon_only_for_that_mpn(self):
        self.assertTrue(
            manufacturers_match("AMD", "Infineon", mpn="AM29F010B-70EC")
        )
        self.assertTrue(
            manufacturers_match(
                "Advanced Micro Devices", "Cypress", mpn="AM29F010B-70EC"
            )
        )
        # Without MPN context, AMD must not silently equal Infineon.
        self.assertFalse(manufacturers_match("AMD", "Infineon"))

    def test_unrelated_brand_mismatch_stays_closed(self):
        self.assertFalse(
            manufacturers_match("Texas Instruments", "AMD", mpn="AM29F010B-70EC")
        )
        self.assertFalse(manufacturers_match("FakeBrand", "AMD", mpn="AM29F010B-70EC"))

    def test_unresolved_identity_payload_fail_closed_with_lineage_choices(self):
        payload = identity_ambiguity_payload(
            mpn="AM29F010B-70EC",
            requested_manufacturer="AMD",
            resolved_manufacturer="",
        )
        self.assertEqual(payload["search_outcome"], "identity_ambiguous")
        self.assertEqual(payload["candidates"], [])
        self.assertFalse(payload["original"]["identity_verified"])
        self.assertEqual(payload["original"]["manufacturer"], "")
        self.assertIn("typed manufacturer text alone is not identity proof", payload["detail"])
        canons = {row["canonical"] for row in payload["identity_choices"]}
        self.assertIn("advanced micro devices", canons)
        self.assertIn("infineon", canons)

    def test_unsupported_alias_never_verifies_identity(self):
        payload = identity_ambiguity_payload(
            mpn="NOSUCH-MPN-XYZ",
            requested_manufacturer="NotARealBrand",
            resolved_manufacturer="",
        )
        self.assertEqual(payload["candidates"], [])
        self.assertFalse(payload["original"]["identity_verified"])
        self.assertEqual(payload["identity_choices"], [])

    def test_lineage_choices_come_from_trusted_route(self):
        choices = lineage_identity_choices("AM29F010B-70EC")
        labels = {row["manufacturer"] for row in choices}
        self.assertIn("AMD", labels)
        self.assertIn("Infineon", labels)


class CatalogLeadsNeverCompatibleTests(unittest.TestCase):
    def test_cross_family_and_unclassified_projection_not_compatible(self):
        from apps.api.legacy_supplier_workflow import find_replacements

        session_result = {
            "status": "completed",
            "search_outcome": OUTCOME_CATALOG_LEADS_ONLY,
            "candidates": [],
            "original_data": {
                "manufacturer_part_number": "AM29F010B-70EC",
                "manufacturer": "",
                "supplier_data_verified": False,
                "identity_verified": False,
            },
            "original_risk": {},
            "discovery_metadata": {
                "providers": {
                    "Mouser": {"catalog": "ok", "catalog_count": 2},
                    "Newark": {"catalog": "ok", "catalog_count": 0},
                },
                "unclassified_leads": [
                    {
                        "Alternative Part": "LEAD-UNCLASS",
                        "Manufacturer": "Example",
                        "Classification": "Compatible",
                        "Candidate Disposition": "Discovery lead only",
                        "Source Identity Verified": False,
                        "Supplier": "Mouser",
                    }
                ],
                "unfiltered_leads": [
                    {
                        "Alternative Part": "LEAD-CROSS",
                        "Manufacturer": "Example",
                        "Classification": "Compatible",
                        "Candidate Disposition": "Discovery lead only",
                        "Source Identity Verified": False,
                        "Supplier": "Mouser",
                    }
                ],
            },
        }

        def _run(state, mpn, requested_manufacturer=""):
            state["alternative_finder_result"] = session_result
            return {"status": "completed", "search_outcome": OUTCOME_CATALOG_LEADS_ONLY}

        with patch(
            "src.alternative_finder_search.run_alternative_finder_search",
            side_effect=_run,
        ), patch(
            "apps.api.legacy_supplier_workflow.configured_supplier_count",
            return_value=3,
        ):
            payload = find_replacements("AM29F010B-70EC")

        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["search_outcome"], OUTCOME_CATALOG_LEADS_ONLY)
        for lead in payload["unclassified_leads"] + payload["unfiltered_leads"]:
            fit = str(lead.get("fit") or "").casefold()
            self.assertIn("not qualified", fit)
            self.assertNotIn("compatible", fit)


if __name__ == "__main__":
    unittest.main()
