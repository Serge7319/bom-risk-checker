import requests
import streamlit as st
from urllib.parse import quote


def get_digikey_access_token() -> str:
    client_id = st.secrets.get("DIGIKEY_CLIENT_ID")
    client_secret = st.secrets.get("DIGIKEY_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError(
            "Missing DIGIKEY_CLIENT_ID or DIGIKEY_CLIENT_SECRET in Streamlit secrets"
        )

    url = "https://api.digikey.com/v1/oauth2/token"

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }

    response = requests.post(url, data=data, timeout=15)
    response.raise_for_status()

    return response.json()["access_token"]


def search_digikey_by_part_number(part_number: str) -> dict:
    client_id = st.secrets.get("DIGIKEY_CLIENT_ID")

    if not client_id:
        raise ValueError("Missing DIGIKEY_CLIENT_ID in Streamlit secrets")

    access_token = get_digikey_access_token()

    encoded_part_number = quote(part_number, safe="")
    url = "https://api.digikey.com/products/v4/search/keyword"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-DIGIKEY-Client-Id": client_id,
        "X-DIGIKEY-Locale-Site": "US",
        "X-DIGIKEY-Locale-Language": "en",
        "X-DIGIKEY-Locale-Currency": "USD",
    }

    payload = {
        "Keywords": part_number,
        "Limit": 1,
        "Offset": 0,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=15)
    response.raise_for_status()

    data = response.json()

    products = data.get("Products", [])

    if not products:
        return default_digikey_result(part_number)

    product = products[0]


    return normalize_digikey_product(product)


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
        "product_detail_url": product.get("ProductUrl", ""),

        "package": package,
        "pin_count": pin_count,
        "mounting_style": mounting_style,

        "voltage_range": voltage_range,
        "supply_voltage_min": supply_voltage_min,
        "supply_voltage_max": supply_voltage_max,

        "bandwidth_mhz": bandwidth_mhz,
        "slew_rate_v_us": slew_rate_v_us,
        "input_offset_mv": input_offset_mv,
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
    }


def extract_frequency_mhz(text: str):
    import re

    text = str(text or "")

    match = re.search(r"(\d+(?:\.\d+)?)\s*MHz", text, re.IGNORECASE)
    if match:
        return float(match.group(1))

    match = re.search(r"(\d+(?:\.\d+)?)\s*kHz", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1000

    return None


def extract_slew_rate_v_us(text: str):
    import re

    text = str(text or "")

    match = re.search(r"(\d+(?:\.\d+)?)\s*V\s*/\s*µ?s", text, re.IGNORECASE)
    if match:
        return float(match.group(1))

    return None


def extract_voltage_mv(text: str):
    import re

    text = str(text or "")

    match = re.search(r"(\d+(?:\.\d+)?)\s*mV", text, re.IGNORECASE)
    if match:
        return float(match.group(1))

    match = re.search(r"(\d+(?:\.\d+)?)\s*V", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) * 1000

    return None

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