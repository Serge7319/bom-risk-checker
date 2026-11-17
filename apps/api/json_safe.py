"""JSON-safe coercion for workspace report payloads.

Postgres jsonb rejects non-finite floats; numpy/pandas scalars also break
``json.dumps``. Sanitize before durable writes so analyze cannot return a
saved id that never lands in storage.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def json_safe(value: Any) -> Any:
    """Return a structure that ``json.dumps(..., allow_nan=False)`` accepts."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:  # noqa: BLE001
            return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    return value
