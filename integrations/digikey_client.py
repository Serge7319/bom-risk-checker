import re
from datetime import datetime, timezone
from typing import Optional

import requests
from urllib.parse import quote

from src.secrets import get_secret
from src.parsing.electrical_extractors import (
    extract_frequency_mhz,
    extract_slew_rate_v_us,
    extract_voltage_mv,
    extract_current_na,
    extract_current_ma,
)


def get_digikey_access_token() -> str:
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

    return response.json()["access_token"]


def _digikey_headers(client_id: str, access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "X-DIGIKEY-Client-Id": client_id,
        "X-DIGIKEY-Locale-Site": "US",
        "X-DIGIKEY-Locale-Language": "en",
        "X-DIGIKEY-Locale-Currency": "USD",
    }


def _mpn_key(value: object) -> str:
    """Return a conservative comparison key for manufacturer part numbers."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _exact_keyword_product(products: list, part_number: str) -> Optional[dict]:
    """Select the exact MPN from a DigiKey keyword response."""
    requested_key = _mpn_key(part_number)
    if not requested_key:
        return None
    for product in products or []:
        if not isinstance(product, dict):
            continue
        if _mpn_key(product.get("ManufacturerProductNumber")) == requested_key:
            return product
    return None


def _search_digikey_exact_product(part_number: str, *, client_id: str, access_token: str) -> Optional[dict]:
    """Return the raw exact keyword product so callers retain package variants."""
    url = "https://api.digikey.com/products/v4/search/keyword"
    headers = _digikey_headers(client_id, access_token)
    payload = {
        "Keywords": part_number,
        "Limit": 12,
        "Offset": 0,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    response.raise_for_status()
    products = (response.json() or {}).get("Products") or []
    return _exact_keyword_product(products, part_number)


def _search_digikey_by_part_number(part_number: str, *, client_id: str, access_token: str) -> dict:
    product = _search_digikey_exact_product(
        part_number, client_id=client_id, access_token=access_token
    )
    if not product:
        return default_digikey_result(part_number)
    return normalize_digikey_product(product)


def _digikey_product_numbers(product: dict) -> list[str]:
    """Collect all distributor product numbers for an exact MPN, in order."""
    numbers = []
    if not isinstance(product, dict):
        return numbers
    primary = str(product.get("DigiKeyProductNumber") or "").strip()
    if primary:
        numbers.append(primary)
    for variation in product.get("ProductVariations") or []:
        if not isinstance(variation, dict):
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


def search_digikey_by_part_number(part_number: str) -> dict:
    client_id = get_secret("DIGIKEY_CLIENT_ID", required=True)
    return _search_digikey_by_part_number(
        part_number, client_id=client_id, access_token=get_digikey_access_token()
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
        requested, client_id=client_id, access_token=access_token
    )
    product_numbers = _digikey_product_numbers(product or {})
    if not product_numbers:
        return []
    results = []
    seen_mpns: set[str] = set()
    retrieved_at = _utc_now_iso()
    for product_number in product_numbers:
        response = requests.get(
            "https://api.digikey.com/products/v4/search/"
            f"{quote(product_number, safe='')}/substitutions",
            headers=_digikey_headers(client_id, access_token),
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json() or {}
        substitute_rows = (
            payload.get("ProductSubstitutes")
            or payload.get("Substitutions")
            or payload.get("Products")
            or []
        )
        for item in substitute_rows:
            if not isinstance(item, dict):
                continue
            mpn = str(item.get("ManufacturerProductNumber") or "").strip()
            mpn_key = _mpn_key(mpn)
            if not mpn or mpn_key == _mpn_key(requested) or mpn_key in seen_mpns:
                continue
            seen_mpns.add(mpn_key)
            manufacturer = item.get("Manufacturer") or {}
            results.append({
                "source": "DigiKey",
                "evidence_type": "Distributor-listed substitute",
                "substitute_type": str(item.get("SubstituteType") or "Candidate").strip(),
                "manufacturer_part_number": mpn,
                "manufacturer": (
                    str(manufacturer.get("Name") or "")
                    if isinstance(manufacturer, dict)
                    else str(manufacturer)
                ),
                "description": str(item.get("Description") or "").strip(),
                "stock_total": int(_as_number(item.get("QuantityAvailable"), 0)),
                "unit_price": _as_number(item.get("UnitPrice"), 0.0),
                "product_detail_url": str(item.get("ProductUrl") or "").strip(),
                "datasheet_url": str(item.get("DatasheetUrl") or "").strip(),
                "digikey_part_number": str(item.get("DigiKeyProductNumber") or "").strip(),
                "retrieval_status": "ok",
                "retrieved_at": retrieved_at,
            })
    return results


def _catalog_search_terms(part_number: str) -> list[str]:
    """Return conservative MPN-family searches without treating them as proof."""
    requested = str(part_number or "").strip()
    terms = [requested]
    upper = requested.upper()
    for suffix in ("CT", "TR", "TU", "DKR"):
        if upper.endswith(suffix) and len(requested) > len(suffix) + 6:
            terms.append(requested[: -len(suffix)])
    seen: set[str] = set()
    return [
        term
        for term in terms
        if term and not (term.casefold() in seen or seen.add(term.casefold()))
    ]


def search_digikey_catalog_candidates(part_number: str, *, limit: int = 12) -> list[dict]:
    """Return catalog candidates when DigiKey has no explicit substitute mapping."""
    requested = str(part_number or "").strip()
    if not requested:
        return []
    client_id = get_secret("DIGIKEY_CLIENT_ID", required=True)
    access_token = get_digikey_access_token()
    candidates = []
    seen_part_numbers: set[str] = set()
    retrieved_at = _utc_now_iso()
    for search_term in _catalog_search_terms(requested):
        response = requests.post(
            "https://api.digikey.com/products/v4/search/keyword",
            headers=_digikey_headers(client_id, access_token),
            json={"Keywords": search_term, "Limit": max(1, min(int(limit), 25)), "Offset": 0},
            timeout=15,
        )
        response.raise_for_status()
        for product in (response.json() or {}).get("Products") or []:
            if not isinstance(product, dict):
                continue
            normalized = normalize_digikey_product(product)
            mpn = str(normalized.get("manufacturer_part_number") or "").strip()
            if (
                not mpn
                or mpn.casefold() == requested.casefold()
                or mpn.casefold() in seen_part_numbers
            ):
                continue
            seen_part_numbers.add(mpn.casefold())
            candidates.append({
                "source": "DigiKey",
                "evidence_type": "Distributor catalog match",
                "substitute_type": "Similar",
                "manufacturer_part_number": mpn,
                "manufacturer": normalized.get("manufacturer", ""),
                "description": normalized.get("description", ""),
                "stock_total": normalized.get("stock_total", 0),
                "unit_price": normalized.get("unit_price", 0.0),
                "product_detail_url": normalized.get("product_detail_url", ""),
                "datasheet_url": normalized.get("datasheet_url", ""),
                "digikey_part_number": normalized.get("digikey_part_number", ""),
                "retrieval_status": "ok",
                "retrieved_at": retrieved_at,
            })
    return candidates


def extract_digikey_parameter(product: dict, target_names: list) -> str:
    parameters = product.get("Parameters", [])

    for param in parameters:
        name = str(param.get("ParameterText", "")).lower()
        value = str(param.get("ValueText", ""))

        for target in target_names:
            if target.lower() in name:
                return value

    return ""


def extract_pin_count(text: str) -> int:
    import re

    match = re.search(r"\b(\d+)\b", str(text))

    if match:
        return int(match.group(1))

    return 0


def normalize_digikey_product(product: dict) -> dict:
    manufacturer = product.get("Manufacturer", {})
    manufacturer_name = (
        manufacturer.get("Name", "")
        if isinstance(manufacturer, dict)
        else str(manufacturer)
    )

    stock_total = product.get("QuantityAvailable", 0) or 0

    package = extract_digikey_parameter(
        product,
        ["Package / Case", "Supplier Device Package"],
    )

    mounting_style = extract_digikey_parameter(
        product,
        ["Mounting Type"],
    )

    pin_count_text = extract_digikey_parameter(
        product,
        ["Number of Pins", "Supplier Device Package", "Package / Case"],
    )

    pin_count = extract_pin_count(pin_count_text)

    description = (
        product.get("Description", {}).get("ProductDescription", "")
        if isinstance(product.get("Description"), dict)
        else str(product.get("Description", ""))
    )

    architecture = infer_architecture_from_description(description)
    channel_count = infer_channel_count_from_description(description)

    voltage_range = extract_digikey_parameter(
        product,
        ["Voltage - Supply", "Supply Voltage", "Operating Supply Voltage"],
    )

    supply_voltage_min, supply_voltage_max = extract_voltage_limits(voltage_range)

    if supply_voltage_min == supply_voltage_max:
        supply_voltage_min = None
        supply_voltage_max = None

    bandwidth_text = extract_digikey_parameter(
        product,
        ["Gain Bandwidth Product", "Bandwidth", "GBW"],
    )

    bandwidth_mhz = extract_frequency_mhz(bandwidth_text)

    slew_rate_text = extract_digikey_parameter(
        product,
        ["Slew Rate"],
    )

    slew_rate_v_us = extract_slew_rate_v_us(slew_rate_text)

    input_offset_text = extract_digikey_parameter(
        product,
        ["Voltage - Input Offset", "Input Offset Voltage"],
    )

    input_offset_mv = extract_voltage_mv(input_offset_text)

    input_bias_text = extract_digikey_parameter(
        product,
        ["Current - Input Bias", "Input Bias Current"],
    )

    input_bias_na = extract_current_na(input_bias_text)

    quiescent_current_text = extract_digikey_parameter(
        product,
        ["Current - Supply", "Supply Current", "Quiescent Current"],
    )

    quiescent_current_ma = extract_current_ma(quiescent_current_text)

    gbw_text = extract_digikey_parameter(
        product,
        ["Gain Bandwidth Product", "Gain Bandwidth", "GBW"],
    )

    gbw_mhz = extract_frequency_mhz(gbw_text)

    parametric_fields = {
        "capacitance": ["Capacitance"],
        "resistance": ["Resistance"],
        "inductance": ["Inductance"],
        "tolerance": ["Tolerance"],
        "rated_voltage": ["Voltage - Rated", "Voltage Rating"],
        "dielectric": ["Temperature Coefficient", "Dielectric"],
        "power_rating": ["Power (Watts)", "Power Rating"],
        "temperature_coefficient": ["Temperature Coefficient"],
        "esr": ["ESR (Equivalent Series Resistance)", "ESR"],
        "rated_current": ["Current - Rated", "Current Rating"],
        "saturation_current": ["Current - Saturation"],
        "dcr": ["DC Resistance (DCR)"],
        "device_type": ["Transistor Type", "Technology"],
        "reverse_voltage": ["Voltage - DC Reverse (Vr) (Max)", "Reverse Voltage"],
        "forward_current": ["Current - Average Rectified (Io)", "Forward Current"],
    }
    parametric = {
        key: extract_digikey_parameter(product, names)
        for key, names in parametric_fields.items()
    }

    return {
        "lifecycle_status": infer_digikey_lifecycle(product),
        "stock_total": int(stock_total),
        "unit_price": extract_digikey_price(product),
        "supplier_count": 1,
        "lead_time_weeks": None,
        "has_alternates": False,
        "source": "DigiKey",
        "manufacturer": manufacturer_name,

        "description": description,
        "architecture": architecture,
        "channel_count": channel_count,

        "mouser_part_number": "",
        "manufacturer_part_number": product.get("ManufacturerProductNumber", ""),
        "digikey_part_number": product.get("DigiKeyProductNumber", ""),
        "product_detail_url": product.get("ProductUrl", ""),
        "datasheet_url": product.get("DatasheetUrl", ""),

        "package": package,
        "pin_count": pin_count,
        "mounting_style": mounting_style,

        "voltage_range": voltage_range,
        "supply_voltage_min": supply_voltage_min,
        "supply_voltage_max": supply_voltage_max,

        "bandwidth_mhz": bandwidth_mhz,
        "slew_rate_v_us": slew_rate_v_us,
        "input_offset_mv": input_offset_mv,
        "input_bias_na": input_bias_na,
        "quiescent_current_ma": quiescent_current_ma,
        "gbw_mhz": gbw_mhz,
        **parametric,
    }

def extract_digikey_price(product: dict) -> float:
    price_breaks = product.get("UnitPrice") or product.get("StandardPricing") or []

    if isinstance(price_breaks, (int, float)):
        return float(price_breaks)

    if isinstance(price_breaks, str):
        try:
            return float(price_breaks.replace("$", "").replace(",", "").strip())
        except ValueError:
            return 0.0

    if isinstance(price_breaks, list) and price_breaks:
        first_break = price_breaks[0]

        price = (
            str(first_break.get("UnitPrice", first_break.get("Price", "")))
            .replace("$", "")
            .replace(",", "")
            .strip()
        )

        try:
            return float(price)
        except ValueError:
            return 0.0

    return 0.0

def infer_digikey_lifecycle(product: dict) -> str:
    status = product.get("ProductStatus", "")

    if isinstance(status, dict):
        status = status.get("Status", "")

    status_text = str(status).strip()

    if status_text:
        return status_text

    return "Active"


def default_digikey_result(part_number: str) -> dict:
    return {
        "source": "DigiKey",
        "searched_part_number": part_number,
        "lifecycle_status": "Unknown",
        "stock_total": 0,
        "supplier_count": 0,
        "lead_time_weeks": None,
        "unit_price": 0.0,
        "has_alternates": False,
        "manufacturer": "",
        "description": "",
        "mouser_part_number": "",
        "manufacturer_part_number": "",
        "digikey_part_number": "",
        "product_detail_url": "",
        "datasheet_url": "",
        "package": "",
        "pin_count": 0,
        "mounting_style": "",
        "architecture": "",
        "channel_count": 0,
        "voltage_range": "",
        "supply_voltage_min": None,
        "supply_voltage_max": None,
        "bandwidth_mhz": None,
        "slew_rate_v_us": None,
    }



def infer_architecture_from_description(description: str) -> str:
    description = str(description).lower()

    if "op amp" in description or "opamp" in description or "operational amplifier" in description:
        return "Operational Amplifier"

    if "comparator" in description:
        return "Comparator"

    if "shift register" in description:
        return "Shift Register"

    if "inverter" in description:
        return "Hex Inverter"

    if "voltage regulator" in description:
        return "Voltage Regulator"

    return ""


def infer_channel_count_from_description(description: str) -> int:
    description = str(description or "").lower()

    if "2 circuit" in description or "dual" in description or "2 channels" in description or "2-channel" in description:
        return 2

    if "4 circuit" in description or "quad" in description or "4 channels" in description or "4-channel" in description:
        return 4

    if "1 circuit" in description or "single" in description or "1 channel" in description or "1-channel" in description:
        return 1

    return 0

def extract_voltage_limits(voltage_text: str):
    import re

    text = str(voltage_text or "").lower().replace(" ", "")

    matches = re.findall(r"(\d+(?:\.\d+)?)v", text)

    if len(matches) >= 2:
        return float(matches[0]), float(matches[1])

    if len(matches) == 1:
        value = float(matches[0])
        return value, value

    return None, None
