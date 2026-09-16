"""Home identity comes from saved BOMs, not a delayed secondary read."""
from __future__ import annotations

from pathlib import Path

from src.pages.home_workspace import (
    HOME_ATTENTION,
    HOME_CONTINUE,
    HOME_NEW,
    HOME_UNKNOWN,
    ONBOARDING_MESSAGES,
    RETRY_UPDATES_LABEL,
    SECONDARY_UPDATE_BANNER,
    apply_saved_analysis_result,
    build_home_model,
)


ROOT = Path(__file__).resolve().parents[1]


def _bom(**overrides):
    row = {
        "id": "bom-1",
        "user_id": "user-1",
        "project_name": "Industrial Controller BOM",
        "filename": "industrial-controller.csv",
        "total_parts": 3,
        "health_score": 42,
        "high_risk_count": 2,
        "created_at": "2026-09-01T12:00:00+00:00",
    }
    row.update(overrides)
    return row


def test_new_user_with_no_saved_boms_is_first_review_only():
    home = build_home_model(user_id="user-1", analyses=[], parts=[], secondary_failed=False)
    assert home["kind"] == HOME_NEW
    assert home["title"] == "Start your first BOM review"
    assert home["primary"]["label"] == "Upload a BOM"
    assert home["show_onboarding"] is True
    assert home["recent"] == []
    assert home["secondary_failed"] is False
    onboarding = (ROOT / "src/components/onboarding.py").read_text(encoding="utf-8")
    first_run = onboarding.split("def render_first_run_dashboard", 1)[1].split(
        "def render_activation_strip", 1
    )[0]
    assert "Upload a BOM" in first_run
    assert "A first review in four steps" in first_run
    for message in ONBOARDING_MESSAGES:
        assert message not in first_run


def test_returning_user_with_urgent_risk_reviews_highest_risk_mpn():
    parts = [
        {"mpn": "TPS54331D", "risk_level": "Medium", "risk_score": 40, "analysis_id": "bom-1"},
        {"mpn": "MAX32625ITK+", "risk_level": "High", "risk_score": 91, "analysis_id": "bom-1"},
        {"mpn": "OTHER-HIGH", "risk_level": "High", "risk_score": 70, "analysis_id": "bom-1"},
    ]
    home = build_home_model(user_id="user-1", analyses=[_bom()], parts=parts)
    assert home["kind"] == HOME_ATTENTION
    assert home["title"] == "What needs attention"
    assert home["primary"]["label"] == "Review MAX32625ITK+"
    assert home["primary"]["analysis_id"] == "bom-1"
    assert home["primary"]["bom_name"] == "Industrial Controller BOM"
    assert "engineering review" in home["primary"]["context"].lower()
    assert home["primary"]["action_label"] == "Review component"
    assert home["show_onboarding"] is False
    card = home["recent"][0]
    assert card["name"] == "Industrial Controller BOM"
    assert card["health"] == 42
    assert card["high_risk_count"] == 2
    assert card["updated"] == "Sep 01, 2026"
    assert "New BOM" in (ROOT / "src/pages/home_workspace.py").read_text(encoding="utf-8")
    for message in ONBOARDING_MESSAGES:
        assert message not in home["title"]
        assert message not in home["primary"]["label"]


def test_returning_user_without_urgent_risk_continues_most_recent_bom():
    older = _bom(
        id="bom-old",
        project_name="Older Board",
        high_risk_count=0,
        health_score=90,
        created_at="2026-08-01T00:00:00+00:00",
    )
    recent = _bom(
        id="bom-new",
        project_name="Sensor Board BOM",
        high_risk_count=0,
        health_score=88,
        created_at="2026-09-10T00:00:00+00:00",
    )
    home = build_home_model(
        user_id="user-1",
        analyses=[older, recent],
        parts=[{"mpn": "GRM188", "risk_level": "Low", "analysis_id": "bom-new"}],
    )
    assert home["kind"] == HOME_CONTINUE
    assert home["title"] == "Continue your engineering work"
    assert home["primary"]["label"] == "Open Sensor Board BOM"
    assert home["primary"]["analysis_id"] == "bom-new"
    assert home["primary"]["bom_name"] == "Sensor Board BOM"
    assert home["primary"]["action_label"] == "Open BOM"
    assert home["primary"]["context"] == "Open the latest saved engineering review."
    assert [card["name"] for card in home["recent"]] == ["Sensor Board BOM", "Older Board"]
    assert home["show_onboarding"] is False


