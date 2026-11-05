"""Focused regressions for New BOM / upload-rerun / save→report blank flashes."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
UPLOAD = (ROOT / "src" / "bom_upload_flow.py").read_text(encoding="utf-8")
APPROVED = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
DETAIL = (ROOT / "src" / "pages" / "analysis_detail.py").read_text(encoding="utf-8")
MAIN_TRANSITION = (ROOT / "src" / "ui" / "main_transition.py").read_text(encoding="utf-8")
SHELL = (ROOT / "src" / "ui" / "unified_shell.py").read_text(encoding="utf-8")


def test_navigation_cover_insets_to_rail_so_sidebar_stays_visible():
    nav_css = MAIN_TRANSITION.split(
        '.cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"]{{',
        1,
    )[1].split("@media(max-width:700px)", 1)[0]
    assert "left:var(--cv-foundation-rail,228px)!important" in nav_css
    assert "top:var(--cv-foundation-top,64px)!important" in nav_css
    assert 'left:var(--cv-foundation-rail,228px);right:0;top:var(--cv-foundation-top,64px)' in (
        MAIN_TRANSITION
    )


def test_same_page_upload_rerun_does_not_hide_stale_route_body():
    """CSV selection remounts widgets; stale form must stay visible without Opening."""
    rule = SHELL.split(
        "Same-page remounts (CSV upload on New BOM)",
        1,
    )[1].split("Retired Streamlit shell containers", 1)[0]
    assert 'body:has([data-cadivor-main-transition="1"])' in rule
    assert "cadivor_authenticated_route_body" in rule
    assert 'body:has([class*="st-key-cv_foundation_navigation"]:not([data-stale="true"]))\n' not in rule


def test_upload_receiving_flag_keeps_form_receiving_surface():
    from src.bom_upload_flow import remember_approved_bom_upload

    upload = type("Uploaded", (), {"name": "flash.csv"})()
    state = {"bom_file_uploader": upload}
    remember_approved_bom_upload(state)
    assert state["cadivor_bom_upload_receiving"] is True
    assert "upload_receiving" in APPROVED
    assert "Receiving file" in APPROVED
    assert "receiving_hidden" in APPROVED


def test_report_handoff_keeps_saving_until_ei_ready():
    """Persist under Analyzer Saving; Details paints EI only (no mixed Opening/Saving)."""
    early_bridge = RUNTIME.split("_pending_details_nav_early", 1)[1].split(
        "def _resolved_qp_value", 1
    )[0]
    assert "cadivor-bom-progress-bridge-hide" not in early_bridge
    assert "finish_approved_bom_submission(st.session_state)" not in early_bridge
    assert 'st.session_state["cadivor_bom_report_handoff_active"] = True' in early_bridge
    assert 'st.session_state["cadivor_bom_details_paint_report_only"] = True' in early_bridge
    assert '[_presented_route_bridge_early] = "Analysis Details"' not in early_bridge
    assert "arm_opening=False" in early_bridge
    assert "arm_opening=True" not in early_bridge

    details = RUNTIME.split('if app_mode == "Analysis Details":', 1)[1].split(
        'if app_mode == "BOM Settings":', 1
    )[0]
    assert "analysis_details_handoff_report_only" in details
    assert "analysis_details_handoff_saving_surface" not in details
    assert 'key="bom8_analysis_progress_card"' not in details.split(
        "with st.container(key=\"approved_page_canvas_standard_analysis_detail\")", 1
    )[0]

    assert "analysis_details_handoff_report_ready" in DETAIL
    assert "finish_approved_bom_submission(st.session_state)" in DETAIL
    handoff = DETAIL.split("_bom_report_handoff", 1)[1].split(
        "active_tab = _render_analysis_section_navigation", 1
    )[0]
    assert 'active_tab = "Engineering Intelligence"' in handoff
    assert "finish_approved_bom_submission" in handoff


def test_report_handoff_suppresses_opening_and_freezes_nav_keys():
    """No Opening Analysis Details during handoff; freeze Analyzer rail keys."""
    startup = RUNTIME.split("inject_premium_css()", 1)[1].split(
        "def _read_users_role_for_shell", 1
    )[0]
    assert "cadivor_bom_report_handoff_active" in startup
    assert "_paint_opening = False" in startup
    render = SHELL.split("def render_unified_shell", 1)[1]
    assert 'highlight_label = "BOM Analyzer"' in render
    assert "cadivor_bom_report_handoff_active" in render


def test_finish_clears_report_handoff_keys():
    assert "cadivor_bom_report_handoff_active" in UPLOAD.split(
        "def finish_approved_bom_submission", 1
    )[1].split("if reopen_upload:", 1)[0]
    assert "cadivor_bom_nav_bridge" in UPLOAD.split(
        "def finish_approved_bom_submission", 1
    )[1].split("if reopen_upload:", 1)[0]
