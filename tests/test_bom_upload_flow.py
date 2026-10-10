import unittest

from src.bom_upload_flow import (
    consume_approved_bom_submission,
    resume_approved_bom_submission,
)


class ApprovedBOMSubmissionTests(unittest.TestCase):
    def test_approved_upload_hands_off_file_names_and_starts_analysis(self):
        upload = object()
        state = {
            "cadivor_bom_analysis_ready": True,
            "cadivor_pending_upload": upload,
            "cadivor_pending_project": "New project",
            "cadivor_pending_bom_name": "Prototype BOM",
            "bom8_project_name": "Old project",
            "bom8_bom_name": "Old BOM",
            "bom8_sample_mode": True,
        }
        submitted, consumed_upload, project, name = consume_approved_bom_submission(state)
        self.assertTrue(submitted)
        self.assertIs(consumed_upload, upload)
        self.assertEqual((project, name), ("New project", "Prototype BOM"))
        self.assertEqual(state["bom8_project_name"], "New project")
        self.assertEqual(state["bom8_bom_name"], "Prototype BOM")
        self.assertTrue(state["bom8_analysis_pending"])
        self.assertTrue(state["cadivor_bom_pipeline_active"])
        self.assertIs(state["bom8_analysis_upload_file"], upload)
        resumed_upload, resumed_project, resumed_name = resume_approved_bom_submission(state)
        self.assertIs(resumed_upload, upload)
        self.assertEqual((resumed_project, resumed_name), ("New project", "Prototype BOM"))
        self.assertNotIn("bom8_sample_mode", state)
        self.assertNotIn("cadivor_pending_upload", state)
        self.assertNotIn("cadivor_bom_analysis_ready", state)

    def test_approved_upload_replaces_stale_names_even_when_fields_are_blank(self):
        state = {
            "cadivor_bom_analysis_ready": True,
            "cadivor_pending_upload": object(),
            "cadivor_pending_project": "",
            "cadivor_pending_bom_name": "",
            "bom8_project_name": "Old project",
            "bom8_bom_name": "Old BOM",
        }
        consume_approved_bom_submission(state)
        self.assertEqual(state["bom8_project_name"], "")
        self.assertEqual(state["bom8_bom_name"], "")

    def test_upload_resumes_after_pending_flag_is_consumed(self):
        upload = object()
        state = {
            "cadivor_bom_analysis_ready": True,
            "cadivor_pending_upload": upload,
            "cadivor_pending_project": "Motor project",
            "cadivor_pending_bom_name": "Rev B",
        }
        consume_approved_bom_submission(state)
        state.pop("bom8_analysis_pending", None)

        resumed_upload, project, name = resume_approved_bom_submission(state)

        self.assertIs(resumed_upload, upload)
        self.assertEqual((project, name), ("Motor project", "Rev B"))

    def test_missing_upload_does_not_queue_analysis(self):
        state = {
            "cadivor_bom_analysis_ready": True,
            "cadivor_pending_upload": None,
            "cadivor_pending_project": "New project",
            "cadivor_pending_bom_name": "Prototype BOM",
        }
        submitted, upload, _, _ = consume_approved_bom_submission(state)
        self.assertTrue(submitted)
        self.assertIsNone(upload)
        self.assertNotIn("bom8_analysis_pending", state)


if __name__ == "__main__":
    unittest.main()
