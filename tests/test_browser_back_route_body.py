"""Browser Back/Forward history integrity and route-body ownership."""
from __future__ import annotations

import types
from pathlib import Path

import src.authenticated_runtime as runtime
import src.ui.navigation as navigation
from src.ui.route_body import (
    ROUTE_BODY_CM_STATE_KEY,
    ROUTE_BODY_HOST_STATE_KEY,
    claim_authenticated_route_body,
    enter_authenticated_route_body,
    exit_authenticated_route_body,
)

ROOT = Path(__file__).resolve().parents[1]


class _Session(dict):
    def pop(self, key, default=None):
        return dict.pop(self, key, default)


class _Query(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.writes = 0
        self.from_dict_calls = 0

    def get(self, key, default=""):
        return dict.get(self, key, default)

    def __setitem__(self, key, value):
        self.writes += 1
        dict.__setitem__(self, key, value)

    def __delitem__(self, key):
        self.writes += 1
        dict.__delitem__(self, key)

    def from_dict(self, mapping):
        self.writes += 1
        self.from_dict_calls += 1
        self.clear()
        self.update(mapping)


class _DelayedQuery(_Query):
    """Keep the server snapshot old to model Streamlit's callback timing."""

    def from_dict(self, mapping):
        self.writes += 1
        self.from_dict_calls += 1


class _Container:
    def __init__(self, key):
        self.key = key
        self.entered = 0
        self.exited = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *_exc):
        self.exited += 1
        return False


class _RouteBodyStreamlit:
    def __init__(self, session):
        self.session_state = session
        self.container_keys = []
        self.containers = []
        self.run_id = "run-1"

    def container(self, *, key):
        self.container_keys.append(key)
        container = _Container(key)
        self.containers.append(container)
        return container


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _patch_runtime(monkeypatch, session, query, consume=None):
    fake_st = types.SimpleNamespace(session_state=session, query_params=query, rerun=lambda: None)
    monkeypatch.setattr(runtime, "st", fake_st)
    monkeypatch.setattr(navigation, "st", fake_st)
    monkeypatch.setattr(
        runtime,
        "consume_browser_navigation_event",
        consume if consume is not None else (lambda: None),
    )
    return fake_st


def test_shell_and_runtime_share_one_body_host_without_rewriting_pages():
    runtime_src = _source("src/authenticated_runtime.py")
    assert "claim_authenticated_route_body(app_mode)" in runtime_src
    assert "enter_authenticated_route_body(app_mode)" in runtime_src
    assert runtime_src.index("render_unified_shell(") < runtime_src.index(
        "claim_authenticated_route_body(app_mode)"
    ) < runtime_src.index(
        "enter_authenticated_route_body(app_mode)"
    )
    assert "exit_authenticated_route_body()" in runtime_src
    shell_src = _source("src/ui/unified_shell.py")
    assert "claim_authenticated_route_body(current_page)" in shell_src
    assert shell_src.index("inject_unified_shell_css()") < shell_src.index(
        "claim_authenticated_route_body(current_page)"
    ) < shell_src.index('with st.container(key="cv_foundation_profile_trigger")')
    assert runtime_src.count("with authenticated_route_body(") == 0
    assert 'st.query_params["page"] = app_mode' not in runtime_src
    detail = _source("src/pages/analysis_detail.py")
    assert detail.count('st.button("Back to BOMs"') == 1
    assert 'key="analysis_back_to_boms"' in detail
    assert 'st.button("Back to BOMs"' not in _source("src/pages/reports.py")
    monitoring = runtime_src.split('if app_mode == "Monitoring":', 1)[1].split(
        'if app_mode == "Supply Risk Scenario":', 1
    )[0]
    reports = runtime_src.split('if app_mode == "Reports":', 1)[1].split(
        'if app_mode == "Pricing":', 1
    )[0]
    assert 'st.button("Back to BOMs"' not in monitoring
    assert 'st.button("Back to BOMs"' not in reports


