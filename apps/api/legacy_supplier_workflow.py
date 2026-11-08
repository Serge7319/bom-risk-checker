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
    configured = (
        bool((os.environ.get("MOUSER_API_KEY") or "").strip()),
        bool((os.environ.get("DIGIKEY_CLIENT_ID") or "").strip())
        and bool((os.environ.get("DIGIKEY_CLIENT_SECRET") or "").strip()),
        bool((os.environ.get("NEWARK_API_KEY") or "").strip()),
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
    try:
        result = get_best_part_data(mpn)
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

    uploaded_manufacturer = bom_metadata_text(
        row.get("manufacturer"), row.get("manufacturer_name"), row.get("mfr"), row.get("mfg")
    )
    uploaded_description = bom_metadata_text(
        row.get("description"), row.get("part_description"), row.get("component_description")
    )
    if uploaded_manufacturer:
        part["manufacturer"] = uploaded_manufacturer
        part["manufacturer_source"] = "BOM upload"
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
    try:
        alternatives = suggest_alternatives_v2(normalized, include_family_search=False) or []
        search_status = "Candidates returned" if alternatives else "No candidate returned; search coverage is incomplete"
    except Exception:
        alternatives = []
        search_status = "Search unavailable; supplier coverage is incomplete"

    risk = calculate_risk(part)
    reasons = list(risk.get("risk_reasons") or [])
    verified = bool(part.get("supplier_data_verified"))
    provider_health = part.get("provider_health") if isinstance(part.get("provider_health"), dict) else {}
    coverage = str(
        provider_health.get("summary_message")
        or "Supplier data could not be verified during this analysis"
    )
    if not bool(part.get("stock_data_complete")) and part.get("total_market_stock") is not None:
        note = "Supplier inventory coverage is incomplete; BOM quantity coverage is not confirmed"
        if note not in reasons:
            reasons.append(note)
    if not verified:
        replacements = unverified_supplier_reason_replacements()
        reasons = [replacements.get(reason, reason) for reason in reasons]
        # Prefer the provider-health status so unavailable credentials / no-match
        # outcomes stay visible instead of a generic "could not be verified" line.
        status_note = coverage.strip() or (
            "No live supplier evidence was available; manufacturer, lifecycle, "
            "stock, and price remain unconfirmed"
        )
        if status_note and not any(
            status_note.casefold() == str(reason).casefold() for reason in reasons
        ):
            reasons.insert(0, status_note)
        elif not any("could not be verified" in str(reason).lower() for reason in reasons):
            reasons.insert(0, "Some supplier data could not be verified during this analysis")

    stock = part.get("total_market_stock")
    if stock is None:
        stock = part.get("stock_total")
    price = part.get("unit_price") or part.get("price") or part.get("best_price") or part.get("minimum_price")
    lifecycle = part.get("lifecycle_status") or "Unknown"
    supplier = part.get("source") or ""
    evidence_class = "live-authorized-supplier" if verified else "missing"
    candidates = normalize_candidate_evidence(alternatives, original_mpn=normalized)
    candidate_mpns = [
        str(candidate.get("Alternative Part") or candidate.get("manufacturer_part_number") or "").strip()
        for candidate in alternatives if isinstance(candidate, dict)
    ]
    candidate_mpns = [candidate for candidate in candidate_mpns if candidate]
    return {
        "MPN": mpn,
        "mpn": mpn,
        "Normalized MPN": normalized,
        "mpn_normalized": normalized,
        "Manufacturer": str(part.get("manufacturer") or ""),
        "manufacturer": str(part.get("manufacturer") or ""),
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
        "evidence_source": evidence_class,
        "evidence_class": evidence_class,
        "Supplier Count": _number(part.get("supplier_count")),
        "supplier_count": _number(part.get("supplier_count")),
        "Supplier Coverage": coverage,
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
        "Stock Evidence": stock_evidence_note(
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
        "Lifecycle": str(lifecycle),
        "Lifecycle Status": str(lifecycle),
        "lifecycle_status": str(lifecycle),
        "Lifecycle Evidence": list(part.get("lifecycle_evidence") or []),
        "Lifecycle Conflict": bool(part.get("lifecycle_conflict")),
        "lifecycle_conflict": bool(part.get("lifecycle_conflict")),
        "Product URL": str(part.get("product_detail_url") or part.get("product_url") or part.get("source_url") or ""),
        "product_url": str(part.get("product_detail_url") or part.get("product_url") or part.get("source_url") or ""),
        "Datasheet URL": str(part.get("datasheet_url") or part.get("datasheet") or ""),
        "datasheet_url": str(part.get("datasheet_url") or part.get("datasheet") or ""),
        "Supplier Offers": list(part.get("supplier_offers") or []),
        "Photo": str(part.get("image_url") or ""),
        "Has Alternates": bool(candidate_mpns),
        "Alternate Count": len(candidate_mpns),
        "Alternate Search Status": str(part.get("alternate_search_status") or search_status),
        "Alternative Part Numbers": ", ".join(candidate_mpns),
        "Alternate Candidates": candidates,
        "alternate_candidates": candidates,
        "Supplier Data Verified": verified,
        "supplier_data_verified": verified,
        "Sourcing Updated At": str(part.get("retrieved_at") or part.get("updated_at") or ""),
        "retrieved_at": str(part.get("retrieved_at") or part.get("updated_at") or ""),
        "Risk Score": risk.get("risk_score"),
        "risk_score": risk.get("risk_score"),
        "Risk Level": risk.get("risk_level") or "Needs verification",
        "risk_level": risk.get("risk_level") or "Needs verification",
        "Risk Reasons": "; ".join(str(reason) for reason in reasons) or (
            "Supplier evidence is insufficient to assign a risk score"
            if risk.get("risk_level") == "Needs verification"
            else "No elevated risk indicators in the recorded evidence"
        ),
        "risk_reasons": reasons,
        "assessment_basis": part.get("assessment_basis") or "",
        "assessment_basis_note": part.get("assessment_basis_note") or "",
    }


def analyze_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Run the preserved exact-part supplier and risk workflow for each BOM row."""
    records = [row.to_dict() for _, row in frame.iterrows()]
    if len(records) <= 1:
        return [_part_analysis(record) for record in records]
    results: list[dict[str, Any] | None] = [None] * len(records)
    workers = min(5, len(records))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_part_analysis, row): index for index, row in enumerate(records)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception:
                results[index] = _part_analysis_failure(records[index])
    return [row for row in results if row is not None]


def _part_analysis_failure(row: Mapping[str, Any]) -> dict[str, Any]:
    mpn = str(row.get("mpn") or row.get("mpn_normalized") or "").strip()
    quantity = row.get("quantity", 0)
    return {
        "MPN": mpn, "mpn": mpn,
        "Normalized MPN": str(row.get("mpn_normalized") or mpn),
        "mpn_normalized": str(row.get("mpn_normalized") or mpn),
        "Manufacturer": str(row.get("manufacturer") or ""),
        "manufacturer": str(row.get("manufacturer") or ""),
        "Description": str(row.get("description") or ""),
        "description": str(row.get("description") or ""),
        "Quantity": quantity, "quantity": quantity,
        "Parent MPN": row.get("parent_mpn") or "", "parent_mpn": row.get("parent_mpn") or "",
        "Line Type": row.get("line_type") or "part", "line_type": row.get("line_type") or "part",
        "Quantity per Parent": row.get("quantity_per_parent", quantity),
        "quantity_per_parent": row.get("quantity_per_parent", quantity),
        "Effective Quantity": row.get("effective_quantity", quantity),
        "effective_quantity": row.get("effective_quantity", quantity),
        "Lifecycle": "Unknown", "Lifecycle Status": "Unknown", "lifecycle_status": "Unknown",
        "Risk Score": None, "risk_score": None,
        "Risk Level": "Needs verification", "risk_level": "Needs verification",
        "Risk Reasons": "Part analysis failed; risk could not be assessed from supplier evidence",
        "risk_reasons": ["Part analysis failed; risk could not be assessed from supplier evidence"],
        "Supplier Data Verified": False, "supplier_data_verified": False,
        "Stock Data Complete": False, "stock_data_complete": False,
        "Alternate Search Status": "Search unavailable",
        "Alternate Candidates": [], "alternate_candidates": [],
        "evidence_source": "missing", "evidence_class": "missing", "source": "",
    }


def find_replacements(mpn: str) -> dict[str, Any]:
    """Run the same Alternative Finder state machine used by the legacy UI."""
    from src.alternative_finder_search import run_alternative_finder_search

    state: dict[str, Any] = {}
    status = run_alternative_finder_search(state, mpn)
    result = state.get("alternative_finder_result")
    result = result if isinstance(result, dict) else {}
    original = result.get("original_data") if isinstance(result.get("original_data"), dict) else {}
    candidates_raw = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    discovery = result.get("discovery_metadata") if isinstance(result.get("discovery_metadata"), dict) else {}

    candidates: list[dict[str, Any]] = []
    for candidate in candidates_raw:
        if not isinstance(candidate, dict):
            continue
        candidate_mpn = str(candidate.get("Alternative Part") or candidate.get("manufacturer_part_number") or "").strip()
        if not candidate_mpn or candidate_mpn.casefold() == str(mpn).strip().casefold():
            continue
        classification = str(candidate.get("Classification") or candidate.get("Category") or "Unverified candidate")
        disposition = str(candidate.get("Candidate Disposition") or "Discovery lead only")
        exact_source = bool(candidate.get("Source Identity Verified"))
        missing = [
            "datasheet-backed electrical, package, thermal, and qualification review",
        ]
        if not exact_source:
            missing.insert(0, "exact source MPN verification")
        candidates.append({
            "mpn": candidate_mpn,
            "manufacturer": str(candidate.get("Manufacturer") or ""),
            "description": str(candidate.get("description") or ""),
            "rationale": str(candidate.get("Recommendation") or candidate.get("Compatibility Notes") or disposition),
            "fit": "supplier-listed candidate; qualification required",
            "classification": classification,
            "missing_evidence": missing,
            "evidence_class": "live-authorized-supplier" if exact_source else "missing",
            "source": str(candidate.get("Evidence Source") or candidate.get("Supplier") or ""),
            "lifecycle_status": str(candidate.get("Lifecycle") or "Unknown"),
            "product_url": str(candidate.get("Product URL") or candidate.get("Source URL") or ""),
            "datasheet_url": str(candidate.get("Datasheet URL") or ""),
            "recommendation_score": candidate.get("Recommendation Score"),
            "source_identity_verified": exact_source,
            "compare_href_query": f"part_a={mpn}&part_b={candidate_mpn}",
        })

    provider_status = discovery.get("providers") if isinstance(discovery.get("providers"), dict) else {}
    missing = []
    if not original.get("supplier_data_verified"):
        missing.append("exact authorized-distributor lookup for the requested part")
    for provider, state_row in provider_status.items():
        if not isinstance(state_row, dict):
            continue
        if any(str(state_row.get(key) or "").casefold() in {"not_configured", "error", "timeout"} for key in ("lookup", "catalog", "substitutions")):
            message = str(state_row.get("message") or f"{provider} search coverage is incomplete")
            if message not in missing:
                missing.append(message)
    if not candidates:
        missing.append("supplier-listed replacement candidates")
    missing.append("datasheet-backed fit scoring")

    return {
        "status": str(status.get("status") or result.get("status") or "failed"),
        "search_outcome": str(status.get("search_outcome") or result.get("search_outcome") or "failure"),
        "requested_mpn": str(mpn).strip(),
        "original": {
            "mpn": str(original.get("manufacturer_part_number") or mpn).strip(),
            "manufacturer": str(original.get("manufacturer") or ""),
            "description": str(original.get("description") or ""),
            "lifecycle_status": str(original.get("lifecycle_status") or "Unknown"),
            "source": str(original.get("source") or ""),
            "supplier_data_verified": bool(original.get("supplier_data_verified")),
            "risk": result.get("original_risk") if isinstance(result.get("original_risk"), dict) else {},
        },
        "candidates": candidates,
        "discovery": discovery,
        "missing_evidence": missing,
        "mode": "legacy-supplier-engine",
        "live_lookups_enabled": configured_supplier_count() > 0,
        "gap": (
            "Candidate parts are research leads, not approved substitutes. Confirm identity, electrical limits, package, lifecycle, and qualification requirements against current manufacturer documentation."
            if candidates
            else "No verified replacement was found in this search. Check current manufacturer documentation and authorized distributors before changing the design."
        ),
    }
