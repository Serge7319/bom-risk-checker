import os
import re

from src.parsing.electrical_extractors import (
    extract_frequency_mhz,
    extract_current_na,
    extract_current_ma,
)
import requests
from dotenv import load_dotenv

from integrations.pin_count import parse_pin_count_from_text, resolve_pin_count
from src.secrets import get_secret
from src.part_images import normalize_supplier_image_url
from src.saved_bom_cost import price_breaks_from_payload, price_number
from src.normalizer import normalize_part_number

load_dotenv()

NEWARK_STORE_ID = "www.newark.com"
NEWARK_STORE_CURRENCY = {NEWARK_STORE_ID: "USD"}


def search_newark_by_part_number(part_number: str) -> dict:
    requested_part_number = str(part_number or "").strip()
    if not requested_part_number:
        return default_newark_result(requested_part_number)

    api_key = get_secret("NEWARK_API_KEY", required=True)

    url = "https://api.element14.com/catalog/products"

    params = {
        "callInfo.apiKey": api_key,
        "callInfo.responseDataFormat": "json",
        "storeInfo.id": NEWARK_STORE_ID,
        "resultsSettings.offset": 0,
        "resultsSettings.numberOfResults": 5,
        "resultsSettings.responseGroup": "large",
        "term": f"manuPartNum:{requested_part_number}",
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    data = response.json()

    products = data.get("manufacturerPartNumberSearchReturn", {}).get("products", [])

    if not products:
        products = data.get("keywordSearchReturn", {}).get("products", [])

    requested_match = normalize_part_number(requested_part_number)
    for product in products:
        if not isinstance(product, dict):
            continue
        candidate_part_numbers = (
            product.get("translatedManufacturerPartNumber"),
            product.get("manufacturerPartNumber"),
        )
        matched_part_number = next(
            (
                str(candidate).strip()
                for candidate in candidate_part_numbers
                if normalize_part_number(str(candidate or "").strip()) == requested_match
            ),
            None,
        )
        if matched_part_number is not None:
            normalized_product = normalize_newark_product(product)
            normalized_product["manufacturer_part_number"] = matched_part_number
            normalized_product["requested_part_number"] = requested_part_number
            normalized_product["retrieved_at"] = _utc_now_iso()
            return normalized_product

    return default_newark_result(requested_part_number)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# Newark order codes (``sku``) are short alphanumeric identifiers such as
# ``58K1234`` or ``NEW1234``.  Anything outside this shape is not trusted as an
# identity hint. SKU alone is never turned into a fabricated product URL.
_NEWARK_SKU_RE = re.compile(r"^[A-Z0-9]{5,12}$")
# Verified listings require the canonical store host only — never the bare
# ``newark.com`` apex or any other host / look-alike.
_OFFICIAL_NEWARK_HOSTS = frozenset({"www.newark.com"})
LISTING_PROVENANCE_PROVIDER_URL = "provider_product_url"
LISTING_PROVENANCE_SKU_LOOKUP = "provider_sku_lookup"
LISTING_PROVENANCE_UNAVAILABLE = "provenance_unavailable"


def _official_newark_https_url(url: object) -> str:
    """Return the URL only when it is HTTPS on ``www.newark.com``."""
    text = str(url or "").strip()
    if not text.lower().startswith("https://"):
        return ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(text)
    except Exception:
        return ""
    host = str(parsed.hostname or "").strip().lower()
    if host not in _OFFICIAL_NEWARK_HOSTS:
        return ""
    return text


def lookup_newark_official_listing_url(
    *,
    sku: str,
    expected_mpn: str = "",
    expected_manufacturer: str = "",
    session: object | None = None,
) -> dict:
    """Documented Element14 catalog lookup by Newark order code (``id:<sku>``).

    Returns an official HTTPS ``www.newark.com`` ``productUrl`` only when the
    provider response verifies the SKU and, when supplied, the exact MPN /
    manufacturer. Never fabricates a listing path from the SKU alone.
    """
    order_code = str(sku or "").strip().upper()
    if not order_code or not _NEWARK_SKU_RE.fullmatch(order_code):
        return {
            "product_detail_url": "",
            "listing_verified": False,
            "listing_url_provenance": LISTING_PROVENANCE_UNAVAILABLE,
            "provenance_unavailable": True,
            "supplier_sku": "",
        }
    api_key = get_secret("NEWARK_API_KEY", required=True)
    params = {
        "callInfo.apiKey": api_key,
        "callInfo.responseDataFormat": "json",
        "storeInfo.id": NEWARK_STORE_ID,
        "resultsSettings.offset": 0,
        "resultsSettings.numberOfResults": 5,
        "resultsSettings.responseGroup": "large",
        "term": f"id:{order_code}",
    }
    http = session or requests
    response = http.get(
        "https://api.element14.com/catalog/products",
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    products = data.get("manufacturerPartNumberSearchReturn", {}).get("products", [])
    if not products:
        products = data.get("keywordSearchReturn", {}).get("products", [])
    expected_mpn_n = normalize_part_number(expected_mpn) if expected_mpn else ""
    expected_mfr_n = str(expected_manufacturer or "").strip().casefold()
    for product in products if isinstance(products, list) else []:
        if not isinstance(product, dict):
            continue
        product_sku = str(product.get("sku") or "").strip().upper()
        if product_sku and product_sku != order_code:
            continue
        candidate_mpn = str(
            product.get("translatedManufacturerPartNumber")
            or product.get("manufacturerPartNumber")
            or ""
        ).strip()
        if expected_mpn_n and normalize_part_number(candidate_mpn) != expected_mpn_n:
            continue
        candidate_mfr = str(product.get("brandName") or "").strip()
        if expected_mfr_n and candidate_mfr.casefold() != expected_mfr_n:
            continue
        official = _official_newark_https_url(product.get("productUrl"))
        if not official:
            continue
        return {
            "product_detail_url": official,
            "listing_verified": True,
            "listing_url_provenance": LISTING_PROVENANCE_SKU_LOOKUP,
            "provenance_unavailable": False,
            "supplier_sku": order_code,
        }
    return {
        "product_detail_url": "",
        "listing_verified": False,
        "listing_url_provenance": LISTING_PROVENANCE_UNAVAILABLE,
        "provenance_unavailable": True,
        "supplier_sku": order_code,
    }


def resolve_newark_listing(
    product: dict,
    *,
    allow_sku_lookup: bool = True,
    lookup: object | None = None,
) -> dict:
    """Return ``product_detail_url`` plus provenance without inventing URLs.

    - Official HTTPS ``productUrl`` on ``www.newark.com`` → verified listing.
    - Arbitrary http(s) hosts are never marked verified.
    - When ``productUrl`` is missing, optionally perform the documented Element14
      ``id:<sku>`` lookup and accept only a verified official HTTPS URL that
      matches the payload MPN/manufacturer/SKU.
    - Otherwise leave the URL empty and mark ``provenance_unavailable``.
    """
    product = product if isinstance(product, dict) else {}
    provider_url = _official_newark_https_url(product.get("productUrl"))
    sku = str(product.get("sku") or "").strip().upper()
    supplier_sku = sku if sku and _NEWARK_SKU_RE.fullmatch(sku) else ""
    if provider_url:
        return {
            "product_detail_url": provider_url,
            "listing_verified": True,
            "listing_url_provenance": LISTING_PROVENANCE_PROVIDER_URL,
            "provenance_unavailable": False,
            "supplier_sku": supplier_sku,
        }
    if allow_sku_lookup and supplier_sku:
        expected_mpn = str(
            product.get("translatedManufacturerPartNumber")
            or product.get("manufacturerPartNumber")
            or product.get("requested_part_number")
            or ""
        ).strip()
        expected_mfr = str(product.get("brandName") or product.get("manufacturer") or "").strip()
        try:
            lookup_fn = lookup or lookup_newark_official_listing_url
            resolved = lookup_fn(
                sku=supplier_sku,
                expected_mpn=expected_mpn,
                expected_manufacturer=expected_mfr,
            )
            if isinstance(resolved, dict) and resolved.get("listing_verified"):
                return {
                    "product_detail_url": str(resolved.get("product_detail_url") or ""),
                    "listing_verified": True,
                    "listing_url_provenance": str(
                        resolved.get("listing_url_provenance") or LISTING_PROVENANCE_SKU_LOOKUP
                    ),
                    "provenance_unavailable": False,
                    "supplier_sku": supplier_sku,
                }
        except Exception:
            # Lookup failures stay provenance-unavailable; never fabricate a URL.
            pass
    return {
        "product_detail_url": "",
        "listing_verified": False,
        "listing_url_provenance": LISTING_PROVENANCE_UNAVAILABLE,
        "provenance_unavailable": True,
        "supplier_sku": supplier_sku,
    }


class NewarkCatalogResponseError(RuntimeError):
    """Invalid Newark catalog payload that is not an empty successful result set."""

    def __init__(self, message: str, *, subreason: str = "malformed_response"):
        super().__init__(message)
        self.subreason = str(subreason or "malformed_response")


class NewarkCatalogPartialResultsError(RuntimeError):
    """Some Newark catalog terms returned leads while another term failed.

    Callers must retain ``candidates`` and still report ``cause`` as a catalog
    failure. Never logs credentials or request URLs.
    """

    def __init__(
        self,
        message: str,
        *,
        candidates: list[dict],
        cause: BaseException,
        failed_term: str = "",
    ):
        super().__init__(message)
        self.candidates = list(candidates or [])
        self.cause = cause
        self.failed_term = str(failed_term or "").strip()
        self.subreason = str(getattr(cause, "subreason", "") or "")
        self.__cause__ = cause
        response = getattr(cause, "response", None)
        if response is not None:
            self.response = response


def search_newark_catalog_candidates(
    part_number: str,
    *,
    limit: int = 12,
    include_family_search: bool = True,
) -> list[dict]:
    """Search Newark catalog terms and return review-only candidate leads.

    Distinguishes:
    - empty successful HTTP responses (``products: []`` or omit ``products`` with
      ``numberOfResults: 0``)
      → ``[]``
    - timeout / HTTP / auth / invalid JSON or payload → raise the classified error
    - mixed terms: keep candidate rows and raise ``NewarkCatalogPartialResultsError``
      so a successful empty or lead-bearing term cannot hide a failed term

    Never logs API keys or credentialed request URLs.
    """
    requested = str(part_number or "").strip()
    if not requested:
        return []
    api_key = get_secret("NEWARK_API_KEY", required=True)
    family = _catalog_family_search_term(requested) if include_family_search else ""
    terms = [requested]
    if family and family.casefold() != requested.casefold():
        terms.append(family)

    candidates: list[dict] = []
    seen: set[str] = set()
    last_failure: BaseException | None = None
    failed_term = ""
    saw_successful_empty = False
    retrieved_at = _utc_now_iso()
    for term in terms:
        # Keep credentials in the request params only — never interpolate into logs.
        params = {
            "callInfo.apiKey": api_key,
            "callInfo.responseDataFormat": "json",
            "storeInfo.id": NEWARK_STORE_ID,
            "resultsSettings.offset": 0,
            "resultsSettings.numberOfResults": max(1, min(int(limit), 25)),
            "resultsSettings.responseGroup": "large",
            # element14 Product Search API documents keyword search as any:<query>.
            "term": f"any:{term}",
        }
        try:
            response = requests.get(
                "https://api.element14.com/catalog/products",
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as error:
                wrapped = NewarkCatalogResponseError(
                    "Newark catalog response was not valid JSON.",
                    subreason="malformed_response",
                )
                wrapped.__cause__ = error
                last_failure = wrapped
                failed_term = term
                continue
        except Exception as error:  # noqa: BLE001 — classify upstream via diagnostics
            last_failure = error
            failed_term = term
            continue

        if not isinstance(data, dict):
            last_failure = NewarkCatalogResponseError(
                "Newark catalog response was not a JSON object.",
                subreason="malformed_response",
            )
            failed_term = term
            continue

        if "keywordSearchReturn" not in data:
            last_failure = NewarkCatalogResponseError(
                "Newark catalog response omitted keywordSearchReturn.",
                subreason="malformed_response",
            )
            failed_term = term
            continue

        search_return = data.get("keywordSearchReturn")
        if not isinstance(search_return, dict):
            last_failure = NewarkCatalogResponseError(
                "Newark catalog keywordSearchReturn was invalid.",
                subreason="malformed_response",
            )
            failed_term = term
            continue

        # element14 omits ``products`` on valid zero-hit responses and returns
        # ``numberOfResults`` only. Treat that as empty success; omit+hits is malformed.
        if "products" not in search_return:
            number_of_results = search_return.get("numberOfResults")
            try:
                result_count = int(number_of_results) if number_of_results is not None else 0
            except (TypeError, ValueError):
                result_count = -1
            if result_count == 0:
                saw_successful_empty = True
                continue
            last_failure = NewarkCatalogResponseError(
                "Newark catalog keywordSearchReturn omitted products.",
                subreason="malformed_response",
            )
            failed_term = term
            continue

        products = search_return.get("products")
        if not isinstance(products, list):
            last_failure = NewarkCatalogResponseError(
                "Newark catalog products payload was invalid.",
                subreason="malformed_response",
            )
            failed_term = term
            continue

        if not products:
            saw_successful_empty = True

        for product in products:
            if not isinstance(product, dict):
                continue
            mpn = str(
                product.get("translatedManufacturerPartNumber")
                or product.get("manufacturerPartNumber")
                or ""
            ).strip()
            key = normalize_part_number(mpn)
            if not mpn or not key or key == normalize_part_number(requested) or key in seen:
                continue
            seen.add(key)
            normalized = normalize_newark_product(product)
            normalized["manufacturer_part_number"] = mpn
            category = _newark_category_text(product)
            candidates.append({
                **normalized,
                "source": "Newark",
                "evidence_type": "Distributor family search match" if family and term.casefold() == family.casefo