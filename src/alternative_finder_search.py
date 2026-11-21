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


_SUPPLEMENT_KEYS = (
    "package",
    "pin_count",
    "mounting_style",
    "voltage_range",
    "temperature_range",
    "channel_count",
    "architecture",
    "lead_time_weeks",
    "datasheet_url",
    "product_detail_url",
    "bandwidth_mhz",
    "slew_rate_v_us",
    "input_offset_mv",
    "input_bias_na",
    "quiescent_current_ma",
    "gbw_mhz",
)


def _evidence_present(key: str, value: Any) -> bool:
    if value is None:
        return False
    if key in {"pin_count", "channel_count"}:
        try:
            return int(float(value)) > 0
        except (TypeError, ValueError):
            return False
    if key == "lead_time_weeks":
        try:
            float(value)
        except (TypeError, ValueError):
            return False
        return True
    if key == "unit_price":
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False
    return bool(str(value).strip())


def _supplement_resolved_part_evidence(part: dict) -> dict:
    """Fill empty original attributes from an exact DigiKey record of the resolved MPN."""
    if not isinstance(part, dict) or not part:
        return part
    canonical = str(part.get("manufacturer_part_number") or "").strip()
    if not canonical:
        return part
    sources = dict(part.get("field_sources") or {})
    notes = dict(part.get("field_source_notes") or {})
    primary = str(part.get("source") or "Supplier")
    for key in _SUPPLEMENT_KEYS:
        if _evidence_present(key, part.get(key)):
            sources.setdefault(key, primary)
    try:
        from integrations.digikey_client import search_digikey_by_part_number

        extra = search_digikey_by_part_number(canonical) or {}
    except Exception:
        extra = {}
    if str(extra.get("manufacturer_part_number") or "").strip().casefold() != canonical.casefold():
        extra = {}
    for key in _SUPPLEMENT_KEYS:
        if not _evidence_present(key, extra.get(key)):
            continue
        if not _evidence_present(key, part.get(key)):
            part[key] = extra.get(key)
            sources[key] = "DigiKey"
            continue
        current = str(part.get(key)).strip()
        incoming = str(extra.get(key)).strip()
        if current.casefold() != incoming.casefold() and sources.get(key) != "DigiKey":
            notes[key] = f"DigiKey also recorded {incoming}."
    part["field_sources"] = sources
    if notes:
        part["field_source_notes"] = notes
    return part


def _replacement_candidate_cause(discovery: Mapping[str, Any]) -> str:
    """Describe an empty replacement search from the supplier response."""
    messages: list[str] = []
    failures = discovery.get("provider_failures") or []
    if isinstance(failures, list):
        for item in failures:
            if isinstance(item, Mapping):
                text = str(item.get("message") or item.get("error") or "").strip()
            else:
                text = str(item or "").strip()
            if text and text not in messages:
                messages.append(_truncate(_redact_secrets(text), 180))
    providers = discovery.get("providers") or {}
    if isinstance(providers, Mapping):
        for name, status in providers.items():
            if not isinstance(status, Mapping):
                continue
            text = str(status.get("message") or "").strip()
            if text and text not in messages:
                messages.append(f"{name}: {_truncate(_redact_secrets(text), 160)}")
    if messages:
        return "No replacement candidates were returned. " + " ".join(messages[:3])
    return "No replacement candidates were returned for this part."


