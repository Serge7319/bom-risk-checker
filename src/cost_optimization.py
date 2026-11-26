"""Cadivor Milestone 21.0 — Cost Optimization.

Uses saved BOM component records to identify priced spend, purchasing
leverage, missing cost data, and estimated cost-reduction opportunities. Part
photos are optional and appear when saved records contain a trusted image URL.
"""
from __future__ import annotations

from collections import defaultdict
import html
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system import cadivor_engineering_dataframe
from src.part_images import part_image_markup, part_image_source


def _verified_stock(row: Dict[str, Any], mpn: str) -> int | None:
    """Reconcile stock only from exact, timestamped authorized supplier rows."""
    from datetime import datetime
    from integrations.stock_coercion import parse_stock_total
    from src.normalizer import normalize_part_number

    observations = _first(row, "stock_evidence", "Stock Evidence", default=[]) or []
    if isinstance(observations, dict):
        observations = [observations]
    trusted = []
    authorized = {"digikey", "digikeyelectronics", "mouser", "mouserelectronics", "newark", "element14", "farnell", "nexarsupply"}
    for item in observations if isinstance(observations, (list, tuple)) else []:
        if not isinstance(item, dict):
            continue
        source = "".join(ch for ch in str(item.get("source") or item.get("supplier") or "").casefold() if ch.isalnum())
        try:
            retrieved = datetime.fromisoformat(str(item.get("retrieved_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if (
            source not in authorized
            or not item.get("mpn")
            or normalize_part_number(str(item.get("mpn"))) != normalize_part_number(mpn)
            or retrieved.tzinfo is None
        ):
            continue
        quantity = parse_stock_total(item.get("stock", item.get("stock_total")))
        if quantity is not None:
            trusted.append(int(quantity))
    reported = parse_stock_total(_first(row, "stock_available", "Stock Available", "Total Market Stock", "total_market_stock", "stock"))
    if trusted and reported is not None and sum(trusted) == reported:
        return int(reported)
    return None


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_money(value: Any, currency: str = "") -> str:
    amount = _number(value, 0.0)
    code = _text(currency).upper()
    if code == "USD":
        return "$" + format(amount, ",.2f")
    return f"{code or 'Currency not recorded'} {amount:,.2f}"


def _first(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def _select_user_entered_quote(
    quotes: Iterable[Dict[str, Any]],
    *,
    mpn: str,
    quantity: int,
    preferred_currency: str = "",
) -> Dict[str, Any] | None:
    """Choose an applicable uploaded price without treating it as verified."""
    from datetime import date
    from src.normalizer import normalize_part_number

    wanted_mpn = normalize_part_number(mpn)
    today = date.today().isoformat()
    candidates: list[Dict[str, Any]] = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        if normalize_part_number(str(quote.get("requested_mpn") or "")) != wanted_mpn:
            continue
        if normalize_part_number(str(quote.get("offered_mpn") or "")) != wanted_mpn:
            continue
        if quote.get("identity_status") not in {"exact_part", "manufacturer_unconfirmed"}:
            continue
        valid_until = str(quote.get("valid_until") or "").strip()
        if valid_until and valid_until < today:
            continue
        minimum_order = _optional_number(quote.get("minimum_order_quantity"))
        if minimum_order is not None and quantity < minimum_order:
            continue
        pack_quantity = _optional_number(quote.get("pack_quantity"))
        if pack_quantity is not None and (pack_quantity <= 0 or quantity % int(pack_quantity) != 0):
            continue
        breaks = quote.get("price_breaks") if isinstance(quote.get("price_breaks"), list) else []
        applicable_breaks: list[tuple[int, float]] = []
        for price_break in breaks:
            if not isinstance(price_break, dict):
                continue
            try:
                threshold = int(float(price_break.get("quantity")))
                price = float(price_break.get("unit_price"))
            except (TypeError, ValueError, OverflowError):
                continue
            if threshold > 0 and threshold <= quantity and price > 0:
                applicable_breaks.append((threshold, price))
        if not applicable_breaks:
            try:
                threshold = int(float(quote.get("price_break_quantity") or 1))
                price = float(quote.get("unit_price"))
            except (TypeError, ValueError, OverflowError):
                continue
            if threshold <= 0 or threshold > quantity or price <= 0:
                continue
            applicable_breaks.append((threshold, price))
        threshold, price = max(applicable_breaks, key=lambda item: item[0])
        currency = str(quote.get("currency") or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            continue
        candidates.append({
            **quote,
            "mpn": str(quote.get("offered_mpn") or mpn),
            "distributor": str(quote.get("supplier") or "User price sheet").strip(),
            "unit_price": price,
            "currency": currency,
            "price_break_quantity": threshold,
            "retrieved_at": str(quote.get("created_at") or ""),
            "product_url": str(quote.get("source_url") or ""),
            "source_kind": "user-entered",
        })
    if not candidates:
        return None
    preferred = str(preferred_currency or "").strip().upper()
    currencies = {candidate["currency"] for candidate in candidates}
    if preferred in currencies:
        candidates = [candidate for candidate in candidates if candidate["currency"] == preferred]
    elif len(currencies) > 1:
        # Never silently choose or convert between currencies.
        return None
    candidates.sort(key=lambda candidate: (float(candidate["unit_price"]), str(candidate.get("created_at") or "")))
    return candidates[0]


def _latest_user_quote_records(quotes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the latest saved quote set for each supplier and currency.

    Rows from one spreadsheet import share a batch id, so all of its price
    tiers survive together while a newer upload supersedes that supplier's
    older sheet rows. Separately recorded suppliers remain comparable.
    """
    groups: Dict[tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for index, quote in enumerate(quotes or []):
        if not isinstance(quote, dict):
            continue
        supplier = _text(quote.get("supplier"), "User price sheet").casefold()
        currency = _text(quote.get("currency")).upper()
        batch = _text(quote.get("import_batch_id"))
        group_id = f"batch:{batch}" if batch else f"record:{_text(quote.get('quote_id') or quote.get('id'), str(index))}"
        groups[(supplier, currency, group_id)].append(quote)

    latest_by_source: Dict[tuple[str, str], tuple[str, List[Dict[str, Any]]]] = {}
    for (supplier, currency, _), records in groups.items():
        created = max((_text(row.get("created_at")) for row in records), default="")
        key = (supplier, currency)
        current = latest_by_source.get(key)
        if current is None or created > current[0]:
            latest_by_source[key] = (created, records)
        elif created == current[0]:
            latest_by_source[key] = (created, current[1] + records)
    return [record for _, records in latest_by_source.values() for record in records]


def build_cost_optimization(
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    build_quantity: int = 100,
    target_unit_cost: float | None = None,
    user_entered_quotes: Iterable[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    analyses = list(analyses or [])
    parts = list(parts or [])
    build_qty = max(1, int(build_quantity or 1))
    target = _optional_number(target_unit_cost)

    analysis_lookup = {
        _text(row.get("id")): _text(
            row.get("project_name") or row.get("name") or row.get("filename"),
            "Saved BOM",
        )
        for row in analyses
    }

    from src.saved_bom_cost import normalize_saved_offers, select_supplier_offer
    from src.normalizer import normalize_part_number

    quote_lookup: Dict[tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for quote in user_entered_quotes or []:
        if not isinstance(quote, dict):
            continue
        quote_lookup[(
            _text(quote.get("analysis_id")),
            normalize_part_number(str(quote.get("requested_mpn") or "")),
            _text(quote.get("requested_manufacturer")).casefold(),
        )].append(quote)

    def identity(part_number: str, manufacturer: str, index: int) -> tuple[str, str]:
        normalized_mpn = normalize_part_number(part_number)
        if not normalized_mpn or normalized_mpn in {"UNKNOWN", "N/A"}:
            normalized_mpn = f"__row_{index}"
        return normalized_mpn, manufacturer.casefold()

    demand_by_identity: Dict[tuple[str, str], int] = defaultdict(int)
    for index, row in enumerate(parts):
        part_number = _text(_first(row, "mpn", "MPN", "part_number"), "Unknown")
        manufacturer = _text(row.get("manufacturer"), "Unknown")
        qty = max(0, int(_number(_first(
            row, "effective_quantity", "Effective Quantity", "quantity", "Quantity", "qty", "required_quantity"
        ), 0)))
        demand_by_identity[identity(part_number, manufacturer, index)] += qty * build_qty

    normalized: List[Dict[str, Any]] = []
    for index, row in enumerate(parts):
        analysis_id = _text(row.get("analysis_id"))
        raw_qty = _number(_first(
            row, "effective_quantity", "Effective Quantity", "quantity", "Quantity", "qty", "required_quantity"
        ), 0)
        qty = max(0, int(raw_qty))
        part_number = _text(_first(row, "mpn", "MPN", "part_number"), "Unknown")
        manufacturer = _text(row.get("manufacturer"), "Unknown")
        order_qty = demand_by_identity[identity(part_number, manufacturer, index)]
        raw_offers = _first(row, "supplier_offers", "Supplier Offers", default=[])
        offers = normalize_saved_offers(raw_offers, mpn=part_number)

        all_verified_offers = []
        for offer in offers:
            verified = select_supplier_offer(
                [offer],
                mpn=part_number,
                supplier=str(offer.get("distributor") or ""),
                unit_price=offer.get("unit_price"),
                currency=offer.get("currency"),
                quantity=None,
            )
            if verified:
                all_verified_offers.append(verified)

        quantity_offers = []
        for offer in all_verified_offers:
            applicable = select_supplier_offer(
                [offer],
                mpn=part_number,
                supplier=str(offer.get("distributor") or ""),
                unit_price=offer.get("unit_price"),
                currency=offer.get("currency"),
                quantity=order_qty if order_qty > 0 else None,
            )
            if applicable and applicable.get("quantity_break_applies") is True:
                quantity_offers.append(applicable)

        selected_supplier = _text(_first(
            row, "price_source", "Price Source", "primary_supplier", "supplier", "best_source"
        ))
        raw_price = _first(row, "unit_price", "Unit Price", "price", "best_price")
        raw_currency = _text(_first(
            row, "unit_price_currency", "Unit Price Currency", "currency", "Currency"
        )).upper()
        current_quote = select_supplier_offer(
            quantity_offers,
            mpn=part_number,
            supplier=selected_supplier,
            unit_price=raw_price if raw_price not in (None, "") else None,
            currency=raw_currency,
            quantity=order_qty if order_qty > 0 else None,
        )
        if current_quote is None and not selected_supplier:
            current_quote = min(
                quantity_offers,
                key=lambda offer: float(offer["unit_price"]),
                default=None,
            )

        report_manufacturer = _text(row.get("manufacturer")).casefold()
        part_user_quotes = _latest_user_quote_records(
            quote_lookup.get((analysis_id, normalize_part_number(part_number), report_manufacturer), [])
        )
        manual_quote = _select_user_entered_quote(
            part_user_quotes,
            mpn=part_number,
            quantity=order_qty,
            preferred_currency=raw_currency,
        )
        if manual_quote:
            # A user-uploaded sheet is explicit price input for this saved BOM.
            # Keep its provenance separate from API-verified supplier offers.
            current_quote = manual_quote

        unit_price = float(current_quote["unit_price"]) if current_quote else 0.0
        currency = str(current_quote.get("currency") or "") if current_quote else ""
        verified_supplier = str(current_quote.get("distributor") or "") if current_quote else ""
        price_evidence = (
            (
                "User-entered price · manufacturer unconfirmed"
                if current_quote.get("identity_status") == "manufacturer_unconfirmed"
                else "User-entered price · supplier not independently verified"
            )
            if current_quote and current_quote.get("source_kind") == "user-entered"
            else "Authorized supplier API snapshot" if current_quote else "Not recorded"
        )
        suppliers = len({
            str(offer.get("distributor") or "").casefold()
            for offer in quantity_offers
        })
        stock_value = _verified_stock(row, part_number)
        stock = int(stock_value) if stock_value is not None else None
        from src.risk_engine import calculate_risk

        scored_risk = calculate_risk(row).get("risk_score")
        risk_score = int(scored_risk) if scored_risk is not None else None
        description = _text(
            _first(row, "description", "Description", "part_description", "product_description"),
            "",
        )
        category = _text(
            _first(row, "category_raw", "category", "part_category", "component_category", "device_type"),
            "",
        )
        image_context = {"description": description, "category": category, "manufacturer": manufacturer}
        for key in (
            "package", "package_type", "package type", "package_case",
            "case_package", "case", "mounting_type", "mounting type",
            "mount_type", "mounting", "through_hole", "is_through_hole",
            "tht", "is_tht", "surface_mount", "is_surface_mount", "smd", "smt",
            "architecture", "device_type",
        ):
            value = row.get(key)
            if value is not None and str(value).strip():
                image_context[key] = value
        image_url = part_image_source(
            _first(row, "image_url", "Image URL", "photo_url"),
            part_number,
            size=48,
            part=image_context,
        )
        normalized.append({
            "Analysis ID": analysis_id,
            "Project": analysis_lookup.get(analysis_id, _text(row.get("project_name"), "Saved BOM")),
            "Part Number": part_number,
            "Description": description,
            "Component Category": category,
            "Image URL": image_url,
            "Image Context": image_context,
            "Manufacturer": manufacturer,
            "Supplier": verified_supplier or "Not verified",
            "Price Source": verified_supplier or "",
            "Price Retrieved At": (
                str(current_quote.get("retrieved_at") or "")
                if current_quote and current_quote.get("source_kind") != "user-entered" else ""
            ),
            "Price Date": (
                str(current_quote.get("price_date") or "")
                if current_quote and current_quote.get("source_kind") == "user-entered"
                else str(current_quote.get("retrieved_at") or "") if current_quote else ""
            ),
            "Price Recorded At": (
                str(current_quote.get("created_at") or current_quote.get("retrieved_at") or "")
                if current_quote else ""
            ),
            "Price Evidence": price_evidence,
            "Price Source URL": str(current_quote.get("product_url") or "") if current_quote else "",
            "_User Entered Quotes": part_user_quotes,
            "Quantity per Build": qty,
            "Order Quantity": order_qty,
            "Unit Price": unit_price if current_quote else None,
            "Currency": currency,
            "Extended Cost per Build": unit_price * qty if current_quote else None,
            "Extended Cost at Build Quantity": unit_price * qty * build_qty if current_quote else None,
            "Supplier Sources": suppliers,
            "Available Stock": stock,
            "Lifecycle": _text(row.get("lifecycle_status"), "Unknown"),
            "Risk Score": risk_score,
            "Verified Offers": quantity_offers,
            "All Verified Offers": all_verified_offers,
            "_Identity": identity(part_number, manufacturer, index),
        })

    priced = [
        row for row in normalized
        if row["Unit Price"] is not None and row["Unit Price"] > 0 and row["Currency"]
    ]
    missing_price = [row for row in normalized if row not in priced]
    currencies = {row["Currency"] for row in priced}
    priced_per_build = {
        code: sum(float(row["Extended Cost per Build"] or 0) for row in priced if row["Currency"] == code)
        for code in sorted(currencies)
    }
    priced_run_cost = {
        code: total * build_qty for code, total in priced_per_build.items()
    }
    current_cost_per_build = next(iter(priced_per_build.values())) if len(priced_per_build) == 1 else None
    complete_cost_per_build = (
        current_cost_per_build
        if len(priced) == len(normalized) and len(currencies) == 1
        else None
    )
    production_run_cost = (
        next(iter(priced_run_cost.values()))
        if len(priced) == len(normalized) and len(currencies) == 1
        else None
    )
    pricing_coverage = round((len(priced) / max(1, len(normalized))) * 100) if normalized else 0

    grouped: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        grouped[row["_Identity"]].append(row)

    opportunities: List[Dict[str, Any]] = []
    for rows in grouped.values():
        reference = rows[0]
        required_qty = sum(int(row["Quantity per Build"]) for row in rows) * build_qty
        if required_qty <= 0:
            continue
        valid_rows = [row for row in rows if row["Unit Price"] is not None and row["Currency"]]
        if not valid_rows:
            continue
        quote_sources = {str(row["Supplier"]).casefold() for row in valid_rows if row["Supplier"] != "Not verified"}
        quote_currencies = {str(row["Currency"]) for row in valid_rows}
        if len(quote_sources) != 1 or len(quote_currencies) != 1 or len(valid_rows) != len(rows):
            continue
        current_sources = {str(row["Supplier"]).casefold() for row in valid_rows}
        current_currencies = {str(row["Currency"]).upper() for row in valid_rows}
        # A blended supplier/currency baseline is ambiguous. Do not imply a
        # savings opportunity until those same-part BOM lines share one basis.
        if len(current_sources) != 1 or len(current_currencies) != 1:
            continue
        current_source = valid_rows[0]["Supplier"]
        current_currency = valid_rows[0]["Currency"]
        current_offers = [offer for row in rows for offer in row["All Verified Offers"]]
        risk_scores = [int(row["Risk Score"]) for row in rows if row["Risk Score"] is not None]
        risk_score = max(risk_scores) if risk_scores else None
        lifecycle_values = list(dict.fromkeys(str(row.get("Lifecycle") or "Unknown") for row in rows))
        lifecycle_risk = any(
            any(term in value.casefold() for term in ("obsolete", "replacement", "nrnd", "not recommended", "eol"))
            for value in lifecycle_values
        )
        stock_values = [int(row["Available Stock"]) for row in rows if row["Available Stock"] is not None]
        recorded_stock = min(stock_values) if stock_values else None
        quote_source_count = max((int(row["Supplier Sources"] or 0) for row in rows), default=0)
        risk_context_parts = []
        if lifecycle_risk:
            risk_context_parts.append("Lifecycle: " + ", ".join(lifecycle_values))
        elif any(value.casefold() in {"", "unknown", "not reported", "n/a"} for value in lifecycle_values):
            risk_context_parts.append("Lifecycle status unknown")
        else:
            risk_context_parts.append("Recorded lifecycle: " + ", ".join(lifecycle_values))
        if recorded_stock is None:
            risk_context_parts.append("Stock availability not verified")
        elif recorded_stock < required_qty:
            risk_context_parts.append(f"Recorded stock {recorded_stock:,} is below order quantity {required_qty:,}")
        else:
            risk_context_parts.append(f"Recorded stock {recorded_stock:,} covers order quantity")
        risk_context_parts.append(f"{quote_source_count} current authorized price source(s) recorded")
        if risk_score is not None:
            risk_context_parts.append(f"Saved BOM risk score {risk_score}")
        manual_current = any(str(row.get("Price Evidence") or "").startswith("User-entered") for row in rows)
        if manual_current:
            risk_context_parts.append(
                "Cost baseline includes a user-entered price; Cadivor has not independently verified it"
            )
        risk_context = "; ".join(risk_context_parts)
        if lifecycle_risk or (risk_score is not None and risk_score >= 70):
            risk_label = "High risk"
        elif (
            recorded_stock is None
            or risk_score is None
            or any(value.casefold() in {"", "unknown", "not reported", "n/a"} for value in lifecycle_values)
        ):
            risk_label = "Needs verification"
        elif risk_score >= 40 or recorded_stock < required_qty:
            risk_label = "Review"
        else:
            risk_label = "No elevated signal recorded"
        def opportunity_risk(offer: Dict[str, Any], purchase_qty: int) -> tuple[str, str]:
            """Add exact-source inventory/lead-time evidence to the BOM risk context."""
            offer_stock = _optional_number(offer.get("stock"))
            offer_lead = _optional_number(offer.get("lead_time_weeks"))
            details = [risk_context]
            if offer_stock is None:
                details.append(f"{offer.get('distributor') or current_source} stock not recorded at this price snapshot")
            elif offer_stock < purchase_qty:
                details.append(
                    f"{offer.get('distributor') or current_source} reported stock "
                    f"{int(offer_stock):,} is below purchase quantity {purchase_qty:,}"
                )
            else:
                details.append(
                    f"{offer.get('distributor') or current_source} reported stock "
                    f"{int(offer_stock):,} covers purchase quantity {purchase_qty:,}"
                )
            if offer_lead is not None:
                details.append(f"Saved supplier lead time: {offer_lead:g} weeks")
            if manual_current:
                label = "Needs verification"
            elif lifecycle_risk or (risk_score is not None and risk_score >= 70):
                label = "High risk"
            elif risk_label == "Needs verification" or offer_stock is None:
                label = "Needs verification"
            elif risk_label == "Review" or offer_stock < purchase_qty:
                label = "Review"
            else:
                label = "No elevated signal recorded"
            return label, "; ".join(details)

        source_offer = select_supplier_offer(
            current_offers,
            mpn=reference["Part Number"],
            supplier=current_source,
            currency=current_currency,
            quantity=required_qty,
        )
        if not source_offer and manual_current:
            source_offer = next(
                (
                    offer for row in rows
                    for offer in [
                        _select_user_entered_quote(
                            quote_lookup.get((str(row.get("Analysis ID") or ""), normalize_part_number(str(row.get("Part Number") or "")), str(row.get("Manufacturer") or "").casefold()), []),
                            mpn=str(row.get("Part Number") or ""),
                            quantity=required_qty,
                            preferred_currency=current_currency,
                        )
                    ]
                    if offer and str(offer.get("distributor") or "").casefold() == current_source.casefold()
                ),
                None,
            )
        if not source_offer:
            continue
        baseline_price = float(source_offer["unit_price"])
        baseline_total = baseline_price * required_qty
        seen = set()

        offers_by_source: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for offer in current_offers:
            offers_by_source[str(offer.get("distributor") or "")].append(offer)

        for supplier, supplier_offers in offers_by_source.items():
            if supplier.casefold() == current_source.casefold():
                continue
            alternate_quote = select_supplier_offer(
                supplier_offers,
                mpn=reference["Part Number"],
                supplier=supplier,
                currency=current_currency,
                quantity=required_qty,
            )
            if not alternate_quote or float(alternate_quote["unit_price"]) >= baseline_price:
                continue
            savings = baseline_total - float(alternate_quote["unit_price"]) * required_qty
            if savings <= 0:
                continue
            alternate_risk_label, alternate_risk_context = opportunity_risk(alternate_quote, required_qty)
            key = ("source", supplier.casefold(), float(alternate_quote["unit_price"]))
            if key in seen:
                continue
            seen.add(key)
            opportunities.append({
                "Part Number": reference["Part Number"],
                "Analysis ID": reference["Analysis ID"],
                "Project": reference["Project"],
                "Description": reference["Description"],
                "Component Category": reference["Component Category"],
                "Image URL": reference["Image URL"],
                "Image Context": reference["Image Context"],
                "Manufacturer": reference["Manufacturer"],
                "Category": "Cheaper authorized source",
                "Supplier": supplier,
                "Current Supplier": current_source,
                "Projects": 1,
                "Units per Build": sum(int(row["Quantity per Build"]) for row in rows),
                "Required Order Quantity": required_qty,
                "Current Unit Price": baseline_price,
                "Estimated Target Price": float(alternate_quote["unit_price"]),
                "Estimated Run Savings": savings,
                "Savings Rate": (baseline_price - float(alternate_quote["unit_price"])) / baseline_price if baseline_price else 0,
                "Currency": current_currency,
                "Current Price Retrieved At": source_offer.get("retrieved_at"),
                "Current Price Evidence": "User-entered price · not independently verified" if manual_current else "Authorized supplier API snapshot",
                "Target Price Retrieved At": alternate_quote.get("retrieved_at"),
                "Target Price Evidence": "Authorized supplier API snapshot",
                "Price Source URL": alternate_quote.get("product_url"),
                "Extra Quantity": 0,
                "Risk Score": risk_score,
                "Risk Label": alternate_risk_label,
                "Risk Context": alternate_risk_context,
                "Reason": (
                    f"{supplier} has a current exact-MPN saved price of {current_currency} "
                    f"{float(alternate_quote['unit_price']):,.4g} at order quantity {required_qty:,}, "
                    f"versus {current_source} at {current_currency} {baseline_price:,.4g}. "
                    "Confirm the supplier quote, freight, tax, MOQ, and availability before acting."
                ),
            })

        # A spreadsheet can contain one row per price tier (using
        # minimum_quantity). Expose a volume break from those records too, but
        # label it Needs verification because the uploaded source is not an
        # independently checked distributor quote.
        if manual_current:
            seen_manual_quotes: set[str] = set()
            manual_tiers: dict[tuple[int, float, str], Dict[str, Any]] = {}
            for row in rows:
                for quote in row.get("_User Entered Quotes") or []:
                    if not isinstance(quote, dict):
                        continue
                    quote_key = str(quote.get("quote_id") or quote.get("id") or "")
                    if quote_key and quote_key in seen_manual_quotes:
                        continue
                    if quote_key:
                        seen_manual_quotes.add(quote_key)
                    if str(quote.get("supplier") or "").casefold() != current_source.casefold():
                        continue
                    if str(quote.get("currency") or "").upper() != current_currency:
                        continue
                    breaks = quote.get("price_breaks") if isinstance(quote.get("price_breaks"), list) else []
                    if not breaks:
                        breaks = [{
                            "quantity": quote.get("price_break_quantity") or 1,
                            "unit_price": quote.get("unit_price"),
                        }]
                    for price_break in breaks:
                        if not isinstance(price_break, dict):
                            continue
                        try:
                            threshold = int(float(price_break.get("quantity")))
                            tier_price = float(price_break.get("unit_price"))
                        except (TypeError, ValueError, OverflowError):
                            continue
                        if threshold <= required_qty or tier_price <= 0 or tier_price >= baseline_price:
                            continue
                        applicable = _select_user_entered_quote(
                            [quote],
                            mpn=reference["Part Number"],
                            quantity=threshold,
                            preferred_currency=current_currency,
                        )
                        if not applicable or int(applicable.get("price_break_quantity") or 0) != threshold:
                            continue
                        tier_price = float(applicable["unit_price"])
                        if tier_price >= baseline_price:
                            continue
                        manual_tiers[(threshold, tier_price, current_source.casefold())] = applicable

            for (purchase_qty, tier_price, _), offer in manual_tiers.items():
                savings = baseline_total - tier_price * purchase_qty
                if savings <= 0:
                    continue
                label, context = opportunity_risk(offer, purchase_qty)
                opportunities.append({
                    "Part Number": reference["Part Number"],
                    "Analysis ID": reference["Analysis ID"],
                    "Project": reference["Project"],
                    "Description": reference["Description"],
                    "Component Category": reference["Component Category"],
                    "Image URL": reference["Image URL"],
                    "Image Context": reference["Image Context"],
                    "Manufacturer": reference["Manufacturer"],
                    "Category": "Price break",
                    "Supplier": current_source,
                    "Current Supplier": current_source,
                    "Projects": 1,
                    "Units per Build": sum(int(row["Quantity per Build"]) for row in rows),
                    "Required Order Quantity": required_qty,
                    "Current Unit Price": baseline_price,
                    "Estimated Target Price": tier_price,
                    "Estimated Run Savings": savings,
                    "Savings Rate": (baseline_price - tier_price) / baseline_price if baseline_price else 0,
                    "Currency": current_currency,
                    "Current Price Retrieved At": source_offer.get("retrieved_at"),
                    "Current Price Evidence": "User-entered price · not independently verified",
                    "Target Price Retrieved At": offer.get("retrieved_at"),
                    "Target Price Evidence": "User-entered price · not independently verified",
                    "Price Source URL": offer.get("product_url"),
                    "Extra Quantity": purchase_qty - required_qty,
                    "Recommended Purchase Quantity": purchase_qty,
                    "Risk Score": risk_score,
                    "Risk Label": label,
                    "Risk Context": context,
                    "Reason": (
                        f"The imported sheet records {current_currency} {tier_price:,.4g} per unit "
                        f"from {current_source} at a minimum quantity of {purchase_qty:,}. "
                        "This estimated net saving is based on user-entered data and has not been verified."
                    ),
                })

        for offer in current_offers:
            if str(offer.get("distributor") or "").casefold() != current_source.casefold():
                continue
            if str(offer.get("currency") or "").upper() != current_currency:
                continue
            threshold = offer.get("price_break_quantity")
            if threshold is None:
                continue
            try:
                purchase_qty = int(float(threshold))
                tier_price = float(offer.get("unit_price") or 0)
            except (TypeError, ValueError):
                continue
            if purchase_qty <= required_qty or tier_price <= 0 or tier_price >= baseline_price:
                continue
            savings = baseline_total - tier_price * purchase_qty
            if savings <= 0:
                continue
            break_risk_label, break_risk_context = opportunity_risk(offer, purchase_qty)
            key = ("break", current_source.casefold(), purchase_qty, tier_price)
            if key in seen:
                continue
            seen.add(key)
            opportunities.append({
                "Part Number": reference["Part Number"],
                "Analysis ID": reference["Analysis ID"],
                "Project": reference["Project"],
                "Description": reference["Description"],
                "Component Category": reference["Component Category"],
                "Image URL": reference["Image URL"],
                "Image Context": reference["Image Context"],
                "Manufacturer": reference["Manufacturer"],
                "Category": "Price break",
                "Supplier": current_source,
                "Current Supplier": current_source,
                "Projects": 1,
                "Units per Build": sum(int(row["Quantity per Build"]) for row in rows),
                "Required Order Quantity": required_qty,
                "Current Unit Price": baseline_price,
                "Estimated Target Price": tier_price,
                "Estimated Run Savings": savings,
                "Savings Rate": (baseline_price - tier_price) / baseline_price if baseline_price else 0,
                "Currency": current_currency,
                "Current Price Retrieved At": source_offer.get("retrieved_at"),
                "Current Price Evidence": "User-entered price · not independently verified" if manual_current else "Authorized supplier API snapshot",
                "Target Price Retrieved At": offer.get("retrieved_at"),
                "Target Price Evidence": "Authorized supplier API snapshot",
                "Price Source URL": offer.get("product_url"),
                "Extra Quantity": purchase_qty - required_qty,
                "Recommended Purchase Quantity": purchase_qty,
                "Risk Score": risk_score,
                "Risk Label": break_risk_label,
                "Risk Context": break_risk_context,
                "Reason": (
                    f"Ordering {purchase_qty:,} units from {current_source} reaches a saved exact-MPN "
                    f"price break of {current_currency} {tier_price:,.4g}; after the extra "
                    f"{purchase_qty - required_qty:,} units, estimated net savings are "
                    f"{current_currency} {savings:,.2f}. Confirm the break and inventory with the supplier."
                ),
            })

    opportunities.sort(key=lambda row: (-row["Estimated Run Savings"], row["Part Number"]))
    best_by_part: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in opportunities:
        key = identity(str(row["Part Number"]), str(row.get("Manufacturer") or ""), len(best_by_part))
        if key not in best_by_part:
            best_by_part[key] = row
    savings_currencies = {row["Currency"] for row in best_by_part.values()}
    estimated_savings = (
        sum(float(row["Estimated Run Savings"]) for row in best_by_part.values())
        if best_by_part and len(savings_currencies) == 1
        else 0.0 if not best_by_part
        else None
    )
    estimated_optimized_cost = (
        max(0.0, production_run_cost - estimated_savings)
        if production_run_cost is not None and estimated_savings is not None
        and (not savings_currencies or savings_currencies == currencies)
        else None
    )

    drivers: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for row in priced:
        key = (row["Part Number"].casefold(), row["Manufacturer"].casefold(), row["Currency"])
        driver = drivers.get(key)
        if driver is None:
            driver = {
                **{name: value for name, value in row.items() if name not in {"Verified Offers", "All Verified Offers", "_Identity", "_User Entered Quotes"}},
                "Quantity per Build": 0,
                "Extended Cost per Build": 0.0,
                "Extended Cost at Build Quantity": 0.0,
                "Supplier Sources": 0,
            }
            drivers[key] = driver
        driver["Quantity per Build"] += int(row["Quantity per Build"])
        driver["Extended Cost per Build"] += float(row["Extended Cost per Build"] or 0)
        driver["Extended Cost at Build Quantity"] += float(row["Extended Cost at Build Quantity"] or 0)
        driver["Supplier Sources"] = max(driver["Supplier Sources"], int(row["Supplier Sources"] or 0))
    top_cost_parts = []
    for currency_code in sorted(currencies):
        top_cost_parts.extend(sorted(
            [row for row in drivers.values() if row["Currency"] == currency_code],
            key=lambda row: -float(row["Extended Cost at Build Quantity"] or 0),
        )[:5])

    sourcing_risk_cost = sum(
        float(row["Extended Cost at Build Quantity"] or 0)
        for row in priced
        if row["Supplier Sources"] <= 1
        or (row["Available Stock"] is not None and row["Available Stock"] <= 0)
    ) if len(currencies) == 1 else None

    recommendations = []
    if opportunities:
        top = opportunities[0]
        recommendations.append(
            f"Review {top['Part Number']}: the best estimated saving is "
            f"{_format_money(top['Estimated Run Savings'], top['Currency'])} at the stated build quantity."
        )
    if missing_price:
        recommendations.append(
            f"Add current pricing for {len(missing_price)} component line(s); the subtotal is partial until these are priced."
        )
    if sourcing_risk_cost is not None and sourcing_risk_cost > 0:
        recommendations.append(
            f"{_format_money(sourcing_risk_cost, next(iter(currencies)))} of priced production spend is attached to "
            "single-source or no-stock records."
        )
    if not recommendations:
        recommendations.append("No verified price reduction is available from the saved supplier evidence.")

    return {
        "rows": [{key: value for key, value in row.items() if not key.startswith("_")} for row in normalized],
        "priced_rows": [{key: value for key, value in row.items() if not key.startswith("_")} for row in priced],
        "missing_price_rows": [{key: value for key, value in row.items() if not key.startswith("_")} for row in missing_price],
        "opportunities": opportunities,
        "top_cost_parts": top_cost_parts,
        "build_quantity": build_qty,
        "target_unit_cost": target,
        "target_cost_gap": (
            current_cost_per_build - target
            if target is not None and complete_cost_per_build is not None
            else None
        ),
        "current_cost_per_build": current_cost_per_build,
        "complete_cost_per_build": complete_cost_per_build,
        "production_run_cost": production_run_cost,
        "estimated_savings": estimated_savings,
        "estimated_optimized_cost": estimated_optimized_cost,
        "currency": next(iter(currencies)) if len(currencies) == 1 else "",
        "currencies": sorted(currencies),
        "priced_subtotals_per_build": priced_per_build,
        "priced_subtotals_at_build_quantity": priced_run_cost,
        "mixed_currency_totals": priced_run_cost,
        "pricing_coverage": pricing_coverage,
        "priced_component_count": len(priced),
        "user_entered_price_count": sum(
            1 for row in priced if str(row.get("Price Evidence") or "").startswith("User-entered")
        ),
        "missing_component_count": len(missing_price),
        "sourcing_risk_cost": sourcing_risk_cost,
        "recommendations": recommendations[:4],
        "project_count": len(analyses),
        "component_count": len(normalized),
    }


def _optional_number(value: Any) -> float | None:
    if value is None or str(value).strip().casefold() in {"", "nan", "none", "<na>"}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if pd.notna(number) else None


def _css() -> None:
    st.markdown(
        """
        <style id="cadivor-cost-optimization-22" data-cadivor-layout-style="true">
          .st-key-cost_optimization_workspace{width:100%;max-width:1500px;margin:0 auto;box-sizing:border-box}
          .cv21-page{width:100%;max-width:1500px;margin:0 auto;box-sizing:border-box}
          .cv21-heading{display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,250px);align-items:end;gap:24px;margin:0 0 20px}
          .cv21-eyebrow{margin:0 0 8px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.08em;text-transform:uppercase}
          .cv21-title{margin:0 0 8px;color:#0f172a;font-size:34px;line-height:1.12;font-weight:900;letter-spacing:-.04em}
          .cv21-copy{margin:0;color:#52647a;font-size:14px;font-weight:600;line-height:1.55;max-width:900px}
          .cv21-kpi-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:22px 0 28px}
          .cv21-kpi{display:flex;align-items:center;gap:16px;min-height:132px;padding:20px 21px;border:1px solid #d9e8fb;border-radius:18px;background:linear-gradient(135deg,#f5faff 0%,#edf6ff 100%);box-sizing:border-box}
          .cv21-kpi-icon{display:inline-flex;align-items:center;justify-content:center;width:58px;height:58px;flex:0 0 58px;border-radius:50%;background:#dbeafe;color:#2563eb}
          .cv21-kpi-icon svg{display:block;width:26px;height:26px}
          .cv21-kpi-label{color:#475569;font-size:13px;font-weight:750;line-height:1.35}
          .cv21-kpi-value{margin-top:8px;color:#0f172a;font-size:30px;font-weight:900;line-height:1.05;letter-spacing:-.04em}
          .cv21-kpi-note{margin-top:7px;color:#64748b;font-size:12px;font-weight:600;line-height:1.4}
          .cv21-section-heading{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:0 0 12px}
          .cv21-section-title{margin:0;color:#0f172a;font-size:21px;font-weight:850;letter-spacing:-.025em;line-height:1.25}
          .cv21-section-subtitle{margin:5px 0 0;color:#64748b;font-size:13px;font-weight:600;line-height:1.45}
          .cv21-table-card{width:100%;border:1px solid #dbe3ef;border-radius:16px;background:#fff;overflow:hidden;box-shadow:0 6px 20px rgba(15,23,42,.035);box-sizing:border-box}
          .cv21-table-scroll{width:100%;overflow-x:auto}
          .cv21-table{width:100%;min-width:900px;border-collapse:separate;border-spacing:0;color:#0f172a}
          .cv21-table th{height:42px;padding:10px 12px;background:#f1f5f9;border-bottom:1px solid #dce4ee;color:#64748b;text-align:left;font-size:10px;font-weight:850;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap}
          .cv21-table td{height:64px;padding:10px 12px;border-bottom:1px solid #e5eaf1;vertical-align:middle;text-align:left;font-size:12px;font-weight:620;line-height:1.35}
          .cv21-table tbody tr:last-child td{border-bottom:0}
          .cv21-table tbody tr:hover{background:#f8fbff}
          .cv21-rank{width:42px;color:#64748b;font-weight:800}
          .cv21-component{display:flex;align-items:center;gap:12px;min-width:210px}
          .cv21-component .cv-part-photo{width:48px;height:48px;flex:0 0 48px;margin:0;border-radius:10px}
          .cv21-component .cv-part-photo__placeholder svg{width:30px;height:30px}
          .cv21-component-copy{min-width:0}
          .cv21-component-name{overflow:hidden;color:#0f172a;font-size:13px;font-weight:800;text-overflow:ellipsis;white-space:nowrap}
          .cv21-component-mpn{margin-top:3px;color:#64748b;font-size:11px;font-weight:600;line-height:1.3;overflow-wrap:anywhere}
          .cv21-price{white-space:nowrap;font-variant-numeric:tabular-nums;font-weight:750}
          .cv21-path-title{color:#0f172a;font-size:12px;font-weight:780}
          .cv21-path-copy{display:-webkit-box;max-width:260px;margin-top:4px;overflow:hidden;color:#64748b;font-size:11px;font-weight:550;line-height:1.35;-webkit-box-orient:vertical;-webkit-line-clamp:2}
          .cv21-savings-amount{display:flex;align-items:center;justify-content:space-between;gap:8px;color:#0f172a;font-size:12px;font-weight:850;font-variant-numeric:tabular-nums;white-space:nowrap}
          .cv21-savings-rate{color:#64748b;font-size:10px;font-weight:700}
          .cv21-progress{width:100%;height:7px;margin-top:7px;border-radius:999px;background:#e6eef8;overflow:hidden}
          .cv21-progress span{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#3b82f6,#2563eb)}
          .cv21-review-pill{display:inline-flex;align-items:center;justify-content:center;padding:6px 9px;border:1px solid #fde68a;border-radius:8px;background:#fffbeb;color:#a16207;font-size:10px;font-weight:800;white-space:nowrap}
          .cv21-review-cell{display:flex;flex-direction:column;align-items:flex-start;gap:6px}
          .cv21-row-action{color:#2563eb;font-size:11px;font-weight:750;text-decoration:none;white-space:nowrap}
          .cv21-row-action:hover{text-decoration:underline;text-underline-offset:3px}
          .cv21-empty{margin:0;padding:24px;border:1px dashed #cbd5e1;border-radius:14px;background:#f8fafc;color:#64748b;font-size:13px;font-weight:620;line-height:1.5}
          .cv21-data-note{margin:12px 0 18px;color:#64748b;font-size:12px;font-weight:600;line-height:1.5}
          .cv21-detail-heading{margin:0 0 12px;color:#0f172a;font-size:17px;font-weight:850}
          .st-key-cost_optimization_opportunities{width:100%;max-width:none;margin:0 0 22px;padding:18px;border:1px solid #dbe3ef;border-radius:18px;background:#fff;box-shadow:0 8px 24px rgba(15,23,42,.04);box-sizing:border-box}
          .st-key-cost_optimization_opportunities .cv21-table-card{border:0;border-radius:12px;box-shadow:none}
          .st-key-cost_optimization_opportunities .cv21-table-scroll{border:1px solid #e5eaf1;border-radius:12px}
          .cv21-table th:first-child{width:42px}.cv21-table th:nth-child(2){width:25%}.cv21-table th:nth-child(3){width:13%}.cv21-table th:nth-child(4){width:24%}.cv21-table th:nth-child(5){width:18%}.cv21-table th:nth-child(6){width:120px}
          .st-key-cost_optimization_opportunities [data-testid="stButton"] button{min-height:40px;border-radius:9px;font-weight:750;white-space:nowrap}
          @media(max-width:1100px){
            .cv21-page{max-width:100%}
            .st-key-cost_optimization_opportunities{padding:14px}

            .cv21-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
            .cv21-kpi:last-child{grid-column:1/-1}
            .cv21-heading{grid-template-columns:minmax(0,1fr) minmax(170px,220px)}
            .cv21-title{font-size:30px}
          }
          @media(max-width:760px){
            .cv21-kpi-grid{grid-template-columns:1fr;gap:10px;margin:16px 0 22px}
            .cv21-kpi,.cv21-kpi:last-child{grid-column:auto;min-height:104px;padding:16px}
            .cv21-heading{grid-template-columns:1fr;gap:12px}
            .cv21-title{font-size:27px}
            .cv21-section-heading{align-items:flex-start;flex-direction:column}
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _opportunity_table_markup(rows: List[Dict[str, Any]]) -> str:
    """Render the ranked opportunity table with the same safe component art as Compare Parts."""
    if not rows:
        return ""

    maximum_savings = max(
        (_number(row.get("Estimated Run Savings"), 0.0) for row in rows),
        default=0.0,
    )
    body = []
    for index, row in enumerate(rows, start=1):
        part_number = _text(row.get("Part Number"), "Component")
        description = _text(row.get("Description"), "")
        manufacturer = _text(row.get("Manufacturer"), "")
        if description:
            component_name = description
            component_meta = part_number
        elif manufacturer and manufacturer.casefold() != "unknown":
            component_name = manufacturer
            component_meta = part_number
        else:
            component_name = part_number
            component_meta = "Part number"

        safe_name = html.escape(component_name)
        safe_part_number = html.escape(component_meta)
        safe_category = html.escape(_text(row.get("Category"), "Cost review"))
        reason = html.escape(_text(row.get("Reason"), ""))
        photo = part_image_markup(
            row.get("Image URL"),
            part_number,
            size=48,
            part=row.get("Image Context") or {
                "description": description,
                "manufacturer": manufacturer,
                "category": row.get("Component Category"),
            },
        )
        unit_price = _number(row.get("Current Unit Price"), 0.0)
        estimated_savings = _number(row.get("Estimated Run Savings"), 0.0)
        currency = _text(row.get("Currency"))
        savings_rate = max(0, min(100, int(round(_number(row.get("Savings Rate"), 0.0) * 100))))
        bar_width = (
            max(0, min(100, int(round(estimated_savings / maximum_savings * 100))))
            if maximum_savings > 0 else 0
        )
        from src.ui.navigation import alternative_finder_href

        alternative_url = alternative_finder_href(
            mpn=part_number,
            manufacturer=manufacturer,
            description=description,
            risk=str(row.get("Risk Score") or ""),
            analysis_id=str(row.get("Analysis ID") or ""),
            return_analysis_id=str(row.get("Analysis ID") or ""),
            source_page="cost_optimization",
            project_name=str(row.get("Project") or ""),
            bom_name=str(row.get("Project") or ""),
        )
        body.append(
            "<tr>"
            f"<td class='cv21-rank'>{index}</td>"
            "<td><div class='cv21-component'>"
            f"{photo}<div class='cv21-component-copy'><div class='cv21-component-name'>{safe_name}</div>"
            f"<div class='cv21-component-mpn'>{safe_part_number}</div></div></div></td>"
            f"<td class='cv21-price'>{html.escape(_format_money(unit_price, currency))}</td>"
            f"<td><div class='cv21-path-title'>{safe_category}</div>"
            f"<div class='cv21-path-copy'>{reason}</div></td>"
            "<td><div class='cv21-savings-amount'>"
            f"<span>{html.escape(_format_money(estimated_savings, currency))}</span>"
            f"<span class='cv21-savings-rate'>{savings_rate}%</span></div>"
            f"<div class='cv21-progress' role='presentation'><span style='width:{bar_width}%'></span></div></td>"
            "<td class='cv21-review-cell'>"
            "<span class='cv21-review-pill' title='Calculated from timestamped exact-part supplier API snapshots; confirm the supplier quote and engineering fit before action'>Confirm quote</span>"
            f"<a class='cv21-row-action' href='{html.escape(alternative_url, quote=True)}' target='_self'>Find alternatives</a></td>"
            "</tr>"
        )
    return (
        "<div class='cv21-table-card'><div class='cv21-table-scroll'>"
        "<table class='cv21-table'><thead><tr>"
        "<th>#</th><th>Component</th><th>Higher saved quote</th>"
        "<th>Evidence and quantity</th><th>Saved quote spread</th><th>Review status</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></div>"
    )


def _currency(value: Any, *, currency: str = "", show_zero: bool = True) -> str:
    if value is None:
        return "Not comparable"
    amount = _number(value, 0.0)
    if not show_zero and amount <= 0:
        return "—"
    return _format_money(amount, currency)


def render_cost_optimization(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
    control: Callable[[], Any] | None = None,
) -> None:
    from src.ui.approved_pages import begin_approved_page, end_approved_page
    from src.ui.cadivor_design_system.icons import lucide

    begin_approved_page()
    _css()

    with st.container(key="cost_optimization_workspace"):
        heading_col, control_col = st.columns([4.0, 1.25], vertical_alignment="bottom")
        with heading_col:
            st.markdown(
                """
                <div class="cv-ap cv21-page">
                  <p class="cv21-eyebrow">Cost optimization</p>
                  <h1 class="cv21-title">Cost optimization</h1>
                  <p class="cv21-copy">Compare exact-part, timestamped supplier price snapshots and quantity breaks. Cadivor only calculates a price spread when the saved offers are comparable.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with control_col:
            if control is not None:
                control()

        component_count = int(intelligence.get("component_count", 0) or 0)
        priced_count = len(intelligence.get("priced_rows") or [])
        pricing_coverage = int(intelligence.get("pricing_coverage", 0) or 0)
        has_priced_components = component_count > 0 and priced_count > 0
        currency = str(intelligence.get("currency") or "")
        mixed_currency = len(intelligence.get("currencies") or []) > 1
        savings_text = (
            "Multiple currencies" if mixed_currency and intelligence.get("estimated_savings") is None
            else _currency(intelligence.get("estimated_savings"), currency=currency, show_zero=bool(intelligence.get("opportunities")))
        )
        spend_text = (
            "Multiple currencies" if mixed_currency and intelligence.get("production_run_cost") is None
            else _currency(intelligence.get("production_run_cost"), currency=currency, show_zero=has_priced_components)
        )
        opportunities = list(intelligence.get("opportunities") or [])
        opportunity_count = len(opportunities)
        build_quantity = int(intelligence.get("build_quantity", 1) or 1)

        if has_priced_components:
            savings_note = (
                f"Saved distributor price spread across {build_quantity:,} builds; excludes freight, tax, MOQ, and checkout"
                if opportunity_count else "Requires two comparable exact-part supplier offers at the BOM quantity"
            )
            spend_note = f"{priced_count} of {component_count} components have exact-part, timestamped price snapshots"
        else:
            savings_note = "No comparable supplier price spread is available"
            spend_note = "No exact-part, timestamped supplier price snapshots are available"

        if opportunity_count:
            opportunity_note = "Ranked by exact-part saved supplier price spread at the stated quantity"
        else:
            opportunity_note = "Two comparable supplier snapshots are required"

        kpis = [
            ("Comparable quote spread", savings_text, savings_note, "dollar-sign"),
            ("Addressable spend", spend_text, spend_note, "chart"),
            ("Opportunities", f"{opportunity_count:,}", opportunity_note, "lightbulb"),
        ]
        kpi_markup = []
        for label, value, note, icon_name in kpis:
            icon = lucide(icon_name, size=24)
            kpi_markup.append(
                "<article class='cv21-kpi'><span class='cv21-kpi-icon' aria-hidden='true'>"
                + icon
                + "</span><div><div class='cv21-kpi-label'>"
                + html.escape(label)
                + "</div><div class='cv21-kpi-value'>"
                + html.escape(value)
                + "</div><div class='cv21-kpi-note'>"
                + html.escape(note)
                + "</div></div></article>"
            )
        st.markdown(
            "<div class='cv-ap cv21-page'><section class='cv21-kpi-grid'>"
            + "".join(kpi_markup)
            + "</section></div>",
            unsafe_allow_html=True,
        )

        if component_count == 0:
            st.info("Upload and analyze a BOM to populate cost optimization with your saved component data.")
        elif pricing_coverage < 100:
            st.caption(
                f"{pricing_coverage}% of component lines have exact-part, timestamped supplier API price snapshots. "
                "Catalog snapshots can differ from checkout prices."
            )

        category_options = sorted(
            {
                _text(row.get("Category"), "Cost review")
                for row in opportunities
            }
        )
        filter_key = "cost_optimization_category_filter"
        filter_options = ["All opportunities", *category_options]
        if st.session_state.get(filter_key) not in filter_options:
            st.session_state[filter_key] = filter_options[0]

        with st.container(key="cost_optimization_opportunities"):
            title_col, filter_col = st.columns([3.4, 1.15], vertical_alignment="center")
            with title_col:
                st.markdown(
                    """
                    <div class="cv21-section-heading">
                      <div>
                        <h2 class="cv21-section-title">Comparable supplier quote spreads</h2>
                        <p class="cv21-section-subtitle">Differences use exact-MPN saved API snapshots in one currency at a stated quantity; confirm with the supplier before purchasing.</p>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with filter_col:
                selected_category = st.selectbox(
                    "Filter opportunities",
                    filter_options,
                    key=filter_key,
                    label_visibility="collapsed",
                    disabled=not category_options,
                )

            filtered_opportunities = (
                opportunities
                if selected_category == "All opportunities"
                else [row for row in opportunities if _text(row.get("Category"), "Cost review") == selected_category]
            )
            visible_opportunities = filtered_opportunities[:8]
            if visible_opportunities:
                st.markdown(
                    _opportunity_table_markup(visible_opportunities),
                    unsafe_allow_html=True,
                )
                if len(filtered_opportunities) > len(visible_opportunities):
                    st.caption(
                        f"Showing the top {len(visible_opportunities)} of {len(filtered_opportunities)} opportunities."
                    )

                labels = [
                    f"{_text(row.get('Part Number'), 'Component')} · {_text(row.get('Category'), 'Cost review')}"
                    for row in visible_opportunities
                ]
                option_map = dict(zip(labels, visible_opportunities))
                action_key = "cost_optimization_selected_opportunity"
                if st.session_state.get(action_key) not in option_map:
                    st.session_state[action_key] = labels[0]
                action_cols = st.columns([4.6, 1.2, 1.2], vertical_alignment="center")
                with action_cols[0]:
                    selected_label = st.selectbox(
                        "Choose an opportunity to review",
                        labels,
                        key=action_key,
                        label_visibility="collapsed",
                    )
                selected_row = option_map[selected_label]
                with action_cols[1]:
                    internal_nav_button(
                        "Find alternatives",
                        "Alternative Finder",
                        key="cost_selected_find_alternatives",
                        original_part=selected_row["Part Number"],
                        manufacturer=selected_row.get("Manufacturer", ""),
                        description=selected_row.get("Description", ""),
                        risk=str(selected_row.get("Risk Score") or ""),
                        analysis_id=selected_row.get("Analysis ID", ""),
                        return_analysis_id=selected_row.get("Analysis ID", ""),
                        project_name=selected_row.get("Project", ""),
                        bom_name=selected_row.get("Project", ""),
                        source_page="cost_optimization",
                        use_container_width=True,
                    )
                with action_cols[2]:
                    internal_nav_button(
                        "Review sourcing",
                        "Procurement Advisor",
                        key="cost_selected_review_sourcing",
                        original_part=selected_row["Part Number"],
                        use_container_width=True,
                    )
            elif opportunities:
                st.markdown(
                    "<p class='cv21-empty'>No opportunities match this filter. Select another opportunity type to continue.</p>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<p class='cv21-empty'>No exact-part, timestamped supplier offers currently support a same-currency price comparison at a known quantity. Record a supplier quote or rerun the analysis to add evidence.</p>",
                    unsafe_allow_html=True,
                )

        with st.expander("Cost data quality and detailed records"):
            st.markdown('<div class="cv21-detail-heading">Cost data quality</div>', unsafe_allow_html=True)
            quality_cols = st.columns(2)
            with quality_cols[0]:
                st.markdown(
                    f"<div class='cv21-kpi'><div><div class='cv21-kpi-label'>Pricing coverage</div>"
                    f"<div class='cv21-kpi-value'>{pricing_coverage}%</div>"
                    f"<div class='cv21-kpi-note'>{priced_count} of {component_count} rows have an exact-part, timestamped supplier price snapshot</div></div></div>",
                    unsafe_allow_html=True,
                )
            with quality_cols[1]:
                st.markdown(
                    f"<div class='cv21-kpi'><div><div class='cv21-kpi-label'>Single-source or no-stock spend</div>"
                    f"<div class='cv21-kpi-value'>{html.escape(_currency(intelligence.get('sourcing_risk_cost'), currency=currency, show_zero=has_priced_components))}</div>"
                    f"<div class='cv21-kpi-note'>Saved price snapshot spend with one quote source or a timestamped zero-stock observation</div></div></div>",
                    unsafe_allow_html=True,
                )

            photo_column = st.column_config.ImageColumn("Part photo", width="small")
            if intelligence.get("top_cost_parts"):
                st.markdown('<div class="cv21-detail-heading">Highest recorded component costs</div>', unsafe_allow_html=True)
                top_df = pd.DataFrame(intelligence["top_cost_parts"])
                cadivor_engineering_dataframe(
                    top_df[
                        [
                            "Project",
                            "Part Number",
                            "Image URL",
                            "Manufacturer",
                        "Quantity per Build",
                            "Unit Price",
                        "Currency",
                            "Extended Cost per Build",
                            "Supplier Sources",
                            "Available Stock",
                            "Risk Score",
                        ]
                    ],
                    column_config={
                        "Image URL": photo_column,
                        "Unit Price": st.column_config.NumberColumn(format="%.4f"),
                        "Extended Cost per Build": st.column_config.NumberColumn(format="%.2f"),
                    },
                )
            missing_tab, all_tab = st.tabs(["Missing price data", "All cost records"])
            with missing_tab:
                if intelligence.get("missing_price_rows"):
                    missing_df = pd.DataFrame(intelligence["missing_price_rows"])
                    cadivor_engineering_dataframe(
                        missing_df[
                            [
                                "Project",
                                "Part Number",
                                "Image URL",
                                "Manufacturer",
                                "Quantity per Build",
                                "Supplier Sources",
                                "Available Stock",
                                "Risk Score",
                            ]
                        ],
                        column_config={"Image URL": photo_column},
                    )
                else:
                    st.success("Every saved component record contains pricing data.")
            with all_tab:
                if intelligence.get("rows"):
                    all_df = pd.DataFrame(intelligence["rows"])
                    cadivor_engineering_dataframe(
                        all_df[
                            [
                                "Project",
                                "Part Number",
                                "Image URL",
                                "Manufacturer",
                                "Quantity per Build",
                                "Unit Price",
                                "Currency",
                                "Extended Cost per Build",
                                "Supplier Sources",
                                "Available Stock",
                                "Lifecycle",
                                "Risk Score",
                            ]
                        ],
                        column_config={
                            "Image URL": photo_column,
                            "Unit Price": st.column_config.NumberColumn(format="%.4f"),
                            "Extended Cost per Build": st.column_config.NumberColumn(format="%.2f"),
                        },
                    )
                else:
                    st.info("No saved component records are available.")
        end_approved_page()
