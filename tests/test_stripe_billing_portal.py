"""Stripe Billing Portal helper unit tests."""
from __future__ import annotations

import re
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

    def _settings_block(self) -> str:
        settings_start = self.runtime.find('app_mode == "Settings"')
        settings_end = self.runtime.find(
            "# ---------- Workspace ----------",
            settings_start,
        )
        self.assertGreater(settings_start, 0)
        self.assertGreater(settings_end, settings_start)
        return self.runtime[settings_start:settings_end]

    def _billing_block(self) -> str:
        start = self.runtime.find("Customer self-service portal")
        end = self.runtime.find(
            "stop_authenticated_page()",
            start,
        )
        self.assertGreater(start, 0)
        self.assertGreater(end, start)
        return self.runtime[start:end]

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
        billing_block = self._billing_block()
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
        # Portal session lands in on_click before the next run; no auto-redirect.
        self.assertNotIn("st.rerun()", billing_block)
        self.assertNotIn("location.replace", billing_block)
        self.assertNotIn("window.location", billing_block)
        self.assertIn("portal_ready = bool(", billing_block)
        # Ineligible / mismatched paths must clear both keys.
        self.assertGreaterEqual(
            billing_block.count("_clear_billing_portal_session_state()"),
            2,
        )

    def test_settings_uses_persistent_button_tabs_not_radio_or_native_tabs(self):
        """Settings sections persist via keyed buttons — never st.radio circles."""
        settings_block = self._settings_block()

        self.assertIn("settings_active_tab", settings_block)
        self.assertIn('"settings_tab_profile"', settings_block)
        self.assertIn('"settings_tab_preferences"', settings_block)
        self.assertIn('"settings_tab_workspace"', settings_block)
        self.assertIn('"settings_tab_security"', settings_block)
        self.assertIn('"settings_tab_billing"', settings_block)
        self.assertIn("key=_settings_tab_keys[tab_label]", settings_block)
        self.assertIn("on_click=_set_settings_active_tab", settings_block)
        self.assertIn('type="primary" if is_active_tab else "secondary"', settings_block)
        # Compact left-aligned segmented group; keyed buttons persist Billing.
        self.assertIn('key="cv_settings_nav"', settings_block)
        self.assertIn('horizontal=True', settings_block)
        self.assertIn('horizontal_alignment="left"', settings_block)
        self.assertIn('width="content"', settings_block)
        self.assertNotIn(
            'st.columns([1, 1, 1, 1, 1, 8], gap="small")',
            settings_block,
        )
        self.assertNotIn(
            "st.columns(len(_settings_tab_options), gap=\"small\")",
            settings_block,
        )
        self.assertNotIn("use_container_width=True,\n                    on_click=_set_settings_active_tab", settings_block)
        for label in (
            "Profile",
            "Preferences",
            "Workspace",
            "Security",
            "Billing",
        ):
            self.assertIn(f'"{label}"', settings_block)

        # No radio navigation or radio-circle CSS/markup path in Settings.
        # horizontal=True is the compact segmented tab group, not st.radio.
        self.assertNotIn("st.radio(", settings_block)
        self.assertNotIn("stRadio", settings_block)
        self.assertNotIn('data-baseweb="radio"', settings_block)
        self.assertNotIn("role=\"radiogroup\"", settings_block)
        self.assertNotIn("[role=\"radiogroup\"]", settings_block)
        self.assertNotIn("label[data-baseweb=\"radio\"]", settings_block)
        self.assertNotIn(".st-key-settings_active_tab", settings_block)

        # Native tabs reset to Profile on every button click — must not drive Settings.
        self.assertNotIn("st.tabs(", settings_block)
        self.assertNotIn("with profile_tab", settings_block)
        self.assertNotIn("with billing_tab", settings_block)
        self.assertIn('elif settings_tab == "Billing":', settings_block)

        # Manage billing must not reset the Settings section selection.
        manage_block = settings_block[
            settings_block.find("def _start_billing_portal_session") : settings_block.find(
                "View Plans"
            )
        ]
        self.assertNotIn(
            'settings_active_tab"] = "Profile"',
            manage_block,
        )
        self.assertNotIn(
            "settings_active_tab'] = 'Profile'",
            manage_block,
        )
        self.assertNotIn("st.rerun()", manage_block)

    def test_manage_and_open_portal_are_mutually_exclusive(self):
        """After portal session creation, only Open renders — never Manage alongside it."""
        billing_block = self._billing_block()
        self.assertIn("on_click=_start_billing_portal_session", billing_block)
        self.assertIn("def _start_billing_portal_session()", billing_block)
        self.assertIn("if portal_ready:", billing_block)

        # Open is nested under portal_ready; Manage is nested under the else branch.
        ready_idx = billing_block.find("if portal_ready:")
        open_idx = billing_block.find("Open secure billing portal", ready_idx)
        else_idx = billing_block.find("\n                    else:", ready_idx)
        manage_idx = billing_block.find('"Manage billing"', else_idx)
        self.assertGreater(open_idx, ready_idx)
        self.assertGreater(else_idx, open_idx)
        self.assertGreater(manage_idx, else_idx)

        # Same-run dual render path must be gone.
        self.assertNotIn("portal_url = created_url", billing_block)
        self.assertNotIn(
            "portal_customer = stored_stripe_customer_id",
            billing_block[manage_idx:],
        )

    def test_billing_portal_link_button_has_scoped_primary_override(self):
        """Scoped billing-panel link_button is primary; global link style stays."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        premium_css = (
            root / "src" / "assets" / "css" / "premium_interactions.css"
        ).read_text(encoding="utf-8")
        # Global generic rule must remain (text-link styling for all other link buttons).
        self.assertRegex(
            premium_css,
            r'section\[data-testid="stMain"\]\s*\.stLinkButton\s*>\s*a\s*\{',
        )
        self.assertIn("background:transparent!important", premium_css.replace(" ", ""))

        settings_block = self._settings_block()
        billing_block = self._billing_block()
        # Streamlit 1.37.1 does not accept key= on st.link_button.
        open_call = billing_block[
            billing_block.find("st.link_button(") : billing_block.find(
                ")",
                billing_block.find("Open secure billing portal"),
            )
            + 1
        ]
        self.assertIn("Open secure billing portal", open_call)
        self.assertNotIn("key=", open_call)
        self.assertNotIn("settings_open_billing_portal", settings_block)
        # Streamlit 1.37: support both wrapper>a and anchor-as-testid forms.
        self.assertIn(
            '[data-testid="stVerticalBlockBorderWrapper"]:has(.cv-billing-actions__label) .stLinkButton > a',
            self.runtime,
        )
        self.assertIn(
            '[data-testid="stVerticalBlockBorderWrapper"]:has(.cv-billing-actions__label) a[data-testid="stLinkButton"]',
            self.runtime,
        )
        self.assertIn(
            '[data-testid="stVerticalBlockBorderWrapper"]:has(.cv-billing-actions__label) .stLinkButton > a:hover',
            self.runtime,
        )
        self.assertIn(
            '[data-testid="stVerticalBlockBorderWrapper"]:has(.cv-billing-actions__label) a[data-testid="stLinkButton"]:hover',
            self.runtime,
        )
        # Do not leave the old nested-only selector as the sole rule.
        self.assertNotRegex(
            self.runtime,
            r'\[data-testid="stVerticalBlockBorderWrapper"\]:has\(\.cv-billing-actions__label\)\s*\[data-testid="stLinkButton"\]\s+a\s*\{',
        )
        compact_runtime = re.sub(r"\s+", "", self.runtime)
        self.assertIn("background:#2563EB!important", compact_runtime)
        self.assertIn("color:#FFFFFF!important", compact_runtime)
        self.assertIn("width:100%!important", compact_runtime)
        # View Plans stays secondary.
        self.assertIn('key="settings_view_plans"', settings_block)
        self.assertIn('cadivor_button_wrap("secondary")', settings_block)

    def test_portal_errors_are_customer_safe(self):
        billing_block = self._billing_block()
        self.assertIn("Billing management could not be opened.", billing_block)
        self.assertIn("settings_billing_portal_error", billing_block)
        self.assertNotIn("Billing portal error:", billing_block)
        self.assertNotIn("{e}", billing_block)
        self.assertNotIn("{exc}", billing_block)
        self.assertNotIn("st.rerun()", billing_block)

    def test_helper_does_not_accept_browser_customer_id_parameterization(self):
        self.assertIn("never from query params", self.helper.casefold())
        self.assertIn(
            "stripe.billing_portal.Session.create",
            self.helper,
        )


if __name__ == "__main__":
    unittest.main()
