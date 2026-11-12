"""Post-#605 generic follow-up: progress, identity, verdicts, timeouts, supply scope.

Parameterized across MPNs / manufacturers / source types — not a single fixture.
"""
from __future__ import annotations

import re
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch

from apps.api.manufacturer_identity import (
    choices_from_manufacturer_labels,
    clear_multi_brand_evidence,
    distinct_manufacturer_labels,
    identity_ambiguity_payload,
    manufacturers_match,
    multi_brand_choices_for_mpn,
    register_multi_brand_evidence,
    select_manufacturer_choice,
)
from apps.api.migration_tools import find_replacement_payload, supply_risk_payload
from src.component_family_profiles import (
    COMPARE_LIMIT_GE,
    COMPARE_LIMIT_LE,
    COMPARE_NOMINAL,
    FieldSpec,
)
from src.parametric_compare import compare_field_values
from src.parts_compare import (
    FINDING_COMPATIBLE,
    FINDING_LISTING_AGREEMENT,
    FINDING_MATERIAL,
    FINDING_NEEDS_VERIFICATION,
    assess_compare_row,
)

ROOT = Path(__file__).resolve().parents[1]
COMPARE_PAGE = ROOT / "apps/web/src/app/compare-parts/page.tsx"
COMPARE_PROGRESS = ROOT / "apps/web/src/lib/compareProgress.ts"
COMPARE_API = ROOT / "apps/web/src/lib/api.ts"
SUPPLY_PAGE = ROOT / "apps/web/src/app/supply-risk/page.tsx"


class CompareProgressLabelTests(unittest.TestCase):
    def test_progress_shows_baseline_and_candidate_not_current_alone(self):
        page = COMPARE_PAGE.read_text(encoding="utf-8")
        helper = COMPARE_PROGRESS.read_text(encoding="utf-8")
        api = COMPARE_API.read_text(encoding="utf-8")
        self.assertIn("formatCompareProgressLabel", page)
        self.assertIn("baselineMpn", page)
        self.assertIn("candidateMpn", page)
        self.assertNotIn("current ${progress.current}", page)
        self.assertNotRegex(page, r"current \$\{progress\.current\}")
        self.assertIn("design ${baseline}", helper)
        self.assertIn("candidate ${candidate}", helper)
        self.assertIn("COMPARE_PARTS_TIMEOUT_MS = 60_000", api)
        self.assertIn("Promise.allSettled", page)

    def test_multi_candidate_settlement_advances_and_maps_mpns(self):
        """Simulate pairwise settle order; settled count advances; results stay mapped."""
        baseline = "DES-BASE-100"
        candidates = ["ALT-A-10K", "ALT-B-4K7", "ALT-C-22R"]
        slots: list[dict | None] = [None] * len(candidates)
        progress_snapshots: list[tuple[int, str | None]] = []

        def publish():
            completed = sum(1 for row in slots if row is not None)
            pending = next(
                (mpn for mpn, row in zip(candidates, slots) if row is None),
                None,
            )
            progress_snapshots.append((completed, pending))

        publish()  # before any settle
        # Settle out of order: index 1, then 0, then timeout on 2.
        slots[1] = {
            "mpn": candidates[1],
            "finding": "Different",
            "ok": True,
            "part_b": candidates[1],
        }
        publish()
        slots[0] = {
            "mpn": candidates[0],
            "finding": FINDING_LISTING_AGREEMENT,
            "ok": True,
            "part_b": candidates[0],
        }
        publish()
        slots[2] = {
            "mpn": candidates[2],
            "finding": FINDING_NEEDS_VERIFICATION,
            "ok": False,
            "part_b": candidates[2],
            "gap": f"Comparison timed out after 60s for {baseline} vs {candidates[2]}.",
        }
        publish()

        self.assertEqual(
            [completed for completed, _ in progress_snapshots],
            [0, 1, 2, 3],
        )
        by_mpn = {
            candidates[i]: slots[i]
            for i in range(len(candidates))
            if slots[i] is not None
        }
        self.assertEqual(by_mpn[candidates[0]]["finding"], FINDING_LISTING_AGREEMENT)
        self.assertEqual(by_mpn[candidates[1]]["finding"], "Different")
        self.assertEqual(by_mpn[candidates[2]]["finding"], FINDING_NEEDS_VERIFICATION)
        self.assertIn("60s", by_mpn[candidates[2]]["gap"])
        self.assertEqual(by_mpn[candidates[0]]["part_b"], candidates[0])
        self.assertEqual(by_mpn[candidates[1]]["part_b"], candidates[1])

        label_helper = COMPARE_PROGRESS.read_text(encoding="utf-8")
        # Helper must mention both design baseline and candidate being processed.
        self.assertRegex(
            label_helper,
            re.compile(r"design \$\{baseline\}.*candidate \$\{candidate\}", re.S),
        )


