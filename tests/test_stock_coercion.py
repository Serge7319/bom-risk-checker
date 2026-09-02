"""Regression coverage for supplier stock coercion across Alternative Finder paths."""
from __future__ import annotations

import importlib
import sys
import types
import unittest


def _cache_data(*_args, **_kwargs):
    return lambda func: func


class StockCoercionTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.SimpleNamespace(cache_data=_cache_data)
        sys.modules.pop("integrations.digikey_client", None)
        sys.modules.pop("integrations.supplier_aggregator", None)
        sys.modules.pop("src.alternative_engine", None)
        self.coerce = importlib.import_module("integrations.stock_coercion")
        self.digikey = importlib.import_module("integrations.digikey_client")
        self.aggregator = importlib.import_module("integrations.supplier_aggregator")
        self.search = importlib.import_module("src.alternative_finder_search")
        self.state = importlib.import_module("src.alternative_finder_state")
        self.engine = importlib.import_module("src.alternative_engine")
        self.classification = importlib.import_module("src.alternative_classification")
        self.risk = importlib.import_module("src.risk_engine")

    def test_coerce_stock_total_handles_human_readable_values(self):
        cases = {
            None: 0,
            "": 0,
            7180: 7180,
            "7180 In Stock": 7180,
            "12,345 On Order": 12345,
            "On Order": 0,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(self.coerce.coerce_stock_total(raw), expected)

    def test_normalize_digikey_product_does_not_raise_on_human_readable_stock(self):
        normalized = self.digikey.normalize_digikey_product(
            {
                "Manufacturer": {"Name": "KEMET"},
                "ManufacturerProductNumber": "C0603C104K5RACTU",
                "QuantityAvailable": "7180 In Stock",
                "Description": {"ProductDescription": "Capacitor"},
            }
        )
        self.assertEqual(normalized["stock_total"], 7180)

    def test_get_best_part_data_aggregates_malformed_and_numeric_stock(self):
        self.aggregator.get_supplier_results = lambda _part: [
            {
                "source": "Mouser",
                "provider_status": "AVAILABLE",
                "manufacturer_part_number": "C0603C104K5RACTU",
                "stock_total": "7180 In Stock",
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            },
            {
                "source": "DigiKey",
                "provider_status": "AVAILABLE",
                "manufacturer_part_number": "C0603C104K5RACTU",
                "stock_total": 5000,
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            },
        ]
        data = self.aggregator.get_best_part_data("C0603C104K5RACTU")
        self.assertTrue(data["supplier_data_verified"])
        self.assertEqual(data["stock_total"], 7180)

    def test_production_failure_path_catalog_and_render_use_coerced_stock(self):
        session: dict = {}
        self.state.init_alternative_finder_state(session)

        self.aggregator.get_supplier_results = lambda _part: [
            {
                "source": "DigiKey",
                "provider_status": "AVAILABLE",
                "manufacturer_part_number": "C0603C104K5RACTU",
                "stock_total": 1000,
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
                "manufacturer": "KEMET",
                "package": "0603",
                "supplier_data_verified": True,
            }
        ]

        explicit = [
            {
                "manufacturer_part_number": "C0603C104K5RAC3121",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
                "retrieval_status": "ok",
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
                "stock_total": "7180 In Stock",
            }
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

        self.assertEqual(outcome["status"], "completed")
        candidate = result["candidates"][0]
        self.assertEqual(candidate["Alternative Part"], "C0603C104K5RAC3121")
        self.assertEqual(candidate["Stock"], 7180)

        risk = self.risk.calculate_risk(
            {"stock_total": "7180 In Stock", "supplier_count": 2, "quantity": 1}
        )
        self.assertIn(risk["risk_level"], {"Low", "Medium", "High"})

        render_stock = float(self.coerce.coerce_stock_total(candidate["Stock"]))
        render_original = float(
            self.coerce.coerce_stock_total(result["original_data"]["stock_total"])
        )
        self.assertEqual(render_stock, 7180.0)
        self.assertEqual(render_original, 1000.0)


if __name__ == "__main__":
    unittest.main()
