"""Regression guards for the native one-click Login form."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
class NativeLoginFormContractTests(unittest.TestCase):
    def test_login_uses_one_native_streamlit_form(self):
        login = AUTH[AUTH.index("if auth_mode == AUTH_MODE_LOGIN:"):AUTH.index('with st.form("cadivor_auth_form"')]
        self.assertIn('with st.form("cadivor_login_form"', login)
        self.assertIn('st.text_input(\n                "Email"', login)
        self.assertIn('st.text_input(\n                "Password"', login)
        self.assertIn("st.form_submit_button(", login)
        self.assertNotIn("render_atomic_login(", login)

    def test_login_error_is_visible_above_the_native_form(self):
        self.assertIn("if auth_error:", AUTH)
        self.assertIn("st.error(auth_error)", AUTH)
        self.assertIn(
            '"Email or password is incorrect. Please try again."',
            AUTH,
        )
        self.assertNotIn("cadivor_atomic_login", AUTH)
        self.assertNotIn('st.session_state["cadivor_auth_password"] =', AUTH)
        self.assertIn("supabase.auth.sign_in_with_password", AUTH)

    def test_submit_uses_the_form_values_once(self):
        login = AUTH[AUTH.index("if auth_mode == AUTH_MODE_LOGIN:\n        if submit:"):AUTH.index("    elif submit:")]
        self.assertIn("if submit:", login)
        self.assertIn("_submit_manual_login(supabase, cookie_manager, email, password)", login)


if __name__ == "__main__":
    unittest.main()
