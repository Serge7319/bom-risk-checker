import os
import re
from src.parsing.electrical_extractors import (
    extract_frequency_mhz,
    extract_current_na,
    extract_current_ma,
)
import requests
from dotenv import load_dotenv

load_dotenv()


def search_newark_by_part_number(part_number: str) -> dict:
    api_key = os.getenv("NEWARK_API_KEY")

    try:
        import streamlit as st

        api_key = api_key or st.secrets.get("NEWARK_API_KEY")
    except Exception:
        pass

    if not api_key:
        raise ValueError("Missing NEWARK_API_KEY in .env file or Streamlit secrets")

    url = "https://api.element14.com/catalog/products"

    params = {
        "callInfo.apiKey": api_key,
        "callInfo.responseDataFormat": "json",
        "storeInfo.id": "www.newark.com",
        "resultsSettings.offset": 0,
        "resultsSettings.numberOfResults": 1,
        "resultsSettings.responseGroup": "medium",
        "term": f"manuPartNum:{part_number}",
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    data = response.json()

    products = data.get("manufacturerPartNumberSearchReturn", {}).get("products", [])

    if not products:
        products = data.get("keywordSearchReturn", {}).get("products", [])

    if not products:
        return default_newark_result(part_number)

    product = products[0]

    return normalize_newark_product(product)


def normalize_newark_product(product: dict) -> dict:
    stock_total = extract_newark_stock(product)
    manufacturer = extract_nested_value(product, ["brandName"]) or ""
    description = extract_nested_value(product, ["displayName"]) or ""
    architecture = infer_architecture_from_description(description)
    channel_count = infer_channel_count_from_description(description)
    package = extract_package_from_text(description)
    pin_count = extract_pin_count_from_text(description)
    mounting_style = extract_mounting_style_from_text(description)
    voltage_range = extract_voltage_range_from_text(description)
    supply_voltage_min, supply_voltage_max = extract_voltage_limits(voltage_range)
    bandwidth_mhz = extract_bandwidth_mhz_from_text(description)
    slew_rate_v_us = extract_slew_rate_from_text(description)
    input_offset_mv = extract_input_offset_mv_from_text(description)
    quiescent_current_ma = extract_quiescent_current_ma_from_text(description)
    input_bias_na = extract_input_bias_na_from_text(description)
    gbw_mhz = extract_gbw_mhz_from_text(description)

    return {
        "lifecycle_status": infer_newark_lifecycle(product),
        "stock_total": stock_total,
        "supplier_count": 1,
        "lead_time_weeks": extract_newark_lead_time_weeks(product),
        "unit_price": extract_newark_price(product),
        "has_alternates": False,
        "source": "Newark",
        "manufacturer": manufacturer,
        "description": description,
        "mouser_part_number": "",
        "manufacturer_part_number": product.get("translatedManufacturerPartNumber", "")
        or product.get("manufacturerPartNumber", ""),
        "product_detail_url": product.get("productUrl", ""),
        "package": package,
        "pin_count": pin_count,
        "mounting_style": mounting_style,
        "architecture": architecture,
        "channel_count": channel_count,
        "voltage_range": voltage_range,
        "supply_voltage_min": supply_voltage_min,
        "supply_voltage_max": supply_voltage_max,
        "bandwidth_mhz": bandwidth_mhz,
        "slew_rate_v_us": slew_rate_v_us,
        "input_offset_mv": input_offset_mv,
        "quiescent_current_ma": quiescent_current_ma,
        "input_bias_na": input_bias_na,
        "gbw_mhz": gbw_mhz,
    }


def extract_newark_price(product: dict) -> float:
    prices = product.get("prices", [])

    if not prices:
        return 0.0

    try:
        return float(prices[0].get("cost", 0))
    except (ValueError, TypeError, AttributeError):
        return 0.0


def extract_newark_stock(product: dict) -> int:
    stock = product.get("stock", {})

    if isinstance(stock, dict):
        level = stock.get("level", 0)
    else:
        level = 0

    try:
        return int(level)
    except (ValueError, TypeError):
        return 0


def extract_newark_lead_time_weeks(product: dict):
    stock = product.get("stock", {})

    if not isinstance(stock, dict):
        return None

    lead_days = stock.get("leastLeadTime")

    try:
        if lead_days is None:
            return None

        return round(float(lead_days) / 7, 1)

    except (ValueError, TypeError):
        return None


def infer_newark_lifecycle(product: dict) -> str:
    status_fields = [
        product.get("productStatus"),
        product.get("status"),
        product.get("rohsStatusCode"),
    ]

    combined = " ".join(str(field).lower() for field in status_fields if field)

    if "obsolete" in combined:
        return "Obsolete"

    if "not recommended" in combined or "nrnd" in combined:
        return "NRND"

    return "Active"


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


def extract_pin_count_from_text(text: str) -> int:
    text = str(text or "")

    match = re.search(r"\b(\d+)\s*Pins?\b", text, re.IGNORECASE)

    if match:
        return int(match.group(1))

    package = extract_package_from_text(text)
    match = re.search(r"(\d+)$", package)

    if match:
        return int(match.group(1))

    return 0


def extract_mounting_style_from_text(text: str) -> str:
    text = str(text or "").upper()

    if "SMD" in text or "SMT" in text or "SURFACE MOUNT" in text:
        return "SMD"

    if "THROUGH HOLE" in text or "DIP" in text or "PDIP" in text:
        return "Through Hole"

    return ""


def extract_nested_value(data: dict, keys: list):
    for key in keys:
        if key in data:
            return data[key]
    return None


def default_newark_result(part_number: str) -> dict:
    return {
        "source": "Newark",
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
        "product_detail_url": "",
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
        "quiescent_current_ma": None,
        "input_bias_na": None,
        "gbw_mhz": None,
    }

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

def extract_voltage_range_from_text(text: str) -> str:
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*V\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*V",
        text,
        re.IGNORECASE,
    )

    if match:
        return f"{match.group(1)}V to {match.group(2)}V"

    return ""


def extract_voltage_limits(voltage_text: str):
    text = str(voltage_text or "").lower().replace(" ", "")

    matches = re.findall(r"(\d+(?:\.\d+)?)v", text)

    if len(matches) >= 2:
        return float(matches[0]), float(matches[1])

    if len(matches) == 1:
        value = float(matches[0])
        return value, value

    return None, None


def extract_bandwidth_mhz_from_text(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*MHz",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    return None


def extract_slew_rate_from_text(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*V\s*/\s*µs",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    return None


def extract_input_offset_mv_from_text(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*mV",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    return None


def extract_quiescent_current_ma_from_text(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*mA",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    return None


def extract_input_bias_na_from_text(text: str):
    text = str(text or "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*nA",
        text,
        re.IGNORECASE,
    )

    if match:
        return float(match.group(1))

    return None


def extract_gbw_mhz_from_text(text: str):
    return None