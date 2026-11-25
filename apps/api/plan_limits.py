"""Server-enforced plan limits and usage metering for the migration API.

Uses existing plan definitions from ``src.plans`` — does not invent prices.
Metering is workspace-scoped against migration store report counts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from src.plans import (
    PLAN_TRIAL,
    PLAN_TRIAL_EXPIRED,
    get_plan,
    normalize_plan_name,
    validate_bom_against_plan,
)
from apps.api.report_visibility import customer_visible_analyses
from apps.api.sandbox_auth import is_production_runtime
from apps.api.workspace_store import get_store


class PlanLimitError(Exception):
    def __init__(self, code: str, detail: str, *, limits: dict[str, Any] | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.limits = limits or {}


ENTITLEMENT_FLAG_KEYS = frozenset({
    "api_access",
    "team_features",
    "datasheet_comparison",
    "can_create_analyses",
})


def validated_feature_overrides(value: Any) -> dict[str, bool]:
    """Accept only explicit boolean feature overrides; nulls clear a flag."""
    if not isinstance(value, dict):
        raise ValueError("feature_overrides must be an object")
    unknown = set(value) - ENTITLEMENT_FLAG_KEYS
    if unknown:
        raise ValueError("Only supported account feature flags can be changed")
    if any(not isinstance(flag, bool) for flag in value.values()):
        raise ValueError("Feature override values must be true or false")
    return {str(key): flag for key, flag in value.items()}


def account_feature_overrides(user_id: str) -> dict[str, bool]:
    getter = getattr(get_store(), "get_account_entitlement_overrides", None)
    if not callable(getter):
        return {}
    try:
        stored = getter(user_id)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(stored, dict):
        return {}
    return {
        key: value
        for key, value in stored.items()
        if key in ENTITLEMENT_FLAG_KEYS and isinstance(value, bool)
    }


def _month_key(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}"


def effective_plan_name(ctx: dict[str, Any] | None) -> str:
    row = ctx or {}
    status = str(row.get("trial_status") or row.get("subscription_status") or "").strip()
    plan = normalize_plan_name(str(row.get("plan") or PLAN_TRIAL))
    if status == "trial_expired" or plan == PLAN_TRIAL_EXPIRED:
        return PLAN_TRIAL_EXPIRED
    return plan


def effective_plan(ctx: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve plan defaults, then apply server-side account feature flags."""
    row = ctx or {}
    plan = get_plan(effective_plan_name(row))
    if (
        normalize_plan_name(effective_plan_name(row)) == "Professional"
        and row.get("api_access_addon_active") is True
    ):
        plan["api_access"] = True
    capacity_addon = row.get("monitored_parts_addon_capacity")
    base_capacity = plan.get("monitored_parts_limit")
    if (
        isinstance(capacity_addon, int)
        and not isinstance(capacity_addon, bool)
        and capacity_addon > 0
        and isinstance(base_capacity, int)
        and not isinstance(base_capacity, bool)
    ):
        plan["monitored_parts_limit"] = base_capacity + capacity_addon
    overrides = row.get("entitlement_overrides")
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if key in ENTITLEMENT_FLAG_KEYS and isinstance(value, bool):
                plan[key] = value
    return plan


def _finish_overage_credit(
    ctx: dict[str, Any] | None,
    reservation_id: str,
    *,
    commit: bool,
) -> bool:
    token = str((ctx or {}).get("access_token") or "").strip()
    if not token or not reservation_id:
        return False
    from apps.api import subscription_billing_service

    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="finish_usage_credit",
            payload={
                "reservation_id": reservation_id,
                "commit": commit,
                "workspace_id": str((ctx or {}).get("workspace_id") or ""),
            },
            timeout_seconds=5,
            internal_context={
                "user_id": str((ctx or {}).get("user_id") or ""),
                "workspace_id": str((ctx or {}).get("workspace_id") or ""),
            },
        )
    except subscription_billing_service.SubscriptionBillingError:
        return False
    return status == 200 and result.get("ok") is True and result.get("finished") is True




