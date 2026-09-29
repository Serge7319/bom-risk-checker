"""BOM release progress must follow saved part decisions, not inferred risk alone."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.bom_review_progress import (
    bom_review_progress_cache_key,
    bom_review_parts_html,
    bom_review_progress_html,
    load_bom_review_progress,
    select_bom_review_parts,
    summarize_bom_review_progress,
)


class BomReviewProgressTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {"id": "bom-1", "high_risk_count": 2, "medium_risk_count": 1}
        self.parts = [
            {"analysis_id": "bom-1", "mpn": "A", "risk_level": "High"},
            {"analysis_id": "bom-1", "mpn": "B", "risk_level": "High"},
            {"analysis_id": "bom-1", "mpn": "C", "risk_level": "Medium"},
            {"analysis_id": "bom-1", "mpn": "D", "risk_level": "Low"},
        ]

    def test_progress_cache_is_scoped_to_account_and_workspace(self):
        self.assertNotEqual(
            bom_review_progress_cache_key("u-1", "ws-1"),
            bom_review_progress_cache_key("u-1", "ws-2"),
        )
        self.assertNotEqual(
            bom_review_progress_cache_key("u-1", "ws-1"),
            bom_review_progress_cache_key("u-2", "ws-1"),
        )

    def test_saved_dispositions_show_recording_and_remaining_release_work_separately(self):
        result = summarize_bom_review_progress(self.analysis, self.parts, [
            {"analysis_id": "bom-1", "mpn": "a", "decision": "Approve"},
            {"analysis_id": "bom-1", "mpn": "B", "decision": "Needs Investigation"},
            {"analysis_id": "bom-1", "mpn": "C", "decision": "Reject"},
            {"analysis_id": "other-bom", "mpn": "D", "decision": "Approve"},
        ])
        self.assertEqual((result["recorded"], result["approved"], result["needs_action"]), (3, 1, 2))
        self.assertEqual(result["total"], 3)
        self.assertTrue(result["evidence_complete"])
        markup = bom_review_progress_html(result, bom_status="New")
        self.assertIn("3 of 3 recorded", markup)
        self.assertIn("2 affected parts still need", markup)
        self.assertIn("Part approvals document review; they do not grant BOM release approval.", markup)

    def test_no_session_or_missing_risk_lines_never_looks_complete(self):
        result = summarize_bom_review_progress(self.analysis, self.parts[:2], [])
        self.assertEqual(result["unreviewed"], 2)
        self.assertEqual(result["missing_lines"], 1)
        self.assertFalse(result["evidence_complete"])
        self.assertIn("could not be matched", bom_review_progress_html(result, bom_status="New"))

    def test_duplicate_mpn_represents_one_review_decision_with_two_bom_lines(self):
        duplicate = [
            {"mpn": "a", "risk_level": "High"},
            {"mpn": "A", "risk_level": "Medium"},
        ]
        result = summarize_bom_review_progress(
            {"id": "bom-1", "high_risk_count": 1, "medium_risk_count": 1},
            duplicate,
            [{"analysis_id": "bom-1", "mpn": "A", "decision": "Approve"}],
        )
        self.assertEqual((result["total"], result["risk_lines"], result["approved"]), (1, 2, 1))
        self.assertIn("2 BOM lines", bom_review_parts_html(result["parts"]))
        self.assertIn("separate whole-BOM release decision", bom_review_progress_html(result, bom_status="New"))

    def test_skipped_part_and_premature_bom_approval_surface_conflict(self):
        result = summarize_bom_review_progress(self.analysis, self.parts, [
            {"analysis_id": "bom-1", "mpn": "A", "decision": "Skip"},
            {"analysis_id": "bom-1", "mpn": "B", "decision": "Approve"},
        ])
        self.assertEqual(result["unreviewed"], 2)
        self.assertIn("skipped, still needing review", bom_review_progress_html(result, bom_status="New"))
        self.assertIn("marked approved while affected parts still need action", bom_review_progress_html(result, bom_status="Production Approved"))

    def test_truncation_and_mismatched_counts_cannot_claim_verification(self):
        decisions = [{"analysis_id": "bom-1", "mpn": mpn, "decision": "Approve"} for mpn in ("A", "B", "C")]
        result = summarize_bom_review_progress(self.analysis, self.parts, decisions, truncated=True)
        self.assertFalse(result["evidence_complete"])
        self.assertIn("too large to verify", bom_review_progress_html(result, bom_status="New"))
        result = summarize_bom_review_progress({"id": "bom-1", "high_risk_count": 1}, self.parts, decisions)
        self.assertFalse(result["evidence_complete"])
        self.assertIn("do not match", bom_review_progress_html(result, bom_status="New"))

    def test_review_queue_keeps_existing_top_five_and_adds_remaining_risk_parts(self):
        ranked = [
            {"mpn": f"LOW-{idx}", "stored_risk_level": "Low"} for idx in range(5)
        ] + [
            {"mpn": "HIGH-6", "stored_risk_level": "High"},
            {"mpn": "MED-7", "stored_risk_level": "Medium"},
            {"mpn": "low-8", "stored_risk_level": "Low"},
            {"mpn": "high-6", "stored_risk_level": "High"},
        ]
        self.assertEqual([part["mpn"] for part in select_bom_review_parts(ranked)],
                         [*(f"LOW-{idx}" for idx in range(5)), "HIGH-6", "MED-7"])

    def test_part_names_and_owner_text_are_escaped(self):
        result = summarize_bom_review_progress(
            {"id": "bom-1", "high_risk_count": 1},
            [{"mpn": '<img src=x onerror=alert(1)>', "risk_level": "High"}],
            [{"analysis_id": "bom-1", "mpn": '<img src=x onerror=alert(1)>',
              "decision": "Needs Investigation", "assignee_name": "<script>"}],
        )
        markup = bom_review_parts_html(result["parts"])
        self.assertNotIn("<img", markup)
        self.assertNotIn("<script>", markup)
        self.assertIn("&lt;img", markup)

    def test_loader_only_uses_parts_and_decisions_from_authorized_bom(self):
        rows = [
            {"analysis_id": "bom-1", "workspace_id": "ws-1", "user_id": "u-1", "mpn": "A", "risk_level": "High"},
            {"analysis_id": "bom-1", "workspace_id": "ws-2", "user_id": "u-1", "mpn": "OTHER-WS", "risk_level": "High"},
            {"analysis_id": "bom-1", "workspace_id": "ws-1", "user_id": "u-2", "mpn": "OTHER-USER", "risk_level": "High"},
        ]

        class Query:
            def __init__(self):
                self.conditions = {}
                self.row_limit = len(rows)

            def select(self, _columns):
                return self

            def eq(self, key, value):
                self.conditions[key] = value
                return self

            def limit(self, limit):
                self.row_limit = limit
                return self

            def execute(self):
                matched = [r for r in rows if all(r.get(k) == v for k, v in self.conditions.items())]
                return SimpleNamespace(data=matched[:self.row_limit])

        class FakeClient:
            def table(self, name):
                self.assert_table(name)
                return Query()

            @staticmethod
            def assert_table(name):
                if name != "analysis_parts":
                    raise AssertionError(f"Unexpected table: {name}")

        with patch("src.bom_review_progress.get_latest_review_session", return_value=({"id": "s-1"}, None)), \
             patch("src.bom_review_progress.list_review_items", return_value=([{
                 "analysis_id": "bom-1", "mpn": "A", "decision": "Approve",
             }], None)):
            result, error = load_bom_review_progress(
                FakeClient(),
                analysis={"id": "bom-1", "high_risk_count": 1},
                user_id="u-1", workspace_id="ws-1",
            )
        self.assertIsNone(error)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["approved"], 1)


if __name__ == "__main__":
    unittest.main()
