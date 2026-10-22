import re

import requests

from integrations.stock_coercion import parse_stock_total
from integrations.pin_count import parse_pin_count_from_text, resolve_pin_count
from src.secrets import get_secret
from src.part_images import normalize_supplier_image_url
from src.saved_bom_cost import price_breaks_from_payload, price_number
from src.normalizer import normalize_part_number


def search_mouser_by_part_number(part_number: str) -> dict:
    requested_key = normalize_part_number(str(part_number or "").strip())
    if not requested_key:
        return default_part_result()
    api_key = get_secret("MOUSER_API_KEY", required=True)

    part_number_payload = {
        "SearchByPartRequest": {
            "mouserPartNumber": str(part_number or "").strip(),
            "partSearchOptions": "Exact",
        }
    }
    parts, exact_errors = _mouser_search_parts(
        "partnumber", part_number_payload, api_key
    )
    exact_part = _exact_mouser_part(parts, requested_key)
    if exact_part:
        return normalize_mouser_part(exact_part)

    # SearchByPart is useful when the query is already a Mouser order number,
    # but some MPNs (including DHT11) are indexed only by the keyword endpoint.
    # Keep the same strict MPN validation after this broader search so a family
    # neighbor can never lend its stock, lifecycle, or datasheet to this part.
    keyword_payload = {
        "SearchByKeywordRequest": {
            "keyword": str(part_number or "").strip(),
            "records": 50,
            "startingRecord": 0,
        }
    }
    keyword_parts, keyword_errors = _mouser_search_parts(
        "keyword", keyword_payload, api_key
    )
    exact_part = _exact_mouser_part(keyword_parts, requested_key)
    if exact_part:
        return normalize_mouser_part(exact_part)

    if exact_errors or keyword_errors:
        raise RuntimeError("Mouser did not return a usable search response.")
    return default_part_result()


def search_mouser_catalog_candidates(
    part_number: str,
    *,
    limit: int = 12,
    include_family_search: bool = True,
) -> list[dict]:
    """Return Mouser catalog leads without implying a substitute relationship.

    The full query can reveal package/order-code variants; an optional short
    family query broadens discovery. Every result remains a catalog match and
    must pass the normal engineering comparison before approval.
    """
    requested = str(part_number or "").strip()
    if not requested:
        return []
    api_key = get_secret("MOUSER_API_KEY", required=True)
    family = _catalog_family_search_term(requested) if include_family_search else ""
    terms = [requested]
    if family and family.casefold() != requested.casefold():
        terms.append(family)

    candidates: list[dict] = []
    seen: set[str] = set()
    had_error = False
    retrieved_at = _utc_now_iso()
    for term in terms:
        payload = {
            "SearchByKeywordRequest": {
                "keyword": term,
                "records": max(1, min(int(limit), 25)),
                "startingRecord": 0,
            }
        }
        parts, failed = _mouser_search_parts("keyword", payload, api_key)
        had_error = had_error or failed
        for part in parts:
            mpn = str(part.get("ManufacturerPartNumber") or "").strip()
            key = normalize_part_number(mpn)
            if not mpn or not key or key == normalize_part_number(requested) or key in seen:
                continue
            seen.add(key)
            normalized = normalize_mouser_part(part)
            category = _mouser_category_text(part)
            candidates.append({
                **normalized,
                "source": "Mouser",
                "evidence_type": "Distributor family search match" if family and term.casefold() == family.casefold() else "Distributor catalog match",
                "discovery_scope": "family_search" if family and term.casefold() == family.casefold() else "catalog_search",
                "discovery_query": term,
                "primary_category": category,
                "manufacturer_part_number": mpn,
                "retrieval_status": "ok",
                "retrieved_at": retrieved_at,
                "substitute_type": "Similar",
                "supplier_relationship_evidence": [],
            })
    if had_error and not candidates:
        raise RuntimeError("Mouser catalog candidate search did not return a usable response.")
    return candidates


