"""Structured, redacted supplier diagnostics for Alternative Finder."""
from __future__ import annotations

import contextvars
import logging
import re
import uuid
from typing import Any, Mapping

from integrations.provider_health import (
    PROVIDER_ERROR,
    PROVIDER_NOT_CONFIGURED,
    PROVIDER_PART_NOT_FOUND,
    PROVIDER_RATE_LIMITED,
    PROVIDER_TIMEOUT,
)

logger = logging.getLogger(__name__)

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_AUTHENTICATION = "authentication"
CATEGORY_HTTP_ERROR = "http_error"
CATEGORY_RATE_LIMIT = "rate_limit"
CATEGORY_TIMEOUT = "timeout_network"
CATEGORY_MALFORMED_RESPONSE = "malformed_response"
CATEGORY_NO_RESULT = "no_result"
CATEGORY_PROVIDER_ERROR = "provider_error"

_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*\S+"
)

_current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "alternative_finder_request_id",
    default="",
)


def new_alternative_finder_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_alternative_finder_request_id(request_id: str) -> contextvars.Token[str]:
    return _current_request_id.set(str(request_id or "").strip())


def reset_alternative_finder_request_id(token: contextvars.Token[str]) -> None:
    _current_request_id.reset(token)


def get_alternative_finder_request_id() -> str:
    return str(_current_request_id.get() or "").strip()


def _redact(message: str) -> str:
    return _SECRET_PATTERN.sub(r"\1=<redacted>", str(message or "")).strip()


def categorize_supplier_failure(
    *,
    provider_status: str,
    error_message: str = "",
    exception_type: str = "",
) -> str:
    status = str(provider_status or "").strip().upper()
    lowered = _redact(error_message).casefold()
    exc = str(exception_type or "").strip()

    if status == PROVIDER_NOT_CONFIGURED:
        return CATEGORY_CONFIGURATION
    if (
        "not configured" in lowered
        or "missing required configuration" in lowered
        or "credentials are not configured" in lowered
    ):
        return CATEGORY_CONFIGURATION
    if status == PROVIDER_PART_NOT_FOUND:
        return CATEGORY_NO_RESULT
    if status == PROVIDER_RATE_LIMITED or "rate limit" in lowered or "429" in lowered:
        return CATEGORY_RATE_LIMIT
    if status == PROVIDER_TIMEOUT or exc in {"ReadTimeout", "ConnectTimeout", "Timeout"}:
        return CATEGORY_TIMEOUT
    if "timeout" in lowered or "timed out" in lowered:
        return CATEGORY_TIMEOUT
    if exc in {"HTTPError", "ConnectionError"} or "http" in lowered:
        return CATEGORY_HTTP_ERROR
    if (
        "authentication" in lowered
        or "unauthorized" in lowered
        or "401" in lowered
        or "403" in lowered
        or "credential" in lowered
    ):
        return CATEGORY_AUTHENTICATION
    if "json" in lowered or "graphql" in lowered or "malformed" in lowered:
        return CATEGORY_MALFORMED_RESPONSE
    if status == PROVIDER_ERROR:
        return CATEGORY_PROVIDER_ERROR
    return CATEGORY_PROVIDER_ERROR


def log_supplier_diagnostic(
    *,
    request_id: str = "",
    supplier: str,
    stage: str,
    provider_status: str,
    error_message: str = "",
    exception_type: str = "",
    retained_candidates: bool = False,
) -> dict[str, str]:
    resolved_request_id = str(request_id or get_alternative_finder_request_id() or "unknown").strip()
    category = categorize_supplier_failure(
        provider_status=provider_status,
        error_message=error_message,
        exception_type=exception_type,
    )
    safe_message = _redact(error_message)[:160]
    payload = {
        "request_id": resolved_request_id,
        "supplier": supplier,
        "stage": stage,
        "category": category,
        "provider_status": str(provider_status or ""),
        "exception_type": str(exception_type or ""),
        "message": safe_message,
        "retained_candidates": "true" if retained_candidates else "false",
    }
    logger.info(
        "ALT_FINDER_SUPPLIER_DIAG request_id=%s supplier=%s stage=%s category=%s "
        "status=%s exception_type=%s retained_candidates=%s message=%s",
        payload["request_id"],
        payload["supplier"],
        payload["stage"],
        payload["category"],
        payload["provider_status"],
        payload["exception_type"] or "none",
        payload["retained_candidates"],
        payload["message"] or "none",
    )
    return payload


