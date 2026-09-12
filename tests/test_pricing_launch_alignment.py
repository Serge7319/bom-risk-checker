"""Guard the approved launch prices across marketing and application surfaces."""

import importlib.util
import pathlib
import unittest
from html.parser import HTMLParser


ROOT = pathlib.Path(__file__).resolve().parents[1]


class MarketingPricingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.annual_prices = {}
        self.billing_modes = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-monthly-price" in attrs and "data-annual-price" in attrs:
            self.annual_prices[attrs["data-monthly-price"]] = attrs["data-annual-price"]
        if "data-billing" in attrs:
            self.billing_modes.add(attrs["data-billing"])


class PricingLaunchAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.marketing = (ROOT / "marketing-web" / "index.html").read_text()
        cls.runtime = (ROOT / "src" / "authenticated_runtime.py").read_text()
        cls.javascript = (ROOT / "marketing-web" / "app.js").read_text()
        cls.styles = (ROOT / "marketing-web" / "styles.css").read_text()
        parser = MarketingPricingParser()
        parser.feed(cls.marketing)
        cls.parser = parser
        spec = importlib.util.spec_from_file_location("cadivor_launch_plans", ROOT / "src" / "plans.py")
        cls.plans_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.plans_module)

    def test_monthly_catalog_does_not_advertise_unpublished_annual_prices(self):
        pricing = self.marketing.split('data-page="pricing"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("Save 15%", pricing)
        self.assertNotIn("data-annual-price", pricing)
        self.assertNotIn("data-billing=\"annual\"", pricing)
        self.assertIn("$29<small>/month</small>", pricing)
        self.assertIn("$99<small>/month</small>", pricing)
        self.assertIn("$299<small>/month</small>", pricing)
        self.assertNotIn('annual_price": "$296"', self.runtime)
        self.assertNotIn("Save 15%", self.runtime)
        self.assertNotIn("$1,010", self.runtime)
        self.assertNotIn("$3,050", self.runtime)

    def test_annual_line_requires_a_configured_price_id_and_amount(self):
        from src.plans import annual_price_line

        self.assertEqual(annual_price_line("Starter"), "")
        self.assertEqual(annual_price_line("Professional", price_id="price_annual_pro"), "")
        self.assertEqual(annual_price_line("Business", price_id="", amount="$3,050"), "")
        self.assertEqual(
            annual_price_line("Professional", price_id="price_annual_pro", amount="$1,010"),
            "$1,010 / year",
        )
        self.assertEqual(
            annual_price_line("Starter", price_id="price_annual_starter", amount="Save 15%"),
            "",
        )

    def test_student_marketing_and_enforcement_match(self):
        student = self.plans_module.PLANS["Student"]
        self.assertEqual(student["monthly_bom_limit"], 5)
        self.assertEqual(student["max_parts_per_bom"], 50)
        self.assertIn("5 BOM analyses/month", self.marketing)
        self.assertIn("50 components/BOM", self.marketing)
        self.assertIn('"5 BOM analyses per month"', self.runtime)
        self.assertIn('"Up to 50 components per BOM"', self.runtime)

    def test_starter_marketing_and_enforcement_match(self):
        starter = self.plans_module.PLANS["Starter"]
        self.assertEqual(starter["price"], "$29/mo")
        self.assertEqual(starter["monthly_bom_limit"], 10)
        self.assertEqual(starter["max_parts_per_bom"], 100)
        self.assertIn("10 BOM analyses/month", self.marketing)
        self.assertIn("100 components/BOM", self.marketing)

    def test_application_escapes_currency_before_markdown_rendering(self):
        paid_rendering = self.runtime.split("paid_plans = [", 1)[1]
        self.assertIn('display_price = html.escape(plan["price"]).replace("$", "&#36;")', self.runtime)
        self.assertIn("annual_price_line(plan[\"name\"])", paid_rendering)
        self.assertIn('<div class="cv311-price">{display_price}', self.runtime)
        self.assertNotIn("Save 15%", paid_rendering)
        self.assertNotIn('"annual_price"', paid_rendering)
        self.assertNotIn('<div class="cv311-price">{plan["price"]}', paid_rendering)

    def test_higher_tiers_explicitly_include_lower_tiers(self):
        self.assertIn('class="plan-includes">Everything in Starter, plus', self.marketing)
        self.assertIn('class="plan-includes">Everything in Professional, plus', self.marketing)
        self.assertIn('class="plan-includes">Everything in Business, plus', self.marketing)
        self.assertIn('"Everything in Starter"', self.runtime)
        self.assertIn('"Supplier intelligence and alternative search"', self.runtime)
        self.assertIn('"PDF and CSV reports"', self.runtime)

    def test_updated_pricing_stylesheet_bypasses_stale_browser_cache(self):
        self.assertIn('styles.css?v=1.0-pricing-layout2', self.marketing)
        self.assertIn('.pricing-grid { display: grid; grid-template-columns: repeat(5,minmax(0,1fr))', self.styles)

    def test_annual_toggle_is_inert_without_a_configured_annual_price(self):
        self.assertIn("if (!price.dataset.annualPrice) return;", self.javascript)
        self.assertNotIn("data-annual-price", self.marketing)
        self.assertNotIn("Save 15%", self.marketing)

    def test_five_plan_layout_and_comparison(self):
        self.assertIn('grid-template-columns: repeat(5, minmax(0, 1fr))', self.styles)
        self.assertIn('grid-template-columns: 1.4fr repeat(5,1fr)', self.styles)
        pricing = self.marketing.split('data-page="pricing"', 1)[1].split('</section>', 1)[0]
        for name in ("Student", "Starter", "Professional", "Business", "Enterprise"):
            self.assertIn(f"<span>{name}</span>", pricing)
        self.assertIn('<article class="featured"><em>MOST POPULAR</em><span>Professional</span>', pricing)

    def test_existing_fourteen_day_trial_remains_available(self):
        self.assertIn("14-day free trial", self.marketing)
        self.assertIn('"name": "Free Trial"', self.runtime)
        self.assertIn('"price": "14 days"', self.runtime)


if __name__ == "__main__":
    unittest.main()
