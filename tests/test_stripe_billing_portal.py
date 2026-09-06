"""Stripe Billing Portal helper unit tests."""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _install_stripe_stub() -> types.ModuleType:
    """Provide a minimal stripe module so unit tests do not need the SDK installed."""
    existing = sys.modules.get("stripe")
    if existing is not None and hasattr(existing, "billing_portal"):
        return existing

    stripe = types.ModuleType("stripe")
    stripe.api_key = None
    billing_portal = types.ModuleType("stripe.billing_portal")
    session_cls = types.SimpleNamespace(create=MagicMock())
    billing_portal.Session = session_cls
    checkout = types.ModuleType("stripe.checkout")
    checkout.Session = types.SimpleNamespace(create=MagicMock())
    stripe.billing_portal = billing_portal
    stripe.checkout = checkout
    sys.modules["stripe"] = stripe
    sys.modules["stripe.billing_portal"] = billing_portal
    sys.modules["stripe.checkout"] = checkout
    return stripe


class StripeBillingPortalHelperTests(unittest.TestCase):
    def setUp(self):
        _install_stripe_stub()
        sys.modules.pop("src.stripe_helper", None)
        import src.stripe_helper as stripe_helper

        self.helper = stripe_helper
        self.helper.stripe.api_key = "sk_test_portal"
        self.helper.stripe.billing_portal.Session.create = MagicMock()

    def test_create_billing_portal_session_passes_customer_and_return_url(self):
        fake_session = types.SimpleNamespace(
            url="https://billing.stripe.com/p/session/test_123"
        )
        self.helper.stripe.billing_portal.Session.create.return_value = fake_session

        url = self.helper.create_billing_portal_session(
            "cus_abc123",
            "https://app.cadivor.com/?page=Settings",
        )

        self.assertEqual(url, "https://billing.stripe.com/p/session/test_123")
        self.helper.stripe.billing_portal.Session.create.assert_called_once_with(
            customer="cus_abc123",
            return_url="https://app.cadivor.com/?page=Settings",
        )

    def test_create_billing_portal_session_rejects_empty_customer(self):
        with self.assertRaises(ValueError):
            self.helper.create_billing_portal_session(
                "  ",
                "https://app.cadivor.com/?page=Settings",
            )
        self.helper.stripe.billing_portal.Session.create.assert_not_called()

    def test_create_billing_portal_session_calls_ensure_api_key(self):
        fake_session = types.SimpleNamespace(url="https://billing.stripe.com/p/session/x")
        self.helper.stripe.billing_portal.Session.create.return_value = fake_session
        with patch.object(self.helper, "_ensure_stripe_api_key") as ensure:
            self.helper.create_billing_portal_session(
                "cus_1",
                "https://app.example.com/?page=Settings",
            )
        ensure.assert_called_once_with()

    def test_customer_may_manage_billing_gates(self):
        self.assertTrue(
            self.helper.customer_may_manage_billing(
                role="member",
                stripe_customer_id="cus_paid",
            )
        )
        self.assertFalse(
            self.helper.customer_may_manage_billing(
                role="member",
                stripe_customer_id="",
            )
        )
        self.assertFalse(
            self.helper.customer_may_manage_billing(
                role="admin",
                stripe_customer_id="cus_paid",
            )
        )
        self.assertFalse(
            self.helper.customer_may_manage_billing(
                role="Admin",
                stripe_customer_id="cus_paid",
            )
        )


class StripeBillingPortalUiContractTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        self.runtime = (root / "src" / "authenticated_runtime.py").read_text(
            encoding="utf-8"
        )
        self.helper = (root / "src" / "stripe_helper.py").read_text(encoding="utf-8")

    def test_settings_billing_tab_wires_portal_for_customers_only(self):
        self.assertIn('"Manage billing"', self.runtime)
        self.assertIn("create_billing_portal_session", self.runtime)
        self.assertIn("customer_may_manage_billing", self.runtime)
        self.assertIn("stripe_customer_id", self.runtime)
        self.assertIn('app_url("", page="Settings")', self.runtime)
        self.assertIn("Open secure billing portal", self.runtime)
        self.assertIn(
            "Manage payment methods, view invoices, or cancel your subscription securely through Stripe.",
            self.runtime,
        )
        self.assertNotIn("Continue to Stripe billing portal", self.runtime)
        self.assertIn("st.container(border=True)", self.runtime)
        self.assertIn("cv-billing-actions__label", self.runtime)
        self.assertNotIn('class="cv-billing-actions"', self.runtime)
        self.assertIn(
            "No active Stripe subscription is connected to this account yet.",
            self.runtime,
        )
        self.assertNotIn("query_params.get(\"customer\"", self.runtime)
        self.assertNotIn("st.text_input(\"Stripe customer", self.runtime)

    def test_portal_session_state_requires_matching_customer_id(self):
        """Portal URL may render only when bound to the current stored customer id."""
        billing_block = self.runtime[
            self.runtime.find("Customer self-service portal") : self.runtime.find(
                "stop_authenticated_page()",
                self.runtime.find("Customer self-service portal"),
            )
        ]
        self.assertIn('portal_url_key = "settings_billing_portal_url"', billing_block)
        self.assertIn(
            'portal_customer_key = "settings_billing_portal_customer_id"',
            billing_block,
        )
        self.assertIn(
            "st.session_state[portal_customer_key] = (",
            billing_block,
        )
        self.assertIn(
            "portal_customer == stored_stripe_customer_id",
            billing_block,
        )
        self.assertIn("_clear_billing_portal_session_state()", billing_block)
        self.assertIn("Open secure billing portal", billing_block)
        self.assertIn(
            "Manage payment methods, view invoices, or cancel your subscription securely through Stripe.",
            billing_block,
        )
        self.assertNotIn("Continue to Stripe billing portal", billing_block)
        self.assertIn("st.container(border=True)", billing_block)
        self.assertIn("cv-billing-actions__label", billing_block)
        self.assertNotIn('class="cv-billing-actions"', billing_block)
        # Ineligible / mismatched paths must clear both keys.
        self.assertGreaterEqual(
            billing_block.count("_clear_billing_portal_session_state()"),
            2,
        )

    def test_portal_errors_are_customer_safe(self):
        billing_block = self.runtime[
            self.runtime.find('"Manage billing"') : self.runtime.find(
                "No active Stripe subscription is connected to this account yet."
            )
        ]
        self.assertIn("Billing management could not be opened.", billing_block)
        self.assertNotIn("Billing portal error:", billing_block)
        self.assertNotIn("{e}", billing_block)
        self.assertNotIn("{exc}", billing_block)

    def test_helper_does_not_accept_browser_customer_id_parameterization(self):
        self.assertIn("never from query params", self.helper.casefold())
        self.assertIn(
            "stripe.billing_portal.Session.create",
            self.helper,
        )


if __name__ == "__main__":
    unittest.main()