def replacement_search_empty_state(
    discovery_metadata: Mapping[str, Any] | None = None,
    *,
    lookup_error: str = "",
    search_error: str = "",
) -> tuple[str, str]:
    """Explain an empty search without presenting provider exceptions as findings.

    A timed-out catalog is incomplete evidence, not proof that no replacement
    exists. Keep supplier names and the failure class, but leave raw transport
    errors in the correlated server diagnostics.
    """
    if str(lookup_error or "").strip():
        discovery = discovery_metadata if isinstance(discovery_metadata, Mapping) else {}
        providers = discovery.get("providers")
        providers = providers if isinstance(providers, Mapping) else {}
        catalog_searches = []
        for name, status in providers.items():
            if not isinstance(status, Mapping):
                continue
            catalog_status = str(status.get("catalog") or "").strip().casefold()
            if catalog_status not in {"ok", "available"}:
                continue
            family_status = str(status.get("family_search") or "").strip().casefold()
            scope = "catalog and family" if family_status in {"ok", "available"} else "catalog"
            catalog_searches.append(f"{name} {scope}")
        if catalog_searches:
            searched = ", ".join(catalog_searches)
            return (
                "Source part needs verification",
                f"Supplier records could not verify the exact source MPN. Cadivor searched {searched} and found only discovery leads or no candidates; this does not validate the source identity or prove that no compatible replacement exists. Confirm the source part against its manufacturer documentation before approval.",
            )
        return (
            "Source part needs verification",
            "Supplier records could not verify the source part. Confirm the MPN and try again; "
            "this does not confirm that no replacement exists.",
        )
    if str(search_error or "").strip():
        return (
            "Supplier search did not complete",
            "Cadivor could not complete the supplier search. Retry in a moment. "
            "This result does not confirm that no replacement exists.",
        )

    discovery = discovery_metadata if isinstance(discovery_metadata, Mapping) else {}
    providers = discovery.get("providers")
    providers = providers if isinstance(providers, Mapping) else {}
    failed_sources: list[str] = []
    not_configured: list[str] = []

    from integrations.supplier_diagnostics import (
        CATEGORY_AUTHENTICATION,
        CATEGORY_CONFIGURATION,
        CATEGORY_RATE_LIMIT,
        CATEGORY_TIMEOUT,
        categorize_supplier_failure,
    )

    explicit_failures = {
        str(item.get("source") or item.get("supplier") or "").strip().casefold()
        if isinstance(item, Mapping)
        else str(item or "").strip().casefold()
        for item in discovery.get("provider_failures") or []
    }
    for source, raw_status in providers.items():
        if not isinstance(raw_status, Mapping):
            continue
        name = str(source or "Supplier").strip()
        message = str(raw_status.get("message") or "").strip()
        statuses = [
            str(raw_status.get(key) or "").strip().casefold()
            for key in ("substitutions", "catalog", "lookup")
        ]
        if "not_configured" in statuses:
            not_configured.append(name)
            continue
        failure = bool(
            name.casefold() in explicit_failures
            or any(status in {"error", "timeout", "failed", "rate_limited"} for status in statuses)
        )
        if not failure:
            continue
        category = categorize_supplier_failure(
            provider_status="PROVIDER_ERROR",
            error_message=message,
        )
        if category == CATEGORY_TIMEOUT:
            label = f"{name} timed out"
        elif category == CATEGORY_RATE_LIMIT:
            label = f"{name} was rate limited"
        elif category == CATEGORY_AUTHENTICATION:
            label = f"{name} could not authenticate"
        elif category == CATEGORY_CONFIGURATION:
            not_configured.append(name)
            continue
        else:
            label = f"{name} did not respond"
        failed_sources.append(label)

    if failed_sources:
        detail = ", ".join(dict.fromkeys(failed_sources))
        if not_configured:
            detail += f"; {', '.join(dict.fromkeys(not_configured))} not configured"
        return (
            "Supplier search incomplete",
            f"{detail}. No candidates were confirmed. Retry the search or check supplier "
            "catalogs directly; this result does not confirm that no replacement exists.",
        )
    if not_configured or bool(discovery.get("has_incomplete_evidence")):
        unique_unconfigured = list(dict.fromkeys(not_configured))
        if unique_unconfigured:
            verb = "is" if len(unique_unconfigured) == 1 else "are"
            detail = f"{', '.join(unique_unconfigured)} {verb} not configured. "
        else:
            detail = "Some supplier catalogs could not be checked. "
        return (
            "Supplier coverage incomplete",
            f"{detail}No candidates were confirmed. Retry after coverage is available or "
            "check supplier catalogs directly; this result does not confirm that no replacement exists.",
        )
    searched_catalogs: list[str] = []
    searched_relationships: list[str] = []
    catalog_only_sources: list[str] = []
    for name, raw_status in providers.items():
        if not isinstance(raw_status, Mapping):
            continue
        catalog_status = str(raw_status.get("catalog") or "").strip().casefold()
        family_status = str(raw_status.get("family_search") or "").strip().casefold()
        relationship_status = str(raw_status.get("substitutions") or "").strip().casefold()
        if catalog_status in {"ok", "available"}:
            scope = "catalog and family" if family_status in {"ok", "available"} else "catalog"
            searched_catalogs.append(f"{name} {scope}")
            if relationship_status in {"not_supported", "available"}:
                catalog_only_sources.append(str(name))
        if relationship_status == "ok":
            searched_relationships.append(f"{name} substitute relationships")

    searched = searched_relationships + searched_catalogs
    scope_text = ", ".join(searched) if searched else "the configured distributor sources"
    relationship_note = (
        f" Catalog hits from {', '.join(catalog_only_sources)} are discovery leads; "
        "this workflow does not receive explicit substitute relationship evidence from those providers."
        if catalog_only_sources
        else " Catalog and family matches are discovery leads that still need engineering validation."
    )
    return (
        "No replacement candidates confirmed",
        f"No candidates were returned by {scope_text}.{relationship_note} "
        "This does not confirm that no replacement exists or that any unlisted part is compatible.",
    )


