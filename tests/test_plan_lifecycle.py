"""Access model for paid Starter, trial expiry, and grandfathered beta."""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]


def _install_stripe_stub() -> None:
    if "stripe" in sys.modules and hasattr(sys.modules["stripe"], "checkout"):
        return
    stripe = types.ModuleType("stripe")
    stripe.api_key = None
    billing_portal = types.ModuleType("stripe.billing_portal")
    billing_portal.Session = types.SimpleNamespace(create=MagicMock())
    checkout = types.ModuleType("stripe.checkout")
    checkout.Session = types.SimpleNamespace(create=MagicMock())
    stripe.billing_portal = billing_portal
    stripe.checkout = checkout
    sys.modules["stripe"] = stripe
    sys.modules["stripe.billing_portal"] = billing_portal
    sys.modules["stripe.checkout"] = checkout


class PlanLifecycleTests(unittest.TestCase):
    def setUp(self):
        from src import plans

        self.plans = plans
        self.now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

    def test_new_signup_contract_is_trial_without_stripe_customer(self):
        from src.services.user_provisioning import build_default_user_row

        auth_user = types.SimpleNamespace(
            id="user-1",
            email="new@example.com",
            user_metadata={},
        )
        row = build_default_user_row(auth_user)
        self.assertEqual(row["plan"], "Trial")
        self.assertNotIn("stripe_customer_id", row)
        name, persist = self.plans.resolve_effective_plan(row, self.now)
        self.assertEqual(name, "Trial")
        self.assertFalse(persist)
        self.assertGreater(self.plans.trial_days_remaining(row, self.now), 13)

    def test_student_access_does_not_expire_as_trial(self):
        expired = (self.now - timedelta(days=2)).isoformat()
        name, persist = self.plans.resolve_effective_plan(
            {"plan": "Student", "role": "user", "trial_ends_at": expired},
            self.now,
        )
        self.assertEqual(name, "Student")
        self.assertFalse(persist)
        self.assertTrue(self.plans.get_plan(name)["can_create_analyses"])
        self.assertEqual(self.plans.get_plan(name)["price"], "$0")

    def test_expired_trial_is_not_starter(self):
        expired = (self.now - timedelta(minutes=1)).isoformat()
        name, persist = self.plans.resolve_effective_plan(
            {"plan": "Trial", "trial_ends_at": expired},
            self.now,
        )
        self.assertEqual(name, "Trial expired")
        self.assertTrue(persist)
        plan = self.plans.get_plan(name)
        self.assertFalse(plan["can_create_analyses"])
        self.assertEqual(plan["ai_credits"], 0)
        allowed, message = self.plans.validate_bom_against_plan([object()], plan, 0)
        self.assertFalse(allowed)
        self.assertIn("view and download", message)
        self.assertNotIn("now on Starter", message)

    def test_missing_trial_end_does_not_lock_an_active_trial(self):
        name, persist = self.plans.resolve_effective_plan({"plan": "Trial"}, self.now)
        self.assertEqual(name, "Trial")
        self.assertFalse(persist)

    def test_grandfathered_beta_remains_usable_without_stripe_customer(self):
        for stored in ("Starter", "free", "Grandfathered beta", ""):
            name, persist = self.plans.resolve_effective_plan(
                {"plan": stored, "role": "user"},
                self.now,
            )
            self.assertEqual(name, "Grandfathered beta", stored)
            self.assertFalse(persist)
            plan = self.plans.get_plan(name)
            self.assertTrue(plan["can_create_analyses"])
            self.assertEqual(plan["monthly_bom_limit"], 10)
            self.assertEqual(self.plans.plan_display_label(name), "Beta access")
            self.assertNotEqual(plan["price"], "$29/mo")

    def test_customer_id_alone_does_not_confirm_paid_starter(self):
        name, _persist = self.plans.resolve_effective_plan(
            {"plan": "Starter", "stripe_customer_id": "cus_only"},
            self.now,
        )
        self.assertEqual(name, "Grandfathered beta")

    def test_confirmed_subscription_shows_paid_starter(self):
        name, _persist = self.plans.resolve_effective_plan(
            {
                "plan": "Starter",
                "stripe_customer_id": "cus_paid",
                "stripe_subscription_status": "active",
            },
            self.now,
        )
        self.assertEqual(name, "Starter")
        self.assertEqual(self.plans.plan_display_label(name), "Starter")
        self.assertEqual(self.plans.get_plan(name)["price"], "$29/mo")

    def test_stale_stripe_identifiers_do_not_grant_paid_access(self):
        stale_ids = {
            "stripe_customer_id": "cus_old",
            "stripe_subscription_id": "sub_old",
            "stripe_price_id": "price_old",
        }
        for stored in ("Starter", "Professional", "Business"):
            name, persist = self.plans.resolve_effective_plan(
                {"plan": stored, **stale_ids},
                self.now,
            )
            self.assertEqual(name, "Subscription inactive", stored)
            self.assertFalse(persist)
            self.assertFalse(self.plans.get_plan(name)["can_create_analyses"])
            self.assertFalse(self.plans.stripe_subscription_confirmed({"plan": stored, **stale_ids}))

    def test_canceled_unpaid_and_incomplete_are_not_paid_access(self):
        for status in ("canceled", "cancelled", "unpaid", "incomplete", "incomplete_expired"):
            for stored in ("Starter", "Professional", "Business"):
                user = {
                    "plan": stored,
                    "stripe_customer_id": "cus_lapsed",
                    "stripe_subscription_id": "sub_lapsed",
                    "stripe_price_id": "price_lapsed",
                    "stripe_subscription_status": status,
                }
                name, _persist = self.plans.resolve_effective_plan(user, self.now)
                self.assertEqual(name, "Subscription inactive", f"{stored}/{status}")
                self.assertFalse(self.plans.paid_status_entitles(status))
                self.assertFalse(self.plans.get_plan(name)["can_create_analyses"])

    def test_past_due_has_no_grace_period(self):
        self.assertIsNone(self.plans.PAST_DUE_GRACE_PERIOD)
        self.assertFalse(self.plans.paid_status_entitles("past_due"))
        self.assertEqual(
            self.plans.PAID_ENTITLING_STATUSES,
            frozenset({"active", "trialing"}),
        )
        name, _persist = self.plans.resolve_effective_plan(
            {
                "plan": "Professional",
                "stripe_customer_id": "cus_due",
                "stripe_subscription_id": "sub_due",
                "stripe_price_id": "price_pro",
                "stripe_subscription_status": "past_due",
            },
            self.now,
        )
        self.assertEqual(name, "Subscription inactive")
        self.assertFalse(self.plans.get_plan(name)["can_create_analyses"])

    def test_active_and_trialing_status_grant_the_stored_paid_plan(self):
        for status in ("active", "trialing"):
            for stored, price in (
                ("Starter", "$29/mo"),
                ("Professional", "$99/mo"),
                ("Business", "$299/mo"),
            ):
                name, _persist = self.plans.resolve_effective_plan(
                    {"plan": stored, "stripe_subscription_status": status},
                    self.now,
                )
                self.assertEqual(name, stored, status)
                self.assertEqual(self.plans.get_plan(name)["price"], price)
                self.assertTrue(self.plans.get_plan(name)["can_create_analyses"])

    def test_missing_status_on_professional_or_business_is_not_paid(self):
        for stored in ("Professional", "Business"):
            name, _persist = self.plans.resolve_effective_plan({"plan": stored}, self.now)
            self.assertEqual(name, "Subscription inactive")
            self.assertFalse(self.plans.get_plan(name)["can_create_analyses"])

    def test_grandfathered_beta_stays_usable_with_absent_stripe_fields(self):
        name, persist = self.plans.resolve_effective_plan(
            {
                "plan": "Grandfathered beta",
                "stripe_customer_id": "",
                "stripe_subscription_id": "",
                "stripe_price_id": "",
                "stripe_subscription_status": "",
            },
            self.now,
        )
        self.assertEqual((name, persist), ("Grandfathered beta", False))
        self.assertTrue(self.plans.get_plan(name)["can_create_analyses"])
        self.assertEqual(self.plans.plan_display_label(name), "Beta access")

    def test_admin_bypass_is_unchanged(self):
        name, persist = self.plans.resolve_effective_plan(
            {"role": "admin", "plan": "Trial expired"},
            self.now,
        )
        self.assertEqual((name, persist), ("Enterprise", False))


