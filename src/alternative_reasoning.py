"""Cadivor Milestone 12.2 — Smarter Alternative Recommendation Reasoning."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    result = str(value).strip()
    return result or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except Exception:
        return default


def _normalize(value: Any) -> str:
    return _text(value).lower().replace("_", " ").strip()


def _same_text(left: Any, right: Any) -> bool:
    left_value = _normalize(left)
    right_value = _normalize(right)
    return bool(left_value and right_value and left_value == right_value)


def _normalize_package(value: Any) -> str:
    """Match the ranking engine's canonical package compatibility contract."""
    package = _text(value).upper().replace(" ", "-")
    if not package:
        return ""
    if any(term in package for term in ("PDIP", "NPDIP", "DIP")):
        for pin_count in ("16", "14", "8", "4"):
            if pin_count in package:
                return f"DIP-{pin_count}"
    if "TO-220" in package:
        return "TO-220"
    if "SOT-223" in package:
        return "SOT-223"
    if "SOIC" in package and "8" in package:
        return "SOIC-8"
    if "SOIC" in package and "14" in package:
        return "SOIC-14"
    return package


def _parse_voltage_range(value: Any) -> tuple[float | None, float | None]:
    text = _text(value).lower().replace("v", " ").replace("to", "-")
    numbers: List[float] = []
    current = ""
    for char in text:
        if char.isdigit() or char == ".":
            current += char
        elif current:
            try:
                numbers.append(float(current))
            except Exception:
                pass
            current = ""
    if current:
        try:
            numbers.append(float(current))
        except Exception:
            pass
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return min(numbers), max(numbers)


