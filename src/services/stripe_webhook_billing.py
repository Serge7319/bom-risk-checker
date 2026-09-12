"""Billing decisions for the stripe-webhook Edge Function.

The versioned handler is ``supabase/functions/stripe-webhook/index.ts``.
This module is the executable contract those handlers and the unapplied
lease RPCs must follow. A Checkout success page is not entitlement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from src.plans import (
    PLAN_GRANDFATHERED_BETA,
    PLAN_SUBSCRIPTION_INACTIVE,
    PLAN_STUDENT,
    PLAN_TRIAL,
    PLAN_TRIAL_EXPIRED,
    has_grandfather_marker,
)

PAID_PLANS = ("Starter", "Professional", "Business")
PLAN_TOKENS = {
    "starter": "Starter",
    "professional": "Professional",
    "business": "Business",
}
PRICE_ENV = {
    "Starter": "STRIPE_STARTER_PRICE_ID",
    "Professional": "STRIPE_PRO_PRICE_ID",
    "Business": "STRIPE_BUSINESS_PRICE_ID",
}
ENTITLING_STATUSES = frozenset({"active", "trialing"})
PROTECTED_PLANS = frozenset({PLAN_STUDENT, PLAN_TRIAL, PLAN_TRIAL_EXPIRED})
LEASE_SECONDS = 120


class WebhookConfigurationError(Exception):
    """Retryable configuration error. Do not mark the event processed."""


@dataclass
class EventRecord:
    event_id: str
    event_type: str = ""
    livemode: bool = False
    event_created: datetime | None = None
    processing_status: str = "processing"
    lease_expires_at: datetime | None = None
    user_id: str | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    last_error: str | None = None
    apply_outcome: str | None = None


@dataclass
class EventStore:
    rows: dict[str, EventRecord] = field(default_factory=dict)

    def claim(
        self,
        *,
        event_id: str,
        event_type: str,
        livemode: bool,
        event_created: datetime | None,
        now: datetime,
        lease_seconds: int = LEASE_SECONDS,
    ) -> str:
        """Atomic claim transitions: claimed, duplicate, or busy.

        A failed apply must call release(). Claiming does not mark the event
        processed, so a crash or a configuration error cannot permanently
        block Stripe retries.
        """
        existing = self.rows.get(event_id)
        lease_end = now + timedelta(seconds=max(lease_seconds, 1))
        if existing is None:
            self.rows[event_id] = EventRecord(
                event_id=event_id,
                event_type=event_type,
                livemode=livemode,
                event_created=event_created,
                processing_status="processing",
                lease_expires_at=lease_end,
            )
            return "claimed"
        if existing.processing_status == "processed":
            return "duplicate"
        if (
            existing.processing_status == "processing"
            and existing.lease_expires_at is not None
            and existing.lease_expires_at > now
        ):
            return "busy"
        existing.processing_status = "processing"
        existing.lease_expires_at = lease_end
        existing.event_type = event_type or existing.event_type
        existing.event_created = event_created or existing.event_created
        existing.last_error = None
        return "claimed"

    def latest_applied_created(self, subscription_id: str | None) -> datetime | None:
        if not subscription_id:
            return None
        created = [
            row.event_created
            for row in self.rows.values()
            if row.processing_status == "processed"
            and row.apply_outcome == "applied"
            and row.stripe_subscription_id == subscription_id
            and row.event_created is not None
        ]
        return max(created) if created else None

    def complete(
        self,
        event_id: str,
        *,
        user_id: str | None,
        customer_id: str | None,
        subscription_id: str | None,
        outcome: str,
    ) -> None:
        row = self.rows[event_id]
        row.processing_status = "processed"
        row.lease_expires_at = None
        row.user_id = user_id
        row.stripe_customer_id = customer_id
        row.stripe_subscription_id = subscription_id
        row.apply_outcome = outcome
        row.last_error = None

    def release(self, event_id: str, error: str, now: datetime) -> None:
        row = self.rows.get(event_id)
        if row is None or row.processing_status == "processed":
            return
        row.processing_status = "failed"
        row.lease_expires_at = now
        row.last_error = error


def resolve_paid_plan(
    metadata: dict | None,
    price_id: str | None,
    price_ids: dict[str, str] | None,
) -> str | None:
    """Resolve a paid plan, or raise when metadata and price disagree.

    Metadata is preferred. A configured price id is only the fallback. An
    unknown token or price does not guess Starter.
    """
    payload = metadata or {}
    token = str(payload.get("cadivor_plan") or "").strip().lower()
    metadata_plan = PLAN_TOKENS.get(token) if token else None
    unknown_token = bool(token) and metadata_plan is None
    price_plan = _plan_for_price(price_id, price_ids)
    if unknown_token and price_plan:
        raise WebhookConfigurationError(
            "cadivor_plan metadata and Stripe price id disagree."
        )
    if metadata_plan and price_plan and metadata_plan != price_plan:
        raise WebhookConfigurationError(
            "cadivor_plan metadata and Stripe price id disagree."
        )
    if unknown_token:
        return None
    return metadata_plan or price_plan


def _plan_for_price(price_id: str | None, price_ids: dict[str, str] | None) -> str | None:
    resolved = str(price_id or "").strip()
    if not resolved or not price_ids:
        return None
    for plan_name, configured in price_ids.items():
        if plan_name in PLAN_TOKENS.values() and str(configured or "").strip() == resolved:
            return plan_name
    return None


def price_id_of(subscription: dict) -> str | None:
    items = ((subscription or {}).get("items") or {}).get("data") or []
    if not items:
        return None
    price = items[0].get("price") or {}
    value = price.get("id") if isinstance(price, dict) else None
    return str(value).strip() if value else None


def as_id(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict) and isinstance(value.get("id"), str):
        return value["id"].strip() or None
    return None


def is_admin(user: dict | None) -> bool:
    return str((user or {}).get("role") or "").strip().lower() == "admin"


def build_subscription_update(
    user: dict,
    subscription: dict,
    *,
    price_ids: dict[str, str],
    event_created: datetime | None,
) -> dict[str, Any]:
    """Return the users update for one subscription snapshot.

    Raises WebhookConfigurationError instead of granting entitlement when
    metadata and price disagree, or when an entitling status has no mapped plan.
    """
    status = str(subscription.get("status") or "").strip().lower()
    mapped = resolve_paid_plan(
        subscription.get("metadata") or {},
        price_id_of(subscription),
        price_ids,
    )
    entitling = status in ENTITLING_STATUSES
    if entitling and not mapped:
        raise WebhookConfigurationError(
            "Active subscription is not mapped to a Cadivor paid plan."
        )
    updates: dict[str, Any] = {
        "stripe_customer_id": as_id(subscription.get("customer")),
        "stripe_subscription_id": subscription.get("id"),
        "stripe_subscription_status": subscription.get("status"),
        "stripe_price_id": price_id_of(subscription),
        "stripe_current_period_end": _as_iso(subscription.get("current_period_end")),
        "stripe_cancel_at_period_end": bool(subscription.get("cancel_at_period_end")),
        "billing_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if event_created is not None:
        updates["stripe_last_event_created"] = event_created.isoformat()
    if entitling and mapped:
        updates["plan"] = mapped
        updates["plan_changed_at"] = updates["billing_updated_at"]
    else:
        restored = _non_paying_plan(user)
        if restored and restored != str(user.get("plan") or "").strip():
            updates["plan"] = restored
            updates["plan_changed_at"] = updates["billing_updated_at"]
    # Never clear plan_grandfather_source. A later cancellation uses it.
    return updates


def _non_paying_plan(user: dict) -> str | None:
    """Plan label to store when the snapshot does not entitle.

    Student, Trial, and Trial expired are left unchanged. A grandfather
    marker restores Grandfathered beta. Everyone else who still carries a
    paid or beta label becomes Subscription inactive. Never write Starter.
    """
    stored = str((user or {}).get("plan") or "").strip()
    if stored in PROTECTED_PLANS:
        return None
    if has_grandfather_marker(user):
        return PLAN_GRANDFATHERED_BETA
    if stored in {*PAID_PLANS, PLAN_GRANDFATHERED_BETA}:
        return PLAN_SUBSCRIPTION_INACTIVE
    return None


def _as_iso(unix_seconds: Any) -> str | None:
    if not isinstance(unix_seconds, (int, float)):
        return None
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()


def snapshot_is_stale(
    store: EventStore,
    subscription_id: str | None,
    event_created: datetime | None,
    *,
    user: dict | None = None,
) -> bool:
    if event_created is None:
        return False
    latest = store.latest_applied_created(subscription_id)
    if latest is not None and event_created < latest:
        return True
    recorded = _parse_dt((user or {}).get("stripe_last_event_created"))
    return recorded is not None and event_created < recorded


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def subscription_id_from_event(event: dict, *, retrieved: dict | None = None) -> str | None:
    obj = (event.get("data") or {}).get("object") or {}
    event_type = str(event.get("type") or "")
    if event_type == "checkout.session.completed":
        return as_id(obj.get("subscription")) or as_id((retrieved or {}).get("id"))
    if event_type.startswith("invoice."):
        return as_id(obj.get("subscription"))
    if event_type.startswith("customer.subscription."):
        return as_id(obj.get("id"))
    return None


def apply_event(
    event: dict,
    *,
    users: dict[str, dict],
    store: EventStore,
    price_ids: dict[str, str],
    now: datetime,
    retrieve_subscription,
) -> dict[str, Any]:
    """Apply one verified Stripe event. Returns a handler result, never raises.

    ``status`` is the HTTP status the Edge Function should return.
    """
    event_id = str(event.get("id") or "")
    event_created = datetime.fromtimestamp(int(event.get("created") or 0), tz=timezone.utc)
    claim = store.claim(
        event_id=event_id,
        event_type=str(event.get("type") or ""),
        livemode=bool(event.get("livemode")),
        event_created=event_created,
        now=now,
    )
    if claim == "duplicate":
        return {"status": 200, "received": True, "duplicate": True}
    if claim == "busy":
        return {"status": 500, "received": False, "busy": True}

    try:
        result = _apply_claimed(
            event,
            users=users,
            store=store,
            price_ids=price_ids,
            event_created=event_created,
            retrieve_subscription=retrieve_subscription,
        )
    except WebhookConfigurationError as exc:
        store.release(event_id, str(exc), now)
        return {"status": 500, "received": False, "error": str(exc)}
    except Exception as exc:
        store.release(event_id, str(exc), now)
        return {"status": 500, "received": False, "error": str(exc)}

    store.complete(
        event_id,
        user_id=result.get("user_id"),
        customer_id=result.get("customer_id"),
        subscription_id=result.get("subscription_id"),
        outcome=result["outcome"],
    )
    return {"status": 200, "received": True, "outcome": result["outcome"]}


def _apply_claimed(
    event: dict,
    *,
    users: dict[str, dict],
    store: EventStore,
    price_ids: dict[str, str],
    event_created: datetime,
    retrieve_subscription,
) -> dict[str, Any]:
    event_type = str(event.get("type") or "")
    obj = (event.get("data") or {}).get("object") or {}
    subscription = None
    if event_type == "checkout.session.completed":
        subscription_id = as_id(obj.get("subscription"))
        if not subscription_id:
            raise WebhookConfigurationError("Completed checkout has no subscription.")
        subscription = retrieve_subscription(subscription_id)
    elif event_type.startswith("customer.subscription."):
        subscription = obj
    elif event_type in {"invoice.payment_failed", "invoice.paid"}:
        subscription_id = as_id(obj.get("subscription"))
        if not subscription_id:
            return {"outcome": "ignored", "user_id": None, "customer_id": None, "subscription_id": None}
        subscription = retrieve_subscription(subscription_id)
    else:
        return {"outcome": "ignored", "user_id": None, "customer_id": None, "subscription_id": None}

    user_id = str((subscription.get("metadata") or {}).get("user_id") or "").strip()
    if not user_id:
        raise WebhookConfigurationError("Subscription is missing Cadivor user metadata.")
    user = users.get(user_id)
    if not user:
        raise WebhookConfigurationError("Cadivor user was not found.")
    subscription_id = as_id(subscription.get("id"))
    customer_id = as_id(subscription.get("customer"))
    if is_admin(user):
        return {
            "outcome": "admin_untouched",
            "user_id": user_id,
            "customer_id": customer_id,
            "subscription_id": subscription_id,
        }
    if snapshot_is_stale(store, subscription_id, event_created, user=user):
        return {
            "outcome": "skipped_stale",
            "user_id": user_id,
            "customer_id": customer_id,
            "subscription_id": subscription_id,
        }
    updates = build_subscription_update(
        user,
        subscription,
        price_ids=price_ids,
        event_created=event_created,
    )
    recorded = _parse_dt(user.get("stripe_last_event_created"))
    if recorded is not None and event_created < recorded:
        return {
            "outcome": "skipped_stale",
            "user_id": user_id,
            "customer_id": customer_id,
            "subscription_id": subscription_id,
        }
    user.update(updates)
    return {
        "outcome": "applied",
        "user_id": user_id,
        "customer_id": customer_id,
        "subscription_id": subscription_id,
    }