def supplier_search_coverage_rows(discovery_metadata: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """Summarize which relationship, catalog, and family searches actually ran."""
    discovery = discovery_metadata if isinstance(discovery_metadata, Mapping) else {}
    providers = discovery.get("providers")
    if not isinstance(providers, Mapping):
        return []

    def _status_label(value: Any) -> str:
        status = str(value or "not_requested").strip().casefold()
        return {
            "ok": "checked",
            "available": "available",
            "not_supported": "not provided by this supplier",
            "not_configured": "not configured",
            "not_requested": "not requested",
            "error": "search failed",
            "timeout": "timed out",
            "failed": "search failed",
            "rate_limited": "rate limited",
        }.get(status, status.replace("_", " "))

    rows: list[tuple[str, str]] = []
    for provider in ("DigiKey", "Mouser", "Newark"):
        status = providers.get(provider)
        if not isinstance(status, Mapping):
            continue
        details = []
        relationship_status = str(status.get("substitutions") or "").casefold()
        if relationship_status == "ok":
            count = int(status.get("explicit_count") or 0)
            details.append(f"explicit substitute check: {count} returned")
        elif relationship_status:
            details.append(f"explicit substitute check: {_status_label(relationship_status)}")

        catalog_status = str(status.get("catalog") or "").casefold()
        if catalog_status in {"ok", "available"}:
            count = int(status.get("catalog_count") or 0)
            details.append(f"catalog search: {count} leads")
        elif catalog_status:
            details.append(f"catalog search: {_status_label(catalog_status)}")

        family_status = str(status.get("family_search") or "").casefold()
        if family_status and family_status != "not_requested":
            details.append(f"family search: {_status_label(family_status)}")

        parametric_status = str(status.get("parametric_search") or "").casefold()
        if parametric_status and parametric_status != "not_requested":
            count = int(status.get("parametric_count") or 0)
            details.append(
                f"spec-led search: {count} leads"
                if parametric_status in {"ok", "available"}
                else f"spec-led search: {_status_label(parametric_status)}"
            )
        if details:
            rows.append((str(provider), "; ".join(details)))
    return rows


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
    elif exc_type in {"PicklingError", "TypeError"} and "pickle" in lowered:
        code = "cache_serialization_failed"
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
        self.active_stage = ""
        self.failed_stage = ""

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._started) * 1000.0, 1)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        previous_stage = self.active_stage
        self.active_stage = name
        s