"""Opening budget, account switch, and non-stacking saved-analysis placeholders."""
from __future__ import annotations

import time
from pathlib import Path

from src.boot_read_budget import (
    FIRST_PAGE_BUDGET_SECONDS,
    begin_first_page_budget,
    end_first_page_budget,
    run_with_read_budget,
)
from src.ui.main_transition import (
    DELAY_ROUTE_BODY_REVEAL_KEY,
    MAIN_TRANSITION_ACTIVE_KEY,
    MAIN_TRANSITION_ROUTE_KEY,
    OPENING_ROUTE_KEY,
    OPENING_STARTED_AT_KEY,
)
from src.ui.navigation import reveal_authenticated_page_body
from src.pages.home_workspace import (
    SECONDARY_UPDATE_BANNER,
    apply_saved_analysis_result,
    render_secondary_update_banner,
)
from src.pages.saved_analysis_control import (
    MANAGE_SAVED_ANALYSES,
    should_render_saved_analysis_control,
)
from src.services.account_scope import (
    bind_authenticated_account,
    first_page_plan_decision,
)


ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _dashboard_source() -> str:
    runtime = _source("src/authenticated_runtime.py")
    return runtime.split('if app_mode == "Dashboard":', 1)[1].split(
        'if app_mode == "Analysis Details":', 1
    )[0]


def _analysis_source() -> str:
    runtime = _source("src/authenticated_runtime.py")
    return runtime.split('if app_mode == "Analysis Details":', 1)[1].split(
        'if app_mode == "Monitoring":', 1
    )[0]


def test_nonessential_hang_does_not_consume_first_page_budget():
    begin_first_page_budget(0.6)

    def hang():
        time.sleep(2)
        return "late"

    started = time.perf_counter()
    value, status = run_with_read_budget(
        hang, budget_seconds=0.2, respect_first_page=False
    )
    essential, essential_status = run_with_read_budget(lambda: "saved", budget_seconds=8)
    elapsed = time.perf_counter() - started
    end_first_page_budget()
    assert value is None and status == "timeout"
    assert essential == "saved" and essential_status == "ok"
    assert elapsed < 1.2


def test_shared_first_page_budget_does_not_stack_hangs():
    begin_first_page_budget(0.35)
    try:
        def hang():
            time.sleep(3)
            return "late"

        started = time.perf_counter()
        first, first_status = run_with_read_budget(hang, budget_seconds=8)
        second, second_status = run_with_read_budget(hang, budget_seconds=8)
        elapsed = time.perf_counter() - started
    finally:
        end_first_page_budget()
    assert first is None and first_status == "timeout"
    assert second is None and second_status == "timeout"
    assert elapsed < 1.5


def test_switched_account_sign_in_cannot_reuse_prior_pending_state():
    session = {
        "cadivor_scoped_user_id": "user-a",
        "cadivor_home_saved_analyses": {
            "user_id": "user-a",
            "rows": [{"id": "old-bom", "user_id": "user-a", "project_name": "Old"}],
        },
        "cadivor_route": "Analysis Details",
        "app_mode": "Analysis Details",
        "cadivor_active_analysis_id": "old-bom",
        "cadivor_secondary_data_delayed": True,
        "cadivor_shell_cache": {"full_name": "Prior User", "plan_name": "Professional"},
        "cadivor_resolved_plan_name": "Professional",
        "active_workspace_id": "ws-a",
    }
    assert bind_authenticated_account(session, "user-b") is True
    assert session["cadivor_route"] == "Dashboard"
    assert session["cadivor_scoped_user_id"] == "user-b"
    assert "cadivor_home_saved_analyses" not in session
    assert "cadivor_active_analysis_id" not in session
    assert "cadivor_secondary_data_delayed" not in session
    assert "cadivor_shell_cache" not in session
    assert "cadivor_resolved_plan_name" not in session
    kept = apply_saved_analysis_result(
        session, user_id="user-b", rows=[{"id": "old-bom", "user_id": "user-a"}], status="timeout"
    )
    assert kept is None
    plan, persist, announce = first_page_plan_decision(
        unresolved=True,
        resolved_name="Subscription inactive",
        trial_expired=True,
        cached_name=str(session.get("cadivor_resolved_plan_name") or ""),
    )
    assert persist is False
    assert announce is False
    assert plan != "Professional"


def _hang_past_budget():
    time.sleep(FIRST_PAGE_BUDGET_SECONDS + 2)
    return "late"


