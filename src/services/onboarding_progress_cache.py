"""Short-lived, account-scoped cache for onboarding progress."""
from __future__ import annotations

import time
from typing import Any, Mapping, MutableMapping


ONBOARDING_PROGRESS_CACHE_KEY = "cadivor_onboarding_progress_cache"
ONBOARDING_PROGRESS_CACHE_MAX_AGE_SECONDS = 120


def remember_onboarding_progress(
    session_state: MutableMapping[str, Any],
    user_id: Any,
    progress: Mapping[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Cache a successful progress read/update for this signed-in user."""
    uid = str(user_id or "").strip()
    if not uid or not isinstance(progress, Mapping):
        return None
    cached = dict(progress)
    session_state[ONBOARDING_PROGRESS_CACHE_KEY] = {
        "user_id": uid,
        "progress": cached,
        "verified_at": time.time() if now is None else float(now),
    }
    return cached


def recent_onboarding_progress(
    session_state: Mapping[str, Any],
    user_id: Any,
    *,
    now: float | None = None,
    max_age_seconds: float = ONBOARDING_PROGRESS_CACHE_MAX_AGE_SECONDS,
) -> dict[str, Any] | None:
    """Return recent progress only when it belongs to the current account."""
    entry = session_state.get(ONBOARDING_PROGRESS_CACHE_KEY)
    uid = str(user_id or "").strip()
    if not uid or not isinstance(entry, Mapping):
        return None
    if str(entry.get("user_id") or "").strip() != uid:
        return None
    progress = entry.get("progress")
    if not isinstance(progress, Mapping):
        return None
    try:
        age = (time.time() if now is None else float(now)) - float(entry.get("verified_at"))
    except (TypeError, ValueError):
        return None
    if age < 0 or age > max_age_seconds:
        return None
    return dict(progress)
