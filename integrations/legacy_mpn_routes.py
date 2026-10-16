"""Conservative legacy-MPN routes with explicit evidence qualification.

These routes expand discovery. A related MPN is never scored unless the exact
order code is documented by the manufacturer as the same device/orderable form.
Family-level searches remain review-only.
"""
from __future__ import annotations

from src.normalizer import normalize_part_number


_ROUTES = {
    normalize_part_number("AM29F010B-70EC"): {
        "lineage": ("AMD", "Spansion", "Cypress", "Infineon"),
        "query_mpns": ("AM29F010B",),
        "assessment_order_codes": (),
        "review_note": "family-level search; speed, temperature, and package must be verified",
    },
    normalize_part_number("IRF540N"): {
        "lineage": ("International Rectifier", "Infineon"),
        "query_mpns": ("IRF540NPBF",),
        "assessment_order_codes": (
            {
                "mpn": "IRF540NPBF",
                "manufacturer": "Infineon",
                "basis": "Infineon lists IRF540NPBF as an active IRF540N TO-220 order code.",
                "source_url": "https://www.infineon.com/part/IRF540N",
            },
        ),
        "review_note": "lead-free ordering-code variant; verify the exact device requirements",
    },
    normalize_part_number("PCF8574P"): {
        "lineage": ("Philips Semiconductors", "NXP"),
        "query_mpns": ("PCF8574P,112",),
        "assessment_order_codes": (
            {
                "mpn": "PCF8574P,112",
                "manufacturer": "NXP",
                "basis": "NXP lists PCF8574P,112 as the PCF8574P DIP16 tube order code.",
                "source_url": "https://www.nxp.com/docs/en/data-sheet/PCF8574_PCF8574A.pdf",
            },
        ),
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
    """Explain whether the route returned exact, qualified, or no evidence."""
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
    order_codes = [
        str(item.get("mpn") or "").strip()
        for item in route.get("assessment_order_codes") or ()
        if isinstance(item, dict) and str(item.get("mpn") or "").strip()
    ]
    if order_codes:
        return (
            f"No exact supplier record was returned for {requested} or its manufacturer-listed "
            f"order code(s) {', '.join(order_codes)}. No related data was assigned; confirm the "
            "full device and ordering suffix before rerunning. Risk remains unassessed."
        )
    return (
        f"No exact supplier match. Legacy manufacturer route {lineage} was checked, but no "
        f"reviewable catalog lead was returned. Verify the full MPN; suffix variants were "
        f"not treated as exact evidence for {requested}; risk remains unassessed."
    )


__all__ = ["legacy_mpn_route", "legacy_route_status"]
