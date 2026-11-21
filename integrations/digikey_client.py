import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterator, Optional

import requests
from urllib.parse import quote

from integrations.pin_count import parse_pin_count_from_text, resolve_pin_count
from integrations.stock_coercion import parse_stock_total
from src.secrets import get_secret
from src.part_images import normalize_supplier_image_url
from src.saved_bom_cost import price_breaks_from_payload, price_number
from src.parsing.electrical_extractors import (
    extract_frequency_mhz,
    extract_slew_rate_v_us,
    extract_voltage_mv,
    extract_current_na,
    extract_current_ma,
)


_DIGIKEY_TOKEN_LOCK = threading.Lock()
_DIGIKEY_CACHED_TOKEN: str | None = None
_DIGIKEY_TOKEN_EXPIRES_AT: float = 0.0
_DIGIKEY_REQUESTED_MANUFACTURER: ContextVar[str] = ContextVar(
    "digikey_requested_manufacturer", default=""
)


@contextmanager
def digikey_requested_manufacturer(manufacturer: str) -> Iterator[None]:
    """Constrain DigiKey exact-product selection to a caller-selected brand."""
    token = _DIGIKEY_REQUESTED_MANUFACTURER.set(str(manufacturer or "").strip())
    try:
        yield
    finally:
        _DIGIKEY_REQUESTED_MANUFACTURER.reset(token)


