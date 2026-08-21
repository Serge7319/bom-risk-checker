"""Cadivor Sprint 31.2 — launch entitlement source of truth."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

UNLIMITED = None

PLANS = {
    "Student": {"ai_credits": 0, "monthly_bom_limit": 3, "max_parts_per_bom": 25, "max_saved_boms": 25, "monitored_parts_limit": 0, "team_features": False, "api_access": False, "student_watermark": True, "price": "$0", "upgrade_to": "Professional", "description": "For verified students and academic projects."},
    "Trial": {"ai_credits": 100, "monthly_bom_limit": UNLIMITED, "max_parts_per_bom": UNLIMITED, "max_saved_boms": UNLIMITED, "monitored_parts_limit": UNLIMITED, "team_features": True, "api_access": True, "student_watermark": False, "price": "$0 for 14 days", "upgrade_to": "Professional", "description": "Full Cadivor access for 14 days."},
    "Starter": {"ai_credits": 0, "monthly_bom_limit": 10, "max_parts_per_bom": 100, "max_saved_boms": 100, "monitored_parts_limit": 0, "team_features": False, "api_access": False, "student_watermark": False, "price": "$29/mo", "upgrade_to": "Professional", "description": "For individual prototype and early production reviews."},
    "Professional": {"ai_credits": 500, "monthly_bom_limit": UNLIMITED, "max_parts_per_bom": UNLIMITED, "max_saved_boms": UNLIMITED, "monitored_parts_limit": 2500, "team_features": False, "api_access": False, "student_watermark": False, "price": "$99/mo", "upgrade_to": "Business", "description": "For professional engineers and growing hardware teams."},
    "Business": {"ai_credits": 2500, "included_users": 10, "monthly_bom_limit": UNLIMITED, "max_parts_per_bom": UNLIMITED, "max_saved_boms": UNLIMITED, "monitored_parts_limit": UNLIMITED, "team_features": True, "api_access": True, "student_watermark": False, "price": "$299/mo", "upgrade_to": "Enterprise", "description": "For teams standardizing engineering decisions."},
    "Enterprise": {"ai_credits": 10000, "included_users": None, "monthly_bom_limit": UNLIMITED, "max_parts_per_bom": UNLIMITED, "max_saved_boms": UNLIMITED, "monitored_parts_limit": UNLIMITED, "team_features": True, "api_access": True, "student_watermark": False, "price": "Custom (from $10,000/year)", "upgrade_to": None, "description": "For secure, integrated, organization-wide deployments."},
}

_ALIASES = {"free":"Starter", "starter":"Starter", "student":"Student", "trial":"Trial", "free trial":"Trial", "pro":"Professional", "professional":"Professional", "business":"Business", "enterprise":"Enterprise", "admin":"Enterprise"}

def normalize_plan_name(plan_name: str | None) -> str:
    return _ALIASES.get(str(plan_name or "Starter").strip().lower(), "Starter")

def _parse_timestamp(value: Any):
    if not value: return None
    if isinstance(value, datetime): dt=value
    else:
        try: dt=datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError): return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def resolve_effective_plan(user: dict, now: datetime | None = None) -> tuple[str, bool]:
    if str(user.get("role", "")).lower() == "admin": return "Enterprise", False
    name=normalize_plan_name(user.get("plan"))
    if name != "Trial": return name, False
    end=_parse_timestamp(user.get("trial_ends_at"))
    expired = end is not None and end <= (now or datetime.now(timezone.utc))
    return ("Starter", True) if expired else ("Trial", False)

def get_plan(plan_name: str | None) -> dict:
    return dict(PLANS[normalize_plan_name(plan_name)])

def format_limit(value: int | None, singular: str, plural: str | None = None) -> str:
    if value is None: return "Unlimited"
    return f"{value:,} {singular if value == 1 else (plural or singular + 's')}"

def validate_bom_against_plan(bom_df, plan: dict, current_monthly_uploads: int, *, is_admin: bool=False) -> tuple[bool, str]:
    if is_admin: return True, "Admin account: all Cadivor limits are bypassed."
    monthly=plan.get("monthly_bom_limit")
    parts=plan.get("max_parts_per_bom")
    count=len(bom_df)
    if monthly is not None and current_monthly_uploads >= monthly:
        return False, f"You have used all {monthly:,} BOM analyses included this month. Your data is safe; upgrade to Professional for unlimited analyses, or continue when your monthly allowance resets."
    if parts is not None and count > parts:
        return False, f"This BOM contains {count:,} unique components, which is {count-parts:,} over your plan limit of {parts:,}. Reduce the BOM size or upgrade to Professional for unlimited components per BOM."
    return True, "BOM is within your plan entitlements."
