"""Invitations, workspaces, members, profile, and preferences for the Next API.

Authoritative membership source
-------------------------------
The Next app's membership is the dedicated migration database
(``CADIVOR_MIGRATION_DATABASE_URL``): ``migration_workspace_members`` for
access/role and ``migration_workspace_invites`` for invitations (see
``apps.api.team_store`` and ``apps.api.sandbox_auth``). Invitations are stored
there with the same security model as Streamlit's
``cadivor_accept_my_workspace_invitations``: acceptance requires an
authenticated, email-verified user whose email matches the invite, the invite
must still be pending and unexpired, and workspace + role are read from the
stored invitation — never from the browser.

Streamlit's Supabase ``workspace_*`` tables are not read or written here.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.api import invitation_email
from apps.api.invitation_email import InvitationEmailError
from apps.api.sandbox_auth import get_auth_store
from apps.api.team_store import get_team_store

ASSIGNABLE_ROLES = ("admin", "engineer", "viewer")
ADMIN_ROLES = ("owner", "admin")
INVITE_DEFAULT_DAYS = 7
INVITE_MAX_DAYS = 30
RESEND_COOLDOWN_SECONDS = 30
MAX_OWNED_WORKSPACES = 10
_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")

APPEARANCE_OPTIONS = ("system", "light", "dark")
DENSITY_OPTIONS = ("comfortable", "compact")
UNIT_OPTIONS = ("metric", "imperial")
CURRENCY_OPTIONS = ("USD", "EUR", "GBP", "CAD")

PREFERENCE_DEFAULTS: dict[str, Any] = {
    "appearance": "system",
    "density": "comfortable",
    "default_units": "metric",
    "default_currency": "USD",
    "monitoring_notifications": True,
}


class TeamError(Exception):
    def __init__(self, detail: str, status_code: int = 400, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def normalize_email(email: str) -> str:
    value = str(email or "").strip().lower()
    if not _EMAIL_RE.fullmatch(value) or len(value) > 254:
        raise TeamError("Enter a valid email address.", 400)
    return value


def valid_timezone(name: str) -> bool:
    value = str(name or "").strip()
    if not value or len(value) > 64:
        return False
    if value.upper() == "UTC":
        return True
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(value)
        return True
    except Exception:  # noqa: BLE001
        return False


def _clean_text(value: Any, label: str, *, max_len: int = 120, required: bool = False) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise TeamError(f"{label} is required.", 400)
    if len(text) > max_len:
        raise TeamError(f"{label} must be {max_len} characters or fewer.", 400)
    return text


def _member_role(ctx: dict[str, Any]) -> str:
    member = get_auth_store().membership_for_user_workspace(
        ctx["user_id"], ctx["workspace_id"]
    )
    return str((member or {}).get("role") or "")


def require_member(ctx: dict[str, Any]) -> str:
    role = _member_role(ctx)
    if not role:
        raise TeamError("You do not have access to this workspace.", 403)
    return role


def require_admin(ctx: dict[str, Any]) -> str:
    role = require_member(ctx)
    if role not in ADMIN_ROLES:
        raise TeamError("Only workspace owners and admins can do this.", 403)
    return role


def _display_name(user_id: str, email: str, profiles: dict[str, dict[str, Any]] | None = None) -> str:
    profile = (profiles or {}).get(user_id) or {}
    name = str(profile.get("full_name") or "").strip()
    if name:
        return name
    local = (email or "").split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
    return local.title() or "Cadivor user"


def _actor_name(ctx: dict[str, Any]) -> str:
    profile = get_team_store().get_profile(ctx["user_id"]) or {}
    return _display_name(ctx["user_id"], ctx["email"], {ctx["user_id"]: profile})


def record_activity(
    ctx: dict[str, Any] | None,
    workspace_id: str,
    action: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
    *,
    actor_id: str | None = None,
    actor_name: str | None = None,
) -> None:
    """Best-effort audit row; never breaks the primary action."""
    try:
        get_team_store().add_activity(
            {
                "workspace_id": workspace_id,
                "actor_id": actor_id or (ctx or {}).get("user_id"),
                "actor_name": actor_name or (_actor_name(ctx) if ctx else "Cadivor"),
                "action": action,
                "summary": summary,
                "metadata": metadata or {},
            }
        )
    except Exception:  # noqa: BLE001
        return


def _workspace_name(workspace_id: str) -> str:
    store = get_auth_store()
    for row in store.list_workspace_members(workspace_id):
        name = str(row.get("workspace_name") or "").strip()
        if name:
            return name
    record = get_team_store().get_workspace(workspace_id) or {}
    return str(record.get("name") or "Cadivor Workspace")


# --------------------------------------------------------------------------
# Invitations
# --------------------------------------------------------------------------

def invite_status(row: dict[str, Any], now: datetime | None = None) -> str:
    status = str(row.get("status") or "pending")
    if status == "pending":
        expires = _parse_dt(row.get("expires_at"))
        if expires is not None and expires <= (now or _now()):
            return "expired"
    return status


def public_invite(row: dict[str, Any]) -> dict[str, Any]:
    """Safe invitation view — never includes the token hash."""
    return {
        "id": row.get("id"),
        "email": row.get("email"),
        "role": row.get("role"),
        "status": invite_status(row),
        "invited_by_name": row.get("invited_by_name"),
        "created_at": row.get("created_at"),
        "expires_at": row.get("expires_at"),
        "accepted_at": row.get("accepted_at"),
        "last_sent_at": row.get("last_sent_at"),
        "send_count": int(row.get("send_count") or 0),
    }


def invite_link(web_origin: str, token: str) -> str:
    return f"{web_origin.rstrip('/')}/login?invite={token}"


def _expiry_days(value: Any) -> int:
    if value in (None, ""):
        return INVITE_DEFAULT_DAYS
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise TeamError("Invitation expiry must be a whole number of days.", 400) from exc
    if days < 1 or days > INVITE_MAX_DAYS:
        raise TeamError(
            f"Invitation expiry must be between 1 and {INVITE_MAX_DAYS} days.", 400
        )
    return days


def _seat_limit_reached(ctx: dict[str, Any]) -> tuple[bool, int | None]:
    from apps.api.plan_limits import effective_plan_name
    from src.plans import get_plan

    plan = get_plan(effective_plan_name(ctx))
    included = plan.get("included_users")
    if included is None:
        return False, None
    members = [
        row
        for row in get_auth_store().list_workspace_members(ctx["workspace_id"])
        if row.get("status") == "active"
    ]
    pending = [
        row
        for row in get_team_store().list_invites(ctx["workspace_id"])
        if invite_status(row) == "pending"
    ]
    return len(members) + len(pending) >= int(included), int(included)


def create_invitation(
    ctx: dict[str, Any],
    *,
    email: str,
    role: str,
    expires_in_days: Any = None,
    web_origin: str,
) -> dict[str, Any]:
    actor_role = require_admin(ctx)
    role_n = str(role or "").strip().lower()
    if role_n not in ASSIGNABLE_ROLES:
        raise TeamError("Choose admin, engineer, or viewer.", 400)
    if role_n == "admin" and actor_role != "owner":
        raise TeamError("Only the workspace owner can invite admins.", 403)
    email_n = normalize_email(email)
    days = _expiry_days(expires_in_days)
    if not invitation_email.delivery_ready():
        raise TeamError(
            "Invitation email is not configured. Set RESEND_API_KEY and "
            "TRANSACTIONAL_FROM_EMAIL before sending workspace invitations.",
            503,
            "email_not_configured",
        )
    if email_n == str(ctx.get("email") or "").strip().lower():
        raise TeamError("You are already a member of this workspace.", 400)

    store = get_auth_store()
    team = get_team_store()
    wid = ctx["workspace_id"]
    for member in store.list_workspace_members(wid):
        if str(member.get("email") or "").lower() == email_n and member.get("status") == "active":
            raise TeamError("That person is already a workspace member.", 409)

    existing = team.find_pending_invite(wid, email_n)
    if existing is not None:
        if invite_status(existing) == "pending":
            raise TeamError(
                "A pending invitation already exists for this email address.", 409
            )
        team.update_invite(
            str(existing["id"]),
            {"status": "expired", "updated_at": _now().isoformat()},
            expect_status="pending",
        )
    at_limit, limit = _seat_limit_reached(ctx)
    if at_limit:
        raise TeamError(
            f"Your plan includes {limit} users. Remove a member or pending invitation, "
            "or upgrade, before inviting another person.",
            402,
            "seat_limit",
        )

    token = new_token()
    now = _now()
    try:
        row = team.create_invite(
            {
                "workspace_id": wid,
                "email": email_n,
                "role": role_n,
                "status": "pending",
                "token_hash": hash_token(token),
                "invited_by": ctx["user_id"],
                "invited_by_name": _actor_name(ctx),
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "expires_at": (now + timedelta(days=days)).isoformat(),
            }
        )
    except ValueError as exc:
        raise TeamError(
            "A pending invitation already exists for this email address.", 409
        ) from exc
    record_activity(
        ctx,
        wid,
        "member.invited",
        f"Invited {email_n} as {role_n}",
        {"email": email_n, "role": role_n, "invitation_id": row["id"]},
    )
    result = _deliver(ctx, row, token, web_origin)
    return {"invitation": public_invite(team.get_invite(str(row["id"])) or row), **result}


def _deliver(
    ctx: dict[str, Any], row: dict[str, Any], token: str, web_origin: str
) -> dict[str, Any]:
    wid = str(row["workspace_id"])
    try:
        invitation_email.send_workspace_invitation(
            to_email=str(row["email"]),
            workspace_name=_workspace_name(wid),
            invited_by_name=_actor_name(ctx),
            role=str(row["role"]),
            invite_url=invite_link(web_origin, token),
        )
    except InvitationEmailError:
        return {
            "email_sent": False,
            "email_delivery": invitation_email.delivery_mode(),
            "warning": (
                "The invitation was saved, but its email could not be sent. "
                "Use Resend after confirming the sender and domain."
            ),
        }
    get_team_store().update_invite(
        str(row["id"]),
        {
            "last_sent_at": _now().isoformat(),
            "send_count": int(row.get("send_count") or 0) + 1,
        },
        expect_status="pending",
    )
    return {"email_sent": True, "email_delivery": invitation_email.delivery_mode()}


def list_invitations(ctx: dict[str, Any]) -> dict[str, Any]:
    """Members may call this; only owners/admins receive pending invite rows."""
    role = require_member(ctx)
    can_manage = role in ADMIN_ROLES
    rows = get_team_store().list_invites(ctx["workspace_id"]) if can_manage else []
    return {
        "invitations": [public_invite(row) for row in rows],
        "can_manage": can_manage,
        "email_delivery": invitation_email.delivery_mode(),
        "email_ready": invitation_email.delivery_ready(),
        "assignable_roles": list(ASSIGNABLE_ROLES) if can_manage else [],
        "default_expiry_days": INVITE_DEFAULT_DAYS,
        "max_expiry_days": INVITE_MAX_DAYS,
    }


def _own_invite(ctx: dict[str, Any], invite_id: str) -> dict[str, Any]:
    row = get_team_store().get_invite(str(invite_id or ""))
    # Same message for "missing" and "other workspace" so ids do not leak.
    if not row or row.get("workspace_id") != ctx["workspace_id"]:
        raise TeamError("Invitation not found.", 404)
    return row


def resend_invitation(
    ctx: dict[str, Any],
    invite_id: str,
    *,
    expires_in_days: Any = None,
    web_origin: str,
) -> dict[str, Any]:
    require_admin(ctx)
    if not invitation_email.delivery_ready():
        raise TeamError(
            "Invitation email is not configured. Set RESEND_API_KEY and "
            "TRANSACTIONAL_FROM_EMAIL before sending workspace invitations.",
            503,
            "email_not_configured",
        )
    row = _own_invite(ctx, invite_id)
    status = invite_status(row)
    if status == "expired":
        raise TeamError(
            "This invitation has expired. Cancel it and create a new invitation.", 409
        )
    if status != "pending":
        raise TeamError(f"This invitation is {status} and cannot be resent.", 409)
    last_sent = _parse_dt(row.get("last_sent_at"))
    if last_sent and (_now() - last_sent).total_seconds() < RESEND_COOLDOWN_SECONDS:
        raise TeamError("Please wait a moment before resending this invitation.", 429)

    # Rotate the token so a forwarded older email stops working; persist the
    # new hash only after the provider accepted the message.
    token = new_token()
    try:
        invitation_email.send_workspace_invitation(
            to_email=str(row["email"]),
            workspace_name=_workspace_name(ctx["workspace_id"]),
            invited_by_name=_actor_name(ctx),
            role=str(row["role"]),
            invite_url=invite_link(web_origin, token),
        )
    except InvitationEmailError as exc:
        raise TeamError(
            "Invitation email could not be sent. Check the email configuration and try again.",
            502,
            "email_failed",
        ) from exc
    fields: dict[str, Any] = {
        "token_hash": hash_token(token),
        "last_sent_at": _now().isoformat(),
        "send_count": int(row.get("send_count") or 0) + 1,
        "updated_at": _now().isoformat(),
    }
    if expires_in_days not in (None, ""):
        fields["expires_at"] = (_now() + timedelta(days=_expiry_days(expires_in_days))).isoformat()
    updated = get_team_store().update_invite(str(row["id"]), fields, expect_status="pending")
    if updated is None:
        raise TeamError("This invitation is no longer pending.", 409)
    record_activity(
        ctx,
        ctx["workspace_id"],
        "member.invite_resent",
        f"Resent invitation for {row['email']}",
        {"email": row["email"], "invitation_id": row["id"]},
    )
    return {"invitation": public_invite(updated), "email_sent": True,
            "email_delivery": invitation_email.delivery_mode()}


def cancel_invitation(ctx: dict[str, Any], invite_id: str) -> dict[str, Any]:
    require_admin(ctx)
    row = _own_invite(ctx, invite_id)
    updated = get_team_store().update_invite(
        str(row["id"]),
        {"status": "cancelled", "updated_at": _now().isoformat()},
        expect_status="pending",
    )
    if updated is None:
        raise TeamError(
            f"This invitation is {invite_status(row)} and cannot be cancelled.", 409
        )
    record_activity(
        ctx,
        ctx["workspace_id"],
        "member.invite_cancelled",
        f"Cancelled invitation for {row['email']}",
        {"email": row["email"], "invitation_id": row["id"]},
    )
    return {"invitation": public_invite(updated)}


def lookup_invitation(token: str) -> dict[str, Any] | None:
    """Public, token-gated view used to pre-fill the account-creation form."""
    row = valid_invitation_for_token(token)
    if row is None:
        return None
    return {
        "email": row["email"],
        "role": row["role"],
        "workspace_name": _workspace_name(str(row["workspace_id"])),
        "invited_by_name": row.get("invited_by_name"),
        "expires_at": row.get("expires_at"),
    }


def valid_invitation_for_token(token: str) -> dict[str, Any] | None:
    value = str(token or "").strip()
    if len(value) < 20 or len(value) > 256:
        return None
    row = get_team_store().find_invite_by_token_hash(hash_token(value))
    if row is None or invite_status(row) != "pending":
        return None
    return row


def invite_id_for_token(token: str) -> str | None:
    """Resolve a raw token to an invitation id (any status) without exposing it."""
    value = str(token or "").strip()
    if len(value) < 20 or len(value) > 256:
        return None
    row = get_team_store().find_invite_by_token_hash(hash_token(value))
    return str(row["id"]) if row else None


def accept_pending_invitations(
    *,
    user_id: str,
    email: str,
    prefer_invite_id: str | None = None,
) -> list[dict[str, Any]]:
    """Accept every unexpired pending invitation addressed to ``email``.

    Callers MUST have verified that ``email`` belongs to the authenticated,
    email-verified ``user_id`` (Supabase Auth ``get_user`` + confirmed email).
    Workspace and role come from the stored invitation only. The write is
    idempotent: membership is an upsert and the invite flips to ``accepted``
    with a compare-and-set, so concurrent logins cannot double-apply it.
    """
    email_n = str(email or "").strip().lower()
    if not user_id or not email_n:
        raise TeamError("Authentication with an email address is required.", 401)
    team = get_team_store()
    store = get_auth_store()
    pending = team.list_pending_for_email(email_n)
    accepted: list[dict[str, Any]] = []
    now = _now()
    for row in pending:
        if invite_status(row, now) != "pending":
            team.update_invite(
                str(row["id"]),
                {"status": "expired", "updated_at": now.isoformat()},
                expect_status="pending",
            )
            continue
        existing_user = store.find_user_by_email(email_n)
        if not existing_user or str(existing_user.get("id")) != user_id:
            store.link_supabase_user(user_id=user_id, email=email_n)
        role = str(row.get("role") or "").lower()
        if role not in ASSIGNABLE_ROLES:
            role = "viewer"
        workspace_id = str(row["workspace_id"])
        workspace_name = _workspace_name(workspace_id)
        store.add_membership(
            user_id=user_id,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            role=role,
            keep_existing_role=True,
        )
        marked = team.update_invite(
            str(row["id"]),
            {
                "status": "accepted",
                "accepted_at": now.isoformat(),
                "accepted_by": user_id,
                "updated_at": now.isoformat(),
            },
            expect_status="pending",
        )
        if marked is None:
            continue
        member = store.membership_for_user_workspace(user_id, workspace_id) or {}
        record_activity(
            None,
            workspace_id,
            "member.joined",
            f"{email_n} accepted the invitation",
            {"email": email_n, "role": member.get("role") or role},
            actor_id=user_id,
            actor_name=_display_name(user_id, email_n),
        )
        accepted.append(
            {
                "invitation_id": str(row["id"]),
                "workspace_id": workspace_id,
                "workspace_name": workspace_name,
                "role": str(member.get("role") or role),
            }
        )
    if prefer_invite_id:
        preferred = next(
            (item for item in accepted if item["invitation_id"] == prefer_invite_id), None
        )
        if preferred:
            store.set_active_workspace(user_id, preferred["workspace_id"])
    return accepted


def register_from_invitation_sandbox(token: str, email: str, password: str) -> dict[str, Any]:
    """Sandbox/local only: create a password account for an invited address.

    Possession of the emailed single-use token proves control of the mailbox, so
    the account is usable immediately. Production uses Supabase Auth instead
    (``supabase_auth.signup_for_invitation``) where email confirmation is
    enforced by Supabase and re-checked on every request. The email must equal
    the stored invitation email; workspace and role are never taken from the
    caller.
    """
    invite = valid_invitation_for_token(token)
    if invite is None:
        raise TeamError("This invitation is not valid or has expired.", 404)
    if normalize_email(email) != str(invite["email"]).lower():
        raise TeamError("Use the email address this invitation was sent to.", 400)
    if len(password or "") < 12:
        raise TeamError("Use a password with at least 12 characters.", 400)
    store = get_auth_store()
    try:
        user_id = store.register_password_user(email=str(invite["email"]), password=password)
    except ValueError as exc:
        raise TeamError(
            "An account already exists for this email. Sign in to accept the invitation.",
            409,
        ) from exc
    accepted = accept_pending_invitations(
        user_id=user_id,
        email=str(invite["email"]),
        prefer_invite_id=str(invite["id"]),
    )
    return {"email": str(invite["email"]), "user_id": user_id, "accepted": accepted}


# --------------------------------------------------------------------------
# Workspaces and members
# --------------------------------------------------------------------------

def workspace_snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
    role = require_member(ctx)
    wid = ctx["workspace_id"]
    record = get_team_store().get_workspace(wid) or {}
    members = get_auth_store().list_workspace_members(wid)
    owner_row = next((m for m in members if m.get("role") == "owner"), None)
    profiles = get_team_store().get_profiles([str(m["user_id"]) for m in members])
    return {
        "workspace_id": wid,
        "name": ctx.get("workspace") or record.get("name") or "Cadivor Workspace",
        "timezone": record.get("timezone") or "UTC",
        "unit_system": record.get("unit_system") or "metric",
        "created_at": record.get("created_at"),
        "owner": (
            {
                "user_id": owner_row["user_id"],
                "email": owner_row.get("email"),
                "display_name": _display_name(
                    str(owner_row["user_id"]), str(owner_row.get("email") or ""), profiles
                ),
            }
            if owner_row
            else None
        ),
        "current_role": role,
        "can_administer": role in ADMIN_ROLES,
        "member_count": sum(1 for m in members if m.get("status") == "active"),
    }


def update_workspace_settings(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    require_admin(ctx)
    wid = ctx["workspace_id"]
    fields: dict[str, Any] = {}
    if "name" in payload:
        name = _clean_text(payload.get("name"), "Workspace name", max_len=80, required=True)
        if len(name) < 2:
            raise TeamError("Workspace name must be at least 2 characters.", 400)
        fields["name"] = name
    if "timezone" in payload:
        tz = str(payload.get("timezone") or "").strip()
        if not valid_timezone(tz):
            raise TeamError("Choose a valid IANA time zone, for example America/New_York.", 400)
        fields["timezone"] = tz
    if "unit_system" in payload:
        units = str(payload.get("unit_system") or "").strip().lower()
        if units not in UNIT_OPTIONS:
            raise TeamError("Units must be metric or imperial.", 400)
        fields["unit_system"] = units
    if not fields:
        raise TeamError("No workspace settings were provided.", 400)
    get_team_store().upsert_workspace(wid, fields)
    if "name" in fields:
        get_auth_store().rename_workspace(wid, fields["name"])
    record_activity(ctx, wid, "workspace.updated", "Updated workspace settings", fields)
    # ctx still carries the old name for this request; reflect the new one.
    return workspace_snapshot({**ctx, "workspace": fields.get("name", ctx.get("workspace"))})


def _can_create_workspace(ctx: dict[str, Any]) -> tuple[bool, str]:
    from apps.api.plan_limits import effective_plan_name
    from src.plans import get_plan

    plan_name = effective_plan_name(ctx)
    plan = get_plan(plan_name)
    if not plan.get("team_features"):
        return False, (
            f"The {plan_name} plan is for individual use. Upgrade to a team plan "
            "to create additional workspaces."
        )
    owned = sum(
        1
        for row in get_auth_store().list_memberships(ctx["user_id"])
        if row.get("role") == "owner"
    )
    if owned >= MAX_OWNED_WORKSPACES:
        return False, f"You can own up to {MAX_OWNED_WORKSPACES} workspaces."
    return True, ""


def list_workspaces(ctx: dict[str, Any]) -> dict[str, Any]:
    team = get_team_store()
    rows = get_auth_store().list_memberships(ctx["user_id"])
    items = []
    for row in rows:
        wid = str(row["workspace_id"])
        record = team.get_workspace(wid) or {}
        items.append(
            {
                "workspace_id": wid,
                "name": row.get("workspace_name") or record.get("name") or wid,
                "role": row.get("role"),
                "active": wid == ctx["workspace_id"],
                "timezone": record.get("timezone") or "UTC",
                "unit_system": record.get("unit_system") or "metric",
            }
        )
    can_create, reason = _can_create_workspace(ctx)
    return {
        "workspaces": items,
        "active_workspace_id": ctx["workspace_id"],
        "can_create": can_create,
        "create_blocked_reason": reason or None,
    }


def create_workspace(ctx: dict[str, Any], name: str) -> dict[str, Any]:
    can_create, reason = _can_create_workspace(ctx)
    if not can_create:
        raise TeamError(reason, 402, "plan_does_not_allow_workspaces")
    clean = _clean_text(name, "Workspace name", max_len=80, required=True)
    if len(clean) < 2:
        raise TeamError("Enter a workspace name with at least 2 characters.", 400)
    store = get_auth_store()
    wid = f"ws-next-{secrets.token_hex(8)}"
    store.add_membership(
        user_id=ctx["user_id"],
        workspace_id=wid,
        workspace_name=clean,
        role="owner",
        keep_existing_role=False,
    )
    get_team_store().upsert_workspace(
        wid,
        {"name": clean, "owner_id": ctx["user_id"], "timezone": "UTC", "unit_system": "metric"},
    )
    store.set_active_workspace(ctx["user_id"], wid)
    record_activity(
        ctx, wid, "workspace.created", f"Created workspace {clean}", {"workspace_name": clean}
    )
    return {"workspace_id": wid, "name": clean, "role": "owner", "active": True}


def switch_workspace(ctx: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    """Select one of the caller's own memberships; the server validates it."""
    wid = str(workspace_id or "").strip()
    member = get_auth_store().membership_for_user_workspace(ctx["user_id"], wid) if wid else None
    if not member or not get_auth_store().set_active_workspace(ctx["user_id"], wid):
        raise TeamError("Workspace not found.", 404)
    return {
        "workspace_id": wid,
        "name": member.get("workspace_name"),
        "role": member.get("role"),
        "active": True,
    }


