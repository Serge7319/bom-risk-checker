"""Saved-analysis manager visibility. Empty hosts must never stack."""
from __future__ import annotations

from typing import Any

MANAGE_SAVED_ANALYSES = "Manage saved analyses"
BOM_ANALYZER_ROUTE = "BOM Analyzer"


def should_render_saved_analysis_control(
    rows: Any,
    *,
    route: str,
    status: str = "ok",
) -> bool:
    """One control, only on BOM Analyzer, only with loaded rows.

    Timeout, error, account switch, and an empty result are not a purpose.
    Those paths must not create an expander placeholder.
    """
    if str(route or "").strip() != BOM_ANALYZER_ROUTE:
        return False
    if str(status or "").strip() != "ok":
        return False
    return any(isinstance(row, dict) and str(row.get("id") or "").strip() for row in rows or [])


def release_saved_analysis_placeholder() -> None:
    """Replace the saved-analysis slot in place. Never append a labeled row."""
    import streamlit as st

    slot = st.empty()
    slot.empty()
