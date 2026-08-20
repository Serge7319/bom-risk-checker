"""Regression guards for one-click manual Login and viewport-stable auth."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
AUTH_PATH = REPO / "src" / "auth.py"


class ManualLoginPointerdownContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AUTH_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_login_uses_server_owned_password_commit_handoff(self):
        self.assertIn("if auth_mode == AUTH_MODE_LOGIN:", self.source)
        self.assertIn("on_change=_request_manual_login_submit", self.source)
        self.assertIn("on_click=_request_manual_login_submit", self.source)
        self.assertIn('key="cadivor_login_submit"', self.source)

    def test_login_is_not_batched_inside_the_signup_form(self):
        login_branch = self.source.index("if auth_mode == AUTH_MODE_LOGIN:")
        signup_form = self.source.index(
            'with st.form("cadivor_auth_form"', login_branch
        )
        login_button = self.source.index("submit = st.button(", login_branch)
        self.assertLess(login_button, signup_form)
        self.assertIn('autocomplete="new-password"', self.source)

    def test_failed_pointerdown_bridge_is_removed(self):
        for removed in (
            "_install_login_pointerdown_bridge",
            "cadivorCommitThenSubmit",
            "addEventListener(\"pointerdown\"",
            "event.preventDefault()",
            "button.click()",
        ):
            self.assertNotIn(removed, self.source)

    def test_existing_submit_latch_and_provider_path_remain(self):
        self.assertIn("AUTH_LOGIN_SUBMIT_REQUESTED_KEY", self.source)
        self.assertIn("supabase.auth.sign_in_with_password", self.source)



class AuthViewportContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AUTH_PATH.read_text(encoding="utf-8")

    def test_auth_card_is_viewport_pinned_not_slot_positioned(self):
        self.assertIn("position:fixed!important", self.source)
        self.assertIn("left:50%!important", self.source)
        self.assertIn("transform:translateX(-50%)!important", self.source)
        self.assertIn("margin:0!important", self.source)

    def test_auth_card_is_bounded_to_dynamic_viewport(self):
        self.assertIn("max-height:calc(100dvh", self.source)
        self.assertIn("overflow-y:auto!important", self.source)
        self.assertIn("width:min(480px,calc(100vw - 24px))", self.source)

    def test_short_and_mobile_viewports_have_compact_rules(self):
        self.assertIn("@media(max-height:900px)", self.source)
        self.assertIn("@media(max-width:700px)", self.source)
        self.assertIn("max-height:calc(100dvh - 16px)", self.source)


if __name__ == "__main__":
    unittest.main()
