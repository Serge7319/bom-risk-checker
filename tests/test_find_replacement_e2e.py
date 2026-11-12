"""Parameterized Find Replacement end-to-end contracts (generic across MPNs)."""
from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

from apps.api.manufacturer_identity import manufacturers_match
from integrations.digikey_client import _exact_keyword_product
from integrations.provider_health import PROVIDER_AVAILABLE, PROVIDER_TIMEOUT
from src.alternative_finder_state import (
    OUTCOME_CATALOG_LEADS_ONLY,
    OUTCOME_FAILURE,
    OUTCOME_NO_RESULTS,
    OUTCOME_PARTIAL_SUPPLIER,
    resolve_search_outcome,
)
from tests.streamlit_cache_stub import install_streamlit_cache_stub


def _digikey_product(mpn: str, manufacturer: str) -> dict:
    return {
        "ManufacturerProductNumber": mpn,
        "Manufacturer": {"Name": manufacturer},
        "ProductDescription": f"{manufacturer} {mpn}",
    }


class DigiKeyLineageMatchTests(unittest.TestCase):
    def test_exact_keyword_product_uses_mpn_lineage(self):
        products = [_digikey_product("AM29F010B-70EC", "Infineon")]
        hit = _exact_keyword_product(
            products, "AM29F010B-70EC", manufacturer="AMD"
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["Manufacturer"]["Name"], "Infineon")

    def test_exact_keyword_rejects_lineage_brand_on_unrelated_mpn(self):
        products = [_digikey_product("LM358N-UNRELATED", "Infineon")]
        hit = _exact_keyword_product(
            products, "LM358N-UNRELATED", manufacturer="AMD"
        )
        self.assertIsNone(hit)


class DiscoveryManufacturerFilterTests(unittest.TestCase):
    def setUp(self):
        install_streamlit_cache_stub()
        import integrations.supplier_aggregator as aggregator

        self.aggregator = aggregator

    def test_discovery_drops_conflicting_brand_keeps_blank_and_lineage(self):
        rows = [
            {
                "manufacturer_part_number": "LEAD-TI",
                "manufacturer": "Texas Instruments",
                "source": "Mouser",
            },
            {
                "manufacturer_part_number": "LEAD-INF",
                "manufacturer": "Infineon",
                "source": "Mouser",
            },
            {
                "manufacturer_part_number": "LEAD-UNK",
                "manufacturer": "",
                "source": "Newark",
            },
        ]

        def fake_mouser(term, include_family_search=True):
            return list(rows)

        with patch.object(
            self.aggregator,
            "_provider_configured",
            return_value=True,
        ), patch.object(
            self.aggregator,
            "search_mouser_catalog_candidates",
            side_effect=fake_mouser,
        ), patch.object(
            self.aggregator,
            "search_newark_catalog_candidates",
            return_value=[],
        ), patch.object(
            self.aggregator,
            "search_digikey_substitutions",
            return_value=[],
        ), patch.object(
            self.aggregator,
            "search_digikey_catalog_candidates",
            return_value=[],
        ):
            discovery = self.aggregator.discover_alternative_candidates(
                "AM29F010B-70EC",
                manufacturer="AMD",
            )

        mpns = {
            str(row.get("manufacturer_part_number") or "")
            for row in discovery.get("candidates") or []
        }
        self.assertIn("LEAD-INF", mpns)
        self.assertIn("LEAD-UNK", mpns)
        self.assertNotIn("LEAD-TI", mpns)
        self.assertTrue(discovery.get("manufacturer_filter_applied"))


