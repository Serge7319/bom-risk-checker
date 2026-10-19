"""Idempotent Cadivor user-profile provisioning for authenticated Supabase users."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from typing import Any

from src.supabase_read import SupabaseReadTransportError, execute_supabase_read
from src.signup_intent import is_report_only_signup

TRIAL_DAYS = 14
# A newly authenticated user can briefly authenticate before their profile is
# visible through the public API. Keep this bounded so the normal profile path
# remains immediate while a first sign-in recovers without an error screen.
PROFILE_VISIBILITY_RETRY_DELAYS_SECONDS = (0.20, 0.40, 0.80, 1.00, 1.00, 1.00)


class UserProvisioningError(Exception):
    """Raised when Cadivor cannot create or load the required users row."""


def _safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _recent_default_trial_profile(auth_user: Any, profile: dict[str, Any]) -> bool:
    """Identify only a fresh Auth account with the legacy trigger's Starter row.

    Some deployments create ``public.users`` at Auth signup with plan=Starter.
    That row wins the insert race in ``ensure_user_profile`` and previously
    bypassed the normal Trial default. Repair is limited to a new account's
    first 14 days and an otherwise untouched, unbilled profile.
    """
    metadata = getattr(auth_user, "user_metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    signup_intent = str(metadata.get("cadivor_signup_intent") or "").strip().lower()
    if is_report_only_signup(metadata) or signup_intent not in {"", "standard_trial"}:
        return False

    if str(profile.get("plan") or "").strip().lower() != "starter":
        return False
    if profile.get("trial_ends_at") not in (None, ""):
        return False
    if str(profile.get("role") or "").strip().lower() == "admin":
        return False

    # Never reclassify a paid, previously subscribed, or grandfathered profile.
    protected_billing_fields = (
        "stripe_customer_id",
        "stripe_subscription_id",
        "stripe_price_id",
        "stripe_subscription_status",
        "plan_grandfather_source",
    )
    if any(str(profile.get(key) or "").strip() for key in protected_billing_fields):
        return False

    created_at = _parse_timestamp(getattr(auth_user, "created_at", None))
    if created_at is None:
        return False
    now = datetime.now(timezone.utc)
    trial_end = created_at + timedelta(days=TRIAL_DAYS)
    age = now - created_at
    return timedelta(0) <= age < timedelta(days=TRIAL_DAYS) and trial_end > now


def _repair_recent_default_trial_profile(
    supabase: Any,
    auth_user: Any,
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Promote a fresh trigger-created Starter row to its signup Trial once."""
    if not _recent_default_trial_profile(auth_user, profile):
        return profile

    created_at = _parse_timestamp(getattr(auth_user, "created_at", None))
    if created_at is None:
        return profile
    trial_end = (created_at + timedelta(days=TRIAL_DAYS)).isoformat()
    payload = {"plan": "Trial", "trial_ends_at": trial_end}

    try:
        query = (
            supabase.table("users")
            .update(payload)
            .eq("id", profile.get("id"))
            .eq("plan", profile.get("plan"))
        )
        # These conditional filters make the repair safe if billing changes
        # between the initial read and the update. Only filter columns present
        # in this schema/profile so older deployments remain compatible.
        for field in (
            "trial_ends_at",
            "stripe_customer_id",
            "stripe_subscription_id",
            "stripe_price_id",
            "stripe_subscription_status",
            "plan_grandfather_source",
        ):
            if field in profile and profile.get(field) in (None, ""):
                query = query.is_(field, "null") if profile.get(field) is None else query.eq(field, "")
        response = query.select("*").execute()
        updated = getattr(response, "data", None)
        if isinstance(updated, list) and updated and isinstance(updated[0], dict):
            return updated[0]
    except Exception:
        # Profile recovery must not prevent a valid Auth session from opening.
        return profile

    # PostgREST may return no representation if the update was rejected by a
    # concurrent change or RLS. Re-read so callers never assume a Trial that
    # was not persisted.
    try:
        refreshed = _select_user_profile(
            supabase,
            _safe_text(profile.get("id")),
            operation="ensure_user_profile_after_trial_repair",
        )
        if refreshed.data:
            return refreshed.data[0]
    except SupabaseReadTransportError:
        pass
    return profile