class GenericManufacturerIdentityTests(unittest.TestCase):
    def setUp(self):
        clear_multi_brand_evidence()
        register_multi_brand_evidence(
            "AMP-DUAL-1",
            [
                {
                    "manufacturer": "Texas Instruments",
                    "canonical": "texas instruments",
                    "product_url": "https://www.ti.com/product/AMP-DUAL-1",
                    "note": "Official TI AMP-DUAL-1 evidence.",
                },
                {
                    "manufacturer": "onsemi",
                    "canonical": "onsemi",
                    "product_url": "https://www.onsemi.com/products/amp-dual-1",
                    "note": "Official onsemi AMP-DUAL-1 evidence.",
                },
            ],
        )
        register_multi_brand_evidence(
            "REG-DUAL-5V",
            [
                {
                    "manufacturer": "Analog Devices",
                    "product_url": "https://www.analog.com/en/products/reg-dual-5v.html",
                },
                {
                    "manufacturer": "Microchip",
                    "product_url": "https://www.microchip.com/en-us/product/REG-DUAL-5V",
                },
            ],
        )

    def tearDown(self):
        clear_multi_brand_evidence()

    def test_registered_mpns_require_manufacturer_and_show_product_urls(self):
        for mpn in ("AMP-DUAL-1", "REG-DUAL-5V"):
            with self.subTest(mpn=mpn):
                payload = find_replacement_payload(workspace_id="ws-test", mpn=mpn)
                self.assertEqual(payload.get("status"), "identity_ambiguous")
                self.assertEqual(payload.get("candidates"), [])
                choices = payload.get("identity_choices") or []
                self.assertGreaterEqual(len(choices), 2)
                self.assertTrue(all(row.get("product_url") for row in choices))
                original = payload.get("original") or {}
                self.assertEqual(original.get("manufacturer"), "")
                self.assertFalse(bool(original.get("identity_verified")))

    def test_select_and_mismatch_are_generic_across_mpns(self):
        cases = [
            ("AMP-DUAL-1", "Texas Instruments", "onsemi"),
            ("REG-DUAL-5V", "Analog Devices", "Microchip"),
        ]
        for mpn, selected, wrong in cases:
            with self.subTest(mpn=mpn, selected=selected):
                choice = select_manufacturer_choice(mpn, selected)
                self.assertIsNotNone(choice)
                fake = {
                    "original": {
                        "mpn": mpn,
                        "manufacturer": wrong,
                        "description": "part",
                    },
                    "candidates": [{"mpn": f"{mpn}-ALT"}],
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
                        mpn=mpn,
                        manufacturer=selected,
                    )
                self.assertEqual(payload.get("status"), "identity_ambiguous")
                self.assertEqual(payload.get("candidates"), [])
                self.assertEqual(
                    str((payload.get("original") or {}).get("manufacturer") or ""),
                    "",
                )

    def test_choices_from_live_hits_without_registry(self):
        labels = distinct_manufacturer_labels(
            [
                {"manufacturer": "Yageo", "manufacturer_part_number": "RC0603"},
                {"manufacturer": "Vishay", "manufacturer_part_number": "RC0603"},
                {"Manufacturer": {"Name": "Yageo"}},
            ]
        )
        self.assertEqual(len(labels), 2)
        choices = choices_from_manufacturer_labels("RC0603FR-0710KL", labels)
        self.assertEqual(len(choices), 2)
        self.assertTrue(all(row.get("manufacturer") for row in choices))

    def test_live_multi_brand_hits_block_without_selection(self):
        from apps.api.legacy_supplier_workflow import find_replacements

        mpn = "CAP-X7R-104"
        with patch(
            "src.alternative_finder_search.run_alternative_finder_search",
            side_effect=lambda state, searched, **kwargs: state.update(
                {
                    "alternative_finder_result": {
                        "original_data": {
                            "manufacturer_part_number": mpn,
                            "manufacturer": "Murata",
                            "all_supplier_results": [
                                {
                                    "manufacturer": "Murata",
                                    "manufacturer_part_number": mpn,
                                    "source": "DigiKey",
                                },
                                {
                                    "manufacturer": "TDK",
                                    "manufacturer_part_number": mpn,
                                    "source": "Mouser",
                                },
                            ],
                        },
                        "candidates": [{"Alternative Part": "SHOULD-NOT-SHOW"}],
                        "discovery_metadata": {},
                    }
                }
            )
            or {"status": "completed"},
        ):
            result = find_replacements(mpn, manufacturer="")
        self.assertEqual(result.get("original", {}).get("identity_status"), "ambiguous")
        self.assertEqual(result.get("candidates"), [])
        self.assertEqual(result.get("original", {}).get("manufacturer"), "")
        self.assertGreaterEqual(len(result.get("original", {}).get("identity_choices") or []), 2)

    def test_concurrent_explicit_manufacturer_propagation(self):
        from tests.streamlit_cache_stub import install_streamlit_cache_stub

        install_streamlit_cache_stub()
        import integrations.supplier_aggregator as aggregator

        if hasattr(aggregator.get_best_part_data, "clear"):
            aggregator.get_best_part_data.clear()

        observed: list[tuple[str, str]] = []

        def fake_digikey(part_number: str, manufacturer: str = ""):
            observed.append((part_number, manufacturer))
            brand = manufacturer.strip()
            return {
                "source": "DigiKey",
                "manufacturer_part_number": part_number,
                "manufacturer": brand,
                "supplier_data_verified": True,
                "stock_total": 10,
            }

        with patch.object(
            aggregator,
            "_supplier_lookup_callable",
            side_effect=lambda name: fake_digikey if name == "DigiKey" else None,
        ):
            outcomes: dict[str, dict] = {}

            def run(mpn: str, brand: str):
                outcomes[f"{mpn}|{brand}"] = aggregator.get_best_part_data(
                    mpn, manufacturer=brand
                )

            pairs = [
                ("AMP-DUAL-1", "Texas Instruments"),
                ("AMP-DUAL-1", "onsemi"),
                ("REG-DUAL-5V", "Analog Devices"),
                ("REG-DUAL-5V", "Microchip"),
            ]
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(run, mpn, brand) for mpn, brand in pairs]
                for future in as_completed(futures):
                    future.result()

        for mpn, brand in pairs:
            row = outcomes[f"{mpn}|{brand}"]
            self.assertEqual(row.get("manufacturer"), brand)
            self.assertEqual(row.get("manufacturer_part_number"), mpn)
            self.assertTrue(row.get("supplier_data_verified"))
        self.assertTrue(
            any(mpn == "AMP-DUAL-1" and brand == "Texas Instruments" for mpn, brand in observed)
        )
        self.assertTrue(
            any(mpn == "REG-DUAL-5V" and brand == "Microchip" for mpn, brand in observed)
        )


