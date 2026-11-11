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
    elif identity_live and (_is_live_label(lifecycle_source) or not lifecycle_source or lifecycle_source == identity_source):
        lifecycle = _field_envelope(
            evidence_class=EVIDENCE_LIVE,
            source=lifecycle_source or identity_source,
            retrieved_at=_first(row.get("lifecycle_retrieved_at"), retrieved_fallback),
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
    live_candidate = {
        "manufacturer_part_number": row.get("manufacturer_part_number") or requested,
        "manufacturer": row.get("Manufacturer") or row.get("manufacturer") or "",
        "source": row.get("source") or row.get("Supplier") or "",
        "lifecycle_status": row.get("Lifecycle") or row.get("lifecycle_status") or "",
        "product_detail_url": row.get("product_url") or row.get("source_url") or "",
        "datasheet_url": row.get("datasheet_url") or "",
        "retrieved_at": row.get("retrieved_at") or "",
        "supplier_data_verified": row.get("supplier_data_verified"),
        "provider_status": row.get("provider_status") or "AVAILABLE",
    }
    exact = exact_supplier_evidence(requested, live_candidate)
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
            "gap": "No live supplier evidence was available for this component.",
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
            "gap": (
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
