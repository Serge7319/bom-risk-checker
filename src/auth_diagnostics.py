"""Optional runtime auth/session diagnostics (disabled by default in production).

Enable with environment variable CADIVOR_AUTH_DIAGNOSTICS=true for short-lived
forensics. Never logs token values, passwords, or cookie contents.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from src.secrets import get_secret_bool


def diagnostics_enabled() -> bool:
    return get_secret_bool("CADIVOR_AUTH_DIAGNOSTICS", default=False)


def log_runtime_diagnostic(event: str, **details: Any) -> None:
    if not diagnostics_enabled():
        return
    safe = {
        str(key): str(value)[:240]
        for key, value in details.items()
        if str(key).lower() not in {"access_token", "refresh_token", "password", "api_key", "cookie"}
        and "token" not in str(key).lower()
    }
    parts = " ".join(f"{key}={value}" for key, value in sorted(safe.items()))
    line = f"[cadivor-diag] ts={datetime.now(timezone.utc).isoformat(timespec='milliseconds')} event={event}"
    if parts:
        line = f"{line} {parts}"
    print(line, flush=True)


def log_bootstrap_diagnostic(*, stage: str, auth_status: str | None = None, **extra: Any) -> None:
    if not diagnostics_enabled():
        return
    payload = {"bootstrap_stage": stage, **extra}
    if auth_status is not None:
        payload["resolved_auth_status"] = auth_status
    log_runtime_diagnostic("bootstrap", **payload)


def log_copilot_diagnostic(*, phase: str, **extra: Any) -> None:
    if not diagnostics_enabled():
        return
    log_runtime_diagnostic("copilot", copilot_phase=phase, **extra)
