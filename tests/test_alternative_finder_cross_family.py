"""Component-agnostic Alternative Finder regressions across Cap/R/L/discrete/IC."""
from __future__ import annotations

import importlib
import sys
import types
import unittest

sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))


def _cache_data(*_args, **_kwargs):
    return lambda func: func


def _relationship(supplier, original, candidate, substitute_type):
    return {
        "supplier": supplier,
        "supplier_part_id": f"{candidate}-DK",
        "original_mpn": original,
        "candidate_mpn": candidate,
        "substitute_type": substitute_type,
        "raw_substitute_type": substitute_type,
        "source_url": f"https://www.digikey.com/en/products/{candidate}",
        "evidence_type": "Distributor-listed substitute",
        "summary": f"{supplier} relationship: {substitute_type}.",
    }


def _pair_candidate(
    *,
    original: str,
    candidate: str,
    substitute_type: str,
    description: str,
    manufacturer: str = "Example Mfr",
    lifecycle: str = "Active",
):
    return {
        "manufacturer_part_number": candidate,
        "manufacturer": manufacturer,
        "source": "DigiKey",
        "substitute_type": substitute_type,
        "evidence_type": "Distributor-listed substitute",
        "original_mpn": original,
        "description": description,
        "lifecycle_status": lifecycle,
        "supplier_relationship_evidence": [
            _relationship("DigiKey", original, candidate, substitute_type)
        ],
    }


FAMILY_FIXTURES = (
    {
        "family": "capacitor",
        "original": "C0603C104K5RACTU",
        "direct": "C0603C104K5RAC3121",
        "upgrade": "C0603C104J5RACTU",
        "similar": "C1608X7S2A104K080AB",
        "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
        "manufacturer": "KEMET",
    },
    {
        "family": "resistor",
        "original": "RC0603FR-0710KL",
        "direct": "RC0603FR-0710K",
        "upgrade": "ERJ-3EKF1002V",
        "similar": "CR0603-FX-1002ELF",
        "description": "Resistor 10kOhm 1% 1/10W 0603 SMD",
        "manufacturer": "YAGEO",
    },
    {
        "family": "inductor",
        "original": "SRN6045-100M",
        "direct": "SRN6045-100M-ALT",
        "upgrade": "SRR6028-100Y",
        "similar": "IHLP2525CZER100M01",
        "description": "Inductor Power 10uH 20% SMD",
        "manufacturer": "Bourns",
    },
    {
        "family": "diode",
        "original": "1N4148W-7-F",
        "direct": "1N4148WS-7-F",
        "upgrade": "BAV99-7-F",
        "similar": "MMBD4148",
        "description": "Diode Switching 100V SOD-123",
        "manufacturer": "Diodes Incorporated",
    },
    {
        "family": "ic",
        "original": "LM358DR",
        "direct": "LM358D",
        "upgrade": "LM2904DR",
        "similar": "TL072CDR",
        "description": "Operational Amplifier Dual SOIC-8",
        "manufacturer": "Texas Instruments",
    },
)


class AlternativeFinderCrossFamilyTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.SimpleNamespace(cache_data=_cache_data)
        for name in (
            "src.alternative_engine",
            "src.alternative_classification",
            "src.datasheet_comparison",
            "integrations.supplier_diagnostics",
            "integrations.supplier_aggregator",
            "integrations.mouser_client",
        ):
            sys.modules.pop(name, None)
        self.engine = importlib.import_module("src.alternative_engine")
        self.classification = importlib.import_module("src.alternative_classification")
        self.comparison = importlib.import_module("src.datasheet_comparison")
        self.diagnostics = importlib.import_module("integrations.supplier_diagnostics")
        self.aggregator = importlib.import_module("integrations.supplier_aggregator")
        self.mouser = importlib.import_module("integrations.mouser_client")

        def part_data(part_number):
            return {
                "manufacturer_part_number": part_number,
                "description": "Generic component",
                "supplier_data_verified": True,
                "package": "0603",
                "mounting_style": "Surface Mount",
            }

        self.engine.get_best_part_data = part_data

    def test_supplier_coverage_status_is_component_agnostic(self):
        import integrations.supplier_diagnostics as diagnostics

        original = diagnostics._octopart_credentials_configured
        diagnostics._octopart_credentials_configured = lambda: True
        self.addCleanup(
            lambda: setattr(diagnostics, "_octopart_credentials_configured", original)
        )
        for fixture in FAMILY_FIXTURES:
            with self.subTest(family=fixture["family"]):
                coverage = self.diagnostics.build_alternative_finder_coverage_notices(
                    original_data={
                        "all_supplier_results": [
                            {"source": "Mouser", "provider_status": "AVAILABLE"},
                            {"source": "DigiKey", "provider_status": "AVAILABLE"},
                            {"source": "Newark", "provider_status": "AVAILABLE"},
                            {
                                "source": "Octopart",
                                "provider_status": "PROVIDER_ERROR",
                                "failure_category": self.diagnostics.CATEGORY_HTTP_ERROR,
                                "error": "500 Server Error",
                            },
                        ]
                    },
                    discovery_metadata={"provider_failures": ["Octopart"]},
                )
                self.assertIn("did not respond", " ".join(coverage["notices"]).casefold())
                self.assertTrue(
                    any("Octopart: unavailable" in item["label"] for item in coverage["runtime_failures"])
                )
                self.assertIn("Octopart: unavailable for this search", coverage["coverage_field"])

        diagnostics._octopart_credentials_configured = lambda: False
        coverage = self.diagnostics.build_alternative_finder_coverage_notices(
            original_data={
                "all_supplier_results": [
                    {"source": "DigiKey", "provider_status": "AVAILABLE"},
                    {
                        "source": "Octopart",
                        "provider_status": "PROVIDER_ERROR",
                        "failure_category": self.diagnostics.CATEGORY_PROVIDER_ERROR,
                    },
                ]
            },
            discovery_metadata={},
        )
        self.assertEqual(
            coverage["notices"],
            [
                "Octopart is not configured for this environment. "
                "Results include Mouser, DigiKey, and Newark."
            ],
        )

    def test_exact_direct_evidence_classifies_across_families(self):
        for fixture in FAMILY_FIXTURES:
            with self.subTest(family=fixture["family"]):
                candidate = _pair_candidate(
                    original=fixture["original"],
                    candidate=fixture["direct"],
                    substitute_type="Direct",
                    description=fixture["description"],
                    manufacturer=fixture["manufacturer"],
                )
                classification = self.classification.classify_from_supplier_evidence(
                    candidate,
                    original_mpn=fixture["original"],
                    original_manufacturer=fixture["manufacturer"],
                )
                self.assertEqual(
                    classification,
                    self.classification.CLASS_VERIFIED_DIRECT,
                )
                self.assertTrue(
                    self.classification.has_exact_direct_relationship(
                        candidate,
                        original_mpn=fixture["original"],
                        candidate_mpn=fixture["direct"],
                    )
                )

    def test_non_pair_direct_looking_data_cannot_be_verified_direct(self):
        for fixture in FAMILY_FIXTURES:
            with self.subTest(family=fixture["family"]):
                paths = [
                    {
                        "manufacturer_part_number": fixture["direct"],
                        "manufacturer": fixture["manufacturer"],
                        "source": "DigiKey",
                        "substitute_type": "Direct",
                        "evidence_type": "Distributor catalog match",
                        "original_mpn": fixture["original"],
                        "description": fixture["description"],
                        "supplier_relationship_evidence": [],
                    },
                    {
                        "manufacturer_part_number": fixture["direct"],
                        "manufacturer": fixture["manufacturer"],
                        "source": "DigiKey",
                        "substitute_type": "Direct",
                        "evidence_type": "Distributor-listed substitute",
                        "original_mpn": fixture["original"],
                        "description": fixture["description"],
                        "supplier_relationship_evidence": [
                            _relationship(
                                "DigiKey",
                                fixture["upgrade"],
                                fixture["direct"],
                                "Direct",
                            )
                        ],
                    },
                    {
                        "manufacturer_part_number": fixture["direct"],
                        "manufacturer": fixture["manufacturer"],
                        "source": "DigiKey",
                        "substitute_type": "Direct",
                        "evidence_type": "Distributor-listed substitute",
                        "original_mpn": fixture["original"],
                        "description": fixture["description"],
                    },
                ]
                for payload in paths:
                    classification = self.classification.classify_from_supplier_evidence(
                        payload,
                        original_mpn=fixture["original"],
                        original_manufacturer=fixture["manufacturer"],
                    )
                    self.assertNotEqual(
                        classification,
                        self.classification.CLASS_VERIFIED_DIRECT,
                        payload,
                    )
                    assessment = self.comparison.build_engineering_evidence_assessment(
                        {"Match": 4, "Different": 0, "Needs data": 1},
                        classification=classification,
                        substitute_type="Direct",
                        evidence_source="DigiKey",
                        supplier_relationship_evidence=self.classification.pair_relationship_evidence_rows(
                            payload,
                            original_mpn=fixture["original"],
                            candidate_mpn=fixture["direct"],
                        ),
                    )
                    self.assertNotIn(
                        "DigiKey relationship: Direct.",
                        assessment["supplier_relationship_summary"],
                    )

    def test_upgrade_and_similar_remain_distinct_from_direct(self):
        for fixture in FAMILY_FIXTURES:
            with self.subTest(family=fixture["family"]):
                upgrade = _pair_candidate(
                    original=fixture["original"],
                    candidate=fixture["upgrade"],
                    substitute_type="Upgrade",
                    description=fixture["description"],
                    manufacturer=fixture["manufacturer"],
                )
                similar = _pair_candidate(
                    original=fixture["original"],
                    candidate=fixture["similar"],
                    substitute_type="Similar",
                    description=fixture["description"],
                    manufacturer=fixture["manufacturer"],
                )
                self.assertEqual(
                    self.classification.classify_from_supplier_evidence(
                        upgrade,
                        original_mpn=fixture["original"],
                        original_manufacturer=fixture["manufacturer"],
                    ),
                    self.classification.CLASS_SUPPLIER_UPGRADE,
                )
                self.assertEqual(
                    self.classification.classify_from_supplier_evidence(
                        similar,
                        original_mpn=fixture["original"],
                        original_manufacturer=fixture["manufacturer"],
                    ),
                    self.classification.CLASS_SUPPLIER_SIMILAR,
                )
                for candidate in (upgrade, similar):
                    self.assertFalse(
                        self.classification.has_exact_direct_relationship(
                            candidate,
                            original_mpn=fixture["original"],
                            candidate_mpn=str(candidate["manufacturer_part_number"]),
                        )
                    )

    def test_lifecycle_warning_reduces_suitability_without_erasing_direct_evidence(self):
        for fixture in FAMILY_FIXTURES:
            with self.subTest(family=fixture["family"]):
                explicit = [
                    _pair_candidate(
                        original=fixture["original"],
                        candidate=fixture["direct"],
                        substitute_type="Direct",
                        description=fixture["description"],
                        manufacturer=fixture["manufacturer"],
                        lifecycle="Active",
                    ),
                    _pair_candidate(
                        original=fixture["original"],
                        candidate=f"{fixture['direct']}-NFND",
                        substitute_type="Direct",
                        description=fixture["description"],
                        manufacturer=fixture["manufacturer"],
                        lifecycle="Not For New Designs",
                    ),
                ]

                def discover(_part, rows=explicit, original=fixture["original"]):
                    return {
                        "original_mpn": original,
                        "candidates": self.classification.merge_discovery_candidates(
                            rows, [], original_mpn=original
                        ),
                        "provider_failures": [],
                        "has_incomplete_evidence": False,
                    }

                self.engine.discover_alternative_candidates = discover
                self.engine.get_best_part_data = lambda part, desc=fixture["description"]: {
                    "manufacturer_part_number": part,
                    "description": desc,
                    "manufacturer": fixture["manufacturer"],
                    "package": "0603",
                    "mounting_style": "Surface Mount",
                    "supplier_data_verified": True,
                }
                results = self.engine.suggest_alternatives_v2(fixture["original"])
                by_part = {row["Alternative Part"]: row for row in results}
                active = by_part[fixture["direct"]]
                nfnd = by_part[f"{fixture['direct']}-NFND"]
                self.assertEqual(
                    active["Classification"],
                    self.classification.CLASS_VERIFIED_DIRECT,
                )
                self.assertEqual(
                    nfnd["Classification"],
                    self.classification.CLASS_VERIFIED_DIRECT,
                )
                self.assertIn(
                    "DigiKey relationship: Direct.",
                    nfnd.get("Supplier Relationship Summary", ""),
                )
                self.assertEqual(
                    active["Recommendation Suitability"],
                    self.classification.SUITABILITY_PREFERRED,
                )
                self.assertEqual(
                    nfnd["Recommendation Suitability"],
                    self.classification.SUITABILITY_SUSTAINING,
                )
                self.assertGreater(
                    active["Recommendation Score"],
                    nfnd["Recommendation Score"],
                )

    def test_capacitor_mpn_heuristics_do_not_pollute_resistor_discovery(self):
        resistor_row = {
            "manufacturer_part_number": "RC0603FR-0710KL",
            "description": "Thick Film Resistor 10kOhm 1% 0603",
            "source": "DigiKey",
        }
        part = self.engine._discovery_row_to_part_data(resistor_row)
        self.assertNotEqual(part.get("tolerance"), "±10%")
        self.assertNotIn("capacitance", part)
        self.assertEqual(part.get("package"), "0603")
        self.assertIn("resistance", part)

        capacitor_row = {
            "manufacturer_part_number": "C0603C104K5RACTU",
            "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            "source": "DigiKey",
        }
        cap = self.engine._discovery_row_to_part_data(capacitor_row)
        self.assertEqual(cap.get("tolerance"), "±10%")
        self.assertEqual(cap.get("package"), "0603")
        self.assertIn("capacitance", cap)

    def test_mouser_package_codes_are_not_pin_counts(self):
        self.assertEqual(self.mouser.extract_pin_count("0603"), 0)
        self.assertEqual(self.mouser.extract_pin_count("Package / Case: 0805"), 0)
        self.assertEqual(self.mouser.extract_pin_count("8"), 8)

    def test_pdf_comparison_omits_pin_count_for_passives(self):
        for family in ("Capacitor", "Resistor", "Inductor"):
            with self.subTest(family=family):
                rows = self.comparison.build_pdf_field_evidence(
                    {"pages": []},
                    {"pages": []},
                    family,
                )
                attributes = {row["Attribute"] for row in rows}
                self.assertNotIn("Pin count", attributes)

    def test_passive_drop_in_confidence_never_uses_ic_scoring(self):
        candidate = {
            "Comparison Family": "Resistor",
            "Comparison Counts": {},
            "Classification": self.classification.CLASS_VERIFIED_DIRECT,
            "Substitute Type": "Direct",
            "architecture": "op-amp",
            "pin_count": 8,
            "channel_count": 2,
        }
        original = {
            "description": "Resistor 10kOhm",
            "architecture": "op-amp",
            "pin_count": 8,
        }
        confidence = self.engine.calculate_drop_in_confidence(original, candidate)
        # Empty comparison counts on a passive must not inherit IC architecture points.
        self.assertLess(confidence, 40)


if __name__ == "__main__":
    unittest.main()
