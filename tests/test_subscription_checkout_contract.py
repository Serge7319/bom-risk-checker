from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SubscriptionCheckoutContractTests(unittest.TestCase):
    def test_checkout_recovers_only_a_missing_saved_customer(self):
        source = (ROOT / "supabase/functions/subscription-checkout/index.ts").read_text(encoding="utf-8")
        self.assertIn('summary.code === "resource_missing"', source)
        self.assertIn('summary.param === "customer"', source)
        self.assertIn("if (!customerId || !isMissingStripeCustomer(error)) throw error;", source)
        self.assertIn("checkoutSessionParams(origin, auth.user.id, auth.user.email!, token, priceId)", source)
        self.assertIn("{ idempotencyKey: `${idempotencyKey}_fresh_customer` }", source)

    def test_checkout_errors_have_support_reference_without_logging_email_or_token(self):
        source = (ROOT / "supabase/functions/subscription-checkout/index.ts").read_text(encoding="utf-8")
        self.assertIn('code: "checkout_unavailable"', source)
        self.assertIn("support_reference: supportReference", source)
        self.assertIn('console.error("subscription_checkout_failed"', source)
        log_block = source[source.index('console.error("subscription_checkout_failed"'):]
        self.assertNotIn("auth.user.email", log_block)
        self.assertNotIn("access_token", log_block)
        self.assertNotIn("stripeSecret", log_block)
        self.assertNotIn("error_message", log_block)

    def test_settings_renders_nested_plan_usage_and_surfaces_support_reference(self):
        source = (ROOT / "apps/web/src/app/settings/page.tsx").read_text(encoding="utf-8")
        self.assertIn("function usageFacts(value: unknown)", source)
        self.assertIn("function usageLabel(key: string)", source)
        self.assertIn("function usageValue(value: unknown, key: string)", source)
        self.assertIn("usageFacts(usage)", source)
        usage_formatter = source[
            source.index("function usageValue(value: unknown, key: string)"):
            source.index(
                "function settingsErrorMessage",
                source.index("function usageValue(value: unknown, key: string)"),
            )
        ]
        self.assertNotIn("String(value)", usage_formatter)
        self.assertIn("err.payload.support_reference", source)
        self.assertIn("Support reference:", source)


if __name__ == "__main__":
    unittest.main()