def test_route_body_uses_one_keyed_container_and_does_not_leak_rerun_context(monkeypatch):
    session = _Session()
    fake_st = _RouteBodyStreamlit(session)
    monkeypatch.setattr("src.ui.route_body.st", fake_st)
    monkeypatch.setattr(
        "src.ui.route_body._current_script_run_id",
        lambda: fake_st.run_id,
    )

    claimed = claim_authenticated_route_body("Monitoring")
    first = claimed
    assert first.key == "cadivor_authenticated_route_body"
    assert fake_st.container_keys == ["cadivor_authenticated_route_body"]
    assert claim_authenticated_route_body("Monitoring") is first
    assert fake_st.container_keys == ["cadivor_authenticated_route_body"]
    # A second claim in the same script run must reuse the host even if the
    # route label changed after the shell painted its chrome.
    assert claim_authenticated_route_body("Engineering Decisions") is first
    assert fake_st.container_keys == ["cadivor_authenticated_route_body"]
    enter_authenticated_route_body("Monitoring")
    assert first.entered == 1
    assert session[ROUTE_BODY_HOST_STATE_KEY] is first
    assert session[ROUTE_BODY_CM_STATE_KEY] is not None

    # A Streamlit rerun abandons its old context. Do not let the next run pop
    # that old container from the new run's context stack.
    fake_st.run_id = "run-2"
    enter_authenticated_route_body("Monitoring")
    assert first.entered == 1
    assert first.exited == 0

    # A fresh keyed container is recreated at the same stable browser identity.
    claim_authenticated_route_body("Monitoring")
    second = session[ROUTE_BODY_HOST_STATE_KEY]
    assert second is not first
    assert second.key == first.key
    assert fake_st.container_keys == [first.key, second.key]
    enter_authenticated_route_body("Monitoring")
    assert second.entered == 1

    exit_authenticated_route_body()
    assert second.exited == 1
    assert ROUTE_BODY_CM_STATE_KEY not in session

    fake_st.run_id = "run-3"
    claim_authenticated_route_body("Reports")
    third = session[ROUTE_BODY_HOST_STATE_KEY]
    assert third.key == first.key
    assert len(fake_st.containers) == 3


def test_home_to_alerts_one_push_then_back_and_forward_zero_restore_pushes(monkeypatch):
    session = _Session(
        {
            "cadivor_route": "Dashboard",
            "app_mode": "Dashboard",
            "cadivor_nav_params": {"page": "Dashboard"},
            "user": types.SimpleNamespace(id="user-1"),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
        }
    )
    query = _Query({"page": "Dashboard"})
    _patch_runtime(monkeypatch, session, query)

    navigation.navigate_to("Monitoring", _rerun=False)
    assert query.from_dict_calls == 1
    assert query.writes == 1
    assert query.get("page") == "Monitoring"
    assert session["cadivor_last_history_push_params"] == {"page": "Monitoring"}
    assert session["cadivor_route"] == "Monitoring"
    assert session.get("access_token") == "live-a"

    # Follow-up authenticated run after the intentional push must not write again.
    writes_after_nav = query.writes
    assert runtime.resolve_canonical_app_route() == "Monitoring"
    assert query.writes == writes_after_nav

    # Browser already restored ?page=Dashboard before the bridge event arrives.
    query.clear()
    query.update({"page": "Dashboard"})
    query.writes = 0
    query.from_dict_calls = 0
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Dashboard",
            "reason": "popstate",
            "event_id": "back-1",
        }
    ]
    _patch_runtime(monkeypatch, session, query, consume=lambda: events.pop(0) if events else None)

    assert runtime.resolve_canonical_app_route() == "Dashboard"
    assert session["cadivor_route"] == "Dashboard"
    assert query.get("page") == "Dashboard"
    assert query.writes == 0
    assert query.from_dict_calls == 0
    assert session["access_token"] == "live-a"
    assert "user" in session

    # Forward restores Monitoring without pushing.
    query.clear()
    query.update({"page": "Monitoring"})
    query.writes = 0
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Monitoring",
            "reason": "popstate",
            "event_id": "forward-1",
        }
    ]
    _patch_runtime(monkeypatch, session, query, consume=lambda: events.pop(0) if events else None)
    assert runtime.resolve_canonical_app_route() == "Monitoring"
    assert query.writes == 0
    assert session["cadivor_route"] == "Monitoring"
    assert session["access_token"] == "live-a"


