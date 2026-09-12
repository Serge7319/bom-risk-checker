"""Executable billing contract for the versioned stripe-webhook function.

Deno and Node are not installed here, so these tests run the Python contract
the TypeScript handler is written to follow. A source check guards the
versioned function against the old ended-status ``plan = Starter`` write.
"""
from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import plans
from src.services.stripe_webhook_billing import (
    EventStore,
    apply_event,
)

ROOT = Path(__file__).resolve().parents[1]
FUNCTION_DIR = ROOT / "supabase" / "functions" / "stripe-webhook"
NOW = datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc)
PRICE_IDS = {
    "Starter": "price_starter",
    "Professional": "price_pro",
    "Business": "price_business",
}
USER_ID = "user-1"


def _subscription(
    status,
    *,
    plan_token=None,
    price_id=None,
    user_id=USER_ID,
    subscription_id="sub_1",
    extra_metadata=None,
):
    metadata = {"user_id": user_id}
    if plan_token is not None:
        metadata["cadivor_plan"] = plan_token
    if extra_metadata:
        metadata.update(extra_metadata)
    items = {"data": []}
    if price_id is not None:
        items = {"data": [{"price": {"id": price_id}}]}
    return {
        "id": subscription_id,
        "customer": "cus_1",
        "status": status,
        "metadata": metadata,
        "items": items,
        "current_period_end": 1_790_000_000,
        "cancel_at_period_end": False,
    }


def _event(event_id, event_type, created, obj):
    return {
        "id": event_id,
        "type": event_type,
        "livemode": False,
        "created": created,
        "data": {"object": obj},
    }


def _user(plan, **extra):
    row = {"id": USER_ID, "role": "user", "plan": plan}
    row.update(extra)
    return row


