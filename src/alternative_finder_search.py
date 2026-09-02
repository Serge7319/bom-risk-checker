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

    supplier_evidence = _enrich_part_data_from_suppliers(get_best_part_data(selected_mpn) or {})
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
