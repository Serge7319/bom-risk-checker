"""Saved-BOM navigation labels. Relabels existing sections; does not drop them."""
from __future__ import annotations

from typing import Any, Mapping

ENGINEERING_DECISION_BRIEF = "Engineering Decision Brief"
PARTS_AND_RISK = "Parts & Risk"
REPLACEMENT_INTELLIGENCE = "Replacement Intelligence"
ENGINEERING_DECISIONS = "Engineering Decisions"

PRIMARY_AREAS: tuple[str, ...] = (
    ENGINEERING_DECISION_BRIEF,
    PARTS_AND_RISK,
    REPLACEMENT_INTELLIGENCE,
    ENGINEERING_DECISIONS,
)

MORE_MENU: tuple[str, ...] = (
    "Discussion",
    "History",
    "Report",
    "Watch this BOM",
    "Ask Cadivor",
    "Datasheet Q&A",
    "Compare parts",
    "Design Impact",
)

# Internal section keys that still have render branches.
LEGACY_SECTIONS: tuple[str, ...] = (
    "Engineering Intelligence",
    "Overview",
    "Intelligence",
    "Components",
    "Alternatives",
    "Discussions",
    "Timeline",
    "Reports",
    "Ask Cadivor",
)

_SECTION_TO_AREA: dict[str, str] = {
    "Engineering Intelligence": ENGINEERING_DECISION_BRIEF,
    "Overview": ENGINEERING_DECISION_BRIEF,
    "Intelligence": ENGINEERING_DECISION_BRIEF,
    "Decision Overview": ENGINEERING_DECISION_BRIEF,
    "Critical Findings": ENGINEERING_DECISION_BRIEF,
    "Recommended Actions": ENGINEERING_DECISIONS,
    "Business Impact": ENGINEERING_DECISION_BRIEF,
    "Evidence": ENGINEERING_DECISION_BRIEF,
    "Risk Analytics": ENGINEERING_DECISION_BRIEF,
    "Components": PARTS_AND_RISK,
    "Parts & Risk": PARTS_AND_RISK,
    "Alternatives": REPLACEMENT_INTELLIGENCE,
    "Replacement Intelligence": REPLACEMENT_INTELLIGENCE,
    "Engineering Decisions": ENGINEERING_DECISIONS,
    "Discussions": "Discussion",
    "Discussion": "Discussion",
    "Timeline": "History",
    "History": "History",
    "Reports": "Report",
    "Report": "Report",
    "Ask Cadivor": "Ask Cadivor",
    "Datasheet Q&A": "Datasheet Q&A",
    "Watch this BOM": "Watch this BOM",
    "Compare parts": "Compare parts",
    "Compare Parts": "Compare parts",
    "Design Impact": "Design Impact",
    "Design Impact Analyzer": "Design Impact",
}

_AREA_TO_SECTION: dict[str, str] = {
    ENGINEERING_DECISION_BRIEF: "Engineering Intelligence",
    PARTS_AND_RISK: "Components",
    REPLACEMENT_INTELLIGENCE: "Alternatives",
    ENGINEERING_DECISIONS: "Engineering Decisions",
    "Discussion": "Discussions",
    "History": "Timeline",
    "Report": "Reports",
    "Ask Cadivor": "Ask Cadivor",
}


def visible_area_for_section(section: str) -> str:
    key = str(section or "").strip()
    return _SECTION_TO_AREA.get(key, ENGINEERING_DECISION_BRIEF)


def section_for_choice(choice: str) -> str:
    """Map a visible area or More item to the internal render key."""
    key = str(choice or "").strip()
    if key in _AREA_TO_SECTION:
        return _AREA_TO_SECTION[key]
    if key in LEGACY_SECTIONS:
        return key
    return "Engineering Intelligence"


def former_destinations_covered() -> dict[str, str]:
    """Every previous Analysis Details destination and where it now lives."""
    return {
        "Engineering Intelligence": ENGINEERING_DECISION_BRIEF,
        "Overview": ENGINEERING_DECISION_BRIEF,
        "Intelligence": ENGINEERING_DECISION_BRIEF,
        "Decision Overview": ENGINEERING_DECISION_BRIEF,
        "Critical Findings": ENGINEERING_DECISION_BRIEF,
        "Recommended Actions": f"{ENGINEERING_DECISION_BRIEF} and {ENGINEERING_DECISIONS}",
        "Business Impact": ENGINEERING_DECISION_BRIEF,
        "Evidence": ENGINEERING_DECISION_BRIEF,
        "Risk Analytics": ENGINEERING_DECISION_BRIEF,
        "Components": PARTS_AND_RISK,
        "Alternatives": REPLACEMENT_INTELLIGENCE,
        "Discussions": "More · Discussion",
        "Timeline": "More · History",
        "Reports": "More · Report",
        "Ask Cadivor": "More · Ask Cadivor",
        "Open BOM Analyzer": "Back to BOMs",
        "Find Alternatives": "Find a replacement on the selected part",
        "Monitor Components": "More · Watch this BOM",
        "Reports Center": "More · Report",
    }


def primary_review_action(
    ranked_parts: list[Mapping[str, Any]] | None,
    *,
    selected_mpn: str = "",
    replacement_chosen: bool = False,
    review_queue_clear: bool = False,
) -> dict[str, str]:
    """One primary action from existing rank. Does not recompute risk."""
    selected = str(selected_mpn or "").strip()
    if review_queue_clear and not selected:
        return {
            "label": "Generate report",
            "kind": "report",
            "mpn": "",
        }
    if selected and replacement_chosen:
        return {
            "label": "Record decision",
            "kind": "decision",
            "mpn": selected,
        }
    if selected:
        return {
            "label": "Find a replacement",
            "kind": "replacement",
            "mpn": selected,
        }
    top = None
    for row in ranked_parts or []:
        if isinstance(row, Mapping):
            top = row
            break
    mpn = str((top or {}).get("mpn") or "").strip()
    if mpn and mpn.lower() not in {"unknown", "unknown mpn", "—", "-"}:
        return {
            "label": f"Review {mpn}",
            "kind": "review_part",
            "mpn": mpn,
        }
    if top is not None:
        return {
            "label": "Review highest-risk part",
            "kind": "review_part",
            "mpn": "",
        }
    return {
        "label": "Review parts",
        "kind": "review_parts",
        "mpn": "",
    }
