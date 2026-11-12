"""Focused Find Replacement outcome wording + raw-vs-retained catalog counts."""
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
                "fit": "compatible",
            }
        ]
        self.assertEqual(
            search_outcome_label(OUTCOME_SUCCESS, candidates=candidates),
            LABEL_VERIFIED_REPLACEMENTS,
        )

    def test_candidates_found_token_follows_fit_evidence(self):
        unverified = [{"classification": "Needs verification", "fit": "not qualified"}]
        self.assertEqual(
            search_outcome_label("candidates_found", candidates=unverified),
            LABEL_SUPPLIER_LISTED_FIT_UNVERIFIED,
        )
        verified = [{"classification": "Compatible"}]
        self.assertEqual(
            search_outcome_label("candidates_found", candidates=verified),
            LABEL_VERIFIED_REPLACEMENTS,
        )

    def test_catalog_only_never_labeled_compatible_in_matrix(self):
        from apps.api.manufacturer_identity import manufacturers_match

        # Guard: lineage match must not invent Compatible classification.
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
                row.get("Classification") or row.get("Category") or row.get("classification") or ""
            )
            self.assertNotEqual(classification.casefold(), "compatible")


class Am29RawVersusRetainedCountTests(unittest.TestCase):
    """AM29-style: provider raw hit count stays distinct from retained leads."""

    def setUp(self):
        install_streamlit_cache_stub()
        import integrations.supplier_aggregator as aggregator

        self.aggregator = aggregator

    def test_mouser_raw_count_preserved_when_most_filtered(self):
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
        self.assertEqual(int(mouser.get("catalog_count") or 0), 19)
        retained = int(mouser.get("catalog_retained_count") or 0)
        self.assertLess(retained, 19)
        self.assertGreaterEqual(retained, 1)
        self.assertEqual(int(discovery.get("catalog_raw_count") or 0), 19)
        self.assertLessEqual(
            int(discovery.get("catalog_retained_count") or 0), retained
        )
        summary = str(discovery.get("catalog_filter_summary") or "")
        self.assertIn("raw catalog matches", summary.casefold())
        # Do not surface filtered TI noise as replacement candidates.
        retained_mpns = {
            str(row.get("manufacturer_part_number") or "")
            for row in discovery.get("candidates") or []
        }
        self.assertTrue(any(mpn.startswith("AM29-LEAD-") for mpn in retained_mpns))
        for row in discovery.get("candidates") or []:
            mfr = str(row.get("manufacturer") or "")
            if mfr:
                self.assertNotEqual(mfr.casefold(), "texas instruments")


if __name__ == "__main__":
    unittest.main()
