import unittest
from pathlib import Path

from src.bom_upload_flow import (
    consume_approved_bom_submission,
    resume_approved_bom_submission,
    should_render_bom_analysis_body,
    should_stop_approved_bom_renderer,
)


class ApprovedBOMPageContractTests(unittest.TestCase):
    def test_bom_analyzer_renders_component_register_and_guards_context_exit(self):
        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("render_bom_component_table(filtered_df)", source)
        self.assertIn("if _bom_new_analysis_context is not None:", source)
        self.assertIn("should_render_bom_analysis_body(", source)

    def test_project_name_is_an_always_editable_text_field(self):
        source = Path("src/ui/approved_pages.py").read_text(encoding="utf-8")
        start = source.index('with st.container(key="approved_bom_upload_panel")')
        end = source.index('    else:\n        from datetime import date', start)
        upload_form = source[start:end]

        self.assertIn('typed_project = st.text_input(', upload_form)
        self.assertIn('"Project name"', upload_form)
        self.assertNotIn('selected_project = st.selectbox(', upload_form)
        self.assertIn('resolve_project_choice(', upload_form)


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

    def test_upload_form_allows_runtime_to_resume_active_pipeline(self):
        active = {"cadivor_bom_pipeline_active": True}

        self.assertFalse(
            should_stop_approved_bom_renderer(active, upload_mode=True)
        )
        self.assertTrue(
            should_stop_approved_bom_renderer({}, upload_mode=True)
        )
        self.assertTrue(
            should_stop_approved_bom_renderer(active, upload_mode=False)
        )


    def test_analysis_body_renders_on_bom_analyzer_without_review_flag(self):
        self.assertTrue(should_render_bom_analysis_body("BOM Analyzer"))
        self.assertFalse(should_render_bom_analysis_body("Monitoring"))

    def test_analysis_body_renders_when_high_risk_review_is_active(self):
        self.assertTrue(
            should_render_bom_analysis_body("High Risk Review", high_risk_review=True)
        )

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
