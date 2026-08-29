"""Regression checks for the authenticated Resources learning center."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
ASSETS = ROOT / "src" / "assets" / "resources"


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
    assert '"Design Impact Analyzer"' in RUNTIME
    assert '"Supply Risk Scenario"' in RUNTIME


def test_resources_ship_real_product_tutorial_screens() -> None:
    for filename in (
        "ask-cadivor-question.png",
        "bom-analyzer-start.png",
        "recommendation-result.png",
        "recommendation-actions.png",
    ):
        asset = ASSETS / filename
        assert asset.is_file()
        assert asset.stat().st_size > 10_000
