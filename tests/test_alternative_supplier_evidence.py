import importlib
import sys
import types
import unittest

sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))


def _cache_data(*_args, **_kwargs):
    return lambda func: func


class AlternativeSupplierEvidenceTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.SimpleNamespace(cache_data=_cache_data)
        sys.modules.pop("src.alternative_engine", None)
        self.engine = importlib.import_module("src.alternative_engine")
        self.engine.get_best_part_data = lambda _part: {}

    def test_retains_direct_and_cross_manufacturer_supplier_candidates(self):
        self.engine.search_supplier_alternatives = lambda _part: [
            {
                "manufacturer_part_number": "C0603C104K5RAC3121",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
            },
            {
                "manufacturer_part_number": "0603BB104K500YT",
                "manufacturer": "Knowles Novacap",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
            },
        ]

        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        parts = {row["Alternative Part"] for row in results}
        self.assertEqual(parts, {"C0603C104K5RAC3121", "0603BB104K500YT"})
        self.assertTrue(all(row["Evidence Type"] == "Distributor-listed substitute" for row in results))

    def test_supplier_relationship_pipeline_is_category_agnostic(self):
        cases = {
            "SRN6045-100M": "SRN6045-100M-ALT",  # inductor
            "750311424": "750311425",  # transformer
            "SN74HC04N": "CD74HC04E",  # IC
        }
        for original, candidate in cases.items():
            with self.subTest(original=original):
                self.engine.search_supplier_alternatives = lambda _part, candidate=candidate: [{
                    "manufacturer_part_number": candidate,
                    "source": "DigiKey",
                    "substitute_type": "Upgrade",
                    "evidence_type": "Distributor-listed substitute",
                }]
                results = self.engine.suggest_alternatives_v2(original)
                self.assertEqual([row["Alternative Part"] for row in results], [candidate])

    def test_does_not_fabricate_hard_coded_candidates_without_supplier_evidence(self):
        self.engine.search_supplier_alternatives = lambda _part: []
        self.assertEqual(self.engine.suggest_alternatives_v2("LM358"), [])

    def test_catalog_candidate_is_visible_but_not_labeled_as_a_direct_substitute(self):
        self.engine.search_supplier_alternatives = lambda _part: [{
            "manufacturer_part_number": "LM358DT",
            "source": "DigiKey",
            "substitute_type": "Similar",
            "evidence_type": "Distributor catalog match",
        }]
        result = self.engine.suggest_alternatives_v2("LM358")[0]
        self.assertEqual(result["Category"], "Distributor catalog candidate")
        self.assertEqual(result["Evidence Type"], "Distributor catalog match")
        self.assertIn("catalog match", result["Recommendation"])

    def test_keeps_up_to_ten_supplier_listed_candidates(self):
        self.engine.search_supplier_alternatives = lambda _part: [
            {
                "manufacturer_part_number": f"CANDIDATE-{index}",
                "source": "DigiKey",
                "substitute_type": "Upgrade",
                "evidence_type": "Distributor-listed substitute",
            }
            for index in range(12)
        ]

        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")

        self.assertEqual(len(results), 10)


if __name__ == "__main__":
    unittest.main()
