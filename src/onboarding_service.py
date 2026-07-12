"""Cadivor Milestone 11A.2 onboarding persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(response: Any) -> Dict[str, Any]:
    data = getattr(response, "data", None)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def _migration_missing(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "onboarding_progress" in text
        or "does not exist" in text
        or "schema cache" in text
        or "could not find the table" in text
    )


def ensure_onboarding_progress(
    supabase: Any,
    user_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        response = (
            supabase.table("onboarding_progress")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        row = _first(response)
        if row:
            return row, None

        payload = {
            "user_id": user_id,
            "welcome_seen": False,
            "profile_completed": False,
            "workspace_completed": False,
            "first_bom_completed": False,
            "first_alternative_completed": False,
            "first_report_completed": False,
            "dismissed": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        created = _first(
            supabase.table("onboarding_progress").insert(payload).execute()
        )
        return created or payload, None
    except Exception as exc:
        if _migration_missing(exc):
            return None, "migration_required"
        return None, str(exc)


def update_onboarding_progress(
    supabase: Any,
    user_id: str,
    updates: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    allowed = {
        "welcome_seen",
        "profile_completed",
        "workspace_completed",
        "first_bom_completed",
        "first_alternative_completed",
        "first_report_completed",
        "dismissed",
        "completed_at",
    }
    payload = {key: value for key, value in updates.items() if key in allowed}
    payload["updated_at"] = _now()

    try:
        response = (
            supabase.table("onboarding_progress")
            .update(payload)
            .eq("user_id", user_id)
            .execute()
        )
        row = _first(response)
        if row:
            return row, None

        payload["user_id"] = user_id
        payload["created_at"] = _now()
        created = _first(
            supabase.table("onboarding_progress").insert(payload).execute()
        )
        return created or payload, None
    except Exception as exc:
        if _migration_missing(exc):
            return None, "migration_required"
        return None, str(exc)


def completion_count(progress: Dict[str, Any]) -> int:
    keys = (
        "profile_completed",
        "workspace_completed",
        "first_bom_completed",
        "first_alternative_completed",
        "first_report_completed",
    )
    return sum(bool(progress.get(key)) for key in keys)
