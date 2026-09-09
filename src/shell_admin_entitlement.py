"""Durable foundation-shell admin entitlement helpers.

``public.users.role`` is the only authoritative admin source. Early shell paint
may see an empty ``cadivor_shell_cache`` before profile IO; these helpers keep
Admin Console navigation in sync without remounting a second unified shell.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def is_admin_from_users_role(user_row) -> bool:
    """Authoritative admin check: ``public.users.role`` only (never client hardcode)."""
    if not isinstance(user_row, dict):
        return False
    return str(user_row.get("role") or "").strip().lower() == "admin"


def _bump_smoke_counter(key: str) -> None:
    """Optional smoke-only counter when CADIVOR_SMOKE_IO_COUNTERS is set."""
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


def maybe_resync_shell_admin_after_profile(
    session_state,
    *,
    early_shell_is_admin: bool,
    loaded_user: dict,
    rerun,
) -> bool:
    """If early shell lagged ``users.role``, refresh cache and one-shot rerun.

    Early foundation chrome may paint with an empty ``cadivor_shell_cache``
    (``is_admin=False``) before ``load_user_data`` returns. Do not remount a
    second unified shell in the same run — update the durable cache and rerun
    once so Admin Console appears without a manual reload.

    Returns True when ``rerun`` was invoked.
    """
    _bump_smoke_counter("shell_admin_resync_check")
    loaded_is_admin = is_admin_from_users_role(loaded_user)
    if bool(early_shell_is_admin) == bool(loaded_is_admin):
        return False

    cache = dict(session_state.get("cadivor_shell_cache") or {})
    cache["is_admin"] = loaded_is_admin
    session_state["cadivor_shell_cache"] = cache

    user_id = str((loaded_user or {}).get("id") or "").strip()
    token = f"{user_id}:{int(bool(loaded_is_admin))}"
    if str(session_state.get("cadivor_shell_admin_resync_token") or "") == token:
        # Same mismatch already resynced — refuse an infinite loop.
        return False
    session_state["cadivor_shell_admin_resync_token"] = token
    _bump_smoke_counter("shell_admin_resync_rerun")
    rerun()
    return True
