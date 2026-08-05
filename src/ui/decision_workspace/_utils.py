"""Shared helpers for decision workspace HTML components."""
from __future__ import annotations

from html import escape
from typing import Any

INSUFFICIENT_EVIDENCE = "Insufficient evidence"


def text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text_value = str(value).strip()
    return text_value or default


def number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def esc(value: Any, default: str = "") -> str:
    return escape(text(value, default))