def test_one_time_report_purchase_is_a_distinct_restorable_route(monkeypatch):
    session = _Session({
        "cadivor_route": "Pricing", "app_mode": "Pricing",
        "cadivor_nav_params": {"page": "Pricing"},
        "user": types.SimpleNamespace(id="user-1"),
        "access_token": "live-a", "refresh_token": "live-r",
        "cadivor_auth_status": "authenticated",
    })
    query = _Query({"page": "Pricing"})
    _patch_runtime(monkeypatch, session, query)

    navigation.navigate_to("Single BOM Report", _rerun=False)
    assert query.get("page") == "Single BOM Report"
    assert runtime.resolve_canonical_app_route() == "Single BOM Report"

    query.clear()
    query.update({"page": "Pricing"})
    query.writes = 0
    events = [{
        "href": "http://127.0.0.1:8581/?page=Pricing",
        "reason": "popstate", "event_id": "purchase-back-1",
    }]
    _patch_runtime(monkeypatch, session, query, consume=lambda: events.pop(0) if events else None)
    assert runtime.resolve_canonical_app_route() == "Pricing"
    assert query.writes == 0
    assert session["access_token"] == "live-a"


def test_home_to_reports_back_once_stays_authenticated(monkeypatch):
    session = _Session(
        {
            "cadivor_route": "Dashboard",
            "app_mode": "Dashboard",
            "user": types.SimpleNamespace(id="user-1"),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
        }
    )
    query = _Query({"page": "Dashboard"})
    _patch_runtime(monkeypatch, session, query)

    navigation.navigate_to("Reports", _rerun=False)
    assert query.writes == 1

    query.clear()
    query.update({"page": "Dashboard"})
    query.writes = 0
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Dashboard",
            "reason": "popstate",
            "event_id": "reports-back",
        }
    ]
    _patch_runtime(monkeypatch, session, query, consume=lambda: events.pop(0) if events else None)
    assert runtime.resolve_canonical_app_route() == "Dashboard"
    assert query.writes == 0
    assert session.get("cadivor_auth_status") == "authenticated"
    assert session.get("cadivor_explicit_logout") is not True


def test_repeated_clicks_create_one_history_write_each_and_restore_pushes_zero(monkeypatch):
    session = _Session(
        {
            "cadivor_route": "Dashboard",
            "app_mode": "Dashboard",
            "user": types.SimpleNamespace(id="user-1"),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
        }
    )
    query = _Query({"page": "Dashboard"})
    _patch_runtime(monkeypatch, session, query)

    navigation.navigate_to("Monitoring", _rerun=False)
    navigation.navigate_to("Reports", _rerun=False)
    assert query.from_dict_calls == 2
    assert query.writes == 2

    # Back to Monitoring (browser already restored the URL).
    query.clear()
    query.update({"page": "Monitoring"})
    query.writes = 0
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Monitoring",
            "reason": "popstate",
            "event_id": "seq-back-1",
        }
    ]
    _patch_runtime(monkeypatch, session, query, consume=lambda: events.pop(0) if events else None)
    assert runtime.resolve_canonical_app_route() == "Monitoring"
    assert query.writes == 0

    # Back to Home.
    query.clear()
    query.update({"page": "Dashboard"})
    query.writes = 0
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Dashboard",
            "reason": "popstate",
            "event_id": "seq-back-2",
        }
    ]
    _patch_runtime(monkeypatch, session, query, consume=lambda: events.pop(0) if events else None)
    assert runtime.resolve_canonical_app_route() == "Dashboard"
    assert query.writes == 0
    assert session["access_token"] == "live-a"