def get_digikey_access_token() -> str:
    """Return a DigiKey access token, reusing one until shortly before expiry.

    Empty or expired cache refreshes are single-flight: concurrent callers share
    one token endpoint request under ``_DIGIKEY_TOKEN_LOCK``.
    """
    global _DIGIKEY_CACHED_TOKEN, _DIGIKEY_TOKEN_EXPIRES_AT
    with _DIGIKEY_TOKEN_LOCK:
        now = time.monotonic()
        if (
            _DIGIKEY_CACHED_TOKEN
            and _DIGIKEY_TOKEN_EXPIRES_AT > now + 60.0
        ):
            return _DIGIKEY_CACHED_TOKEN

        client_id = get_secret("DIGIKEY_CLIENT_ID", required=True)
        client_secret = get_secret("DIGIKEY_CLIENT_SECRET", required=True)

        url = "https://api.digikey.com/v1/oauth2/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        }

        response = requests.post(url, data=data, timeout=15)
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("DigiKey token response did not include an access token.")
        try:
            expires_in = float(payload.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires_in = 3600.0
        _DIGIKEY_CACHED_TOKEN = token
        _DIGIKEY_TOKEN_EXPIRES_AT = time.monotonic() + max(60.0, expires_in)
        return token


_DIGIKEY_SITE = "US"
_DIGIKEY_CURRENCY = "USD"


def _digikey_headers(client_id: str, access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "X-DIGIKEY-Client-Id": client_id,
        "X-DIGIKEY-Locale-Site": _DIGIKEY_SITE,
        "X-DIGIKEY-Locale-Language": "en",
        "X-DIGIKEY-Locale-Currency": _DIGIKEY_CURRENCY,
    }


def _mpn_key(value: object) -> str:
    """Return a conservative comparison key for manufacturer part numbers."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


_DIGIKEY_DISTRIBUTOR_PART_RE = re.compile(r"^\d+-.+?-ND$", re.IGNORECASE)


def is_digikey_distributor_part_number(part_number: str) -> bool:
    """True when the input looks like a DigiKey distributor/order number."""
    text = str(part_number or "").strip()
    return bool(text and _DIGIKEY_DISTRIBUTOR_PART_RE.match(text))


def _digikey_product_number_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _product_matches_digikey_number(product: dict, distributor_number: str) -> bool:
    requested = _digikey_product_number_key(distributor_number)
    if not requested or not isinstance(product, dict):
        return False
    if _digikey_product_number_key(product.get("DigiKeyProductNumber")) == requested:
        return True
    for variation in product.get("ProductVariations") or []:
        if not isinstance(variation, dict):
            continue
        if _digikey_product_number_key(variation.get("DigiKeyProductNumber")) == requested:
            return True
    return False


def resolve_engineering_part_identity(part_number: str) -> dict:
    """Resolve a user-entered part to canonical manufacturer identity."""
    requested = str(part_number or "").strip()
    identity = {
        "requested_part_number": requested,
        "manufacturer_part_number": requested,
        "digikey_part_number": "",
        "order_part_number": "",
    }
    if not requested:
        return identity
    if not is_digikey_distributor_part_number(requested):
        return identity
    supplier_data = search_digikey_by_part_number(requested)
    mpn = str(supplier_data.get("manufacturer_part_number") or "").strip()
    if mpn:
        identity["manufacturer_part_number"] = mpn
    identity["digikey_part_number"] = str(
        supplier_data.get("digikey_part_number") or requested
    ).strip()
    identity["order_part_number"] = requested
    identity["supplier_data"] = supplier_data
    return identity


def _exact_keyword_products(products: list, part_number: str) -> list[dict]:
    """Return every exact manufacturer-MPN hit from a DigiKey keyword response."""
    requested_key = _mpn_key(part_number)
    if not requested_key:
        return []
    matches: list[dict] = []
    for product in products or []:
        if not isinstance(product, dict):
            continue
        if _mpn_key(product.get("ManufacturerProductNumber")) == requested_key:
            matches.append(product)
    return matches


def _product_manufacturer_name(product: dict) -> str:
    manufacturer = product.get("Manufacturer")
    if isinstance(manufacturer, dict):
        return str(manufacturer.get("Name") or manufacturer.get("Value") or "").strip()
    return str(manufacturer or "").strip()


def _exact_keyword_product(
    products: list,
    part_number: str,
    *,
    manufacturer: str = "",
) -> Optional[dict]:
    """Select the exact MPN from a DigiKey keyword response.

    Keyword search is ranked, not an exact-MPN endpoint. Using its first result
    can attach a substitution lookup to a neighboring package, tape/reel
    variant, or unrelated prefix match. Only an exact manufacturer MPN is a
    safe baseline for a replacement recommendation. When manufacturer is
    provided, prefer the matching brand instead of silently picking another.
    """
    matches = _exact_keyword_products(products, part_number)
    if not matches:
        return None
    requested_mfr = str(manufacturer or "").strip()
    if requested_mfr:
        try:
            from apps.api.manufacturer_identity import manufacturers_match
        except Exception:  # noqa: BLE001
            manufacturers_match = None  # type: ignore[assignment]
        preferred: list[dict] = []
        for product in matches:
            product_mfr = _product_manufacturer_name(product)
            if manufacturers_match and manufacturers_match(
                requested_mfr, product_mfr, mpn=part_number
            ):
                preferred.append(product)
            elif (
                not manufacturers_match
                and product_mfr.casefold() == requested_mfr.casefold()
            ):
                preferred.append(product)
        if preferred:
            return preferred[0]
        # Exact MPN exists only under other brands — do not silently substitute.
        return None
    return matches[0]


def _select_exact_digikey_product(
    products: list,
    part_number: str,
    *,
    manufacturer: str = "",
) -> Optional[dict]:
    """Select an exact MPN match or a DigiKey distributor/order-number match."""
    requested = str(part_number or "").strip()
    if not requested:
        return None
    if is_digikey_distributor_part_number(requested):
        for product in products or []:
            if isinstance(product, dict) and _product_matches_digikey_number(product, requested):
                return product
        return None
    return _exact_keyword_product(products, part_number, manufacturer=manufacturer)


def _search_digikey_exact_product(
    part_number: str,
    *,
    client_id: str,
    access_token: str,
    manufacturer: str = "",
) -> Optional[dict]:
    """Return the raw exact keyword product so callers retain package variants.

    DigiKey can associate the same manufacturer MPN with multiple purchasing
    package numbers (TR, CT, and DKR).  The substitutions endpoint is keyed by
    a DigiKey product number, so keeping these variants lets us ask every
    authoritative representation instead of silently falling back when the
    first variant does not expose the relationship.
    """
    url = "https://api.digikey.com/products/v4/search/keyword"
    headers = _digikey_headers(client_id, access_token)
    payload = {
        "Keywords": part_number,
        # A keyword search is not guaranteed to put the exact MPN first.
        # Keep this bounded, then explicitly select the exact product below.
        "Limit": 12,
        "Offset": 0,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    response.raise_for_status()
    products = (response.json() or {}).get("Products") or []
    requested_mfr = str(manufacturer or "").strip() or _DIGIKEY_REQUESTED_MANUFACTURER.get()
    return _select_exact_digikey_product(
        products, part_number, manufacturer=requested_mfr
    )


def _search_digikey_by_part_number(
    part_number: str,
    *,
    client_id: str,
    access_token: str,
    manufacturer: str = "",
) -> dict:
    requested = str(part_number or "").strip()
    product = _search_digikey_exact_product(
        requested,
        client_id=client_id,
        access_token=access_token,
        manufacturer=manufacturer,
    )
    if not product:
        return default_digikey_result(requested)
    normalized = normalize_digikey_product(product)
    normalized["searched_part_number"] = requested
    normalized["retrieved_at"] = _utc_now_iso()
    if is_digikey_distributor_part_number(requested):
        normalized["order_part_number"] = requested
        normalized["digikey_part_number"] = requested
    return normalized


def _variation_mpn(product: dict, variation: Optional[dict] = None) -> str:
    """Return an explicit manufacturer MPN from a variation, else empty string.

    DigiKey ProductVariations often omit ManufacturerProductNumber for true
    packaging SKUs of the parent product, but may also list sibling family
    DigiKey numbers without an MPN. Callers must not treat a missing variation
    MPN as automatically equal to the parent MPN.
    """
    if not isinstance(variation, dict):
        return ""
    for key in ("ManufacturerProductNumber", "ManufacturerPartNumber", "RequestedPartNumber"):
        value = str(variation.get(key) or "").strip()
        if value:
            return value
    return ""


def _variation_belongs_to_requested_mpn(
    product: dict,
    variation: dict,
    *,
    required_mpn: str,
) -> bool:
    """True when a ProductVariation is a packaging SKU of the requested MPN."""
    required_key = _mpn_key(required_mpn) or _mpn_key(
        (product or {}).get("ManufacturerProductNumber")
    )
    if not required_key:
        return False
    explicit_mpn = _variation_mpn(product, variation)
    if explicit_mpn:
        return _mpn_key(explicit_mpn) == required_key
    # No explicit MPN: only keep DigiKey numbers that encode this manufacturer MPN.
    digikey_number = str((variation or {}).get("DigiKeyProductNumber") or "").strip()
    return bool(digikey_number) and required_key in _mpn_key(digikey_number)


def _digikey_product_numbers(product: dict, *, required_mpn: str = "") -> list[str]:
    """Collect distributor product numbers that belong to the requested manufacturer MPN.

    DigiKey sometimes lists sibling family SKUs under ProductVariations. Those
    numbers must not be used as substitutions keys for a different MPN — their
    Direct/Upgrade/Similar lists describe a different original part.
    """
    numbers = []
    if not isinstance(product, dict):
        return numbers
    required_key = _mpn_key(required_mpn) or _mpn_key(product.get("ManufacturerProductNumber"))
    parent_mpn = str(product.get("ManufacturerProductNumber") or "").strip()
    if not required_key or _mpn_key(parent_mpn) == required_key:
        primary = str(product.get("DigiKeyProductNumber") or "").strip()
        if primary:
            numbers.append(primary)
    for variation in product.get("ProductVariations") or []:
        if not isinstance(variation, dict):
            continue
        if required_key and not _variation_belongs_to_requested_mpn(
            product, variation, required_mpn=required_mpn or parent_mpn
        ):
            continue
        value = str(variation.get("DigiKeyProductNumber") or "").strip()
        if value:
            numbers.append(value)
    seen: set[str] = set()
    return [
        value
        for value in numbers
        if not (value.casefold() in seen or seen.add(value.casefold()))
    ]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def search_digikey_by_part_number(part_number: str, manufacturer: str = "") -> dict:
    client_id = get_secret("DIGIKEY_CLIENT_ID", required=True)
    requested_mfr = str(manufacturer or "").strip() or _DIGIKEY_REQUESTED_MANUFACTURER.get()
    return _search_digikey_by_part_number(
        part_number,
        client_id=client_id,
        access_token=get_digikey_access_token(),
        manufacturer=requested_mfr,
    )


def _as_number(value, default=0):
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def search_digikey_substitutions(part_number: str) -> list[dict]:
    """Return genuine DigiKey substitute relationships for any product family."""
    requested = str(part_number or "").strip()
    if not requested:
        return []
    client_id = get_secret("DIGIKEY_CLIENT_ID", required=True)
    access_token = get_digikey_access_token()
    product = _search_digikey_exact_product(
        requested,
        client_id=client_id,
        access_token=access_token,
        manufacturer=_DIGIKEY_REQUESTED_MANUFACTURER.get(),
    )
    product_numbers = _digikey_product_numbers(product or {}, required_mpn=requested)
    if not product_numbers:
        # Do not call the substitutions endpoint for an unverified keyword
        # match. A catalog search below can still provide clearly-labelled
        # candidates, but it must not look like substitute evidence.
        return []
    results = []
    seen_by_mpn: dict[str, dict] = {}
    retrieved_at = _utc_now_iso()
    from src.alternative_classification import (
        build_supplier_relationship_evidence,
        conservative_substitute_type,
        normalize_substitute_type,
    )

    for product_number in product_numbers:
        response = requests.get(
            "https://api.digikey.com/products/v4/search/"
            f"{quote(product_number, safe='')}/substitutions",
            headers=_digikey_headers(client_id, access_token),
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json() or {}
        substitute_rows = payload.get("ProductSubstitutes")
        if substitute_rows is None:
            substitute_rows = payload.get("Substitutions")
        if not isinstance(substitute_rows, list):
            # Never fall back to generic Products lists: those are not substitute
            # relationships and must not inherit Direct/Upgrade/Similar evidence.
            substitute_rows = []
        for item in substitute_rows:
            if not isinstance(item, dict):
                continue
            mpn = str(item.get("ManufacturerProductNumber") or "").strip()
            mpn_key = _mpn_key(mpn)
            if not mpn or mpn_key == _mpn_key(requested):
                continue
            manufacturer = item.get("Manufacturer") or {}
            lifecycle_status = infer_digikey_lifecycle(