"""Thread-safe bounded profile read used while the authenticated route opens."""
from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from typing import Any


def _user_id(user: Any) -> str:
    if isinstance(user, Mapping):
        return str(user.get("id") or "").strip()
    return str(getattr(user, "id", "") or "").strip()


def load_profile_for_opening(
    *,
    session_state: MutableMapping[str, Any],
    user: Any,
    access_token_fresh: bool,
    supabase: Any,
    read_profile: Callable[[str], Any],
    ensure_profile: Callable[[Any, Any], Any],
    recent_profile: Callable[[Any, str], dict[str, Any] | None],
    remember_profile: Callable[[Any, Mapping[str, Any]], dict[str, Any] | None],
    run_with_budget: Callable[..., tuple[Any, str]],
) -> tuple[dict[str, Any] | None, str]:
    """Read and cache the profile without exposing Streamlit state to a worker.

    The caller owns auth refresh and retry UI on the script thread. This helper
    is only for a fresh token, so the detached work can safely perform a profile
    SELECT (or first-login provisioning) without touching Streamlit APIs.
    """
    user_id = _user_id(user)
    if not user_id:
        return None, "error"
    if not access_token_fresh:
        return None, "refresh_required"

    cached = recent_profile(session_state, user_id)
    if cached:
        return cached, "ok"

    def _read() -> dict[str, Any] | None:
        response = read_profile(user_id)
        rows = getattr(response, "data", None)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows[0]
        ensured = ensure_profile(supabase, user)
        if isinstance(ensured, tuple):
            profile = ensured[0]
        else:
            profile = ensured
        return profile if isinstance(profile, dict) else None

    profile, status = run_with_budget(_read)
    if status != "ok" or not isinstance(profile, dict) or not profile.get("id"):
        return None, status if status != "ok" else "error"
    remembered = remember_profile(session_state, profile)
    return remembered or profile, "ok"
