"""Structured, redacted supplier diagnostics for Alternative Finder."""
from __future__ import annotations

import contextvars
import logging
import re
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

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

# Railway-searchable Octopart/Nexar provider_response subreasons.
SUBREASON_GRAPHQL_ERRORS = "graphql_errors"
SUBREASON_EMPTY_RESPONSE = "empty_response"
SUBREASON_MALFORMED_RESPONSE = "malformed_response"
SUBREASON_MISSING_EXPECTED_DATA = "missing_expected_data"
SUBREASON_SCHEMA_MISMATCH = "schema_mismatch"
SUBREASON_ZERO_RESULTS = "zero_results"

_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*\S+"
)

_current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "alternative_finder_request_id",
    default="",
)

# Streamlit @st.cache_data and ThreadPoolExecutor workers do not reliably inherit
# ContextVars. Keep a process-local stack + last AF id so every supplier diagnostic
# during/after a user search can resolve the originating request_id.
_REQUEST_ID_LOCK = threading.Lock()
_ACTIVE_REQUEST_ID_STACK: list[str] = []
_LAST_AF_REQUEST_ID = ""


def new_alternative_finder_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_alternative_finder_request_id(request_id: str) -> contextvars.Token[str]:
    global _LAST_AF_REQUEST_ID
    cleaned = str(request_id or "").strip()
    with _REQUEST_ID_LOCK:
        _ACTIVE_REQUEST_ID_STACK.append(cleaned)
        if cleaned:
            _LAST_AF_REQUEST_ID = cleaned
    return _current_request_id.set(cleaned)


def reset_alternative_finder_request_id(token: contextvars.Token[str]) -> None:
    with _REQUEST_ID_LOCK:
        if _ACTIVE_REQUEST_ID_STACK:
            _ACTIVE_REQUEST_ID_STACK.pop()
    _current_request_id.reset(token)


def get_alternative_finder_request_id() -> str:
    value = str(_current_request_id.get() or "").strip()
    if value:
        return value
    with _REQUEST_ID_LOCK:
        if _ACTIVE_REQUEST_ID_STACK:
            stacked = str(_ACTIVE_REQUEST_ID_STACK[-1] or "").strip()
            if stacked:
                return stacked
        return str(_LAST_AF_REQUEST_ID or "").strip()


def resolve_supplier_diagnostic_request_id(request_id: str = "") -> str:
    """Resolve a correlator for supplier diagnostics; prefer AF search id over unknown."""
    explicit = str(request_id or "").strip()
    if explicit and explicit.casefold() != "unknown":
        return explicit
    inherited = get_alternative_finder_request_id()
    if inherited and inherited.casefold() != "unknown":
        return inherited
    return ""


@contextmanager
def bind_alternative_finder_request_id(request_id: str = "") -> Iterator[str]:
    """Bind an AF request id for nested supplier lookups (enrichment / UI fallbacks)."""
    cleaned = str(request_id or "").strip()
    if not cleaned or cleaned.casefold() == "unknown":
        yield ""
        return
    token = set_alternative_finder_request_id(cleaned)
    try:
        yield cleaned
    finally:
        reset_alternative_finder_request_id(token)


def _redact(message: str) -> str:
    return _SECRET_PATTERN.sub(r"\1=<redacted>", str(message or "")).strip()


