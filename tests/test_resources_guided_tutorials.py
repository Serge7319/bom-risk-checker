"""Regression checks for the authenticated Resources learning center."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


def test_resources_cover_every_cadivor_feature_with_a_tutorial() -> None:
    for tutorial_title in (
        "Set up your profile & workspace",
        "Use the Dashboard",
        "Upload and analyze a BOM",
        "Ask Cadivor about a BOM",
        "Find and compare alternatives",
        "Use Design Impact",
        "Record an engineering decision",
        "Use Procurement Advisor",
        "Use Cost Optimization",
        "Build a Supply Scenario",
        "Monitor a component",
        "Use Portfolio Intelligence",
        "Create and export reports",
        "Use the Admin Console",
    ):
        assert tutorial_title in RUNTIME

    assert "Back to all tutorials" in RUNTIME
    assert "Open tutorial →" in RUNTIME
    assert "Next tutorial →" in RUNTIME
    assert 'st.session_state["cadivor_resources_tutorial"] = tutorial[0]' in RUNTIME
    assert "resources_open_" in RUNTIME
    assert '"Design Impact Analyzer"' in RUNTIME
    assert '"Supply Risk Scenario"' in RUNTIME


def test_resources_show_step_matched_screen_guides_without_image_dependency() -> None:
    assert "cv-resource-guide-screen" in RUNTIME
    assert "cv-resource-guide-marker" in RUNTIME
    assert "Complete this action" in RUNTIME
    assert "Select each step to see its matching highlighted Cadivor screen guide." in RUNTIME
    assert "st.image(" not in RUNTIME[RUNTIME.index("# ---------- Resources / Help ----------"):RUNTIME.index("# ---------- About ----------")]
