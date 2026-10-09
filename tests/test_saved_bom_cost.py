import unittest

from src.saved_bom_cost import (
    analysis_part_cost_fields,
    collect_supplier_offers,
    distributor_comparison,
    extended_cost,
    omitted_optional_column,
    without_column,
)
from src.ui.ei_bom_report import engineering_intelligence_html


SUPPLIER_ROW = {
    "MPN": "TPS54331D",
    "Best Source": "DigiKey",
    "Unit Price": 1.2,
    "Quantity": 10,
    "Product URL": "https://www.digikey.com/en/products/detail/ti/TPS54331D/1",
    "Risk Level": "Medium",
    "Risk Reasons": "Lead time is longer than the release window.",
}


class SavedBomCostPersistenceTests(unittest.TestCase):
    def test_supplier_price_quantity_and_product_url_persist_across_reanalysis(self):
        first_save = analysis_part_cost_fields(SUPPLIER_ROW)
        reanalysis = analysis_part_cost_fields(dict(SUPPLIER_ROW))
        self.assertEqual(first_save, reanalysis)
        self.assertEqual(first_save["primary_supplier"], "DigiKey")
        self.assertEqual(first_save["unit_price"], 1.2)
        self.assertEqual(first_save["quantity"], 10)
        self.assertEqual(
            first_save["product_url"],
            "https://www.digikey.com/en/products/detail/ti/TPS54331D/1",
        )

    def test_missing_inputs_are_not_invented(self):
        saved = analysis_part_cost_fields(
            {
                "Best Source": "No supplier match",
                "Unit Price": 0,
                "Quantity": None,
                "Product URL": "",
            }
        )
        self.assertEqual(saved["primary_supplier"], "")
        self.assertEqual(saved["unit_price"], 0)
        self.assertEqual(saved["quantity"], 0)
        self.assertEqual(saved["product_url"], "")
        self.assertEqual(saved["supplier_offers"], [])
        self.assertIsNone(extended_cost(saved["unit_price"], saved["quantity"]))
        comparison = distributor_comparison([], mpn="TPS54331D", bom_quantity=10)
        self.assertIsNone(comparison["savings_per_unit"])

    def test_extended_cost_requires_price_and_bom_quantity(self):
        self.assertIsNone(extended_cost(1.2, None))
        self.assertIsNone(extended_cost(1.2, 0))
        self.assertIsNone(extended_cost(0, 10))
        self.assertEqual(extended_cost(1.2, 10), 12)

    def _offers(self, *, mouser_currency="USD", mouser_qty=1, digikey_qty=1, digikey_currency="USD", mouser_mpn="TPS54331D"):
        return [
            {
                "mpn": "TPS54331D",
                "distributor": "DigiKey",
                "unit_price": 1.2,
                "currency": digikey_currency,
                "price_break_quantity": digikey_qty,
                "stock": 1200,
                "product_url": "https://www.digikey.com/en/products/detail/ti/TPS54331D/1",
                "retrieved_at": "2026-10-09T14:00:00+00:00",
            },
            {
                "mpn": mouser_mpn,
                "distributor": "Mouser",
                "unit_price": 1.0,
                "currency": mouser_currency,
                "price_break_quantity": mouser_qty,
                "stock": 80,
                "product_url": "https://www.mouser.com/ProductDetail/TPS54331D",
                "retrieved_at": "2026-10-09T14:00:00+00:00",
            },
        ]

    def test_valid_lower_priced_offer_is_saved_and_compared(self):
        offers = collect_supplier_offers(
            [
                {
                    "provider_status": "AVAILABLE",
                    "source": "DigiKey",
                    "unit_price": 1.2,
                    "stock_total": 1200,
                    "product_detail_url": "https://www.digikey.com/en/products/detail/ti/TPS54331D/1",
                    "retrieved_at": "2026-10-09T14:00:00+00:00",
                    "price_breaks": [
                        {"unit_price": 1.2, "price_break_quantity": 1, "currency": "USD"}
                    ],
                },
                {
                    "provider_status": "AVAILABLE",
                    "source": "Mouser",
                    "unit_price": 1.0,
                    "stock_total": 80,
                    "product_detail_url": "https://www.mouser.com/ProductDetail/TPS54331D",
                    "retrieved_at": "2026-10-09T14:00:00+00:00",
                    "price_breaks": [
                        {"unit_price": 1.0, "price_break_quantity": 1, "currency": "USD"}
                    ],
                },
            ],
            mpn="TPS54331D",
        )
        saved = analysis_part_cost_fields(
            {
                "MPN": "TPS54331D",
                "Best Source": "DigiKey",
                "Unit Price": 1.2,
                "Quantity": 10,
                "Product URL": "https://www.digikey.com/en/products/detail/ti/TPS54331D/1",
                "Supplier Offers": offers,
            }
        )
        again = analysis_part_cost_fields(dict(saved, MPN="TPS54331D", **{
            "Supplier Offers": saved["supplier_offers"],
        }))
        self.assertEqual(len(saved["supplier_offers"]), 2)
        self.assertEqual(saved["supplier_offers"], again["supplier_offers"])
        comparison = distributor_comparison(
            saved["supplier_offers"],
            mpn="TPS54331D",
            bom_quantity=10,
        )
        self.assertEqual(comparison["savings_per_unit"], 0.2)
        self.assertEqual(comparison["lower_distributor"], "Mouser")
        self.assertEqual(comparison["currency"], "USD")

    def test_one_saved_offer_has_no_distributor_comparison(self):
        comparison = distributor_comparison(self._offers()[:1], mpn="TPS54331D", bom_quantity=10)
        self.assertIsNone(comparison["savings_per_unit"])
        self.assertEqual(comparison["message"], "A distributor comparison is unavailable.")

    def test_different_currency_or_quantity_is_not_comparable(self):
        currency = distributor_comparison(
            self._offers(mouser_currency="EUR"),
            mpn="TPS54331D",
            bom_quantity=10,
        )
        self.assertIsNone(currency["savings_per_unit"])
        self.assertIn("do not share a currency", currency["message"])
        quantity = distributor_comparison(
            self._offers(digikey_qty=100),
            mpn="TPS54331D",
            bom_quantity=10,
        )
        self.assertIsNone(quantity["savings_per_unit"])
        self.assertIn("do not apply to the BOM quantity", quantity["message"])
        other_part = distributor_comparison(
            self._offers(mouser_mpn="LM358N"),
            mpn="TPS54331D",
            bom_quantity=10,
        )
        self.assertIsNone(other_part["savings_per_unit"])
        self.assertEqual(other_part["message"], "A distributor comparison is unavailable.")

    def test_missing_product_url_column_can_be_dropped_without_losing_price(self):
        column = omitted_optional_column(
            "Could not find the 'product_url' column of 'analysis_parts' in the schema cache"
        )
        self.assertEqual(column, "product_url")
        records = without_column(
            [{"unit_price": 1.2, "quantity": 10, "product_url": "https://www.digikey.com/product"}],
            column,
        )
        self.assertEqual(records, [{"unit_price": 1.2, "quantity": 10}])
        self.assertEqual(omitted_optional_column("network timeout"), "")
        offers_column = omitted_optional_column(
            "Could not find the 'supplier_offers' column of 'analysis_parts' in the schema cache"
        )
        self.assertEqual(offers_column, "supplier_offers")
        kept = without_column(
            [{"unit_price": 1.2, "supplier_offers": [{"distributor": "Mouser"}]}],
            offers_column,
        )
        self.assertEqual(kept, [{"unit_price": 1.2}])

    def test_cost_table_does_not_calculate_cost_or_savings_without_inputs(self):
        html = engineering_intelligence_html(
            bom_name="Industrial Controller BOM",
            part_count=2,
            tab="Cost Insights",
            parts=[
                {
                    "mpn": "MAX32625ITK+",
                    "manufacturer": "Analog Devices",
                    "risk_level": "High",
                    "risk_reasons": "Lifecycle and single-source exposure require a replacement review.",
                    "unit_price": 0.0,
                    "quantity": 0,
                    "stock_available": 0,
                },
                {
                    "mpn": "TPS54331D",
                    "manufacturer": "Texas Instruments",
                    "risk_level": "Medium",
                    "risk_reasons": "Lead time is longer than the release window.",
                    "unit_price": 1.2,
                    "quantity": 10,
                    "primary_supplier": "DigiKey",
                    "stock_available": 1200,
                    "product_url": "https://www.digikey.com/en/products/detail/ti/TPS54331D/1",
                    "supplier_offers": self._offers(),
                },
            ],
        )
        self.assertIn("Distributor was not saved.", html)
        self.assertIn("unit price and BOM quantity were not saved", html)
        self.assertIn("Not calculated", html)
        self.assertNotIn("$0.00", html)
        self.assertIn("DigiKey", html)
        self.assertIn("$12", html)
        self.assertIn("https://www.digikey.com/en/products/detail/ti/TPS54331D/1", html)
        self.assertIn("Savings of $0.2 per unit versus DigiKey", html)
        self.assertIn("The Mouser price is $1.", html)
        self.assertNotIn("best", html.casefold())
        self.assertIn("Lifecycle and single-source exposure require a replacement review.", html)
        self.assertNotIn("and a product link", html)
        priced = html.split("TPS54331D", 1)[1]
        missing = html.split("MAX32625ITK+", 1)[1].split("TPS54331D", 1)[0]
        self.assertNotIn("A distributor comparison is unavailable.", missing)
        self.assertNotIn("Savings of", missing)


if __name__ == "__main__":
    unittest.main()
