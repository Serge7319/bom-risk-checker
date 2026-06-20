import re

import requests
import streamlit as st


def search_mouser_by_part_number(part_number: str) -> dict:
    
    api_key = st.secrets.get("MOUSER_API_KEY")

    if not api_key:
        raise ValueError("Missing MOUSER_API_KEY in Streamlit secrets")

    url = f"https://api.mouser.com/api/v1/search/partnumber?apiKey={api_key}"

    payload = {
        "SearchByPartRequest": {
            "mouserPartNumber": part_number,
            "partSearchOptions": "string",
        }
    }

    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()

    data = response.json()

    search_results = data.get("SearchResults") or {}
    parts = search_results.get("Parts") or []

    if not parts:
        return default_part_result()

    part = parts[0]
    st.write(part.get("ProductAttributes", []))
    

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
        ["Number of Pins", "Pin Count", "Package / Case", "Package"],
    )

    pin_count = extract_pin_count(pin_count_text)

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

    
    st.write("Voltage text:", voltage_text)
    st.write("Voltage min:", supply_voltage_min)
    st.write("Voltage max:", supply_voltage_max)

    description = part.get("Description", "")
    architecture = infer_architecture_from_description(description)
    channel_count = infer_channel_count_from_description(description)

    return {
        "lifecycle_status": infer_lifecycle_status(part),
        "stock_total": stock_total,
        "unit_price": extract_mouser_price(part),
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
        "package": package,
        "pin_count": pin_count,
        "mounting_style": mounting_style,
        "channel_count": channel_count,
        "voltage_range": voltage_text,
        "supply_voltage_min": supply_voltage_min,
        "supply_voltage_max": supply_voltage_max,
    }


def default_part_result() -> dict:
    return {
        "lifecycle_status": "Unknown",
        "stock_total": 0,
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
        "package": "",
        "pin_count": 0,
        "mounting_style": "",
        "architecture": "",
        "channel_count": 0,
        "voltage_range": "",
        "supply_voltage_min": None,
        "supply_voltage_max": None,
    }


def extract_mouser_attribute(part: dict, target_names: list) -> str:
    attributes = part.get("ProductAttributes", [])

    for attribute in attributes:
        name = str(attribute.get("AttributeName", "")).lower()
        value = str(attribute.get("AttributeValue", "")).strip()

        for target in target_names:
            if target.lower() in name:
                return value

    return ""


def extract_pin_count(text: str) -> int:
    match = re.search(r"\b(\d+)\b", str(text))

    if match:
        return int(match.group(1))

    return 0

def extract_voltage_limits(voltage_text: str):
    text = str(voltage_text or "").lower().replace(" ", "")

    matches = re.findall(r"(\d+(?:\.\d+)?)v", text)

    if len(matches) >= 2:
        return float(matches[0]), float(matches[1])

    if len(matches) == 1:
        value = float(matches[0])
        return value, value

    return None, None


def extract_stock_number(availability: str) -> int:
    digits = ""

    for char in availability:
        if char.isdigit():
            digits += char
        elif digits:
            break

    return int(digits) if digits else 0


def extract_mouser_price(part: dict) -> float:
    price_breaks = part.get("PriceBreaks", [])

    if not price_breaks:
        return 0.0

    first_break = price_breaks[0]

    price = (
        str(first_break.get("Price", ""))
        .replace("$", "")
        .replace(",", "")
        .strip()
    )

    try:
        return float(price)
    except ValueError:
        return 0.0


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

    return "Active"



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