"""Evidence-aware component risk scoring shared by public and signed-in BOMs."""

from __future__ import annotations

import math
from typing import Any

from integrations.stock_coercion import parse_stock_total


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _stock_value(part_data: dict) -> int | None:
    """Prefer summed, exact-match supplier evidence, then the selected source."""
    if part_data.get("total_market_stock") not in (None, ""):
        value = parse_stock_total(part_data.get("total_market_stock"))
        if value is not None:
            return value
    for key in ("stock_total", "stock_available", "Stock Available", "Stock"):
        if key in part_data:
            value = parse_stock_total(part_data.get(key))
            if value is not None:
                return value
    return None


def calculate_risk(part_data: dict) -> dict:
    """Score only recorded evidence; report unassessed parts as such.

    Missing stock/lifecycle data is not a stockout or an obsolete component.
    Alternate-part risk is not scored here because supplier result absence does
    not prove that a complete, qualified alternate search was performed.
    """
    part_data = part_data if isinstance(part_data, dict) else {}
    score = 0
    reasons: list[str] = []
    evidence_count = 0

    lifecycle_status = str(part_data.get("lifecycle_status") or "").strip()
    lifecycle_text = lifecycle_status.casefold().replace("_", " ")
    lifecycle_known = lifecycle_text not in {
        "", "unknown", "unverified", "n/a", "not available",
    }
    if part_data.get("lifecycle_conflict") or "conflicting supplier data" in lifecycle_text:
        evidence_count += 1
        score += 35
        reasons.append("Supplier lifecycle records conflict; confirm with the manufacturer")
    elif lifecycle_known:
        evidence_count += 1
        if any(term in lifecycle_text for term in ("obsolete", "end of life", "eol", "discontinued")):
            score += 50
            reasons.append("Part is end-of-life or obsolete")
        elif "not recommended" in lifecycle_text or "nrnd" in lifecycle_text:
            score += 35
            reasons.append("Part is not recommended for new designs")
        elif "replacement suggested" in lifecycle_text:
            score += 20
            reasons.append("Supplier suggests a replacement part")
        elif "factory special order" in lifecycle_text:
            score += 20
            reasons.append("Part requires factory special order")

    stock_total = _stock_value(part_data)
    quantity = _number(part_data.get("quantity"))
    if stock_total is not None:
        stock_complete = bool(part_data.get("stock_data_complete", True))
        if stock_complete:
            evidence_count += 1
            if stock_total == 0:
                score += 45
                reasons.append("No on-hand stock was reported across matched suppliers")
            elif quantity is not None and quantity > 0 and stock_total < quantity:
                shortage_ratio = stock_total / quantity
                if shortage_ratio < 0.25:
                    score += 35
                    reasons.append("Severe stock shortage relative to BOM quantity")
                elif shortage_ratio < 0.5:
                    score += 25
                    reasons.append("Moderate stock shortage relative to BOM quantity")
                else:
                    score += 15
                    reasons.append("Reported stock is below BOM quantity")
        else:
            reasons.append("Reported inventory is partial and cannot confirm BOM coverage")

    supplier_count = _number(part_data.get("supplier_count"))
    if supplier_count is not None and supplier_count > 0:
        coverage = part_data.get("provider_health")
        # A supplier count without provider coverage does not say how much of
        # the configured market was checked, so it cannot support a
        # single-source or diversity claim.
        coverage_complete = False
        enough_sources_checked = False
        if isinstance(coverage, dict):
            try:
                coverage_complete = int(coverage.get("failed_count") or 0) == 0
                enough_sources_checked = int(coverage.get("configured_count") or 0) >= 2
            except (TypeError, ValueError):
                coverage_complete = False
                enough_sources_checked = False
        if coverage_complete and enough_sources_checked:
            evidence_count += 1
            if supplier_count == 1:
                score += 25
                reasons.append("Only one checked supplier lists this part")
            elif supplier_count == 2:
                if stock_total is not None and quantity is not None and stock_total < quantity:
                    score += 15
                    reasons.append("Two checked suppliers with inventory below BOM quantity")
                else:
                    score += 5
                    reasons.append("Only two checked suppliers list this part")
        elif supplier_count <= 2:
            coverage = part_data.get("provider_health")
            if isinstance(coverage, dict) and coverage_complete and not enough_sources_checked:
                reasons.append("Supplier concentration is not assessed because fewer than two supplier sources are configured")
            else:
                reasons.append("Supplier concentration is not assessed because source coverage is incomplete")

    lead_time = _number(part_data.get("lead_time_weeks"))
    if lead_time is not None and lead_time >= 0:
        evidence_count += 1
        if lead_time >= 52:
            score += 35
            reasons.append("Reported manufacturer lead time is at least 52 weeks")
        elif lead_time >= 26:
            score += 25
            reasons.append("Reported manufacturer lead time is 26 weeks or longer")
        elif lead_time >= 12:
            score += 15
            reasons.append("Reported manufacturer lead time is 12 weeks or longer")
        elif lead_time >= 8:
            score += 10
            reasons.append("Reported manufacturer lead time is 8 weeks or longer")

    score = min(score, 100)
    if evidence_count == 0:
        risk_level = "Needs verification"
    elif score >= 60:
        risk_level = "High"
    elif score >= 30:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    # Preserve qualified-variant provenance in the same risk explanation used
    # by authenticated, one-time, and public BOM reports. This note is
    # informative only; it does not add evidence or change the score.
    assessment_basis_note = str(part_data.get("assessment_basis_note") or "").strip()
    if assessment_basis_note and assessment_basis_note not in reasons:
        reasons.append(assessment_basis_note)

    return {
        "risk_score": score if evidence_count else None,
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "evidence_count": evidence_count,
    }


def recorded_supply_factors(part_data: dict) -> list[dict]:
    """Apply risk thresholds only to fields this record actually contains."""
    if not isinstance(part_data, dict):
        return []
    factors = []

    def _factor(overrides: dict, label: str, recorded: str, source: str) -> None:
        scored = calculate_risk({**overrides, "quantity": part_data.get("quantity") or 0})
        reasons = list(scored["risk_reasons"])
        points = int(scored["risk_score"] or 0)
        factors.append({
            "factor": label,
            "recorded": recorded,
            "source": source,
            "reasons": reasons,
            "points": points,
        })

    lifecycle = str(part_data.get("lifecycle_status") or "").strip()
    if lifecycle and lifecycle.casefold() not in {"unknown", "unverified", "n/a"}:
        _factor(
            {"lifecycle_status": lifecycle, "lifecycle_conflict": part_data.get("lifecycle_conflict")},
            "Lifecycle", lifecycle,
            str(part_data.get("lifecycle_status_source") or part_data.get("source") or ""),
        )

    stock = _stock_value(part_data)
    if stock is not None:
        _factor(
            {
                "stock_total": stock,
                "stock_data_complete": part_data.get("stock_data_complete", True),
            }, "Stock", str(stock),
            str(part_data.get("stock_source") or part_data.get("source") or ""),
        )

    lead = _number(part_data.get("lead_time_weeks"))
    if lead is not None:
        _factor(
            {"lead_time_weeks": lead}, "Lead time", f"{lead:g} weeks",
            str(part_data.get("lead_time_source") or part_data.get("source") or ""),
        )
    return factors