def list_members(ctx: dict[str, Any]) -> dict[str, Any]:
    role = require_member(ctx)
    members = [
        m
        for m in get_auth_store().list_workspace_members(ctx["workspace_id"])
        if m.get("status") == "active"
    ]
    profiles = get_team_store().get_profiles([str(m["user_id"]) for m in members])
    rows = [
        {
            "user_id": m["user_id"],
            "email": m.get("email"),
            "display_name": _display_name(str(m["user_id"]), str(m.get("email") or ""), profiles),
            "role": m.get("role"),
            "status": "active",
            "joined_at": m.get("joined_at") or m.get("created_at"),
            "is_you": str(m["user_id"]) == ctx["user_id"],
        }
        for m in members
    ]
    order = {name: i for i, name in enumerate(("owner", "admin", "engineer", "viewer"))}
    rows.sort(key=lambda r: (order.get(str(r["role"]), 9), str(r["email"] or "")))
    return {
        "members": rows,
        "current_role": role,
        "can_change_roles": role == "owner",
        "can_remove": role in ADMIN_ROLES,
        "assignable_roles": list(ASSIGNABLE_ROLES),
    }


def update_member_role(ctx: dict[str, Any], user_id: str, role: str) -> dict[str, Any]:
    actor = require_member(ctx)
    if actor != "owner":
        raise TeamError("Only the workspace owner can change member roles.", 403)
    role_n = str(role or "").strip().lower()
    if role_n not in ASSIGNABLE_ROLES:
        raise TeamError("Choose admin, engineer, or viewer.", 400)
    store = get_auth_store()
    target = store.membership_for_user_workspace(str(user_id), ctx["workspace_id"])
    if not target:
        raise TeamError("Member not found.", 404)
    if target.get("role") == "owner":
        raise TeamError("The owner's role cannot be changed.", 400)
    store.set_membership_role(ctx["workspace_id"], str(user_id), role_n)
    email = next(
        (
            m.get("email")
            for m in store.list_workspace_members(ctx["workspace_id"])
            if str(m["user_id"]) == str(user_id)
        ),
        "",
    )
    record_activity(
        ctx,
        ctx["workspace_id"],
        "member.role_changed",
        f"Changed {email} to {role_n}",
        {"email": email, "role": role_n},
    )
    return {"user_id": str(user_id), "role": role_n}


