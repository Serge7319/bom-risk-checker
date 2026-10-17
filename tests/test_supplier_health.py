"""Sprint 74 — supplier health and degraded-data tests."""
from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from integrations.provider_health import (
    PROVIDER_AVAILABLE,
    PROVIDER_ERROR,
    PROVIDER_NOT_CONFIGURED,
    PROVIDER_PART_NOT_FOUND,
    PROVIDER_RATE_LIMITED,
    PROVIDER_TIMEOUT,
    classify_provider_exception,
    sanitize_provider_message,
    summarize_provider_health,
)
from integrations.supplier_aggregator import (
    _safe_supplier_lookup,
    _supplier_query_variants,
    default_aggregated_result,
)


class SupplierHealthTests(unittest.TestCase):
    def test_review_lookup_returns_datasheet_before_slowest_supplier_finishes(self):
        from integrations import supplier_aggregator

        release_slow_provider = threading.Event()
        slow_provider_started = threading.Event()
        slow_provider_finished = threading.Event()

        def slow_lookup(_query):
            slow_provider_started.set()
            release_slow_provider.wait(timeout=2)
            slow_provider_finished.set()
            return {"manufacturer_part_number": "LM7805ACT"}

        def fast_lookup(_query):
            return {
                "manufacturer_part_number": "LM7805ACT",
                "datasheet_url": "https://example.test/lm7805act.pdf",
                "product_detail_url": "https://example.test/lm7805act",
            }

        lookups = {
            "Mouser": slow_lookup,
            "DigiKey": fast_lookup,
            "Newark": lambda _query: {},
        }
        try:
            with patch.object(
                supplier_aggregator,
                "_supplier_lookup_callable",
                side_effect=lambda source: lookups[source],
            ):
                result = supplier_aggregator.get_first_exact_supplier_result(
                    "LM7805ACT"
                )

            self.assertEqual(
                result.get("datasheet_url"),
                "https://example.test/lm7805act.pdf",
            )
            self.assertTrue(slow_provider_started.wait(timeout=1))
            self.assertFalse(slow_provider_finished.is_set())
        finally:
            release_slow_provider.set()

    def test_review_lookup_does_not_accept_neighboring_mpn_datasheets(self):
        from integrations import supplier_aggregator

        wrong_part = {
            "manufacturer_part_number": "LM7805ACTG",
            "datasheet_url": "https://example.test/wrong-part.pdf",
        }
        with patch.object(
            supplier_aggregator,
            "_supplier_lookup_callable",
            return_value=lambda _query: wrong_part,
        ):
            result = supplier_aggregator.get_first_exact_supplier_result("LM7805ACT")

        self.assertEqual(result, {})

    def test_query_variants_keep_speed_and_package_suffixes(self):
        variants = _supplier_query_variants("AM29F010B-70EC")
        self.assertEqual(variants, ("AM29F010B-70EC", "AM29F010B70EC"))
        self.assertTrue(all("70EC" in variant for variant in variants))

    def test_separator_retry_accepts_only_the_same_mpn(self):
        calls = []

        def lookup(query):
            calls.append(query)
            if query == "IRF-540N":
                return {
                    "manufacturer_part_number": "IRF540NPBF",
                    "stock_total": 300,
                }
            return {
                "manufacturer_part_number": "IRF540N",
                "stock_total": 25,
            }

        result = _safe_supplier_lookup("DigiKey", lookup, "IRF-540N")
        self.assertEqual(calls, ["IRF-540N", "IRF540N"])
        self.assertEqual(result["provider_status"], PROVIDER_AVAILABLE)
        self.assertEqual(result["manufacturer_part_number"], "IRF540N")
        self.assertEqual(result["stock_total"], 25)

    def test_related_order_code_never_lends_stock_or_lifecycle_to_requested_mpn(self):
        result = _safe_supplier_lookup(
            "DigiKey",
            lambda _query: {
                "manufacturer_part_number": "IRF540NPBF",
                "stock_total": 300,
                "unit_price": 0.55,
                "lifecycle_status": "Active",
            },
            "IRF540N",
        )
        self.assertEqual(result["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertIsNone(result["stock_total"])
        self.assertEqual(result["lifecycle_status"], "Unknown")
        self.assertEqual(result["unit_price"], 0.0)

    def test_manufacturer_documented_order_code_metrics_feed_bom_risk(self):
        from integrations import supplier_aggregator
        from src.risk_engine import calculate_risk

        original_failures = [
            {"source": "DigiKey", "provider_status": PROVIDER_PART_NOT_FOUND},
            {"source": "Mouser", "provider_status": PROVIDER_NOT_CONFIGURED},
            {"source": "Newark", "provider_status": PROVIDER_NOT_CONFIGURED},
        ]
        cases = (
            ("IRF540N", "IRF540NPBF", "Infineon", "Active", "https://www.infineon.com/part/IRF540N"),
            (
                "PCF8574P",
                "PCF8574P,112",
                "NXP",
                "Obsolete",
                "https://www.nxp.com/docs/en/data-sheet/PCF8574_PCF8574A.pdf",
            ),
        )

        for requested, variant, manufacturer, lifecycle, source_url in cases:
            with self.subTest(requested=requested):
                def supplier_results(part_number, request_id=""):
                    if part_number == requested:
                        return original_failures
                    return [
                        {
                            "source": "DigiKey",
                            "provider_status": PROVIDER_AVAILABLE,
                            "manufacturer_part_number": variant,
                            "manufacturer": manufacturer,
                            "product_detail_url": f"https://example.test/{variant}",
                            "stock_total": 300,
                            "unit_price": 0.55,
                            "unit_price_currency": "USD",
                            "lifecycle_status": lifecycle,
                            "lead_time_weeks": 8,
                        },
                        {"source": "Mouser", "provider_status": PROVIDER_NOT_CONFIGURED},
                        {"source": "Newark", "provider_status": PROVIDER_NOT_CONFIGURED},
                    ]

                supplier_aggregator.get_best_part_data.clear()
                try:
                    with patch.object(
                        supplier_aggregator,
                        "get_supplier_results",
                        side_effect=supplier_results,
                    ):
                        data = supplier_aggregator.get_best_part_data(requested)
                finally:
                    supplier_aggregator.get_best_part_data.clear()

                self.assertEqual(data["mpn"], requested)
                self.assertEqual(data["assessment_basis"], "manufacturer_documented_order_code")
                self.assertEqual(data["assessment_evidence_mpn"], variant)
                self.assertEqual(data["manufacturer_part_number"], variant)
                self.assertEqual(data["lifecycle_status"], lifecycle)
                self.assertEqual(data["stock_total"], 300)
                self.assertEqual(data["unit_price_currency"], "USD")
                self.assertTrue(data["supplier_data_verified"])
                self.assertIn(variant, data["alternate_search_status"])
                self.assertIn(source_url, data["alternate_search_status"])
                self.assertIn(variant, data["assessment_basis_note"])

                risk = calculate_risk({**data, "quantity": 75})
                self.assertIsNotNone(risk["risk_score"])
                self.assertNotEqual(risk["risk_level"], "Needs verification")

    def test_family_only_legacy_route_remains_unassessed_without_an_exact_record(self):
        from integrations import supplier_aggregator

        supplier_aggregator.get_best_part_data.clear()
        try:
            with patch.object(
                supplier_aggregator,
                "get_supplier_results",
                return_value=[
                    {"source": "DigiKey", "provider_status": PROVIDER_PART_NOT_FOUND},
                    {"source": "Mouser", "provider_status": PROVIDER_NOT_CONFIGURED},
                    {"source": "Newark", "provider_status": PROVIDER_NOT_CONFIGURED},
                ],
            ), patch.object(
                supplier_aggregator,
                "_supplier_lookup_callable",
                return_value=None,
            ):
                data = supplier_aggregator.get_best_part_data("AM29F010B-70EC")
        finally:
            supplier_aggregator.get_best_part_data.clear()

        self.assertEqual(data["lifecycle_status"], "Unknown")
        self.assertFalse(data["supplier_data_verified"])
        self.assertIsNone(data["stock_total"])
        self.assertIn("remains unassessed", data["alternate_search_status"])

    def test_supplier_lookup_rejects_a_fuzzy_neighbor_mpn(self):
        result = _safe_supplier_lookup(
            "Mouser",
            lambda _part: {
                "manufacturer_part_number": "LM358",
                "mouser_part_number": "595-LM358",
                "stock_total": 1000,
                "lifecycle_status": "Active",
            },
            "LM358N",
        )
        self.assertEqual(result["provider_status"], PROVIDER_PART_NOT_FOUND)

    def test_matched_supplier_with_missing_stock_keeps_stock_unknown(self):
        result = _safe_supplier_lookup(
            "Mouser",
            lambda _part: {
                "manufacturer_part_number": "LM358N",
                "lifecycle_status": "Unknown",
            },
            "LM358N",
        )
        self.assertEqual(result["provider_status"], PROVIDER_AVAILABLE)
        self.assertIsNone(result["stock_total"])

    def test_aggregated_lifecycle_reports_conflicting_supplier_status(self):
        from integrations import supplier_aggregator

        supplier_aggregator.get_supplier_results = lambda _part: [
            {
                "source": "DigiKey",
                "provider_status": PROVIDER_AVAILABLE,
                "manufacturer_part_number": "LM358N-CONFLICT",
                "lifecycle_status": "Active",
                "stock_total": 100,
            },
            {
                "source": "Mouser",
                "provider_status": PROVIDER_AVAILABLE,
                "manufacturer_part_number": "LM358N-CONFLICT",
                "lifecycle_status": "Obsolete",
                "stock_total": 50,
            },
        ]
        data = supplier_aggregator.get_best_part_data("LM358N-CONFLICT")
        self.assertEqual(data["lifecycle_status"], "Conflicting supplier data")
        self.assertTrue(data["lifecycle_conflict"])
        self.assertEqual(
            {row["source"] for row in data["lifecycle_evidence"]},
            {"DigiKey", "Mouser"},
        )

    def test_aggregated_stock_does_not_turn_missing_sources_into_zero(self):
        from integrations import supplier_aggregator

        supplier_aggregator.get_supplier_results = lambda _part: [
            {
                "source": "DigiKey",
                "provider_status": PROVIDER_AVAILABLE,
                "manufacturer_part_number": "LM358N-STOCK",
                "stock_total": None,
                "lifecycle_status": "Unknown",
            },
        ]
        data = supplier_aggregator.get_best_part_data("LM358N-STOCK")
        self.assertIsNone(data["stock_total"])
        self.assertIsNone(data["total_market_stock"])
        self.assertFalse(data["stock_data_complete"])

    def test_mouser_inference_does_not_assume_active_or_zero_stock(self):
        from integrations.mouser_client import extract_stock_number, infer_lifecycle_status

        self.assertEqual(infer_lifecycle_status({"Description": "Dual operational amplifier"}), "Unknown")
        self.assertIsNone(extract_stock_number(""))
        self.assertIsNone(extract_stock_number("On Order: 1200"))
        self.assertEqual(extract_stock_number("0 In Stock"), 0)
        self.assertEqual(extract_stock_number("1,234 In Stock"), 1234)

    def test_all_providers_successful(self):
        results = [
            {"source": "Mouser", "provider_status": PROVIDER_AVAILABLE},
            {"source": "DigiKey", "provider_status": PROVIDER_AVAILABLE},
        ]
        health = summarize_provider_health(results)
        self.assertTrue(health["has_verified_data"])
        self.assertEqual(health["successful_count"], 2)

    def test_one_provider_timeout(self):
        results = [
            {"source": "Mouser", "provider_status": PROVIDER_AVAILABLE},
            {"source": "DigiKey", "provider_status": PROVIDER_TIMEOUT, "error": "timed out"},
        ]
        health = summarize_provider_health(results)
        self.assertTrue(health["has_verified_data"])
        self.assertIn("DigiKey", health["failed_sources"])

    def test_provider_not_configured(self):
        results = [{"source": "Newark", "provider_status": PROVIDER_NOT_CONFIGURED}]
        health = summarize_provider_health(results)
        self.assertFalse(health["has_verified_data"])
        self.assertEqual(health["configured_count"], 0)

    def test_provider_part_not_found(self):
        result = _safe_supplier_lookup(
            "Mouser",
            lambda part: {"manufacturer_part_number": "", "stock_total": 0},
            "ABC123",
        )
        self.assertEqual(result["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertNotIn("error", result)

    def test_part_not_found_distinct_from_provider_error(self):
        not_found = _safe_supplier_lookup(
            "Mouser",
            lambda part: {"manufacturer_part_number": "", "stock_total": 0},
            "ABC123",
        )
        provider_error = _safe_supplier_lookup(
            "DigiKey",
            lambda part: (_ for _ in ()).throw(RuntimeError("HTTP 500")),
            "ABC123",
        )
        self.assertNotEqual(not_found["provider_status"], provider_error["provider_status"])
        self.assertEqual(not_found["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertEqual(provider_error["provider_status"], PROVIDER_ERROR)

    def test_part_not_found_distinct_from_timeout_not_configured_rate_limit(self):
        not_found = _safe_supplier_lookup(
            "Mouser",
            lambda part: {"manufacturer_part_number": ""},
            "ABC123",
        )
        timeout = _safe_supplier_lookup(
            "DigiKey",
            lambda part: (_ for _ in ()).throw(TimeoutError("timed out")),
            "ABC123",
        )
        not_configured = _safe_supplier_lookup("Newark", None, "ABC123")
        rate_limited = _safe_supplier_lookup(
            "Mouser",
            lambda part: (_ for _ in ()).throw(Exception("429 Too Many Requests")),
            "ABC123",
        )
        statuses = {
            not_found["provider_status"],
            timeout["provider_status"],
            not_configured["provider_status"],
            rate_limited["provider_status"],
        }
        self.assertEqual(len(statuses), 4)
        self.assertEqual(not_found["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertEqual(timeout["provider_status"], PROVIDER_TIMEOUT)
        self.assertEqual(not_configured["provider_status"], PROVIDER_NOT_CONFIGURED)
        self.assertEqual(rate_limited["provider_status"], PROVIDER_RATE_LIMITED)

    def test_unverified_provider_data_does_not_claim_zero_stock_as_fact(self):
        from integrations.provider_health import unverified_supplier_reason_replacements

        replacements = unverified_supplier_reason_replacements()
        self.assertIn("No stock available", replacements)
        self.assertIn("could not be verified", replacements["No stock available"].lower())
        self.assertIn("Single-source supply risk", replacements)
        self.assertIn("Lifecycle status is unknown", replacements)

    def test_all_providers_unavailable(self):
        results = [
            {"source": "Mouser", "provider_status": PROVIDER_ERROR, "error": "HTTP 500"},
            {"source": "DigiKey", "provider_status": PROVIDER_TIMEOUT, "error": "timed out"},
        ]
        health = summarize_provider_health(results)
        self.assertFalse(health["has_verified_data"])
        self.assertIn("could not be verified", health["summary_message"].lower())

    def test_provider_failure_does_not_surface_secrets(self):
        message = sanitize_provider_message(
            Exception("401 Unauthorized bearer sk-live-secret-token")
        )
        self.assertNotIn("sk-live", message)
        self.assertIn("authentication", message.lower())

    def test_newark_style_500_with_apikey_query_is_not_auth_message(self):
        class _Response:
            status_code = 500

        class _HTTPError(Exception):
            def __init__(self):
                super().__init__(
                    "500 Server Error for url: "
                    "https://api.element14.com/catalog/products?callInfo.apiKey=sekrit"
                )
                self.response = _Response()

        message = sanitize_provider_message(_HTTPError())
        self.assertEqual(message, "Supplier lookup failed.")
        self.assertNotIn("sekrit", message)
        self.assertNotIn("authentication", message.lower())

    def test_classify_rate_limit(self):
        self.assertEqual(
            classify_provider_exception(Exception("429 Too Many Requests")),
            PROVIDER_RATE_LIMITED,
        )

    def test_default_aggregated_result_marks_unverified_on_provider_failure(self):
        results = [
            {
                "source": "Mouser",
                "provider_status": PROVIDER_ERROR,
                "error": "HTTP 500",
                "manufacturer_part_number": "",
            }
        ]
        data = default_aggregated_result("ABC123", results)
        self.assertFalse(data["supplier_data_verified"])
        self.assertEqual(data["provider_health"]["failed_count"], 1)

    def test_available_provider_result_is_verified(self):
        results = [
            {
                "source": "Mouser",
                "provider_status": PROVIDER_AVAILABLE,
                "manufacturer_part_number": "LM358",
                "stock_total": 100,
            }
        ]
        health = summarize_provider_health(results)
        self.assertTrue(health["has_verified_data"])
        self.assertEqual(results[0]["stock_total"], 100)

    def test_default_aggregated_result_includes_health(self):
        results = [
            {"source": "Mouser", "provider_status": PROVIDER_PART_NOT_FOUND},
            {"source": "DigiKey", "provider_status": PROVIDER_PART_NOT_FOUND},
        ]
        aggregated = default_aggregated_result("ABC123", results)
        self.assertFalse(aggregated["supplier_data_verified"])
        self.assertIn("provider_health", aggregated)


if __name__ == "__main__":
    unittest.main()
