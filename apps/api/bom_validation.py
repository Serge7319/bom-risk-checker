"""BOM upload validation preview.

Runs the same intake parser as ``/boms/analyze`` (``src.bom_intake``) so the
preview and the analysis can never disagree. It reads, maps, and normalizes the
file and reports every issue, but never runs risk scoring or persists anything.
"""

from __future__ import annotations

from typing import Any

from src.bom_intake import parse_intake

# Matches the UI copy: "CSV or XLSX · up to 10 MB"
MAX_BOM_UPLOAD_BYTES = 10 * 1024 * 1024


def validation_preview(
    filename: str,
    payload: bytes,
    *,
    column_mapping: dict[str, str] | None = None,
    supplier_specific: bool = False,
    default_supplier: str = "",
    exclude_invalid_rows: bool = False,
    row_corrections: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Return column mapping, normalized rows, counts, and actionable issues.

    ``row_count`` is the source BOM data row count before aggregation.
    """
    if len(payload) > MAX_BOM_UPLOAD_BYTES:
        return {
            "ok": False,
            "can_analyze": False,
            "filename": filename,
            "detected_columns": [],
            "required_columns": ["mpn", "quantity"],
            "missing_required": ["mpn", "quantity"],
            "row_count": 0,
            "unique_part_count": 0,
            "parsed_row_count": 0,
            "errors": ["BOM file must be 10 MB or smaller."],
            "warnings": [],
            "code": "payload_too_large",
        }
    result = parse_intake(
        filename,
        payload,
        column_mapping=column_mapping,
        supplier_specific=supplier_specific,
        default_supplier=default_supplier,
        exclude_invalid_rows=exclude_invalid_rows,
        row_corrections=row_corrections,
    )
    return result.preview()
