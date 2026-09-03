"""Evidence-integrity regressions for DigiKey Direct/Upgrade/Similar labeling."""
from __future__ import annotations

import importlib
import sys
import types
import unittest

sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))


def _cache_data(*_args, **_kwargs):
    return lambda func: func


def _relationship(supplier, original, candidate, substitute_type, url=""):
    return {
        "supplier": supplier,
        "supplier_part_id": f"{candidate}-DK",
        "original_mpn": original,
        "candidate_mpn": candidate,
        "substitute_type": substitute_type,
        "raw_substitute_type": substitute_type,
        "source_url": url or f"https://www.digikey.com/en/products/{candidate}",
        "evidence_type": "Distributor-listed substitute",
        "summary": f"{supplier} substitute type: {substitute_type}",
    }


class AlternativeEvidenceIntegrityTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.SimpleNamespace(cache_data=_cache_data)
        sys.modules.pop("src.alternative_engine", None)
        sys.modules.pop("integrations.digikey_client", None)
        self.engine = importlib.import_module("src.alternative_engine")
        self.classification = importlib.import_module("src.alternative_classification")
        self.digikey = importlib.import_module("integrations.digikey_client")
        self.datasheet = importlib.import_module("src.datasheet_comparison")

        capacitor_fields = {
            "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            "capacitance": "0.1 µF",
            "tolerance": "±10%",
            "dielectric": "X7R",
            "package": "0603",
            "mounting_style": "Surface Mount, MLCC",
            "rated_voltage": "50V",
            "temperature_coefficient": "X7R",
            "stock_total": 10000,
            "unit_price": 0.05,
            "supplier_data_verified": True,
            "manufacturer": "KEMET",
        }

        def part_data(part_number):
            return dict(capacitor_fields, manufacturer_part_number=part_number)

        self.engine.get_best_part_data = part_data
        self.original = "C0603C104K5RACTU"

    def _c0603_fixture_rows(self):
        original = self.original
        rows = []
        for mpn, substitute_type in (
            ("C0603C104K5RAC3121", "Direct"),
            ("0603BB104K500YT", "Direct"),
            ("C0603C104J5RALTU", "Upgrade"),
            ("C0603G104K5RACT500", "Upgrade"),
            ("C0603G104K5RACTU", "Upgrade"),
            ("0603BB104K500NGT", "Upgrade"),
            ("CC0603KRX7R0BB104", "Upgrade"),
            ("C1608X7S2A104K080AB", "Similar"),
            ("C1608X8R1H104K080AB", "Similar"),
            ("C0603C104K5RAC7411", "Similar"),
        ):
            rows.append(
                {
                    "manufacturer_part_number": mpn,
                    "manufacturer": "KEMET",
                    "source": "DigiKey",
                    "substitute_type": substitute_type,
                    "evidence_type": "Distributor-listed substitute",
                    "original_mpn": original,
                    "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
                    "product_detail_url": f"https://www.digikey.com/en/products/{mpn}",
                    "digikey_part_number": f"{mpn}-ND",
                    "supplier_relationship_evidence": [
                        _relationship("DigiKey", original, mpn, substitute_type)
                    ],
                }
            )
        return rows

    def test_c0603_fixture_only_lists_exact_digikey_directs(self):
        explicit = self._c0603_fixture_rows()

        def discover(_part):
            merged = self.classification.merge_discovery_candidates(
                explicit,
                [],
                original_mpn=self.original,
            )
            return {
                "original_mpn": self.original,
                "candidates": merged,
                "provider_failures": [],
                "has_incomplete_evidence": False,
            }

        self.engine.discover_alternative_candidates = discover
        results = self.engine.suggest_alternatives_v2(self.original)
        by_part = {row["Alternative Part"]: row for row in results}

        for mpn in ("C0603C104K5RAC3121", "0603BB104K500YT"):
            self.assertEqual(
                by_part[mpn]["Classification"],
                self.classification.CLASS_VERIFIED_DIRECT,
            )
            self.assertEqual(by_part[mpn]["Substitute Type"], "Direct")
            self.assertIn(
                "DigiKey substitute type: Direct",
                by_part[mpn]["Supplier Relationship Summary"],
            )

        for mpn in (
            "C0603C104J5RALTU",
            "C0603G104K5RACT500",
            "C0603G104K5RACTU",
            "0603BB104K500NGT",
            "CC0603KRX7R0BB104",
        ):
            self.assertEqual(
                by_part[mpn]["Classification"],
                self.classification.CLASS_SUPPLIER_UPGRADE,
            )
            self.assertEqual(by_part[mpn]["Substitute Type"], "Upgrade")
            self.assertIn(
                "DigiKey substitute type: Upgrade",
                by_part[mpn]["Supplier Relationship Summary"],
            )

        for mpn in ("C1608X7S2A104K080AB", "C1608X8R1H104K080AB", "C0603C104K5RAC7411"):
            self.assertEqual(
                by_part[mpn]["Classification"],
                self.classification.CLASS_SUPPLIER_SIMILAR,
            )
            self.assertEqual(by_part[mpn]["Substitute Type"], "Similar")
            self.assertNotEqual(
                by_part[mpn]["Classification"],
                self.classification.CLASS_VERIFIED_DIRECT,
            )
            self.assertNotIn(
                "DigiKey identifies this candidate as a Direct",
                by_part[mpn]["Supplier Relationship Summary"],
            )

    def test_spec_matched_without_exact_direct_relationship(self):
        catalog = [
            {
                "manufacturer_part_number": "GRM188R71H104KA93D",
                "source": "DigiKey",
                "substitute_type": "Similar",
                "evidence_type": "Distributor catalog match",
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
                "original_mpn": self.original,
            }
        ]

        def discover(_part):
            return {
                "original_mpn": self.original,
                "candidates": self.classification.merge_discovery_candidates(
                    [],
                    catalog,
                    original_mpn=self.original,
                ),
                "provider_failures": [],
                "has_incomplete_evidence": False,
            }

        self.engine.discover_alternative_candidates = discover
        result = self.engine.suggest_alternatives_v2(self.original)[0]
        self.assertIn(
            result["Classification"],
            {
                self.classification.CLASS_SPEC_MATCHED,
                self.classification.CLASS_CATALOG_INSUFFICIENT,
            },
        )
        self.assertNotEqual(
            result["Classification"],
            self.classification.CLASS_VERIFIED_DIRECT,
        )
        self.assertNotIn(
            "DigiKey substitute type: Direct",
            result.get("Supplier Relationship Summary", ""),
        )

    def test_merge_does_not_leak_direct_evidence_across_part_numbers(self):
        direct = {
            "manufacturer_part_number": "C0603C104K5RAC3121",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": self.original,
            "supplier_relationship_evidence": [
                _relationship("DigiKey", self.original, "C0603C104K5RAC3121", "Direct")
            ],
        }
        similar = {
            "manufacturer_part_number": "C0603C104K5RAC7411",
            "source": "DigiKey",
            "substitute_type": "Similar",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": self.original,
            "supplier_relationship_evidence": [
                _relationship("DigiKey", self.original, "C0603C104K5RAC7411", "Similar")
            ],
        }
        merged = self.classification.merge_discovery_candidates(
            [direct, similar],
            [
                {
                    "manufacturer_part_number": "C0603C104K5RAC7411",
                    "source": "DigiKey",
                    "substitute_type": "Direct",
                    "evidence_type": "Distributor catalog match",
                }
            ],
            original_mpn=self.original,
        )
        by_part = {row["manufacturer_part_number"]: row for row in merged}
        self.assertEqual(by_part["C0603C104K5RAC3121"]["substitute_type"], "Direct")
        self.assertEqual(by_part["C0603C104K5RAC7411"]["substitute_type"], "Similar")
        leaked = any(
            str(row.get("substitute_type")) == "Direct"
            for row in by_part["C0603C104K5RAC7411"].get("supplier_relationship_evidence") or []
        )
        self.assertFalse(leaked)

    def test_conservative_merge_when_same_mpn_has_conflicting_types(self):
        first = {
            "manufacturer_part_number": "C0603C104K5RAC7411",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": self.original,
            "supplier_relationship_evidence": [
                _relationship("DigiKey", self.original, "C0603C104K5RAC7411", "Direct")
            ],
        }
        second = {
            "manufacturer_part_number": "C0603C104K5RAC7411",
            "source": "DigiKey",
            "substitute_type": "Similar",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": self.original,
            "supplier_relationship_evidence": [
                _relationship("DigiKey", self.original, "C0603C104K5RAC7411", "Similar")
            ],
        }
        merged = self.classification.merge_discovery_candidates(
            [first, second],
            [],
            original_mpn=self.original,
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["substitute_type"], "Similar")
        classification = self.classification.classify_from_supplier_evidence(
            merged[0],
            original_mpn=self.original,
        )
        self.assertEqual(classification, self.classification.CLASS_SUPPLIER_SIMILAR)

    def test_non_digikey_candidate_cannot_render_digikey_direct_without_record(self):
        assessment = self.datasheet.build_engineering_evidence_assessment(
            {"Match": 6, "Different": 0, "Needs data": 0},
            classification=self.classification.CLASS_SPEC_MATCHED,
            substitute_type="Unknown",
            evidence_source="Mouser",
            supplier_relationship_evidence=[],
        )
        self.assertNotIn("DigiKey", assessment["supplier_relationship_summary"])
        self.assertNotIn("Direct", assessment["supplier_relationship_summary"])

        mouser_direct = self.datasheet.build_engineering_evidence_assessment(
            {"Match": 6, "Different": 0, "Needs data": 0},
            classification=self.classification.CLASS_VERIFIED_DIRECT,
            substitute_type="Direct",
            evidence_source="Mouser",
            supplier_relationship_evidence=[
                _relationship("Mouser", self.original, "ALT-1", "Direct")
            ],
        )
        self.assertIn("Mouser substitute type: Direct", mouser_direct["supplier_relationship_summary"])
        self.assertNotIn(
            "DigiKey identifies this candidate as a Direct",
            mouser_direct["supplier_relationship_summary"],
        )

    def test_digikey_empty_products_fallback_does_not_invent_substitutes(self):
        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "ProductSubstitutes": [],
                    "Products": [
                        {
                            "ManufacturerProductNumber": "C0603C104K5RAC7411",
                            "SubstituteType": "Direct",
                            "DigiKeyProductNumber": "7411-ND",
                        }
                    ],
                }

        self.digikey.get_secret = lambda *_a, **_k: "client-id"
        self.digikey.get_digikey_access_token = lambda: "token"
        self.digikey._search_digikey_exact_product = lambda *_a, **_k: {
            "DigiKeyProductNumber": "ORIG-ND",
            "ProductVariations": [{"DigiKeyProductNumber": "ORIG-ND"}],
        }
        self.digikey.requests.get = lambda *_a, **_k: _Response()
        results = self.digikey.search_digikey_substitutions(self.original)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
