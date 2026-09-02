"""Alternative Finder search timing and safe failure diagnostics."""
from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, MutableMapping

logger = logging.getLogger(__name__)

STAGE_ORIGINAL_LOOKUP = "original_lookup"
STAGE_DISCOVERY = "digikey_discovery"
STAGE_CANDIDATE_ENGINE = "candidate_engine"
STAGE_SELECTED_ENRICHMENT = "selected_candidate_enrichment"
STAGE_PERSIST = "persist_results"

ENRICHED_SELECTED_CACHE_KEY = "alternative_finder_enriched_selected"

_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*\S+"
)
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-z0-9._\-+/=]{8,}")


def _redact_secrets(message: str) -> str:
    text = str(message or "")
    text = _SECRET_PATTERN.sub(r"\1=<redacted>", text)
    text = _BEARER_PATTERN.sub("Bearer <redacted>", text)
    return text.strip()


def _truncate(message: str, limit: int = 240) -> str:
    text = str(message or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def sanitize_search_diagnostic(
    exc: BaseException,
    *,
    provider: str = "",
    operation: str = "",
) -> dict[str, str]:
    """Return a concise, UI-safe diagnostic payload for failed searches."""
    exc_type = type(exc).__name__
    raw_message = _redact_secrets(str(exc) or exc_type)
    lowered = raw_message.casefold()

    if "timeout" in lowered or "timed out" in lowered:
        code = "supplier_timeout"
    elif exc_type in {"RecursionError", "MemoryError"}:
        code = "internal_error"
    elif "not configured" in lowered or "missing required configuration" in lowered:
        code = "supplier_not_configured"
    elif provider:
        code = f"{provider.lower()}_lookup_failed"
    else:
        code = "alternative_search_failed"

    message = _truncate(raw_message or exc_type)
    if provider and operation:
        message = _truncate(f"{provider} {operation}: {message}")

    return {
        "diagnostic_code": code,
        "diagnostic_message": message,
        "exception_type": exc_type,
    }


class AlternativeFinderSearchRun:
    """Collect per-stage timings for one Alternative Finder search."""

    def __init__(self) -> None:
        self._started = time.perf_counter()
        self.stages_ms: dict[str, float] = {}
        self.provider = ""
        self.operation = ""

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._started) * 1000.0, 1)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.stages_ms[name] = round((time.perf_counter() - started) * 1000.0, 1)

    def timing_breakdown(self) -> dict[str, Any]:
        total = round(sum(self.stages_ms.values()), 1)
        return {
            "stages_ms": dict(self.stages_ms),
            "total_ms": total,
            "elapsed_ms": self.elapsed_ms(),
        }

    def log_failure(self, exc: BaseException) -> dict[str, str]:
        diagnostic = sanitize_search_diagnostic(
            exc,
            provider=self.provider,
            operation=self.operation,
        )
        logger.exception(
            "Alternative Finder search failed after %.1fms "
            "(provider=%s operation=%s code=%s type=%s message=%s stages=%s)",
            self.elapsed_ms(),
            self.provider or "unknown",
            self.operation or "unknown",
            diagnostic["diagnostic_code"],
            diagnostic["exception_type"],
            diagnostic["diagnostic_message"],
            self.stages_ms,
        )
        return diagnostic

    def log_stage_warning(self, exc: BaseException, *, stage: str) -> None:
        logger.warning(
            "Alternative Finder stage %s failed after %.1fms (type=%s): %s",
            stage,
            self.elapsed_ms(),
            type(exc).__name__,
            _truncate(_redact_secrets(str(exc) or type(exc).__name__)),
            exc_info=exc,
        )


def attach_failure_diagnostics(
    session_state: MutableMapping[str, Any],
    *,
    diagnostic: Mapping[str, str],
    stage_timings_ms: Mapping[str, float] | None = None,
) -> None:
    """Persist safe diagnostics on the durable failed result object."""
    result = session_state.get("alternative_finder_result")
    if not isinstance(result, dict):
        return
    result["diagnostic_code"] = str(diagnostic.get("diagnostic_code") or "").strip()
    result["diagnostic_message"] = str(diagnostic.get("diagnostic_message") or "").strip()
    result["exception_type"] = str(diagnostic.get("exception_type") or "").strip()
    if stage_timings_ms:
        result["stage_timings_ms"] = {
            str(stage): float(duration)
            for stage, duration in stage_timings_ms.items()
        }


