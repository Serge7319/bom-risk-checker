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
        if "data-monthly-price" in attrs:
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

    def test_approved_monthly_and_annual_marketing_prices(self):
        self.assertEqual(
            self.parser.annual_prices,
            {"$29": "$296", "$99": "$1,010", "$299": "$3,050"},
        )
        self.assertEqual(self.parser.billing_modes, {"monthly", "annual"})

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

    def test_application_lists_every_approved_annual_price(self):
        for annual_price in ("$296", "$1,010", "$3,050"):
            self.assertIn(f'"annual_price": "{annual_price}"', self.runtime)

    def test_annual_toggle_updates_displayed_prices(self):
        self.assertIn("b.dataset.billing === 'annual'", self.javascript)
        self.assertIn("price.dataset.annualPrice", self.javascript)
        self.assertIn("price.dataset.monthlyPrice", self.javascript)

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
