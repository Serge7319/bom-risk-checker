"""Regression coverage for polished Alternative Finder search feedback."""

import ast
from pathlib import Path
import unittest


SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
).read_text(encoding="utf-8")


class AlternativeFinderSearchFeedbackTests(unittest.TestCase):
    def test_search_status_uses_a_removable_placeholder(self):
        self.assertIn("search_status = st.empty()", SOURCE)
        self.assertIn("with search_status.container():", SOURCE)

    def test_search_status_clears_after_success_or_failure(self):
        route = SOURCE.split('    if app_mode == "Alternative Finder":', 1)[1]
        route = route.split("\n    if app_mode == ", 1)[0]
        function = ast.parse("def route():\n    if True:" + route)
        cleanup = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Try)
            and any(
                isinstance(item, ast.Expr)
                and isinstance(item.value, ast.Call)
                and isinstance(item.value.func, ast.Attribute)
                and item.value.func.attr == "empty"
                and isinstance(item.value.func.value, ast.Name)
                and item.value.func.value.id == "search_status"
                for item in node.finalbody
            )
        ]
        self.assertEqual(len(cleanup), 1)

    def test_operation_state_is_still_cleared(self):
        self.assertIn('st.session_state.pop("cadivor_operation", None)', SOURCE)

    def test_decision_note_example_does_not_invent_a_package_change(self):
        self.assertNotIn("Package change requires PCB", SOURCE)
        self.assertIn("Approve after reviewing the datasheet", SOURCE)

    def test_supplier_search_guidance_remains_visible_while_loading(self):
        self.assertIn("Searching component intelligence", SOURCE)
        self.assertIn("Checking supplier coverage, lifecycle evidence", SOURCE)


if __name__ == "__main__":
    unittest.main()
