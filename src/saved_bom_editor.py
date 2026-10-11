"""Small helpers for rebuilding an editable BOM from saved analysis rows."""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from typing import Any


def normalize_saved_bom_rows(records: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Validate MPN and positive integer quantities from the BOM editor."""
    normalized: list[dict[str, Any]] = []
    for record in records:
        mpn = str(record.get("MPN") or record.get("mpn") or "").strip()
        raw_quantity = record.get("Quantity", record.get("quantity", 1))
        try:
            value = float(raw_quantity)
            quantity = int(value)
        except (TypeError, ValueError, OverflowError):
            return [], "Every row needs a part number and a positive whole-number quantity."
        if not mpn or quantity <= 0 or value != quantity:
            return [], "Every row needs a part number and a positive whole-number quantity."
        normalized.append({"mpn": mpn, "quantity": quantity})
    if not normalized:
        return [], "Add at least one component before rerunning this analysis."
    return normalized, ""


def saved_bom_csv_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    """Serialize validated MPN/quantity rows using the standard upload format."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=("mpn", "quantity"), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({"mpn": row["mpn"], "quantity": row["quantity"]})
    return buffer.getvalue().encode("utf-8")