class StripeWebhookBillingTests(unittest.TestCase):
    def setUp(self):
        self.store = EventStore()
        self.users = {}
        self.subscriptions = {}

    def _retrieve(self, subscription_id):
        if subscription_id not in self.subscriptions:
            raise RuntimeError(f"missing subscription {subscription_id}")
        return copy.deepcopy(self.subscriptions[subscription_id])

    def _apply(self, event, *, now=NOW):
        return apply_event(
            event,
            users=self.users,
            store=self.store,
            price_ids=PRICE_IDS,
            now=now,
            retrieve_subscription=self._retrieve,
        )

    def _put(self, plan="Grandfathered beta", **extra):
        self.users[USER_ID] = _user(plan, **extra)
        return self.users[USER_ID]

    def test_active_and_trialing_grant_only_the_mapped_paid_plan(self):
        cases = (
            ("active", "starter", "price_starter", "Starter"),
            ("trialing", "starter", "price_starter", "Starter"),
            ("active", "professional", "price_pro", "Professional"),
            ("trialing", "professional", "price_pro", "Professional"),
            ("active", "business", "price_business", "Business"),
            ("trialing", "business", "price_business", "Business"),
        )
        for index, (status, token, price_id, expected) in enumerate(cases):
            self.users.clear()
            self.store = EventStore()
            self._put("Trial")
            created = 1_700_000_000 + index
            result = self._apply(
                _event(
                    f"evt_paid_{index}",
                    "customer.subscription.updated",
                    created,
                    _subscription(status, plan_token=token, price_id=price_id),
                )
            )
            user = self.users[USER_ID]
            self.assertEqual(result["status"], 200, status)
            self.assertEqual(result["outcome"], "applied")
            self.assertEqual(user["plan"], expected)
            self.assertEqual(user["stripe_subscription_status"], status)
            self.assertEqual(user["stripe_price_id"], price_id)
            self.assertTrue(plans.stripe_subscription_confirmed(user))
            name, persist = plans.resolve_effective_plan(user, NOW)
            self.assertEqual(name, expected)
            self.assertFalse(persist)

    def test_metadata_wins_when_price_id_is_unmapped(self):
        self._put("Trial")
        result = self._apply(
            _event(
                "evt_meta_only",
                "customer.subscription.updated",
                1_700_000_100,
                _subscription("active", plan_token="professional", price_id="price_unknown"),
            )
        )
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(self.users[USER_ID]["plan"], "Professional")

    def test_price_id_is_only_the_fallback(self):
        self._put("Trial")
        result = self._apply(
            _event(
                "evt_price_fallback",
                "customer.subscription.updated",
                1_700_000_110,
                _subscription("active", price_id="price_business"),
            )
        )
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(self.users[USER_ID]["plan"], "Business")

    def test_metadata_and_price_disagreement_does_not_grant_and_can_retry(self):
        self._put("Grandfathered beta")
        result = self._apply(
            _event(
                "evt_mismatch",
                "customer.subscription.updated",
                1_700_000_200,
                _subscription("active", plan_token="professional", price_id="price_starter"),
            )
        )
        self.assertEqual(result["status"], 500)
        self.assertIn("disagree", result["error"])
        self.assertEqual(self.users[USER_ID]["plan"], "Grandfathered beta")
        self.assertNotIn("stripe_subscription_status", self.users[USER_ID])
        self.assertEqual(self.store.rows["evt_mismatch"].processing_status, "failed")

        result = self._apply(
            _event(
                "evt_mismatch",
                "customer.subscription.updated",
                1_700_000_200,
                _subscription("active", plan_token="starter", price_id="price_starter"),
            ),
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(self.users[USER_ID]["plan"], "Starter")
        self.assertTrue(plans.paid_status_entitles("active"))

    def test_unknown_price_on_entitling_status_does_not_guess_starter(self):
        self._put("Trial")
        result = self._apply(
            _event(
                "evt_unknown_price",
                "customer.subscription.updated",
                1_700_000_300,
                _subscription("active", price_id="price_not_configured"),
            )
        )
        self.assertEqual(result["status"], 500)
        self.assertEqual(self.users[USER_ID]["plan"], "Trial")
        self.assertNotEqual(self.users[USER_ID]["plan"], "Starter")
        self.assertEqual(self.store.rows["evt_unknown_price"].processing_status, "failed")

    def test_non_entitling_statuses_never_set_plan_or_starter(self):
        for status in (
            "past_due",
            "canceled",
            "unpaid",
            "incomplete",
            "incomplete_expired",
            "",
            None,
        ):
            with self.subTest(status=status):
                self.store = EventStore()
                self._put("Professional")
                before = copy.deepcopy(self.users[USER_ID])
                result = self._apply(
                    _event(
                        f"evt_{status or 'missing'}",
                        "customer.subscription.updated",
                        1_700_000_400,
                        _subscription(status, plan_token="professional", price_id="price_pro"),
                    )
                )
                user = self.users[USER_ID]
                self.assertEqual(result["outcome"], "applied")
                self.assertEqual(user["plan"], "Subscription inactive")
                self.assertNotEqual(user["plan"], before["plan"])
                self.assertNotEqual(user["plan"], "Starter")
                self.assertNotEqual(user["plan"], "Grandfathered beta")
                self.assertFalse(plans.has_grandfather_marker(user))
                self.assertEqual(user["stripe_subscription_status"], status)
                self.assertFalse(plans.paid_status_entitles(status))
                name, _persist = plans.resolve_effective_plan(user, NOW)
                self.assertEqual(name, "Subscription inactive")
                self.assertFalse(plans.get_plan(name)["can_create_analyses"])

    def test_student_trial_and_trial_expired_survive_non_paying_events(self):
        for stored in ("Student", "Trial", "Trial expired"):
            with self.subTest(plan=stored):
                self.store = EventStore()
                self._put(stored, trial_ends_at="2026-09-20T00:00:00+00:00")
                result = self._apply(
                    _event(
                        f"evt_keep_{stored}",
                        "customer.subscription.deleted",
                        1_700_000_500,
                        _subscription("canceled", plan_token="starter", price_id="price_starter"),
                    )
                )
                user = self.users[USER_ID]
                self.assertEqual(result["outcome"], "applied")
                self.assertEqual(user["plan"], stored)
                self.assertEqual(user["stripe_subscription_status"], "canceled")
                name, persist = plans.resolve_effective_plan(user, NOW)
                self.assertEqual(name, stored)
                self.assertFalse(persist)

    def test_canceled_or_failed_checkout_keeps_grandfathered_beta_usable(self):
        for status in ("canceled", "past_due", "unpaid", "incomplete", "incomplete_expired"):
            with self.subTest(status=status):
                self.store = EventStore()
                self.subscriptions.clear()
                self._put("Grandfathered beta", plan_grandfather_source="Starter")
                subscription = _subscription(status, plan_token="starter", price_id="price_starter")
                self.subscriptions[subscription["id"]] = subscription
                result = self._apply(
                    _event(
                        f"evt_beta_{status}",
                        "checkout.session.completed",
                        1_700_000_600,
                        {"subscription": subscription["id"], "customer": "cus_1"},
                    )
                )
                user = self.users[USER_ID]
                self.assertEqual(result["outcome"], "applied", status)
                self.assertEqual(user["plan"], "Grandfathered beta")
                self.assertEqual(user["plan_grandfather_source"], "Starter")
                self.assertEqual(user["stripe_subscription_id"], "sub_1")
                self.assertEqual(user["stripe_subscription_status"], status)
                name, persist = plans.resolve_effective_plan(user, NOW)
                self.assertEqual(name, "Grandfathered beta")
                self.assertFalse(persist)
                self.assertTrue(plans.get_plan(name)["can_create_analyses"])
                self.assertEqual(plans.plan_display_label(name), "Beta access")
                self.assertNotEqual(name, "Subscription inactive")

    def test_admin_billing_update_does_not_touch_the_user(self):
        self._put("Student", role="admin")
        before = copy.deepcopy(self.users[USER_ID])
        result = self._apply(
            _event(
                "evt_admin",
                "customer.subscription.updated",
                1_700_000_700,
                _subscription("active", plan_token="business", price_id="price_business"),
            )
        )
        self.assertEqual(result["outcome"], "admin_untouched")
        self.assertEqual(self.users[USER_ID], before)
        self.assertEqual(self.store.rows["evt_admin"].processing_status, "processed")

    def test_duplicate_delivery_does_not_apply_twice(self):
        self._put("Trial")
        event = _event(
            "evt_dup",
            "customer.subscription.updated",
            1_700_000_800,
            _subscription("active", plan_token="professional", price_id="price_pro"),
        )
        first = self._apply(event)
        self.users[USER_ID]["plan"] = "MARKER"
        self.users[USER_ID]["stripe_subscription_status"] = "marker-status"
        second = self._apply(event, now=NOW + timedelta(seconds=5))
        self.assertEqual(first["outcome"], "applied")
        self.assertEqual(second["status"], 200)
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.users[USER_ID]["plan"], "MARKER")
        self.assertEqual(self.users[USER_ID]["stripe_subscription_status"], "marker-status")

    def test_older_subscription_event_does_not_overwrite_a_newer_one(self):
        self._put("Trial")
        newer = self._apply(
            _event(
                "evt_new",
                "customer.subscription.updated",
                1_700_000_900,
                _subscription("active", plan_token="professional", price_id="price_pro"),
            )
        )
        older = self._apply(
            _event(
                "evt_old",
                "customer.subscription.updated",
                1_700_000_100,
                _subscription("canceled", plan_token="starter", price_id="price_starter"),
            ),
            now=NOW + timedelta(seconds=2),
        )
        user = self.users[USER_ID]
        self.assertEqual(newer["outcome"], "applied")
        self.assertEqual(older["outcome"], "skipped_stale")
        self.assertEqual(user["plan"], "Professional")
        self.assertEqual(user["stripe_subscription_status"], "active")
        self.assertEqual(self.store.rows["evt_old"].processing_status, "processed")
        retried = self._apply(
            _event(
                "evt_old",
                "customer.subscription.updated",
                1_700_000_100,
                _subscription("canceled", plan_token="starter", price_id="price_starter"),
            ),
            now=NOW + timedelta(seconds=3),
        )
        self.assertTrue(retried["duplicate"])
        self.assertEqual(user["stripe_subscription_status"], "active")

    def test_failed_apply_does_not_permanently_block_retry(self):
        self._put("Trial")
        missing = self._apply(
            _event(
                "evt_retry",
                "customer.subscription.updated",
                1_700_001_000,
                _subscription("active", plan_token="business", price_id="price_business", user_id="missing-user"),
            )
        )
        self.assertEqual(missing["status"], 500)
        self.assertEqual(self.store.rows["evt_retry"].processing_status, "failed")
        self.assertNotIn("missing-user", self.users)

        self.users["missing-user"] = _user("Trial")
        self.users["missing-user"]["id"] = "missing-user"
        retried = self._apply(
            _event(
                "evt_retry",
                "customer.subscription.updated",
                1_700_001_000,
                _subscription("active", plan_token="business", price_id="price_business", user_id="missing-user"),
            ),
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(retried["outcome"], "applied")
        self.assertEqual(self.users["missing-user"]["plan"], "Business")

    def test_active_lease_is_busy_and_expired_lease_can_be_reclaimed(self):
        self._put("Trial")
        event = _event(
            "evt_lease",
            "customer.subscription.updated",
            1_700_001_100,
            _subscription("active", plan_token="starter", price_id="price_starter"),
        )
        claim = self.store.claim(
            event_id="evt_lease",
            event_type=event["type"],
            livemode=False,
            event_created=datetime.fromtimestamp(event["created"], tz=timezone.utc),
            now=NOW,
        )
        self.assertEqual(claim, "claimed")
        busy = self._apply(event, now=NOW + timedelta(seconds=10))
        self.assertEqual(busy["status"], 500)
        self.assertTrue(busy["busy"])
        self.assertEqual(self.users[USER_ID]["plan"], "Trial")

        reclaimed = self._apply(event, now=NOW + timedelta(seconds=121))
        self.assertEqual(reclaimed["outcome"], "applied")
        self.assertEqual(self.users[USER_ID]["plan"], "Starter")

    def test_invoice_payment_failed_uses_retrieved_status_and_does_not_grant(self):
        self._put("Student")
        subscription = _subscription("past_due", plan_token="professional", price_id="price_pro")
        self.subscriptions["sub_1"] = subscription
        result = self._apply(
            _event(
                "evt_invoice_failed",
                "invoice.payment_failed",
                1_700_001_200,
                {"subscription": "sub_1", "customer": "cus_1"},
            )
        )
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(self.users[USER_ID]["plan"], "Student")
        self.assertEqual(self.users[USER_ID]["stripe_subscription_status"], "past_due")
        self.assertFalse(plans.stripe_subscription_confirmed(self.users[USER_ID]))


class GrandfatherMarkerAccessTests(unittest.TestCase):
    """Beta eligibility is plan_grandfather_source, not plan text or Stripe ids."""

    def setUp(self):
        self.store = EventStore()
        self.users = {}
        self.subscriptions = {}

    def _retrieve(self, subscription_id):
        return copy.deepcopy(self.subscriptions[subscription_id])

    def _apply(self, event, *, created_offset=0):
        return apply_event(
            event,
            users=self.users,
            store=self.store,
            price_ids=PRICE_IDS,
            now=NOW + timedelta(seconds=created_offset),
            retrieve_subscription=self._retrieve,
        )

    def _apply_status(self, event_id, status, token, price_id, created, *, user_id=USER_ID):
        return self._apply(
            _event(
                event_id,
                "customer.subscription.updated",
                created,
                _subscription(status, plan_token=token, price_id=price_id, user_id=user_id),
            ),
            created_offset=created - 1_700_000_000,
        )

    def test_pre_existing_unpaid_starter_is_grandfathered_only_by_the_migration(self):
        unpaid = {
            "plan": "Starter",
            "stripe_customer_id": "",
            "stripe_subscription_id": "",
            "stripe_price_id": "",
            "stripe_subscription_status": "",
        }
        unmarked, _persist = plans.resolve_effective_plan(unpaid, NOW)
        self.assertEqual(unmarked, "Subscription inactive")
        self.assertFalse(plans.has_grandfather_marker(unpaid))

        marked = {
            "plan": "Grandfathered beta",
            "plan_grandfather_source": "Starter",
            **{key: unpaid[key] for key in unpaid if key != "plan"},
        }
        name, persist = plans.resolve_effective_plan(marked, NOW)
        self.assertEqual(name, "Grandfathered beta")
        self.assertFalse(persist)
        self.assertTrue(plans.get_plan(name)["can_create_analyses"])
        self.assertEqual(plans.plan_display_label(name), "Beta access")

        sql = (
            ROOT / "supabase" / "migrations" / "20260912_grandfather_unpaid_starter.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("in ('starter', 'free')", sql)
        self.assertIn("plan = 'Grandfathered beta'", sql)
        self.assertIn("plan_grandfather_source = plan", sql)
        self.assertIn("plan_grandfather_source is null", sql)
        self.assertIn("Do not apply until approved", sql)

    def test_grandfathered_beta_returns_after_paid_starter_is_canceled(self):
        self.users[USER_ID] = _user(
            "Grandfathered beta",
            plan_grandfather_source="Starter",
        )
        paid = self._apply_status("evt_gf_paid", "active", "starter", "price_starter", 1_700_002_000)
        user = self.users[USER_ID]
        self.assertEqual(paid["outcome"], "applied")
        self.assertEqual(user["plan"], "Starter")
        self.assertEqual(user["plan_grandfather_source"], "Starter")
        self.assertEqual(plans.resolve_effective_plan(user, NOW)[0], "Starter")

        canceled = self._apply_status(
            "evt_gf_cancel",
            "canceled",
            "starter",
            "price_starter",
            1_700_002_100,
        )
        user = self.users[USER_ID]
        self.assertEqual(canceled["outcome"], "applied")
        self.assertEqual(user["plan"], "Grandfathered beta")
        self.assertEqual(user["plan_grandfather_source"], "Starter")
        self.assertEqual(user["stripe_subscription_status"], "canceled")
        self.assertTrue(user["stripe_subscription_id"])
        name, persist = plans.resolve_effective_plan(user, NOW)
        self.assertEqual(name, "Grandfathered beta")
        self.assertFalse(persist)
        self.assertTrue(plans.get_plan(name)["can_create_analyses"])
        self.assertNotEqual(name, "Subscription inactive")

    def test_new_paid_starter_non_paying_status_is_subscription_inactive(self):
        for index, status in enumerate(
            ("canceled", "past_due", "unpaid", "incomplete", "incomplete_expired")
        ):
            with self.subTest(status=status):
                self.store = EventStore()
                self.users[USER_ID] = _user("Trial")
                created = 1_700_003_000 + (index * 10)
                self._apply_status(
                    f"evt_new_paid_{status}",
                    "active",
                    "starter",
                    "price_starter",
                    created,
                )
                self.assertEqual(self.users[USER_ID]["plan"], "Starter")
                self.assertFalse(plans.has_grandfather_marker(self.users[USER_ID]))
                self._apply_status(
                    f"evt_new_end_{status}",
                    status,
                    "starter",
                    "price_starter",
                    created + 1,
                )
                user = self.users[USER_ID]
                self.assertEqual(user["plan"], "Subscription inactive")
                self.assertNotIn("plan_grandfather_source", user)
                self.assertEqual(user["stripe_subscription_status"], status)
                name, _persist = plans.resolve_effective_plan(user, NOW)
                self.assertEqual(name, "Subscription inactive")
                self.assertFalse(plans.get_plan(name)["can_create_analyses"])
                self.assertNotEqual(name, "Grandfathered beta")

    def test_new_paid_professional_and_business_non_paying_status_is_inactive(self):
        for plan_name, token, price_id in (
            ("Professional", "professional", "price_pro"),
            ("Business", "business", "price_business"),
        ):
            for status in ("canceled", "past_due", "unpaid", "incomplete", "incomplete_expired"):
                with self.subTest(plan=plan_name, status=status):
                    self.store = EventStore()
                    self.users[USER_ID] = _user("Trial")
                    self._apply_status("evt_up", "active", token, price_id, 1_700_004_000)
                    self.assertEqual(self.users[USER_ID]["plan"], plan_name)
                    self._apply_status("evt_down", status, token, price_id, 1_700_004_100)
                    user = self.users[USER_ID]
                    self.assertEqual(user["plan"], "Subscription inactive")
                    self.assertFalse(plans.has_grandfather_marker(user))
                    name, _persist = plans.resolve_effective_plan(user, NOW)
                    self.assertEqual(name, "Subscription inactive")
                    self.assertFalse(plans.get_plan(name)["can_create_analyses"])

    def test_plan_text_and_stripe_ids_do_not_grant_beta(self):
        labeled = {
            "plan": "Grandfathered beta",
            "stripe_customer_id": "",
            "stripe_subscription_id": "",
            "stripe_price_id": "",
            "stripe_subscription_status": "",
        }
        self.assertEqual(plans.resolve_effective_plan(labeled, NOW)[0], "Subscription inactive")
        leftover = {
            "plan": "Starter",
            "stripe_subscription_id": "sub_old",
            "stripe_price_id": "price_starter",
            "stripe_subscription_status": "canceled",
        }
        self.assertEqual(plans.resolve_effective_plan(leftover, NOW)[0], "Subscription inactive")

    def test_student_trial_and_trial_expired_are_unchanged_even_with_a_marker(self):
        for stored in ("Student", "Trial", "Trial expired"):
            with self.subTest(plan=stored):
                self.store = EventStore()
                self.users[USER_ID] = _user(
                    stored,
                    plan_grandfather_source="Starter",
                    trial_ends_at="2026-09-20T00:00:00+00:00",
                )
                result = self._apply_status(
                    f"evt_protect_{stored}",
                    "canceled",
                    "starter",
                    "price_starter",
                    1_700_005_000,
                )
                user = self.users[USER_ID]
                self.assertEqual(result["outcome"], "applied")
                self.assertEqual(user["plan"], stored)
                self.assertEqual(user["plan_grandfather_source"], "Starter")
                self.assertEqual(user["stripe_subscription_status"], "canceled")
                name, persist = plans.resolve_effective_plan(user, NOW)
                self.assertEqual(name, stored)
                self.assertFalse(persist)
                self.assertNotEqual(name, "Grandfathered beta")
                self.assertNotEqual(name, "Subscription inactive")


class StripeWebhookSourceAlignmentTests(unittest.TestCase):
    def test_versioned_function_keeps_signature_verification_and_drops_starter_demotion(self):
        index = (FUNCTION_DIR / "index.ts").read_text()
        billing = (FUNCTION_DIR / "billing.ts").read_text()
        config = (ROOT / "supabase" / "config.toml").read_text()
        combined = index + billing

        self.assertIn("constructEventAsync", index)
        self.assertIn("STRIPE_WEBHOOK_SECRET", index)
        self.assertIn("Missing Stripe signature", index)
        self.assertIn("checkout.session.completed", index)
        self.assertIn("customer.subscription.deleted", index)
        self.assertIn("invoice.payment_failed", index)
        self.assertIn("invoice.paid", index)
        self.assertIn("cadivor_claim_stripe_webhook_event", index)
        self.assertIn("cadivor_complete_stripe_webhook_event", index)
        self.assertIn("cadivor_release_stripe_webhook_event", index)
        self.assertIn("cadivor_apply_stripe_billing_snapshot", index)
        self.assertIn("cadivor_plan", billing)
        self.assertIn("disagree", billing)
        self.assertNotIn("ENDED_STATUSES", combined)
        self.assertNotIn('plan = "Starter"', combined)
        self.assertNotIn("plan = 'Starter'", combined)
        self.assertEqual(
            config.strip(),
            "[functions.stripe-webhook]\nverify_jwt = false",
        )
        sql = (
            ROOT / "supabase" / "migrations" / "20260912_stripe_webhook_event_lease.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("plan_grandfather_source", sql)
        self.assertIn("Grandfathered beta", sql)
        self.assertIn("Subscription inactive", sql)
        self.assertNotIn("v_next_plan := 'Starter'", sql)
        self.assertNotIn("plan = 'Starter'", sql)
