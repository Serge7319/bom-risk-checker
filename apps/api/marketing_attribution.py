"""Small, allowlisted marketing attribution fields used during signup."""
from __future__ import annotations

import re
from typing import Any

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
_SAFE_VALUE = re.compile(r"^[\w .:+~/=-]{1,80}$", re.UNICODE)


def sanitize_marketing_attribution(value: Any) -> dict[str, str]:
    """Return only short, non-address-like UTM values from untrusted input."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key in UTM_KEYS:
        raw = value.get(key)
        if not isinstance(raw, str):
            continue
        candidate = " ".join(raw.split())[:80]
        if not candidate or "@" in candidate or not _SAFE_VALUE.fullmatch(candidate):
            continue
        result[key] = candidate
    return result
