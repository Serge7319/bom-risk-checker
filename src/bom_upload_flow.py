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
            # The first run starts the pipeline, while later reruns need the
            # same UploadedFile to rebuild the preview and render progress.
            state["bom8_analysis_upload_file"] = uploaded_file
            state["cadivor_bom_pipeline_active"] = True
            state["bom8_analysis_pending"] = True

    if uploaded_file is not None:
        state.pop("bom8_sample_mode", None)

    return submitted, uploaded_file, project_name, bom_name


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


__all__ = [
    "consume_approved_bom_submission",
    "resume_approved_bom_submission",
    "should_stop_approved_bom_renderer",
]


def should_stop_approved_bom_renderer(
    state: MutableMapping[str, Any],
    *,
    upload_mode: bool,
) -> bool:
    """Keep the authenticated BOM pipeline running after its upload form reruns."""
    return not (bool(upload_mode) and bool(state.get("cadivor_bom_pipeline_active")))
