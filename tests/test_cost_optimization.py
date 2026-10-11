import base64
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
        image_source = intelligence["rows"][0]["Image URL"]
        self.assertTrue(image_source.startswith("data:image/png;base64,"))
        self.assertTrue(
            base64.b64decode(image_source.split(",", 1)[1]).startswith(
                bytes.fromhex("89504e470d0a1a0a")
            )
        )

        markup = _opportunity_table_markup(intelligence["opportunities"])

        self.assertIn('data-illustration="capacitor"', markup)
        self.assertIn("Ceramic capacitor", markup)
        self.assertIn("CAP-100", markup)
        self.assertIn("$1.2500", markup)
        self.assertIn("$62.50", markup)
        self.assertIn("Opportunity", markup)
        self.assertIn("Review status", markup)
        self.assertIn("Needs review", markup)
        self.assertIn("Find alternatives", markup)
        self.assertIn("page=Alternative%20Finder", markup)
        self.assertIn("original_part=CAP-100", markup)

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


if __name__ == "__main__":
    unittest.main()
