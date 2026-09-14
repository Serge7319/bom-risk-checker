"""Ask Cadivor stays a saved-BOM assistant. Datasheet Q&A stays a Decision Tool."""
from __future__ import annotations

from pathlib import Path

from src.ui.bom_navigation import (
    MORE_MENU,
    PRIMARY_AREAS,
    feature_map,
    former_destinations_covered,
    section_for_choice,
    selected_component_context,
)
from src.ui.unified_shell import NAV_GROUPS


ROOT = Path(__file__).resolve().parents[1]
SAVED_BOM_CAPABILITIES = (
    "Engineering Decision Brief",
    "Parts & Risk",
    "Replacement Intelligence",
    "Engineering Decisions",
    "Discussion",
    "History",
    "Report",
    "Watch this BOM",
    "Datasheet Q&A",
    "Compare parts",
    "Design Impact",
)


def _decision_tool_labels() -> list[str]:
    return [item[0] for name, items in NAV_GROUPS if name == "Decision Tools" for item in items]


def test_ask_cadivor_is_visible_in_saved_bom_primary_navigation():
    assert PRIMARY_AREAS == (
        "Engineering Decision Brief",
        "Parts & Risk",
        "Replacement Intelligence",
        "Engineering Decisions",
        "Ask Cadivor",
    )
    assert "Ask Cadivor" not in MORE_MENU
    locations = feature_map()
    assert locations["Ask Cadivor"]["location"] == "saved BOM navigation"
    assert locations["Ask Cadivor"]["reach"] == "one click while a BOM is open"
    assert former_destinations_covered()["Ask Cadivor"] == "Ask Cadivor"
    assert section_for_choice("Ask Cadivor") == "Ask Cadivor"

    detail = (ROOT / "src/pages/analysis_detail.py").read_text(encoding="utf-8")
    nav = detail.split("def _render_analysis_section_navigation", 1)[1].split(
        "def _num(", 1
    )[0]
    assert "list(PRIMARY_AREAS)" in nav
    assert 'navigate_to("Ask Cadivor"' not in nav
    assert '"Ask Cadivor": "Ask Cadivor"' not in nav


def test_ask_cadivor_receives_active_bom_and_selected_part_context():
    session = {
        "cadivor_active_analysis_id": "bom-9",
        "cadivor_selected_component_analysis_id": "bom-9",
        "cadivor_selected_component_mpn": "TPS54331D",
    }
    launch = selected_component_context(session, analysis_id="bom-9")
    assert launch == {"analysis_id": "bom-9", "selected_component": "TPS54331D"}

    from_query = selected_component_context(
        session,
        analysis_id="bom-9",
        requested_component="MAX32625ITK+",
    )
    assert from_query["selected_component"] == "MAX32625ITK+"

    from_selector = selected_component_context(
        {"analysis_component_selector_bom-9": "GRM188R71H104KA93D — Murata"},
        analysis_id="bom-9",
    )
    assert from_selector["analysis_id"] == "bom-9"
    assert from_selector["selected_component"] == "GRM188R71H104KA93D"

    other_bom = selected_component_context(session, analysis_id="bom-other")
    assert other_bom["analysis_id"] == "bom-other"
    assert other_bom["selected_component"] == ""

    source = (ROOT / "src/pages/analysis_detail.py").read_text(encoding="utf-8")
    ask_block = source.split('if active_tab == "Ask Cadivor":', 1)[1].split(
        "if saved_bom_top_requested", 1
    )[0]
    assert "selected_component_context(" in ask_block
    assert "engineering_context=engineering_context" in ask_block
    assert 'selected_component=launch["selected_component"]' in ask_block
    assert "cadivor_active_analysis_id" in source.split("def render_analysis_detail", 1)[1]


def test_datasheet_qa_remains_separately_reachable():
    labels = _decision_tool_labels()
    assert "Datasheet Q&A" in labels
    assert "Ask Cadivor" not in labels
    locations = feature_map()
    assert locations["Datasheet Q&A"]["label"] == "Datasheet Q&A"
    assert locations["Datasheet Q&A"]["location"] == "Decision Tools"
    assert locations["Datasheet Q&A"]["reach"] == "one click globally"
    assert "Datasheet Q&A" in MORE_MENU
    assert locations["Ask Cadivor"]["label"] != locations["Datasheet Q&A"]["label"]

    page = (ROOT / "src/pages/datasheet_qa.py").read_text(encoding="utf-8")
    assert 'dq-kicker">Datasheet Q&A' in page
    assert 'st.button(\n            "Ask Cadivor"' not in page
    detail = (ROOT / "src/pages/analysis_detail.py").read_text(encoding="utf-8")
    assert 'navigate_to("Datasheet Q&A"' in detail
    assert 'navigate_to("Ask Cadivor"' not in detail


def test_restoring_ask_cadivor_does_not_drop_saved_bom_capabilities():
    visible = set(PRIMARY_AREAS) | set(MORE_MENU)
    missing = [name for name in SAVED_BOM_CAPABILITIES if name not in visible]
    assert missing == []
    covered = former_destinations_covered()
    for former in (
        "Engineering Intelligence",
        "Components",
        "Alternatives",
        "Discussions",
        "Timeline",
        "Reports",
        "Ask Cadivor",
        "Monitor Components",
        "Find Alternatives",
        "Reports Center",
        "Open BOM Analyzer",
    ):
        assert covered[former]
    assert covered["Ask Cadivor"] != covered["Datasheet Q&A"]
