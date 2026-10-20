import importlib
import sys
import types
import unittest

sys.modules.setdefault("requests", types.SimpleNamespace(get=None, post=None))


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class DigiKeySubstitutionTests(unittest.TestCase):
    def setUp(self):
        streamlit = types.SimpleNamespace(secrets={})
        sys.modules["streamlit"] = streamlit
        sys.modules.pop("integrations.digikey_client", None)
        self.client = importlib.import_module("integrations.digikey_client")
        self.client.get_secret = lambda *_args, **_kwargs: "client-id"
        self.client.get_digikey_access_token = lambda: "access-token"

    def test_c0603_direct_substitute_from_package_variant_substitutions_call(self):
        primary_dk = "399-C0603C104K5RACTUCT-ND"
        variant_dk = "399-C0603C104K5RACTU-DKR-ND"
        other_variant_dk = "399-C0603C104K5RACTU-ND"
        substitution_urls = []

        def post(*_args, **_kwargs):
            return _Response({
                "Products": [{
                    "ManufacturerProductNumber": "C0603C104K5RACTU",
                    "DigiKeyProductNumber": primary_dk,
                    "ProductVariations": [
                        {"DigiKeyProductNumber": other_variant_dk},
                        {"DigiKeyProductNumber": variant_dk},
                    ],
                }]
            })

        def get(url, **_kwargs):
            substitution_urls.append(url)
            if variant_dk in url:
                return _Response({
                    "ProductSubstitutes": [{
                        "ManufacturerProductNumber": "C0603C104K5RAC3121",
                        "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
                        "Manufacturer": {"Name": "KEMET"},
                        "SubstituteType": "Direct",
                        "QuantityAvailable": 122352,
                        "UnitPrice": 0.15,
                        "ProductUrl": "https://www.digikey.com/example",
                    }]
                })
            return _Response({"ProductSubstitutes": []})

        self.client.requests.post = post
        self.client.requests.get = get
        results = self.client.search_digikey_substitutions("C0603C104K5RACTU")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["manufacturer_part_number"], "C0603C104K5RAC3121")
        self.assertEqual(results[0]["substitute_type"], "Direct")
        self.assertEqual(results[0]["evidence_type"], "Distributor-listed substitute")
        self.assertTrue(any(variant_dk in url for url in substitution_urls))
        self.assertFalse(any("C0603C104K5RAC3121" in url for url in substitution_urls))
        primary_calls = [url for url in substitution_urls if primary_dk in url]
        variant_calls = [url for url in substitution_urls if variant_dk in url]
        self.assertGreaterEqual(len(primary_calls), 1)
        self.assertEqual(len(variant_calls), 1)

    def test_returns_supplier_listed_substitutes_and_preserves_classification(self):
        requested_urls = []

        def post(*_args, **_kwargs):
            return _Response({"Products": [{
                "ManufacturerProductNumber": "C0603C104K5RACTU",
                "DigiKeyProductNumber": "399-C0603C104K5RACTUCT-ND",
            }]})

        def get(url, **_kwargs):
            requested_urls.append(url)
            return _Response({"ProductSubstitutes": [{
                "ManufacturerProductNumber": "C0603C104K5RAC3121",
                "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
                "Manufacturer": {"Name": "KEMET"},
                "SubstituteType": "Direct",
                "QuantityAvailable": 122352,
                "UnitPrice": 0.15,
                "ProductUrl": "https://www.digikey.com/example",
            }]})

        self.client.requests.post = post
        self.client.requests.get = get
        results = self.client.search_digikey_substitutions("C0603C104K5RACTU")

        self.assertEqual(results[0]["manufacturer_part_number"], "C0603C104K5RAC3121")
        self.assertEqual(results[0]["substitute_type"], "Direct")
        self.assertIn("399-C0603C104K5RACTUCT-ND/substitutions", requested_urls[0])

    def test_substitutions_use_exact_mpn_not_first_keyword_result(self):
        requested_urls = []

        def post(*_args, **_kwargs):
            return _Response({"Products": [
                {
                    "ManufacturerProductNumber": "C0603C104K5RAC3121",
                    "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
                },
                {
                    "ManufacturerProductNumber": "C0603C104K5RACTU",
                    "DigiKeyProductNumber": "399-C0603C104K5RACTUCT-ND",
                },
            ]})

        def get(url, **_kwargs):
            requested_urls.append(url)
            return _Response({"ProductSubstitutes": []})

        self.client.requests.post = post
        self.client.requests.get = get
        self.client.search_digikey_substitutions("C0603C104K5RACTU")

        self.assertIn("399-C0603C104K5RACTUCT-ND/substitutions", requested_urls[0])

    def test_substitutions_query_each_exact_product_package_variant(self):
        requested_urls = []

        def post(*_args, **_kwargs):
            return _Response({"Products": [{
                "ManufacturerProductNumber": "C0603C104K5RACTU",
                "DigiKeyProductNumber": "399-C0603C104K5RACTUTR-ND",
                "ProductVariations": [
                    {"DigiKeyProductNumber": "399-C0603C104K5RACTUCT-ND"},
                    {"DigiKeyProductNumber": "399-C0603C104K5RACTUDKR-ND"},
                ],
            }]})

        def get(url, **_kwargs):
            requested_urls.append(url)
            if "RACTUCT" in url:
                return _Response({"ProductSubstitutes": [{
                    "ManufacturerProductNumber": "C0603C104K5RAC3121",
                    "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
                    "Manufacturer": {"Name": "KEMET"},
                    "SubstituteType": "Direct",
                }]})
            return _Response({"ProductSubstitutes": []})

        self.client.requests.post = post
        self.client.requests.get = get

        results = self.client.search_digikey_substitutions("C0603C104K5RACTU")

        self.assertEqual([row["manufacturer_part_number"] for row in results], ["C0603C104K5RAC3121"])
        self.assertEqual(len(requested_urls), 3)
        self.assertTrue(any("RACTUCT" in url for url in requested_urls))

    def test_non_exact_keyword_result_is_not_treated_as_verified_part(self):
        self.client.requests.post = lambda *_args, **_kwargs: _Response({"Products": [{
            "ManufacturerProductNumber": "C0603C104K5RAC3121",
            "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
        }]})

        result = self.client.search_digikey_by_part_number("C0603C104K5RACTU")

        self.assertEqual(result["manufacturer_part_number"], "")

    def test_catalog_matches_are_not_claimed_as_direct_substitutes(self):
        self.client.requests.post = lambda *_args, **_kwargs: _Response({"Products": [{
            "ManufacturerProductNumber": "LM358DT",
            "DigiKeyProductNumber": "497-1257-1-ND",
            "Manufacturer": {"Name": "STMicroelectronics"},
            "Description": {"ProductDescription": "IC OPAMP GP 2 CIRCUIT 8SO"},
            "QuantityAvailable": 100,
        }]})
        self.client.get_secret = lambda *_args, **_kwargs: "client-id"
        self.client.get_digikey_access_token = lambda: "access-token"

        results = self.client.search_digikey_catalog_candidates("LM358")

        self.assertEqual(results[0]["manufacturer_part_number"], "LM358DT")
        self.assertEqual(results[0]["evidence_type"], "Distributor catalog match")
        self.assertEqual(results[0]["substitute_type"], "Similar")

    def test_lm317_orderable_suffix_expands_to_labeled_family_catalog_search(self):
        requested_terms = []

        def post(_url, *, json, **_kwargs):
            term = json["Keywords"]
            requested_terms.append(term)
            if term == "LM317":
                return _Response({"Products": [{
                    "ManufacturerProductNumber": "LM317BS-TR",
                    "DigiKeyProductNumber": "497-LM317BS-TR-ND",
                    "Manufacturer": {"Name": "STMicroelectronics"},
                    "PrimaryCategory": {"Name": "Integrated Circuits (ICs)"},
                    "Description": {"ProductDescription": "IC REG LINEAR ADJUSTABLE"},
                    "ProductStatus": {"Name": "Active"},
                    "QuantityAvailable": 500,
                    "ProductUrl": "https://www.digikey.com/example/lm317bs-tr",
                }]})
            return _Response({"Products": []})

        self.client.requests.post = post
        results = self.client.search_digikey_catalog_candidates("LM317DCYR")

        self.assertEqual(requested_terms, ["LM317DCYR", "LM317"])
        self.assertEqual(self.client._catalog_search_terms("LM317DCYR"), ["LM317DCYR", "LM317"])
        self.assertEqual(results[0]["manufacturer_part_number"], "LM317BS-TR")
        self.assertEqual(results[0]["evidence_type"], "Distributor family search match")
        self.assertEqual(results[0]["discovery_scope"], "family_search")
        self.assertEqual(results[0]["discovery_query"], "LM317")
        self.assertEqual(results[0]["substitute_type"], "Similar")

    def test_bom_mode_can_skip_family_search_without_skipping_exact_catalog_search(self):
        requested_terms = []

        def post(_url, *, json, **_kwargs):
            requested_terms.append(json["Keywords"])
            return _Response({"Products": []})

        self.client.requests.post = post
        self.client.search_digikey_catalog_candidates(
            "LM317DCYR",
            include_family_search=False,
        )

        self.assertEqual(requested_terms, ["LM317DCYR"])

    def test_family_search_stems_cover_mixed_and_numeric_leading_mpns(self):
        cases = {
            "MC68HC11E1CFNE2": "MC68HC11",
            "STM32F103C8T6": "STM32F103",
            "6N137S-TA1": "6N137",
            "74HC595D": "74HC595",
            "C0603C104K5RACTU": "",
        }

        for part_number, expected in cases.items():
            with self.subTest(part_number=part_number):
                self.assertEqual(
                    self.client._catalog_family_search_term(part_number),
                    expected,
                )

    def test_lifecycle_parser_reads_common_digikey_enum_object_shapes(self):
        cases = (
            ({"ProductStatus": {"Id": 0, "Status": "Active"}}, "Active"),
            ({"ProductStatus": {"Name": "NRND"}}, "NRND"),
            ({"LifecycleStatus": {"Value": "EOL"}}, "EOL"),
        )
        for product, expected in cases:
            with self.subTest(product=product):
                self.assertEqual(self.client.infer_digikey_lifecycle(product), expected)

    def test_catalog_candidate_preserves_lifecycle_and_primary_category(self):
        self.client.requests.post = lambda *_args, **_kwargs: _Response({"Products": [{
            "ManufacturerProductNumber": "LM7805ACTG",
            "DigiKeyProductNumber": "516-LM7805ACTG-ND",
            "Manufacturer": {"Name": "onsemi"},
            "ProductStatus": {"Id": 0, "Name": "Active"},
            "PrimaryCategory": {"CategoryId": 32, "Name": "Integrated Circuits (ICs)"},
            "Description": {"ProductDescription": "IC REG LINEAR 5V 1A TO220"},
            "QuantityAvailable": 12140,
        }]})

        result = self.client.search_digikey_catalog_candidates("LM7805ACT")[0]

        self.assertEqual(result["lifecycle_status"], "Active")
        self.assertEqual(result["primary_category"], "Integrated Circuits (ICs)")
        self.assertEqual(result["stock_total"], 12140)

    def test_category_parser_reads_nested_supplier_value_and_product_category_name(self):
        cases = (
            ({"CategoryId": 42, "Value": "Development Boards, Kits, Programmers"},
             "Development Boards, Kits, Programmers"),
            ({"ProductCategoryId": 7, "ProductCategoryName": "Sensors"}, "Sensors"),
        )
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.client._digikey_category_text(payload), expected)


    def test_normalizes_capacitor_parametric_evidence(self):
        product = {
            "Manufacturer": {"Name": "KEMET"},
            "ManufacturerProductNumber": "C0603C104K5RACTU",
            "Description": {"ProductDescription": "CAP CER 0.1UF 50V X7R 0603"},
            "Parameters": [
                {"ParameterText": "Capacitance", "ValueText": "0.1 µF"},
                {"ParameterText": "Voltage - Rated", "ValueText": "50V"},
                {"ParameterText": "Temperature Coefficient", "ValueText": "X7R"},
                {"ParameterText": "Tolerance", "ValueText": "±10%"},
                {"ParameterText": "Package / Case", "ValueText": "0603 (1608 Metric)"},
            ],
        }
        result = self.client.normalize_digikey_product(product)
        self.assertEqual(result["capacitance"], "0.1 µF")
        self.assertEqual(result["rated_voltage"], "50V")
        self.assertEqual(result["dielectric"], "X7R")
        self.assertEqual(result["tolerance"], "±10%")
        self.assertEqual(result["pin_count"], 0)

    def test_explicit_usd_request_locale_is_retained_when_product_omits_currency(self):
        product = {
            "Manufacturer": {"Name": "onsemi"},
            "ManufacturerProductNumber": "BC547B",
            "UnitPrice": [{"BreakQuantity": 1, "UnitPrice": "$0.13"}],
        }
        result = self.client.normalize_digikey_product(product)
        self.assertEqual(result["unit_price"], 0.13)
        self.assertEqual(result["unit_price_currency"], "USD")
        self.assertEqual(result["price_breaks"][0]["currency"], "USD")

        headers = self.client._digikey_headers("client-id", "token")
        self.assertEqual(headers["X-DIGIKEY-Locale-Site"], "US")
        self.assertEqual(headers["X-DIGIKEY-Locale-Currency"], "USD")

    def test_digikey_distributor_number_resolves_to_manufacturer_mpn(self):
        distributor_number = "399-C0603C104K5RAC3121DKR-ND"

        def post(*_args, **_kwargs):
            return _Response({"Products": [{
                "ManufacturerProductNumber": "C0603C104K5RAC3121",
                "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
                "ProductVariations": [
                    {"DigiKeyProductNumber": distributor_number},
                ],
            }]})

        self.client.requests.post = post
        result = self.client.search_digikey_by_part_number(distributor_number)

        self.assertEqual(result["manufacturer_part_number"], "C0603C104K5RAC3121")
        self.assertEqual(result["order_part_number"], distributor_number)
        self.assertEqual(result["digikey_part_number"], distributor_number)

        identity = self.client.resolve_engineering_part_identity(distributor_number)
        self.assertEqual(identity["manufacturer_part_number"], "C0603C104K5RAC3121")


    def test_catalog_search_expands_packaging_suffix_to_mpn_family(self):
        self.assertEqual(
            self.client._catalog_search_terms("C0603C104K5RACTU"),
            ["C0603C104K5RACTU", "C0603C104K5RAC"],
        )

    def test_sibling_mpn_variations_do_not_supply_direct_evidence(self):
        substitution_urls = []

        def post(*_args, **_kwargs):
            return _Response({
                "Products": [{
                    "ManufacturerProductNumber": "C0603C104K5RACTU",
                    "DigiKeyProductNumber": "399-C0603C104K5RACTUCT-ND",
                    "ProductVariations": [
                        {"DigiKeyProductNumber": "399-C0603C104K5RACTUTR-ND"},
                        {
                            "ManufacturerProductNumber": "C0603C104K5RAC7411",
                            "DigiKeyProductNumber": "399-C0603C104K5RAC7411CT-ND",
                        },
                        {
                            # Live DigiKey payloads often omit ManufacturerProductNumber
                            # for sibling family SKUs listed under ProductVariations.
                            "DigiKeyProductNumber": "399-C0603C104K5RAC7411DKR-ND",
                        },
                        {
                            "ManufacturerProductNumber": "C0603C104K5RAC3121",
                            "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
                        },
                    ],
                }]
            })

        def get(url, **_kwargs):
            substitution_urls.append(url)
            if "RACTUCT" in url or "RACTUTR" in url:
                return _Response({
                    "ProductSubstitutes": [
                        {
                            "ManufacturerProductNumber": "C0603C104K5RAC3121",
                            "DigiKeyProductNumber": "399-C0603C104K5RAC3121CT-ND",
                            "Manufacturer": {"Name": "KEMET"},
                            "SubstituteType": "Direct",
                            "ProductUrl": "https://www.digikey.com/3121",
                        },
                        {
                            "ManufacturerProductNumber": "0603BB104K500YT",
                            "DigiKeyProductNumber": "0603BB104K500YT-ND",
                            "Manufacturer": {"Name": "ATC"},
                            "SubstituteType": "Direct",
                            "ProductUrl": "https://www.digikey.com/yt",
                        },
                    ]
                })
            if "7411" in url:
                return _Response({
                    "ProductSubstitutes": [{
                        "ManufacturerProductNumber": "C0603C104K5RAC7411",
                        "DigiKeyProductNumber": "399-C0603C104K5RAC7411CT-ND",
                        "Manufacturer": {"Name": "KEMET"},
                        "SubstituteType": "Direct",
                    }]
                })
            if "3121CT" in url:
                return _Response({
                    "ProductSubstitutes": [{
                        "ManufacturerProductNumber": "C0603C104K5RAC7411",
                        "DigiKeyProductNumber": "399-C0603C104K5RAC7411CT-ND",
                        "Manufacturer": {"Name": "KEMET"},
                        "SubstituteType": "Direct",
                    }]
                })
            return _Response({"ProductSubstitutes": []})

        self.client.requests.post = post
        self.client.requests.get = get
        results = self.client.search_digikey_substitutions("C0603C104K5RACTU")
        by_part = {row["manufacturer_part_number"]: row for row in results}

        self.assertIn("C0603C104K5RAC3121", by_part)
        self.assertEqual(by_part["C0603C104K5RAC3121"]["substitute_type"], "Direct")
        self.assertIn("0603BB104K500YT", by_part)
        self.assertNotIn("C0603C104K5RAC7411", by_part)
        self.assertFalse(any("7411" in url for url in substitution_urls))
        self.assertFalse(any("3121CT" in url for url in substitution_urls))
        self.assertTrue(any("RACTUTR" in url for url in substitution_urls))


if __name__ == "__main__":
    unittest.main()
