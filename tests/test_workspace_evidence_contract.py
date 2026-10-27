"""Focused contracts for shared workspace width and evidence wording."""
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceEvidenceContractTests(unittest.TestCase):
    def test_compare_parts_uses_the_home_canvas_width(self):
        source = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
        mapping = source.split("for _renderer_name, _width_variant in (", 1)[1].split("):", 1)[0]
        self.assertIn('("render_home", "standard")', mapping)
        self.assertIn('("render_monitoring", "standard")', mapping)
        self.assertIn('("render_compare_live", "standard")', mapping)
        self.assertNotIn('("render_compare_live", "wide")', mapping)

    def test_shell_geometry_survives_reruns_and_stacks_narrow_cards(self):
        bridge = (ROOT / "src" / "components" / "browser_navigation" / "index.html").read_text(encoding="utf-8")
        self.assertIn("cadivor-shell-geometry-lock", bridge)
        self.assertIn("margin-left:0!important", bridge)
        self.assertIn("grid-template-columns:1fr!important", bridge)
        self.assertIn("width:48px!important", bridge)

    def test_home_review_count_uses_the_report_part_definition(self):
        from src.ui.approved_pages import bom_needs_report_review

        health_only = {"health_score": 70, "high_risk_count": 0, "medium_risk_count": 0, "low_risk_count": 4, "total_parts": 4}
        medium_only = {"health_score": 80, "high_risk_count": 0, "medium_risk_count": 3, "low_risk_count": 1, "total_parts": 4}
        clear = {"health_score": 95, "high_risk_count": 0, "medium_risk_count": 0, "low_risk_count": 4, "total_parts": 4}
        self.assertFalse(bom_needs_report_review(health_only))
        self.assertTrue(bom_needs_report_review(medium_only))
        self.assertFalse(bom_needs_report_review(clear))

    def test_missing_price_keeps_the_number_and_does_not_invent_currency(self):
        from src.procurement_advisor import money_label

        self.assertEqual(money_label(433.4, ""), "433.4 (currency not recorded)")
        self.assertEqual(money_label(433.4, "USD"), "433.4 USD")
        self.assertEqual(money_label(None, "USD"), "Not reported by supplier")

    def test_source_count_is_not_presented_as_the_offer_table(self):
        from src.procurement_advisor import procurement_part_summary_html

        html = procurement_part_summary_html(
            {
                "mpn": "LM358DR",
                "supplier_offers": [{"supplier": "Newark", "unit_price": 1.2, "currency": "USD", "stock": 0}],
            },
            {"Recommendation": "Complete sourcing data", "Supplier Sources": 3, "Lifecycle Status": "Active"},
        )
        self.assertIn("3 recorded sources", html)
        self.assertIn("1 offer row in the table", html)
        self.assertNotIn("Resolve the verified supply gap", html)

    def test_confirmed_zero_stock_is_not_called_missing(self):
        from src.procurement_advisor import supplier_comparison_table_html

        html = supplier_comparison_table_html(
            {
                "mpn": "NE555P",
                "supplier_offers": [
                    {"supplier": "Newark", "unit_price": 433.4, "currency": "", "stock": 0},
                ],
            }
        )
        self.assertIn("433.4 (currency not recorded)", html)
        self.assertIn("Confirmed zero in the saved quote", html)
        self.assertNotIn("No stock reported", html)

    def test_lifecycle_conflict_names_saved_sources(self):
        from src.procurement_advisor import procurement_part_summary_html

        html = procurement_part_summary_html(
            {
                "mpn": "LM358DR",
                "lifecycle_evidence": [
                    {"source": "Newark", "status": "Active", "retrieved_at": "2026-10-01"},
                    {"source": "Mouser", "status": "NRND", "retrieved_at": "2026-10-02"},
                ],
            },
            {"Lifecycle Status": "Conflicting supplier data", "Supplier Sources": 2},
        )
        self.assertIn("Sources disagree", html)
        self.assertIn("Newark", html)
        self.assertIn("Mouser", html)

    def test_generic_risk_reason_does_not_invent_a_recommendation(self):
        from src.ui.ei_bom_report import _part_rows

        rows = _part_rows([
            {
                "mpn": "LM358DR",
                "risk_level": "Medium",
                "risk_score": 60,
                "supplier_count": 4,
                "stock_available": 1000,
                "lifecycle_status": "Active",
            }
        ])
        self.assertEqual(rows[0]["level"], "Medium")
        self.assertIn("does not record a part-specific exception", " ".join(rows[0]["drivers"]))
        self.assertEqual(rows[0]["action"], "No part-specific recommendation")

    def test_synthetic_compare_without_supplier_evidence_returns_a_clear_failure(self):
        from src.parts_compare import run_compare_parts_many

        def missing(_mpn):
            return {"found": False, "mpn": _mpn}

        with patch("src.parts_compare.lookup_part_for_compare", side_effect=missing):
            result = run_compare_parts_many(["LM358DR", "NE555P"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("could not retrieve", result["error"].casefold())
        self.assertEqual(result["part_numbers"], ["LM358DR", "NE555P"])


if __name__ == "__main__":
    unittest.main()
