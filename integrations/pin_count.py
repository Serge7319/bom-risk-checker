"""Conservative pin/lead/ball-count parsing for supplier package text.

Never treat JEDEC outlines, EIA passives, or the first number in a package
string as a pin count. Prefer explicit supplier count fields; fall back to
unambiguous package suffixes only.
"""
from __future__ import annotations

import re
from typing import Iterable

# Explicit supplier attribute values are often bare integers ("3", "32").
_BARE_COUNT_RE = re.compile(r"^\d{1,4}$")
_PASSIVE_SIZE_CODE_RE = re.compile(r"^(?:0\d{3}|\d{4})$")

_EXPLICIT_LABEL_RE = re.compile(
    r"(?i)(?:number of (?:pins?|leads?|balls?|terminals?)|pin(?:s)? count|"
    r"ball count|lead count|termination count)\s*[:=]?\s*(\d{1,4})\b"
)
_EXPLICIT_TRAILING_RE = re.compile(
    r"(?i)\b(\d{1,4})\s*(?:pins?|leads?|balls?|terminals?)\b"
)

# TO-236-3 / SOT-23-3 / SOD-323-2 — outline + pin suffix.
_OUTLINE_WITH_PIN_RE = re.compile(
    r"(?i)\b(?:TO|SOT|SC|SOD|TSOT|TSOP)\s*-?\s*\d+(?:\.\d+)?\s*-\s*(\d{1,3})\b"
)

# SOIC-8, QFN-32, LQFP-64, BGA-256, WLCSP-16, DIP-8, ...
# (?![A-Za-z]) prevents SO matching inside SOIC, DIP inside PDIP, etc.
_NAMED_PACKAGE_PIN_RE = re.compile(
    r"(?i)\b(?:"
    r"U?FBGA|PBGA|MBGA|LFBGA|TFBGA|UBGA|BGA|"
    r"WLCSP|UCSP|CSP|"
    r"LQFP|TQFP|PQFP|VQFP|QFP|"
    r"VQFN|WQFN|UQFN|QFN|DFN|UTDFN|UDFN|"
    r"SOIC|SOP|SSOP|TSSOP|MSOP|VSSOP|QSOP|SO|"
    r"PDIP|CDIP|DIP|PLCC|LGA"
    r")(?![A-Za-z])\s*-?\s*(\d{1,4})\b"
)

_PASSIVE_EIA_RE = re.compile(r"(?i)\b(?:0\d{3}|\d{4})\b")
_PASSIVE_METRIC_RE = re.compile(r"(?i)\b\d{4}\s*metric\b")
_OUTLINE_ONLY_RE = re.compile(
    r"(?i)^\s*(?:TO|SOT|SC|SOD|TSOT|TSOP)\s*-?\s*\d+(?:\.\d+)?\s*$"
)
# Outline number sitting in family codes like TO-236 / SC-59 (not a pin count).
# Also matches the outline portion of TO-236-3 so a stored 236 can be rejected.
_OUTLINE_FAMILY_NUM_RE = re.compile(
    r"(?i)\b(?:TO|SOT|SC|SOD|TSOT|TSOP)\s*-?\s*(\d+(?:\.\d+)?)\b"
)


def _segment_is_non_count(segment: str) -> bool:
    text = str(segment or "").strip()
    if not text:
        return True
    if _PASSIVE_METRIC_RE.search(text):
        return True
    compact = re.sub(r"[^0-9A-Za-z]", "", text)
    if _PASSIVE_SIZE_CODE_RE.fullmatch(compact or ""):
        return True
    if _PASSIVE_EIA_RE.fullmatch(text.strip()):
        return True
    if _OUTLINE_ONLY_RE.match(text):
        return True
    return False


def _parse_package_segment(segment: str) -> int:
    text = str(segment or "").strip()
    if not text or _segment_is_non_count(text):
        return 0
    match = _OUTLINE_WITH_PIN_RE.search(text)
    if match:
        return int(match.group(1))
    match = _NAMED_PACKAGE_PIN_RE.search(text)
    if match:
        return int(match.group(1))
    return 0


