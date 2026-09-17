"""Reliability and navigation package: reveal order, budgets, and saved-BOM IA."""

from __future__ import annotations

import inspect
import time
from pathlib import Path

from src.boot_read_budget import run_with_read_budget
from src.ui.bom_navigation import (
    MORE_MENU,
    PRIMARY_AREAS,
    former_destinations_covered,
    primary_review_action,
)
from src.ui.main_transition import DELAY_ROUTE_BODY_REVEAL_KEY, MAIN_TRANSITION_ACTIVE_KEY
from src.ui.navigation import (
    navigate_to,
    open_high_risk_component_review,
    open_component_in_saved_bom,
    open_saved_bom,
    return_to_saved_bom_list,
)
from src.ui.unified_shell import NAV_GROUPS, _open_plan_and_billing


ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_dashboard_and_pricing_reveal_before_secondary_reads():
    runtime = _source("src/authenticated_runtime.py")
    dashboard = runtime.split('if app_mode == "Dashboard":', 1)[1].split(
        'if app_mode == "Analysis Details":', 1
    )[0]
    reveal = dashboard.index('reveal_authenticated_page_body("Dashboard")')
    secondary = dashboard.index("def _load_dashboard_secondary")
    commands = dashboard.index("build_workspace_commands(")
    assert reveal < secondary
    assert reveal < commands
    assert 'select("*")' not in dashboard
    assert "select('*')" not in dashboard

    pricing = runtime.split('if app_mode == "Pricing":', 1)[1].split(
        'if app_mode == "Admin Console":', 1
    )[0]
    reveal = pricing.index('reveal_authenticated_page_body("Pricing")')
    cards = pricing.index('<span class="cv311-card"></span>')
    assert reveal < cards
    assert pricing.index("build_workspace_commands(") > reveal


def test_delayed_secondary_read_cannot_hold_past_budget():
    def slow():
        time.sleep(5)
        return "late"

    started = time.perf_counter()
    value, status = run_with_read_budget(slow, budget_seconds=0.2)
    elapsed = time.perf_counter() - started
    assert status == "timeout"
    assert value is None
    assert elapsed < 2.0


def test_pricing_navigation_does_not_use_hard_query_or_force_opening(monkeypatch):
    state: dict = {}
    monkeypatch.setattr("src.ui.navigation.st.session_state", state)
    monkeypatch.setattr("src.ui.navigation.st.rerun", lambda: None)
    monkeypatch.setattr("src.ui.navigation.st.query_params", type("Q", (), {"from_dict": lambda *_a, **_k: None})())
    navigate_to("Pricing", arm_opening=False, _rerun=False)
    assert state["app_mode"] == "Pricing"
    assert DELAY_ROUTE_BODY_REVEAL_KEY not in state
    assert MAIN_TRANSITION_ACTIVE_KEY not in state
    live = "\n".join(
        _source(path)
        for path in (
            "src/components/upgrade_prompt.py",
            "src/components/engineering_assistant.py",
            "src/ui/framework.py",
            "src/ui/unified_shell.py",
        )
    )
    assert "?page=Pricing" not in live


def test_plan_label_does_not_rerun_while_opening_is_armed():
    runtime = _source("src/authenticated_runtime.py")
    window = runtime.split("_opening_armed = bool", 1)[1][:800]
    assert "not _opening_armed" in window
    assert "st.rerun()" in window
    assert "DELAY_ROUTE_BODY_REVEAL_KEY" in runtime[runtime.index("_opening_armed = bool") - 400:runtime.index("_opening_armed = bool") + 200]