def build_default_user_row(auth_user: Any) -> dict[str, Any]:
    """Return the smallest safe default row derived from Supabase auth metadata."""
    user_id = _safe_text(getattr(auth_user, "id", ""))
    if not user_id:
        raise UserProvisioningError("Authenticated user id is required for provisioning.")

    email = _safe_text(getattr(auth_user, "email", ""))
    metadata = getattr(auth_user, "user_metadata", {}) or {}
    report_only = is_report_only_signup(metadata)
    now = datetime.now(timezone.utc)
    # Preserve compatibility with schemas that require trial_ends_at to be
    # populated. The inactive plan means this timestamp never grants a trial.
    trial_ends_at = (
        (now - timedelta(seconds=1)).isoformat()
        if report_only
        else (now + timedelta(days=TRIAL_DAYS)).isoformat()
    )

    return {
        "id": user_id,
        "email": email,
        "plan": "Subscription inactive" if report_only else "Trial",
        "trial_ends_at": trial_ends_at,
        "monthly_upload_count": 0,
        "full_name": _safe_text(metadata.get("full_name"), _safe_text(metadata.get("name"), "")),
        "company_name": _safe_text(metadata.get("company_name"), _safe_text(metadata.get("company"), "")),
    }


def _select_user_profile(supabase: Any, user_id: str, *, operation: str):
    return execute_supabase_read(
        supabase.table("users").select("*").eq("id", user_id),
        operation=operation,
    )


def _retry_select_user_profile(
    supabase: Any,
    user_id: str,
    *,
    operation: str,
    attempts: int = len(PROFILE_VISIBILITY_RETRY_DELAYS_SECONDS) + 1,
):
    """Allow a just-created profile time to become readable.

    Supabase Auth triggers and a browser's first authenticated request can race.
    This is intentionally limited to the post-create path, so ordinary page
    loads do not wait and no profile data is ever overwritten.
    """
    response = None
    for attempt in range(attempts):
        response = _select_user_profile(
            supabase,
            user_id,
            operation=f"{operation}_attempt_{attempt + 1}",
        )
        if response.data:
            return response
        if attempt < attempts - 1:
            time.sleep(PROFILE_VISIBILITY_RETRY_DELAYS_SECONDS[attempt])
    return response


def ensure_user_profile(
    supabase: Any,
    auth_user: Any,
    *,
    operation: str = "ensure_user_profile",
) -> tuple[dict[str, Any], bool]:
    """Ensure a Cadivor users row exists for the authenticated Supabase user.

    Returns ``(profile_row, created)``. Never overwrites an existing profile.
    """
    session_user_id = _safe_text(getattr(auth_user, "id", ""))
    if not session_user_id:
        raise UserProvisioningError("Authenticated user id is required for provisioning.")

    try:
        existing = _select_user_profile(supabase, session_user_id, operation=operation)
    except SupabaseReadTransportError as exc:
        raise UserProvisioningError("Could not read user profile from Cadivor.") from exc

    if existing.data:
        profile = existing.data[0]
        repaired = _repair_recent_default_trial_profile(supabase, auth_user, profile)
        return repaired, False

    row = build_default_user_row(auth_user)
    if row["id"] != session_user_id:
        raise UserProvisioningError("Provisioning identity mismatch.")

    try:
        insert_response = supabase.table("users").insert(row).execute()
    except Exception as exc:
        # Another login may have created the row concurrently; re-read once.
        try:
            retry = _retry_select_user_profile(
                supabase,
                session_user_id,
                operation=f"{operation}_after_insert_conflict",
            )
        except SupabaseReadTransportError as read_exc:
            raise UserProvisioningError(
                "Cadivor could not create the user profile after a conflict."
            ) from read_exc
        if retry.data:
            profile = retry.data[0]
            repaired = _repair_recent_default_trial_profile(supabase, auth_user, profile)
            return repaired, False
        raise UserProvisioningError("Cadivor could not create the user profile.") from exc

    if insert_response.data:
        return insert_response.data[0], True

    created = _retry_select_user_profile(
        supabase,
        session_user_id,
        operation=f"{operation}_after_insert",
    )
    if created.data:
        return created.data[0], True

    raise UserProvisioningError("Cadivor user profile was not available after provisioning.")
