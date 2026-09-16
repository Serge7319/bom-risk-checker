"""Regression guards for native manual Login and viewport-stable auth."""
from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AUTH = (REPO / "src" / "auth.py").read_text(encoding="utf-8")
class ManualLoginNativeFormTests(unittest.TestCase):
    def test_login_uses_native_form_without_callback_latch(self):
        self.assertIn('with st.form("cadivor_login_form"', AUTH)
        self.assertNotIn("render_atomic_login(", AUTH)
        self.assertNotIn("_request_manual_login_submit", AUTH)
        self.assertNotIn("AUTH_LOGIN_SUBMIT_REQUESTED_KEY", AUTH)

    def test_native_submit_has_no_browser_click_replay(self):
        self.assertIn('key="cadivor_login_submit"', AUTH)
        self.assertNotIn("button.click()", AUTH)
        self.assertNotIn("cadivorCommitThenSubmit", AUTH)


class AuthViewportContractTests(unittest.TestCase):
    def test_auth_card_is_viewport_pinned(self):
        self.assertIn("position:fixed!important", AUTH)
        self.assertIn("left:50%!important", AUTH)
        self.assertIn("transform:translateX(-50%)!important", AUTH)

    def test_auth_card_is_bounded_to_dynamic_viewport(self):
        self.assertIn("max-height:calc(100dvh", AUTH)
        self.assertIn("overflow-y:auto!important", AUTH)
        self.assertIn("width:min(480px,calc(100vw - 24px))", AUTH)


if __name__ == "__main__":
    unittest.main()
