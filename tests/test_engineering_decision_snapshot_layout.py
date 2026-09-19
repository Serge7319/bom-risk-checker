"""Contracts for the actionable Engineering Decisions snapshot."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


class EngineeringDecisionSnapshotLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.branch = RUNTIME.split('if app_mode == "Engineering Decisions":', 1)[1]
        cls.branch = cls.branch.split('if app_mode == "Reports":', 1)[0]
        cls.snapshot = cls.branch.split("with decision_metrics_col:", 1)[1]

    def test_snapshot_uses_home_style_action_cards(self):
        for key in (
            "ed_decision_snapshot",
            "ed_snapshot_pending",
            "ed_snapshot_critical",
            "ed_snapshot_rejected",
            "ed_snapshot_approved",
        ):
            self.assertIn(f'key="{key}"', self.snapshot)

        for action, focus in (
            ("Review pending decisions", "pending"),
            ("Review critical decisions", "critical"),
            ("View rejected decisions", "rejected"),
            ("View approved decisions", "approved"),
        ):
            self.assertIn(action, self.snapshot)
            self.assertIn(f'decision_focus=focus', self.snapshot)

        self.assertIn("cv-ed-kpi-preview", self.snapshot)
        self.assertIn("cv-ed-kpi-line--primary", self.snapshot)
        self.assertIn("cadivor-ed-snapshot-card-css", self.snapshot)

    def test_snapshot_does_not_render_passive_rollups(self):
        self.assertNotIn('label="Engineering Hours"', self.snapshot)
        self.assertNotIn('label="Average Age"', self.snapshot)
        self.assertNotIn('context_class="decision-snapshot"', self.snapshot)

    def test_focus_actions_have_filter_defaults(self):
        queue = self.branch.split("with queue_tab:", 1)[1]
        for focus in ("pending", "critical", "rejected", "approved"):
            self.assertIn(f'"{focus}"', queue)
        self.assertIn("decision_priority_filter_", queue)
        self.assertIn("decision_status_filter_", queue)
        self.assertIn('decision["status"] not in ("Closed", "Rejected")', queue)


if __name__ == "__main__":
    unittest.main()
