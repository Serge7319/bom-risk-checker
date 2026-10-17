"""Exact-MPN fallback coverage for Mouser keyword-only listings."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import Mock


class MouserKeywordFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_requests = sys.modules.get("requests")
        cls.original_client = sys.modules.pop("integrations.mouser_client", None)
        cls.requests = types.ModuleType("requests")
        cls.requests.post = Mock()
        sys.modules["requests"] = cls.requests
        cls.client = importlib.import_module("integrations.mouser_client")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("integrations.mouser_client", None)
        if cls.original_client is not None:
            sys.modules["integrations.mouser_client"] = cls.original_client
        if cls.original_requests is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = cls.original_requests

    def setUp(self):
        self.requests.post.reset_mock()
        self.client.get_secret = Mock(return_value="test-key")

    @staticmethod
    def _response(parts):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"SearchResults": {"Parts": parts}}
        return response

    @staticmethod
    def _part(mpn, *, datasheet="", lifecycle="Active"):
        return {
            "ManufacturerPartNumber": mpn,
            "MouserPartNumber": f"123-{mpn}",
            "Manufacturer": "Aosong",
            "Description": "Humidity and temperature sensor",
            "Availability": "1,000 In Stock",
            "LifecycleStatus": lifecycle,
            "DataSheetUrl": datasheet,
        }

    def test_keyword_fallback_returns_datasheet_only_for_exact_mpn(self):
        datasheet_url = "https://www.mouser.com/datasheet/dht11.pdf"
        self.requests.post.side_effect = [
            self._response([self._part("DHT11M")]),
            self._response([self._part("DHT11", datasheet=datasheet_url)]),
        ]

        result = self.client.search_mouser_by_part_number("DHT11")

        self.assertEqual(result["manufacturer_part_number"], "DHT11")
        self.assertEqual(result["datasheet_url"], datasheet_url)
        self.assertEqual(result["lifecycle_status"], "Active")
        self.assertEqual(self.requests.post.call_count, 2)
        keyword_call = self.requests.post.call_args_list[1]
        self.assertIn("/search/keyword?", keyword_call.args[0])
        self.assertEqual(
            keyword_call.kwargs["json"]["SearchByKeywordRequest"],
            {"keyword": "DHT11", "records": 50, "startingRecord": 0},
        )

    def test_keyword_family_neighbor_cannot_supply_datasheet(self):
        self.requests.post.side_effect = [
            self._response([]),
            self._response(
                [self._part("DHT11M", datasheet="https://example.com/neighbor.pdf")]
            ),
        ]

        result = self.client.search_mouser_by_part_number("DHT11")

        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertEqual(result["datasheet_url"], "")
        self.assertEqual(result["supplier_count"], 0)

    def test_exact_part_number_result_skips_keyword_fallback(self):
        self.requests.post.side_effect = [
            self._response(
                [self._part("DHT11", datasheet="https://example.com/dht11.pdf")]
            )
        ]

        result = self.client.search_mouser_by_part_number("DHT11")

        self.assertEqual(result["manufacturer_part_number"], "DHT11")
        self.assertEqual(self.requests.post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
