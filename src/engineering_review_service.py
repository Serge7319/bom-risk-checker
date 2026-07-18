"""Persistent collaborative engineering review data access for Cadivor Milestone 27.2."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _apply_workspace(query, workspace_id: str | None):
    if workspace_id:
        return query.eq("workspace_id", workspace_id)
    return query.is_("workspace_id", "null")


def get_latest_review_session(
    supabase,
    *,
    analysis_id: str,
    user_id: str,
    workspace_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        query = (
            supabase.table("engineering_review_sessions")
            .select("*")
            .eq("analysis_id", analysis_id)
            .eq("user_id", user_id)
        )
        query = _apply_workspace(query, workspace_id)
        rows = query.order("created_at", desc=True).limit(1).execute().data or []
        return (rows[0] if rows else None), None
    except Exception as exc:
        return None, _error(exc)


def create_review_session(
    supabase,
    *,
    analysis_id: str,
    user_id: str,
    workspace_id: str | None,
    reviewer_name: str,
    reviewer_email: str,
    total_items: int,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        existing, error = get_latest_review_session(
            supabase,
            analysis_id=analysis_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        if existing and existing.get("status") in {"active", "paused", "completed"}:
            if existing.get("status") == "paused":
                return update_review_session_status(
                    supabase,
                    session_id=existing["id"],
                    user_id=user_id,
                    workspace_id=workspace_id,
                    status="active",
                )
            return existing, None
        payload = {
            "analysis_id": analysis_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "reviewer_name": reviewer_name,
            "reviewer_email": reviewer_email or None,
            "status": "active",
            "is_locked": False,
            "total_items": max(0, int(total_items)),
            "reviewed_items": 0,
            "decision_counts": {},
            "started_at": _now(),
            "updated_at": _now(),
        }
        rows = supabase.table("engineering_review_sessions").insert(payload).execute().data or []
        session = rows[0] if rows else None
        if session:
            _insert_event(
                supabase,
                session_id=session["id"],
                analysis_id=analysis_id,
                user_id=user_id,
                workspace_id=workspace_id,
                event_type="session_started",
                title="Engineering review started",
                body=f"{reviewer_name} started an engineering review.",
                actor_name=reviewer_name,
                actor_email=reviewer_email,
            )
        return session, None
    except Exception as exc:
        return None, _error(exc)


def list_review_items(
    supabase,
    *,
    session_id: str,
    user_id: str,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        query = (
            supabase.table("engineering_review_items")
            .select("*")
            .eq("session_id", session_id)
            .eq("user_id", user_id)
        )
        query = _apply_workspace(query, workspace_id)
        rows = query.order("updated_at", desc=True).execute().data or []
        return rows, None
    except Exception as exc:
        return [], _error(exc)


def save_review_item(
    supabase,
    *,
    session_id: str,
    analysis_id: str,
    user_id: str,
    workspace_id: str | None,
    mpn: str,
    manufacturer: str,
    decision: str,
    owner: str,
    due_label: str,
    due_date: str | None,
    assignee_name: str,
    assignee_email: str,
    assignee_user_id: str,
    priority: str,
    notes: str,
    reviewer_name: str,
    reviewer_email: str,
    recommendation: str,
    recommendation_confidence: int,
    evidence: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        session_rows = (
            supabase.table("engineering_review_sessions")
            .select("id,is_locked,status")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute().data
            or []
        )
        if not session_rows:
            return None, "Review session was not found."
        if session_rows[0].get("is_locked"):
            return None, "This review is locked."

        existing_rows = (
            supabase.table("engineering_review_items")
            .select("*")
            .eq("session_id", session_id)
            .eq("mpn", mpn)
            .limit(1)
            .execute().data
            or []
        )
        previous = existing_rows[0] if existing_rows else None
        payload = {
            "session_id": session_id,
            "analysis_id": analysis_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "mpn": mpn,
            "manufacturer": manufacturer or None,
            "decision": decision,
            "owner": owner,
            "due_label": due_label,
            "due_date": due_date,
            "assignee_name": assignee_name or None,
            "assignee_email": assignee_email or None,
            "assignee_user_id": assignee_user_id or None,
            "priority": priority,
            "notes": notes,
            "reviewer_name": reviewer_name,
            "reviewer_email": reviewer_email or None,
            "recommendation": recommendation,
            "recommendation_confidence": max(0, min(100, int(recommendation_confidence))),
            "evidence": evidence or {},
            "reviewed_at": _now(),
            "updated_at": _now(),
        }
        if previous:
            rows = (
                supabase.table("engineering_review_items")
                .update(payload)
                .eq("id", previous["id"])
                .execute().data
                or []
            )
        else:
            rows = supabase.table("engineering_review_items").insert(payload).execute().data or []
        item = rows[0] if rows else None

        all_items, _ = list_review_items(
            supabase,
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        reviewed = sum(1 for row in all_items if row.get("decision") in {"Approve", "Needs Investigation", "Reject"})
        counts = {"Approve": 0, "Needs Investigation": 0, "Reject": 0, "Skip": 0}
        for row in all_items:
            if row.get("decision") in counts:
                counts[row["decision"]] += 1
        supabase.table("engineering_review_sessions").update(
            {"reviewed_items": reviewed, "decision_counts": counts, "updated_at": _now()}
        ).eq("id", session_id).execute()

        prior_decision = previous.get("decision") if previous else None
        verb = "updated" if previous else "recorded"
        assignee_text = assignee_name or "Unassigned"
        body = f"{mpn} was {verb} as {decision}. Owner: {owner}. Assigned to: {assignee_text}. Due: {due_label}."
        if prior_decision and prior_decision != decision:
            body += f" Previous decision: {prior_decision}."
        _insert_event(
            supabase,
            session_id=session_id,
            analysis_id=analysis_id,
            user_id=user_id,
            workspace_id=workspace_id,
            review_item_id=item.get("id") if item else None,
            event_type="decision_saved",
            title=f"Engineering review decision · {mpn}",
            body=body,
            actor_name=reviewer_name,
            actor_email=reviewer_email,
            metadata={"decision": decision, "previous_decision": prior_decision, "owner": owner, "assignee_name": assignee_name, "assignee_email": assignee_email, "due_date": due_date, "priority": priority},
        )
        return item, None
    except Exception as exc:
        return None, _error(exc)


def update_review_session_status(
    supabase,
    *,
    session_id: str,
    user_id: str,
    workspace_id: str | None,
    status: str,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = {"status": status, "updated_at": _now()}
        rows = (
            supabase.table("engineering_review_sessions")
            .update(payload)
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute().data
            or []
        )
        return (rows[0] if rows else None), None
    except Exception as exc:
        return None, _error(exc)


def set_review_lock(
    supabase,
    *,
    session_id: str,
    user_id: str,
    workspace_id: str | None,
    locked: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = {
            "is_locked": bool(locked),
            "status": "completed" if locked else "active",
            "updated_at": _now(),
        }
        if not locked:
            payload["completed_at"] = None
        rows = (
            supabase.table("engineering_review_sessions")
            .update(payload)
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute().data
            or []
        )
        return (rows[0] if rows else None), None
    except Exception as exc:
        return None, _error(exc)


def complete_review_session(
    supabase,
    *,
    session_id: str,
    user_id: str,
    workspace_id: str | None,
    reviewed_items: int,
    decision_counts: dict[str, int],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = {
            "status": "completed",
            "is_locked": True,
            "reviewed_items": int(reviewed_items),
            "decision_counts": decision_counts,
            "completed_at": _now(),
            "updated_at": _now(),
        }
        rows = (
            supabase.table("engineering_review_sessions")
            .update(payload)
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute().data
            or []
        )
        session = rows[0] if rows else None
        if session:
            _insert_event(
                supabase,
                session_id=session_id,
                analysis_id=session.get("analysis_id"),
                user_id=user_id,
                workspace_id=workspace_id,
                event_type="session_completed",
                title="Engineering review completed",
                body=f"The review was completed and locked with {reviewed_items} reviewed component(s).",
                actor_name=session.get("reviewer_name") or "Cadivor reviewer",
                actor_email=session.get("reviewer_email") or "",
                metadata={"decision_counts": decision_counts},
            )
        return session, None
    except Exception as exc:
        return None, _error(exc)


def list_review_events(
    supabase,
    *,
    analysis_id: str,
    user_id: str,
    workspace_id: str | None = None,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        query = (
            supabase.table("engineering_review_events")
            .select("*")
            .eq("analysis_id", analysis_id)
            .eq("user_id", user_id)
        )
        query = _apply_workspace(query, workspace_id)
        rows = query.order("created_at", desc=True).limit(limit).execute().data or []
        return rows, None
    except Exception as exc:
        return [], _error(exc)


def _insert_event(
    supabase,
    *,
    session_id: str,
    analysis_id: str,
    user_id: str,
    workspace_id: str | None,
    event_type: str,
    title: str,
    body: str,
    actor_name: str,
    actor_email: str,
    review_item_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    payload = {
        "session_id": session_id,
        "review_item_id": review_item_id,
        "analysis_id": analysis_id,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "event_type": event_type,
        "title": title,
        "body": body,
        "actor_name": actor_name,
        "actor_email": actor_email or None,
        "metadata": metadata or {},
        "created_at": _now(),
    }
    supabase.table("engineering_review_events").insert(payload).execute()


def list_review_comments(
    supabase,
    *,
    review_item_id: str,
    user_id: str,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        query = (
            supabase.table("engineering_review_comments")
            .select("*")
            .eq("review_item_id", review_item_id)
            .eq("user_id", user_id)
        )
        query = _apply_workspace(query, workspace_id)
        rows = query.order("created_at", desc=False).execute().data or []
        return rows, None
    except Exception as exc:
        return [], _error(exc)


def add_review_comment(
    supabase,
    *,
    review_item_id: str,
    session_id: str,
    analysis_id: str,
    user_id: str,
    workspace_id: str | None,
    body: str,
    author_name: str,
    author_email: str,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        clean_body = str(body or "").strip()
        if not clean_body:
            return None, "Comment cannot be empty."
        payload = {
            "review_item_id": review_item_id,
            "session_id": session_id,
            "analysis_id": analysis_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "body": clean_body,
            "author_name": author_name,
            "author_email": author_email or None,
            "created_at": _now(),
        }
        rows = supabase.table("engineering_review_comments").insert(payload).execute().data or []
        comment = rows[0] if rows else None
        _insert_event(
            supabase,
            session_id=session_id,
            analysis_id=analysis_id,
            user_id=user_id,
            workspace_id=workspace_id,
            review_item_id=review_item_id,
            event_type="review_comment",
            title="Engineering review comment added",
            body=clean_body,
            actor_name=author_name,
            actor_email=author_email,
        )
        return comment, None
    except Exception as exc:
        return None, _error(exc)


def reopen_review_session(
    supabase,
    *,
    session_id: str,
    user_id: str,
    workspace_id: str | None,
    reason: str,
    actor_name: str,
    actor_email: str,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        reason = str(reason or "").strip()
        if not reason:
            return None, "A reopen reason is required."
        rows = (
            supabase.table("engineering_review_sessions")
            .update({"is_locked": False, "status": "active", "completed_at": None, "updated_at": _now()})
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute().data or []
        )
        session = rows[0] if rows else None
        if not session:
            return None, "Review session was not found."
        _insert_event(
            supabase,
            session_id=session_id,
            analysis_id=session.get("analysis_id"),
            user_id=user_id,
            workspace_id=workspace_id,
            event_type="session_reopened",
            title="Engineering review reopened",
            body=f"Reason: {reason}",
            actor_name=actor_name,
            actor_email=actor_email,
            metadata={"reason": reason},
        )
        return session, None
    except Exception as exc:
        return None, _error(exc)