def categorize_supplier_failure(
    *,
    provider_status: str,
    error_message: str = "",
    exception_type: str = "",
    status_code: str | int | None = None,
    subreason: str = "",
) -> str:
    status = str(provider_status or "").strip().upper()
    lowered = _redact(error_message).casefold()
    exc = str(exception_type or "").strip()
    code = _safe_http_status_code(status_code, error_message)
    reason = str(subreason or "").strip().casefold()

    if reason == SUBREASON_ZERO_RESULTS or status == PROVIDER_PART_NOT_FOUND:
        return CATEGORY_NO_RESULT
    if reason == SUBREASON_GRAPHQL_ERRORS:
        return CATEGORY_PROVIDER_ERROR
    if reason in {
        SUBREASON_SCHEMA_MISMATCH,
        SUBREASON_MISSING_EXPECTED_DATA,
        SUBREASON_EMPTY_RESPONSE,
        SUBREASON_MALFORMED_RESPONSE,
    }:
        return CATEGORY_MALFORMED_RESPONSE
    if status == PROVIDER_NOT_CONFIGURED:
        return CATEGORY_CONFIGURATION
    if (
        "not configured" in lowered
        or "missing required configuration" in lowered
        or "credentials are not configured" in lowered
    ):
        return CATEGORY_CONFIGURATION
    if status == PROVIDER_RATE_LIMITED or "rate limit" in lowered or "429" in lowered or code == "429":
        return CATEGORY_RATE_LIMIT
    if status == PROVIDER_TIMEOUT or exc in {"ReadTimeout", "ConnectTimeout", "Timeout"}:
        return CATEGORY_TIMEOUT
    if "timeout" in lowered or "timed out" in lowered:
        return CATEGORY_TIMEOUT
    # Auth must win over generic HTTPError (requests raises HTTPError for 401/403).
    if (
        code in {"401", "403"}
        or "authentication" in lowered
        or "unauthorized" in lowered
        or "forbidden" in lowered
        or "401" in lowered
        or "403" in lowered
        or "credential" in lowered
    ):
        return CATEGORY_AUTHENTICATION
    if exc in {"HTTPError", "ConnectionError"} or "http" in lowered or code:
        return CATEGORY_HTTP_ERROR
    # Match GraphQL payload failures only — not credentialed/API URLs containing "/graphql".
    if "graphql error" in lowered or "graphql errors" in lowered:
        return CATEGORY_PROVIDER_ERROR
    if "json" in lowered or "malformed" in lowered:
        return CATEGORY_MALFORMED_RESPONSE
    if status == PROVIDER_ERROR:
        return CATEGORY_PROVIDER_ERROR
    return CATEGORY_PROVIDER_ERROR


def normalize_provider_response_subreason(
    *,
    subreason: str = "",
    provider_status: str = "",
    category: str = "",
    exception_type: str = "",
    error_message: str = "",
) -> str:
    """Return a safe Octopart/provider_response subreason for diagnostics."""
    reason = str(subreason or "").strip().casefold()
    allowed = {
        SUBREASON_GRAPHQL_ERRORS,
        SUBREASON_EMPTY_RESPONSE,
        SUBREASON_MALFORMED_RESPONSE,
        SUBREASON_MISSING_EXPECTED_DATA,
        SUBREASON_SCHEMA_MISMATCH,
        SUBREASON_ZERO_RESULTS,
    }
    if reason in allowed:
        return reason
    status = str(provider_status or "").strip().upper()
    if status == PROVIDER_PART_NOT_FOUND:
        return SUBREASON_ZERO_RESULTS
    lowered = _redact(error_message).casefold()
    exc = str(exception_type or "").strip()
    if "cannot query field" in lowered or "unknown field" in lowered:
        return SUBREASON_SCHEMA_MISMATCH
    # Do not treat "…/graphql" URLs in HTTP error strings as GraphQL payload failures.
    if exc == "OctopartResponseError" or "graphql error" in lowered or "graphql errors" in lowered:
        return SUBREASON_GRAPHQL_ERRORS
    if "json" in lowered or "malformed" in lowered:
        return SUBREASON_MALFORMED_RESPONSE
    if str(category or "") == CATEGORY_MALFORMED_RESPONSE:
        return SUBREASON_MALFORMED_RESPONSE
    if str(category or "") == CATEGORY_NO_RESULT:
        return SUBREASON_ZERO_RESULTS
    return ""


