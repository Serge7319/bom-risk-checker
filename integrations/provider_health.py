"""Supplier provider health and degraded-data provenance helpers."""
from __future__ import annotations

from typing import Any

from src.configuration_errors import ConfigurationError

PROVIDER_AVAILABLE = "AVAILABLE"
PROVIDER_PART_NOT_FOUND = "PART_NOT_FOUND"
PROVIDER_NOT_CONFIGURED = "NOT_CONFIGURED"
PROVIDER_TIMEOUT = "TIMEOUT"
PROVIDER_RATE_LIMITED = "RATE_LIMITED"
PROVIDER_ERROR = "PROVIDER_ERROR"

_FAILURE_STATUSES = {
    PROVIDER_NOT_CONFIGURED,
    PROVIDER_TIMEOUT,
    PROVIDER_RATE_LIMITED,
    PROVIDER_ERROR,
}


def classify_provider_exception(error: Exception) -> str:
    if isinstance(error, ConfigurationError):
        return PROVIDER_NOT_CONFIGURED

    message = str(error or "").lower()
    if "timeout" in message or "timed out" in message:
        return PROVIDER_TIMEOUT
    if "429" in message or "rate limit" in message or "too many requests" in message:
        return PROVIDER_RATE_LIMITED
    if "401" in message or "403" in message or "unauthorized" in message:
        return PROVIDER_ERROR
    return PROVIDER_ERROR


def sanitize_provider_message(error: Exception | str | None) -> str:
    """Return a user-safe provider message without secrets or raw internals."""
    if error is None:
        return "Supplier lookup failed."
    text = str(error).strip()
    if not text:
        return "Supplier lookup failed."
    lowered = text.lower()
    secret_markers = (
        "api_key",
        "apikey",
        "authorization",
        "bearer ",
        "client_secret",
        "password",
        "token",
    )
    if any(marker in lowered for marker in secret_markers):
        return "Supplier authentication or configuration failed."
    if len(text) > 160:
        return "Supplier lookup failed."
    return text


def provider_status_label(status: str) -> str:
    labels = {
        PROVIDER_AVAILABLE: "available",
        PROVIDER_PART_NOT_FOUND: "part not found",
        PROVIDER_NOT_CONFIGURED: "not configured",
        PROVIDER_TIMEOUT: "timed out",
        PROVIDER_RATE_LIMITED: "rate limited",
        PROVIDER_ERROR: "provider error",
    }
    return labels.get(status, "unknown")


def summarize_provider_health(supplier_results: list[dict[str, Any]]) -> dict[str, Any]:
    configured = [
        result for result in supplier_results
        if result.get("provider_status") != PROVIDER_NOT_CONFIGURED
    ]
    available = [
        result for result in supplier_results
        if result.get("provider_status") == PROVIDER_AVAILABLE
    ]
    failed = [
        result for result in supplier_results
        if result.get("provider_status") in _FAILURE_STATUSES
        and result.get("provider_status") != PROVIDER_NOT_CONFIGURED
    ]
    part_not_found = [
        result for result in supplier_results
        if result.get("provider_status") == PROVIDER_PART_NOT_FOUND
    ]

    configured_count = len(configured)
    successful_count = len(available)
    has_verified_data = successful_count > 0

    failed_sources = sorted(
        {
            str(result.get("source") or "Supplier").strip()
            for result in failed
            if str(result.get("source") or "").strip()
        }
    )
    available_sources = sorted(
        str(result.get("source") or "Supplier").strip()
        for result in available
        if str(result.get("source") or "").strip()
    )
    not_configured_sources = sorted(
        str(result.get("source") or "Supplier").strip()
        for result in supplier_results
        if result.get("provider_status") == PROVIDER_NOT_CONFIGURED
        and str(result.get("source") or "").strip()
    )

    if configured_count == 0:
        summary_message = "No supplier integrations are configured for this analysis."
    elif has_verified_data and failed:
        summary_message = (
            f"{successful_count} of {configured_count} configured supplier sources "
            f"responded successfully."
        )
    elif has_verified_data:
        summary_message = (
            f"{successful_count} of {configured_count} configured supplier sources "
            f"responded successfully."
        )
    elif failed and not part_not_found:
        summary_message = "Supplier data could not be verified during this analysis."
    elif failed and part_not_found:
        summary_message = (
            "Some supplier data could not be verified during this analysis."
        )
    elif part_not_found and not failed:
        summary_message = "No configured supplier returned a matching part record."
    else:
        summary_message = "Supplier data could not be verified during this analysis."

    return {
        "configured_count": configured_count,
        "successful_count": successful_count,
        "failed_count": len(failed),
        "part_not_found_count": len(part_not_found),
        "failed_sources": failed_sources,
        "available_sources": available_sources,
        "not_configured_sources": not_configured_sources,
        "has_verified_data": has_verified_data,
        "summary_message": summary_message,
    }


def unverified_supplier_reason_replacements() -> dict[str, str]:
    """Map misleading verified-style risk reasons to unverified wording."""
    return {
        "No stock available": "Stock could not be verified during this analysis",
        "Single-source supply risk": "Supplier coverage could not be verified during this analysis",
        "Limited supplier diversity": "Supplier diversity could not be verified during this analysis",
        "Limited supplier diversity with constrained inventory": (
            "Supplier diversity and inventory could not be verified during this analysis"
        ),
        "Lifecycle status is unknown": "Lifecycle status could not be verified during this analysis",
        "No alternate parts found": "Alternate availability could not be verified during this analysis",
    }
