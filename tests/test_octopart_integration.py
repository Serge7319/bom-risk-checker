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

    def _part(self, mpn="LM358N", *, description="Operational amplifier"):
        return {
            "mpn": mpn,
            "manufacturer": {"name": "Texas Instruments"},
            "sellers": [
                {
                    "company": {"name": "Arrow"},
                    "offers": [
                        {
                            "inventoryLevel": 120,
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
            "_description": description,
        }

    def _responses(self, parts, *, hits=None):
        token = Mock()
        token.json.return_value = {"access_token": "private-token", "expires_in": 3600}
        graphql = Mock()
        results = []
        for part in parts:
            row = dict(part)
            description = str(row.pop("_description", "") or "")
            results.append({"description": description, "part": row})
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

    def test_canonical_query_matches_official_nexar_supply_example(self):
        query = self.client.canonical_sup_search_mpn_query()
        self.assertEqual(query, self.client.CANONICAL_SUP_SEARCH_MPN_QUERY)
        self.assertEqual(query, self.client._PART_QUERY)
        self.assertIn("query SearchMpn($mpn: String!, $limit: Int!)", query)
        self.assertIn("supSearchMpn(q: $mpn, limit: $limit)", query)
        self.assertIn("hits", query)
        self.assertIn("description", query)
        self.assertIn("manufacturer {", query)
        self.assertIn("inventoryLevel", query)
        self.assertIn("prices {", query)
        self.assertIn("quantity", query)
        self.assertIn("price", query)
        self.assertEqual(self.client.query_contains_unsupported_fields(query), [])
        self.assertNotIn("clickUrl", query)
        self.assertNotIn("shortDescription", query)
        self.assertNotIn("currency:", query)
        self.assertNotIn("country:", query)
        self.assertNotRegex(query, r"\bpart\s*\{\s*id\b")

    def test_request_builder_emits_documented_query_and_limit_variable(self):
        body = self.client.build_nexar_sup_search_mpn_request("LM358N", limit=5)
        self.assertEqual(body["query"], self.client.CANONICAL_SUP_SEARCH_MPN_QUERY)
        self.assertEqual(body["variables"], {"mpn": "LM358N", "limit": 5})
        self.assertEqual(
            self.client.query_contains_unsupported_fields(body["query"]), []
        )

    def test_authorization_header_uses_bearer_token_form(self):
        headers = self.client.nexar_authorization_headers("private-token")
        self.assertEqual(headers, {"Authorization": "Bearer private-token"})

    def test_query_uses_current_nexar_fields(self):
        query = self.client._PART_QUERY
        self.assertIn("supSearchMpn", query)
        self.assertIn("manufacturer {", query)
        self.assertIn("prices {", query)
        self.assertIn("quantity", query)
        self.assertIn("price", query)
        self.assertIn("inventoryLevel", query)
        self.assertIn("description", query)
        self.assertNotIn("shortDescription", query)
        self.assertNotRegex(query, r"\bpart\s*\{\s*id\b")
        self.assertNotRegex(query, r"\bpart\s*\{\s*id\s*mpn\s*name\b")
        self.assertNotIn("country:", query)
        self.assertNotIn("currency:", query)
        self.assertNotIn("clickUrl", query)

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

    def test_oauth_token_requests_supply_domain_scope(self):
        self._responses([self._part()])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            self.client.search_octopart_by_part_number("LM358N")
        token_call = self.requests.post.call_args_list[0]
        self.assertEqual(token_call.args[0], self.client.TOKEN_URL)
        self.assertEqual(
            token_call.kwargs["data"]["scope"],
            self.client.NEXAR_TOKEN_SCOPE,
        )
        self.assertEqual(token_call.kwargs["data"]["scope"], "supply.domain")

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
        graphql.json.return_value = {"errors": [{"message": "private opaque gate failure xyz"}]}
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            with self.assertRaises(self.client.OctopartResponseError) as caught:
                self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(caught.exception.subreason, self.client.SUBREASON_GRAPHQL_ERRORS)
        self.assertEqual(caught.exception.graphql_kind, self.client.GRAPHQL_KIND_OTHER)
        self.assertTrue(str(caught.exception.error_fingerprint or "").startswith("gql_"))
        self.assertEqual(caught.exception.error_count, 1)
        self.assertNotIn("private opaque", str(caught.exception))
        self.assertNotIn("xyz", str(caught.exception))

    def test_auth_graphql_errors_classified_as_authentication(self):
        from pathlib import Path
        import json

        fixtures = json.loads(
            (
                Path(__file__).resolve().parent
                / "fixtures"
                / "nexar_graphql_errors.json"
            ).read_text(encoding="utf-8")
        )
        for key in ("auth_insufficient_scope", "auth_unauthenticated"):
            payload = fixtures[key]
            inspected = self.client.inspect_nexar_graphql_errors(payload["errors"])
            self.assertEqual(inspected["graphql_kind"], self.client.GRAPHQL_KIND_AUTH)
            self.assertEqual(
                inspected["subreason"], self.client.SUBREASON_AUTHENTICATION
            )
            classified = self.client.classify_nexar_graphql_payload(payload)
            self.assertEqual(
                classified["subreason"], self.client.SUBREASON_AUTHENTICATION
            )
            self.assertTrue(classified["error_codes"])

    def test_fixture_schema_and_generic_kinds(self):
        from pathlib import Path
        import json

        fixtures = json.loads(
            (
                Path(__file__).resolve().parent
                / "fixtures"
                / "nexar_graphql_errors.json"
            ).read_text(encoding="utf-8")
        )
        schema = self.client.inspect_nexar_graphql_errors(
            fixtures["schema_unknown_argument"]["errors"]
        )
        self.assertEqual(schema["graphql_kind"], self.client.GRAPHQL_KIND_SCHEMA)
        self.assertEqual(schema["rejected_fields"], ["currency"])
        path_leaf = self.client.inspect_nexar_graphql_errors(
            fixtures["schema_path_leaf"]["errors"]
        )
        self.assertEqual(path_leaf["graphql_kind"], self.client.GRAPHQL_KIND_SCHEMA)
        self.assertIn("name", path_leaf["rejected_fields"])
        rate = self.client.inspect_nexar_graphql_errors(fixtures["rate_limited"]["errors"])
        self.assertEqual(rate["graphql_kind"], self.client.GRAPHQL_KIND_RATE_LIMIT)
        self.assertEqual(rate["subreason"], self.client.SUBREASON_RATE_LIMIT)
        generic = self.client.inspect_nexar_graphql_errors(
            fixtures["generic_graphql"]["errors"]
        )
        self.assertEqual(generic["graphql_kind"], self.client.GRAPHQL_KIND_PROVIDER)
        self.assertEqual(generic["subreason"], self.client.SUBREASON_PROVIDER_FAILURE)
        self.assertTrue(generic["error_fingerprint"].startswith("gql_"))
        opaque = self.client.inspect_nexar_graphql_errors(
            fixtures["unknown_opaque"]["errors"]
        )
        self.assertEqual(opaque["graphql_kind"], self.client.GRAPHQL_KIND_OTHER)
        self.assertEqual(opaque["subreason"], self.client.SUBREASON_GRAPHQL_ERRORS)
        self.assertTrue(opaque["error_fingerprint"].startswith("gql_"))
        self.assertEqual(opaque["error_count"], 1)
        self.assertNotIn("secret", opaque["error_fingerprint"].casefold())
        self.assertNotIn("token", opaque["error_fingerprint"].casefold())
        self.assertNotIn("nexar.com", opaque["error_fingerprint"].casefold())

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
        self.assertEqual(classified["rejected_fields"], ["shortDescription"])

    def test_live_equivalent_unknown_argument_classified_safely(self):
        """Live-shaped GraphQL validation errors must expose rejected args only."""
        payload = {
            "errors": [
                {
                    "message": "Unknown argument 'currency' on field 'Query.supSearchMpn'.",
                    "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"},
                },
                {
                    "message": "Cannot query field 'clickUrl' on type 'SupOffer'.",
                },
            ]
        }
        inspected = self.client.inspect_nexar_graphql_errors(payload["errors"])
        self.assertEqual(inspected["subreason"], self.client.SUBREASON_SCHEMA_MISMATCH)
        self.assertEqual(inspected["rejected_fields"], ["currency", "clickUrl"])
        self.assertEqual(inspected["error_codes"], ["GRAPHQL_VALIDATION_FAILED"])
        classified = self.client.classify_nexar_graphql_payload(payload)
        self.assertEqual(classified["subreason"], self.client.SUBREASON_SCHEMA_MISMATCH)
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            token = Mock()
            token.json.return_value = {"access_token": "private-token", "expires_in": 3600}
            graphql = Mock()
            graphql.json.return_value = payload
            self.requests.post.side_effect = [token, graphql]
            with self.assertRaises(self.client.OctopartResponseError) as caught:
                self.client.search_octopart_by_part_number("NOMATCH")
        self.assertEqual(caught.exception.subreason, self.client.SUBREASON_SCHEMA_MISMATCH)
        self.assertEqual(list(caught.exception.rejected_fields), ["currency", "clickUrl"])
        self.assertNotIn("private-token", str(caught.exception))
        self.assertNotIn("Bearer", str(caught.exception))

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
        self.assertTrue(str(with_errors.get("error_fingerprint") or "").startswith("gql_"))
        self.assertEqual(with_errors.get("error_count"), 1)
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
        self.assertEqual(
            query_call.kwargs["headers"],
            self.client.nexar_authorization_headers("private-token"),
        )
        self.assertEqual(
            query_call.kwargs["json"],
            self.client.build_nexar_sup_search_mpn_request("LM358N"),
        )
        self.assertEqual(query_call.kwargs["json"]["variables"]["mpn"], "LM358N")
        self.assertEqual(query_call.kwargs["json"]["variables"]["limit"], 5)
        self.assertEqual(
            query_call.kwargs["json"]["query"],
            self.client.CANONICAL_SUP_SEARCH_MPN_QUERY,
        )

    def test_normal_response_contract(self):
        self._responses([self._part(description="Official result description")])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            result = self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(result["manufacturer_part_number"], "LM358N")
        self.assertEqual(result["description"], "Official result description")
        self.assertEqual(result["octopart_subreason"], self.client.SUBREASON_OK)
        self.assertGreater(result["stock_total"], 0)

    def test_http_auth_failure_classified_as_authentication(self):
        token = Mock()
        token.json.return_value = {"access_token": "private-token", "expires_in": 3600}
        graphql = Mock()
        graphql.status_code = 401
        graphql.json.return_value = {"errors": [{"message": "should not leak"}]}
        self.requests.post.side_effect = [token, graphql]
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            with self.assertRaises(self.client.OctopartResponseError) as caught:
                self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(caught.exception.subreason, self.client.SUBREASON_AUTHENTICATION)
        self.assertEqual(caught.exception.graphql_kind, self.client.GRAPHQL_KIND_AUTH)
        self.assertNotIn("should not leak", str(caught.exception))

    def test_schema_failure_contract_via_search(self):
        token = Mock()
        token.json.return_value = {"access_token": "private-token", "expires_in": 3600}
        graphql = Mock()
        graphql.json.return_value = {
            "errors": [
                {
                    "message": "Cannot query field 'shortDescription' on type 'SupPart'.",
                    "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"},
                }
            ]
        }
        self.requests.post.side_effect = [token, graphql]
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            with self.assertRaises(self.client.OctopartResponseError) as caught:
                self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(caught.exception.subreason, self.client.SUBREASON_SCHEMA_MISMATCH)
        self.assertEqual(list(caught.exception.rejected_fields), ["shortDescription"])

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
        # Force a cache_data-capable Streamlit stub even if an earlier test left a
        # partial streamlit module in sys.modules (setdefault would keep it).
        streamlit = types.ModuleType("streamlit")
        streamlit.cache_data = lambda *a, **k: (lambda f: f)
        streamlit.secrets = {}
        sys.modules["streamlit"] = streamlit
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
                        rejected_fields=["shortDescription"],
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
        self.assertIn("rejected_fields=shortDescription", joined)

    def test_unknown_graphql_emits_fingerprint_not_raw_message(self):
        from pathlib import Path
        import json

        fixtures = json.loads(
            (
                Path(__file__).resolve().parent
                / "fixtures"
                / "nexar_graphql_errors.json"
            ).read_text(encoding="utf-8")
        )
        errors = fixtures["unknown_opaque"]["errors"]
        inspected = self.client.inspect_nexar_graphql_errors(errors)
        fingerprint = inspected["error_fingerprint"]
        self.assertTrue(fingerprint.startswith("gql_1_"))
        self.assertEqual(inspected["error_count"], 1)

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
                        graphql_kind=self.client.GRAPHQL_KIND_OTHER,
                        error_fingerprint=fingerprint,
                        error_count=1,
                    )

                return boom
            return None

        self.aggregator._supplier_lookup_callable = lookup_callable
        self.addCleanup(
            lambda: setattr(
                self.aggregator, "_supplier_lookup_callable", original_callable
            )
        )

        with self.assertLogs("integrations.supplier_diagnostics", level="WARNING") as logs:
            results = self.aggregator.get_supplier_results("LM358N")

        octopart = next(row for row in results if row.get("source") == "Octopart")
        self.assertEqual(octopart.get("diagnostic_error_fingerprint"), fingerprint)
        self.assertEqual(octopart.get("diagnostic_error_count"), "1")
        joined = "\n".join(logs.output)
        self.assertIn(f"error_fingerprint={fingerprint}", joined)
        self.assertIn("error_count=1", joined)
        self.assertIn("graphql_kind=other", joined)
        self.assertNotIn("policy gate", joined)
        self.assertNotIn("7f3a9c", joined)
        self.assertNotIn("request_id=unknown", joined)
        self.assertNotIn("Bearer ", joined)
        self.assertNotIn("private-token", joined)

    def test_worker_diagnostics_inherit_request_id_after_contextvar_cleared(self):
        """Fallback/worker paths must use the AF stack/last id, never unknown."""
        original_creds = self.diagnostics._octopart_credentials_configured
        self.diagnostics._octopart_credentials_configured = lambda: True
        self.addCleanup(
            lambda: setattr(
                self.diagnostics, "_octopart_credentials_configured", original_creds
            )
        )
        original_callable = self.aggregator._supplier_lookup_callable

        def lookup_callable(source_name):
            if source_name in {"Mouser", "DigiKey", "Newark", "Octopart"}:

                def empty(_part):
                    row = self.client.default_octopart_result() if source_name == "Octopart" else {
                        "source": source_name,
                        "manufacturer_part_number": "",
                    }
                    if source_name == "Octopart":
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

        request_id = "stackreq99aa"
        token = self.diagnostics.set_alternative_finder_request_id(request_id)
        # Simulate Streamlit/cache worker frame where ContextVar is empty but the
        # AF search stack/last id remains.
        self.diagnostics._current_request_id.set("")
        self.addCleanup(
            lambda: self.diagnostics.reset_alternative_finder_request_id(token)
        )

        with self.assertLogs("integrations.supplier_diagnostics", level="WARNING") as logs:
            # Explicitly omit request_id argument to force inheritance.
            results = self.aggregator.get_supplier_results("NOMATCHPART", request_id="")

        for row in results:
            self.assertEqual(row.get("diagnostic_request_id"), request_id)
            self.assertNotEqual(row.get("diagnostic_request_id"), "unknown")
        joined = "\n".join(logs.output)
        self.assertIn(f"request_id={request_id}", joined)
        self.assertNotIn("request_id=unknown", joined)
        octopart = next(row for row in results if row.get("source") == "Octopart")
        self.assertEqual(octopart.get("diagnostic_subreason"), "zero_results")
        self.assertEqual(octopart.get("provider_status"), "PART_NOT_FOUND")

    def test_bind_helper_propagates_session_request_id_into_lookup(self):
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
                        subreason=self.client.SUBREASON_SCHEMA_MISMATCH,
                        rejected_fields=["currency"],
                    )

                return boom
            return None

        self.aggregator._supplier_lookup_callable = lookup_callable
        self.addCleanup(
            lambda: setattr(
                self.aggregator, "_supplier_lookup_callable", original_callable
            )
        )

        request_id = "sessionbind01"
        with self.diagnostics.bind_alternative_finder_request_id(request_id):
            with self.assertLogs("integrations.supplier_diagnostics", level="WARNING") as logs:
                results = self.aggregator.get_supplier_results("LM358N", request_id="")

        octopart = next(row for row in results if row.get("source") == "Octopart")
        self.assertEqual(octopart.get("diagnostic_request_id"), request_id)
        self.assertEqual(octopart.get("diagnostic_subreason"), "schema_mismatch")
        self.assertEqual(octopart.get("diagnostic_rejected_fields"), "currency")
        joined = "\n".join(logs.output)
        self.assertIn(f"request_id={request_id}", joined)
        self.assertIn("rejected_fields=currency", joined)
        self.assertNotIn("request_id=unknown", joined)

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

    def test_newark_http_500_with_apikey_url_is_http_not_auth(self):
        """Element14 URLs embed apiKey; 500 must not be mislabeled as auth."""
        class _Response:
            status_code = 500

        class _HTTPError(Exception):
            def __init__(self):
                super().__init__(
                    "500 Server Error: Internal Server Error for url: "
                    "https://api.element14.com/catalog/products?"
                    "callInfo.apiKey=secret-newark-key&term=manuPartNum:LM358"
                )
                self.response = _Response()

        error = _HTTPError()
        from integrations.provider_health import sanitize_provider_message

        safe = sanitize_provider_message(error)
        self.assertNotIn("secret-newark-key", safe)
        self.assertNotIn("authentication", safe.casefold())

        payload = self.diagnostics.log_supplier_diagnostic(
            request_id="newark500aa",
            supplier="Newark",
            stage="lookup",
            provider_status="PROVIDER_ERROR",
            error_message=safe,
            exception_type=type(error).__name__,
            error=error,
        )
        self.assertEqual(payload["status_code"], "500")
        self.assertEqual(payload["category"], self.diagnostics.CATEGORY_HTTP_ERROR)
        self.assertEqual(payload["log_category"], "http")
        self.assertNotEqual(payload["log_category"], "auth")
        self.assertNotIn("secret-newark-key", "\n".join(str(v) for v in payload.values()))

        label = self.diagnostics.supplier_coverage_label(
            "Newark",
            "PROVIDER_ERROR",
            failure_category=payload["category"],
            error_message=safe,
        )
        self.assertTrue(label.startswith("Newark: unavailable"))
        self.assertNotIn("not configured", label.casefold())
        self.assertNotIn("no exact match", label.casefold())

    def test_newark_http_401_remains_auth(self):
        class _Response:
            status_code = 401

        class _HTTPError(Exception):
            def __init__(self):
                super().__init__(
                    "401 Client Error: Unauthorized for url: "
                    "https://api.element14.com/catalog/products?callInfo.apiKey=secret"
                )
                self.response = _Response()

        error = _HTTPError()
        payload = self.diagnostics.log_supplier_diagnostic(
            request_id="newark401aa",
            supplier="Newark",
            stage="lookup",
            provider_status="PROVIDER_ERROR",
            error_message=str(error),
            exception_type=type(error).__name__,
            error=error,
        )
        self.assertEqual(payload["status_code"], "401")
        self.assertEqual(payload["category"], self.diagnostics.CATEGORY_AUTHENTICATION)
        self.assertEqual(payload["log_category"], "auth")


if __name__ == "__main__":
    unittest.main()
