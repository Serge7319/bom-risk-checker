"""Production Postgres rows must be JSON safe before reaching the web client."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from apps.api import team_service


class WorkspaceMemberTimestampSerializationTests(unittest.TestCase):
    def _list_members(self, joined_at: datetime) -> dict:
        auth_store = Mock()
        auth_store.membership_for_user_workspace.return_value = {"role": "owner"}
        auth_store.list_workspace_members.return_value = [
            {
                "user_id": "user-1",
                "workspace_id": "workspace-1",
                "email": "owner@example.test",
                "role": "owner",
                "status": "active",
                "created_at": joined_at,
            }
        ]
        team_store = Mock()
        team_store.get_profiles.return_value = {}

        with (
            patch.object(team_service, "get_auth_store", return_value=auth_store),
            patch.object(team_service, "get_team_store", return_value=team_store),
        ):
            result = team_service.list_members(
                {"user_id": "user-1", "workspace_id": "workspace-1"}
            )

        # Match the JSON boundary used by Starlette's JSONResponse.
        json.dumps(result)
        return result

    def test_timezone_aware_database_timestamp_is_iso_8601(self):
        joined_at = datetime(2026, 11, 16, 12, 30, tzinfo=timezone.utc)

        result = self._list_members(joined_at)

        self.assertEqual(
            result["members"][0]["joined_at"], "2026-11-16T12:30:00+00:00"
        )

    def test_naive_database_timestamp_is_treated_as_utc(self):
        joined_at = datetime(2026, 11, 16, 12, 30)

        result = self._list_members(joined_at)

        self.assertEqual(
            result["members"][0]["joined_at"], "2026-11-16T12:30:00+00:00"
        )


if __name__ == "__main__":
    unittest.main()
