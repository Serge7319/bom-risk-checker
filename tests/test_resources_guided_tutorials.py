"""Regression checks for the authenticated Resources learning center."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
ASSETS = ROOT / "src" / "assets" / "resources"


def test_resources_use_step_by_step_tutorial_content() -> None:
    assert '"1 · Analyze a BOM"' in RUNTIME
    assert '"2 · Ask Cadivor"' in RUNTIME
    assert '"3 · Decide & monitor"' in RUNTIME
    assert "Take the first-review walkthrough" in RUNTIME
    assert "Good first questions" in RUNTIME
    assert "Before you approve" in RUNTIME


def test_resources_ship_real_product_tutorial_screens() -> None:
    for filename in (
        "ask-cadivor-question.png",
        "recommendation-result.png",
        "recommendation-actions.png",
    ):
        asset = ASSETS / filename
        assert asset.is_file()
        assert asset.stat().st_size > 10_000
