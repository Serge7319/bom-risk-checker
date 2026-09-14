"""In-session navigation must respond and must not sign a valid user out."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_route_families_do_not_hard_reload():
    navigation = _source("src/ui/navigation.py")
    shell = _source("src/ui/unified_shell.py")
    home = _source("src/pages/home_workspace.py")
    detail = _source("src/pages/analysis_detail.py")
    command = _source("src/components/command_center.py")
    reports = _source("src/pages/reports.py")
    runtime = _source("src/authenticated_runtime.py")

    assert "st.button(" in navigation.split("def internal_nav_button", 1)[1].split("def consume_navigation_error", 1)[0]
    assert "target=\"_self\"" not in navigation.split("def internal_nav_button", 1)[1]
    assert "on_click=_commit_navigation" in shell
    assert "open_saved_bom(" in home
    assert 'st.button("Back to BOMs"' in detail
    assert "navigate_to(" in detail
    assert "link.href = command.href" not in command
    assert "Couldn’t open that page" in command
    assert "href=\"?page=" not in reports
    assert "href=\"?page=" not in runtime.split("def render_global_search", 1)[-1][:4000] or "href=\"?page=" not in runtime
    assert "pointer-events:none!important" in _source("src/ui/main_transition.py")


def test_page_hop_calls_the_authenticated_session_guard():
    bootstrap = _source("src/auth_bootstrap.py")
    assert "drop_stale_logout_query_for_authenticated_page_hop()" in bootstrap
    assert "authenticated_in_app_session" in _source("src/auth_state.py")
    hop = _source("src/ui/navigation.py").split("def navigate_to", 1)[1]
    assert "authenticated_in_app_session" in hop
    assert "cadivor_explicit_logout" not in hop.split("def inject_nav_scroll_reset", 1)[0]
