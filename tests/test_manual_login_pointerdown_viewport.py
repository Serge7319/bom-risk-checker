"""Regression guards for atomic manual Login and viewport-stable auth."""
from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AUTH = (REPO / "src" / "auth.py").read_text(encoding="utf-8")
HTML = (REPO / "src" / "components" / "atomic_login" / "index.html").read_text(encoding="utf-8")


class ManualLoginAtomicComponentTests(unittest.TestCase):
    def test_login_uses_atomic_component_and_no_callback_latch(self):
        self.assertIn("render_atomic_login(", AUTH)
        self.assertNotIn("_request_manual_login_submit", AUTH)
        self.assertNotIn("AUTH_LOGIN_SUBMIT_REQUESTED_KEY", AUTH)

    def test_component_uses_real_submit_without_click_replay(self):
        self.assertIn('button id="submit" type="submit"', HTML)
        self.assertIn('form.addEventListener("submit"', HTML)
        for removed in ("pointerdown", "button.click()", "cadivorCommitThenSubmit"):
            self.assertNotIn(removed, HTML)


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
