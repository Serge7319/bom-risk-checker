import unittest
from pathlib import Path

from src.cost_optimization import _opportunity_table_markup, build_cost_optimization


class CostOptimizationWorkspaceTests(unittest.TestCase):
    def test_opportunity_table_uses_saved_prices_and_component_illustrations(self):
        intelligence = build_cost_optimization(
            [{"id": "analysis-1", "project_name": "Motor controller"}],
            [
                {
                    "analysis_id": "analysis-1",
                    "mpn": "CAP-100",
                    "description": "Ceramic capacitor",
                    "category": "Ceramic capacitor",
                    "manufacturer": "Acme",
                    "quantity": 10,
                    "unit_price": 1.25,
                    "supplier_count": 2,
                    "stock_available": 100,
                    "risk_score": 20,
                }
            ],
            build_quantity=100,
        )

        self.assertEqual(intelligence["production_run_cost"], 1250)
        self.assertEqual(intelligence["estimated_savings"], 62.5)
        self.assertEqual(intelligence["opportunities"][0]["Description"], "Ceramic capacitor")
        self.assertEqual(intelligence["opportunities"][0]["Component Category"], "Ceramic capacitor")

        markup = _opportunity_table_markup(intelligence["opportunities"])

        self.assertIn('data-illustration="capacitor"', markup)
        self.assertIn("Ceramic capacitor", markup)
        self.assertIn("CAP-100", markup)
        self.assertIn("$1.2500", markup)
        self.assertIn("$62.50", markup)
        self.assertIn("Opportunity", markup)
        self.assertIn("Review status", markup)
        self.assertIn("Needs review", markup)

    def test_cost_route_uses_the_data_driven_workspace(self):
        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        route = source.split("# ---------- Cost Optimization ----------", 1)[1].split(
            "# ---------- Design Impact Analyzer ----------", 1
        )[0]

        self.assertNotIn("render_simple_workspace", route)
        self.assertIn("render_cost_optimization(", route)
        self.assertIn("control=_cost_build_control", route)


if __name__ == "__main__":
    unittest.main()
