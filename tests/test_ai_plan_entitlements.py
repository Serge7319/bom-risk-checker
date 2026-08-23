"""Regression coverage for the AI access portion of Cadivor plan enforcement."""

from datetime import datetime, timedelta, timezone
import unittest

from src.services.ai_entitlements import consume_ai_credits, get_ai_usage_status


class AIPlanEntitlementTests(unittest.TestCase):
    def test_student_and_starter_do_not_receive_unpurchased_ai_credits(self):
        for plan_name in ("Student", "Starter"):
            status = get_ai_usage_status({}, {"id": plan_name, "plan": plan_name})
            self.assertEqual(status.allowance, 0)
            self.assertFalse(status.can_use)

    def test_paid_plan_uses_the_canonical_plan_allowance(self):
        status = get_ai_usage_status({}, {"id": "pro", "plan": "Professional"})
        self.assertEqual(status.allowance, 500)
        self.assertTrue(status.can_use)

    def test_expired_trial_falls_back_to_starter_entitlements(self):
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        status = get_ai_usage_status(
            {}, {"id": "expired-trial", "plan": "Trial", "trial_ends_at": expired}
        )
        self.assertEqual(status.plan, "Starter")
        self.assertEqual(status.allowance, 0)

    def test_admin_bypasses_ai_credits_without_consuming_them(self):
        state = {}
        before = get_ai_usage_status(state, {"id": "admin", "role": "admin", "plan": "Student"})
        after = consume_ai_credits(state, {"id": "admin", "role": "admin", "plan": "Student"})
        self.assertTrue(before.is_admin)
        self.assertTrue(after.can_use)
        self.assertEqual(state, {})


if __name__ == "__main__":
    unittest.main()
