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


def supplier_coverage_label(
    source: str,
    provider_status: str,
    *,
    failure_category: str = "",
) -> str:
    status = str(provider_status or "").strip().upper()
    name = str(source or "").strip() or "Supplier"
    if status == "AVAILABLE":
        return f"{name}: available"
    if name.casefold() == "octopart":
        if failure_category == CATEGORY_CONFIGURATION or status == PROVIDER_NOT_CONFIGURED:
            return f"{name}: not configured"
        return f"{name}: unavailable for this search"
    labels = {
        PROVIDER_NOT_CONFIGURED: "not configured",
        PROVIDER_PART_NOT_FOUND: "no exact match",
        PROVIDER_TIMEOUT: "timed out",
        PROVIDER_RATE_LIMITED: "rate limited",
        PROVIDER_ERROR: "unavailable",
    }
    return f"{name}: {labels.get(status, 'unknown')}"


def attach_supplier_diagnostic(result: dict[str, Any], diagnostic: Mapping[str, str]) -> None:
    if not isinstance(result, dict) or not diagnostic:
        return
    result["failure_category"] = str(diagnostic.get("category") or "")
    result["diagnostic_stage"] = str(diagnostic.get("stage") or "")
