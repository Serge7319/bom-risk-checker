"""BOM upload validation preview — reuses existing parse/validate, no analysis."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from src.bom_parser import (
    REQUIRED_COLUMNS,
    aggregate_bom_rows,
    clean_bom_data,
    normalize_bom_columns,
    validate_bom,
)
from src.normalizer import normalize_column_name


def _read_raw_frame(filename: str, payload: bytes) -> pd.DataFrame:
    buffer = io.BytesIO(payload)
    buffer.name = filename or "bom.csv"
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(buffer)
    return pd.read_csv(buffer)


def _parse_bom_bytes(filename: str, payload: bytes) -> pd.DataFrame:
    """Same parse path as apps.api.synthetic_analyze.parse_bom_bytes."""
    df = _read_raw_frame(filename, payload)
    df = normalize_bom_columns(df)
    df = validate_bom(df)
    hierarchical = (
        "parent_mpn" in df.columns
        and df["parent_mpn"].fillna("").astype(str).str.strip().ne("").any()
    )
    if hierarchical:
        if "parent_mpn" not in df.columns:
            df["parent_mpn"] = ""
        df["parent_mpn"] = df["parent_mpn"].fillna("").astype(str)
        groups = []
        for (_mpn, _parent), group in df.groupby(["mpn", "parent_mpn"], sort=False, dropna=False):
            first = group.iloc[0].to_dict()
            if "quantity" in group.columns:
                quantity_values = pd.to_numeric(group["quantity"], errors="coerce")
                first["quantity"] = quantity_values.fillna(0).sum()
            groups.append(first)
        df = pd.DataFrame(groups)
    else:
        df = aggregate_bom_rows(df)
    return clean_bom_data(df)


def validation_preview(filename: str, payload: bytes) -> dict[str, Any]:
    """Return column detection, counts, and actionable errors/warnings.

    Uses the same parse path as ``/boms/analyze``. Does not run the risk
    analysis engine.
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
            "errors": ["Empty file"],
            "warnings": [],
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
            "errors": [f"Could not read the BOM file: {exc}"],
            "warnings": [],
        }

    normalized_names = {item["normalized"] for item in detected_columns}
    missing_required = [col for col in REQUIRED_COLUMNS if col not in normalized_names]

    try:
        parsed = _parse_bom_bytes(filename, payload)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        return {
            "ok": False,
            "can_analyze": False,
            "filename": filename,
            "detected_columns": detected_columns,
            "required_columns": list(REQUIRED_COLUMNS),
            "missing_required": missing_required or list(REQUIRED_COLUMNS),
            "row_count": int(len(raw.index)),
            "unique_part_count": 0,
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
        "row_count": int(len(parsed.index)),
        "unique_part_count": len(unique_parts),
        "errors": errors,
        "warnings": warnings,
        "has_hierarchy_columns": bool(has_hierarchy),
    }
