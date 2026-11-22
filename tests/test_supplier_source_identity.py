from __future__ import annotations

import unittest

from src.supplier_source_identity import (
    canonical_supplier_key,
    is_supported_distributor,
    supplier_listing_url_is_valid,
)


class SupplierSourceIdentityTests(unittest.TestCase):
    def test_supplier_aliases_normalize_to_supported_distributors(self):
        self.assertEqual(canonical_supplier_key("DigiKey Electronics"), "digikey")
        self.assertEqual(canonical_supplier_key("element14"), "newark")
        self.assertEqual(canonical_supplier_key("Octopart"), "nexarsupply")
        self.assertTrue(is_supported_distributor("Mouser Electronics"))
        self.assertFalse(is_supported_distributor("Unknown Components"))

    def test_listing_url_must_use_https_and_named_distributor_host(self):
        self.assertTrue(supplier_listing_url_is_valid(
            "DigiKey", "https://www.digikey.com/en/products/detail/vendor/part/123"
        ))
        self.assertFalse(supplier_listing_url_is_valid(
            "DigiKey", "http://www.digikey.com/en/products/detail/vendor/part/123"
        ))
        self.assertFalse(supplier_listing_url_is_valid(
            "DigiKey", "https://digikey.com.attacker.example/part"
        ))
        self.assertFalse(supplier_listing_url_is_valid(
            "DigiKey", "https://www.mouser.com/ProductDetail/part"
        ))
        self.assertFalse(supplier_listing_url_is_valid(
            "DigiKey", "https://user:password@www.digikey.com/part"
        ))


if __name__ == "__main__":
    unittest.main()
