"""Regressions for post-deploy smoke follow-up (manufacturer identity, compare
honesty, supply-risk scope, compare timeout messaging).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from apps.api.manufacturer_identity import (
    identity_ambiguity_payload,
    manufacturers_match,
    multi_brand_choices_for_mpn,
    select_manufacturer_choice,
)
from apps.api.migration_tools import find_replacement_payload, supply_risk_payload
from src.parts_compare import (
    FINDING_COMPATIBLE,
    FINDING_LISTING_AGREEMENT,
    FINDING_NEEDS_VERIFICATION,
    assess_compare_row,
    user_facing_compare_rows,
)


class ManufacturerIdentityTests(unittest.TestCase):
    def test_lm358n_is_dual_source_ti_and_onsemi(self):
        choices = multi_brand_choices_for_mpn("LM358N")
        brands = {row["canonical"] for row in choices}
        self.assertEqual(brands, {"texas instruments", "onsemi"})
        self.assertTrue(any("ti.com" in row.get("product_url", "") for row in choices))
        self.assertTrue(any("onsemi.com" in row.get("product_url", "") for row in choices))

    def test_manufacturer_aliases_match(self):
        self.assertTrue(manufacturers_match("TI", "Texas Instruments"))
        self.assertTrue(manufacturers_match("ON Semiconductor", "onsemi"))
        self.assertFalse(manufacturers_match("Texas Instruments", "onsemi"))

    def test_select_manufacturer_choice_honors_ti(self):
        choice = select_manufacturer_choice("LM358N", "Texas Instruments")
        self.assertIsNotNone(choice)
        self.assertEqual(choice["canonical"], "texas instruments")

    def test_find_replacement_requires_manufacturer_for_lm358n(self):
        payload = find_replacement_payload(workspace_id="ws-test", mpn="LM358N")
        self.assertEqual(payload.get("status"), "identity_ambiguous")
        self.assertEqual(payload.get("identity_status"), "ambiguous")
        self.assertEqual(payload.get("candidates"), [])
        self.assertGreaterEqual(len(payload.get("identity_choices") or []), 2)

    def test_find_replacement_ti_mismatch_does_not_wash_to_onsemi(self):
        fake = {
            "original": {
                "mpn": "LM358N",
                "manufacturer": "onsemi",
                "description": "Op amp",
            },
            "candidates": [{"mpn": "FAKE-ALT"}],
            "search_outcome": "candidates_found",
        }
        with patch(
            "apps.api.legacy_supplier_workflow.production_analysis_enabled",
            return_value=True,
        ), patch(
            "apps.api.legacy_supplier_workflow.find_replacements",
            return_value=fake,
        ):
            payload = find_replacement_payload(
                workspace_id="ws-test",
                mpn="LM358N",
                manufacturer="Texas Instruments",
            )
        self.assertEqual(payload.get("status"), "identity_ambiguous")
        self.assertEqual(payload.get("requested_manufacturer"), "Texas Instruments")
        self.assertEqual(payload.get("resolved_manufacturer"), "onsemi")
        self.assertEqual(payload.get("candidates"), [])
        # Must not present onsemi as the original identity.
        original = payload.get("original") or {}
        self.assertNotEqual(
            str(original.get("manufacturer") or "").casefold(),
            "onsemi",
        )

    def test_successful_ti_and_onsemi_selections_match_identity(self):
        for brand in ("Texas Instruments", "onsemi"):
            fake = {
                "original": {
                    "mpn": "LM358N",
                    "manufacturer": brand,
                    "identity_status": "matched",
                    "identity_verified": True,
                    "description": "Op amp",
                },
                "candidates": [{"mpn": f"{brand}-ALT"}],
                "search_outcome": "candidates_found",
            }
            with patch(
                "apps.api.legacy_supplier_workflow.production_analysis_enabled",
                return_value=True,
            ), patch(
                "apps.api.legacy_supplier_workflow.find_replacements",
                return_value=fake,
            ) as mocked:
                payload = find_replacement_payload(
                    workspace_id="ws-test",
                    mpn="LM358N",
                    manufacturer=brand,
                )
            mocked.assert_called_once()
            called_mfr = mocked.call_args.kwargs.get("manufacturer")
            if called_mfr is None and len(mocked.call_args.args) > 1:
                called_mfr = mocked.call_args.args[1]
            self.assertEqual(called_mfr, brand)
            self.assertNotEqual(payload.get("status"), "identity_ambiguous")
            self.assertEqual(
                str((payload.get("original") or {}).get("manufacturer") or ""),
                brand,
            )
            self.assertTrue(payload.get("candidates"))

    def test_lookup_wrong_brand_clears_candidates_in_workflow(self):
        from apps.api.legacy_supplier_workflow import find_replacements

        with patch(
            "src.alternative_finder_search.run_alternative_finder_search",
            side_effect=lambda state, mpn, **kwargs: state.update(
                {
                    "alternative_finder_result": {
                        "original_data": {
                            "manufacturer_part_number": "LM358N",
                            "manufacturer": "onsemi",
                        },
                        "candidates": [
                            {
                                "Alternative Part": "WRONG-ALT",
                                "Manufacturer": "onsemi",
                                "Classification": "Spec-matched candidate",
                                "Candidate Disposition": "Discovery lead only",
                            }
                        ],
                        "discovery_metadata": {},
                    }
                }
            )
            or {"status": "completed"},
        ):
            result = find_replacements("LM358N", manufacturer="Texas Instruments")
        self.assertEqual(result.get("original", {}).get("identity_status"), "manufacturer_mismatch")
        self.assertEqual(result.get("original", {}).get("manufacturer"), "")
        self.assertEqual(result.get("candidates"), [])
        self.assertEqual(
            result.get("original", {}).get("requested_manufacturer"),
            "Texas Instruments",
        )

    def test_digikey_selector_honors_requested_manufacturer(self):
        from integrations.digikey_client import _select_exact_digikey_product

        products = [
            {
                "ManufacturerProductNumber": "LM358N",
                "Manufacturer": {"Name": "onsemi"},
                "DigiKeyProductNumber": "ON-1",
            },
            {
                "ManufacturerProductNumber": "LM358N",
                "Manufacturer": {"Name": "Texas Instruments"},
                "DigiKeyProductNumber": "TI-1",
            },
        ]
        selected = _select_exact_digikey_product(
            products, "LM358N", manufacturer="Texas Instruments"
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.get("DigiKeyProductNumber"), "TI-1")
        missing = _select_exact_digikey_product(
            products, "LM358N", manufacturer="Analog Devices"
        )
        self.assertIsNone(missing)


class CompareAssessmentHonestyTests(unittest.TestCase):
    def test_catalog_unknown_class_is_needs_verification_not_compatible(self):
        assessment = assess_compare_row(
            status="Match",
            class_a="unknown",
            class_b="unknown",
            condition_a="Not stated",
            condition_b="Not stated",
            source_a="supplier catalog",
            source_b="DigiKey",
        )
        self.assertEqual(assessment, FINDING_NEEDS_VERIFICATION)
        self.assertNotEqual(assessment, FINDING_COMPATIBLE)

    def test_catalog_agreement_label_is_fit_unverified(self):
        assessment = assess_compare_row(
            status="Listing agreement",
            class_a="typical",
            class_b="typical",
            condition_a="@ 25C",
            condition_b="@ 25C",
            source_a="supplier catalog",
            source_b="Mouser",
        )
        self.assertEqual(assessment, FINDING_LISTING_AGREEMENT)
        self.assertIn("fit unverified", assessment.casefold())
        self.assertNotEqual(assessment, FINDING_COMPATIBLE)

    def test_user_facing_rows_demote_catalog_match(self):
        unknown_rows = user_facing_compare_rows(
            [
                {
                    "Attribute": "Input bias",
                    "Original": "20 nA",
                    "Candidate": "20 nA",
                    "Status": "Match",
                    "Part A source": "supplier catalog",
                    "Part B source": "supplier catalog",
                    "Part A value class": "unknown",
                    "Part B value class": "unknown",
                    "Part A test condition": "Not stated",
                    "Part B test condition": "Not stated",
                    "Evidence": "Supplier listings agree",
                }
            ]
        )
        self.assertEqual(unknown_rows[0]["Assessment"], FINDING_NEEDS_VERIFICATION)
        self.assertNotEqual(unknown_rows[0]["Assessment"], FINDING_COMPATIBLE)

        known_catalog_rows = user_facing_compare_rows(
            [
                {
                    "Attribute": "Input bias",
                    "Original": "20 nA (typ) @ 25C",
                    "Candidate": "20 nA (typ) @ 25C",
                    "Status": "Match",
                    "Part A source": "supplier catalog",
                    "Part B source": "supplier catalog",
                    "Part A value class": "typical",
                    "Part B value class": "typical",
                    "Part A test condition": "@ 25C",
                    "Part B test condition": "@ 25C",
                    "Evidence": "Supplier listings agree",
                }
            ]
        )
        self.assertEqual(known_catalog_rows[0]["Assessment"], FINDING_LISTING_AGREEMENT)
        self.assertNotEqual(known_catalog_rows[0]["Assessment"], FINDING_COMPATIBLE)

    def test_known_classes_with_missing_sources_are_not_compatible(self):
        assessment = assess_compare_row(
            status="Match",
            class_a="typical",
            class_b="typical",
            condition_a="@ 25C",
            condition_b="@ 25C",
            source_a="",
            source_b="",
        )
        self.assertEqual(assessment, FINDING_NEEDS_VERIFICATION)
        self.assertNotEqual(assessment, FINDING_COMPATIBLE)
        rows = user_facing_compare_rows(
            [
                {
                    "Attribute": "Input bias",
                    "Original": "20 nA (typ) @ 25C",
                    "Candidate": "20 nA (typ) @ 25C",
                    "Status": "Match",
                    "Part A source": "",
                    "Part B source": "",
                    "Part A value class": "typical",
                    "Part B value class": "typical",
                    "Part A test condition": "@ 25C",
                    "Part B test condition": "@ 25C",
                    "Evidence": "Values match",
                }
            ]
        )
        self.assertEqual(rows[0]["Assessment"], FINDING_NEEDS_VERIFICATION)
        self.assertNotEqual(rows[0]["Assessment"], FINDING_COMPATIBLE)


class SupplyRiskScopeTests(unittest.TestCase):
    def test_analysis_scope_stays_on_selected_bom(self):
        analyses = [
            {"id": "nested-7", "project_name": "Nested BOM", "filename": "nested.csv"},
            {"id": "flat-9", "project_name": "Flat BOM", "filename": "flat.csv"},
        ]
        parts = [
            {"analysis_id": "nested-7", "mpn": f"N{i}", "quantity": 1, "stock_available": 10}
            for i in range(7)
        ] + [
            {"analysis_id": "flat-9", "mpn": f"F{i}", "quantity": 1, "stock_available": 10}
            for i in range(9)
        ]
        with patch(
            "apps.api.migration_tools.analyses_and_parts",
            return_value=(analyses, parts),
        ):
            payload = supply_risk_payload(
                workspace_id="ws-test",
                analysis_id="nested-7",
                build_quantity=100,
                stock_reduction_percent=25,
            )
        self.assertEqual(payload.get("scope"), "analysis")
        self.assertEqual(payload.get("analysis_id"), "nested-7")
        self.assertEqual(payload.get("source_part_count"), 7)
        self.assertIn("scoped", str(payload.get("gap") or "").casefold())
        scenario_rows = (payload.get("scenario") or {}).get("rows") or []
        mpns = {str(row.get("Part Number") or "") for row in scenario_rows}
        self.assertTrue(all(mpn.startswith("N") for mpn in mpns if mpn))
        self.assertFalse(any(mpn.startswith("F") for mpn in mpns))

    def test_missing_analysis_id_is_labeled_portfolio_wide(self):
        analyses = [
            {"id": "a1", "project_name": "A", "filename": "a.csv"},
            {"id": "a2", "project_name": "B", "filename": "b.csv"},
        ]
        parts = [
            {"analysis_id": "a1", "mpn": "A1", "quantity": 1, "stock_available": 5},
            {"analysis_id": "a2", "mpn": "B1", "quantity": 1, "stock_available": 5},
        ]
        with patch(
            "apps.api.migration_tools.analyses_and_parts",
            return_value=(analyses, parts),
        ):
            payload = supply_risk_payload(workspace_id="ws-test", analysis_id=None)
        self.assertEqual(payload.get("scope"), "portfolio")
        self.assertIsNone(payload.get("analysis_id"))
        self.assertEqual(payload.get("source_part_count"), 2)
        self.assertIn("portfolio-wide", str(payload.get("gap") or "").casefold())


class AmbiguityPayloadTests(unittest.TestCase):
    def test_ambiguity_payload_has_no_candidates(self):
        payload = identity_ambiguity_payload(
            mpn="LM358N",
            requested_manufacturer="Texas Instruments",
            resolved_manufacturer="onsemi",
        )
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["status"], "identity_ambiguous")
        self.assertIn("Texas Instruments", payload["detail"])
        self.assertIn("onsemi", payload["detail"])


if __name__ == "__main__":
    unittest.main()
