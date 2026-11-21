"""Cadivor Milestone 19.0 — Portfolio Intelligence.

Turns saved BOM and component records into cross-project engineering,
lifecycle, and supplier intelligence. Part photos are shown when saved records
contain a trusted distributor image URL.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import html
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system import MetricCard, cadivor_engineering_dataframe, render_kpi_row_safe
from src.part_images import normalize_supplier_image_url, part_image_markup


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _first(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def _open_all_saved_boms_from_portfolio() -> None:
    """Set the BOM list route in the click callback before page rendering."""
    from src.ui.navigation import return_to_saved_bom_list

    return_to_saved_bom_list(_rerun=False, arm_opening=True)


def _optional_number(value: Any) -> float | None:
    if value is None or str(value).strip().casefold() in {"", "nan", "none", "<na>"}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if pd.notna(number) else None


def _risk_bucket(score: float | None, raw_level: Any) -> str:
    level = _text(raw_level).casefold()
    if score is not None and score >= 60:
        return "High"
    if score is not None and score >= 30:
        return "Medium"
    if level in {"high", "critical", "severe"}:
        return "High"
    if level in {"medium", "moderate", "watch"}:
        return "Medium"
    if level in {"low", "minimal"} or (score is not None and score > 0):
        return "Low"
    return "Unknown"


def _shared_component_evidence_labels(row: Dict[str, Any]) -> tuple[str, str, str]:
    """Render absent portfolio evidence as unknown, never as a number."""
    risk_score = _optional_number(row.get("Highest Risk Score"))
    stock = _optional_number(row.get("Lowest Stock"))
    sources = _optional_number(row.get("Minimum Supplier Sources"))
    risk_label = (
        f"Risk {int(risk_score)}/100" if risk_score is not None else "Risk not assessed"
    )
    stock_label = (
        f"Lowest stock {int(stock):,}" if stock is not None else "Stock not recorded"
    )
    source_label = (
        f"{int(sources)} source(s)"
        if sources is not None
        else "Supplier sources not recorded"
    )
    return risk_label, stock_label, source_label


def _recorded_date(row: Dict[str, Any]) -> datetime | None:
    raw = _first(row, "updated_at", "created_at", "analyzed_at", "date", default=None)
    if raw is None:
        return None
    try:
        parsed = pd.to_datetime(raw, errors="coerce", utc=True)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def filter_portfolio_window(
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    alerts: Iterable[Dict[str, Any]],
    window: str,
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str]:
    """Filter live records using analysis timestamps and explain missing dates."""
    analysis_rows = [row for row in (analyses or []) if isinstance(row, dict)]
    part_rows = [row for row in (parts or []) if isinstance(row, dict)]
    alert_rows = [row for row in (alerts or []) if isinstance(row, dict)]
    normalized_window = _text(window, "All time")
    days = {
        "Last 30 days": 30,
        "Last 90 days": 90,
        "Last 12 months": 365,
    }.get(normalized_window)
    if days is None:
        return (
            analysis_rows,
            part_rows,
            alert_rows,
            "All saved records are included. The trend uses analyses with a recorded date.",
        )

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(days=days)
    selected_ids = set()
    dated_count = 0
    undated_count = 0
    filtered_analyses = []
    for row in analysis_rows:
        updated = _recorded_date(row)
        if updated is None:
            undated_count += 1
            continue
        dated_count += 1
        if cutoff <= updated <= current:
            filtered_analyses.append(row)
            selected_ids.add(_text(row.get("id")))
    filtered_parts = [
        row for row in part_rows
        if _text(row.get("analysis_id")) in selected_ids
    ]
    filtered_alerts = []
    for row in alert_rows:
        created = _recorded_date(row)
        if created is not None and cutoff <= created <= current:
            filtered_alerts.append(row)
    note = f"Showing records from the last {days} days."
    if undated_count:
        note += f" {undated_count:,} undated BOM(s) are excluded from this time range."
    if not dated_count:
        note = "No dated BOM analyses are available for the selected time range."
    return filtered_analyses, filtered_parts, filtered_alerts, note


def filter_previous_portfolio_window(
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    alerts: Iterable[Dict[str, Any]],
    window: str,
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str]:
    """Return the immediately preceding window for evidence-backed KPI deltas."""
    analysis_rows = [row for row in (analyses or []) if isinstance(row, dict)]
    part_rows = [row for row in (parts or []) if isinstance(row, dict)]
    alert_rows = [row for row in (alerts or []) if isinstance(row, dict)]
    days = {
        "Last 30 days": 30,
        "Last 90 days": 90,
        "Last 12 months": 365,
    }.get(_text(window, "All time"))
    if days is None:
        return [], [], [], "No previous-period comparison is available for the all-time view."

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current_cutoff = current - timedelta(days=days)
    previous_cutoff = current - timedelta(days=days * 2)
    selected = []
    selected_ids = set()
    for row in analysis_rows:
        timestamp = _recorded_date(row)
        if timestamp is not None and previous_cutoff <= timestamp < current_cutoff:
            selected.append(row)
            selected_ids.add(_text(row.get("id")))
    selected_parts = [row for row in part_rows if _text(row.get("analysis_id")) in selected_ids]
    selected_alerts = [
        row for row in alert_rows
        if (timestamp := _recorded_date(row)) is not None
        and previous_cutoff <= timestamp < current_cutoff
    ]
    note = (
        f"Prior window: {previous_cutoff.date().isoformat()} to "
        f"{(current_cutoff - timedelta(seconds=1)).date().isoformat()}."
    )
    return selected, selected_parts, selected_alerts, note


def high_risk_components_disclosure(
    risk_count: int,
    risk_records: Iterable[Dict[str, Any]],
) -> str:
    """Build an accessible table-cell disclosure for one saved BOM's risky parts."""
    count = max(0, int(_number(risk_count, 0)))
    if count == 0:
        return (
            "<span class='cv-ap-risk-zero' aria-label='No at-risk components'>0</span>"
        )

    items = []
    for row in risk_records or []:
        mpn = html.escape(_text(row.get("Part Number"), "Component"))
        maker = _text(row.get("Manufacturer"))
        level = html.escape(_text(row.get("Risk Level"), "High"))
        quantity = int(_number(row.get("Quantity"), 0))
        evidence = []
        if maker != "Unknown":
            evidence.append(html.escape(maker))
        evidence.append(level)
        if quantity > 0:
            evidence.append(f"Qty {quantity:,}")
        items.append(
            f"<li><strong>{mpn}</strong> <span>{html.escape(' · '.join(evidence))}</span></li>"
        )

    if items:
        detail_markup = f"<ul>{''.join(items)}</ul>"
    else:
        detail_markup = (
            f"<p class='cv-ap-risk-missing'>The saved summary reports {count} at-risk "
            "component(s), but matching part-level records are unavailable.</p>"
        )
    return (
        "<details class='cv-ap-risk-disclosure'>"
        f"<summary><span>{count}</span><span>View components</span></summary>"
        f"{detail_markup}</details>"
    )


