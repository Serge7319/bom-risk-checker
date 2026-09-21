"""Contracts for contextual Engineering Decisions analytics."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


class EngineeringDecisionAnalyticsLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.branch = RUNTIME.split('if app_mode == "Engineering Decisions":', 1)[1]
        cls.branch = cls.branch.split('if app_mode == "Reports":', 1)[0]
        cls.analytics = cls.branch.split("with analytics_tab:", 1)[1]
        cls.analytics = cls.analytics.split("with archive_tab:", 1)[0]

    def test_internal_persistence_scope_copy_is_removed(self):
        self.assertNotIn("Persistent scope:", self.branch)
        self.assertIn('key="refresh_persistent_decisions"', self.branch)

    def test_analytics_replaces_ambiguous_metric_tiles_with_interpretation(self):
        self.assertIn('key="ed_analytics_brief"', self.analytics)
        self.assertIn("Queue interpretation", self.analytics)
        self.assertIn("analytics_critical_share", self.analytics)
        self.assertIn("estimated engineering hours", self.analytics)
        self.assertIn("average open decision has", self.analytics)

        self.assertNotIn("cadivor_metric_row(", self.analytics)
        self.assertNotIn('label="Projected Health Gain"', self.analytics)
        self.assertNotIn('label="Supply Risk Reduction"', self.analytics)
        self.assertNotIn('label="Closed / Rejected"', self.analytics)
        self.assertNotIn('label="Average Open Age"', self.analytics)

    def test_tables_explain_workflow_position_and_queue_drivers(self):
        self.assertIn("Where decisions are in the workflow", self.analytics)
        self.assertIn('"Volume"', self.analytics)
        self.assertIn('"What this means"', self.analytics)
        self.assertIn("What is driving the active queue", self.analytics)
        self.assertIn('"Open"', self.analytics)
        self.assertIn('"Critical"', self.analytics)
        self.assertIn('"Effort (hrs)"', self.analytics)
        self.assertIn('"What it addresses"', self.analytics)
        self.assertIn("driver_meaning", self.analytics)
        self.assertNotIn("Average Priority", self.analytics)

    def test_queue_driver_table_drills_into_open_and_critical_decisions(self):
        self.assertIn('key="ed_analytics_driver_table"', self.analytics)
        self.assertIn("driver_table_result = cadivor_smart_dataframe(", self.analytics)
        self.assertIn("driver_table_result.selected_rows", self.analytics)
        self.assertIn("selected_driver_rows", self.analytics)
        self.assertIn("selected_driver_critical", self.analytics)
        self.assertIn('key="ed_queue_driver_drilldown"', self.analytics)
        self.assertIn("All open (", self.analytics)
        self.assertIn("Critical (", self.analytics)
        self.assertIn("st.pills(", self.analytics)

    def test_drilldown_records_have_direct_review_actions(self):
        self.assertIn("visible_driver_decisions", self.analytics)
        self.assertIn('"Review decision"', self.analytics)
        self.assertIn('key=f"ed_driver_review_{decision_id}"', self.analytics)
        self.assertIn('"Engineering Decisions",', self.analytics)
        self.assertIn("decision_id=decision_id", self.analytics)


if __name__ == "__main__":
    unittest.main()
