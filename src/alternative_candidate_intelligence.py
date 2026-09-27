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


def build_alternative_candidate_insight(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Build useful inline evidence without inferring unsupported compatibility."""
    score = max(0, min(100, int(round(_number(candidate.get("Recommendation Score"))))))
    engineering_confidence = max(0, min(100, int(round(_number(
        candidate.get("Engineering Comparison Confidence"),
        _number(candidate.get("Drop-In Confidence")),
    )))))
    supplier_confidence = max(0, min(100, int(round(_number(
        candidate.get("Supplier Relationship Confidence")
    )))))
    stock = max(0, int(round(_number(candidate.get("Stock")))))
    lifecycle = _text(candidate, "Lifecycle", "Lifecycle Status", fallback="Unknown")
    evidence_summary = _text(candidate, "Engineering Evidence Summary")
    recommendation = _text(candidate, "Recommendation")
    rank_explanation = evidence_summary or recommendation or (
        f"Ranked {score}/100 from the available compatibility, lifecycle, "
        "availability, and supplier evidence."
    )

    verification_gaps = _comparison_gaps(candidate)
    lifecycle_normalized = lifecycle.casefold()
    if lifecycle_normalized in {"unknown", "not available", "unverified"}:
        verification_gaps.append("Confirm the manufacturer lifecycle status.")
    elif any(marker in lifecycle_normalized for marker in (
        "obsolete", "end of life", "eol", "not for new designs", "nfnd"
    )):
        verification_gaps.append(
            f"Review lifecycle suitability because this candidate is {lifecycle}."
        )
    if stock <= 0:
        verification_gaps.append("Confirm procurable stock before qualification.")

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
            f"{engineering_confidence}%" if engineering_confidence else "Not verified"
        ),
        "supplier_confidence": supplier_confidence,
        "supplier_confidence_label": (
            f"{supplier_confidence}%" if supplier_confidence else "Not verified"
        ),
        "stock": stock,
        "stock_label": f"{stock:,}" if stock else "No confirmed stock",
        "lifecycle": lifecycle,
        "rank_explanation": rank_explanation,
        "supplier_summary": _text(candidate, "Supplier Relationship Summary"),
        "verification_gaps": unique_gaps[:4],
        "next_action": next_action,
    }
