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
        self.assertIn('"Queue"', self.analytics)
        self.assertIn('"Effort"', self.analytics)
        self.assertIn('"What it addresses"', self.analytics)
        self.assertIn("driver_meaning", self.analytics)
        self.assertNotIn("Average Priority", self.analytics)


if __name__ == "__main__":
    unittest.main()
