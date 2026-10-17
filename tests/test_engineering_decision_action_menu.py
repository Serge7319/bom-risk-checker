"""Visual and action contracts for the Engineering Decisions queue."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVED = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
CORE_UI = (ROOT / "src" / "ui" / "core_premium_ui.py").read_text(encoding="utf-8")
NAV_RECOVERY = (ROOT / "src" / "assets" / "css" / "navigation_recovery.css").read_text(encoding="utf-8")


class EngineeringDecisionQueueActionTests(unittest.TestCase):
    def test_rows_keep_review_and_offer_contextual_overflow_actions(self):
        queue = APPROVED.split("def render_decision_queue", 1)[1]
        queue = queue.split("\ndef _alert_slots", 1)[0]

        self.assertIn('st.popover(\n                                "⋯"', queue)
        for label in (
            '"Open original BOM"',
            '"BOM Risk"',
            '"Detailed Risk Report"',
            '"Find replacement"',
        ):
            self.assertIn(label, queue)
        self.assertIn("navigate_to_alternative_finder(", queue)
        self.assertIn('saved_bom_action="open"', queue)

    def test_record_decision_opens_the_exact_engineering_decision_packet(self):
        queue = APPROVED.split("def render_decision_queue", 1)[1]
        primary_action = queue.split("if st.button(\n                            action,", 1)[1]
        primary_action = primary_action.split("with overflow_col:", 1)[0]

        self.assertIn('navigate_to(\n', primary_action)
        self.assertIn('"Engineering Decisions"', primary_action)
        self.assertIn("decision_id=decision_id", primary_action)
        self.assertIn("monitoring_decision_id(row)", primary_action)
        self.assertNotIn('navigate_to(\n                                        "Analysis Details"', primary_action)

    def test_clickable_kpi_target_cannot_cover_card_content(self):
        card = CORE_UI.split(
            '[class*="st-key-approved_decision_cardwrap_"] .cv-ed-card {{',
            1,
        )[1].split("}}", 1)[0]
        click_target = CORE_UI.split(
            '[data-testid="stElementContainer"]:has([class*="st-key-approved_decision_drill_"]) {{',
            1,
        )[1].split("}}", 1)[0]

        self.assertIn("z-index:3", card)
        self.assertIn("pointer-events:none", card)
        self.assertIn("z-index:1", click_target)

    def test_navigation_icons_and_decision_packet_keep_distinct_workspace_geometry(self):
        self.assertIn("padding-left: 54px !important", NAV_RECOVERY)
        self.assertIn("left: 12px !important", NAV_RECOVERY)
        self.assertIn("max-width: 1440px !important", NAV_RECOVERY)
        self.assertIn("cv-decision-table-heading.owner", NAV_RECOVERY)
        self.assertIn("cv-decision-table-heading.due-date", NAV_RECOVERY)
        self.assertIn("cv-decision-table-heading.actions", NAV_RECOVERY)


if __name__ == "__main__":
    unittest.main()
