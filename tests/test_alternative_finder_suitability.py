"""Regression coverage for Alternative Finder coverage notices and suitability ranking."""
from __future__ import annotations

import importlib
import sys
import types
import unittest

sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))


def _cache_data(*_args, **_kwargs):
    return lambda func: func


def _digikey_direct_pair(mpn: str, original: str = "C0603C104K5RACTU", **extra):
    """Build a DigiKey Direct candidate with exact original→candidate pair evidence."""
    row = {
        "manufacturer_part_number": mpn,
        "manufacturer": "KEMET",
        "source": "DigiKey",
        "substitute_type": "Direct",
        "evidence_type": "Distributor-listed substitute",
        "original_mpn": original,
        "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
        "supplier_relationship_evidence": [
            {
                "supplier": "DigiKey",
                "original_mpn": original,
                "candidate_mpn": mpn,
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
                "summary": "DigiKey relationship: Direct.",
                "supplier_part_id": f"{mpn}-DK",
                "source_url": f"https://www.digikey.com/en/products/{mpn}",
            }
        ],
    }
    row.update(extra)
    return row


class AlternativeFinderSuitabilityTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.SimpleNamespace(cache_data=_cache_data)
        sys.modules.pop("src.alternative_engine", None)
        sys.modules.pop("integrations.supplier_aggregator", None)
        self.engine = importlib.import_module("src.alternative_engine")
        self.classification = importlib.import_module("src.alternative_classification")
        self.diagnostics = importlib.import_module("integrations.supplier_diagnostics")

        capacitor_fields = {
            "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            "capacitance": "0.1 µF",
            "tolerance": "±10%",
            "dielectric": "X7R",
            "package": "0603",
            "mounting_style": "Surface Mount, MLCC",
            "rated_voltage": "50V",
            "temperature_coefficient": "X7R",
            "esr": "",
            "stock_total": 50000,
            "unit_price": 0.05,
            "supplier_data_verified": True,
            "manufacturer": "KEMET",
        }

        def part_data(part_number):
            return dict(capacitor_fields, manufacturer_part_number=part_number)

        self.engine.get_best_part_data = part_data
        self.capacitor_fields = capacitor_fields

    def _mock_discovery(self, explicit, catalog=None):
        catalog = catalog or []

        def discover(_part):
            merged = self.classification.merge_discovery_candidates(
                explicit,
                catalog,
                original_mpn="C0603C104K5RACTU",
            )
            return {
                "original_mpn": "C0603C104K5RACTU",
                "candidates": merged,
                "explicit_count": len(explicit),
                "catalog_count": len(catalog),
                "provider_failures": [],
                "has_incomplete_evidence": True,
                "retrieved_at": "2026-09-03T00:00:00+00:00",
                "providers": {
                    "DigiKey": {"substitutions": "ok", "catalog": "ok"},
                    "Octopart": {"lookup": "not_configured"},
                },
            }

        self.engine.discover_alternative_candidates = discover

    def test_octopart_configuration_notice_not_generic_configured_failure(self):
        coverage = self.diagnostics.build_alternative_finder_coverage_notices(
            original_data={
                "all_supplier_results": [
                    {"source": "Mouser", "provider_status": "AVAILABLE"},
                    {"source": "DigiKey", "provider_status": "AVAILABLE"},
                    {"source": "Newark", "provider_status": "AVAILABLE"},
                    {
                        "source": "Octopart",
                        "provider_status": "NOT_CONFIGURED",
                        "failure_category": self.diagnostics.CATEGORY_CONFIGURATION,
                    },
                ]
            },
            discovery_metadata={"has_incomplete_evidence": True, "provider_failures": []},
        )
        joined = " ".join(coverage["notices"]).casefold()
        self.assertTrue(coverage["notices"])
        self.assertIn("octopart is not configured", joined)
        self.assertIn("mouser, digikey, and newark", joined)
        self.assertNotIn("configured supplier sources were unavailable", joined)
        self.assertNotIn("temporarily unavailable", joined)
        self.assertFalse(coverage["runtime_failures"])
        self.assertEqual(coverage["configuration_sources"], ["Octopart"])

    def test_octopart_provider_error_does_not_override_discovery_not_configured(self):
        coverage = self.diagnostics.build_alternative_finder_coverage_notices(
            original_data={
                "all_supplier_results": [
                    {"source": "Mouser", "provider_status": "AVAILABLE"},
                    {"source": "DigiKey", "provider_status": "AVAILABLE"},
                    {"source": "Newark", "provider_status": "AVAILABLE"},
                    {
                        "source": "Octopart",
                        "provider_status": "PROVIDER_ERROR",
                        "error": "timed out",
                    },
                ]
            },
            discovery_metadata={
                "provider_failures": ["Octopart"],
                "providers": {"Octopart": {"lookup": "not_configured"}},
            },
        )
        self.assertEqual(
            coverage["notices"],
            [
                "Octopart is not configured for this environment. "
                "Results include Mouser, DigiKey, and Newark."
            ],
        )
        self.assertFalse(coverage["runtime_failures"])
        self.assertEqual(coverage["captions"], [])

    def test_production_ui_shape_octopart_unavailable_without_discovery_uses_config_notice(self):
        """Reproduce the live Railway UI payload after db8233d.

        Production showed provider-error/unavailable Octopart rows while the
        session discovery mirror was empty. Missing Nexar credentials must still
        force the configuration-specific notice — never the generic timeout copy.
        """
        import integrations.supplier_diagnostics as diagnostics

        original = diagnostics._octopart_credentials_configured
        diagnostics._octopart_credentials_configured = lambda: False
        self.addCleanup(
            lambda: setattr(
                diagnostics, "_octopart_credentials_configured", original
            )
        )
        coverage = self.diagnostics.build_alternative_finder_coverage_notices(
            original_data={
                "all_supplier_results": [
                    {"source": "Mouser", "provider_status": "AVAILABLE"},
                    {"source": "DigiKey", "provider_status": "AVAILABLE"},
                    {"source": "Newark", "provider_status": "AVAILABLE"},
                    {
                        "source": "Octopart",
                        "provider_status": "PROVIDER_ERROR",
                        "failure_category": self.diagnostics.CATEGORY_PROVIDER_ERROR,
                        "error": "No response from Octopart",
                    },
                ]
            },
            discovery_metadata={"provider_failures": ["Octopart"], "has_incomplete_evidence": True},
        )
        joined = " ".join(coverage["notices"] + coverage["captions"])
        self.assertEqual(
            coverage["notices"],
            [
                "Octopart is not configured for this environment. "
                "Results include Mouser, DigiKey, and Newark."
            ],
        )
        self.assertFalse(coverage["runtime_failures"])
        self.assertNotIn("did not respond", joined.casefold())
        self.assertNotIn("unavailable for this search", joined.casefold())
        self.assertEqual(
            self.diagnostics.supplier_coverage_label(
                "Octopart",
                "PROVIDER_ERROR",
                failure_category=self.diagnostics.CATEGORY_PROVIDER_ERROR,
            ),
            "Octopart: not configured",
        )

    def test_runtime_supplier_failure_keeps_distinct_notice(self):
        coverage = self.diagnostics.build_alternative_finder_coverage_notices(
            original_data={
                "all_supplier_results": [
                    {"source": "DigiKey", "provider_status": "AVAILABLE"},
                    {
                        "source": "Mouser",
                        "provider_status": "TIMEOUT",
                        "failure_category": self.diagnostics.CATEGORY_TIMEOUT,
                    },
                ]
            },
            discovery_metadata={"provider_failures": ["Mouser"]},
        )
        joined = " ".join(coverage["notices"]).casefold()
        self.assertIn("did not respond", joined)
        self.assertNotIn("octopart is not configured", joined)
        self.assertTrue(any("Mouser" in caption for caption in coverage["captions"]))

    def test_active_verified_direct_ranks_above_nfnd_peer(self):
        explicit = [
            _digikey_direct_pair("C0603C104K5RAC3121", lifecycle_status="Active"),
            _digikey_direct_pair(
                "C0603C104K5RACTU-NFND", lifecycle_status="Not For New Designs"
            ),
        ]
        self._mock_discovery(explicit)
        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        parts = [row["Alternative Part"] for row in results]
        self.assertLess(
            parts.index("C0603C104K5RAC3121"),
            parts.index("C0603C104K5RACTU-NFND"),
        )
        active = next(row for row in results if row["Alternative Part"] == "C0603C104K5RAC3121")
        nfnd = next(row for row in results if row["Alternative Part"] == "C0603C104K5RACTU-NFND")
        self.assertEqual(active["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertEqual(nfnd["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertEqual(
            active["Recommendation Suitability"],
            self.classification.SUITABILITY_PREFERRED,
        )
        self.assertEqual(
            nfnd["Recommendation Suitability"],
            self.classification.SUITABILITY_SUSTAINING,
        )
        self.assertGreater(active["Recommendation Score"], nfnd["Recommendation Score"])
        self.assertLessEqual(nfnd["Recommendation Score"], 74)
        self.assertLess(nfnd["Recommendation Score"], 75)
        self.assertIn("sustaining an existing design", nfnd["Recommendation"].casefold())

    def test_active_verified_direct_ranks_above_distributor_discontinuation(self):
        explicit = [
            _digikey_direct_pair("C0603C104K5RAC3121", lifecycle_status="Active"),
            _digikey_direct_pair(
                "C0603C104K5RACDISC", lifecycle_status="Discontinued at DigiKey"
            ),
        ]
        self._mock_discovery(explicit)
        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        parts = [row["Alternative Part"] for row in results]
        self.assertLess(
            parts.index("C0603C104K5RAC3121"),
            parts.index("C0603C104K5RACDISC"),
        )
        discontinued = next(
            row for row in results if row["Alternative Part"] == "C0603C104K5RACDISC"
        )
        self.assertEqual(
            discontinued["Classification"],
            self.classification.CLASS_VERIFIED_DIRECT,
        )
        self.assertEqual(
            discontinued["Recommendation Suitability"],
            self.classification.SUITABILITY_SOURCE_DISCONTINUATION,
        )
        self.assertLessEqual(discontinued["Recommendation Score"], 74)
        copy = discontinued["Recommendation"].casefold()
        self.assertIn("sustaining an existing design", copy)
        self.assertIn("not automatic manufacturer end-of-life", copy)

    def test_unknown_lifecycle_is_not_preferred_for_new_designs(self):
        suitability = self.classification.classify_recommendation_suitability(
            "Unknown",
            source="DigiKey",
        )
        self.assertEqual(
            suitability,
            self.classification.SUITABILITY_LIFECYCLE_VERIFY,
        )
        self.assertNotEqual(suitability, self.classification.SUITABILITY_PREFERRED)

        missing = self.classification.classify_recommendation_suitability("")
        self.assertEqual(
            missing,
            self.classification.SUITABILITY_LIFECYCLE_VERIFY,
        )

        adjusted = self.classification.apply_suitability_score_adjustment(89, suitability)
        self.assertEqual(adjusted["recommendation_score"], 70)
        self.assertLess(adjusted["recommendation_score"], 75)

        explicit = [
            _digikey_direct_pair("C0603C104K5RAC3121", lifecycle_status="Active"),
            _digikey_direct_pair("C0603C104K5RACUNK", lifecycle_status="Unknown"),
        ]
        self._mock_discovery(explicit)
        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        parts = [row["Alternative Part"] for row in results]
        self.assertLess(
            parts.index("C0603C104K5RAC3121"),
            parts.index("C0603C104K5RACUNK"),
        )
        unknown = next(
            row for row in results if row["Alternative Part"] == "C0603C104K5RACUNK"
        )
        self.assertEqual(unknown["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertEqual(
            unknown["Recommendation Suitability"],
            self.classification.SUITABILITY_LIFECYCLE_VERIFY,
        )
        self.assertNotEqual(
            unknown["Recommendation Suitability"],
            self.classification.SUITABILITY_PREFERRED,
        )
        self.assertLessEqual(unknown["Recommendation Score"], 74)
        copy = unknown["Recommendation"].casefold()
        self.assertIn("lifecycle verification", copy)
        self.assertIn("before new-design approval", copy)
        self.assertNotIn("preferred for new designs", copy)

    def test_verified_direct_label_preserved_when_suitability_downgraded(self):
        suitability = self.classification.classify_recommendation_suitability(
            "Not For New Designs",
            source="DigiKey",
        )
        self.assertEqual(suitability, self.classification.SUITABILITY_SUSTAINING)
        # Top-level Direct without pair evidence must not become Verified Direct.
        without_pair = self.classification.classify_from_supplier_evidence(
            {
                "evidence_type": "Distributor-listed substitute",
                "substitute_type": "Direct",
                "manufacturer_part_number": "C0603C104K5RACNFND",
                "manufacturer": "KEMET",
            },
            original_mpn="C0603C104K5RACTU",
            original_manufacturer="KEMET",
        )
        self.assertNotEqual(without_pair, self.classification.CLASS_VERIFIED_DIRECT)
        classification = self.classification.classify_from_supplier_evidence(
            _digikey_direct_pair("C0603C104K5RACNFND"),
            original_mpn="C0603C104K5RACTU",
            original_manufacturer="KEMET",
        )
        self.assertEqual(classification, self.classification.CLASS_VERIFIED_DIRECT)
        adjusted = self.classification.apply_suitability_score_adjustment(89, suitability)
        self.assertEqual(adjusted["recommendation_score"], 69)
        self.assertEqual(adjusted["suitability_penalty"], 5)

    def test_c3121_remains_top_active_verified_direct(self):
        explicit = [
            _digikey_direct_pair("C0603C104K5RAC3121", lifecycle_status="Active"),
            _digikey_direct_pair(
                "C0603C104K5RACNFND", lifecycle_status="Not For New Designs"
            ),
            _digikey_direct_pair(
                "C0603C104K5RACDISC", lifecycle_status="Discontinued at DigiKey"
            ),
            {
                "manufacturer_part_number": "GRM188R71H104KA93D",
                "manufacturer": "Murata",
                "source": "DigiKey",
                "substitute_type": "Similar",
                "evidence_type": "Distributor catalog match",
                "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
                "lifecycle_status": "Active",
            },
        ]
        self._mock_discovery(explicit)
        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        top = results[0]
        self.assertEqual(top["Alternative Part"], "C0603C104K5RAC3121")
        self.assertEqual(top["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertEqual(
            top["Recommendation Suitability"],
            self.classification.SUITABILITY_PREFERRED,
        )
        self.assertGreaterEqual(top["Recommendation Score"], 70)


    def test_live_equivalent_provider_error_renders_config_notice_and_coverage_field(self):
        """Final rendered notice + coverage field for live-equivalent Octopart payload."""
        import integrations.supplier_diagnostics as diagnostics

        original = diagnostics._octopart_credentials_configured
        diagnostics._octopart_credentials_configured = lambda: False
        self.addCleanup(
            lambda: setattr(diagnostics, "_octopart_credentials_configured", original)
        )
        original_data = {
            "all_supplier_results": [
                {"source": "Mouser", "provider_status": "AVAILABLE"},
                {"source": "DigiKey", "provider_status": "AVAILABLE"},
                {"source": "Newark", "provider_status": "AVAILABLE"},
                {
                    "source": "Octopart",
                    "provider_status": "PROVIDER_ERROR",
                    "failure_category": self.diagnostics.CATEGORY_PROVIDER_ERROR,
                    "error": "No response from Octopart",
                },
            ]
        }
        discovery = {
            "provider_failures": ["Octopart"],
            "has_incomplete_evidence": True,
            "providers": {"Octopart": {"lookup": "error", "substitutions": "skipped"}},
        }
        coverage = self.diagnostics.build_alternative_finder_coverage_notices(
            original_data=original_data,
            discovery_metadata=discovery,
        )
        expected_notice = (
            "Octopart is not configured for this environment. "
            "Results include Mouser, DigiKey, and Newark."
        )
        self.assertEqual(coverage["notices"], [expected_notice])
        self.assertEqual(coverage["captions"], [])
        self.assertFalse(coverage["runtime_failures"])
        self.assertIn("Octopart: not configured", coverage["coverage_field"])
        self.assertNotIn("unavailable for this search", coverage["coverage_field"])
        self.assertNotIn("did not respond", " ".join(coverage["notices"]).casefold())
        # Both renderers must agree via the canonical resolver.
        field = self.diagnostics.format_alternative_finder_provider_coverage(
            original_data=original_data,
            discovery_metadata=discovery,
        )
        self.assertEqual(field, coverage["coverage_field"])
        self.assertEqual(
            self.diagnostics.supplier_coverage_label(
                "Octopart",
                "PROVIDER_ERROR",
                failure_category=self.diagnostics.CATEGORY_PROVIDER_ERROR,
                discovery_metadata=discovery,
            ),
            "Octopart: not configured",
        )



if __name__ == "__main__":
    unittest.main()