class CheckoutMetadataTests(unittest.TestCase):
    def test_starter_professional_and_business_metadata(self):
        from src.plans import checkout_metadata

        self.assertEqual(
            checkout_metadata("user-9", "Starter"),
            {"user_id": "user-9", "cadivor_plan": "starter"},
        )
        self.assertEqual(
            checkout_metadata("user-9", "Professional")["cadivor_plan"],
            "professional",
        )
        self.assertEqual(
            checkout_metadata("user-9", "Business")["cadivor_plan"],
            "business",
        )
        with self.assertRaises(ValueError):
            checkout_metadata("user-9", "Enterprise")
        with self.assertRaises(ValueError):
            checkout_metadata("user-9", "Trial expired")

    def test_checkout_session_attaches_metadata_to_session_and_subscription(self):
        _install_stripe_stub()
        sys.modules.pop("src.stripe_helper", None)
        import src.stripe_helper as helper

        helper.stripe.api_key = "sk_test"
        helper.stripe.checkout.Session.create = MagicMock(
            return_value=types.SimpleNamespace(url="https://checkout.stripe.com/c/pay/cs_test")
        )
        url = helper.create_checkout_session(
            "price_starter",
            "user@example.com",
            "user-9",
            "https://app.example/?checkout=success",
            "https://app.example/?checkout=cancel",
            cadivor_plan="starter",
        )
        self.assertIn("checkout.stripe.com", url)
        kwargs = helper.stripe.checkout.Session.create.call_args.kwargs
        expected = {"user_id": "user-9", "cadivor_plan": "starter"}
        self.assertEqual(kwargs["metadata"], expected)
        self.assertEqual(kwargs["subscription_data"]["metadata"], expected)
        self.assertEqual(kwargs["line_items"][0]["price"], "price_starter")

    def test_plan_mapping_uses_metadata_then_price_id_and_does_not_guess(self):
        from src.plans import plan_from_checkout_metadata

        prices = {
            "Starter": "price_starter",
            "Professional": "price_pro",
            "Business": "price_biz",
        }
        self.assertEqual(
            plan_from_checkout_metadata({"cadivor_plan": "starter", "user_id": "u"}),
            "Starter",
        )
        self.assertEqual(
            plan_from_checkout_metadata({}, price_id="price_pro", price_ids=prices),
            "Professional",
        )
        self.assertIsNone(
            plan_from_checkout_metadata({"cadivor_plan": "enterprise"}, price_id="price_unknown")
        )

    def test_self_serve_checkout_does_not_downgrade_or_sell_enterprise(self):
        from src.plans import may_self_serve_checkout

        self.assertTrue(may_self_serve_checkout("Trial", "Starter"))
        self.assertTrue(may_self_serve_checkout("Trial expired", "Business"))
        self.assertTrue(may_self_serve_checkout("Grandfathered beta", "Starter"))
        self.assertFalse(may_self_serve_checkout("Professional", "Starter"))
        self.assertFalse(may_self_serve_checkout("Enterprise", "Business"))
        self.assertFalse(may_self_serve_checkout("Starter", "Enterprise"))


