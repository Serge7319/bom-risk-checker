"""Verified ``public.users.role`` for foundation-shell admin navigation.

Authoritative owner: a narrow ``users.role`` SELECT for the authenticated user id,
resolved **before** the first ``render_unified_shell`` call.

``cadivor_shell_cache["is_admin"]`` is never the final decision for whether an
already-known admin sees Admin Console. Session cache holds only a verified role
for the current user identity and is cleared on logout, user change, expired
session, and explicit account refresh.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping


VERIFIED_USERS_ROLE_KEY = "cadivor_verified_users_role"
VERIFIED_ROLE_MAX_AGE_SECONDS = 300


def is_admin_from_users_role(user_row) -> bool:
    """Authoritative admin check: ``public.users.role`` only (never client hardcode)."""
    if not isinstance(user_row, dict):
        return False
    return str(user_row.get("role") or "").strip().lower() == "admin"


def role_is_admin(role: Any) -> bool:
    return str(role or "").strip().lower() == "admin"


def _bump_smoke_counter(key: str) -> None:
    path = str(os.environ.get("CADIVOR_SMOKE_IO_COUNTERS") or "").strip()
    if not path:
        return
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8") or "{}")
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}
        data[key] = int(data.get(key) or 0) + 1
        target.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def clear_verified_users_role(session_state: MutableMapping[str, Any]) -> None:
    """Drop verified role cache (logout, user switch, expired session, refresh)."""
    session_state.pop(VERIFIED_USERS_ROLE_KEY, None)
    session_state.pop("cadivor_shell_admin_resync_token", None)
    session_state.pop("cadivor_shell_admin_role_diag", None)


def get_cached_verified_users_role(
    session_state: Mapping[str, Any],
    user_id: Any,
    *,
    now: float | None = None,
    max_age_seconds: float = VERIFIED_ROLE_MAX_AGE_SECONDS,
) -> str | None:
    """Return a verified role string only for the same authenticated user id."""
    entry = session_state.get(VERIFIED_USERS_ROLE_KEY)
    expected_id = str(user_id or "").strip()
    if not isinstance(entry, Mapping) or not expected_id:
        return None
    if str(entry.get("user_id") or "").strip() != expected_id:
        return None
    if str(entry.get("status") or "") != "verified":
        return None
    try:
        age = (time.time() if now is None else now) - float(entry.get("verified_at"))
    except (TypeError, ValueError):
        return None
    if age < 0 or age > max_age_seconds:
        return None
    role = str(entry.get("role") or "").strip()
    return role or None


def remember_verified_users_role(
    session_state: MutableMapping[str, Any],
    *,
    user_id: Any,
    role: Any,
    now: float | None = None,
) -> str:
    """Cache a successfully verified ``public.users.role`` for this user only."""
    uid = str(user_id or "").strip()
    role_text = str(role or "").strip()
    session_state[VERIFIED_USERS_ROLE_KEY] = {
        "user_id": uid,
        "role": role_text,
        "status": "verified",
        "verified_at": time.time() if now is None else now,
        "source": "public.users.role",
    }
    return role_text


def mark_verified_users_role_lookup_failed(
    session_state: MutableMapping[str, Any],
    *,
    user_id: Any,
    error: str,
    now: float | None = None,
) -> None:
    """Record a recoverable lookup failure without caching a False admin decision."""
    uid = str(user_id or "").strip()
    session_state["cadivor_shell_admin_role_diag"] = {
        "user_id": uid,
        "status": "lookup_failed",
        "error": str(error or "role_lookup_failed")[:240],
        "at": time.time() if now is None else now,
    }
    # Do not write status=verified with role="" — that would poison the next paint.


def extract_role_from_users_read(result: Any) -> str:
    """Parse ``role`` from a narrow users SELECT response."""
    data = getattr(result, "data", None)
    if isinstance(data, list) and data:
        row = data[0]
        if isinstance(row, Mapping):
            return str(row.get("role") or "").strip()
    if isinstance(data, Mapping):
        return str(data.get("role") or "").strip()
    return ""


def lookup_public_users_role(
    *,
    user_id: Any,
    read_role: Callable[[str], Any],
) -> str:
    """Execute the narrow ``public.users.role`` lookup for ``user_id``."""
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("missing_user_id")
    _bump_smoke_counter("shell_admin_role_lookup")
    result = read_role(uid)
    role = extract_role_from_users_read(result)
    return role


def resolve_shell_admin_before_paint(
    session_state: MutableMapping[str, Any],
    *,
    user_id: Any,
    read_role: Callable[[str], Any],
    shell_cache_is_admin: bool = False,
    force_refresh: bool = False,
    now: float | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Resolve Admin Console entitlement before the first shell paint.

    ``shell_cache_is_admin`` is ignored as an authoritative source: a stale
    ``False`` must not hide Admin Console when ``public.users.role`` is admin.

    On lookup failure, retain a previously verified role for the same user
    (recoverable) and surface diagnostics — never cache failure as verified
    non-admin.
    """
    del shell_cache_is_admin  # never authoritative for this decision
    uid = str(user_id or "").strip()
    diag: dict[str, Any] = {
        "user_id": uid,
        "source": "public.users.role",
        "lookup": "skipped",
        "cached": False,
        "failed": False,
    }
    if not uid:
        diag["lookup"] = "missing_user_id"
        diag["failed"] = True
        session_state["cadivor_shell_admin_role_diag"] = diag
        return False, diag

    cached = None if force_refresh else get_cached_verified_users_role(
        session_state, uid, now=now
    )
    if cached is not None:
        diag["lookup"] = "cache_hit"
        diag["cached"] = True
        diag["role"] = cached
        session_state["cadivor_shell_admin_role_diag"] = diag
        _bump_smoke_counter("shell_admin_role_cache_hit")
        return role_is_admin(cached), diag

    # User change: drop any other identity's verified role before lookup.
    prior = session_state.get(VERIFIED_USERS_ROLE_KEY)
    if isinstance(prior, Mapping) and str(prior.get("user_id") or "").strip() not in {"", uid}:
        clear_verified_users_role(session_state)

    try:
        role = lookup_public_users_role(user_id=uid, read_role=read_role)
        remember_verified_users_role(session_state, user_id=uid, role=role, now=now)
        diag["lookup"] = "fetched"
        diag["role"] = role
        session_state["cadivor_shell_admin_role_diag"] = diag
        return role_is_admin(role), diag
    except Exception as exc:
        mark_verified_users_role_lookup_failed(
            session_state, user_id=uid, error=f"{type(exc).__name__}:{exc}", now=now
        )
        # Retain last verified role for this user if present (may be aged out of
        # get_cached… but still in the raw entry after a transient failure path).
        entry = session_state.get(VERIFIED_USERS_ROLE_KEY)
        retained = None
        if (
            isinstance(entry, Mapping)
            and str(entry.get("user_id") or "").strip() == uid
            and str(entry.get("status") or "") == "verified"
        ):
            retained = str(entry.get("role") or "").strip() or None
        diag["lookup"] = "failed"
        diag["failed"] = True
        diag["error"] = f"{type(exc).__name__}:{exc}"[:240]
        diag["retained_role"] = retained
        session_state["cadivor_shell_admin_role_diag"] = diag
        _bump_smoke_counter("shell_admin_role_lookup_failed")
        if retained is not None:
            return role_is_admin(retained), diag
        # Safe recoverable: omit Admin Console this paint; do not cache False.
        return False, diag
