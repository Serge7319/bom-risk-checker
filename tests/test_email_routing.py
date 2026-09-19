"""Email routing contract for Cadivor inboxes and transactional mail."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class EmailRoutingTests(unittest.TestCase):
    def test_intent_map_covers_required_inboxes(self):
        from src.email_routing import (
            BETA_EMAIL,
            BILLING_EMAIL,
            INFO_EMAIL,
            LEGAL_EMAIL,
            SECURITY_EMAIL,
            SUPPORT_EMAIL,
            resolve_inbox,
        )

        self.assertEqual(resolve_inbox("demo"), INFO_EMAIL)
        self.assertEqual(resolve_inbox("student"), INFO_EMAIL)
        self.assertEqual(resolve_inbox("general"), INFO_EMAIL)
        self.assertEqual(resolve_inbox("beta"), BETA_EMAIL)
        self.assertEqual(resolve_inbox("blocker"), BETA_EMAIL)
        self.assertEqual(resolve_inbox("support"), SUPPORT_EMAIL)
        self.assertEqual(resolve_inbox("security"), SECURITY_EMAIL)
        self.assertEqual(resolve_inbox("disclosure"), SECURITY_EMAIL)
        self.assertEqual(resolve_inbox("legal"), LEGAL_EMAIL)
        self.assertEqual(resolve_inbox("privacy"), LEGAL_EMAIL)
        self.assertEqual(resolve_inbox("billing"), BILLING_EMAIL)
        self.assertEqual(resolve_inbox("unknown-topic"), INFO_EMAIL)

    def test_mailto_href_targets_resolved_inbox(self):
        from src.email_routing import mailto_href

        href = mailto_href("beta", subject="Cadivor Beta Program", body="hello")
        self.assertTrue(href.startswith("mailto:beta@cadivor.com?"))
        self.assertIn("subject=Cadivor%20Beta%20Program", href)
        self.assertIn("body=hello", href)

    def test_marketing_site_routes_beta_support_security_legal(self):
        marketing = (ROOT / "src" / "marketing_site.py").read_text(encoding="utf-8")
        self.assertIn("mailto:beta@cadivor.com?subject=Cadivor%20Beta%20Program", marketing)
        self.assertIn("mailto:support@cadivor.com?subject=Cadivor%20Product%20Question", marketing)
        self.assertIn("mailto:security@cadivor.com?subject=Cadivor%20Security", marketing)
        self.assertIn("legal@cadivor.com", marketing)
        self.assertNotIn(
            "mailto:info@cadivor.com?subject=Cadivor%20Beta%20Program",
            marketing,
        )

    def test_marketing_web_contact_form_routes_by_topic(self):
        app_js = (ROOT / "marketing-web" / "app.js").read_text(encoding="utf-8")
        index = (ROOT / "marketing-web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("CONTACT_INBOX", app_js)
        self.assertIn("beta: 'beta@cadivor.com'", app_js)
        self.assertIn("support: 'support@cadivor.com'", app_js)
        self.assertIn("security: 'security@cadivor.com'", app_js)
        self.assertIn("billing: 'billing@cadivor.com'", app_js)
        self.assertIn("mailto:${inbox}", app_js)
        self.assertIn('id="contactTopic"', index)
        self.assertIn('value="security"', index)
        self.assertIn("legal@cadivor.com", index)

    def test_auth_terms_point_to_legal_inbox(self):
        auth = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        self.assertIn("legal@cadivor.com", auth)
        self.assertNotIn(
            "Questions about these Terms may be sent to **info@cadivor.com**",
            auth,
        )

    def test_workspace_invite_sends_resend_email(self):
        from src import workspace_service as ws

        supabase = MagicMock()
        supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "inv-1", "email": "eng@example.com", "role": "engineer"}]
        )

        with patch.object(ws, "record_activity"), patch.object(ws, "create_notification"), patch(
            "src.email_routing.send_resend_email"
        ) as send_mail:
            invite, error = ws.create_invite(
                supabase,
                "ws-1",
                "eng@example.com",
                "engineer",
                "user-1",
                "Owner Name",
            )
        self.assertIsNone(error)
        self.assertIsNotNone(invite)
        send_mail.assert_called_once()
        kwargs = send_mail.call_args.kwargs
        self.assertEqual(kwargs["to_email"], "eng@example.com")
        self.assertIn("invited", kwargs["subject"].lower())

    def test_monitoring_script_honors_notification_preferences(self):
        monitoring = (ROOT / "src" / "run_scheduled_monitoring.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_user_allows_monitoring_email", monitoring)
        self.assertIn("monitoring_notifications", monitoring)
        self.assertIn("CADIVOR_FROM_EMAIL", monitoring)
        self.assertNotIn("onboarding@resend.dev", monitoring)

    def test_transactional_from_email_prefers_cadivor_from(self):
        from src import email_routing

        with patch("src.secrets.get_secret", side_effect=lambda name, **kwargs: {
            "CADIVOR_FROM_EMAIL": "Cadivor <noreply@cadivor.com>",
            "ALERT_FROM_EMAIL": "Cadivor <alerts@cadivor.com>",
        }.get(name, kwargs.get("default"))):
            self.assertEqual(
                email_routing.transactional_from_email(),
                "Cadivor <noreply@cadivor.com>",
            )


if __name__ == "__main__":
    unittest.main()
