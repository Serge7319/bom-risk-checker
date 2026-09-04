"""Regression coverage for Alternative Finder one-click / Enter search submit."""

from pathlib import Path
import unittest

from src.alternative_finder_state import (
    ALT_FINDER_RESULT_KEY,
    ALTERNATIVE_ORIGINAL_PART_WIDGET_KEY,
    STATUS_COMPLETED,
    STATUS_RUNNING,
    claim_alternative_finder_search_submit,
    resolve_alternative_finder_submitted_mpn,
)


RUNTIME_SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
).read_text(encoding="utf-8")


class AlternativeFinderSearchSubmitTests(unittest.TestCase):
    def test_runtime_uses_form_submit_for_button_and_enter(self):
        self.assertIn('st.form("af62_search_form"', RUNTIME_SOURCE)
        self.assertIn("st.form_submit_button(", RUNTIME_SOURCE)
        self.assertIn("Find Alternatives →", RUNTIME_SOURCE)
        self.assertIn("resolve_alternative_finder_submitted_mpn(", RUNTIME_SOURCE)
        self.assertIn("claim_alternative_finder_search_submit(", RUNTIME_SOURCE)
        # Legacy non-form button path must not remain the only submit trigger.
        self.assertNotIn('key="alternative_find_button_62a"', RUNTIME_SOURCE)

    def test_first_click_resolves_current_typed_mpn(self):
        typed = "MMBT3904"
        resolved = resolve_alternative_finder_submitted_mpn(
            typed,
            "",  # blank durable/session fallback must not win
        )
        self.assertEqual(resolved, "MMBT3904")

        # Widget session value is also accepted when form return is empty.
        session_widget = {ALTERNATIVE_ORIGINAL_PART_WIDGET_KEY: "C0603C104K5RACTU"}
        resolved_from_widget = resolve_alternative_finder_submitted_mpn(
            "",
            session_widget.get(ALTERNATIVE_ORIGINAL_PART_WIDGET_KEY),
        )
        self.assertEqual(resolved_from_widget, "C0603C104K5RACTU")

    def test_enter_and_button_share_the_same_submit_claim_path(self):
        # Form submit (Enter or button) both funnel through claim + resolve.
        self.assertIn("if find_alternatives_clicked:", RUNTIME_SOURCE)
        claim_idx = RUNTIME_SOURCE.index("claim_alternative_finder_search_submit(")
        form_idx = RUNTIME_SOURCE.index("st.form_submit_button(")
        self.assertLess(form_idx, claim_idx)

    def test_duplicate_submit_is_rejected_within_debounce_window(self):
        session = {}
        self.assertTrue(
            claim_alternative_finder_search_submit(
                session, "MMBT3904", now=1000.0, debounce_seconds=2.0
            )
        )
        self.assertFalse(
            claim_alternative_finder_search_submit(
                session, "MMBT3904", now=1000.5, debounce_seconds=2.0
            )
        )
        self.assertTrue(
            claim_alternative_finder_search_submit(
                session, "MMBT3904", now=1003.0, debounce_seconds=2.0
            )
        )

    def test_in_flight_same_mpn_submit_is_rejected(self):
        session = {
            ALT_FINDER_RESULT_KEY: {
                "status": STATUS_RUNNING,
                "entered_mpn": "MMBT3904",
            }
        }
        self.assertFalse(
            claim_alternative_finder_search_submit(session, "mmbt3904", now=5000.0)
        )
        session[ALT_FINDER_RESULT_KEY] = {
            "status": STATUS_COMPLETED,
            "entered_mpn": "MMBT3904",
        }
        self.assertTrue(
            claim_alternative_finder_search_submit(session, "MMBT3904", now=5000.0)
        )

    def test_empty_submit_is_rejected(self):
        session = {}
        self.assertFalse(claim_alternative_finder_search_submit(session, "  "))
        self.assertEqual(resolve_alternative_finder_submitted_mpn("", None, "  "), "")


if __name__ == "__main__":
    unittest.main()