def parse_pin_count_from_text(
    text: object,
    *,
    allow_bare_integer: bool = False,
) -> int:
    """Return a trustworthy pin/lead/ball count, or 0 when ambiguous.

    ``allow_bare_integer`` is only for explicit supplier count fields
    (Number of Pins = \"3\"). Package strings must never use bare-integer mode.
    """
    raw = str(text or "").strip()
    if not raw:
        return 0

    match = _EXPLICIT_LABEL_RE.search(raw)
    if match:
        return int(match.group(1))
    match = _EXPLICIT_TRAILING_RE.search(raw)
    if match:
        return int(match.group(1))

    segments = [part.strip() for part in re.split(r"[,;/|]+", raw) if part.strip()]
    if not segments:
        segments = [raw]

    counts: list[int] = []
    for segment in segments:
        value = _parse_package_segment(segment)
        if value > 0:
            counts.append(value)

    if counts:
        unique = set(counts)
        if len(unique) == 1:
            return next(iter(unique))
        return 0

    if allow_bare_integer and _BARE_COUNT_RE.fullmatch(raw):
        # Never treat EIA / metric size codes as explicit pin fields.
        if _PASSIVE_SIZE_CODE_RE.fullmatch(raw):
            return 0
        value = int(raw)
        return value if value > 0 else 0
    return 0


def resolve_pin_count(
    *,
    explicit_count_text: object = "",
    package_text: object = "",
    fallback_texts: Iterable[object] | None = None,
) -> int:
    """Prefer an explicit supplier count field; otherwise unambiguous package text."""
    explicit = parse_pin_count_from_text(explicit_count_text, allow_bare_integer=True)
    if explicit > 0:
        return explicit

    package = parse_pin_count_from_text(package_text, allow_bare_integer=False)
    if package > 0:
        return package

    for text in fallback_texts or ():
        value = parse_pin_count_from_text(text, allow_bare_integer=False)
        if value > 0:
            return value
    return 0


def sanitize_stored_pin_count(
    value: object,
    *,
    package_text: object = "",
) -> int:
    """Drop invented stored counts that contradict package rules.

    Re-validates normalized supplier rows before comparison or UI so a stale
    236 from TO-236 packaging cannot score as a match. Explicit supplier
    counts still take precedence over package suffixes unless the stored value
    is clearly a JEDEC/outline or EIA code embedded in the package string.
    """
    try:
        stored = int(float(value or 0))
    except (TypeError, ValueError):
        stored = 0
    if stored <= 0:
        return 0

    package = str(package_text or "").strip()
    if not package:
        return stored

    parsed = parse_pin_count_from_text(package, allow_bare_integer=False)
    outline_nums = {
        m.group(1).split(".")[0]
        for m in _OUTLINE_FAMILY_NUM_RE.finditer(package)
    }
    if str(stored) in outline_nums:
        return parsed if parsed > 0 else 0

    if _PASSIVE_EIA_RE.search(package) or _PASSIVE_METRIC_RE.search(package):
        for match in re.finditer(r"\d+", package):
            token = match.group(0)
            if int(token) != stored:
                continue
            if _PASSIVE_SIZE_CODE_RE.fullmatch(token) or _PASSIVE_METRIC_RE.search(package):
                return 0

    # Explicit stored supplier count wins over a conflicting package suffix
    # (e.g. Number of Pins=14 with PDIP-8 package text).
    return stored


def effective_pin_count(part: object) -> int:
    """Trusted pin count for a part dict, or 0 when Needs data."""
    if not isinstance(part, dict):
        return 0
    value = part.get("pin_count", part.get("Pin Count", part.get("pins", 0)))
    package = part.get("package", part.get("Package", part.get("Case Package", "")))
    sanitized = sanitize_stored_pin_count(value, package_text=package)
    if sanitized > 0:
        return sanitized
    return parse_pin_count_from_text(package, allow_bare_integer=False)
