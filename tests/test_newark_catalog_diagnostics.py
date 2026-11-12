"""Newark catalog-search diagnostics: empty success vs timeout/auth/HTTP/invalid.

Production evidence (AM29F010B-70EC, request_id=cf31d9b17119) showed Newark
collapsing to a generic “usable response” catalog error while Mouser retained
candidates. These tests lock classified diagnostics, partial-term handling, and
deferred retained_candidates logging.
"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import Mock, patch

import requests

from integrations.provider_health import (
    PROVIDER_ERROR,
    PROVIDER_PART_NOT_FOUND,
    PROVIDER_TIMEOUT,
    classify_provider_exception,
    sanitize_provider_message,
)
from integrations.supplier_diagnostics import (
    CATEGORY_AUTHENTICATION,
    CATEGORY_HTTP_ERROR,
    CATEGORY_MALFORMED_RESPONSE,
    CATEGORY_NO_RESULT,
    CATEGORY_TIMEOUT,
    bind_alternative_finder_request_id,
    categorize_supplier_failure,
    log_supplier_diagnostic,
)
from tests.streamlit_cache_stub import install_streamlit_cache_stub


class NewarkCatalogClientDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        import integrations.newark_client as newark

        self.newark = newark
        self.requests_patch = patch.object(newark, "requests")
        self.requests = self.requests_patch.start()
        self.addCleanup(self.requests_patch.stop)

    def _ok_response(self, payload: dict):
        response = Mock()
        response.raise_for_status = Mock()
        response.json = Mock(return_value=payload)
        return response

    def _http_error(
        self,
        status_code: int,
        url: str = "https://api.element14.com/catalog/products?callInfo.apiKey=secret-key",
    ):
        response = Mock()
        response.status_code = status_code
        error = requests.HTTPError(f"{status_code} Error for url: {url}")
        error.response = response
        return error

    def _product(self, mpn: str) -> dict:
        return {
            "translatedManufacturerPartNumber": mpn,
            "manufacturerPartNumber": mpn,
            "brandName": "Example",
            "displayName": mpn,
            "productStatus": "Active",
            "stock": {"level": 1},
            "prices": [{"cost": 1.0}],
        }

    def test_empty_successful_response_returns_empty_list_not_error(self):
        empty = self._ok_response({"keywordSearchReturn": {"products": []}})
        self.requests.get.return_value = empty
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            rows = self.newark.search_newark_catalog_candidates(
                "NOSUCH-MPN-ONLY", include_family_search=False
            )
        self.assertEqual(rows, [])
        self.assertIn("callInfo.apiKey", self.requests.get.call_args.kwargs["params"])

    def test_am29_empty_exact_plus_family_timeout_exposes_timeout(self):
        empty = self._ok_response({"keywordSearchReturn": {"products": []}})
        self.requests.get.side_effect = [empty, requests.Timeout("family timed out")]
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            with self.assertRaises(requests.Timeout):
                self.newark.search_newark_catalog_candidates("AM29F010B-70EC")
        self.assertEqual(self.requests.get.call_count, 2)
        terms = [call.kwargs["params"]["term"] for call in self.requests.get.call_args_list]
        self.assertEqual(terms[0], "keyword:AM29F010B-70EC")
        self.assertEqual(terms[1], "keyword:AM29F010")

    def test_partial_candidates_plus_failed_term_keeps_rows_and_failure(self):
        lead = self._ok_response(
            {"keywordSearchReturn": {"products": [self._product("AM29-FAMILY-LEAD")]}}
        )
        self.requests.get.side_effect = [lead, requests.Timeout("family timed out")]
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            with self.assertRaises(self.newark.NewarkCatalogPartialResultsError) as raised:
                # Force two terms: exact then family.
                with patch.object(
                    self.newark, "_catalog_family_search_term", return_value="AM29F010"
                ):
                    self.newark.search_newark_catalog_candidates("AM29F010B-70EC")
        err = raised.exception
        self.assertEqual(
            [row["manufacturer_part_number"] for row in err.candidates],
            ["AM29-FAMILY-LEAD"],
        )
        self.assertIsInstance(err.cause, requests.Timeout)

    def test_timeout_raises_classified_timeout(self):
        self.requests.get.side_effect = requests.Timeout("timed out")
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            with self.assertRaises(requests.Timeout):
                self.newark.search_newark_catalog_candidates(
                    "AM29F010B-70EC", include_family_search=False
                )
        self.assertEqual(
            categorize_supplier_failure(
                provider_status=PROVIDER_TIMEOUT,
                error_message="timed out",
                exception_type="Timeout",
            ),
            CATEGORY_TIMEOUT,
        )

    def test_http_401_is_auth_and_redacts_credentialed_url(self):
        error = self._http_error(401)
        self.requests.get.side_effect = error
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            with self.assertRaises(requests.HTTPError):
                self.newark.search_newark_catalog_candidates(
                    "AM29F010B-70EC", include_family_search=False
                )
        safe = sanitize_provider_message(error)
        self.assertNotIn("secret-key", safe)
        self.assertNotIn("apiKey", safe.casefold())
        self.assertEqual(
            categorize_supplier_failure(
                provider_status=PROVIDER_ERROR,
                error_message=str(error),
                exception_type="HTTPError",
                status_code=401,
            ),
            CATEGORY_AUTHENTICATION,
        )

    def test_http_500_is_http_error(self):
        error = self._http_error(500)
        self.requests.get.side_effect = error
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            with self.assertRaises(requests.HTTPError):
                self.newark.search_newark_catalog_candidates(
                    "AM29F010B-70EC", include_family_search=False
                )
        self.assertEqual(
            categorize_supplier_failure(
                provider_status=PROVIDER_ERROR,
                error_message=sanitize_provider_message(error),
                exception_type="HTTPError",
                status_code=500,
            ),
            CATEGORY_HTTP_ERROR,
        )

    def test_invalid_json_is_malformed_response(self):
        response = Mock()
        response.raise_for_status = Mock()
        response.json = Mock(side_effect=ValueError("No JSON"))
        self.requests.get.return_value = response
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            with self.assertRaises(self.newark.NewarkCatalogResponseError) as raised:
                self.newark.search_newark_catalog_candidates(
                    "AM29F010B-70EC", include_family_search=False
                )
        self.assertEqual(raised.exception.subreason, "malformed_response")
        self.assertEqual(
            categorize_supplier_failure(
                provider_status=PROVIDER_ERROR,
                error_message=str(raised.exception),
                exception_type="NewarkCatalogResponseError",
                subreason=raised.exception.subreason,
            ),
            CATEGORY_MALFORMED_RESPONSE,
        )

    def test_missing_keyword_search_return_is_malformed(self):
        self.requests.get.return_value = self._ok_response({"other": True})
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            with self.assertRaises(self.newark.NewarkCatalogResponseError):
                self.newark.search_newark_catalog_candidates(
                    "AM29F010B-70EC", include_family_search=False
                )

    def test_missing_products_key_is_malformed(self):
        self.requests.get.return_value = self._ok_response({"keywordSearchReturn": {}})
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            with self.assertRaises(self.newark.NewarkCatalogResponseError):
                self.newark.search_newark_catalog_candidates(
                    "AM29F010B-70EC", include_family_search=False
                )

    def test_invalid_products_payload_is_malformed(self):
        self.requests.get.return_value = self._ok_response(
            {"keywordSearchReturn": {"products": {"unexpected": True}}}
        )
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            with self.assertRaises(self.newark.NewarkCatalogResponseError):
                self.newark.search_newark_catalog_candidates(
                    "AM29F010B-70EC", include_family_search=False
                )


class NewarkCatalogDiscoveryIsolationTests(unittest.TestCase):
    def setUp(self):
        install_streamlit_cache_stub()
        import integrations.supplier_aggregator as aggregator

        self.aggregator = aggregator
        if hasattr(aggregator.discover_alternative_candidates, "clear"):
            aggregator.discover_alternative_candidates.clear()

    def _capture_diag_logs(self) -> list[str]:
        records: list[str] = []

        class _Handler(logging.Handler):
            def emit(self, record):  # noqa: ANN001
                records.append(str(record.getMessage()))

        handler = _Handler()
        logger = logging.getLogger("integrations.supplier_diagnostics")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        self.addCleanup(lambda: logger.removeHandler(handler))
        return records

    def test_newark_timeout_preserves_mouser_candidates_and_logs_retained(self):
        mouser_rows = [
            {
                "manufacturer_part_number": "MOUSER-ALT-1",
                "manufacturer": "Texas Instruments",
                "source": "Mouser",
                "evidence_type": "Distributor catalog match",
                "substitute_type": "Similar",
            }
        ]
        records = self._capture_diag_logs()

        with bind_alternative_finder_request_id("cf31d9b17119"), patch.object(
            self.aggregator, "_provider_configured", return_value=True
        ), patch.object(
            self.aggregator, "search_digikey_substitutions", return_value=[]
        ), patch.object(
            self.aggregator, "search_digikey_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator,
            "search_mouser_catalog_candidates",
            side_effect=lambda *_a, **_k: list(mouser_rows),
        ), patch.object(
            self.aggregator,
            "search_newark_catalog_candidates",
            side_effect=requests.Timeout("Newark catalog timed out"),
        ):
            discovery = self.aggregator.discover_alternative_candidates("AM29F010B-70EC")

        self.assertIn("Newark", discovery.get("provider_failures") or [])
        newark_status = (discovery.get("providers") or {}).get("Newark") or {}
        self.assertEqual(newark_status.get("catalog"), "error")
        self.assertEqual(newark_status.get("provider_status"), PROVIDER_TIMEOUT)
        mpns = {
            str(row.get("manufacturer_part_number") or row.get("mpn") or "")
            for row in (discovery.get("candidates") or [])
        }
        self.assertIn("MOUSER-ALT-1", mpns)
        newark_lines = [
            line
            for line in records
            if "supplier=Newark" in line and "stage=catalog_search" in line
        ]
        self.assertTrue(newark_lines, msg=records)
        self.assertTrue(any("category=timeout" in line for line in newark_lines))
        self.assertTrue(any("retained_candidates=true" in line for line in newark_lines))
        joined = "\n".join(records)
        self.assertNotIn("secret", joined.casefold())
        self.assertNotIn("apikey=", joined.casefold())

    def test_newark_empty_with_mouser_candidate_logs_retained_true(self):
        records = self._capture_diag_logs()
        mouser_rows = [
            {
                "manufacturer_part_number": "MOUSER-KEEP-1",
                "manufacturer": "Yageo",
                "source": "Mouser",
                "evidence_type": "Distributor catalog match",
                "substitute_type": "Similar",
            }
        ]
        with bind_alternative_finder_request_id("emptyretained01"), patch.object(
            self.aggregator, "_provider_configured", return_value=True
        ), patch.object(
            self.aggregator, "search_digikey_substitutions", return_value=[]
        ), patch.object(
            self.aggregator, "search_digikey_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator,
            "search_mouser_catalog_candidates",
            side_effect=lambda *_a, **_k: list(mouser_rows),
        ), patch.object(
            self.aggregator, "search_newark_catalog_candidates", return_value=[]
        ):
            discovery = self.aggregator.discover_alternative_candidates("NOSUCH-MPN-999")

        newark_status = (discovery.get("providers") or {}).get("Newark") or {}
        self.assertEqual(newark_status.get("catalog"), "ok")
        self.assertNotIn("Newark", discovery.get("provider_failures") or [])
        self.assertTrue(
            any(
                "supplier=Newark" in line
                and "stage=catalog_search" in line
                and "subreason=zero_results" in line
                and "retained_candidates=true" in line
                for line in records
            ),
            msg=records,
        )
        self.assertEqual(
            categorize_supplier_failure(
                provider_status=PROVIDER_PART_NOT_FOUND,
                subreason="zero_results",
            ),
            CATEGORY_NO_RESULT,
        )

    def test_partial_newark_keeps_candidates_and_reports_failure(self):
        from integrations.newark_client import NewarkCatalogPartialResultsError

        partial_rows = [
            {
                "manufacturer_part_number": "NEWARK-PARTIAL-1",
                "manufacturer": "Example",
                "source": "Newark",
                "evidence_type": "Distributor catalog match",
                "substitute_type": "Similar",
            }
        ]
        records = self._capture_diag_logs()

        def fake_newark(*_a, **_k):
            raise NewarkCatalogPartialResultsError(
                "partial",
                candidates=partial_rows,
                cause=requests.Timeout("family timed out"),
                failed_term="AM29F010",
            )

        with bind_alternative_finder_request_id("partialnewarka1"), patch.object(
            self.aggregator, "_provider_configured", return_value=True
        ), patch.object(
            self.aggregator, "search_digikey_substitutions", return_value=[]
        ), patch.object(
            self.aggregator, "search_digikey_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator, "search_mouser_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator, "search_newark_catalog_candidates", side_effect=fake_newark
        ):
            discovery = self.aggregator.discover_alternative_candidates("AM29F010B-70EC")

        newark_status = (discovery.get("providers") or {}).get("Newark") or {}
        self.assertEqual(newark_status.get("catalog"), "partial")
        self.assertEqual(newark_status.get("catalog_count"), 1)
        self.assertIn("Newark", discovery.get("provider_failures") or [])
        mpns = {
            str(row.get("manufacturer_part_number") or row.get("mpn") or "")
            for row in (discovery.get("candidates") or [])
        }
        self.assertIn("NEWARK-PARTIAL-1", mpns)
        self.assertTrue(
            any(
                "supplier=Newark" in line
                and "stage=catalog_search" in line
                and "category=timeout" in line
                for line in records
            ),
            msg=records,
        )

    def test_unconfigured_newark_skips_catalog_failure_logging(self):
        records = self._capture_diag_logs()

        def configured(secret_name: str) -> bool:
            return secret_name != "NEWARK_API_KEY"

        with bind_alternative_finder_request_id("unconfnewark01"), patch.object(
            self.aggregator, "_provider_configured", side_effect=configured
        ), patch.object(
            self.aggregator, "search_digikey_substitutions", return_value=[]
        ), patch.object(
            self.aggregator, "search_digikey_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator, "search_mouser_catalog_candidates", return_value=[]
        ), patch.object(
            self.aggregator,
            "search_newark_catalog_candidates",
            side_effect=AssertionError("Newark catalog must not be called when unconfigured"),
        ):
            discovery = self.aggregator.discover_alternative_candidates("AM29F010B-70EC")

        newark_status = (discovery.get("providers") or {}).get("Newark") or {}
        self.assertEqual(newark_status.get("lookup"), "not_configured")
        self.assertEqual(newark_status.get("catalog"), "not_configured")
        self.assertNotIn("Newark", discovery.get("provider_failures") or [])
        self.assertFalse(
            any(
                "supplier=Newark" in line and "stage=catalog_search" in line
                for line in records
            ),
            msg=records,
        )

    def test_catalog_diagnostic_payload_omits_secrets(self):
        class _Response:
            status_code = 401

        class _HTTPError(Exception):
            def __init__(self):
                super().__init__(
                    "401 Client Error: Unauthorized for url: "
                    "https://api.element14.com/catalog/products?callInfo.apiKey=secret-newark-key"
                )
                self.response = _Response()

        error = _HTTPError()
        payload = log_supplier_diagnostic(
            request_id="newark401cat",
            supplier="Newark",
            stage="catalog_search",
            provider_status=PROVIDER_ERROR,
            error_message=str(error),
            exception_type=type(error).__name__,
            error=error,
            retained_candidates=True,
        )
        self.assertEqual(payload["log_category"], "auth")
        self.assertEqual(payload["stage"], "catalog_search")
        self.assertEqual(payload["retained_candidates"], "true")
        blob = "\n".join(str(value) for value in payload.values())
        self.assertNotIn("secret-newark-key", blob)
        self.assertNotIn("apiKey=", blob)


class UnregisteredMultiBrandLiveHitsTests(unittest.TestCase):
    def test_unregistered_mpn_with_multiple_live_manufacturer_hits_blocks(self):
        from apps.api.legacy_supplier_workflow import find_replacements
        from apps.api.manufacturer_identity import (
            clear_multi_brand_evidence,
            multi_brand_choices_for_mpn,
        )

        clear_multi_brand_evidence()
        mpn = "UNREG-MULTI-104K"
        self.assertEqual(multi_brand_choices_for_mpn(mpn), [])

        with patch(
            "src.alternative_finder_search.run_alternative_finder_search",
            side_effect=lambda state, searched, **kwargs: state.update(
                {
                    "alternative_finder_result": {
                        "original_data": {
                            "manufacturer_part_number": mpn,
                            "manufacturer": "Yageo",
                            "all_supplier_results": [
                                {
                                    "manufacturer": "Yageo",
                                    "manufacturer_part_number": mpn,
                                    "source": "DigiKey",
                                },
                                {
                                    "manufacturer": "Vishay",
                                    "manufacturer_part_number": mpn,
                                    "source": "Mouser",
                                },
                            ],
                        },
                        "candidates": [{"Alternative Part": "SHOULD-NOT-APPEAR"}],
                        "discovery_metadata": {},
                    }
                }
            )
            or {"status": "completed"},
        ):
            result = find_replacements(mpn, manufacturer="")

        original = result.get("original") or {}
        self.assertEqual(original.get("identity_status"), "ambiguous")
        self.assertEqual(original.get("manufacturer"), "")
        self.assertFalse(bool(original.get("identity_verified")))
        self.assertEqual(result.get("candidates") or [], [])
        brands = {
            str(row.get("canonical") or "")
            for row in (original.get("identity_choices") or [])
        }
        self.assertIn("yageo", brands)
        self.assertIn("vishay", brands)


if __name__ == "__main__":
    unittest.main()
