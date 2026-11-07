"""Validation preview reuses parse path without running analysis."""

from __future__ import annotations

import unittest

from apps.api.bom_validation import validation_preview


class BomValidationPreviewTests(unittest.TestCase):
    def test_valid_csv_can_analyze(self):
        preview = validation_preview(
            "motor.csv",
            b"MPN,Quantity,Manufacturer\nLM358DR,4,TI\nCRCW060310K0FKEA,10,Vishay\n",
        )
        self.assertTrue(preview["can_analyze"])
        self.assertEqual(preview["unique_part_count"], 2)
        self.assertEqual(preview["row_count"], 2)
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


if __name__ == "__main__":
    unittest.main()
