"""Regression checks for the authenticated Resources learning center."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


def test_resources_is_hidden_from_non_admin_navigation_during_rebuild() -> None:
    assert 'NAV_OPTIONS.remove("Help")' in RUNTIME
    assert "Resources is undergoing an administrator-only rebuild" in RUNTIME


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


def test_resources_use_distinct_real_screens_for_each_alternative_finder_step() -> None:
    resources_block = RUNTIME[RUNTIME.index("# ---------- Resources / Help ----------"):RUNTIME.index("# ---------- About ----------")]
    assert '"alternative-finder-01-enter-part.jpg"' in resources_block
    assert '"alternative-finder-02-run-search.jpg"' in resources_block
    assert '"alternative-finder-03-review-baseline.jpg"' in resources_block
    assert "tutorial_screens" in resources_block
    assert "len(screens) == len(steps)" in resources_block
    assert "st.image(" in resources_block
    assert "generic or unrelated image" in resources_block
    assert "cv-resource-guide-screen" not in resources_block
    assert "cv-resource-guide-marker" not in resources_block


def test_resources_tutorial_images_are_valid_image_files() -> None:
    from PIL import Image

    tutorial_root = ROOT / "src" / "assets" / "resources" / "tutorials"
    expected = (
        "alternative-finder-01-enter-part.jpg",
        "alternative-finder-02-run-search.jpg",
        "alternative-finder-03-review-baseline.jpg",
    )
    for filename in expected:
        image_path = tutorial_root / filename
        assert image_path.is_file()
        with Image.open(image_path) as image:
            image.verify()
