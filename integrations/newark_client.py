import os
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

    products = (
        data.get("manufacturerPartNumberSearchReturn", {})
        .get("products", [])
    )

    if not products:
        products = (
            data.get("keywordSearchReturn", {})
            .get("products", [])
        )

    if not products:
        return default_newark_result(part_number)

    product = products[0]
    

    return normalize_newark_product(product)


def normalize_newark_product(product: dict) -> dict:
    stock_total = extract_newark_stock(product)
    manufacturer = extract_nested_value(product, ["brandName"]) or ""
    description = extract_nested_value(product, ["displayName"]) or ""

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
        "has_alternates": False,
        "manufacturer": "",
        "description": "",
        "mouser_part_number": "",
        "manufacturer_part_number": "",
        "product_detail_url": "",
    }