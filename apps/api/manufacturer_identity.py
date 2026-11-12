"""Manufacturer identity matching and multi-brand MPN disambiguation.

Any MPN can be offered by more than one manufacturer. When the caller names a
manufacturer, Cadivor must honor that choice. When multiple brands are known or
observed for the same MPN, require an explicit manufacturer selection and show
official product evidence when available — never silently substitute a brand or
stamp an unverified identity as verified.
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
    "murata": {"murata", "murata manufacturing", "murata manufacturing co"},
    "yageo": {"yageo", "yageo corporation"},
    "tdk": {"tdk", "tdk corporation"},
    "bourns": {"bourns", "bourns inc"},
    "ohmite": {"ohmite", "ohmite manufacturing"},
}

# Optional seed evidence for exact MPNs known to have official product pages
# under multiple brands. Lookups remain generic: any MPN can register choices,
# and live supplier hits can also force disambiguation.
_DEFAULT_MULTI_BRAND_EVIDENCE: dict[str, list[dict[str, str]]] = {
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
_MULTI_BRAND_EVIDENCE: dict[str, list[dict[str, str]]] = {
    key: [dict(row) for row in rows]
    for key, rows in _DEFAULT_MULTI_BRAND_EVIDENCE.items()
}


def _fold(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _mpn_key(mpn: object) -> str:
    return str(mpn or "").strip().upper()


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


def register_multi_brand_evidence(mpn: object, choices: list[dict[str, str]]) -> None:
    """Register or replace dual-source evidence for an exact MPN (tests + ops)."""
    key = _mpn_key(mpn)
    if not key:
        return
    normalized: list[dict[str, str]] = []
    for row in choices or []:
        if not isinstance(row, dict):
            continue
        manufacturer = str(row.get("manufacturer") or "").strip()
        if not manufacturer:
            continue
        normalized.append(
            {
                "manufacturer": manufacturer,
                "canonical": str(row.get("canonical") or manufacturer_canonical(manufacturer)),
                "product_url": str(row.get("product_url") or "").strip(),
                "note": str(row.get("note") or "").strip()
                or f"Official product evidence for {manufacturer}.",
            }
        )
    if normalized:
        _MULTI_BRAND_EVIDENCE[key] = normalized


def clear_multi_brand_evidence(mpn: object | None = None) -> None:
    """Clear registered dual-source evidence for one MPN, or restore defaults."""
    if mpn is None:
        _MULTI_BRAND_EVIDENCE.clear()
        _MULTI_BRAND_EVIDENCE.update(
            {
                key: [dict(row) for row in rows]
                for key, rows in _DEFAULT_MULTI_BRAND_EVIDENCE.items()
            }
        )
        return
    _MULTI_BRAND_EVIDENCE.pop(_mpn_key(mpn), None)


def multi_brand_choices_for_mpn(mpn: object) -> list[dict[str, str]]:
    """Return known dual-source choices for an exact MPN, if any."""
    key = _mpn_key(mpn)
    return [dict(row) for row in _MULTI_BRAND_EVIDENCE.get(key, [])]


def choices_from_manufacturer_labels(
    mpn: object,
    labels: list[str] | tuple[str, ...] | set[str],
    *,
    product_urls: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Build identity choices from observed manufacturer labels for any MPN."""
    urls = product_urls or {}
    seen: set[str] = set()
    choices: list[dict[str, str]] = []
    for label in labels:
        manufacturer = str(label or "").strip()
        if not manufacturer:
            continue
        canonical = manufacturer_canonical(manufacturer)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        url = str(
            urls.get(canonical)
            or urls.get(manufacturer)
            or urls.get(manufacturer.casefold())
            or ""
        ).strip()
        choices.append(
            {
                "manufacturer": manufacturer,
                "canonical": canonical,
                "product_url": url,
                "note": (
                    f"Official product evidence for {manufacturer}."
                    if url
                    else f"Supplier records list {manufacturer} for {_mpn_key(mpn) or 'this MPN'}."
                ),
            }
        )
    # Prefer registered product URLs when the same brand is already known.
    known = {row["canonical"]: row for row in multi_brand_choices_for_mpn(mpn)}
    for choice in choices:
        registered = known.get(choice["canonical"])
        if registered and not choice.get("product_url") and registered.get("product_url"):
            choice["product_url"] = registered["product_url"]
            choice["note"] = registered.get("note") or choice["note"]
            choice["manufacturer"] = registered.get("manufacturer") or choice["manufacturer"]
    return choices


def distinct_manufacturer_labels(
    hits: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    *,
    fallback: object = "",
) -> list[str]:
    """Collect distinct manufacturer labels from supplier hit rows."""
    labels: list[str] = []
    seen: set[str] = set()
    for row in hits or []:
        if not isinstance(row, dict):
            continue
        manufacturer_field = row.get("Manufacturer")
        if isinstance(manufacturer_field, dict):
            label = str(manufacturer_field.get("Name") or "").strip()
        else:
            label = str(
                row.get("manufacturer") or manufacturer_field or ""
            ).strip()
        if not label:
            continue
        canonical = manufacturer_canonical(label)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        labels.append(label)
    fallback_label = str(fallback or "").strip()
    if fallback_label:
        canonical = manufacturer_canonical(fallback_label)
        if canonical and canonical not in seen:
            labels.append(fallback_label)
    return labels


def select_manufacturer_choice(
    mpn: object,
    requested_manufacturer: object,
    *,
    choices: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Return the matching dual-source choice, or None when not selected."""
    requested = manufacturer_canonical(requested_manufacturer)
    if not requested:
        return None
    options = choices if choices is not None else multi_brand_choices_for_mpn(mpn)
    for choice in options:
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
        options = choices_from_manufacturer_labels(
            mpn,
            [resolved_manufacturer]
            + (
                [requested_manufacturer]
                if requested_manufacturer
                and not manufacturers_match(requested_manufacturer, resolved_manufacturer)
                else []
            ),
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
    elif not options and requested_manufacturer and not resolved_manufacturer:
        detail = (
            f"Could not verify manufacturer identity for {mpn} as {requested_manufacturer}. "
            "Replacement search paused until the selected brand is confirmed against supplier records."
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
            # Never stamp an unverified or mismatched selection as identity.
            "manufacturer": "",
            "identity_verified": False,
            "identity_status": "ambiguous",
            "requested_manufacturer": requested_manufacturer,
            "resolved_manufacturer": resolved_manufacturer,
        },
        "discovery": {
            "providers": {},
            "message": "Replacement search paused until manufacturer identity is confirmed.",
        },
    }