class ParameterizedVerdictTests(unittest.TestCase):
    def test_numeric_differences_across_component_classes(self):
        cases = [
            (
                "capacitor_voltage",
                FieldSpec("rated_voltage", "Rated voltage", compare=COMPARE_LIMIT_GE, unit="V"),
                "50 V",
                "100 V",
                "Different",
            ),
            (
                "resistor_power",
                FieldSpec("power_rating", "Power rating", compare=COMPARE_LIMIT_GE, unit="W"),
                "0.125 W",
                "0.25 W",
                "Different",
            ),
            (
                "resistor_resistance_match",
                FieldSpec("resistance", "Resistance", compare=COMPARE_NOMINAL, unit="Ohm"),
                "10 kOhm",
                "10kΩ",
                "Match",
            ),
            (
                "diode_reverse",
                FieldSpec("reverse_voltage", "Reverse voltage", compare=COMPARE_LIMIT_GE, unit="V"),
                "40 V",
                "100 V",
                "Different",
            ),
            (
                "opamp_offset",
                FieldSpec("input_offset_mv", "Input offset", compare=COMPARE_LIMIT_LE, unit="mV"),
                "3 mV",
                "2 mV",
                "Different",
            ),
        ]
        for name, spec, left, right, expected in cases:
            with self.subTest(name=name):
                status, _note = compare_field_values(left, right, spec)
                self.assertEqual(status, expected)

    def test_assessment_rules_parameterized_by_source_type(self):
        cases = [
            (
                "unknown_catalog",
                dict(
                    status="Match",
                    class_a="unknown",
                    class_b="unknown",
                    condition_a="Not stated",
                    condition_b="Not stated",
                    source_a="DigiKey catalog",
                    source_b="Mouser",
                ),
                FINDING_NEEDS_VERIFICATION,
            ),
            (
                "catalog_agreement",
                dict(
                    status="Listing agreement",
                    class_a="typical",
                    class_b="typical",
                    condition_a="@ 25C",
                    condition_b="@ 25C",
                    source_a="supplier catalog",
                    source_b="supplier listing",
                ),
                FINDING_LISTING_AGREEMENT,
            ),
            (
                "catalog_match_not_compatible",
                dict(
                    status="Match",
                    class_a="typical",
                    class_b="typical",
                    condition_a="@ 25C",
                    condition_b="@ 25C",
                    source_a="DigiKey",
                    source_b="Mouser",
                ),
                FINDING_LISTING_AGREEMENT,
            ),
            (
                "missing_sources",
                dict(
                    status="Match",
                    class_a="typical",
                    class_b="typical",
                    condition_a="@ 25C",
                    condition_b="@ 25C",
                    source_a="",
                    source_b="",
                ),
                FINDING_NEEDS_VERIFICATION,
            ),
            (
                "authoritative_compatible",
                dict(
                    status="Match",
                    class_a="typical",
                    class_b="typical",
                    condition_a="@ 25C",
                    condition_b="@ 25C",
                    source_a="manufacturer datasheet",
                    source_b="uploaded-manufacturer-datasheet",
                ),
                FINDING_COMPATIBLE,
            ),
            (
                "material_difference",
                dict(
                    status="Different",
                    class_a="unknown",
                    class_b="unknown",
                    condition_a="Not stated",
                    condition_b="Not stated",
                    source_a="DigiKey",
                    source_b="Mouser",
                ),
                FINDING_MATERIAL,
            ),
        ]
        for name, kwargs, expected in cases:
            with self.subTest(name=name):
                assessment = assess_compare_row(**kwargs)
                self.assertEqual(assessment, expected)
                if expected != FINDING_COMPATIBLE:
                    self.assertNotEqual(assessment, FINDING_COMPATIBLE)
        self.assertIn("fit unverified", FINDING_LISTING_AGREEMENT.casefold())


