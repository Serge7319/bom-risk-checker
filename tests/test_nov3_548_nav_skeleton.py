"""Nov 3 blank-canvas recording: skeleton cover + canonical route labels."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (
    ROOT / "src" / "components" / "browser_navigation" / "index.html"
).read_text(encoding="utf-8")


def test_cover_version_is_skeleton_v7():
    assert 'IMMEDIATE_NAV_COVER_VERSION = "nov3-548-skeleton-v7"' in BRIDGE


def test_cover_maps_menu_alias_to_canonical_route():
    assert '"Sourcing Recommendation": "Procurement Advisor"' in BRIDGE
    assert "canonicalRouteForLabel" in BRIDGE
    assert "displayNameForRoute" in BRIDGE
    assert "data-cadivor-dest-route" in BRIDGE


def test_cover_paints_page_skeleton_not_blank_canvas():
    assert "cv-instant-navigation-skeleton" in BRIDGE
    assert "cv-transition-hero" in BRIDGE
    assert "cv-transition-table" in BRIDGE
    # Main column only — leave the live foundation rail alone.
    assert "top:var(--cv-foundation-top,64px)" in BRIDGE
    assert "left:var(--cv-foundation-rail,296px)" in BRIDGE


def test_cover_does_not_paint_empty_duplicate_rail_strip():
    assert "#cadivor-rail-continuity{display:none!important;}" in BRIDGE


def test_release_requires_matching_destination_and_scroll_top():
    assert "matchingDestinationReleased" in BRIDGE
    assert "singleFoundationRailReady" in BRIDGE
    assert "suppressDuplicateFoundationRails" in BRIDGE
    assert "other.contains(element)" in BRIDGE
    assert "mainScrollAtTop" in BRIDGE
    assert "function titleYStable" not in BRIDGE
    assert "querySelector(\"h1\")" not in BRIDGE
    # Slow routes keep the skeleton; bound only as a last resort.
    assert "now - shownAt >= 8000" in BRIDGE
    assert "now - shownAt >= 1600" not in BRIDGE


def test_python_cover_is_not_blanked_to_empty_canvas():
    assert 'pythonCover.style.setProperty("visibility", "hidden"' not in BRIDGE
    assert 'pythonCover.style.setProperty("opacity", "0"' not in BRIDGE
