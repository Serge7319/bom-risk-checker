"""Regressions for Nov 10 two-BOM smoke production defects.

Synthetic fixtures only — no live distributor calls.
"""
from __future__ import annotations

import unittest
from unittest import mock

from integrations.legacy_mpn_routes import legacy_mpn_route, legacy_route_status
from integrations.provider_health import PROVIDER_AVAILABLE
from integrations.supplier_aggregator import (
    PROVIDER_PART_NOT_FOUND,
    _safe_supplier_lookup,
    _supplier_query_variants,
    discover_alternative_candidates,
)
from src.alternative_classification import partition_candidates_by_family
from src.datasheet_comparison import build_datasheet_comparison
from src.parametric_compare import engineering_confidence_from_rows
from src.parts_compare import FINDING_COMPATIBLE, FINDING_LISTING_AGREEMENT, map_status_to_assessment


class Am29ExactMatchAndDiscoveryTests(unittest.TestCase):
    def test_hyphen_and_compact_mpns_share_legacy_family_route(self):
        for mpn in ("AM29F010B-70EC", "AM29F010B70EC"):
            route = legacy_mpn_route(mpn)
            self.assertIsNotNone(route, mpn)
            self.assertEqual(route["query_mpns"], ("AM29F010B",))
            self.assertIn("AMD", route["lineage"])

    def test_query_variants_cover_both_order_code_spellings(self):
        for mpn in ("AM29F010B-70EC", "AM29F010B70EC"):
            variants = _supplier_query_variants(mpn)
            self.assertIn("AM29F010B-70EC", variants)
            self.assertIn("AM29F010B70EC", variants)
            self.assertTrue(all("70EC" in item for item in variants))

    def test_compact_request_accepts_hyphenated_supplier_identity(self):
        calls: list[str] = []

        def lookup(query: str):
            calls.append(query)
            if query == "AM29F010B-70EC":
                return {
                    "manufacturer_part_number": "AM29F010B-70EC",
                    "manufacturer": "AMD",
                    "stock_total": 12,
                    "lifecycle_status": "Obsolete",
                }
            return {
                "manufacturer_part_number": "AM29F010B",
                "manufacturer": "AMD",
                "stock_total": 99,
            }

        result = _safe_supplier_lookup("DigiKey", lookup, "AM29F010B70EC")
        self.assertIn("AM29F010B-70EC", calls)
        self.assertEqual(result["provider_status"], PROVIDER_AVAILABLE)
        self.assertEqual(result["manufacturer_part_number"], "AM29F010B-70EC")
        self.assertEqual(result["stock_total"], 12)

    def test_provider_not_found_does_not_claim_compatible_or_no_alternative(self):
        status = legacy_route_status("AM29F010B70EC", leads=[], searched=True)
        folded = status.casefold()
        self.assertIn("no exact supplier match", folded)
        self.assertNotIn("compatible", folded)
        self.assertNotIn("no replacement exists", folded)
        self.assertIn("remains unassessed", folded)

    def test_provider_failure_keeps_discovery_incomplete_without_compatibility(self):
        with mock.patch(
            "integrations.supplier_aggregator._provider_configured",
            return_value=True,
        ), mock.patch(
            "integrations.supplier_aggregator.search_digikey_substitutions",
            side_effect=RuntimeError("DigiKey timed out"),
        ), mock.patch(
            "integrations.supplier_aggregator.search_digikey_catalog_candidates",
            side_effect=RuntimeError("DigiKey timed out"),
        ), mock.patch(
            "integrations.supplier_aggregator.search_mouser_catalog_candidates",
            return_value=[],
        ), mock.patch(
            "integrations.supplier_aggregator.search_newark_catalog_candidates",
            return_value=[],
        ):
            discovery = discover_alternative_candidates("AM29F010B-70EC")

        self.assertTrue(discovery["has_incomplete_evidence"])
        self.assertIn("DigiKey", discovery["provider_failures"])
        self.assertEqual(discovery["candidates"], [])
        # Empty/failed discovery must never be narrated as "no alternative".
        blob = str(discovery).casefold()
        self.assertNotIn("compatible", blob)
        self.assertNotIn("no alternative exists", blob)

    def test_family_partition_keeps_buckets_distinct(self):
        original = {
            "manufacturer_part_number": "AM29F010B-70EC",
            "manufacturer": "AMD",
            "description": "1 Megabit Flash Memory",
            "primary_category": "Memory|Flash",
        }
        candidates = [
            {
                "mpn": "AM29F010B-90EC",
                "manufacturer": "AMD",
                "description": "1 Megabit Flash Memory",
                "primary_category": "Memory|Flash",
                "fit": "not qualified",
            },
            {
                "mpn": "UNKNOWN-LEAD",
                "manufacturer": "Generic",
                "description": "Catalog keyword hit",
                "fit": "not qualified — component family not classified from available evidence",
            },
            {
                "mpn": "LM358DR",
                "manufacturer": "Texas Instruments",
                "description": "Dual operational amplifier",
                "primary_category": "Integrated Circuits|Linear|Amplifiers",
                "architecture": "Operational Amplifier",
                "fit": "not qualified — different component family",
            },
        ]
        relevant, unclassified, unfiltered = partition_candidates_by_family(
            original, candidates
        )
        relevant_mpns = {row["mpn"] for row in relevant}
        unclassified_mpns = {row["mpn"] for row in unclassified}
        unfiltered_mpns = {row["mpn"] for row in unfiltered}
        # Buckets must not overlap and must not label discovery leads Compatible.
        self.assertFalse(relevant_mpns & unclassified_mpns)
        self.assertFalse(relevant_mpns & unfiltered_mpns)
        self.assertFalse(unclassified_mpns & unfiltered_mpns)
        for row in relevant + unclassified + unfiltered:
            fit = str(row.get("fit") or "").casefold()
            self.assertNotIn("compatible", fit)


