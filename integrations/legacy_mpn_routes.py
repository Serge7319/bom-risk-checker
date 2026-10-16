"""Conservative, review-only routes for a few known legacy ordering codes.

These routes expand discovery. They never promote a related MPN's price, stock,
or lifecycle into evidence for the BOM's original MPN.
"""
from __future__ import annotations

from src.normalizer import normalize_part_number


_ROUTES = {
    normalize_part_number("AM29F010B-70EC"): {
        "lineage": ("AMD", "Spansion", "Cypress", "Infineon"),
        "query_mpns": ("AM29F010B",),
        "review_note": "family-level search; speed, temperature, and package must be verified",
    },
    normalize_part_number("IRF540N"): {
        "lineage": ("International Rectifier", "Infineon"),
        "query_mpns": ("IRF540NPBF",),
        "review_note": "lead-free ordering-code variant; verify the exact device requirements",
    },
    normalize_part_number("PCF8574P"): {
        "lineage": ("Philips Semiconductors", "NXP"),
        "query_mpns": ("PCF8574P,112",),
        "review_note": "orderable package variant; verify the package and ordering suffix",
    },
}


def legacy_mpn_route(mpn: object) -> dict | None:
    """Return a copy of a narrow route keyed by an exact normalized MPN."""
    key = normalize_part_number(str(mpn or "").strip())
    route = _ROUTES.get(key)
    if route is None:
        return None
    return {
        **route,
        "requested_mpn": str(mpn or "").strip(),
    }


def legacy_route_status(
    mpn: object,
    leads: list[dict] | None = None,
    *,
    searched: bool = True,
) -> str:
    """Explain the route without implying that related catalog hits are exact evidence."""
    route = legacy_mpn_route(mpn)
    if route is None:
        return ""
    requested = str(route["requested_mpn"] or "this MPN")
    lineage = " → ".join(route["lineage"])
    candidates = []
    for lead in leads or []:
        candidate = str(lead.get("mpn") or "").strip()
        supplier = str(lead.get("supplier") or "").strip()
        if candidate:
            candidates.append(f"{candidate}" + (f" ({supplier})" if supplier else ""))
    if candidates:
        found = ", ".join(dict.fromkeys(candidates))
        return (
            f"No exact supplier match. Legacy route {lineage} found related catalog lead(s) "
            f"for review only: {found}. {route['review_note']}; no candidate stock, price, "
            f"or lifecycle is attributed to {requested}."
        )
    if not searched:
        return (
            f"Legacy manufacturer route {lineage} is recognized, but no configured distributor "
            f"was available to check its related catalog leads. Verify the full MPN; risk for "
            f"{requested} remains unassessed without a matching supplier record."
        )
    return (
        f"No exact supplier match. Legacy manufacturer route {lineage} was checked, but no "
        f"reviewable catalog lead was returned. Verify the full MPN; suffix variants were "
        f"not treated as exact evidence for {requested}."
    )


__all__ = ["legacy_mpn_route", "legacy_route_status"]
