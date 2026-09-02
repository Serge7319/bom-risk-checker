"""Shared supplier stock normalization helpers."""
from __future__ import annotations


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
