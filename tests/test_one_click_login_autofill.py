"""Regression coverage for native one-click Login submission and autofill."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
class OneClickLoginAutofillContractTests(unittest.TestCase):
    def test_email_and_password_share_one_streamlit_form(self):
        login = AUTH[AUTH.index("if auth_mode == AUTH_MODE_LOGIN:"):AUTH.index('with st.form("cadivor_auth_form"')]
        self.assertIn('with st.form("cadivor_login_form"', login)
        self.assertIn('key=AUTH_EMAIL_WIDGET_KEY', login)
        self.assertIn('key=AUTH_PASSWORD_WIDGET_KEY', login)
        self.assertIn('autocomplete="current-password"', login)

    def test_manual_and_saved_credentials_use_one_form_submit(self):
        self.assertEqual(AUTH.count('with st.form("cadivor_login_form"'), 1)
        self.assertIn('key="cadivor_login_submit"', AUTH)
        self.assertIn("if submit:", AUTH)

    def test_no_custom_component_or_synthetic_replay(self):
        self.assertNotIn("render_atomic_login(", AUTH)
        self.assertNotIn("declare_component(", AUTH)
        self.assertNotIn("on_click=_request_manual_login_submit", AUTH)

    def test_one_submit_enters_the_existing_login_handoff(self):
        self.assertIn("_submit_manual_login(supabase, cookie_manager, email, password)", AUTH)


if __name__ == "__main__":
    unittest.main()