def _arm_opening_dashboard(session: dict) -> None:
    session[DELAY_ROUTE_BODY_REVEAL_KEY] = True
    session[MAIN_TRANSITION_ACTIVE_KEY] = True
    session[MAIN_TRANSITION_ROUTE_KEY] = "Dashboard"
    session[OPENING_ROUTE_KEY] = "Dashboard"
    session[OPENING_STARTED_AT_KEY] = time.perf_counter()
    session["cadivor_route"] = "Dashboard"
    session["app_mode"] = "Dashboard"


def _reveal_home_after_bounded_hang(session: dict, monkeypatch) -> float:
    """Run a hanging workspace read, then the production Home reveal.

    Dashboard reveals the heading before the secondary read. The hang uses the
    same shared deadline, so Opening cannot stay up past that budget.
    """
    monkeypatch.setattr("src.ui.main_transition.st.session_state", session)
    monkeypatch.setattr("src.ui.main_transition.st.markdown", lambda *_args, **_kwargs: None)
    begin_first_page_budget(0.35)
    started = time.perf_counter()
    try:
        workspace, workspace_status = run_with_read_budget(_hang_past_budget, budget_seconds=8)
        secondary, secondary_status = run_with_read_budget(_hang_past_budget, budget_seconds=8)
        reveal_authenticated_page_body("Dashboard")
        elapsed = time.perf_counter() - started
    finally:
        end_first_page_budget()
    assert workspace is None and workspace_status == "timeout"
    assert secondary is None and secondary_status == "timeout"
    assert elapsed < 0.8
    assert session.get(DELAY_ROUTE_BODY_REVEAL_KEY) is None
    assert session.get(MAIN_TRANSITION_ACTIVE_KEY) is False
    assert session.get(OPENING_ROUTE_KEY) is None
    assert session.get("cadivor_presented_route") == "Dashboard"
    dashboard = _dashboard_source()
    heading_at = dashboard.index("render_dashboard_page_heading()")
    reveal_at = dashboard.index('reveal_authenticated_page_body("Dashboard")')
    secondary_at = dashboard.index("run_with_read_budget(_load_dashboard_secondary)")
    assert heading_at < reveal_at < secondary_at
    assert "Opening Dashboard" not in dashboard[heading_at:reveal_at]
    return elapsed


def test_fresh_sign_in_hanging_workspace_read_reveals_home_within_budget(monkeypatch):
    """A fresh sign-in must leave Opening Dashboard when a workspace read hangs."""
    assert FIRST_PAGE_BUDGET_SECONDS == 8.0
    session: dict = {}
    assert bind_authenticated_account(session, "user-fresh") is False
    _arm_opening_dashboard(session)
    _reveal_home_after_bounded_hang(session, monkeypatch)
    runtime = _source("src/authenticated_runtime.py")
    budget_at = runtime.index("begin_first_page_budget()")
    assert budget_at < runtime.index("run_with_read_budget(load_user_data)")
    assert runtime.index("def _bounded_boot_read") < runtime.index("runtime.workspace_init")


def test_switched_account_hanging_workspace_read_reveals_home_within_budget(monkeypatch):
    """The next account must get Home within budget, with none of the prior user's state."""
    session = {
        "cadivor_scoped_user_id": "user-a",
        "cadivor_route": "Analysis Details",
        "app_mode": "Analysis Details",
        "cadivor_active_analysis_id": "prior-bom",
        "analysis_id": "prior-bom",
        "cadivor_selected_component_mpn": "PRIOR-MPN",
        "cadivor_selected_component_analysis_id": "prior-bom",
        "cadivor_review_mpn": "PRIOR-MPN",
        "analysis_component_selector_prior-bom": "PRIOR-MPN — Capacitor",
        "cv3424_selected_component_prior-bom": "prior-bom:prior-mpn",
        "cadivor_secondary_data_delayed": True,
        "cadivor_home_saved_analyses": {
            "user_id": "user-a",
            "rows": [{"id": "prior-bom", "user_id": "user-a", "project_name": "Prior BOM"}],
        },
        "bom81_saved_manager": "placeholder",
        "bom81_manager_search": "prior",
    }
    assert bind_authenticated_account(session, "user-b") is True
    assert session["cadivor_scoped_user_id"] == "user-b"
    assert session["cadivor_route"] == "Dashboard"
    assert session["app_mode"] == "Dashboard"
    for key in (
        "cadivor_active_analysis_id",
        "analysis_id",
        "cadivor_selected_component_mpn",
        "cadivor_selected_component_analysis_id",
        "cadivor_review_mpn",
        "analysis_component_selector_prior-bom",
        "cv3424_selected_component_prior-bom",
        "cadivor_secondary_data_delayed",
        "cadivor_home_saved_analyses",
        "bom81_saved_manager",
        "bom81_manager_search",
    ):
        assert key not in session
    leftover = [{"id": "prior-bom", "user_id": "user-a", "project_name": "Prior BOM"}]
    assert should_render_saved_analysis_control(leftover, route="Dashboard", status="timeout") is False
    assert should_render_saved_analysis_control(leftover, route="Analysis Details", status="ok") is False
    kept = apply_saved_analysis_result(
        session, user_id="user-b", rows=leftover, status="timeout"
    )
    assert kept is None
    _arm_opening_dashboard(session)
    _reveal_home_after_bounded_hang(session, monkeypatch)
    assert session["cadivor_scoped_user_id"] == "user-b"
    assert "cadivor_selected_component_mpn" not in session
    assert "cadivor_active_analysis_id" not in session


