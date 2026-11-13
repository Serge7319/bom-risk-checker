"""Focused Find Replacement outcome wording + catalog vs explicit count contract."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.alternative_finder_state import (
    LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
    LABEL_VERIFIED_REPLACEMENTS,
    OUTCOME_SUCCESS,
    resolve_search_outcome,
    search_outcome_label,
)
from tests.streamlit_cache_stub import install_streamlit_cache_stub


class OutcomeWordingLm358Tests(unittest.TestCase):
    """LM358N-style: candidates exist but none are Compatible → no 'Verified' banner."""

    def test_success_without_compatible_is_fit_unverified(self):
        candidates = [
            {
                "Alternative Part": f"LM358N-ALT-{idx}",
                "Manufacturer": "Texas Instruments",
                "Classification": "Needs verification",
                "fit": "supplier-listed candidate; qualification required",
            }
            for idx in range(10)
        ]
        outcome = resolve_search_outcome(
            candidates,
            discovery={"providers": {"DigiKey": {"substitutions": "ok"}}},
        )
        self.assertEqual(outcome, OUTCOME_SUCCESS)
        self.assertEqual(
            search_outcome_label(outcome, candidates=candidates),
            LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
        )
        self.assertNotIn("Verified", search_outcome_label(outcome, candidates=candidates))

    def test_compatible_candidate_keeps_verified_wording(self):
        candidates = [
            {
                "Alternative Part": "LM358P",
                "Classification": "Compatible",
                "fit": "compatible — datasheet-backed",
                "evidence_class": "manufacturer-datasheet",
                "authoritative_fit_evidence": True,
            }
        ]
        self.assertEqual(
            search_outcome_label(OUTCOME_SUCCESS, candidates=candidates),
            LABEL_VERIFIED_REPLACEMENTS,
        )

    def test_compatible_without_authoritative_evidence_is_fit_unverified(self):
        candidates = [
            {
                "Alternative Part": "LM358P",
                "Classification": "Compatible",
                "fit": "compatible",
            }
        ]
        self.assertEqual(
            search_outcome_label(OUTCOME_SUCCESS, candidates=candidates),
            LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
        )

    def test_compatible_with_qualification_required_is_fit_unverified(self):
        candidates = [
            {
                "Alternative Part": "LM358ADR2G",
                "Classification": "Compatible",
                "fit": "supplier-listed candidate; qualification required",
            }
        ]
        self.assertEqual(
            search_outcome_label(OUTCOME_SUCCESS, candidates=candidates),
            LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
        )

    def test_candidates_found_token_follows_fit_evidence(self):
        unverified = [{"classification": "Needs verification", "fit": "not qualified"}]
        self.assertEqual(
            search_outcome_label("candidates_found", candidates=unverified),
            LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
        )
        classification_only = [{"classification": "Compatible"}]
        self.assertEqual(
            search_outcome_label("candidates_found", candidates=classification_only),
            LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
        )
        verified = [{
            "classification": "Compatible",
            "authoritative_fit_evidence": True,
            "evidence_class": "manufacturer-datasheet",
        }]
        self.assertEqual(
            search_outcome_label("candidates_found", candidates=verified),
            LABEL_VERIFIED_REPLACEMENTS,
        )

    def test_catalog_only_never_labeled_compatible_in_matrix(self):
        from apps.api.manufacturer_identity import manufacturers_match

        self.assertTrue(
            manufacturers_match("AMD", "Infineon", mpn="AM29F010B-70EC")
        )
        rows = [
            {
                "Alternative Part": "AM29-LEAD",
                "Classification": "Needs verification",
                "Category": "Needs verification",
            },
            {
                "mpn": "UNK-LEAD",
                "classification": "Unverified candidate",
                "fit": "not qualified — component family not classified from available evidence",
            },
        ]
        for row in rows:
            classification = str(
                row.get("Classification")
                or row.get("Category")
                or row.get("classification")
                or ""
            )
            self.assertNotEqual(classification.casefold(), "compatible")


class CatalogVersusExplicitCountTests(unittest.TestCase):
    """catalog_* counts are catalog-only; explicit_* stay separate."""

    def setUp(self):
        install_streamlit_cache_stub()
        import integrations.supplier_aggregator as aggregator

        self.aggregator = aggregator

    def test_nineteen_raw_eighteen_filtered_one_retained(self):
        raw_rows = []
        for idx in range(19):
            brand = "Texas Instruments" if idx < 18 else "Infineon"
            raw_rows.append(
                {
                    "manufacturer_part_number": f"AM29-LEAD-{idx}",
                    "manufacturer": brand,
                    "source": "Mouser",
                    "description": "flash lead",
                    "primary_category": "Memory|Flash" if brand == "Infineon" else "Amplifiers",
                }
            )

        with patch.object(
            self.aggregator, "_provider_configured", return_value=True
        ), patch.object(
            self.aggregator,
            "search_mouser_catalog_candidates",
            return_value=list(raw_rows),
        ), patch.object(
            self.aggregator, "search_newark_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator, "search_digikey_substitutions", return_value=[]
        ), patch.object(
            self.aggregator, "search_digikey_catalog_candidates", return_value=[]
        ):
            discovery = self.aggregator.discover_alternative_candidates(
                "AM29F010B-70EC",
                manufacturer="AMD",
            )

        mouser = (discovery.get("providers") or {}).get("Mouser") or {}
        self.assertEqual(int(mouser.get("catalog_raw_count") or 0), 19)
        self.assertEqual(int(mouser.get("catalog_retained_count") or 0), 1)
        self.assertEqual(int(discovery.get("catalog_raw_count") or 0), 19)
        self.assertEqual(int(discovery.get("catalog_retained_count") or 0), 1)
        self.assertEqual(int(discovery.get("manufacturer_filtered_count") or 0), 18)
        self.assertEqual(int(discovery.get("explicit_raw_count") or 0), 0)
        self.assertEqual(int(discovery.get("explicit_retained_count") or 0), 0)
        summary = str(discovery.get("catalog_filter_summary") or "").casefold()
        self.assertIn("19 raw catalog matches", summary)
        self.assertIn("1 retained", summary)
        self.assertNotIn("supplier substitution", summary)

    def test_zero_catalog_two_explicit_never_counts_as_catalog(self):
        explicit = [
            {
                "manufacturer_part_number": "SUB-A",
                "manufacturer": "Texas Instruments",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
            },
            {
                "manufacturer_part_number": "SUB-B",
                "manufacturer": "Texas Instruments",
                "source": "DigiKey",
                "substitute_type": "Similar",
                "evidence_type": "Distributor-listed substitute",
            },
        ]

        with patch.object(
            self.aggregator, "_provider_configured", return_value=True
        ), patch.object(
            self.aggregator, "search_mouser_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator, "search_newark_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator, "search_digikey_substitutions", return_value=list(explicit)
        ), patch.object(
            self.aggregator, "search_digikey_catalog_candidates", return_value=[]
        ):
            discovery = self.aggregator.discover_alternative_candidates(
                "LM358N",
                manufacturer="Texas Instruments",
            )

        digikey = (discovery.get("providers") or {}).get("DigiKey") or {}
        self.assertEqual(int(digikey.get("catalog_raw_count") or 0), 0)
        self.assertEqual(int(digikey.get("catalog_retained_count") or 0), 0)
        self.assertEqual(int(digikey.get("explicit_raw_count") or 0), 2)
        self.assertEqual(int(digikey.get("explicit_retained_count") or 0), 2)
        self.assertEqual(int(discovery.get("catalog_raw_count") or 0), 0)
        self.assertEqual(int(discovery.get("catalog_retained_count") or 0), 0)
        self.assertEqual(int(discovery.get("explicit_retained_count") or 0), 2)
        summary = str(discovery.get("catalog_filter_summary") or "").casefold()
        self.assertNotIn("raw catalog matches", summary)
        channels = {
            str(row.get("discovery_channel") or "")
            for row in discovery.get("candidates") or []
        }
        self.assertEqual(channels, {"explicit"})

    def test_mixed_explicit_and_catalog_with_duplicate_mpn(self):
        explicit = [
            {
                "manufacturer_part_number": "SHARED-MPN",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
            },
            {
                "manufacturer_part_number": "EXPLICIT-ONLY",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "substitute_type": "Upgrade",
                "evidence_type": "Distributor-listed substitute",
            },
        ]
        catalog = [
            {
                "manufacturer_part_number": "SHARED-MPN",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "description": "catalog duplicate of explicit",
                "evidence_type": "Distributor catalog match",
                "discovery_scope": "family_search",
            },
            {
                "manufacturer_part_number": "CATALOG-ONLY",
                "manufacturer": "KEMET",
                "source": "Mouser",
                "description": "catalog lead",
                "evidence_type": "Distributor catalog match",
                "discovery_scope": "family_search",
            },
            {
                "manufacturer_part_number": "CATALOG-ONLY",
                "manufacturer": "KEMET",
                "source": "Mouser",
                "description": "duplicate catalog MPN",
                "evidence_type": "Distributor catalog match",
                "discovery_scope": "family_search",
            },
        ]

        with patch.object(
            self.aggregator, "_provider_configured", return_value=True
        ), patch.object(
            self.aggregator,
            "search_mouser_catalog_candidates",
            return_value=[row for row in catalog if row["source"] == "Mouser"],
        ), patch.object(
            self.aggregator, "search_newark_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator, "search_digikey_substitutions", return_value=list(explicit)
        ), patch.object(
            self.aggregator,
            "search_digikey_catalog_candidates",
            return_value=[row for row in catalog if row["source"] == "DigiKey"],
        ):
            discovery = self.aggregator.discover_alternative_candidates(
                "C0603C104K5RACTU",
                manufacturer="KEMET",
            )

        # DigiKey: 1 raw catalog (SHARED absorbed into explicit) + 2 explicit.
        digikey = (discovery.get("providers") or {}).get("DigiKey") or {}
        self.assertEqual(int(digikey.get("catalog_raw_count") or 0), 1)
        self.assertEqual(int(digikey.get("explicit_raw_count") or 0), 2)
        self.assertEqual(int(digikey.get("explicit_retained_count") or 0), 2)
        # SHARED-MPN stays explicit after merge; DigiKey catalog retained is 0.
        self.assertEqual(int(digikey.get("catalog_retained_count") or 0), 0)

        mouser = (discovery.get("providers") or {}).get("Mouser") or {}
        self.assertEqual(int(mouser.get("catalog_raw_count") or 0), 2)
        self.assertEqual(int(mouser.get("catalog_retained_count") or 0), 1)

        self.assertEqual(int(discovery.get("catalog_raw_count") or 0), 3)
        self.assertEqual(int(discovery.get("catalog_retained_count") or 0), 1)
        self.assertEqual(int(discovery.get("explicit_retained_count") or 0), 2)

        by_channel: dict[str, set[str]] = {"catalog": set(), "explicit": set()}
        for row in discovery.get("candidates") or []:
            channel = str(row.get("discovery_channel") or "")
            mpn = str(row.get("manufacturer_part_number") or "")
            by_channel.setdefault(channel, set()).add(mpn)
        self.assertIn("SHARED-MPN", by_channel["explicit"])
        self.assertIn("EXPLICIT-ONLY", by_channel["explicit"])
        self.assertIn("CATALOG-ONLY", by_channel["catalog"])
        self.assertNotIn("SHARED-MPN", by_channel["catalog"])
        summary = str(discovery.get("catalog_filter_summary") or "").casefold()
        self.assertIn("raw catalog matches", summary)
        self.assertIn("retained", summary)


if __name__ == "__main__":
    unittest.main()
