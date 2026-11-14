"""Deterministic DigiKey / Mouser / Newark supplier acceptance matrix.

Every provider response here is mocked: no network, no credentials. The matrix
covers, per provider:

* exact MPN + manufacturer match
* manufacturer mismatch -> not found / not verified
* no hit
* provider failure (timeout / HTTP) is NOT a no-hit
* missing stock / price stay ``None`` (never coerced to ``0``)
* displayed offer fields (``product_detail_url`` + ``retrieved_at``) on hits

Newark additionally only reports a verified listing for an official
``https://www.newark.com/...`` URL and never fabricates one from a SKU.
"""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests

from integrations import digikey_client, mouser_client, newark_client
from integrations import supplier_aggregator as aggregator
from integrations.provider_health import (
    PROVIDER_AVAILABLE,
    PROVIDER_ERROR,
    PROVIDER_PART_NOT_FOUND,
    PROVIDER_TIMEOUT,
)

MPN = "LM358DR"
MFR = "Texas Instruments"
OTHER_MFR = "STMicroelectronics"

DIGIKEY_URL = "https://www.digikey.com/en/products/detail/texas-instruments/LM358DR/404003"
MOUSER_URL = "https://www.mouser.com/ProductDetail/Texas-Instruments/LM358DR?qs=abc"
NEWARK_URL = "https://www.newark.com/texas-instruments/lm358dr/op-amp/dp/58K1234"


def _response(payload: dict | None = None, *, http_error: Exception | None = None) -> Mock:
    response = Mock()
    response.json.return_value = payload if payload is not None else {}
    if http_error is not None:
        response.raise_for_status.side_effect = http_error
    else:
        response.raise_for_status.return_value = None
    return response


def _http_error(status: int) -> requests.HTTPError:
    error = requests.HTTPError(f"{status} Server Error")
    error.response = Mock(status_code=status)
    return error


# --------------------------------------------------------------------------- #
# Payload builders
# --------------------------------------------------------------------------- #
def _digikey_product(**overrides) -> dict:
    product = {
        "ManufacturerProductNumber": MPN,
        "Manufacturer": {"Name": MFR},
        "DigiKeyProductNumber": "296-1395-1-ND",
        "Description": {"ProductDescription": "IC OPAMP GP 2 CIRCUIT 8SOIC"},
        "QuantityAvailable": 4321,
        "UnitPrice": 0.52,
        "ProductUrl": DIGIKEY_URL,
    }
    product.update(overrides)
    return {k: v for k, v in product.items() if v is not _MISSING}


_MISSING = object()


def _mouser_part(**overrides) -> dict:
    part = {
        "ManufacturerPartNumber": MPN,
        "MouserPartNumber": "595-LM358DR",
        "Manufacturer": MFR,
        "Description": "Op Amps Dual Gen Purpose",
        "Availability": "1,234 In Stock",
        "PriceBreaks": [{"Quantity": 1, "Price": "$0.55", "Currency": "USD"}],
        "ProductDetailUrl": MOUSER_URL,
    }
    part.update(overrides)
    return {k: v for k, v in part.items() if v is not _MISSING}


def _mouser_payload(*parts: dict) -> dict:
    return {"Errors": [], "SearchResults": {"NumberOfResult": len(parts), "Parts": list(parts)}}


def _newark_product(**overrides) -> dict:
    product = {
        "sku": "58K1234",
        "brandName": MFR,
        "displayName": "LM358DR - Dual Op Amp, SOIC-8",
        "manufacturerPartNumber": MPN,
        "translatedManufacturerPartNumber": MPN,
        "productUrl": NEWARK_URL,
        "stock": {"level": 987, "leastLeadTime": 14},
        "prices": [{"from": 1, "to": 9, "cost": 0.61}],
    }
    product.update(overrides)
    return {k: v for k, v in product.items() if v is not _MISSING}


def _newark_payload(*products: dict) -> dict:
    return {"manufacturerPartNumberSearchReturn": {"products": list(products)}}


