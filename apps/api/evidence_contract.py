"""Evidence labeling for the Next.js migration API.

Separates live authorized-supplier evidence from synthetic/preview estimates.
Identity, lifecycle, stock, and price each keep their own source class,
retrieval time, and (for price) price type so a live identity never makes a
synthetic or missing price appear live.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.decision_packet_evidence import exact_supplier_evidence


EVIDENCE_LIVE = "live-authorized-supplier"
EVIDENCE_SYNTHETIC = "synthetic-preview"
EVIDENCE_MISSING = "missing"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _first(*values: object, default: str = "") -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return default


def _is_synthetic_label(value: object) -> bool:
    text = _text(value).casefold()
    return "synthetic" in text or "preview" in text


def _is_live_label(value: object) -> bool:
    text = _text(value).casefold()
    return text.startswith("live") or text == EVIDENCE_LIVE


def _is_authorized_supplier_source(value: object) -> bool:
    """Recognize explicit distributor names without treating any URL as proof."""
    import re

    known = {"digikey", "mouser", "newark", "nexar supply"}
    labels = {
        " ".join(item.casefold().split())
        for item in re.split(r"[,;/|]", _text(value))
        if item.strip()
    }
    return bool(labels & known)


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, tuple, dict)) and not value:
        return False
    return True


def _price_type_for_row(row: dict[str, Any], *, price_present: bool, price_class: str) -> str:
    explicit = _first(row.get("price_type"), row.get("Price Type"))
    if explicit:
        return explicit
    if not price_present or price_class == EVIDENCE_MISSING:
        return "not-recorded"
    if price_class == EVIDENCE_SYNTHETIC:
        return "synthetic-estimate"
    break_qty = row.get("price_break_quantity")
    if break_qty in (None, ""):
        offers = row.get("supplier_offers") or row.get("Supplier Offers") or []
        if isinstance(offers, list):
            for offer in offers:
                if isinstance(offer, dict) and offer.get("price_break_quantity") not in (None, ""):
                    break_qty = offer.get("price_break_quantity")
                    break
    if break_qty not in (None, ""):
        return "quantity-break"
    if price_class == EVIDENCE_LIVE:
        return "distributor-list"
    return "recorded"


def classify_compliance_fields(
    row: dict[str, Any], *, identity_live: bool, requested_mpn: str
) -> dict[str, dict[str, Any]]:
    """Classify only declarations tied to the exact live supplier identity."""
    from src.normalizer import normalize_part_number

    root = row.get("compliance_evidence")
    root = root if isinstance(root, dict) else {}
    output: dict[str, dict[str, Any]] = {}
    requested_key = normalize_part_number(requested_mpn)
    for kind, label in (("rohs", "RoHS"), ("reach", "REACH"), ("pfas", "PFAS")):
        node = root.get(kind) if isinstance(root.get(kind), dict) else {}
        value = _first(
            node.get("reported_value"),
            node.get("status"),
            row.get(f"{kind}_status"),
            row.get(f"{label} status"),
        )
        source = _first(node.get("source"), row.get(f"{kind}_source"))
        source_url = _first(
            node.get("source_url"),
            node.get("url"),
            row.get(f"{kind}_source_url"),
            row.get(f"{kind}_evidence_url"),
        )
        retrieved_at = _first(
            node.get("retrieved_at"), row.get(f"{kind}_retrieved_at"),
        )
        node_mpn = str(node.get("mpn") or requested_mpn).strip()
        exact_mpn = bool(
            requested_key and normalize_part_number(node_mpn) == requested_key
        )
        node_class = str(
            node.get("evidence_class") or row.get(f"{kind}_evidence_class") or ""
        ).strip()
        live_declaration = bool(
            value
            and identity_live
            and exact_mpn
            and node_class == EVIDENCE_LIVE
            and _is_authorized_supplier_source(source)
            and source_url.startswith("https://")
        )
        if not value:
            classified = _field_envelope(
                evidence_class=EVIDENCE_MISSING,
                source=source,
                retrieved_at=retrieved_at,
                gap=f"No {label} declaration was returned by the supplier lookup; status is unknown.",
            )
        elif not exact_mpn:
            classified = _field_envelope(
                evidence_class=EVIDENCE_MISSING,
                source=source,
                retrieved_at=retrieved_at,
                gap=f"The {label} declaration could not be tied to the exact BOM part number.",
            )
        elif live_declaration:
            classified = _field_envelope(
                evidence_class=EVIDENCE_LIVE,
                source=source,
                retrieved_at=retrieved_at,
                gap=(
                    f"Supplier records disagree on {label}; review the linked declarations."
                    if bool(node.get("conflict")) else None
                ),
            )
        else:
            classified = _field_envelope(
                evidence_class=EVIDENCE_SYNTHETIC,
                source=source or EVIDENCE_SYNTHETIC,
                retrieved_at=retrieved_at,
                gap=f"The {label} value is recorded without verified exact-part supplier provenance.",
            )
        classified.update({
            "reported_value": value or None,
            "source_url": source_url,
            "manufacturer": str(node.get("manufacturer") or ""),
            "mpn": node_mpn if value else "",
            "conflict": bool(node.get("conflict")),
            "sources": node.get("sources") if isinstance(node.get("sources"), list) else [],
            "basis": str(node.get("basis") or ""),
        })
        output[kind] = classified
    return output


def _field_envelope(
    *,
    evidence_class: str,
    source: str = "",
    retrieved_at: str = "",
    price_type: str | None = None,
    gap: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "evidence_class": evidence_class,
        "source": source,
        "retrieved_at": retrieved_at,
    }
    if price_type is not None:
        payload["price_type"] = price_type
    if gap:
        payload["gap"] = gap
    return payload


def classify_commercial_fields(
    row: dict[str, Any],
    *,
    identity_live: bool,
    identity_source: str,
    identity_retrieved_at: str,
) -> dict[str, Any]:
    """Classify lifecycle/stock/price independently of identity liveness."""
    retrieved_fallback = _first(
        row.get("retrieved_at"),
        row.get("Sourcing Updated At"),
        row.get("sourcing_updated_at"),
        row.get("updated_at"),
        identity_retrieved_at,
    )

    lifecycle_value = _first(
        row.get("Lifecycle"),
        row.get("lifecycle_status"),
        row.get("Lifecycle Status"),
    )
    lifecycle_source = _first(
        row.get("lifecycle_source"),
        row.get("Lifecycle Source"),
        identity_source if identity_live else "",
        row.get("evidence_source"),
        row.get("source"),
    )
    if not _has_value(lifecycle_value) or lifecycle_value.casefold() in {"unknown", "not recorded"}:
        lifecycle = _field_envelope(
            evidence_class=EVIDENCE_MISSING,
            source=lifecycle_source,
            retrieved_at=_first(row.get("lifecycle_retrieved_at"), retrieved_fallback),
            gap="Lifecycle status was not recorded from an authorized source.",
        )
    elif _is_synthetic_label(lifecycle_source) or (
        not identity_live and _is_synthetic_label(row.get("evidence_source") or row.get("evidence_class"))
    ):
        lifecycle = _field_envelope(
            evidence_class=EVIDENCE_SYNTHETIC,
            source=lifecycle_source or EVIDENCE_SYNTHETIC,
            retrieved_at=_first(row.get("lifecycle_retrieved_at"), retrieved_fallback),
            gap="Lifecycle is a synthetic/preview estimate, not live supplier verification.",
        )
    elif identity_live and (
        _is_live_label(lifecycle_source)
        or _is_authorized_supplier_source(lifecycle_source)
        or not lifecycle_source
        or lifecycle_source == identity_source
    ):
        lifecycle = _field_envelope(
            evidence_class=EVIDENCE_LIVE,
            source=lifecycle_source or identity_source,
            retrieved_at=_first(row.get("lifecycle_retrieved_at"), retrieved_fallback),
        )
        if bool(row.get("lifecycle_conflict")) or lifecycle_value.casefold() in {
            "conflicting supplier data", "conflict"
        }:
            lifecycle["conflict"] = True
            lifecycle["gap"] = (
                "Authorized suppliers returned conflicting lifecycle statuses; reconcile the records before relying on the status."
            )
    else:
        lifecycle = _field_envelope(
            evidence_class=EVIDENCE_SYNTHETIC if lifecycle_source else EVIDENCE_MISSING,
            source=lifecycle_source or EVIDENCE_SYNTHETIC,
            retrieved_at=_first(row.get("lifecycle_retrieved_at"), retrieved_fallback),
        )

    stock_value = row.get("Stock")
    if stock_value is None:
        stock_value = row.get("stock_available")
    if stock_value is None:
        stock_value = row.get("stock")
    if stock_value is None:
        stock_value = row.get("Total Market Stock")
    if stock_value is None:
        stock_value = row.get("total_market_stock")
    stock_source = _first(
        row.get("stock_source"),
        row.get("Stock Source"),
        # Prefer explicit stock data sources over identity source.
        ", ".join(str(item) for item in (row.get("stock_data_sources") or row.get("Stock Data Sources") or []) if item)
        if isinstance(row.get("stock_data_sources") or row.get("Stock Data Sources"), list)
        else "",
        row.get("price_source") if _is_synthetic_label(row.get("price_source")) else "",
        identity_source if identity_live else "",
        row.get("evidence_source"),
        row.get("source"),
    )
    if not _has_value(stock_value):
        stock = _field_envelope(
            evidence_class=EVIDENCE_MISSING,
            source=stock_source,
            retrieved_at=_first(row.get("stock_retrieved_at"), retrieved_fallback),
            gap="Stock was not recorded from an authorized source.",
        )
    elif _is_synthetic_label(stock_source) or _is_synthetic_label(row.get("price_source")):
        stock = _field_envelope(
            evidence_class=EVIDENCE_SYNTHETIC,
            source=stock_source or EVIDENCE_SYNTHETIC,
            retrieved_at=_first(row.get("stock_retrieved_at"), retrieved_fallback),
            gap="Stock is a synthetic/preview estimate, not live supplier inventory.",
        )
    elif identity_live and (
        _is_live_label(stock_source)
        or _is_authorized_supplier_source(stock_source)
        or bool(row.get("stock_data_complete"))
        or (not stock_source and identity_live)
    ):
        stock = _field_envelope(
            evidence_class=EVIDENCE_LIVE,
            source=stock_source or identity_source,
            retrieved_at=_first(row.get("stock_retrieved_at"), retrieved_fallback),
        )
    else:
        stock = _field_envelope(
            evidence_class=EVIDENCE_SYNTHETIC if stock_source else EVIDENCE_MISSING,
            source=stock_source or EVIDENCE_SYNTHETIC,
            retrieved_at=_first(row.get("stock_retrieved_at"), retrieved_fallback),
        )

    price_value = row.get("Unit Price")
    if price_value is None:
        price_value = row.get("unit_price")
    if price_value is None:
        price_value = row.get("price")
    price_source = _first(
        row.get("price_source"),
        row.get("Price Source"),
        row.get("unit_price_source"),
    )
    offers = row.get("supplier_offers") or row.get("Supplier Offers") or []
    live_offer_price = False
    offer_retrieved = ""
    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            if offer.get("unit_price") is None and offer.get("price") is None:
                continue
            offer_source = _first(offer.get("source"), offer.get("supplier"), offer.get("evidence_class"))
            if _is_synthetic_label(offer_source):
                continue
            if _first(offer.get("retrieved_at")) or identity_live:
                live_offer_price = True
                offer_retrieved = _first(offer.get("retrieved_at"), offer_retrieved)
                if not price_source:
                    price_source = _first(offer.get("supplier"), offer.get("source"), identity_source)
                break

    price_present = _has_value(price_value)
    if not price_present:
        price_class = EVIDENCE_MISSING
        price_gap = "Unit price was not recorded from an authorized source."
    elif _is_synthetic_label(price_source) or (
        not price_source and _is_synthetic_label(row.get("evidence_source") or row.get("evidence_class"))
    ):
        # Explicit synthetic price — never promote to live because identity matched.
        price_class = EVIDENCE_SYNTHETIC
        price_source = price_source or EVIDENCE_SYNTHETIC
        price_gap = "Price is a synthetic/preview estimate, not a live distributor quote."
    elif live_offer_price or (_is_live_label(price_source) and identity_live):
        price_class = EVIDENCE_LIVE
        price_source = price_source or identity_source
        price_gap = None
    elif identity_live and not price_source:
        # Live identity alone must not wash an unlabeled/stub price into "live".
        price_class = EVIDENCE_SYNTHETIC
        price_source = EVIDENCE_SYNTHETIC
        price_gap = (
            "Identity was verified from an authorized supplier, but the recorded "
            "price is not backed by a live quote. Treat the price as unverified."
        )
    else:
        price_class = EVIDENCE_SYNTHETIC if price_source else EVIDENCE_MISSING
        price_source = price_source or (EVIDENCE_SYNTHETIC if price_present else "")
        price_gap = (
            "Price evidence is incomplete. Confirm an authorized distributor quote before ordering."
            if price_present
            else "Unit price was not recorded from an authorized source."
        )

    price = _field_envelope(
        evidence_class=price_class,
        source=price_source,
        retrieved_at=_first(
            row.get("price_retrieved_at"),
            offer_retrieved,
            retrieved_fallback if price_class == EVIDENCE_LIVE else "",
            retrieved_fallback if price_class == EVIDENCE_SYNTHETIC else "",
        ),
        price_type=_price_type_for_row(row, price_present=price_present, price_class=price_class),
        gap=price_gap,
    )

    lead_time_value = row.get("Lead Time Weeks")
    if lead_time_value is None:
        lead_time_value = row.get("lead_time_weeks")
    lead_time_source = _first(
        row.get("lead_time_source"), row.get("Lead Time Source")
    )
    lead_time_retrieved = _first(
        row.get("lead_time_retrieved_at"), row.get("Lead Time Retrieved At")
    )
    lead_time_rows = row.get("lead_time_evidence") or row.get("Lead Time Evidence") or []
    if not isinstance(lead_time_rows, list):
        lead_time_rows = []
    lead_time_row = next(
        (
            item for item in lead_time_rows
            if isinstance(item, dict)
            and str(item.get("source") or "").casefold() == lead_time_source.casefold()
            and str(item.get("weeks") if item.get("weeks") is not None else "")
            == str(lead_time_value if lead_time_value is not None else "")
        ),
        {},
    )
    lead_time_retrieved = _first(
        lead_time_retrieved, lead_time_row.get("retrieved_at")
    )
    if not _has_value(lead_time_value):
        lead_time = _field_envelope(
            evidence_class=EVIDENCE_MISSING,
            source=lead_time_source,
            retrieved_at=lead_time_retrieved,
            gap="Lead time was not returned by an authorized supplier lookup.",
        )
    elif identity_live and lead_time_source and lead_time_row and lead_time_retrieved:
        lead_time = _field_envelope(
            evidence_class=EVIDENCE_LIVE,
            source=lead_time_source,
            retrieved_at=lead_time_retrieved,
        )
    else:
        lead_time = _field_envelope(
            evidence_class=EVIDENCE_SYNTHETIC if lead_time_value not in (None, "") else EVIDENCE_MISSING,
            source=lead_time_source or EVIDENCE_SYNTHETIC,
            retrieved_at=lead_time_retrieved,
            gap="Lead time is recorded without a matching supplier field record; verify it before relying on it.",
        )

    compliance = classify_compliance_fields(
        row,
        identity_live=identity_live,
        requested_mpn=str(row.get("MPN") or row.get("manufacturer_part_number") or "").strip(),
    )

    identity = _field_envelope(
        evidence_class=EVIDENCE_LIVE if identity_live else (
            EVIDENCE_SYNTHETIC if _is_synthetic_label(identity_source) or identity_source else EVIDENCE_MISSING
        ),
        source=identity_source,
        retrieved_at=identity_retrieved_at,
    )
    return {
        "identity": identity,
        "lifecycle": lifecycle,
        "stock": stock,
        "price": price,
        "lead_time": lead_time,
        "compliance": compliance,
    }


def classify_part_evidence(part: dict[str, Any] | None) -> dict[str, Any]:
    """Return a normalized evidence envelope for one part row."""
    row = part if isinstance(part, dict) else {}
    requested = str(row.get("MPN") or row.get("manufacturer_part_number") or "").strip()
    source_label = _first(
        row.get("identity_source"),
        row.get("evidence_source"),
        row.get("source"),
    )
    # Never use price_source as the identity label — that washes commercial fields.
    explicit_class = str(row.get("evidence_class") or "").strip().casefold()
    bom_manufacturer = _first(
        row.get("BOM Manufacturer"), row.get("bom_manufacturer"),
        row.get("requested_manufacturer"),
    )
    supplier_manufacturer = _first(
        row.get("Supplier Manufacturer"), row.get("supplier_manufacturer"),
        row.get("manufacturer") if "bom upload" not in str(row.get("manufacturer_source") or "").casefold() else "",
    )
    manufacturer_identity_gap = ""
    if bom_manufacturer:
        try:
            from apps.api.manufacturer_identity import manufacturers_match

            manufacturer_matches = bool(
                supplier_manufacturer
                and manufacturers_match(bom_manufacturer, supplier_manufacturer, mpn=requested)
            )
        except Exception:  # noqa: BLE001
            manufacturer_matches = bool(
                supplier_manufacturer
                and supplier_manufacturer.casefold() == bom_manufacturer.casefold()
            )
        if not manufacturer_matches:
            manufacturer_identity_gap = (
                "The supplier manufacturer could not be matched to the manufacturer in the BOM."
            )

    live_candidate = {
        "manufacturer_part_number": row.get("manufacturer_part_number") or requested,
        "manufacturer": supplier_manufacturer or row.get("Manufacturer") or "",
        "source": row.get("source") or row.get("Supplier") or "",
        "lifecycle_status": row.get("Lifecycle") or row.get("lifecycle_status") or "",
        "product_detail_url": row.get("product_url") or row.get("source_url") or "",
        "datasheet_url": row.get("datasheet_url") or "",
        "retrieved_at": row.get("retrieved_at") or "",
        "supplier_data_verified": row.get("supplier_data_verified"),
        "provider_status": row.get("provider_status") or "AVAILABLE",
    }
    exact = exact_supplier_evidence(requested, live_candidate)
    if manufacturer_identity_gap:
        exact = None
    identity_retrieved = _first(
        (exact or {}).get("retrieved_at") if exact else "",
        row.get("identity_retrieved_at"),
        row.get("retrieved_at"),
        row.get("Sourcing Updated At"),
    )

    if explicit_class == EVIDENCE_MISSING:
        fields = classify_commercial_fields(
            row,
            identity_live=False,
            identity_source="",
            identity_retrieved_at=identity_retrieved,
        )
        return {
            "evidence_class": EVIDENCE_MISSING,
            "requested_mpn": requested,
            "identity_verified": False,
            "source": "",
            "source_url": "",
            "datasheet_url": "",
            "retrieved_at": identity_retrieved,
            "units": {
                "quantity": row.get("Quantity") or row.get("quantity"),
                "unit_price": row.get("Unit Price") or row.get("unit_price"),
                "currency": row.get("unit_price_currency") or row.get("currency") or "",
            },
            "fields": fields,
            "synthetic": False,
            "gap": manufacturer_identity_gap or "No live supplier evidence was available for this component.",
        }

    identity_live = bool(exact and source_label.casefold().startswith("live"))
    if identity_live:
        identity_source = _first((exact or {}).get("source"), source_label, EVIDENCE_LIVE)
        identity_retrieved = _first(identity_retrieved, utc_now())
        fields = classify_commercial_fields(
            row,
            identity_live=True,
            identity_source=identity_source,
            identity_retrieved_at=identity_retrieved,
        )
        return {
            "evidence_class": EVIDENCE_LIVE,
            "requested_mpn": requested,
            "identity_verified": True,
            "source": identity_source,
            "source_url": (exact or {}).get("product_detail_url") or "",
            "datasheet_url": (exact or {}).get("datasheet_url") or "",
            "retrieved_at": identity_retrieved,
            "units": {
                "quantity": row.get("Quantity") or row.get("quantity"),
                "unit_price": row.get("Unit Price") or row.get("unit_price"),
                "currency": row.get("unit_price_currency") or row.get("currency") or "",
            },
            "fields": fields,
            "synthetic": False,
            # Surface price caution when identity is live but price is not.
            "gap": (fields.get("price") or {}).get("gap")
            if (fields.get("price") or {}).get("evidence_class") != EVIDENCE_LIVE
            else None,
        }

    if requested:
        identity_source = source_label or EVIDENCE_SYNTHETIC
        fields = classify_commercial_fields(
            row,
            identity_live=False,
            identity_source=identity_source,
            identity_retrieved_at=identity_retrieved,
        )
        return {
            "evidence_class": EVIDENCE_SYNTHETIC if (source_label or row) else EVIDENCE_MISSING,
            "requested_mpn": requested,
            "identity_verified": False,
            "source": identity_source,
            "source_url": "",
            "datasheet_url": "",
            "retrieved_at": identity_retrieved,
            "units": {
                "quantity": row.get("Quantity") or row.get("quantity"),
                "unit_price": row.get("Unit Price") or row.get("unit_price"),
                "currency": row.get("unit_price_currency") or row.get("currency") or "",
            },
            "fields": fields,
            "synthetic": True,
            "gap": manufacturer_identity_gap or (
                "Not live authorized-supplier evidence. Treat values as "
                "synthetic-preview until provider credentials are configured "
                "on the migration API."
            ),
        }

    fields = classify_commercial_fields(
        row,
        identity_live=False,
        identity_source="",
        identity_retrieved_at="",
    )
    return {
        "evidence_class": EVIDENCE_MISSING,
        "requested_mpn": "",
        "identity_verified": False,
        "fields": fields,
        "synthetic": True,
        "gap": "No part identity available for evidence classification.",
    }


def evidence_mode_and_gap(
    *,
    live_count: int,
    synthetic_count: int,
    missing_count: int,
    configured_sources: int = 0,
    analysis_mode: str | None = None,
) -> tuple[str, str | None]:
    """Derive a banner mode/gap from row-level evidence counts."""
    if live_count and (synthetic_count or missing_count):
        return (
            "mixed-evidence",
            "Evidence varies by component. Check each row's identity, lifecycle, stock, and price sources before acting.",
        )
    if live_count:
        return ("live-source-evidence", None)
    if synthetic_count:
        gap = (
            "This saved analysis contains sample estimates, not distributor quotes. "
            "No supplier credentials are configured on this API service."
            if configured_sources == 0
            else "This saved analysis contains sample estimates, not distributor quotes. "
            "Supplier integrations are configured; run the BOM again to retrieve current supplier evidence."
        )
        return ("synthetic-preview", gap)
    if configured_sources == 0:
        return (
            "source-unavailable",
            "No supplier credentials are configured on this API service, so this analysis has no live distributor quotes.",
        )
    if analysis_mode and not _is_synthetic_label(analysis_mode):
        return (
            "source-check-complete",
            "No verified supplier quotes are saved for this analysis. Supplier integrations are configured; run the BOM again to check current availability and pricing.",
        )
    return (
        "synthetic-preview",
        "Detailed risk rows reflect the saved analysis evidence. Extended costs use recorded unit prices only when present — absent prices stay blank.",
    )


def annotate_report_parts(report: dict[str, Any] | None) -> dict[str, Any]:
    """Attach evidence envelopes to each part without mutating live claims."""
    payload = dict(report or {})
    parts = []
    for part in payload.get("parts") or []:
        row = dict(part) if isinstance(part, dict) else {"value": part}
        row["evidence"] = classify_part_evidence(row)
        parts.append(row)
    payload["parts"] = parts
    live_count = sum(
        1 for p in parts if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_LIVE
    )
    synthetic_count = sum(
        1 for p in parts if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_SYNTHETIC
    )
    missing_count = sum(
        1 for p in parts if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_MISSING
    )
    payload["evidence_summary"] = {
        "live_count": live_count,
        "synthetic_count": synthetic_count,
        "missing_count": missing_count,
        "live_lookups_enabled": live_count > 0,
        "live_price_count": sum(
            1
            for p in parts
            if ((p.get("evidence") or {}).get("fields") or {}).get("price", {}).get("evidence_class")
            == EVIDENCE_LIVE
        ),
        "synthetic_price_count": sum(
            1
            for p in parts
            if ((p.get("evidence") or {}).get("fields") or {}).get("price", {}).get("evidence_class")
            == EVIDENCE_SYNTHETIC
        ),
        "missing_price_count": sum(
            1
            for p in parts
            if ((p.get("evidence") or {}).get("fields") or {}).get("price", {}).get("evidence_class")
            == EVIDENCE_MISSING
        ),
    }
    return payload
