"""Server-enforced plan limits and usage metering for the migration API.

Uses existing plan definitions from ``src.plans`` — does not invent prices.
Metering is workspace-scoped against migration store report counts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.plans import (
    PLAN_TRIAL,
    PLAN_TRIAL_EXPIRED,
    get_plan,
    normalize_plan_name,
    validate_bom_against_plan,
)
from apps.api.workspace_store import get_store


class PlanLimitError(Exception):
    def __init__(self, code: str, detail: str, *, limits: dict[str, Any] | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.limits = limits or {}


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


def usage_snapshot(workspace_id: str, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    plan_name = effective_plan_name(ctx)
    plan = get_plan(plan_name)
    store = get_store()
    reports = store.list_reports(workspace_id=workspace_id)
    month = _month_key()
    month_count = sum(1 for r in reports if str(r.get("created_at") or "").startswith(month))
    return {
        "plan": plan_name,
        "limits": {
            "monthly_bom_limit": plan.get("monthly_bom_limit"),
            "max_parts_per_bom": plan.get("max_parts_per_bom"),
            "max_saved_boms": plan.get("max_saved_boms"),
            "monitored_parts_limit": plan.get("monitored_parts_limit"),
            "can_create_analyses": plan.get("can_create_analyses", True),
        },
        "usage": {
            "saved_boms": len(reports),
            "analyses_this_month": month_count,
            "month": month,
        },
        "enforced": True,
    }


def assert_analysis_allowed(
    *,
    workspace_id: str,
    ctx: dict[str, Any] | None,
    part_count: int,
) -> dict[str, Any]:
    """Raise PlanLimitError when the workspace cannot run another analysis."""
    snap = usage_snapshot(workspace_id, ctx)
    plan = get_plan(snap["plan"])
    monthly_used = int(snap["usage"]["analyses_this_month"])
    ok, reason = validate_bom_against_plan(
        list(range(max(0, int(part_count)))),
        plan,
        monthly_used,
    )
    if not ok:
        raise PlanLimitError("plan_limit", reason, limits=snap)
    saved_limit = plan.get("max_saved_boms")
    if saved_limit is not None and int(snap["usage"]["saved_boms"]) >= int(saved_limit):
        raise PlanLimitError(
            "saved_bom_limit",
            f"Saved BOM limit reached ({saved_limit}). Delete a report or upgrade.",
            limits=snap,
        )
    return snap
