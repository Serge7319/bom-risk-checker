"""Regression contracts for BOM analysis progress position stability.

Preparing and component progress must share one top-aligned surface. Once
component progress begins, the UI must not regress to Preparing. Completing
the worker arms a handoff that keeps the progress card until save/navigate.
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
    assert "progress_handoff_path" in surface
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
    assert 'st.session_state["cadivor_bom_analysis_handoff"] = True' in success.split(
        "st.rerun()", 1
    )[0]
    # Handoff path keeps Analyzing/Saving — never Preparing.
    handoff = RUNTIME.split("progress_handoff_path", 1)[1].split("preparing_top_path", 1)[0]
    assert "Analyzing BOM" in handoff
    assert "Saving the analysis" in handoff
    assert "Preparing your BOM analysis" not in handoff


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
    # In-progress progress still stops; persist runs inside the fragment.
    assert "stop_authenticated_page()" in surface
    assert "handoff_armed" in surface


def test_handoff_keeps_progress_surface_until_save_completes():
    """Results must not clear the top progress card before Analysis Details."""
    assert "cadivor_bom_analysis_handoff" in RUNTIME
    assert "cadivor_bom_analysis_handoff" in UPLOAD
    success = RUNTIME.split('st.session_state["results_df"] = results_df', 1)[1]
    # Must arm handoff instead of finishing the pipeline immediately.
    assert 'st.session_state["cadivor_bom_analysis_handoff"] = True' in success.split(
        "CADIVOR_PHASE handoff_armed", 1
    )[0]
    armed = success.split("CADIVOR_PHASE handoff_armed", 1)[1].split("return", 1)[0]
    assert "finish_approved_bom_submission(st.session_state, reopen_upload=False)" not in armed
    assert "_persist_bom_handoff_analysis(" in armed
    assert "progress_handoff_path" in RUNTIME
    assert "handoff_fallthrough_to_save" in RUNTIME
    # Catalog must refuse to paint during handoff.
    approved = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
    assert 'st.session_state.get("cadivor_bom_analysis_handoff")' in approved

def test_handoff_skips_catalog_chrome_before_save():
    """Fallthrough must not remount catalog/CSS above the saving card."""
    assert "_handoff_save_active" in RUNTIME
    assert "handoff_fallthrough_to_save" in RUNTIME
    # Catalog path is skipped while handoff owns the surface.
    assert "elif _handoff_save_active:" in RUNTIME
    handoff_branch = RUNTIME.split("elif _handoff_save_active:", 1)[1].split(
        "render_bom_catalog(", 1
    )[0]
    assert "resume_approved_bom_submission" in handoff_branch
    assert "render_bom_catalog(" not in handoff_branch

def test_handoff_defers_analysis_details_navigation_one_frame():
    """Saving stays on BOM Analyzer, then bridge-reruns into Details without remounting the card."""
    assert "cadivor_bom_open_details_after_save" in RUNTIME
    assert "handoff_saved_hold_saving" in RUNTIME
    assert "handoff_navigate_bridge" in RUNTIME
    assert "cadivor_bom_navigate_details_id" in RUNTIME
    assert "via=bridge_rerun" in RUNTIME
    assert "handoff_navigate_analysis_details" in RUNTIME
    # Same-run navigate after Saving remounted the card under Analysis Details.
    hold = RUNTIME.split("handoff_hold_armed", 1)[1].split(
        "elif _future is not None and not _results_ready:", 1
    )[0]
    assert "cadivor_bom_navigate_details_id" in hold
    assert "st.rerun()" in hold
    assert 'navigate_to(\n                        "Analysis Details"' not in hold



def test_handoff_persists_inline_without_catalog_fallthrough():
    """Saving persist must not remount catalog/form widgets under the card."""
    assert "_persist_bom_handoff_analysis" in RUNTIME
    surface = RUNTIME.split("handoff_fallthrough_to_save", 1)[1].split(
        "elif _future is not None and not _results_ready:", 1
    )[0]
    assert "_persist_bom_handoff_analysis(" in surface
    assert "handoff_hold_armed" in surface
    assert "sleep(" in surface
    assert "handoff_navigate_bridge" in surface
    assert "cadivor_bom_navigate_details_id" in surface
    # Must not resume catalog painting on this path.
    assert "render_bom_catalog(" not in surface


def test_persist_keeps_shell_until_report_contract():
    """Saving must persist inline and only then navigate, keeping one saving frame."""
    assert "handoff_saved_hold_saving" in RUNTIME
    assert "handoff_navigate_bridge" in RUNTIME
    assert "handoff_navigate_analysis_details" in RUNTIME
    assert "_persist_bom_handoff_analysis" in RUNTIME
    # Inline persist happens before the hold/bridge rerun.
    fall = RUNTIME.split("handoff_fallthrough_to_save", 1)[1]
    assert fall.index("_persist_bom_handoff_analysis(") < fall.index("handoff_saved_hold_saving")
    assert fall.index("handoff_saved_hold_saving") < fall.index("handoff_navigate_bridge")


def test_handoff_armed_does_not_remount_via_rerun():
    """Worker completion persists inline; only the post-hold bridge uses st.rerun()."""
    armed = RUNTIME.split("CADIVOR_PHASE handoff_armed", 1)[1].split(
        "handoff_hold_armed", 1
    )[0]
    assert "st.rerun()" not in armed
    assert "_persist_bom_handoff_analysis(" in armed
    hold = RUNTIME.split("handoff_hold_armed", 1)[1].split(
        "elif _future is not None and not _results_ready:", 1
    )[0]
    assert "handoff_navigate_bridge" in hold
    assert "st.rerun()" in hold