def test_back_to_boms_opens_list_without_clearing_or_auto_resume(monkeypatch):
    detail = _source("src/pages/analysis_detail.py")
    runtime = _source("src/authenticated_runtime.py")
    helper = _source("src/ui/navigation.py").split("def return_to_saved_bom_list", 1)[1].split("\ndef ", 1)[0]
    assert 'st.button("Back to BOMs"' in detail
    assert "return_to_saved_bom_list" in detail
    assert "new_analysis" not in detail
    assert "show_saved_analyses" in helper
    assert "cadivor_active_analysis_id" in helper
    assert "SHOW_SAVED_BOMS_KEY" in helper
    assert "PRESELECT_SAVED_BOM_KEY" in helper
    assert 'SHOW_SAVED_BOMS_KEY = "cadivor_show_saved_boms"' in _source("src/ui/navigation.py")
    assert "new_analysis" not in helper
    resume = runtime.split("_resume_analysis_id = _safe_text(", 1)[1].split("st.markdown(", 1)[0]
    assert "cadivor_show_saved_boms" in resume
    assert "not _show_saved_analyses" in resume
    editor = runtime.split('preselect_id = str(', 1)[1].split("edited_manager = st.data_editor", 1)[0]
    assert 'editor_df.loc[match, "Select"] = True' in editor
    assert "bom81_selected_analysis_ids" in editor
    assert "cadivor_preselect_saved_bom_id" in editor
    status = runtime.split("selected_project = \"\"", 1)[1].split("st.markdown(", 1)[0]
    assert "Selected: {selected_project}" in status

    recorded: dict = {}
    state = {
        "cadivor_route": "Analysis Details",
        "cadivor_active_analysis_id": "saved-bom-42",
        "analysis_id": "saved-bom-42",
        "cadivor_active_analysis_tab": "Components",
    }

    class _Params:
        def from_dict(self, payload):
            recorded["params"] = dict(payload)

        def __contains__(self, key):
            return False

    monkeypatch.setattr("src.ui.navigation.st.session_state", state)
    monkeypatch.setattr("src.ui.navigation.st.rerun", lambda: recorded.setdefault("reran", True))
    monkeypatch.setattr("src.ui.navigation.st.query_params", _Params())
    return_to_saved_bom_list(_rerun=False, arm_opening=False)
    assert state["app_mode"] == "BOM Analyzer"
    assert state["cadivor_active_analysis_id"] == "saved-bom-42"
    assert state["analysis_id"] == "saved-bom-42"
    assert state["cadivor_active_analysis_tab"] == "Components"
    assert state["cadivor_show_saved_boms"] is True
    assert state["cadivor_preselect_saved_bom_id"] == "saved-bom-42"
    assert state["bom81_selected_analysis_ids"] == ["saved-bom-42"]
    assert recorded["params"]["show_saved_analyses"] == "1"
    assert "new_analysis" not in recorded["params"]
    assert DELAY_ROUTE_BODY_REVEAL_KEY not in state

    open_saved_bom("saved-bom-42", _rerun=False, arm_opening=False)
    assert "cadivor_show_saved_boms" not in state
    assert state["app_mode"] == "Analysis Details"
    assert state["cadivor_active_analysis_id"] == "saved-bom-42"
    assert state["cadivor_active_analysis_tab"] == "Components"


def test_former_analysis_destinations_remain_reachable():
    covered = former_destinations_covered()
    assert covered["Engineering Intelligence"] == "Engineering Decision Brief"
    assert covered["Components"] == "Parts & Risk"
    assert covered["Alternatives"] == "Replacement Intelligence"
    assert covered["Ask Cadivor"] == "Ask Cadivor"
    assert covered["Datasheet Q&A"] == "Decision Tools · Datasheet Q&A"
    assert covered["Monitor Components"] == "More · Watch this BOM"
    assert all(covered.values())
    assert PRIMARY_AREAS == (
        "Engineering Decision Brief",
        "Parts & Risk",
        "Replacement Intelligence",
        "Engineering Decisions",
        "Ask Cadivor",
    )
    assert "Ask Cadivor" not in MORE_MENU
    assert set(MORE_MENU) == {
        "Discussion",
        "History",
        "Report",
        "Watch this BOM",
        "Datasheet Q&A",
        "Compare parts",
        "Design Impact",
    }


def test_primary_action_uses_ranked_part_or_safe_fallback():
    ranked = primary_review_action(
        [{"mpn": "MAX32625ITK+", "risk_score": 90}],
        replacement_chosen=False,
        review_queue_clear=False,
    )
    assert ranked["label"] == "Review MAX32625ITK+"
    assert ranked["kind"] == "review_part"
    fallback = primary_review_action(
        [],
        replacement_chosen=False,
        review_queue_clear=False,
    )
    assert fallback["label"] == "Review parts"
    unnamed = primary_review_action(
        [{"mpn": "Unknown MPN", "risk_score": 10}],
    )
    assert unnamed["label"] == "Review highest-risk part"
    ready = primary_review_action(
        [{"mpn": "MAX32625ITK+", "risk_score": 90}],
        selected_mpn="MAX32625ITK+",
        replacement_chosen=True,
        review_queue_clear=False,
    )
    assert ready["kind"] == "decision"
    report = primary_review_action(
        [],
        review_queue_clear=True,
    )
    assert report["kind"] == "report"