# --------------------------------------------------------------------------- #
# Network patch helpers
# --------------------------------------------------------------------------- #
def _patch_digikey(post_mock: Mock):
    return _Stack(
        patch.object(digikey_client, "get_secret", return_value="test-client-id"),
        patch.object(digikey_client, "get_digikey_access_token", return_value="tok"),
        patch.object(digikey_client.requests, "post", post_mock),
    )


def _patch_mouser(post_mock: Mock):
    return _Stack(
        patch.object(mouser_client, "get_secret", return_value="test-key"),
        patch.object(mouser_client.requests, "post", post_mock),
    )


def _patch_newark(get_mock: Mock):
    return _Stack(
        patch.object(newark_client, "get_secret", return_value="test-key"),
        patch.object(newark_client.requests, "get", get_mock),
        # Never reach the network for the SKU fallback in these tests.
        patch.object(
            newark_client,
            "lookup_newark_official_listing_url",
            return_value={"listing_verified": False},
        ),
    )


class _Stack:
    def __init__(self, *patchers):
        self._patchers = patchers

    def __enter__(self):
        for patcher in self._patchers:
            patcher.start()
        return self

    def __exit__(self, *exc):
        for patcher in reversed(self._patchers):
            patcher.stop()
        return False


def _aggregated(source: str, lookup, manufacturer: str = "") -> dict:
    """Run a provider lookup through the production per-supplier guard."""
    return aggregator._safe_supplier_lookup(
        source, lookup, MPN, request_id="matrix", manufacturer=manufacturer
    )


