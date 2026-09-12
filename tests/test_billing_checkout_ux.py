"""UI contracts for Settings billing checkout confirmation and compact nav."""
from __future__ import annotations

import unittest
from pathlib import Path


class BillingCheckoutUxContractTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.runtime = (root / "src" / "authenticated_runtime.py").read_text(
            encoding="utf-8"
        )
        self.laptop_css = (
            root / "src" / "assets" / "css" / "laptop_kpi_table_pass.css"
        ).read_text(encoding="utf-8")

    def _pricing_block(self) -> str:
        start = self.runtime.find('if app_mode == "Pricing":')
        end = self.runtime.find('if app_mode == "Settings":', start)
        self.assertGreater(start, 0)
        self.assertGreater(end, start)
        return self.runtime[start:end]

    def _paid_card_loop(self) -> str:
        pricing = self._pricing_block()
        start = pricing.find("paid_rows = [paid_plans[:2], paid_plans[2:]]")
        end = pricing.find("feature_rows = [", start)
        self.assertGreater(start, 0)
        self.assertGreater(end, start)
        return pricing[start:end]

    def _settings_block(self) -> str:
        start = self.runtime.find('app_mode == "Settings"')
        end = self.runtime.find("# ---------- Workspace ----------", start)
        self.assertGreater(start, 0)
        self.assertGreater(end, start)
        return self.runtime[start:end]

    def test_checkout_confirmation_is_in_card_before_features(self):
        card_loop = self._paid_card_loop()
        confirm_idx = card_loop.find("_render_plan_checkout_confirm(")
        features_idx = card_loop.find("cv311-card-features")
        self.assertGreater(confirm_idx, 0)
        self.assertGreater(features_idx, confirm_idx)
        self.assertIn('"Professional — $99/month"', card_loop)
        self.assertIn('"Business — $299/month"', card_loop)
        self.assertIn("STRIPE_PRO_PRICE_ID", card_loop)
        self.assertIn("STRIPE_BUSINESS_PRICE_ID", card_loop)
        # One plan grid only — confirmation replaces the upgrade control in-card.
        self.assertEqual(card_loop.count("paid_columns = st.columns(2"), 1)
        self.assertNotIn("_start_plan_checkout(", card_loop)

    def test_checkout_cta_is_native_primary_with_stripe_handoff_copy(self):
        pricing = self._pricing_block()
        confirm = pricing[
            pricing.find("def _render_plan_checkout_confirm") : pricing.find(
                "education_plans = ["
            )
        ]
        self.assertIn("@st.fragment", pricing[pricing.find("@st.fragment") : pricing.find("def _render_plan_checkout_confirm")])
        self.assertIn('data-testid="cv311-checkout-confirm"', confirm)
        self.assertIn(
            "You'll be redirected to Stripe to complete your subscription.",
            confirm,
        )
        self.assertIn("Continue to secure checkout →", confirm)
        self.assertIn('type="primary"', confirm)
        self.assertIn("use_container_width=True", confirm)
        self.assertIn('key=f"cv311_checkout_{plan_slug}"', confirm)
        self.assertEqual(confirm.count('st.link_button('), 1)
        self.assertIn('st.rerun(scope="fragment")', confirm)
        self.assertNotIn("_show_checkout_confirm", confirm)
        self.assertIn("create_checkout_session(", confirm)
        self.assertIn('app_checkout_url(page="Pricing", checkout="success")', confirm)
        self.assertIn('app_checkout_url(page="Pricing", checkout="cancel")', confirm)
        self.assertNotIn("window.location", confirm)
        self.assertNotIn("location.replace", confirm)
        self.assertNotIn("<a ", confirm)
        self.assertNotIn("<button", confirm)
        # Ready state is only the keyed confirmation. No same-run fallback link.
        rerun_tail = confirm[confirm.find('st.rerun(scope="fragment")') :]
        self.assertNotIn("st.link_button", rerun_tail)
        self.assertNotIn("cv311-checkout-confirm", rerun_tail)

    def test_checkout_link_has_scoped_primary_override(self):
        root = Path(__file__).resolve().parents[1]
        premium = (
            root / "src" / "assets" / "css" / "premium_interactions.css"
        ).read_text(encoding="utf-8")
        core = (root / "src" / "assets" / "css" / "core_premium_ui.css").read_text(
            encoding="utf-8"
        )
        for stylesheet in (premium, core):
            compact = stylesheet.replace(" ", "").replace("\n", "")
            self.assertIn(".st-key-cv311_checkout_professional", compact)
            self.assertIn(".st-key-cv311_checkout_business", compact)
            self.assertIn("background:#2563EB!important", compact)
            self.assertIn("color:#FFFFFF!important", compact)
            self.assertIn("width:100%!important", compact)
            self.assertIn("min-height:48px!important", compact)
            self.assertIn("text-decoration:none!important", compact)
        pricing = self._pricing_block().replace(" ", "").replace("\n", "")
        self.assertNotIn(
            "stVerticalBlock:has(.cv311-checkout-confirm):not(:has(.cv311-contact-sales)).stLinkButton",
            pricing,
        )

    def test_enterprise_stays_contact_sales_not_checkout(self):
        card_loop = self._paid_card_loop()
        enterprise = card_loop[card_loop.find('plan_key == "enterprise"') :]
        self.assertIn("Contact Sales", enterprise)
        self.assertIn('data-testid="cv311-contact-sales"', enterprise)
        self.assertIn('type="secondary"', enterprise)
        self.assertNotIn("create_checkout_session", enterprise)
        self.assertNotIn("Continue to secure checkout", enterprise)
        self.assertNotIn("STRIPE_", enterprise)

    def test_settings_nav_is_compact_left_aligned_segmented_group(self):
        settings = self._settings_block()
        nav = settings[
            settings.find('key="cv_settings_nav"') : settings.find(
                'settings_tab = str(st.session_state.get("settings_active_tab")'
            )
        ]
        self.assertIn("horizontal=True", nav)
        self.assertIn('horizontal_alignment="left"', nav)
        self.assertIn('width="content"', nav)
        self.assertIn("key=_settings_tab_keys[tab_label]", nav)
        self.assertIn("on_click=_set_settings_active_tab", nav)
        self.assertNotIn("st.columns(", nav)
        self.assertNotIn("use_container_width=True", nav)
        self.assertIn(".st-key-cv_settings_nav", settings)
        self.assertIn("width:max-content!important", settings.replace(" ", ""))
        self.assertIn("justify-content:flex-start!important", settings.replace(" ", ""))
        self.assertIn(":not(.st-key-cv_settings_nav)", self.laptop_css)

    def test_setup_actions_are_grouped(self):
        settings = self._settings_block()
        setup = settings[
            settings.find('key="cv_settings_setup_actions"') : settings.find(
                "migration_required ="
            )
        ]
        self.assertIn("horizontal=True", setup)
        self.assertIn('horizontal_alignment="left"', setup)
        self.assertIn("Continue Customer Setup", setup)
        self.assertIn("Dismiss setup", setup)
        self.assertLess(
            setup.find("Continue Customer Setup"),
            setup.find("Dismiss setup"),
        )
        self.assertNotIn("st.columns([1, 1, 2])", setup)

    def test_billing_tab_hero_is_plan_and_billing(self):
        settings = self._settings_block()
        self.assertIn('_settings_hero_tab == "Billing"', settings)
        self.assertIn('_settings_hero_title = "Plan & billing"', settings)
        self.assertIn("cv-customer-title", settings)
        self.assertLess(
            settings.find("_settings_hero_title"),
            settings.find('key="cv_settings_nav"'),
        )


if __name__ == "__main__":
    unittest.main()
