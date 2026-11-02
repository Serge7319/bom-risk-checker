"""Nov 2 recording regressions: blank/partial shell + Saving→report nav leak."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
SHELL = (ROOT / "src" / "ui" / "unified_shell.py").read_text(encoding="utf-8")
ENTRY = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
MAIN_TRANSITION = (ROOT / "src" / "ui" / "main_transition.py").read_text(encoding="utf-8")


def test_entrypoint_forces_light_canvas_before_auth_paint():
    """Marketing Sign in must not flash Streamlit's dark default frame."""
    chrome = ENTRY.split('id="cadivor-root-chrome"', 1)[1].split("</style>", 1)[0]
    assert "color-scheme: light" in chrome
    assert "background: #F5F7FB" in chrome
    assert "html, body, .stApp" in chrome


def test_first_admit_injects_shell_css_and_arms_navigation_opening():
    """Login→Home Opening must inset to the rail, not a lone centered card."""
    startup = RUNTIME.split("inject_premium_css()", 1)[1].split(
        "def _read_users_role_for_shell", 1
    )[0]
    assert "inject_unified_shell_css" in startup
    assert startup.index("inject_unified_shell_css") < startup.index(
        "mount_main_transition_loading(_shell_route, paint_markup=True)"
    )
    assert 'kind="navigation"' in startup
    assert "_arm_first_admit" in startup or "arm_main_transition" in startup
    assert 'if not str(_presented_route or "").strip():' in startup


def test_approved_shell_css_restates_fixed_rail_geometry():
    """Partial shell mount must still pin the foundation rail (not flow into main)."""
    approved = SHELL.split("def _approved_shell_css", 1)[1].split(
        "def _escape", 1
    )[0]
    assert "position:fixed!important" in approved
    assert 'st-key-cv_foundation_navigation"' in approved or (
        "st-key-cv_foundation_navigation" in approved
    )
    assert "left:0!important" in approved


def test_saving_bridge_does_not_disarm_opening_or_preclaim_presented():
    """Uncovered foundation remount produced duplicate vertical nav lists."""
    early_bridge = RUNTIME.split("_pending_details_nav_early", 1)[1].split(
        "def _resolved_qp_value", 1
    )[0]
    assert '[_presented_route_bridge_early] = "Analysis Details"' not in early_bridge
    assert "pop(_transition_kind_bridge_early" not in early_bridge
    assert "pop(\"cadivor_main_transition_active\"" not in early_bridge
    assert "arm_opening=True" in early_bridge
    assert "arm_opening=False" not in early_bridge


def test_navigation_opening_keeps_rail_inset_fallback():
    """First-admit navigation cover must reserve rail width before CSS vars land."""
    assert "left:var(--cv-foundation-rail,228px)" in MAIN_TRANSITION
    assert 'data-cadivor-transition-kind="navigation"' in MAIN_TRANSITION
