"""Shared workflow rules for Cadivor engineering reviews.

Milestone 28.1 moves non-visual review logic out of the Analysis Detail page so
future review screens use the same due-date, workflow-health, unresolved-state,
and audit-validation rules.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

_COMPLETED = {"Approve", "Reject", "Skip"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def parse_due_date(row: dict[str, Any], *, today: date | None = None) -> date | None:
    today = today or date.today()
    raw = row.get("due_date")
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except (TypeError, ValueError):
            pass
    return {
        "Today": today,
        "Tomorrow": today + timedelta(days=1),
        "This Week": today + timedelta(days=7),
        "Next Week": today + timedelta(days=14),
        "Next Sprint": today + timedelta(days=21),
    }.get(_text(row.get("due_label")))


def is_unresolved_review(row: dict[str, Any], *, today: date | None = None) -> bool:
    decision = _text(row.get("decision"))
    due = parse_due_date(row, today=today)
    today = today or date.today()
    return (
        decision not in _COMPLETED
        or not _text(row.get("assignee_name"))
        or bool(due and due < today and decision not in _COMPLETED)
    )


def summarize_review_workflow(
    review_items: list[dict[str, Any]],
    *,
    reviewer_email: str,
    total_items: int,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    email = _text(reviewer_email).lower()
    open_rows = [row for row in review_items if _text(row.get("decision")) not in _COMPLETED]
    overdue = [row for row in open_rows if (parse_due_date(row, today=today) or today) < today]
    due_week = [
        row for row in open_rows
        if (due := parse_due_date(row, today=today)) and today <= due <= today + timedelta(days=7)
    ]
    assigned_me = [row for row in open_rows if email and _text(row.get("assignee_email")).lower() == email]
    waiting = [row for row in open_rows if _text(row.get("assignee_email")) and _text(row.get("assignee_email")).lower() != email]
    completed_today = [
        row for row in review_items
        if _text(row.get("decision")) in _COMPLETED and str(row.get("updated_at") or "")[:10] == today.isoformat()
    ]
    unassigned = sum(1 for row in open_rows if not _text(row.get("assignee_name")))
    workflow_health = max(
        0,
        min(100, round(100 - len(overdue) * 18 - unassigned * 8 - len(open_rows) / max(1, total_items) * 30)),
    )
    return {
        "open_rows": open_rows,
        "overdue_rows": overdue,
        "due_week_rows": due_week,
        "assigned_me_rows": assigned_me,
        "waiting_rows": waiting,
        "completed_today": completed_today,
        "unassigned_count": unassigned,
        "workflow_health": workflow_health,
    }


def validate_review_decision(
    *,
    decision: str,
    notes: str,
    assignee_name: str,
    risk_score: int,
    lifecycle: str,
) -> tuple[bool, str | None, str | None]:
    """Return (can_save, blocking_error, nonblocking_warning)."""
    decision = _text(decision)
    notes = _text(notes)
    assignee_name = _text(assignee_name)
    lifecycle_lower = _text(lifecycle).lower()

    if decision == "Reject" and not notes:
        return False, "Add an engineering note explaining why this component is rejected.", None
    if decision == "Skip" and not notes:
        return False, "Add a reason before skipping this component.", None
    if decision == "Needs Investigation" and not notes and not assignee_name:
        return False, "Assign an owner or add an investigation note before saving.", None

    risky_lifecycle = any(token in lifecycle_lower for token in ("obsolete", "eol", "end of life", "nrnd", "replacement"))
    if decision == "Approve" and (risk_score >= 70 or risky_lifecycle):
        return True, None, "Approval overrides elevated recorded risk. Confirm the supporting evidence in the notes."
    return True, None, None
