"""Preference checks shared by scheduled monitoring email delivery."""
from __future__ import annotations

from typing import Any


def monitoring_email_enabled(
    supabase: Any,
    user_id: str,
) -> tuple[bool, str | None]:
    """Return whether a user permits monitoring email.

    A missing preference row retains Cadivor's documented opt-in default. A
    read failure fails closed so a database/configuration issue cannot send
    email against a user's saved preference.
    """
    try:
        response = (
            supabase.table("user_preferences")
            .select("email_notifications,monitoring_notifications")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return True, None
        row = rows[0] if isinstance(rows[0], dict) else {}
        return bool(
            row.get("email_notifications", True)
            and row.get("monitoring_notifications", True)
        ), None
    except Exception as exc:
        return False, str(exc).strip() or exc.__class__.__name__
