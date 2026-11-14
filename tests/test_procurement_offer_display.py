"""Browser/source contract: each supplier offer shows listing URL + retrieval time."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCUREMENT_PAGE = ROOT / "apps" / "web" / "src" / "app" / "procurement" / "page.tsx"


class ProcurementOfferDisplayTests(unittest.TestCase):
    def test_offer_rows_render_listing_url_and_retrieved_at(self):
        source = PROCUREMENT_PAGE.read_text(encoding="utf-8")
        self.assertIn("supplier_offers.map", source)
        self.assertIn("offer.product_url", source)
        self.assertIn("Supplier listing", source)
        self.assertIn("offer.retrieved_at", source)
        self.assertIn("Retrieved:", source)
        # Only render clickable listing links for absolute http(s) URLs.
        self.assertIn('productUrl.startsWith("https://")', source)
        self.assertIn('productUrl.startsWith("http://")', source)


if __name__ == "__main__":
    unittest.main()
