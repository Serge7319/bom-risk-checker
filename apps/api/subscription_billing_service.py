"""Authenticated bridge to the existing Supabase subscription checkout.

Stripe credentials and configured Price IDs remain in Supabase Edge Functions.
The Next API forwards only the caller's verified Supabase access token.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ALLOWED_ACTIONS = frozenset({"status", "entitlements", "checkout", "portal"})


class SubscriptionBillingError(RuntimeError):
    """The subscription billing function could not be reached."""


def bridge_configured() -> bool:
    base = str(os.environ.get("SUPABASE_URL") or "").strip()
    key = str(os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    return bool(base and key)


def request_action(
    *,
    access_token: str,
    action: str,
    payload: dict[str, Any] | None = None,
    origin: str = "",
    timeout_seconds: float = 15,
) -> tuple[dict[str, Any], int]:
    selected = str(action or "").strip().lower()
    if selected not in ALLOWED_ACTIONS:
        return {"ok": False, "detail": "Unknown billing action."}, 400

    base = str(os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    public_key = (
        str(os.environ.get("SUPABASE_KEY") or "").strip()
        or str(os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    )
    token = str(access_token or "").strip()
    if not base or not public_key or not token:
        raise SubscriptionBillingError("Subscription billing is not configured.")

    request = Request(
        f"{base}/functions/v1/subscription-checkout",
        data=json.dumps({"action": selected, **(payload or {})}, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": public_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            **({"Origin": origin} if origin else {}),
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
        raise SubscriptionBillingError("Subscription billing is temporarily unavailable.") from None

    try:
        result = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        result = {}
    return (result if isinstance(result, dict) else {}), status
