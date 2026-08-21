"""Sprint 74 — supplier health and degraded-data tests."""
from __future__ import annotations

import unittest

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
    default_aggregated_result,
)


class SupplierHealthTests(unittest.TestCase):
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