def _octopart_credentials_configured() -> bool:
    """True when any supported Octopart/Nexar credential is present in this environment."""
    try:
        from src.secrets import get_secret

        for name in ("NEXAR_CLIENT_ID", "OCTOPART_CLIENT_ID"):
            if str(get_secret(name, required=False) or "").strip():
                return True
    except Exception:
        return False
    return False


def _force_octopart_configuration_gap(
    source: str,
    *,
    status: str = "",
    category: str = "",
) -> bool:
    """Octopart must never use timeout/unavailable wording when credentials are absent."""
    if str(source or "").strip().casefold() != "octopart":
        return False
    if str(status or "").strip().upper() == "AVAILABLE":
        return False
    if category == CATEGORY_CONFIGURATION or status == PROVIDER_NOT_CONFIGURED:
        return True
    return not _octopart_credentials_configured()


def supplier_coverage_label(
    source: str,
    provider_status: str,
    *,
    failure_category: str = "",
) -> str:
    status = str(provider_status or "").strip().upper()
    category = str(failure_category or "").strip()
    name = str(source or "").strip() or "Supplier"
    if status == "AVAILABLE":
        return f"{name}: available"
    if _force_octopart_configuration_gap(name, status=status, category=category):
        return f"{name}: not configured"
    if category == CATEGORY_CONFIGURATION or status == PROVIDER_NOT_CONFIGURED:
        return f"{name}: not configured"
    if name.casefold() == "octopart":
        return f"{name}: unavailable for this search"
    labels = {
        PROVIDER_NOT_CONFIGURED: "not configured",
        PROVIDER_PART_NOT_FOUND: "no exact match",
        PROVIDER_TIMEOUT: "timed out",
        PROVIDER_RATE_LIMITED: "rate limited",
        PROVIDER_ERROR: "unavailable",
    }
    return f"{name}: {labels.get(status, 'unknown')}"


def _discovery_not_configured_sources(
    discovery_metadata: Mapping[str, Any] | None = None,
) -> set[str]:
    names: set[str] = set()
    for source_name, status in ((discovery_metadata or {}).get("providers") or {}).items():
        if not isinstance(status, dict):
            continue
        lookup = str(status.get("lookup") or "").strip().lower()
        substitutions = str(status.get("substitutions") or "").strip().lower()
        if lookup == "not_configured" or substitutions == "not_configured":
            names.add(str(source_name).strip())
    return {name for name in names if name}