def _safe_http_status_code(
    status_code: str | int | None = None,
    error_message: str = "",
    error: BaseException | None = None,
) -> str:
    """Return a bare HTTP status code string, never URLs or response bodies."""
    if status_code is not None and str(status_code).strip():
        raw = str(status_code).strip()
        if raw.isdigit() and 100 <= int(raw) <= 599:
            return raw
    if error is not None:
        response = getattr(error, "response", None)
        code = getattr(response, "status_code", None) if response is not None else None
        if isinstance(code, int) and 100 <= code <= 599:
            return str(code)
    # Only accept a standalone 3-digit status; never scrape credentialed URLs.
    match = re.search(r"(?<![0-9])([1-5][0-9]{2})(?![0-9])", str(error_message or ""))
    if match:
        return match.group(1)
    return ""


def railway_diagnostic_category(internal_category: str) -> str:
    """Map internal failure categories to the Railway-searchable taxonomy."""
    mapping = {
        CATEGORY_CONFIGURATION: "configuration",
        CATEGORY_AUTHENTICATION: "auth",
        CATEGORY_HTTP_ERROR: "http",
        CATEGORY_RATE_LIMIT: "rate_limit",
        CATEGORY_TIMEOUT: "timeout",
        CATEGORY_MALFORMED_RESPONSE: "provider_response",
        CATEGORY_NO_RESULT: "provider_response",
        CATEGORY_PROVIDER_ERROR: "provider_response",
    }
    return mapping.get(str(internal_category or "").strip(), "unknown")


def diagnostic_is_retryable(
    *,
    log_category: str,
    status_code: str = "",
) -> bool:
    if log_category in {"timeout", "rate_limit"}:
        return True
    if log_category in {"configuration", "auth"}:
        return False
    if status_code.isdigit():
        code = int(status_code)
        if code == 429 or code == 408 or code >= 500:
            return True
        if 400 <= code < 500:
            return False
    if log_category == "http":
        return True
    return False


def log_supplier_diagnostic(
    *,
    request_id: str = "",
    supplier: str,
    stage: str,
    provider_status: str,
    error_message: str = "",
    exception_type: str = "",
    status_code: str | int | None = None,
    error: BaseException | None = None,
    retained_candidates: bool = False,
    subreason: str = "",
) -> dict[str, str]:
    """Emit one Railway-searchable supplier diagnostic for a non-success lookup.

    Uses WARNING so Deploy Logs capture the event (INFO is not reliably retained).
    The log line contains only safe searchable fields — never headers, tokens,
    credentialed URLs, or response bodies.
    """
    resolved_request_id = resolve_supplier_diagnostic_request_id(request_id) or "unknown"
    error_subreason = ""
    rejected_fields: list[str] = []
    if error is not None:
        error_subreason = str(getattr(error, "subreason", "") or "").strip()
        raw_fields = getattr(error, "rejected_fields", None) or ()
        rejected_fields = [
            str(item).strip()
            for item in raw_fields
            if str(item or "").strip() and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(item).strip())
        ]
    safe_status_code = _safe_http_status_code(status_code, error_message, error)
    resolved_subreason = normalize_provider_response_subreason(
        subreason=subreason or error_subreason,
        provider_status=provider_status,
        exception_type=exception_type or (type(error).__name__ if error is not None else ""),
        error_message=error_message,
    )
    category = categorize_supplier_failure(
        provider_status=provider_status,
        error_message=error_message,
        exception_type=exception_type or (type(error).__name__ if error is not None else ""),
        status_code=safe_status_code,
        subreason=resolved_subreason,
    )
    if not resolved_subreason:
        resolved_subreason = normalize_provider_response_subreason(
            provider_status=provider_status,
            category=category,
            exception_type=exception_type or (type(error).__name__ if error is not None else ""),
            error_message=error_message,
        )
    log_category = railway_diagnostic_category(category)
    retryable = diagnostic_is_retryable(
        log_category=log_category,
        status_code=safe_status_code,
    )
    safe_message = _redact(error_message)[:160]
    # Drop anything that still looks like a URL after redaction.
    if "://" in safe_message or "nexar.com" in safe_message.casefold():
        safe_message = "Supplier lookup failed."
    payload = {
        "request_id": resolved_request_id,
        "supplier": str(supplier or "").strip() or "Supplier",
        "stage": str(stage or "").strip() or "lookup",
        "category": category,
        "log_category": log_category,
        "subreason": resolved_subreason,
        "provider_status": str(provider_status or ""),
        "exception_type": str(exception_type or (type(error).__name__ if error is not None else "")),
        "status_code": safe_status_code,
        "retryable": "true" if retryable else "false",
        "message": safe_message,
        "retained_candidates": "true" if retained_candidates else "false",
    }
    if rejected_fields:
        # Field names only — never GraphQL messages, tokens, or bodies.
        payload["rejected_fields"] = ",".join(rejected_fields[:8])
    if resolved_subreason and rejected_fields:
        logger.warning(
            "ALT_FINDER_SUPPLIER_DIAG request_id=%s supplier=%s category=%s "
            "subreason=%s rejected_fields=%s status_code=%s retryable=%s",
            payload["request_id"],
            payload["supplier"],
            payload["log_category"],
            payload["subreason"],
            payload["rejected_fields"],
            payload["status_code"] or "none",
            payload["retryable"],
        )
    elif resolved_subreason:
        logger.warning(
            "ALT_FINDER_SUPPLIER_DIAG request_id=%s supplier=%s category=%s "
            "subreason=%s status_code=%s retryable=%s",
            payload["request_id"],
            payload["supplier"],
            payload["log_category"],
            payload["subreason"],
            payload["status_code"] or "none",
            payload["retryable"],
        )
    else:
        logger.warning(
            "ALT_FINDER_SUPPLIER_DIAG request_id=%s supplier=%s category=%s "
            "status_code=%s retryable=%s",
            payload["request_id"],
            payload["supplier"],
            payload["log_category"],
            payload["status_code"] or "none",
            payload["retryable"],
        )
    return payload


