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


_PLACEHOLDER_SECRET_VALUES = frozenset(
    {
        "changeme",
        "todo",
        "xxx",
        "none",
        "null",
        "your_client_id",
        "your_secret",
        "your_client_secret",
        "replace_me",
        "redacted",
    }
)


def _secret_value_present(raw_value: object) -> bool:
    """True when a secret value looks like real configuration (not empty/placeholder)."""
    value = str(raw_value or "").strip()
    if not value:
        return False
    lowered = value.casefold()
    if lowered in _PLACEHOLDER_SECRET_VALUES:
        return False
    if "placeholder" in lowered or "example" in lowered or lowered.startswith("replace"):
        return False
    return True


def _octopart_credentials_configured() -> bool:
    """True only when Octopart/Nexar has both a client id and secret in this environment.

    A lone client id (or placeholder) is not production configuration — treating it
    as configured caused live PROVIDER_ERROR rows to render as timeout/unavailable.
    Never log or return secret names/values from this helper.
    """
    try:
        from src.secrets import get_secret

        def _has(name: str) -> bool:
            return _secret_value_present(get_secret(name, required=False))

        has_id = _has("NEXAR_CLIENT_ID") or _has("OCTOPART_CLIENT_ID")
        has_secret = _has("NEXAR_CLIENT_SECRET") or _has("OCTOPART_CLIENT_SECRET")
        return has_id and has_secret
    except Exception:
        return False


def _force_octopart_configuration_gap(
    source: str,
    *,
    status: str = "",
    category: str = "",
    error_message: str = "",
) -> bool:
    """Octopart must use configuration wording when this environment is not usable."""
    if str(source or "").strip().casefold() != "octopart":
        return False
    if str(status or "").strip().upper() == "AVAILABLE":
        return False
    if category == CATEGORY_CONFIGURATION or status == PROVIDER_NOT_CONFIGURED:
        return True
    if category == CATEGORY_AUTHENTICATION:
        return True
    lowered = _redact(error_message).casefold()
    if any(
        token in lowered
        for token in (
            "not configured",
            "missing required configuration",
            "authentication",
            "unauthorized",
            "credential",
            "configuration failed",
        )
    ):
        return True
    return not _octopart_credentials_configured()


