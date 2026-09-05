"""Focused Nexar authentication, exact-match, and supplier pipeline checks."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class OctopartIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.names = ("streamlit", "requests", "integrations.octopart_client")
        cls.originals = {name: sys.modules.get(name) for name in cls.names}
        streamlit = types.ModuleType("streamlit")
        streamlit.secrets = {}
        sys.modules["streamlit"] = streamlit
        cls.requests = types.ModuleType("requests")
        cls.requests.post = Mock()
        sys.modules["requests"] = cls.requests
        sys.modules.pop("integrations.octopart_client", None)
        cls.client = importlib.import_module("integrations.octopart_client")

    @classmethod
    def tearDownClass(cls):
        for name, original in cls.originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    def setUp(self):
        self.requests.post.reset_mock()
        self.client._TOKEN_CACHE.clear()

    def _part(self, mpn="LM358N", *, name="Operational amplifier"):
        return {
            "mpn": mpn,
            "name": name,
            "manufacturer": {"name": "Texas Instruments"},
            "sellers": [
                {
                    "company": {"name": "Arrow"},
                    "offers": [
                        {
                            "inventoryLevel": 120,
                            "clickUrl": "https://example.com/a",
                            "prices": [{"quantity": 1, "price": 0.62}],
                        }
                    ],
                },
                {
                    "company": {"name": "Avnet"},
                    "offers": [
                        {
                            "inventoryLevel": 80,
                            "prices": [{"quantity": 1, "price": 0.48}],
                        }
                    ],
                },
            ],
        }

    def _responses(self, parts, *, hits=None):
        token = Mock()
        token.json.return_value = {"access_token": "private-token", "expires_in": 3600}
        graphql = Mock()
        results = [{"part": part} for part in parts]
        payload = {
            "data": {
                "supSearchMpn": {
                    "hits": len(results) if hits is None else hits,
                    "results": results,
                }
            }
        }
        graphql.json.return_value = payload
        self.requests.post.side_effect = [token, graphql]
        return token, graphql

    def _secrets(self, name, **kwargs):
        return {"NEXAR_CLIENT_ID": "client-id", "NEXAR_CLIENT_SECRET": "private-secret"}[name]

    def test_query_uses_current_nexar_fields(self):
        query = self.client._PART_QUERY
        self.assertIn("supSearchMpn", query)
        self.assertIn('country: "US"', query)
        self.assertIn('currency: "USD"', query)
        self.assertIn("name", query)
        self.assertIn("prices { quantity price }", query)
        self.assertNotIn("shortDescription", query)

    def test_exact_match_normalizes_inventory_price_and_sellers(self):
        self._responses([self._part()])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            result = self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(result["manufacturer_part_number"], "LM358N")
        self.assertEqual(result["manufacturer"], "Texas Instruments")
        self.assertEqual(result["description"], "Operational amplifier")
        self.assertEqual(result["stock_total"], 200)
        self.assertEqual(result["unit_price"], 0.48)
        self.assertEqual(result["octopart_sellers"], ["Arrow", "Avnet"])
        self.assertEqual(result["octopart_subreason"], self.client.SUBREASON_OK)

    def test_exact_match_can_be_second_result(self):
        self._responses([self._part("LM358P"), self._part("lm358n")])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            result = self.client.search_octopart_by_part_number(" LM358N ")
        self.assertEqual(result["manufacturer_part_number"], "lm358n")

    def test_format_only_mpn_difference_is_an_exact_match(self):
        self._responses([self._part("C0603C104K5RAC-TU")])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            result = self.client.search_octopart_by_part_number("C0603C104K5RACTU")
        self.assertEqual(result["manufacturer_part_number"], "C0603C104K5RAC-TU")

    def test_similar_part_is_rejected_as_zero_results(self):
        self._responses([self._part("LM358P")])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            result = self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertEqual(result["octopart_subreason"], self.client.SUBREASON_ZERO_RESULTS)

    def test_empty_part_never_requests_credentials_or_network(self):
        with patch.object(self.client, "get_secret") as secret:
            result = self.client.search_octopart_by_part_number("  ")
        self.assertEqual(result["supplier_count"], 0)
        self.assertEqual(result["octopart_subreason"], self.client.SUBREASON_ZERO_RESULTS)
        secret.assert_not_called()
        self.requests.post.assert_not_called()

    def test_oauth_token_is_cached(self):
        self._responses([self._part()])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            first = self.client._access_token()
            second = self.client._access_token()
        self.assertEqual(first, second)
        self.assertEqual(self.requests.post.call_count, 1)

    def test_missing_configuration_is_not_silenced(self):
        from src.configuration_errors import ConfigurationError

        with patch.object(
            self.client,
            "get_secret",
            side_effect=ConfigurationError(
                "Missing required configuration variable: NEXAR_CLIENT_ID"
            ),
        ):
            with self.assertRaises(ConfigurationError):
                self.client.search_octopart_by_part_number("LM358N")

    def test_graphql_errors_classified_without_leaking_provider_details(self):
        _, graphql = self._responses([])
        graphql.json.return_value = {"errors": [{"message": "private upstream error"}]}
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            with self.assertRaises(self.client.OctopartResponseError) as caught:
                self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(caught.exception.subreason, self.client.SUBREASON_GRAPHQL_ERRORS)
        self.assertNotIn("private upstream", str(caught.exception))

    def test_schema_mismatch_graphql_errors(self):
        classified = self.client.classify_nexar_graphql_payload(
            {
                "errors": [
                    {
                        "message": "Cannot query field 'shortDescription' on type 'SupPart'."
                    }
                ]
            }
        )
        self.assertEqual(classified["subreason"], self.client.SUBREASON_SCHEMA_MISMATCH)
        self.assertFalse(classified["usable"])

    def test_empty_response_classified(self):
        for payload in (None, "", {}):
            classified = self.client.classify_nexar_graphql_payload(payload)
            self.assertEqual(classified["subreason"], self.client.SUBREASON_EMPTY_RESPONSE)
            self.assertFalse(classified["usable"])

    def test_malformed_response_classified(self):
        for payload in ([], "not-json-object", {"data": "oops"}):
            classified = self.client.classify_nexar_graphql_payload(payload)
            self.assertEqual(
                classified["subreason"], self.client.SUBREASON_MALFORMED_RESPONSE
            )
            self.assertFalse(classified["usable"])

    def test_missing_expected_data_classified(self):
        classified = self.client.classify_nexar_graphql_payload({"data": {"other": 1}})
        self.assertEqual(
            classified["subreason"], self.client.SUBREASON_MISSING_EXPECTED_DATA
        )
        self.assertFalse(classified["usable"])

    def test_zero_results_payload_is_usable(self):
        classified = self.client.classify_nexar_graphql_payload(
            {"data": {"supSearchMpn": {"hits": 0, "results": []}}}
        )
        self.assertEqual(classified["subreason"], self.client.SUBREASON_ZERO_RESULTS)
        self.assertTrue(classified["usable"])

        self._responses([], hits=0)
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            result = self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertEqual(result["octopart_subreason"], self.client.SUBREASON_ZERO_RESULTS)
        self.assertEqual(result["octopart_hits"], 0)

    def test_graphql_errors_remain_distinct_from_zero_results(self):
        with_errors = self.client.classify_nexar_graphql_payload(
            {
                "errors": [{"message": "something failed"}],
                "data": {"supSearchMpn": {"hits": 0, "results": []}},
            }
        )
        without_errors = self.client.classify_nexar_graphql_payload(
            {"data": {"supSearchMpn": {"hits": 0, "results": []}}}
        )
        self.assertEqual(with_errors["subreason"], self.client.SUBREASON_GRAPHQL_ERRORS)
        self.assertFalse(with_errors["usable"])
        self.assertEqual(without_errors["subreason"], self.client.SUBREASON_ZERO_RESULTS)
        self.assertTrue(without_errors["usable"])

    def test_malformed_http_json_raises_malformed_response(self):
        token = Mock()
        token.json.return_value = {"access_token": "private-token", "expires_in": 3600}
        graphql = Mock()
        graphql.json.side_effect = ValueError("No JSON")
        self.requests.post.side_effect = [token, graphql]
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            with self.assertRaises(self.client.OctopartResponseError) as caught:
                self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(caught.exception.subreason, self.client.SUBREASON_MALFORMED_RESPONSE)

    def test_requests_use_bounded_timeout_and_bearer_header(self):
        self._responses([self._part()])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            self.client.search_octopart_by_part_number("LM358N")
        token_call, query_call = self.requests.post.call_args_list
        self.assertEqual(token_call.kwargs["timeout"], 15)
        self.assertEqual(query_call.kwargs["timeout"], 15)
        self.assertEqual(
            query_call.kwargs["headers"]["Authorization"], "Bearer private-token"
        )
        self.assertEqual(query_call.kwargs["json"]["variables"]["mpn"], "LM358N")

    def test_supplier_aggregator_registers_octopart(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "integrations"
            / "supplier_aggregator.py"
        ).read_text()
        self.assertIn("from integrations.octopart_client import search_octopart_by_part_number", source)
        self.assertIn('"Octopart"', source)
        self.assertIn("search_octopart_by_part_number", source)


class OctopartDiagnosticPropagationTests(unittest.TestCase):
    def setUp(self):
        sys.modules.setdefault(
            "streamlit", types.SimpleNamespace(cache_data=lambda *a, **k: (lambda f: f))
        )
        sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))
        sys.modules.pop("integrations.supplier_aggregator", None)
        self.aggregator = importlib.import_module("integrations.supplier_aggregator")
        self.diagnostics = importlib.import_module("integrations.supplier_diagnostics")
        self.client = importlib.import_module("integrations.octopart_client")

    def test_request_id_propagates_through_threaded_octopart_lookup(self):
        original_creds = self.diagnostics._octopart_credentials_configured
        self.diagnostics._octopart_credentials_configured = lambda: True
        self.addCleanup(
            lambda: setattr(
                self.diagnostics, "_octopart_credentials_configured", original_creds
            )
        )
        original_callable = self.aggregator._supplier_lookup_callable

        def lookup_callable(source_name):
            if source_name == "Octopart":

                def boom(_part):
                    raise self.client.OctopartResponseError(
                        "Octopart supplier query could not be completed.",
                        subreason=self.client.SUBREASON_GRAPHQL_ERRORS,
                    )

                return boom
            return None

        self.aggregator._supplier_lookup_callable = lookup_callable
        self.addCleanup(
            lambda: setattr(
                self.aggregator, "_supplier_lookup_callable", original_callable
            )
        )

        request_id = "afreqid9abc"
        token = self.diagnostics.set_alternative_finder_request_id(request_id)
        self.addCleanup(
            lambda: self.diagnostics.reset_alternative_finder_request_id(token)
        )

        with self.assertLogs("integrations.supplier_diagnostics", level="WARNING") as logs:
            results = self.aggregator.get_supplier_results("LM358N")

        octopart = next(row for row in results if row.get("source") == "Octopart")
        self.assertEqual(octopart.get("diagnostic_request_id"), request_id)
        self.assertEqual(octopart.get("diagnostic_subreason"), "graphql_errors")
        self.assertEqual(octopart.get("diagnostic_log_category"), "provider_response")
        joined = "\n".join(logs.output)
        self.assertIn(f"request_id={request_id}", joined)
        self.assertIn("subreason=graphql_errors", joined)
        self.assertNotIn("request_id=unknown", joined)
        self.assertNotIn("Bearer ", joined)
        self.assertNotIn("private-token", joined)

    def test_zero_results_is_completed_search_not_outage(self):
        original_creds = self.diagnostics._octopart_credentials_configured
        self.diagnostics._octopart_credentials_configured = lambda: True
        self.addCleanup(
            lambda: setattr(
                self.diagnostics, "_octopart_credentials_configured", original_creds
            )
        )
        original_callable = self.aggregator._supplier_lookup_callable

        def lookup_callable(source_name):
            if source_name == "Octopart":

                def empty(_part):
                    row = self.client.default_octopart_result()
                    row["octopart_subreason"] = self.client.SUBREASON_ZERO_RESULTS
                    return row

                return empty
            return None

        self.aggregator._supplier_lookup_callable = lookup_callable
        self.addCleanup(
            lambda: setattr(
                self.aggregator, "_supplier_lookup_callable", original_callable
            )
        )

        request_id = "zeroreqid123"
        token = self.diagnostics.set_alternative_finder_request_id(request_id)
        self.addCleanup(
            lambda: self.diagnostics.reset_alternative_finder_request_id(token)
        )

        with self.assertLogs("integrations.supplier_diagnostics", level="WARNING") as logs:
            results = self.aggregator.get_supplier_results("NOMATCHPART")

        octopart = next(row for row in results if row.get("source") == "Octopart")
        self.assertEqual(octopart.get("provider_status"), "PART_NOT_FOUND")
        self.assertEqual(octopart.get("failure_category"), self.diagnostics.CATEGORY_NO_RESULT)
        self.assertEqual(octopart.get("diagnostic_subreason"), "zero_results")
        self.assertEqual(octopart.get("diagnostic_request_id"), request_id)
        self.assertEqual(octopart.get("diagnostic_log_category"), "provider_response")

        resolved = self.diagnostics.resolve_supplier_coverage_status(
            "Octopart",
            provider_status=octopart.get("provider_status"),
            failure_category=octopart.get("failure_category"),
        )
        self.assertEqual(resolved["label"], "Octopart: no exact match")
        self.assertFalse(resolved["is_runtime_failure"])
        self.assertNotIn("unavailable", resolved["label"].casefold())

        joined = "\n".join(logs.output)
        self.assertIn(f"request_id={request_id}", joined)
        self.assertIn("subreason=zero_results", joined)
        self.assertNotIn("Bearer ", joined)
        self.assertNotIn("api.nexar.com", joined)

    def test_diagnostic_redaction_strips_tokens_and_urls(self):
        payload = self.diagnostics.log_supplier_diagnostic(
            request_id="redact123",
            supplier="Octopart",
            stage="lookup",
            provider_status="PROVIDER_ERROR",
            error_message=(
                "Authorization: Bearer super-secret-token "
                "https://api.nexar.com/graphql?token=abc"
            ),
            exception_type="OctopartResponseError",
            subreason="malformed_response",
        )
        self.assertEqual(payload["request_id"], "redact123")
        self.assertEqual(payload["subreason"], "malformed_response")
        self.assertEqual(payload["log_category"], "provider_response")
        self.assertNotIn("super-secret-token", payload["message"])
        self.assertNotIn("Bearer ", payload["message"])
        self.assertNotIn("api.nexar.com", payload["message"])
        self.assertNotIn("://", payload["message"])

    def test_http_error_url_containing_graphql_is_not_graphql_subreason(self):
        class _Response:
            status_code = 500

        class _HTTPError(Exception):
            def __init__(self):
                super().__init__(
                    "500 Server Error: Internal Server Error for url: "
                    "https://api.nexar.com/graphql"
                )
                self.response = _Response()

        error = _HTTPError()
        payload = self.diagnostics.log_supplier_diagnostic(
            request_id="httpreqid01",
            supplier="Octopart",
            stage="lookup",
            provider_status="PROVIDER_ERROR",
            error_message=str(error),
            exception_type=type(error).__name__,
            error=error,
        )
        self.assertEqual(payload["category"], self.diagnostics.CATEGORY_HTTP_ERROR)
        self.assertEqual(payload["log_category"], "http")
        self.assertEqual(payload["status_code"], "500")
        self.assertNotEqual(payload["subreason"], "graphql_errors")
        self.assertNotIn("api.nexar.com", payload["message"])


if __name__ == "__main__":
    unittest.main()
