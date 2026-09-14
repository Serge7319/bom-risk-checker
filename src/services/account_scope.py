"""Drop prior-account workspace state when the authenticated user changes.

A switched sign-in must not inherit the previous user's caches, route, or
pending analysis. Those leftovers can pin Opening Dashboard or replay empty
controls into the next account.
"""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping

SCOPED_USER_KEY = "cadivor_scoped_user_id"
RESOLVED_PLAN_KEY = "cadivor_resolved_plan_name"
PROFILE_UNRESOLVED_KEY = "cadivor_profile_unresolved"

_EXACT_KEYS = (
    "cadivor_shell_cache",
    "cadivor_workspace_admit_cache",
    "cadivor_verified_profile",
    "cadivor_verified_users_role",
    "cadivor_home_saved_analyses",
    "cadivor_workspace_command_cache",
    "cadivor_secondary_data_delayed",
    "cadivor_home_secondary_cache",
    "cadivor_secondary_refresh_requested",
    "cadivor_secondary_refresh_failed",
    "cadivor_shell_label_resync",
    "cadivor_active_analysis_id",
    "cadivor_active_analysis_tab",
    "cadivor_selected_component_mpn",
    "cadivor_selected_component_analysis_id",
    "cadivor_review_mpn",
    "cadivor_pending_analysis_section",
    "cadivor_pending_analysis_section_id",
    "cadivor_analysis_section_sync_id",
    "analysis_id",
    "results_df",
    "analysis_saved",
    "active_workspace_id",
    "active_workspace_name",
    "active_workspace_role",
    RESOLVED_PLAN_KEY,
    PROFILE_UNRESOLVED_KEY,
)

_PREFIXES = (
    "dashboard_portfolio_ctx_",
    "cadivor_bom_area_",
    "cadivor_bom_more_",
    "bom81_",
    "analysis_component_selector_",
    "cv3424_selected_component_",
)


def user_id_of(user: Any) -> str:
    if user is None:
        return ""
    if isinstance(user, Mapping):
        return str(user.get("id") or "").strip()
    return str(getattr(user, "id", "") or "").strip()


def bind_authenticated_account(session_state: MutableMapping[str, Any], user_id: Any) -> bool:
    """Record ``user_id``. Clear prior-account state when it differs.

    Returns True only on an account switch. A first bind does not clear
    same-session caches that were written before this key existed.
    """
    uid = str(user_id or "").strip()
    if not uid:
        return False
    prior = str(session_state.get(SCOPED_USER_KEY) or "").strip()
    session_state[SCOPED_USER_KEY] = uid
    if not prior or prior == uid:
        return False
    for key in _EXACT_KEYS:
        session_state.pop(key, None)
    for key in list(session_state.keys()):
        if any(str(key).startswith(prefix) for prefix in _PREFIXES):
            session_state.pop(key, None)
    session_state["cadivor_route"] = "Dashboard"
    session_state["app_mode"] = "Dashboard"
    session_state.pop("cadivor_nav_params", None)
    return True


def session_user_fallback(auth_user: Any) -> dict[str, Any]:
    """Identity-only user row used when the profile read does not finish."""
    email = ""
    if isinstance(auth_user, Mapping):
        email = str(auth_user.get("email") or "")
    else:
        email = str(getattr(auth_user, "email", "") or "")
    return {
        "id": user_id_of(auth_user),
        "email": email,
        "monthly_upload_count": 0,
        "full_name": "",
        "role": "",
        "plan": "",
    }


def first_page_plan_decision(
    *,
    unresolved: bool,
    resolved_name: str,
    trial_expired: bool,
    cached_name: str = "",
) -> tuple[str, bool, bool]:
    """Return (plan name, persist trial expiry, announce expiry).

    A missing profile read must not persist a plan change or announce expiry
    from a stub row. A same-user cached name is reused; a switched account has
    no cache because bind clears it.
    """
    if not unresolved:
        return resolved_name, bool(trial_expired), bool(trial_expired)
    cached = str(cached_name or "").strip()
    if cached:
        return cached, False, False
    return resolved_name, False, False
