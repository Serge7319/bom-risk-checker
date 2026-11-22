"""Evidence-aware component risk scoring shared by BOM workflows."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from integrations.stock_coercion import parse_stock_total
from src.normalizer import normalize_part_number


_AUTHORIZED_SOURCES = {
    "digikey", "digikeyelectronics", "mouser", "mouserelectronics",
    "newark", "element14", "farnell", "nexarsupply",
}


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _truthy(value: Any) -> bool:
    return value is True or str(value or "").strip().casefold() in {"1", "true", "yes"}


def _aware_timestamp(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _authorized_source(value: Any) -> bool:
    import re

    parts = re.split(r"[,;/|]", str(value or ""))
    return any(
        re.sub(r"[^a-z0-9]+", "", item.casefold()) in _AUTHORIZED_SOURCES
        for item in parts
        if item.strip()
    )


def _prepare_evidence_row(part_data: dict[str, Any]) -> dict[str, Any]:
    """Adapt a fresh exact supplier response to the saved evidence contract.

    The supplier aggregator returns a provider name as ``source``. Saved rows
    use an explicit evidence class. Promote the identity label only when the
    response itself proves an exact MPN, a recognized provider, and a
    timezone-aware retrieval timestamp.
    """
    row = dict(part_data)
    requested = str(
        row.get("MPN") or row.get("mpn") or row.get("requested_mpn")
        or row.get("searched_part_number") or ""
    ).strip()
    returned = str(
        row.get("manufacturer_part_number") or row.get("Manufacturer Part Number") or ""
    ).strip()
    source = str(row.get("source") or row.get("Supplier") or row.get("Best Source") or "").strip()
    exact_identity = bool(
        _truthy(row.get("supplier_data_verified"))
        and requested
        and returned
        and normalize_part_number(requested) == normalize_part_number(returned)
        and _authorized_source(source)
        and _aware_timestamp(row.get("retrieved_at") or row.get("Sourcing Updated At"))
        and str(row.get("provider_status") or "AVAILABLE").strip().upper() == "AVAILABLE"
    )
    if exact_identity and not str(row.get("evidence_source") or row.get("identity_source") or "").strip():
        row["MPN"] = requested
        row["manufacturer_part_number"] = returned
        row["identity_source"] = "live-authorized-supplier"
        row["evidence_source"] = "live-authorized-supplier"
    return row


def _field_evidence(part_data: dict[str, Any]) -> dict[str, Any]:
    from apps.api.evidence_contract import classify_part_evidence

    row = _prepare_evidence_row(part_data)
    # Saved envelopes are useful display snapshots but may predate the current
    # verification rules. Rebuild them from the row's exact supplier records
    # before using any value to score risk.
    return classify_part_evidence(row)


def _coverage_complete(part_data: dict[str, Any]) -> tuple[bool, int]:
    """Require multiple configured lookups and zero provider failures."""
    provider_health = part_data.get("provider_health")
    if isinstance(provider_health, dict):
        try:
            configured = int(provider_health.get("configured_count") or 0)
            failed = int(provider_health.get("failed_count") or 0)
            responded = int(provider_health.get("responded_count") or 0)
        except (TypeError, ValueError):
            return False, 0
        return configured >= 2 and failed == 0 and responded == configured, configured

    query_rows = (
        part_data.get("Supplier Query Details")
        or part_data.get("supplier_query_details")
        or part_data.get("all_supplier_results")
        or []
    )
    if isinstance(query_rows, dict):
        query_rows = [query_rows]
    if not isinstance(query_rows, list):
        return False, 0
    sources: set[str] = set()
    failed = False
    for item in query_rows:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        key = "".join(character for character in source.casefold() if character.isalnum())
        status = str(item.get("status") or item.get("provider_status") or "").strip().casefold()
        if key in _AUTHORIZED_SOURCES and status not in {"not_configured", "not configured"}:
            sources.add(key)
        if status in {"error", "timeout", "unavailable", "not_configured"}:
            failed = True
    complete_flag = _truthy(
        part_data.get("Supplier Coverage Complete", part_data.get("supplier_coverage_complete"))
    )
    return len(sources) >= 2 and complete_flag and not failed, len(sources)


def _stock_value(part_data: dict[str, Any]) -> int | None:
    """Return the validated exact-part stock total, when the evidence allows it."""
    fields = _field_evidence(part_data).get("fields") or {}
    stock_field = fields.get("stock") if isinstance(fields.get("stock"), dict) else {}
    if stock_field.get("evidence_class") != "live-authorized-supplier":
        return None
    if not _truthy(part_data.get("Stock Data Complete", part_data.get("stock_data_complete"))):
        return None
    value = stock_field.get("observed_total")
    if value is None:
        value = stock_field.get("reported_value")
    return parse_stock_total(value)


def calculate_risk(part_data: dict) -> dict:
    """Score only exact, timestamped supplier evidence.

    Missing fields and incomplete provider coverage never become low risk,
    obsolescence, stockout, or supplier concentration. Positive risk findings
    remain actionable when verified; a clean result is shown as Low only when
    lifecycle, complete inventory, and multi-provider coverage were all
    actually assessed.
    """
    part_data = part_data if isinstance(part_data, dict) else {}
    envelope = _field_evidence(part_data)
    fields = envelope.get("fields") if isinstance(envelope.get("fields"), dict) else {}
    lifecycle_field = fields.get("lifecycle") if isinstance(fields.get("lifecycle"), dict) else {}
    stock_field = fields.get("stock") if isinstance(fields.get("stock"), dict) else {}
    lead_field = fields.get("lead_time") if isinstance(fields.get("lead_time"), dict) else {}

    score = 0
    factor_points = {"Lifecycle": 0, "Stock": 0, "Lead time": 0}
    reasons: list[str] = []
    evidence_count = 0
    lifecycle_live = lifecycle_field.get("evidence_class") == "live-authorized-supplier"
    lifecycle_status = ""
    if lifecycle_live:
        lifecycle_status = str(
            part_data.get("Lifecycle") or part_data.get("lifecycle_status")
            or part_data.get("Lifecycle Status") or ""
        ).strip()
        lifecycle_text = lifecycle_status.casefold().replace("_", " ")
        evidence_count += 1
        if lifecycle_field.get("conflict") or "conflicting supplier data" in lifecycle_text:
            score += 35
            factor_points["Lifecycle"] += 35
            reasons.append("Authorized supplier lifecycle records conflict; confirm with the manufacturer")
        elif any(term in lifecycle_text for term in ("obsolete", "end of life", "eol", "discontinued")):
            score += 50
            factor_points["Lifecycle"] += 50
            reasons.append("Exact-part supplier evidence marks this part end-of-life or obsolete")
        elif "not recommended" in lifecycle_text or "nrnd" in lifecycle_text:
            score += 35
            factor_points["Lifecycle"] += 35
            reasons.append("Exact-part supplier evidence marks this part not recommended for new designs")
        elif "replacement suggested" in lifecycle_text:
            score += 20
            factor_points["Lifecycle"] += 20
            reasons.append("Exact-part supplier evidence suggests a replacement part")
        elif "factory special order" in lifecycle_text:
            score += 20
            factor_points["Lifecycle"] += 20
            reasons.append("Exact-part supplier evidence identifies factory special order")
    elif str(part_data.get("lifecycle_status") or part_data.get("Lifecycle Status") or "").strip():
        reasons.append("Lifecycle value is recorded but lacks verified exact-part supplier provenance")

    stock_complete = _truthy(
        part_data.get("Stock Data Complete", part_data.get("stock_data_complete"))
    )
    stock_total = _stock_value(part_data)
    quantity = _number(part_data.get("Effective Quantity", part_data.get("effective_quantity", part_data.get("Quantity", part_data.get("quantity")))))
    stock_live = stock_field.get("evidence_class") == "live-authorized-supplier"
    if stock_live and stock_complete and stock_total is not None:
        evidence_count += 1
        if stock_total == 0:
            score += 45
            factor_points["Stock"] += 45
            reasons.append("No on-hand stock was reported across the checked exact-part supplier sources")
        elif quantity is not None and quantity > 0 and stock_total < quantity:
            shortage_ratio = stock_total / quantity
            if shortage_ratio < 0.25:
                score += 35
                factor_points["Stock"] += 35
                reasons.append("Severe verified stock shortage relative to BOM quantity")
            elif shortage_ratio < 0.5:
                score += 25
                factor_points["Stock"] += 25
                reasons.append("Moderate verified stock shortage relative to BOM quantity")
            else:
                score += 15
                factor_points["Stock"] += 15
                reasons.append("Verified stock is below BOM quantity")
    elif stock_field.get("evidence_class") == "live-authorized-supplier" and not stock_complete:
        reasons.append("Exact-part inventory readings are partial; BOM quantity coverage is not confirmed")
    elif part_data.get("stock_total") not in (None, "") or part_data.get("stock_available") not in (None, ""):
        reasons.append("Stock value is recorded but lacks verified exact-part supplier provenance")

    supplier_count = _number(
        part_data.get("Supplier Count", part_data.get("supplier_count"))
    )
    coverage_complete, configured_count = _coverage_complete(part_data)
    identity_field = fields.get("identity") if isinstance(fields.get("identity"), dict) else {}
    identity_live = identity_field.get("evidence_class") == "live-authorized-supplier"
    if supplier_count is not None and supplier_count == 0 and coverage_complete:
        evidence_count += 1
        score += 35
        reasons.append("No exact-part listing was found across completed configured supplier checks")
    elif supplier_count is not None and supplier_count > 0 and coverage_complete and identity_live:
        evidence_count += 1
        if supplier_count == 1:
            score += 25
            reasons.append("Only one checked supplier returned this exact part")
        elif supplier_count == 2:
            if stock_total is not None and quantity is not None and stock_total < quantity:
                score += 15
                reasons.append("Two checked suppliers returned this part with inventory below BOM demand")
            else:
                score += 5
                reasons.append("Only two checked suppliers returned this exact part")
    elif supplier_count is not None and supplier_count <= 2:
        reasons.append(
            "Supplier concentration is not assessed because multi-provider lookup coverage is incomplete"
        )

    lead_time_value = _number(
        part_data.get("Lead Time Weeks", part_data.get("lead_time_weeks"))
    )
    lead_live = lead_field.get("evidence_class") == "live-authorized-supplier"
    if lead_live and lead_time_value is not None and lead_time_value >= 0:
        evidence_count += 1
        if lead_time_value >= 52:
            score += 35
            factor_points["Lead time"] += 35
            reasons.append("Verified manufacturer lead time is at least 52 weeks")
        elif lead_time_value >= 26:
            score += 30
            factor_points["Lead time"] += 30
            reasons.append("Verified manufacturer lead time is 26 weeks or longer")
        elif lead_time_value >= 12:
            score += 15
            factor_points["Lead time"] += 15
            reasons.append("Verified manufacturer lead time is 12 weeks or longer")
        elif lead_time_value >= 8:
            score += 10
            factor_points["Lead time"] += 10
            reasons.append("Verified manufacturer lead time is 8 weeks or longer")
    elif part_data.get("lead_time_weeks") not in (None, ""):
        reasons.append("Lead time is recorded but lacks a matching timestamped supplier field record")

    score = min(score, 100)
    clean_assessment_complete = bool(
        lifecycle_live and stock_live and stock_complete and coverage_complete
        and identity_live
        and configured_count >= 2 and quantity is not None and quantity > 0
    )
    if score >= 60:
        risk_level = "High"
    elif score >= 30:
        risk_level = "Medium"
    elif evidence_count and clean_assessment_complete:
        risk_level = "Low"
    else:
        risk_level = "Needs verification"

    assessed_score = score if evidence_count and (score > 0 or clean_assessment_complete) else None
    assessment_basis_note = str(part_data.get("assessment_basis_note") or "").strip()
    if assessment_basis_note and assessment_basis_note not in reasons:
        reasons.append(assessment_basis_note)

    return {
        "risk_score": assessed_score,
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "evidence_count": evidence_count,
        "evidence_coverage_complete": clean_assessment_complete,
        "supplier_coverage_complete": coverage_complete,
        "factor_points": factor_points,
    }


def recorded_supply_factors(part_data: dict) -> list[dict]:
    """Expose only supply factors backed by the same verified field rules."""
    if not isinstance(part_data, dict):
        return []
    assessment = calculate_risk(part_data)
    score_by_factor = assessment.get("factor_points") or {}

    envelope = _field_evidence(part_data)
    fields = envelope.get("fields") or {}
    candidates = (
        ("Lifecycle", "lifecycle", "Lifecycle Status", "lifecycle_status", "lifecycle_source"),
        ("Stock", "stock", "Stock Available", "stock_available", "stock_source"),
        ("Lead time", "lead_time", "Lead Time Weeks", "lead_time_weeks", "lead_time_source"),
    )
    output = []
    for label, field_key, display_key, value_key, source_key in candidates:
        field = fields.get(field_key) if isinstance(fields.get(field_key), dict) else {}
        if field.get("evidence_class") != "live-authorized-supplier":
            continue
        recorded = part_data.get(display_key, part_data.get(value_key))
        if field_key == "stock" and recorded in (None, ""):
            recorded = field.get("observed_total")
        if recorded in (None, ""):
            continue
        score = int(score_by_factor.get(label, 0))
        output.append({
            "factor": label,
            "recorded": f"{recorded}{' weeks' if label == 'Lead time' else ''}",
            "source": str(field.get("source") or part_data.get(source_key) or part_data.get("source") or ""),
            "reasons": [reason for reason in assessment["risk_reasons"] if label.casefold() in reason.casefold()],
            "points": score,
        })
    return output
