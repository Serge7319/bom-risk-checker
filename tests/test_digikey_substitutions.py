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


if __name__ == "__main__":
    unittest.main()
