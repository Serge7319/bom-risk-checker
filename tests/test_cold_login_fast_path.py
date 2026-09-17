"""Regression contracts for the reliable signed-out Cadivor login sequence."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ColdLoginReliabilityTests(unittest.TestCase):
    def test_auth_client_is_ready_before_the_first_gate_paint(self) -> None:
        source = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")

        client_init = source.index("supabase = get_supabase_client()")
        first_gate_paint = source.index("paint_auth_gate(gate_state)")

        self.assertLess(client_init, first_gate_paint)
        self.assertNotIn("show_auth_ui(None, None)", source)

    def test_signup_uses_the_bootstrap_auth_client(self) -> None:
        source = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        signup_submit = source.index("elif submit:", source.index("def _render_auth_page"))
        signup_action = source.index("_submit_manual_signup", signup_submit)
        block = source[signup_submit:signup_action]

        self.assertNotIn("if supabase is None:", block)


if __name__ == "__main__":
    unittest.main()
