"""Contracts for one canonical Alternative Finder compatibility value."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


class AlternativeFinderCompatibilityPresentationTests(unittest.TestCase):
    def test_decision_ui_and_exports_use_engineering_comparison_confidence(self):
        self.assertIn(
            "<strong>{engineering_comparison_confidence}% · {confidence_label}</strong>",
            RUNTIME,
        )
        self.assertIn(
            '"compatibility_confidence": engineering_comparison_confidence',
            RUNTIME,
        )
        self.assertIn(
            "compatibility_confidence=engineering_comparison_confidence",
            RUNTIME,
        )
        self.assertNotIn("<strong>{drop_in_confidence}% ·", RUNTIME)
        self.assertNotIn('"compatibility_confidence": drop_in_confidence', RUNTIME)
        self.assertNotIn("compatibility_confidence=drop_in_confidence", RUNTIME)
        self.assertIn('"Attribute": "Engineering Compatibility"', RUNTIME)
        self.assertNotIn('"Attribute": "Drop-In Confidence"', RUNTIME)
        self.assertNotIn('"Attribute": "Drop-In Rating"', RUNTIME)


if __name__ == "__main__":
    unittest.main()
