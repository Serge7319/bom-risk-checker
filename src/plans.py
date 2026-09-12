"""Cadivor plan and access source of truth.

Starter is the paid $29 plan only. Beta access is reserved for rows the
grandfather migration marked with a non-null ``plan_grandfather_source``.
Plan text and Stripe ids do not confer that eligibility. Trial expiry is a
distinct view-only state, not a downgrade to Starter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

UNLIMITED = None

PLAN_STUDENT = "Student"
PLAN_TRIAL = "Trial"
PLAN_TRIAL_EXPIRED = "Trial expired"
PLAN_GRANDFATHERED_BETA = "Grandfathered beta"
PLAN_SUBSCRIPTION_INACTIVE = "Subscription inactive"
PLAN_STARTER = "Starter"
PLAN_PROFESSIONAL = "Professional"
PLAN_BUSINESS = "Business"
PLAN_ENTERPRISE = "Enterprise"

# Normalized values written to Stripe Checkout and subscription metadata.
CHECKOUT_PLAN_TOKENS = {
    PLAN_STARTER: "starter",
    PLAN_PROFESSIONAL: "professional",
    PLAN_BUSINESS: "business",
}
CHECKOUT_PRICE_SECRETS = {
    PLAN_STARTER: "STRIPE_STARTER_PRICE_ID",
    PLAN_PROFESSIONAL: "STRIPE_PRO_PRICE_ID",
    PLAN_BUSINESS: "STRIPE_BUSINESS_PRICE_ID",
}
# Optional. Do not create annual Stripe prices to populate these. A missing
# value means the Live catalog is monthly-only and the UI must not invent a
# yearly price or a savings claim.
ANNUAL_CHECKOUT_PRICE_SECRETS = {
    PLAN_STARTER: "STRIPE_STARTER_ANNUAL_PRICE_ID",
    PLAN_PROFESSIONAL: "STRIPE_PRO_ANNUAL_PRICE_ID",
    PLAN_BUSINESS: "STRIPE_BUSINESS_ANNUAL_PRICE_ID",
}
_TOKEN_TO_PLAN = {token: name for name, token in CHECKOUT_PLAN_TOKENS.items()}
# Webhook-recorded stripe_subscription_status is the only paid-entitlement source.
# stripe_subscription_id and stripe_price_id are not entitlement: they can remain
# after cancellation or a failed payment.
#
# past_due policy: no grace period is implemented. PAST_DUE_GRACE_PERIOD stays
# None until a founder-approved window and a webhook timestamp exist. Until
# then, past_due does not grant paid access. Do not treat a non-None value as
# entitlement without updating paid_status_entitles().
PAST_DUE_GRACE_PERIOD = None
PAID_ENTITLING_STATUSES = frozenset({"active", "trialing"})
_PAID_PLAN_NAMES = frozenset({PLAN_STARTER, PLAN_PROFESSIONAL, PLAN_BUSINESS})
_CHECKOUT_RANK = {
    PLAN_STUDENT: 0,
    PLAN_TRIAL: 0,
    PLAN_TRIAL_EXPIRED: 0,
    PLAN_GRANDFATHERED_BETA: 0,
    PLAN_SUBSCRIPTION_INACTIVE: 0,
    PLAN_STARTER: 1,
    PLAN_PROFESSIONAL: 2,
    PLAN_BUSINESS: 3,
    PLAN_ENTERPRISE: 4,
}

_PAID_STARTER_LIMITS = {
    "ai_credits": 0,
    "monthly_bom_limit": 10,
    "max_parts_per_bom": 100,
    "max_saved_boms": 100,
    "monitored_parts_limit": 0,
    "team_features": False,
    "api_access": False,
    "datasheet_comparison": False,
    "student_watermark": False,
    "can_create_analyses": True,
    "price": "$29/mo",
    "upgrade_to": "Professional",
    "display_label": "Starter",
    "description": "Paid individual plan for prototype and early production reviews.",
}

PLANS = {
    PLAN_STUDENT: {
        "ai_credits": 0,
        "monthly_bom_limit": 5,
        "max_parts_per_bom": 50,
        "max_saved_boms": 25,
        "monitored_parts_limit": 0,
        "team_features": False,
        "api_access": False,
        "datasheet_comparison": False,
        "student_watermark": True,
        "can_create_analyses": True,
        "price": "$0",
        "upgrade_to": "Professional",
        "display_label": "Student",
        "description": "For verified students and academic projects.",
    },
    PLAN_TRIAL: {
        "ai_credits": 100,
        "monthly_bom_limit": UNLIMITED,
        "max_parts_per_bom": UNLIMITED,
        "max_saved_boms": UNLIMITED,
        "monitored_parts_limit": UNLIMITED,
        "team_features": True,
        "api_access": True,
        "datasheet_comparison": True,
        "student_watermark": False,
        "can_create_analyses": True,
        "price": "$0 for 14 days",
        "upgrade_to": "Starter",
        "display_label": "Trial",
        "description": "Full Cadivor evaluation access for 14 days. No card required.",
    },
    PLAN_TRIAL_EXPIRED: {
        "ai_credits": 0,
        "monthly_bom_limit": 0,
        "max_parts_per_bom": 0,
        "max_saved_boms": UNLIMITED,
        "monitored_parts_limit": 0,
        "team_features": False,
        "api_access": False,
        "datasheet_comparison": False,
        "student_watermark": False,
        "can_create_analyses": False,
        "price": "Trial ended",
        "upgrade_to": "Starter",
        "display_label": "Trial expired",
        "description": "Saved work remains available. New analyses require a paid plan.",
    },
    PLAN_SUBSCRIPTION_INACTIVE: {
        "ai_credits": 0,
        "monthly_bom_limit": 0,
        "max_parts_per_bom": 0,
        "max_saved_boms": UNLIMITED,
        "monitored_parts_limit": 0,
        "team_features": False,
        "api_access": False,
        "datasheet_comparison": False,
        "student_watermark": False,
        "can_create_analyses": False,
        "price": "Not active",
        "upgrade_to": "Starter",
        "display_label": "Subscription inactive",
        "description": (
            "The webhook-recorded subscription status is not active or trialing. "
            "Saved work remains available. New analyses require a paid plan."
        ),
    },
    PLAN_GRANDFATHERED_BETA: {
        **_PAID_STARTER_LIMITS,
        "price": "Beta access",
        "display_label": "Beta access",
        "description": "Grandfathered beta access. Not a paid Starter subscription.",
    },
    PLAN_STARTER: dict(_PAID_STARTER_LIMITS),
    PLAN_PROFESSIONAL: {
        "ai_credits": 500,
        "monthly_bom_limit": UNLIMITED,
        "max_parts_per_bom": UNLIMITED,
        "max_saved_boms": UNLIMITED,
        "monitored_parts_limit": 2500,
        "team_features": False,
        "api_access": False,
        "datasheet_comparison": True,
        "student_watermark": False,
        "can_create_analyses": True,
        "price": "$99/mo",
        "upgrade_to": "Business",
        "display_label": "Professional",
        "description": "For professional engineers and growing hardware teams.",
    },
    PLAN_BUSINESS: {
        "ai_credits": 2500,
        "included_users": 10,
        "monthly_bom_limit": UNLIMITED,
        "max_parts_per_bom": UNLIMITED,
        "max_saved_boms": UNLIMITED,
        "monitored_parts_limit": UNLIMITED,
        "team_features": True,
        "api_access": True,
        "datasheet_comparison": True,
        "student_watermark": False,
        "can_create_analyses": True,
        "price": "$299/mo",
        "upgrade_to": "Enterprise",
        "display_label": "Business",
        "description": "For teams standardizing engineering decisions.",
    },
    PLAN_ENTERPRISE: {
        "ai_credits": 10000,
        "included_users": None,
        "monthly_bom_limit": UNLIMITED,
        "max_parts_per_bom": UNLIMITED,
        "max_saved_boms": UNLIMITED,
        "monitored_parts_limit": UNLIMITED,
        "team_features": True,
        "api_access": True,
        "datasheet_comparison": True,
        "student_watermark": False,
        "can_create_analyses": True,
        "price": "Custom (from $10,000/year)",
        "upgrade_to": None,
        "display_label": "Enterprise",
        "description": "For secure, integrated, organization-wide deployments.",
    },
}

_ALIASES = {
    "free": PLAN_GRANDFATHERED_BETA,
    "beta": PLAN_GRANDFATHERED_BETA,
    "beta access": PLAN_GRANDFATHERED_BETA,
    "grandfathered": PLAN_GRANDFATHERED_BETA,
    "grandfathered beta": PLAN_GRANDFATHERED_BETA,
    "starter": PLAN_STARTER,
    "student": PLAN_STUDENT,
    "trial": PLAN_TRIAL,
    "free trial": PLAN_TRIAL,
    "trial expired": PLAN_TRIAL_EXPIRED,
    "expired trial": PLAN_TRIAL_EXPIRED,
    "subscription inactive": PLAN_SUBSCRIPTION_INACTIVE,
    "pro": PLAN_PROFESSIONAL,
    "professional": PLAN_PROFESSIONAL,
    "business": PLAN_BUSINESS,
    "enterprise": PLAN_ENTERPRISE,
    "admin": PLAN_ENTERPRISE,
}


def normalize_plan_name(plan_name: str | None) -> str:
    """Map a stored label to a canonical plan name.

    This does not decide beta eligibility. Unknown and empty labels are not a
    paid Starter subscription; access still comes from
    ``resolve_effective_plan``.
    """
    key = str(plan_name or "").strip().lower()
    if not key:
        return PLAN_GRANDFATHERED_BETA
    return _ALIASES.get(key, PLAN_GRANDFATHERED_BETA)


def paid_status_entitles(status: str | None) -> bool:
    """Whether a webhook-recorded subscription status currently grants paid access.

    Only ``active`` and ``trialing`` entitle. ``past_due`` does not: no grace
    period is implemented (``PAST_DUE_GRACE_PERIOD`` is None). ``canceled``,
    ``unpaid``, ``incomplete``, a missing status, and every other value do not
    entitle. Stripe identifiers are not consulted.
    """
    normalized = str(status or "").strip().lower()
    if normalized == "past_due":
        return False
    return normalized in PAID_ENTITLING_STATUSES


def has_grandfather_marker(user: dict | None) -> bool:
    """True only when the grandfather migration recorded this account.

    A non-null ``plan_grandfather_source`` is the durable beta marker. The
    ``plan`` string and any Stripe ids are not a substitute. Later paid
    purchases must retain the marker so a later cancellation can restore beta.
    """
    return bool(str((user or {}).get("plan_grandfather_source") or "").strip())


def stripe_subscription_confirmed(user: dict | None) -> bool:
    """True only when the webhook-recorded status currently entitles paid access.

    A non-empty ``stripe_subscription_id`` or ``stripe_price_id`` is never
    enough. Those values can be stale after cancellation or a failed payment.
    A Stripe customer id alone is also not enough.
    """
    if not isinstance(user, dict):
        return False
    return paid_status_entitles(user.get("stripe_subscription_status"))


def _parse_timestamp(value: Any):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def resolve_effective_plan(user: dict | None, now: datetime | None = None) -> tuple[str, bool]:
    """Return (canonical plan, should_persist_trial_expiry).

    The bool is true only when a stored Trial has passed trial_ends_at and the
    caller should persist Trial expired. It is never used to write Starter.
    """
    record = user or {}
    if str(record.get("role", "")).lower() == "admin":
        return PLAN_ENTERPRISE, False
    name = normalize_plan_name(record.get("plan"))
    if name == PLAN_STUDENT:
        return PLAN_STUDENT, False
    if name == PLAN_TRIAL:
        end = _parse_timestamp(record.get("trial_ends_at"))
        expired = end is not None and end <= (now or datetime.now(timezone.utc))
        if expired:
            return PLAN_TRIAL_EXPIRED, True
        return PLAN_TRIAL, False
    if name == PLAN_TRIAL_EXPIRED:
        return PLAN_TRIAL_EXPIRED, False
    if name in _PAID_PLAN_NAMES and stripe_subscription_confirmed(record):
        return name, False
    # Beta is the grandfather marker, not the stored plan label and not the
    # absence of Stripe ids. A canceled paid Starter with no marker is inactive.
    if has_grandfather_marker(record):
        return PLAN_GRANDFATHERED_BETA, False
    if name in _PAID_PLAN_NAMES or name in {PLAN_GRANDFATHERED_BETA, PLAN_SUBSCRIPTION_INACTIVE}:
        return PLAN_SUBSCRIPTION_INACTIVE, False
    if name == PLAN_ENTERPRISE:
        return PLAN_ENTERPRISE, False
    return PLAN_SUBSCRIPTION_INACTIVE, False


def get_plan(plan_name: str | None) -> dict:
    return dict(PLANS[normalize_plan_name(plan_name)])


def plan_display_label(plan_name: str | None) -> str:
    plan = get_plan(plan_name)
    return str(plan.get("display_label") or normalize_plan_name(plan_name))


def trial_days_remaining(user: dict | None, now: datetime | None = None) -> int | None:
    """Whole days left on an active trial, or None if the account is not in trial."""
    record = user or {}
    name, _expired = resolve_effective_plan(record, now)
    if name != PLAN_TRIAL:
        return None
    end = _parse_timestamp(record.get("trial_ends_at"))
    if end is None:
        return None
    current = now or datetime.now(timezone.utc)
    remaining = end - current
    if remaining.total_seconds() <= 0:
        return 0
    days = remaining.days
    if remaining.seconds or remaining.microseconds:
        days += 1
    return days


def may_self_serve_checkout(current_plan: str | None, target_plan: str | None) -> bool:
    """True when the customer may start Checkout for a higher paid plan."""
    target = normalize_plan_name(target_plan)
    if target not in CHECKOUT_PRICE_SECRETS:
        return False
    current = normalize_plan_name(current_plan)
    return _CHECKOUT_RANK.get(current, 0) < _CHECKOUT_RANK[target]


def configured_annual_price_id(plan_name: str | None) -> str:
    """Return a configured annual Price ID, or empty when the catalog is monthly-only.

    Does not create Stripe prices. An unset secret is the normal Live state.
    """
    secret_name = ANNUAL_CHECKOUT_PRICE_SECRETS.get(normalize_plan_name(plan_name))
    if not secret_name:
        return ""
    from src.secrets import get_secret

    return str(get_secret(secret_name, default="") or "").strip()


def annual_price_line(
    plan_name: str | None,
    *,
    price_id: str | None = None,
    amount: str | None = None,
) -> str:
    """Annual price text only when that exact plan has a selectable annual Price ID and a real amount.

    Never invent a yearly price or a savings percentage. Empty when either
    value is missing.
    """
    resolved_id = configured_annual_price_id(plan_name) if price_id is None else str(price_id or "").strip()
    resolved_amount = str(amount or "").strip()
    if not resolved_id or not resolved_amount:
        return ""
    if "save" in resolved_amount.lower() or "%" in resolved_amount:
        return ""
    return f"{resolved_amount} / year"


def checkout_metadata(user_id: str, target_plan: str) -> dict[str, str]:
    """Metadata attached to both the Checkout Session and the Subscription."""
    token = CHECKOUT_PLAN_TOKENS.get(target_plan) or CHECKOUT_PLAN_TOKENS.get(
        normalize_plan_name(target_plan)
    )
    if not token:
        raise ValueError("Unsupported checkout plan")
    resolved_user = str(user_id or "").strip()
    if not resolved_user:
        raise ValueError("Missing checkout user id")
    return {"user_id": resolved_user, "cadivor_plan": token}


def plan_from_checkout_metadata(
    metadata: dict | None,
    *,
    price_id: str | None = None,
    price_ids: dict[str, str] | None = None,
) -> str | None:
    """Map Stripe metadata or a known price id to a Cadivor paid plan.

    Metadata wins when it names a checkout plan. Price ids are the fallback so
    a webhook can still provision if metadata is missing. Unknown values return
    None; callers must not guess Starter.
    """
    payload = metadata or {}
    token = str(payload.get("cadivor_plan") or "").strip().lower()
    if token in _TOKEN_TO_PLAN:
        return _TOKEN_TO_PLAN[token]
    resolved_price = str(price_id or payload.get("price_id") or "").strip()
    if not resolved_price or not price_ids:
        return None
    for plan_name, configured in price_ids.items():
        if str(configured or "").strip() and str(configured).strip() == resolved_price:
            canonical = normalize_plan_name(plan_name)
            if canonical in CHECKOUT_PLAN_TOKENS:
                return canonical
    return None


def format_limit(value: int | None, singular: str, plural: str | None = None) -> str:
    if value is None:
        return "Unlimited"
    return f"{value:,} {singular if value == 1 else (plural or singular + 's')}"


def validate_bom_against_plan(
    bom_df, plan: dict, current_monthly_uploads: int, *, is_admin: bool = False
) -> tuple[bool, str]:
    if is_admin:
        return True, "Admin account: all Cadivor limits are bypassed."
    if plan.get("can_create_analyses") is False:
        return (
            False,
            "Your 14-day trial has ended. Saved analyses remain available to view and download. "
            "Choose Starter, Professional, or Business to create new analyses.",
        )
    monthly = plan.get("monthly_bom_limit")
    parts = plan.get("max_parts_per_bom")
    count = len(bom_df)
    if monthly is not None and current_monthly_uploads >= monthly:
        return (
            False,
            f"You have used all {monthly:,} BOM analyses included this month. Your data is safe; "
            "upgrade to Professional for unlimited analyses, or continue when your monthly allowance resets.",
        )
    if parts is not None and count > parts:
        return (
            False,
            f"This BOM contains {count:,} unique components, which is {count - parts:,} over your "
            f"plan limit of {parts:,}. Reduce the BOM size or upgrade to Professional for unlimited components per BOM.",
        )
    return True, "BOM is within your plan entitlements."