def build_alternative_reasoning(
    *,
    original_part: str,
    original_data: Dict[str, Any],
    candidate: Dict[str, Any],
    recommendation_score: int,
    compatibility_confidence: int,
    engineering_matches: Iterable[str],
    warnings: Iterable[str],
    stock_delta: str,
    price_delta: str,
) -> Dict[str, Any]:
    matches = list(engineering_matches or [])
    warning_items = list(warnings or [])

    original_package = _text(
        original_data.get("package")
        or original_data.get("Package")
        or original_data.get("case_package")
    )
    candidate_package = _text(
        candidate.get("Package")
        or candidate.get("package")
        or candidate.get("Case Package")
    )

    original_pins = int(
        _number(
            original_data.get("pin_count")
            or original_data.get("Pin Count")
            or original_data.get("pins"),
            0,
        )
    )
    candidate_pins = int(
        _number(
            candidate.get("Pin Count")
            or candidate.get("pin_count")
            or candidate.get("Pins"),
            0,
        )
    )

    original_architecture = _text(
        original_data.get("architecture")
        or original_data.get("Architecture")
        or original_data.get("category")
    )
    candidate_architecture = _text(
        candidate.get("Architecture")
        or candidate.get("architecture")
        or candidate.get("Category")
    )

    original_voltage = _text(
        original_data.get("voltage_range")
        or original_data.get("Voltage Range")
        or original_data.get("supply_voltage")
    )
    candidate_voltage = _text(
        candidate.get("Voltage Range")
        or candidate.get("voltage_range")
        or candidate.get("Supply Voltage")
    )

    lifecycle = _text(candidate.get("Lifecycle"), "Unknown")
    estimated_risk = _text(candidate.get("Estimated Risk"), "Unknown")
    stock = int(_number(candidate.get("Stock"), 0))
    unit_price = _number(candidate.get("Unit Price"), 0)

    blockers: List[str] = []
    verification: List[str] = []
    confirmed: List[str] = []

    original_package_normalized = _normalize_package(original_package)
    candidate_package_normalized = _normalize_package(candidate_package)
    package_match = bool(
        original_package_normalized
        and candidate_package_normalized
        and original_package_normalized == candidate_package_normalized
    )
    if original_package and candidate_package:
        if package_match:
            confirmed.append(
                f"Package matches the original: {candidate_package} "
                f"({candidate_package_normalized})."
            )
        else:
            blockers.append(
                f"Package differs: original {original_package}, candidate {candidate_package}."
            )
    else:
        verification.append("Verify package and PCB footprint compatibility.")

    if original_pins and candidate_pins:
        if original_pins == candidate_pins:
            confirmed.append(f"Pin count matches at {candidate_pins}.")
        else:
            blockers.append(
                f"Pin count differs: original {original_pins}, candidate {candidate_pins}."
            )
    else:
        verification.append("Verify pin count and pin assignment.")

    if original_architecture and candidate_architecture:
        if _same_text(original_architecture, candidate_architecture):
            confirmed.append(
                f"Architecture matches: {candidate_architecture}."
            )
        else:
            blockers.append(
                f"Architecture differs: original {original_architecture}, "
                f"candidate {candidate_architecture}."
            )
    else:
        verification.append("Confirm architecture and functional equivalence.")

    original_low, original_high = _parse_voltage_range(original_voltage)
    candidate_low, candidate_high = _parse_voltage_range(candidate_voltage)
    if (
        original_low is not None
        and original_high is not None
        and candidate_low is not None
        and candidate_high is not None
    ):
        if candidate_low <= original_low and candidate_high >= original_high:
            confirmed.append(
                f"Candidate voltage range covers the original operating range."
            )
        else:
            blockers.append(
                "Candidate voltage range does not fully cover the original operating range."
            )
    else:
        verification.append("Verify operating and absolute maximum voltage limits.")

    if lifecycle.lower() == "active":
        confirmed.append("Candidate lifecycle is active.")
    else:
        verification.append(f"Review lifecycle status: {lifecycle}.")

    if stock <= 0:
        blockers.append("No confirmed stock is currently available.")
    elif stock < 100:
        verification.append(
            f"Only {stock:,} units are currently recorded; confirm build coverage."
        )
    else:
        confirmed.append(f"{stock:,} units are currently recorded.")

    if estimated_risk.lower() == "high":
        blockers.append("Candidate is classified as high engineering risk.")
    elif estimated_risk.lower() == "medium":
        verification.append("Candidate requires focused engineering review.")

    for warning in warning_items:
        if warning and warning not in verification and warning not in blockers:
            verification.append(str(warning))

    for match in matches:
        if match and match not in confirmed:
            confirmed.append(str(match))

    hard_blocker_count = len(blockers)
    verification_count = len(verification)

    if hard_blocker_count == 0 and compatibility_confidence >= 80:
        disposition = "Recommended for engineering qualification"
        disposition_tone = "good"
        use_case = "Prototype and controlled production qualification"
        approval_guidance = (
            "Proceed with datasheet review, footprint confirmation, and prototype validation."
        )
    elif hard_blocker_count == 0 and compatibility_confidence >= 55:
        disposition = "Conditional candidate"
        disposition_tone = "warn"
        use_case = "Prototype evaluation only"
        approval_guidance = (
            "Resolve the verification checklist before approving this candidate for production."
        )
    else:
        disposition = "Not recommended as a drop-in replacement"
        disposition_tone = "bad"
        use_case = "Comparison reference only"
        approval_guidance = (
            "Do not approve for production until the identified compatibility blockers are resolved."
        )

    if hard_blocker_count:
        confidence_adjustment = min(35, hard_blocker_count * 12)
    else:
        confidence_adjustment = min(15, verification_count * 4)

    decision_confidence = max(
        5,
        min(
            98,
            round(
                recommendation_score * 0.45
                + compatibility_confidence * 0.55
                - confidence_adjustment
            ),
        ),
    )

    stock_advantage = "more stock" in _normalize(stock_delta)
    cost_advantage = "lower cost" in _normalize(price_delta)
    business_value = []
    if stock_advantage:
        business_value.append("Improves current supply availability.")
    if cost_advantage:
        business_value.append("Reduces estimated unit cost.")
    if lifecycle.lower() == "active":
        business_value.append("Supports longer-term sourcing continuity.")
    if not business_value:
        business_value.append("No verified sourcing or cost advantage dominates.")

    expected_work = []
    if not package_match:
        expected_work.append("PCB footprint review")
    if original_pins != candidate_pins or not original_pins or not candidate_pins:
        expected_work.append("Pinout review")
    expected_work.extend(
        [
            "Electrical limit comparison",
            "Prototype validation",
            "Engineering approval record",
        ]
    )

    return {
        "disposition": disposition,
        "disposition_tone": disposition_tone,
        "decision_confidence": decision_confidence,
        "use_case": use_case,
        "approval_guidance": approval_guidance,
        "confirmed_matches": confirmed,
        "verification_required": verification,
        "blockers": blockers,
        "business_value": business_value,
        "expected_work": expected_work,
        "estimated_effort_hours": max(
            2,
            min(
                16,
                2 + hard_blocker_count * 3 + verification_count,
            ),
        ),
        "hard_blocker_count": hard_blocker_count,
        "verification_count": verification_count,
        "candidate_part": _text(candidate.get("Alternative Part"), "Candidate"),
        "original_part": original_part,
        "stock": stock,
        "unit_price": unit_price,
    }
