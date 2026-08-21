"""Cadivor Milestone 11C.1 collaboration services."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data(response: Any) -> List[Dict[str, Any]]:
    data = getattr(response, "data", None)
    return data if isinstance(data, list) else []


def _message(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def migration_missing(exc: Exception) -> bool:
    text = _message(exc).lower()
    return any(
        signal in text
        for signal in (
            "workspace_audit_log",
            "workspace_presence",
            "does not exist",
            "schema cache",
            "could not find the table",
        )
    )


def touch_workspace_presence(
    supabase: Any,
    workspace_id: str,
    user_id: str,
    display_name: str,
    email: str,
    page_name: str,
    object_label: str = "",
) -> Optional[str]:
    """Upsert a lightweight presence record for the active workspace."""
    payload = {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "display_name": display_name or email or "Cadivor user",
        "email": (email or "").strip().lower(),
        "page_name": page_name or "Cadivor",
        "object_label": object_label or "",
        "last_seen_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    try:
        existing = _data(
            supabase.table("workspace_presence")
            .select("id")
            .eq("workspace_id", workspace_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if existing:
            (
                supabase.table("workspace_presence")
                .update(payload)
                .eq("id", existing[0]["id"])
                .execute()
            )
        else:
            payload["created_at"] = _now_iso()
            supabase.table("workspace_presence").insert(payload).execute()
        return None
    except Exception as exc:
        if migration_missing(exc):
            return "migration_required"
        return _message(exc)


def list_workspace_presence(
    supabase: Any,
    workspace_id: str,
    limit: int = 25,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        rows = _data(
            supabase.table("workspace_presence")
            .select("*")
            .eq("workspace_id", workspace_id)
            .order("last_seen_at", desc=True)
            .limit(limit)
            .execute()
        )
        return rows, None
    except Exception as exc:
        if migration_missing(exc):
            return [], "migration_required"
        return [], _message(exc)


def list_audit_log(
    supabase: Any,
    workspace_id: str,
    *,
    limit: int = 250,
    action_type: str = "",
    actor_user_id: str = "",
    search_text: str = "",
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        query = (
            supabase.table("workspace_audit_log")
            .select("*")
            .eq("workspace_id", workspace_id)
        )
        if action_type and action_type != "All":
            query = query.eq("action_type", action_type)
        if actor_user_id and actor_user_id != "All":
            query = query.eq("actor_user_id", actor_user_id)
        if search_text.strip():
            query = query.ilike("search_text", f"%{search_text.strip()}%")
        rows = _data(
            query.order("created_at", desc=True).limit(limit).execute()
        )
        return rows, None
    except Exception as exc:
        if migration_missing(exc):
            return [], "migration_required"
        return [], _message(exc)


def mark_all_notifications_read(
    supabase: Any,
    workspace_id: str,
    user_id: str,
) -> Optional[str]:
    try:
        (
            supabase.table("workspace_notifications")
            .update({"is_read": True, "read_at": _now_iso()})
            .eq("workspace_id", workspace_id)
            .eq("user_id", user_id)
            .eq("is_read", False)
            .execute()
        )
        return None
    except Exception as exc:
        return _message(exc)
