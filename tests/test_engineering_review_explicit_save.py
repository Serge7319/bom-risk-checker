from __future__ import annotations

from pathlib import Path
import unittest

from src.components.review import should_persist_review_decision


class EngineeringReviewExplicitSaveTests(unittest.TestCase):
    def test_valid_default_recommendation_waits_for_explicit_save(self):
        # A low-risk suggested Approve is valid and differs from an empty saved
        # row, but rendering the review form must not persist it.
        self.assertFalse(should_persist_review_decision(
            save_requested=False,
            changed=True,
            disabled=False,
            can_save_decision=True,
        ))

    def test_explicit_save_persists_a_valid_changed_decision(self):
        self.assertTrue(should_persist_review_decision(
            save_requested=True,
            changed=True,
            disabled=False,
            can_save_decision=True,
        ))

    def test_save_gate_rejects_unchanged_invalid_and_disabled_decisions(self):
        base = {
            "save_requested": True,
            "changed": True,
            "disabled": False,
            "can_save_decision": True,
        }
        self.assertFalse(should_persist_review_decision(**{**base, "changed": False}))
        self.assertFalse(should_persist_review_decision(**{**base, "can_save_decision": False}))
        self.assertFalse(should_persist_review_decision(**{**base, "disabled": True}))

    def test_analysis_detail_uses_the_explicit_save_gate(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "pages"
            / "analysis_detail.py"
        ).read_text(encoding="utf-8")
        self.assertIn('save_requested = st.button(', source)
        self.assertIn('"Save review decision"', source)
        self.assertIn("if should_persist_review_decision(", source)
        self.assertNotIn(
            "if changed and not disabled and can_save_decision:",
            source,
        )


if __name__ == "__main__":
    unittest.main()
