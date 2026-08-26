from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BrandedMaintenanceScreenContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = (ROOT / "src" / "authenticated_runtime.py").read_text()

    def test_maintenance_route_uses_the_branded_surface(self):
        self.assertIn("def render_maintenance_mode_surface(message):", self.runtime)
        self.assertIn('id="cadivor-maintenance-screen"', self.runtime)
        self.assertIn('id="cadivor-maintenance-mode"', self.runtime)
        self.assertIn('render_maintenance_mode_surface(runtime_access.get("maintenance_message"))', self.runtime)

    def test_screen_preserves_customer_message_safely(self):
        self.assertIn("safe_message = html.escape(customer_message)", self.runtime)
        self.assertIn("Your engineering data is safe.", self.runtime)
        self.assertIn("beta@cadivor.com", self.runtime)

    def test_admin_bypass_and_suspension_guard_remain_in_place(self):
        self.assertIn('bool(runtime_access.get("maintenance_mode")) and not is_admin', self.runtime)
        self.assertIn('runtime_access.get("account_status", "active")', self.runtime)


if __name__ == "__main__":
    unittest.main()
