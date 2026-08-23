import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_plans():
    spec = importlib.util.spec_from_file_location("billing_plans", ROOT / "src" / "plans.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BillingPlanEnforcementTests(unittest.TestCase):
    def test_admin_resolves_to_enterprise(self):
        plans = load_plans()
        self.assertEqual(plans.resolve_effective_plan({"role": "admin", "plan": "Starter"}), ("Enterprise", False))

    def test_admin_bypasses_bom_limits(self):
        plans = load_plans()
        allowed, _ = plans.validate_bom_against_plan([object()] * 500, plans.get_plan("Student"), 500, is_admin=True)
        self.assertTrue(allowed)

    def test_non_admin_limits_remain_enforced(self):
        plans = load_plans()
        allowed, _ = plans.validate_bom_against_plan([object()], plans.get_plan("Starter"), 10)
        self.assertFalse(allowed)

    def test_launch_plan_matrix_is_explicit(self):
        plans = load_plans()
        self.assertEqual(plans.get_plan("Student")["price"], "$0")
        self.assertEqual(plans.get_plan("Starter")["price"], "$29/mo")
        self.assertEqual(plans.get_plan("Professional")["price"], "$99/mo")
        self.assertEqual(plans.get_plan("Business")["price"], "$299/mo")
        self.assertIsNone(plans.get_plan("Enterprise")["monthly_bom_limit"])
        self.assertTrue(plans.get_plan("Business")["team_features"])
        self.assertTrue(plans.get_plan("Business")["api_access"])

    def test_paid_plan_grants_require_checkout(self):
        source = (ROOT / "src" / "authenticated_runtime.py").read_text()
        self.assertNotIn('"plan": "Pro"', source)
        self.assertNotIn('"plan": "Business"', source)
        self.assertIn("Paid plans are activated through secure Stripe checkout.", source)

    def test_checkout_price_matches_destination_plan(self):
        source = (ROOT / "src" / "authenticated_runtime.py").read_text()
        self.assertIn('"Professional": "STRIPE_PRO_PRICE_ID"', source)
        self.assertIn('"Business": "STRIPE_BUSINESS_PRICE_ID"', source)
        self.assertIn('and not is_admin', source)

    def test_checkout_errors_do_not_expose_provider_details(self):
        source = (ROOT / "src" / "authenticated_runtime.py").read_text()
        self.assertNotIn('Unable to create checkout session: {e}', source)
        self.assertNotIn('Unable to create {plan_name} checkout: {exc}', source)
        self.assertIn('Secure {plan_name} checkout could not be started.', source)

    def test_dashboard_upgrade_prompt_uses_effective_plan_and_skips_admins(self):
        source = (ROOT / "src" / "authenticated_runtime.py").read_text()
        self.assertIn('if not is_admin:\n                    render_upgrade_prompt(', source)
        self.assertIn('plan_name=selected_plan_name', source)
        self.assertIn('monthly_limit=selected_plan.get("monthly_bom_limit")', source)


if __name__ == "__main__":
    unittest.main()
