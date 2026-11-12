"""Integration regressions: manufacturer constraint through threaded DigiKey lookups.

``get_supplier_results`` dispatches DigiKey via ThreadPoolExecutor. The selected
manufacturer must be passed explicitly into the worker — ContextVar from the
parent thread is not reliable. Concurrent brand requests must not leak across
MPNs.
"""
from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

from apps.api.manufacturer_identity import (
    clear_multi_brand_evidence,
    manufacturers_match,
    register_multi_brand_evidence,
)
from tests.streamlit_cache_stub import install_streamlit_cache_stub


class ThreadedManufacturerLookupTests(unittest.TestCase):
    def setUp(self):
        install_streamlit_cache_stub()
        import integrations.supplier_aggregator as aggregator

        self.aggregator = aggregator
        if hasattr(self.aggregator.get_best_part_data, "clear"):
            self.aggregator.get_best_part_data.clear()

        clear_multi_brand_evidence()
        register_multi_brand_evidence(
            "AMP-DUAL-1",
            [
                {
                    "manufacturer": "Texas Instruments",
                    "product_url": "https://www.ti.com/product/AMP-DUAL-1",
                },
                {
                    "manufacturer": "onsemi",
                    "product_url": "https://www.onsemi.com/products/amp-dual-1",
                },
            ],
        )
        register_multi_brand_evidence(
            "REG-DUAL-5V",
            [
                {
                    "manufacturer": "Analog Devices",
                    "product_url": "https://www.analog.com/en/products/reg-dual-5v.html",
                },
                {
                    "manufacturer": "Microchip",
                    "product_url": "https://www.microchip.com/en-us/product/REG-DUAL-5V",
                },
            ],
        )

        self.digikey_calls: list[dict] = []
        self._lock = threading.Lock()
        self._catalog = {
            ("AMP-DUAL-1", "texas instruments"): {
                "source": "DigiKey",
                "manufacturer_part_number": "AMP-DUAL-1",
                "manufacturer": "Texas Instruments",
                "description": "TI amp",
                "supplier_data_verified": True,
                "stock_total": 100,
                "product_detail_url": "https://www.ti.com/product/AMP-DUAL-1",
            },
            ("AMP-DUAL-1", "onsemi"): {
                "source": "DigiKey",
                "manufacturer_part_number": "AMP-DUAL-1",
                "manufacturer": "onsemi",
                "description": "onsemi amp",
                "supplier_data_verified": True,
                "stock_total": 200,
                "product_detail_url": "https://www.onsemi.com/products/amp-dual-1",
            },
            ("REG-DUAL-5V", "analog devices"): {
                "source": "DigiKey",
                "manufacturer_part_number": "REG-DUAL-5V",
                "manufacturer": "Analog Devices",
                "description": "ADI regulator",
                "supplier_data_verified": True,
                "stock_total": 50,
                "product_detail_url": "https://www.analog.com/en/products/reg-dual-5v.html",
            },
            ("REG-DUAL-5V", "microchip"): {
                "source": "DigiKey",
                "manufacturer_part_number": "REG-DUAL-5V",
                "manufacturer": "Microchip",
                "description": "Microchip regulator",
                "supplier_data_verified": True,
                "stock_total": 75,
                "product_detail_url": "https://www.microchip.com/en-us/product/REG-DUAL-5V",
            },
        }

        def fake_digikey(part_number: str, manufacturer: str = ""):
            with self._lock:
                self.digikey_calls.append(
                    {
                        "part": str(part_number or "").strip(),
                        "manufacturer": str(manufacturer or "").strip(),
                        "thread": threading.current_thread().name,
                    }
                )
            time.sleep(0.05)
            requested = str(part_number or "").strip().upper()
            mfr = str(manufacturer or "").strip()
            from apps.api.manufacturer_identity import manufacturer_canonical

            key = (requested, manufacturer_canonical(mfr))
            hit = self._catalog.get(key)
            if hit:
                return dict(hit)
            return {
                "source": "DigiKey",
                "manufacturer_part_number": "",
                "manufacturer": "",
                "error": "not found for requested manufacturer",
            }

        def fake_lookup_callable(source_name: str):
            if source_name == "DigiKey":
                return fake_digikey
            return None

        self._lookup_patch = patch.object(
            self.aggregator,
            "_supplier_lookup_callable",
            side_effect=fake_lookup_callable,
        )
        self._lookup_patch.start()
        self.addCleanup(self._lookup_patch.stop)
        self.addCleanup(clear_multi_brand_evidence)

    def test_branded_lookups_select_matching_records_via_threaded_path(self):
        cases = [
            ("AMP-DUAL-1", "Texas Instruments"),
            ("AMP-DUAL-1", "onsemi"),
            ("REG-DUAL-5V", "Analog Devices"),
            ("REG-DUAL-5V", "Microchip"),
        ]
        for mpn, brand in cases:
            with self.subTest(mpn=mpn, brand=brand):
                row = self.aggregator.get_best_part_data(mpn, manufacturer=brand)
                self.assertEqual(row.get("manufacturer"), brand)
                self.assertEqual(row.get("manufacturer_part_number"), mpn)
                self.assertTrue(row.get("supplier_data_verified"))

        brands = {row["manufacturer"] for row in self.digikey_calls}
        self.assertTrue({"Texas Instruments", "onsemi", "Analog Devices", "Microchip"} <= brands)
        self.assertTrue(
            any(row["thread"] != threading.current_thread().name for row in self.digikey_calls)
        )

    def test_absent_manufacturer_does_not_verify_wrong_brand(self):
        data = self.aggregator.get_best_part_data(
            "AMP-DUAL-1", manufacturer="Vishay"
        )
        self.assertFalse(bool(data.get("supplier_data_verified")))
        self.assertNotEqual(
            str(data.get("manufacturer") or "").casefold(),
            "texas instruments",
        )
        self.assertNotEqual(str(data.get("manufacturer") or "").casefold(), "onsemi")

    def test_find_replacements_fail_closed_when_brand_unverifiable(self):
        from apps.api.legacy_supplier_workflow import find_replacements

        for mpn, brand in (("AMP-DUAL-1", "Vishay"), ("REG-DUAL-5V", "Yageo")):
            with self.subTest(mpn=mpn, brand=brand):
                result = find_replacements(mpn, manufacturer=brand)
                original = result.get("original") or {}
                self.assertIn(
                    str(original.get("identity_status") or ""),
                    {"unresolved", "manufacturer_mismatch", "ambiguous"},
                )
                self.assertEqual(original.get("manufacturer"), "")
                self.assertFalse(bool(original.get("identity_verified")))
                self.assertEqual(result.get("candidates") or [], [])

    def test_concurrent_brands_do_not_leak_across_mpns(self):
        outcomes: dict[str, dict] = {}

        def run(mpn: str, brand: str):
            outcomes[f"{mpn}|{brand}"] = self.aggregator.get_best_part_data(
                mpn, manufacturer=brand
            )

        pairs = [
            ("AMP-DUAL-1", "Texas Instruments"),
            ("AMP-DUAL-1", "onsemi"),
            ("REG-DUAL-5V", "Analog Devices"),
            ("REG-DUAL-5V", "Microchip"),
        ]
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(run, mpn, brand) for mpn, brand in pairs]
            for future in as_completed(futures):
                future.result()

        for mpn, brand in pairs:
            self.assertEqual(outcomes[f"{mpn}|{brand}"].get("manufacturer"), brand)
            self.assertEqual(
                outcomes[f"{mpn}|{brand}"].get("manufacturer_part_number"), mpn
            )

        for row in self.digikey_calls:
            self.assertTrue(row["manufacturer"])
            self.assertTrue(
                any(
                    manufacturers_match(row["manufacturer"], brand)
                    and row["part"] == mpn
                    for mpn, brand in pairs
                )
            )


