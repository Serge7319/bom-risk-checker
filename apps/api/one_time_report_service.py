"""Authenticated bridge to the existing Supabase one-time report service.

Stripe secrets and the service-role key remain inside Supabase Edge Functions;
the migration API forwards only the caller's already-verified access token.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ALLOWED_ACTIONS = frozenset({"status", "checkout", "reserve", "release", "consume"})


class OneTimeReportServiceError(RuntimeError):
    """The existing Supabase purchase/credit service could not be reached."""


def request_action(
    *,
    access_token: str,
    action: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 15,
) -> tuple[dict[str, Any], int]:
    """Call the existing Supabase function without exposing privileged keys."""
    selected = str(action or "").strip().lower()
    if selected not in ALLOWED_ACTIONS:
        return {"ok": False, "detail": "Unknown one-time report action."}, 400

    base = str(os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    public_key = (
        str(os.environ.get("SUPABASE_KEY") or "").strip()
        or str(os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    )
    token = str(access_token or "").strip()
    if not base or not public_key or not token:
        raise OneTimeReportServiceError("One-time report service is not configured.")

    body = {"action": selected, **(payload or {})}
    request = Request(
        f"{base}/functions/v1/one-time-report",
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": public_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            raw = response.read(1_000_000)
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read(1_000_000)
    except (TimeoutError, URLError, OSError):
        raise OneTimeReportServiceError(
            "One-time report service is temporarily unavailable."
        ) from None

    try:
        result = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        result = {}
    if not isinstance(result, dict):
        result = {}
    return result, status