def resolve_supplier_coverage_status(
    source: str,
    *,
    provider_status: str = "",
    failure_category: str = "",
    error_message: str = "",
    discovery_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical configuration-aware coverage status for one supplier.

    Both the Supplier coverage field and the blue coverage notices must use this
    resolver so Octopart cannot diverge into unavailable/runtime-failure wording
    when production credentials are absent or incomplete.
    """
    name = str(source or "").strip() or "Supplier"
    status = str(provider_status or "").strip().upper()
    category = str(failure_category or "").strip() or categorize_supplier_failure(
        provider_status=status,
        error_message=error_message,
    )
    discovery_gaps = {
        item.casefold() for item in _discovery_not_configured_sources(discovery_metadata)
    }
    if name.casefold() in discovery_gaps or _force_octopart_configuration_gap(
        name,
        status=status,
        category=category,
        error_message=error_message,
    ):
        status = PROVIDER_NOT_CONFIGURED
        category = CATEGORY_CONFIGURATION

    if status == "AVAILABLE" and category != CATEGORY_CONFIGURATION:
        label = f"{name}: available"
        return {
            "source": name,
            "provider_status": status,
            "failure_category": category,
            "label": label,
            "is_available": True,
            "is_configuration_gap": False,
            "is_runtime_failure": False,
        }

    if category == CATEGORY_CONFIGURATION or status == PROVIDER_NOT_CONFIGURED:
        return {
            "source": name,
            "provider_status": PROVIDER_NOT_CONFIGURED,
            "failure_category": CATEGORY_CONFIGURATION,
            "label": f"{name}: not configured",
            "is_available": False,
            "is_configuration_gap": True,
            "is_runtime_failure": False,
        }

    if name.casefold() == "octopart":
        # Fully configured Octopart that still failed this search.
        label = f"{name}: unavailable for this search"
    else:
        labels = {
            PROVIDER_NOT_CONFIGURED: "not configured",
            PROVIDER_PART_NOT_FOUND: "no exact match",
            PROVIDER_TIMEOUT: "timed out",
            PROVIDER_RATE_LIMITED: "rate limited",
            PROVIDER_ERROR: "unavailable",
        }
        label = f"{name}: {labels.get(status, 'unknown')}"

    is_runtime = status in {
        PROVIDER_TIMEOUT,
        PROVIDER_RATE_LIMITED,
        PROVIDER_ERROR,
    } or category in {
        CATEGORY_TIMEOUT,
        CATEGORY_RATE_LIMIT,
        CATEGORY_HTTP_ERROR,
        CATEGORY_AUTHENTICATION,
        CATEGORY_MALFORMED_RESPONSE,
        CATEGORY_PROVIDER_ERROR,
    }
    return {
        "source": name,
        "provider_status": status,
        "failure_category": category,
        "label": label,
        "is_available": False,
        "is_configuration_gap": False,
        "is_runtime_failure": is_runtime,
    }


def supplier_coverage_label(
    source: str,
    provider_status: str,
    *,
    failure_category: str = "",
    error_message: str = "",
    discovery_metadata: Mapping[str, Any] | None = None,
) -> str:
    return str(
        resolve_supplier_coverage_status(
            source,
            provider_status=provider_status,
            failure_category=failure_category,
            error_message=error_message,
            discovery_metadata=discovery_metadata,
        ).get("label")
        or f"{str(source or 'Supplier').strip() or 'Supplier'}: unknown"
    )


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
            resolved = resolve_supplier_coverage_status(
                source,
                provider_status=str(row.get("provider_status") or ""),
                failure_category=str(row.get("failure_category") or ""),
                error_message=str(row.get("error") or ""),
                discovery_metadata=discovery_metadata,
            )
            payload = dict(row)
            payload["provider_status"] = resolved["provider_status"]
            payload["failure_category"] = resolved["failure_category"]
            payload["coverage_label"] = resolved["label"]
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
            resolved = resolve_supplier_coverage_status(
                source,
                provider_status=PROVIDER_NOT_CONFIGURED,
                failure_category=CATEGORY_CONFIGURATION,
                discovery_metadata=discovery_metadata,
            )
            rows.append(
                {
                    "source": source,
                    "provider_status": resolved["provider_status"],
                    "failure_category": resolved["failure_category"],
                    "coverage_label": resolved["label"],
                }
            )
            seen.add(source.casefold())
    return rows


def format_alternative_finder_provider_coverage(
    *,
    original_data: Mapping[str, Any] | None = None,
    discovery_metadata: Mapping[str, Any] | None = None,
) -> str:
    """Render the Supplier coverage field from the canonical coverage resolver."""
    rows = _supplier_result_rows(
        original_data=original_data,
        discovery_metadata=discovery_metadata,
    )
    labels = [
        str(row.get("coverage_label") or "").strip()
        for row in rows
        if str(row.get("coverage_label") or "").strip()
    ]
    return " · ".join(labels) if labels else "Not checked"


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
        resolved = resolve_supplier_coverage_status(
            source,
            provider_status=str(row.get("provider_status") or ""),
            failure_category=str(row.get("failure_category") or ""),
            error_message=str(row.get("error") or ""),
            discovery_metadata=discovery_metadata,
        )
        if resolved["is_available"]:
            available_sources.append(source)
            continue
        if resolved["is_configuration_gap"]:
            if source not in configuration_sources:
                configuration_sources.append(source)
            continue
        if resolved["is_runtime_failure"]:
            runtime_failures.append(
                {
                    "source": source,
                    "category": str(resolved["failure_category"]),
                    "label": str(resolved["label"]),
                }
            )

    configured_gaps = {name.casefold() for name in configuration_sources}
    configured_gaps.update(
        name.casefold() for name in _discovery_not_configured_sources(discovery_metadata)
    )
    # Discovery-level provider_failures are treated as runtime gaps when present,
    # except Octopart which must remain configuration-aware via the canonical resolver.
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
        resolved = resolve_supplier_coverage_status(
            source,
            provider_status=PROVIDER_ERROR,
            failure_category=CATEGORY_PROVIDER_ERROR,
            discovery_metadata=discovery_metadata,
        )
        if resolved["is_configuration_gap"]:
            if source not in configuration_sources:
                configuration_sources.append(source)
            configured_gaps.add(source.casefold())
            continue
        runtime_failures.append(
            {
                "source": source,
                "category": str(resolved["failure_category"]),
                "label": str(resolved["label"]),
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
        "coverage_field": format_alternative_finder_provider_coverage(
            original_data=original_data,
            discovery_metadata=discovery_metadata,
        ),
        "show_generic_configured_failure": False,
    }


def attach_supplier_diagnostic(result: dict[str, Any], diagnostic: Mapping[str, str]) -> None:
    if not isinstance(result, dict) or not diagnostic:
        return
    result["failure_category"] = str(diagnostic.get("category") or "")
    result["diagnostic_stage"] = str(diagnostic.get("stage") or "")
