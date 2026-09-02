"""Regression coverage for Alternative Finder search timing and safe failures."""
from __future__ import annotations

import importlib
import sys
import types
import unittest

sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))


def _cache_data(*_args, **_kwargs):
    return lambda func: func


class AlternativeFinderSearchTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.SimpleNamespace(cache_data=_cache_data)
        sys.modules.pop("src.alternative_engine", None)
        sys.modules.pop("integrations.supplier_aggregator", None)
        self.search = importlib.import_module("src.alternative_finder_search")
        self.state = importlib.import_module("src.alternative_finder_state")
        self.engine = importlib.import_module("src.alternative_engine")
        self.classification = importlib.import_module("src.alternative_classification")
        self.aggregator = importlib.import_module("integrations.supplier_aggregator")

    def test_sanitize_search_diagnostic_redacts_secrets(self):
        diagnostic = self.search.sanitize_search_diagnostic(
            RuntimeError("Bearer abcdefghijklmnop token=super-secret"),
            provider="Octopart",
            operation="lookup",
        )
        self.assertEqual(diagnostic["diagnostic_code"], "octopart_lookup_failed")
        self.assertNotIn("super-secret", diagnostic["diagnostic_message"])
        self.assertNotIn("abcdefghijklmnop", diagnostic["diagnostic_message"])

    def test_search_run_collects_stage_timings(self):
        run = self.search.AlternativeFinderSearchRun()
        with run.stage("original_lookup"):
            pass
        with run.stage("candidate_engine"):
            pass
        breakdown = run.timing_breakdown()
        self.assertIn("original_lookup", breakdown["stages_ms"])
        self.assertIn("candidate_engine", breakdown["stages_ms"])
        self.assertGreaterEqual(breakdown["elapsed_ms"], breakdown["total_ms"])

    def test_fail_alternative_finder_search_records_safe_diagnostics(self):
        session: dict = {}
        self.state.fail_alternative_finder_search(
            session,
            entered_mpn="C0603C104K5RACTU",
            search_error="Cadivor could not complete the supplier search right now.",
            diagnostic_code="alternative_search_failed",
            diagnostic_message="candidate engine exploded",
            exception_type="RuntimeError",
            stage_timings_ms={"original_lookup": 1200.0, "candidate_engine": 45000.0},
            original_data={"manufacturer_part_number": "C0603C104K5RACTU"},
        )
        result = session[self.state.ALT_FINDER_RESULT_KEY]
        self.assertEqual(result["status"], self.state.STATUS_FAILED)
        self.assertEqual(result["diagnostic_code"], "alternative_search_failed")
        self.assertEqual(result["exception_type"], "RuntimeError")
        self.assertEqual(result["stage_timings_ms"]["candidate_engine"], 45000.0)
        self.assertNotIn("api_key", str(result).casefold())

    def test_suggest_alternatives_avoids_per_candidate_supplier_lookups(self):
        calls: list[str] = []

        def track_lookup(part_number: str):
            calls.append(str(part_number))
            return {
                "manufacturer_part_number": part_number,
                "manufacturer": "KEMET",
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
                "capacitance": "0.1 µF",
                "tolerance": "±10%",
                "dielectric": "X7R",
                "package": "0603",
                "mounting_style": "Surface Mount",
                "supplier_data_verified": True,
                "all_supplier_results": [],
            }

        self.engine.get_best_part_data = track_lookup

        explicit = [
            {
                "manufacturer_part_number": f"DIRECT-SUB-{index:02d}",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
                "retrieval_status": "ok",
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            }
            for index in range(12)
        ]

        def discover(_part):
            merged = self.classification.merge_discovery_candidates(
                explicit,
                [],
                original_mpn="C0603C104K5RACTU",
            )
            return {
                "original_mpn": "C0603C104K5RACTU",
                "candidates": merged,
                "explicit_count": len(explicit),
                "catalog_count": 0,
                "provider_failures": [],
                "has_incomplete_evidence": False,
                "retrieved_at": "2026-08-29T00:00:00+00:00",
                "providers": {"DigiKey": {"substitutions": "ok", "catalog": "ok"}},
            }

        self.engine.discover_alternative_candidates = discover

        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        self.assertGreaterEqual(len(results), 12)
        self.assertEqual(calls, ["C0603C104K5RACTU"])
        for row in results:
            self.assertNotIn("_discovery_row", row)

    def test_fail_with_cyclic_original_data_does_not_crash_sanitizer(self):
        cyclic: dict = {"manufacturer_part_number": "C0603C104K5RACTU"}
        cyclic["all_supplier_results"] = [cyclic]
        session: dict = {}
        self.state.fail_alternative_finder_search(
            session,
            entered_mpn="C0603C104K5RACTU",
            search_error="failed",
            diagnostic_code="internal_error",
            original_data=cyclic,
        )
        result = session[self.state.ALT_FINDER_RESULT_KEY]
        self.assertEqual(result["status"], self.state.STATUS_FAILED)
        self.assertIn(
            self.state.MARKER_CIRCULAR_REF,
            str(result["original_data"]["all_supplier_results"][0]),
        )

    def test_initial_render_enriches_auto_selected_candidate_before_reasoning(self):
        from src.alternative_reasoning import VERIFIED_DIRECT_DISPOSITION, build_alternative_reasoning

        capacitor_fields = {
            "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            "capacitance": "0.1 µF",
            "tolerance": "±10%",
            "dielectric": "X7R",
            "package": "0603",
            "mounting_style": "Surface Mount, MLCC",
            "rated_voltage": "50V",
            "temperature_coefficient": "X7R",
            "esr": "",
            "lifecycle_status": "Active",
            "stock_total": 50000,
            "unit_price": 0.05,
            "supplier_data_verified": True,
            "all_supplier_results": [],
        }
        lookup_calls: list[str] = []

        def search_lookup(part_number: str):
            lookup_calls.append(part_number)
            if part_number == "C0603C104K5RACTU":
                return dict(capacitor_fields, manufacturer_part_number=part_number)
            return {}

        def enrich_lookup(part_number: str):
            lookup_calls.append(part_number)
            if part_number in {"C0603C104K5RACTU", "C0603C104K5RAC3121"}:
                return dict(capacitor_fields, manufacturer_part_number=part_number)
            return {}

        self.engine.get_best_part_data = search_lookup
        self.aggregator.get_best_part_data = enrich_lookup

        def discover(_part):
            merged = self.classification.merge_discovery_candidates(
                [{
                    "manufacturer_part_number": "C0603C104K5RAC3121",
                    "source": "DigiKey",
                    "substitute_type": "Direct",
                    "evidence_type": "Distributor-listed substitute",
                }],
                [],
                original_mpn="C0603C104K5RACTU",
            )
            return {
                "original_mpn": "C0603C104K5RACTU",
                "candidates": merged,
                "explicit_count": 1,
                "catalog_count": 0,
                "provider_failures": [],
                "has_incomplete_evidence": False,
                "retrieved_at": "2026-08-29T00:00:00+00:00",
                "providers": {"DigiKey": {"substitutions": "ok", "catalog": "ok"}},
            }

        self.engine.discover_alternative_candidates = discover

        original_data = dict(capacitor_fields, manufacturer_part_number="C0603C104K5RACTU")
        candidates = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        sparse_row = next(
            row for row in candidates if row["Alternative Part"] == "C0603C104K5RAC3121"
        )
        self.assertLess(
            int(sparse_row.get("Engineering Comparison Confidence", 0) or 0),
            82,
        )

        session: dict = {}
        completed = self.state.complete_alternative_finder_search(
            session,
            entered_mpn="C0603C104K5RACTU",
            canonical_mpn="C0603C104K5RACTU",
            original_data=original_data,
            original_risk={},
            candidates=candidates,
            discovery_metadata=discover("C0603C104K5RACTU"),
        )
        auto_selected = completed["selected_candidate_mpn"]
        self.assertEqual(auto_selected, "C0603C104K5RAC3121")

        enriched, supplier_evidence, performed = self.search.get_or_enrich_selected_candidate(
            session,
            search_mpn="C0603C104K5RACTU",
            original_data=original_data,
            candidate_row=sparse_row,
            selected_mpn=auto_selected,
        )
        self.assertTrue(performed)
        self.assertEqual(enriched["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertEqual(enriched["Comparison Counts"], {"Match": 7, "Different": 0, "Needs data": 1})
        self.assertIn("Direct substitute", enriched["Supplier Relationship Summary"])
        self.assertGreaterEqual(enriched["Engineering Comparison Confidence"], 82)
        self.assertTrue(supplier_evidence.get("supplier_data_verified"))

        reasoning = build_alternative_reasoning(
            original_part="C0603C104K5RACTU",
            original_data=original_data,
            candidate=enriched,
            recommendation_score=enriched["Recommendation Score"],
            compatibility_confidence=enriched["Engineering Comparison Confidence"],
            engineering_matches=[],
            warnings=[],
            stock_delta="N/A",
            price_delta="N/A",
            comparison_family=enriched.get("Comparison Family", ""),
            classification=enriched.get("Classification", ""),
            comparison_rows=enriched.get("Comparison Rows") or [],
            comparison_counts=enriched.get("Comparison Counts") or {},
        )
        self.assertEqual(reasoning["disposition"], VERIFIED_DIRECT_DISPOSITION)
        self.assertGreaterEqual(reasoning["engineering_comparison_confidence"], 82)
        self.assertTrue(
            any("ESR" in item for item in reasoning.get("verification_required", []))
        )
        self.assertEqual(reasoning.get("hard_blocker_count", 0), 0)

        enriched_rerun, _, performed_rerun = self.search.get_or_enrich_selected_candidate(
            session,
            search_mpn="C0603C104K5RACTU",
            original_data=original_data,
            candidate_row=sparse_row,
            selected_mpn=auto_selected,
        )
        self.assertFalse(performed_rerun)
        self.assertEqual(enriched_rerun["Comparison Counts"], enriched["Comparison Counts"])
        self.assertEqual(lookup_calls.count("C0603C104K5RACTU"), 1)
        self.assertEqual(lookup_calls.count("C0603C104K5RAC3121"), 1)

    def test_malformed_stock_total_does_not_abort_supplier_aggregation(self):
        self.aggregator.get_supplier_results = lambda _part: [
            {
                "source": "Mouser",
                "provider_status": "AVAILABLE",
                "manufacturer_part_number": "C0603C104K5RACTU",
                "stock_total": "12,345 On Order",
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            },
            {
                "source": "DigiKey",
                "provider_status": "AVAILABLE",
                "manufacturer_part_number": "C0603C104K5RACTU",
                "stock_total": 50,
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            },
        ]
        data = self.aggregator.get_best_part_data("C0603C104K5RACTU")
        self.assertTrue(data["supplier_data_verified"])
        self.assertEqual(data["stock_total"], 12345)
        self.assertEqual(data["source"], "Mouser")

    def test_run_alternative_finder_search_keeps_partial_results_when_one_provider_fails(self):
        session: dict = {}
        self.state.init_alternative_finder_state(session)

        self.aggregator.get_supplier_results = lambda _part: [
            {
                "source": "Mouser",
                "provider_status": "PROVIDER_ERROR",
                "error": "HTTP 500",
                "manufacturer_part_number": "",
            },
            {
                "source": "DigiKey",
                "provider_status": "AVAILABLE",
                "manufacturer_part_number": "C0603C104K5RACTU",
                "stock_total": 1000,
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
                "manufacturer": "KEMET",
                "package": "0603",
            },
        ]

        explicit = [
            {
                "manufacturer_part_number": "C0603C104K5RAC3121",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
                "retrieval_status": "ok",
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            }
        ]

        def discover(_part):
            merged = self.classification.merge_discovery_candidates(
                explicit,
                [],
                original_mpn="C0603C104K5RACTU",
            )
            return {
                "original_mpn": "C0603C104K5RACTU",
                "candidates": merged,
                "explicit_count": len(explicit),
                "catalog_count": 0,
                "provider_failures": [],
                "has_incomplete_evidence": False,
                "retrieved_at": "2026-08-29T00:00:00+00:00",
                "providers": {"DigiKey": {"substitutions": "ok", "catalog": "ok"}},
            }

        self.engine.discover_alternative_candidates = discover
        self.engine.get_best_part_data = self.aggregator.get_best_part_data

        outcome = self.search.run_alternative_finder_search(session, "C0603C104K5RACTU")
        result = session[self.state.ALT_FINDER_RESULT_KEY]

        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(result["status"], self.state.STATUS_COMPLETED)
        self.assertGreater(len(result["candidates"]), 0)
        self.assertIn(
            "C0603C104K5RAC3121",
            [row["Alternative Part"] for row in result["candidates"]],
        )
        self.assertIn("Mouser", result["discovery_metadata"]["provider_failures"])
        self.assertTrue(result["discovery_metadata"]["has_incomplete_evidence"])
        self.assertNotIn("Cadivor could not complete the supplier search", str(result))


if __name__ == "__main__":
    unittest.main()
