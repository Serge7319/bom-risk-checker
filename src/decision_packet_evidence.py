"""Identity-safe helpers for live evidence shown in decision review packets."""
from __future__ import annotations

from typing import Any

from src.normalizer import normalize_part_number


def exact_supplier_evidence(requested_mpn: object, record: object) -> dict[str, Any] | None:
    """Return a small public-evidence snapshot only for an exact MPN result.

    Supplier search can return family or neighboring catalog results. A review
    packet must never borrow their lifecycle or document links for the alert's
    component, so require an exact normalized manufacturer part number.
    """
    if not isinstance(record, dict):
        return None

    requested = normalize_part_number(str(requested_mpn or "").strip())
    returned = normalize_part_number(
        str(record.get("manufacturer_part_number") or "").strip()
    )
    if not requested or not returned or requested != returned:
        return None

    def _safe_url(*values: object) -> str:
        for value in values:
            candidate = str(value or "").strip()
            if candidate.startswith(("https://", "http://")):
                return candidate
        return ""

    return {
        "identity_verified": True,
        "manufacturer_part_number": str(
            record.get("manufacturer_part_number") or ""
        ).strip(),
        "manufacturer": str(record.get("manufacturer") or "").strip(),
        "source": str(record.get("source") or "Supplier listing").strip(),
        "lifecycle_status": str(record.get("lifecycle_status") or "").strip(),
        "product_detail_url": _safe_url(
            record.get("product_detail_url"),
            record.get("product_url"),
            record.get("source_url"),
            record.get("supplier_url"),
        ),
        "datasheet_url": _safe_url(
            record.get("datasheet_url"),
            record.get("datasheet"),
            record.get("datasheet_link"),
        ),
        "retrieved_at": str(record.get("retrieved_at") or "").strip(),
    }
