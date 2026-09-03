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

    def _part(self, mpn="LM358N"):
        return {
            "mpn": mpn,
            "manufacturer": {"name": "Texas Instruments"},
            "shortDescription": "Operational amplifier",
            "sellers": [
                {"company": {"name": "Arrow"}, "offers": [{"inventoryLevel": 120, "clickUrl": "https://example.com/a", "prices": [{"quantity": 1, "price": 0.62, "currency": "USD"}]}]},
                {"company": {"name": "Avnet"}, "offers": [{"inventoryLevel": 80, "prices": [{"quantity": 1, "price": 0.48, "currency": "USD"}]}]},
            ],
        }

    def _responses(self, parts):
        token = Mock()
        token.json.return_value = {"access_token": "private-token", "expires_in": 3600}
        graphql = Mock()
        graphql.json.return_value = {"data": {"supSearchMpn": {"results": [{"part": part} for part in parts]}}}
        self.requests.post.side_effect = [token, graphql]
        return token, graphql

    def _secrets(self, name, **kwargs):
        return {"NEXAR_CLIENT_ID": "client-id", "NEXAR_CLIENT_SECRET": "private-secret"}[name]

    def test_exact_match_normalizes_inventory_price_and_sellers(self):
        self._responses([self._part()])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            result = self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(result["manufacturer_part_number"], "LM358N")
        self.assertEqual(result["manufacturer"], "Texas Instruments")
        self.assertEqual(result["stock_total"], 200)
        self.assertEqual(result["unit_price"], 0.48)
        self.assertEqual(result["octopart_sellers"], ["Arrow", "Avnet"])

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

    def test_similar_part_is_rejected(self):
        self._responses([self._part("LM358P")])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            result = self.client.search_octopart_by_part_number("LM358N")
        self.assertEqual(result["manufacturer_part_number"], "")

    def test_empty_part_never_requests_credentials_or_network(self):
        with patch.object(self.client, "get_secret") as secret:
            result = self.client.search_octopart_by_part_number("  ")
        self.assertEqual(result["supplier_count"], 0)
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
        with patch.object(self.client, "get_secret", side_effect=ConfigurationError("Missing required configuration variable: NEXAR_CLIENT_ID")):
            with self.assertRaises(ConfigurationError):
                self.client.search_octopart_by_part_number("LM358N")

    def test_graphql_errors_do_not_leak_provider_details(self):
        _, graphql = self._responses([])
        graphql.json.return_value = {"errors": [{"message": "private upstream error"}]}
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            with self.assertRaisesRegex(RuntimeError, "could not be completed") as caught:
                self.client.search_octopart_by_part_number("LM358N")
        self.assertNotIn("private upstream", str(caught.exception))

    def test_requests_use_bounded_timeout_and_bearer_header(self):
        self._responses([self._part()])
        with patch.object(self.client, "get_secret", side_effect=self._secrets):
            self.client.search_octopart_by_part_number("LM358N")
        token_call, query_call = self.requests.post.call_args_list
        self.assertEqual(token_call.kwargs["timeout"], 15)
        self.assertEqual(query_call.kwargs["timeout"], 15)
        self.assertEqual(query_call.kwargs["headers"]["Authorization"], "Bearer private-token")
        self.assertEqual(query_call.kwargs["json"]["variables"]["mpn"], "LM358N")

    def test_supplier_aggregator_registers_octopart(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "integrations" / "supplier_aggregator.py").read_text()
        self.assertIn('(\"Octopart\", search_octopart_by_part_number)', source)


if __name__ == "__main__":
    unittest.main()
