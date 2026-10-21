"""Saved BOM cost fields.

Supplier lookup can return more than one distributor offer. analysis_parts
stores the chosen row's distributor and unit price, and every real offer in
supplier_offers. Savings use only offers for the same MPN whose currency
matches and whose price break applies to the BOM quantity.
"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from numbers import Integral, Real
from typing import Any, Mapping

OPTIONAL_SAVED_PART_COLUMNS = (
    "image_url",
    "product_url",
    "datasheet_url",
    "supplier_offers",
    "unit_price_currency",
    "description",
    "category",
    "supplier_data_verified",
    "sourcing_updated_at",
    "stock_data_sources",
    "stock_data_complete",
    "lifecycle_evidence",
    "lifecycle_conflict",
    "lead_time_source",
    "alternate_search_status",
    "alternate_candidates",
    "supplier_coverage",
)

_MISSING_TEXT = {"", "nan", "none", "null", "no supplier match", "unknown"}

def json_safe_value(value: Any) -> Any:
    """Recursively convert supplier and analysis values to strict JSON values."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None
    if isinstance(value, Mapping):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe_value(item) for item in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        try:
            listed = value.tolist()
        except (TypeError, ValueError):
            listed = value
        if listed is not value:
            return json_safe_value(listed)
    if hasattr(value, "item") and not isinstance(value, (str, bytes, dict)):
        try:
            scalar = value.item()
        except (TypeError, ValueError):
            scalar = value
        if scalar is not value:
            return json_safe_value(scalar)
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, (Real, Decimal)):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            return str(value)
    return str(value)



def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    return str(value).strip().casefold() in _MISSING_TEXT


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in row:
            continue
        value = row.get(key)
        if not _blank(value):
            return value
    return None


def positive_number(value: Any) -> float | None:
    """A recorded number above zero. Zero and blanks are missing defaults."""
    if _blank(value):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def price_number(value: Any) -> float | None:
    """Parse a supplier price amount while keeping currency identity separate.

    A bare ``$`` is not interpreted as USD because several currencies use it.
    """
    if isinstance(value, (Real, Decimal)) and not isinstance(value, bool):
        return positive_number(value)
    if _blank(value):
        return None
    text = str(value).strip().replace("\u00a0", " ").upper()
    match = re.fullmatch(
        r"\s*(?:[A-Z]{3}\s*)?[$€£¥₹₩¢]?\s*"
        r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
        r"\s*(?:[A-Z]{3})?\s*",
        text,
    )
    if not match:
        return None
    return positive_number(match.group("amount").replace(",", ""))


def http_url(value: Any) -> str:
    text = "" if _blank(value) else str(value).strip()
    if text.startswith("https://") or text.startswith("http://"):
        return text
    return ""


