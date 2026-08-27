"""Idempotent Cadivor user-profile provisioning for authenticated Supabase users."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from typing import Any

from src.supabase_read import SupabaseReadTransportError, execute_supabase_read

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


def build_default_user_row(auth_user: Any) -> dict[str, Any]:
    """Return the smallest safe default row derived from Supabase auth metadata."""
    user_id = _safe_text(getattr(auth_user, "id", ""))
    if not user_id:
        raise UserProvisioningError("Authenticated user id is required for provisioning.")

    email = _safe_text(getattr(auth_user, "email", ""))
    metadata = getattr(auth_user, "user_metadata", {}) or {}
    trial_ends_at = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)

    return {
        "id": user_id,
        "email": email,
        "plan": "Trial",
        "trial_ends_at": trial_ends_at.isoformat(),
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
        return existing.data[0], False

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
            return retry.data[0], False
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
