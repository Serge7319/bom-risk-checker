"""Keep authenticated writes attached to the workspace resolved for this run."""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any


ACTIVE_WORKSPACE_KEYS = (
    "active_workspace_id",
    "active_workspace_name",
    "active_workspace_role",
)
ANALYSIS_WRITE_ROLES = frozenset({"owner", "admin", "engineer"})


def sync_active_workspace_context(
    session_state: MutableMapping[str, Any],
    workspace: Mapping[str, Any] | None,
) -> tuple[str, str, str]:
    """Replace cached workspace scope, clearing it when no workspace was verified."""
    workspace = workspace if isinstance(workspace, Mapping) else {}
    workspace_id = str(workspace.get("id") or "").strip()
    if not workspace_id:
        for key in ACTIVE_WORKSPACE_KEYS:
            session_state.pop(key, None)
        return "", "", ""

    workspace_name = str(workspace.get("name") or "Cadivor Workspace").strip()
    workspace_role = str(workspace.get("current_role") or "viewer").strip().lower()
    session_state["active_workspace_id"] = workspace_id
    session_state["active_workspace_name"] = workspace_name
    session_state["active_workspace_role"] = workspace_role
    return workspace_id, workspace_name, workspace_role


def can_create_analysis(workspace_id: Any, workspace_role: Any) -> bool:
    """Match the analyses insert policy's active workspace roles."""
    return (
        bool(str(workspace_id or "").strip())
        and str(workspace_role or "").strip().lower() in ANALYSIS_WRITE_ROLES
    )


def build_workspace_payload(payload: Mapping[str, Any] | None, workspace_id: Any) -> dict[str, Any]:
    """Use only the explicitly resolved workspace; never inherit stale payload scope."""
    result = dict(payload or {})
    result.pop("workspace_id", None)
    resolved_workspace_id = str(workspace_id or "").strip()
    if resolved_workspace_id:
        result["workspace_id"] = resolved_workspace_id
    return result
