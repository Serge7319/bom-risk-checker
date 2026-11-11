"""Integration regressions: manufacturer constraint through threaded DigiKey lookups.

``get_supplier_results`` dispatches DigiKey via ThreadPoolExecutor. The selected
manufacturer must be passed explicitly into the worker — ContextVar from the
parent thread is not reliable. Concurrent TI/onsemi requests must not leak.
"""
from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

from tests.streamlit_cache_stub import install_streamlit_cache_stub


class ThreadedManufacturerLookupTests(unittest.TestCase):
    def setUp(self):
        install_streamlit_cache_stub()
        import integrations.supplier_aggregator as aggregator

        self.aggregator = aggregator
        # Ensure cache_data stub does not retain prior results across tests.
        if hasattr(self.aggregator.get_best_part_data, "clear"):
            self.aggregator.get_best_part_data.clear()

        self.digikey_calls: list[dict] = []
        self._lock = threading.Lock()

        def fake_digikey(part_number: str, manufacturer: str = ""):
            # Prove the worker thread actually received the brand argument.
            with self._lock:
                self.digikey_calls.append(
                    {
                        "part": str(part_number or "").strip(),
                        "manufacturer": str(manufacturer or "").strip(),
                        "thread": threading.current_thread().name,
                    }
                )
            # Simulate slow keyword search so concurrent calls overlap.
            time.sleep(0.05)
            requested = str(part_number or "").strip().upper()
            mfr = str(manufacturer or "").strip()
            if requested != "LM358N":
                return {
                    "source": "DigiKey",
                    "manufacturer_part_number": "",
                    "manufacturer": "",
                    "error": "not found",
                }
            from apps.api.manufacturer_identity import manufacturers_match

            if manufacturers_match(mfr, "Texas Instruments"):
                return {
                    "source": "DigiKey",
                    "manufacturer_part_number": "LM358N",
                    "manufacturer": "Texas Instruments",
                    "description": "TI LM358N",
                    "supplier_data_verified": True,
                    "stock_total": 100,
                    "product_detail_url": "https://www.ti.com/product/LM358",
                }
            if manufacturers_match(mfr, "onsemi"):
                return {
                    "source": "DigiKey",
                    "manufacturer_part_number": "LM358N",
                    "manufacturer": "onsemi",
                    "description": "onsemi LM358N",
                    "supplier_data_verified": True,
                    "stock_total": 200,
                    "product_detail_url": "https://www.onsemi.com/products/lm358",
                }
            # Absent / unverifiable brand — DigiKey has the MPN under other brands only.
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

    def test_ti_and_onsemi_select_matching_records_via_threaded_path(self):
        ti = self.aggregator.get_best_part_data(
            "LM358N", manufacturer="Texas Instruments"
        )
        onsemi = self.aggregator.get_best_part_data("LM358N", manufacturer="onsemi")

        self.assertEqual(ti.get("manufacturer"), "Texas Instruments")
        self.assertEqual(ti.get("manufacturer_part_number"), "LM358N")
        self.assertTrue(ti.get("supplier_data_verified"))

        self.assertEqual(onsemi.get("manufacturer"), "onsemi")
        self.assertEqual(onsemi.get("manufacturer_part_number"), "LM358N")
        self.assertTrue(onsemi.get("supplier_data_verified"))

        brands = {row["manufacturer"] for row in self.digikey_calls}
        self.assertIn("Texas Instruments", brands)
        self.assertIn("onsemi", brands)
        # Calls must have run off the main thread (ThreadPoolExecutor workers).
        self.assertTrue(
            any(row["thread"] != threading.current_thread().name for row in self.digikey_calls)
        )

    def test_absent_manufacturer_does_not_verify_wrong_brand(self):
        data = self.aggregator.get_best_part_data(
            "LM358N", manufacturer="Analog Devices"
        )
        self.assertFalse(bool(data.get("supplier_data_verified")))
        self.assertNotEqual(
            str(data.get("manufacturer") or "").casefold(),
            "texas instruments",
        )
        self.assertNotEqual(str(data.get("manufacturer") or "").casefold(), "onsemi")

    def test_find_replacements_fail_closed_when_brand_unverifiable(self):
        from apps.api.legacy_supplier_workflow import find_replacements

        result = find_replacements("LM358N", manufacturer="Analog Devices")
        original = result.get("original") or {}
        self.assertIn(
            str(original.get("identity_status") or ""),
            {"unresolved", "manufacturer_mismatch"},
        )
        self.assertEqual(original.get("manufacturer"), "")
        self.assertFalse(bool(original.get("identity_verified")))
        self.assertEqual(result.get("candidates") or [], [])

    def test_concurrent_ti_and_onsemi_do_not_leak(self):
        outcomes: dict[str, dict] = {}

        def run(brand: str):
            outcomes[brand] = self.aggregator.get_best_part_data(
                "LM358N", manufacturer=brand
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(run, "Texas Instruments"),
                executor.submit(run, "onsemi"),
            ]
            for future in as_completed(futures):
                future.result()

        self.assertEqual(
            outcomes["Texas Instruments"].get("manufacturer"),
            "Texas Instruments",
        )
        self.assertEqual(outcomes["onsemi"].get("manufacturer"), "onsemi")

        # Every DigiKey worker call must carry the brand for that request only.
        for row in self.digikey_calls:
            self.assertIn(
                row["manufacturer"],
                {"Texas Instruments", "onsemi"},
            )


if __name__ == "__main__":
    unittest.main()