def test_secondary_timeout_keeps_saved_boms_and_does_not_invent_a_part():
    cached = [_bom()]
    session = {}
    assert apply_saved_analysis_result(
        session, user_id="user-1", rows=cached, status="ok"
    ) == cached
    kept = apply_saved_analysis_result(
        session, user_id="user-1", rows=[], status="timeout"
    )
    assert kept == cached
    home = build_home_model(
        user_id="user-1",
        analyses=kept,
        parts=None,
        secondary_failed=True,
    )
    assert home["kind"] == HOME_ATTENTION
    assert home["title"] == "What needs attention"
    assert home["primary"]["label"] == "Open Industrial Controller BOM"
    assert "Review " not in home["primary"]["label"]
    assert "2 high-risk components need review" in home["primary"]["context"]
    assert "choose a component" in home["primary"]["context"]
    assert home["secondary_failed"] is True
    assert home["show_onboarding"] is False
    assert home["recent"][0]["name"] == "Industrial Controller BOM"
    assert SECONDARY_UPDATE_BANNER.startswith("We couldn’t refresh workspace updates.")
    assert RETRY_UPDATES_LABEL == "Refresh workspace updates"
    assert home["secondary_failed"] is True
    ordinary = build_home_model(
        user_id="user-1",
        analyses=cached,
        parts=[{"mpn": "MAX32625ITK+", "risk_level": "High", "risk_score": 91, "analysis_id": "bom-1"}],
        secondary_failed=False,
    )
    assert ordinary["secondary_failed"] is False
    assert ordinary["primary"]["label"] == "Review MAX32625ITK+"


def test_timeout_without_cache_is_not_a_new_user():
    session = {}
    missing = apply_saved_analysis_result(
        session, user_id="user-1", rows=None, status="timeout"
    )
    assert missing is None
    home = build_home_model(user_id="user-1", analyses=None, secondary_failed=True)
    assert home["kind"] == HOME_UNKNOWN
    assert home["show_onboarding"] is False
    assert home["title"] != "Start your first BOM review"


def test_other_users_boms_do_not_make_this_user_returning():
    home = build_home_model(
        user_id="user-1",
        analyses=[_bom(user_id="someone-else")],
        parts=[],
    )
    assert home["kind"] == HOME_NEW
    assert home["analyses"] == []


def test_paused_plan_does_not_change_saved_bom_identity():
    home = build_home_model(user_id="user-1", analyses=[_bom()], parts=[])
    assert home["kind"] == HOME_ATTENTION
    runtime = (ROOT / "src/authenticated_runtime.py").read_text(encoding="utf-8")
    returning = runtime.split('if workspace_category == "Engineering Overview":', 1)[1].split(
        'elif workspace_category == "Portfolio Intelligence":', 1
    )[0]
    assert "pause_new_analyses=pause_new" in returning
    assert "New analyses are paused." in returning
    assert "Your saved BOMs and reports are still available." in returning
    assert "render_first_run_dashboard(" not in returning
    assert "Open reports" in (ROOT / "src/pages/home_workspace.py").read_text(encoding="utf-8")
    dashboard = runtime.split('if app_mode == "Dashboard":', 1)[1].split(
        'if app_mode == "Analysis Details":', 1
    )[0]
    assert "Some details are still loading" not in dashboard
    assert "Try again" not in dashboard
    assert 'reveal_authenticated_page_body("Dashboard")' in dashboard
    new_user = dashboard.split('if home["kind"] == HOME_NEW', 1)[1].split(
        "dashboard_nav_key", 1
    )[0]
    assert "render_first_run_dashboard(" in new_user
    assert "Start your first BOM review" in new_user


RETURNING_CONTROLS = (
    "Show analytics",
    "Setup Progress",
    "Preview onboarding",
)


