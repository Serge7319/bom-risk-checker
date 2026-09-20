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
