"""Tests that live review links never borrow evidence from another MPN."""
from __future__ import annotations

import unittest

from src.decision_packet_evidence import (
    exact_supplier_evidence,
    public_datasheet_search_url,
)


class ExactSupplierEvidenceTests(unittest.TestCase):
    def test_accepts_exact_mpn_and_keeps_verified_document_links(self):
        result = exact_supplier_evidence(
            "ATMEGA328P-PU",
            {
                "manufacturer_part_number": "atmega328ppu",
                "source": "DigiKey",
                "manufacturer": "Microchip",
                "lifecycle_status": "Active",
                "product_detail_url": "https://example.test/part",
                "datasheet_url": "https://example.test/datasheet.pdf",
                "retrieved_at": "2026-10-17T14:00:00Z",
            },
        )

        self.assertTrue(result["identity_verified"])
        self.assertEqual(result["source"], "DigiKey")
        self.assertEqual(result["lifecycle_status"], "Active")
        self.assertEqual(result["datasheet_url"], "https://example.test/datasheet.pdf")

    def test_rejects_neighboring_part_results(self):
        result = exact_supplier_evidence(
            "MC68HC11E1CFNE2",
            {
                "manufacturer_part_number": "MC68HC11E1CFNE3",
                "source": "DigiKey",
                "datasheet_url": "https://example.test/wrong-part.pdf",
            },
        )

        self.assertIsNone(result)

    def test_rejects_non_web_document_urls(self):
        result = exact_supplier_evidence(
            "LM7805ACT",
            {
                "manufacturer_part_number": "LM7805ACT",
                "source": "Supplier",
                "datasheet_url": "javascript:alert(1)",
            },
        )

        self.assertEqual(result["datasheet_url"], "")

    def test_rejects_synthetic_or_unavailable_supplier_records(self):
        for source, provider_status in (
            ("No supplier match", "PART_NOT_FOUND"),
            ("Supplier lookup unavailable", "ERROR"),
            ("", ""),
        ):
            with self.subTest(source=source, provider_status=provider_status):
                result = exact_supplier_evidence(
                    "DHT11",
                    {
                        "manufacturer_part_number": "DHT11",
                        "source": source,
                        "provider_status": provider_status,
                        "datasheet_url": "https://example.test/not-verified.pdf",
                    },
                )
                self.assertIsNone(result)

    def test_public_datasheet_link_is_a_search_lead_not_a_document_url(self):
        url = public_datasheet_search_url(" DHT11 ")

        self.assertEqual(
            url,
            "https://www.google.com/search?q=%22DHT11%22+datasheet+PDF",
        )
        self.assertEqual(public_datasheet_search_url(" "), "")


if __name__ == "__main__":
    unittest.main()
