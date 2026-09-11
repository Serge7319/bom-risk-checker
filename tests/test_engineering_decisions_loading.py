"""Engineering Decisions shell-first loading and timeout contracts."""
from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
REPO = (ROOT / "src" / "decision_repository.py").read_text(encoding="utf-8")


class EngineeringDecisionsLoadingContractTests(unittest.TestCase):
    def test_shell_reveals_before_hydrate_and_stops(self):
        branch = RUNTIME.split('if app_mode == "Engineering Decisions":', 1)[1]
        branch = branch.split('if app_mode == "Reports":', 1)[0]
        # Exactly one primary ED hero mount in source.
        self.assertEqual(
            branch.count('eyebrow="Cadivor Engineering Decision Center"'),
            1,
        )
        self.assertIn('test_id="ed-page-hero"', branch)
        self.assertIn('data-testid="ed-page-shell"', branch)

        hero_at = branch.find('test_id="ed-page-hero"')
        reveal_at = branch.find('reveal_authenticated_page_body("Engineering Decisions")')
        pass2_io_at = branch.find('decision_hydrate_key) == "loading"')
        hydrate_arm_at = branch.find('decision_hydrate_key] = "loading"')
        stop_at = branch.rfind("stop_authenticated_page()")

        self.assertGreater(pass2_io_at, 0)
        self.assertGreater(hero_at, pass2_io_at)
        self.assertGreater(reveal_at, hero_at)
        self.assertGreater(hydrate_arm_at, reveal_at)
        self.assertGreater(stop_at, hydrate_arm_at)
        self.assertIn("ed-inline-loading", branch)
        self.assertIn("Do not use cv56-skeleton-page", branch)

        # Pass 1 must schedule hydrate via st.rerun() — stop() never returns.
        pass1 = branch.split('decision_hydrate_key] = "loading"', 1)[1]
        pass1 = pass1.split("else:", 1)[0]
        self.assertIn("st.rerun()", pass1)
        self.assertNotIn("stop_authenticated_page()", pass1)

    def test_decision_reads_use_bounded_helper(self):
        self.assertIn("execute_supabase_read", REPO)
        self.assertIn("DECISION_LOAD_TIMEOUT_TOKEN", REPO)
        self.assertIn("DEFAULT_DECISION_LOAD_BUDGET_SECONDS", REPO)
        self.assertIn("deadline", REPO)

    def test_load_decision_state_respects_deadline(self):
        from src.decision_repository import (
            DECISION_LOAD_TIMEOUT_TOKEN,
            load_decision_state,
        )

        supabase = MagicMock()
        # Any table access should not be reached when deadline already passed.
        state, error = load_decision_state(
            supabase,
            user_id="user-1",
            workspace_id="ws-1",
            deadline=time.monotonic() - 1.0,
        )
        self.assertEqual(state, {})
        self.assertEqual(error, DECISION_LOAD_TIMEOUT_TOKEN)
        supabase.table.assert_not_called()

    def test_scope_keys_remain_workspace_scoped(self):
        branch = RUNTIME.split('if app_mode == "Engineering Decisions":', 1)[1]
        branch = branch.split('if app_mode == "Reports":', 1)[0]
        self.assertIn("active_workspace_id or \"personal\"", branch)
        self.assertIn("engineering_decision_state_", branch)
        self.assertIn("workspace_id=active_workspace_id or None", branch)


if __name__ == "__main__":
    unittest.main()