def _ask_credit_topup_balance(ctx: dict[str, Any]) -> tuple[int, bool]:
    """Read prepaid Ask Cadivor credits through the signed billing bridge."""
    token = str(ctx.get("access_token") or "").strip()
    user_id = str(ctx.get("user_id") or "").strip()
    workspace_id = str(ctx.get("workspace_id") or "").strip()
    if not token or not user_id or not workspace_id:
        return 0, False
    from apps.api import subscription_billing_service

    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="ai_usage_balance",
            payload={"workspace_id": workspace_id},
            timeout_seconds=5,
            internal_context={"user_id": user_id, "workspace_id": workspace_id},
        )
    except subscription_billing_service.SubscriptionBillingError:
        return 0, False
    if status != 200 or result.get("ok") is not True:
        return 0, False
    try:
        balance = max(0, int(result.get("credits") or 0))
    except (TypeError, ValueError):
        return 0, False
    return balance, True


def finish_ai_credit(
    ctx: dict[str, Any] | None,
    *,
    reservation_id: str,
    source: str,
    commit: bool,
) -> bool:
    """Commit or refund a prepaid credit reservation."""
    if source != "topup":
        return True
    row = ctx or {}
    token = str(row.get("access_token") or "").strip()
    user_id = str(row.get("user_id") or "").strip()
    workspace_id = str(row.get("workspace_id") or "").strip()
    if not token or not user_id or not workspace_id or not reservation_id:
        return False
    from apps.api import subscription_billing_service

    try:
        result, status = subscription_billing_service.request_action(
            access_token=token,
            action="finish_ai_question_credit",
            payload={
                "reservation_id": reservation_id,
                "commit": bool(commit),
                "workspace_id": workspace_id,
            },
            timeout_seconds=5,
            internal_context={"user_id": user_id, "workspace_id": workspace_id},
        )
    except subscription_billing_service.SubscriptionBillingError:
        return False
    return status == 200 and result.get("ok") is True and result.get("finished") is True


def ai_credit_status(
    ctx: dict[str, Any] | None,
    *,
    store: Any | None = None,
    include_topup_balance: bool = True,
) -> dict[str, Any]:
    """Return the authenticated user's included and prepaid Ask Cadivor balance."""
    row = ctx or {}
    plan = effective_plan(row)
    plan_name = effective_plan_name(row)
    allowance = max(0, int(plan.get("ai_credits", 0) or 0))
    user_id = str(row.get("user_id") or "").strip()
    admin = str(row.get("platform_role") or row.get("role") or "").strip().lower() == "admin"
    now = datetime.now(timezone.utc)
    month = _month_key(now)
    next_month = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1, tzinfo=timezone.utc)
    reset_at = next_month.isoformat()
    selected_store = store or get_store()
    usage_reader = getattr(selected_store, "get_ai_credit_usage", None)
    used = (
        max(0, int(usage_reader(user_id=user_id, usage_month=month) or 0))
        if user_id and callable(usage_reader)
        else 0
    )
    remaining = max(0, allowance - used)
    topup_balance, topup_balance_available = (
        (0, True)
        if admin
        else _ask_credit_topup_balance(row)
        if include_topup_balance
        else (0, False)
    )
    total_remaining = remaining + topup_balance
    return {
        "plan": plan_name,
        "allowance": allowance,
        "used": used,
        "remaining": None if admin else remaining,
        "topup_credits": None if admin else topup_balance,
        "topup_balance_available": topup_balance_available,
        "total_remaining": None if admin else total_remaining,
        "month": month,
        "reset_at": reset_at,
        "reset_label": "Monthly credits reset at the start of next month",
        "is_admin": admin,
        "can_use": admin or total_remaining > 0,
    }


