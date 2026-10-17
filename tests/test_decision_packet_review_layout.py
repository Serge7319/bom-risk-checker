"""Contracts for the evidence-first monitoring decision packet."""
from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from src.decision_dashboard import packet_header_html
from src.decision_engine import build_decision_center, monitoring_decision_id


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
NAV_RECOVERY = (
    ROOT / "src" / "assets" / "css" / "navigation_recovery.css"
).read_text(encoding="utf-8")
NAVIGATION = (ROOT / "src" / "ui" / "navigation.py").read_text(encoding="utf-8")


class DecisionPacketHeaderTests(unittest.TestCase):
    def test_header_matches_the_approved_three_step_review_flow(self):
        alert = {
            "alert_type": "Lifecycle Change",
            "alert_message": "Lifecycle changed from Obsolete to Active",
            "previous_value": "Obsolete",
            "current_value": "Active",
        }
        decision = {
            "mpn": "MPU6050",
            "priority": "High",
            "priority_score": 82,
            "status": "New",
            "source": "Monitoring",
        }

        rendered = packet_header_html(
            decision,
            alert=alert,
            saved_bom_label="Not linked",
            saved_bom_linked=False,
        )

        for expected in (
            "Review lifecycle alert",
            "MPU6050",
            "Lifecycle changed",
            "Obsolete",
            "Active",
            "Not linked",
            "HIGH RISK",
            "Review evidence",
            "Choose mitigation",
            "Record outcome",
        ):
            self.assertIn(expected, rendered)
        for removed in ("Review target", "Confidence", "Estimated Effort", "Priority matrix"):
            self.assertNotIn(removed, rendered)

    def test_header_escapes_part_and_supplier_supplied_text(self):
        rendered = packet_header_html(
            {"mpn": "<script>alert(1)</script>", "priority": "High"},
            alert={"alert_type": "Lifecycle", "previous_value": "<bad>"},
        )
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&lt;bad&gt;", rendered)


class DecisionPacketWorkflowTests(unittest.TestCase):
    def test_inventory_verification_survives_decision_center_rebuild(self):
        alert = {
            "part_number": "MPU6050",
            "alert_type": "Lifecycle Change",
            "alert_message": "Lifecycle changed from NRND to EOL",
            "previous_value": "NRND",
            "current_value": "EOL",
            "created_at": "2026-10-17T10:00:00Z",
            "severity": "High",
        }
        inventory = {
            "supplier": "Authorized distributor",
            "quantity": 240,
            "source_reference": "Quote Q-42",
            "verified_by": "Engineer",
            "verified_at": "2026-10-17T14:00:00Z",
        }
        saved_state = {
            monitoring_decision_id(alert): {
                "status": "Engineering Review",
                "owner": "Component Engineering",
                "decision_payload": {"inventory_evidence": inventory},
            }
        }

        center = build_decision_center(
            alert_df=pd.DataFrame([alert]),
            analyses=[],
            saved_state=saved_state,
            part_links=[],
        )

        self.assertEqual(
            center["decisions"][0]["inventory_evidence"],
            inventory,
        )

    def test_packet_uses_home_width_and_keeps_actions_in_the_packet(self):
        packet = RUNTIME.split(
            "if selected_decision and monitoring_component_decision:", 1
        )[1].split("if selected_decision:", 1)[0]
        self.assertIn('key="cadivor_decision_packet_shell"', packet)
        self.assertIn('key=f"decision_packet_evidence_{decision_id}"', packet)
        self.assertIn('key=f"decision_packet_gate_{decision_id}"', packet)
        self.assertIn('"Record verified inventory"', packet)
        self.assertIn('"Record mitigation and close alert"', packet)
        self.assertIn('"Review saved comparison and datasheet evidence"', packet)
        self.assertIn('return_page="Engineering Decisions"', packet)
        self.assertIn("return_decision_id=decision_id", packet)
        self.assertNotIn('"Decision Summary", "Evidence", "Engineering Notes"', packet)
        self.assertNotIn('label="Confidence"', packet)
        self.assertNotIn('label="Estimated Effort"', packet)
        self.assertIn("max-width: 1440px !important", NAV_RECOVERY)
        self.assertIn(".st-key-cadivor_decision_packet_shell", NAV_RECOVERY)

    def test_alternative_finder_returns_to_the_exact_open_decision(self):
        self.assertIn("ALT_FINDER_RETURN_DECISION_ID_KEY", NAVIGATION)
        self.assertIn('"return_decision_id"', NAVIGATION)
        self.assertIn('return_page == "Engineering Decisions"', RUNTIME)
        self.assertIn('key="alternative_back_to_decision_packet"', RUNTIME)


if __name__ == "__main__":
    unittest.main()