def test_primary_rail_keeps_specialist_tools():
    labels = [(group, [item[0] for item in items]) for group, items in NAV_GROUPS]
    assert labels[0][0] == ""
    assert labels[0][1] == [
        "Home",
        "BOMs",
        "Engineering Decisions",
        "Alerts & Monitoring",
        "Reports",
    ]
    assert labels[1][0] == "Decision Tools"
    assert set(labels[1][1]) == {
        "Find a replacement",
        "Compare parts",
        "Datasheet Q&A",
        "Design Impact",
        "Procurement Advisor",
        "Cost Optimization",
        "Supply Scenario",
        "Portfolio Intelligence",
    }


def test_plan_and_billing_opens_settings_billing_without_opening(monkeypatch):
    state: dict = {}

    class _Streamlit:
        session_state = state

        @staticmethod
        def button(*_args, **_kwargs):
            return False

    monkeypatch.setattr("src.ui.unified_shell.st", _Streamlit)
    monkeypatch.setattr("src.ui.navigation.st.session_state", state)
    monkeypatch.setattr("src.ui.navigation.st.rerun", lambda: None)
    monkeypatch.setattr("src.ui.navigation.st.query_params", type("Q", (), {"from_dict": lambda *_a, **_k: None})())
    _open_plan_and_billing()
    assert inspect.signature(navigate_to).parameters["arm_opening"].default is True
    assert state["app_mode"] == "Settings"
    assert state["settings_active_tab"] == "Billing"
    assert DELAY_ROUTE_BODY_REVEAL_KEY not in state


def test_home_saved_bom_open_does_not_force_query_route_reload(monkeypatch):
    living = _source("src/living_workspace.py")
    table = living.split("def render_portfolio_project_summaries", 1)[1].split("\ndef ", 1)[0]
    helper = _source("src/ui/navigation.py").split("def open_saved_bom", 1)[1].split("\ndef ", 1)[0]
    assert "?page=Analysis" not in table
    assert 'href="' not in table
    assert "open_saved_bom" in table
    assert 'st.button(\n            f"Open Project · {label}"' in table or "Open Project ·" in table
    assert "cadivor_active_analysis_id" in helper
    assert "new_analysis" not in helper

    recorded: dict = {}
    state: dict = {}

    class _Params:
        def from_dict(self, payload):
            recorded["params"] = dict(payload)

        def __contains__(self, key):
            return False

    monkeypatch.setattr("src.ui.navigation.st.session_state", state)
    monkeypatch.setattr("src.ui.navigation.st.rerun", lambda: recorded.setdefault("reran", True))
    monkeypatch.setattr("src.ui.navigation.st.query_params", _Params())
    open_saved_bom("saved-bom-42", _rerun=False, arm_opening=False)
    assert state["cadivor_active_analysis_id"] == "saved-bom-42"
    assert state["analysis_id"] == "saved-bom-42"
    assert state["app_mode"] == "Analysis Details"
    assert recorded["params"] == {"page": "Analysis Details", "analysis_id": "saved-bom-42"}
    assert "new_analysis" not in state
    assert DELAY_ROUTE_BODY_REVEAL_KEY not in state
    assert MAIN_TRANSITION_ACTIVE_KEY not in state
    assert "reran" not in recorded



def test_high_risk_component_opens_exact_saved_bom_component(monkeypatch):
    recorded: dict = {}
    state: dict = {"cadivor_route": "BOM Analyzer"}

    class _Params:
        def from_dict(self, payload):
            recorded["params"] = dict(payload)

        def __contains__(self, key):
            return False

    monkeypatch.setattr("src.ui.navigation.st.session_state", state)
    monkeypatch.setattr("src.ui.navigation.st.rerun", lambda: recorded.setdefault("reran", True))
    monkeypatch.setattr("src.ui.navigation.st.query_params", _Params())

    open_component_in_saved_bom(
        "saved-bom-42",
        "MCP2551-I/SN",
        _rerun=False,
        arm_opening=False,
    )

    assert state["app_mode"] == "Analysis Details"
    assert state["cadivor_active_analysis_id"] == "saved-bom-42"
    assert state["analysis_id"] == "saved-bom-42"
    assert state["cadivor_active_analysis_tab"] == "Components"
    assert state["cadivor_pending_analysis_section"] == "Components"
    assert state["cadivor_pending_analysis_section_id"] == "saved-bom-42"
    assert recorded["params"] == {
        "page": "Analysis Details",
        "analysis_id": "saved-bom-42",
        "tab": "components",
        "component": "MCP2551-I/SN",
        "focus": "component-risk",
    }
    assert "cadivor_show_saved_boms" not in state