# --------------------------------------------------------------------------- #
# DigiKey
# --------------------------------------------------------------------------- #
class DigiKeyMatrixTests(unittest.TestCase):
    def _lookup(self, post_mock: Mock, manufacturer: str = "") -> dict:
        with _patch_digikey(post_mock):
            return digikey_client.search_digikey_by_part_number(MPN, manufacturer=manufacturer)

    def test_exact_mpn_and_manufacturer_match(self):
        post = Mock(return_value=_response({"Products": [_digikey_product()]}))
        result = self._lookup(post, MFR)
        self.assertEqual(result["manufacturer_part_number"], MPN)
        self.assertEqual(result["manufacturer"], MFR)
        self.assertEqual(result["stock_total"], 4321)
        self.assertEqual(result["unit_price"], 0.52)
        self.assertEqual(result["product_detail_url"], DIGIKEY_URL)
        self.assertTrue(result["retrieved_at"])

        guarded = _aggregated("DigiKey", lambda part, **kw: result, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_AVAILABLE)
        self.assertTrue(guarded["unit_price_known"])
        self.assertEqual(guarded["product_detail_url"], DIGIKEY_URL)
        self.assertTrue(guarded["retrieved_at"])

    def test_manufacturer_mismatch_is_not_found(self):
        post = Mock(return_value=_response({"Products": [_digikey_product()]}))
        result = self._lookup(post, OTHER_MFR)
        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertEqual(result["product_detail_url"], "")
        self.assertIsNone(result["stock_total"])
        self.assertIsNone(result["unit_price"])

        with _patch_digikey(post):
            guarded = _aggregated(
                "DigiKey", digikey_client.search_digikey_by_part_number, OTHER_MFR
            )
        self.assertEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)

    def test_no_hit(self):
        post = Mock(return_value=_response({"Products": []}))
        result = self._lookup(post, MFR)
        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertIsNone(result["stock_total"])
        self.assertIsNone(result["unit_price"])
        with _patch_digikey(post):
            guarded = _aggregated("DigiKey", digikey_client.search_digikey_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)

    def test_neighbor_mpn_is_not_an_exact_hit(self):
        post = Mock(
            return_value=_response(
                {"Products": [_digikey_product(ManufacturerProductNumber="LM358DRG4")]}
            )
        )
        result = self._lookup(post, MFR)
        self.assertEqual(result["manufacturer_part_number"], "")

    def test_provider_timeout_is_not_a_no_hit(self):
        post = Mock(side_effect=requests.Timeout("read timed out"))
        with _patch_digikey(post):
            guarded = _aggregated("DigiKey", digikey_client.search_digikey_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_TIMEOUT)
        self.assertNotEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertTrue(guarded["error"])

    def test_provider_http_error_is_not_a_no_hit(self):
        post = Mock(return_value=_response(http_error=_http_error(500)))
        with _patch_digikey(post):
            guarded = _aggregated("DigiKey", digikey_client.search_digikey_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_ERROR)
        self.assertNotEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)

    def test_missing_stock_and_price_stay_none(self):
        product = _digikey_product(QuantityAvailable=_MISSING, UnitPrice=_MISSING)
        post = Mock(return_value=_response({"Products": [product]}))
        result = self._lookup(post, MFR)
        self.assertEqual(result["manufacturer_part_number"], MPN)
        self.assertIsNone(result["stock_total"])
        self.assertIsNone(result["unit_price"])

        guarded = _aggregated("DigiKey", lambda part, **kw: result, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_AVAILABLE)
        self.assertIsNone(guarded["stock_total"])
        self.assertFalse(guarded["unit_price_known"])

    def test_explicit_zero_stock_is_preserved_as_zero(self):
        post = Mock(return_value=_response({"Products": [_digikey_product(QuantityAvailable=0)]}))
        self.assertEqual(self._lookup(post, MFR)["stock_total"], 0)

    def test_extract_helpers_never_coerce_missing_to_zero(self):
        self.assertIsNone(digikey_client.extract_digikey_price({}))
        self.assertIsNone(digikey_client.extract_digikey_price({"UnitPrice": 0}))
        self.assertIsNone(digikey_client.extract_digikey_price({"StandardPricing": []}))
        self.assertIsNone(digikey_client.extract_digikey_price({"StandardPricing": ["bad"]}))
        self.assertIsNone(
            digikey_client.extract_digikey_price({"StandardPricing": [{"UnitPrice": ""}]})
        )
        self.assertEqual(
            digikey_client.extract_digikey_price(
                {"StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 0.13}]}
            ),
            0.13,
        )
        default = digikey_client.default_digikey_result(MPN)
        self.assertIsNone(default["stock_total"])
        self.assertIsNone(default["unit_price"])


# --------------------------------------------------------------------------- #
# Mouser
# --------------------------------------------------------------------------- #
class MouserMatrixTests(unittest.TestCase):
    def _lookup(self, post_mock: Mock) -> dict:
        with _patch_mouser(post_mock):
            return mouser_client.search_mouser_by_part_number(MPN)

    def test_exact_mpn_and_manufacturer_match(self):
        post = Mock(return_value=_response(_mouser_payload(_mouser_part())))
        result = self._lookup(post)
        self.assertEqual(result["manufacturer_part_number"], MPN)
        self.assertEqual(result["manufacturer"], MFR)
        self.assertEqual(result["stock_total"], 1234)
        self.assertEqual(result["unit_price"], 0.55)
        self.assertEqual(result["product_detail_url"], MOUSER_URL)
        self.assertTrue(result["retrieved_at"])

        with _patch_mouser(post):
            guarded = _aggregated("Mouser", mouser_client.search_mouser_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_AVAILABLE)
        self.assertTrue(guarded["unit_price_known"])
        self.assertEqual(guarded["product_detail_url"], MOUSER_URL)
        self.assertTrue(guarded["retrieved_at"])

    def test_manufacturer_mismatch_is_not_verified(self):
        post = Mock(return_value=_response(_mouser_payload(_mouser_part())))
        with _patch_mouser(post):
            guarded = _aggregated("Mouser", mouser_client.search_mouser_by_part_number, OTHER_MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertEqual(guarded["manufacturer_part_number"], "")
        self.assertEqual(guarded["product_detail_url"], "")

    def test_no_hit(self):
        post = Mock(return_value=_response(_mouser_payload()))
        result = self._lookup(post)
        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertIsNone(result["stock_total"])
        self.assertIsNone(result["unit_price"])
        with _patch_mouser(post):
            guarded = _aggregated("Mouser", mouser_client.search_mouser_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)

    def test_neighbor_mpn_is_not_an_exact_hit(self):
        neighbor = _mouser_part(ManufacturerPartNumber="LM358DRG4", MouserPartNumber="595-LM358DRG4")
        post = Mock(return_value=_response(_mouser_payload(neighbor)))
        self.assertEqual(self._lookup(post)["manufacturer_part_number"], "")

    def test_provider_timeout_is_not_a_no_hit(self):
        post = Mock(side_effect=requests.Timeout("read timed out"))
        with _patch_mouser(post):
            with self.assertRaises(RuntimeError):
                mouser_client.search_mouser_by_part_number(MPN)
            guarded = _aggregated("Mouser", mouser_client.search_mouser_by_part_number, MFR)
        self.assertNotEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertEqual(guarded["provider_status"], PROVIDER_ERROR)
        self.assertTrue(guarded["error"])

    def test_provider_http_error_is_not_a_no_hit(self):
        post = Mock(return_value=_response(http_error=_http_error(503)))
        with _patch_mouser(post):
            guarded = _aggregated("Mouser", mouser_client.search_mouser_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_ERROR)
        self.assertNotEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)

    def test_missing_stock_and_price_stay_none(self):
        part = _mouser_part(Availability=_MISSING, PriceBreaks=_MISSING)
        post = Mock(return_value=_response(_mouser_payload(part)))
        result = self._lookup(post)
        self.assertEqual(result["manufacturer_part_number"], MPN)
        self.assertIsNone(result["stock_total"])
        self.assertIsNone(result["unit_price"])

        with _patch_mouser(post):
            guarded = _aggregated("Mouser", mouser_client.search_mouser_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_AVAILABLE)
        self.assertIsNone(guarded["stock_total"])
        self.assertFalse(guarded["unit_price_known"])

    def test_non_stock_availability_text_is_unknown_not_zero(self):
        part = _mouser_part(Availability="Factory Lead Time 12 Weeks")
        post = Mock(return_value=_response(_mouser_payload(part)))
        self.assertIsNone(self._lookup(post)["stock_total"])

    def test_extract_helpers_never_coerce_missing_to_zero(self):
        self.assertIsNone(mouser_client.extract_mouser_price({}))
        self.assertIsNone(mouser_client.extract_mouser_price({"PriceBreaks": []}))
        self.assertIsNone(mouser_client.extract_mouser_price({"PriceBreaks": [{"Price": ""}]}))
        self.assertIsNone(mouser_client.extract_mouser_price({"PriceBreaks": [{"Price": "$0.00"}]}))
        self.assertEqual(
            mouser_client.extract_mouser_price({"PriceBreaks": [{"Price": "$0.55"}]}), 0.55
        )
        self.assertIsNone(mouser_client.extract_stock_number(""))
        self.assertIsNone(mouser_client.extract_stock_number(None))
        default = mouser_client.default_part_result()
        self.assertIsNone(default["stock_total"])
        self.assertIsNone(default["unit_price"])


# --------------------------------------------------------------------------- #
# Newark
# --------------------------------------------------------------------------- #
class NewarkMatrixTests(unittest.TestCase):
    def _lookup(self, get_mock: Mock) -> dict:
        with _patch_newark(get_mock):
            return newark_client.search_newark_by_part_number(MPN)

    def test_exact_mpn_and_manufacturer_match_with_official_url(self):
        get = Mock(return_value=_response(_newark_payload(_newark_product())))
        result = self._lookup(get)
        self.assertEqual(result["manufacturer_part_number"], MPN)
        self.assertEqual(result["manufacturer"], MFR)
        self.assertEqual(result["stock_total"], 987)
        self.assertEqual(result["unit_price"], 0.61)
        self.assertEqual(result["product_detail_url"], NEWARK_URL)
        self.assertTrue(result["listing_verified"])
        self.assertTrue(result["retrieved_at"])

        with _patch_newark(get):
            guarded = _aggregated("Newark", newark_client.search_newark_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_AVAILABLE)
        self.assertTrue(guarded["unit_price_known"])
        self.assertEqual(guarded["product_detail_url"], NEWARK_URL)
        self.assertTrue(guarded["listing_verified"])
        self.assertTrue(guarded["retrieved_at"])

    def test_manufacturer_mismatch_is_not_verified(self):
        get = Mock(return_value=_response(_newark_payload(_newark_product())))
        with _patch_newark(get):
            guarded = _aggregated("Newark", newark_client.search_newark_by_part_number, OTHER_MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertEqual(guarded["manufacturer_part_number"], "")
        self.assertEqual(guarded["product_detail_url"], "")

    def test_no_hit(self):
        get = Mock(return_value=_response({"manufacturerPartNumberSearchReturn": {"products": []}}))
        result = self._lookup(get)
        self.assertEqual(result["manufacturer_part_number"], "")
        self.assertEqual(result["product_detail_url"], "")
        self.assertFalse(result["listing_verified"])
        self.assertIsNone(result["stock_total"])
        self.assertIsNone(result["unit_price"])
        with _patch_newark(get):
            guarded = _aggregated("Newark", newark_client.search_newark_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)

    def test_neighbor_mpn_is_not_an_exact_hit(self):
        product = _newark_product(
            manufacturerPartNumber="LM358DRG4", translatedManufacturerPartNumber="LM358DRG4"
        )
        get = Mock(return_value=_response(_newark_payload(product)))
        self.assertEqual(self._lookup(get)["manufacturer_part_number"], "")

    def test_provider_timeout_is_not_a_no_hit(self):
        get = Mock(side_effect=requests.Timeout("read timed out"))
        with _patch_newark(get):
            guarded = _aggregated("Newark", newark_client.search_newark_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_TIMEOUT)
        self.assertNotEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)
        self.assertTrue(guarded["error"])

    def test_provider_http_error_is_not_a_no_hit(self):
        get = Mock(return_value=_response(http_error=_http_error(502)))
        with _patch_newark(get):
            guarded = _aggregated("Newark", newark_client.search_newark_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_ERROR)
        self.assertNotEqual(guarded["provider_status"], PROVIDER_PART_NOT_FOUND)

    def test_missing_stock_and_price_stay_none(self):
        product = _newark_product(stock=_MISSING, prices=_MISSING)
        get = Mock(return_value=_response(_newark_payload(product)))
        result = self._lookup(get)
        self.assertEqual(result["manufacturer_part_number"], MPN)
        self.assertIsNone(result["stock_total"])
        self.assertIsNone(result["unit_price"])

        with _patch_newark(get):
            guarded = _aggregated("Newark", newark_client.search_newark_by_part_number, MFR)
        self.assertEqual(guarded["provider_status"], PROVIDER_AVAILABLE)
        self.assertIsNone(guarded["stock_total"])
        self.assertFalse(guarded["unit_price_known"])

    def test_explicit_zero_stock_is_preserved_as_zero(self):
        product = _newark_product(stock={"level": 0})
        get = Mock(return_value=_response(_newark_payload(product)))
        self.assertEqual(self._lookup(get)["stock_total"], 0)

    def test_only_official_https_newark_url_is_verified(self):
        official = newark_client.resolve_newark_listing(_newark_product(), allow_sku_lookup=False)
        self.assertTrue(official["listing_verified"])
        self.assertEqual(official["product_detail_url"], NEWARK_URL)
        self.assertTrue(
            official["product_detail_url"].startswith("https://www.newark.com/")
        )

        # Bare apex host is not the canonical store host — reject it.
        bare_host = newark_client.resolve_newark_listing(
            _newark_product(productUrl="https://newark.com/p/58K1234"), allow_sku_lookup=False
        )
        self.assertFalse(bare_host["listing_verified"])
        self.assertEqual(bare_host["product_detail_url"], "")
        self.assertTrue(bare_host["provenance_unavailable"])

        rejected = {
            "bare apex host": "https://newark.com/texas-instruments/lm358dr/dp/58K1234",
            "plain http": "http://www.newark.com/texas-instruments/lm358dr/dp/58K1234",
            "foreign host": "https://www.example.com/www.newark.com/dp/58K1234",
            "lookalike host": "https://www.newark.com.evil.example/dp/58K1234",
            "other distributor": "https://www.digikey.com/en/products/detail/LM358DR",
            "relative path": "/texas-instruments/lm358dr/dp/58K1234",
            "blank": "",
        }
        for label, url in rejected.items():
            with self.subTest(label):
                listing = newark_client.resolve_newark_listing(
                    _newark_product(productUrl=url), allow_sku_lookup=False
                )
                self.assertFalse(listing["listing_verified"])
                self.assertEqual(listing["product_detail_url"], "")
                self.assertTrue(listing["provenance_unavailable"])

    def test_missing_product_url_is_never_fabricated_from_sku(self):
        product = _newark_product(productUrl=_MISSING)
        get = Mock(return_value=_response(_newark_payload(product)))
        result = self._lookup(get)
        self.assertEqual(result["manufacturer_part_number"], MPN)
        self.assertEqual(result["product_detail_url"], "")
        self.assertFalse(result["listing_verified"])
        self.assertTrue(result["provenance_unavailable"])
        self.assertTrue(result["retrieved_at"])
        self.assertNotIn("58K1234", result["product_detail_url"])

    def test_non_official_url_in_search_result_is_dropped(self):
        product = _newark_product(productUrl="https://shop.example.com/58K1234")
        get = Mock(return_value=_response(_newark_payload(product)))
        result = self._lookup(get)
        self.assertEqual(result["product_detail_url"], "")
        self.assertFalse(result["listing_verified"])

    def test_sku_lookup_returns_only_verified_official_url(self):
        verified_payload = _newark_payload(_newark_product())
        with patch.object(newark_client, "get_secret", return_value="k"):
            session = Mock()
            session.get.return_value = _response(verified_payload)
            found = newark_client.lookup_newark_official_listing_url(
                sku="58K1234", expected_mpn=MPN, expected_manufacturer=MFR, session=session
            )
            self.assertTrue(found["listing_verified"])
            self.assertEqual(found["product_detail_url"], NEWARK_URL)

            session.get.return_value = _response(verified_payload)
            mismatch = newark_client.lookup_newark_official_listing_url(
                sku="58K1234", expected_mpn=MPN, expected_manufacturer=OTHER_MFR, session=session
            )
            self.assertFalse(mismatch["listing_verified"])
            self.assertEqual(mismatch["product_detail_url"], "")

            bad_url_payload = _newark_payload(_newark_product(productUrl="http://www.newark.com/x"))
            session.get.return_value = _response(bad_url_payload)
            insecure = newark_client.lookup_newark_official_listing_url(
                sku="58K1234", expected_mpn=MPN, session=session
            )
            self.assertFalse(insecure["listing_verified"])
            self.assertEqual(insecure["product_detail_url"], "")

            invalid_sku = newark_client.lookup_newark_official_listing_url(sku="x!", session=session)
            self.assertFalse(invalid_sku["listing_verified"])

    def test_extract_helpers_never_coerce_missing_to_zero(self):
        self.assertIsNone(newark_client.extract_newark_price({}))
        self.assertIsNone(newark_client.extract_newark_price({"prices": [{"cost": ""}]}))
        self.assertIsNone(newark_client.extract_newark_price({"prices": [{"cost": 0}]}))
        self.assertIsNone(newark_client.extract_newark_stock({}))
        self.assertIsNone(newark_client.extract_newark_stock({"stock": {"level": ""}}))
        self.assertEqual(newark_client.extract_newark_stock({"stock": {"level": 0}}), 0)
        default = newark_client.default_newark_result(MPN)
        self.assertIsNone(default["stock_total"])
        self.assertIsNone(default["unit_price"])


if __name__ == "__main__":
    unittest.main()
