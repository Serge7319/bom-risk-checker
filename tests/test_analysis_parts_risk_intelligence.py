"""Contracts for the saved BOM Parts & Risk inline intelligence table."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DETAIL = (ROOT / "src" / "pages" / "analysis_detail.py").read_text(
    encoding="utf-8"
)
CSS = (ROOT / "src" / "assets" / "css" / "analysis_detail_v2.css").read_text(
    encoding="utf-8"
)


class AnalysisPartsRiskIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.branch = ANALYSIS_DETAIL.split('if active_tab == "Components":', 1)[1].split(
            'if active_tab == "Alternatives":', 1
        )[0]

    def test_parts_table_expands_details_in_place(self):
        self.assertIn("cadivor_expandable_table(", self.branch)
        self.assertIn('"Component", "Component", 1.15, 150, kind="strong"', self.branch)
        self.assertIn("row_ids=component_row_ids", self.branch)
        self.assertIn("component_table_result.detail_slot.container()", self.branch)
        self.assertNotIn("table_col, detail_col = st.columns", self.branch)
        self.assertNotIn("Component Intelligence", self.branch)

    def test_expanded_row_explains_bom_impact_instead_of_repeating_cells(self):
        for copy in (
            "Decision context",
            "BOM demand",
            "Inventory coverage",
            "Sourcing resilience",
            "Schedule exposure",
            "Linked intelligence",
            "Stored risk explanation",
        ):
            self.assertIn(copy, self.branch)
        self.assertIn("_component_risk_detail_model(", self.branch)
        self.assertIn("complete BOM build", ANALYSIS_DETAIL)
        self.assertIn("Records explicitly linked to this component", self.branch)

    def test_actions_are_contextual_and_preload_the_component(self):
        self.assertIn('"Run Alternative Finder"', self.branch)
        self.assertIn("original_part=selected_mpn", self.branch)
        self.assertIn('"Open decision workflow"', self.branch)
        self.assertIn("on_click=_open_component_analysis_section", self.branch)
        self.assertIn('"Engineering Decisions"', self.branch)
        self.assertIn('"Monitor component"', self.branch)
        self.assertIn('"View design impact"', self.branch)
        self.assertIn('if detail["url"] and len(action_specs) < 4:', self.branch)

    def test_deep_linked_component_opens_and_clears_stale_filters(self):
        self.assertIn('st.session_state[f"analysis_component_search_{analysis_id}"] = ""', self.branch)
        self.assertIn('st.session_state[f"analysis_component_risk_{analysis_id}"] = "All"', self.branch)
        self.assertIn("initial_row_id=(", self.branch)
        self.assertIn("requested_row_id", self.branch)

    def test_inline_detail_has_clear_responsive_visual_hierarchy(self):
        for selector in (
            ".cv-part-risk-detail",
            ".cv-part-risk-summary",
            ".cv-part-risk-driver-grid",
            ".cv-part-risk-evidence-grid",
            ".cv-part-risk-evidence-card",
        ):
            self.assertIn(selector, CSS)
        self.assertIn("@media (max-width: 760px)", CSS)

    def test_decision_model_calculates_real_bom_impact(self):
        tree = ast.parse(ANALYSIS_DETAIL)
        helper_names = {
            "_safe",
            "_num",
            "_part_value",
            "_risk_label",
            "_matching_component_records",
            "_component_risk_detail_model",
        }
        helper_nodes = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in helper_names
        ]
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__",
                    names=[ast.alias(name="annotations")],
                    level=0,
                ),
                *helper_nodes,
            ],
            type_ignores=[],
        )
        namespace: dict[str, object] = {}
        exec(compile(ast.fix_missing_locations(module), "analysis_detail_helpers", "exec"), namespace)
        build_detail = namespace["_component_risk_detail_model"]
        detail = build_detail(
            {
                "mpn": "MCP2551-I/SN",
                "manufacturer": "Microchip Technology",
                "lifecycle_status": "Obsolete",
                "quantity": 4,
                "stock_available": 10,
                "supplier_count": 1,
                "lead_time_weeks": 16,
                "risk_score": 85,
                "risk_level": "High",
                "unit_price": 2.5,
            },
            alerts=[{"part_number": "mcp2551-i/sn"}],
            alternatives=[{"original_part": "MCP2551-I/SN"}],
        )
        self.assertEqual(detail["inventory_coverage"], "2 complete BOM builds")
        self.assertEqual(detail["extended_cost"], 10.0)
        self.assertEqual(detail["alert_count"], 1)
        self.assertEqual(detail["alternative_count"], 1)
        self.assertTrue(detail["needs_alternative"])
        self.assertTrue(detail["needs_decision"])
        self.assertEqual(
            {driver[0] for driver in detail["drivers"]},
            {"Lifecycle continuity", "Supplier concentration", "Schedule exposure"},
        )


if __name__ == "__main__":
    unittest.main()
