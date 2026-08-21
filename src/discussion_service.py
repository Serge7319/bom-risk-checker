"""Cadivor Milestone 11C.2 engineering discussion services."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data(response: Any) -> List[Dict[str, Any]]:
    value = getattr(response, "data", None)
    return value if isinstance(value, list) else []


def _message(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def list_analysis_comments(
    supabase: Any,
    workspace_id: str,
    analysis_id: str,
    limit: int = 250,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        rows = _data(
            supabase.table("analysis_comments")
            .select("*")
            .eq("workspace_id", workspace_id)
            .eq("analysis_id", analysis_id)
            .eq("is_deleted", False)
            .order("is_pinned", desc=True)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return rows, None
    except Exception as exc:
        return [], _message(exc)


def add_analysis_comment(
    supabase: Any,
    *,
    workspace_id: str,
    analysis_id: str,
    user_id: str,
    author_name: str,
    author_email: str,
    body: str,
    comment_type: str = "discussion",
    component_mpn: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    cleaned = (body or "").strip()
    if not cleaned:
        return None, "Comment text is required."
    try:
        response = (
            supabase.table("analysis_comments")
            .insert(
                {
                    "workspace_id": workspace_id,
                    "analysis_id": analysis_id,
                    "user_id": user_id,
                    "author_name": author_name or author_email or "Cadivor user",
                    "author_email": (author_email or "").strip().lower(),
                    "body": cleaned,
                    "comment_type": comment_type or "discussion",
                    "component_mpn": component_mpn or "",
                    "is_pinned": False,
                    "is_deleted": False,
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                }
            )
            .execute()
        )
        rows = _data(response)
        return (rows[0] if rows else None), None
    except Exception as exc:
        return None, _message(exc)


def set_comment_pinned(
    supabase: Any,
    *,
    workspace_id: str,
    comment_id: str,
    is_pinned: bool,
) -> Optional[str]:
    try:
        (
            supabase.table("analysis_comments")
            .update({"is_pinned": bool(is_pinned), "updated_at": _now_iso()})
            .eq("workspace_id", workspace_id)
            .eq("id", comment_id)
            .execute()
        )
        return None
    except Exception as exc:
        return _message(exc)


def delete_comment(
    supabase: Any,
    *,
    workspace_id: str,
    comment_id: str,
    user_id: str,
    can_manage: bool,
) -> Optional[str]:
    try:
        query = (
            supabase.table("analysis_comments")
            .update(
                {
                    "is_deleted": True,
                    "deleted_at": _now_iso(),
                    "updated_at": _now_iso(),
                }
            )
            .eq("workspace_id", workspace_id)
            .eq("id", comment_id)
        )
        if not can_manage:
            query = query.eq("user_id", user_id)
        query.execute()
        return None
    except Exception as exc:
        return _message(exc)


def is_following_analysis(
    supabase: Any,
    *,
    workspace_id: str,
    analysis_id: str,
    user_id: str,
) -> Tuple[bool, Optional[str]]:
    try:
        rows = _data(
            supabase.table("analysis_followers")
            .select("id")
            .eq("workspace_id", workspace_id)
            .eq("analysis_id", analysis_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return bool(rows), None
    except Exception as exc:
        return False, _message(exc)


def follow_analysis(
    supabase: Any,
    *,
    workspace_id: str,
    analysis_id: str,
    user_id: str,
) -> Optional[str]:
    try:
        existing, error = is_following_analysis(
            supabase,
            workspace_id=workspace_id,
            analysis_id=analysis_id,
            user_id=user_id,
        )
        if error:
            return error
        if existing:
            return None
        (
            supabase.table("analysis_followers")
            .insert(
                {
                    "workspace_id": workspace_id,
                    "analysis_id": analysis_id,
                    "user_id": user_id,
                    "created_at": _now_iso(),
                }
            )
            .execute()
        )
        return None
    except Exception as exc:
        return _message(exc)


def unfollow_analysis(
    supabase: Any,
    *,
    workspace_id: str,
    analysis_id: str,
    user_id: str,
) -> Optional[str]:
    try:
        (
            supabase.table("analysis_followers")
            .delete()
            .eq("workspace_id", workspace_id)
            .eq("analysis_id", analysis_id)
            .eq("user_id", user_id)
            .execute()
        )
        return None
    except Exception as exc:
        return _message(exc)


def list_analysis_followers(
    supabase: Any,
    *,
    workspace_id: str,
    analysis_id: str,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        rows = _data(
            supabase.table("analysis_followers")
            .select("id,user_id,created_at")
            .eq("workspace_id", workspace_id)
            .eq("analysis_id", analysis_id)
            .order("created_at", desc=False)
            .execute()
        )
        return rows, None
    except Exception as exc:
        return [], _message(exc)


def extract_mentions(body: str) -> List[str]:
    """Return normalized @mention handles from a comment body."""
    values = re.findall(r"(?<!\w)@([A-Za-z0-9._+-]+)", body or "")
    seen = set()
    result = []
    for value in values:
        normalized = value.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def resolve_mentioned_members(
    members: List[Dict[str, Any]],
    mentions: List[str],
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    seen_users = set()
    for member in members or []:
        email = str(member.get("email") or "").strip().lower()
        name = str(member.get("display_name") or "").strip().lower()
        email_handle = email.split("@", 1)[0] if "@" in email else email
        name_tokens = {
            token
            for token in re.split(r"[^a-z0-9._+-]+", name)
            if token
        }
        candidates = {email, email_handle, name.replace(" ", ".")} | name_tokens
        if any(mention in candidates for mention in mentions):
            user_id = str(member.get("user_id") or "")
            if user_id and user_id not in seen_users:
                seen_users.add(user_id)
                matched.append(member)
    return matched


def create_workspace_notification(
    supabase: Any,
    *,
    workspace_id: str,
    user_id: str,
    title: str,
    message: str,
    notification_type: str,
) -> Optional[str]:
    try:
        (
            supabase.table("workspace_notifications")
            .insert(
                {
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "title": title,
                    "message": message,
                    "notification_type": notification_type,
                    "is_read": False,
                    "created_at": _now_iso(),
                }
            )
            .execute()
        )
        return None
    except Exception as exc:
        return _message(exc)
