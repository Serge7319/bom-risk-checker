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

    def test_bridge_is_login_only_and_installed_after_form(self):
        form_call = self.source.find('with st.form("cadivor_auth_form"')
        bridge_call = self.source.find(
            "\n        _install_login_pointerdown_bridge()", form_call
        )
        self.assertGreater(bridge_call, form_call)
        self.assertIn("if auth_mode == AUTH_MODE_LOGIN:", self.source)

    def test_bridge_commits_then_submits_fresh_password_once(self):
        self.assertIn('addEventListener("pointerdown"', self.source)
        self.assertIn('active.getAttribute("type") !== "password"', self.source)
        self.assertIn("event.preventDefault()", self.source)
        self.assertIn("event.stopImmediatePropagation()", self.source)
        self.assertIn('active.dispatchEvent(new Event("change"', self.source)
        self.assertIn("active.blur()", self.source)
        self.assertIn("originalButton.isConnected", self.source)
        self.assertIn("commitGraceElapsed", self.source)
        self.assertIn("delete parentWindow[intentKey]", self.source)
        self.assertIn("button.click()", self.source)

    def test_bridge_intent_survives_only_the_commit_rerun(self):
        self.assertIn('const intentKey = "__cadivorLoginCommitThenSubmit"', self.source)
        self.assertIn("deadline: Date.now() + 5000", self.source)
        self.assertIn("const poll = window.setInterval(finishIntent, 100)", self.source)
        self.assertIn("if (!parentWindow[intentKey])", self.source)

    def test_bridge_does_not_read_or_copy_credentials(self):
        start = self.source.index("def _install_login_pointerdown_bridge")
        end = self.source.index("\ndef _auth_css", start)
        bridge = self.source[start:end]
        for forbidden in (
            ".value",
            "AUTH_EMAIL_WIDGET_KEY",
            "AUTH_PASSWORD_WIDGET_KEY",
            "sessionStorage",
            "localStorage",
            "query_params",
            "postMessage",
            "fetch(",
        ):
            self.assertNotIn(forbidden, bridge)

    def test_existing_submit_latch_and_provider_path_remain(self):
        self.assertIn("AUTH_LOGIN_SUBMIT_REQUESTED_KEY", self.source)
        self.assertIn("on_click=_request_manual_login_submit", self.source)
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
