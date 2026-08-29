"""Exact-match Octopart component intelligence through the Nexar Supply API."""
from __future__ import annotations

import threading
import time

import requests

from src.secrets import get_secret


TOKEN_URL = "https://identity.nexar.com/connect/token"
GRAPHQL_URL = "https://api.nexar.com/graphql"
REQUEST_TIMEOUT_SECONDS = 15
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, object] = {}

_PART_QUERY = """
query CadivorSupplierSearch($mpn: String!) {
  supSearchMpn(q: $mpn, limit: 5) {
    results {
      part {
        mpn
        manufacturer { name }
        shortDescription
        sellers {
          company { name }
          offers {
            inventoryLevel
            clickUrl
            prices { quantity price currency }
          }
        }
      }
    }
  }
}
"""


def _access_token() -> str:
    client_id = get_secret("NEXAR_CLIENT_ID", required=True)
    client_secret = get_secret("NEXAR_CLIENT_SECRET", required=True)
    with _TOKEN_LOCK:
        if (
            _TOKEN_CACHE.get("client_id") == client_id
            and float(_TOKEN_CACHE.get("expires_at", 0)) > time.monotonic() + 60
        ):
            return str(_TOKEN_CACHE["access_token"])

        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("Octopart authentication returned no usable credential.")
        try:
            expires_in = max(int(payload.get("expires_in", 3600)), 1)
        except (TypeError, ValueError):
            expires_in = 3600
        _TOKEN_CACHE.update(
            client_id=client_id,
            access_token=access_token,
            expires_at=time.monotonic() + expires_in,
        )
        return access_token


def default_octopart_result(part_number: str = "") -> dict:
    return {
        "source": "Octopart",
        "manufacturer_part_number": "",
        "manufacturer": "",
        "description": "",
        "lifecycle_status": "Unknown",
        "stock_total": 0,
        "supplier_count": 0,
        "unit_price": 0.0,
        "lead_time_weeks": None,
        "has_alternates": False,
        "product_detail_url": "",
        "datasheet_url": "",
        "mouser_part_number": "",
        "package": "",
        "pin_count": 0,
        "mounting_style": "",
        "voltage_range": "",
        "architecture": "",
        "channel_count": 0,
        "supply_voltage_min": None,
        "supply_voltage_max": None,
        "octopart_sellers": [],
    }


def _normalize_part(part: dict) -> dict:
    result = default_octopart_result()
    result["manufacturer_part_number"] = str(part.get("mpn") or "").strip()
    manufacturer = part.get("manufacturer") or {}
    result["manufacturer"] = str(manufacturer.get("name") or "") if isinstance(manufacturer, dict) else ""
    result["description"] = str(part.get("shortDescription") or "")

    seller_names = set()
    prices = []
    for seller in part.get("sellers") or []:
        if not isinstance(seller, dict):
            continue
        company = seller.get("company") or {}
        seller_name = str(company.get("name") or "").strip() if isinstance(company, dict) else ""
        if seller_name:
            seller_names.add(seller_name)
        for offer in seller.get("offers") or []:
            if not isinstance(offer, dict):
                continue
            try:
                result["stock_total"] += max(int(offer.get("inventoryLevel") or 0), 0)
            except (TypeError, ValueError):
                pass
            if not result["product_detail_url"]:
                result["product_detail_url"] = str(offer.get("clickUrl") or "")
            for tier in offer.get("prices") or []:
                if not isinstance(tier, dict):
                    continue
                if str(tier.get("currency") or "USD").upper() != "USD":
                    continue
                try:
                    quantity = int(tier.get("quantity") or 1)
                    price = float(tier.get("price"))
                    if price > 0:
                        prices.append((quantity, price))
                except (TypeError, ValueError):
                    continue

    result["octopart_sellers"] = sorted(seller_names)
    result["supplier_count"] = len(seller_names)
    if prices:
        smallest_quantity = min(quantity for quantity, _ in prices)
        result["unit_price"] = min(price for quantity, price in prices if quantity == smallest_quantity)
    return result


def search_octopart_by_part_number(part_number: str) -> dict:
    requested = str(part_number or "").strip()
    if not requested:
        return default_octopart_result()

    response = requests.post(
        GRAPHQL_URL,
        json={"query": _PART_QUERY, "variables": {"mpn": requested}},
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError("Octopart supplier query could not be completed.")

    search = (payload.get("data") or {}).get("supSearchMpn") or {}
    for candidate in search.get("results") or []:
        if not isinstance(candidate, dict):
            continue
        part = candidate.get("part") or {}
        if not isinstance(part, dict):
            continue
        if str(part.get("mpn") or "").strip().casefold() == requested.casefold():
            return _normalize_part(part)
    return default_octopart_result(requested)
