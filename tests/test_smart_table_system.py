"""Contracts for Cadivor's shared interactive engineering-table system."""
from __future__ import annotations

import unittest
from pathlib import Path


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
        self.assertIn("def selected_dataframe_rows(", COMPONENTS)
        self.assertIn("def cadivor_smart_dataframe(", COMPONENTS)
        self.assertIn('kwargs.setdefault("on_select", "rerun")', COMPONENTS)
        self.assertIn('selection_mode: str = "single-row"', COMPONENTS)
        self.assertIn("def humanize_table_date(", COMPONENTS)
        self.assertIn("def semantic_priority_label(", COMPONENTS)
        for exported_name in (
            "SmartTableResult",
            "cadivor_smart_dataframe",
            "humanize_table_date",
            "semantic_priority_label",
        ):
            self.assertIn(f'"{exported_name}"', PUBLIC_API)

    def test_selected_rows_have_visible_shared_feedback(self):
        self.assertIn(".cv-smart-table-context", CSS)
        self.assertIn('[aria-selected="true"]', CSS)
        self.assertIn("prefers-reduced-motion", CSS)

    def test_monitoring_queue_and_coverage_share_the_contract(self):
        monitoring = RUNTIME.split('if app_mode == "Monitoring":', 1)[1].split(
            'if app_mode == "Supply Risk Scenario":', 1
        )[0]
        self.assertGreaterEqual(monitoring.count("cadivor_smart_dataframe("), 2)
        self.assertIn("queue_table_state = queue_table_result.event", monitoring)
        self.assertIn("selected_rows = _monitor_selected_rows(queue_table_state)", monitoring)
        self.assertIn("component_table_result.first_selected_row", monitoring)
        self.assertIn("semantic_priority_label(score)", monitoring)
        self.assertIn("humanize_table_date(", monitoring)

    def test_saved_bom_components_use_row_selection_not_a_picker(self):
        component_branch = ANALYSIS_DETAIL.split("if parts:", 1)[1]
        self.assertIn("component_table_result = cadivor_smart_dataframe(", component_branch)
        self.assertIn("component_table_result.first_selected_row", component_branch)
        self.assertNotIn('st.selectbox("Select a component to inspect"', component_branch)

    def test_alternative_finder_selection_drives_the_candidate_workspace(self):
        finder = RUNTIME.split('if app_mode == "Alternative Finder":', 1)[1].split(
            'if app_mode == "Compare Parts":', 1
        )[0]
        self.assertIn("candidate_table_result = cadivor_smart_dataframe(", finder)
        self.assertIn("candidate_table_result.first_selected_row", finder)
        self.assertIn("sync_alternative_finder_selected_candidate_result(", finder)
        self.assertNotIn('st.selectbox("Recommended candidate"', finder)

    def test_decisions_and_reports_use_focused_evidence_rows(self):
        decisions = RUNTIME.split('if app_mode == "Engineering Decisions":', 1)[1].split(
            'if app_mode == "Reports":', 1
        )[0]
        reports = RUNTIME.split('if app_mode == "Reports":', 1)[1].split(
            'if app_mode == "Notifications":', 1
        )[0]
        self.assertIn("decision_table_result = cadivor_smart_dataframe(", decisions)
        self.assertIn("driver_table_result = cadivor_smart_dataframe(", decisions)
        self.assertIn("report_table_result = cadivor_smart_dataframe(", reports)
        self.assertIn("selected_report_row = visible.iloc", reports)
        self.assertIn("Run Alternative Finder for", reports)


if __name__ == "__main__":
    unittest.main()
