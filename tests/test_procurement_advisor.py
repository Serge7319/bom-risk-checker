import unittest
from types import SimpleNamespace

from src.procurement_advisor import (
    apply_sourcing_override,
    build_procurement_advisor,
    normalize_sourcing_override,
    persist_sourcing_update,
    procurement_header_html,
    sourcing_editor_values,
)


class ProcurementAdvisorTests(unittest.TestCase):
    def test_missing_supplier_defaults_are_not_presented_as_a_stockout(self):
        advisor = build_procurement_advisor(
            analyses=[],
            parts=[
                {
                    "mpn": "TPS54331D",
                    "stock_available": 0,
                    "supplier_count": 0,
                    "lead_time_weeks": 0,
                    "unit_price": 0,
                    "supplier_data_verified": False,
                }
            ],
        )
        row = advisor["recommendations"][0]
        self.assertEqual(row["Recommendation"], "Complete sourcing data")
        self.assertIsNone(row["Available Stock"])
        self.assertIsNone(row["Supplier Sources"])
        self.assertEqual(row["Evidence Status"], "Incomplete")
        self.assertEqual(advisor["urgent_count"], 0)
        self.assertIn("current sourcing data", advisor["summary"])

    def test_unverified_numeric_zeroes_are_blank_in_the_editor(self):
        values = sourcing_editor_values(
            {
                "mpn": "TPS54331D",
                "stock_available": 0,
                "supplier_count": 0,
                "lead_time_weeks": 0,
                "unit_price": 0,
                "supplier_data_verified": False,
            }
        )
        self.assertIsNone(values["stock_available"])
        self.assertIsNone(values["supplier_count"])
        self.assertIsNone(values["lead_time_weeks"])
        self.assertIsNone(values["unit_price"])

    def test_verified_zero_stock_creates_a_real_supply_gap_action(self):
        row = build_procurement_advisor(
            analyses=[],
            parts=[
                {
                    "mpn": "TPS54331D",
                    "quantity": 100,
                    "stock_available": 0,
                    "supplier_count": 2,
                    "lead_time_weeks": 8,
                    "unit_price": 1.2,
                    "supplier_data_verified": True,
                }
            ],
        )["recommendations"][0]
        self.assertEqual(row["Recommendation"], "Resolve supply gap")
        self.assertEqual(row["Available Stock"], 0)
        self.assertEqual(row["Supplier Sources"], 2)

    def test_manual_sourcing_override_is_used_for_recommendation(self):
        part = apply_sourcing_override(
            {
                "mpn": "TPS54331D",
                "quantity": 100,
                "stock_available": 0,
                "supplier_count": 0,
                "sourcing_override": {
                    "primary_supplier": "Mouser",
                    "stock_available": 200,
                    "supplier_count": 2,
                    "lead_time_weeks": 6,
                    "unit_price": 1.1,
                    "lifecycle_status": "Active",
                },
            }
        )
        row = build_procurement_advisor(analyses=[], parts=[part])["recommendations"][0]
        self.assertEqual(row["Available Stock"], 200)
        self.assertEqual(row["Supplier Sources"], 2)
        self.assertEqual(row["Recommendation"], "Monitor closely")

    def test_editor_keeps_blank_values_unknown_and_rejects_invalid_numbers(self):
        payload, errors = normalize_sourcing_override(
            {
                "primary_supplier": "  DigiKey ",
                "unit_price": "",
                "stock_available": "0",
                "supplier_count": "2.5",
                "lead_time_weeks": "8",
                "lifecycle_status": "Active",
            }
        )
        self.assertIsNone(payload["unit_price"])
        self.assertEqual(payload["stock_available"], 0)
        self.assertEqual(payload["primary_supplier"], "DigiKey")
        self.assertTrue(any("Supplier count" in error for error in errors))

    def test_editor_requires_currency_for_a_manual_unit_price(self):
        payload, errors = normalize_sourcing_override(
            {"unit_price": "1.25", "currency": ""}
        )
        self.assertEqual(payload["unit_price"], 1.25)
        self.assertTrue(any("Currency code" in error for error in errors))

    def test_saved_part_header_uses_component_metadata_and_analysis_date(self):
        html = procurement_header_html(
            {
                "mpn": "TPS54331D",
                "manufacturer": "Texas Instruments",
                "description": "Step-down regulator",
                "component_type": "Power management",
                "lifecycle_status": "Active",
                "unit_price": 1.2,
                "primary_supplier": "Mouser",
                "supplier_offers": [
                    {"distributor": "Mouser", "unit_price": 1.2, "currency": "USD"}
                ],
                "_analysis_created_at": "2026-10-11T15:00:00Z",
            }
        )
        self.assertIn("Step-down regulator", html)
        self.assertIn("Power management", html)
        self.assertIn("1.2 USD", html)
        self.assertIn("Oct 11, 2026", html)
        self.assertIn("BOM analysis", html)
        self.assertNotIn("Last updated</span><strong>Not recorded", html)

    def test_sourcing_updates_are_scoped_to_user_and_active_workspace(self):
        class Query:
            def __init__(self):
                self.filters = []
                self.updated = None
                self.selected = None

            def update(self, values):
                self.updated = values
                return self

            def eq(self, key, value):
                self.filters.append((key, value))
                return self

            def select(self, value):
                self.selected = value
                return self

            def execute(self):
                return SimpleNamespace(data=[{"id": "part-1"}, {"id": "part-2"}])

        query = Query()

        class Client:
            def table(self, name):
                self.table_name = name
                return query

        updated = persist_sourcing_update(
            Client(),
            user_id="user-1",
            workspace_id="workspace-1",
            mpn="TPS54331D",
            description="Step-down regulator",
            category="Power management",
            sourcing_override={"stock_available": 0},
            updated_at="2026-10-11T16:00:00+00:00",
        )
        self.assertEqual(updated, 2)
        self.assertEqual(
            query.filters,
            [("user_id", "user-1"), ("mpn", "TPS54331D"), ("workspace_id", "workspace-1")],
        )
        self.assertEqual(query.updated["sourcing_override"], {"stock_available": 0})
        self.assertEqual(query.selected, "id")


if __name__ == "__main__":
    unittest.main()