class GrandfatherMigrationContractTests(unittest.TestCase):
    def test_migration_is_proposed_not_applied_and_is_idempotent(self):
        sql = (
            ROOT / "supabase" / "migrations" / "20260912_grandfather_unpaid_starter.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("Do not apply until approved", sql)
        self.assertIn("plan = 'Grandfathered beta'", sql)
        self.assertIn("plan_grandfather_source", sql)
        self.assertIn("stripe_customer_id", sql)
        self.assertIn("stripe_subscription_id", sql)
        self.assertIn("in ('starter', 'free')", sql)
        self.assertIn("plan_grandfather_source is null", sql)
        self.assertIn("Reverse", sql)


class PortalAndFailureRegressionTests(unittest.TestCase):
    def test_portal_still_excludes_admins_and_does_not_mutate_plan(self):
        helper = (ROOT / "src" / "stripe_helper.py").read_text(encoding="utf-8")
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("customer_may_manage_billing", helper)
        self.assertIn('str(role or "").strip().lower() == "admin"', helper)
        self.assertIn("webhook remains the source of truth", helper)
        self.assertNotIn("invoice.payment_failed", runtime)
        self.assertNotIn('update({"plan": "Starter"})', runtime)
        self.assertIn('update({"plan": "Trial expired"})', runtime)


if __name__ == "__main__":
    unittest.main()
