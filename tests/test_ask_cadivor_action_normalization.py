"""Sprint 72.2.5 — Recommended action normalization tests."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"


def _load_assistant():
    st = types.ModuleType("streamlit")
    st.session_state = {}
    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = types.ModuleType("streamlit.runtime")
    sys.modules["streamlit.runtime.scriptrunner"] = types.ModuleType("streamlit.runtime.scriptrunner")
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = types.ModuleType("streamlit.components.v1")
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


class AskCadivorActionNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")

    def setUp(self) -> None:
        self.assistant = _load_assistant()

    def test_numbered_lines_without_trailing_periods(self) -> None:
        actions = (
            "1. Investigate alternate suppliers for PC817\n"
            "2. Validate procurement plans for moderate-lead-time components\n"
            "3. Assess replacement strategy for DRV8825"
        )
        items = self.assistant._normalize_action_items(actions)
        self.assertEqual(len(items), 3)
        self.assertNotIn("1", items)
        self.assertNotIn("2", items)
        self.assertTrue(all(not item.isdigit() for item in items))

    def test_malformed_split_from_period_in_list_marker(self) -> None:
        actions = "1. Investigate alternate. 2. Validate procurement. 3. Assess replacement."
        items = self.assistant._normalize_action_items(actions)
        self.assertEqual(
            items,
            [
                "Investigate alternate",
                "Validate procurement",
                "Assess replacement",
            ],
        )

    def test_preserves_numeric_engineering_values(self) -> None:
        actions = "Confirm 21.4 week lead time and 2 suppliers before approving PC817."
        items = self.assistant._normalize_action_items(actions)
        self.assertEqual(len(items), 1)
        self.assertIn("21.4", items[0])
        self.assertIn("2 suppliers", items[0])

    def test_filters_enumeration_only_rows(self) -> None:
        actions = "1.\nInvestigate alternate suppliers for PC817.\n2.\nValidate procurement plans."
        items = self.assistant._normalize_action_items(actions)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item[0].isalpha() for item in items))

    def test_bullet_actions(self) -> None:
        actions = (
            "- Investigate alternative suppliers or parts for PC817.\n"
            "- Validate procurement plans for moderate-lead-time components.\n"
            "- Assess replacement strategy for DRV8825."
        )
        items = self.assistant._normalize_action_items(actions)
        self.assertEqual(len(items), 3)
        self.assertIn("PC817", items[0])

    def test_no_standalone_number_rows_in_rendered_html(self) -> None:
        from tests.harness_ask_cadivor_presentation import render_pc817_harness

        html = render_pc817_harness()
        self.assertNotIn("<p>1</p>", html)
        self.assertNotIn("<p>2</p>", html)
        self.assertNotRegex(html, r'cv722-row-body"><p>\d+</p>')


if __name__ == "__main__":
    unittest.main()
