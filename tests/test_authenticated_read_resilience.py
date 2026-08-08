"""Sprint 72.4C — authenticated startup read resilience tests."""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "src" / "authenticated_runtime.py"
AUTH_BOOTSTRAP_PATH = ROOT / "src" / "auth_bootstrap.py"


def _runtime_source() -> str:
    return RUNTIME_PATH.read_text(encoding="utf-8")


class AuthenticatedReadResilienceTests(unittest.TestCase):
    def test_dead_analysis_history_prefetch_removed(self) -> None:
        source = _runtime_source()
        self.assertNotIn("analysis_history = (", source)
        self.assertNotIn("global current_user, is_admin, analysis_history", source)

    def test_no_analysis_history_global_consumer_remains(self) -> None:
        tree = ast.parse(_runtime_source())
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "analysis_history"
        }
        self.assertEqual(names, set())

    def test_load_analysis_history_loader_still_exists(self) -> None:
        source = _runtime_source()
        self.assertIn("def load_analysis_history(user_id):", source)

    def test_trial_downgrade_update_not_using_read_helper(self) -> None:
        source = _runtime_source()
        trial_block_start = source.index('supabase.table("users").update({"plan": "Starter"})')
        trial_block = source[trial_block_start : trial_block_start + 180]
        self.assertNotIn("execute_supabase_read", trial_block)

    def test_get_supabase_client_unchanged(self) -> None:
        source = AUTH_BOOTSTRAP_PATH.read_text(encoding="utf-8")
        self.assertIn("return create_client(url, key)", source)
        self.assertNotIn("ClientOptions", source)
        self.assertNotIn("HTTPTransport", source)

    def test_read_helper_not_used_for_delete_or_insert_paths(self) -> None:
        source = _runtime_source()
        for token in ('.delete().', '.insert(', '.update('):
            idx = 0
            while True:
                pos = source.find(token, idx)
                if pos == -1:
                    break
                window = source[max(0, pos - 220) : pos + 80]
                self.assertNotIn(
                    "execute_supabase_read",
                    window,
                    msg=f"execute_supabase_read found near {token}",
                )
                idx = pos + len(token)

    def test_load_user_data_uses_read_helper(self) -> None:
        source = _runtime_source()
        start = source.index("def load_user_data():")
        end = source.index("\ndef _safe_text", start)
        block = source[start:end]
        self.assertIn("execute_supabase_read(", block)
        self.assertIn('operation="load_user_data"', block)
        self.assertIn("SupabaseReadTransportError", block)
        self.assertIn("stop_authenticated_page()", block)
        self.assertNotIn(".execute()", block)

    def test_saved_bom_count_uses_read_helper_with_fallback(self) -> None:
        source = _runtime_source()
        start = source.index("saved_bom_count_response = execute_supabase_read")
        block = source[start : start + 320]
        self.assertIn('operation="saved_bom_count"', block)
        self.assertIn("except SupabaseReadTransportError:", source[start : start + 420])
        self.assertIn("saved_bom_count = 0", source[start : start + 420])


if __name__ == "__main__":
    unittest.main()
