"""Project, BOM, and decision-queue labels stay tied to saved records."""

import unittest
from datetime import date

from src.saved_bom_project import (
    analysis_title_for_upload,
    assign_project,
    resolve_project_choice,
    split_project_and_bom,
)
from src.ui.approved_pages import (
    catalog_health_label,
    catalog_project_options,
    decision_action_label,
    decision_queue_view,
    decision_status_label,
    reset_catalog_filters,
    within_analyzed_range,
)


class ProjectBomSplitTests(unittest.TestCase):
    def test_parent_project_is_not_repeated_as_the_bom_name(self):
        project, bom = split_project_and_bom(
            {"project_name": "Controller — Power Board", "filename": "power.csv"}
        )
        self.assertEqual(project, "Controller")
        self.assertEqual(bom, "Power Board")

    def test_a_single_stored_name_stays_in_the_bom_column(self):
        project, bom = split_project_and_bom(
            {"project_name": "Industrial Controller BOM", "filename": "industrial-controller.csv"}
        )
        self.assertEqual(project, "")
        self.assertEqual(bom, "Industrial Controller BOM")
        self.assertNotEqual(project, bom)

    def test_project_options_come_from_saved_groups(self):
        options = catalog_project_options(
            [
                {"project_name": "Controller — Power Board"},
                {"project_name": "Industrial Controller BOM"},
            ]
        )
        self.assertEqual(options[0], "All projects")
        self.assertIn("Controller", options)
        self.assertNotIn("Not recorded", options)
        self.assertNotIn("Industrial Controller BOM", options)

    def test_blank_upload_uses_general_and_keeps_the_bom_name(self):
        self.assertEqual(resolve_project_choice("Enter a new project", "", blank_uses_general=True), "General")
        title = analysis_title_for_upload("", "Power Board")
        project, bom = split_project_and_bom({"project_name": title, "filename": "power.csv"})
        self.assertEqual(project, "General")
        self.assertEqual(bom, "Power Board")
        self.assertNotEqual(project, bom)

    def test_assigning_and_changing_a_project_persists_when_the_bom_is_reopened(self):
        original = {
            "id": "bom-1",
            "project_name": "Power Board",
            "filename": "power.csv",
            "total_parts": 3,
            "health_score": 42,
        }
        assigned = assign_project(original, "Controller")
        self.assertEqual(original["project_name"], "Power Board")
        self.assertEqual(assigned["filename"], "power.csv")
        self.assertEqual(assigned["total_parts"], 3)
        self.assertEqual(assigned["health_score"], 42)
        reopened_project, reopened_bom = split_project_and_bom(assigned)
        self.assertEqual(reopened_project, "Controller")
        self.assertEqual(reopened_bom, "Power Board")
        changed = assign_project(assigned, "Flight")
        self.assertEqual(split_project_and_bom(changed), ("Flight", "Power Board"))
        self.assertEqual(changed["filename"], original["filename"])
        self.assertEqual(changed["total_parts"], original["total_parts"])
        sibling = analysis_title_for_upload("Flight", "Rev B")
        self.assertEqual(split_project_and_bom({"project_name": sibling})[0], "Flight")


class CatalogFilterTests(unittest.TestCase):
    def test_clear_filters_resets_every_control(self):
        state = {"approved_bom_filter_nonce": 2}
        reset_catalog_filters(state)
        self.assertEqual(state["approved_bom_filter_nonce"], 3)

    def test_health_and_date_filters_use_saved_values(self):
        self.assertEqual(catalog_health_label(42, 2), "At risk")
        today = date(2026, 10, 9)
        self.assertTrue(within_analyzed_range("2026-09-01T12:00:00+00:00", "Last 90 days", today))
        self.assertFalse(within_analyzed_range("2026-09-01T12:00:00+00:00", "Last 30 days", today))
        self.assertFalse(within_analyzed_range("", "Last 90 days", today))
        self.assertTrue(within_analyzed_range("", "All time", today))


class DecisionQueueTests(unittest.TestCase):
    def test_missing_owner_and_due_date_are_not_invented(self):
        today = date(2026, 10, 9)
        row = {
            "mpn": "MAX32625ITK+",
            "severity": "High",
            "status": "Open",
            "alert_message": "Lifecycle moved to NRND.",
            "analysis_id": "fixture-saved-bom-001",
            "created_at": "2026-09-03T12:00:00+00:00",
        }
        self.assertEqual(decision_status_label(row, today), "Open")
        self.assertEqual(decision_action_label(row, "Open"), "Record decision")
        view = decision_queue_view([row], today=today)
        self.assertEqual(view["open"], 1)
        self.assertEqual(view["overdue"], 0)
        self.assertEqual(view["resolved_month"], 0)
        self.assertEqual(view["affected"], 1)

    def test_cards_filter_search_and_sort_use_the_loaded_records(self):
        today = date(2026, 10, 9)
        rows = [
            {"mpn": "AAA", "severity": "Low", "status": "Open", "owner": "Pat", "due_date": "2026-10-01"},
            {"mpn": "ZZZ", "severity": "High", "status": "Resolved", "created_at": "2026-10-02"},
            {"mpn": "MMM", "severity": "Medium", "status": "In review", "analysis_id": "bom-2"},
        ]
        self.assertEqual(decision_status_label(rows[0], today), "Overdue")
        self.assertEqual(decision_action_label(rows[1], "Resolved"), "Review")
        overdue = decision_queue_view(rows, status_filter="Overdue", today=today)
        self.assertEqual([row["mpn"] for row, _status in overdue["rows"]], ["AAA"])
        self.assertEqual(overdue["open"], 0)
        self.assertEqual(overdue["resolved_month"], 1)
        searched = decision_queue_view(rows, query="pat", today=today)
        self.assertEqual([row["mpn"] for row, _status in searched["rows"]], ["AAA"])
        by_risk = decision_queue_view(rows, sort_by="Risk level", today=today)
        self.assertEqual([row["mpn"] for row, _status in by_risk["rows"]], ["ZZZ", "MMM", "AAA"])
        affected = decision_queue_view(rows, scope="boms", today=today)
        self.assertEqual([row["mpn"] for row, _status in affected["rows"]], ["MMM"])


if __name__ == "__main__":
    unittest.main()
