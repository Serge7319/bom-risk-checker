"""Regression coverage for cycle-safe Alternative Finder session sanitization."""

import unittest
from datetime import datetime, timezone

from src.alternative_finder_state import (
    ALT_FINDER_RESULT_KEY,
    MARKER_CIRCULAR_REF,
    MARKER_MAX_DEPTH,
    STATUS_FAILED,
    complete_alternative_finder_search,
    fail_alternative_finder_search,
    sanitize_for_session,
)


class AlternativeFinderSanitizeTests(unittest.TestCase):
    def test_self_referencing_dictionary_is_marked_not_recursive(self):
        payload: dict = {"manufacturer_part_number": "C0603C104K5RACTU"}
        payload["self"] = payload

        sanitized = sanitize_for_session(payload)

        self.assertEqual(sanitized["manufacturer_part_number"], "C0603C104K5RACTU")
        self.assertIn(MARKER_CIRCULAR_REF, sanitized["self"])

    def test_dictionary_list_circular_reference_is_marked(self):
        root: dict = {"name": "root"}
        child: dict = {"name": "child", "parent": root}
        root["children"] = [child]
        child["back_to_root"] = root

        sanitized = sanitize_for_session(root)

        self.assertEqual(sanitized["name"], "root")
        self.assertEqual(sanitized["children"][0]["name"], "child")
        self.assertIn(MARKER_CIRCULAR_REF, sanitized["children"][0]["parent"])
        self.assertIn(MARKER_CIRCULAR_REF, sanitized["children"][0]["back_to_root"])

    def test_deeply_nested_structure_is_truncated_with_marker(self):
        depth = 80
        payload: dict = {"level": 0}
        current = payload
        for level in range(1, depth):
            nxt = {"level": level}
            current["child"] = nxt
            current = nxt

        sanitized = sanitize_for_session(payload)
        cursor = sanitized
        seen_levels = 0
        while isinstance(cursor, dict) and "child" in cursor:
            seen_levels += 1
            cursor = cursor["child"]
            if isinstance(cursor, str) and MARKER_MAX_DEPTH in cursor:
                break
        self.assertIn(MARKER_MAX_DEPTH, str(cursor))
        self.assertLess(seen_levels, depth)

    def test_fail_alternative_finder_search_with_cyclic_original_data(self):
        session: dict = {}
        cyclic: dict = {
            "manufacturer_part_number": "C0603C104K5RACTU",
            "package": "0603",
        }
        cyclic["all_supplier_results"] = [cyclic]

        fail_alternative_finder_search(
            session,
            entered_mpn="C0603C104K5RACTU",
            search_error=(
                "Cadivor could not complete the supplier search right now. "
                "Please try again in a moment."
            ),
            lookup_error="",
            original_data=cyclic,
            original_risk={},
        )

        result = session[ALT_FINDER_RESULT_KEY]
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertEqual(result["entered_mpn"], "C0603C104K5RACTU")
        self.assertIn(MARKER_CIRCULAR_REF, result["original_data"]["all_supplier_results"][0])
        self.assertEqual(session["alternative_search_error"], result["search_error"])

    def test_normal_candidate_payload_with_sets_and_nested_values(self):
        session: dict = {}
        candidates = [
            {
                "Alternative Part": "C0603C104K5RAC3121",
                "Recommendation Score": 92,
                "Feature Tags": {"automotive", "mlcc"},
                "Comparison Counts": {"Match": 7, "Different": 0, "Needs data": 1},
                "Retrieved At": datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
                "Nested": {"Mounting": "Surface Mount, MLCC"},
            }
        ]

        complete_alternative_finder_search(
            session,
            entered_mpn="C0603C104K5RACTU",
            canonical_mpn="C0603C104K5RACTU",
            original_data={"package": "0603", "capacitance": "0.1 µF"},
            original_risk={"risk_level": "Low"},
            candidates=candidates,
        )

        stored = session[ALT_FINDER_RESULT_KEY]["candidates"][0]
        self.assertEqual(stored["Alternative Part"], "C0603C104K5RAC3121")
        self.assertIsInstance(stored["Feature Tags"], list)
        self.assertEqual(sorted(stored["Feature Tags"]), ["automotive", "mlcc"])
        self.assertTrue(str(stored["Retrieved At"]).startswith("2026-09-02"))
        self.assertEqual(stored["Nested"]["Mounting"], "Surface Mount, MLCC")

    def test_supplier_like_cycle_path_matches_all_supplier_results(self):
        """Reproduce the likely production cycle path from aggregated supplier data."""
        original: dict = {
            "manufacturer_part_number": "C0603C104K5RACTU",
            "package": "0603 (1608 Metric)",
            "source": "DigiKey",
        }
        original["all_supplier_results"] = [original]

        sanitized = sanitize_for_session(original)

        self.assertEqual(sanitized["manufacturer_part_number"], "C0603C104K5RACTU")
        cyclic_marker = sanitized["all_supplier_results"][0]
        self.assertIn(MARKER_CIRCULAR_REF, cyclic_marker)
        self.assertIn("all_supplier_results[0]", cyclic_marker)


if __name__ == "__main__":
    unittest.main()
