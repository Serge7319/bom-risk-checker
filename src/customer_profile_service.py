"""Cadivor customer profile and preference service.

Milestone 11A.1 stores customer-facing profile and preference data outside
the legacy public.users table. This avoids requiring every optional field to
exist in the original account table and provides a stable foundation for
onboarding, branding, security, and organization features.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(response: Any) -> Dict[str, Any]:
    data = getattr(response, "data", None)
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {}
    return {}


def _message(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def migration_missing(exc: Exception) -> bool:
    text = _message(exc).lower()
    signals = (
        "customer_profiles",
        "user_preferences",
        "does not exist",
        "could not find the table",
        "schema cache",
        "relation",
    )
    return any(signal in text for signal in signals)


def ensure_customer_profile(
    supabase: Any,
    user_id: str,
    email: str,
    display_name: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load the customer profile, creating a minimal record when absent."""
    try:
        response = (
            supabase.table("customer_profiles")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        existing = _row(response)
        if existing:
            return existing, None

        payload = {
            "user_id": user_id,
            "email": (email or "").strip().lower(),
            "full_name": (display_name or "").strip(),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        created = _row(
            supabase.table("customer_profiles")
            .insert(payload)
            .execute()
        )
        return created or payload, None
    except Exception as exc:
        if migration_missing(exc):
            return None, "migration_required"
        return None, _message(exc)


def update_customer_profile(
    supabase: Any,
    user_id: str,
    updates: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    allowed_fields = {
        "full_name",
        "company_name",
        "job_title",
        "phone",
        "country",
        "timezone",
        "avatar_url",
        "bio",
    }
    payload = {
        key: value
        for key, value in updates.items()
        if key in allowed_fields
    }
    payload["updated_at"] = _now_iso()

    try:
        response = (
            supabase.table("customer_profiles")
            .update(payload)
            .eq("user_id", user_id)
            .execute()
        )
        updated = _row(response)
        if updated:
            return updated, None

        payload["user_id"] = user_id
        payload["created_at"] = _now_iso()
        created = _row(
            supabase.table("customer_profiles")
            .insert(payload)
            .execute()
        )
        return created or payload, None
    except Exception as exc:
        if migration_missing(exc):
            return None, "migration_required"
        return None, _message(exc)


def ensure_user_preferences(
    supabase: Any,
    user_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        response = (
            supabase.table("user_preferences")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        existing = _row(response)
        if existing:
            return existing, None

        payload = {
            "user_id": user_id,
            "appearance": "system",
            "density": "comfortable",
            "default_units": "metric",
            "default_currency": "USD",
            "email_notifications": True,
            "workspace_notifications": True,
            "monitoring_notifications": True,
            "report_notifications": True,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        created = _row(
            supabase.table("user_preferences")
            .insert(payload)
            .execute()
        )
        return created or payload, None
    except Exception as exc:
        if migration_missing(exc):
            return None, "migration_required"
        return None, _message(exc)


def update_user_preferences(
    supabase: Any,
    user_id: str,
    updates: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    allowed_fields = {
        "appearance",
        "density",
        "default_units",
        "default_currency",
        "email_notifications",
        "workspace_notifications",
        "monitoring_notifications",
        "report_notifications",
    }
    payload = {
        key: value
        for key, value in updates.items()
        if key in allowed_fields
    }
    payload["updated_at"] = _now_iso()

    try:
        response = (
            supabase.table("user_preferences")
            .update(payload)
            .eq("user_id", user_id)
            .execute()
        )
        updated = _row(response)
        if updated:
            return updated, None

        payload["user_id"] = user_id
        payload["created_at"] = _now_iso()
        created = _row(
            supabase.table("user_preferences")
            .insert(payload)
            .execute()
        )
        return created or payload, None
    except Exception as exc:
        if migration_missing(exc):
            return None, "migration_required"
        return None, _message(exc)
