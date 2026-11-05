"""Nov 3 4:26 recording: nav flash + mid-page title settle on every route change."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSITION = (ROOT / "src" / "ui" / "main_transition.py").read_text(encoding="utf-8")
NAVIGATION = (ROOT / "src" / "ui" / "navigation.py").read_text(encoding="utf-8")
BRIDGE = (
    ROOT / "src" / "components" / "browser_navigation" / "index.html"
).read_text(encoding="utf-8")


def test_navigation_reveal_does_not_publish_release_gen():
    reveal = TRANSITION.split("def reveal_main_transition", 1)[1]
    assert 'if transition_kind == "navigation"' in reveal
    assert 'release_attr = (' in reveal
    assert 'data-cadivor-page-body-release-gen="{gen}"' in reveal


def test_scroll_reset_bounds_wait_without_early_mid_scroll_release():
    reset = NAVIGATION.split("def inject_nav_scroll_reset_if_needed", 1)[1]
    assert "state.settled >= 2" in reset
    assert "Date.now() - state.startedAt > 900" in reset
    assert "Date.now() - state.startedAt > 250" not in reset


def test_instant_cover_keeps_workspace_column_inset():
    assert "left:var(--cv-foundation-rail,296px)" in BRIDGE
    assert "cv-instant-navigation-skeleton" in BRIDGE


def test_cover_installer_is_versioned_so_deploys_replace_stale_handlers():
    assert 'IMMEDIATE_NAV_COVER_VERSION = "nov3-548-skeleton-v7"' in BRIDGE
    assert "__cadivorImmediateNavigationClick" in BRIDGE
    assert "removeEventListener(\"click\", w.__cadivorImmediateNavigationClick, true)" in BRIDGE
    assert "__cadivorQueueNavigationCoverRelease" in BRIDGE
    assert 'staleStyle.remove()' in BRIDGE or "staleStyle) staleStyle.remove()" in BRIDGE
    assert "data-cadivor-cover-shown-at" in BRIDGE
    assert "matchingDestinationReleased" in BRIDGE


def test_navigation_re_reveal_keeps_deferred_release_gen():
    assert "NAV_RELEASE_DEFER_GEN_KEY" in TRANSITION
    assert "deferred_gen = int(st.session_state.get(NAV_RELEASE_DEFER_GEN_KEY)" in TRANSITION
    assert "defer_release = transition_kind == \"navigation\"" in TRANSITION
