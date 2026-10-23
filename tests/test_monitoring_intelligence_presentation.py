"""Presentation-safe monitoring intelligence contracts."""
from __future__ import annotations

import unittest

import pandas as pd

from src.monitoring_intelligence import (
    build_monitoring_action_center,
    monitoring_overview_alert_rows,
    monitoring_workflow_urgency,
)


class MonitoringIntelligencePresentationTests(unittest.TestCase):
    def test_workflow_urgency_cannot_understate_the_evidence_score(self):
        self.assertEqual(monitoring_workflow_urgency(95, "Normal"), "Urgent")
        self.assertEqual(monitoring_workflow_urgency(80, "Low"), "High")
        self.assertEqual(monitoring_workflow_urgency(55, ""), "Normal")
        self.assertEqual(monitoring_workflow_urgency(20, "Urgent"), "Urgent")

    def test_action_center_aligns_critical_score_and_workflow_urgency(self):
        alerts = pd.DataFrame(
            [
                {
                    "id": "alert-critical",
                    "part_number": "TPS5430DDAR",
                    "alert_type": "Stock Drop",
                    "alert_message": "Stock dropped from 13918 to 0",
                    "severity": "High",
                    "current_value": 0,
                    "priority": "Normal",
                }
            ]
        )

        record = build_monitoring_action_center(
            alerts,
            pd.DataFrame(),
        )["prioritized_alerts"].iloc[0]

        self.assertEqual(record["Priority Score"], 95)
        self.assertEqual(record["Priority"], "Urgent")

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

    def test_alert_overview_uses_active_rows_and_keeps_supplier_context(self):
        alerts = pd.DataFrame(
            [
                {
                    "id": "alert-open",
                    "part_number": "SN74LVC2T45DCUR",
                    "manufacturer": "Texas Instruments",
                    "alert_type": "Lifecycle Change",
                    "alert_message": "Lifecycle changed to NRND",
                    "severity": "High",
                    "created_at": "2026-10-22T09:14:00Z",
                    "workflow_status": "Open",
                },
                {
                    "id": "alert-resolved",
                    "part_number": "TPS5430DDAR",
                    "manufacturer": "Texas Instruments",
                    "alert_type": "Inventory Update",
                    "alert_message": "Inventory increased",
                    "severity": "Low",
                    "created_at": "2026-10-22T08:00:00Z",
                    "workflow_status": "Resolved",
                },
            ]
        )
        center = build_monitoring_action_center(alerts, pd.DataFrame())

        rows = monitoring_overview_alert_rows(alerts, center["active_queue"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mpn"], "SN74LVC2T45DCUR")
        self.assertEqual(rows[0]["manufacturer"], "Texas Instruments")
        self.assertEqual(rows[0]["alert_type"], "Lifecycle Change")
        self.assertEqual(rows[0]["workflow_status"], "Open")


if __name__ == "__main__":
    unittest.main()