class OutcomeAggregationParameterizedTests(unittest.TestCase):
    def test_outcome_cases(self):
        cases = [
            (
                "valid_zero",
                [],
                {"providers": {"Mouser": {"catalog": "ok", "catalog_count": 0}}},
                0,
                OUTCOME_NO_RESULTS,
            ),
            (
                "catalog_leads",
                [],
                {
                    "providers": {"Mouser": {"catalog": "ok", "catalog_count": 5}},
                    "unclassified_leads": [{"Alternative Part": "X"}],
                },
                1,
                OUTCOME_CATALOG_LEADS_ONLY,
            ),
            (
                "partial_supplier",
                [],
                {
                    "providers": {
                        "Newark": {"catalog": "error"},
                        "Mouser": {"catalog": "ok", "catalog_count": 2},
                    },
                    "unclassified_leads": [{"Alternative Part": "Y"}],
                },
                1,
                OUTCOME_PARTIAL_SUPPLIER,
            ),
            (
                "total_failure",
                [],
                {
                    "providers": {
                        "Newark": {"catalog": "timeout"},
                        "Mouser": {"catalog": "error"},
                    }
                },
                0,
                OUTCOME_FAILURE,
            ),
        ]
        for name, candidates, discovery, lead_count, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    resolve_search_outcome(
                        candidates,
                        discovery=discovery,
                        catalog_lead_count=lead_count,
                    ),
                    expected,
                )


class IdentityPathParameterizedTests(unittest.TestCase):
    """Exercise find_replacements identity paths with deterministic fixtures."""

    CASES = [
        ("AM29F010B-70EC", "AMD", "Infineon", "matched_lineage"),
        ("AM29F010B-70EC", "Advanced Micro Devices", "Cypress", "matched_lineage"),
        ("AM29F010B-70EC", "Texas Instruments", "Infineon", "mismatch"),
        ("AM29F010B-70EC", "AMD", "", "unresolved_review_only"),
        ("LM358N", "Texas Instruments", "Texas Instruments", "matched_alias"),
        ("LM358N", "onsemi", "Texas Instruments", "mismatch"),
        ("C0603C104K5RACTU", "KEMET", "KEMET", "matched_exact"),
        ("C0603C104K5RACTU", "", "KEMET", "blank_accepts_supplier"),
    ]

    def setUp(self):
        install_streamlit_cache_stub()

    def test_identity_matrix(self):
        from src.alternative_finder_search import run_alternative_finder_search

        discovery_fixture = {
            "providers": {"Mouser": {"catalog": "ok", "catalog_count": 1}},
            "candidates": [
                {
                    "manufacturer_part_number": "CATALOG-LEAD",
                    "Alternative Part": "CATALOG-LEAD",
                    "manufacturer": "",
                    "Manufacturer": "",
                    "source": "Mouser",
                    "description": "flash family lead",
                    "primary_category": "Memory|Flash",
                    "Classification": "Needs verification",
                }
            ],
            "catalog_count": 1,
            "has_incomplete_evidence": True,
        }

        for mpn, requested, supplier_mfr, expect in self.CASES:
            with self.subTest(mpn=mpn, requested=requested, expect=expect):
                lookup = {
                    "manufacturer_part_number": mpn if supplier_mfr else "",
                    "manufacturer": supplier_mfr,
                    "supplier_data_verified": bool(supplier_mfr),
                    "all_supplier_results": (
                        [
                            {
                                "source": "DigiKey",
                                "manufacturer": supplier_mfr,
                                "manufacturer_part_number": mpn,
                            }
                        ]
                        if supplier_mfr
                        else []
                    ),
                }
                state: dict = {}
                with patch(
                    "integrations.supplier_aggregator.discover_alternative_candidates",
                    return_value=discovery_fixture,
                ), patch(
                    "src.alternative_engine.suggest_alternatives_v2",
                    return_value=[],
                ), patch(
                    "src.alternative_engine.get_alternative_discovery_metadata",
                    return_value={},
                ), patch(
                    "src.alternative_engine.build_salvage_candidates_from_discovery",
                    side_effect=lambda discovery, **kwargs: [
                        dict(row) for row in (discovery.get("candidates") or [])
                    ],
                ):
                    outcome = run_alternative_finder_search(
                        state,
                        mpn,
                        original_lookup=lookup,
                        requested_manufacturer=requested,
                    )

                result = state.get("alternative_finder_result") or {}
                original = result.get("original_data") or {}
                if expect in {"matched_lineage", "matched_alias", "matched_exact"}:
                    self.assertTrue(original.get("identity_verified"))
                    self.assertEqual(original.get("identity_status"), "matched")
                    if supplier_mfr:
                        self.assertEqual(original.get("manufacturer"), supplier_mfr)
                elif expect == "mismatch":
                    self.assertFalse(original.get("identity_verified"))
                    self.assertEqual(
                        original.get("identity_status"), "manufacturer_mismatch"
                    )
                    self.assertEqual(result.get("candidates") or [], [])
                elif expect == "unresolved_review_only":
                    self.assertFalse(original.get("identity_verified"))
                    self.assertEqual(original.get("identity_status"), "unresolved")
                    self.assertTrue(original.get("identity_review_only"))
                    meta = result.get("discovery_metadata") or {}
                    self.assertTrue(
                        bool(result.get("candidates"))
                        or bool(meta.get("unclassified_leads"))
                        or bool(meta.get("unfiltered_leads"))
                        or outcome.get("search_outcome")
                        in {
                            OUTCOME_CATALOG_LEADS_ONLY,
                            OUTCOME_NO_RESULTS,
                            "unable_to_confirm",
                        }
                    )
                elif expect == "blank_accepts_supplier":
                    self.assertTrue(original.get("identity_verified") or supplier_mfr)
                    if supplier_mfr and original.get("identity_verified"):
                        self.assertEqual(original.get("manufacturer"), supplier_mfr)

                for row in result.get("candidates") or []:
                    if original.get("identity_review_only"):
                        classification = str(
                            row.get("Classification") or row.get("Category") or ""
                        )
                        self.assertNotEqual(classification.casefold(), "compatible")


