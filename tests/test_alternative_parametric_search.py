import sys
import types
import unittest
from pathlib import Path


def _identity_cache(*_args, **_kwargs):
    return lambda function: function


if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = types.SimpleNamespace(cache_data=_identity_cache)
elif not hasattr(sys.modules["streamlit"], "cache_data"):
    sys.modules["streamlit"].cache_data = _identity_cache
sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))

from src.alternative_classification import CLASS_CATALOG_INSUFFICIENT, classification_sort_key
from src.alternative_engine import _discovery_row_to_part_data, apply_supplier_enrichment_to_candidate
from integrations.supplier_aggregator import (
    _parametric_catalog_search_terms,
    _provider_discovery_status,
)
from src.alternative_finder_search import supplier_search_coverage_rows


class AlternativeParametricSearchTests(unittest.TestCase):
    def test_capacitor_source_attributes_form_a_spec_led_search(self):
        terms = _parametric_catalog_search_terms({
            "manufacturer_part_number": "GRM188R71H104KA93D",
            "description": "Multilayer Ceramic Capacitor",
            "capacitance": "0.1 µF",
            "rated_voltage": "50V",
            "dielectric": "X7R",
            "package": "0603",
        })
        self.assertEqual(len(terms), 1)
        self.assertIn("0.1uF", terms[0])
        self.assertIn("50V", terms[0])
        self.assertIn("X7R", terms[0])
        self.assertIn("0603", terms[0])
        self.assertIn("capacitor", terms[0])

    def test_insufficient_source_data_does_not_create_a_guessing_query(self):
        self.assertEqual(
            _parametric_catalog_search_terms({
                "manufacturer_part_number": "GRM188R71H104KA93D",
                "description": "Capacitor",
                "capacitance": "0.1 µF",
            }),
            [],
        )

    def test_same_spec_capacitor_leads_rank_above_wrong_capacitance(self):
        source = {
            "manufacturer_part_number": "GRM188R71H104KA93D",
            "description": "Multilayer Ceramic Capacitor",
            "capacitance": "0.1 µF",
            "tolerance": "±10%",
            "rated_voltage": "50V",
            "dielectric": "X7R",
            "package": "0603 (1608 Metric)",
        }

        def evaluate(mpn, capacitance, voltage):
            discovery = {
                "manufacturer_part_number": mpn,
                "description": f"CAP CER {capacitance} {voltage} X7R 0603",
                "capacitance": capacitance,
                "tolerance": "±10%",
                "rated_voltage": voltage,
                "dielectric": "X7R",
                "package": "0603 (1608 Metric)",
                "source": "DigiKey",
                "stock_total": 10000,
                "lifecycle_status": "Active",
            }
            candidate = {
                "Alternative Part": mpn,
                "Classification": CLASS_CATALOG_INSUFFICIENT,
                "Category": CLASS_CATALOG_INSUFFICIENT,
                "Supplier": "DigiKey",
                "Lifecycle": "Active",
                "Substitute Type": "Similar",
                "Recommendation Score": 45,
            }
            return apply_supplier_enrichment_to_candidate(
                original_data=source,
                candidate=candidate,
                candidate_supplier_data=_discovery_row_to_part_data(discovery),
                canonical_part_number=source["manufacturer_part_number"],
            )

        matching = evaluate("GRM188R72A104KA35D", "0.1 µF", "100V")
        wrong_value = evaluate("GRM1885C1H472JA01D", "4700 pF", "50V")

        self.assertEqual(matching["Comparison Counts"]["Different"], 0)
        self.assertEqual(wrong_value["Comparison Counts"]["Different"], 1)
        self.assertGreater(matching["Recommendation Score"], wrong_value["Recommendation Score"])
        self.assertLess(classification_sort_key(matching), classification_sort_key(wrong_value))

    def test_search_coverage_distinguishes_explicit_and_catalog_leads(self):
        rows = supplier_search_coverage_rows({
            "providers": {
                "DigiKey": {
                    "substitutions": "ok",
                    "explicit_count": 0,
                    "catalog": "ok",
                    "catalog_count": 21,
                    "family_search": "ok",
                    "parametric_search": "ok",
                    "parametric_count": 4,
                },
                "Mouser": {
                    "substitutions": "not_supported",
                    "catalog": "not_configured",
                    "lookup": "not_configured",
                },
            }
        })
        digikey = dict(rows)["DigiKey"]
        mouser = dict(rows)["Mouser"]
        self.assertIn("explicit substitute check: 0 returned", digikey)
        self.assertIn("catalog search: 21 leads", digikey)
        self.assertIn("spec-led search: 4 leads", digikey)
        self.assertIn("not provided by this supplier", mouser)
        self.assertIn("not configured", mouser)

    def test_unconfigured_catalog_provider_is_not_misreported_as_searched(self):
        # This module-level helper uses the aggregator's shared credential check.
        from integrations import supplier_aggregator

        original = supplier_aggregator._provider_configured
        supplier_aggregator._provider_configured = lambda _name: False
        try:
            status = _provider_discovery_status("Mouser")
        finally:
            supplier_aggregator._provider_configured = original

        self.assertEqual(status["substitutions"], "not_supported")
        self.assertEqual(status["catalog"], "not_configured")
        self.assertEqual(status["family_search"], "not_configured")
        coverage = dict(supplier_search_coverage_rows({"providers": {"Mouser": status}}))
        self.assertIn("catalog search: not configured", coverage["Mouser"])
        self.assertIn("family search: not configured", coverage["Mouser"])

    def test_replacement_screen_discloses_supplier_coverage_without_a_collapsed_expander(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "ui"
            / "approved_pages.py"
        ).read_text(encoding="utf-8")
        coverage = source.split('with st.container(key="approved_replacement_search_coverage")', 1)[1]
        coverage = coverage.split("if excluded_obsolete:", 1)[0]
        self.assertIn("Supplier search coverage", coverage)
        self.assertIn("not configured", coverage)
        self.assertNotIn("st.expander", coverage)


if __name__ == "__main__":
    unittest.main()
