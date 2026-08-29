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

    def test_returns_supplier_listed_substitutes_and_preserves_classification(self):
        requested_urls = []

        def post(*_args, **_kwargs):
            return _Response({"Products": [{"DigiKeyProductNumber": "399-C0603C104K5RACTUCT-ND"}]})

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


if __name__ == "__main__":
    unittest.main()
