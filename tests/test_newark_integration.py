"""Focused Newark supplier integration and sourcing-visibility regressions."""
from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class NewarkIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module_names = (
            "streamlit",
            "requests",
            "dotenv",
            "src.parsing",
            "src.parsing.electrical_extractors",
            "src.performance_timing",
            "integrations.mouser_client",
            "integrations.digikey_client",
            "integrations.newark_client",
            "integrations.provider_health",
            "integrations.supplier_aggregator",
        )
        cls.original_modules = {
            name: sys.modules.get(name) for name in cls.module_names
        }

        streamlit = types.ModuleType("streamlit")
        streamlit.secrets = {}
        streamlit.cache_data = lambda **kwargs: lambda function: function
        sys.modules["streamlit"] = streamlit

        cls.requests = types.ModuleType("requests")
        cls.requests.get = Mock()
        sys.modules["requests"] = cls.requests

        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda: None
        sys.modules["dotenv"] = dotenv

        parsing = types.ModuleType("src.parsing")
        parsing.__path__ = []
        sys.modules["src.parsing"] = parsing
        extractors = types.ModuleType("src.parsing.electrical_extractors")
        extractors.extract_frequency_mhz = lambda value: None
        extractors.extract_current_na = lambda value: None
        extractors.extract_current_ma = lambda value: None
        sys.modules["src.parsing.electrical_extractors"] = extractors

        timing = types.ModuleType("src.performance_timing")
        timing.emit_timing = lambda *args, **kwargs: None
        timing.normalize_provider = lambda name: str(name).lower()
        timing.supplier_outcome_from_status = lambda status: str(status).lower()
        timing.timing_enabled = lambda: False
        sys.modules["src.performance_timing"] = timing

        mouser = types.ModuleType("integrations.mouser_client")
        mouser.search_mouser_by_part_number = lambda part: {}
        sys.modules["integrations.mouser_client"] = mouser
        digikey = types.ModuleType("integrations.digikey_client")
        digikey.search_digikey_by_part_number = lambda part: {}
        sys.modules["integrations.digikey_client"] = digikey

        for name in (
            "integrations.newark_client",
            "integrations.provider_health",
            "integrations.supplier_aggregator",
        ):
            sys.modules.pop(name, None)

        cls.newark = importlib.import_module("integrations.newark_client")
        cls.health = importlib.import_module("integrations.provider_health")
        cls.aggregator = importlib.import_module("integrations.supplier_aggregator")

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def setUp(self):
        self.requests.get.reset_mock()
        self.requests.get.side_effect = None

    def _product(self, mpn="LM358N", **overrides):
        product = {
            "translatedManufacturerPartNumber": mpn,
            "manufacturerPartNumber": mpn,
            "brandName": "Texas Instruments",
            "displayName": "Operational amplifier DIP-8",
            "stock": {"level": 125, "leastLeadTime": 14},
            "prices": [{"cost": "$0.42", "from": 1}],
            "productStatus": "Active",
            "productUrl": "https://www.newark.com/example",
        }
        product.update(overrides)
        return product

    def _response(self, products, *, response_key="manufacturerPartNumberSearchReturn"):
        response = Mock()
        response.json.return_value = {response_key: {"products": products}}
        self.requests.get.return_value = response
        return response

    def test_exact_match_returns_normalized_newark_result(self):
        self._response([self._product()])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("LM358N")

        self.assertEqual(result["source"], "Newark")
        self.assertEqual(result["manufacturer_part_number"], "LM358N")
        self.assertEqual(result["stock_total"], 125)
        self.assertEqual(result["unit_price"], 0.42)
        self.assertEqual(result["unit_price_currency"], "USD")
        self.assertEqual(result["price_breaks"][0]["currency"], "USD")
        self.assertEqual(result["lead_time_weeks"], 2.0)

    def test_catalog_candidate_search_uses_bounded_family_keywords(self):
        exact_response = {
            "keywordSearchReturn": {"products": [self._product("LM317DCYR")]}
        }
        family_response = {
            "keywordSearchReturn": {"products": [
                self._product("LM317DCYR"),
                self._product("LM317MDCYR", primaryCategory="Integrated Circuits"),
            ]}
        }
        self.requests.get.side_effect = [
            Mock(json=Mock(return_value=exact_response), raise_for_status=Mock()),
            Mock(json=Mock(return_value=family_response), raise_for_status=Mock()),
        ]
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            rows = self.newark.search_newark_catalog_candidates("LM317DCYR")

        self.assertEqual([row["manufacturer_part_number"] for row in rows], ["LM317MDCYR"])
        self.assertEqual(rows[0]["source"], "Newark")
        self.assertEqual(rows[0]["discovery_scope"], "family_search")
        self.assertEqual(rows[0]["discovery_query"], "LM317")
        self.assertEqual(rows[0]["primary_category"], "Integrated Circuits")
        self.assertEqual(rows[0]["lifecycle_status"], "Active")
        self.assertEqual(self.requests.get.call_count, 2)
        self.assertTrue(all("any:" in call.kwargs["params"]["term"] for call in self.requests.get.call_args_list))
        self.assertEqual(
            [call.kwargs["params"]["term"] for call in self.requests.get.call_args_list],
            ["any:LM317DCYR", "any:LM317"],
        )

    def test_catalog_family_search_covers_dht_sensor_series(self):
        self.requests.get.side_effect = [
            Mock(json=Mock(return_value={
                "keywordSearchReturn": {"products": [self._product("DHT11", primaryCategory="Sensors")]}
            }), raise_for_status=Mock()),
            Mock(json=Mock(return_value={
                "keywordSearchReturn": {"products": [
                    self._product("DHT11", primaryCategory="Sensors"),
                    self._product("DHT22", primaryCategory="Sensors"),
                ]}
            }), raise_for_status=Mock()),
        ]
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            rows = self.newark.search_newark_catalog_candidates("DHT11")

        self.assertEqual([row["manufacturer_part_number"] for row in rows], ["DHT22"])
        self.assertEqual(rows[0]["discovery_scope"], "family_search")
        self.assertEqual(rows[0]["discovery_query"], "DHT")
        self.assertEqual(self.requests.get.call_count, 2)

    def test_part_match_is_case_insensitive_and_trims_outer_whitespace(self):
        self._response([self._product("lm358n")])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("  LM358N  ")

        self.assertEqual(result["manufacturer_part_number"], "lm358n")

    def test_exact_match_can_be_second_returned_product(self):
        self._response([self._product("LM358P"), self._product("LM358N")])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("LM358N")

        self.assertEqual(result["manufacturer_part_number"], "LM358N")

    def test_related_but_different_part_is_not_accepted(self):
        self._response([self._product("LM358P")])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("LM358N")

        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertEqual(result["supplier_count"], 0)

    def test_separator_only_mpn_formatting_difference_is_accepted(self):
        self._response([self._product("IRF-540N")])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("IRF540N")

        self.assertEqual(result["manufacturer_part_number"], "IRF-540N")
        self.assertEqual(result["unit_price"], 0.42)

    def test_suffix_variant_is_not_accepted_as_exact_mpn(self):
        self._response([self._product("IRF540NPBF")])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("IRF540N")

        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertEqual(result["supplier_count"], 0)

    def test_raw_manufacturer_part_number_can_match(self):
        product = self._product(
            "WRONG-TRANSLATED", manufacturerPartNumber="LM358N"
        )
        self._response([product])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("LM358N")

        self.assertEqual(result["source"], "Newark")
        self.assertEqual(result["manufacturer_part_number"], "LM358N")

    def test_keyword_response_requires_same_exact_match(self):
        self._response([self._product()], response_key="keywordSearchReturn")
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("LM358N")

        self.assertEqual(result["manufacturer_part_number"], "LM358N")

    def test_empty_part_does_not_request_credentials_or_network(self):
        with patch.object(self.newark, "get_secret") as get_secret:
            result = self.newark.search_newark_by_part_number("   ")

        self.assertEqual(result["manufacturer_part_number"], "")
        get_secret.assert_not_called()
        self.requests.get.assert_not_called()

    def test_request_uses_newark_store_bounded_timeout_and_five_candidates(self):
        self._response([self._product()])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            self.newark.search_newark_by_part_number(" LM358N ")

        _, kwargs = self.requests.get.call_args
        self.assertEqual(kwargs["timeout"], 15)
        self.assertEqual(kwargs["params"]["storeInfo.id"], "www.newark.com")
        self.assertEqual(kwargs["params"]["resultsSettings.numberOfResults"], 5)
        self.assertEqual(kwargs["params"]["term"], "manuPartNum:LM358N")

    def test_missing_status_is_unknown_not_active(self):
        self.assertEqual(self.newark.infer_newark_lifecycle({}), "Unknown")

    def test_rohs_status_does_not_invent_product_lifecycle(self):
        self.assertEqual(
            self.newark.infer_newark_lifecycle({"rohsStatusCode": "Compliant"}),
            "Unknown",
        )

    def test_explicit_active_obsolete_and_nrnd_are_preserved(self):
        self.assertEqual(
            self.newark.infer_newark_lifecycle({"productStatus": "Active"}),
            "Active",
        )
        self.assertEqual(
            self.newark.infer_newark_lifecycle({"status": "Obsolete"}),
            "Obsolete",
        )
        self.assertEqual(
            self.newark.infer_newark_lifecycle({"status": "Not recommended"}),
            "NRND",
        )

    def test_missing_newark_api_key_is_not_configured(self):
        from src.configuration_errors import ConfigurationError

        error = ConfigurationError("Missing required configuration variable: NEWARK_API_KEY")
        self.assertEqual(
            self.health.classify_provider_exception(error),
            self.health.PROVIDER_NOT_CONFIGURED,
        )

    def test_safe_lookup_reports_missing_newark_configuration(self):
        from src.configuration_errors import ConfigurationError

        def lookup(part):
            raise ConfigurationError("Missing required configuration variable: NEWARK_API_KEY")

        result = self.aggregator._safe_supplier_lookup("Newark", lookup, "LM358N")
        self.assertEqual(result["provider_status"], self.health.PROVIDER_NOT_CONFIGURED)
        self.assertNotIn("NEWARK_API_KEY", result["error"])

    def test_mismatched_newark_result_is_part_not_found(self):
        result = self.aggregator._safe_supplier_lookup(
            "Newark", lambda part: self.newark.default_newark_result(part), "LM358N"
        )
        self.assertEqual(result["provider_status"], self.health.PROVIDER_PART_NOT_FOUND)

    def test_provider_health_names_available_and_unconfigured_suppliers(self):
        summary = self.health.summarize_provider_health(
            [
                {"source": "Mouser", "provider_status": self.health.PROVIDER_AVAILABLE},
                {"source": "Newark", "provider_status": self.health.PROVIDER_NOT_CONFIGURED},
            ]
        )
        self.assertEqual(summary["available_sources"], ["Mouser"])
        self.assertEqual(summary["not_configured_sources"], ["Newark"])
        self.assertEqual(summary["configured_count"], 1)
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(summary["failed_sources"], [])

    def test_newark_is_included_in_aggregate_supplier_names_and_counts(self):
        results = [
            {
                "source": "Mouser",
                "provider_status": self.health.PROVIDER_AVAILABLE,
                "manufacturer_part_number": "LM358N",
                "stock_total": 50,
            },
            {
                "source": "Newark",
                "provider_status": self.health.PROVIDER_AVAILABLE,
                "manufacturer_part_number": "LM358N",
                "stock_total": 125,
            },
        ]
        with patch.object(self.aggregator, "get_supplier_results", return_value=results):
            result = self.aggregator.get_best_part_data("LM358N")

        self.assertEqual(result["supplier_count"], 2)
        self.assertEqual(result["total_market_stock"], 175)
        self.assertIn("Newark", result["sources_available"])
        self.assertEqual(result["source"], "Newark")

    def test_supplier_import_only_handles_import_errors(self):
        source = (ROOT / "integrations/supplier_aggregator.py").read_text()
        self.assertIn("except ImportError as newark_import_error:", source)
        self.assertNotIn("except Exception:\n    search_newark_by_part_number = None", source)

    def test_bom_results_show_available_supplier_names(self):
        # The legacy Streamlit BOM table now renders a single "Supplier" column
        # for the best source, while per-row "Sources Available" carries every
        # verified supplier name.
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        display_start = source.index("display_columns = [", source.index("visible = visible.reset_index(drop=True)"))
        display_end = source.index("display_components = visible[display_columns]", display_start)
        self.assertIn('"Supplier"', source[display_start:display_end])
        self.assertIn('"Sources Available": part_data.get("sources_available", "")', source)
        self.assertIn("**Available Suppliers:** ", source)

    def test_saved_component_details_use_persisted_primary_supplier(self):
        source = (ROOT / "src/pages/analysis_detail.py").read_text()
        detail_start = source.index('"source": _safe(', source.index("def _part_signals") if "def _part_signals" in source else 0)
        detail_end = source.index('"url": _safe(', detail_start)
        block = source[detail_start:detail_end]
        self.assertIn('"primary_supplier"', block)
        self.assertIn('"Not recorded"', block)

    def test_existing_bom_and_alternative_supplier_paths_remain_intact(self):
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        self.assertIn('"Sources Available": part_data.get("sources_available", "")', source)
        self.assertIn("run_alternative_finder_search(", source)

    def test_alternative_candidates_use_discovery_evidence_without_per_candidate_lookup(self):
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        self.assertNotIn("supplier_data = get_best_part_data(candidate_part)", source)
        self.assertIn("run_alternative_finder_search(", source)
        self.assertIn("get_or_enrich_selected_candidate(", source)
        self.assertIn("candidate_evidence_data = get_best_part_data(selected_alternative)", source)

    def test_original_component_shows_all_verified_suppliers(self):
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        self.assertIn("Verified Suppliers", source)
        self.assertIn('["sources_available", "source"]', source)

    def test_unknown_replacement_price_is_not_reported_as_free(self):
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        self.assertIn("if original_price > 0 and alternative_price > 0:", source)


    # ---- Acceptance C: URL provenance, null stock/price, outcomes ----

    def test_provider_product_url_is_verified_listing(self):
        result = self.newark.normalize_newark_product(self._product())
        self.assertEqual(result["product_detail_url"], "https://www.newark.com/example")
        self.assertTrue(result["listing_verified"])
        self.assertEqual(result["listing_url_provenance"], "provider_product_url")
        self.assertFalse(result["provenance_unavailable"])

    def test_arbitrary_https_host_is_not_verified(self):
        result = self.newark.resolve_newark_listing(
            self._product(productUrl="https://evil.example/product/1", sku="58K1234"),
            allow_sku_lookup=False,
        )
        self.assertEqual(result["product_detail_url"], "")
        self.assertFalse(result["listing_verified"])
        self.assertTrue(result["provenance_unavailable"])

    def test_http_newark_url_is_not_verified(self):
        result = self.newark.resolve_newark_listing(
            self._product(productUrl="http://www.newark.com/example", sku="58K1234"),
            allow_sku_lookup=False,
        )
        self.assertEqual(result["product_detail_url"], "")
        self.assertTrue(result["provenance_unavailable"])

    def test_missing_product_url_uses_documented_sku_lookup_when_official(self):
        product = self._product(productUrl="", sku="58K1234")

        def _lookup(**kwargs):
            self.assertEqual(kwargs["sku"], "58K1234")
            return {
                "product_detail_url": "https://www.newark.com/ti/lm358dr/dp/58K1234",
                "listing_verified": True,
                "listing_url_provenance": "provider_sku_lookup",
                "provenance_unavailable": False,
                "supplier_sku": "58K1234",
            }

        result = self.newark.resolve_newark_listing(product, lookup=_lookup)
        self.assertEqual(
            result["product_detail_url"],
            "https://www.newark.com/ti/lm358dr/dp/58K1234",
        )
        self.assertTrue(result["listing_verified"])
        self.assertEqual(result["listing_url_provenance"], "provider_sku_lookup")

    def test_missing_product_url_stays_unavailable_when_lookup_cannot_resolve(self):
        product = self._product(productUrl="", sku="58K1234")
        result = self.newark.resolve_newark_listing(
            product,
            lookup=lambda **_kwargs: {
                "product_detail_url": "",
                "listing_verified": False,
                "listing_url_provenance": "provenance_unavailable",
                "provenance_unavailable": True,
                "supplier_sku": "58K1234",
            },
        )
        self.assertEqual(result["product_detail_url"], "")
        self.assertFalse(result["listing_verified"])
        self.assertTrue(result["provenance_unavailable"])
        self.assertEqual(result.get("supplier_sku"), "58K1234")

    def test_missing_url_and_sku_never_invents_identifier(self):
        product = self._product(productUrl="", productId="not-a-newark-sku-123", id="abc")
        product.pop("sku", None)
        result = self.newark.normalize_newark_product(product)
        self.assertEqual(result["product_detail_url"], "")
        self.assertFalse(result["listing_verified"])
        self.assertTrue(result["provenance_unavailable"])
        self.assertEqual(result["listing_url_provenance"], "provenance_unavailable")

    def test_malformed_sku_is_not_used_to_build_a_url(self):
        for bad in ("../etc", "58K 1234", "x", "a" * 40, None, 123):
            with self.subTest(sku=bad):
                result = self.newark.normalize_newark_product(
                    self._product(productUrl=None, sku=bad)
                )
                self.assertEqual(result["product_detail_url"], "")
                self.assertTrue(result["provenance_unavailable"])

    def test_non_http_product_url_is_rejected(self):
        result = self.newark.normalize_newark_product(
            self._product(productUrl="javascript:alert(1)")
        )
        self.assertEqual(result["product_detail_url"], "")
        self.assertFalse(result["listing_verified"])

    def test_missing_stock_and_price_are_none_not_zero(self):
        product = self._product()
        product.pop("stock")
        product.pop("prices")
        self.assertIsNone(self.newark.extract_newark_stock(product))
        self.assertIsNone(self.newark.extract_newark_price(product))
        normalized = self.newark.normalize_newark_product(product)
        self.assertIsNone(normalized["stock_total"])
        self.assertIsNone(normalized["unit_price"])
        self.assertIsNone(normalized["lead_time_weeks"])

    def test_malformed_stock_and_price_are_none(self):
        self.assertIsNone(self.newark.extract_newark_stock({"stock": {"level": "n/a"}}))
        self.assertIsNone(self.newark.extract_newark_stock({"stock": {"level": None}}))
        self.assertIsNone(self.newark.extract_newark_stock({"stock": "In stock"}))
        self.assertIsNone(self.newark.extract_newark_price({"prices": [{"cost": ""}]}))
        self.assertIsNone(self.newark.extract_newark_price({"prices": [{"cost": "call"}]}))
        self.assertIsNone(self.newark.extract_newark_price({"prices": [{"cost": 0}]}))
        self.assertIsNone(self.newark.extract_newark_price({"prices": ["bad"]}))

    def test_explicit_zero_stock_is_preserved_as_zero(self):
        self.assertEqual(self.newark.extract_newark_stock({"stock": {"level": 0}}), 0)
        self.assertEqual(self.newark.extract_newark_stock({"stock": {"level": "1,250"}}), 1250)

    def test_exact_hit_carries_retrieved_at_and_exact_identity(self):
        self._response([self._product("LM358N")])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("lm358n")
        self.assertEqual(result["manufacturer_part_number"], "LM358N")
        self.assertEqual(result["requested_part_number"], "lm358n")
        self.assertEqual(result["manufacturer"], "Texas Instruments")
        from datetime import datetime

        stamp = datetime.fromisoformat(result["retrieved_at"])
        self.assertIsNotNone(stamp.tzinfo)

    def test_no_hit_default_is_unverified_with_null_stock_and_price(self):
        self._response([])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.newark.search_newark_by_part_number("NOPE123")
        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertIsNone(result["stock_total"])
        self.assertIsNone(result["unit_price"])
        self.assertEqual(result["product_detail_url"], "")
        self.assertFalse(result["listing_verified"])
        self.assertTrue(result["provenance_unavailable"])

    def test_aggregator_marks_missing_newark_price_and_stock_unknown(self):
        product = self._product(productUrl="")
        product.pop("stock")
        product.pop("prices")
        self._response([product])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.aggregator._safe_supplier_lookup(
                "Newark", self.newark.search_newark_by_part_number, "LM358N"
            )
        self.assertEqual(result["provider_status"], self.health.PROVIDER_AVAILABLE)
        self.assertIsNone(result["stock_total"])
        self.assertFalse(result["unit_price_known"])
        self.assertFalse(result["listing_verified"])
        self.assertEqual(result["product_detail_url"], "")

    def _failing_lookup(self, error):
        def lookup(_part):
            raise error

        return lookup

    def test_timeout_http_auth_and_malformed_are_failures_not_no_hit(self):
        class _Resp:
            def __init__(self, status):
                self.status_code = status

        class _HTTPError(Exception):
            def __init__(self, message, status):
                super().__init__(message)
                self.response = _Resp(status)

        no_hit = self.aggregator._safe_supplier_lookup(
            "Newark", lambda part: self.newark.default_newark_result(part), "LM358N"
        )
        self.assertEqual(no_hit["provider_status"], self.health.PROVIDER_PART_NOT_FOUND)

        cases = {
            "timeout": (Exception("Read timed out"), self.health.PROVIDER_TIMEOUT),
            "http_500": (_HTTPError("500 Server Error", 500), self.health.PROVIDER_ERROR),
            "rate_limit": (_HTTPError("429 Too Many Requests", 429), self.health.PROVIDER_RATE_LIMITED),
            "auth": (_HTTPError("401 Unauthorized", 401), self.health.PROVIDER_ERROR),
        }
        for label, (error, expected) in cases.items():
            with self.subTest(label=label):
                result = self.aggregator._safe_supplier_lookup(
                    "Newark", self._failing_lookup(error), "LM358N"
                )
                self.assertEqual(result["provider_status"], expected)
                self.assertNotEqual(result["provider_status"], no_hit["provider_status"])
                self.assertIsNone(result["stock_total"])
                self.assertNotIn("sekrit", result.get("error", ""))

    def test_malformed_payload_is_provider_error_not_no_hit(self):
        for payload in (["not", "a", "dict"], {"manufacturerPartNumberSearchReturn": ["bad"]}):
            with self.subTest(payload=payload):
                response = Mock()
                response.json.return_value = payload
                self.requests.get.return_value = response
                with patch.object(self.newark, "get_secret", return_value="private-api-key"):
                    result = self.aggregator._safe_supplier_lookup(
                        "Newark", self.newark.search_newark_by_part_number, "LM358N"
                    )
                self.assertEqual(result["provider_status"], self.health.PROVIDER_ERROR)

    def test_exact_mpn_with_wrong_manufacturer_is_part_not_found(self):
        self._response([self._product("LM358N", brandName="Some Other Vendor")])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            mismatch = self.aggregator._safe_supplier_lookup(
                "Newark", self.newark.search_newark_by_part_number, "LM358N", "", "Texas Instruments"
            )

        self.assertEqual(mismatch["provider_status"], self.health.PROVIDER_PART_NOT_FOUND)

    def test_exact_mpn_with_matching_manufacturer_is_available(self):
        self._response([self._product("LM358N")])
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            result = self.aggregator._safe_supplier_lookup(
                "Newark", self.newark.search_newark_by_part_number, "LM358N", "", "Texas Instruments"
            )
        self.assertEqual(result["provider_status"], self.health.PROVIDER_AVAILABLE)
        self.assertEqual(result["manufacturer"], "Texas Instruments")

    def test_catalog_candidates_empty_success_vs_timeout_vs_malformed(self):
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            self.requests.get.side_effect = None
            self.requests.get.return_value = Mock(
                json=Mock(return_value={"keywordSearchReturn": {"numberOfResults": 0}}),
                raise_for_status=Mock(),
            )
            self.assertEqual(self.newark.search_newark_catalog_candidates("ZZZ999"), [])

            self.requests.get.side_effect = Exception("Read timed out")
            with self.assertRaises(Exception) as ctx:
                self.newark.search_newark_catalog_candidates("ZZZ999")
            self.assertEqual(
                self.health.classify_provider_exception(ctx.exception),
                self.health.PROVIDER_TIMEOUT,
            )

            self.requests.get.side_effect = None
            self.requests.get.return_value = Mock(
                json=Mock(return_value={"unexpected": True}), raise_for_status=Mock()
            )
            with self.assertRaises(self.newark.NewarkCatalogResponseError):
                self.newark.search_newark_catalog_candidates("ZZZ999")

    def test_catalog_candidates_are_review_leads_with_provenance_and_no_fit_claim(self):
        self.requests.get.side_effect = [
            Mock(json=Mock(return_value={"keywordSearchReturn": {"products": [self._product("LM317DCYR")]}}), raise_for_status=Mock()),
            Mock(json=Mock(return_value={"keywordSearchReturn": {"products": [
                self._product("LM317MDCYR", productUrl="", sku="12X3456"),
            ]}}), raise_for_status=Mock()),
        ]
        with patch.object(self.newark, "get_secret", return_value="private-api-key"):
            rows = self.newark.search_newark_catalog_candidates("LM317DCYR")
        row = rows[0]
        self.assertEqual(row["evidence_type"], "Distributor family search match")
        self.assertEqual(row["substitute_type"], "Similar")
        self.assertEqual(row["supplier_relationship_evidence"], [])
        self.assertFalse(row["listing_verified"])
        self.assertTrue(row["retrieved_at"])
        self.assertNotIn("Compatible", str(row.get("substitute_type")))


if __name__ == "__main__":
    unittest.main()
