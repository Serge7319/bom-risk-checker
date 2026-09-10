"""Verified public.users.role must drive Admin Console before first shell paint."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class VerifiedAdminRoleBeforeShellTests(unittest.TestCase):
    def test_cold_stale_shell_cache_false_admin_db_role_first_shell_has_admin_console(self):
        from src.shell_admin_entitlement import resolve_shell_admin_before_paint
        from src.ui.unified_shell import workspace_nav_rows

        session = {"cadivor_shell_cache": {"is_admin": False}}
        lookups: list[str] = []

        def read_role(user_id: str):
            lookups.append(user_id)
            return SimpleNamespace(data=[{"role": "admin"}])

        is_admin, diag = resolve_shell_admin_before_paint(
            session,
            user_id="admin-user-1",
            read_role=read_role,
            shell_cache_is_admin=False,
        )
        self.assertTrue(is_admin)
        self.assertEqual(lookups, ["admin-user-1"])
        self.assertEqual(diag.get("lookup"), "fetched")
        labels = [row[0] for row in workspace_nav_rows(is_admin=is_admin)]
        self.assertIn("Admin Console", labels)

        # Second paint in-session uses verified cache — still Admin Console, no rerun API.
        is_admin2, diag2 = resolve_shell_admin_before_paint(
            session,
            user_id="admin-user-1",
            read_role=read_role,
            shell_cache_is_admin=False,
        )
        self.assertTrue(is_admin2)
        self.assertEqual(diag2.get("lookup"), "cache_hit")
        self.assertEqual(lookups, ["admin-user-1"])

    def test_second_login_after_logout_clears_cache_and_shell_has_admin(self):
        from src.shell_admin_entitlement import (
            clear_verified_users_role,
            resolve_shell_admin_before_paint,
        )
        from src.ui.unified_shell import workspace_nav_rows

        session = {
            "cadivor_shell_cache": {"is_admin": False},
            "cadivor_verified_users_role": {
                "user_id": "admin-user-1",
                "role": "admin",
                "status": "verified",
                "verified_at": 1.0,
            },
            "cadivor_shell_admin_resync_token": "admin-user-1:1",
        }
        clear_verified_users_role(session)
        self.assertNotIn("cadivor_verified_users_role", session)
        self.assertNotIn("cadivor_shell_admin_resync_token", session)

        lookups: list[str] = []

        def read_role(user_id: str):
            lookups.append(user_id)
            return SimpleNamespace(data=[{"role": "admin"}])

        is_admin, diag = resolve_shell_admin_before_paint(
            session,
            user_id="admin-user-1",
            read_role=read_role,
            shell_cache_is_admin=False,
        )
        self.assertTrue(is_admin)
        self.assertEqual(lookups, ["admin-user-1"])
        self.assertEqual(diag.get("lookup"), "fetched")
        self.assertIn(
            "Admin Console",
            [row[0] for row in workspace_nav_rows(is_admin=True)],
        )

    def test_non_admin_database_role_omits_admin_console(self):
        from src.shell_admin_entitlement import resolve_shell_admin_before_paint
        from src.ui.unified_shell import workspace_nav_rows

        session: dict = {}

        def read_role(user_id: str):
            return SimpleNamespace(data=[{"role": "user"}])

        is_admin, _ = resolve_shell_admin_before_paint(
            session,
            user_id="user-2",
            read_role=read_role,
            shell_cache_is_admin=True,  # stale True must not win
        )
        self.assertFalse(is_admin)
        self.assertNotIn(
            "Admin Console",
            [row[0] for row in workspace_nav_rows(is_admin=False)],
        )

    def test_logout_and_user_switch_clear_verified_role_cache(self):
        from src.shell_admin_entitlement import (
            clear_verified_users_role,
            remember_verified_users_role,
            resolve_shell_admin_before_paint,
        )

        session: dict = {}
        remember_verified_users_role(session, user_id="a1", role="admin")
        clear_verified_users_role(session)
        self.assertIsNone(session.get("cadivor_verified_users_role"))

        # User switch: prior admin cache must not apply to a different id.
        remember_verified_users_role(session, user_id="a1", role="admin")
        lookups: list[str] = []

        def read_role(user_id: str):
            lookups.append(user_id)
            return SimpleNamespace(data=[{"role": "user"}])

        is_admin, diag = resolve_shell_admin_before_paint(
            session,
            user_id="b2",
            read_role=read_role,
        )
        self.assertFalse(is_admin)
        self.assertEqual(lookups, ["b2"])
        self.assertEqual(diag.get("lookup"), "fetched")

        auth_state = (ROOT / "src" / "auth_state.py").read_text(encoding="utf-8")
        self.assertIn("clear_verified_users_role", auth_state)

    def test_role_lookup_failure_does_not_poison_next_successful_lookup(self):
        from src.shell_admin_entitlement import resolve_shell_admin_before_paint

        session: dict = {}
        calls = {"n": 0}

        def read_role(user_id: str):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("transient")
            return SimpleNamespace(data=[{"role": "admin"}])

        is_admin1, diag1 = resolve_shell_admin_before_paint(
            session, user_id="admin-user-1", read_role=read_role
        )
        self.assertFalse(is_admin1)
        self.assertTrue(diag1.get("failed"))
        # Failure must not be stored as verified non-admin.
        entry = session.get("cadivor_verified_users_role")
        self.assertTrue(entry is None or entry.get("status") != "verified")

        is_admin2, diag2 = resolve_shell_admin_before_paint(
            session, user_id="admin-user-1", read_role=read_role
        )
        self.assertTrue(is_admin2)
        self.assertEqual(diag2.get("lookup"), "fetched")
        self.assertEqual(calls["n"], 2)

    def test_no_admin_entitlement_rerun_api(self):
        import src.shell_admin_entitlement as entitlement

        self.assertFalse(hasattr(entitlement, "maybe_resync_shell_admin_after_profile"))
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("resolve_shell_admin_before_paint(", runtime)
        self.assertNotIn("maybe_resync_shell_admin_after_profile(", runtime)
        self.assertIn('operation="shell_admin_role_lookup"', runtime)
        # Single shell paint authority remains.
        early = runtime[
            runtime.find("Paint the durable foundation shell") : runtime.find(
                'log_startup_phase("authenticated_runtime_begin")'
            )
        ]
        self.assertEqual(early.count("render_unified_shell("), 1)
        late = runtime[
            runtime.find("# ---------- Cadivor Unified Application Shell ----------") :
            runtime.find('with timed_phase("runtime.workspace_commands"')
        ]
        self.assertNotIn("render_unified_shell(", late)

    def test_failure_retains_prior_verified_admin(self):
        from src.shell_admin_entitlement import (
            remember_verified_users_role,
            resolve_shell_admin_before_paint,
        )

        session: dict = {}
        remember_verified_users_role(session, user_id="admin-user-1", role="admin")

        def read_role(user_id: str):
            raise ConnectionError("down")

        is_admin, diag = resolve_shell_admin_before_paint(
            session,
            user_id="admin-user-1",
            read_role=read_role,
            force_refresh=True,
        )
        self.assertTrue(is_admin)
        self.assertTrue(diag.get("failed"))
        self.assertEqual(diag.get("retained_role"), "admin")


if __name__ == "__main__":
    unittest.main()
