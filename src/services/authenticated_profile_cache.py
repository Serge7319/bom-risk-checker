"""Session-scoped continuity cache for a verified Cadivor user profile."""
from __future__ import annotations

import time
from typing import Any, Mapping, MutableMapping


PROFILE_CACHE_KEY = "cadivor_verified_profile"
PROFILE_CACHE_MAX_AGE_SECONDS = 120


def remember_verified_profile(
    session_state: MutableMapping[str, Any],
    profile: Mapping[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Store only a complete, identity-bound profile for transient-read recovery."""
    profile_id = str(profile.get("id") or "").strip()
    if not profile_id:
        return None
    cached = dict(profile)
    session_state[PROFILE_CACHE_KEY] = {
        "user_id": profile_id,
        "profile": cached,
        "verified_at": time.time() if now is None else now,
    }
    return cached


def recent_verified_profile(
    session_state: Mapping[str, Any],
    user_id: Any,
    *,
    now: float | None = None,
    max_age_seconds: float = PROFILE_CACHE_MAX_AGE_SECONDS,
) -> dict[str, Any] | None:
    """Return a brief fallback only for the same authenticated user."""
    entry = session_state.get(PROFILE_CACHE_KEY)
    expected_id = str(user_id or "").strip()
    if not isinstance(entry, Mapping) or not expected_id:
        return None
    profile = entry.get("profile")
    verified_user_id = str(entry.get("user_id") or "").strip()
    verified_at = entry.get("verified_at")
    if (
        not isinstance(profile, Mapping)
        or verified_user_id != expected_id
        or str(profile.get("id") or "").strip() != expected_id
    ):
        return None
    try:
        age = (time.time() if now is None else now) - float(verified_at)
    except (TypeError, ValueError):
        return None
    if age < 0 or age > max_age_seconds:
        return None
    return dict(profile)
