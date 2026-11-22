"""Evidence labeling for the Next.js migration API.

Separates live authorized-supplier evidence from synthetic/preview estimates.
Identity, lifecycle, stock, and price each keep their own source class,
retrieval time, and (for price) price type so a live identity never makes a
synthetic or missing price appear live.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

from src.decision_packet_evidence import exact_supplier_evidence


EVIDENCE_LIVE = "live-authorized-supplier"
EVIDENCE_SYNTHETIC = "synthetic-preview"
EVIDENCE_MISSING = "missing"
EVIDENCE_UNVERIFIED = "reported-unverified"


def _text(value: object, default: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    text = str(value or "").strip()
    return default if text.casefold() in {"", "nan", "none", "null", "nat"} else text


def _clean_bom_text(value: object) -> str:
    """Unwrap only the recognizable legacy KiCad BoardText representation."""
    try:
        from src.bom_intake import clean_text

        return clean_text(value)
    except Exception:  # noqa: BLE001
        return _text(value)


def _first(*values: object, default: str = "") -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return default


def _is_synthetic_label(value: object) -> bool:
    text = _text(value).casefold()
    return "synthetic" in text or "preview" in text


def _is_authorized_supplier_source(value: object) -> bool:
    """Recognize explicit distributor names without treating any URL as proof."""
    from src.supplier_source_identity import is_supported_distributor

    return any(
        is_supported_distributor(item)
        for item in re.split(r"[,;/|]", _text(value))
        if item.strip()
    )


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, str) and value.strip().casefold() in {"nan", "none", "null", "nat"}:
        return False
    if isinstance(value, (list, tuple, dict)) and not value:
        return False
    return True


def _has_aware_timestamp(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _has_current_timestamp(value: object, *, now: datetime | None = None) -> bool:
    """Require an aware retrieval time that is not in the future."""
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    current_time = (
        now.astimezone(timezone.utc)
        if now is not None and now.tzinfo is not None
        else datetime.now(timezone.utc)
    )
    return parsed.astimezone(timezone.utc) <= current_time


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _price_type_for_row(row: dict[str, Any], *, price_present: bool, price_class: str) -> str:
    if not price_present or price_class == EVIDENCE_MISSING:
        return "not-recorded"
    if price_class == EVIDENCE_SYNTHETIC:
        return "synthetic-estimate"
    if price_class == EVIDENCE_UNVERIFIED:
        return "unverified"
    explicit = _first(row.get("price_type"), row.get("Price Type"))
    if explicit:
        return explicit
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
    row: dict[str, Any], *, identity_live: bool, requested_mpn: str,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Classify only declarations tied to the exact live supplier identity."""
    from src.normalizer import normalize_part_number

    root = row.get("compliance_evidence")
    root = root if isinstance(root, dict) else {}
    output: dict[str, dict[str, Any]] = {}
    requested_mpn = _clean_bom_text(requested_mpn)
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
        node_mpn = _clean_bom_text(node.get("mpn") or requested_mpn)
        exact_mpn = bool(
            requested_key and normalize_part_number(node_mpn) == requested_key
        )
        node_class = str(
            node.get("evidence_class") or row.get(f"{kind}_evidence_class") or ""
        ).strip()
        source_readings = node.get("sources") if isinstance(node.get("sources"), list) else []
        from src.supplier_source_identity import supplier_listing_url_is_valid

        source_backed = False
        for reading in source_readings:
            if not isinstance(reading, dict):
                continue
            reading_mpn = _clean_bom_text(reading.get("mpn"))
            reading_source = _first(reading.get("source"), reading.get("supplier"))
            reading_url = _first(reading.get("source_url"), reading.get("url"))
            reading_value = _first(reading.get("reported_value"), reading.get("status"))
            reading_time = _first(reading.get("retrieved_at"))
            source_backed = bool(
                reading_value
                and requested_key
                and normalize_part_number(reading_mpn) == requested_key
                and _is_authorized_supplier_source(reading_source)
                and supplier_listing_url_is_valid(reading_source, reading_url)
                and _has_current_timestamp(reading_time, now=now)
            )
            if source_backed:
                break
        live_declaration = bool(
            value
            and identity_live
            and exact_mpn
            and node_class == EVIDENCE_LIVE
            and source_backed
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
                    if bool(node.get("conflict"))
                    else str(node.get("review_note") or f"{label} evidence is partial or qualified; review the linked declarations.")
                    if bool(node.get("partial"))
                    else None
                ),
            )
        else:
            classified = _field_envelope(
                evidence_class=(
                    EVIDENCE_SYNTHETIC
                    if _is_synthetic_label(node_class) or _is_synthetic_label(source)
                    else EVIDENCE_UNVERIFIED
                ),
                source=source or (
                    EVIDENCE_SYNTHETIC
                    if _is_synthetic_label(node_class)
                    else "Recorded declaration"
                ),
                retrieved_at=retrieved_at,
                gap=f"The {label} value is recorded without verified exact-part supplier provenance.",
            )
        classified.update({
            "reported_value": value or None,
            "source_url": source_url,
            "manufacturer": str(node.get("manufacturer") or ""),
            "mpn": node_mpn if value else "",
            "conflict": bool(node.get("conflict")),
            "partial": bool(node.get("partial")),
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


_CURRENT_FIELD_MAX_AGE_SECONDS = {
    "stock": 24 * 60 * 60,
    "price": 24 * 60 * 60,
    "lead_time": 7 * 24 * 60 * 60,
    "lifecycle": 30 * 24 * 60 * 60,
}


def _apply_field_freshness(
    field: str,
    envelope: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Keep old distributor snapshots visible without calling them current."""
    if envelope.get("evidence_class") != EVIDENCE_LIVE:
        envelope["current"] = False
        envelope["freshness"] = "not-verified"
        return envelope
    retrieved = _parse_aware_utc(envelope.get("retrieved_at"))
    if retrieved is None:
        envelope["recorded_evidence_class"] = EVIDENCE_LIVE
        envelope["evidence_class"] = EVIDENCE_UNVERIFIED
        envelope["current"] = False
        envelope["freshness"] = "unknown"
        envelope["gap"] = "The supplier snapshot has no valid retrieval timestamp."
        return envelope
    current_time = now.astimezone(timezone.utc) if now and now.tzinfo else datetime.now(timezone.utc)
    raw_age_seconds = (current_time - retrieved).total_seconds()
    if raw_age_seconds < 0:
        envelope["recorded_evidence_class"] = EVIDENCE_LIVE
        envelope["evidence_class"] = EVIDENCE_UNVERIFIED
        envelope["current"] = False
        envelope["freshness"] = "invalid-future-timestamp"
        envelope["age_seconds"] = None
        envelope["freshness_limit_seconds"] = _CURRENT_FIELD_MAX_AGE_SECONDS[field]
        note = f"Supplier {field.replace('_', ' ')} snapshot has a future retrieval timestamp; refresh it before use."
        envelope["gap"] = f"{envelope.get('gap')}; {note}" if envelope.get("gap") else note
        return envelope
    age_seconds = int(raw_age_seconds)
    envelope["age_seconds"] = age_seconds
    envelope["freshness_limit_seconds"] = _CURRENT_FIELD_MAX_AGE_SECONDS[field]
    if age_seconds > _CURRENT_FIELD_MAX_AGE_SECONDS[field]:
        envelope["recorded_evidence_class"] = EVIDENCE_LIVE
        envelope["evidence_class"] = EVIDENCE_UNVERIFIED
        envelope["current"] = False
        envelope["freshness"] = "stale"
        hours = age_seconds // 3600
        age = f"{hours} hours" if hours < 48 else f"{age_seconds // 86400} days"
        note = f"Supplier snapshot is {age} old; refresh it before treating {field.replace('_', ' ')} as current."
        envelope["gap"] = f"{envelope.get('gap')}; {note}" if envelope.get("gap") else note
    else:
        envelope["current"] = True
        envelope["freshness"] = "current"
    return envelope


def is_current_supplier_snapshot(
    field: str,
    retrieved_at: object,
    *,
    now: datetime | None = None,
) -> bool:
    """Apply the shared field-specific age limit to a distributor reading.

    Procurement tables also consume saved offer rows directly. Keep those rows
    on the same freshness policy as reports so a timestamp that is merely
    present cannot make stale stock or lead-time data look current.
    """
    if field not in _CURRENT_FIELD_MAX_AGE_SECONDS:
        return False
    envelope = _apply_field_freshness(
        field,
        {"evidence_class": EVIDENCE_LIVE, "retrieved_at": retrieved_at},
        now=now,
    )
    return envelope.get("current") is True


def _parse_aware_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def classify_commercial_fields(
    row: dict[str, Any],
    *,
    identity_live: bool,
    identity_source: str,
    identity_retrieved_at: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify lifecycle/stock/price independently of identity liveness."""
    current_time = now.astimezone(timezone.utc) if now and now.tzinfo else datetime.now(timezone.utc)
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
    lifecycle_evidence = row.get("lifecycle_evidence") or row.get("Lifecycle Evidence") or []
    if isinstance(lifecycle_evidence, str):
        try:
            import json

            lifecycle_evidence = json.loads(lifecycle_evidence)
        except (TypeError, ValueError):
            lifecycle_evidence = []
    if isinstance(lifecycle_evidence, dict):
        lifecycle_evidence = [lifecycle_evidence]
    lifecycle_source_backed = False
    lifecycle_record_retrieved_at = ""
    from src.supplier_source_identity import supplier_listing_url_is_valid

    if isinstance(lifecycle_evidence, list):
        from src.normalizer import normalize_part_number

        requested_lifecycle_mpn = normalize_part_number(_clean_bom_text(
            _first(row.get("MPN"), row.get("mpn"), row.get("manufacturer_part_number"))
        ))
        lifecycle_key = " ".join(lifecycle_value.casefold().replace("_", " ").split())
        matched_lifecycle_rows = []
        for item in lifecycle_evidence:
            if not isinstance(item, dict):
                continue
            item_mpn = normalize_part_number(_clean_bom_text(item.get("mpn")))
            item_source = _first(item.get("source"), item.get("supplier"))
            item_url = _first(item.get("product_url"), item.get("source_url"), item.get("url"))
            item_status = " ".join(
                _first(item.get("normalized_status"), item.get("status")).casefold().replace("_", " ").split()
            )
            item_time = _first(item.get("retrieved_at"))
            valid_source = bool(
                requested_lifecycle_mpn
                and item_mpn == requested_lifecycle_mpn
                and _is_authorized_supplier_source(item_source)
                and supplier_listing_url_is_valid(item_source, item_url)
                and item_status
                and _has_current_timestamp(item_time, now=now)
            )
            if valid_source:
                matched_lifecycle_rows.append(item)
        if lifecycle_key in {"conflicting supplier data", "conflict"}:
            normalized_statuses = {
                " ".join(
                    _first(item.get("normalized_status"), item.get("status")).casefold().replace("_", " ").split()
                )
                for item in matched_lifecycle_rows
            }
            lifecycle_source_backed = len(normalized_statuses) > 1
        else:
            lifecycle_source_backed = any(
                " ".join(
                    _first(item.get("normalized_status"), item.get("status")).casefold().replace("_", " ").split()
                ) == lifecycle_key
                for item in matched_lifecycle_rows
            )
        matching_lifecycle_rows = [
            item for item in matched_lifecycle_rows
            if lifecycle_key in {"conflicting supplier data", "conflict"}
            or " ".join(
                _first(item.get("normalized_status"), item.get("status")).casefold().replace("_", " ").split()
            ) == lifecycle_key
        ]
        lifecycle_record_retrieved_at = max(
            (_first(item.get("retrieved_at")) for item in matching_lifecycle_rows),
            default="",
        )
    lifecycle_retrieved_at = _first(
        row.get("lifecycle_retrieved_at"), lifecycle_record_retrieved_at
    ) or retrieved_fallback

    if not _has_value(lifecycle_value) or lifecycle_value.casefold() in {"unknown", "not recorded"}:
        lifecycle = _field_envelope(
            evidence_class=EVIDENCE_MISSING,
            source=lifecycle_source,
            retrieved_at=lifecycle_retrieved_at,
            gap="Lifecycle status was not recorded from an authorized source.",
        )
    elif _is_synthetic_label(lifecycle_source) or (
        not identity_live and _is_synthetic_label(row.get("evidence_source") or row.get("evidence_class"))
    ):
        lifecycle = _field_envelope(
            evidence_class=EVIDENCE_SYNTHETIC,
            source=lifecycle_source or EVIDENCE_SYNTHETIC,
            retrieved_at=lifecycle_retrieved_at,
            gap="Lifecycle is a synthetic/preview estimate, not live supplier verification.",
        )
    elif identity_live and lifecycle_source_backed:
        lifecycle = _field_envelope(
            evidence_class=EVIDENCE_LIVE,
            source=lifecycle_source,
            retrieved_at=lifecycle_retrieved_at,
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
            evidence_class=EVIDENCE_UNVERIFIED,
            source=lifecycle_source or "Recorded lifecycle value",
            retrieved_at=lifecycle_retrieved_at,
            gap="The lifecycle value has no timestamped, exact-MPN authorized-supplier record attached.",
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
        identity_source if identity_live else "",
        row.get("evidence_source"),
        row.get("source"),
    )
    stock_observations = row.get("stock_evidence") or row.get("Stock Evidence") or []
    if isinstance(stock_observations, str):
        try:
            import json

            stock_observations = json.loads(stock_observations)
        except (TypeError, ValueError):
            stock_observations = []
    if isinstance(stock_observations, dict):
        stock_observations = [stock_observations]
    from src.normalizer import normalize_part_number
    from integrations.stock_coercion import parse_stock_total

    requested_mpn = _clean_bom_text(
        _first(row.get("MPN"), row.get("mpn"), row.get("manufacturer_part_number"))
    )
    requested_mpn_key = normalize_part_number(requested_mpn)

    def _parse_timestamp(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    latest_stock_by_source: dict[str, dict[str, Any]] = {}
    stale_stock_observation = False
    future_stock_observation = False
    if isinstance(stock_observations, list) and requested_mpn_key:
        for observation in stock_observations:
            if not isinstance(observation, dict):
                continue
            observation_mpn = _clean_bom_text(observation.get("mpn"))
            source = _first(observation.get("source"), observation.get("supplier"))
            quantity = parse_stock_total(observation.get("stock", observation.get("stock_total")))
            retrieved_at = _parse_timestamp(observation.get("retrieved_at"))
            if (
                normalize_part_number(observation_mpn) != requested_mpn_key
                or not _is_authorized_supplier_source(source)
                or quantity is None
                or retrieved_at is None
            ):
                continue
            if retrieved_at > current_time:
                future_stock_observation = True
                continue
            if (current_time - retrieved_at).total_seconds() > _CURRENT_FIELD_MAX_AGE_SECONDS["stock"]:
                stale_stock_observation = True
                continue
            normalized_source = "".join(
                character for character in str(source).casefold()
                if character.isalnum()
            )
            candidate = {
                **observation,
                "source": source,
                "mpn": observation_mpn,
                "stock": quantity,
                "retrieved_at": retrieved_at.isoformat(),
                "_retrieved_at_utc": retrieved_at,
            }
            previous = latest_stock_by_source.get(normalized_source)
            if (
                previous is None
                or retrieved_at > previous["_retrieved_at_utc"]
            ):
                latest_stock_by_source[normalized_source] = candidate
    matched_stock_observations = [
        {key: value for key, value in item.items() if key != "_retrieved_at_utc"}
        for item in latest_stock_by_source.values()
    ]
    reported_stock = parse_stock_total(stock_value)
    observed_stock = (
        sum(int(item["stock"]) for item in matched_stock_observations)
        if matched_stock_observations
        else None
    )
    stock_sources = sorted({
        str(item["source"]).strip()
        for item in matched_stock_observations
        if str(item.get("source") or "").strip()
    })
    stock_retrieved_at = max(
        (str(item.get("retrieved_at") or "") for item in matched_stock_observations),
        default="",
    )
    stock_snapshot_matches = bool(
        reported_stock is not None
        and observed_stock is not None
        and reported_stock == observed_stock
    )
    stock_complete = row.get("stock_data_complete") is True or str(
        row.get("stock_data_complete") or ""
    ).strip().casefold() in {"1", "true", "yes"}
    stock_complete = stock_complete and not stale_stock_observation and not future_stock_observation
    if not _has_value(stock_value):
        stock = _field_envelope(
            evidence_class=EVIDENCE_MISSING,
            source=stock_source,
            retrieved_at=_first(row.get("stock_retrieved_at"), retrieved_fallback),
            gap="Stock was not recorded from an authorized source.",
        )
    elif _is_synthetic_label(stock_source) or _is_synthetic_label(row.get("evidence_source")):
        stock = _field_envelope(
            evidence_class=EVIDENCE_SYNTHETIC,
            source=stock_source or EVIDENCE_SYNTHETIC,
            retrieved_at=_first(row.get("stock_retrieved_at"), retrieved_fallback),
            gap="Stock is a synthetic/preview estimate, not live supplier inventory.",
        )
    elif stale_stock_observation:
        stock = _field_envelope(
            evidence_class=EVIDENCE_UNVERIFIED,
            source=stock_source or ", ".join(stock_sources),
            retrieved_at=stock_retrieved_at,
            gap="At least one supplier stock reading is older than 24 hours; refresh all configured sources before treating the aggregate as current.",
        )
    elif future_stock_observation:
        stock = _field_envelope(
            evidence_class=EVIDENCE_UNVERIFIED,
            source=stock_source or ", ".join(stock_sources),
            retrieved_at="",
            gap="A supplier stock reading has a future retrieval timestamp and was excluded; refresh supplier data before relying on the stock total.",
        )
    elif identity_live and stock_snapshot_matches:
        stock = _field_envelope(
            evidence_class=EVIDENCE_LIVE,
            source=", ".join(stock_sources),
            retrieved_at=stock_retrieved_at,
            gap=None if stock_complete else (
                "Supplier API inventory readings are exact-part snapshots, but supplier coverage is incomplete; this is not checkout inventory."
            ),
        )
    else:
        stock = _field_envelope(
            evidence_class=EVIDENCE_UNVERIFIED,
            source=stock_source or "Recorded stock value",
            retrieved_at="",
            gap=(
                "The stock total does not reconcile to timestamped exact-MPN supplier readings; verify the source records before relying on it."
            ),
        )
    stock.update({
        "reported_value": stock_value,
        "sources": matched_stock_observations,
        "complete": stock_complete,
        "observed_total": observed_stock,
    })

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
    price_present = _has_value(price_value)
    offers = row.get("supplier_offers") or row.get("Supplier Offers") or []
    if isinstance(offers, str):
        try:
            import json

            offers = json.loads(offers)
        except (TypeError, ValueError):
            offers = []
    if isinstance(offers, dict):
        offers = [offers]
    primary_supplier = _first(
        row.get("Best Source"), row.get("primary_supplier"), row.get("source")
    )
    price_supplier = (
        price_source
        if _is_authorized_supplier_source(price_source)
        else primary_supplier
    )
    price_currency = _first(
        row.get("unit_price_currency"), row.get("Unit Price Currency"),
        row.get("currency"), row.get("Currency"),
    )
    effective_quantity = _first(
        row.get("Effective Quantity"), row.get("effective_quantity"),
        row.get("Quantity"), row.get("quantity"), row.get("qty"),
    )
    matching_offer = None
    recorded_offer = None
    if identity_live and price_present and isinstance(offers, list):
        try:
            from src.saved_bom_cost import select_supplier_offer

            matching_offer = select_supplier_offer(
                offers,
                mpn=requested_mpn,
                supplier=price_supplier,
                unit_price=price_value,
                currency=price_currency,
                quantity=effective_quantity,
                require_current=True,
                now=current_time,
            )
            if matching_offer is None:
                recorded_offer = select_supplier_offer(
                    offers,
                    mpn=requested_mpn,
                    supplier=price_supplier,
                    unit_price=price_value,
                    currency=price_currency,
                    quantity=effective_quantity,
                    require_current=False,
                    now=current_time,
                )
                recorded_at = _parse_aware_utc((recorded_offer or {}).get("retrieved_at"))
                if recorded_at is not None and recorded_at > current_time:
                    recorded_offer = None
        except (TypeError, ValueError):
            matching_offer = None
            recorded_offer = None

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
    elif matching_offer is not None and matching_offer.get("quantity_break_applies") is True:
        price_class = EVIDENCE_LIVE
        price_source = str(matching_offer.get("distributor") or price_supplier or identity_source)
        price_gap = None
    elif matching_offer is not None:
        price_class = EVIDENCE_UNVERIFIED
        price_source = str(matching_offer.get("distributor") or price_supplier or "Recorded price")
        price_gap = (
            "The supplier API price is recorded at a quantity break, but the BOM quantity is missing; applicability and extended cost are not established."
        )
    elif recorded_offer is not None and recorded_offer.get("quantity_break_applies") is True:
        # Preserve exact old prices in the evidence record, then let the common
        # freshness rule mark them stale rather than making them look missing.
        price_class = EVIDENCE_LIVE
        price_source = str(recorded_offer.get("distributor") or price_supplier or identity_source)
        price_gap = None
    elif price_present:
        price_class = EVIDENCE_UNVERIFIED
        price_source = price_source or primary_supplier or "Recorded price"
        price_gap = (
            "The recorded amount could not be matched to an exact-MPN offer from the same authorized supplier with currency, retrieval time, and an applicable quantity break."
        )
    else:
        price_class = EVIDENCE_MISSING
        price_gap = "Unit price was not recorded from an authorized source."

    price = _field_envelope(
        evidence_class=price_class,
        source=price_source,
        retrieved_at=_first(
            row.get("price_retrieved_at"),
            (matching_offer or {}).get("retrieved_at") if matching_offer else "",
            (recorded_offer or {}).get("retrieved_at") if recorded_offer else "",
            retrieved_fallback if price_class == EVIDENCE_LIVE else "",
            retrieved_fallback if price_class == EVIDENCE_SYNTHETIC else "",
        ),
        price_type=_price_type_for_row(row, price_present=price_present, price_class=price_class),
        gap=price_gap,
    )
    price.update({
        "reported_value": price_value,
        "currency": (matching_offer or recorded_offer or {}).get("currency") or price_currency or "",
        "price_break_quantity": (matching_offer or recorded_offer or {}).get("price_break_quantity"),
        "quantity_break_applies": (
            bool((matching_offer or recorded_offer or {}).get("quantity_break_applies"))
            if matching_offer or recorded_offer
            else False
        ),
        "product_url": (matching_offer or recorded_offer or {}).get("product_url") or "",
    })

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
    from src.normalizer import normalize_part_number

    requested_lead_mpn = normalize_part_number(_clean_bom_text(
        _first(row.get("MPN"), row.get("mpn"), row.get("manufacturer_part_number"))
    ))
    lead_time_row = next(
        (
            item for item in lead_time_rows
            if isinstance(item, dict)
            and str(item.get("source") or "").casefold() == lead_time_source.casefold()
            and str(item.get("weeks") if item.get("weeks") is not None else "")
            == str(lead_time_value if lead_time_value is not None else "")
            and normalize_part_number(_clean_bom_text(item.get("mpn"))) == requested_lead_mpn
            and _is_authorized_supplier_source(item.get("source"))
            and supplier_listing_url_is_valid(
                item.get("source"),
                item.get("product_url") or item.get("source_url"),
            )
            and _has_current_timestamp(item.get("retrieved_at"), now=now)
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
            evidence_class=(
                EVIDENCE_SYNTHETIC
                if _is_synthetic_label(lead_time_source) or _is_synthetic_label(row.get("evidence_source"))
                else EVIDENCE_UNVERIFIED
            ),
            source=lead_time_source or (
                EVIDENCE_SYNTHETIC
                if _is_synthetic_label(row.get("evidence_source"))
                else "Recorded lead time"
            ),
            retrieved_at=lead_time_retrieved,
            gap="Lead time is recorded without a matching supplier field record; verify it before relying on it.",
        )

    compliance = classify_compliance_fields(
        row,
        identity_live=identity_live,
        requested_mpn=_clean_bom_text(row.get("MPN") or row.get("manufacturer_part_number") or ""),
        now=now,
    )

    identity = _field_envelope(
        evidence_class=EVIDENCE_LIVE if identity_live else (
            EVIDENCE_SYNTHETIC if _is_synthetic_label(identity_source)
            else EVIDENCE_UNVERIFIED if identity_source
            else EVIDENCE_MISSING
        ),
        source=identity_source,
        retrieved_at=identity_retrieved_at,
    )
    for field_name, field_envelope in (
        ("lifecycle", lifecycle),
        ("stock", stock),
        ("price", price),
        ("lead_time", lead_time),
    ):
        _apply_field_freshness(field_name, field_envelope, now=now)
    for field_envelope in compliance.values():
        _apply_field_freshness("lifecycle", field_envelope, now=now)

    return {
        "identity": identity,
        "lifecycle": lifecycle,
        "stock": stock,
        "price": price,
        "lead_time": lead_time,
        "compliance": compliance,
    }


def classify_part_evidence(
    part: dict[str, Any] | None, *, now: datetime | None = None
) -> dict[str, Any]:
    """Return a normalized evidence envelope for one part row."""
    row = part if isinstance(part, dict) else {}
    requested = _clean_bom_text(
        row.get("MPN")
        or row.get("mpn")
        or row.get("manufacturer_part_number")
        or row.get("part_number")
        or ""
    )
    source_label = _first(
        row.get("identity_source"),
        row.get("evidence_source"),
        row.get("source"),
    )
    # Never use price_source as the identity label — that washes commercial fields.
    explicit_class = str(row.get("evidence_class") or "").strip().casefold()
    # Preserve a previously classified synthetic marker. Never accept a saved
    # "live" envelope as proof: live status is rebuilt from the raw supplier
    # identity and field provenance below.
    saved_envelope = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    if not _is_synthetic_label(explicit_class) and _is_synthetic_label(
        saved_envelope.get("evidence_class")
    ):
        explicit_class = EVIDENCE_SYNTHETIC
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
        "manufacturer_part_number": _clean_bom_text(
            row.get("manufacturer_part_number")
            or row.get("Manufacturer Part Number")
            or row.get("matched_mpn")
            or ""
        ),
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
    from src.supplier_source_identity import supplier_listing_url_is_valid

    if (
        exact
        and exact.get("product_detail_url")
        and not supplier_listing_url_is_valid(
            exact.get("source"), exact.get("product_detail_url")
        )
    ):
        exact = None
    if manufacturer_identity_gap:
        exact = None
    identity_retrieved = _first(
        (exact or {}).get("retrieved_at") if exact else "",
        row.get("identity_retrieved_at"),
        row.get("retrieved_at"),
        row.get("Sourcing Updated At"),
    )

    source_name = _first(row.get("source"), row.get("Supplier"), row.get("Best Source"))
    provider_status = str(row.get("provider_status") or "AVAILABLE").strip().upper()
    identity_live = bool(
        exact
        and source_label.casefold().startswith("live")
        and _is_authorized_supplier_source(source_name)
        and _truthy(row.get("supplier_data_verified"))
        and provider_status == "AVAILABLE"
        and _has_current_timestamp(identity_retrieved, now=now)
        and not _is_synthetic_label(explicit_class)
        and not _is_synthetic_label(source_label)
    )
    if identity_live:
        identity_source = _first((exact or {}).get("source"), source_label, EVIDENCE_LIVE)
        fields = classify_commercial_fields(
            row,
            identity_live=True,
            identity_source=identity_source,
            identity_retrieved_at=identity_retrieved,
            now=now,
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
        explicitly_synthetic = any(
            _is_synthetic_label(candidate)
            for candidate in (
                explicit_class,
                source_label,
                row.get("evidence_source"),
                row.get("evidence_class"),
                row.get("identity_source"),
            )
        )
        has_recorded_supplier_source = bool(
            source_label
            and str(source_label).strip().casefold()
            not in {"missing", "not recorded", "not reported", "unknown"}
            and explicit_class != EVIDENCE_MISSING
        )
        unverified = has_recorded_supplier_source and not explicitly_synthetic
        identity_source = (
            EVIDENCE_SYNTHETIC
            if explicitly_synthetic
            else source_label
        )
        fields = classify_commercial_fields(
            row,
            identity_live=False,
            identity_source=identity_source,
            identity_retrieved_at=identity_retrieved,
        )
        overall_class = (
            EVIDENCE_SYNTHETIC
            if explicitly_synthetic
            else EVIDENCE_UNVERIFIED
            if unverified
            else EVIDENCE_MISSING
        )
        return {
            "evidence_class": overall_class,
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
            "synthetic": overall_class == EVIDENCE_SYNTHETIC,
            "gap": manufacturer_identity_gap or (
                "The recorded supplier identity could not be verified against an exact part number."
                if unverified
                else "No live supplier identity or field-level evidence is attached to this component."
                if overall_class == EVIDENCE_MISSING
                else "This is synthetic preview data, not supplier evidence."
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
        "synthetic": False,
        "gap": "No part identity available for evidence classification.",
    }


def evidence_mode_and_gap(
    *,
    live_count: int,
    synthetic_count: int,
    missing_count: int,
    unverified_count: int = 0,
    configured_sources: int = 0,
    analysis_mode: str | None = None,
) -> tuple[str, str | None]:
    """Derive a banner mode/gap from row-level evidence counts."""
    present_classes = sum(
        1 for count in (live_count, synthetic_count, missing_count, unverified_count)
        if count > 0
    )
    if present_classes > 1:
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
    if unverified_count:
        return (
            "source-check-complete",
            "Supplier data was recorded, but exact part identity or field-level provenance could not be verified. Review the source evidence and rerun the BOM before relying on it.",
        )
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
    """Attach evidence and recalculate customer-facing risk from current evidence.

    Saved rows can carry risk labels from an older scoring contract. Expose a
    fresh label and matching aggregates so report summaries, component signals,
    detailed-risk views, and exports do not disagree.
    """
    payload = dict(report or {})
    parts = []
    report_is_synthetic = _is_synthetic_label(payload.get("mode"))
    risk_counts = {"high": 0, "medium": 0, "low": 0}
    from src.risk_engine import calculate_risk

    for part in payload.get("parts") or []:
        row = dict(part) if isinstance(part, dict) else {"value": part}
        if report_is_synthetic:
            row["evidence_class"] = EVIDENCE_SYNTHETIC
            row["identity_source"] = EVIDENCE_SYNTHETIC
            row["evidence_source"] = EVIDENCE_SYNTHETIC
        row["evidence"] = classify_part_evidence(row)

        # Historical risk fields are display snapshots, not inputs. Rebuild
        # them from the same field-level evidence contract used by detailed
        # risk and report exports.
        assessment = calculate_risk(row)
        risk_level = str(assessment.get("risk_level") or "Needs verification")
        risk_score = assessment.get("risk_score")
        risk_reasons = assessment.get("risk_reasons") or []
        normalized_level = risk_level.casefold()
        if normalized_level in {"high", "critical"}:
            risk_counts["high"] += 1
        elif normalized_level == "medium":
            risk_counts["medium"] += 1
        elif normalized_level in {"low", "healthy"}:
            risk_counts["low"] += 1
        row["Risk Level"] = risk_level
        row["risk_level"] = risk_level
        row["risk_level_display"] = risk_level
        row["Risk Score"] = risk_score
        row["risk_score"] = risk_score
        row["Risk Reasons"] = "; ".join(
            str(item).strip() for item in risk_reasons if str(item).strip()
        )
        row["risk_reasons"] = risk_reasons
        parts.append(row)

    payload["parts"] = parts
    payload["high_risk_count"] = risk_counts["high"]
    payload["medium_risk_count"] = risk_counts["medium"]
    payload["low_risk_count"] = risk_counts["low"]
    live_count = sum(
        1 for p in parts if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_LIVE
    )
    synthetic_count = sum(
        1 for p in parts if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_SYNTHETIC
    )
    missing_count = sum(
        1 for p in parts if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_MISSING
    )
    unverified_count = sum(
        1 for p in parts if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_UNVERIFIED
    )
    payload["evidence_summary"] = {
        "live_count": live_count,
        "synthetic_count": synthetic_count,
        "missing_count": missing_count,
        "unverified_count": unverified_count,
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
        "unverified_price_count": sum(
            1
            for p in parts
            if ((p.get("evidence") or {}).get("fields") or {}).get("price", {}).get("evidence_class")
            == EVIDENCE_UNVERIFIED
        ),
        "unverified_stock_count": sum(
            1
            for p in parts
            if ((p.get("evidence") or {}).get("fields") or {}).get("stock", {}).get("evidence_class")
            == EVIDENCE_UNVERIFIED
        ),
        "unverified_lifecycle_count": sum(
            1
            for p in parts
            if ((p.get("evidence") or {}).get("fields") or {}).get("lifecycle", {}).get("evidence_class")
            == EVIDENCE_UNVERIFIED
        ),
    }
    return payload