def test_fresh_sign_in_timeout_fail_opens_without_persisting_plan():
    session = {}
    assert bind_authenticated_account(session, "user-fresh") is False
    missing = apply_saved_analysis_result(
        session, user_id="user-fresh", rows=None, status="timeout"
    )
    assert missing is None
    _plan, persist, announce = first_page_plan_decision(
        unresolved=True,
        resolved_name="Subscription inactive",
        trial_expired=True,
        cached_name="",
    )
    assert persist is False
    assert announce is False
    runtime = _source("src/authenticated_runtime.py")
    budget_at = runtime.index("begin_first_page_budget()")
    load_at = runtime.index("run_with_read_budget(load_user_data)")
    assert budget_at < load_at
    assert "respect_first_page=False" in runtime[budget_at:runtime.index("def _load_saved_analyses")]
    assert runtime.index("def _bounded_boot_read") < runtime.index("runtime.workspace_init")
    dashboard = _dashboard_source()
    assert 'reveal_authenticated_page_body("Dashboard")' in dashboard
    assert dashboard.index("release_saved_analysis_placeholder()") < dashboard.index(
        'reveal_authenticated_page_body("Dashboard")'
    )


def test_retry_updates_replays_leave_one_banner(monkeypatch):
    notices: list[str] = []
    buttons: list[str] = []
    clears: list[str] = []
    state: dict = {"cadivor_secondary_data_delayed": True}

    class _Slot:
        def empty(self):
            clears.append("slot")
            notices.clear()
            buttons.clear()

        def container(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Session(dict):
        def pop(self, key, default=None):
            return dict.pop(self, key, default)

    session = _Session(state)

    monkeypatch.setattr("src.pages.home_workspace.st.session_state", session)
    monkeypatch.setattr("src.pages.home_workspace.st.empty", lambda: _Slot())
    monkeypatch.setattr(
        "src.pages.home_workspace.st.markdown",
        lambda text, **_kwargs: notices.append(text),
    )
    monkeypatch.setattr(
        "src.pages.home_workspace.st.button",
        lambda label, **_kwargs: buttons.append(label) or False,
    )
    monkeypatch.setattr("src.pages.home_workspace.st.rerun", lambda: None)
    monkeypatch.setattr("src.pages.home_workspace.st.container", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("keyed container would append")))

    for _ in range(3):
        render_secondary_update_banner()

    banner_hits = [item for item in notices if SECONDARY_UPDATE_BANNER in item]
    assert len(banner_hits) == 1
    assert buttons.count("Retry updates") == 1
    assert clears
    assert "st.container(key=\"cv_home_retry\")" not in _source("src/pages/home_workspace.py")


def test_same_user_timeout_keeps_selected_bom_and_part():
    """Slow data, retry, and a same-user rerun must not drop the open BOM or part.

    An account switch still drops the prior user's selection. That is not a
    placeholder and must not leak into the next account.
    """
    session = {
        "cadivor_scoped_user_id": "user-1",
        "cadivor_active_analysis_id": "bom-1",
        "analysis_id": "bom-1",
        "cadivor_selected_component_mpn": "MAX32625ITK+",
        "cadivor_selected_component_analysis_id": "bom-1",
    }
    assert bind_authenticated_account(session, "user-1") is False
    apply_saved_analysis_result(session, user_id="user-1", rows=None, status="timeout")
    assert session["cadivor_active_analysis_id"] == "bom-1"
    assert session["analysis_id"] == "bom-1"
    assert session["cadivor_selected_component_mpn"] == "MAX32625ITK+"
    home = _source("src/pages/home_workspace.py")
    retry = home.split("def render_secondary_update_banner", 1)[1].split(
        "def render_saved_boms_unavailable", 1
    )[0]
    assert "cadivor_active_analysis_id" not in retry
    assert "cadivor_selected_component_mpn" not in retry
    switched = dict(session)
    assert bind_authenticated_account(switched, "user-2") is True
    assert "cadivor_active_analysis_id" not in switched