def remove_member(ctx: dict[str, Any], user_id: str) -> dict[str, Any]:
    actor = require_admin(ctx)
    target_id = str(user_id)
    if target_id == ctx["user_id"]:
        raise TeamError("You cannot remove yourself from the workspace.", 400)
    store = get_auth_store()
    target = store.membership_for_user_workspace(target_id, ctx["workspace_id"])
    if not target:
        raise TeamError("Member not found.", 404)
    if target.get("role") == "owner":
        raise TeamError("The workspace owner cannot be removed.", 400)
    if target.get("role") == "admin" and actor != "owner":
        raise TeamError("Only the workspace owner can remove admins.", 403)
    email = next(
        (
            m.get("email")
            for m in store.list_workspace_members(ctx["workspace_id"])
            if str(m["user_id"]) == target_id
        ),
        "",
    )
    store.set_membership_status(ctx["workspace_id"], target_id, "removed")
    record_activity(
        ctx,
        ctx["workspace_id"],
        "member.removed",
        f"Removed {email} from the workspace",
        {"email": email},
    )
    return {"user_id": target_id, "removed": True}


def list_activity(ctx: dict[str, Any], limit: int = 50) -> dict[str, Any]:
    role = require_member(ctx)
    rows = get_team_store().list_activity(ctx["workspace_id"], limit=min(max(limit, 1), 200))
    items = [
        {
            "id": row.get("id"),
            "actor_name": row.get("actor_name"),
            "action": row.get("action"),
            "summary": row.get("summary"),
            "created_at": row.get("created_at"),
            # Audit metadata (emails, ids) is for owners/admins only.
            **({"metadata": row.get("metadata") or {}} if role in ADMIN_ROLES else {}),
        }
        for row in rows
    ]
    return {"activity": items, "audit_detail": role in ADMIN_ROLES}


