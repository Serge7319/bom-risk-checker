"""Session-scoped cache for authenticated workspace admit IO.

Warm navigations reuse the admit bundle from first admit instead of re-hitting
ensure/list/preference/count on every route change.
"""
from __future__ import annotations

import time
from typing import Any, Mapping, MutableMapping


WORKSPACE_ADMIT_CACHE_KEY = "cadivor_workspace_admit_cache"
WORKSPACE_ADMIT_CACHE_MAX_AGE_SECONDS = 90


def remember_workspace_admit(
    session_state: MutableMapping[str, Any],
    *,
    user_id: str,
    payload: Mapping[str, Any],
    now: float | None = None,
) -> None:
    uid = str(user_id or "").strip()
    if not uid:
        return
    session_state[WORKSPACE_ADMIT_CACHE_KEY] = {
        "user_id": uid,
        "payload": dict(payload),
        "verified_at": time.time() if now is None else now,
    }


def recent_workspace_admit(
    session_state: Mapping[str, Any],
    user_id: Any,
    *,
    now: float | None = None,
    max_age_seconds: float = WORKSPACE_ADMIT_CACHE_MAX_AGE_SECONDS,
) -> dict[str, Any] | None:
    entry = session_state.get(WORKSPACE_ADMIT_CACHE_KEY)
    expected = str(user_id or "").strip()
    if not isinstance(entry, Mapping) or not expected:
        return None
    if str(entry.get("user_id") or "").strip() != expected:
        return None
    payload = entry.get("payload")
    if not isinstance(payload, Mapping):
        return None
    try:
        age = (time.time() if now is None else now) - float(entry.get("verified_at"))
    except (TypeError, ValueError):
        return None
    if age < 0 or age > max_age_seconds:
        return None
    return dict(payload)


def clear_workspace_admit_cache(session_state: MutableMapping[str, Any]) -> None:
    session_state.pop(WORKSPACE_ADMIT_CACHE_KEY, None)


def warm_workspace_admit_ready(
    session_state: Mapping[str, Any],
    user_id: Any,
) -> bool:
    return recent_workspace_admit(session_state, user_id) is not None
