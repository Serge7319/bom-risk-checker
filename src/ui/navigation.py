"""Cadivor internal same-tab navigation helpers."""
from __future__ import annotations

from typing import Any, Mapping, Optional

import streamlit as st

from src.normalizer import normalize_part_number
from src.urls import internal_app_href

ALTERNATIVE_FINDER_PAGE = "Alternative Finder"
ALT_FINDER_CONTEXT_KEY = "cadivor_alt_finder_pending_context"
ALT_FINDER_RETURN_ANALYSIS_KEY = "cadivor_alt_finder_return_analysis_id"
ALT_FINDER_RETURN_SECTION_KEY = "cadivor_alt_finder_return_analysis_section"
ALT_FINDER_INTENT = "find_alternatives"

_ALT_NAV_KEYS = (
    "original_part",
    "manufacturer",
    "description",
    "analysis_id",
    "return_analysis_id",
    "part_id",
    "source_page",
    "intent",
)


def navigate_to(page: str, *, _rerun: bool = True, **params: Any) -> None:
    """Navigate without a browser reload or a new Streamlit session.

    Internal navigation is intentionally session-state driven. Query strings are
    still accepted for external/deep links, but ordinary clicks must not force
    CookieManager and Supabase authentication to hydrate again.
    """
    current_page = str(st.session_state.get("cadivor_route", "") or "").strip()
    if current_page == "BOM Analyzer" and page != "BOM Analyzer":
        # The table widget is removed on other pages. Its row selections must
        # leave with it; otherwise a return shows unchecked rows beside stale
        # enabled Open/Delete actions from the previous editor instance.
        if st.session_state.get("bom81_selected_analysis_ids"):
            st.session_state["bom81_selected_analysis_ids"] = []
            st.session_state["bom81_saved_analysis_editor_revision"] = int(
                st.session_state.get("bom81_saved_analysis_editor_revision", 0)
            ) + 1
        st.session_state.pop("bom81_pending_delete_ids", None)

    st.session_state["cadivor_route"] = page
    st.session_state["app_mode"] = page
    nav_params = {"page": page}
    for key, value in params.items():
        if value is not None and str(value).strip() != "":
            nav_params[key] = str(value)
    st.session_state["cadivor_nav_params"] = nav_params
    if _rerun:
        st.rerun()


def build_alternative_finder_context(
    *,
    mpn: str,
    manufacturer: str = "",
    description: str = "",
    analysis_id: str = "",
    part_id: str = "",
    source_page: str = "",
) -> dict[str, str]:
    """Return one canonical Alternative Finder navigation payload."""
    trimmed_mpn = str(mpn or "").strip()
    normalized_mpn = normalize_part_number(trimmed_mpn) or trimmed_mpn.upper()
    return {
        "mpn": trimmed_mpn,
        "normalized_mpn": normalized_mpn,
        "manufacturer": str(manufacturer or "").strip(),
        "description": str(description or "").strip(),
        "analysis_id": str(analysis_id or "").strip(),
        "part_id": str(part_id or "").strip(),
        "source_page": str(source_page or "").strip(),
        "intent": ALT_FINDER_INTENT,
    }


