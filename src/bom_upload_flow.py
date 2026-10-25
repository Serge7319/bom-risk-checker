"""State handoff from the approved BOM upload form to the analysis pipeline."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


def consume_approved_bom_submission(
    state: MutableMapping[str, Any],
) -> tuple[bool, Any, str, str]:
    """Consume the form event and preserve its file for later Streamlit reruns."""
    submitted = bool(state.pop("cadivor_bom_analysis_ready", False))
    uploaded_file = state.pop("cadivor_pending_upload", None)
    project_name = str(state.pop("cadivor_pending_project", "") or "")
    bom_name = str(state.pop("cadivor_pending_bom_name", "") or "")

    if submitted:
        # Replace prior names, including with blanks, so a new upload cannot
        # silently inherit the previous BOM's title or project.
        state["bom8_project_name"] = project_name
        state["bom8_bom_name"] = bom_name
        if uploaded_file is not None:
            for key in (
                "results_df",
                "analysis_saved",
                "analysis_id",
                "health_score",
                "health_status",
                "show_analysis_success_29b",
                "cadivor_active_analysis_id",
                "cadivor_active_analysis_tab",
                "cadivor_show_detailed_risk",
            ):
                state.pop(key, None)
            # Keep the file available across reruns while the analysis runtime
            # parses it and renders the progress state.
            state["bom8_analysis_upload_file"] = uploaded_file
            state["cadivor_bom_pipeline_active"] = True
            state["bom8_analysis_pending"] = True

    if uploaded_file is not None:
        state.pop("bom8_sample_mode", None)

    return submitted, uploaded_file, project_name, bom_name


def stage_approved_bom_submission(
    state: MutableMapping[str, Any],
    *,
    submitted: bool,
    uploaded_file: Any,
    project_name: str,
    bom_name: str,
) -> bool:
    """Stage a form submit from the returned value or keyed widget state.

    If neither source contains a file, retain a visible error instead of
    silently dropping Analyze.
    """
    if not submitted:
        return False

    upload = uploaded_file
    if upload is None:
        upload = state.get("bom_file_uploader")

    if upload is None:
        state["cadivor_bom_submission_error"] = (
            "Analyze was received, but the selected file was not available on Cadivor. "
            "Remove it from the upload box, select it again, wait for the upload to finish, "
            "then select Analyze BOM."
        )
        return False

    state.pop("cadivor_bom_submission_error", None)
    state["cadivor_bom_analysis_ready"] = True
    state["cadivor_pending_upload"] = upload
    state["cadivor_pending_project"] = str(project_name or "")
    state["cadivor_pending_bom_name"] = str(bom_name or "")
    return True


def resume_approved_bom_submission(
    state: MutableMapping[str, Any],
) -> tuple[Any, str, str]:
    """Restore the active upload and names on later analysis reruns."""
    if not state.get("cadivor_bom_pipeline_active"):
        return None, "", ""

    return (
        state.get("bom8_analysis_upload_file"),
        str(state.get("bom8_project_name") or ""),
        str(state.get("bom8_bom_name") or ""),
    )


def finish_approved_bom_submission(
    state: MutableMapping[str, Any], *, reopen_upload: bool = False
) -> None:
    """Clear an interrupted pipeline so the user can retry or leave the page."""
    for key in (
        "cadivor_bom_pipeline_active",
        "bom8_analysis_upload_file",
        "bom8_analysis_pending",
        "bom8_analysis_in_progress",
        "bom8_analysis_future",
        "bom8_analysis_executor",
        "bom8_analysis_progress_queue",
        "bom8_analysis_cancel_event",
        "bom8_analysis_progress",
        "cadivor_bom_analysis_transition",
    ):
        state.pop(key, None)
    if reopen_upload:
        state["cadivor_bom_upload_open"] = True

def fail_approved_bom_summary_save(
    state: MutableMapping[str, Any], *, message: str
) -> None:
    """Clear unsaved analysis state and reopen the BOM form after a summary-save failure."""
    finish_approved_bom_submission(state, reopen_upload=True)
    for key in (
        "results_df",
        "analysis_saved",
        "analysis_id",
        "health_score",
        "health_status",
        "show_analysis_success_29b",
        "cadivor_active_analysis_id",
        "cadivor_active_analysis_tab",
        "cadivor_show_detailed_risk",
        "cadivor_saved_bom_rerun_active",
        "cadivor_one_time_pending_source_filename",
        "cadivor_one_time_pending_project_name",
        "cadivor_one_time_pending_bom_name",
        "cadivor_one_time_pending_component_count",
    ):
        state.pop(key, None)
    state["cadivor_bom_analysis_error"] = str(message or "").strip() or (
        "Cadivor could not save the analysis summary. Check workspace access and retry."
    )


__all__ = [
    "consume_approved_bom_submission",
    "stage_approved_bom_submission",
    "resume_approved_bom_submission",
    "finish_approved_bom_submission",
    "fail_approved_bom_summary_save",
    "should_render_approved_bom_upload_form",
    "should_render_legacy_bom_workspace",
    "should_render_bom_analysis_body",
    "should_stop_approved_bom_renderer",
    "prepare_new_approved_bom_analysis",
    "has_completed_saved_bom_results",
]


def has_completed_saved_bom_results(state: MutableMapping[str, Any]) -> bool:
    """True when this session has a saved result that can render without its upload file."""
    results = state.get("results_df")
    return bool(
        results is not None
        and not getattr(results, "empty", True)
        and state.get("analysis_saved")
        and str(
            state.get("analysis_id") or state.get("cadivor_active_analysis_id") or ""
        ).strip()
    )


def should_disable_bom_analyze_button(
    *, analysis_running: bool, upload_available: bool
) -> bool:
    """Enable Analyze only after the server confirms the complete upload is available."""
    return bool(analysis_running or not upload_available)


def should_render_approved_bom_upload_form(
    *,
    upload_mode: bool,
    analysis_running: bool,
    results_visible: bool = False,
) -> bool:
    """Hide upload controls while progress or completed results own the page."""
    return (
        bool(upload_mode)
        and not bool(analysis_running)
        and not bool(results_visible)
    )


def should_stop_approved_bom_renderer(
    state: MutableMapping[str, Any],
    *,
    upload_mode: bool,
    results_visible: bool = False,
) -> bool:
    """Keep the analysis pipeline running while it renders progress or results."""
    return not (
        bool(results_visible)
        or (bool(upload_mode) and bool(state.get("cadivor_bom_pipeline_active")))
    )


def prepare_new_approved_bom_analysis(state: MutableMapping[str, Any]) -> None:
    """Clear the finished analysis context before showing a fresh upload form."""
    for key in (
        "results_df",
        "analysis_saved",
        "analysis_id",
        "health_score",
        "health_status",
        "show_analysis_success_29b",
        "cadivor_active_analysis_id",
        "cadivor_active_analysis_tab",
        "cadivor_show_detailed_risk",
        "cadivor_bom_pipeline_active",
        "cadivor_bom_catalog_requested",
        "cadivor_show_saved_boms",
        "cadivor_preselect_saved_bom_id",
        "bom8_analysis_future",
        "bom8_analysis_pending",
        "bom8_analysis_in_progress",
        "bom8_analysis_upload_file",
        "cadivor_bom_analysis_transition",
        "bom8_project_name",
        "bom8_bom_name",
        "cadivor_bom_analysis_ready",
        "cadivor_pending_upload",
        "cadivor_pending_project",
        "cadivor_pending_bom_name",
        "cadivor_bom_submission_error",
        "approved_bom_project_name",
        "approved_bom_name",
        "bom_file_uploader",
    ):
        state.pop(key, None)
    state["cadivor_bom_upload_open"] = True
    state["cadivor_manage_saved_boms"] = False


def should_render_legacy_bom_workspace(state: MutableMapping[str, Any]) -> bool:
    """Avoid rendering a second upload form while the approved BOM form is active."""
    return not (
        bool(state.get("cadivor_bom_upload_open"))
        or bool(state.get("cadivor_bom_pipeline_active"))
        or bool(state.get("bom8_analysis_pending"))
        or bool(state.get("bom8_analysis_in_progress"))
        or bool(state.get("bom8_analysis_future"))
        or bool(state.get("cadivor_bom_catalog_requested"))
        or bool(state.get("cadivor_show_saved_boms"))
        or has_completed_saved_bom_results(state)
    )


def should_render_bom_analysis_body(
    app_mode: object,
    *,
    high_risk_review: bool = False,
) -> bool:
    """Render the analysis pipeline for BOM Analyzer and the cross-BOM review."""
    return str(app_mode or "").strip() == "BOM Analyzer" or bool(high_risk_review)
