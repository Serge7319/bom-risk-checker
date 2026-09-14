"""Saved-BOM navigation labels and the one shared section tab row."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

ENGINEERING_DECISION_BRIEF = "Engineering Decision Brief"
PARTS_AND_RISK = "Parts & Risk"
REPLACEMENT_INTELLIGENCE = "Replacement Intelligence"
ENGINEERING_DECISIONS = "Engineering Decisions"
ASK_CADIVOR = "Ask Cadivor"
DATASHEET_QA = "Datasheet Q&A"

PRIMARY_AREAS: tuple[str, ...] = (
    ENGINEERING_DECISION_BRIEF,
    PARTS_AND_RISK,
    REPLACEMENT_INTELLIGENCE,
    ENGINEERING_DECISIONS,
    ASK_CADIVOR,
)

MORE_MENU: tuple[str, ...] = (
    "Discussion",
    "History",
    "Report",
    "Watch this BOM",
    DATASHEET_QA,
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


def feature_map() -> dict[str, dict[str, str]]:
    """Distinct locations. Ask Cadivor and Datasheet Q&A are not interchangeable."""
    return {
        ASK_CADIVOR: {
            "label": ASK_CADIVOR,
            "location": "saved BOM navigation",
            "reach": "one click while a BOM is open",
        },
        DATASHEET_QA: {
            "label": DATASHEET_QA,
            "location": "Decision Tools",
            "reach": "one click globally",
            "contextual": f"More · {DATASHEET_QA}",
        },
    }


def selected_component_context(
    session: Mapping[str, Any],
    *,
    analysis_id: str,
    requested_component: str = "",
) -> dict[str, str]:
    """BOM and selected-part context for Ask Cadivor. Does not invent a part."""
    analysis = str(analysis_id or "").strip()
    requested = str(requested_component or "").strip()
    component = requested
    if not component:
        stored_analysis = str(session.get("cadivor_selected_component_analysis_id") or "").strip()
        stored_mpn = str(session.get("cadivor_selected_component_mpn") or "").strip()
        if stored_mpn and (not stored_analysis or stored_analysis == analysis):
            component = stored_mpn
    if not component:
        label = str(session.get(f"analysis_component_selector_{analysis}") or "").strip()
        if " — " in label:
            component = label.split(" — ", 1)[0].strip()
        elif label and label.lower() not in {"unknown", "unknown mpn"}:
            component = label
    if not component:
        review = str(session.get("cadivor_review_mpn") or "").strip()
        if review and review.lower() not in {"unknown", "unknown mpn"}:
            component = review
    return {
        "analysis_id": analysis,
        "selected_component": component,
    }


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
        "Ask Cadivor": ASK_CADIVOR,
        "Datasheet Q&A": f"Decision Tools · {DATASHEET_QA}",
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


SAVED_BOM_NAV_KEY = "cv_analysis_section_nav"
SAVED_BOM_NAV_CLASS = "cv-saved-bom-nav"
SAVED_BOM_NAV_MORE_KEY = "cv_saved_bom_nav_more"
SAVED_BOM_TAB_KEY_PREFIX = "cadivor_bom_tab_"
_SAVED_BOM_NAV_CSS = (
    Path(__file__).resolve().parents[1] / "assets" / "css" / "saved_bom_nav.css"
)


def saved_bom_nav_css() -> str:
    """The one underline treatment used by every saved-BOM section."""
    try:
        return _SAVED_BOM_NAV_CSS.read_text(encoding="utf-8")
    except OSError:
        return ""


def inject_saved_bom_nav_css() -> None:
    """Load the shared tab style after global button chrome."""
    import streamlit as st

    css = saved_bom_nav_css()
    if css.strip():
        st.markdown(
            f"<style id='cadivor-saved-bom-nav'>{css}</style>",
            unsafe_allow_html=True,
        )


def render_saved_bom_section_nav(
    *,
    analysis_id: str,
    selected_area: str,
    more_choice: str,
    more_menu: tuple[str, ...] = MORE_MENU,
    more_key: str = "",
) -> tuple[str | None, str | None]:
    """Render the shared tab row. Returns (area clicked, More item clicked)."""
    import streamlit as st

    inject_saved_bom_nav_css()
    active_token = "more" if more_choice != "More" else "area"
    st.markdown(
        (
            f'<div class="{SAVED_BOM_NAV_CLASS}" data-cv-saved-bom-nav="shared" '
            f'data-cv-saved-bom-active="{active_token}" hidden></div>'
        ),
        unsafe_allow_html=True,
    )
    area_clicked = None
    more_clicked = None
    with st.container(key=SAVED_BOM_NAV_KEY):
        try:
            nav_row = st.container(horizontal=True, vertical_alignment="bottom", gap="small")
        except TypeError:
            nav_row = st.container()
        with nav_row:
            button = getattr(st, "button", None)
            for area in list(PRIMARY_AREAS):
                active = area == selected_area and more_choice == "More"
                clicked = False
                if callable(button):
                    clicked = bool(
                        button(
                            area,
                            key=f"{SAVED_BOM_TAB_KEY_PREFIX}{analysis_id}_{area}",
                            type="primary" if active else "secondary",
                        )
                    )
                if clicked:
                    area_clicked = area
            popover = getattr(st, "popover", None)
            if callable(popover):
                with st.container(key=SAVED_BOM_NAV_MORE_KEY):
                    with popover("More ▾"):
                        button = getattr(st, "button", None)
                        for item in more_menu:
                            clicked = False
                            if callable(button):
                                clicked = bool(
                                    button(
                                        item,
                                        key=f"cadivor_bom_more_btn_{analysis_id}_{item}",
                                    )
                                )
                            if clicked:
                                more_clicked = item
            else:
                selectbox = getattr(st, "selectbox", None)
                if callable(selectbox):
                    selectbox(
                        "More",
                        ["More", *more_menu],
                        key=more_key or f"cadivor_bom_more_{analysis_id}",
                        label_visibility="collapsed",
                    )
    return area_clicked, more_clicked
