"""Contracts for Cadivor's shared interactive engineering-table system."""
from __future__ import annotations

import unittest
import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = (
    ROOT / "src" / "ui" / "cadivor_design_system" / "components.py"
).read_text(encoding="utf-8")
PUBLIC_API = (
    ROOT / "src" / "ui" / "cadivor_design_system" / "__init__.py"
).read_text(encoding="utf-8")
CSS = (ROOT / "src" / "assets" / "css" / "cadivor_design_system.css").read_text(
    encoding="utf-8"
)
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
ANALYSIS_DETAIL = (ROOT / "src" / "pages" / "analysis_detail.py").read_text(
    encoding="utf-8"
)


class SmartTableSystemTests(unittest.TestCase):
    def test_design_system_owns_selection_and_context_contract(self):
        self.assertIn("class SmartTableResult", COMPONENTS)
        self.assertIn("class ExpandableTableColumn", COMPONENTS)
        self.assertIn("def selected_dataframe_rows(", COMPONENTS)
        self.assertIn("def cadivor_smart_dataframe(", COMPONENTS)
        self.assertIn("def cadivor_expandable_table(", COMPONENTS)
        self.assertIn('kwargs.setdefault("on_select", "rerun")', COMPONENTS)
        self.assertIn('selection_mode: str | Sequence[str] = ("single-row", "single-cell")', COMPONENTS)
        self.assertIn("cells = getattr(selection, \"cells\", None)", COMPONENTS)
        self.assertIn("def humanize_table_date(", COMPONENTS)
        self.assertIn("def semantic_priority_label(", COMPONENTS)
        for exported_name in (
            "SmartTableResult",
            "ExpandableTableColumn",
            "cadivor_expandable_table",
            "cadivor_smart_dataframe",
            "humanize_table_date",
            "semantic_priority_label",
        ):
            self.assertIn(f'"{exported_name}"', PUBLIC_API)

    def test_selected_rows_have_visible_shared_feedback(self):
        self.assertIn(".cv-smart-table-context", CSS)
        self.assertIn('[aria-selected="true"]', CSS)
        self.assertIn(".cv-expandable-table__row--open", CSS)
        self.assertIn('st-key-cv_expandable_detail_', CSS)
        self.assertIn("prefers-reduced-motion", CSS)

    def test_expandable_table_owns_one_inline_detail_slot(self):
        self.assertIn("def _toggle_expandable_table_row(", COMPONENTS)
        self.assertIn("detail_slot = st.empty()", COMPONENTS)
        self.assertIn("on_click=_toggle_expandable_table_row", COMPONENTS)
        self.assertIn("selected_token == row_token", COMPONENTS)
        self.assertIn("initial_row_id: Any | None = None", COMPONENTS)
        self.assertIn("requested_token = _expandable_table_token(initial_row_id", COMPONENTS)
        self.assertIn("initial_request_key", COMPONENTS)
        self.assertIn("detail_slot=detail_slot", COMPONENTS)
        self.assertIn("on_toggle: Callable[[Any], None] | None = None", COMPONENTS)
        self.assertIn("on_toggle(row_id if next_token else", COMPONENTS)
        self.assertIn("args=(state_key, row_token, row_id, on_toggle)", COMPONENTS)

    def test_expandable_table_notifies_open_and_collapse_at_click_time(self):
        tree = ast.parse(COMPONENTS)
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_toggle_expandable_table_row"
        )
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__",
                    names=[ast.alias(name="annotations")],
                    level=0,
                ),
                helper,
            ],
            type_ignores=[],
        )
        state = {}
        notifications = []
        namespace = {
            "Any": Any,
            "Callable": Callable,
            "st": SimpleNamespace(session_state=state),
        }
        exec(compile(ast.fix_missing_locations(module), "<table-toggle>", "exec"), namespace)
        toggle = namespace["_toggle_expandable_table_row"]

        toggle("selected", "row-token", "MCP2551-I/SN", notifications.append)
        self.assertEqual(state["selected"], "row-token")
        self.assertEqual(notifications[-1], "MCP2551-I/SN")

        toggle("selected", "row-token", "MCP2551-I/SN", notifications.append)
        self.assertEqual(state["selected"], "")
        self.assertEqual(notifications[-1], "")

        toggle("selected", "row-token", "MCP2551-I/SN", notifications.append)
        self.assertEqual(state["selected"], "row-token")
        self.assertEqual(notifications[-1], "MCP2551-I/SN")

    def test_monitoring_queue_and_coverage_share_the_contract(self):
        monitoring = RUNTIME.split('if app_mode == "Monitoring":', 1)[1].split(
            'if app_mode == "Supply Risk Scenario":', 1
        )[0]
        self.assertGreaterEqual(monitoring.count("cadivor_expandable_table("), 2)
        self.assertIn("queue_table_result = cadivor_expandable_table(", monitoring)
        self.assertIn("queue_table_result.detail_slot.container()", monitoring)
        self.assertIn("component_table_result = cadivor_expandable_table(", monitoring)
        self.assertIn("component_table_result.first_selected_row", monitoring)
        self.assertIn("component_table_result.detail_slot.container()", monitoring)
        self.assertIn("row_ids=(", monitoring)
        self.assertIn("Click a component to expand", monitoring)
        self.assertIn("semantic_priority_label(score)", monitoring)
        self.assertIn("humanize_table_date(", monitoring)

    def test_saved_bom_components_use_row_selection_not_a_picker(self):
        component_branch = ANALYSIS_DETAIL.split("if parts:", 1)[1]
        self.assertIn("component_table_result = cadivor_expandable_table(", component_branch)
        self.assertIn("component_table_result.first_selected_row", component_branch)
        self.assertIn("component_table_result.detail_slot.container()", component_branch)
        self.assertIn("initial_row_id=(", component_branch)
        self.assertIn("row_ids=component_row_ids", component_branch)
        self.assertNotIn('st.selectbox("Select a component to inspect"', component_branch)

    def test_alternative_finder_selection_drives_the_candidate_workspace(self):
        finder = RUNTIME.split('if app_mode == "Alternative Finder":', 1)[1].split(
            'if app_mode == "Compare Parts":', 1
        )[0]
        self.assertIn("candidate_table_result = cadivor_expandable_table(", finder)
        self.assertIn("candidate_table_result.first_selected_row", finder)
        self.assertIn("candidate_table_result.detail_slot.container()", finder)
        self.assertIn("row_ids=alternative_options", finder)
        self.assertIn("Click a candidate row to expand", finder)
        self.assertIn("build_alternative_candidate_insight(", finder)
        self.assertIn("sync_alternative_finder_selected_candidate_result(", finder)
        self.assertNotIn('st.selectbox("Recommended candidate"', finder)

    def test_decisions_and_reports_use_focused_evidence_rows(self):
        decisions = RUNTIME.split('if app_mode == "Engineering Decisions":', 1)[1].split(
            'if app_mode == "Reports":', 1
        )[0]
        reports = RUNTIME.split('if app_mode == "Reports":', 1)[1].split(
            'if app_mode == "Notifications":', 1
        )[0]
        self.assertIn("decision_table_result = cadivor_expandable_table(", decisions)
        self.assertIn("render_expanded=_render_queue_decision", decisions)
        self.assertIn("driver_table_result = cadivor_expandable_table(", decisions)
        self.assertIn("render_expanded=_render_driver_queue_intelligence", decisions)
        self.assertIn("Click a row to expand its evidence and actions.", decisions)
        self.assertIn("report_table_result = cadivor_smart_dataframe(", reports)
        self.assertIn("selected_report_row = visible.iloc", reports)
        self.assertIn("Run Alternative Finder for", reports)

    def test_decision_actions_carry_component_context_to_monitoring(self):
        action_helper = COMPONENTS.split("def render_decision_card_actions(", 1)[1]
        self.assertIn('"Open Monitoring"', action_helper)
        self.assertIn('mpn=(decision.get("mpn") or decision.get("part_number"))', action_helper)
        self.assertIn('return_analysis_id=str(decision.get("analysis_id")', action_helper)
        self.assertIn('"Review component decisions"', action_helper)
        self.assertIn('analysis_tab="Engineering Decisions"', action_helper)
        self.assertIn('target_type = str(decision.get("target_type")', action_helper)

    def test_decision_queue_uses_explicit_target_scope_and_context(self):
        decisions = RUNTIME.split('if app_mode == "Engineering Decisions":', 1)[1].split(
            'if app_mode == "Reports":', 1
        )[0]
        self.assertIn('component_decisions, bom_decisions = partition_decision_queue(visible)', decisions)
        self.assertIn('target_column: decision_target_cell(decision)', decisions)
        self.assertIn('target_column="Component"', decisions)
        self.assertIn('target_column="Saved BOM"', decisions)
        self.assertIn('kind="target"', decisions)
        self.assertIn('Saved BOM context:', decisions)
        self.assertIn('decision_target_context(decision)', decisions)
        self.assertIn('decision_target_type(selected_decision)', decisions)


if __name__ == "__main__":
    unittest.main()
