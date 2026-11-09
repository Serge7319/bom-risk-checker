"""Regressions for the Nov 9 synthetic production smoke defects."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.component_family_profiles import FieldSpec, COMPARE_EXACT
from src.datasheet_comparison import (
    _find_pdf_evidence,
    _is_specific_pdf_field_value,
    _looks_like_supply_test_condition,
)
from src.parametric_compare import compare_field_values


ROOT = Path(__file__).resolve().parents[1]
WEB_CSS = ROOT / "apps" / "web" / "src" / "app" / "globals.css"
COMPARE_PAGE = ROOT / "apps" / "web" / "src" / "app" / "compare-parts" / "page.tsx"
BOM_ANALYZER = ROOT / "apps" / "web" / "src" / "app" / "bom-analyzer" / "page.tsx"
DESIGN_IMPACT = ROOT / "apps" / "web" / "src" / "app" / "design-impact" / "page.tsx"
BOM_IDENTITY = ROOT / "apps" / "web" / "src" / "lib" / "bomFileIdentity.ts"


class SupplyVoltageExtractionTests(unittest.TestCase):
    def test_vs_plus_minus_14_is_test_condition_not_supply_rating(self):
        self.assertTrue(_looks_like_supply_test_condition("VS = ±14 V"))
        self.assertTrue(_looks_like_supply_test_condition("±14 V"))
        self.assertFalse(_looks_like_supply_test_condition("3 V to 32 V"))
        self.assertFalse(_looks_like_supply_test_condition("3-32V"))

        voltage_spec = FieldSpec(
            key="voltage_range",
            label="Supply voltage",
            compare=COMPARE_EXACT,
            unit="V",
        )
        self.assertFalse(_is_specific_pdf_field_value(voltage_spec, "VS = ±14 V"))
        self.assertTrue(_is_specific_pdf_field_value(voltage_spec, "3 V to 32 V"))

        pdf = {
            "pages": [
                {
                    "page": 4,
                    "document": "LM358ADR2G",
                    "text": (
                        "Electrical Characteristics\n"
                        "VS = ±14 V, TA = 25C\n"
                        "Supply voltage 3 V to 32 V single supply\n"
                    ),
                }
            ]
        }
        value, _page, excerpt = _find_pdf_evidence(
            pdf,
            ("supply voltage",),
            field_spec=voltage_spec,
        )
        self.assertIn("3", value)
        self.assertIn("32", value)
        self.assertNotIn("±14", value)
        self.assertIn("3 V to 32 V", excerpt)

    def test_dual_rail_test_vs_single_span_stays_needs_data(self):
        status, note = compare_field_values(
            "VS = ±14 V",
            "3 V to 32 V",
            FieldSpec(key="voltage_range", label="Supply voltage", compare=COMPARE_EXACT, unit="V"),
        )
        self.assertEqual(status, "Needs data")
        self.assertIn("test-condition", note.casefold())
        self.assertIn("unknown", note.casefold())


class UiLayoutContractTests(unittest.TestCase):
    def test_replacement_and_compare_tables_allocate_all_columns(self):
        css = WEB_CSS.read_text(encoding="utf-8")
        self.assertIn(".cv-table.cv-table-actions th:nth-child(6)", css)
        self.assertIn(".cv-table.cv-table-actions th:nth-child(4)", css)
        self.assertIn(".cv-table.cv-table-actions th:nth-child(5)", css)
        self.assertIn("min-width: 920px", css)
        self.assertIn(".cv-compare-table th:nth-child(6)", css)
        self.assertIn(".cv-compare-table th:nth-child(7)", css)
        self.assertIn(".cv-compare-multi-table", css)
        # Width percentages for the first five compare columns must not sum to 100% alone.
        self.assertNotRegex(
            css,
            r"\.cv-compare-table th:nth-child\(1\) \{ width: 15%; \}\s*"
            r"\.cv-compare-table th:nth-child\(2\),\s*"
            r"\.cv-compare-table th:nth-child\(3\) \{ width: 18%; \}\s*"
            r"\.cv-compare-table th:nth-child\(4\) \{ width: 17%; \}\s*"
            r"\.cv-compare-table th:nth-child\(5\) \{ width: 32%; \}",
        )

    def test_compare_page_supports_multi_alternate_matrix(self):
        source = COMPARE_PAGE.read_text(encoding="utf-8")
        self.assertIn("parseCandidateMpns", source)
        self.assertIn("buildMultiCompareMatrix", source)
        self.assertIn("cv-compare-multi-table", source)
        self.assertIn("does not imply drop-in compatibility", source.casefold())

    def test_bom_analyzer_materializes_file_before_validation(self):
        analyzer = BOM_ANALYZER.read_text(encoding="utf-8")
        identity = BOM_IDENTITY.read_text(encoding="utf-8")
        draft = (ROOT / "apps" / "web" / "src" / "lib" / "bomDraft.ts").read_text(encoding="utf-8")
        self.assertIn("materializeBomFile", identity)
        self.assertIn("materializeBomFile", analyzer)
        self.assertIn("Re-select the file to continue", analyzer)
        self.assertIn("Validation continues with the file still in memory", analyzer)
        # Draft persistence must not gate POST /boms/validate.
        self.assertIn("void saveDraftFile(", analyzer)
        self.assertNotIn("await saveDraftFile(", analyzer)
        self.assertIn("onblocked", draft)
        self.assertIn("Timed out saving BOM draft file.", draft)

    def test_design_impact_aggregates_all_workspace_boms(self):
        source = DESIGN_IMPACT.read_text(encoding="utf-8")
        self.assertNotIn("analysisId: last?.analysis_id", source)
        self.assertIn("combined quantity", source.casefold())
        self.assertIn("intel.total_quantity", source)


if __name__ == "__main__":
    unittest.main()
