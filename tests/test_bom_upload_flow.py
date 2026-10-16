import json
import unittest
from pathlib import Path

from src.saved_bom_cost import analysis_part_cost_fields, json_safe_value
from src.bom_upload_flow import (
    consume_approved_bom_submission,
    finish_approved_bom_submission,
    resume_approved_bom_submission,
    should_render_approved_bom_upload_form,
    should_render_legacy_bom_workspace,
    should_render_bom_analysis_body,
    should_stop_approved_bom_renderer,
    prepare_new_approved_bom_analysis,
    has_completed_saved_bom_results,
)


class ApprovedBOMPageContractTests(unittest.TestCase):
    def test_bom_analyzer_renders_component_register_and_guards_context_exit(self):
        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("render_bom_component_table(filtered_df)", source)
        self.assertIn("if _bom_new_analysis_context is not None:", source)
        self.assertIn("should_render_bom_analysis_body(", source)

    def test_home_new_analysis_clears_old_context_before_navigation(self):
        source = Path("src/ui/approved_pages.py").read_text(encoding="utf-8")
        action_start = source.index('key="approved_home_new_bom"')
        home_action = source[action_start : action_start + 600]
        self.assertIn("prepare_new_approved_bom_analysis(st.session_state)", home_action)
        self.assertIn('navigate_to("BOM Analyzer", new_analysis="1")', home_action)
        workspace_source = Path("src/pages/home_workspace.py").read_text(encoding="utf-8")
        workspace_action = workspace_source[workspace_source.index('key="home_new_bom"') :]
        self.assertIn("prepare_new_approved_bom_analysis(st.session_state)", workspace_action)
        self.assertIn('navigate_to("BOM Analyzer", new_analysis="1", arm_opening=False)', workspace_action)

    def test_completed_saved_results_render_without_reopening_the_upload(self):
        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("has_completed_saved_bom_results(st.session_state)", source)
        self.assertIn("and not _has_completed_saved_results", source)
        self.assertIn("if _has_completed_saved_results and uploaded_file is None:", source)
        self.assertIn("cadivor_bom_catalog_requested", source)

    def test_bom_analyzer_menu_returns_to_the_saved_catalog(self):
        page_source = Path("src/ui/approved_pages.py").read_text(encoding="utf-8")
        runtime_source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("catalog_requested = bool(", page_source)
        self.assertIn("not catalog_requested", page_source)
        self.assertIn("st.session_state.get(\"cadivor_bom_catalog_requested\")", runtime_source)
        self.assertIn("# The BOM Analyzer menu should show the saved-BOM catalog", runtime_source)

    def test_project_name_is_an_always_editable_text_field(self):
        source = Path("src/ui/approved_pages.py").read_text(encoding="utf-8")
        start = source.index('with st.container(key="approved_bom_upload_panel")')
        end = source.index('    else:\n        from datetime import date', start)
        upload_form = source[start:end]

        self.assertIn('typed_project = st.text_input(', upload_form)
        self.assertIn('"Project name"', upload_form)
        self.assertNotIn('selected_project = st.selectbox(', upload_form)
        self.assertIn('resolve_project_choice(', upload_form)

    def test_one_time_checkout_discloses_unassessed_components(self):
        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        start = source.index('if not one_time_credit_available(_one_time_user_id):')
        end = source.index('high_count = len(results_df[results_df["Risk Level"] == "High"])', start)
        checkout = source[start:end]

        self.assertIn("could not be risk-rated", checkout)
        self.assertIn("does not add missing supplier coverage.", checkout)
        self.assertIn("st.checkbox(", checkout)
        self.assertIn("if _one_time_evidence_acknowledged:", checkout)


    def test_completed_saved_results_are_reusable_without_the_upload_file(self):
        saved_results = type("Results", (), {"empty": False})()
        self.assertTrue(
            has_completed_saved_bom_results(
                {
                    "results_df": saved_results,
                    "analysis_saved": True,
                    "analysis_id": "saved-analysis",
                }
            )
        )
        self.assertFalse(
            has_completed_saved_bom_results(
                {
                    "results_df": saved_results,
                    "analysis_saved": False,
                    "analysis_id": "preview-only",
                }
            )
        )
        self.assertFalse(
            has_completed_saved_bom_results(
                {"results_df": saved_results, "analysis_saved": True}
            )
        )

    def test_explicit_new_analysis_clears_saved_catalog_context(self):
        state = {
            "results_df": object(),
            "analysis_saved": True,
            "analysis_id": "old-analysis",
            "cadivor_active_analysis_id": "old-analysis",
            "cadivor_bom_catalog_requested": True,
            "cadivor_show_saved_boms": True,
        }
        prepare_new_approved_bom_analysis(state)
        self.assertTrue(state["cadivor_bom_upload_open"])
        self.assertNotIn("analysis_id", state)
        self.assertNotIn("cadivor_active_analysis_id", state)
        self.assertNotIn("results_df", state)
        self.assertNotIn("cadivor_bom_catalog_requested", state)
        self.assertNotIn("cadivor_show_saved_boms", state)


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

    def test_new_upload_clears_previous_report_before_the_progress_transition(self):
        state = {
            "cadivor_bom_analysis_ready": True,
            "cadivor_pending_upload": object(),
            "cadivor_pending_project": "New project",
            "cadivor_pending_bom_name": "New BOM",
            "results_df": "stale report",
            "analysis_saved": True,
            "analysis_id": "old-analysis",
            "health_score": 12,
            "cadivor_active_analysis_id": "old-analysis",
        }

        consume_approved_bom_submission(state)

        self.assertNotIn("results_df", state)
        self.assertNotIn("analysis_saved", state)
        self.assertNotIn("analysis_id", state)
        self.assertNotIn("cadivor_active_analysis_id", state)
        self.assertTrue(state["cadivor_bom_pipeline_active"])

    def test_interrupted_pipeline_can_reopen_upload_form(self):
        state = {
            "cadivor_bom_pipeline_active": True,
            "bom8_analysis_upload_file": object(),
            "bom8_analysis_pending": True,
            "bom8_analysis_in_progress": True,
        }
        finish_approved_bom_submission(state, reopen_upload=True)
        self.assertTrue(state["cadivor_bom_upload_open"])
        self.assertFalse(state.get("cadivor_bom_pipeline_active", False))
        self.assertNotIn("bom8_analysis_upload_file", state)
        self.assertNotIn("bom8_analysis_pending", state)

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

    def test_upload_form_hides_during_the_runtime_progress_view(self):
        source = Path("src/ui/approved_pages.py").read_text(encoding="utf-8")
        start = source.index("if upload_mode and analysis_running and not results_visible:")
        end = source.index('    else:\n        from datetime import date', start)
        transition = source[start:end]

        self.assertIn("approved_bom_upload_progress", transition)
        self.assertIn("should_render_approved_bom_upload_form(", transition)
        self.assertIn("approved_bom_upload_panel", transition)
        self.assertIn("elif results_visible:", transition)
        self.assertIn("results_visible=results_visible", source)

    def test_submitted_form_reruns_before_rendering_the_analysis_transition(self):
        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        render = source.index("            render_bom_catalog(", source.index("saved_bom_rerun_handoff"))
        consume = source.index("consume_approved_bom_submission(st.session_state)", render)
        transition = source[consume : consume + 700]
        self.assertIn("if _approved_bom_submitted and uploaded_file is not None:", transition)
        self.assertIn("st.rerun()", transition)
        self.assertIn("if not analysis_in_progress:\n            render_upload_detected(", source)
        self.assertNotIn("st.data_editor(\n                    bom_df", source)

    def test_upload_form_is_hidden_while_analysis_progress_is_active(self):
        self.assertTrue(
            should_render_approved_bom_upload_form(
                upload_mode=True,
                analysis_running=False,
            )
        )
        self.assertFalse(
            should_render_approved_bom_upload_form(
                upload_mode=True,
                analysis_running=True,
            )
        )
        self.assertFalse(
            should_render_approved_bom_upload_form(
                upload_mode=False,
                analysis_running=False,
            )
        )
        self.assertFalse(
            should_render_approved_bom_upload_form(
                upload_mode=True,
                analysis_running=False,
                results_visible=True,
            )
        )

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
        self.assertFalse(
            should_stop_approved_bom_renderer(
                active,
                upload_mode=True,
                results_visible=True,
            )
        )

    def test_starting_new_analysis_clears_completed_result_state(self):
        state = {
            "results_df": object(),
            "analysis_id": "old-analysis",
            "analysis_saved": True,
            "show_analysis_success_29b": True,
            "approved_bom_project_name": "Old project",
            "cadivor_bom_pipeline_active": True,
        }

        prepare_new_approved_bom_analysis(state)

        self.assertNotIn("results_df", state)
        self.assertNotIn("analysis_id", state)
        self.assertNotIn("approved_bom_project_name", state)
        self.assertNotIn("cadivor_bom_pipeline_active", state)
        self.assertTrue(state["cadivor_bom_upload_open"])

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

    def test_approved_upload_hides_duplicate_legacy_workspace(self):
        self.assertFalse(
            should_render_legacy_bom_workspace({"cadivor_bom_upload_open": True})
        )
        self.assertFalse(
            should_render_legacy_bom_workspace({"cadivor_bom_pipeline_active": True})
        )
        self.assertFalse(
            should_render_legacy_bom_workspace({"cadivor_bom_catalog_requested": True})
        )
        self.assertFalse(
            should_render_legacy_bom_workspace({"cadivor_show_saved_boms": True})
        )
        self.assertFalse(
            should_render_legacy_bom_workspace(
                {
                    "results_df": type("Results", (), {"empty": False})(),
                    "analysis_saved": True,
                    "analysis_id": "saved-analysis",
                }
            )
        )
        self.assertTrue(should_render_legacy_bom_workspace({}))


