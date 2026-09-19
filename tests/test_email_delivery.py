import sys
import types
import unittest
from unittest.mock import patch

from src.email_delivery import (
    EmailDeliveryError,
    email_delivery_configured,
    send_transactional_email,
    send_workspace_invitation_email,
)


class _FakeEmails:
    payloads = []

    @classmethod
    def send(cls, payload):
        cls.payloads.append(payload)
        return {"id": "email_test_123"}


class EmailDeliveryTests(unittest.TestCase):
    def setUp(self):
        _FakeEmails.payloads = []
        self.resend = types.SimpleNamespace(api_key=None, Emails=_FakeEmails)

    @staticmethod
    def _secret(name, *, default=None, required=False):
        values = {
            "RESEND_API_KEY": "re_test_key",
            "TRANSACTIONAL_FROM_EMAIL": "Cadivor <no-reply@cadivor.com>",
            "EMAIL_REPLY_TO": "support@cadivor.com",
        }
        value = values.get(name, default)
        if required and not value:
            raise RuntimeError(f"missing {name}")
        return value

    def test_transactional_email_uses_verified_domain_contract(self):
        with patch.dict(sys.modules, {"resend": self.resend}), patch(
            "src.email_delivery.get_secret",
            side_effect=self._secret,
        ):
            result = send_transactional_email(
                to_email=" Engineer@Example.com ",
                subject="Cadivor test",
                html_body="<p>Ready</p>",
                text_body="Ready",
            )

        self.assertEqual(result, {"id": "email_test_123"})
        self.assertEqual(self.resend.api_key, "re_test_key")
        self.assertEqual(len(_FakeEmails.payloads), 1)
        payload = _FakeEmails.payloads[0]
        self.assertEqual(payload["from"], "Cadivor <no-reply@cadivor.com>")
        self.assertEqual(payload["to"], ["engineer@example.com"])
        self.assertEqual(payload["reply_to"], "support@cadivor.com")
        self.assertEqual(payload["text"], "Ready")

    def test_workspace_invitation_is_branded_escaped_and_actionable(self):
        with patch.dict(sys.modules, {"resend": self.resend}), patch(
            "src.email_delivery.get_secret",
            side_effect=self._secret,
        ):
            send_workspace_invitation_email(
                to_email="new.member@example.com",
                workspace_name="Power <Lab>",
                invited_by_name="Alex & Team",
                role="engineer",
            )

        payload = _FakeEmails.payloads[0]
        self.assertIn("Power &lt;Lab&gt;", payload["html"])
        self.assertIn("Alex &amp; Team", payload["html"])
        self.assertIn("page=Workspace", payload["html"])
        self.assertIn("auth=signup", payload["html"])
        self.assertIn("support@cadivor.com", payload["html"])

    def test_invalid_recipient_is_rejected_before_provider_call(self):
        with self.assertRaises(EmailDeliveryError):
            send_transactional_email(
                to_email="not-an-address",
                subject="Invalid",
                html_body="<p>No</p>",
            )
        self.assertEqual(_FakeEmails.payloads, [])

    def test_configuration_probe_requires_resend_key(self):
        with patch("src.email_delivery.get_secret", side_effect=self._secret):
            self.assertTrue(email_delivery_configured())

        def no_key(name, *, default=None, required=False):
            if name == "RESEND_API_KEY":
                return ""
            return self._secret(name, default=default, required=required)

        with patch("src.email_delivery.get_secret", side_effect=no_key):
            self.assertFalse(email_delivery_configured())


if __name__ == "__main__":
    unittest.main()
