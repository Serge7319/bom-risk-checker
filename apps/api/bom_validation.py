"""BOM upload validation preview — reuses existing parse/validate, no analysis."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from apps.api.synthetic_analyze import parse_bom_bytes
from src.bom_parser import REQUIRED_COLUMNS
from src.normalizer import normalize_column_name

# Matches the UI copy: "CSV or XLSX · up to 10 MB"
MAX_BOM_UPLOAD_BYTES = 10 * 1024 * 1024


def _read_raw_frame(filename: str, payload: bytes) -> pd.DataFrame:
    buffer = io.BytesIO(payload)
    buffer.name = filename or "bom.csv"
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(buffer)
    return pd.read_csv(buffer)


def validation_preview(filename: str, payload: bytes) -> dict[str, Any]:
    """Return column detection, counts, and actionable errors/warnings.

    Uses ``synthetic_analyze.parse_bom_bytes`` — the same parse path as
    ``/boms/analyze``. Does not run risk scoring or persist reports.
    ``row_count`` is the source BOM data row count before aggregation.
    """
    if not payload:
        return {
            "ok": False,
            "can_analyze": False,
            "filename": filename,
            "detected_columns": [],
            "required_columns": list(REQUIRED_COLUMNS),
            "missing_required": list(REQUIRED_COLUMNS),
            "row_count": 0,
            "unique_part_count": 0,
            "parsed_row_count": 0,
            "errors": ["Empty file"],
            "warnings": [],
        }

    if len(payload) > MAX_BOM_UPLOAD_BYTES:
        return {
            "ok": False,
            "can_analyze": False,
            "filename": filename,
            "detected_columns": [],
            "required_columns": list(REQUIRED_COLUMNS),
            "missing_required": list(REQUIRED_COLUMNS),
            "row_count": 0,
            "unique_part_count": 0,
            "parsed_row_count": 0,
            "errors": ["BOM file must be 10 MB or smaller."],
            "warnings": [],
            "code": "payload_too_large",
        }

    errors: list[str] = []
    warnings: list[str] = []
    detected_columns: list[dict[str, str]] = []
    try:
        raw = _read_raw_frame(filename, payload)
        for source in raw.columns:
            source_label = str(source)
            detected_columns.append(
                {
                    "source": source_label,
                    "normalized": normalize_column_name(source_label),
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "can_analyze": False,
            "filename": filename,
            "detected_columns": [],
            "required_columns": list(REQUIRED_COLUMNS),
            "missing_required": list(REQUIRED_COLUMNS),
            "row_count": 0,
            "unique_part_count": 0,
            "parsed_row_count": 0,
            "errors": [f"Could not read the BOM file: {exc}"],
            "warnings": [],
        }

    source_row_count = int(len(raw.index))
    normalized_names = {item["normalized"] for item in detected_columns}
    missing_required = [col for col in REQUIRED_COLUMNS if col not in normalized_names]

    try:
        parsed = parse_bom_bytes(filename, payload)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        return {
            "ok": False,
            "can_analyze": False,
            "filename": filename,
            "detected_columns": detected_columns,
            "required_columns": list(REQUIRED_COLUMNS),
            "missing_required": missing_required or list(REQUIRED_COLUMNS),
            "row_count": source_row_count,
            "unique_part_count": 0,
            "parsed_row_count": 0,
            "errors": errors,
            "warnings": warnings,
            "has_hierarchy_columns": "parent_mpn" in normalized_names,
        }

    part_series = parsed.get("mpn_normalized", parsed.get("mpn"))
    unique_parts = {
        str(value).strip().casefold()
        for value in part_series
        if str(value).strip()
    }
    if not unique_parts:
        errors.append("No manufacturer part numbers were found after cleaning.")
    if "quantity" not in parsed.columns:
        warnings.append(
            "No quantity column was detected. Analysis will treat missing quantities carefully."
        )
    if "manufacturer" not in parsed.columns:
        warnings.append(
            "No manufacturer column was detected. Supplier matching may be less specific."
        )
    has_hierarchy = "parent_mpn" in parsed.columns and parsed["parent_mpn"].fillna("").astype(
        str
    ).str.strip().ne("").any()
    if "parent_mpn" in normalized_names and not has_hierarchy:
        warnings.append(
            "A Parent MPN column is present but empty. Assembly roll-up will stay flat."
        )

    can_analyze = not errors and len(unique_parts) > 0
    return {
        "ok": can_analyze,
        "can_analyze": can_analyze,
        "filename": filename,
        "detected_columns": detected_columns,
        "required_columns": list(REQUIRED_COLUMNS),
        "missing_required": missing_required,
        "row_count": source_row_count,
        "unique_part_count": len(unique_parts),
        "parsed_row_count": int(len(parsed.index)),
        "errors": errors,
        "warnings": warnings,
        "has_hierarchy_columns": bool(has_hierarchy),
    }
