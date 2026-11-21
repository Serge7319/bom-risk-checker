"""Adapters that expose Cadivor's established supplier and replacement engines.

This module deliberately calls the same aggregator, risk engine, and
Alternative Finder pipeline used by the original authenticated workflow. It
does not invent supplier values when providers are missing or unavailable.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Mapping

import pandas as pd


def production_analysis_enabled() -> bool:
    """Use the established supplier engine on production unless explicitly off."""
    configured = (os.environ.get("CADIVOR_ANALYSIS_MODE") or "").strip().lower()
    if configured in {"synthetic", "synthetic-preview", "preview"}:
        return False
    if configured in {"legacy", "supplier", "production"}:
        return True
    from apps.api.sandbox_auth import is_production_runtime

    return is_production_runtime()


def configured_supplier_count() -> int:
    """Count configured provider credentials without returning secret values."""
    nexar_client_id = (
        os.environ.get("NEXAR_CLIENT_ID") or os.environ.get("OCTOPART_CLIENT_ID") or ""
    ).strip()
    nexar_client_secret = (
        os.environ.get("NEXAR_CLIENT_SECRET") or os.environ.get("OCTOPART_CLIENT_SECRET") or ""
    ).strip()
    configured = (
        bool((os.environ.get("MOUSER_API_KEY") or "").strip()),
        bool((os.environ.get("DIGIKEY_CLIENT_ID") or "").strip())
        and bool((os.environ.get("DIGIKEY_CLIENT_SECRET") or "").strip()),
        bool((os.environ.get("NEWARK_API_KEY") or "").strip()),
        bool(nexar_client_id) and bool(nexar_client_secret),
    )
    return sum(configured)


def _number(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        import math

        number = float(value)
        if math.isfinite(number):
            return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None
    return None


def _part_data_for_row(row: Mapping[str, Any]) -> dict[str, Any]:
    from src.bom_parser import bom_metadata_text
    from integrations.supplier_aggregator import get_best_part_data

    mpn = str(row.get("mpn") or row.get("mpn_normalized") or "").strip()
    uploaded_manufacturer = bom_metadata_text(
        row.get("manufacturer"), row.get("manufacturer_name"), row.get("mfr"), row.get("mfg")
    )
    try:
        result = (
            get_best_part_data(mpn, manufacturer=uploaded_manufacturer)
            if uploaded_manufacturer
            else get_best_part_data(mpn)
        )
    except Exception:
        result = {
            "mpn": mpn,
            "manufacturer_part_number": mpn,
            "lifecycle_status": "Unknown",
            "stock_total": None,
            "total_market_stock": None,
            "supplier_count": None,
            "supplier_data_verified": False,
            "stock_data_complete": False,
            "provider_health": {
                "has_verified_data": False,
                "summary_message": "Supplier data could not be verified during this analysis.",
            },
        }
    if not isinstance(result, dict):
        result = {}
    part = dict(result)
    part["mpn"] = mpn
    part["searched_part_number"] = mpn
    part["quantity"] = row.get("quantity", 0)
    part["bom_manufacturer"] = uploaded_manufacturer
    part["requested_manufacturer"] = uploaded_manufacturer
    part["supplier_manufacturer"] = str(part.get("manufacturer") or "").strip()
    uploaded_description = bom_metadata_text(
        row.get("description"), row.get("part_description"), row.get("component_description")
    )
    if uploaded_manufacturer and part.get("supplier_data_verified"):
        part["manufacturer_source"] = str(part.get("source") or "authorized supplier")
    elif uploaded_manufacturer:
        # Keep the BOM's original value visible, but never label it as supplier
        # verified. The supplier lookup above was constrained to this brand.
        part["manufacturer"] = uploaded_manufacturer
        part["manufacturer_source"] = "BOM upload (not supplier-verified)"
    elif part.get("supplier_manufacturer"):
        part["manufacturer_source"] = str(part.get("source") or "authorized supplier")
    if uploaded_description:
        part["description"] = uploaded_description
    return part


def _part_analysis(row: Mapping[str, Any]) -> dict[str, Any]:
    from integrations.provider_health import unverified_supplier_reason_replacements
    from integrations.stock_coercion import stock_evidence_note
    from src.alternative_engine import suggest_alternatives_v2
    from src.alternate_candidate_evidence import normalize_candidate_evidence
    from src.risk_engine import calculate_risk

    part = _part_data_for_row(row)
    mpn = str(row.get("mpn") or row.get("mpn_normalized") or "").strip()
    normalized = str(row.get("mpn_normalized") or mpn).strip()
    requested_manufacturer = str(part.get("bom_manufacturer") or "").strip()
    try:
        alternatives = suggest_alternatives_v2(
            normalized,
            original_manufacturer=requested_manufacturer,
            include_family_search=False,
        ) or []
        search_status = "Candidates returned" if alternatives else "No candidate returned; search coverage is incomplete"
    except Exception:
        alternatives = []
        search_status = "Search unavailable; supplier coverage is incomplete"

    risk = calculate_risk(part)
    reasons = list(risk.get("risk_reasons") or [])
    verified = bool(part.get("supplier_data_verified"))
    if not bool(part.get("stock_data_complete")) and part.get("total_market_stock") is not None:
        note = "Supplier inventory coverage is incomplete; BOM quantity coverage is not confirmed"
        if note not in reasons:
            reasons.append(note)
    if not verified:
        replacements = unverified_supplier_reason_replacements()
        reasons = [replacements.get(reason, reason) for reason in reasons]
        if not any("could not be verified" in str(reason).lower() for reason in reasons):
            reasons.insert(0, "Some supplier data could not be verified during this analysis")

    stock = part.get("total_market_stock")
    if stock is None:
        stock = part.get("stock_total")
    price = part.get("unit_price")
    if price is None:
        price = part.get("price")
    if price is None:
        price = part.get("best_price")
    if price is None:
        price = part.get("minimum_price")
    price_number = _number(price)
    # Legacy supplier clients use 0.0 as a missing-price sentinel. A zero
    # supplier price is not a verified quote, so store it as unknown.
    if price_number is not None and price_number <= 0:
        price = None
    lifecycle = part.get("lifecycle_status") or "Unknown"
    supplier = part.get("source") or ""
    evidence_class = "live-authorized-supplier" if verified else "missing"
    explicit_price_source = str(part.get("price_source") or "").strip()
    offers = part.get("supplier_offers") if isinstance(part.get("supplier_offers"), list) else []
    lead_time_evidence = part.get("lead_time_evidence") if isinstance(part.get("lead_time_evidence"), list) else []
    stock_evidence = part.get("stock_evidence") if isinstance(part.get("stock_evidence"), list) else []
    lifecycle_evidence = part.get("lifecycle_evidence") if isinstance(part.get("lifecycle_evidence"), list) else []
    has_live_offer_price = any(
        isinstance(offer, dict)
        and (offer.get("unit_price") is not None or offer.get("price") is not None)
        and str(offer.get("retrieved_at") or "").strip()
        for offer in offers
    )
    if explicit_price_source:
        price_source = explicit_price_source
    elif price is None:
        price_source = "missing"
    elif verified and has_live_offer_price:
        price_source = str(part.get("source") or "live-authorized-supplier")
    elif verified:
        # Live identity must not wash an unlabeled/synthetic price into "live".
        price_source = "synthetic-preview"
    else:
        price_source = "missing"
    lifecycle_sources = sorted({
        str(item.get("source") or "").strip()
        for item in lifecycle_evidence
        if isinstance(item, dict) and str(item.get("source") or "").strip()
    })
    lifecycle_source = ", ".join(lifecycle_sources) or str(
        part.get("lifecycle_source") or (supplier if verified else evidence_class)
    )
    stock_sources = list(part.get("stock_data_sources") or [])
    stock_retrieval_times = [
        str(item.get("retrieved_at") or "").strip()
        for item in stock_evidence
        if isinstance(item, dict) and str(item.get("retrieved_at") or "").strip()
    ]
    lead_time_retrieval = str(part.get("lead_time_retrieved_at") or "").strip()
    if not lead_time_retrieval:
        lead_time_retrieval = next(
            (
                str(item.get("retrieved_at") or "").strip()
                for item in lead_time_evidence
                if isinstance(item, dict)
                and str(item.get("source") or "").casefold()
                == str(part.get("lead_time_source") or "").casefold()
                and str(item.get("weeks") if item.get("weeks") is not None else "")
                == str(part.get("lead_time_weeks") if part.get("lead_time_weeks") is not None else "")
            ),
            "",
        )
    matching_price_offer = next(
        (
            offer for offer in offers
            if isinstance(offer, dict)
            and str(offer.get("distributor") or offer.get("source") or "").casefold()
            == str(supplier or "").casefold()
            and _number(offer.get("unit_price")) == _number(price)
            and str(offer.get("retrieved_at") or "").strip()
        ),
        {},
    )
    stock_source = (
        ", ".join(str(item) for item in stock_sources if item)
        if stock_sources
        else (evidence_class if stock is not None and verified else ("missing" if stock is None else "synthetic-preview"))
    )
    price_type = str(part.get("price_type") or "").strip()
    if not price_type:
        if price is None:
            price_type = "not-recorded"
        elif "synthetic" in price_source.casefold() or "preview" in price_source.casefold():
            price_type = "synthetic-estimate"
        elif any(
            isinstance(offer, dict) and offer.get("price_break_quantity") not in (None, "")
            for offer in offers
        ):
            price_type = "quantity-break"
        elif price_source == "live-authorized-supplier":
            price_type = "distributor-list"
        else:
            price_type = "recorded"
    candidates = normalize_candidate_evidence(alternatives, original_mpn=normalized)
    candidate_mpns = [
        str(candidate.get("Alternative Part") or candidate.get("manufacturer_part_number") or "").strip()
        for candidate in alternatives if isinstance(candidate, dict)
    ]
    candidate_mpns = [candidate for candidate in candidate_mpns if candidate]
    provider_health = part.get("provider_health") if isinstance(part.get("provider_health"), dict) else {}
    coverage = str(provider_health.get("summary_message") or "Supplier data could not be verified during this analysis")
    try:
        configured_source_count = int(provider_health.get("configured_count") or 0)
        successful_source_count = int(provider_health.get("successful_count") or 0)
        failed_source_count = int(provider_health.get("failed_count") or 0)
    except (TypeError, ValueError):
        configured_source_count = successful_source_count = 0
        failed_source_count = 1
    supplier_coverage_complete = bool(
        configured_source_count > 0 and failed_source_count == 0
    )
    checked_source_summary = (
        f"{successful_source_count}/{configured_source_count} configured supplier sources responded"
        if configured_source_count
        else "No supplier sources configured"
    )
    return {
        "MPN": mpn,
        "mpn": mpn,
        "Normalized MPN": normalized,
        "mpn_normalized": normalized,
        "Manufacturer": str(part.get("manufacturer") or ""),
        "manufacturer": str(part.get("manufacturer") or ""),
        "BOM Manufacturer": str(part.get("bom_manufacturer") or ""),
        "bom_manufacturer": str(part.get("bom_manufacturer") or ""),
        "Supplier Manufacturer": str(part.get("supplier_manufacturer") or ""),
        "supplier_manufacturer": str(part.get("supplier_manufacturer") or ""),
        "Manufacturer Source": str(part.get("manufacturer_source") or ""),
        "manufacturer_source": str(part.get("manufacturer_source") or ""),
        "Manufacturer Identity Status": str(part.get("identity_status") or ("matched" if verified else "unverified")),
        "Manufacturer Part Number": str(part.get("manufacturer_part_number") or mpn),
        "Description": str(part.get("description") or row.get("description") or row.get("part_description") or ""),
        "description": str(part.get("description") or row.get("description") or row.get("part_description") or ""),
        "Category": str(part.get("category") or part.get("architecture") or row.get("category") or ""),
        "Quantity": row.get("quantity", 0),
        "quantity": row.get("quantity", 0),
        "Parent MPN": row.get("parent_mpn") or "",
        "parent_mpn": row.get("parent_mpn") or "",
        "Line Type": row.get("line_type") or "part",
        "line_type": row.get("line_type") or "part",
        "Quantity per Parent": row.get("quantity_per_parent", row.get("quantity", 0)),
        "quantity_per_parent": row.get("quantity_per_parent", row.get("quantity", 0)),
        "Effective Quantity": row.get("effective_quantity", row.get("quantity", 0)),
        "effective_quantity": row.get("effective_quantity", row.get("quantity", 0)),
        "Best Source": str(supplier),
        "source": str(supplier),
        "identity_source": evidence_class,
        "evidence_source": evidence_class,
        "evidence_class": evidence_class,
        "price_source": price_source,
        "price_type": price_type,
        "Price Retrieved At": str(
            matching_price_offer.get("retrieved_at")
            or (part.get("retrieved_at") if price is not None and verified else "")
        ),
        "price_retrieved_at": str(
            matching_price_offer.get("retrieved_at")
            or (part.get("retrieved_at") if price is not None and verified else "")
        ),
        "lifecycle_source": lifecycle_source,
        "stock_source": stock_source,
        "Supplier Count": _number(part.get("supplier_count")),
        "supplier_count": _number(part.get("supplier_count")),
        "Supplier Coverage": coverage,
        "Supplier Sources Checked": checked_source_summary,
        "supplier_sources_checked": checked_source_summary,
        "Supplier Coverage Complete": supplier_coverage_complete,
        "supplier_coverage_complete": supplier_coverage_complete,
        "Total Market Stock": _number(stock),
        "Stock Available": _number(stock),
        "Stock": _number(stock),
        "stock": _number(stock),
        "stock_available": _number(stock),
        "stock_total": _number(part.get("stock_total")),
        "total_market_stock": _number(part.get("total_market_stock")),
        "Stock Data Sources": list(part.get("stock_data_sources") or []),
        "Stock Data Complete": bool(part.get("stock_data_complete")),
        "stock_data_complete": bool(part.get("stock_data_complete")),
        "Stock Coverage Note": stock_evidence_note(
            stock, part.get("stock_data_sources") or [],
            complete=bool(part.get("stock_data_complete")),
            matching_supplier_count=part.get("supplier_count"),
        ),
        "Unit Price": _number(price),
        "unit_price": _number(price),
        "Unit Price Currency": str(part.get("unit_price_currency") or part.get("currency") or ""),
        "unit_price_currency": str(part.get("unit_price_currency") or part.get("currency") or ""),
        "Lead Time Weeks": _number(part.get("lead_time_weeks")),
        "Lead Time Source": str(part.get("lead_time_source") or ""),
        "Lead Time Retrieved At": lead_time_retrieval,
        "Lead Time Evidence": lead_time_evidence,
        "Stock Evidence