def test_popstate_restore_survives_when_streamlit_query_snapshot_stays_stale(monkeypatch):
    """A browser restore must not bounce forward on the following rerun."""
    session = _Session(
        {
            "cadivor_route": "Reports",
            "app_mode": "Reports",
            "cadivor_nav_params": {"page": "Reports"},
            "user": types.SimpleNamespace(id="user-1"),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
        }
    )
    # Streamlit can keep its backend query snapshot on the route being left,
    # even though Chrome's address bar has already moved back to Dashboard.
    query = _Query({"page": "Reports"})
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Dashboard",
            "reason": "popstate",
            "event_id": "stale-query-back-1",
        }
    ]
    _patch_runtime(
        monkeypatch,
        session,
        query,
        consume=lambda: events.pop(0) if events else None,
    )

    assert runtime.resolve_canonical_app_route() == "Dashboard"
    assert session["cadivor_route"] == "Dashboard"
    assert query.get("page") == "Reports"
    assert query.writes == 0

    # A normal rerun still sees the stale server query. The browser-restored
    # Dashboard route must remain authoritative instead of bouncing to Reports.
    _patch_runtime(monkeypatch, session, query, consume=lambda: None)
    assert runtime.resolve_canonical_app_route() == "Dashboard"
    assert session["cadivor_route"] == "Dashboard"
    assert session["cadivor_nav_params"] == {"page": "Dashboard"}
    assert query.get("page") == "Reports"
    assert query.writes == 0
    assert session["access_token"] == "live-a"
    assert "user" in session

    # The next explicit in-app navigation supersedes the restore snapshot.
    navigation.navigate_to("Monitoring", _rerun=False)
    assert session["cadivor_route"] == "Monitoring"
    assert "cadivor_history_restore_snapshot" not in session
    assert query.get("page") == "Monitoring"


def test_new_bom_route_survives_stale_home_query_and_back_still_restores_home(monkeypatch):
    target_params = {"page": "BOM Analyzer", "new_analysis": "1"}
    session = _Session({
        "cadivor_route": "BOM Analyzer",
        "app_mode": "BOM Analyzer",
        "cadivor_nav_params": dict(target_params),
        "cadivor_pending_route_commit": {
            "page": "BOM Analyzer",
            "stale_page": "Dashboard",
            "params": dict(target_params),
        },
        "user": types.SimpleNamespace(id="user-1"),
        "access_token": "live-a",
        "refresh_token": "live-r",
        "cadivor_auth_status": "authenticated",
    })
    # Model a Streamlit run whose backend query still says Home after the
    # user's explicit New BOM Analysis route push.
    query = _DelayedQuery({"page": "Dashboard"})
    _patch_runtime(monkeypatch, session, query)

    assert runtime.resolve_canonical_app_route() == "BOM Analyzer"
    assert session["cadivor_nav_params"] == target_params
    assert session["cadivor_pending_route_commit"]["page"] == "BOM Analyzer"
    assert query.writes == 0

    # The browser Back event remains authoritative while the temporary
    # in-app route handoff is pending.
    query.clear()
    query.update({"page": "Dashboard"})
    events = [{
        "href": "http://127.0.0.1:8581/?page=Dashboard",
        "reason": "popstate",
        "event_id": "new-analysis-back-1",
    }]
    _patch_runtime(
        monkeypatch,
        session,
        query,
        consume=lambda: events.pop(0) if events else None,
    )
    assert runtime.resolve_canonical_app_route() == "Dashboard"
    assert "cadivor_pending_route_commit" not in session
    assert query.writes == 0


def test_new_bom_context_survives_a_partially_committed_target_query(monkeypatch):
    target_params = {"page": "BOM Analyzer", "new_analysis": "1"}
    session = _Session({
        "cadivor_route": "BOM Analyzer",
        "app_mode": "BOM Analyzer",
        "cadivor_nav_params": dict(target_params),
        "cadivor_pending_route_commit": {
            "page": "BOM Analyzer",
            "stale_page": "Dashboard",
            "params": dict(target_params),
        },
        "user": types.SimpleNamespace(id="user-1"),
        "access_token": "live-a",
        "refresh_token": "live-r",
        "cadivor_auth_status": "authenticated",
    })
    query = _DelayedQuery({"page": "BOM Analyzer"})
    _patch_runtime(monkeypatch, session, query)

    assert runtime.resolve_canonical_app_route() == "BOM Analyzer"
    assert session["cadivor_nav_params"] == target_params
    assert "cadivor_pending_route_commit" in session

    # The handoff clears only after Streamlit reflects the complete target URL.
    query.clear()
    query.update(target_params)
    _patch_runtime(monkeypatch, session, query)
    assert runtime.resolve_canonical_app_route() == "BOM Analyzer"
    assert session["cadivor_nav_params"] == target_params
    assert "cadivor_pending_route_commit" not in session


