"""Regression coverage for atomic Login submission and autofill."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
HTML = (ROOT / "src" / "components" / "atomic_login" / "index.html").read_text(encoding="utf-8")


class OneClickLoginAutofillContractTests(unittest.TestCase):
    def test_email_and_password_share_one_native_form(self):
        self.assertIn('<form id="login" autocomplete="on"', HTML)
        self.assertIn('name="email"', HTML)
        self.assertIn('name="password"', HTML)
        self.assertIn('type="submit"', HTML)

    def test_manual_and_saved_credentials_use_same_submit_event(self):
        self.assertEqual(HTML.count('form.addEventListener("submit"'), 1)
        self.assertIn("const emailValue = email.value.trim()", HTML)
        self.assertIn("const passwordValue = password.value", HTML)

    def test_no_streamlit_password_commit_callback_or_synthetic_replay(self):
        self.assertNotIn("on_change=_request_manual_login_submit", AUTH)
        self.assertNotIn("on_click=_request_manual_login_submit", AUTH)
        self.assertNotIn("button.click()", HTML)

    def test_one_request_id_prevents_provider_replay(self):
        self.assertIn("request_id and request_id != consumed_id", AUTH)
        self.assertIn("AUTH_ATOMIC_LOGIN_CONSUMED_KEY", AUTH)


if __name__ == "__main__":
    unittest.main()