def test_saved_bom_page_has_no_generic_open_button():
    """Command-palette Open anchors must not lead the saved-BOM page."""
    runtime = _source("src/authenticated_runtime.py")
    call_at = runtime.index("render_command_nav_triggers(")
    guard = runtime[call_at - 280:call_at]
    assert 'app_mode != "Analysis Details"' in guard
    detail = _source("src/pages/analysis_detail.py")
    assert 'st.button("Open"' not in detail
    assert "internal_nav_button(\n            \"Open\"" not in detail
    assert 'class="cv-native-nav-button' not in detail
    bom = runtime.split('if app_mode == "BOM Analyzer":', 1)[1]
    assert "Open Selected Analysis" in bom
    nav = detail.split("def _render_analysis_section_navigation", 1)[1].split("def _num", 1)[0]
    assert nav.count("st.container(key=\"cv_analysis_section_nav\")") == 1
    header_at = detail.index('class="cv-analysis-header"')
    leading = detail[detail.index("def render_analysis_detail"):header_at]
    assert "st.html(" not in leading
    assert "cvcc-nav-triggers" not in leading


def test_failed_workspace_read_does_not_render_empty_saved_analysis_rows():
    rows = [{"id": "bom-1", "user_id": "user-1"}]
    assert should_render_saved_analysis_control(rows, route="Dashboard", status="timeout") is False
    assert should_render_saved_analysis_control(rows, route="Analysis Details", status="ok") is False
    assert should_render_saved_analysis_control([], route="BOM Analyzer", status="ok") is False
    assert should_render_saved_analysis_control(None, route="BOM Analyzer", status="error") is False
    assert should_render_saved_analysis_control(rows, route="BOM Analyzer", status="ok") is True

    dashboard = _dashboard_source()
    analysis = _analysis_source()
    detail = _source("src/pages/analysis_detail.py")
    assert MANAGE_SAVED_ANALYSES not in dashboard
    assert MANAGE_SAVED_ANALYSES not in analysis
    assert MANAGE_SAVED_ANALYSES not in detail
    runtime = _source("src/authenticated_runtime.py")
    assert runtime.index("bind_authenticated_account(") < runtime.index("begin_first_page_budget()")
    bom = runtime.split('if app_mode == "BOM Analyzer":', 1)[1]
    label_at = bom.rindex("MANAGE_SAVED_ANALYSES")
    guard_at = bom.rfind("should_render_saved_analysis_control", 0, label_at)
    assert guard_at > 0
    assert "No saved analyses yet" not in bom[guard_at:label_at + 800]

    header_at = detail.index('class="cv-analysis-header"')
    back_at = detail.index('st.button("Back to BOMs"', header_at)
    between = detail[header_at:back_at]
    assert "release_saved_analysis_placeholder()" in between
    reveal_at = between.index('reveal_authenticated_page_body("Analysis Details")')
    assert between.index("release_saved_analysis_placeholder()") < reveal_at
    assert between.count('st.button("Back to BOMs"') == 0
    assert detail.count('st.container(key="cv_analysis_hero_actions")') == 1
    assert detail.count('st.container(key="cv_analysis_section_nav")') == 1
    saved_loader = dashboard.split("def _load_saved_analyses", 1)[1].split(
        "overview_analyses = apply_saved_analysis_result", 1
    )[0]
    assert "_workspace_query(" not in saved_loader
    secondary = dashboard.split("def _load_dashboard_secondary", 1)[1].split(
        "return (", 1
    )[0]
    assert "_workspace_query(" not in secondary
    assert 'popover("More ▾")' in detail
    assert 'selectbox(\n            "More"' not in detail.split("else:", 1)[-1] or "popover" in detail
    nav = detail.split("def _render_analysis_section_navigation", 1)[1].split("def _num", 1)[0]
    assert nav.index('popover("More ▾")') < nav.index("selectbox(")
    assert "st.pills" not in nav
    css = _source("src/assets/css/analysis_detail_v2.css")
    assert "border-bottom: 2px solid transparent" in css
    assert "flex-wrap: nowrap !important" in css
    assert "overflow-x: auto !important" in css
    assert "white-space: nowrap !important" in css
    assert "st-key-cv_analysis_section_nav [data-testid=\"stSelectbox\"]" in css
