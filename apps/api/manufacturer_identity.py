"""Manufacturer identity matching and dual-source MPN disambiguation.

Some common MPNs (for example LM358N) are sold by more than one manufacturer
with official product evidence. When the caller names a manufacturer, Cadivor
must honor that choice instead of silently presenting another brand's identity.
"""
from __future__ import annotations

from typing import Any

# Canonical brand → aliases (casefolded).
_MANUFACTURER_ALIASES: dict[str, set[str]] = {
    "texas instruments": {
        "texas instruments",
        "ti",
        "texas instruments incorporated",
        "texas instruments inc",
        "texas instruments, inc.",
    },
    "onsemi": {
        "onsemi",
        "on semiconductor",
        "on semi",
        "on semiconductor corporation",
        "semiconductor components industries, llc",
    },
    "stmicroelectronics": {"stmicroelectronics", "st microelectronics", "st"},
    "analog devices": {"analog devices", "adi", "analog devices inc"},
    "microchip": {"microchip", "microchip technology", "microchip technology inc"},
    "nxp": {"nxp", "nxp semiconductors", "nxp semicon"},
    "infineon": {"infineon", "infineon technologies"},
    "vishay": {"vishay", "vishay intertechnology"},
    "diodes incorporated": {"diodes incorporated", "diodes inc", "diodes"},
}

# Exact MPNs known to have official product pages under multiple brands.
# Used to force explicit disambiguation even before a live lookup returns.
_MULTI_BRAND_MPNS: dict[str, list[dict[str, str]]] = {
    "LM358N": [
        {
            "manufacturer": "Texas Instruments",
            "canonical": "texas instruments",
            "product_url": "https://www.ti.com/product/LM358",
            "note": "Official Texas Instruments LM358 / LM358N family product evidence.",
        },
        {
            "manufacturer": "onsemi",
            "canonical": "onsemi",
            "product_url": "https://www.onsemi.com/products/amplifiers-comparators/operational-amplifiers-op-amps/lm358",
            "note": "Official onsemi LM358N product evidence.",
        },
    ],
}


def _fold(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def manufacturer_canonical(value: object) -> str:
    """Return a canonical manufacturer key, or the folded raw string."""
    folded = _fold(value)
    if not folded:
        return ""
    for canonical, aliases in _MANUFACTURER_ALIASES.items():
        if folded == canonical or folded in aliases:
            return canonical
        # Allow substring containment for longer supplier labels.
        if any(alias in folded or folded in alias for alias in aliases if len(alias) >= 3):
            return canonical
    return folded


def manufacturers_match(left: object, right: object) -> bool:
    """True when both labels resolve to the same manufacturer family."""
    a = manufacturer_canonical(left)
    b = manufacturer_canonical(right)
    if not a or not b:
        return False
    return a == b


def multi_brand_choices_for_mpn(mpn: object) -> list[dict[str, str]]:
    """Return known dual-source choices for an exact MPN, if any."""
    key = str(mpn or "").strip().upper()
    return [dict(row) for row in _MULTI_BRAND_MPNS.get(key, [])]


def select_manufacturer_choice(
    mpn: object,
    requested_manufacturer: object,
) -> dict[str, Any] | None:
    """Return the matching dual-source choice, or None when not selected."""
    requested = manufacturer_canonical(requested_manufacturer)
    if not requested:
        return None
    for choice in multi_brand_choices_for_mpn(mpn):
        if manufacturers_match(requested, choice.get("manufacturer")):
            return choice
    return None


def identity_ambiguity_payload(
    *,
    mpn: str,
    requested_manufacturer: str = "",
    resolved_manufacturer: str = "",
    choices: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed identity ambiguity response for Find Replacement."""
    options = choices if choices is not None else multi_brand_choices_for_mpn(mpn)
    if not options and resolved_manufacturer:
        options = [
            {
                "manufacturer": resolved_manufacturer,
                "canonical": manufacturer_canonical(resolved_manufacturer),
                "product_url": "",
                "note": "Supplier lookup returned this manufacturer for the MPN.",
            }
        ]
        if requested_manufacturer and not manufacturers_match(
            requested_manufacturer, resolved_manufacturer
        ):
            options.insert(
                0,
                {
                    "manufacturer": requested_manufacturer,
                    "canonical": manufacturer_canonical(requested_manufacturer),
                    "product_url": "",
                    "note": "Manufacturer selected by the user for this search.",
                },
            )
    detail = (
        f"{mpn} is offered by more than one manufacturer with official product evidence. "
        "Select the manufacturer identity to continue — Cadivor will not silently substitute another brand."
    )
    if requested_manufacturer and resolved_manufacturer and not manufacturers_match(
        requested_manufacturer, resolved_manufacturer
    ):
        detail = (
            f"You selected {requested_manufacturer}, but the first supplier hit for {mpn} "
            f"resolved to {resolved_manufacturer}. Choose the intended manufacturer identity "
            "before reviewing replacements."
        )
    return {
        "ok": True,
        "status": "identity_ambiguous",
        "outcome": "identity_ambiguous",
        "search_outcome": "identity_ambiguous",
        "identity_status": "ambiguous",
        "requested_mpn": mpn,
        "requested_manufacturer": requested_manufacturer,
        "resolved_manufacturer": resolved_manufacturer,
        "identity_choices": options,
        "gap": detail,
        "detail": detail,
        "candidates": [],
        "unclassified_leads": [],
        "unfiltered_leads": [],
        "original": {
            "mpn": mpn,
            "manufacturer_part_number": mpn,
            "manufacturer": requested_manufacturer or "",
            "identity_verified": False,
            "identity_status": "ambiguous",
        },
        "discovery": {
            "providers": {},
            "message": "Replacement search paused until manufacturer identity is confirmed.",
        },
    }