def _catalog_family_search_term(part_number: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", str(part_number or "").upper())
    if compact.startswith(("DHT11", "DHT22", "DHT12")):
        return "DHT"
    for pattern in (
        r"^([A-Z]{2,}\d{3,})",
        r"^([A-Z]{2,}\d{2,}[A-Z]+\d{2,})",
        r"^(\d{1,2}[A-Z]{1,}\d{2,})",
    ):
        match = re.match(pattern, compact)
        if match and len(match.group(1)) >= 5 and match.group(1) != compact:
            return match.group(1)
    return ""


def _mouser_category_text(part: dict) -> str:
    values = []
    for key in ("PrimaryCategory", "ProductCategory", "Category", "CategoryName"):
        value = part.get(key)
        if isinstance(value, dict):
            value = value.get("Name") or value.get("CategoryName") or value.get("DisplayName")
        if isinstance(value, (list, tuple)):
            values.extend(str(item).strip() for item in value if str(item).strip())
        elif value:
            values.append(str(value).strip())
    return " / ".join(dict.fromkeys(value for value in values if value))


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mouser_search_parts(
    endpoint: str,
    payload: dict,
    api_key: str,
) -> tuple[list[dict], bool]:
    """Return catalog rows and whether the distributor request failed."""
    url = f"https://api.mouser.com/api/v1/search/{endpoint}?apiKey={api_key}"
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception:
        # A rejected part-number mode should not prevent the keyword lookup.
        return [], True

    if not isinstance(data, dict):
        return [], True
    search_results = data.get("SearchResults") or {}
    if not isinstance(search_results, dict):
        return [], True
    parts = [
        row for row in (search_results.get("Parts") or [])
        if isinstance(row, dict)
    ]
    errors = data.get("Errors") or []
    return parts, bool(errors and not parts)


def _exact_mouser_part(parts: list[dict], requested_key: str) -> dict | None:
    if not requested_key:
        return None
    for field in ("ManufacturerPartNumber", "MouserPartNumber"):
        for part in parts:
            returned_key = normalize_part_number(
                str(part.get(field) or "").strip()
            )
            if returned_key and returned_key == requested_key:
                return part
    return None


def normalize_mouser_part(part: dict) -> dict:
    availability = part.get("Availability", "")
    stock_total = extract_stock_number(availability)

    package = extract_mouser_attribute(
        part,
        ["Package / Case", "Package", "Supplier Device Package"],
    )

    if not package:
        package = extract_package_from_text(part.get("Description", ""))

    mounting_style = extract_mouser_attribute(
        part,
        ["Mounting Style", "Mounting Type"],
    )

    pin_count_text = extract_mouser_attribute(
        part,
        [
            "Number of Pins",
            "Pin Count",
            "Number of Terminations",
            "Number of Balls",
            "Ball Count",
        ],
    )
    pin_count = resolve_pin_count(
        explicit_count_text=pin_count_text,
        package_text=package,
    )

    voltage_text = extract_mouser_attribute(
        part,
        [
            "Supply Voltage",
            "Operating Supply Voltage",
            "Operating Voltage",
            "Voltage - Supply",
            "Vcc",
        ],
    )

    supply_voltage_min, supply_voltage_max = extract_voltage_limits(voltage_text)

    description = part.get("Description", "")
    architecture = infer_architecture_from_description(description)
    channel_count = infer_channel_count_from_description(description)

    bandwidth_text = extract_mouser_attribute(
        part,
        ["Gain Bandwidth Product", "Bandwidth", "GBW"],
    )
    bandwidth_mhz = extract_frequency_mhz(bandwidth_text)

    slew_rate_text = extract_mouser_attribute(part, ["Slew Rate"])
    slew_rate_v_us = extract_slew_rate_v_us(slew_rate_text)

    input_offset_text = extract_mouser_attribute(
        part,
        ["Input Offset Voltage", "Voltage - Input Offset"],
    )
    input_offset_mv = extract_voltage_mv(input_offset_text)

    input_bias_text = extract_mouser_attribute(
        part,
        ["Input Bias Current", "Current - Input Bias"],
    )
    input_bias_na = extract_current_na(input_bias_text)

    quiescent_current_text = extract_mouser_attribute(
        part,
        ["Supply Current", "Current - Supply", "Quiescent Current"],
    )
    quiescent_current_ma = extract_current_ma(quiescent_current_text)

    gbw_mhz = None

    from src.component_family_profiles import mouser_parametric_map

    parametric = {}
    skip_keys = {
        "package",
        "pin_count",
        "mounting_style",
        "voltage_range",
        "lifecycle_status",
    }
    for key, names in mouser_parametric_map().items():
        if key in skip_keys:
            continue
        value = extract_mouser_attribute(part, names)
        if value:
            parametric[key] = value
    temperature_range = extract_mouser_attribute(
        part, ["Operating Temperature", "Temperature Range"]
    )
    if temperature_range:
        parametric.setdefault("temperature_range", temperature_range)

    return {
        "lifecycle_status": infer_lifecycle_status(part),
        "stock_total": stock_total,
        "unit_price": extract_mouser_price(part),
        "currency": _mouser_recorded_currency(part),
        "unit_price_currency": _mouser_recorded_currency(part),
        "price_breaks": price_breaks_from_payload(part.get("PriceBreaks")),
        "supplier_count": 1,
        "lead_time_weeks": None,
        "has_alternates": False,
        "source": "Mouser",
        "manufacturer": part.get("Manufacturer", ""),
        "description": description,
        "architecture": architecture,
        "mouser_part_number": part.get("MouserPartNumber", ""),
        "manufacturer_part_number": part.get("ManufacturerPartNumber", ""),
        "product_detail_url": part.get("ProductDetailUrl", ""),
        "image_url": normalize_supplier_image_url(
            part.get("ImagePath") or part.get("ImageURL") or part.get("ImageUrl"),
            provider="Mouser",
        ),
        "datasheet_url": part.get("DataSheetUrl", ""),
        "package": package,
        "pin_count": pin_count,
        "mounting_style": mounting_style,
        "channel_count": channel_count,
        "voltage_range": voltage_text,
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


def default_part_result() -> dict:
    return {
        "lifecycle_status": "Unknown",
        "stock_total": None,
        "unit_price": 0.0,
        "supplier_count": 0,
        "lead_time_weeks": None,
        "has_alternates": False,
        "source": "Mouser",
        "manufacturer": "",
        "description": "",
        "mouser_part_number": "",
        "manufacturer_part_number": "",
        "product_detail_url": "",
        "image_url": "",
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
        "input_offset_mv": None,
        "input_bias_na": None,
        "quiescent_current_ma": None,
        "gbw_mhz": None,
    }


def extract_mouser_attribute(part: dict, target_names: list) -> str:
    """Extract a Mouser attribute using exact match, then longest safe alias."""
    attributes = part.get("ProductAttributes", []) or []
    normalized_targets = [str(target or "").strip() for target in target_names if str(target or "").strip()]
    if not normalized_targets:
        return ""

    for target in normalized_targets:
        target_key = target.casefold()
        for attribute in attributes:
            name = str(attribute.get("AttributeName", "")).strip()
            if name.casefold() == target_key:
                return str(attribute.get("AttributeValue", "")).strip()

    generic = {"type", "function", "series", "family", "technology"}
    best_value = ""
    best_score = 0
    for attribute in attributes:
        name = str(attribute.get("AttributeName", "")).strip()
        name_key = name.casefold()
        value = str(attribute.get("AttributeValue", "")).strip()
        for target in normalized_targets:
            target_key = target.casefold()
            if target_key in generic:
                continue
            if target_key in name_key and len(target_key) > best_score:
                best_value = value
                best_score = len(target_key)
    return best_value

def extract_pin_count(text: str) -> int:
    """Parse pin count; bare integers allowed for explicit Number of Pins fields."""
    return parse_pin_count_from_text(text, allow_bare_integer=True)

def extract_voltage_limits(voltage_text: str):
    text = str(voltage_text or "").lower().replace(" ", "")

    matches = re.findall(r"(\d+(?:\.\d+)?)v", text)

    if len(matches) >= 2:
        return float(matches[0]), float(matches[1])

    if len(matches) == 1:
        value = float(matches[0])
        return value, value

    return None, None


def extract_stock_number(availability: str) -> int | None:
    """Return on-hand stock only when Mouser text explicitly reports it."""
    return parse_stock_total(availability)


def extract_mouser_price(part: dict) -> float:
    price_breaks = part.get("PriceBreaks", [])

    if not price_breaks:
        return 0.0

    first_break = price_breaks[0]

    return price_number(first_break.get("Price", "")) or 0.0


def _mouser_recorded_currency(part: dict) -> str:
    """Return the currency attached to the selected (first) Mouser price break."""
    price_breaks = part.get("PriceBreaks") or []
    if not isinstance(price_breaks, list) or not price_breaks:
        return ""
    first_break = price_breaks[0]
    if not isinstance(first_break, dict):
        return ""
    return str(first_break.get("Currency") or first_break.get("currency") or "").strip()


def infer_lifecycle_status(part: dict) -> str:
    lifecycle = part.get("LifecycleStatus")

    if lifecycle is not None and str(lifecycle).strip():
        return str(lifecycle).strip()

    description = str(part.get("Description", "")).lower()
    availability = str(part.get("Availability", "")).lower()
    suggested_replacement = str(part.get("SuggestedReplacement", "")).lower()

    if "obsolete" in description or "obsolete" in availability:
        return "Obsolete"

    if "not recommended" in description or "nrnd" in description:
        return "NRND"

    if suggested_replacement:
        return "Replacement Suggested"

    # Product listing and on-hand stock do not establish manufacturer lifecycle.
    return "Unknown"



def infer_architecture_from_description(description: str) -> str:
    description = str(description).lower()

    if "op amp" in description or "operational amplifier" in description:
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

    if "dual" in description or "2 channels" in description or "2-channel" in description:
        return 2

    if "quad" in description or "4 channels" in description or "4-channel" in description:
        return 4

    if "single" in description or "1 channel" in description or "1-channel" in description:
        return 1

    return 0

def extract_package_from_text(text: str) -> str:
    text = str(text or "").upper()

    package_patterns = [
        r"\bPDIP[-\s]?(\d+)\b",
        r"\bDIP[-\s]?(\d+)\b",
        r"\bSOIC[-\s]?(\d+)\b",
        r"\bSOP[-\s]?(\d+)\b",
        r"\bTSSOP[-\s]?(\d+)\b",
        r"\bSOT[-\s]?223\b",
        r"\bTO[-\s]?220\b",
    ]

    for pattern in package_patterns:
        match = re.search(pattern, text)

        if match:
            matched_text = match.group(0)

            if "SOT" in matched_text:
                return "SOT-223"

            if "TO" in matched_text:
                return "TO-220"

            number = match.group(1)
            package_name = re.sub(r"[^A-Z]", "", matched_text)

            if "PDIP" in package_name:
                return f"PDIP-{number}"
            if "DIP" in package_name:
                return f"DIP-{number}"
            if "SOIC" in package_name:
                return f"SOIC-{number}"
            if "SOP" in package_name:
                return f"SOP-{number}"
            if "TSSOP" in package_name:
                return f"TSSOP-{number}"

    return ""

def extract_frequency_mhz(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*MHz",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*kHz",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1)) / 1000

    return None

def extract_slew_rate_v_us(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*V\s*/\s*(?:µ|u)s",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    return None

def extract_voltage_mv(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*mV",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*µV",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1)) / 1000

    return None

def extract_current_na(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*nA",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:µ|u)A",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1)) * 1000

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*mA",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1)) * 1_000_000

    return None

def extract_current_ma(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*mA",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:µ|u)A",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1)) / 1000

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*nA",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1)) / 1_000_000

    return None