def build_portfolio_intelligence(
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    alerts: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    analyses = list(analyses or [])
    parts = list(parts or [])
    alerts = list(alerts or [])

    analysis_names = {
        _text(row.get("id")): _text(
            row.get("project_name") or row.get("name") or row.get("filename"),
            "Saved BOM",
        )
        for row in analyses
    }
    analysis_boms = {
        _text(row.get("id")): _text(
            row.get("filename") or row.get("file_name"),
            "Saved BOM",
        )
        for row in analyses
    }

    project_health = []
    for row in analyses:
        health_value = _optional_number(row.get("health_score"))
        # Preserve Not scored / Unknown — never coerce unscored health to 0.
        if health_value is None:
            health_display: int | str = "Not scored"
            health_sort = float("inf")
        else:
            health_display = int(health_value)
            health_sort = float(health_value)
        project_health.append(
            {
                "Analysis ID": _text(row.get("id")),
                "Project": _text(
                    row.get("project_name") or row.get("name") or row.get("filename"),
                    "Saved BOM",
                ),
                "Health": health_display,
                "High-Risk": int(_number(row.get("high_risk_count") or row.get("high_risk_parts"), 0)),
                "Components": int(_number(row.get("total_parts") or row.get("part_count") or row.get("parts_count"), 0)),
                "BOM": _text(row.get("filename") or row.get("file_name"), "Saved BOM"),
                "Updated": _text(row.get("updated_at") or row.get("created_at"), "Not recorded"),
                "_health_sort": health_sort,
            }
        )
    project_health.sort(key=lambda row: (row["_health_sort"], -row["High-Risk"]))
    for row in project_health:
        row.pop("_health_sort", None)

    normalized = []
    for row in parts:
        mpn = _text(_first(row, "mpn", "MPN", "part_number"), "Unknown")
        analysis_id = _text(row.get("analysis_id"))
        lifecycle = _text(row.get("lifecycle_status"), "Unknown")
        supplier_raw = _first(row, "supplier_count", default=None)
        supplier_value = _optional_number(supplier_raw)
        supplier_recorded = supplier_value is not None
        supplier_count = int(supplier_value) if supplier_value is not None else None
        raw_stock = _first(row, "stock_available", "stock", default=None)
        stock_value = _optional_number(raw_stock)
        stock_recorded = stock_value is not None
        stock = int(stock_value) if stock_value is not None else None
        raw_score = _first(row, "risk_score", "Risk Score", default=None)
        risk_score_value = _optional_number(raw_score)
        risk_score = int(risk_score_value) if risk_score_value is not None else None
        raw_risk_level = _first(row, "risk_level", "Risk Level", default=None)
        risk_level = _risk_bucket(risk_score_value, raw_risk_level)
        manufacturer = _text(row.get("manufacturer"), "Unknown")
        normalized.append(
            {
                "Analysis ID": analysis_id,
                "Project": analysis_names.get(analysis_id, _text(row.get("project_name"), "Saved BOM")),
                "BOM": analysis_boms.get(
                    analysis_id,
                    _text(_first(row, "filename", "file_name"), "Saved BOM"),
                ),
                "Part Number": mpn,
                "Description": _text(_first(row, "description", "part_description"), ""),
                "Category": _text(_first(row, "category", "category_raw", "device_type"), ""),
                "Image URL": normalize_supplier_image_url(
                    _first(row, "image_url", "Image URL", "photo_url")
                ),
                "Manufacturer": manufacturer,
                "Lifecycle": lifecycle,
                "Supplier Sources": supplier_count,
                "Supplier Sources Recorded": supplier_recorded,
                "Available Stock": stock,
                "Stock Recorded": stock_recorded,
                "Risk Score": risk_score,
                "Risk Score Recorded": risk_score_value is not None,
                "Risk Level": risk_level,
                "Quantity": int(_number(_first(row, "quantity", "qty", "required_quantity"), 1)),
            }
        )

    mpn_projects: Dict[str, set] = defaultdict(set)
    mpn_analyses: Dict[str, set] = defaultdict(set)
    mpn_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    manufacturer_counts = Counter()
    for row in normalized:
        key = row["Part Number"].upper()
        if key.strip() in {"", "UNKNOWN", "N/A", "NAN"}:
            continue
        mpn_projects[key].add(row["Project"])
        if row["Analysis ID"]:
            mpn_analyses[key].add(row["Analysis ID"])
        mpn_rows[key].append(row)
        manufacturer_counts[row["Manufacturer"]] += 1

    shared_components = []
    for key, analyses_using_part in mpn_analyses.items():
        rows = mpn_rows[key]
        if len(analyses_using_part) < 2:
            continue
        projects = mpn_projects[key]
        scored_rows = [row for row in rows if row["Risk Score"] is not None]
        stock_rows = [row for row in rows if row["Stock Recorded"]]
        source_rows = [row for row in rows if row["Supplier Sources Recorded"]]
        worst = max(scored_rows or rows, key=lambda row: row["Risk Score"] or 0)
        shared_components.append(
            {
                "Part Number": worst["Part Number"],
                "Manufacturer": worst["Manufacturer"],
                "BOMs Using Part": len(analyses_using_part),
                "Projects Using Part": len(projects),
                "Highest Risk Score": max(
                    (row["Risk Score"] for row in scored_rows), default=None
                ),
                "Lowest Stock": min(
                    (row["Available Stock"] for row in stock_rows), default=None
                ),
                "Minimum Supplier Sources": min(
                    (row["Supplier Sources"] for row in source_rows), default=None
                ),
                "Lifecycle": worst["Lifecycle"],
                "Image URL": worst["Image URL"],
            }
        )
    # Unknown risk scores are valid portfolio data. Keep them after scored
    # components instead of negating None, which used to crash the page when
    # any shared part had not yet been assessed.
    shared_components.sort(
        key=lambda row: (
            -row["Projects Using Part"],
            row["Highest Risk Score"] is None,
            -(row["Highest Risk Score"] or 0),
        )
    )

    single_source = [
        row for row in normalized
        if row["Supplier Sources Recorded"] and row["Supplier Sources"] <= 1
    ]
    no_stock = [
        row for row in normalized
        if row["Stock Recorded"] and (row["Available Stock"] or 0) <= 0
    ]
    lifecycle_exposed = [
        row for row in normalized
        if any(
            term in row["Lifecycle"].lower()
            for term in ("obsolete", "replacement", "nrnd", "not recommended", "eol")
  