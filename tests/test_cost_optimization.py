import base64
import unittest
from pathlib import Path

from src.cost_optimization import _opportunity_table_markup, build_cost_optimization
from src.part_images import part_image_source
from tests.evidence_fixtures import live_supplier_part


class CostOptimizationWorkspaceTests(unittest.TestCase):
    def test_opportunity_table_uses_saved_prices_and_component_illustrations(self):
        part = live_supplier_part(
            "CAP-100",
            lifecycle="Active",
            stock=1000,
            quantity=10,
            unit_price=1.25,
        )
        part.update({
            "analysis_id": "analysis-1",
            "description": "Ceramic capacitor",
            "category": "Ceramic capacitor",
            "package": "Radial through-hole",
        })
        intelligence = build_cost_optimization(
            [{"id": "analysis-1", "project_name": "Motor controller"}],
            [part],
            build_quantity=100,
        )

        self.assertEqual(intelligence["production_run_cost"], 1250)
        self.assertEqual(intelligence["estimated_savings"], 62.5)
        self.assertEqual(intelligence["opportunities"][0]["Description"], "Ceramic capacitor")
        self.assertEqual(intelligence["opportunities"][0]["Component Category"], "Ceramic capacitor")
        self.assertEqual(
            intelligence["opportunities"][0]["Image Context"]["package"],
            "Radial through-hole",
        )
        image_source = intelligence["rows"][0]["Image URL"]
        self.assertTrue(image_source.startswith("data:image/png;base64,"))
        self.assertTrue(
            base64.b64decode(image_source.split(",", 1)[1]).startswith(
                bytes.fromhex("89504e470d0a1a0a")
            )
        )

        markup = _opportunity_table_markup(intelligence["opportunities"])
        expected_image = part_image_source(
            "",
            "CAP-100",
            category="Ceramic capacitor",
            part=intelligence["opportunities"][0]["Image Context"],
        )

        self.assertIn('data-illustration="capacitor"', markup)
        self.assertIn(f'src="{expected_image}"', markup)
        self.assertIn("Ceramic capacitor", markup)
        self.assertIn("CAP-100", markup)
        self.assertIn("$1.31", markup)
        self.assertIn("$62.50", markup)
        self.assertIn("Comparable supplier quote", markup)
        self.assertIn("Review status", markup)
        self.assertIn("Confirm quote", markup)
        self.assertIn("Find alternatives", markup)
        self.assertIn("page=Alternative%20Finder", markup)
        self.assertIn("original_part=CAP-100", markup)

    def test_unverified_saved_price_and_risk_are_not_used_as_current_metrics(self):
        intelligence = build_cost_optimization(
            [{"id": "analysis-1", "project_name": "Motor controller"}],
            [{
                "analysis_id": "analysis-1",
                "mpn": "CAP-100",
                "quantity": 10,
                "unit_price": 1.25,
                "unit_price_currency": "USD",
                "risk_score": 4,
            }],
            build_quantity=100,
        )

        self.assertIsNone(intelligence["production_run_cost"])
        self.assertEqual(intelligence["pricing_coverage"], 0)
        self.assertEqual(intelligence["rows"][0]["Unit Price"], 0.0)
        self.assertIsNone(intelligence["rows"][0]["Risk Score"])

    def test_partial_price_coverage_does_not_report_a_full_bom_run_cost(self):
        priced = live_supplier_part("CAP-100", unit_price=1.25, quantity=10)
        priced.update({"analysis_id": "analysis-1", "description": "Capacitor"})
        unpriced = {"analysis_id": "analysis-1", "mpn": "RES-100", "quantity": 10}
        intelligence = build_cost_optimization(
            [{"id": "analysis-1", "project_name": "Motor controller"}],
            [priced, unpriced],
            build_quantity=100,
        )

        self.assertEqual(intelligence["pricing_coverage"], 50)
        self.assertIsNone(intelligence["production_run_cost"])

    def test_cost_route_uses_the_data_driven_workspace(self):
        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        route = source.split("# ---------- Cost Optimization ----------", 1)[1].split(
            "# ---------- Design Impact Analyzer ----------", 1
        )[0]

        self.assertNotIn("render_simple_workspace", route)
        self.assertIn("render_cost_optimization(", route)
        self.assertIn("control=_cost_build_control", route)
        workspace = Path("src/cost_optimization.py").read_text(encoding="utf-8")
        self.assertIn('st.container(key="cost_optimization_workspace")', workspace)
        self.assertIn("max-width:1500px", workspace)
        self.assertIn(
            "from src.ui.approved_pages import begin_approved_page, end_approved_page",
            workspace,
        )
        self.assertIn("end_approved_page()", workspace)


if __name__ == "__main__":
    unittest.main()
