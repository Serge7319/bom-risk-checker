import unittest
from pathlib import Path
from types import SimpleNamespace
import pandas as pd

from src.procurement_advisor import (
    apply_sourcing_override,
    build_procurement_advisor,
    normalize_sourcing_override,
    persist_sourcing_update,
    procurement_details_display_frame,
    procurement_header_html,
    procurement_page_header_html,
    procurement_part_summary_html,
    procurement_recommendation_html,
    procurement_summary_cards_html,
    procurement_supplier_insight_context,
    procurement_workspace_panels_html,
    generate_procurement_supplier_insight,
    normalize_supplier_offer_records,
    supplier_comparison_table_html,
    sourcing_editor_values,
    supplier_comparison_dataframe,
    supplier_landed_cost_override,
    supplier_offer_override,
)


class ProcurementAdvisorTests(unittest.TestCase):
    def test_sourcing_recommendation_markup_uses_visible_streamlit_containers(self):
        part = {"mpn": "TPS54331D", "description": "Power controller"}
        recommendation = {
            "Recommendation": "Complete sourcing data",
            "Next Step": "Confirm the current supplier quote.",
            "Supplier Sources": None,
        }
        self.assertIn("<h1>Procurement advisor</h1>", procurement_page_header_html())
        self.assertIn("<div class='cv-pa-page-head'>", procurement_page_header_html())
        self.assertNotIn("<header", procurement_page_header_html())

        part_html = procurement_part_summary_html(part, recommendation)
        self.assertIn("<div class='cv-pa-summary'>", part_html)
        self.assertNotIn("<section", part_html)

        recommendation_html = procurement_recommendation_html(part, recommendation)
        self.assertIn("<div class='cv-pa-recommendation-v2'>", recommendation_html)
        self.assertNotIn("<section", recommendation_html)

        cards_html = procurement_summary_cards_html(part, recommendation)
        self.assertIn("<div class='cv-pa-metric-grid'>", cards_html)
        self.assertIn("<div class='cv-pa-metric cv-pa-metric--", cards_html)
        self.assertNotIn("<article", cards_html)

    def test_sidebar_names_procurement_destination_sourcing_recommendation(self):
        from src.ui.approved_shell_nav import shared_nav_groups

        decision_tools = next(
            rows for group, rows in shared_nav_groups() if group == "Decision Tools"
        )
        self.assertIn(
            ("Sourcing Recommendation", "procurement", "Procurement Advisor"),
            decision_tools,
        )

    def test_sourcing_workspace_panels_share_one_render_block_and_keep_mockup_sections(self):
        markup = procurement_workspace_panels_html(
            {"mpn": "TPS54331D", "description": "Power controller"},
            {
                "Recommendation": "Complete sourcing data",
                "Next Step": "Confirm the current supplier quote.",
                "Supplier Sources": None,
            },
        )

        self.assertEqual(markup.count("<style>"), 1)
        self.assertEqual(markup.count("</style>"), 1)
        self.assertIn("<div class='cv-pa-summary'>", markup)
        self.assertIn("<div class='cv-pa-recommendation-v2'>", markup)
        self.assertIn("<div class='cv-pa-metric-grid'>", markup)

        runtime = (
            Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
        ).read_text(encoding="utf-8")
        branch = runtime.split('if app_mode == "Procurement Advisor":', 1)[1].split(
            'if app_mode == "Engineering Decisions":', 1
        )[0]
        self.assertIn("max-width:1440px", branch)
        self.assertLess(
            branch.index("procurement_workspace_panels_html("),
            branch.index("<h2>Supplier options</h2>"),
        )
        self.assertLess(
            branch.index("procurement_workspace_panels_html("),
            branch.index('reveal_authenticated_page_body("Procurement Advisor")'),
        )

    def test_procurement_advisor_explains_its_decision_and_hands_off_bom_context(self):
        runtime = (
            Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
        ).read_text(encoding="utf-8")
        branch = runtime.split('if app_mode == "Procurement Advisor":', 1)[1].split(
            'if app_mode == "Engineering Decisions":', 1
        )[0]

        self.assertIn("What to review here", branch)
        self.assertIn("“Not recorded” means Cadivor", branch)
        self.assertIn("does not have verified data", branch)
        self.assertIn("does not place an order", branch)
        self.assertIn('"Find qualified alternative"', branch)
        self.assertIn('key="pa_find_qualified_alternative_top"', branch)
        self.assertIn('analysis_id=str(focus.get("analysis_id") or focus_analysis.get("id") or "")', branch)
        self.assertLess(
            branch.index('key="pa_find_qualified_alternative_top"'),
            branch.index('"<div class=\'cv-pa-section-head\'><div><h2>Supplier options</h2>'),
        )

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

    def test_sourcing_context_fields_can_be_saved_without_verifying_supplier_fields(self):
        override, errors = normalize_sourcing_override(
            {
                "annual_demand": "50000",
                "target_unit_price": "2.10",
                "target_currency": "usd",
                "required_by": "Q3 2026",
            }
        )
        self.assertEqual(errors, [])
        self.assertEqual(override["annual_demand"], 50000)
        self.assertEqual(override["target_unit_price"], 2.1)
        self.assertEqual(override["target_currency"], "USD")
        self.assertEqual(override["required_by"], "Q3 2026")

        part = apply_sourcing_override(
            {"mpn": "TPS54331D", "supplier_data_verified": False, "sourcing_override": {
                "annual_demand": 50000,
                "target_unit_price": 2.1,
                "target_currency": "USD",
                "required_by": "Q3 2026",
            }}
        )
        self.assertFalse(part["supplier_data_verified"])
        self.assertEqual(sourcing_editor_values(part)["annual_demand"], 50000)
        self.assertEqual(sourcing_editor_values(part)["required_by"], "Q3 2026")

    def test_context_only_override_does_not_hide_legacy_supplier_evidence(self):
        part = apply_sourcing_override(
            {
                "mpn": "TPS54331D",
                "primary_supplier": "Mouser",
                "unit_price": 1.25,
                "currency": "USD",
                "supplier_data_verified": None,
                "sourcing_override": {"annual_demand": 50000},
            }
        )
        current = normalize_supplier_offer_records(part)[0]
        self.assertTrue(current["is_current"])
        self.assertEqual(current["unit_price"], 1.25)

    def test_target_price_requires_its_own_currency(self):
        payload, errors = normalize_sourcing_override(
            {"target_unit_price": "2.1", "target_currency": ""}
        )
        self.assertEqual(payload["target_unit_price"], 2.1)
        self.assertTrue(any("Target currency" in error for error in errors))

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

    def test_supplier_comparison_keeps_unknown_stock_as_text_and_marks_current_offer(self):
        frame = supplier_comparison_dataframe(
            {
                "mpn": "TPS54331D",
                "primary_supplier": "DigiKey",
                "unit_price": 2.0,
                "currency": "USD",
                "supplier_data_verified": True,
                "supplier_offers": [
                    {
                        "mpn": "TPS54331D",
                        "distributor": "DigiKey",
                        "unit_price": 2.0,
                        "currency": "USD",
                        "price_break_quantity": 10,
                        "stock": None,
                    },
                    {
                        "mpn": "TPS54331D",
                        "distributor": "Mouser",
                        "unit_price": 1.8,
                        "currency": "USD",
                        "price_break_quantity": 10,
                        "stock": "25000",
                    },
                ],
            },
            selected_supplier="DigiKey",
        )
        self.assertEqual(frame.loc[0, "Selected"], "● Selected")
        self.assertEqual(frame.loc[0, "Available stock"], "Not recorded")
        self.assertEqual(frame.loc[1, "Available stock"], "25,000")
        self.assertEqual(frame.loc[1, "Price vs current"], "-10.0%")
        self.assertTrue(all(str(dtype) == "object" for dtype in frame.dtypes))

    def test_supplier_comparison_mockup_table_highlights_selection_and_escapes_supplier_text(self):
        markup = supplier_comparison_table_html(
            {
                "mpn": "TPS54331D",
                "quantity": 100,
                "supplier_offers": [
                    {
                        "distributor": "Mouser <script>",
                        "unit_price": 1.8,
                        "currency": "USD",
                        "stock": 75,
                        "lead_time_weeks": 12,
                        "region": "US",
                        "supply_risk": "Medium",
                        "retrieved_at": "2026-10-16T09:00:00Z",
                    },
                    {
                        "distributor": "DigiKey",
                        "unit_price": 2.0,
                        "currency": "USD",
                        "stock": 120,
                        "lead_time_weeks": 8,
                    },
                ],
            },
            selected_supplier="Mouser <script>",
            required_quantity=100,
        )
        self.assertIn("cv-pa-supplier-table", markup)
        self.assertIn("is-selected", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertNotIn("<script>", markup)
        self.assertIn("Short by 25 for BOM", markup)
        self.assertIn("Lowest quote", markup)
        self.assertIn("Not assessed", markup)
        self.assertIn("Total cost index", markup)

    def test_supplier_table_ranks_only_comparable_entered_landed_costs(self):
        part = {
            "mpn": "TPS54331D",
            "supplier_offers": [
                {"distributor": "Mouser", "unit_price": 1.80, "currency": "USD"},
                {"distributor": "DigiKey", "unit_price": 2.00, "currency": "USD"},
                {"distributor": "Newark", "unit_price": 1.75, "currency": "EUR"},
            ],
            "sourcing_override": {
                "supplier_landed_costs": {
                    "mouser": {"supplier": "Mouser", "unit_cost": 1.95, "currency": "USD"},
                    "digikey": {"supplier": "DigiKey", "unit_cost": 2.05, "currency": "USD"},
                    "newark": {"supplier": "Newark", "unit_cost": 1.80, "currency": "EUR"},
                },
            },
        }
        markup = supplier_comparison_table_html(part, view="All evidence")
        self.assertIn("<th>Total cost index</th>", markup)
        self.assertIn("<th>Landed unit cost</th>", markup)
        self.assertIn("<strong>100</strong>", markup)
        self.assertIn("<strong>95</strong>", markup)
        # The EUR quote is not ranked against the USD landed costs.
        self.assertIn("Need comparable quote", markup)

        one_cost = supplier_comparison_table_html(
            {
                "mpn": "TPS54331D",
                "supplier_offers": part["supplier_offers"][:2],
                "sourcing_override": {
                    "supplier_landed_costs": {
                        "mouser": {"supplier": "Mouser", "unit_cost": 1.95, "currency": "USD"},
                    },
                },
            }
        )
        self.assertIn("Need comparable quote", one_cost)
        self.assertIn("Add landed cost", one_cost)

    def test_landed_cost_save_merges_with_existing_procurement_override(self):
        override = supplier_landed_cost_override(
            {
                "sourcing_override": {
                    "annual_demand": 50000,
                    "required_by": "Q4 2026",
                    "primary_supplier": "Mouser",
                    "supplier_count": 2,
                }
            },
            "DigiKey",
            "2.15",
            "usd",
        )
        self.assertEqual(override["annual_demand"], 50000)
        self.assertEqual(override["required_by"], "Q4 2026")
        self.assertEqual(override["supplier_landed_costs"]["digikey"]["unit_cost"], 2.15)
        self.assertEqual(override["supplier_landed_costs"]["digikey"]["currency"], "USD")
        with self.assertRaisesRegex(ValueError, "three-letter currency"):
            supplier_landed_cost_override({}, "Mouser", "2.10", "US")

    def test_supplier_insight_uses_saved_evidence_and_explicit_fallback(self):
        part = {
            "mpn": "TPS54331D",
            "supplier_offers": [
                {"distributor": "Mouser", "unit_price": 1.8, "currency": "USD", "stock": 250, "product_url": "https://supplier.example/part"}
            ],
        }
        recommendation = {
            "Recommendation": "Add a second source",
            "Next Step": "Qualify another source.",
            "Missing Sourcing Data": "supplier coverage, lead time",
        }
        context = procurement_supplier_insight_context(part, recommendation)
        self.assertEqual(context["sourcing_evidence"]["quotes"][0]["supplier"], "Mouser")
        self.assertNotIn("product_url", context["sourcing_evidence"]["quotes"][0])

        class AIStub:
            configured = True

            def ask(self, *, question, context, history):
                self.question = question
                self.context = context
                self.history = history
                return SimpleNamespace(
                    answer="### Supplier insights\n- Saved quote evidence only.",
                    provider="anthropic",
                    model="test-model",
                    grounded=True,
                )

        stub = AIStub()
        result = generate_procurement_supplier_insight(
            part, recommendation, ai_client=stub
        )
        self.assertEqual(result["provider"], "anthropic")
        self.assertTrue(result["ai_assisted"])
        self.assertIn("Never invent prices", stub.question)
        self.assertEqual(stub.history, [])

        fallback = generate_procurement_supplier_insight(
            part, recommendation, ai_client=SimpleNamespace(configured=False)
        )
        self.assertEqual(fallback["provider"], "cadivor-grounded")
        self.assertFalse(fallback["ai_assisted"])
        self.assertIn("quote does not establish authorization", fallback["answer"])
        self.assertIn("Total cost is not rankable yet", fallback["answer"])

    def test_selected_supplier_offer_override_preserves_other_verified_values(self):
        override = supplier_offer_override(
            {
                "mpn": "TPS54331D",
                "sourcing_override": {
                    "primary_supplier": "DigiKey",
                    "supplier_count": 2,
                    "lead_time_weeks": 8,
                    "lifecycle_status": "Active",
                    "annual_demand": 50000,
                    "supplier_landed_costs": {
                        "digikey": {"supplier": "DigiKey", "unit_cost": 2.1, "currency": "USD"},
                    },
                },
                "supplier_offers": [
                    {
                        "distributor": "Mouser",
                        "unit_price": 1.8,
                        "currency": "USD",
                        "stock": 125,
                        "lead_time_weeks": 6,
                    }
                ],
            },
            "Mouser",
        )
        self.assertEqual(override["primary_supplier"], "Mouser")
        self.assertEqual(override["unit_price"], 1.8)
        self.assertEqual(override["currency"], "USD")
        self.assertEqual(override["stock_available"], 125)
        self.assertEqual(override["supplier_count"], 2)
        self.assertEqual(override["lead_time_weeks"], 6)
        self.assertEqual(override["lifecycle_status"], "Active")
        self.assertEqual(override["annual_demand"], 50000)
        self.assertEqual(override["supplier_landed_costs"]["digikey"]["unit_cost"], 2.1)

    def test_procurement_details_keeps_nullable_numeric_columns_arrow_safe(self):
        frame = procurement_details_display_frame(
            pd.DataFrame(
                {
                    "Part Number": ["A", "B"],
                    "Available Stock": [150, None],
                    "Supplier Sources": [2, None],
                    "Unit Price": [1.25, None],
                    "Recommendation": ["Buy now", None],
                }
            )
        )
        self.assertEqual(str(frame["Available Stock"].dtype), "Int64")
        self.assertEqual(str(frame["Unit Price"].dtype), "Float64")
        self.assertEqual(frame.loc[1, "Recommendation"], "Not recorded")
        self.assertTrue(pd.isna(frame.loc[1, "Available Stock"]))
        self.assertTrue(pd.isna(frame.loc[1, "Unit Price"]))

    def test_unverified_legacy_source_fields_do_not_leak_into_offer_comparison(self):
        rows = supplier_comparison_dataframe(
            {
                "mpn": "TPS54331D",
                "primary_supplier": "Legacy supplier",
                "supplier_data_verified": False,
                "stock_available": 9999,
                "unit_price": 9.99,
                "supplier_count": 4,
                "lead_time_weeks": 1,
                "supplier_offers": [
                    {
                        "mpn": "TPS54331D",
                        "distributor": "Mouser",
                        "unit_price": 1.8,
                        "currency": "USD",
                        "stock": 25,
                    }
                ],
            }
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("Mouser", rows.loc[0, "Supplier"])
        self.assertNotIn("Legacy supplier", rows.loc[0, "Supplier"])

    def test_summary_cards_do_not_invent_annual_savings_or_blended_risk(self):
        html = procurement_summary_cards_html(
            {"mpn": "TPS54331D"},
            {
                "Recommendation": "Complete sourcing data",
                "Next Step": "Confirm the current quote.",
                "Supplier Sources": None,
            },
        )
        self.assertIn("Estimated annual savings", html)
        self.assertIn("Annual demand and comparable same-currency supplier quotes are required", html)
        self.assertIn("Supply risk (blended)", html)
        self.assertIn("Not assessed", html)

    def test_annual_savings_uses_landed_cost_when_comparable_costs_exist(self):
        html = procurement_summary_cards_html(
            {
                "mpn": "TPS54331D",
                "annual_demand": 50000,
                "primary_supplier": "Mouser",
                "unit_price": 2.0,
                "currency": "USD",
                "supplier_data_verified": True,
                "supplier_offers": [
                    {"distributor": "Mouser", "unit_price": 2.0, "currency": "USD"},
                    {"distributor": "DigiKey", "unit_price": 1.8, "currency": "USD"},
                ],
                "sourcing_override": {
                    "supplier_landed_costs": {
                        "mouser": {"supplier": "Mouser", "unit_cost": 2.10, "currency": "USD"},
                        "digikey": {"supplier": "DigiKey", "unit_cost": 1.90, "currency": "USD"},
                    },
                },
            },
            {"Recommendation": "Add a second source", "Next Step": "Qualify DigiKey."},
        )
        self.assertIn("10,000.00 USD", html)
        self.assertIn("Entered landed costs vs current source", html)

    def test_sourcing_recommendation_header_uses_annual_demand_and_target_fields(self):
        html = procurement_part_summary_html(
            {
                "mpn": "TPS54331D",
                "description": "Power management IC",
                "manufacturer": "Texas Instruments",
                "annual_demand": 50000,
                "quantity": 100,
                "target_unit_price": 2.1,
                "target_currency": "USD",
                "required_by": "Q3 2025",
            },
            {
                "Recommendation": "Add a second source",
                "Supplier Sources": 1,
                "Lifecycle Status": "Active",
            },
        )
        self.assertIn("Annual demand", html)
        self.assertIn("50,000 units", html)
        self.assertIn("2.1 USD", html)
        self.assertIn("Q3 2025", html)
        self.assertIn("Single source", html)
        self.assertNotIn("BOM quantity", html)

    def test_sourcing_header_does_not_substitute_bom_quantity_for_annual_demand(self):
        html = procurement_part_summary_html(
            {"mpn": "TPS54331D", "quantity": 100},
            {"Recommendation": "Complete sourcing data", "Supplier Sources": None},
        )
        self.assertIn("Annual demand</span><strong>Not recorded", html)
        self.assertNotIn("100 units", html)

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
