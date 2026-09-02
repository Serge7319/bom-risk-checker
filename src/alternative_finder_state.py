"""Durable Alternative Finder session-state helpers for Streamlit reruns."""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

ALT_FINDER_RESULT_KEY = "alternative_finder_result"
ALT_FINDER_NAV_CONSUMED_KEY = "alternative_finder_nav_consumed_token"
RESULT_ALGORITHM_VERSION = "supplier-evidence-v4"

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_LEGACY_KEYS = (
    "suggested_alternatives",
    "alternative_search_attempted",
    "alternative_original_data",
    "alternative_original_risk",
    "alternative_original_lookup_part",
    "alternative_original_lookup_error",
    "alternative_search_error",
    "alternative_discovery_metadata",
    "alternative_result_algorithm_version",
)


def _normalize_mpn(value: Any) -> str:
    return str(value or "").strip().upper()


def sanitize_for_session(value: Any) -> Any:
    """Make nested candidate payloads safe for Streamlit session persistence."""
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if isinstance(value, dict):
        return {key: sanitize_for_session(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_for_session(item) for item in value]
    return value


def init_alternative_finder_state(session_state: MutableMapping[str, Any]) -> None:
    """Initialize Alternative Finder keys and migrate legacy session payloads."""
    session_state.setdefault("alternative_original_part", "")
    session_state.setdefault("alternative_candidate_shortlist", [])
    session_state.setdefault("alternative_engineering_decisions", {})
    session_state.setdefault("alternative_decision_notes", {})
    session_state.setdefault("alternative_decision_db_status", "")
    session_state.setdefault("alternative_decision_db_error", "")
    session_state.setdefault("alternative_decision_flash", "")

    result = session_state.get(ALT_FINDER_RESULT_KEY)
    if not isinstance(result, dict):
        result = {"status": STATUS_IDLE, "algorithm_version": RESULT_ALGORITHM_VERSION}
        session_state[ALT_FINDER_RESULT_KEY] = result

    stored_version = str(result.get("algorithm_version") or "")
    if stored_version != RESULT_ALGORITHM_VERSION:
        clear_alternative_finder_search(session_state, clear_widget=False)
        session_state[ALT_FINDER_RESULT_KEY] = {
            "status": STATUS_IDLE,
            "algorithm_version": RESULT_ALGORITHM_VERSION,
        }
        return

    if result.get("status") == STATUS_COMPLETED:
        _sync_legacy_from_result(session_state, result)
        return

    if session_state.get("alternative_search_attempted") and session_state.get("suggested_alternatives"):
        _migrate_legacy_completed_search(session_state)


def _migrate_legacy_completed_search(session_state: MutableMapping[str, Any]) -> None:
    entered_mpn = str(session_state.get("alternative_original_lookup_part") or "").strip()
    if not entered_mpn:
        entered_mpn = str(session_state.get("alternative_original_part") or "").strip()
    if not entered_mpn:
        return

    candidates = sanitize_for_session(session_state.get("suggested_alternatives") or [])
    selected_mpn = str(session_state.get("alternative_selected_candidate_62b") or "").strip()
    if not selected_mpn and candidates:
        selected_mpn = str(candidates[0].get("Alternative Part") or "").strip()

    complete_alternative_finder_search(
        session_state,
        entered_mpn=entered_mpn,
        canonical_mpn=entered_mpn,
        original_data=session_state.get("alternative_original_data") or {},
        original_risk=session_state.get("alternative_original_risk") or {},
        candidates=candidates,
        selected_candidate_mpn=selected_mpn,
        discovery_metadata=session_state.get("alternative_discovery_metadata") or {},
        lookup_error=str(session_state.get("alternative_original_lookup_error") or ""),
        search_error=str(session_state.get("alternative_search_error") or ""),
    )


def _sync_legacy_from_result(
    session_state: MutableMapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    session_state["suggested_alternatives"] = list(result.get("candidates") or [])
    session_state["alternative_search_attempted"] = True
    session_state["alternative_original_data"] = dict(result.get("original_data") or {})
    session_state["alternative_original_risk"] = dict(result.get("original_risk") or {})
    session_state["alternative_original_lookup_part"] = str(result.get("entered_mpn") or "")
    session_state["alternative_original_lookup_error"] = str(result.get("lookup_error") or "")
    session_state["alternative_search_error"] = str(result.get("search_error") or "")
    session_state["alternative_discovery_metadata"] = dict(
        result.get("discovery_metadata") or {}
    )
    session_state["alternative_result_algorithm_version"] = RESULT_ALGORITHM_VERSION
    entered_mpn = str(result.get("entered_mpn") or "")
    if entered_mpn:
        session_state["alternative_original_part"] = entered_mpn


def get_active_alternative_finder_result(
    session_state: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    result = session_state.get(ALT_FINDER_RESULT_KEY)
    if not isinstance(result, dict):
        return None
    if result.get("status") != STATUS_COMPLETED:
        return None
    return result


def get_alternative_finder_candidates(session_state: Mapping[str, Any]) -> list[dict[str, Any]]:
    active = get_active_alternative_finder_result(session_state)
    if active:
        return list(active.get("candidates") or [])
    legacy = session_state.get("suggested_alternatives") or []
    return list(legacy) if isinstance(legacy, list) else []


def get_alternative_finder_display_mpn(
    session_state: Mapping[str, Any],
    widget_value: Any = "",
) -> str:
    active = get_active_alternative_finder_result(session_state)
    if active:
        return str(active.get("entered_mpn") or "").strip()
    return str(widget_value or session_state.get("alternative_original_part") or "").strip()


def get_alternative_finder_original_data(session_state: Mapping[str, Any]) -> dict[str, Any]:
    active = get_active_alternative_finder_result(session_state)
    if active:
        return dict(active.get("original_data") or {})
    return dict(session_state.get("alternative_original_data") or {})


def get_alternative_finder_original_risk(session_state: Mapping[str, Any]) -> dict[str, Any]:
    active = get_active_alternative_finder_result(session_state)
    if active:
        return dict(active.get("original_risk") or {})
    return dict(session_state.get("alternative_original_risk") or {})


def get_alternative_finder_lookup_error(session_state: Mapping[str, Any]) -> str:
    active = get_active_alternative_finder_result(session_state)
    if active:
        return str(active.get("lookup_error") or "")
    return str(session_state.get("alternative_original_lookup_error") or "")


def get_alternative_finder_selected_candidate(
    session_state: Mapping[str, Any],
    *,
    fallback: str = "",
) -> str:
    active = get_active_alternative_finder_result(session_state)
    if active:
        selected = str(active.get("selected_candidate_mpn") or "").strip()
        if selected:
            return selected
    widget_selected = str(session_state.get("alternative_selected_candidate_62b") or "").strip()
    return widget_selected or fallback


def mark_alternative_finder_running(
    session_state: MutableMapping[str, Any],
    *,
    entered_mpn: str,
) -> None:
    session_state[ALT_FINDER_RESULT_KEY] = {
        "status": STATUS_RUNNING,
        "entered_mpn": entered_mpn,
        "algorithm_version": RESULT_ALGORITHM_VERSION,
    }


def complete_alternative_finder_search(
    session_state: MutableMapping[str, Any],
    *,
    entered_mpn: str,
    canonical_mpn: str,
    original_data: Mapping[str, Any],
    original_risk: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
    selected_candidate_mpn: str = "",
    discovery_metadata: Optional[Mapping[str, Any]] = None,
    lookup_error: str = "",
    search_error: str = "",
) -> dict[str, Any]:
    sanitized_candidates = sanitize_for_session(list(candidates or []))
    selected = selected_candidate_mpn.strip()
    if not selected and sanitized_candidates:
        selected = str(sanitized_candidates[0].get("Alternative Part") or "").strip()

    result = {
        "status": STATUS_COMPLETED,
        "algorithm_version": RESULT_ALGORITHM_VERSION,
        "entered_mpn": entered_mpn.strip(),
        "canonical_mpn": (canonical_mpn or entered_mpn).strip(),
        "original_data": sanitize_for_session(dict(original_data or {})),
        "original_risk": sanitize_for_session(dict(original_risk or {})),
        "candidates": sanitized_candidates,
        "selected_candidate_mpn": selected,
        "discovery_metadata": sanitize_for_session(dict(discovery_metadata or {})),
        "lookup_error": lookup_error.strip(),
        "search_error": search_error.strip(),
    }
    session_state[ALT_FINDER_RESULT_KEY] = result
    session_state["alternative_original_part"] = entered_mpn.strip()
    if selected:
        session_state["alternative_selected_candidate_62b"] = selected
    _sync_legacy_from_result(session_state, result)
    return result


def fail_alternative_finder_search(
    session_state: MutableMapping[str, Any],
    *,
    entered_mpn: str,
    search_error: str,
    lookup_error: str = "",
    original_data: Optional[Mapping[str, Any]] = None,
    original_risk: Optional[Mapping[str, Any]] = None,
) -> None:
    session_state[ALT_FINDER_RESULT_KEY] = {
        "status": STATUS_FAILED,
        "algorithm_version": RESULT_ALGORITHM_VERSION,
        "entered_mpn": entered_mpn.strip(),
        "search_error": search_error.strip(),
        "lookup_error": lookup_error.strip(),
        "original_data": sanitize_for_session(dict(original_data or {})),
        "original_risk": sanitize_for_session(dict(original_risk or {})),
        "candidates": [],
    }
    session_state["suggested_alternatives"] = []
    session_state["alternative_search_attempted"] = True
    session_state["alternative_search_error"] = search_error.strip()
    session_state["alternative_original_lookup_part"] = entered_mpn.strip()
    session_state["alternative_original_lookup_error"] = lookup_error.strip()
    session_state["alternative_original_data"] = dict(original_data or {})
    session_state["alternative_original_risk"] = dict(original_risk or {})


def set_alternative_finder_selected_candidate(
    session_state: MutableMapping[str, Any],
    candidate_mpn: str,
) -> None:
    selected = str(candidate_mpn or "").strip()
    if not selected:
        return
    session_state["alternative_selected_candidate_62b"] = selected
    result = session_state.get(ALT_FINDER_RESULT_KEY)
    if isinstance(result, dict) and result.get("status") == STATUS_COMPLETED:
        result["selected_candidate_mpn"] = selected


def should_start_new_alternative_search(
    session_state: Mapping[str, Any],
    submitted_mpn: str,
) -> bool:
    submitted = _normalize_mpn(submitted_mpn)
    if not submitted:
        return False
    active = get_active_alternative_finder_result(session_state)
    if not active:
        return True
    return _normalize_mpn(active.get("entered_mpn")) != submitted


def clear_alternative_finder_search(
    session_state: MutableMapping[str, Any],
    *,
    clear_widget: bool = True,
) -> None:
    session_state[ALT_FINDER_RESULT_KEY] = {
        "status": STATUS_IDLE,
        "algorithm_version": RESULT_ALGORITHM_VERSION,
    }
    for key in _LEGACY_KEYS:
        if key.endswith("_metadata"):
            session_state[key] = {}
        elif key.endswith("_attempted"):
            session_state[key] = False
        elif key.endswith("_error") or key.endswith("_part"):
            session_state[key] = ""
        else:
            session_state[key] = [] if key == "suggested_alternatives" else {}
    if clear_widget:
        session_state["alternative_original_part"] = ""
    session_state.pop("alternative_selected_candidate_62b", None)
    session_state.pop("alternative_compare_parts", None)
    session_state.pop("alternative_advanced_parts", None)


def mark_alternative_finder_nav_consumed(
    session_state: MutableMapping[str, Any],
    *,
    token: str,
) -> None:
    session_state[ALT_FINDER_NAV_CONSUMED_KEY] = token


def alternative_finder_nav_already_consumed(
    session_state: Mapping[str, Any],
    *,
    token: str,
) -> bool:
    return str(session_state.get(ALT_FINDER_NAV_CONSUMED_KEY) or "") == token


def should_apply_alternative_finder_prefill(
    session_state: Mapping[str, Any],
    *,
    mpn: str,
    analysis_id: str = "",
) -> bool:
    """Return True when navigation prefill should replace the current workspace."""
    token = f"{analysis_id}::{_normalize_mpn(mpn)}"
    if alternative_finder_nav_already_consumed(session_state, token=token):
        return False

    active = get_active_alternative_finder_result(session_state)
    if not active:
        return True
    return _normalize_mpn(active.get("entered_mpn")) != _normalize_mpn(mpn)
