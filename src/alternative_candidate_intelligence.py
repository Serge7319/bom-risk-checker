"""Concise, evidence-bound intelligence for expandable Alternative Finder rows."""
from __future__ import annotations

from typing import Any, Mapping


_EMPTY_VALUES = {"", "none", "nan", "null", "nat", "n/a", "—"}


def _text(candidate: Mapping[str, Any], *keys: str, fallback: str = "") -> str:
    for key in keys:
        value = candidate.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.casefold() not in _EMPTY_VALUES:
            return text
    return fallback


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return fallback


def _comparison_gaps(candidate: Mapping[str, Any]) -> list[str]:
    rows = candidate.get("Comparison Rows") or []
    if not isinstance(rows, (list, tuple)):
        return []
    gaps: list[str] = []
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        attribute = _text(raw_row, "Attribute", "attribute")
        status = _text(raw_row, "Status", "status").casefold()
        original = _text(raw_row, "Original", "original", fallback="not available")
        replacement = _text(raw_row, "Candidate", "candidate", fallback="not available")
        if not attribute or status in {"match", "confirmed", "pass", "same"}:
            continue
        if status in {"different", "mismatch", "fail"}:
            gaps.append(f"{attribute} differs: original {original}; candidate {replacement}.")
        elif status in {"needs data", "unknown", "missing", "not verified", "review"}:
            gaps.append(f"Verify {attribute.lower()}; retrieved evidence is incomplete.")
    return gaps


