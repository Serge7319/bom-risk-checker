"""Offline compare/replacement catalog for known MPNs when live suppliers are off.

Values are labeled synthetic reference attributes (manufacturer public family
identity), not live distributor quotes. Never invent stock, price, or
compatibility verdicts beyond what family/package evidence supports.
"""
from __future__ import annotations

import re
from typing import Any

from src.normalizer import normalize_part_number

# Stem → reference attributes used only when live lookup is unavailable.
_CATALOG: dict[str, dict[str, Any]] = {
    "LM358": {
        "manufacturer": "Texas Instruments",
        "description": "Dual operational amplifier",
        "category": "Operational amplifier",
        "architecture": "Operational Amplifier",
        "package": "SOIC-8",
        "pin_count": 8,
        "mounting_style": "Surface Mount",
        "voltage_range": "3V to 32V",
        "channel_count": 2,
    },
    "NE555": {
        "manufacturer": "Texas Instruments",
        "description": "Precision timer IC",
        "category": "Timer / oscillator",
        "architecture": "555 Timer",
        "package": "PDIP-8",
        "pin_count": 8,
        "mounting_style": "Through Hole",
        "voltage_range": "4.5V to 16V",
        "channel_count": 1,
    },
    "LM555": {
        "manufacturer": "Texas Instruments",
        "description": "Precision timer IC",
        "category": "Timer / oscillator",
        "architecture": "555 Timer",
        "package": "PDIP-8",
        "pin_count": 8,
        "mounting_style": "Through Hole",
        "voltage_range": "4.5V to 16V",
        "channel_count": 1,
    },
    "TLC555": {
        "manufacturer": "Texas Instruments",
        "description": "Low-power timer IC",
        "category": "Timer / oscillator",
        "architecture": "555 Timer",
        "package": "PDIP-8",
        "pin_count": 8,
        "mounting_style": "Through Hole",
        "voltage_range": "2V to 15V",
        "channel_count": 1,
    },
    "RES10K": {
        "manufacturer": "Mock Components Inc",
        "description": "10 kΩ wirewound rheostat",
        "category": "Potentiometer / rheostat",
        "package": "Panel",
        "pin_count": 3,
        "mounting_style": "Panel Mount",
    },
    "CAP100U": {
        "manufacturer": "Mock Caps Ltd",
        "description": "100 µF electrolytic capacitor",
        "category": "Capacitor",
        "package": "Radial",
        "pin_count": 2,
        "mounting_style": "Through Hole",
    },
}

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
    # Longest stem first so LM555 beats LM55…
    for stem in sorted(_CATALOG.keys(), key=len, reverse=True):
        if key == stem or key.startswith(stem):
            # Avoid matching LM358 inside unrelated longer codes without stem prefix.
            rest = key[len(stem) :]
            if not rest or re.fullmatch(r"[A-Z0-9/\-]*", rest):
                return dict(_CATALOG[stem])
    return None


def enrich_compare_part(mpn: str, base: dict[str, Any]) -> dict[str, Any]:
    """Merge offline catalog attributes into a compare-ready part record."""
    out = dict(base or {})
    ref = _stem_match(mpn)
    if not ref:
        return out
    for key, value in ref.items():
        current = out.get(key)
        if current is None or str(current).strip() == "":
            out[key] = value
    out.setdefault("category", ref.get("category"))
    out.setdefault("found", True)
    sources = dict(out.get("field_sources") or {})
    for key in ref:
        sources.setdefault(key, "offline-catalog-reference")
    out["field_sources"] = sources
    out["catalog_reference"] = True
    return out


def offline_replacement_candidates(mpn: str) -> list[dict[str, Any]]:
    key = normalize_part_number(mpn)
    if not key:
        return []
    if key in _REPLACEMENT_MAP:
        return [dict(item) for item in _REPLACEMENT_MAP[key]]
    # Soft stem match for LM358* / NE555* packaging suffixes.
    for stem, rows in _REPLACEMENT_MAP.items():
        stem_n = normalize_part_number(stem)
        if key.startswith(stem_n) or stem_n.startswith(key):
            return [dict(item) for item in rows]
    return []
