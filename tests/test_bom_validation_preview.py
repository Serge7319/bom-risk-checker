"""Validation preview reuses parse path without running analysis."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from apps.api.bom_validation import MAX_BOM_UPLOAD_BYTES, validation_preview
from apps.api.synthetic_analyze import parse_bom_bytes

ROOT = Path(__file__).resolve().parents[1]
NESTED = ROOT / "tests" / "fixtures" / "nested_bom_product.csv"


class BomValidationPreviewTests(unittest.TestCase):
    def test_valid_csv_can_analyze(self):
        preview = validation_preview(
            "motor.csv",
            b"MPN,Quantity,Manufacturer\nLM358DR,4,TI\nCRCW060310K0FKEA,10,Vishay\n",
        )
        self.assertTrue(preview["can_analyze"])
        self.assertEqual(preview["unique_part_count"], 2)
        self.assertEqual(preview["row_count"], 2)
        self.assertEqual(preview["parsed_row_count"], 2)
        self.assertEqual(preview["errors"], [])
        normalized = {item["normalized"] for item in preview["detected_columns"]}
        self.assertIn("mpn", normalized)

    def test_missing_mpn_blocks_analyze(self):
        preview = validation_preview(
            "bad.csv",
            b"Description,Qty\nResistor,2\n",
        )
        self.assertFalse(preview["can_analyze"])
        self.assertTrue(preview["errors"] or preview["missing_required"])

    def test_empty_file_errors(self):
        preview = validation_preview("empty.csv", b"")
        self.assertFalse(preview["can_analyze"])
        self.assertIn("Empty file", preview["errors"])

    def test_duplicate_mpn_counts_source_rows_before_aggregation(self):
        payload = b"MPN,Quantity,Manufacturer\nAAA,2,TI\nAAA,3,TI\nBBB,1,ST\n"
        preview = validation_preview("dup.csv", payload)
        parsed = parse_bom_bytes("dup.csv", payload)
        self.assertEqual(preview["row_count"], 3, "source rows before aggregation")
        self.assertEqual(preview["unique_part_count"], 2)
        self.assertEqual(preview["parsed_row_count"], len(parsed.index))
        self.assertEqual(preview["parsed_row_count"], 2)
        self.assertEqual(int(parsed.loc[parsed["mpn"] == "AAA", "quantity"].iloc[0]), 5)

    def test_hierarchical_fixture_preserves_rows_and_quantities(self):
        payload = NESTED.read_bytes()
        preview = validation_preview("nested_bom_product.csv", payload)
        parsed = parse_bom_bytes("nested_bom_product.csv", payload)
        self.assertTrue(preview["can_analyze"])
        self.assertTrue(preview["has_hierarchy_columns"])
        self.assertEqual(preview["row_count"], 7)
        self.assertEqual(preview["parsed_row_count"], len(parsed.index))
        self.assertEqual(preview["unique_part_count"], 7)
        # Parser path parity: validation must not invent a different frame.
        again = parse_bom_bytes("nested_bom_product.csv", payload)
        self.assertEqual(list(parsed["mpn"]), list(again["mpn"]))

    def test_payload_over_10mb_rejected(self):
        payload = b"x" * (MAX_BOM_UPLOAD_BYTES + 1)
        preview = validation_preview("huge.csv", payload)
        self.assertFalse(preview["can_analyze"])
        self.assertEqual(preview.get("code"), "payload_too_large")
        self.assertIn("10 MB", preview["errors"][0])

    def test_validation_does_not_run_risk_scoring_or_persist(self):
        payload = b"MPN,Quantity,Manufacturer\nLM358DR,4,TI\n"
        with mock.patch("apps.api.bom_validation.parse_bom_bytes", wraps=parse_bom_bytes) as parsed:
            with mock.patch("apps.api.synthetic_analyze.analyze_upload") as analyze:
                with mock.patch("apps.api.synthetic_analyze.analyze_dataframe") as score:
                    from apps.api import synthetic_analyze as sa

                    before = dict(sa._REPORTS)
                    preview = validation_preview("safe.csv", payload)
                    self.assertTrue(preview["can_analyze"])
                    parsed.assert_called_once()
                    analyze.assert_not_called()
                    score.assert_not_called()
                    self.assertEqual(sa._REPORTS, before)


if __name__ == "__main__":
    unittest.main()
