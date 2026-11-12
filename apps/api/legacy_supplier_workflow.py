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
    lifecycle = part.get("lifecycle_status") or "Unknown"
    supplier = part.get("source") or ""
    evidence_class = "live-authorized-supplier" if verified else "missing"
    explicit_price_source = str(part.get("price_source") or "").strip()
    offers = part.get("supplier_offers") if isinstance(part.get("supplier_offers"), list) else []
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
        price_source = "live-authorized-supplier"
    elif verified:
        # Live identity must not wash an unlabeled/synthetic price into "live".
        price_source = "synthetic-preview"
    else:
        price_source = "missing"
    lifecycle_source = str(part.get("lifecycle_source") or evidence_class)
    stock_sources = list(part.get("stock_data_sources") or [])
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
        "identity_source": evidence_class,
        "evidence_source": evidence_class,
        "evidence_class": evidence_class,
        "price_source": price_source,
        "price_type": price_type,
        "lifecycle_source": lifecycle_source,
        "stock_source": stock_source,
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


def find_replacements(mpn: str, manufacturer: str = "") -> dict[str, Any]:
    """Run the same Alternative Finder state machine used by the legacy UI."""
    from apps.api.manufacturer_identity import (
        choices_from_manufacturer_labels,
        distinct_manufacturer_labels,
        manufacturers_match,
        multi_brand_choices_for_mpn,
    )
    from src.alternative_finder_search import run_alternative_finder_search

    state: dict[str, Any] = {}
    requested_manufacturer = str(manufacturer or "").strip()
    status = run_alternative_finder_search(
        state,
        mpn,
        requested_manufacturer=requested_manufacturer,
    )
    result = state.get("alternative_finder_result")
    result = result if isinstance(result, dict) else {}
    original = result.get("original_data") if isinstance(result.get("original_data"), dict) else {}
    identity_blocked = False
    identity_review_only = False
    status_hint = str(original.get("identity_status") or "").strip()
    if status_hint == "ambiguous":
        identity_blocked = True
        original = dict(original)
        original["manufacturer"] = ""
        original["identity_verified"] = False
        original["identity_status"] = "ambiguous"
        if not original.get("identity_choices"):
            labels = distinct_manufacturer_labels(
                original.get("all_supplier_results") or [],
                fallback=original.get("resolved_manufacturer")
                or original.get("manufacturer"),
            )
            original["identity_choices"] = multi_brand_choices_for_mpn(mpn) or (
                choices_from_manufacturer_labels(mpn, labels) if labels else []
            )
    elif requested_manufacturer:
        resolved = str(original.get("manufacturer") or original.get("Manufacturer") or "").strip()
        identity_review_only = bool(
            original.get("identity_review_only")
            and status_hint == "unresolved"
            and not resolved
            and not original.get("identity_verified")
        )
        if status_hint == "manufacturer_mismatch" or (
            status_hint == "unresolved" and not identity_review_only
        ) or (
            resolved
            and not manufacturers_match(requested_manufacturer, resolved, mpn=mpn)
        ):
            # A known conflicting supplier identity must remain a hard stop.
            identity_blocked = True
            original = dict(original)
            original["identity_status"] = (
                status_hint
                if status_hint in {"manufacturer_mismatch", "unresolved"}
                else ("manufacturer_mismatch" if resolved else "unresolved")
            )
            original["requested_manufacturer"] = requested_manufacturer
            original["resolved_manufacturer"] = resolved
            original["manufacturer"] = ""
            original["identity_verified"] = False
            original["identity_review_only"] = False
        elif not resolved:
            # This path is enabled only by the search engine's explicit review-only
            # marker. Preserve leads, while keeping source identity unverified.
            identity_blocked = not identity_review_only
            original = dict(original)
            original["manufacturer"] = ""
            original["requested_manufacturer"] = requested_manufacturer
            original["identity_status"] = "unresolved"
            original["identity_verified"] = False
            original["identity_review_only"] = identity_review_only
        else:
            original = dict(original)
            original["identity_status"] = "matched"
            original["requested_manufacturer"] = requested_manufacturer
            original["identity_verified"] = True
    elif not requested_manufacturer:
        # No brand selected: if supplier hits span multiple manufacturers for this
        # MPN, require an explicit choice before any candidates are returned.
        labels = distinct_manufacturer_labels(
            original.get("all_supplier_results") or [],
            fallback=original.get("manufacturer") or original.get("Manufacturer"),
        )
        known = multi_brand_choices_for_mpn(mpn)
        if len(labels) > 1 or len(known) > 1:
            identity_blocked = True
            original = dict(original)
            original["manufacturer"] = ""
            original["identity_verified"] = False
            original["identity_status"] = "ambiguous"
            original["identity_choices"] = known or choices_from_manufacturer_labels(
                mpn, labels
            )
            original["resolved_manufacturer"] = str(
                original.get("resolved_manufacturer")
                or (labels[0] if labels else "")
            )
    candidates_raw = (
        []
        if identity_blocked
        else (result.get("candidates") if isinstance(result.get("candidates"), list) else [])
    )
    discovery = result.get("discovery_metadata") if isinstance(result.get("discovery_metadata"), dict) else {}
    if identity_review_only:
        discovery = dict(discovery)
        discovery["identity_review_only"] = True
        discovery["source_identity_verified"] = False

    def _project_candidate(
        candidate: dict[str, Any],
        *,
        family_bucket: str = "relevant",
    ) -> dict[str, Any]:
        candidate_mpn = str(candidate.get("Alternative Part") or candidate.get("manufacturer_part_number") or "").strip()
        classification = str(candidate.get("Classification") or candidate.get("Category") or "Unverified candidate")
        disposition = str(candidate.get("Candidate Disposition") or "Discovery lead only")
        exact_source = bool(candidate.get("Source Identity Verified")) and not identity_review_only
        missing = [
            "datasheet-backed electrical, package, thermal, and qualification review",
        ]
        if not exact_source:
            missing.insert(0, "exact source MPN verification")
        lifecycle_status = str(candidate.get("Lifecycle") or "Unknown").strip() or "Unknown"
        lifecycle_evidence = list(
            candidate.get("Lifecycle Evidence")
            or candidate.get("lifecycle_evidence")
            or []
        )
        lifecycle_conflict = bool(
            candidate.get("Lifecycle Conflict")
            or candidate.get("lifecycle_conflict")
        )
        if family_bucket == "unfiltered":
            missing.insert(0, "component family / function match with the original part")
        elif family_bucket == "unclassified":
            missing.insert(0, "component family classification from datasheet or authorized listing")
        if lifecycle_conflict:
            missing.insert(0, "reconcile conflicting supplier lifecycle records")
        elif not lifecycle_status or lifecycle_status.casefold() in {"unknown", "not stated"}:
            missing.insert(0, "lifecycle status from authorized sources")
        fit = "supplier-listed candidate; qualification required"
        if family_bucket == "unfiltered":
            fit = "not qualified — different component family from the original"
        elif family_bucket == "unclassified":
            fit = "not qualified — component family not classified from available evidence"
        elif lifecycle_conflict or not lifecycle_status or lifecycle_status.casefold() in {"unknown", "not stated"}:
            fit = "not qualified — lifecycle evidence incomplete or conflicting"
        if identity_review_only:
            classification = "Needs verification"
            fit = "not qualified — source manufacturer identity is unverified"
            missing.insert(0, "confirm the source manufacturer against an authorized source")
        return {
            "mpn": candidate_mpn,
            "manufacturer": str(candidate.get("Manufacturer") or ""),
            "description": str(candidate.get("description") or ""),
            "rationale": (
                f"Catalog lead only. The source manufacturer identity for {mpn} is unverified; "
                "confirm it against an authorized source before assessing this lead."
                if identity_review_only
                else str(candidate.get("Recommendation") or candidate.get("Compatibility Notes") or disposition)
            ),
            "fit": fit,
            "classification": classification,
            "missing_evidence": missing,
            "evidence_class": "live-authorized-supplier" if exact_source else "missing",
            "source": str(candidate.get("Evidence Source") or candidate.get("Supplier") or ""),
            "lifecycle_status": lifecycle_status,
            "lifecycle_evidence": lifecycle_evidence,
            "lifecycle_conflict": lifecycle_conflict,
            "product_url": str(candidate.get("Product URL") or candidate.get("Source URL") or ""),
            "datasheet_url": str(candidate.get("Datasheet URL") or ""),
            "recommendation_score": candidate.get("Recommendation Score"),
            "source_identity_verified": exact_source,
            "compare_href_query": f"part_a={mpn}&part_b={candidate_mpn}",
        }

    original_for_family = {
        **original,
        "manufacturer_part_number": str(original.get("manufacturer_part_number") or mpn).strip(),
        "description": original.get("description") or "",
        "primary_category": original.get("primary_category") or original.get("Category") or "",
    }
    # Re-partition presentation rows; also surface AF-search unclassified/unfiltered leads.
    # Deduplicate by canonical MPN across all buckets while retaining per-supplier offers.
    relevant_raw: list[dict[str, Any]] = []
    unclassified_raw: list[dict[str, Any]] = []
    unfiltered_raw: list[dict[str, Any]] = []
    from src.alternative_classification import (
        classify_candidate_family_bucket,
        normalize_mpn_for_comparison,
    )

    _BUCKET_PRIORITY = {"relevant": 0, "unclassified": 1, "unfiltered": 2}
    seen_by_key: dict[str, dict[str, Any]] = {}

    def _offer_from_candidate(candidate: dict[str, Any], projected: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": projected.get("source") or str(candidate.get("Supplier") or ""),
            "product_url": projected.get("product_url") or "",
            "datasheet_url": projected.get("datasheet_url") or "",
            "lifecycle_status": projected.get("lifecycle_status") or "Unknown",
            "lifecycle_conflict": bool(projected.get("lifecycle_conflict")),
            "evidence_class": projected.get("evidence_class") or "missing",
            "recommendation_score": projected.get("recommendation_score"),
        }

    def _merge_into_existing(
        existing: dict[str, Any],
        projected: dict[str, Any],
        *,
        bucket: str,
        candidate: dict[str, Any],
    ) -> None:
        offers = list(existing.get("supplier_offers") or [])
        offer = _offer_from_candidate(candidate, projected)
        offer_key = (
            str(offer.get("source") or "").casefold(),
            str(offer.get("product_url") or "").casefold(),
        )
        if offer_key != ("", "") and not any(
            (
                str(row.get("source") or "").casefold(),
                str(row.get("product_url") or "").casefold(),
            )
            == offer_key
            for row in offers
        ):
            offers.append(offer)
        existing["supplier_offers"] = offers

        existing_life = str(existing.get("lifecycle_status") or "").strip()
        new_life = str(projected.get("lifecycle_status") or "").strip()
        known = {
            value.casefold()
            for value in (existing_life, new_life)
            if value and value.casefold() not in {"unknown", "not stated", ""}
        }
        if (
            bool(projected.get("lifecycle_conflict"))
            or bool(existing.get("lifecycle_conflict"))
            or len(known) > 1
        ):
            existing["lifecycle_conflict"] = True
            evidence = list(existing.get("lifecycle_evidence") or [])
            for item in projected.get("lifecycle_evidence") or []:
                if item not in evidence:
                    evidence.append(item)
            if existing_life and new_life and existing_life.casefold() != new_life.casefold():
                note = f"Conflicting lifecycle records: {existing_life} vs {new_life}"
                if note not in evidence:
                    evidence.append(note)
            existing["lifecycle_evidence"] = evidence
            missing = list(existing.get("missing_evidence") or [])
            conflict_note = "reconcile conflicting supplier lifecycle records"
            if conflict_note not in missing:
                missing.insert(0, conflict_note)
            existing["missing_evidence"] = missing
            existing["fit"] = "not qualified — lifecycle evidence incomplete or conflicting"

        # Prefer a more specific family bucket when the same MPN appears again.
        current_bucket = str(existing.get("_bucket") or "unclassified")
        if _BUCKET_PRIORITY.get(bucket, 9) < _BUCKET_PRIORITY.get(current_bucket, 9):
            existing["_bucket"] = bucket
            for key in (
                "fit",
                "classification",
                "rationale",
                "evidence_class",
                "source",
                "product_url",
                "datasheet_url",
                "recommendation_score",
                "source_identity_verified",
            ):
                if projected.get(key) not in (None, ""):
                    existing[key] = projected.get(key)

    def _ingest(candidate: dict[str, Any], *, force_bucket: str | None = None) -> None:
        candidate_mpn = str(
            candidate.get("Alternative Part") or candidate.get("manufacturer_part_number") or ""
        ).strip()
        key = normalize_mpn_for_comparison(candidate_mpn)
        orig_key = normalize_mpn_for_comparison(mpn)
        if not candidate_mpn or not key or key == orig_key:
            return
        family_row = {
            **candidate,
            "manufacturer_part_number": candidate_mpn,
            "description": candidate.get("description") or candidate.get("Description") or "",
            "primary_category": candidate.get("primary_category") or candidate.get("Category") or "",
            "Category": candidate.get("Category") or "",
        }
        try:
            bucket = force_bucket or classify_candidate_family_bucket(
                original_for_family, family_row
            )
        except Exception:
            bucket = "unclassified"
        if bucket not in {"relevant", "unfiltered"}:
            bucket = "unclassified"
        projected = _project_candidate(family_row, family_bucket=bucket)
        existing = seen_by_key.get(key)
        if existing is not None:
            _merge_into_existing(existing, projected, bucket=bucket, candidate=candidate)
            return
        projected["_bucket"] = bucket
        projected["supplier_offers"] = [_offer_from_candidate(candidate, projected)]
        seen_by_key[key] = projected

    for candidate in candidates_raw:
        if isinstance(candidate, dict):
            _ingest(
                candidate,
                force_bucket="unclassified" if identity_review_only else None,
            )
    for candidate in discovery.get("unclassified_leads") or []:
        if isinstance(candidate, dict):
            _ingest(candidate, force_bucket="unclassified")
    for candidate in discovery.get("unfiltered_leads") or []:
        if isinstance(candidate, dict):
            _ingest(candidate, force_bucket="unfiltered")

    for projected in seen_by_key.values():
        bucket = str(projected.pop("_bucket", "unclassified") or "unclassified")
        if bucket == "relevant":
            relevant_raw.append(projected)
        elif bucket == "unfiltered":
            unfiltered_raw.append(projected)
        else:
            unclassified_raw.append(projected)

    candidates = relevant_raw
    unclassified_leads = unclassified_raw
    unfiltered_leads = unfiltered_raw
    separated_leads = unclassified_leads or unfiltered_leads

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
    if not candidates and not separated_leads:
        missing.append("supplier-listed replacement candidates")
    elif not candidates and separated_leads:
        missing.append(
            "same-family replacement candidates (unclassified/cross-family leads were separated)"
        )
    missing.append("datasheet-backed fit scoring")

    from src.alternative_finder_state import resolve_search_outcome, search_outcome_label

    if identity_review_only:
        search_outcome = resolve_search_outcome(
            [],
            has_incomplete_evidence=True,
            discovery=discovery,
            catalog_lead_count=len(unclassified_leads) + len(unfiltered_leads),
        )
    else:
        search_outcome = str(
            status.get("search_outcome") or result.get("search_outcome") or "failure"
        )
    return {
        "status": str(status.get("status") or result.get("status") or "failed"),
        "search_outcome": search_outcome,
        "search_outcome_label": str(
            status.get("search_outcome_label")
            or result.get("search_outcome_label")
            or search_outcome_label(search_outcome)
        ),
        "requested_mpn": str(mpn).strip(),
        "identity_review_only": bool(original.get("identity_review_only")),
        "original": {
            "mpn": str(original.get("manufacturer_part_number") or mpn).strip(),
            "manufacturer": str(original.get("manufacturer") or ""),
            "description": str(original.get("description") or ""),
            "lifecycle_status": str(original.get("lifecycle_status") or "Unknown"),
            "lifecycle_evidence": list(original.get("lifecycle_evidence") or []),
            "lifecycle_conflict": bool(original.get("lifecycle_conflict")),
            "source": str(original.get("source") or ""),
            "supplier_data_verified": bool(original.get("supplier_data_verified")),
            "identity_status": str(original.get("identity_status") or ""),
            "identity_verified": bool(original.get("identity_verified")),
            "identity_review_only": bool(original.get("identity_review_only")),
            "requested_manufacturer": str(original.get("requested_manufacturer") or ""),
            "resolved_manufacturer": str(original.get("resolved_manufacturer") or ""),
            "identity_choices": list(original.get("identity_choices") or []),
            "all_supplier_results": list(original.get("all_supplier_results") or []),
            "risk": result.get("original_risk") if isinstance(result.get("original_risk"), dict) else {},
        },
        "candidates": candidates,
        "unclassified_leads": unclassified_leads,
        "unfiltered_leads": unfiltered_leads,
        "discovery": discovery,
        "missing_evidence": missing,
        "mode": "legacy-supplier-engine",
        "live_lookups_enabled": configured_supplier_count() > 0,
        "gap": (
            "Candidate parts are research leads, not approved substitutes. Confirm identity, electrical limits, package, lifecycle, and qualification requirements against current manufacturer documentation."
            if candidates or separated_leads
            else "No verified replacement was found in this search. Check current manufacturer documentation and authorized distributors before changing the design."
        ),
    }