def _dashboard_source() -> str:
    return (ROOT / "src/authenticated_runtime.py").read_text(encoding="utf-8").split(
        'if app_mode == "Dashboard":', 1
    )[1].split('if app_mode == "Analysis Details":', 1)[0]


def _returning_home_source() -> str:
    dashboard = _dashboard_source()
    return dashboard.split('if workspace_category == "Engineering Overview":', 1)[1].split(
        'elif workspace_category == "Portfolio Intelligence":', 1
    )[0]


def test_returning_home_hides_analytics_and_onboarding_controls():
    returning = _returning_home_source()
    dashboard = _dashboard_source()
    for label in RETURNING_CONTROLS:
        assert label not in returning
        assert label not in dashboard
    assert "render_returning_home(" in returning
    assert "Retry updates" not in returning
    assert "Refresh workspace updates" not in returning
    home = (ROOT / "src/pages/home_workspace.py").read_text(encoding="utf-8")
    assert SECONDARY_UPDATE_BANNER in home
    assert RETRY_UPDATES_LABEL in home
    shell = (ROOT / "src/ui/unified_shell.py").read_text(encoding="utf-8")
    assert '("Portfolio Intelligence", "portfolio", "Portfolio Intelligence")' in shell


def test_every_returning_state_uses_the_control_free_home():
    states = (
        build_home_model(user_id="user-1", analyses=[_bom()], parts=[
            {"mpn": "MAX32625ITK+", "risk_level": "High", "risk_score": 91, "analysis_id": "bom-1"},
        ]),
        build_home_model(user_id="user-1", analyses=[_bom(high_risk_count=0, health_score=92)], parts=[]),
        build_home_model(user_id="user-1", analyses=[_bom()], parts=None, secondary_failed=True),
    )
    returning = _returning_home_source()
    for home in states:
        assert home["kind"] != HOME_NEW
        assert home["show_onboarding"] is False
    assert "pause_new_analyses=pause_new" in returning
    assert "PLAN_TRIAL_EXPIRED" in returning
    assert "PLAN_SUBSCRIPTION_INACTIVE" in returning
    for label in RETURNING_CONTROLS:
        assert label not in returning
    assert "New analyses are paused." in returning


def test_home_presentation_keeps_actions_and_adds_visual_hierarchy():
    home = (ROOT / "src/pages/home_workspace.py").read_text(encoding="utf-8")
    onboarding = (ROOT / "src/components/onboarding.py").read_text(encoding="utf-8")
    styles = (ROOT / "src/assets/css/dashboard_v2.css").read_text(encoding="utf-8")
    first_run = onboarding.split("def render_first_run_dashboard", 1)[1].split(
        "def render_activation_strip", 1
    )[0]
    assert "Next engineering action" in home
    assert "cv-home-chip" in home
    assert "cv-home-notice--inline" in home
    assert "cv-home-notice--caution" in styles
    assert "cv-home-notice--account" in home
    assert SECONDARY_UPDATE_BANNER in home
    assert 'key="home_retry_updates"' in home
    assert 'key="home_primary_action"' in home
    assert "A first review in four steps" in first_run
    assert "cv-home-step-num" in first_run
    assert 'key="ftue_upload_first_bom"' in first_run
    for token in (
        ".cv-home-notice--caution",
        ".cv-home-notice--account",
        ".st-key-cv_home_next",
        ".cv-home-chip--risk",
        ":focus-visible",
    ):
        assert token in styles
    home = build_home_model(user_id="user-1", analyses=[], parts=[])
    assert home["kind"] == HOME_NEW
    assert home["show_onboarding"] is True
    onboarding = (ROOT / "src/components/onboarding.py").read_text(encoding="utf-8")
    first_run = onboarding.split("def render_first_run_dashboard", 1)[1].split(
        "def render_activation_strip", 1
    )[0]
    assert "A first review in four steps" in first_run
    assert "Upload a BOM" in first_run
    dashboard = _dashboard_source()
    new_user = dashboard.split('if home["kind"] == HOME_NEW', 1)[1].split(
        "dashboard_nav_key", 1
    )[0]
    assert "render_first_run_dashboard(" in new_user
    for label in RETURNING_CONTROLS:
        assert label not in new_user
        assert label not in first_run