def reserve_ai_credit(
    ctx: dict[str, Any] | None,
    *,
    action: str = "question",
) -> dict[str, Any]:
    """Reserve an included monthly credit first, then a prepaid credit."""
    row = ctx or {}
    status = ai_credit_status(row, include_topup_balance=False)
    if status["is_admin"]:
        return {"reserved": True, "usage": status, "cost": 1, "source": "admin"}
    user_id = str(row.get("user_id") or "").strip()
    workspace_id = str(row.get("workspace_id") or "").strip()
    token = str(row.get("access_token") or "").strip()
    allowance = int(status["allowance"])
    cost = max(1, int({"question": 1}.get(action, 1)))
    if not user_id:
        return {"reserved": False, "usage": status, "cost": cost, "code": "missing_user"}

    store = get_store()
    reserve = getattr(store, "reserve_ai_credits", None)
    if not callable(reserve):
        return {"reserved": False, "usage": status, "cost": cost, "code": "usage_store_unavailable"}
    if allowance >= cost:
        used = reserve(
            user_id=user_id,
            usage_month=str(status["month"]),
            allowance=allowance,
            cost=cost,
        )
        if used is not None:
            status = dict(status)
            used_after = max(0, int(used))
            remaining_after = max(0, allowance - used_after)
            status.update({
                "used": used_after,
                "remaining": remaining_after,
                "total_remaining": remaining_after,
                "can_use": remaining_after > 0,
            })
            return {
                "reserved": True,
                "usage": status,
                "cost": cost,
                "source": "monthly",
            }
        status = ai_credit_status(row)
        if int(status.get("remaining") or 0) >= cost:
            return {"reserved": False, "usage": status, "cost": cost, "code": "usage_store_unavailable"}
    else:
        status = ai_credit_status(row)

    if not status.get("topup_balance_available"):
        return {"reserved": False, "usage": status, "cost": cost, "code": "ai_credits_unavailable"}
    if int(status.get("topup_credits") or 0) < cost:
        return {"reserved": False, "usage": status, "cost": cost, "code": "ai_credit_limit"}
    if not token or not workspace_id:
        return {"reserved": False, "usage": status, "cost": cost, "code": "ai_credits_unavailable"}

    reservation_id = uuid.uuid4().hex
    from apps.api import subscription_billing_service

    try:
        result, result_status = subscription_billing_service.request_action(
            access_token=token,
            action="reserve_ai_question_credit",
            payload={"reservation_id": reservation_id, "workspace_id": workspace_id},
            timeout_seconds=5,
            internal_context={"user_id": user_id, "workspace_id": workspace_id},
        )
    except subscription_billing_service.SubscriptionBillingError:
        return {"reserved": False, "usage": status, "cost": cost, "code": "ai_credits_unavailable"}
    if result_status != 200 or result.get("ok") is not True:
        return {"reserved": False, "usage": status, "cost": cost, "code": "ai_credits_unavailable"}
    if result.get("reserved") is not True:
        return {
            "reserved": False,
            "usage": ai_credit_status(row),
            "cost": cost,
            "code": "ai_credit_limit",
        }
    status = dict(status)
    topup_after = max(0, int(status.get("topup_credits") or 0) - cost)
    remaining = max(0, int(status.get("remaining") or 0))
    status.update({
        "topup_credits": topup_after,
        "total_remaining": remaining + topup_after,
        "can_use": remaining + topup_after > 0,
    })
    return {
        "reserved": True,
        "usage": status,
        "cost": cost,
        "source": "topup",
        "reservation_id": reservation_id,
    }


def release_ai_credit(
    ctx: dict[str, Any] | None,
    *,
    usage_month: str,
    cost: int = 1,
    source: str = "monthly",
    reservation_id: str = "",
) -> int:
    """Refund a reserved monthly or prepaid credit after a failed AI call."""
    row = ctx or {}
    if str(row.get("platform_role") or row.get("role") or "").strip().lower() == "admin":
        return 0
    if source == "topup":
        return int(finish_ai_credit(
            row,
            reservation_id=reservation_id,
            source="topup",
            commit=False,
        ))
    user_id = str(row.get("user_id") or "").strip()
    if not user_id:
        return 0
    release = getattr(get_store(), "release_ai_credits", None)
    if not callable(release):
        return 0
    return release(user_id=user_id, usage_month=usage_month, cost=cost)