def test_url_change_echo_of_in_app_push_is_not_treated_as_restore(monkeypatch):
    session = _Session(
        {
            "cadivor_route": "Monitoring",
            "app_mode": "Monitoring",
            "cadivor_last_history_push_page": "Monitoring",
            "user": types.SimpleNamespace(id="user-1"),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
        }
    )
    query = _Query({"page": "Monitoring"})
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Monitoring",
            "reason": "url-change",
            "event_id": "echo-1",
        }
    ]
    _patch_runtime(monkeypatch, session, query, consume=lambda: events.pop(0) if events else None)

    assert runtime.resolve_canonical_app_route() == "Monitoring"
    assert query.writes == 0
    assert session.get("cadivor_main_transition_active") is not True


def test_same_page_url_change_restores_query_state_when_polling_fallback_fires(monkeypatch):
    session = _Session(
        {
            "cadivor_route": "Analysis Details",
            "app_mode": "Analysis Details",
            "cadivor_nav_params": {
                "page": "Analysis Details",
                "analysis_id": "bom-1",
                "analysis_tab": "Components",
            },
            "cadivor_last_history_push_page": "Analysis Details",
            "cadivor_last_history_push_params": {
                "page": "Analysis Details",
                "analysis_id": "bom-1",
                "analysis_tab": "Components",
            },
            "user": types.SimpleNamespace(id="user-1"),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
        }
    )
    query = _Query(
        {
            "page": "Analysis Details",
            "analysis_id": "bom-1",
            "analysis_tab": "Components",
        }
    )
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Analysis+Details&analysis_id=bom-2&analysis_tab=Engineering+Intelligence",
            "reason": "url-change",
            "event_id": "same-page-back-1",
        }
    ]
    _patch_runtime(monkeypatch, session, query, consume=lambda: events.pop(0) if events else None)

    assert runtime.resolve_canonical_app_route() == "Analysis Details"
    assert session["cadivor_nav_params"]["analysis_id"] == "bom-2"
    assert session["cadivor_nav_params"]["analysis_tab"] == "Engineering Intelligence"
    assert session["cadivor_active_analysis_id"] == "bom-2"
    assert session["cadivor_analysis_section_bom-2"] == "Engineering Intelligence"
    assert navigation.current_navigation_query_value(
        "analysis_id", "", route="Analysis Details"
    ) == "bom-2"
    assert query.writes == 0

    # A deliberate in-page selection after restoration replaces that restored
    # context and must not be overwritten by the pending stale-query snapshot.
    navigation.replace_navigation_query_params(
        {"analysis_tab": "Components"}, supersede_restore=True
    )
    assert "cadivor_history_restore_snapshot" not in session
    assert session["cadivor_nav_params"]["analysis_tab"] == "Components"
    assert query.writes == 0


def test_same_page_project_bom_selection_beats_a_stale_query_snapshot(monkeypatch):
    session = _Session(
        {
            "cadivor_route": "Analysis Details",
            "app_mode": "Analysis Details",
            "cadivor_nav_params": {
                "page": "Analysis Details",
                "analysis_id": "bom-1",
                "analysis_tab": "Engineering Intelligence",
            },
            "cadivor_active_analysis_id": "bom-1",
            "user": types.SimpleNamespace(id="user-1"),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
        }
    )
    query = _DelayedQuery(
        {
            "page": "Analysis Details",
            "analysis_id": "bom-1",
            "analysis_tab": "Engineering Intelligence",
        }
    )
    _patch_runtime(monkeypatch, session, query)

    navigation.navigate_to(
        "Analysis Details",
        analysis_id="bom-2",
        analysis_tab="Engineering Intelligence",
        _rerun=False,
        arm_opening=False,
    )

    assert query.get("analysis_id") == "bom-1"
    assert session[navigation.PENDING_NAVIGATION_CONTEXT_KEY]["analysis_id"] == "bom-2"
    assert runtime.resolve_canonical_app_route() == "Analysis Details"
    assert session["cadivor_nav_params"]["analysis_id"] == "bom-2"
    assert session["cadivor_active_analysis_id"] == "bom-2"
    assert navigation.current_navigation_query_value(
        "analysis_id", route="Analysis Details"
    ) == "bom-2"

    # A real browser Back event supersedes the pending callback target.
    query.clear()
    query.update(
        {
            "page": "Analysis Details",
            "analysis_id": "bom-1",
            "analysis_tab": "Engineering Intelligence",
        }
    )
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Analysis+Details&analysis_id=bom-1&analysis_tab=Engineering+Intelligence",
            "reason": "popstate",
            "event_id": "project-bom-back-1",
        }
    ]
    _patch_runtime(monkeypatch, session, query, consume=lambda: events.pop(0) if events else None)
    assert runtime.resolve_canonical_app_route() == "Analysis Details"
    assert session["cadivor_active_analysis_id"] == "bom-1"
    assert navigation.PENDING_NAVIGATION_CONTEXT_KEY not in session


