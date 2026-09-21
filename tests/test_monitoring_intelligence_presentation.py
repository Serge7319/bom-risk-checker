"""Presentation-safe monitoring intelligence contracts."""
from __future__ import annotations

import unittest

import pandas as pd

from src.monitoring_intelligence import build_monitoring_action_center


class MonitoringIntelligencePresentationTests(unittest.TestCase):
    def test_missing_workflow_values_use_human_fallbacks(self):
        alerts = pd.DataFrame(
            [
                {
                    "id": "alert-1",
                    "part_number": "TPS5430DDAR",
                    "analysis_id": "analysis-internal-id",
                    "alert_type": "Lifecycle Change",
                    "alert_message": (
                        "Lifecycle changed from replacement suggested to active"
                    ),
                    "severity": "High",
                    "assigned_to": float("nan"),
                    "due_date": pd.NaT,
                }
            ]
        )

        center = build_monitoring_action_center(alerts, pd.DataFrame())
        record = center["prioritized_alerts"].iloc[0]

        self.assertEqual(record["Owner"], "Component Engineering")
        self.assertEqual(record["Due Date"], "This week")
        self.assertNotEqual(record["Owner"].casefold(), "nan")
        self.assertNotEqual(record["Due Date"].casefold(), "nat")

    def test_monitored_component_data_does_not_expose_analysis_id(self):
        history = pd.DataFrame(
            [
                {
                    "part_number": "TPS5430DDAR",
                    "supplier": "DigiKey",
                    "lifecycle_status": "Active",
                    "stock": 1200,
                    "unit_price": 4.46,
                    "risk_level": "High",
                    "created_at": "2026-09-21T10:31:00+00:00",
                    "analysis_id": "analysis-internal-id",
                }
            ]
        )

        center = build_monitoring_action_center(pd.DataFrame(), history)

        self.assertNotIn("Analysis ID", center["latest_components"].columns)
        self.assertIn("Last Checked", center["latest_components"].columns)


if __name__ == "__main__":
    unittest.main()
