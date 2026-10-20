"""Short session cache for the profile fields used by authenticated chrome."""
from __future__ import annotations

import time
from typing import Any, Mapping, MutableMapping


SHELL_PROFILE_CACHE_KEY = "cadivor_shell_profile_cache"
SHELL_PROFILE_CACHE_TTL_SECONDS = 120


def remember_shell_profile(
    session_state: MutableMapping[str, Any],
    user_id: Any,
    profile: Mapping[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Cache a resolved profile for the same signed-in user only."""
    uid = str(user_id or "").strip()
    if not uid or not isinstance(profile, Mapping):
        return None
    cached = dict(profile)
    session_state[SHELL_PROFILE_CACHE_KEY] = {
        "user_id": uid,
        "profile": cached,
        "cached_at": time.time() if now is None else float(now),
    }
    return cached


def recent_shell_profile(
    session_state: Mapping[str, Any],
    user_id: Any,
    *,
    now: float | None = None,
    max_age_seconds: float = SHELL_PROFILE_CACHE_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Return a fresh profile for this user, never a prior user's chrome."""
    uid = str(user_id or "").strip()
    entry = session_state.get(SHELL_PROFILE_CACHE_KEY)
    if (
        not uid
        or not isinstance(entry, Mapping)
        or str(entry.get("user_id") or "").strip() != uid
    ):
        return None
    profile = entry.get("profile")
    if not isinstance(profile, Mapping):
        return None
    try:
        age = (time.time() if now is None else float(now)) - float(entry.get("cached_at"))
    except (TypeError, ValueError):
        return None
    if age < 0 or age > max(0.0, float(max_age_seconds)):
        return None
    return dict(profile)


def clear_shell_profile_cache(
    session_state: MutableMapping[str, Any],
    user_id: Any = None,
) -> None:
    """Invalidate the shell profile after an explicit profile update/logout."""
    if user_id is None:
        session_state.pop(SHELL_PROFILE_CACHE_KEY, None)
        return
    entry = session_state.get(SHELL_PROFILE_CACHE_KEY)
    if (
        isinstance(entry, Mapping)
        and str(entry.get("user_id") or "").strip() == str(user_id or "").strip()
    ):
        session_state.pop(SHELL_PROFILE_CACHE_KEY, None)
