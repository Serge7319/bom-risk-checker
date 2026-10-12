from src.approved_alternatives import (
    approval_candidate_options,
    approved_records_for_bom,
    approved_records_for_part,
    project_decision_context_key,
    report_alternative,
)


import unittest


class ApprovedAlternativesTests(unittest.TestCase):
    def test_project_context_key_survives_analysis_reruns(self):
        self.assertEqual(
            project_decision_context_key("Flight Controller", "analysis-old"),
            project_decision_context_key(" flight   controller ", "analysis-new"),
        )
        self.assertEqual(project_decision_context_key("", "analysis-1"), "analysis-1")

    def test_approved_part_records_are_project_scoped_and_deduplicated(self):
        records = [
            {
                "original_part": "LM358N",
                "alternative_part": "LM358DR2G",
                "decision": "Approved",
                "project_name": "Controller",
                "updated_at": "2026-10-11T10:00:00Z",
            },
            {
                "original_part": "LM358N",
                "alternative_part": "LM358DR2G",
                "decision": "Approved",
                "project_name": "Controller",
                "updated_at": "2026-10-12T10:00:00Z",
                "engineering_note": "Current approval",
            },
            {
                "original_part": "LM358N",
                "alternative_part": "LM358M",
                "decision": "Approved",
                "project_name": "Other project",
            },
            {
                "original_part": "LM358N",
                "alternative_part": "LM358Q",
                "decision": "Pending review",
                "project_name": "Controller",
            },
        ]

        approved = approved_records_for_part(records, "lm358-n", project_name="Controller")

        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["alternative_part"], "LM358DR2G")
        self.assertEqual(approved[0]["engineering_note"], "Current approval")

    def test_bom_approvals_and_report_row_include_the_approved_candidate(self):
        decision = {
            "original_part": "TPS5430DDA",
            "alternative_part": "TPS5430DDAR",
            "decision": "Approved",
            "project_name": "Power Board",
            "engineer_name": "A. Engineer",
            "engineering_note": "Validated package and voltage range",
            "created_at": "2026-10-12T10:00:00Z",
            "source_snapshot": {
                "candidate": {
                    "manufacturer": "Texas Instruments",
                    "description": "Step-down regulator",
                    "image_url": "https://example.com/part.png",
                }
            },
        }

        approved = approved_records_for_bom(
            [decision],
            [{"mpn": "TPS5430DDA"}, {"mpn": "LM358N"}],
            project_name="Power Board",
            analysis_id="analysis-2",
        )
        row = report_alternative(approved[0])

        self.assertEqual(row["decision"], "Approved")
        self.assertEqual(row["alternative_part"], "TPS5430DDAR")
        self.assertEqual(row["manufacturer"], "Texas Instruments")
        self.assertEqual(row["approved_by"], "A. Engineer")
        self.assertIn("Validated package", row["reason"])

    def test_candidate_options_keep_saved_approvals_available_and_deduplicate(self):
        options = approval_candidate_options(
            ["TPS5430DDAR", "LM358DR2G", "tps5430-ddar"],
            [{"alternative_part": "LM358DR2G"}, {"alternative_part": "LM358M"}],
        )
        self.assertEqual(options, ["TPS5430DDAR", "LM358DR2G", "LM358M"])

    def test_approved_candidate_remains_visible_after_bom_analysis_rerun(self):
        project = "Motor Controller"
        decision = {
            "analysis_id": "analysis-before-rerun",
            "context_key": project_decision_context_key(project, "analysis-before-rerun"),
            "original_part": "LM358N",
            "alternative_part": "LM358DR2G",
            "decision": "Approved",
            "project_name": project,
            "engineer_name": "A. Engineer",
        }

        approved = approved_records_for_bom(
            [decision],
            [{"mpn": "LM358N"}],
            project_name=project,
            analysis_id="analysis-after-rerun",
        )

        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["alternative_part"], "LM358DR2G")
