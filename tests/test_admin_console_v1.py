import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminConsoleV1ContractTests(unittest.TestCase):
    def test_console_is_admin_only_in_navigation_and_route(self):
        source = (ROOT / "src" / "authenticated_runtime.py").read_text()
        shell_source = (ROOT / "src" / "ui" / "unified_shell.py").read_text()
        self.assertIn('if is_admin:\n        NAV_OPTIONS.insert(NAV_OPTIONS.index("Settings"), "Admin Console")', source)
        self.assertIn("is_admin=is_admin", source)
        self.assertIn('if group_name == "Workspace" and is_admin:', shell_source)
        self.assertIn('("Admin Console", "admin", "Admin Console")', shell_source)
        self.assertIn('if app_mode == "Admin Console":', source)
        self.assertIn('if not is_admin:', source)

    def test_console_uses_server_enforced_rpcs(self):
        source = (ROOT / "src" / "authenticated_runtime.py").read_text()
        self.assertIn('supabase.rpc("cadivor_admin_list_users")', source)
        self.assertIn('supabase.rpc("cadivor_admin_audit_events")', source)

    def test_console_does_not_shadow_module_pandas_import(self):
        source = (ROOT / "src" / "authenticated_runtime.py").read_text()
        module = ast.parse(source)
        runtime = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_authenticated_app"
        )
        pandas_imports = [
            node for node in ast.walk(runtime)
            if isinstance(node, ast.Import)
            and any(alias.name == "pandas" for alias in node.names)
        ]
        self.assertEqual(pandas_imports, [])

    def test_migration_gates_all_data_by_admin_role(self):
        sql = (ROOT / "supabase" / "migrations" / "20260825_admin_console_v1.sql").read_text()
        self.assertIn("create or replace function public.cadivor_is_admin()", sql)
        self.assertIn("where public.cadivor_is_admin()", sql)
        self.assertIn("revoke all on function public.cadivor_admin_list_users() from public", sql)
        self.assertIn("admin_audit_events", sql)

    def test_migration_reads_optional_profile_columns_defensively(self):
        sql = (ROOT / "supabase" / "migrations" / "20260825_admin_console_v1.sql").read_text()
        self.assertIn("to_jsonb(u) ->> 'full_name'", sql)
        self.assertIn("to_jsonb(u) ->> 'company_name'", sql)
        self.assertIn("revoke all on function public.cadivor_is_admin() from public", sql)


if __name__ == "__main__":
    unittest.main()
