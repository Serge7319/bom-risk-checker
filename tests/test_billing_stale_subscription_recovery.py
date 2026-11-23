"""Regression checks for stale Stripe subscription links in production."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BillingStaleSubscriptionRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkout = (
            ROOT / "supabase" / "functions" / "subscription-checkout" / "index.ts"
        ).read_text(encoding="utf-8")
        cls.settings = (
            ROOT / "apps" / "web" / "src" / "app" / "settings" / "page.tsx"
        ).read_text(encoding="utf-8")
        cls.shell = (
            ROOT / "apps" / "web" / "src" / "components" / "Shell.tsx"
        ).read_text(encoding="utf-8")

    def test_expired_paid_period_does_not_preserve_paid_access(self):
        helper_start = self.checkout.index("function hasCurrentPaidSubscription(")
        helper_end = self.checkout.index("function effectivePlan(", helper_start)
        helper = self.checkout[helper_start:helper_end]
        self.assertIn("stripe_current_period_end", helper)
        self.assertIn("periodEnd > now", helper)
        self.assertIn("hasCurrentPaidSubscription(profile, now)", self.checkout)

    def test_new_checkout_checks_stripe_before_trusting_profile_status(self):
        checkout_guard = self.checkout[
            self.checkout.index('if (action !== "checkout")') :
        ]
        self.assertIn("stripe.subscriptions.search", checkout_guard)
        self.assertIn("billing_subscription_unverified", checkout_guard)
        self.assertIn("billing_subscription_ambiguous", checkout_guard)
        self.assertIn("const customerId = String(profile.stripe_customer_id", checkout_guard)
        self.assertNotIn(
            'if (["active", "trialing"].includes(status) && profile.stripe_customer_id)',
            checkout_guard,
        )

    def test_plan_change_falls_back_to_checkout_when_portal_has_no_active_subscription(self):
        plan_change = self.settings[
            self.settings.index("async function selectPlan(") :
            self.settings.index("function addonPriceLabel(")
        ]
        self.assertIn('portal.code === "billing_subscription_not_found"', plan_change)
        self.assertIn('err.payload.code === "billing_subscription_not_found"', plan_change)
        self.assertIn("beginSubscriptionCheckout(session.access_token, token, billingInterval)", plan_change)
        self.assertIn("checkout_started", plan_change)

    def test_shared_shell_uses_server_plan_instead_of_stale_login_snapshot(self):
        self.assertIn("fetchPlanUsage(session.access_token)", self.shell)
        self.assertIn('const planLabel = verifiedPlan || session.plan;', self.shell)
        self.assertIn('planLabel === "Subscription inactive"', self.shell)


if __name__ == "__main__":
    unittest.main()
