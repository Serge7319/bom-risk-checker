"""Regression contracts for the first signed-out Cadivor page paint."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ColdLoginFastPathTests(unittest.TestCase):
    def test_direct_login_form_precedes_client_initialization(self) -> None:
        source = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        fast_path = source.index("# A clean login or signup visit")
        client_init = source.index("# Provider recovery and session restoration require a client")

        self.assertLess(fast_path, client_init)
        self.assertIn("show_auth_ui(None, None)", source[fast_path:client_init])
        self.assertNotIn("paint_auth_gate(\"login\")", source[fast_path:client_init])

    def test_signup_initializes_client_only_when_submitted(self) -> None:
        source = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        signup_submit = source.index("elif submit:", source.index("def _render_auth_page"))
        signup_action = source.index("_submit_manual_signup", signup_submit)
        block = source[signup_submit:signup_action]

        self.assertIn("if supabase is None:", block)
        self.assertIn("get_supabase_client()", block)


if __name__ == "__main__":
    unittest.main()
