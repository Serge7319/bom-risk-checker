"""Regression coverage for Alternative Finder search timing and safe failures."""
from __future__ import annotations

import importlib
import sys
import types
import unittest

sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))

def _digikey_direct_pair(mpn: str, original: str = "C0603C104K5RACTU", **extra):
    row = {
        "manufacturer_part_number": mpn,
        "manufacturer": "KEMET",
        "source": "DigiKey",
        "substitute_type": "Direct",
        "evidence_type": "Distributor-listed substitute",
        "original_mpn": original,
        "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
        "supplier_relationship_evidence": [
            {
                "supplier": "DigiKey",
                "original_mpn": original,
                "candidate_mpn": mpn,
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
                "summary": "DigiKey substitute type: Direct",
                "supplier_part_id": f"{mpn}-DK",
                "source_url": f"https://www.digikey.com/en/products/{mpn}",
            }
        ],
    }
    row.update(extra)
    return row




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

    def test_suggest_return_is_cache_serializable_without_sets(self):
        explicit = [
            _digikey_direct_pair(
                "C0603C104K5RAC3121", retrieval_status="ok", stock_total=7180
            )
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
        self.engine.get_best_part_data = lambda part: {
            "manufacturer_part_number": part,
            "manufacturer": "KEMET",
            "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            "package": "0603",
            "supplier_data_verified": True,
            "all_supplier_results": [],
        }

        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        self.assertGreater(len(results), 0)
        for row in results:
            self.assertIsInstance(row.get("Feature Tags"), list)
        self.engine.assert_candidates_cache_serializable(results)

    def test_run_alternative_finder_search_preserves_salvage_candidates_on_persist_failure(self):
        session: dict = {}
        self.state.init_alternative_finder_state(session)

        explicit = [
            _digikey_direct_pair("C0603C104K5RAC3121", retrieval_status="ok")
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
        self.aggregator.get_supplier_results = lambda _part: [
            {
                "source": "DigiKey",
                "provider_status": "AVAILABLE",
                "manufacturer_part_number": "C0603C104K5RACTU",
                "stock_total": 1000,
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
                "manufacturer": "KEMET",
                "package": "0603",
            }
        ]
        self.engine.get_best_part_data = self.aggregator.get_best_part_data

        original_complete = self.state.complete_alternative_finder_search
        complete_calls = {"count": 0}

        def exploding_complete(*args, **kwargs):
            complete_calls["count"] += 1
            if complete_calls["count"] == 1:
                raise TypeError("cannot pickle set state")
            return original_complete(*args, **kwargs)

        self.state.complete_alternative_finder_search = exploding_complete
        outcome = self.search.run_alternative_finder_search(session, "C0603C104K5RACTU")
        self.state.complete_alternative_finder_search = original_complete

        result = session[self.state.ALT_FINDER_RESULT_KEY]
        self.assertEqual(outcome["status"], "partial_success")
        self.assertEqual(outcome["search_outcome"], self.state.OUTCOME_PARTIAL_SUCCESS)
        self.assertEqual(result["status"], self.state.STATUS_COMPLETED)
        self.assertEqual(result["search_outcome"], self.state.OUTCOME_PARTIAL_SUCCESS)
        self.assertEqual(result.get("failed_stage"), self.search.STAGE_PERSIST)
        self.assertEqual(result.get("exception_type"), "TypeError")
        self.assertGreater(len(result.get("candidates") or []), 0)
        self.assertIn(
            "C0603C104K5RAC3121",
            [row["Alternative Part"] for row in result["candidates"]],
        )
        self.assertEqual(session.get("alternative_search_error"), "")
        self.assertFalse(self.state.should_show_terminal_search_error(session))

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
            _digikey_direct_pair(
                f"DIRECT-SUB-{index:02d}",
                retrieval_status="ok",
            )
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
                [_digikey_direct_pair("C0603C104K5RAC3121", description="")],
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
        counts = enriched["Comparison Counts"]
        self.assertEqual(counts.get("Different"), 0)
        self.assertGreaterEqual(counts.get("Match", 0), 6)
        self.assertIn("DigiKey substitute type: Direct", enriched["Supplier Relationship Summary"])
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
            _digikey_direct_pair("C0603C104K5RAC3121", retrieval_status="ok")
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

        self.assertEqual(outcome["status"], "partial_success")
        self.assertEqual(outcome["search_outcome"], self.state.OUTCOME_PARTIAL_SUCCESS)
        self.assertEqual(result["status"], self.state.STATUS_COMPLETED)
        self.assertEqual(result["search_outcome"], self.state.OUTCOME_PARTIAL_SUCCESS)
        self.assertGreater(len(result["candidates"]), 0)
        self.assertIn(
            "C0603C104K5RAC3121",
            [row["Alternative Part"] for row in result["candidates"]],
        )
        self.assertIn("Mouser", result["discovery_metadata"]["provider_failures"])
        self.assertTrue(result["discovery_metadata"]["has_incomplete_evidence"])
        self.assertEqual(session.get("alternative_search_error"), "")
        self.assertFalse(self.state.should_show_terminal_search_error(session))
        self.assertNotIn("Cadivor could not complete the supplier search", str(result))


class AlternativeFinderOutcomeTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.SimpleNamespace(cache_data=_cache_data)
        sys.modules.pop("src.alternative_engine", None)
        sys.modules.pop("integrations.supplier_aggregator", None)
        self.search = importlib.import_module("src.alternative_finder_search")
        self.state = importlib.import_module("src.alternative_finder_state")
        self.engine = importlib.import_module("src.alternative_engine")
        self.classification = importlib.import_module("src.alternative_classification")
        self.aggregator = importlib.import_module("integrations.supplier_aggregator")
        self.diagnostics = importlib.import_module("integrations.supplier_diagnostics")

    def _verified_direct_candidate(self):
        original = "C0603C104K5RACTU"
        mpn = "C0603C104K5RAC3121"
        return {
            "manufacturer_part_number": mpn,
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": original,
            "retrieval_status": "ok",
            "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            "supplier_relationship_evidence": [
                {
                    "supplier": "DigiKey",
                    "original_mpn": original,
                    "candidate_mpn": mpn,
                    "substitute_type": "Direct",
                    "evidence_type": "Distributor-listed substitute",
                    "summary": "DigiKey substitute type: Direct",
                    "supplier_part_id": f"{mpn}-DK",
                    "source_url": f"https://www.digikey.com/en/products/{mpn}",
                }
            ],
        }

    def test_true_failure_shows_terminal_error_without_candidates(self):
        session: dict = {}
        self.state.init_alternative_finder_state(session)
        self.aggregator.get_best_part_data = lambda _part: {
            "manufacturer_part_number": "C0603C104K5RACTU",
            "supplier_data_verified": True,
            "all_supplier_results": [],
        }
        self.engine.suggest_alternatives_v2 = lambda _part: (_ for _ in ()).throw(
            RuntimeError("candidate engine exploded")
        )
        self.engine.discover_alternative_candidates = lambda _part: {
            "original_mpn": "C0603C104K5RACTU",
            "candidates": [],
            "provider_failures": [],
            "has_incomplete_evidence": False,
        }

        outcome = self.search.run_alternative_finder_search(session, "C0603C104K5RACTU")
        result = session[self.state.ALT_FINDER_RESULT_KEY]

        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["search_outcome"], "failure")
        self.assertEqual(result["status"], self.state.STATUS_FAILED)
        self.assertEqual(result["search_outcome"], self.state.OUTCOME_FAILURE)
        self.assertEqual(result.get("candidates") or [], [])
        self.assertIn("Cadivor could not complete the supplier search", session["alternative_search_error"])
        self.assertTrue(self.state.should_show_terminal_search_error(session))

    def test_stale_terminal_error_cleared_after_later_successful_search(self):
        session: dict = {}
        self.state.init_alternative_finder_state(session)
        self.state.fail_alternative_finder_search(
            session,
            entered_mpn="OLD-PART",
            search_error=self.state.TERMINAL_SEARCH_ERROR_MESSAGE,
        )
        self.assertTrue(self.state.should_show_terminal_search_error(session))

        explicit = [self._verified_direct_candidate()]

        def discover(_part):
            merged = self.classification.merge_discovery_candidates(
                explicit,
                [],
                original_mpn="C0603C104K5RACTU",
            )
            return {
                "original_mpn": "C0603C104K5RACTU",
                "candidates": merged,
                "provider_failures": [],
                "has_incomplete_evidence": False,
            }

        self.engine.discover_alternative_candidates = discover
        self.aggregator.get_best_part_data = lambda _part: {
            "manufacturer_part_number": "C0603C104K5RACTU",
            "supplier_data_verified": True,
            "all_supplier_results": [
                {"source": "DigiKey", "provider_status": "AVAILABLE"},
            ],
        }

        self.state.mark_alternative_finder_running(session, entered_mpn="C0603C104K5RACTU")
        outcome = self.search.run_alternative_finder_search(session, "C0603C104K5RACTU")

        self.assertIn(outcome["status"], {"completed", "partial_success"})
        self.assertEqual(session.get("alternative_search_error"), "")
        self.assertFalse(self.state.should_show_terminal_search_error(session))
        self.assertGreater(len(self.state.get_alternative_finder_candidates(session)), 0)

    def test_octopart_not_configured_records_configuration_category(self):
        with self.assertLogs("integrations.supplier_diagnostics", level="WARNING") as logs:
            results = self.aggregator.get_supplier_results("C0603C104K5RACTU")
        octopart_rows = [row for row in results if row.get("source") == "Octopart"]
        self.assertEqual(len(octopart_rows), 1)
        row = octopart_rows[0]
        self.assertEqual(row.get("provider_status"), "NOT_CONFIGURED")
        self.assertEqual(row.get("failure_category"), self.diagnostics.CATEGORY_CONFIGURATION)
        joined = "\n".join(logs.output)
        self.assertIn("ALT_FINDER_SUPPLIER_DIAG", joined)
        self.assertIn("supplier=Octopart", joined)
        self.assertIn("category=configuration", joined)
        self.assertNotIn("Bearer ", joined)
        self.assertNotIn("client_secret", joined.casefold())

    def test_configured_octopart_auth_failure_emits_warning_diagnostic(self):
        """Configured Nexar auth failure must emit searchable WARNING diagnostics."""
        import integrations.supplier_diagnostics as diagnostics

        class _Response:
            status_code = 401

        class _HTTPError(Exception):
            def __init__(self):
                super().__init__(
                    "401 Client Error: Unauthorized for url: "
                    "https://identity.nexar.com/connect/token"
                )
                self.response = _Response()

        original_creds = diagnostics._octopart_credentials_configured
        diagnostics._octopart_credentials_configured = lambda: True
        self.addCleanup(
            lambda: setattr(diagnostics, "_octopart_credentials_configured", original_creds)
        )
        original_callable = self.aggregator._supplier_lookup_callable

        def lookup_callable(source_name):
            if source_name == "Octopart":
                def boom(_part):
                    raise _HTTPError()

                return boom
            return None

        self.aggregator._supplier_lookup_callable = lookup_callable
        self.addCleanup(
            lambda: setattr(self.aggregator, "_supplier_lookup_callable", original_callable)
        )

        with self.assertLogs("integrations.supplier_diagnostics", level="WARNING") as logs:
            results = self.aggregator.get_supplier_results("C0603C104K5RACTU")

        octopart = next(row for row in results if row.get("source") == "Octopart")
        self.assertEqual(octopart.get("provider_status"), "PROVIDER_ERROR")
        self.assertEqual(octopart.get("failure_category"), self.diagnostics.CATEGORY_AUTHENTICATION)
        self.assertEqual(octopart.get("diagnostic_log_category"), "auth")
        self.assertEqual(octopart.get("diagnostic_status_code"), "401")
        self.assertEqual(octopart.get("diagnostic_retryable"), "false")

        joined = "\n".join(logs.output)
        octopart_diags = [
            message
            for message in logs.output
            if "ALT_FINDER_SUPPLIER_DIAG" in message and "supplier=Octopart" in message
        ]
        self.assertEqual(len(octopart_diags), 1)
        self.assertIn("ALT_FINDER_SUPPLIER_DIAG", joined)
        self.assertIn("supplier=Octopart", joined)
        self.assertIn("category=auth", joined)
        self.assertIn("status_code=401", joined)
        self.assertIn("retryable=false", joined)
        self.assertNotIn("identity.nexar.com", joined)
        self.assertNotIn("Bearer ", joined)
        self.assertNotIn("client_secret", joined.casefold())
        self.assertNotIn("connect/token", joined)

        # Configured auth failure remains unavailable in coverage UI (not "not configured").
        label = self.diagnostics.supplier_coverage_label(
            "Octopart",
            octopart.get("provider_status"),
            failure_category=octopart.get("failure_category"),
            error_message=str(octopart.get("error") or ""),
        )
        self.assertEqual(label, "Octopart: unavailable for this search")

    def test_configured_octopart_http_failure_emits_warning_diagnostic(self):
        """Configured Nexar HTTP 500 must emit searchable WARNING diagnostics."""
        import integrations.supplier_diagnostics as diagnostics

        class _Response:
            status_code = 500

        class _HTTPError(Exception):
            def __init__(self):
                super().__init__("500 Server Error: Internal Server Error for url: https://api.nexar.com/graphql")
                self.response = _Response()

        original_creds = diagnostics._octopart_credentials_configured
        diagnostics._octopart_credentials_configured = lambda: True
        self.addCleanup(
            lambda: setattr(diagnostics, "_octopart_credentials_configured", original_creds)
        )
        original_callable = self.aggregator._supplier_lookup_callable

        def lookup_callable(source_name):
            if source_name == "Octopart":
                def boom(_part):
                    raise _HTTPError()

                return boom
            return None

        self.aggregator._supplier_lookup_callable = lookup_callable
        self.addCleanup(
            lambda: setattr(self.aggregator, "_supplier_lookup_callable", original_callable)
        )

        with self.assertLogs("integrations.supplier_diagnostics", level="WARNING") as logs:
            results = self.aggregator.get_supplier_results("C0603C104K5RACTU")

        octopart = next(row for row in results if row.get("source") == "Octopart")
        self.assertEqual(octopart.get("provider_status"), "PROVIDER_ERROR")
        self.assertEqual(octopart.get("failure_category"), self.diagnostics.CATEGORY_HTTP_ERROR)
        self.assertEqual(octopart.get("diagnostic_log_category"), "http")
        self.assertEqual(octopart.get("diagnostic_status_code"), "500")
        self.assertEqual(octopart.get("diagnostic_retryable"), "true")

        joined = "\n".join(logs.output)
        self.assertIn("ALT_FINDER_SUPPLIER_DIAG", joined)
        self.assertIn("supplier=Octopart", joined)
        self.assertIn("category=http", joined)
        self.assertIn("status_code=500", joined)
        self.assertIn("retryable=true", joined)
        self.assertNotIn("api.nexar.com", joined)
        self.assertNotIn("Bearer ", joined)
        self.assertNotIn("graphql", joined.casefold())

        # Existing PROVIDER_ERROR row still produced exactly one searchable Octopart diagnostic.
        octopart_diags = [
            message
            for message in logs.output
            if "ALT_FINDER_SUPPLIER_DIAG" in message and "supplier=Octopart" in message
        ]
        self.assertEqual(len(octopart_diags), 1)

    def test_octopart_coverage_label_distinguishes_configuration_from_failure(self):
        import integrations.supplier_diagnostics as diagnostics

        original = diagnostics._octopart_credentials_configured
        diagnostics._octopart_credentials_configured = lambda: True
        self.addCleanup(
            lambda: setattr(diagnostics, "_octopart_credentials_configured", original)
        )
        configured_label = self.diagnostics.supplier_coverage_label(
            "Octopart",
            "NOT_CONFIGURED",
            failure_category=self.diagnostics.CATEGORY_CONFIGURATION,
        )
        failed_label = self.diagnostics.supplier_coverage_label(
            "Octopart",
            "PROVIDER_ERROR",
            failure_category=self.diagnostics.CATEGORY_HTTP_ERROR,
        )
        self.assertEqual(configured_label, "Octopart: not configured")
        self.assertEqual(failed_label, "Octopart: unavailable for this search")

    def test_c3121_classification_follows_verified_direct_evidence(self):
        explicit = [self._verified_direct_candidate()]
        merged = self.classification.merge_discovery_candidates(
            explicit,
            [],
            original_mpn="C0603C104K5RACTU",
        )
        classification = self.classification.classify_from_supplier_evidence(
            merged[0],
            original_mpn="C0603C104K5RACTU",
            original_manufacturer="KEMET",
        )
        self.assertEqual(classification, self.classification.CLASS_VERIFIED_DIRECT)

        def discover(_part):
            return {
                "original_mpn": "C0603C104K5RACTU",
                "candidates": merged,
                "provider_failures": [],
                "has_incomplete_evidence": True,
                "providers": {"DigiKey": {"substitutions": "ok"}},
            }

        self.engine.discover_alternative_candidates = discover
        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        target = next(
            row for row in results if row["Alternative Part"] == "C0603C104K5RAC3121"
        )
        self.assertEqual(target["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertEqual(target["Substitute Type"], "Direct")
        self.assertEqual(target["Evidence Type"], "Distributor-listed substitute")
        self.assertEqual(
            str(target.get("Supplier Relationship Summary") or "").count(
                "DigiKey substitute type: Direct"
            ),
            1,
        )

    def test_octopart_misclassified_lookup_error_does_not_use_unavailable_wording(self):
        coverage = self.diagnostics.build_alternative_finder_coverage_notices(
            original_data={
                "all_supplier_results": [
                    {"source": "Mouser", "provider_status": "AVAILABLE"},
                    {"source": "DigiKey", "provider_status": "AVAILABLE"},
                    {"source": "Newark", "provider_status": "AVAILABLE"},
                    {
                        "source": "Octopart",
                        "provider_status": "PROVIDER_ERROR",
                        "failure_category": self.diagnostics.CATEGORY_PROVIDER_ERROR,
                        "error": "No response from Octopart",
                    },
                ]
            },
            discovery_metadata={
                "has_incomplete_evidence": True,
                "provider_failures": ["Octopart"],
                "providers": {
                    "Octopart": {"lookup": "not_configured", "substitutions": "not_configured"},
                    "DigiKey": {"lookup": "available", "substitutions": "ok"},
                },
            },
        )
        joined_notices = " ".join(coverage["notices"])
        joined_captions = " ".join(coverage["captions"])
        self.assertEqual(
            coverage["notices"][0],
            "Octopart is not configured for this environment. "
            "Results include Mouser, DigiKey, and Newark.",
        )
        self.assertNotIn("did not respond", joined_notices.casefold())
        self.assertNotIn("unavailable for this search", joined_notices.casefold())
        self.assertNotIn("unavailable for this search", joined_captions.casefold())
        self.assertEqual(coverage["configuration_sources"], ["Octopart"])
        self.assertFalse(coverage["runtime_failures"])


if __name__ == "__main__":
    unittest.main()
