"""Opt-in Cadivor performance timing (Sprint 75.1).

Disabled unless CADIVOR_STARTUP_TIMING is truthy (env or Streamlit secrets).
Never logs secrets, PII, tokens, BOM/part content, prompts, or raw exceptions.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

PERF_LOG_PREFIX = "CADIVOR_PERF"
TIMING_FLAG = "CADIVOR_STARTUP_TIMING"

# Railway / deploy version allowlist only — never dump os.environ.
_DEPLOY_VERSION_ENV_KEYS = (
    "RAILWAY_GIT_COMMIT_SHA",
    "RAILWAY_GIT_COMMIT",
    "RAILWAY_DEPLOYMENT_ID",
)

_ROUTE_ALLOWLIST = frozenset(
    {
        "dashboard",
        "bom_analyzer",
        "alternative_finder",
        "design_impact",
        "engineering_decisions",
        "procurement_advisor",
        "cost_optimization",
        "supply_scenario",
        "monitoring",
        "portfolio_intelligence",
        "reports",
        "settings",
        "help",
        "analysis_details",
        "onboarding",
        "workspace",
        "notifications",
        "about",
        "admin",
        "pricing",
        "unknown",
        "signed_out",
        "password_recovery",
        "signup_confirmation",
        "authenticated",
    }
)

_PROVIDER_ALLOWLIST = frozenset(
    {
        "mouser",
        "digikey",
        "newark",
        "octopart",
        "openai",
        "supabase",
        "unknown",
    }
)

_OUTCOME_ALLOWLIST = frozenset(
    {
        "success",
        "error",
        "empty",
        "timeout",
        "unavailable",
        "retry",
        "continue",
        "settled",
        "stopped",
        "redirected",
        "signed_out",
        "authenticated",
        "other",
    }
)

_OPERATION_ALLOWLIST = frozenset(
    {
        "read",
        "lookup",
        "http",
        "import",
        "render",
        "hydrate",
        "validate",
        "resolve",
        "init",
        "other",
        # supabase_read logical ops (normalized)
        "load_user_data",
        "load_analysis_history",
        "workspace_commands",
        "ensure_user_profile",
        "supabase_read",
        "other_read",
    }
)

_APP_MODE_TO_ROUTE = {
    "Dashboard": "dashboard",
    "BOM Analyzer": "bom_analyzer",
    "Alternative Finder": "alternative_finder",
    "Design Impact Analyzer": "design_impact",
    "Engineering Decisions": "engineering_decisions",
    "Procurement Advisor": "procurement_advisor",
    "Cost Optimization": "cost_optimization",
    "Supply Risk Scenario": "supply_scenario",
    "Monitoring": "monitoring",
    "Portfolio Intelligence": "portfolio_intelligence",
    "Reports": "reports",
    "Settings": "settings",
    "Help": "help",
    "Analysis Details": "analysis_details",
    "Onboarding": "onboarding",
    "Workspace": "workspace",
    "Notifications": "notifications",
    "About": "about",
    "Admin": "admin",
    "Pricing": "pricing",
}

_PROVIDER_ALIASES = {
    "mouser": "mouser",
    "digikey": "digikey",
    "digi-key": "digikey",
    "digi_key": "digikey",
    "newark": "newark",
    "element14": "newark",
    "octopart": "octopart",
    "openai": "openai",
    "supabase": "supabase",
}


def timing_enabled() -> bool:
    """Return True only when CADIVOR_STARTUP_TIMING is explicitly enabled."""
    try:
        from src.secrets import get_secret_bool

        return bool(get_secret_bool(TIMING_FLAG, default=False))
    except Exception:
        raw = os.getenv(TIMING_FLAG)
        if raw is None or str(raw).strip() == "":
            return False
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def deployment_version() -> str:
    """Short deploy/commit id from allowlisted Railway env vars only."""
    for key in _DEPLOY_VERSION_ENV_KEYS:
        try:
            value = os.getenv(key)
        except Exception:
            value = None
        if value and str(value).strip():
            text = str(value).strip()
            return text[:12] if len(text) > 12 else text
    return "unknown"


def normalize_route(label: Any) -> str:
    if label is None:
        return "unknown"
    text = str(label).strip()
    if not text:
        return "unknown"
    mapped = _APP_MODE_TO_ROUTE.get(text)
    if mapped:
        return mapped
    slug = text.lower().replace(" ", "_").replace("-", "_")
    if slug in _ROUTE_ALLOWLIST:
        return slug
    return "unknown"


def normalize_provider(label: Any) -> str:
    if label is None:
        return "unknown"
    key = str(label).strip().lower().replace(" ", "")
    key = key.replace("_", "").replace("-", "")
    # Re-check with common separators preserved for alias table
    raw = str(label).strip().lower()
    if raw in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[raw]
    compact = raw.replace(" ", "").replace("_", "").replace("-", "")
    for alias, canonical in _PROVIDER_ALIASES.items():
        if alias.replace("-", "").replace("_", "") == compact:
            return canonical
    if raw in _PROVIDER_ALLOWLIST:
        return raw
    return "unknown"


def normalize_operation(label: Any) -> str:
    if label is None:
        return "other"
    text = str(label).strip().lower()
    if text in _OPERATION_ALLOWLIST:
        return text
    # Map common caller strings without leaking free-form content.
    if "user" in text and "data" in text:
        return "load_user_data"
    if "history" in text:
        return "load_analysis_history"
    if "command" in text:
        return "workspace_commands"
    if "profile" in text:
        return "ensure_user_profile"
    if text in {"read", "select", "execute"}:
        return "supabase_read"
    return "other_read" if "read" in text or "select" in text else "other"


def safe_outcome(value: Any, *, default: str = "other") -> str:
    text = str(value or default).strip().lower()
    if text in _OUTCOME_ALLOWLIST:
        return text
    return default


def row_count_bucket(count: Any) -> str:
    """Coarse cardinality bucket — never exact sensitive sizes beyond ranges."""
    try:
        n = int(count)
    except Exception:
        return "unknown"
    if n <= 0:
        return "0"
    if n <= 10:
        return "1_10"
    if n <= 100:
        return "11_100"
    if n <= 1000:
        return "101_1000"
    if n <= 5000:
        return "1001_5000"
    return "5001_plus"


def _round_ms(seconds: float) -> float:
    return round(max(0.0, float(seconds) * 1000.0), 1)


def emit_timing(
    phase: str,
    *,
    duration_ms: float | None = None,
    outcome: str = "success",
    route: str | None = None,
    provider: str | None = None,
    operation: str | None = None,
    attempt: int | None = None,
    max_attempts: int | None = None,
    row_count: Any = None,
    cache_status: str | None = None,
    event: str = "phase_complete",
    **_ignored: Any,
) -> None:
    """Emit one CADIVOR_PERF line when timing is enabled. Never raises."""
    try:
        if not timing_enabled():
            return
        payload: dict[str, Any] = {
            "event": str(event or "phase_complete"),
            "phase": str(phase or "unknown")[:96],
            "outcome": safe_outcome(outcome),
            "deploy": deployment_version(),
        }
        if duration_ms is not None:
            try:
                payload["duration_ms"] = round(max(0.0, float(duration_ms)), 1)
            except Exception:
                payload["duration_ms"] = 0.0
        if route is not None:
            payload["route"] = normalize_route(route)
        if provider is not None:
            payload["provider"] = normalize_provider(provider)
        if operation is not None:
            payload["operation"] = normalize_operation(operation)
        if attempt is not None:
            try:
                payload["attempt"] = int(attempt)
            except Exception:
                pass
        if max_attempts is not None:
            try:
                payload["max_attempts"] = int(max_attempts)
            except Exception:
                pass
        if row_count is not None:
            payload["row_count_bucket"] = row_count_bucket(row_count)
        if cache_status in {"hit", "miss", "unknown"}:
            payload["cache_status"] = cache_status
        line = f"{PERF_LOG_PREFIX} {json.dumps(payload, separators=(',', ':'), sort_keys=True)}"
        print(line, flush=True)
    except Exception:
        return


@contextmanager
def timed_phase(
    phase: str,
    *,
    route: str | None = None,
    provider: str | None = None,
    operation: str | None = None,
    attempt: int | None = None,
    max_attempts: int | None = None,
    cache_status: str | None = None,
    outcome_on_success: str = "success",
) -> Iterator[dict[str, Any]]:
    """Measure a phase. Re-raises exceptions unchanged. Logs in finally when enabled."""
    meta: dict[str, Any] = {"outcome": outcome_on_success, "row_count": None}
    enabled = False
    started = 0.0
    try:
        enabled = timing_enabled()
    except Exception:
        enabled = False
    if enabled:
        started = time.perf_counter()
    try:
        yield meta
    except Exception:
        meta["outcome"] = "error"
        raise
    finally:
        if not enabled:
            return
        try:
            duration_ms = _round_ms(time.perf_counter() - started)
            emit_timing(
                phase,
                duration_ms=duration_ms,
                outcome=safe_outcome(meta.get("outcome"), default="success"),
                route=route,
                provider=provider,
                operation=operation,
                attempt=attempt,
                max_attempts=max_attempts,
                row_count=meta.get("row_count"),
                cache_status=cache_status,
            )
        except Exception:
            pass


def supplier_outcome_from_status(provider_status: Any) -> str:
    text = str(provider_status or "").strip().lower()
    if text in {"available", "ok", "success"}:
        return "success"
    if text in {"part_not_found", "empty"}:
        return "empty"
    if "timeout" in text:
        return "timeout"
    if text in {"not_configured", "unavailable"}:
        return "unavailable"
    if "rate" in text:
        return "unavailable"
    if text in {"error", "failed", "provider_error"}:
        return "error"
    return "other"
