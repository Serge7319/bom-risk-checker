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


def test_saving_bridge_paints_details_report_only_without_opening():
    """Mixed Opening+Saving+clipped nav came from arm_opening and Details Saving."""
    early_bridge = RUNTIME.split("_pending_details_nav_early", 1)[1].split(
        "def _resolved_qp_value", 1
    )[0]
    assert '[_presented_route_bridge_early] = "Analysis Details"' not in early_bridge
    assert "arm_opening=False" in early_bridge
    assert "arm_opening=True" not in early_bridge
    assert 'cadivor_bom_details_paint_report_only"] = True' in early_bridge
    startup = RUNTIME.split("inject_premium_css()", 1)[1].split(
        "def _read_users_role_for_shell", 1
    )[0]
    assert "_paint_opening = False" in startup
    details = RUNTIME.split('if app_mode == "Analysis Details":', 1)[1].split(
        'if app_mode == "BOM Settings":', 1
    )[0]
    assert "analysis_details_handoff_report_only" in details
    assert "analysis_details_handoff_saving_surface" not in details


def test_navigation_opening_keeps_rail_inset_fallback():
    """First-admit navigation cover must reserve rail width before CSS vars land."""
    assert "left:var(--cv-foundation-rail,228px)" in MAIN_TRANSITION
    assert 'data-cadivor-transition-kind="navigation"' in MAIN_TRANSITION


def test_light_boot_splash_patches_streamlit_index():
    boot = (ROOT / "scripts" / "cadivor_streamlit_boot.py").read_text(encoding="utf-8")
    assert "def apply_light_boot_splash" in boot
    assert "cadivor-light-boot" in boot
    assert "cadivor-boot-splash" in boot
    assert "stAppSkeleton" in boot
    assert "Loading your workspace" in boot
    assert "color-scheme:light" in boot
    assert "apply_light_boot_splash()" in boot.split("def main", 1)[1]


def test_light_boot_splash_writes_branded_cover_into_streamlit_index(tmp_path, monkeypatch):
    """Cold load must show Cadivor cover, not dark skeleton or empty white."""
    import scripts.cadivor_streamlit_boot as boot

    fake_streamlit = tmp_path / "streamlit"
    static = fake_streamlit / "static"
    static.mkdir(parents=True)
    index = static / "index.html"
    index.write_text(
        "<!doctype html><html><head><title>Streamlit</title></head>"
        "<body><div id=\"root\"></div></body></html>",
        encoding="utf-8",
    )

    class _FakeStreamlit:
        __file__ = str(fake_streamlit / "__init__.py")

    monkeypatch.setitem(__import__("sys").modules, "streamlit", _FakeStreamlit())
    assert boot.apply_light_boot_splash() is True
    text = index.read_text(encoding="utf-8")
    assert 'id="cadivor-light-boot"' in text
    assert '<div id="cadivor-boot-splash"' in text
    assert "Loading your workspace" in text
    assert "stAppSkeleton" in text
    assert "color-scheme:light" in text
    # Idempotent upgrade path replaces prior fragments instead of stacking.
    assert boot.apply_light_boot_splash() is True
    text2 = index.read_text(encoding="utf-8")
    assert text2.count('<div id="cadivor-boot-splash"') == 1
    assert text2.count('id="cadivor-light-boot"') == 1
    assert text2.count('cadivor-boot-splash-retire') == 1
