"""Authenticated bridge to the existing Supabase subscription checkout.

Stripe credentials and configured Price IDs remain in Supabase Edge Functions.
The Next API forwards only the caller's verified Supabase access token.
"""
from __future__ import annotations

import json
import hashlib
import hmac
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ALLOWED_ACTIONS = frozenset({
    "status",
    "entitlements",
    "checkout",
    "portal",
    "addons_catalog",
    "professional_api_addon_checkout",
    "monitored_parts_addon_checkout",
    "monitored_parts_addon_remove",
    "usage_overage_checkout",
    "reserve_usage_credit",
    "finish_usage_credit",
    "ai_usage_balance",
    "reserve_ai_question_credit",
    "finish_ai_question_credit",
    "allocate_monitored_part_credits",
    "developer_api_keys_list",
    "developer_api_key_create",
    "developer_api_key_revoke",
    "developer_api_access_override_sync",
    "admin_validate_account_deletion",
    "admin_prepare_account_deletion",
    "admin_delete_account",
    "admin_sync_account_status",
    "admin_manual_plan_billing_list",
    "admin_manual_plan_invoice_create",
    "admin_manual_plan_invoice_send",
    "admin_manual_plan_payment_record",
    "admin_manual_plan_invoice_void",
})

PUBLIC_ACTIONS = frozenset({"catalog", "addons_catalog", "developer_api_key_resolve"})
INTERNAL_ACTIONS = frozenset({
    "developer_api_keys_list",
    "developer_api_key_create",
    "developer_api_key_revoke",
    "reserve_usage_credit",
    "finish_usage_credit",
    "ai_usage_balance",
    "reserve_ai_question_credit",
    "finish_ai_question_credit",
    "allocate_monitored_part_credits",
})


class SubscriptionBillingError(RuntimeError):
    """The subscription billing function could not be reached."""


def bridge_configured() -> bool:
    base = str(os.environ.get("SUPABASE_URL") or "").strip()
    key = str(os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    return bool(base and key)


def _canonical_json(value: Any) -> str:
    """Stable JSON shared with the Supabase Edge Function proof verifier."""
    if isinstance(value, dict):
        return "{" + ",".join(
            f"{json.dumps(str(key), ensure_ascii=False)}:{_canonical_json(value[key])}"
            for key in sorted(value, key=lambda item: str(item))
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _internal_action_proof(
    *, action: str, user_id: str, workspace_id: str, payload: dict[str, Any]
) -> str:
    """Sign API-only Edge actions with a secret unavailable to browser clients."""
    secret = str(os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not secret:
        raise SubscriptionBillingError("Internal billing action proof is not configured.")
    message = "\n".join((action, user_id, workspace_id, _canonical_json(payload)))
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def request_action(
    *,
    access_token: str,
    action: str,
    payload: dict[str, Any] | None = None,
    origin: str = "",
    timeout_seconds: float = 15,
    internal_context: dict[str, str] | None = None,
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

    body = {"action": selected, **(payload or {})}
    if selected in INTERNAL_ACTIONS:
        actor = str((internal_context or {}).get("user_id") or "").strip()
        workspace = str((internal_context or {}).get("workspace_id") or "").strip()
        if not actor or not workspace:
            raise SubscriptionBillingError("Internal billing action context is missing.")
        body["_cadivor_internal_proof"] = _internal_action_proof(
            action=selected,
            user_id=actor,
            workspace_id=workspace,
            payload={key: value for key, value in body.items() if key != "action"},
        )

    request = Request(
        f"{base}/functions/v1/subscription-checkout",
        data=json.dumps(body, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"),
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


def request_public_catalog(*, timeout_seconds: float = 10) -> tuple[dict[str, Any], int]:
    """Read Stripe's public plan catalog without an account access token."""
    base = str(os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    public_key = (
        str(os.environ.get("SUPABASE_ANON_KEY") or "").strip()
        or str(os.environ.get("SUPABASE_KEY") or "").strip()
    )
    if not base or not public_key:
        raise SubscriptionBillingError("Subscription billing is not configured.")

    request = Request(
        f"{base}/functions/v1/subscription-checkout",
        data=b'{"action":"catalog"}',
        headers={
            "apikey": public_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            raw = response.read(256_000)
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read(256_000)
    except (TimeoutError, URLError, OSError):
        raise SubscriptionBillingError("Subscription pricing is temporarily unavailable.") from None

    try:
        result = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        result = {}
    return (result if isinstance(result, dict) else {}), status


def request_public_action(
    *,
    action: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 5,
) -> tuple[dict[str, Any], int]:
    """Call a deliberately public, narrowly allow-listed Edge action."""
    selected = str(action or "").strip().lower()
    if selected not in PUBLIC_ACTIONS:
        return {"ok": False, "detail": "Unknown public billing action."}, 400
    base = str(os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    public_key = (
        str(os.environ.get("SUPABASE_KEY") or "").strip()
        or str(os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    )
    if not base or not public_key:
        raise SubscriptionBillingError("Subscription billing is not configured.")
    request = Request(
        f"{base}/functions/v1/subscription-checkout",
        data=json.dumps({"action": selected, **(payload or {})}, separators=(",", ":")).encode("utf-8"),
        headers={
            "apikey": public_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            raw = response.read(256_000)
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read(256_000)
    except (TimeoutError, URLError, OSError):
        raise SubscriptionBillingError("Subscription billing is temporarily unavailable.") from None
    try:
        result = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        result = {}
    return (result if isinstance(result, dict) else {}), status
