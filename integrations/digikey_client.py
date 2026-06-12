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
    url = f"https://api.digikey.com/products/v4/search/{encoded_part_number}/productdetails"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-DIGIKEY-Client-Id": client_id,
        "X-DIGIKEY-Locale-Site": "US",
        "X-DIGIKEY-Locale-Language": "en",
        "X-DIGIKEY-Locale-Currency": "USD",
    }

    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    data = response.json()
    import json

    with open("digikey_raw_response.json", "w") as f:
        json.dump(data, f, indent=2)
    product = data.get("Product", data)

    return normalize_digikey_product(product)


def normalize_digikey_product(product: dict) -> dict:
    import json

    with open("digikey_sample.json", "w") as f:
        json.dump(product, f, indent=2)
    manufacturer = product.get("Manufacturer", {})
    manufacturer_name = (
        manufacturer.get("Name", "")
        if isinstance(manufacturer, dict)
        else str(manufacturer)
    )

    stock_total = product.get("QuantityAvailable", 0) or 0

    return {
        "lifecycle_status": infer_digikey_lifecycle(product),
        "stock_total": int(stock_total),
        "unit_price": extract_digikey_price(product),
        "supplier_count": 1,
        "lead_time_weeks": None,
        "has_alternates": False,
        "source": "DigiKey",
        "manufacturer": manufacturer_name,
        "description": (
            product.get("Description", {}).get("ProductDescription", "")
            if isinstance(product.get("Description"), dict)
            else str(product.get("Description", ""))
        ),
        "mouser_part_number": "",
        "manufacturer_part_number": product.get("ManufacturerProductNumber", ""),
        "product_detail_url": product.get("ProductUrl", ""),
        "package": "",
        "pin_count": 0,
        "mounting_style": "",
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