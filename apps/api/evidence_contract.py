"""Evidence labeling for the Next.js migration API.

Separates live authorized-supplier evidence from synthetic/preview estimates.
Never invents distributor facts. Live lookups stay disabled until the migration
service is explicitly authorized for provider credentials.
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


def classify_part_evidence(part: dict[str, Any] | None) -> dict[str, Any]:
    """Return a normalized evidence envelope for one part row."""
    row = part if isinstance(part, dict) else {}
    requested = str(row.get("MPN") or row.get("manufacturer_part_number") or "").strip()
    source_label = str(
        row.get("evidence_source")
        or row.get("price_source")
        or row.get("source")
        or ""
    ).strip()
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
    if explicit_class == EVIDENCE_MISSING:
        return {
            "evidence_class": EVIDENCE_MISSING,
            "requested_mpn": requested,
            "identity_verified": False,
            "source": "",
            "source_url": "",
            "datasheet_url": "",
            "retrieved_at": row.get("retrieved_at") or "",
            "units": {
                "quantity": row.get("Quantity") or row.get("quantity"),
                "unit_price": row.get("Unit Price") or row.get("unit_price"),
                "currency": row.get("unit_price_currency") or row.get("currency") or "",
            },
            "synthetic": False,
            "gap": "No live supplier evidence was available for this component.",
        }
    # Live class requires an explicit live source label AND exact identity match.
    if exact and source_label.casefold().startswith("live"):
        return {
            "evidence_class": EVIDENCE_LIVE,
            "requested_mpn": requested,
            "identity_verified": True,
            "source": exact.get("source") or "",
            "source_url": exact.get("product_detail_url") or "",
            "datasheet_url": exact.get("datasheet_url") or "",
            "retrieved_at": exact.get("retrieved_at") or utc_now(),
            "units": {
                "quantity": row.get("Quantity") or row.get("quantity"),
                "unit_price": row.get("Unit Price") or row.get("unit_price"),
                "currency": row.get("unit_price_currency") or row.get("currency") or "",
            },
            "synthetic": False,
        }
    if requested:
        return {
            "evidence_class": EVIDENCE_SYNTHETIC if (source_label or row) else EVIDENCE_MISSING,
            "requested_mpn": requested,
            "identity_verified": False,
            "source": source_label or EVIDENCE_SYNTHETIC,
            "source_url": "",
            "datasheet_url": "",
            "retrieved_at": row.get("retrieved_at") or "",
            "units": {
                "quantity": row.get("Quantity") or row.get("quantity"),
                "unit_price": row.get("Unit Price") or row.get("unit_price"),
                "currency": row.get("unit_price_currency") or row.get("currency") or "",
            },
            "synthetic": True,
            "gap": (
                "Not live authorized-supplier evidence. Treat values as "
                "synthetic-preview until provider credentials are configured "
                "on the migration API."
            ),
        }
    return {
        "evidence_class": EVIDENCE_MISSING,
        "requested_mpn": "",
        "identity_verified": False,
        "synthetic": True,
        "gap": "No part identity available for evidence classification.",
    }


def annotate_report_parts(report: dict[str, Any] | None) -> dict[str, Any]:
    """Attach evidence envelopes to each part without mutating live claims."""
    payload = dict(report or {})
    parts = []
    for part in payload.get("parts") or []:
        row = dict(part) if isinstance(part, dict) else {"value": part}
        row["evidence"] = classify_part_evidence(row)
        parts.append(row)
    payload["parts"] = parts
    payload["evidence_summary"] = {
        "live_count": sum(
            1 for p in parts if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_LIVE
        ),
        "synthetic_count": sum(
            1
            for p in parts
            if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_SYNTHETIC
        ),
        "missing_count": sum(
            1
            for p in parts
            if (p.get("evidence") or {}).get("evidence_class") == EVIDENCE_MISSING
        ),
        "live_lookups_enabled": any(
            (part.get("evidence") or {}).get("evidence_class") == EVIDENCE_LIVE
            for part in parts
        ),
    }
    return payload