class SupplyRiskScopeClearTests(unittest.TestCase):
    def test_explicit_analysis_id_scopes_only_that_analysis(self):
        analyses = [
            {"id": "bom-alpha", "project_name": "Alpha", "filename": "a.csv"},
            {"id": "bom-beta", "project_name": "Beta", "filename": "b.csv"},
        ]
        parts = [
            {"analysis_id": "bom-alpha", "mpn": f"A{i}", "quantity": 1, "stock_available": 8}
            for i in range(3)
        ] + [
            {"analysis_id": "bom-beta", "mpn": f"B{i}", "quantity": 1, "stock_available": 8}
            for i in range(5)
        ]
        with patch(
            "apps.api.migration_tools.analyses_and_parts",
            return_value=(analyses, parts),
        ):
            payload = supply_risk_payload(
                workspace_id="ws-test",
                analysis_id="bom-alpha",
            )
        self.assertEqual(payload.get("scope"), "analysis")
        self.assertEqual(payload.get("analysis_id"), "bom-alpha")
        self.assertEqual(payload.get("source_part_count"), 3)
        self.assertIn("scoped", str(payload.get("gap") or "").casefold())

    def test_portfolio_when_no_analysis_context(self):
        analyses = [
            {"id": "bom-alpha", "project_name": "Alpha", "filename": "a.csv"},
            {"id": "bom-beta", "project_name": "Beta", "filename": "b.csv"},
        ]
        parts = [
            {"analysis_id": "bom-alpha", "mpn": "A1", "quantity": 1, "stock_available": 5},
            {"analysis_id": "bom-beta", "mpn": "B1", "quantity": 1, "stock_available": 5},
        ]
        with patch(
            "apps.api.migration_tools.analyses_and_parts",
            return_value=(analyses, parts),
        ):
            payload = supply_risk_payload(workspace_id="ws-test", analysis_id=None)
        self.assertEqual(payload.get("scope"), "portfolio")
        self.assertIsNone(payload.get("analysis_id"))
        self.assertIn("portfolio-wide", str(payload.get("gap") or "").casefold())

    def test_supply_page_labels_inherited_scope_and_clear_control(self):
        source = SUPPLY_PAGE.read_text(encoding="utf-8")
        self.assertIn("Clear analysis scope (portfolio-wide)", source)
        self.assertIn("forcePortfolio", source)
        self.assertIn("Scope source: inherited selected analysis from session", source)
        self.assertIn("Portfolio-wide across saved analyses in this workspace", source)
        self.assertIn("Scoped to selected analysis", source)


class AmbiguityDoesNotStampIdentityTests(unittest.TestCase):
    def test_ambiguity_payload_never_stamps_verified_manufacturer(self):
        payload = identity_ambiguity_payload(
            mpn="AMP-DUAL-1",
            requested_manufacturer="Texas Instruments",
            resolved_manufacturer="onsemi",
            choices=multi_brand_choices_for_mpn("AMP-DUAL-1")
            or choices_from_manufacturer_labels(
                "AMP-DUAL-1", ["Texas Instruments", "onsemi"]
            ),
        )
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["original"]["manufacturer"], "")
        self.assertFalse(payload["original"]["identity_verified"])
        self.assertTrue(manufacturers_match("TI", "Texas Instruments"))


if __name__ == "__main__":
    unittest.main()