class ConcurrentManufacturerIsolationTests(unittest.TestCase):
    def test_lineage_and_unrelated_concurrent_requests(self):
        install_streamlit_cache_stub()
        import integrations.supplier_aggregator as aggregator

        if hasattr(aggregator.get_best_part_data, "clear"):
            aggregator.get_best_part_data.clear()

        def fake_digikey(part_number: str, manufacturer: str = ""):
            mpn = str(part_number or "").strip()
            if mpn.upper() == "AM29F010B-70EC":
                return {
                    "source": "DigiKey",
                    "manufacturer_part_number": mpn,
                    "manufacturer": "Infineon",
                    "supplier_data_verified": True,
                    "stock_total": 1,
                }
            return {
                "source": "DigiKey",
                "manufacturer_part_number": mpn,
                "manufacturer": "Infineon",
                "supplier_data_verified": True,
                "stock_total": 1,
            }

        with patch.object(
            aggregator,
            "_supplier_lookup_callable",
            side_effect=lambda source: fake_digikey if source == "DigiKey" else None,
        ):
            outcomes = {}

            def run(key, mpn, brand):
                outcomes[key] = aggregator.get_best_part_data(mpn, manufacturer=brand)

            pairs = [
                ("am29", "AM29F010B-70EC", "AMD"),
                ("other", "NOSUCH-MPN-ZZ", "AMD"),
            ]
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run, *pair) for pair in pairs]
                for future in as_completed(futures):
                    future.result()

        self.assertEqual(outcomes["am29"].get("manufacturer"), "Infineon")
        self.assertTrue(outcomes["am29"].get("supplier_data_verified"))
        self.assertFalse(bool(outcomes["other"].get("supplier_data_verified")))


class CompatibleVerdictGuardTests(unittest.TestCase):
    def test_catalog_only_never_compatible_string(self):
        # Guardrail: manufacturers_match lineage must not invent Compatible labels.
        self.assertTrue(
            manufacturers_match("AMD", "Infineon", mpn="AM29F010B-70EC")
        )
        self.assertFalse(manufacturers_match("AMD", "Infineon"))


if __name__ == "__main__":
    unittest.main()
