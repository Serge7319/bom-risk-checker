"""Regression guards for the atomic one-click Login component."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
BRIDGE = (ROOT / "src" / "auth_atomic_login.py").read_text(encoding="utf-8")
HTML = (ROOT / "src" / "components" / "atomic_login" / "index.html").read_text(encoding="utf-8")


class AtomicLoginComponentContractTests(unittest.TestCase):
    def test_login_uses_component_not_streamlit_credential_widgets(self):
        login = AUTH[AUTH.index("if auth_mode == AUTH_MODE_LOGIN:"):AUTH.index('with st.form("cadivor_auth_form"')]
        self.assertIn("render_atomic_login(", login)
        self.assertNotIn("st.text_input(", login)
        self.assertNotIn("st.form_submit_button(", login)

    def test_native_browser_form_emits_one_atomic_payload(self):
        self.assertIn('<form id="login"', HTML)
        self.assertIn('form.addEventListener("submit"', HTML)
        self.assertIn("email:emailValue,password:passwordValue,request_id:requestId()", HTML)
        self.assertIn('type:"streamlit:setComponentValue"', HTML)
        self.assertIn("if (submitted) return", HTML)

    def test_password_manager_contract_is_native_and_no_browser_storage(self):
        self.assertIn('autocomplete="email"', HTML)
        self.assertIn('autocomplete="current-password"', HTML)
        self.assertIn('type="submit"', HTML)
        for forbidden in ("localStorage", "sessionStorage", "location.search", "URLSearchParams"):
            self.assertNotIn(forbidden, HTML)

    def test_python_persists_only_replay_id(self):
        self.assertIn("AUTH_ATOMIC_LOGIN_CONSUMED_KEY", AUTH)
        self.assertIn("request_id != consumed_id", AUTH)
        self.assertIn('payload.get("password")', AUTH)
        self.assertNotIn('st.session_state["cadivor_auth_password"] =', AUTH)
        self.assertIn("supabase.auth.sign_in_with_password", AUTH)

    def test_component_is_local_and_requires_no_frontend_build(self):
        self.assertIn("declare_component(", BRIDGE)
        self.assertIn("path=str(_COMPONENT_DIR)", BRIDGE)
        self.assertNotIn("npm", BRIDGE.lower())


if __name__ == "__main__":
    unittest.main()
