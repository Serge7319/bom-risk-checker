"""Exact-match Octopart component intelligence through the Nexar Supply API."""
from __future__ import annotations

import re
import threading
import time
from typing import Any

import requests

from integrations.stock_coercion import coerce_stock_total

from src.secrets import get_secret


TOKEN_URL = "https://identity.nexar.com/connect/token"
GRAPHQL_URL = "https://api.nexar.com/graphql"
REQUEST_TIMEOUT_SECONDS = 15
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, object] = {}

# Subreasons for structured Alternative Finder diagnostics (never include secrets).
SUBREASON_GRAPHQL_ERRORS = "graphql_errors"
SUBREASON_EMPTY_RESPONSE = "empty_response"
SUBREASON_MALFORMED_RESPONSE = "malformed_response"
SUBREASON_MISSING_EXPECTED_DATA = "missing_expected_data"
SUBREASON_SCHEMA_MISMATCH = "schema_mismatch"
SUBREASON_ZERO_RESULTS = "zero_results"
SUBREASON_OK = "ok"

# Align with current Nexar Supply docs: search-level country/currency, offer
# prices as quantity+price (currency is selected on the query, not per tier).
_PART_QUERY = """
query CadivorSupplierSearch($mpn: String!) {
  supSearchMpn(q: $mpn, limit: 5, country: "US", currency: "USD") {
    hits
    results {
      part {
        mpn
        name
        manufacturer { name }
        sellers {
          company { name }
          offers {
            inventoryLevel
            clickUrl
            prices { quantity price }
          }
        }
      }
    }
  }
}
"""


class OctopartResponseError(RuntimeError):
    """Configured Octopart/Nexar call failed with a classified response subreason."""

    def __init__(self, message: str, *, subreason: str):
        super().__init__(message)
        self.subreason = str(subreason or SUBREASON_MALFORMED_RESPONSE).strip()


def _nexar_secret(primary_name: str, legacy_name: str) -> str:
    """Resolve the current Nexar key, then the pre-standardization alias."""
    value = get_secret(primary_name, default=None)
    if value:
        return str(value)
    return str(get_secret(legacy_name, required=True))


def _access_token() -> str:
    # Some Railway deployments were configured before the Nexar naming was
    # standardized. Continue accepting those variable names so a working
    # Octopart credential is not silently disconnected by a code upgrade.
    client_id = _nexar_secret("NEXAR_CLIENT_ID", "OCTOPART_CLIENT_ID")
    client_secret = _nexar_secret("NEXAR_CLIENT_SECRET", "OCTOPART_CLIENT_SECRET")
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
        try:
            payload = response.json()
        except ValueError as exc:
            raise OctopartResponseError(
                "Octopart authentication returned a malformed token payload.",
                subreason=SUBREASON_MALFORMED_RESPONSE,
            ) from exc
        if not isinstance(payload, dict):
            raise OctopartResponseError(
                "Octopart authentication returned a malformed token payload.",
                subreason=SUBREASON_MALFORMED_RESPONSE,
            )
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
        "octopart_subreason": "",
        "octopart_hits": 0,
    }


def _normalize_part(part: dict) -> dict:
    result = default_octopart_result()
    result["manufacturer_part_number"] = str(part.get("mpn") or "").strip()
    manufacturer = part.get("manufacturer") or {}
    result["manufacturer"] = (
        str(manufacturer.get("name") or "") if isinstance(manufacturer, dict) else ""
    )
    result["description"] = str(part.get("name") or part.get("shortDescription") or "")

    seller_names = set()
    prices = []
    for seller in part.get("sellers") or []:
        if not isinstance(seller, dict):
            continue
        company = seller.get("company") or {}
        seller_name = (
            str(company.get("name") or "").strip() if isinstance(company, dict) else ""
        )
        if seller_name:
            seller_names.add(seller_name)
        for offer in seller.get("offers") or []:
            if not isinstance(offer, dict):
                continue
            try:
                result["stock_total"] += coerce_stock_total(offer.get("inventoryLevel"))
            except (TypeError, ValueError):
                pass
            if not result["product_detail_url"]:
                result["product_detail_url"] = str(offer.get("clickUrl") or "")
            for tier in offer.get("prices") or []:
                if not isinstance(tier, dict):
                    continue
                # Search-level currency:"USD" already scopes prices; accept tiers as-is.
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
        result["unit_price"] = min(
            price for quantity, price in prices if quantity == smallest_quantity
        )
    result["octopart_subreason"] = SUBREASON_OK
    return result


def _graphql_error_subreason(errors: list[Any]) -> str:
    snippets: list[str] = []
    for item in errors:
        if isinstance(item, dict):
            snippets.append(str(item.get("message") or ""))
        else:
            snippets.append(str(item or ""))
    joined = " ".join(snippets).casefold()
    if (
        "cannot query field" in joined
        or "unknown field" in joined
        or "field undefined" in joined
        or "is not defined by type" in joined
    ):
        return SUBREASON_SCHEMA_MISMATCH
    return SUBREASON_GRAPHQL_ERRORS