def _supplier_result_rows(
    *,
    original_data: Mapping[str, Any] | None = None,
    discovery_metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in (original_data or {}).get("all_supplier_results") or []:
        if isinstance(row, dict) and row.get("source"):
            source = str(row.get("source") or "").strip()
            payload = dict(row)
            if source in _discovery_not_configured_sources(discovery_metadata) or _force_octopart_configuration_gap(
                source,
                status=str(payload.get("provider_status") or ""),
                category=str(payload.get("failure_category") or ""),
            ):
                payload["provider_status"] = PROVIDER_NOT_CONFIGURED
                payload["failure_category"] = CATEGORY_CONFIGURATION
            rows.append(payload)
            if source:
                seen.add(source.casefold())
    # Discovery metadata may only know configuration gaps without full supplier rows.
    for source_name, status in ((discovery_metadata or {}).get("providers") or {}).items():
        if not isinstance(status, dict):
            continue
        lookup = str(status.get("lookup") or "").strip().lower()
        substitutions = str(status.get("substitutions") or "").strip().lower()
        source = str(source_name).strip()
        if not source or source.casefold() in seen:
            continue
        if lookup == "not_configured" or substitutions == "not_configured":
            rows.append(
                {
                    "source": source,
                    "provider_status": PROVIDER_NOT_CONFIGURED,
                    "failure_category": CATEGORY_CONFIGURATION,
                }
            )
            seen.add(source.casefold())
    return rows


def build_alternative_finder_coverage_notices(
    *,
    original_data: Mapping[str, Any] | None = None,
    discovery_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build category-aware supplier coverage notices for Alternative Finder UI."""
    rows = _supplier_result_rows(
        original_data=original_data,
        discovery_metadata=discovery_metadata,
    )
    configuration_sources: list[str] = []
    runtime_failures: list[dict[str, str]] = []
    available_sources: list[str] = []

    for row in rows:
        source = str(row.get("source") or "").strip()
        if not source:
            continue
        status = str(row.get("provider_status") or "").strip().upper()
        category = str(row.get("failure_category") or "").strip() or categorize_supplier_failure(
            provider_status=status,
            error_message=str(row.get("error") or ""),
        )
        if source in _discovery_not_configured_sources(discovery_metadata) or _force_octopart_configuration_gap(
            source,
            status=status,
            category=category,
        ):
            category = CATEGORY_CONFIGURATION
            status = PROVIDER_NOT_CONFIGURED
        if status == "AVAILABLE" and category != CATEGORY_CONFIGURATION:
            available_sources.append(source)
            continue
        if category == CATEGORY_CONFIGURATION or status == PROVIDER_NOT_CONFIGURED:
            if source not in configuration_sources:
                configuration_sources.append(source)
            continue
        if status in {
            PROVIDER_TIMEOUT,
            PROVIDER_RATE_LIMITED,
            PROVIDER_ERROR,
            "TIMEOUT",
            "RATE_LIMITED",
            "PROVIDER_ERROR",
        } or category in {
            CATEGORY_TIMEOUT,
            CATEGORY_RATE_LIMIT,
            CATEGORY_HTTP_ERROR,
            CATEGORY_AUTHENTICATION,
            CATEGORY_MALFORMED_RESPONSE,
            CATEGORY_PROVIDER_ERROR,
        }:
            runtime_failures.append(
                {
                    "source": source,
                    "category": category,
                    "label": supplier_coverage_label(
                        source,
                        status,
                        failure_category=category,
                    ),
                }
            )

    configured_gaps = {name.casefold() for name in configuration_sources}
    configured_gaps.update(
        name.casefold() for name in _discovery_not_configured_sources(discovery_metadata)
    )
    # Discovery-level provider_failures are treated as runtime gaps when present.
    for name in (discovery_metadata or {}).get("provider_failures") or []:
        source = str(name).strip()
        if not source:
            continue
        if source.casefold() in configured_gaps or source in configuration_sources:
            continue
        if any(item["source"] == source for item in runtime_failures):
            continue
        if source in available_sources:
            continue
        runtime_failures.append(
            {
                "source": source,
                "category": CATEGORY_PROVIDER_ERROR,
                "label": f"{source}: unavailable",
            }
        )

    notices: list[str] = []
    captions: list[str] = []

    if configuration_sources:
        if (
            len(configuration_sources) == 1
            and configuration_sources[0].casefold() == "octopart"
        ):
            notices.append(
                "Octopart is not configured for this environment. "
                "Results include Mouser, DigiKey, and Newark."
            )
        else:
            names = ", ".join(configuration_sources)
            notices.append(
                f"{names} "
                f"{'is' if len(configuration_sources) == 1 else 'are'} "
                "not configured for this environment. "
                "Cadivor kept results from the sources that are configured."
            )

    if runtime_failures:
        notices.append(
            "Some supplier sources did not respond during this search. "
            "Cadivor kept the candidates retrieved from the sources that responded."
        )
        captions.append(
            "Unavailable or failed sources: "
            + ", ".join(item["label"] for item in runtime_failures)
        )

    return {
        "notices": notices,
        "captions": captions,
        "configuration_sources": configuration_sources,
        "runtime_failures": runtime_failures,
        "available_sources": available_sources,
        "show_generic_configured_failure": False,
    }


def attach_supplier_diagnostic(result: dict[str, Any], diagnostic: Mapping[str, str]) -> None:
    if not isinstance(result, dict) or not diagnostic:
        return
    result["failure_category"] = str(diagnostic.get("category") or "")
    result["diagnostic_stage"] = str(diagnostic.get("stage") or "")