def _enrichment_cache_key(search_mpn: str, selected_mpn: str) -> str:
    return f"{str(search_mpn or '').strip().upper()}::{str(selected_mpn or '').strip().upper()}"


def _get_enrichment_cache(session_state: MutableMapping[str, Any]) -> dict[str, dict[str, Any]]:
    cache = session_state.get(ENRICHED_SELECTED_CACHE_KEY)
    if not isinstance(cache, dict):
        cache = {}
        session_state[ENRICHED_SELECTED_CACHE_KEY] = cache
    return cache


def clear_selected_candidate_enrichment_cache(session_state: MutableMapping[str, Any]) -> None:
    session_state.pop(ENRICHED_SELECTED_CACHE_KEY, None)


def _is_streamlit_control_flow(exc: BaseException) -> bool:
    return type(exc).__name__ in {"RerunException", "StopException"}


def collect_provider_failure_names(
    *,
    discovery_metadata: Mapping[str, Any] | None = None,
    original_data: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return configured supplier sources that failed during lookup or discovery."""
    failures: list[str] = []
    seen: set[str] = set()
    for name in (discovery_metadata or {}).get("provider_failures") or []:
        text = str(name).strip()
        if text and text not in seen:
            seen.add(text)
            failures.append(text)
    for row in (original_data or {}).get("all_supplier_results") or []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "").strip()
        status = str(row.get("provider_status") or "").strip().upper()
        if source and status in {"TIMEOUT", "RATE_LIMITED", "PROVIDER_ERROR"} and source not in seen:
            seen.add(source)
            failures.append(source)
    return failures


def merge_supplier_failures_into_discovery(
    discovery_metadata: Mapping[str, Any] | None,
    original_data: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Attach lookup failures from the original supplier aggregation to discovery metadata."""
    discovery = dict(discovery_metadata or {})
    failures = collect_provider_failure_names(
        discovery_metadata=discovery,
        original_data=original_data,
    )
    if failures:
        discovery["provider_failures"] = failures
        discovery["has_incomplete_evidence"] = True
    return discovery


def run_alternative_finder_search(
    session_state: MutableMapping[str, Any],
    searched_part: str,
    *,
    original_lookup: Mapping[str, Any] | None = None,
    original_risk: Mapping[str, Any] | None = None,
    lookup_error: str = "",
) -> dict[str, Any]:
    """Execute Alternative Finder search stages and persist durable session results."""
    from integrations.supplier_aggregator import get_best_part_data
    from integrations.stock_coercion import coerce_stock_total
    from src.alternative_engine import get_alternative_discovery_metadata, suggest_alternatives_v2
    from src.alternative_finder_state import complete_alternative_finder_search, fail_alternative_finder_search
    from src.risk_engine import calculate_risk

    search_run = AlternativeFinderSearchRun()
    entered_mpn = str(searched_part or "").strip()
    safe_original: dict = dict(original_lookup or {})
    safe_risk: dict = dict(original_risk or {})
    safe_lookup_error = str(lookup_error or "")

    if not safe_original:
        try:
            with search_run.stage(STAGE_ORIGINAL_LOOKUP):
                search_run.operation = "lookup"
                search_run.provider = "aggregator"
                safe_original = get_best_part_data(entered_mpn) or {}
            if not isinstance(safe_original, dict):
                safe_original = {}
            if safe_original.get("stock_total") is not None:
                safe_original["stock_total"] = coerce_stock_total(safe_original.get("stock_total"))
            try:
                safe_risk = calculate_risk(safe_original) or {}
            except Exception:
                safe_risk = {}
            if not safe_original.get("supplier_data_verified"):
                safe_lookup_error = (
                    f'No exact supplier match was found for "{entered_mpn}". '
                    "Enter the complete manufacturer part number, including package or suffix where applicable."
                )
        except Exception as original_exc:
            if _is_streamlit_control_flow(original_exc):
                raise
            safe_original = {}
            safe_risk = {}
            safe_lookup_error = (
                "Some original-component details are temporarily unavailable. "
                "You can still review the available replacement evidence."
            )
            search_run.log_stage_warning(original_exc, stage=STAGE_ORIGINAL_LOOKUP)

    try:
        candidates: list = []
        discovery: dict = {}
        if safe_original.get("supplier_data_verified"):
            with search_run.stage(STAGE_CANDIDATE_ENGINE):
                search_run.operation = "suggest_alternatives_v2"
                search_run.provider = "digikey"
                candidates = suggest_alternatives_v2(entered_mpn) or []
            discovery = get_alternative_discovery_metadata() or {}
        discovery = merge_supplier_failures_into_discovery(discovery, safe_original)
        with search_run.stage(STAGE_PERSIST):
            canonical_mpn = str(
                safe_original.get("manufacturer_part_number") or entered_mpn
            ).strip()
            complete_alternative_finder_search(
                session_state,
                entered_mpn=entered_mpn,
                canonical_mpn=canonical_mpn,
                original_data=safe_original,
                original_risk=safe_risk,
                candidates=candidates,
                discovery_metadata=discovery,
                lookup_error=safe_lookup_error,
                search_error="",
            )
        return {
            "status": "completed",
            "candidate_count": len(candidates),
            "stage_timings_ms": dict(search_run.stages_ms),
            "discovery_metadata": discovery,
        }
    except Exception as search_exc:
        if _is_streamlit_control_flow(search_exc):
            raise
        diagnostic = search_run.log_failure(search_exc)
        fail_alternative_finder_search(
            session_state,
            entered_mpn=entered_mpn,
            search_error=(
                "Cadivor could not complete the supplier search right now. "
                "Please try again in a moment."
            ),
            lookup_error=safe_lookup_error,
            original_data=safe_original,
            original_risk=safe_risk,
            diagnostic_code=diagnostic["diagnostic_code"],
            diagnostic_message=diagnostic["diagnostic_message"],
            exception_type=diagnostic["exception_type"],
            stage_timings_ms=search_run.stages_ms,
        )
        attach_failure_diagnostics(
            session_state,
            diagnostic=diagnostic,
            stage_timings_ms=search_run.stages_ms,
        )
        return {
            "status": "failed",
            "diagnostic": diagnostic,
            "stage_timings_ms": dict(search_run.stages_ms),
        }


def get_or_enrich_selected_candidate(
    session_state: MutableMapping[str, Any],
    *,
    search_mpn: str,
    original_data: Mapping[str, Any],
    candidate_row: Mapping[str, Any],
    selected_mpn: str,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Enrich the selected candidate once per search/selection for initial render.

    Returns `(enriched_candidate, supplier_evidence, performed_lookup)`.
    Session caching prevents repeat supplier calls on ordinary reruns.
    """
    from integrations.supplier_aggregator import get_best_part_data
    from src.alternative_engine import (
        _enrich_part_data_from_suppliers,
        apply_supplier_enrichment_to_candidate,
    )

    cache_key = _enrichment_cache_key(search_mpn, selected_mpn)
    cache = _get_enrichment_cache(session_state)
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and isinstance(cached.get("candidate"), dict):
        supplier_evidence = cached.get("supplier_evidence")
        return (
            dict(cached["candidate"]),
            dict(supplier_evidence) if isinstance(supplier_evidence, dict) else {},
            False,
        )

    supplier_evidence = {}
    try:
        supplier_evidence = _enrich_part_data_from_suppliers(get_best_part_data(selected_mpn) or {})
    except Exception as enrich_exc:
        logger.warning(
            "Alternative Finder selected-candidate enrichment failed for %s: %s",
            selected_mpn,
            _truncate(_redact_secrets(str(enrich_exc) or type(enrich_exc).__name__)),
            exc_info=enrich_exc,
        )
    canonical_part_number = str(
        original_data.get("manufacturer_part_number") or search_mpn or selected_mpn
    ).strip()
    enriched = apply_supplier_enrichment_to_candidate(
        original_data=dict(original_data or {}),
        candidate=dict(candidate_row or {}),
        candidate_supplier_data=supplier_evidence,
        canonical_part_number=canonical_part_number,
    )
    cache[cache_key] = {
        "candidate": enriched,
        "supplier_evidence": supplier_evidence,
    }
    return enriched, supplier_evidence, True