def usage_snapshot(workspace_id: str, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    plan_name = effective_plan_name(ctx)
    plan = effective_plan(ctx)
    store = get_store()
    reports = customer_visible_analyses(
        store.list_reports(workspace_id=workspace_id),
        production=is_production_runtime(),
    )
    month = _month_key()
    ai_usage = ai_credit_status(ctx, store=store)
    month_count = sum(1 for r in reports if str(r.get("created_at") or "").startswith(month))
    saved_bom_keys = {
        str(r.get("bom_id") or r.get("id") or "").strip()
        for r in reports
        if r.get("bom_id") or r.get("id")
    }
    return {
        "plan": plan_name,
        "limits": {
            "monthly_bom_limit": plan.get("monthly_bom_limit"),
            "max_parts_per_bom": plan.get("max_parts_per_bom"),
            "max_saved_boms": plan.get("max_saved_boms"),
            "monitored_parts_limit": plan.get("monitored_parts_limit"),
            "can_create_analyses": plan.get("can_create_analyses", True),
            "api_access": bool(plan.get("api_access")),
            "team_features": bool(plan.get("team_features")),
            "datasheet_comparison": bool(plan.get("datasheet_comparison")),
            "monthly_ai_credits": ai_usage["allowance"],
        },
        "usage": {
            "saved_boms": len(saved_bom_keys),
            "analyses_this_month": month_count,
            "month": month,
            "ai_credits": ai_usage,
            "overage_credits": {
                key: max(0, int(value))
                for key, value in (ctx or {}).get("usage_credits", {}).items()
                if key in {"bom_analysis", "monitored_part"}
                and isinstance(value, (int, float))
            },
        },
        "enforced": True,
    }


def assert_analysis_allowed(
    *,
    workspace_id: str,
    ctx: dict[str, Any] | None,
    part_count: int,
    analysis_id: str | None = None,
) -> dict[str, Any]:
    """Raise PlanLimitError when the workspace cannot run another analysis."""
    snap = usage_snapshot(workspace_id, ctx)
    plan = effective_plan(ctx)
    monthly_used = int(snap["usage"]["analyses_this_month"])
    reservation_id = ""
    monthly_limit = plan.get("monthly_bom_limit")
    if (
        plan.get("can_create_analyses") is not False
        and monthly_limit is not None
        and monthly_used >= int(monthly_limit)
        and analysis_id
        and str((ctx or {}).get("access_token") or "").strip()
    ):
        from apps.api import subscription_billing_service

        try:
            reserved, status = subscription_billing_service.request_action(
                access_token=str((ctx or {}).get("access_token") or ""),
                action="reserve_usage_credit",
                payload={
                    "credit_kind": "bom_analysis",
                    "reservation_id": str(analysis_id),
                    "workspace_id": str((ctx or {}).get("workspace_id") or ""),
                },
                timeout_seconds=5,
                internal_context={
                    "user_id": str((ctx or {}).get("user_id") or ""),
                    "workspace_id": str((ctx or {}).get("workspace_id") or ""),
                },
            )
            if status == 200 and reserved.get("ok") is True and reserved.get("reserved") is True:
                reservation_id = str(analysis_id)
                monthly_used = max(0, int(monthly_limit) - 1)
        except subscription_billing_service.SubscriptionBillingError:
            pass
    ok, reason = validate_bom_against_plan(
        list(range(max(0, int(part_count)))),
        plan,
        monthly_used,
    )
    if not ok:
        if reservation_id:
            _finish_overage_credit(ctx, reservation_id, commit=False)
        raise PlanLimitError("plan_limit", reason, limits=snap)
    saved_limit = plan.get("max_saved_boms")
    if saved_limit is not None and int(snap["usage"]["saved_boms"]) >= int(saved_limit):
        if reservation_id:
            _finish_overage_credit(ctx, reservation_id, commit=False)
        raise PlanLimitError(
            "saved_bom_limit",
            f"Saved BOM limit reached ({saved_limit}). Delete a report or upgrade.",
            limits=snap,
        )
    if reservation_id:
        snap["usage"]["overage_credit_reservation_id"] = reservation_id
    return snap