def navigate_to_alternative_finder(
    *,
    mpn: str,
    manufacturer: str = "",
    description: str = "",
    analysis_id: str = "",
    part_id: str = "",
    source_page: str = "",
    return_analysis_id: str = "",
    _rerun: bool = True,
) -> None:
    """Navigate to Alternative Finder with normalized, shared part context."""
    context = build_alternative_finder_context(
        mpn=mpn,
        manufacturer=manufacturer,
        description=description,
        analysis_id=analysis_id,
        part_id=part_id,
        source_page=source_page,
    )
    if not context["mpn"]:
        navigate_to(ALTERNATIVE_FINDER_PAGE, _rerun=_rerun)
        return

    st.session_state[ALT_FINDER_CONTEXT_KEY] = context

    nav_kwargs: dict[str, str] = {
        "original_part": context["mpn"],
        "intent": ALT_FINDER_INTENT,
    }
    effective_analysis_id = return_analysis_id or context["analysis_id"]
    if effective_analysis_id:
        st.session_state[ALT_FINDER_RETURN_ANALYSIS_KEY] = effective_analysis_id
        active_section = str(st.session_state.get("cadivor_active_analysis_tab", "") or "").strip()
        if active_section:
            st.session_state[ALT_FINDER_RETURN_SECTION_KEY] = active_section
        nav_kwargs["analysis_id"] = effective_analysis_id
        nav_kwargs["return_analysis_id"] = effective_analysis_id
    else:
        st.session_state.pop(ALT_FINDER_RETURN_ANALYSIS_KEY, None)
        st.session_state.pop(ALT_FINDER_RETURN_SECTION_KEY, None)
    if context["manufacturer"]:
        nav_kwargs["manufacturer"] = context["manufacturer"]
    if context["description"]:
        nav_kwargs["description"] = context["description"]
    if context["part_id"]:
        nav_kwargs["part_id"] = context["part_id"]
    if context["source_page"]:
        nav_kwargs["source_page"] = context["source_page"]

    navigate_to(ALTERNATIVE_FINDER_PAGE, _rerun=_rerun, **nav_kwargs)


def consume_alternative_finder_context(
    qp_value: Any,
) -> Optional[dict[str, str]]:
    """Read Alternative Finder navigation context exactly once per navigation."""
    pending = st.session_state.pop(ALT_FINDER_CONTEXT_KEY, None)
    if isinstance(pending, dict) and pending.get("mpn"):
        if pending.get("analysis_id"):
            st.session_state[ALT_FINDER_RETURN_ANALYSIS_KEY] = pending["analysis_id"]
        _clear_consumed_alt_nav_params()
        _clear_alt_query_params()
        return pending

    original_part = str(qp_value("original_part", "") or "").strip()
    if not original_part:
        return None

    context = build_alternative_finder_context(
        mpn=original_part,
        manufacturer=str(qp_value("manufacturer", "") or ""),
        description=str(qp_value("description", "") or ""),
        analysis_id=str(qp_value("analysis_id", "") or ""),
        part_id=str(qp_value("part_id", "") or ""),
        source_page=str(qp_value("source_page", "") or ""),
    )
    return_analysis_id = str(qp_value("return_analysis_id", "") or context["analysis_id"]).strip()
    if return_analysis_id:
        st.session_state[ALT_FINDER_RETURN_ANALYSIS_KEY] = return_analysis_id
    _clear_consumed_alt_nav_params()
    _clear_alt_query_params()
    return context


def _clear_alt_query_params() -> None:
    try:
        for key in _ALT_NAV_KEYS:
            if key in st.query_params:
                del st.query_params[key]
    except Exception:
        pass


def _clear_consumed_alt_nav_params() -> None:
    nav_params = dict(st.session_state.get("cadivor_nav_params") or {})
    for key in _ALT_NAV_KEYS:
        nav_params.pop(key, None)
    if nav_params.get("page") == ALTERNATIVE_FINDER_PAGE and len(nav_params) == 1:
        st.session_state.pop("cadivor_nav_params", None)
    elif nav_params:
        st.session_state["cadivor_nav_params"] = nav_params
    else:
        st.session_state.pop("cadivor_nav_params", None)


def apply_alternative_finder_prefill(context: Mapping[str, str]) -> None:
    """Populate Alternative Finder widgets from a consumed navigation context."""
    if not context or not context.get("mpn"):
        return

    prefill_token = (
        f"{context.get('analysis_id', '')}::"
        f"{context.get('normalized_mpn') or str(context.get('mpn', '')).upper()}"
    )
    if st.session_state.get("alternative_prefill_token") == prefill_token:
        return

    st.session_state["alternative_original_part"] = context["mpn"]
    st.session_state["alternative_prefill_token"] = prefill_token
    if context.get("manufacturer"):
        st.session_state["alternative_original_manufacturer"] = context["manufacturer"]
    else:
        st.session_state.pop("alternative_original_manufacturer", None)
    if context.get("analysis_id"):
        st.session_state["cadivor_active_analysis_id"] = context["analysis_id"]
        st.session_state["analysis_id"] = context["analysis_id"]

    st.session_state["alternative_search_attempted"] = False
    st.session_state["suggested_alternatives"] = []
    st.session_state["alternative_original_data"] = {}
    st.session_state["alternative_original_risk"] = {}
    st.session_state["alternative_original_lookup_part"] = ""
    st.session_state["alternative_original_lookup_error"] = ""
    st.session_state["alternative_search_error"] = ""


