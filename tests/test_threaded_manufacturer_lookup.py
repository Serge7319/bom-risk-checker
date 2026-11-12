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


if __name__ == "__main__":
    unittest.main()
