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
        self.search = importlib.import_module("src.alternative_finder_search")
        self.state = importlib.import_module("src.alternative_finder_state")
        self.engine = importlib.import_module("src.alternative_engine")
        self.classification = importlib.import_module("src.alternative_classification")

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


if __name__ == "__main__":
    unittest.main()