class Am29LineageAggregatorPathTests(unittest.TestCase):
    """Route-aware AMD↔Infineon matching must run through the real aggregator."""

    AM29 = "AM29F010B-70EC"
    UNRELATED = "LM358N-UNRELATED"

    def setUp(self):
        install_streamlit_cache_stub()
        import integrations.supplier_aggregator as aggregator
        from integrations.provider_health import PROVIDER_AVAILABLE

        self.aggregator = aggregator
        self.PROVIDER_AVAILABLE = PROVIDER_AVAILABLE
        if hasattr(self.aggregator.get_best_part_data, "clear"):
            self.aggregator.get_best_part_data.clear()
        self.digikey_calls: list[dict] = []
        self._lock = threading.Lock()

    def _available_row(
        self,
        *,
        source: str,
        mpn: str,
        manufacturer: str,
    ) -> dict:
        return {
            "source": source,
            "manufacturer_part_number": mpn,
            "manufacturer": manufacturer,
            "description": f"{manufacturer} {mpn}",
            "supplier_data_verified": True,
            "stock_total": 10,
            "provider_status": self.PROVIDER_AVAILABLE,
            "product_detail_url": f"https://example.test/{source.lower()}/{mpn}",
        }

    def test_digikey_worker_accepts_infineon_when_amd_requested_for_am29(self):
        def fake_digikey(part_number: str, manufacturer: str = ""):
            with self._lock:
                self.digikey_calls.append(
                    {
                        "part": str(part_number or "").strip(),
                        "manufacturer": str(manufacturer or "").strip(),
                        "thread": threading.current_thread().name,
                    }
                )
            # Supplier reports Infineon; caller requested AMD — lineage only for AM29.
            return {
                "source": "DigiKey",
                "manufacturer_part_number": str(part_number or "").strip(),
                "manufacturer": "Infineon",
                "description": "Flash",
                "supplier_data_verified": True,
                "stock_total": 3,
                "product_detail_url": "https://example.test/infineon/am29",
            }

        with patch.object(
            self.aggregator,
            "_supplier_lookup_callable",
            side_effect=lambda source: fake_digikey if source == "DigiKey" else None,
        ):
            row = self.aggregator.get_best_part_data(self.AM29, manufacturer="AMD")

        self.assertEqual(row.get("manufacturer_part_number"), self.AM29)
        # Preserve supplier-reported brand — do not stamp typed AMD over Infineon.
        self.assertEqual(row.get("manufacturer"), "Infineon")
        self.assertTrue(row.get("supplier_data_verified"))
        self.assertTrue(self.digikey_calls)
        self.assertTrue(
            any(call["thread"] != threading.current_thread().name for call in self.digikey_calls)
        )

    def test_digikey_worker_rejects_infineon_for_unrelated_mpn_with_amd(self):
        def fake_digikey(part_number: str, manufacturer: str = ""):
            return {
                "source": "DigiKey",
                "manufacturer_part_number": str(part_number or "").strip(),
                "manufacturer": "Infineon",
                "description": "Not lineage-linked",
                "supplier_data_verified": True,
                "stock_total": 3,
            }

        with patch.object(
            self.aggregator,
            "_supplier_lookup_callable",
            side_effect=lambda source: fake_digikey if source == "DigiKey" else None,
        ):
            row = self.aggregator.get_best_part_data(self.UNRELATED, manufacturer="AMD")

        self.assertFalse(bool(row.get("supplier_data_verified")))
        self.assertNotEqual(str(row.get("manufacturer") or ""), "Infineon")
        self.assertNotEqual(str(row.get("manufacturer") or "").casefold(), "amd")

    def _clear_best_part_cache(self):
        if hasattr(self.aggregator.get_best_part_data, "clear"):
            self.aggregator.get_best_part_data.clear()

    def test_aggregation_filter_accepts_lineage_and_rejects_missing_manufacturer(self):
        am29_infineon = self._available_row(
            source="Mouser", mpn=self.AM29, manufacturer="Infineon"
        )
        am29_blank = self._available_row(source="Newark", mpn=self.AM29, manufacturer="")
        unrelated_infineon = self._available_row(
            source="Mouser", mpn=self.UNRELATED, manufacturer="Infineon"
        )

        self._clear_best_part_cache()
        with patch.object(
            self.aggregator,
            "get_supplier_results",
            return_value=[am29_infineon, am29_blank],
        ):
            matched = self.aggregator.get_best_part_data(self.AM29, manufacturer="AMD")
        self.assertEqual(matched.get("manufacturer"), "Infineon")
        self.assertEqual(matched.get("manufacturer_part_number"), self.AM29)
        self.assertTrue(matched.get("supplier_data_verified"))

        self._clear_best_part_cache()
        with patch.object(
            self.aggregator,
            "get_supplier_results",
            return_value=[am29_blank],
        ):
            missing = self.aggregator.get_best_part_data(self.AM29, manufacturer="AMD")
        # Brand filter drops blank-manufacturer rows; do not stamp typed AMD.
        self.assertEqual(str(missing.get("manufacturer") or ""), "")
        self.assertEqual(str(missing.get("source") or ""), "No supplier match")
        self.assertNotEqual(str(missing.get("manufacturer") or "").casefold(), "amd")

        self._clear_best_part_cache()
        with patch.object(
            self.aggregator,
            "get_supplier_results",
            return_value=[unrelated_infineon],
        ):
            rejected = self.aggregator.get_best_part_data(
                self.UNRELATED, manufacturer="Advanced Micro Devices"
            )
        self.assertEqual(str(rejected.get("manufacturer") or ""), "")
        self.assertEqual(str(rejected.get("source") or ""), "No supplier match")
        self.assertNotEqual(str(rejected.get("manufacturer") or ""), "Infineon")

    def test_missing_supplier_manufacturer_yields_no_verified_replacement(self):
        from apps.api.legacy_supplier_workflow import find_replacements

        blank = self._available_row(source="DigiKey", mpn=self.AM29, manufacturer="")
        self._clear_best_part_cache()
        with patch.object(
            self.aggregator,
            "get_supplier_results",
            return_value=[blank],
        ):
            aggregated = self.aggregator.get_best_part_data(self.AM29, manufacturer="AMD")

        self.assertEqual(str(aggregated.get("manufacturer") or ""), "")
        self.assertEqual(str(aggregated.get("source") or ""), "No supplier match")

        with patch(
            "integrations.supplier_aggregator.get_best_part_data",
            return_value=dict(aggregated),
        ), patch(
            "integrations.supplier_aggregator.discover_alternative_candidates",
            return_value={
                "providers": {},
                "candidates": [],
                "catalog_count": 0,
                "has_incomplete_evidence": False,
            },
        ), patch(
            "src.alternative_engine.suggest_alternatives_v2",
            return_value=[],
        ), patch(
            "src.alternative_engine.get_alternative_discovery_metadata",
            return_value={},
        ), patch(
            "src.alternative_engine.build_salvage_candidates_from_discovery",
            return_value=[],
        ):
            result = find_replacements(self.AM29, manufacturer="AMD")

        original = result.get("original") or {}
        self.assertFalse(bool(original.get("identity_verified")))
        self.assertEqual(original.get("manufacturer"), "")
        self.assertEqual(result.get("candidates") or [], [])
        self.assertIn(
            str(original.get("identity_status") or ""),
            {"unresolved", "manufacturer_mismatch", "ambiguous"},
        )

    def test_concurrent_am29_lineage_requests_stay_isolated(self):
        def fake_digikey(part_number: str, manufacturer: str = ""):
            time.sleep(0.03)
            mpn = str(part_number or "").strip()
            if mpn.upper() == self.AM29.upper():
                return {
                    "source": "DigiKey",
                    "manufacturer_part_number": mpn,
                    "manufacturer": "Cypress",
                    "description": "AM29 lineage",
                    "supplier_data_verified": True,
                    "stock_total": 1,
                }
            return {
                "source": "DigiKey",
                "manufacturer_part_number": mpn,
                "manufacturer": "Infineon",
                "description": "unrelated",
                "supplier_data_verified": True,
                "stock_total": 1,
            }

        with patch.object(
            self.aggregator,
            "_supplier_lookup_callable",
            side_effect=lambda source: fake_digikey if source == "DigiKey" else None,
        ):
            outcomes: dict[str, dict] = {}

            def run(key: str, mpn: str, brand: str):
                outcomes[key] = self.aggregator.get_best_part_data(mpn, manufacturer=brand)

            pairs = [
                ("am29-amd", self.AM29, "AMD"),
                ("am29-advanced", self.AM29, "Advanced Micro Devices"),
                ("other-amd", self.UNRELATED, "AMD"),
                ("other-ti", self.UNRELATED, "Texas Instruments"),
            ]
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [
                    executor.submit(run, key, mpn, brand) for key, mpn, brand in pairs
                ]
                for future in as_completed(futures):
                    future.result()

        self.assertEqual(outcomes["am29-amd"].get("manufacturer"), "Cypress")
        self.assertEqual(outcomes["am29-advanced"].get("manufacturer"), "Cypress")
        self.assertTrue(outcomes["am29-amd"].get("supplier_data_verified"))
        self.assertFalse(bool(outcomes["other-amd"].get("supplier_data_verified")))
        self.assertNotEqual(str(outcomes["other-amd"].get("manufacturer") or ""), "Infineon")


if __name__ == "__main__":
    unittest.main()
