import ast
from pathlib import Path
import unittest

from src.email_routing import (
    BETA_EMAIL,
    BILLING_EMAIL,
    GENERAL_EMAIL,
    LEGAL_EMAIL,
    SECURITY_EMAIL,
    SUPPORT_EMAIL,
)


ROOT = Path(__file__).resolve().parents[1]


class EmailRoutingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.marketing_html = (ROOT / "marketing-web" / "index.html").read_text()
        cls.marketing_js = (ROOT / "marketing-web" / "app.js").read_text()
        cls.legacy_marketing = (ROOT / "src" / "marketing_site.py").read_text()
        cls.runtime = (ROOT / "src" / "authenticated_runtime.py").read_text()
        cls.scheduler = (ROOT / "src" / "run_scheduled_monitoring.py").read_text()
        cls.auth = (ROOT / "src" / "auth.py").read_text()
        cls.auth_recovery = (ROOT / "src" / "auth_recovery.py").read_text()
        cls.stripe_helper = (ROOT / "src" / "stripe_helper.py").read_text()
        cls.invitation_migration = (
            ROOT
            / "supabase"
            / "migrations"
            / "20260919_workspace_invitation_acceptance.sql"
        ).read_text()

    def test_public_inquiry_routes_are_explicit(self):
        self.assertIn(GENERAL_EMAIL, self.marketing_html)
        self.assertIn("CONTACT_INBOX", self.marketing_js)
        self.assertIn("resolveContactInbox", self.marketing_js)
        self.assertIn("GENERAL_EMAIL", self.legacy_marketing)
        self.assertIn(BETA_EMAIL, self.runtime)
        self.assertIn("BETA_EMAIL", self.legacy_marketing)
        self.assertIn("SUPPORT_EMAIL", self.legacy_marketing)
        self.assertIn(SECURITY_EMAIL, self.marketing_html)
        self.assertIn(LEGAL_EMAIL, self.marketing_html)
        self.assertIn("BILLING_EMAIL", self.runtime)

    def test_production_code_never_uses_resend_sandbox_sender(self):
        production_source = "\n".join(
            path.read_text(errors="ignore")
            for path in (ROOT / "src").rglob("*.py")
        )
        self.assertNotIn("onboarding@resend.dev", production_source)

    def test_monitoring_delivery_checks_saved_preferences(self):
        self.assertIn("monitoring_email_enabled", self.scheduler)
        self.assertIn("email_allowed", self.scheduler)
        self.assertIn("monitoring_email_enabled", self.runtime)
        self.assertIn("monitor_email_allowed", self.runtime)

    def test_invitation_acceptance_is_authenticated_and_email_matched(self):
        self.assertIn("auth.uid()", self.invitation_migration)
        self.assertIn("auth.jwt() ->> 'email'", self.invitation_migration)
        self.assertIn("lower(invitation.email) = current_email", self.invitation_migration)
        self.assertIn("grant execute", self.invitation_migration.lower())
        self.assertIn("to authenticated", self.invitation_migration.lower())

    def test_supabase_auth_and_stripe_email_handoffs_are_wired(self):
        self.assertIn('"email_redirect_to": confirm.signup_confirmation_redirect_url()', self.auth)
        self.assertIn("reset_password_for_email", self.auth_recovery)
        self.assertIn('{"redirect_to": redirect_to}', self.auth_recovery)
        self.assertIn("customer_email=user_email", self.stripe_helper)

    def test_email_helpers_are_not_shadowed_inside_authenticated_app(self):
        """Pricing and Billing must read the module-level email helpers.

        Importing either helper anywhere inside run_authenticated_app makes the
        name local to that entire function and can crash other page branches
        with UnboundLocalError before the conditional import is reached.
        """
        tree = ast.parse(self.runtime)
        authenticated_app = next(
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "run_authenticated_app"
        )
        nested_helper_imports = [
            alias.name
            for node in ast.walk(authenticated_app)
            if isinstance(node, ast.ImportFrom)
            and node.module == "src.email_routing"
            for alias in node.names
            if alias.name in {"BILLING_EMAIL", "mailto_href"}
        ]
        self.assertEqual(nested_helper_imports, [])
        self.assertIn(
            "from src.email_routing import BILLING_EMAIL, mailto_href",
            self.runtime,
        )


if __name__ == "__main__":
    unittest.main()
