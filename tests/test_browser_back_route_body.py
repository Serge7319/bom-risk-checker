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


class _Empty:
    def __init__(self):
        self.cleared = 0
        self.containers = []
        self.entered = 0
        self.exited = 0

    def empty(self):
        self.cleared += 1

    def container(self):
        host = self

        class _CM:
            def __enter__(self_inner):
                host.entered += 1
                return self_inner

            def __exit__(self_inner, *_exc):
                host.exited += 1
                return False

        cm = _CM()
        self.containers.append(cm)
        return cm


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


def test_runtime_owns_shared_route_body_host_without_rewriting_pages():
    runtime_src = _source("src/authenticated_runtime.py")
    assert "claim_authenticated_route_body(app_mode)" in runtime_src
    assert "enter_authenticated_route_body(app_mode)" in runtime_src
    assert "exit_authenticated_route_body()" in runtime_src
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


def test_route_body_host_clears_and_enters_without_stacking(monkeypatch):
    host = _Empty()
    session = _Session()
    fake_st = types.SimpleNamespace(empty=lambda: host, session_state=session)
    monkeypatch.setattr("src.ui.route_body.st", fake_st)

    claimed = claim_authenticated_route_body("Monitoring")
    assert claimed is host
    assert host.cleared == 1
    enter_authenticated_route_body("Monitoring")
    assert host.entered == 1
    assert session[ROUTE_BODY_HOST_STATE_KEY] is host
    assert session[ROUTE_BODY_CM_STATE_KEY] is not None

    enter_authenticated_route_body("Monitoring")
    assert host.entered == 1

    exit_authenticated_route_body()
    assert host.exited == 1
    assert ROUTE_BODY_CM_STATE_KEY not in session

    claim_authenticated_route_body("Reports")
    assert host.cleared == 2


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
    assert "host.empty()" in body
    assert "without CSS hiding" in body
    nav = _source("src/ui/navigation.py")
    assert "commit_navigation_query_params" in nav
    assert "LAST_HISTORY_PUSH_PAGE_KEY" in nav
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
    assert "display:none can" in auth_gate
