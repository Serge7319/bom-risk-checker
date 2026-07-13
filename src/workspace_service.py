"""Cadivor workspace and collaboration data service.

Milestone 10B keeps database access out of the Streamlit page and provides
safe, small helpers for workspace bootstrap, membership, invitations,
activity, and notifications.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_TABLES = {
    "workspaces",
    "workspace_members",
    "workspace_invites",
    "workspace_activity",
    "workspace_notifications",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data(response: Any) -> List[Dict[str, Any]]:
    value = getattr(response, "data", None)
    return value if isinstance(value, list) else []


def _message(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def migration_missing(exc: Exception) -> bool:
    text = _message(exc).lower()
    signals = (
        "does not exist",
        "could not find the table",
        "schema cache",
        "relation",
        "workspace_members",
        "workspaces",
        "user_workspace_preferences",
    )
    return any(signal in text for signal in signals)


def ensure_personal_workspace(
    supabase: Any,
    user_id: str,
    owner_email: str,
    owner_name: str,
    workspace_name: str,
    plan: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return the user's first active workspace, creating one when necessary."""
    try:
        memberships = _data(
            supabase.table("workspace_members")
            .select("workspace_id,role,status,joined_at,workspaces(*)")
            .eq("user_id", user_id)
            .eq("status", "active")
            .order("joined_at", desc=False)
            .limit(1)
            .execute()
        )
        if memberships:
            row = memberships[0]
            workspace = row.get("workspaces") or {}
            if isinstance(workspace, list):
                workspace = workspace[0] if workspace else {}
            workspace["current_role"] = row.get("role", "viewer")
            return workspace, None

        workspace_payload = {
            "name": workspace_name or "Cadivor Workspace",
            "owner_id": user_id,
            "plan": (plan or "Starter").lower(),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        created = _data(supabase.table("workspaces").insert(workspace_payload).execute())
        if not created:
            return None, "Cadivor could not create the workspace record."
        workspace = created[0]
        supabase.table("workspace_members").insert(
            {
                "workspace_id": workspace["id"],
                "user_id": user_id,
                "email": owner_email,
                "display_name": owner_name,
                "role": "owner",
                "status": "active",
                "joined_at": _now_iso(),
            }
        ).execute()
        record_activity(
            supabase,
            workspace["id"],
            user_id,
            owner_name,
            "workspace.created",
            f"Created workspace {workspace['name']}",
            {"workspace_name": workspace["name"]},
        )
        workspace["current_role"] = "owner"
        return workspace, None
    except Exception as exc:
        if migration_missing(exc):
            return None, "migration_required"
        return None, _message(exc)


def list_members(supabase: Any, workspace_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        rows = _data(
            supabase.table("workspace_members")
            .select("id,user_id,email,display_name,role,status,joined_at")
            .eq("workspace_id", workspace_id)
            .order("joined_at", desc=False)
            .execute()
        )
        return rows, None
    except Exception as exc:
        return [], _message(exc)


def list_invites(supabase: Any, workspace_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        rows = _data(
            supabase.table("workspace_invites")
            .select("id,email,role,status,invited_by_name,created_at,expires_at")
            .eq("workspace_id", workspace_id)
            .order("created_at", desc=True)
            .execute()
        )
        return rows, None
    except Exception as exc:
        return [], _message(exc)


def create_invite(
    supabase: Any,
    workspace_id: str,
    email: str,
    role: str,
    invited_by: str,
    invited_by_name: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    normalized_email = (email or "").strip().lower()
    normalized_role = (role or "engineer").strip().lower()
    if normalized_role not in {"admin", "engineer", "viewer"}:
        normalized_role = "engineer"
    if "@" not in normalized_email or normalized_email.startswith("@"):
        return None, "Enter a valid email address."
    try:
        existing = _data(
            supabase.table("workspace_invites")
            .select("id,status")
            .eq("workspace_id", workspace_id)
            .eq("email", normalized_email)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        if existing:
            return None, "A pending invitation already exists for this email address."
        rows = _data(
            supabase.table("workspace_invites")
            .insert(
                {
                    "workspace_id": workspace_id,
                    "email": normalized_email,
                    "role": normalized_role,
                    "status": "pending",
                    "invited_by": invited_by,
                    "invited_by_name": invited_by_name,
                    "created_at": _now_iso(),
                }
            )
            .execute()
        )
        invite = rows[0] if rows else None
        record_activity(
            supabase,
            workspace_id,
            invited_by,
            invited_by_name,
            "member.invited",
            f"Invited {normalized_email} as {normalized_role}",
            {"email": normalized_email, "role": normalized_role},
        )
        create_notification(
            supabase,
            workspace_id,
            invited_by,
            "Workspace invitation created",
            f"{normalized_email} was invited as {normalized_role}.",
            "workspace_invite",
        )
        return invite, None
    except Exception as exc:
        return None, _message(exc)


def cancel_invite(
    supabase: Any,
    workspace_id: str,
    invite_id: str,
    actor_id: str,
    actor_name: str,
    invite_email: str,
) -> Optional[str]:
    try:
        supabase.table("workspace_invites").update(
            {"status": "cancelled", "updated_at": _now_iso()}
        ).eq("workspace_id", workspace_id).eq("id", invite_id).execute()
        record_activity(
            supabase,
            workspace_id,
            actor_id,
            actor_name,
            "member.invite_cancelled",
            f"Cancelled invitation for {invite_email}",
            {"email": invite_email},
        )
        return None
    except Exception as exc:
        return _message(exc)


def update_member_role(
    supabase: Any,
    workspace_id: str,
    member_id: str,
    new_role: str,
    actor_id: str,
    actor_name: str,
    member_email: str,
) -> Optional[str]:
    role = (new_role or "viewer").lower()
    if role not in {"admin", "engineer", "viewer"}:
        return "Unsupported workspace role."
    try:
        supabase.table("workspace_members").update(
            {"role": role, "updated_at": _now_iso()}
        ).eq("workspace_id", workspace_id).eq("id", member_id).neq("role", "owner").execute()
        record_activity(
            supabase,
            workspace_id,
            actor_id,
            actor_name,
            "member.role_changed",
            f"Changed {member_email} to {role}",
            {"email": member_email, "role": role},
        )
        return None
    except Exception as exc:
        return _message(exc)


def remove_member(
    supabase: Any,
    workspace_id: str,
    member_id: str,
    actor_id: str,
    actor_name: str,
    member_email: str,
) -> Optional[str]:
    try:
        supabase.table("workspace_members").update(
            {"status": "removed", "updated_at": _now_iso()}
        ).eq("workspace_id", workspace_id).eq("id", member_id).neq("role", "owner").execute()
        record_activity(
            supabase,
            workspace_id,
            actor_id,
            actor_name,
            "member.removed",
            f"Removed {member_email} from the workspace",
            {"email": member_email},
        )
        return None
    except Exception as exc:
        return _message(exc)


def update_workspace(
    supabase: Any,
    workspace_id: str,
    name: str,
    timezone_name: str,
    unit_system: str,
    actor_id: str,
    actor_name: str,
) -> Optional[str]:
    try:
        payload = {
            "name": (name or "Cadivor Workspace").strip(),
            "timezone": (timezone_name or "UTC").strip(),
            "unit_system": unit_system if unit_system in {"metric", "imperial"} else "metric",
            "updated_at": _now_iso(),
        }
        supabase.table("workspaces").update(payload).eq("id", workspace_id).execute()
        record_activity(
            supabase,
            workspace_id,
            actor_id,
            actor_name,
            "workspace.updated",
            "Updated workspace settings",
            payload,
        )
        return None
    except Exception as exc:
        return _message(exc)


def list_activity(supabase: Any, workspace_id: str, limit: int = 50) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        rows = _data(
            supabase.table("workspace_activity")
            .select("id,actor_id,actor_name,action,summary,metadata,created_at")
            .eq("workspace_id", workspace_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return rows, None
    except Exception as exc:
        return [], _message(exc)


def record_activity(
    supabase: Any,
    workspace_id: str,
    actor_id: Optional[str],
    actor_name: str,
    action: str,
    summary: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        supabase.table("workspace_activity").insert(
            {
                "workspace_id": workspace_id,
                "actor_id": actor_id,
                "actor_name": actor_name or "Cadivor user",
                "action": action,
                "summary": summary,
                "metadata": metadata or {},
                "created_at": _now_iso(),
            }
        ).execute()
    except Exception:
        # Activity must never break the primary user action.
        return


def create_notification(
    supabase: Any,
    workspace_id: str,
    user_id: Optional[str],
    title: str,
    message: str,
    notification_type: str,
) -> None:
    try:
        supabase.table("workspace_notifications").insert(
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "title": title,
                "message": message,
                "notification_type": notification_type,
                "is_read": False,
                "created_at": _now_iso(),
            }
        ).execute()
    except Exception:
        return


def list_notifications(
    supabase: Any,
    workspace_id: str,
    user_id: str,
    limit: int = 50,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        rows = _data(
            supabase.table("workspace_notifications")
            .select("id,title,message,notification_type,is_read,created_at")
            .eq("workspace_id", workspace_id)
            .or_(f"user_id.eq.{user_id},user_id.is.null")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return rows, None
    except Exception as exc:
        return [], _message(exc)


def mark_notification_read(supabase: Any, notification_id: str) -> Optional[str]:
    try:
        supabase.table("workspace_notifications").update(
            {"is_read": True, "read_at": _now_iso()}
        ).eq("id", notification_id).execute()
        return None
    except Exception as exc:
        return _message(exc)


def list_user_workspaces(
    supabase: Any,
    user_id: str,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Return every active organization/workspace available to a user."""
    try:
        rows = _data(
            supabase.table("workspace_members")
            .select("workspace_id,role,status,joined_at,workspaces(*)")
            .eq("user_id", user_id)
            .eq("status", "active")
            .order("joined_at", desc=False)
            .execute()
        )
        organizations: List[Dict[str, Any]] = []
        for row in rows:
            workspace = row.get("workspaces") or {}
            if isinstance(workspace, list):
                workspace = workspace[0] if workspace else {}
            if not isinstance(workspace, dict) or not workspace.get("id"):
                continue
            item = dict(workspace)
            item["current_role"] = row.get("role", "viewer")
            item["membership_status"] = row.get("status", "active")
            organizations.append(item)
        return organizations, None
    except Exception as exc:
        return [], _message(exc)


def get_workspace_by_id(
    supabase: Any,
    user_id: str,
    workspace_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load one workspace only when the user has an active membership."""
    try:
        rows = _data(
            supabase.table("workspace_members")
            .select("workspace_id,role,status,workspaces(*)")
            .eq("user_id", user_id)
            .eq("workspace_id", workspace_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        if not rows:
            return None, "Workspace access was not found."
        row = rows[0]
        workspace = row.get("workspaces") or {}
        if isinstance(workspace, list):
            workspace = workspace[0] if workspace else {}
        if not isinstance(workspace, dict):
            return None, "Workspace record was unavailable."
        workspace = dict(workspace)
        workspace["current_role"] = row.get("role", "viewer")
        return workspace, None
    except Exception as exc:
        return None, _message(exc)


def get_active_workspace_preference(
    supabase: Any,
    user_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Return the user's persisted active workspace preference."""
    try:
        rows = _data(
            supabase.table("user_workspace_preferences")
            .select("active_workspace_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not rows:
            return None, None
        value = rows[0].get("active_workspace_id")
        return str(value) if value else None, None
    except Exception as exc:
        if migration_missing(exc) or "user_workspace_preferences" in _message(exc).lower():
            return None, "migration_required"
        return None, _message(exc)


def set_active_workspace_preference(
    supabase: Any,
    user_id: str,
    workspace_id: str,
) -> Optional[str]:
    """Persist the organization the user last opened."""
    try:
        existing = _data(
            supabase.table("user_workspace_preferences")
            .select("user_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        payload = {
            "user_id": user_id,
            "active_workspace_id": workspace_id,
            "updated_at": _now_iso(),
        }
        if existing:
            supabase.table("user_workspace_preferences").update(payload).eq(
                "user_id", user_id
            ).execute()
        else:
            payload["created_at"] = _now_iso()
            supabase.table("user_workspace_preferences").insert(payload).execute()
        return None
    except Exception as exc:
        return _message(exc)


def create_organization_workspace(
    supabase: Any,
    user_id: str,
    owner_email: str,
    owner_name: str,
    organization_name: str,
    plan: str = "starter",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Create a second organization and make the creator its owner."""
    clean_name = (organization_name or "").strip()
    if len(clean_name) < 2:
        return None, "Enter an organization name with at least 2 characters."
    try:
        created = _data(
            supabase.table("workspaces")
            .insert(
                {
                    "name": clean_name,
                    "owner_id": user_id,
                    "plan": (plan or "starter").lower(),
                    "organization_type": "company",
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                }
            )
            .execute()
        )
        if not created:
            return None, "Cadivor could not create the organization."
        workspace = created[0]
        supabase.table("workspace_members").insert(
            {
                "workspace_id": workspace["id"],
                "user_id": user_id,
                "email": owner_email,
                "display_name": owner_name,
                "role": "owner",
                "status": "active",
                "joined_at": _now_iso(),
            }
        ).execute()
        record_activity(
            supabase,
            workspace["id"],
            user_id,
            owner_name,
            "organization.created",
            f"Created organization {clean_name}",
            {"organization_name": clean_name},
        )
        workspace["current_role"] = "owner"
        return workspace, None
    except Exception as exc:
        return None, _message(exc)
