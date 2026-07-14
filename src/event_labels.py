"""User-facing labels for Cadivor collaboration and audit events.

Raw database action names remain available for exports and support diagnostics,
but customer-facing pages use the helpers in this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

_ACTION_LABELS = {
    "analysis_comments.insert": "Comment added",
    "analysis_comments.update": "Comment updated",
    "analysis_comments.delete": "Comment deleted",
    "analysis_followers.insert": "BOM followed",
    "analysis_followers.delete": "BOM unfollowed",
    "alternative_recommendations.insert": "Alternative recommendation saved",
    "alternative_recommendations.update": "Alternative recommendation updated",
    "decision_records.insert": "Engineering decision saved",
    "decision_records.update": "Engineering decision updated",
    "monitoring_alerts.insert": "Monitoring alert created",
    "monitoring_alerts.update": "Monitoring alert updated",
    "analyses.insert": "BOM analysis created",
    "analyses.update": "BOM analysis updated",
    "analyses.delete": "BOM analysis deleted",
    "workspace.created": "Workspace created",
    "workspace.updated": "Workspace settings updated",
    "organization.created": "Organization created",
    "member.invited": "Team member invited",
    "member_invited": "Team member invited",
    "member.invite_cancelled": "Invitation cancelled",
    "member_invite_cancelled": "Invitation cancelled",
    "member.role_updated": "Member role updated",
    "member.removed": "Team member removed",
    "report.generated": "Report generated",
    "report.downloaded": "Report downloaded",
}

_CATEGORY_LABELS = {
    "analysis": "BOM analysis",
    "discussion": "Discussions",
    "alternative": "Alternatives",
    "monitoring": "Monitoring",
    "report": "Reports",
    "workspace": "Workspace",
    "member": "Team access",
    "security": "Security",
    "other": "Other activity",
}


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    return value or fallback


def normalize_action(action: Any) -> str:
    return _text(action).lower().strip()


def event_category(action: Any, object_type: Any = "") -> str:
    joined = f"{normalize_action(action)} {_text(object_type).lower()}"
    if any(token in joined for token in ("analysis_comment", "comment", "discussion")):
        return "discussion"
    if any(token in joined for token in ("alternative", "replacement", "decision_record")):
        return "alternative"
    if any(token in joined for token in ("monitor", "alert", "stock", "lifecycle")):
        return "monitoring"
    if "report" in joined or "export" in joined:
        return "report"
    if any(token in joined for token in ("member", "invite", "role")):
        return "member"
    if any(token in joined for token in ("workspace", "organization")):
        return "workspace"
    if any(token in joined for token in ("analysis", "bom")):
        return "analysis"
    if any(token in joined for token in ("login", "security", "password", "auth")):
        return "security"
    return "other"


def category_label(category: Any) -> str:
    return _CATEGORY_LABELS.get(_text(category).lower(), "Other activity")


def action_label(action: Any) -> str:
    raw = normalize_action(action)
    if not raw:
        return "Engineering activity"
    if raw in _ACTION_LABELS:
        return _ACTION_LABELS[raw]

    # Normalize common database trigger names without exposing table syntax.
    normalized = raw.replace("::", ".").replace("_", " ").replace(".", " ")
    replacements = {
        " insert": " added",
        " update": " updated",
        " delete": " removed",
        " created": " created",
        " cancelled": " cancelled",
    }
    for old, new in replacements.items():
        if normalized.endswith(old):
            normalized = normalized[: -len(old)] + new
            break
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.title() if normalized else "Engineering activity"


def friendly_summary(row: dict[str, Any]) -> str:
    action = normalize_action(row.get("action_type") or row.get("action"))
    object_label = _text(row.get("object_label"))
    summary = _text(row.get("summary"))

    if action.startswith("analysis_comments"):
        return f"Engineering discussion on {object_label}" if object_label else "Engineering discussion updated"
    if action.startswith("analysis_followers"):
        return f"Following status changed for {object_label}" if object_label else "BOM following status changed"
    if action.startswith("alternative_recommendations"):
        return f"Replacement review saved for {object_label}" if object_label else "Replacement review saved"
    if action.startswith("monitoring_alerts"):
        return f"Monitoring change recorded for {object_label}" if object_label else "Monitoring change recorded"
    if action.startswith("analyses"):
        return f"BOM analysis updated: {object_label}" if object_label else action_label(action)

    if summary:
        # Remove backend-oriented phrases when a trigger generated the summary.
        cleaned = re.sub(r"\b(insert|update|delete)\b", "", summary, flags=re.I)
        cleaned = cleaned.replace("Analysis Comments", "Engineering discussion")
        cleaned = cleaned.replace("Analysis Followers", "BOM follower")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ·-")
        if cleaned and not re.fullmatch(r"[0-9a-f-]{24,}", cleaned, flags=re.I):
            return cleaned
    if object_label:
        return object_label
    return action_label(action)


def display_time(value: Any) -> str:
    text = _text(value)
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%b %d, %Y · %I:%M %p UTC")
    except Exception:
        return text[:19].replace("T", " ")
