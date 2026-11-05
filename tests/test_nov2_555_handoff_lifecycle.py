"""Nov 2 5:55 recording: blank login splash + Saving/Details mixed-route handoff."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
BOOT = (ROOT / "scripts" / "cadivor_streamlit_boot.py").read_text(encoding="utf-8")
ENTRY = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
CSV_25 = ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv"


def test_synthetic_25_component_fixture_exists():
    text = CSV_25.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[0].lower().startswith("mpn")
    assert len(lines) == 26  # header + 25


def test_boot_splash_and_entry_force_light_canvas():
    assert "def apply_light_boot_splash" in BOOT
    assert "cadivor-light-boot" in BOOT
    assert "cadivor-boot-splash" in BOOT
    assert "stAppSkeleton" in BOOT
    assert "apply_light_boot_splash()" in ENTRY
    chrome = ENTRY.split('id="cadivor-root-chrome"', 1)[1].split("</style>", 1)[0]
    assert "color-scheme: light" in chrome


def test_handoff_stays_on_analyzer_saving_then_details_paints_report_only():
    """Event order from the 5:55 recording: persist under Saving, then Details=EI."""
    assert "handoff_saved_hold_saving" in RUNTIME
    assert "handoff_navigate_bridge" in RUNTIME
    hold = RUNTIME.split("handoff_hold_armed", 1)[1].split(
        "elif _future is not None and not _results_ready:", 1
    )[0]
    assert "cadivor_bom_navigate_details_id" in hold
    assert "finish_approved_bom_submission(st.session_state)" not in hold
    early = RUNTIME.split("_pending_details_nav_early", 1)[1].split(
        "def _resolved_qp_value", 1
    )[0]
    assert "arm_opening=False" in early
    assert "_rerun=False" in early
    assert 'app_mode = _shell_route' in early
    assert "cadivor_bom_details_paint_report_only" in early
    assert "via=bridge_same_run" in early
    startup = RUNTIME.split("inject_premium_css()", 1)[1].split(
        "mount_main_transition_loading", 1
    )[0]
    assert "cadivor_bom_report_handoff_active" in startup
    assert "_paint_opening = False" in startup
    details = RUNTIME.split('if app_mode == "Analysis Details":', 1)[1].split(
        'if app_mode == "BOM Settings":', 1
    )[0]
    assert "analysis_details_handoff_report_only" in details
    assert "analysis_details_handoff_saving_surface" not in details
    # No second Saving card under Analysis Details URL.
    pre_canvas = details.split(
        'with st.container(key="approved_page_canvas_standard_analysis_detail")', 1
    )[0]
    assert 'key="bom8_analysis_progress_card"' not in pre_canvas
