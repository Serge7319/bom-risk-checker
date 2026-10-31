"""Regression contracts for BOM analysis progress position stability.

Preparing and component progress must share one top-aligned surface. Once
component progress begins, the UI must not regress to Preparing. Completing
the worker must clear pipeline flags with the result mount.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
UPLOAD = (ROOT / "src" / "bom_upload_flow.py").read_text(encoding="utf-8")


def test_analysis_surface_owns_top_before_catalog_css():
    surface = RUNTIME.split("Unified analysis surface:", 1)[1]
    assert "preparing_top_path" in surface
    assert "progress_top_path" in surface
    assert "progress_hold_path" in surface
    assert 'key="bom8_analysis_progress_card"' in surface.split("stop_authenticated_page()", 1)[0]
    # Preparing and progress share the progress_card key (no mid-page remount).
    assert surface.index("preparing_top_path") < surface.index("stop_authenticated_page()")
    assert "Preparing your BOM analysis" in surface.split("preparing_top_path", 1)[1].split(
        "stop_authenticated_page()", 1
    )[0]


def test_component_progress_is_monotonic_and_never_regresses_to_preparing():
    assert "cadivor_bom_component_progress_started" in RUNTIME
    assert "cadivor_bom_component_progress_started" in UPLOAD
    success = RUNTIME.split('st.session_state["results_df"] = results_df', 1)[1]
    assert "finish_approved_bom_submission(st.session_state, reopen_upload=False)" in success.split(
        "st.rerun()", 1
    )[0]
    # Hold path keeps Analyzing when progress started but future already cleared.
    hold = RUNTIME.split("progress_hold_path", 1)[1].split("preparing_top_path", 1)[0]
    assert "Analyzing BOM" in hold
    assert "Preparing your BOM analysis" not in hold


def test_analyze_click_does_not_paint_preparing_under_the_upload_form():
    click = RUNTIME.split("CADIVOR_PHASE analyze_click_consumed", 1)[1].split(
        "if not _approved_bom_submitted and st.session_state.get(\"cadivor_bom_pipeline_active\"):",
        1,
    )[0]
    assert "bom8_analysis_preparing_card" not in click
    assert "st.rerun()" in click


def test_mid_page_armed_path_does_not_paint_a_second_preparing_card():
    mid = RUNTIME.split(
        "Preparing already painted on the early surface", 1
    )[1].split("New BOM upload is the destination surface", 1)[0]
    assert "bom8_analysis_preparing_card" not in mid
    assert "Preparing your BOM analysis" not in mid


def test_worker_bootstraps_before_progress_paint_then_stops():
    """Bootstrap the worker before painting so the first card is already top progress.

    Painting Preparing first, then remounting progress after rerun, let leftover
    upload chrome push Preparing mid-page (~700px) before progress landed at top.
    """
    surface = RUNTIME.split("Unified analysis surface:", 1)[1].split(
        "_has_completed_saved_results = has_completed_saved_bom_results", 1
    )[0]
    assert "via=bootstrap_before_paint" in surface
    assert surface.index("via=bootstrap_before_paint") < surface.index(
        "progress_top_path"
    )
    assert surface.index("progress_top_path") < surface.index("stop_authenticated_page()")
    assert "_early_analysis_surface_painted = True" not in surface