def reset_alternative_finder_prefill() -> None:
    """Clear Alternative Finder prefill state during an intentional reset."""
    st.session_state.pop("alternative_prefill_token", None)
    st.session_state.pop("alternative_original_manufacturer", None)


def alternative_finder_href(
    *,
    mpn: str,
    manufacturer: str = "",
    description: str = "",
    analysis_id: str = "",
    part_id: str = "",
    source_page: str = "",
    return_analysis_id: str = "",
) -> str:
    """Build a query-string link to Alternative Finder using the shared context."""
    context = build_alternative_finder_context(
        mpn=mpn,
        manufacturer=manufacturer,
        description=description,
        analysis_id=analysis_id,
        part_id=part_id,
        source_page=source_page,
    )
    params: dict[str, str] = {
        "original_part": context["mpn"],
        "intent": ALT_FINDER_INTENT,
    }
    effective_analysis_id = return_analysis_id or context["analysis_id"]
    if effective_analysis_id:
        params["analysis_id"] = effective_analysis_id
        params["return_analysis_id"] = effective_analysis_id
    if context["manufacturer"]:
        params["manufacturer"] = context["manufacturer"]
    if context["description"]:
        params["description"] = context["description"]
    if context["part_id"]:
        params["part_id"] = context["part_id"]
    if context["source_page"]:
        params["source_page"] = context["source_page"]
    return internal_app_href(ALTERNATIVE_FINDER_PAGE, **params)


def internal_nav_button(
    label: str,
    page: str,
    *,
    key: str,
    use_container_width: bool = False,
    type: str = "primary",
    disabled: bool = False,
    **params: Any,
) -> bool:
    """Render a button that keeps navigation inside the current Cadivor tab."""
    clean_label = str(label or "").strip()
    if not clean_label:
        return False
    def _commit_button_navigation() -> None:
        # Widget callbacks run before Streamlit renders the next script pass.
        # Committing here prevents the old page from consuming the first click.
        if page == ALTERNATIVE_FINDER_PAGE:
            navigate_to_alternative_finder(
                mpn=str(params.get("original_part", "") or ""),
                manufacturer=str(params.get("manufacturer", "") or ""),
                description=str(params.get("description", "") or ""),
                analysis_id=str(params.get("analysis_id", "") or ""),
                part_id=str(params.get("part_id", "") or ""),
                source_page=str(params.get("source_page", "") or ""),
                return_analysis_id=str(params.get("return_analysis_id", "") or ""),
                _rerun=False,
            )
        else:
            navigate_to(page, _rerun=False, **params)

    clicked = st.button(
        clean_label,
        key=key,
        use_container_width=use_container_width,
        type=type,
        disabled=disabled,
        on_click=_commit_button_navigation,
    )
    return clicked


def render_command_nav_triggers(commands: list[dict]) -> None:
    """Mount hidden session-state navigation buttons for the command palette."""
    triggers = [command for command in commands if command.get("nav_page")]
    if not triggers:
        return

    st.markdown(
        """
        <style id="cadivor-command-nav-triggers">
        .cvcc-nav-triggers {
          position: absolute !important;
          left: -10000px !important;
          width: 1px !important;
          height: 1px !important;
          overflow: hidden !important;
          opacity: 0 !important;
          pointer-events: none !important;
        }
        </style>
        <div class="cvcc-nav-triggers" aria-hidden="true"></div>
        """,
        unsafe_allow_html=True,
    )
    for command in triggers[:60]:
        safe_key = str(command.get("id") or "").replace("-", "_")
        page = str(command.get("nav_page") or "")
        params = dict(command.get("nav_params") or {})
        internal_nav_button(
            "Open",
            page,
            key=f"cvcc_nav_{safe_key}",
            **params,
        )
