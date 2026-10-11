"""Shared supplier stock normalization helpers."""
from __future__ import annotations

import math
import re


def parse_stock_total(value: object) -> int | None:
    """Parse an on-hand count without turning missing or ambiguous text into zero.

    ``None`` means the supplier did not provide a usable inventory figure;
    ``0`` means it explicitly reported no on-hand stock.  This distinction is
    important for risk scoring and reports.  The older ``coerce_stock_total``
    remains available for UI paths that require a numeric fallback.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return max(int(value), 0)

    text = str(value).strip()
    if not text:
        return None
    numeric = text.replace(",", "")
    if re.fullmatch(r"\d+(?:\.0+)?", numeric):
        return max(int(float(numeric)), 0)

    # Accept only wording that explicitly describes on-hand inventory. Do not
    # mistake order quantities, lead times, or dates for available stock.
    patterns = (
        r"(?<!\d)(\d[\d,]*)\s*(?:pcs?|pieces?|units?)?\s*(?:in\s+stock|available|on\s+hand)\b",
        r"\b(?:in\s+stock|available|on\s+hand)\s*:?\s*(\d[\d,]*)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return max(int(match.group(1).replace(",", "")), 0)
            except ValueError:
                return None
    return None


def stock_evidence_note(
    stock: object,
    sources: object,
    *,
    complete: bool,
    matching_supplier_count: object = None,
) -> str:
    """Describe which matched supplier records contributed to a stock total."""
    count = parse_stock_total(stock)
    if count is None:
        return "Not reported by matched suppliers"
    source_values = sources.split(",") if isinstance(sources, str) else (sources or [])
    source_names = sorted({str(item).strip() for item in source_values if str(item).strip()})
    if not source_names:
        return "Reported stock source unavailable"
    if complete:
        return f"Reported by {', '.join(source_names)}"
    matched = parse_stock_total(matching_supplier_count)
    if matched is None:
        return f"Partial reported total from {', '.join(source_names)}"
    return f"Partial: {', '.join(source_names)} ({len(source_names)} of {matched} matched sources)"


def coerce_stock_total(value: object) -> int:
    """Normalize supplier stock counts from ints, floats, or human-readable strings."""
    try:
        if value is None or value == "":
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, float):
            return max(int(value), 0)

        text = str(value).strip().replace(",", "")
        if not text:
            return 0

        try:
            return max(int(float(text)), 0)
        except (TypeError, ValueError):
            pass

        digits = ""
        for char in text:
            if char.isdigit():
                digits += char
            elif digits:
                break
        return int(digits) if digits else 0
    except (TypeError, ValueError):
        return 0
