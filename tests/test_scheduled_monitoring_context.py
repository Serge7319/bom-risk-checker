"""Regression tests for the scheduled component monitoring refresh."""
from __future__ import annotations

import unittest

from src.monitoring_engine import (
    build_updated_monitor_snapshot,
    detect_monitored_part_changes,
)


class ScheduledMonitoringContextTests(unittest.TestCase):
    def test_refresh_carries_saved_bom_scope_forward(self) -> None:
        previous = {
            "analysis_id": "analysis-123",
            "workspace_id": "workspace-456",
            "risk_level": "High",
            "stock": 100,
            "unit_price": 2.0,
            "lifecycle_status": "Active",
        }

        current = build_updated_monitor_snapshot(
            "user-789",
            "ABC123",
            previous,
            {
                "source": "Example Distributor",
                "lifecycle_status": "Active",
                "stock_total": 25,
                "unit_price": 2.0,
            },
        )

        self.assertEqual(current["analysis_id"], "analysis-123")
        self.assertEqual(current["workspace_id"], "workspace-456")
        self.assertEqual(current["part_number"], "ABC123")
        self.assertEqual(current["stock"], 25)

    def test_detected_alert_uses_the_detector_signature_and_saved_scope(self) -> None:
        previous = {
            "analysis_id": "analysis-123",
            "workspace_id": "workspace-456",
            "stock": 100,
            "unit_price": 2.0,
            "lifecycle_status": "Active",
        }
        current = build_updated_monitor_snapshot(
            "user-789",
            "ABC123",
            previous,
            {
                "source": "Example Distributor",
                "lifecycle_status": "Active",
                "stock_total": 25,
                "unit_price": 2.0,
            },
        )

        alerts, messages = detect_monitored_part_changes(
            "user-789", "ABC123", previous, current
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["analysis_id"], "analysis-123")
        self.assertEqual(alerts[0]["workspace_id"], "workspace-456")
        self.assertEqual(alerts[0]["part_number"], "ABC123")
        self.assertIn("Stock dropped", messages[0])


if __name__ == "__main__":
    unittest.main()
