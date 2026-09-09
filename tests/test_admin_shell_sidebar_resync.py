"""Admin Console sidebar must appear after cold login once users.role loads."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AdminShellSidebarResyncTests(unittest.TestCase):
    def test_cold_empty_cache_admin_role_resyncs_shell_with_admin_console(self):
        from src.shell_admin_entitlement import (
            is_admin_from_users_role,
            maybe_resync_shell_admin_after_profile,
        )
        from src.ui.unified_shell import workspace_nav_rows

        session: dict = {}
        reruns: list[int] = []
        loaded = {"id": "admin-user-1", "role": "admin", "plan": "Starter"}

        self.assertFalse(bool((session.get("cadivor_shell_cache") or {}).get("is_admin")))
        self.assertTrue(is_admin_from_users_role(loaded))

        invoked = maybe_resync_shell_admin_after_profile(
            session,
            early_shell_is_admin=False,
            loaded_user=loaded,
            rerun=lambda: reruns.append(1),
        )
        self.assertTrue(invoked)
        self.assertEqual(reruns, [1])
        self.assertTrue(session["cadivor_shell_cache"]["is_admin"])

        labels = [row[0] for row in workspace_nav_rows(is_admin=True)]
        self.assertIn("Admin Console", labels)

        invoked_again = maybe_resync_shell_admin_after_profile(
            session,
            early_shell_is_admin=True,
            loaded_user=loaded,
            rerun=lambda: reruns.append(1),
        )
        self.assertFalse(invoked_again)
        self.assertEqual(reruns, [1])

    def test_non_admin_never_gets_admin_console_nav_or_access(self):
        from src.shell_admin_entitlement import (
            is_admin_from_users_role,
            maybe_resync_shell_admin_after_profile,
        )
        from src.ui.unified_shell import workspace_nav_rows

        labels = [row[0] for row in workspace_nav_rows(is_admin=False)]
        self.assertNotIn("Admin Console", labels)

        session: dict = {"cadivor_shell_cache": {"is_admin": True}}
        reruns: list[int] = []
        loaded = {"id": "user-2", "role": "user"}
        self.assertFalse(is_admin_from_users_role(loaded))
        maybe_resync_shell_admin_after_profile(
            session,
            early_shell_is_admin=True,
            loaded_user=loaded,
            rerun=lambda: reruns.append(1),
        )
        self.assertFalse(session["cadivor_shell_cache"]["is_admin"])
        self.assertEqual(reruns, [1])
        self.assertNotIn(
            "Admin Console",
            [row[0] for row in workspace_nav_rows(is_admin=False)],
        )

        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn('if not is_admin and app_mode in {"Admin Console", "Help", "Admin"}:', runtime)
        gate = runtime[
            runtime.find('if app_mode == "Admin Console":') : runtime.find(
                'st.title("Admin Console")'
            )
        ]
        self.assertIn("if not is_admin:", gate)
        self.assertIn("available only to Cadivor administrators", gate)

        allowlist_src = runtime[
            runtime.find("def _canonical_route_allowlist") : runtime.find(
                "def resolve_canonical_app_route"
            )
        ]
        self.assertIn('"Admin Console"', allowlist_src)
        self.assertIn('allow = allow - {"Admin Console", "Help", "Admin"}', runtime)

    def test_role_sourced_from_public_users_not_hardcoded_client_state(self):
        from src.shell_admin_entitlement import is_admin_from_users_role

        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        entitlement = (ROOT / "src" / "shell_admin_entitlement.py").read_text(
            encoding="utf-8"
        )
        load_fn = runtime[
            runtime.find("def load_user_data():") : runtime.find("def _safe_text")
        ]
        self.assertIn('supabase.table("users").select("*")', load_fn)
        self.assertIn("is_admin = is_admin_from_users_role(current_user)", runtime)
        self.assertIn("maybe_resync_shell_admin_after_profile(", runtime)
        self.assertIn("public.users.role", entitlement)
        self.assertNotIn("is_admin = True", runtime)
        self.assertNotIn("is_admin = True", entitlement)

        self.assertTrue(is_admin_from_users_role({"role": "admin"}))
        self.assertTrue(is_admin_from_users_role({"role": "Admin"}))
        self.assertFalse(is_admin_from_users_role({"role": "user"}))
        self.assertFalse(is_admin_from_users_role({"role": ""}))
        self.assertFalse(is_admin_from_users_role({}))
        self.assertFalse(is_admin_from_users_role(None))
        self.assertFalse(is_admin_from_users_role({"is_admin": True}))
        self.assertFalse(is_admin_from_users_role({"role_title": "admin"}))

    def test_resync_refuses_infinite_loop_for_same_token(self):
        from src.shell_admin_entitlement import maybe_resync_shell_admin_after_profile

        session = {
            "cadivor_shell_cache": {},
            "cadivor_shell_admin_resync_token": "u1:1",
        }
        reruns: list[int] = []
        invoked = maybe_resync_shell_admin_after_profile(
            session,
            early_shell_is_admin=False,
            loaded_user={"id": "u1", "role": "admin"},
            rerun=lambda: reruns.append(1),
        )
        self.assertFalse(invoked)
        self.assertEqual(reruns, [])
        self.assertTrue(session["cadivor_shell_cache"]["is_admin"])

    def test_single_shell_paint_contract_preserved(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        early = runtime[
            runtime.find("Paint the durable foundation shell") : runtime.find(
                'log_startup_phase("authenticated_runtime_begin")'
            )
        ]
        late = runtime[
            runtime.find("# ---------- Cadivor Unified Application Shell ----------") :
            runtime.find('with timed_phase("runtime.workspace_commands"')
        ]
        self.assertEqual(early.count("render_unified_shell("), 1)
        self.assertNotIn("render_unified_shell(", late)
        self.assertIn("maybe_resync_shell_admin_after_profile(", runtime)


if __name__ == "__main__":
    unittest.main()