def supplier_evidence_row(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize distributor rows for the shared, field-by-field evidence rules."""
    row = dict(candidate)
    mpn = _text(row, "MPN", "mpn", "manufacturer_part_number", "Alternative Part")
    if mpn:
        row.setdefault("MPN", mpn)
        row.setdefault("manufacturer_part_number", mpn)
    if row.get("supplier_data_verified"):
        row.setdefault("identity_source", "live-authorized-supplier")
        row.setdefault("evidence_source", "live-authorized-supplier")
    return row


def build_alternative_candidate_insight(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Build useful inline evidence without inferring unsupported compatibility."""
    from apps.api.evidence_contract import EVIDENCE_LIVE, classify_part_evidence

    score = max(0, min(100, int(round(_number(candidate.get("Recommendation Score"))))))
    engineering_confidence = max(0, min(100, int(round(_number(
        candidate.get("Engineering Comparison Confidence"),
        _number(candidate.get("Drop-In Confidence")),
    )))))
    supplier_confidence = max(0, min(100, int(round(_number(
        candidate.get("Supplier Relationship Confidence")
    )))))
    evidence_row = supplier_evidence_row(candidate)
    envelope = classify_part_evidence(evidence_row)
    fields = envelope.get("fields") if isinstance(envelope.get("fields"), Mapping) else {}
    stock_evidence = fields.get("stock") if isinstance(fields.get("stock"), Mapping) else {}
    price_evidence = fields.get("price") if isinstance(fields.get("price"), Mapping) else {}
    lifecycle_evidence = fields.get("lifecycle") if isinstance(fields.get("lifecycle"), Mapping) else {}

    stock_value = stock_evidence.get("observed_total")
    stock_verified = bool(
        stock_evidence.get("evidence_class") == EVIDENCE_LIVE
        and stock_evidence.get("current") is True
        and stock_value is not None
    )
    stock = max(0, int(round(_number(stock_value)))) if stock_verified else None
    if stock_verified:
        stock_label = f"{stock:,} reported by supplier API"
        if stock_evidence.get("complete") is not True:
            stock_label += " (supplier coverage incomplete; checkout availability not verified)"
    else:
        stock_label = "Not verified"

    price_value = price_evidence.get("reported_value")
    price_verified = bool(
        price_evidence.get("evidence_class") == EVIDENCE_LIVE
        and price_evidence.get("current") is True
        and price_evidence.get("quantity_break_applies") is True
    )
    if price_verified:
        currency = _text(price_evidence, "currency", fallback="")
        price_label = (
            f"{currency} {_number(price_value):.4g} per unit"
            if currency else "Not verified"
        )
    elif price_evidence.get("evidence_class") == EVIDENCE_LIVE and price_value is not None:
        price_label = "Supplier price break; quantity not verified"
    else:
        price_label = "Not verified"

    lifecycle_value = _text(candidate, "Lifecycle", "Lifecycle Status", fallback="Unknown")
    lifecycle_verified = bool(
        lifecycle_evidence.get("evidence_class") == EVIDENCE_LIVE
        and lifecycle_evidence.get("current") is True
    )
    lifecycle = lifecycle_value if lifecycle_verified else "Needs verification"
    evidence_summary = _text(candidate, "Engineering Evidence Summary")
    recommendation = _text(candidate, "Recommendation")
    comparison_assessment = candidate.get("Engineering Evidence Assessment")
    comparison_assessment = comparison_assessment if isinstance(comparison_assessment, Mapping) else {}
    comparison_counts = {
        "matches": max(0, int(_number(comparison_assessment.get("matches")))),
        "differences": max(0, int(_number(comparison_assessment.get("differences")))),
        "needs_data": max(0, int(_number(comparison_assessment.get("needs_data")))),
        "compared_fields": max(0, int(_number(comparison_assessment.get("compared_fields")))),
    }
    rank_explanation = evidence_summary or recommendation or (
        "This rule-based screening rank orders candidates for review; it is not a compatibility probability or approval."
    )

    verification_gaps = _comparison_gaps(candidate)
    lifecycle_normalized = lifecycle.casefold()
    if lifecycle_normalized in {"unknown", "not available", "unverified", "needs verification"}:
        verification_gaps.append("Confirm the manufacturer lifecycle status.")
    elif any(marker in lifecycle_normalized for marker in (
        "obsolete", "end of life", "eol", "not for new designs", "nfnd"
    )):
        verification_gaps.append(
            f"Review lifecycle suitability because this candidate is {lifecycle}."
        )
    if not stock_verified:
        verification_gaps.append("Supplier inventory is not verified for this exact candidate.")
    elif stock == 0:
        verification_gaps.append("Confirm procurable stock before qualification.")
    if not price_verified:
        verification_gaps.append(
            str(price_evidence.get("gap") or "A current price applicable to the required quantity is not verified.")
        )

    unique_gaps: list[str] = []
    seen: set[str] = set()
    for gap in verification_gaps:
        token = gap.casefold()
        if token not in seen:
            seen.add(token)
            unique_gaps.append(gap)

    if unique_gaps:
        next_action = unique_gaps[0]
    elif engineering_confidence < 75:
        next_action = "Complete the missing engineering comparison before approving this candidate."
    else:
        next_action = (
            "Review the detailed comparison, then document footprint, electrical, "
            "and circuit qualification before approval."
        )

    return {
        "score": score,
        "engineering_confidence": engineering_confidence,
        "engineering_confidence_label": (
            (
                f"{comparison_counts['matches']} match · "
                f"{comparison_counts['differences']} differ · "
                f"{comparison_counts['needs_data']} need verification"
            )
            if comparison_counts["compared_fields"]
            else "Insufficient comparison data"
        ),
        "supplier_confidence": supplier_confidence,
        "supplier_confidence_label": (
            "Supplier relationship recorded" if supplier_confidence else "No exact relationship recorded"
        ),
        "stock": stock,
        "stock_label": stock_label,
        "stock_verified": stock_verified,
        "price_label": price_label,
        "price_verified": price_verified,
        "lifecycle": lifecycle,
        "lifecycle_verified": lifecycle_verified,
        "evidence": envelope,
        "comparison_counts": comparison_counts,
        "rank_explanation": rank_explanation,
        "supplier_summary": _text(candidate, "Supplier Relationship Summary"),
        "verification_gaps": unique_gaps[:4],
        "next_action": next_action,
    }
