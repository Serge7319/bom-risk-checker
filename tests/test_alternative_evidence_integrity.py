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

    def test_c7411_without_exact_direct_pair_record_is_not_verified_direct(self):
        catalog_only = {
            "manufacturer_part_number": "C0603C104K5RAC7411",
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor catalog match",
            "original_mpn": self.original,
            "supplier_relationship_evidence": [],
        }
        leaked_from_sibling = {
            "manufacturer_part_number": "C0603C104K5RAC7411",
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": self.original,
            "supplier_relationship_evidence": [
                _relationship(
                    "DigiKey",
                    "C0603C104K5RAC3121",
                    "C0603C104K5RAC7411",
                    "Direct",
                )
            ],
        }
        for candidate in (catalog_only, leaked_from_sibling):
            classification = self.classification.classify_from_supplier_evidence(
                candidate,
                original_mpn=self.original,
                original_manufacturer="KEMET",
            )
            self.assertNotEqual(
                classification,
                self.classification.CLASS_VERIFIED_DIRECT,
                candidate,
            )
            self.assertFalse(
                self.classification.has_exact_direct_relationship(
                    candidate,
                    original_mpn=self.original,
                    candidate_mpn="C0603C104K5RAC7411",
                )
            )

        def discover(_part):
            merged = self.classification.merge_discovery_candidates(
                [],
                [catalog_only],
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
        row = next(
            item for item in results if item["Alternative Part"] == "C0603C104K5RAC7411"
        )
        self.assertNotEqual(row["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertNotIn(
            "DigiKey substitute type: Direct",
            row.get("Supplier Relationship Summary", ""),
        )

    def test_c0603_end_to_end_only_pair_supported_directs_are_verified(self):
        """End-to-end: DigiKey Direct only for pair-supported 3121/YT; never fabricated 7411 Direct.

        Live DigiKey ProductVariations often list sibling RAC7411 DigiKey numbers
        without ManufacturerProductNumber. Querying those SKUs and stamping
        original_mpn=C0603C104K5RACTU fabricated Verified Direct for RAC7411.
        """
        original = self.original

        class _Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        substitution_urls = []

        def post(*_args, **_kwargs):
            return _Response({
                "Products": [{
                    "ManufacturerProductNumber": original,
                    "DigiKeyProductNumber": "399-C0603C104K5RACTUCT-ND",
                    "ProductVariations": [
                        {"DigiKeyProductNumber": "399-C0603C104K5RACTUTR-ND"},
                        # Sibling family SKU with no manufacturer MPN — must be ignored.
                        {"DigiKeyProductNumber": "399-C0603C104K5RAC7411CT-ND"},
                    ],
                    "Manufacturer": {"Name": "KEMET"},
                    "Description": {"ProductDescription": "CAP CER 0.1UF 50V X7R 0603"},
                    "QuantityAvailable": 10000,
                }]
            })

        def get(url, **_kwargs):
            substitution_urls.append(url)
            if "7411" in url:
                # If queried, DigiKey would return a Direct row that older code
                # wrongly attributed to the original search MPN.
                return _Response({
                    "ProductSubstitutes": [{
                        "ManufacturerProductNumber": "C0603C104K5RAC7411",
                        "DigiKeyProductNumber": "399-C0603C104K5RAC7411CT-ND",
                        "Manufacturer": {"Name": "KEMET"},
                        "SubstituteType": "Direct",
                        "ProductUrl": "https://www.digikey.com/7411",
                        "QuantityAvailable": 50000,
                        "UnitPrice": 0.04,
                    }]
                })
            return _Response({
                "ProductSubstitutes": [
                    {
                        "ManufacturerProductNumber": "C0603C104K5RAC3121",
                        "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
                        "Manufacturer": {"Name": "KEMET"},
                        "SubstituteType": "Direct",
                        "ProductUrl": "https://www.digikey.com/3121",
                        "QuantityAvailable": 12000,
                        "UnitPrice": 0.05,
                    },
                    {
                        "ManufacturerProductNumber": "0603BB104K500YT",
                        "DigiKeyProductNumber": "0603BB104K500YT-ND",
                        "Manufacturer": {"Name": "ATC"},
                        "SubstituteType": "Direct",
                        "ProductUrl": "https://www.digikey.com/yt",
                        "QuantityAvailable": 8000,
                        "UnitPrice": 0.06,
                    },
                    {
                        "ManufacturerProductNumber": "C0603C104K5RAC7411",
                        "DigiKeyProductNumber": "399-C0603C104K5RAC7411CT-ND",
                        "Manufacturer": {"Name": "KEMET"},
                        "SubstituteType": "Similar",
                        "ProductUrl": "https://www.digikey.com/7411-similar",
                        "QuantityAvailable": 50000,
                        "UnitPrice": 0.04,
                    },
                ]
            })

        self.digikey.get_secret = lambda *_a, **_k: "client-id"
        self.digikey.get_digikey_access_token = lambda: "access-token"
        self.digikey.requests.post = post
        self.digikey.requests.get = get

        explicit = self.digikey.search_digikey_substitutions(original)
        catalog = [
            {
                "manufacturer_part_number": "C0603C104K5RAC7411",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "substitute_type": "Similar",
                "evidence_type": "Distributor catalog match",
                "original_mpn": original,
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            }
        ]
        merged = self.classification.merge_discovery_candidates(
            explicit,
            catalog,
            original_mpn=original,
        )

        def discover(_part):
            return {
                "original_mpn": original,
                "candidates": merged,
                "provider_failures": [],
                "has_incomplete_evidence": False,
            }

        self.engine.discover_alternative_candidates = discover
        results = self.engine.suggest_alternatives_v2(original)
        by_part = {row["Alternative Part"]: row for row in results}

        self.assertFalse(any("7411" in url for url in substitution_urls))
        self.assertEqual(
            by_part["C0603C104K5RAC3121"]["Classification"],
            self.classification.CLASS_VERIFIED_DIRECT,
        )
        self.assertEqual(
            by_part["0603BB104K500YT"]["Classification"],
            self.classification.CLASS_VERIFIED_DIRECT,
        )
        self.assertEqual(
            str(by_part["C0603C104K5RAC3121"]["Supplier Relationship Summary"]).count(
                "DigiKey substitute type: Direct"
            ),
            1,
        )
        self.assertTrue(
            self.classification.has_exact_direct_relationship(
                {
                    "manufacturer_part_number": "C0603C104K5RAC3121",
                    "evidence_type": by_part["C0603C104K5RAC3121"]["Evidence Type"],
                    "supplier_relationship_evidence": by_part["C0603C104K5RAC3121"][
                        "Supplier Relationship Evidence"
                    ],
                },
                original_mpn=original,
                candidate_mpn="C0603C104K5RAC3121",
            )
        )
        self.assertNotEqual(
            by_part["C0603C104K5RAC7411"]["Classification"],
            self.classification.CLASS_VERIFIED_DIRECT,
        )
        self.assertFalse(
            self.classification.has_exact_direct_relationship(
                {
                    "manufacturer_part_number": "C0603C104K5RAC7411",
                    "evidence_type": by_part["C0603C104K5RAC7411"]["Evidence Type"],
                    "supplier_relationship_evidence": by_part["C0603C104K5RAC7411"][
                        "Supplier Relationship Evidence"
                    ],
                },
                original_mpn=original,
                candidate_mpn="C0603C104K5RAC7411",
            )
        )
        self.assertNotIn(
            "DigiKey substitute type: Direct",
            by_part["C0603C104K5RAC7411"].get("Supplier Relationship Summary", ""),
        )

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

    def test_rac7411_cannot_reach_direct_from_non_pair_scoped_paths(self):
        """RAC7411 must not become Direct/Verified Direct without TU→7411 pair evidence."""
        original = self.original
        candidate = "C0603C104K5RAC7411"

        # 1) Catalog Direct claim with no pair evidence.
        catalog_direct = {
            "manufacturer_part_number": candidate,
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor catalog match",
            "original_mpn": original,
            "supplier_relationship_evidence": [],
        }
        # 2) Sibling SKU Direct evidence (wrong original_mpn).
        sibling_leak = {
            "manufacturer_part_number": candidate,
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": original,
            "supplier_relationship_evidence": [
                _relationship("DigiKey", "C0603C104K5RAC3121", candidate, "Direct")
            ],
        }
        # 3) Candidate's own family/SKU Direct mention without original=TU pair.
        own_sku_direct = {
            "manufacturer_part_number": candidate,
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": candidate,
            "supplier_relationship_evidence": [
                _relationship("DigiKey", candidate, candidate, "Direct")
            ],
        }
        # 4) Top-level Direct only (no evidence rows).
        top_level_only = {
            "manufacturer_part_number": candidate,
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": original,
        }

        for payload in (catalog_direct, sibling_leak, own_sku_direct, top_level_only):
            classification = self.classification.classify_from_supplier_evidence(
                payload,
                original_mpn=original,
                original_manufacturer="KEMET",
            )
            self.assertNotEqual(
                classification,
                self.classification.CLASS_VERIFIED_DIRECT,
                payload,
            )
            self.assertFalse(
                self.classification.has_exact_direct_relationship(
                    payload,
                    original_mpn=original,
                    candidate_mpn=candidate,
                ),
                payload,
            )
            assessment = self.datasheet.build_engineering_evidence_assessment(
                {"Match": 6, "Different": 0, "Needs data": 0},
                classification=classification,
                substitute_type=payload.get("substitute_type"),
                evidence_source="DigiKey",
                supplier_relationship_evidence=self.classification.pair_relationship_evidence_rows(
                    payload,
                    original_mpn=original,
                    candidate_mpn=candidate,
                ),
            )
            self.assertNotIn(
                "DigiKey substitute type: Direct",
                assessment["supplier_relationship_summary"],
                payload,
            )

        # Exact TU→3121 pair evidence still yields Verified Direct + one-line display.
        pair_3121 = {
            "manufacturer_part_number": "C0603C104K5RAC3121",
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
            "original_mpn": original,
            "supplier_relationship_evidence": [
                _relationship("DigiKey", original, "C0603C104K5RAC3121", "Direct")
            ],
        }
        self.assertEqual(
            self.classification.classify_from_supplier_evidence(
                pair_3121,
                original_mpn=original,
                original_manufacturer="KEMET",
            ),
            self.classification.CLASS_VERIFIED_DIRECT,
        )
        summary = self.classification.relationship_evidence_summary(
            pair_3121["supplier_relationship_evidence"]
        )
        self.assertEqual(summary.count("DigiKey substitute type: Direct"), 1)

        def discover(_part):
            merged = self.classification.merge_discovery_candidates(
                [pair_3121],
                [catalog_direct, sibling_leak],
                original_mpn=original,
            )
            return {
                "original_mpn": original,
                "candidates": merged,
                "provider_failures": [],
                "has_incomplete_evidence": False,
            }

        self.engine.discover_alternative_candidates = discover
        results = self.engine.suggest_alternatives_v2(original)
        by_part = {row["Alternative Part"]: row for row in results}
        self.assertEqual(
            by_part["C0603C104K5RAC3121"]["Classification"],
            self.classification.CLASS_VERIFIED_DIRECT,
        )
        self.assertEqual(
            str(by_part["C0603C104K5RAC3121"]["Supplier Relationship Summary"]).count(
                "DigiKey substitute type: Direct"
            ),
            1,
        )
        self.assertNotEqual(
            by_part[candidate]["Classification"],
            self.classification.CLASS_VERIFIED_DIRECT,
        )
        self.assertNotIn(
            "DigiKey substitute type: Direct",
            by_part[candidate].get("Supplier Relationship Summary", ""),
        )


if __name__ == "__main__":
    unittest.main()
