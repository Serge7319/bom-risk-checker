from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NAVIGATION = (ROOT / "src" / "ui" / "navigation.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
EI_REPORT = (ROOT / "src" / "ui" / "ei_bom_report.py").read_text(encoding="utf-8")


def test_scroll_reset_runs_in_app_document_until_destination_mounts():
    reset = NAVIGATION.split("def inject_nav_scroll_reset_if_needed", 1)[1]

    assert "st.html(" in reset
    assert "unsafe_allow_javascript=True" in reset
    assert "const doc = document;" in reset
    assert 'main.querySelector(\'[data-testid="stMainBlockContainer"]\')' in reset
    assert "data-cadivor-page-body" in reset
    assert "state.timer = window.setInterval(state.reset, 100)" in reset
    assert "state.settled >= 3" in reset
    assert "Date.now() - state.startedAt > 10000" in reset
    assert "components.html" not in reset


def test_analysis_submission_and_report_switch_request_same_route_scroll_reset():
    assert "def request_main_scroll_reset()" in NAVIGATION
    standalone_finder_reset = NAVIGATION.split(
        'if page == ALTERNATIVE_FINDER_PAGE', 1
    )[1].split("# Any explicit in-app navigation", 1)[0]
    assert '"cadivor_replacement_search_pending"' in standalone_finder_reset
    assert "request_main_scroll_reset()" in NAVIGATION.split("def navigate_to", 1)[1].split(
        "def request_main_scroll_reset", 1
    )[0]


def test_long_bom_analysis_keeps_top_anchor_until_progress_finishes_or_user_scrolls():
    progress = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
    start = progress.index("if analysis_running and not results_visible:")
    end = progress.index('with st.container(key="approved_bom_title")', start)
    active_scroll = progress[start:end]

    assert "window.setInterval(state.reset, 350)" in active_scroll
    assert "const progress = doc.querySelector('.st-key-bom8_analysis_progress_card')" in active_scroll
    assert "doc.addEventListener('wheel', cancelOnScroll" in active_scroll
    assert "doc.addEventListener('touchmove', cancelOnScroll" in active_scroll
    assert "Date.now() - state.startedAt > 600000" in active_scroll
    assert "Date.now() - state.missingSince > 10000" in active_scroll
    assert 'cadivor_bom_analysis_scroll_token' in active_scroll

    submit = RUNTIME.split("if _approved_bom_submitted and uploaded_file is not None:", 1)[1]
    assert "request_main_scroll_reset()" in submit.split("st.rerun()", 1)[0]
    selector_callback = EI_REPORT.split(
        "def _navigate_to_detailed_report_analysis", 1
    )[1].split("def _esc", 1)[0]
    assert "request_main_scroll_reset()" in selector_callback
    assert "st.rerun()" in selector_callback


def test_bom_analysis_resets_scroll_again_after_the_result_or_terminal_state_mounts():
    active_fragment = RUNTIME.split("def _render_active_bom_analysis():", 1)[1].split(
        "with st.container(key=\"bom8_analysis_progress_card\")", 1
    )[0]
    assert active_fragment.count("request_main_scroll_reset()") >= 3
    success_path = active_fragment.split('st.session_state["results_df"] = results_df', 1)[1]
    assert success_path.index("request_main_scroll_reset()") < success_path.index("st.rerun()")