def attach_supplier_diagnostic(result: dict[str, Any], diagnostic: Mapping[str, str]) -> None:
    if not isinstance(result, dict) or not diagnostic:
        return
    result["failure_category"] = str(diagnostic.get("category") or "")
    result["diagnostic_stage"] = str(diagnostic.get("stage") or "")
    if diagnostic.get("status_code"):
        result["diagnostic_status_code"] = str(diagnostic.get("status_code") or "")
    if diagnostic.get("retryable"):
        result["diagnostic_retryable"] = str(diagnostic.get("retryable") or "")
    if diagnostic.get("log_category"):
        result["diagnostic_log_category"] = str(diagnostic.get("log_category") or "")
    if diagnostic.get("subreason"):
        result["diagnostic_subreason"] = str(diagnostic.get("subreason") or "")
    if diagnostic.get("request_id"):
        result["diagnostic_request_id"] = str(diagnostic.get("request_id") or "")
    if diagnostic.get("rejected_fields"):
        result["diagnostic_rejected_fields"] = str(diagnostic.get("rejected_fields") or "")


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
    """Octopart uses configuration wording only when this environment is not usable.

    Configured-but-failing Octopart (invalid credentials, HTTP errors, timeouts)
    must remain a runtime unavailable path so Deploy Logs and UI stay aligned.
    """
    if str(source or "").strip().casefold() != "octopart":
        return False
    if str(status or "").strip().upper() == "AVAILABLE":
        return False
    if category == CATEGORY_CONFIGURATION or status == PROVIDER_NOT_CONFIGURED:
        return True
    lowered = _redact(error_message).casefold()
    if (
        "not configured" in lowered
        or "missing required configuration" in lowered
        or "credentials are not configured" in lowered
    ):
        return True
    # Invalid/expired credentials are runtime failures when secrets are present.
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

    # Valid zero-result / no exact match is a completed supplier search, not an outage.
    if status == PROVIDER_PART_NOT_FOUND or category == CATEGORY_NO_RESULT:
        return {
            "source": name,
            "provider_status": PROVIDER_PART_NOT_FOUND,
            "failure_category": CATEGORY_NO_RESULT,
            "label": f"{name}: no exact match",
            "is_available": False,
            "is_configuration_gap": False,
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
