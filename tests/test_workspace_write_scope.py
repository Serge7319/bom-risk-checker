"""Regression tests for workspace-scoped write context."""
import unittest

from src.workspace_write_scope import (
    ACTIVE_WORKSPACE_KEYS,
    build_workspace_payload,
    can_create_analysis,
    sync_active_workspace_context,
)


class WorkspaceWriteScopeTests(unittest.TestCase):
    def test_missing_workspace_clears_stale_session_scope(self):
        state = {
            "active_workspace_id": "stale-workspace",
            "active_workspace_name": "Old Workspace",
            "active_workspace_role": "owner",
        }

        resolved = sync_active_workspace_context(state, None)

        self.assertEqual(resolved, ("", "", ""))
        self.assertTrue(all(key not in state for key in ACTIVE_WORKSPACE_KEYS))

    def test_verified_workspace_replaces_id_and_uses_reported_role(self):
        state = {
            "active_workspace_id": "stale-workspace",
            "active_workspace_name": "Old Workspace",
            "active_workspace_role": "owner",
        }

        resolved = sync_active_workspace_context(
            state,
            {"id": "current-workspace", "name": "Current Workspace", "current_role": "viewer"},
        )

        self.assertEqual(
            resolved,
            ("current-workspace", "Current Workspace", "viewer"),
        )
        self.assertEqual(state["active_workspace_id"], "current-workspace")
        self.assertEqual(state["active_workspace_role"], "viewer")

    def test_missing_role_fails_closed_as_viewer(self):
        state = {}
        resolved = sync_active_workspace_context(
            state,
            {"id": "current-workspace", "name": "Current Workspace"},
        )

        self.assertEqual(resolved[2], "viewer")
        self.assertFalse(can_create_analysis(*[resolved[0], resolved[2]]))

    def test_analysis_write_requires_policy_role_and_workspace(self):
        for role in ("owner", "admin", "engineer"):
            with self.subTest(role=role):
                self.assertTrue(can_create_analysis("workspace-1", role))
        self.assertFalse(can_create_analysis("workspace-1", "viewer"))
        self.assertFalse(can_create_analysis("", "owner"))

    def test_payload_replaces_or_removes_unverified_workspace(self):
        payload = {"user_id": "synthetic-user", "workspace_id": "stale-workspace"}

        self.assertEqual(
            build_workspace_payload(payload, "current-workspace"),
            {"user_id": "synthetic-user", "workspace_id": "current-workspace"},
        )
        self.assertEqual(
            build_workspace_payload(payload, ""),
            {"user_id": "synthetic-user"},
        )


if __name__ == "__main__":
    unittest.main()
