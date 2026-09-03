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

    def _product(self, mpn="LM358N", **overrides):
        product = {
            "translatedManufacturerPartNumber": mpn,
            "manufacturerPartNumber": mpn,
            "brandName": "Texas Instruments",
            "displayName": "Operational amplifier DIP-8",
            "stock": {"level": 125, "leastLeadTime": 14},
            "prices": [{"cost": 0.42}],
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
        self.assertEqual(result["lead_time_weeks"], 2.0)

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
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        display_start = source.index("            display_columns = [", source.index('st.subheader("Detailed Risk Report")'))
        display_end = source.index("            ]", display_start)
        self.assertIn('"Sources Available"', source[display_start:display_end])
        self.assertIn('"Available Suppliers", width="medium"', source)

    def test_saved_component_details_use_persisted_primary_supplier(self):
        source = (ROOT / "src/pages/analysis_detail.py").read_text()
        detail_start = source.index("                    selected_source = _safe(")
        detail_end = source.index("                    selected_url = _safe(", detail_start)
        self.assertIn('"primary_supplier"', source[detail_start:detail_end])
        self.assertIn("html.escape(primary_supplier)", source)

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


if __name__ == "__main__":
    unittest.main()