def classify_nexar_graphql_payload(payload: Any) -> dict[str, Any]:
    """Classify a Nexar GraphQL JSON body without logging secrets or bodies."""
    if payload is None or payload == "":
        return {
            "subreason": SUBREASON_EMPTY_RESPONSE,
            "hits": 0,
            "results": [],
            "usable": False,
        }
    if not isinstance(payload, dict):
        return {
            "subreason": SUBREASON_MALFORMED_RESPONSE,
            "hits": 0,
            "results": [],
            "usable": False,
        }
    if not payload:
        return {
            "subreason": SUBREASON_EMPTY_RESPONSE,
            "hits": 0,
            "results": [],
            "usable": False,
        }

    errors = payload.get("errors")
    has_errors = isinstance(errors, list) and bool(errors)
    data = payload.get("data")

    if has_errors and data in (None, {}):
        return {
            "subreason": _graphql_error_subreason(errors),
            "hits": 0,
            "results": [],
            "usable": False,
        }

    if data is None and not has_errors:
        return {
            "subreason": SUBREASON_EMPTY_RESPONSE,
            "hits": 0,
            "results": [],
            "usable": False,
        }

    if not isinstance(data, dict):
        return {
            "subreason": SUBREASON_MALFORMED_RESPONSE,
            "hits": 0,
            "results": [],
            "usable": False,
        }

    if "supSearchMpn" not in data:
        # Successful auth/HTTP but unexpected GraphQL shape.
        if has_errors:
            return {
                "subreason": _graphql_error_subreason(errors if isinstance(errors, list) else []),
                "hits": 0,
                "results": [],
                "usable": False,
            }
        return {
            "subreason": SUBREASON_MISSING_EXPECTED_DATA,
            "hits": 0,
            "results": [],
            "usable": False,
        }

    search = data.get("supSearchMpn")
    if search is None:
        return {
            "subreason": SUBREASON_ZERO_RESULTS,
            "hits": 0,
            "results": [],
            "usable": True,
        }
    if not isinstance(search, dict):
        return {
            "subreason": SUBREASON_MALFORMED_RESPONSE,
            "hits": 0,
            "results": [],
            "usable": False,
        }

    results = search.get("results")
    if results is None:
        results = []
    if not isinstance(results, list):
        return {
            "subreason": SUBREASON_MALFORMED_RESPONSE,
            "hits": 0,
            "results": [],
            "usable": False,
        }

    try:
        hits = int(search.get("hits") if search.get("hits") is not None else len(results))
    except (TypeError, ValueError):
        hits = len(results)

    if not results:
        # GraphQL errors with empty results still count as provider GraphQL failure.
        if has_errors:
            return {
                "subreason": _graphql_error_subreason(errors if isinstance(errors, list) else []),
                "hits": hits,
                "results": [],
                "usable": False,
            }
        return {
            "subreason": SUBREASON_ZERO_RESULTS,
            "hits": hits,
            "results": [],
            "usable": True,
        }

    return {
        "subreason": SUBREASON_OK,
        "hits": hits,
        "results": results,
        "usable": True,
    }


def _exact_match_part(requested: str, results: list[Any]) -> dict | None:
    requested_key = re.sub(r"[^a-z0-9]", "", requested.casefold())
    for candidate in results:
        if not isinstance(candidate, dict):
            continue
        part = candidate.get("part") or {}
        if not isinstance(part, dict):
            continue
        candidate_key = re.sub(
            r"[^a-z0-9]", "", str(part.get("mpn") or "").strip().casefold()
        )
        if candidate_key and candidate_key == requested_key:
            return part
    return None


def search_octopart_by_part_number(part_number: str) -> dict:
    requested = str(part_number or "").strip()
    if not requested:
        empty = default_octopart_result()
        empty["octopart_subreason"] = SUBREASON_ZERO_RESULTS
        return empty

    response = requests.post(
        GRAPHQL_URL,
        json={"query": _PART_QUERY, "variables": {"mpn": requested}},
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise OctopartResponseError(
            "Octopart supplier query returned a malformed response.",
            subreason=SUBREASON_MALFORMED_RESPONSE,
        ) from exc

    classified = classify_nexar_graphql_payload(payload)
    subreason = str(classified.get("subreason") or SUBREASON_MALFORMED_RESPONSE)
    if not classified.get("usable"):
        raise OctopartResponseError(
            "Octopart supplier query could not be completed.",
            subreason=subreason,
        )

    results = list(classified.get("results") or [])
    hits = int(classified.get("hits") or 0)
    matched = _exact_match_part(requested, results)
    if matched is not None:
        normalized = _normalize_part(matched)
        normalized["octopart_hits"] = hits
        return normalized

    # Valid GraphQL data with no exact MPN match is a completed zero-result search.
    empty = default_octopart_result(requested)
    empty["octopart_subreason"] = SUBREASON_ZERO_RESULTS
    empty["octopart_hits"] = hits
    return empty