# --------------------------------------------------------------------------
# Profile and preferences (per user, persisted in the migration database)
# --------------------------------------------------------------------------

def get_profile(ctx: dict[str, Any]) -> dict[str, Any]:
    row = get_team_store().get_profile(ctx["user_id"])
    stored = row or {}
    return {
        "email": ctx["email"],
        "email_managed_by_auth": True,
        "full_name": stored.get("full_name") or "",
        "company_name": stored.get("company_name") or "",
        "job_title": stored.get("job_title") or "",
        "country": stored.get("country") or "",
        "language": stored.get("language") or "en",
        "timezone": stored.get("timezone") or "UTC",
        "persisted": row is not None,
        "updated_at": stored.get("updated_at"),
    }


def update_profile(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if "email" in payload and str(payload.get("email") or "").strip().lower() != ctx["email"]:
        raise TeamError("Email is managed by sign-in and cannot be edited here.", 400)
    fields: dict[str, Any] = {}
    if "full_name" in payload:
        fields["full_name"] = _clean_text(payload.get("full_name"), "Full name")
    if "company_name" in payload:
        fields["company_name"] = _clean_text(payload.get("company_name"), "Organization")
    if "job_title" in payload:
        fields["job_title"] = _clean_text(payload.get("job_title"), "Role or job title")
    if "country" in payload:
        fields["country"] = _clean_text(payload.get("country"), "Location", max_len=80)
    if "language" in payload:
        language = str(payload.get("language") or "").strip()
        if not _LANGUAGE_RE.fullmatch(language):
            raise TeamError("Choose a valid language.", 400)
        fields["language"] = language
    if "timezone" in payload:
        tz = str(payload.get("timezone") or "").strip()
        if not valid_timezone(tz):
            raise TeamError("Choose a valid IANA time zone, for example America/New_York.", 400)
        fields["timezone"] = tz
    if not fields:
        raise TeamError("No profile fields were provided.", 400)
    get_team_store().upsert_profile(ctx["user_id"], fields)
    return get_profile(ctx)


def _notification_defaults_from(row: dict[str, Any] | None) -> dict[str, bool]:
    from src.customer_profile_service import notification_preferences_from_record

    return notification_preferences_from_record(row)


def get_preferences(ctx: dict[str, Any]) -> dict[str, Any]:
    row = get_team_store().get_preferences(ctx["user_id"])
    stored = row or {}
    profile = get_profile(ctx)
    monitoring = stored.get("monitoring_notifications")
    return {
        "appearance": stored.get("appearance") or PREFERENCE_DEFAULTS["appearance"],
        "density": stored.get("density") or PREFERENCE_DEFAULTS["density"],
        "default_units": stored.get("default_units") or PREFERENCE_DEFAULTS["default_units"],
        "default_currency": stored.get("default_currency")
        or PREFERENCE_DEFAULTS["default_currency"],
        "monitoring_notifications": (
            PREFERENCE_DEFAULTS["monitoring_notifications"]
            if monitoring is None
            else bool(monitoring)
        ),
        "notification_preferences": _notification_defaults_from(stored),
        # Time zone is a single per-user setting shared with the profile.
        "timezone": profile["timezone"],
        "persisted": row is not None,
        "updated_at": stored.get("updated_at"),
        "options": {
            "appearance": list(APPEARANCE_OPTIONS),
            "density": list(DENSITY_OPTIONS),
            "default_units": list(UNIT_OPTIONS),
            "default_currency": list(CURRENCY_OPTIONS),
        },
    }


def update_preferences(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    from src.customer_profile_service import _NOTIFICATION_PREFERENCE_DEFAULTS

    fields: dict[str, Any] = {}
    choices = {
        "appearance": APPEARANCE_OPTIONS,
        "density": DENSITY_OPTIONS,
        "default_units": UNIT_OPTIONS,
    }
    for key, allowed in choices.items():
        if key in payload:
            value = str(payload.get(key) or "").strip().lower()
            if value not in allowed:
                raise TeamError(f"Unsupported {key.replace('_', ' ')}.", 400)
            fields[key] = value
    if "default_currency" in payload:
        currency = str(payload.get("default_currency") or "").strip().upper()
        if currency not in CURRENCY_OPTIONS:
            raise TeamError("Unsupported currency.", 400)
        fields["default_currency"] = currency
    if "monitoring_notifications" in payload:
        if not isinstance(payload["monitoring_notifications"], bool):
            raise TeamError("monitoring_notifications must be true or false.", 400)
        fields["monitoring_notifications"] = payload["monitoring_notifications"]
    if "notification_preferences" in payload:
        incoming = payload["notification_preferences"]
        if not isinstance(incoming, dict):
            raise TeamError("notification_preferences must be an object.", 400)
        unknown = set(incoming) - set(_NOTIFICATION_PREFERENCE_DEFAULTS)
        if unknown:
            raise TeamError("Unknown notification preference.", 400)
        current = _notification_defaults_from(get_team_store().get_preferences(ctx["user_id"]))
        for key, value in incoming.items():
            if not isinstance(value, bool):
                raise TeamError(f"{key} must be true or false.", 400)
            current[key] = value
        fields["notification_preferences"] = current
    tz_value: str | None = None
    if "timezone" in payload:
        tz_value = str(payload.get("timezone") or "").strip()
        if not valid_timezone(tz_value):
            raise TeamError("Choose a valid IANA time zone, for example America/New_York.", 400)
    if not fields and tz_value is None:
        raise TeamError("No preferences were provided.", 400)
    if fields:
        get_team_store().upsert_preferences(ctx["user_id"], fields)
    if tz_value is not None:
        get_team_store().upsert_profile(ctx["user_id"], {"timezone": tz_value})
    return get_preferences(ctx)
