import importlib
import sys
import types
import unittest

sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))


def _cache_data(*_args, **_kwargs):
    return lambda func: func


class AlternativeFinderReliabilityTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.SimpleNamespace(cache_data=_cache_data)
        sys.modules.pop("src.alternative_engine", None)
        sys.modules.pop("integrations.supplier_aggregator", None)
        self.engine = importlib.import_module("src.alternative_engine")
        self.classification = importlib.import_module("src.alternative_classification")
        self.comparison = importlib.import_module("src.datasheet_comparison")
        self.aggregator = importlib.import_module("integrations.supplier_aggregator")
        self.engine.get_best_part_data = lambda _part: {
            "manufacturer": "KEMET",
            "description": "Capacitor Ceramic 0.1uF 50V X7R 0603",
            "capacitance": "0.1 µF",
            "tolerance": "±10%",
            "dielectric": "X7R",
            "package": "0603",
            "mounting_style": "Surface Mount",
        }

    def _mock_discovery(self, explicit, catalog=None):
        def discover(_part):
            merged = self.classification.merge_discovery_candidates(
                explicit,
                catalog or [],
                original_mpn="C0603C104K5RACTU",
            )
            return {
                "original_mpn": "C0603C104K5RACTU",
                "candidates": merged,
                "explicit_count": len(explicit),
                "catalog_count": len(catalog or []),
                "provider_failures": [],
                "has_incomplete_evidence": False,
                "retrieved_at": "2026-08-29T00:00:00+00:00",
                "providers": {"DigiKey": {"substitutions": "ok", "catalog": "ok"}},
            }

        self.engine.discover_alternative_candidates = discover
        self.aggregator.discover_alternative_candidates = discover

    def test_verified_direct_substitutes_beyond_display_cap_remain_visible(self):
        explicit = [
            {
                "manufacturer_part_number": f"DIRECT-SUB-{index:02d}",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
                "retrieval_status": "ok",
            }
            for index in range(11)
        ]
        explicit.append({
            "manufacturer_part_number": "C0603C104K5RAC3121",
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
            "retrieval_status": "ok",
        })
        catalog = [
            {
                "manufacturer_part_number": f"GRM-CATALOG-{index}",
                "source": "DigiKey",
                "substitute_type": "Similar",
                "evidence_type": "Distributor catalog match",
            }
            for index in range(15)
        ]
        self._mock_discovery(explicit, catalog)
        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        parts = [row["Alternative Part"] for row in results]
        target = [
            row for row in results
            if row["Alternative Part"] == "C0603C104K5RAC3121"
        ]
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertGreater(parts.index("C0603C104K5RAC3121"), 9)
        for index in range(11):
            self.assertIn(f"DIRECT-SUB-{index:02d}", parts)

    def test_digikey_distributor_sku_retains_verified_direct_substitute(self):
        distributor_number = "399-C0603C104K5RAC3121DKR-ND"
        digikey = importlib.import_module("integrations.digikey_client")

        def post(*_args, **_kwargs):
            payload = {"Products": [{
                "ManufacturerProductNumber": "C0603C104K5RAC3121",
                "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
                "ProductVariations": [{"DigiKeyProductNumber": distributor_number}],
            }]}

            class _Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return payload

            return _Response()

        digikey.requests.post = post
        digikey.get_secret = lambda *_args, **_kwargs: "client-id"
        digikey.get_digikey_access_token = lambda: "access-token"
        identity = digikey.resolve_engineering_part_identity(distributor_number)
        self.assertEqual(identity["manufacturer_part_number"], "C0603C104K5RAC3121")

        explicit = [{
            "manufacturer_part_number": "C0603C104K5RAC3121",
            "manufacturer": "KEMET",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
        }]
        self._mock_discovery(explicit, [])
        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        target = [
            row for row in results
            if row["Alternative Part"] == "C0603C104K5RAC3121"
        ]
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]["Classification"], self.classification.CLASS_VERIFIED_DIRECT)

    def test_c0603_direct_substitute_is_verified_and_ranked_first(self):
        explicit = [
            {
                "manufacturer_part_number": "C0603C104K5RAC3121",
                "manufacturer": "KEMET",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
                "retrieval_status": "ok",
            },
            {
                "manufacturer_part_number": "0603BB104K500YT",
                "manufacturer": "Knowles Novacap",
                "source": "DigiKey",
                "substitute_type": "Direct",
                "evidence_type": "Distributor-listed substitute",
                "retrieval_status": "ok",
            },
        ]
        catalog = [
            {
                "manufacturer_part_number": "GRM188R71H104KA93D",
                "source": "DigiKey",
                "substitute_type": "Similar",
                "evidence_type": "Distributor catalog match",
            }
        ]
        self._mock_discovery(explicit, catalog)
        results = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")
        self.assertGreaterEqual(len(results), 2)
        self.assertEqual(results[0]["Alternative Part"], "C0603C104K5RAC3121")
        self.assertEqual(
            results[0]["Classification"],
            self.classification.CLASS_VERIFIED_DIRECT,
        )

    def test_explicit_substitutes_are_not_removed_by_catalog_candidates(self):
        explicit = [{
            "manufacturer_part_number": "C0603C104K5RAC3121",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
        }]
        catalog = [{
            "manufacturer_part_number": "GRM188R71H104KA93D",
            "source": "DigiKey",
            "substitute_type": "Similar",
            "evidence_type": "Distributor catalog match",
        }] * 8
        self._mock_discovery(explicit, catalog)
        parts = {row["Alternative Part"] for row in self.engine.suggest_alternatives_v2("C0603C104K5RACTU")}
        self.assertIn("C0603C104K5RAC3121", parts)

    def test_catalog_candidate_cannot_be_labeled_direct(self):
        self._mock_discovery([], [{
            "manufacturer_part_number": "GRM188R71H104KA93D",
            "source": "DigiKey",
            "substitute_type": "Similar",
            "evidence_type": "Distributor catalog match",
        }])
        result = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")[0]
        self.assertNotEqual(result["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertEqual(result["Substitute Type"], "Similar")

    def test_missing_capacitor_rated_voltage_is_needs_data_not_match(self):
        original = {
            "description": "Capacitor Ceramic 0.1uF",
            "capacitance": "0.1 µF",
            "tolerance": "±10%",
            "dielectric": "X7R",
            "package": "0603",
            "mounting_style": "Surface Mount",
        }
        candidate = dict(original)
        comparison = self.comparison.build_datasheet_comparison(original, candidate)
        rated_voltage_rows = [
            row for row in comparison["rows"] if row["Attribute"] == "Rated voltage"
        ]
        self.assertEqual(len(rated_voltage_rows), 1)
        self.assertEqual(rated_voltage_rows[0]["Status"], "Needs data")

    def test_mpn_normalization_dedupes_variants_not_unrelated_parts(self):
        explicit = [
            {"manufacturer_part_number": "C0603C104K5RACTU-TR", "evidence_type": "Distributor-listed substitute", "substitute_type": "Direct"},
        ]
        catalog = [
            {"manufacturer_part_number": "C0603C104K5RACTU", "evidence_type": "Distributor catalog match", "substitute_type": "Similar"},
            {"manufacturer_part_number": "LM358N", "evidence_type": "Distributor catalog match", "substitute_type": "Similar"},
        ]
        merged = self.classification.merge_discovery_candidates(
            explicit,
            catalog,
            original_mpn="C0603C104K5RACTU",
        )
        mpns = {row["manufacturer_part_number"] for row in merged}
        self.assertIn("C0603C104K5RACTU-TR", mpns)
        self.assertIn("LM358N", mpns)
        self.assertNotIn("C0603C104K5RACTU", mpns)

    def test_provider_failure_marks_incomplete_evidence(self):
        def failing_substitutions(_part):
            raise TimeoutError("DigiKey API timeout")

        original_configured = self.aggregator._provider_configured
        self.aggregator._provider_configured = lambda secret_name: (
            secret_name == "DIGIKEY_CLIENT_ID"
            or original_configured(secret_name)
        )
        self.aggregator.search_digikey_substitutions = failing_substitutions

        discovery = self.aggregator.discover_alternative_candidates("C0603C104K5RACTU")

        self.assertTrue(discovery["has_incomplete_evidence"])
        self.assertIn("DigiKey", discovery["provider_failures"])
        self.assertIsInstance(discovery["candidates"], list)
        self.assertEqual(discovery["providers"]["DigiKey"]["substitutions"], "error")
        self.assertNotEqual(
            discovery.get("has_incomplete_evidence"),
            False,
            "empty candidates must not be treated as proof that no market alternatives exist",
        )

    def test_resistor_comparison_includes_voltage_rating(self):
        original = {
            "description": "Resistor thick film 10k",
            "resistance": "10 kOhms",
            "tolerance": "±1%",
            "power_rating": "0.1W",
            "temperature_coefficient": "±100ppm/°C",
            "package": "0603",
        }
        candidate = dict(original, resistance="10 kOhms")
        rows = {
            row["Attribute"]: row["Status"]
            for row in self.comparison.build_datasheet_comparison(original, candidate)["rows"]
        }
        self.assertEqual(rows["Resistance"], "Match")
        self.assertEqual(rows["Voltage rating"], "Needs data")

    def test_inductor_comparison_includes_saturation_current(self):
        original = {
            "description": "Inductor shielded 10uH",
            "inductance": "10 µH",
            "tolerance": "±20%",
            "dcr": "0.05 Ohms",
            "rated_current": "2 A",
            "package": "6x6mm",
        }
        candidate = dict(original)
        rows = {
            row["Attribute"]: row["Status"]
            for row in self.comparison.build_datasheet_comparison(original, candidate)["rows"]
        }
        self.assertEqual(rows["Inductance"], "Match")
        self.assertEqual(rows["Saturation current"], "Needs data")

    def test_semiconductor_comparison_tracks_device_type(self):
        original = {
            "description": "MOSFET N-channel 30V",
            "device_type": "N-Channel",
            "reverse_voltage": "30 V",
            "rated_current": "5 A",
            "package": "SOT-23",
            "pin_count": 3,
        }
        candidate = dict(original, rated_current="4.5 A")
        rows = {
            row["Attribute"]: row["Status"]
            for row in self.comparison.build_datasheet_comparison(original, candidate)["rows"]
        }
        self.assertEqual(rows["Device type"], "Match")
        self.assertEqual(rows["Current"], "Different")

    def test_ic_comparison_includes_pinout_evidence_field(self):
        original = {
            "description": "Microcontroller ARM Cortex-M3",
            "architecture": "ARM Cortex-M3",
            "pin_count": 48,
            "voltage_range": "2.0V-3.6V",
            "package": "LQFP-48",
        }
        candidate = dict(original)
        rows = {
            row["Attribute"]: row["Status"]
            for row in self.comparison.build_datasheet_comparison(original, candidate)["rows"]
        }
        self.assertIn("Pinout evidence", rows)
        self.assertEqual(rows["Pinout evidence"], "Needs data")

    def test_verified_direct_capacitor_gets_strong_passive_confidence(self):
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
            "lifecycle_status": "Active",
            "stock_total": 50000,
            "unit_price": 0.05,
            "supplier_data_verified": True,
        }

        def part_data(part_number):
            if part_number == "C0603C104K5RACTU":
                return dict(capacitor_fields, manufacturer_part_number=part_number)
            if part_number == "C0603C104K5RAC3121":
                return dict(capacitor_fields, manufacturer_part_number=part_number)
            return {}

        self.engine.get_best_part_data = part_data
        self._mock_discovery([{
            "manufacturer_part_number": "C0603C104K5RAC3121",
            "source": "DigiKey",
            "substitute_type": "Direct",
            "evidence_type": "Distributor-listed substitute",
        }], [])
        result = self.engine.suggest_alternatives_v2("C0603C104K5RACTU")[0]
        self.assertEqual(result["Classification"], self.classification.CLASS_VERIFIED_DIRECT)
        self.assertEqual(result["Comparison Family"], "Capacitor")
        self.assertGreaterEqual(result["Drop-In Confidence"], 82)
        counts = result.get("Comparison Counts") or {}
        self.assertEqual(counts.get("Different", 0), 0)
        self.assertGreaterEqual(counts.get("Match", 0), 6)


if __name__ == "__main__":
    unittest.main()
