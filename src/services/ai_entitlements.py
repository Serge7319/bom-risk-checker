"""AI entitlements and lightweight usage accounting for Cadivor.

The launch MVP keeps usage accounting in the current Streamlit session so it
works without a database migration. The public interface is intentionally
stable; a persistent Supabase-backed repository can replace the storage later
without changing the assistant UI or provider integration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, MutableMapping

from src.plans import normalize_plan_name

AI_CREDITS_BY_PLAN = {
    "Student": 20,
    "Trial": 100,
    "Starter": 30,
    "Professional": 500,
    "Business": 2500,
    "Enterprise": 10000,
}

ACTION_COSTS = {
    "question": 1,
    "summary": 2,
    "component_review": 2,
    "recommendation": 2,
    "report": 4,
    "simulation": 8,
}


@dataclass(frozen=True, slots=True)
class AIUsageStatus:
    plan: str
    allowance: int
    used: int
    remaining: int
    percent_used: int
    warning_level: str
    reset_label: str
    is_admin: bool = False

    @property
    def can_use(self) -> bool:
        return self.is_admin or self.remaining > 0


def _month_key(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.strftime("%Y-%m")


def _is_admin(user: dict[str, Any]) -> bool:
    return str(user.get("role") or "").strip().lower() == "admin"


def _plan(user: dict[str, Any]) -> str:
    return "Enterprise" if _is_admin(user) else normalize_plan_name(user.get("plan"))


def _warning(percent: int) -> str:
    if percent >= 100:
        return "reached"
    if percent >= 95:
        return "critical"
    if percent >= 90:
        return "high"
    if percent >= 75:
        return "notice"
    return "normal"


def get_ai_usage_status(
    state: MutableMapping[str, Any],
    user: dict[str, Any],
    *,
    now: datetime | None = None,
) -> AIUsageStatus:
    plan = _plan(user)
    admin = _is_admin(user)
    allowance = AI_CREDITS_BY_PLAN.get(plan, AI_CREDITS_BY_PLAN["Starter"])
    key = f"cadivor_ai_usage:{user.get('id', 'anonymous')}:{_month_key(now)}"
    used = max(0, int(state.get(key, 0) or 0))
    remaining = max(0, allowance - used)
    percent = min(100, round((used / max(1, allowance)) * 100))
    if admin:
        remaining = allowance
        percent = 0
    return AIUsageStatus(
        plan=plan,
        allowance=allowance,
        used=used,
        remaining=remaining,
        percent_used=percent,
        warning_level="normal" if admin else _warning(percent),
        reset_label="Resets on the first day of next month",
        is_admin=admin,
    )


def consume_ai_credits(
    state: MutableMapping[str, Any],
    user: dict[str, Any],
    *,
    action: str = "question",
    now: datetime | None = None,
) -> AIUsageStatus:
    status = get_ai_usage_status(state, user, now=now)
    if status.is_admin:
        return status
    cost = max(1, int(ACTION_COSTS.get(action, 1)))
    if status.remaining < cost:
        return status
    key = f"cadivor_ai_usage:{user.get('id', 'anonymous')}:{_month_key(now)}"
    state[key] = status.used + cost
    return get_ai_usage_status(state, user, now=now)
