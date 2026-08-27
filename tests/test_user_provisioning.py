"""Sprint 74 — user provisioning tests."""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.services.user_provisioning import (
    UserProvisioningError,
    build_default_user_row,
    ensure_user_profile,
)
from src.supabase_read import SupabaseReadTransportError


class UserProvisioningTests(unittest.TestCase):
    def _auth_user(self, user_id="user-1", email="user@example.com"):
        return types.SimpleNamespace(
            id=user_id,
            email=email,
            user_metadata={"full_name": "Test User", "company_name": "Acme"},
        )

    def test_build_default_user_row_uses_trial_plan(self):
        row = build_default_user_row(self._auth_user())
        self.assertEqual(row["id"], "user-1")
        self.assertEqual(row["email"], "user@example.com")
        self.assertEqual(row["plan"], "Trial")
        self.assertEqual(row["monthly_upload_count"], 0)
        self.assertTrue(row["trial_ends_at"])

    def test_existing_user_row_is_not_overwritten(self):
        supabase = MagicMock()
        existing = {"id": "user-1", "email": "user@example.com", "plan": "Professional"}
        supabase.table.return_value.select.return_value.eq.return_value = MagicMock()
        with patch(
            "src.services.user_provisioning.execute_supabase_read",
            return_value=types.SimpleNamespace(data=[existing]),
        ):
            profile, created = ensure_user_profile(supabase, self._auth_user())
        self.assertFalse(created)
        self.assertEqual(profile["plan"], "Professional")
        supabase.table.return_value.insert.assert_not_called()

    def test_missing_user_row_is_created(self):
        supabase = MagicMock()
        created_row = {
            "id": "user-1",
            "email": "user@example.com",
            "plan": "Trial",
            "monthly_upload_count": 0,
            "trial_ends_at": datetime.now(timezone.utc).isoformat(),
        }
        read_responses = [
            types.SimpleNamespace(data=[]),
            types.SimpleNamespace(data=[created_row]),
        ]
        supabase.table.return_value.insert.return_value.execute.return_value = types.SimpleNamespace(
            data=[created_row]
        )
        with patch(
            "src.services.user_provisioning.execute_supabase_read",
            side_effect=read_responses,
        ):
            profile, created = ensure_user_profile(supabase, self._auth_user())
        self.assertTrue(created)
        self.assertEqual(profile["plan"], "Trial")
        insert_call = supabase.table.return_value.insert.call_args[0][0]
        self.assertEqual(insert_call["id"], "user-1")

    def test_repeated_provisioning_is_idempotent(self):
        supabase = MagicMock()
        existing = {"id": "user-1", "email": "user@example.com", "plan": "Trial"}
        with patch(
            "src.services.user_provisioning.execute_supabase_read",
            return_value=types.SimpleNamespace(data=[existing]),
        ):
            first, created_first = ensure_user_profile(supabase, self._auth_user())
            second, created_second = ensure_user_profile(supabase, self._auth_user())
        self.assertFalse(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first, second)

    def test_cross_user_isolation_uses_session_user_id(self):
        supabase = MagicMock()
        other_profile = {"id": "user-2", "email": "other@example.com", "plan": "Trial"}

        def _read_side_effect(*args, **kwargs):
            query = args[0]
            _ = query
            return types.SimpleNamespace(data=[])

        supabase.table.return_value.insert.return_value.execute.return_value = types.SimpleNamespace(
            data=[{"id": "user-1", "email": "user@example.com", "plan": "Trial"}]
        )
        with patch(
            "src.services.user_provisioning.execute_supabase_read",
            side_effect=_read_side_effect,
        ):
            profile, created = ensure_user_profile(
                supabase,
                self._auth_user(user_id="user-1"),
            )
        self.assertTrue(created)
        self.assertEqual(profile["id"], "user-1")
        self.assertNotEqual(profile, other_profile)

    def test_provisioning_failure_surfaces_error(self):
        supabase = MagicMock()
        with patch(
            "src.services.user_provisioning.execute_supabase_read",
            side_effect=SupabaseReadTransportError("ensure_user_profile", RuntimeError("down")),
        ):
            with self.assertRaises(UserProvisioningError):
                ensure_user_profile(supabase, self._auth_user())

    def test_insert_conflict_retries_read(self):
        supabase = MagicMock()
        existing = {"id": "user-1", "email": "user@example.com", "plan": "Trial"}
        supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError("duplicate")
        with patch(
            "src.services.user_provisioning.execute_supabase_read",
            side_effect=[
                types.SimpleNamespace(data=[]),
                types.SimpleNamespace(data=[existing]),
            ],
        ):
            profile, created = ensure_user_profile(supabase, self._auth_user())
        self.assertFalse(created)
        self.assertEqual(profile["id"], "user-1")

    def test_trigger_created_row_wins_after_insert_conflict(self):
        """Simulate auth signup + DB trigger race: insert loses, existing row wins."""
        supabase = MagicMock()
        trigger_created = {
            "id": "user-1",
            "email": "user@example.com",
            "plan": "Professional",
            "trial_ends_at": "2026-01-01T00:00:00+00:00",
            "monthly_upload_count": 7,
            "role": "admin",
        }
        supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError(
            'duplicate key value violates unique constraint "users_pkey"'
        )
        with patch(
            "src.services.user_provisioning.execute_supabase_read",
            side_effect=[
                types.SimpleNamespace(data=[]),
                types.SimpleNamespace(data=[trigger_created]),
            ],
        ) as read_mock:
            profile, created = ensure_user_profile(supabase, self._auth_user())

        self.assertFalse(created)
        self.assertEqual(profile, trigger_created)
        self.assertEqual(profile["plan"], "Professional")
        self.assertEqual(profile["monthly_upload_count"], 7)
        self.assertEqual(profile["trial_ends_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(read_mock.call_count, 2)
        supabase.table.return_value.update.assert_not_called()

    def test_profile_visibility_is_retried_after_create(self):
        supabase = MagicMock()
        delayed_profile = {"id": "user-1", "email": "user@example.com", "plan": "Trial"}
        supabase.table.return_value.insert.return_value.execute.return_value = types.SimpleNamespace(data=[])
        with patch(
            "src.services.user_provisioning.execute_supabase_read",
            side_effect=[
                types.SimpleNamespace(data=[]),
                types.SimpleNamespace(data=[]),
                types.SimpleNamespace(data=[]),
                types.SimpleNamespace(data=[delayed_profile]),
            ],
        ), patch("src.services.user_provisioning.time.sleep") as sleep_mock:
            profile, created = ensure_user_profile(supabase, self._auth_user())

        self.assertTrue(created)
        self.assertEqual(profile, delayed_profile)
        self.assertEqual(sleep_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
