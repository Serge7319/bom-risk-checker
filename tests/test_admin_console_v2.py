from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminConsoleV2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = (ROOT / "src" / "authenticated_runtime.py").read_text()
        cls.migration = (ROOT / "supabase" / "migrations" / "20260826_admin_console_v2.sql").read_text()

    def test_runtime_enforces_maintenance_and_suspension_server_state(self):
        self.assertIn('supabase.rpc("cadivor_admin_runtime_access")', self.runtime)
        self.assertIn('runtime_access.get("account_status", "active")', self.runtime)
        self.assertIn('runtime_access.get("maintenance_mode")', self.runtime)
        self.assertIn("and not is_admin", self.runtime)

    def test_console_uses_audited_server_side_controls(self):
        for rpc_name in (
            "cadivor_admin_overview",
            "cadivor_admin_list_users_v2",
            "cadivor_admin_set_account_status",
            "cadivor_admin_set_role",
            "cadivor_admin_set_maintenance",
        ):
            self.assertIn(rpc_name, self.runtime)
        self.assertIn("ENABLE MAINTENANCE", self.runtime)
        self.assertIn("DISABLE MAINTENANCE", self.runtime)

    def test_selected_user_details_are_human_readable_not_a_raw_dictionary(self):
        self.assertIn("account_details = (", self.runtime)
        self.assertIn("for detail_label, detail_value in account_details", self.runtime)
        self.assertNotIn('st.write({\n                        "Email"', self.runtime)

    def test_migration_preserves_stripe_owned_paid_plan_activation(self):
        self.assertNotIn("cadivor_admin_set_plan", self.migration)
        self.assertIn("Paid-plan changes remain owned by Stripe/webhooks", self.migration)

    def test_migration_protects_admin_controls(self):
        self.assertIn("Administrators cannot change their own account status", self.migration)
        self.assertIn("Administrators cannot change their own role", self.migration)
        self.assertIn("Cadivor must retain at least one administrator", self.migration)
        self.assertIn("Administrator accounts cannot be suspended", self.migration)
        self.assertIn("insert into public.admin_audit_events", self.migration)
        self.assertIn("revoke all on function public.cadivor_admin_set_maintenance", self.migration)


if __name__ == "__main__":
    unittest.main()
