"""State handoff from the approved BOM upload form to the analysis pipeline."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


def consume_approved_bom_submission(
    state: MutableMapping[str, Any],
) -> tuple[bool, Any, str, str]:
    """Consume the new-BOM form values and queue the existing analysis flow."""
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
            state["bom8_analysis_pending"] = True

    if uploaded_file is not None:
        state.pop("bom8_sample_mode", None)

    return submitted, uploaded_file, project_name, bom_name


__all__ = ["consume_approved_bom_submission"]
