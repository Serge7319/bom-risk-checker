"""Offline compare/replacement catalog for known MPNs when live suppliers are off.

Only manufacturer/MPN identity and component-family description are treated as
catalog-confirmed. Electrical and package attributes are omitted unless a live
or datasheet path verified them — compare rows then show Unable to confirm.
"""
from __future__ import annotations

import re
from typing import Any

from src.normalizer import normalize_part_number

# Identity-only catalog (no unverified package/electrical values).
_CATALOG: dict[str, dict[str, Any]] = {
    "LM358": {
        "manufacturer": "Texas Instruments",
        "description": "Dual operational amplifier",
        "category": "Operational amplifier",
        "architecture": "Operational amplifier",
    },
    "NE555": {
        "manufacturer": "Texas Instruments",
        "description": "Precision timer IC",
        "category": "Timer IC",
        "architecture": "555 timer",
    },
    "LM555": {
        "manufacturer": "Texas Instruments",
        "description": "Precision timer IC",
        "category": "Timer IC",
        "architecture": "555 timer",
    },
    "TLC555": {
        "manufacturer": "Texas Instruments",
        "description": "Low-power timer IC",
        "category": "Timer IC",
        "architecture": "555 timer",
    },
    "RES10K": {
        "manufacturer": "Mock Components Inc",
        "description": "10 kΩ wirewound rheostat",
        "category": "Potentiometer / rheostat",
    },
    "CAP100U": {
        "manufacturer": "Mock Caps Ltd",
        "description": "100 µF electrolytic capacitor",
        "category": "Capacitor",
    },
}

_IDENTITY_KEYS = (
    "manufacturer",
    "description",
    "category",
    "architecture",
)

# Offline candidate map for Find a Replacement (not live offers).
_REPLACEMENT_MAP: dict[str, list[dict[str, Any]]] = {
    "LM358DR": [
        {
            "mpn": "LM358N",
            "manufacturer": "Texas Instruments",
            "rationale": "Same dual op-amp family; package and pinout still need datasheet confirmation.",
            "fit": "unable_to_confirm",
            "missing": ["package fit evidence", "pinout confirmation", "electrical datasheet comparison"],
        },
        {
            "mpn": "LM358P",
            "manufacturer": "Texas Instruments",
            "rationale": "Same dual op-amp family; mounting style differs from SOIC and must be verified.",
            "fit": "unable_to_confirm",
            "missing": ["package fit evidence", "mounting style", "electrical datasheet comparison"],
        },
    ],
    "LM358N": [
        {
            "mpn": "LM358P",
            "manufacturer": "Texas Instruments",
            "rationale": "Same dual op-amp family; confirm package and electrical limits from datasheets.",
            "fit": "unable_to_confirm",
            "missing": ["package fit evidence", "electrical datasheet comparison"],
        },
        {
            "mpn": "LM358DR",
            "manufacturer": "Texas Instruments",
            "rationale": "Same dual op-amp family in SOIC; confirm pinout and thermal limits.",
            "fit": "unable_to_confirm",
            "missing": ["package fit evidence", "pinout confirmation"],
        },
    ],
    "NE555P": [
        {
            "mpn": "LM555CN/NOPB",
            "manufacturer": "Texas Instruments",
            "rationale": "Common 555-timer family candidate; confirm package and electrical ratings.",
            "fit": "unable_to_confirm",
            "missing": ["datasheet comparison", "package fit evidence"],
        },
        {
            "mpn": "TLC555CP",
            "manufacturer": "Texas Instruments",
            "rationale": "Low-power 555-timer candidate; supply and timing limits must be verified.",
            "fit": "unable_to_confirm",
            "missing": ["datasheet comparison", "supply voltage evidence"],
        },
    ],
    "LM555": [
        {
            "mpn": "NE555P",
            "manufacturer": "Texas Instruments",
            "rationale": "Common 555-timer family candidate; confirm package and electrical ratings.",
            "fit": "unable_to_confirm",
            "missing": ["datasheet comparison", "package fit evidence"],
        },
        {
            "mpn": "TLC555CP",
            "manufacturer": "Texas Instruments",
            "rationale": "Low-power 555-timer candidate; supply and timing limits must be verified.",
            "fit": "unable_to_confirm",
            "missing": ["datasheet comparison", "supply voltage evidence"],
        },
    ],
    "LM555CN/NOPB": [
        {
            "mpn": "NE555P",
            "manufacturer": "Texas Instruments",
            "rationale": "Common 555-timer family candidate; confirm package and electrical ratings.",
            "fit": "unable_to_confirm",
            "missing": ["datasheet comparison", "package fit evidence"],
        },
        {
            "mpn": "TLC555CP",
            "manufacturer": "Texas Instruments",
            "rationale": "Low-power 555-timer candidate; supply and timing limits must be verified.",
            "fit": "unable_to_confirm",
            "missing": ["datasheet comparison", "supply voltage evidence"],
        },
    ],
    "RES10K": [
        {
            "mpn": "RES10KE",
            "manufacturer": "Ohmite",
            "rationale": "Catalog sibling in the rheostat family; resistance, power, and taper still need evidence.",
            "fit": "unable_to_confirm",
            "missing": ["manufacturer datasheet comparison", "power rating evidence"],
        },
    ],
}


def _stem_match(mpn: str) -> dict[str, Any] | None:
    key = normalize_part_number(mpn)
    if not key:
        return None
    for stem in sorted(_CATALOG.keys(), key=len, reverse=True):
        if key == stem or key.startswith(stem):
            rest = key[len(stem) :]
            if not rest or re.fullmatch(r"[A-Z0-9/\-]*", rest):
                return dict(_CATALOG[stem])
    return None


def enrich_compare_part(mpn: str, base: dict[str, Any]) -> dict[str, Any]:
    """Merge offline identity into a compare-ready part before family inference.

    Does not invent package, pin, voltage, or stock values. Those stay empty so
    the comparison matrix reports Unable to confirm without false compatibility.
    """
    out = dict(base or {})
    requested = str(mpn or out.get("manufacturer_part_number") or "").strip()
    if requested:
        out["manufacturer_part_number"] = requested
    ref = _stem_match(requested)
    if not ref:
        return out
    for key in _IDENTITY_KEYS:
        value = ref.get(key)
        if value is None or str(value).strip() == "":
            continue
        current = out.get(key)
        if current is None or str(current).strip() == "":
            out[key] = value
    out.setdefault("found", True)
    sources = dict(out.get("field_sources") or {})
    for key in _IDENTITY_KEYS:
        if out.get(key):
            sources.setdefault(key, "offline-identity-catalog")
    out["field_sources"] = sources
    out["catalog_reference"] = True
    out["catalog_identity_only"] = True
    return out


def offline_replacement_candidates(mpn: str) -> list[dict[str, Any]]:
    key = normalize_part_number(mpn)
    if not key:
        return []
    if key in _REPLACEMENT_MAP:
        return [dict(item) for item in _REPLACEMENT_MAP[key]]
    for stem, rows in _REPLACEMENT_MAP.items():
        stem_n = normalize_part_number(stem)
        if key.startswith(stem_n) or stem_n.startswith(key):
            return [dict(item) for item in rows]
    return []
