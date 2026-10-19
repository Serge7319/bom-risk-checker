from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NAVIGATION = (ROOT / "src" / "ui" / "navigation.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
EI_REPORT = (ROOT / "src" / "ui" / "ei_bom_report.py").read_text(encoding="utf-8")


def test_scroll_reset_retries_until_the_route_has_had_time_to_mount():
    reset = NAVIGATION.split("def inject_nav_scroll_reset_if_needed", 1)[1]

    assert "if (marked && finalAttempt)" in reset
    assert "index === delays.length - 1" in reset
    assert "if (userInteracted) return" in reset
    assert "[0, 40, 120, 280, 600, 1100]" in reset
    assert "marked.setAttribute('data-cadivor-nav-scroll-done', '1')" in reset


def test_analysis_submission_and_report_switch_request_same_route_scroll_reset():
    assert "def request_main_scroll_reset()" in NAVIGATION
    standalone_finder_reset = NAVIGATION.split(
        'if page == ALTERNATIVE_FINDER_PAGE', 1
    )[1].split("# Any explicit in-app navigation", 1)[0]
    assert '"cadivor_replacement_search_pending"' in standalone_finder_reset
    assert "request_main_scroll_reset()" in NAVIGATION.split("def navigate_to", 1)[1].split(
        "def request_main_scroll_reset", 1
    )[0]

    submit = RUNTIME.split("if _approved_bom_submitted and uploaded_file is not None:", 1)[1]
    assert "request_main_scroll_reset()" in submit.split("st.rerun()", 1)[0]
    selector_callback = EI_REPORT.split(
        "def _navigate_to_detailed_report_analysis", 1
    )[1].split("def _esc", 1)[0]
    assert "request_main_scroll_reset()" in selector_callback
    assert "st.rerun()" in selector_callback
