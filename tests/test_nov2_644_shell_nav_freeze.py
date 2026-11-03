"""Nov 2 6:44 recording: duplicate foundation nav in Analysis Details main body."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = (ROOT / "src" / "ui" / "unified_shell.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
DETAIL = (ROOT / "src" / "pages" / "analysis_detail.py").read_text(encoding="utf-8")
FLOW = (ROOT / "src" / "bom_upload_flow.py").read_text(encoding="utf-8")


def test_shell_freezes_analyzer_nav_identity_during_bom_details_handoff():
    """Rail must not remount when Details becomes the session route mid-handoff."""
    render = SHELL.split("def render_unified_shell", 1)[1]
    assert "_bom_shell_handoff" in render
    assert 'active_route = "BOM Analyzer"' in render
    assert "include_analysis_reports = bool(active_analysis_id) and not _bom_shell_handoff" in render
    assert 'highlight_label = "BOM Analyzer" if _bom_shell_handoff else active_label' in render
    assert "cadivor_bom_shell_nav_hold" in render
    assert 'cadivor_bom_details_paint_report_only' in render


def test_shell_retires_orphaned_foundation_chrome_outside_rail_host():
    """6:44 leak: workspace + nav button stack remounted outside the rail host."""
    css = SHELL.split("def inject_unified_shell_css", 1)[1].split(
        "def render_unified_shell", 1
    )[0]
    assert ".cv-foundation-workspace):not(" in css.replace("\n", "").replace(" ", "") or (
        ":has(.cv-foundation-workspace):not(" in css
    )
    assert ":has(.cv-foundation-sidebar-brand):not(" in css
    assert ":has(.cv-foundation-nav-group):not(" in css
    assert '[class*="st-key-cv_foundation_nav_"]:not(' in css
    assert '[class*="st-key-cv_foundation_navigation"] *' in css


def test_runtime_passes_analyzer_page_to_shell_during_handoff():
    assert '_shell_page_for_chrome = "BOM Analyzer"' in RUNTIME
    assert "cadivor_bom_shell_nav_hold" in RUNTIME
    block = RUNTIME.split("_shell_page_for_chrome = _shell_route", 1)[1].split(
        "render_unified_shell(", 1
    )[0]
    assert "cadivor_bom_report_handoff_active" in block
    assert "cadivor_bom_nav_bridge" in block


def test_report_ready_holds_shell_nav_one_frame_after_finish():
    ready = DETAIL.split("_bom_report_handoff", 1)[1].split("else:", 1)[0]
    assert 'st.session_state["cadivor_bom_shell_nav_hold"] = True' in ready
    assert "finish_approved_bom_submission(st.session_state)" in ready
    # Hold is armed after finish clears transient keys.
    assert ready.index("finish_approved_bom_submission") < ready.index(
        'cadivor_bom_shell_nav_hold"] = True'
    )
    assert '"cadivor_bom_shell_nav_hold"' in FLOW
