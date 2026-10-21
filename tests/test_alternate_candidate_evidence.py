import unittest

from src.alternate_candidate_evidence import normalize_candidate_evidence


class AlternateCandidateEvidenceTests(unittest.TestCase):
    def test_candidate_snapshot_keeps_reviewable_evidence_and_drops_internal_payloads(self):
        rows = normalize_candidate_evidence(
            [
                {
                    "Alternative Part": "LM317BS-TR",
                    "Manufacturer": "STMicroelectronics",
                    "Supplier": "DigiKey",
                    "Classification": "Supplier-listed similar",
                    "Evidence Type": "Catalog search",
                    "Primary Category": "Integrated Circuits",
                    "package": "SOT-223",
                    "pin_count": 3,
                    "architecture": "Adjustable linear regulator",
                    "Lifecycle": "Active",
                    "Source URL": "https://supplier.example/LM317BS-TR",
                    "Datasheet URL": "https://vendor.example/lm317.pdf",
                    "Retrieved At": "2026-10-21T12:00:00Z",
                    "_discovery_row": {"secret": "discard me"},
                },
                {"Alternative Part": "LM317BS-TR", "Supplier": "Duplicate"},
                {"Alternative Part": "LM317DCYR", "Supplier": "same part"},
                {"Alternative Part": "UNSAFE", "Source URL": "javascript:alert(1)"},
            ],
            original_mpn="LM317-DCYR",
        )

        self.assertEqual(len(rows), 2)
        candidate = rows[0]
        self.assertEqual(candidate["mpn"], "LM317BS-TR")
        self.assertEqual(candidate["relationship"], "Supplier-listed similar")
        self.assertEqual(candidate["package"], "SOT-223")
        self.assertEqual(candidate["pin_count"], 3)
        self.assertEqual(candidate["product_url"], "https://supplier.example/LM317BS-TR")
        self.assertEqual(candidate["datasheet_url"], "https://vendor.example/lm317.pdf")
        self.assertNotIn("_discovery_row", candidate)
        self.assertEqual(rows[1]["product_url"], "")