class BOMPartPayloadJsonSafetyTests(unittest.TestCase):
    def test_non_finite_cost_and_quantity_values_are_treated_as_missing(self):
        fields = analysis_part_cost_fields(
            {
                "MPN": "CAP-10U",
                "Unit Price": float("inf"),
                "Quantity": float("inf"),
                "Supplier Offers": [
                    {"distributor": "DigiKey", "unit_price": float("inf")}
                ],
            }
        )

        self.assertEqual(fields["unit_price"], 0)
        self.assertEqual(fields["quantity"], 0)
        self.assertEqual(fields["supplier_offers"], [])

        finite_price_fields = analysis_part_cost_fields(
            {
                "MPN": "CAP-10U",
                "Unit Price": 0.25,
                "Quantity": 4,
                "Supplier Offers": [
                    {
                        "distributor": "DigiKey",
                        "unit_price": 0.25,
                        "price_break_quantity": float("inf"),
                        "stock": float("inf"),
                    }
                ],
            }
        )
        self.assertEqual(
            finite_price_fields["supplier_offers"][0]["price_break_quantity"],
            None,
        )
        self.assertEqual(finite_price_fields["supplier_offers"][0]["stock"], None)

    def test_nested_non_finite_supplier_values_become_strict_json(self):
        payload = {
            "risk_score": 72,
            "supplier_evidence": [
                {"stock": float("inf"), "lead_time": float("-inf")},
                {"price": float("nan")},
            ],
        }

        cleaned = json_safe_value(payload)

        self.assertEqual(
            cleaned,
            {
                "risk_score": 72,
                "supplier_evidence": [
                    {"stock": None, "lead_time": None},
                    {"price": None},
                ],
            },
        )
        json.dumps(cleaned, allow_nan=False)

    def test_analysis_part_insert_sanitizes_nested_supplier_payload(self):
        source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn(
            "pending_records = [json_safe_value(record) for record in part_records]",
            source,
        )


if __name__ == "__main__":
    unittest.main()
