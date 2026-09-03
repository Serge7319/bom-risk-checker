"""Durable Alternative Finder session-state helpers for Streamlit reruns."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, MutableMapping, Optional

ALT_FINDER_RESULT_KEY = "alternative_finder_result"
ALT_FINDER_NAV_CONSUMED_KEY = "alternative_finder_nav_consumed_token"
# Widget-bound text input key. Never assign to this after the widget is created.
ALTERNATIVE_ORIGINAL_PART_WIDGET_KEY = "alternative_original_part"
# Durable non-widget store for the MPN used by the completed/failed search.
ALTERNATIVE_COMPLETED_ORIGINAL_PART_KEY = "alternative_completed_original_part"
RESULT_ALGORITHM_VERSION = "supplier-evidence-v4"

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

OUTCOME_SUCCESS = "success"
OUTCOME_PARTIAL_SUCCESS = "partial_success"
OUTCOME_FAILURE = "failure"

TERMINAL_SEARCH_ERROR_MESSAGE = (
    "Cadivor could not complete the supplier search right now. "
    "Please try again in a moment."
)

MAX_SANITIZE_DEPTH = 64
MARKER_CIRCULAR_REF = "<circular-reference>"
MARKER_MAX_DEPTH = "<max-depth-exceeded>"
MARKER_NON_SERIALIZABLE = "<non-serializable-object>"

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


def _sanitize_path(parent: str, segment: str) -> str:
    if not parent or parent == "root":
        return segment
    return f"{parent}.{segment}"


def _record_sanitize_issue(kind: str, path: str) -> str:
    marker = {
        "circular": MARKER_CIRCULAR_REF,
        "depth": MARKER_MAX_DEPTH,
        "non_serializable": MARKER_NON_SERIALIZABLE,
    }.get(kind, MARKER_NON_SERIALIZABLE)
    return f"{marker} at {path}"


def _sanitize_scalar(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return repr(value)
    try:
        return str(value)
    except Exception:
        return _record_sanitize_issue("non_serializable", path)


def sanitize_for_session(
    value: Any,
    *,
    _seen: Optional[set[int]] = None,
    _depth: int = 0,
    _path: str = "root",
) -> Any:
    """Make nested candidate payloads safe for Streamlit session persistence."""
    if _depth >= MAX_SANITIZE_DEPTH:
        return _record_sanitize_issue("depth", _path)

    if isinstance(value, (type(None), bool, int, float, str)):
        return value

    if isinstance(value, (datetime, date, Decimal, bytes)):
        return _sanitize_scalar(value, path=_path)

    if isinstance(value, Mapping):
        seen = _seen or set()
        obj_id = id(value)
        if obj_id in seen:
            return _record_sanitize_issue("circular", _path)
        seen = set(seen)
        seen.add(obj_id)
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            item_path = _sanitize_path(_path, key)
            sanitized[key] = sanitize_for_session(
                item,
                _seen=seen,
                _depth=_depth + 1,
                _path=item_path,
            )
        return sanitized

    if isinstance(value, set):
        seen = _seen or set()
        obj_id = id(value)
        if obj_id in seen:
            return _record_sanitize_issue("circular", _path)
        seen = set(seen)
        seen.add(obj_id)
        items = sorted(
            (
                sanitize_for_session(
                    item,
                    _seen=seen,
                    _depth=_depth + 1,
                    _path=f"{_path}[]",
                )
                for item in value
            ),
            key=lambda item: repr(item),
        )
        return items

    if isinstance(value, (list, tuple)):
        seen = _seen or set()
        obj_id = id(value)
        if obj_id in seen:
            return _record_sanitize_issue("circular", _path)
        seen = set(seen)
        seen.add(obj_id)
        return [
            sanitize_for_session(
                item,
                _seen=seen,
                _depth=_depth + 1,
                _path=f"{_path}[{index}]",
            )
            for index, item in enumerate(value)
        ]

    return _sanitize_scalar(value, path=_path)


def _safe_sanitize_mapping(value: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not value:
        return {}
    try:
        sanitized = sanitize_for_session(value)
    except RecursionError:
        return {_record_sanitize_issue("circular", "root"): True}
    except Exception:
        return {MARKER_NON_SERIALIZABLE: True}
    return sanitized if isinstance(sanitized, dict) else {MARKER_NON_SERIALIZABLE: True}


def _safe_sanitize_list(value: Optional[list[Any]]) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        sanitized = sanitize_for_session(list(value))
    except RecursionError:
        return [{MARKER_CIRCULAR_REF: True}]
    except Exception:
        return [{MARKER_NON_SERIALIZABLE: True}]
    if not isinstance(sanitized, list):
        return [{MARKER_NON_SERIALIZABLE: True}]
    return [row for row in sanitized if isinstance(row, dict)]


def _ensure_legacy_defaults(session_state: MutableMapping[str, Any]) -> None:
    """Ensure legacy Alternative Finder keys exist on brand-new or partial sessions."""
    for key in _LEGACY_KEYS:
        if key in session_state:
            continue
        if key.endswith("_metadata"):
            session_state[key] = {}
        elif key.endswith("_attempted"):
            session_state[key] = False
        elif key.endswith("_error") or key == "alternative_original_lookup_part":
            session_state[key] = ""
        elif key == "suggested_alternatives":
            session_state[key] = []
        else:
            session_state[key] = {}


def alternative_search_was_attempted(session_state: Mapping[str, Any]) -> bool:
    """Return True when a search has been attempted according to durable result state."""
    result = session_state.get(ALT_FINDER_RESULT_KEY)
    if isinstance(result, dict):
        status = str(result.get("status") or STATUS_IDLE)
        if status == STATUS_IDLE:
            return False
        if status in {STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED}:
            return True
    return bool(session_state.get("alternative_search_attempted", False))


def _store_completed_original_part(
    session_state: MutableMapping[str, Any],
    entered_mpn: str,
) -> None:
    """Persist the searched MPN without touching the text-input widget key."""
    value = str(entered_mpn or "").strip()
    session_state[ALTERNATIVE_COMPLETED_ORIGINAL_PART_KEY] = value
    session_state["alternative_original_lookup_part"] = value


def init_alternative_finder_state(session_state: MutableMapping[str, Any]) -> None:
    """Initialize Alternative Finder keys and migrate legacy session payloads."""
    session_state.setdefault(ALTERNATIVE_ORIGINAL_PART_WIDGET_KEY, "")
    session_state.setdefault(ALTERNATIVE_COMPLETED_ORIGINAL_PART_KEY, "")
    session_state.setdefault("alternative_candidate_shortlist", [])
    session_state.setdefault("alternative_engineering_decisions", {})
    session_state.setdefault("alternative_decision_notes", {})
    session_state.setdefault("alternative_decision_db_status", "")
    session_state.setdefault("alternative_decision_db_error", "")
    session_state.setdefault("alternative_decision_flash", "")
    _ensure_legacy_defaults(session_state)

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

    if result.get("status") == STATUS_IDLE:
        session_state["alternative_search_attempted"] = False
        return

    if result.get("status") == STATUS_COMPLETED:
        _sync_legacy_from_result(session_state, result)
        return

    if result.get("status") == STATUS_FAILED:
        session_state["alternative_search_attempted"] = True
        return

    if result.get("status") == STATUS_RUNNING:
        session_state["alternative_search_attempted"] = True
        return

    if session_state.get("alternative_search_attempted") and session_state.get("suggested_alternatives"):
        _migrate_legacy_completed_search(session_state)


def _migrate_legacy_completed_search(session_state: MutableMapping[str, Any]) -> None:
    entered_mpn = str(session_state.get(ALTERNATIVE_COMPLETED_ORIGINAL_PART_KEY) or "").strip()
    if not entered_mpn:
        entered_mpn = str(session_state.get("alternative_original_lookup_part") or "").strip()
    if not entered_mpn:
        # Widget value is a last-resort migration source only; never write back to it here.
        entered_mpn = str(session_state.get(ALTERNATIVE_ORIGINAL_PART_WIDGET_KEY) or "").strip()
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


def resolve_search_outcome(
    candidates: list[Any],
    *,
    has_incomplete_evidence: bool = False,
    persist_issue: bool = False,
) -> str:
    if not candidates:
        return OUTCOME_FAILURE
    if has_incomplete_evidence or persist_issue:
        return OUTCOME_PARTIAL_SUCCESS
    return OUTCOME_SUCCESS


def clear_alternative_finder_search_errors(session_state: MutableMapping[str, Any]) -> None:
    session_state["alternative_search_error"] = ""


def get_alternative_finder_durable_result(
    session_state: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    result = session_state.get(ALT_FINDER_RESULT_KEY)
    if not isinstance(result, dict):
        return None
    status = str(result.get("status") or STATUS_IDLE)
    if status in {STATUS_COMPLETED, STATUS_FAILED}:
        return result
    return None


def get_alternative_finder_outcome(session_state: Mapping[str, Any]) -> str:
    result = get_alternative_finder_durable_result(session_state)
    if not result:
        return ""
    outcome = str(result.get("search_outcome") or "").strip()
    if outcome:
        return outcome
    if result.get("status") == STATUS_FAILED:
        return OUTCOME_FAILURE
    if result.get("status") == STATUS_COMPLETED:
        return OUTCOME_SUCCESS
    return ""


def should_show_terminal_search_error(session_state: Mapping[str, Any]) -> bool:
    if get_alternative_finder_candidates(session_state):
        return False
    outcome = get_alternative_finder_outcome(session_state)
    if outcome and outcome != OUTCOME_FAILURE:
        return False
    result = get_alternative_finder_durable_result(session_state)
    if result and str(result.get("search_error") or "").strip():
        return True
    return bool(str(session_state.get("alternative_search_error") or "").strip())


def _sync_legacy_from_result(
    session_state: MutableMapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    session_state["suggested_alternatives"] = list(result.get("candidates") or [])
    session_state["alternative_search_attempted"] = True
    session_state["alternative_original_data"] = dict(result.get("original_data") or {})
    session_state["alternative_original_risk"] = dict(result.get("original_risk") or {})
    session_state["alternative_original_lookup_error"] = str(result.get("lookup_error") or "")
    outcome = str(result.get("search_outcome") or "").strip()
    if not outcome and result.get("status") == STATUS_FAILED:
        outcome = OUTCOME_FAILURE
    if outcome in {OUTCOME_SUCCESS, OUTCOME_PARTIAL_SUCCESS}:
        session_state["alternative_search_error"] = ""
    else:
        session_state["alternative_search_error"] = str(result.get("search_error") or "")
    session_state["alternative_discovery_metadata"] = dict(
        result.get("discovery_metadata") or {}
    )
    session_state["alternative_result_algorithm_version"] = RESULT_ALGORITHM_VERSION
    entered_mpn = str(result.get("entered_mpn") or "")
    if entered_mpn:
        # Keep the text-input widget as the live user-entry source of truth.
        # Completed-search MPN lives on a separate non-widget key.
        _store_completed_original_part(session_state, entered_mpn)


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
    result = session_state.get(ALT_FINDER_RESULT_KEY)
    if isinstance(result, dict):
        stored = list(result.get("candidates") or [])
        if stored:
            return stored
    legacy = session_state.get("suggested_alternatives") or []
    return list(legacy) if isinstance(legacy, list) else []


def get_alternative_finder_display_mpn(
    session_state: Mapping[str, Any],
    widget_value: Any = "",
) -> str:
    active = get_active_alternative_finder_result(session_state)
    if active:
        return str(active.get("entered_mpn") or "").strip()
    completed = str(session_state.get(ALTERNATIVE_COMPLETED_ORIGINAL_PART_KEY) or "").strip()
    if completed:
        return completed
    lookup = str(session_state.get("alternative_original_lookup_part") or "").strip()
    if lookup:
        return lookup
    return str(widget_value or session_state.get(ALTERNATIVE_ORIGINAL_PART_WIDGET_KEY) or "").strip()


def get_alternative_finder_discovery_metadata(
    session_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Return discovery metadata from the durable result, falling back to the session mirror."""
    active = get_active_alternative_finder_result(session_state)
    if active:
        discovery = active.get("discovery_metadata")
        if isinstance(discovery, dict):
            return dict(discovery)
    result = session_state.get(ALT_FINDER_RESULT_KEY)
    if isinstance(result, dict):
        discovery = result.get("discovery_metadata")
        if isinstance(discovery, dict):
            return dict(discovery)
    return dict(session_state.get("alternative_discovery_metadata") or {})


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
    clear_alternative_finder_search_errors(session_state)
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
    search_outcome: str = "",
    persist_diagnostic: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    sanitized_candidates = _safe_sanitize_list(list(candidates or []))
    selected = selected_candidate_mpn.strip()
    if not selected and sanitized_candidates:
        selected = str(sanitized_candidates[0].get("Alternative Part") or "").strip()

    discovery = dict(discovery_metadata or {})
    resolved_outcome = str(search_outcome or "").strip()
    if not resolved_outcome:
        resolved_outcome = resolve_search_outcome(
            sanitized_candidates,
            has_incomplete_evidence=bool(discovery.get("has_incomplete_evidence")),
            persist_issue=bool(persist_diagnostic),
        )

    result = {
        "status": STATUS_COMPLETED,
        "algorithm_version": RESULT_ALGORITHM_VERSION,
        "entered_mpn": entered_mpn.strip(),
        "canonical_mpn": (canonical_mpn or entered_mpn).strip(),
        "original_data": _safe_sanitize_mapping(original_data),
        "original_risk": _safe_sanitize_mapping(original_risk),
        "candidates": sanitized_candidates,
        "selected_candidate_mpn": selected,
        "discovery_metadata": _safe_sanitize_mapping(discovery),
        "lookup_error": lookup_error.strip(),
        "search_error": "",
        "search_outcome": resolved_outcome,
    }
    if persist_diagnostic:
        for key in (
            "diagnostic_code",
            "diagnostic_message",
            "exception_type",
            "failed_stage",
        ):
            value = str(persist_diagnostic.get(key) or "").strip()
            if value:
                result[key] = value
    session_state[ALT_FINDER_RESULT_KEY] = result
    # Do not assign alternative_original_part here: that key is bound to the
    # search text_input widget and Streamlit forbids mutation after instantiation.
    _store_completed_original_part(session_state, entered_mpn)
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
    candidates: Optional[list[Mapping[str, Any]]] = None,
    discovery_metadata: Optional[Mapping[str, Any]] = None,
    diagnostic_code: str = "",
    diagnostic_message: str = "",
    exception_type: str = "",
    failed_stage: str = "",
    stage_timings_ms: Optional[Mapping[str, float]] = None,
) -> None:
    safe_original_data = _safe_sanitize_mapping(original_data)
    safe_original_risk = _safe_sanitize_mapping(original_risk)
    sanitized_candidates = _safe_sanitize_list(list(candidates or []))
    if sanitized_candidates:
        persist_diagnostic = {
            "diagnostic_code": diagnostic_code.strip(),
            "diagnostic_message": diagnostic_message.strip(),
            "exception_type": exception_type.strip(),
            "failed_stage": failed_stage.strip(),
        }
        complete_alternative_finder_search(
            session_state,
            entered_mpn=entered_mpn,
            canonical_mpn=entered_mpn,
            original_data=safe_original_data,
            original_risk=safe_original_risk,
            candidates=sanitized_candidates,
            discovery_metadata=discovery_metadata,
            lookup_error=lookup_error,
            search_outcome=OUTCOME_PARTIAL_SUCCESS,
            persist_diagnostic=persist_diagnostic,
        )
        result = session_state.get(ALT_FINDER_RESULT_KEY)
        if isinstance(result, dict) and stage_timings_ms:
            result["stage_timings_ms"] = {
                str(stage): float(duration)
                for stage, duration in stage_timings_ms.items()
            }
        return

    failed_result: dict[str, Any] = {
        "status": STATUS_FAILED,
        "algorithm_version": RESULT_ALGORITHM_VERSION,
        "entered_mpn": entered_mpn.strip(),
        "search_error": search_error.strip() or TERMINAL_SEARCH_ERROR_MESSAGE,
        "lookup_error": lookup_error.strip(),
        "original_data": safe_original_data,
        "original_risk": safe_original_risk,
        "candidates": [],
        "discovery_metadata": _safe_sanitize_mapping(discovery_metadata),
        "search_outcome": OUTCOME_FAILURE,
    }
    if diagnostic_code.strip():
        failed_result["diagnostic_code"] = diagnostic_code.strip()
    if diagnostic_message.strip():
        failed_result["diagnostic_message"] = diagnostic_message.strip()
    if exception_type.strip():
        failed_result["exception_type"] = exception_type.strip()
    if failed_stage.strip():
        failed_result["failed_stage"] = failed_stage.strip()
    if stage_timings_ms:
        failed_result["stage_timings_ms"] = {
            str(stage): float(duration)
            for stage, duration in stage_timings_ms.items()
        }
    session_state[ALT_FINDER_RESULT_KEY] = failed_result
    session_state["suggested_alternatives"] = sanitized_candidates
    session_state["alternative_search_attempted"] = True
    session_state["alternative_search_error"] = search_error.strip()
    _store_completed_original_part(session_state, entered_mpn)
    session_state["alternative_original_lookup_error"] = lookup_error.strip()
    session_state["alternative_original_data"] = safe_original_data
    session_state["alternative_original_risk"] = safe_original_risk


def set_alternative_finder_selected_candidate(
    session_state: MutableMapping[str, Any],
    candidate_mpn: str,
) -> None:
    """Seed or update the selected candidate before the selectbox widget renders."""
    selected = str(candidate_mpn or "").strip()
    if not selected:
        return
    session_state["alternative_selected_candidate_62b"] = selected
    sync_alternative_finder_selected_candidate_result(session_state, selected)


def sync_alternative_finder_selected_candidate_result(
    session_state: MutableMapping[str, Any],
    candidate_mpn: str,
) -> None:
    """Persist the selected candidate on the durable result without touching widget keys."""
    selected = str(candidate_mpn or "").strip()
    if not selected:
        return
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
    session_state[ALTERNATIVE_COMPLETED_ORIGINAL_PART_KEY] = ""
    if clear_widget:
        session_state[ALTERNATIVE_ORIGINAL_PART_WIDGET_KEY] = ""
    session_state.pop("alternative_selected_candidate_62b", None)
    session_state.pop("alternative_compare_parts", None)
    session_state.pop("alternative_advanced_parts", None)
    session_state.pop("alternative_finder_enriched_selected", None)


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
