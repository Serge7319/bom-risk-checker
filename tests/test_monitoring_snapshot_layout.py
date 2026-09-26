"""Contracts for the actionable Alerts & Monitoring two-column workspace."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


class MonitoringSnapshotLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.branch = RUNTIME.split('if app_mode == "Monitoring":', 1)[1]
        cls.branch = cls.branch.split('if app_mode == "Supply Risk Scenario":', 1)[0]

    def test_page_uses_two_column_action_workspace(self):
        self.assertIn("monitoring_workspace_col, monitoring_snapshot_col", self.branch)
        self.assertIn("[0.66, 0.34]", self.branch)
        self.assertIn('key="monitoring_snapshot"', self.branch)
        self.assertIn("Monitoring snapshot", self.branch)
        self.assertIn("Monitoring workspace", self.branch)

    def test_snapshot_keeps_only_distinct_actionable_metrics(self):
        for card_key in (
            "monitor_snapshot_immediate",
            "monitor_snapshot_lifecycle",
            "monitor_snapshot_inventory",
            "monitor_snapshot_pricing",
            "monitor_snapshot_components",
        ):
            self.assertIn(f'card_key="{card_key}"', self.branch)

        self.assertNotIn('MetricCard(label="Stock"', self.branch)
        self.assertNotIn('MetricCard(label="Monitored"', self.branch)
        self.assertNotIn("render_kpi_row_safe(", self.branch)
        self.assertIn("if price_alerts > 0:", self.branch)
        self.assertIn("and monitor_usage >= 80", self.branch)

    def test_snapshot_previews_name_the_actual_affected_components(self):
        self.assertIn("def _monitor_preview_parts(focus: str)", self.branch)
        self.assertIn('preview_label="Affected components"', self.branch)
        self.assertIn('_monitor_preview_parts("immediate")', self.branch)
        self.assertIn('_monitor_preview_parts("lifecycle")', self.branch)
        self.assertIn('_monitor_preview_parts("inventory")', self.branch)
        self.assertNotIn("cv-monitor-kpi-line cv-monitor-kpi-line--primary", self.branch)

    def test_snapshot_makes_the_selected_shortcut_unmistakable(self):
        self.assertIn("is_active: bool = False", self.branch)
        self.assertIn('cv-monitor-kpi-copy{active_class}', self.branch)
        self.assertIn("Current view", self.branch)
        self.assertIn('"Currently showing" if is_active else action_label', self.branch)
        self.assertIn("disabled=is_active", self.branch)
        self.assertIn('active_snapshot_focus == "immediate"', self.branch)
        self.assertIn('active_snapshot_focus == "components"', self.branch)

    def test_every_snapshot_card_has_a_destination(self):
        for action_label in (
            "Review immediate actions",
            "Review lifecycle changes",
            "Review inventory alerts",
            "Review price changes",
            "View monitored components",
        ):
            self.assertIn(action_label, self.branch)

        self.assertIn('navigate_to(\n                        "Monitoring"', self.branch)
        self.assertIn('navigation_params = {"monitor_view": target_view}', self.branch)
        for focus in ("immediate", "lifecycle", "inventory", "pricing"):
            self.assertIn(f'focus="{focus}"', self.branch)

    def test_shortcuts_apply_matching_queue_filters(self):
        self.assertIn('"immediate": ("Immediate action", "Active", "All")', self.branch)
        self.assertIn('"lifecycle": ("All", "Active", "Lifecycle")', self.branch)
        self.assertIn('"inventory": ("All", "Active", "Inventory")', self.branch)
        self.assertIn('"pricing": ("All", "Active", "Price")', self.branch)
        self.assertIn('filtered = filtered[priority_scores >= 75]', self.branch)
        self.assertIn('key=f"m32_attention_{monitor_filter_key}"', self.branch)
        self.assertIn('key=f"m32_type_{monitor_filter_key}"', self.branch)

    def test_action_queue_expands_one_record_inside_the_table(self):
        self.assertIn("queue_table_result = cadivor_expandable_table(", self.branch)
        self.assertIn('f"m32_queue_table_{monitor_filter_key}_"', self.branch)
        self.assertIn("ExpandableTableColumn(", self.branch)
        self.assertIn("queue_table_result.first_selected_row", self.branch)
        self.assertIn("queue_table_result.detail_slot.container()", self.branch)
        self.assertIn('key=f"monitor_alert_detail_{detail_key}"', self.branch)
        self.assertIn("Click a row to expand its evidence", self.branch)
        self.assertNotIn("queue_table_result.event", self.branch)
        self.assertNotIn("for idx, row in filtered.head(50).iterrows()", self.branch)

    def test_queue_explains_the_active_view_and_priority_meaning(self):
        self.assertIn("monitor_focus_labels", self.branch)
        self.assertIn("All rows below match this view", self.branch)
        self.assertIn("def _monitor_priority_label(score)", self.branch)
        for priority_label in ("Critical", "Immediate", "Review", "Monitor"):
            self.assertIn(priority_label, self.branch)
        self.assertNotIn("st.column_config.ProgressColumn", self.branch)

    def test_monitored_components_hide_internal_ids_and_format_dates(self):
        component_view = self.branch.split(
            "def _render_monitored_components", 1
        )[1].split("def _render_monitoring_timeline", 1)[0]
        self.assertNotIn('"Analysis ID"', component_view)
        self.assertIn('columns={"Last Checked": "Last checked (UTC)"}', component_view)
        self.assertIn("include_time=True", component_view)
        self.assertIn("Search by component, supplier, lifecycle status, or risk", component_view)

    def test_selected_alert_keeps_workflow_and_contextual_actions(self):
        for label in (
            "Save workflow",
            "Run Alternative Finder",
            "Open decisions",
            "Export evidence",
        ):
            self.assertIn(label, self.branch)
        self.assertIn("mpn=part_number", self.branch)
        self.assertIn('source_page="monitoring"', self.branch)

    def test_monitoring_views_are_directly_addressable(self):
        for token, label in (
            ("queue", "Action Queue"),
            ("components", "Monitored Components"),
            ("timeline", "Timeline"),
            ("export", "Export"),
        ):
            self.assertIn(f'"{token}": "{label}"', self.branch)
        self.assertIn('_qp_value("monitor_view", "queue")', self.branch)
        self.assertIn('target_view="components"', self.branch)


if __name__ == "__main__":
    unittest.main()