def test_high_risk_component_review_stays_in_session(monkeypatch):
    runtime = _source("src/authenticated_runtime.py")
    card = runtime.split('label="High-risk findings"', 1)[1].split("MetricCard(", 1)[0]
    assert "href=" not in card
    assert "?page=" not in card
    assert "open_high_risk_component_review(arm_opening=False)" in runtime
    helper = _source("src/ui/navigation.py").split("def open_high_risk_component_review", 1)[1].split("\ndef ", 1)[0]
    assert "bom81_high_risk_review" in helper
    assert "new_analysis" not in helper
    assert 'navigate_to(\n        "BOM Analyzer"' in helper
    resume = runtime.split("_resume_analysis_id = _safe_text(", 1)[1].split("st.markdown(", 1)[0]
    assert "bom81_high_risk_review" in resume

    recorded: dict = {}
    state = {
        "cadivor_route": "BOM Analyzer",
        "cadivor_active_analysis_id": "saved-bom-42",
        "analysis_id": "saved-bom-42",
        "cadivor_active_analysis_tab": "Components",
        "cadivor_show_saved_boms": True,
        "cadivor_preselect_saved_bom_id": "saved-bom-42",
        "bom81_selected_analysis_ids": ["saved-bom-42"],
    }

    class _Params:
        def from_dict(self, payload):
            recorded["params"] = dict(payload)

        def __contains__(self, key):
            return False

    monkeypatch.setattr("src.ui.navigation.st.session_state", state)
    monkeypatch.setattr("src.ui.navigation.st.rerun", lambda: recorded.setdefault("reran", True))
    monkeypatch.setattr("src.ui.navigation.st.query_params", _Params())
    open_high_risk_component_review(_rerun=False, arm_opening=False)
    assert state["bom81_high_risk_review"] is True
    assert state["cadivor_show_saved_boms"] is True
    assert state["cadivor_active_analysis_id"] == "saved-bom-42"
    assert state["analysis_id"] == "saved-bom-42"
    assert state["cadivor_active_analysis_tab"] == "Components"
    assert state["cadivor_preselect_saved_bom_id"] == "saved-bom-42"
    assert state["bom81_selected_analysis_ids"] == ["saved-bom-42"]
    assert state["app_mode"] == "BOM Analyzer"
    assert recorded["params"]["page"] == "BOM Analyzer"
    assert recorded["params"]["analysis_id"] == "saved-bom-42"
    assert recorded["params"]["show_saved_analyses"] == "1"
    assert "new_analysis" not in recorded["params"]
    assert "high_risk_review" not in recorded["params"]
    assert DELAY_ROUTE_BODY_REVEAL_KEY not in state
    assert MAIN_TRANSITION_ACTIVE_KEY not in state


def test_dashboard_workspace_navigation_does_not_force_query_route_reload():
    source = _source("src/pages/dashboard_workspaces.py")
    runtime = _source("src/authenticated_runtime.py")
    assert "render_dashboard_workspace_navigation" not in source
    assert "dashboard_workspace=" not in source
    assert "?page=Analysis" not in source
    assert "open_saved_bom" in source
    window = runtime.split('dashboard_nav_key = "cv672_dashboard_workspace_radio"', 1)[1][:4000]
    assert "dashboard_workspace=" not in window
    assert "render_returning_home(" in window
    assert "Show analytics" not in window
    assert "Setup Progress" not in window
    assert "Preview onboarding" not in window


def test_remaining_package_navigation_does_not_use_hard_query_links():
    workspaces = _source("src/pages/dashboard_workspaces.py")
    onboarding = _source("src/components/onboarding.py")
    detail = _source("src/pages/analysis_detail.py")
    living = _source("src/living_workspace.py")
    assert "href=\"?page=" not in workspaces
    assert "?page=" not in workspaces
    assert "return_to_saved_bom_list" in workspaces
    assert 'navigate_to("Portfolio Intelligence"' in workspaces
    assert 'navigate_to("Monitoring"' in workspaces
    success = onboarding.split("def render_analysis_success", 1)[1]
    assert "?page=" not in success
    assert "open_saved_bom" in success
    assert 'navigate_to(\n                "Reports"' in success or 'navigate_to("Reports"' in success
    assert "href=\"?page=" not in detail
    assert "?page=" not in detail
    assert "?page=" not in living


def test_opening_reveal_is_always_logged(capsys):
    from src.performance_timing import log_opening_reveal

    log_opening_reveal("Dashboard", 42)
    captured = capsys.readouterr().out
    assert "CADIVOR_OPENING route=dashboard duration_ms=42.0" in captured
    assert "@" not in captured
