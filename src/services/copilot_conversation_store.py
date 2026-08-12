"""Durable Ask Cadivor conversation persistence (user + analysis scoped)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

TABLE = "copilot_conversation_threads"
MAX_TURNS = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data(response: Any) -> list[dict[str, Any]]:
    value = getattr(response, "data", None)
    return value if isinstance(value, list) else []


def _message(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def normalize_persisted_thread(raw: Any) -> list[dict[str, Any]]:
    """Return a safe thread list from persisted JSON; corrupt rows are dropped."""
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not question or not answer:
            continue
        normalized.append(
            {
                "question": question,
                "answer": answer,
                "provider_connected": bool(item.get("provider_connected")),
            }
        )
    return normalized[-MAX_TURNS:]


def load_thread(
    supabase: Any,
    *,
    user_id: str,
    analysis_id: str,
    workspace_id: str = "",
) -> tuple[list[dict[str, Any]], str | None]:
    """Load the saved Ask Cadivor thread for one authorized user/analysis pair."""
    user_key = str(user_id or "").strip()
    analysis_key = str(analysis_id or "").strip()
    if not supabase or not user_key or not analysis_key:
        return [], None
    try:
        query = (
            supabase.table(TABLE)
            .select("thread")
            .eq("user_id", user_key)
            .eq("analysis_id", analysis_key)
            .limit(1)
        )
        workspace_key = str(workspace_id or "").strip()
        if workspace_key:
            query = query.eq("workspace_id", workspace_key)
        rows = _data(query.execute())
        if not rows:
            return [], None
        thread = normalize_persisted_thread(rows[0].get("thread"))
        return thread, None
    except Exception as exc:
        return [], _message(exc)


def save_thread(
    supabase: Any,
    *,
    user_id: str,
    analysis_id: str,
    workspace_id: str,
    thread: list[dict[str, Any]],
) -> str | None:
    """Upsert the Ask Cadivor thread for one authorized user/analysis pair."""
    user_key = str(user_id or "").strip()
    analysis_key = str(analysis_id or "").strip()
    if not supabase or not user_key or not analysis_key:
        return None
    payload = normalize_persisted_thread(thread)
    if not payload:
        return delete_thread(
            supabase,
            user_id=user_key,
            analysis_id=analysis_key,
            workspace_id=workspace_id,
        )
    record: dict[str, Any] = {
        "user_id": user_key,
        "analysis_id": analysis_key,
        "thread": payload,
        "updated_at": _now_iso(),
    }
    workspace_key = str(workspace_id or "").strip()
    if workspace_key:
        record["workspace_id"] = workspace_key
    try:
        supabase.table(TABLE).upsert(
            record,
            on_conflict="user_id,analysis_id",
        ).execute()
        return None
    except Exception as exc:
        return _message(exc)


def delete_thread(
    supabase: Any,
    *,
    user_id: str,
    analysis_id: str,
    workspace_id: str = "",
) -> str | None:
    """Remove the saved Ask Cadivor thread for one authorized user/analysis pair."""
    user_key = str(user_id or "").strip()
    analysis_key = str(analysis_id or "").strip()
    if not supabase or not user_key or not analysis_key:
        return None
    try:
        query = (
            supabase.table(TABLE)
            .delete()
            .eq("user_id", user_key)
            .eq("analysis_id", analysis_key)
        )
        workspace_key = str(workspace_id or "").strip()
        if workspace_key:
            query = query.eq("workspace_id", workspace_key)
        query.execute()
        return None
    except Exception as exc:
        return _message(exc)
