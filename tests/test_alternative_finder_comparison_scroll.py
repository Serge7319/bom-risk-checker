"""Guards for Alternative Finder comparison-table scroll / layout behavior."""

from pathlib import Path
import unittest
from unittest import mock

from src.component_family_profiles import FAMILY_PROFILES
from src.ui.cadivor_design_system import (
    COMPARISON_MATRIX_EXPAND_ROW_LIMIT,
    comparison_matrix_dataframe_height,
)
from src.ui.cadivor_design_system import components as cds_components


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SOURCE = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
COMPONENTS_SOURCE = (
    ROOT / "src" / "ui" / "cadivor_design_system" / "components.py"
).read_text(encoding="utf-8")
DESIGN_CSS = (
    ROOT / "src" / "assets" / "css" / "cadivor_design_system.css"
).read_text(encoding="utf-8")

# Representative matrices called out in the scroll-accessibility fix.
_FAMILY_KEYS = (
    "Bipolar transistor",
    "Capacitor",
    "Resistor",
    "MCU / processor",
    "FPGA / CPLD",
)


class AlternativeFinderComparisonScrollTests(unittest.TestCase):
    def test_modest_matrices_expand_without_fixed_clip(self):
        for family_key in _FAMILY_KEYS:
            with self.subTest(family=family_key):
                profile = FAMILY_PROFILES[family_key]
                row_count = len(profile.fields)
                self.assertLessEqual(row_count, COMPARISON_MATRIX_EXPAND_ROW_LIMIT)
                with mock.patch.object(
                    cds_components, "_streamlit_supports_content_height", return_value=True
                ):
                    self.assertEqual(
                        comparison_matrix_dataframe_height(row_count),
                        "content",
                    )
                with mock.patch.object(
                    cds_components, "_streamlit_supports_content_height", return_value=False
                ):
                    height = comparison_matrix_dataframe_height(row_count)
                    self.assertIsInstance(height, int)
                    self.assertGreaterEqual(height, 46 + row_count * 35)

    def test_long_matrices_use_single_scroll_viewport(self):
        long_rows = COMPARISON_MATRIX_EXPAND_ROW_LIMIT + 10
        with mock.patch.object(
            cds_components, "_streamlit_supports_content_height", return_value=True
        ):
            expanded_at_limit = comparison_matrix_dataframe_height(
                COMPARISON_MATRIX_EXPAND_ROW_LIMIT
            )
            long_height = comparison_matrix_dataframe_height(long_rows)
        self.assertEqual(expanded_at_limit, "content")
        # Long matrices share one fixed pixel viewport (not content expansion).
        self.assertIsInstance(long_height, int)
        self.assertEqual(
            long_height,
            comparison_matrix_dataframe_height(COMPARISON_MATRIX_EXPAND_ROW_LIMIT + 1),
        )
        self.assertEqual(
            long_height,
            comparison_matrix_dataframe_height(long_rows + 50),
        )

    def test_runtime_does_not_force_broken_430px_outer_scroll(self):
        self.assertNotIn("max-height:430px!important;", RUNTIME_SOURCE)
        self.assertIn("cadivor_comparison_matrix_dataframe(comparison_df)", RUNTIME_SOURCE)
        self.assertIn('key="af62b_datasheet_evidence"', RUNTIME_SOURCE)
        self.assertIn("overflow-y:visible!important;", RUNTIME_SOURCE)
        self.assertIn("overflow-x:auto!important;", RUNTIME_SOURCE)

    def test_comparison_host_css_avoids_nested_vertical_scrollport(self):
        self.assertIn(".cv64-comparison-table-host", DESIGN_CSS)
        self.assertIn("max-height: none !important;", DESIGN_CSS)
        self.assertIn("overflow-y: visible !important;", DESIGN_CSS)
        self.assertIn("overflow-x: auto !important;", DESIGN_CSS)
        self.assertIn("cv64-comparison-table-host", COMPONENTS_SOURCE)
        self.assertIn("comparison_matrix_dataframe_height", COMPONENTS_SOURCE)
        self.assertIn("_COMPARISON_MATRIX_CONTENT_HEIGHT", COMPONENTS_SOURCE)
        self.assertIn('"content"', COMPONENTS_SOURCE)


if __name__ == "__main__":
    unittest.main()