def test_divergent_query_beats_stale_session_without_weakening_auth(monkeypatch):
    session = _Session(
        {
            "cadivor_route": "Monitoring",
            "app_mode": "Monitoring",
            "access_token": "live-a",
            "refresh_token": "live-r",
            "user": types.SimpleNamespace(id="user-1"),
            "cadivor_auth_status": "authenticated",
        }
    )
    query = _Query({"page": "Dashboard"})
    query.writes = 0
    _patch_runtime(monkeypatch, session, query)

    assert runtime.resolve_canonical_app_route() == "Dashboard"
    assert session["cadivor_route"] == "Dashboard"
    assert query.writes == 0
    assert session["access_token"] == "live-a"
    assert "user" in session


def test_repeated_route_ownership_does_not_stack_back_controls():
    runtime_src = _source("src/authenticated_runtime.py")
    detail = _source("src/pages/analysis_detail.py")
    assert runtime_src.count("claim_authenticated_route_body(app_mode)") == 1
    assert runtime_src.count("enter_authenticated_route_body(app_mode)") == 1
    assert detail.count('key="analysis_back_to_boms"') == 1
    assert 'st.container(key="cv_analysis_hero_actions")' in detail
    body = _source("src/ui/route_body.py")
    assert 'st.container(key=ROUTE_BODY_CONTAINER_KEY)' in body
    assert "stable keyed container" in body
    assert "return str(run_id) if run_id else str(id(ctx))" in body
    assert "ROUTE_BODY_CM_RUN_STATE_KEY" in body
    nav = _source("src/ui/navigation.py")
    assert "commit_navigation_query_params" in nav
    assert "LAST_HISTORY_PUSH_PAGE_KEY" in nav
    assert "replace_navigation_query_params" in nav
    assert "history.replaceState" in nav
    assert "LAST_HISTORY_PUSH_PARAMS_KEY" in nav
    assert "browser_query_state == server_query_state" in _source("src/authenticated_runtime.py")
    assert "replace_navigation_query_params" in _source("src/pages/analysis_detail.py")
    assert 'st.query_params.from_dict(' not in _source("src/pages/analysis_detail.py").split(
        "def _persist_component_focus_query", 1
    )[1].split("def _matching_component_records", 1)[0]
    assert "cadivor_browser_navigation_bridge_v4" in _source("src/browser_navigation.py")
    assert "@lru_cache" in _source("src/browser_navigation.py")
    assert "register_component" in _source("src/browser_navigation.py")
    bridge = _source("src/components/browser_navigation/index.html")
    assert "__cadivorNavBridgeV4" in bridge
    assert 'queue("popstate")' in bridge
    assert "url-change" in bridge
    auth_gate = _source("src/auth_gate.py")
    assert "st-key-cadivor_browser_navigation_bridge" in auth_gate
    assert "left:-10000px!important" in auth_gate
    assert "Keep the Back/Forward bridge mounted" in auth_gate
    assert "display:block!important" in auth_gate.split(
        "Keep the Back/Forward bridge mounted", 1
    )[1].split("</style>", 1)[0]
    assert 'post("streamlit:setFrameHeight", {height: 1})' in bridge
    assert "display:none can" in auth_gate


def test_same_page_menu_selection_does_not_arm_opening_cover():
    navigation_src = _source("src/ui/navigation.py")
    nav = navigation_src.split("def navigate_to", 1)[1].split(
        "def inject_nav_scroll_reset", 1
    )[0]
    assert "if arm_opening and current_page != page:" in nav
