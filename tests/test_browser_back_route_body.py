"""Browser Back/Forward and route-body ownership must replace prior page UI."""
from __future__ import annotations

import types
from pathlib import Path

import src.authenticated_runtime as runtime
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
    def get(self, key, default=""):
        return dict.get(self, key, default)

    def __setitem__(self, key, value):
        dict.__setitem__(self, key, value)

    def from_dict(self, mapping):
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


def test_runtime_owns_shared_route_body_host_without_rewriting_pages():
    runtime_src = _source("src/authenticated_runtime.py")
    assert "claim_authenticated_route_body(app_mode)" in runtime_src
    assert "enter_authenticated_route_body(app_mode)" in runtime_src
    assert "exit_authenticated_route_body()" in runtime_src
    assert runtime_src.count("with authenticated_route_body(") == 0
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

    # Second enter is a no-op while the container is active.
    enter_authenticated_route_body("Monitoring")
    assert host.entered == 1

    exit_authenticated_route_body()
    assert host.exited == 1
    assert ROUTE_BODY_CM_STATE_KEY not in session

    claim_authenticated_route_body("Reports")
    assert host.cleared == 2


def test_browser_back_restores_previous_route_while_authenticated(monkeypatch):
    session = _Session(
        {
            "cadivor_route": "Monitoring",
            "app_mode": "Monitoring",
            "cadivor_nav_params": {"page": "Monitoring"},
            "user": types.SimpleNamespace(id="user-1"),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
        }
    )
    query = _Query({"page": "Monitoring"})
    events = [
        {
            "href": "http://127.0.0.1:8581/?page=Dashboard",
            "reason": "popstate",
            "event_id": "back-1",
        }
    ]

    def _consume():
        return events.pop(0) if events else None

    fake_st = types.SimpleNamespace(session_state=session, query_params=query)
    monkeypatch.setattr(runtime, "st", fake_st)
    monkeypatch.setattr(runtime, "consume_browser_navigation_event", _consume)

    route = runtime.resolve_canonical_app_route()

    assert route == "Dashboard"
    assert session["cadivor_route"] == "Dashboard"
    assert session["app_mode"] == "Dashboard"
    assert query.get("page") == "Dashboard"
    assert session.get("cadivor_main_transition_active") is True
    assert session.get("cadivor_main_transition_route") == "Dashboard"
    assert "user" in session
    assert session["access_token"] == "live-a"
    assert session.get("cadivor_explicit_logout") is not True


def test_browser_forward_restores_next_route(monkeypatch):
    session = _Session(
        {
            "cadivor_route": "Dashboard",
            "app_mode": "Dashboard",
            "cadivor_nav_params": {"page": "Dashboard"},
        }
    )
    query = _Query({"page": "Dashboard"})

    def _consume():
        return {
            "href": "http://127.0.0.1:8581/?page=Monitoring",
            "reason": "popstate",
            "event_id": "forward-1",
        }

    fake_st = types.SimpleNamespace(session_state=session, query_params=query)
    monkeypatch.setattr(runtime, "st", fake_st)
    monkeypatch.setattr(runtime, "consume_browser_navigation_event", _consume)

    assert runtime.resolve_canonical_app_route() == "Monitoring"
    assert session["cadivor_route"] == "Monitoring"
    assert query.get("page") == "Monitoring"


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
    fake_st = types.SimpleNamespace(session_state=session, query_params=query)
    monkeypatch.setattr(runtime, "st", fake_st)
    monkeypatch.setattr(runtime, "consume_browser_navigation_event", lambda: None)

    assert runtime.resolve_canonical_app_route() == "Dashboard"
    assert session["cadivor_route"] == "Dashboard"
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