def analysis_part_cost_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Fields written on every analysis save, including a later reanalysis.

    Missing supplier, price, quantity, and product URL stay empty or zero.
    Zero is the stored missing-number default. It is not a price or a quantity.
    """
    supplier = _first(row, "Best Source", "primary_supplier", "source", "supplier")
    price = price_number(_first(row, "Unit Price", "unit_price", "price", "best_price"))
    quantity = positive_number(_first(row, "Quantity", "quantity", "qty"))
    product = http_url(
        _first(row, "Product URL", "product_url", "product_detail_url", "source_url")
    )
    datasheet = http_url(
        _first(row, "Datasheet URL", "datasheet_url", "datasheet", "datasheet_link")
    )
    mpn = str(_first(row, "MPN", "mpn", "manufacturer_part_number") or "").strip()
    saved_offers = normalize_saved_offers(
        _offer_list(row.get("Supplier Offers", row.get("supplier_offers"))),
        mpn=mpn,
    )
    raw_price = _first(row, "Unit Price", "unit_price", "price", "best_price")
    price_currency = _currency(
        _first(row, "Unit Price Currency", "unit_price_currency", "currency")
    ) or _currency_from_price_text(raw_price)
    if not price_currency and price is not None and supplier:
        wanted_mpn = _mpn_key(mpn)
        wanted_supplier = str(supplier).strip().casefold()
        matching_currencies = {
            _currency(offer.get("currency"))
            for offer in saved_offers
            if _mpn_key(offer.get("mpn")) == wanted_mpn
            and str(offer.get("distributor") or "").strip().casefold() == wanted_supplier
            and price_number(offer.get("unit_price")) is not None
            and math.isclose(
                float(offer["unit_price"]), price, rel_tol=1e-8, abs_tol=1e-8
            )
            and _currency(offer.get("currency"))
        }
        if len(matching_currencies) == 1:
            price_currency = next(iter(matching_currencies))
    return {
        "primary_supplier": "" if supplier is None else str(supplier).strip(),
        "unit_price": 0 if price is None else price,
        "unit_price_currency": price_currency or None,
        "quantity": 0 if quantity is None else quantity,
        "product_url": product,
        "datasheet_url": datasheet,
        "supplier_offers": saved_offers,
    }


def extended_cost(unit_price: Any, quantity: Any) -> float | None:
    """Extended cost only when both a positive unit price and a BOM quantity exist."""
    price = positive_number(unit_price)
    count = positive_number(quantity)
    if price is None or count is None:
        return None
    return price * count


def _recorded_stock(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and value != value:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return int(number)


def _offer_list(value: Any) -> list[Any]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, float) and value != value:
        return []
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        value = value.tolist()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _mpn_key(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _currency(value: Any) -> str:
    if _blank(value):
        return ""
    text = str(value).strip().upper()
    return text if re.fullmatch(r"[A-Z]{3}", text) else ""


def normalize_currency_code(value: Any) -> str:
    """Return an ISO-style three-letter currency code, or blank if unverified."""
    return _currency(value)


def _currency_from_price_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().upper()
    symbol = r"[$€£¥₹₩¢]?"
    prefix = re.search(rf"^\s*([A-Z]{{3}})(?=\s*{symbol}\s*\d)", text)
    suffix = re.search(r"(?<=\d)\s*([A-Z]{3})\s*$", text)
    match = prefix or suffix
    return _currency(match.group(1)) if match else ""


def _break_quantity(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or _blank(value):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def price_breaks_from_payload(payload: Any, *, currency: str = "") -> list[dict[str, Any]]:
    """Price breaks present on a supplier payload. Missing quantity or currency stay empty."""
    parent_currency = _currency(currency)
    rows = payload if isinstance(payload, list) else [payload]
    breaks: list[dict[str, Any]] = []
    for item in rows:
        if isinstance(item, dict):
            price = None
            for key in ("UnitPrice", "unit_price", "Price", "price", "cost"):
                if key in item:
                    price = price_number(item.get(key))
                    if price is not None:
                        break
            if price is None:
                continue
            quantity = None
            for key in ("BreakQuantity", "Quantity", "quantity", "from", "minimum"):
                if key in item and item.get(key) not in (None, ""):
                    quantity = _break_quantity(item.get(key))
                    break
            row_currency = ""
            for key in ("Currency", "currency"):
                if key in item:
                    row_currency = _currency(item.get(key))
                    break
            if not row_currency:
                raw_price = next(
                    (
                        item.get(key)
                        for key in ("UnitPrice", "unit_price", "Price", "price", "cost")
                        if item.get(key) not in (None, "")
                    ),
                    None,
                )
                row_currency = _currency_from_price_text(raw_price)
            breaks.append(
                {
                    "unit_price": price,
                    "price_break_quantity": quantity,
                    "currency": row_currency or parent_currency,
                }
            )
            continue
        price = price_number(item)
        if price is None:
            continue
        breaks.append(
            {
                "unit_price": price,
                "price_break_quantity": None,
                "currency": parent_currency,
            }
        )
    return breaks


def _offer(
    *,
    mpn: str,
    distributor: Any,
    unit_price: Any,
    currency: Any = "",
    price_break_quantity: Any = None,
    stock: Any = None,
    product_url: Any = "",
    retrieved_at: Any = "",
) -> dict[str, Any] | None:
    name = "" if _blank(distributor) else str(distributor).strip()
    if name.casefold() in _MISSING_TEXT:
        return None
    price = price_number(unit_price)
    if price is None:
        return None
    retrieved = "" if _blank(retrieved_at) else str(retrieved_at).strip()
    return {
        "mpn": str(mpn or "").strip(),
        "distributor": name,
        "unit_price": price,
        "currency": _currency(currency),
        "price_break_quantity": _break_quantity(price_break_quantity),
        "stock": _recorded_stock(stock),
        "product_url": http_url(product_url),
        "retrieved_at": retrieved,
    }


def normalize_saved_offers(offers: Any, *, mpn: str = "") -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    for item in _offer_list(offers):
        if not isinstance(item, dict):
            continue
        offer = _offer(
            mpn=str(item.get("mpn") or mpn or ""),
            distributor=item.get("distributor") or item.get("source") or item.get("supplier"),
            unit_price=item.get("unit_price"),
            currency=item.get("currency"),
            price_break_quantity=item.get("price_break_quantity"),
            stock=item.get("stock", item.get("stock_total")),
            product_url=item.get("product_url") or item.get("product_detail_url"),
            retrieved_at=item.get("retrieved_at"),
        )
        if offer:
            saved.append(offer)
    return saved


def collect_supplier_offers(results: Any, *, mpn: str) -> list[dict[str, Any]]:
    """One saved row per real priced offer. Unpriced supplier rows are omitted."""
    offers: list[dict[str, Any]] = []
    for result in results or []:
        if not isinstance(result, dict):
            continue
        status = str(result.get("provider_status") or "").strip().casefold()
        if status and status not in {"available", "ok"}:
            continue
        retrieved_at = result.get("retrieved_at")
        seller_offers = result.get("seller_offers")
        if isinstance(seller_offers, list) and seller_offers:
            added = normalize_saved_offers(seller_offers, mpn=mpn)
            if not _blank(retrieved_at):
                for offer in added:
                    if not offer["retrieved_at"]:
                        offer["retrieved_at"] = str(retrieved_at).strip()
            offers.extend(added)
            continue
        distributor = result.get("source")
        stock = result.get("stock_total")
        product_url = result.get("product_detail_url") or result.get("source_url")
        breaks = result.get("price_breaks")
        if not isinstance(breaks, list) or not breaks:
            unit_price = price_number(result.get("unit_price"))
            if unit_price is None:
                continue
            breaks = [
                {
                    "unit_price": unit_price,
                    "price_break_quantity": result.get("price_break_quantity"),
                    "currency": (
                        result.get("unit_price_currency")
                        or result.get("currency")
                        or ""
                    ),
                }
            ]
        for item in breaks:
            if not isinstance(item, dict):
                continue
            offer = _offer(
                mpn=mpn,
                distributor=distributor,
                unit_price=item.get("unit_price"),
                currency=(
                    item.get("currency")
                    or result.get("unit_price_currency")
                    or result.get("currency")
                ),
                price_break_quantity=item.get("price_break_quantity"),
                stock=stock,
                product_url=product_url,
                retrieved_at=retrieved_at,
            )
            if offer:
                offers.append(offer)
    return offers


def _same_part(offer: Mapping[str, Any], mpn: str) -> bool:
    offer_mpn = _mpn_key(offer.get("mpn"))
    part_mpn = _mpn_key(mpn)
    if not offer_mpn or not part_mpn:
        return True
    return offer_mpn == part_mpn


def _applicable_offer(offers: list[dict[str, Any]], bom_quantity: float) -> dict[str, Any] | None:
    eligible = [
        offer
        for offer in offers
        if offer.get("price_break_quantity") is not None
        and float(offer["price_break_quantity"]) <= bom_quantity
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda offer: float(offer["price_break_quantity"]))


def distributor_comparison(
    offers: Any,
    *,
    mpn: str,
    bom_quantity: Any,
) -> dict[str, Any]:
    """Savings only for the same MPN, the same currency, and a break that covers the BOM quantity."""
    unavailable = {
        "savings_per_unit": None,
        "message": "A distributor comparison is unavailable.",
        "lower_distributor": "",
        "lower_price": None,
        "higher_distributor": "",
        "higher_price": None,
        "currency": "",
        "break_quantity": None,
    }
    saved = [
        offer
        for offer in normalize_saved_offers(offers, mpn=mpn)
        if _same_part(offer, mpn)
    ]
    if len(saved) < 2:
        return unavailable
    quantity = positive_number(bom_quantity)
    if quantity is None:
        return {
            **unavailable,
            "message": (
                "A distributor comparison is unavailable. "
                "The saved prices do not apply to the BOM quantity."
            ),
        }
    by_currency: dict[str, dict[str, list[dict[str, Any]]]] = {}
    missing_currency = False
    for offer in saved:
        currency = _currency(offer.get("currency"))
        distributor = str(offer.get("distributor") or "")
        if not currency:
            missing_currency = True
            continue
        by_currency.setdefault(currency, {}).setdefault(distributor.casefold(), []).append(offer)
    comparable: list[tuple[str, dict[str, Any]]] = []
    quantity_blocked = False
    for currency, grouped in by_currency.items():
        chosen: list[dict[str, Any]] = []
        for rows in grouped.values():
            applicable = _applicable_offer(rows, quantity)
            if applicable is None:
                if any(row.get("price_break_quantity") is not None for row in rows):
                    quantity_blocked = True
                continue
            chosen.append(applicable)
        if len(chosen) >= 2:
            comparable.append((currency, chosen))
    if not comparable:
        if missing_currency or len(by_currency) != 1:
            if missing_currency or len({_currency(offer.get("currency")) for offer in saved if _currency(offer.get("currency"))}) > 1 or any(not _currency(offer.get("currency")) for offer in saved):
                return {
                    **unavailable,
                    "message": (
                        "A distributor comparison is unavailable. "
                        "The saved offers do not share a currency."
                    ),
                }
        if quantity_blocked:
            return {
                **unavailable,
                "message": (
                    "A distributor comparison is unavailable. "
                    "The saved prices do not apply to the BOM quantity."
                ),
            }
        return unavailable
    currency, chosen = comparable[0]
    ordered = sorted(chosen, key=lambda offer: float(offer["unit_price"]))
    lower = ordered[0]
    higher = ordered[-1]
    if float(lower["unit_price"]) >= float(higher["unit_price"]):
        return {
            **unavailable,
            "message": "No savings. The comparable saved prices are not lower.",
            "currency": currency,
            "lower_distributor": str(lower["distributor"]),
            "lower_price": float(lower["unit_price"]),
            "higher_distributor": str(higher["distributor"]),
            "higher_price": float(higher["unit_price"]),
            "break_quantity": lower.get("price_break_quantity"),
        }
    savings = round(float(higher["unit_price"]) - float(lower["unit_price"]), 6)
    return {
        "savings_per_unit": savings,
        "message": (
            f"Savings of {savings} per unit versus {higher['distributor']} "
            f"at quantity {lower['price_break_quantity']:g} {currency}."
        ),
        "lower_distributor": str(lower["distributor"]),
        "lower_price": float(lower["unit_price"]),
        "higher_distributor": str(higher["distributor"]),
        "higher_price": float(higher["unit_price"]),
        "currency": currency,
        "break_quantity": lower.get("price_break_quantity"),
    }


def omitted_optional_column(error_text: str) -> str:
    """Column to drop when the saved-parts table does not have it yet."""
    folded = str(error_text or "").casefold()
    if "schema cache" not in folded and "column" not in folded:
        return ""
    for column in OPTIONAL_SAVED_PART_COLUMNS:
        if column in folded:
            return column
    return ""


def without_column(records: list[dict[str, Any]], column: str) -> list[dict[str, Any]]:
    return [{key: value for key, value in record.items() if key != column} for record in records]