class Lm358DrComparisonClassificationTests(unittest.TestCase):
    def test_catalog_package_and_pin_count_are_listing_agreement_not_compatible(self):
        original = {
            "manufacturer_part_number": "LM358DR",
            "manufacturer": "Texas Instruments",
            "description": "Dual operational amplifier",
            "architecture": "Operational Amplifier",
            "package": "8-SOIC",
            "pin_count": 8,
            "mounting_style": "Surface Mount",
            "lifecycle_status": "Active",
            "source": "DigiKey",
            "supplier_data_verified": True,
        }
        candidate = {
            "manufacturer_part_number": "LM358DR2G",
            "manufacturer": "onsemi",
            "description": "Dual operational amplifier",
            "architecture": "Operational Amplifier",
            "package": "8-SOIC",
            "pin_count": 8,
            "mounting_style": "Surface Mount",
            "lifecycle_status": "Active",
            "source": "Mouser",
            "supplier_data_verified": True,
        }
        comparison = build_datasheet_comparison(original, candidate)
        by_attr = {row["Attribute"]: row for row in comparison["rows"]}
        self.assertEqual(by_attr["Package"]["Status"], "Listing agreement")
        self.assertEqual(by_attr["Pin count"]["Status"], "Listing agreement")
        self.assertEqual(
            map_status_to_assessment(by_attr["Package"]["Status"]),
            FINDING_LISTING_AGREEMENT,
        )
        self.assertNotEqual(
            map_status_to_assessment(by_attr["Package"]["Status"]),
            FINDING_COMPATIBLE,
        )

        counts = comparison["counts"]
        # Package / pin listing agreement must not inflate Compatible Match KPIs.
        self.assertGreaterEqual(int(counts.get("Listing agreement") or 0), 2)
        self.assertNotEqual(by_attr["Package"]["Status"], "Match")
        self.assertNotEqual(by_attr["Pin count"]["Status"], "Match")
        scored = engineering_confidence_from_rows(comparison["rows"])
        self.assertGreaterEqual(scored["listing_agreements"], 2)
        # Listing agreement alone must not create an engineering-ready band.
        self.assertLess(scored["engineering_comparison_confidence"], 75)

    def test_unknown_value_class_numeric_typical_field_needs_data(self):
        from src.component_family_profiles import FieldSpec, COMPARE_NOMINAL
        from src.parametric_compare import compare_field_values

        spec = FieldSpec(
            key="input_bias_na",
            label="Input bias",
            compare=COMPARE_NOMINAL,
            unit="nA",
            value_role="typical",
        )
        status, note = compare_field_values("20", "20", spec)
        self.assertEqual(status, "Needs data")
        self.assertIn("class", note.casefold())


class ProviderEmptyResultTests(unittest.TestCase):
    def test_part_not_found_clears_borrowed_identity(self):
        result = _safe_supplier_lookup(
            "DigiKey",
            lambda _query: {
                "manufacturer_part_number": "AM29F010B",
                "stock_total": 40,
                "lifecycle_status": "Active",
            },
            "AM29F010B70EC",
        )
        self.assertEqual(result["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertIsNone(result["stock_total"])


if __name__ == "__main__":
    unittest.main()
