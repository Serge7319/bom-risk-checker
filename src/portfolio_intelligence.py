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
        project_health.append(
            {
                "Analysis ID": _text(row.get("id")),
                "Project": _text(
                    row.get("project_name") or row.get("name") or row.get("filename"),
                    "Saved BOM",
                ),
                "Health": int(_number(row.get("health_score"), 0)),
                "High-Risk": int(_number(row.get("high_risk_count") or row.get("high_risk_parts"), 0)),
                "Components": int(_number(row.get("total_parts") or row.get("part_count") or row.get("parts_count"), 0)),
                "BOM": _text(row.get("filename") or row.get("file_name"), "Saved BOM"),
                "Updated": _text(row.get("updated_at") or row.get("created_at"), "Not recorded"),
            }
        )
    project_health.sort(key=lambda row: (row["Health"], -row["High-Risk"]))

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
    mpn_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    manufacturer_counts = Counter()
    for row in normalized:
        key = row["Part Number"].upper()
        if key.strip() in {"", "UNKNOWN", "N/A", "NAN"}:
            continue
        mpn_projects[key].add(row["Project"])
        mpn_rows[key].append(row)
        manufacturer_counts[row["Manufacturer"]] += 1

    shared_components = []
    for key, projects in mpn_projects.items():
        rows = mpn_rows[key]
        if len(projects) < 2:
            continue
        scored_rows = [row for row in rows if row["Risk Score"] is not None]
        stock_rows = [row for row in rows if row["Stock Recorded"]]
        source_rows = [row for row in rows if row["Supplier Sources Recorded"]]
        worst = max(scored_rows or rows, key=lambda row: row["Risk Score"] or 0)
        shared_components.append(
            {
                "Part Number": worst["Part Number"],
                "Manufacturer": worst["Manufacturer"],
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
    shared_components.sort(
        key=lambda row: (-row["Projects Using Part"], -row["Highest Risk Score"])
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
        )
    ]
    high_risk = [
        row for row in normalized
        if row["Risk Level"] == "High"
    ]
    medium_risk = [row for row in normalized if row["Risk Level"] == "Medium"]
    low_risk = [row for row in normalized if row["Risk Level"] == "Low"]
    unassessed = [row for row in normalized if row["Risk Level"] == "Unknown"]

    total_parts = len(normalized)
    concentration = 0
    top_manufacturer = "No data"
    known_manufacturer_counts = Counter(
        row["Manufacturer"] for row in normalized
        if row["Manufacturer"].casefold() not in {"unknown", "not recorded", ""}
    )
    if known_manufacturer_counts:
        top_manufacturer, top_count = known_manufacturer_counts.most_common(1)[0]
        concentration = round((top_count / max(1, sum(known_manufacturer_counts.values()))) * 100)

    alert_counts = Counter(
        _text(row.get("part_number") or row.get("mpn"), "Unknown")
        for row in alerts
    )
    recurring_alerts = [
        {"Part Number": mpn, "Recorded Alerts": count}
        for mpn, count in alert_counts.most_common()
        if mpn != "Unknown" and count > 1
    ]

    opportunity_score = 0
    if total_parts:
        exposure_keys = {
            (row["Analysis ID"], row["Part Number"])
            for group in (single_source, no_stock, lifecycle_exposed, high_risk, medium_risk)
            for row in group
        }
        exposure = len(exposure_keys)
        opportunity_score = min(100, round((exposure / total_parts) * 100))

    recommendations = []
    if shared_components:
        top = shared_components[0]
        recommendations.append(
            f"Prioritize {top['Part Number']}: it is used in {top['Projects Using Part']} projects, "
            "so one approved replacement can reduce risk across the portfolio."
        )
    if single_source:
        recommendations.append(
            f"Add sourcing coverage for {len(single_source)} component record(s) with one or fewer approved sources."
        )
    if lifecycle_exposed:
        recommendations.append(
            f"Create replacement plans for {len(lifecycle_exposed)} lifecycle-exposed component record(s)."
        )
    if concentration >= 30:
        recommendations.append(
            f"Review manufacturer concentration: {top_manufacturer} represents approximately {concentration}% of recorded component usage."
        )
    if not recommendations:
        recommendations.append(
            "The portfolio has no major cross-project concentration or lifecycle exception recorded."
        )

    high_risk_by_analysis: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in high_risk:
        analysis_id = row["Analysis ID"]
        if analysis_id:
            high_risk_by_analysis[analysis_id].append(row)

    parts_by_analysis: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        if row["Analysis ID"]:
            parts_by_analysis[row["Analysis ID"]].append(row)

    at_risk_boms = []
    monthly_counts: Dict[str, Counter] = defaultdict(Counter)
    for analysis in analyses:
        analysis_id = _text(analysis.get("id"))
        detail_rows = parts_by_analysis.get(analysis_id, [])
        summary_high_raw = _first(analysis, "high_risk_count", "high_risk_parts", default=None)
        summary_medium_raw = _first(analysis, "medium_risk_count", "medium_risk_parts", default=None)
        summary_low_raw = _first(analysis, "low_risk_count", "low_risk_parts", default=None)
        summary_high = max(0, int(_number(summary_high_raw, 0)))
        summary_medium = max(0, int(_number(summary_medium_raw, 0)))
        summary_low = max(0, int(_number(summary_low_raw, 0)))
        high_rows = [row for row in detail_rows if row["Risk Level"] == "High"]
        medium_rows = [row for row in detail_rows if row["Risk Level"] == "Medium"]
        low_rows = [row for row in detail_rows if row["Risk Level"] == "Low"]
        risky_rows = [
            row for row in detail_rows
            if row["Risk Level"] in {"High", "Medium"}
            or row in single_source
            or row in lifecycle_exposed
            or row in no_stock
        ]
        high_count = max(summary_high, len(high_rows))
        medium_count = max(summary_medium, len(medium_rows))
        low_count = max(summary_low, len(low_rows))
        recorded_risk_count = high_count + medium_count
        at_risk_count = max(recorded_risk_count, len(risky_rows))
        if at_risk_count:
            if high_count:
                overall_level = "High"
            elif medium_count or risky_rows:
                overall_level = "Medium"
            else:
                overall_level = "Unknown"
            driver_counts = []
            if high_count:
                driver_counts.append((high_count, "High risk"))
            if len([row for row in detail_rows if row in single_source]):
                driver_counts.append((len([row for row in detail_rows if row in single_source]), "Single-source"))
            if len([row for row in detail_rows if row in lifecycle_exposed]):
                driver_counts.append((len([row for row in detail_rows if row in lifecycle_exposed]), "End-of-life"))
            if len([row for row in detail_rows if row in no_stock]):
                driver_counts.append((len([row for row in detail_rows if row in no_stock]), "Out-of-stock"))
            if medium_count:
                driver_counts.append((medium_count, "Medium risk"))
            primary_driver = (
                f"{max(driver_counts)[1]} ({max(driver_counts)[0]})"
                if driver_counts else f"Risk flagged in BOM summary ({at_risk_count})"
            )
            analysis_name = analysis_names.get(analysis_id, _text(analysis.get("project_name"), "Saved BOM"))
            at_risk_boms.append({
                "Analysis ID": analysis_id,
                "Project": analysis_name,
                "BOM": analysis_boms.get(analysis_id, _text(_first(analysis, "filename", "file_name"), "Saved BOM")),
                "Total Components": int(_number(_first(analysis, "total_parts", "part_count", "parts_count"), len(detail_rows))),
                "At-Risk Components": at_risk_count,
                "Risk Level": overall_level,
                "Primary Risk Driver": primary_driver,
                "Last Updated": _text(_first(analysis, "updated_at", "created_at"), "Not recorded"),
                "Health": _optional_number(analysis.get("health_score")),
            })
        recorded_date = _recorded_date(analysis)
        if recorded_date:
            month_label = recorded_date.strftime("%Y-%m")
            monthly_counts[month_label]["High risk"] += max(summary_high, len(high_rows))
            monthly_counts[month_label]["Medium risk"] += max(summary_medium, len(medium_rows))
            monthly_counts[month_label]["Low risk"] += max(summary_low, len(low_rows))
    at_risk_boms.sort(
        key=lambda row: (
            -row["At-Risk Components"],
            0 if row["Risk Level"] == "High" else 1,
            row["Project"].casefold(),
        )
    )

    monthly_risk_trend = [
        {"Month": month, **{label: counts.get(label, 0) for label in ("High risk", "Medium risk", "Low risk")}}
        for month, counts in sorted(monthly_counts.items())
    ]
    distribution_counts = Counter()
    analyses_by_id = {_text(row.get("id")): row for row in analyses}
    for analysis_id, analysis in analyses_by_id.items():
        detail_rows = parts_by_analysis.get(analysis_id, [])
        actual = Counter(row["Risk Level"] for row in detail_rows)
        expected_total = max(
            len(detail_rows),
            max(
                0,
                int(
                    _number(
                        _first(analysis, "total_parts", "part_count", "parts_count"),
                        0,
                    )
                ),
            ),
        )
        summary_values = {
            "High": max(0, int(_number(_first(analysis, "high_risk_count", "high_risk_parts"), 0))),
            "Medium": max(0, int(_number(_first(analysis, "medium_risk_count", "medium_risk_parts"), 0))),
            "Low": max(0, int(_number(_first(analysis, "low_risk_count", "low_risk_parts"), 0))),
        }
        classified_counts = {
            level: max(actual.get(level, 0), summary_values[level])
            for level in ("High", "Medium", "Low")
        }
        for level, count in classified_counts.items():
            distribution_counts[level] += count
        # Preserve explicitly unknown detail rows and fill any remaining BOM
        # total as unassessed. This makes the chart reconcile even when only
        # summary-level risk counts were saved for an analysis.
        unassessed_count = max(
            actual.get("Unknown", 0),
            expected_total - sum(classified_counts.values()),
        )
        distribution_counts["Unknown"] += max(0, unassessed_count)
    for row in normalized:
        if not row["Analysis ID"]:
            distribution_counts[row["Risk Level"]] += 1
    risk_distribution = {
        "High risk": distribution_counts["High"],
        "Medium risk": distribution_counts["Medium"],
        "Low risk": distribution_counts["Low"],
        "Unassessed": distribution_counts["Unknown"],
    }

    component_detail_headers = [
        "Project", "BOM", "Part Number", "Manufacturer", "Risk Level",
        "Risk Score", "Lifecycle", "Quantity",
    ]
    portfolio_kpi_details = {
        "Saved Projects": {
            "description": "Saved BOM analyses and their current project-level health.",
            "headers": ["Project", "BOM", "Health", "High-Risk", "Components", "Updated"],
            "rows": [
                {
                    "Project": row["Project"],
                    "BOM": row["BOM"],
                    "Health": row["Health"],
                    "High-Risk": row["High-Risk"],
                    "Components": row["Components"],
                    "Updated": row["Updated"],
                }
                for row in project_health
            ],
        },
        "Component Records": {
            "description": "Recorded part entries across saved BOMs.",
            "headers": component_detail_headers,
            "rows": [
                {
                    "Project": row["Project"],
                    "BOM": row["BOM"],
                    "Part Number": row["Part Number"],
                    "Manufacturer": row["Manufacturer"],
                    "Risk Level": row["Risk Level"],
                    "Risk Score": row["Risk Score"],
                    "Lifecycle": row["Lifecycle"],
                    "Quantity": row["Quantity"],
                }
                for row in normalized
            ],
        },
        "Shared Components": {
            "description": "Parts recorded in more than one saved project.",
            "headers": [
                "Part Number", "Manufacturer", "Projects Using Part",
                "Highest Risk Score", "Lowest Stock", "Minimum Supplier Sources", "Lifecycle",
            ],
            "rows": shared_components,
        },
        "Single-Source Records": {
            "description": "Part records with a recorded supplier count of one or fewer.",
            "headers": [
                "Project", "BOM", "Part Number", "Manufacturer",
                "Supplier Sources", "Available Stock", "Risk Level", "Risk Score",
            ],
            "rows": [
                {
                    "Project": row["Project"],
                    "BOM": row["BOM"],
                    "Part Number": row["Part Number"],
                    "Manufacturer": row["Manufacturer"],
                    "Supplier Sources": row["Supplier Sources"],
                    "Available Stock": row["Available Stock"],
                    "Risk Level": row["Risk Level"],
                    "Risk Score": row["Risk Score"],
                }
                for row in single_source
            ],
        },
        "High-risk component records": {
            "description": "Component records marked high risk or scored 60/100 and above.",
            "headers": [
                "Project", "BOM", "Part Number", "Manufacturer",
                "Risk Level", "Risk Score", "Lifecycle", "Quantity",
            ],
            "rows": [
                {
                    "Project": row["Project"],
                    "BOM": row["BOM"],
                    "Part Number": row["Part Number"],
                    "Manufacturer": row["Manufacturer"],
                    "Risk Level": row["Risk Level"],
                    "Risk Score": row["Risk Score"],
                    "Lifecycle": row["Lifecycle"],
                    "Quantity": row["Quantity"],
                }
                for row in high_risk
            ],
        },
    }

    return {
        "project_health": project_health,
        "shared_components": shared_components,
        "single_source": single_source,
        "no_stock": no_stock,
        "lifecycle_exposed": lifecycle_exposed,
        "high_risk": high_risk,
        "recurring_alerts": recurring_alerts,
        "recommendations": recommendations[:4],
        "total_projects": len(analyses),
        "total_component_records": total_parts,
        "assessed_component_records": sum(
            risk_distribution[key] for key in ("High risk", "Medium risk", "Low risk")
        ),
        "unassessed_component_records": risk_distribution["Unassessed"],
        "shared_component_count": len(shared_components),
        "single_source_count": len(single_source),
        "supplier_data_recorded": any(row["Supplier Sources Recorded"] for row in normalized),
        "lifecycle_count": len(lifecycle_exposed),
        "manufacturer_concentration": concentration,
        "top_manufacturer": top_manufacturer,
        "portfolio_exposure": opportunity_score,
        "risk_distribution": risk_distribution,
        "at_risk_boms": at_risk_boms,
        "monthly_risk_trend": monthly_risk_trend,
        "kpi_details": portfolio_kpi_details,
        "high_risk_by_analysis": dict(high_risk_by_analysis),
    }


def _css() -> None:
    st.markdown(
        """
        <style id="cadivor-portfolio-intelligence-19" data-cadivor-layout-style="true">
          .cv19-hero{
            border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eef5ff);
            border-radius:24px;padding:25px;margin-bottom:18px;
            box-shadow:0 16px 42px rgba(37,99,235,.07)
          }
          .cv19-eyebrow{font-size:11px;font-weight:900;color:#2563eb;letter-spacing:.11em;text-transform:uppercase}
          .cv19-title{font-size:30px;font-weight:950;color:#0f172a;letter-spacing:-.045em;margin:7px 0}
          .cv19-copy{font-size:14px;font-weight:680;color:#52647a;line-height:1.58;max-width:1050px}
          .cv19-section{font-size:22px;font-weight:950;color:#0f172a;letter-spacing:-.03em;margin:22px 0 5px}
          .cv19-subtitle{font-size:13px;font-weight:650;color:#64748b;margin-bottom:12px}
          .cv19-card{
            border:1px solid #dbe3ef;background:#fff;border-radius:17px;padding:17px;
            margin-bottom:11px;box-shadow:0 8px 24px rgba(15,23,42,.04)
          }
          .cv19-card-title{font-size:16px;font-weight:950;color:#0f172a}
          .cv19-card-copy{font-size:13px;font-weight:680;color:#475569;line-height:1.52;margin-top:6px}
          .cv19-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}
          .cv19-meta span{
            font-size:10px;font-weight:850;color:#1d4ed8;background:#eff6ff;
            border:1px solid #dbeafe;border-radius:999px;padding:5px 8px
          }
          .cv19-recommendation{
            border-left:4px solid #2563eb;background:#f8fbff;border-radius:0 14px 14px 0;
            padding:14px 16px;margin-bottom:10px;font-size:13px;font-weight:740;
            color:#334155;line-height:1.5
          }
          .cv19-exposure{
            border:1px solid #fde68a;background:#fffbeb;border-radius:18px;padding:18px
          }
          .cv19-exposure strong{font-size:31px;color:#92400e;letter-spacing:-.04em}
          .cv19-exposure span{display:block;font-size:12px;font-weight:800;color:#a16207;margin-top:3px}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_portfolio_intelligence(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
) -> None:
    _css()
    photo_column = st.column_config.ImageColumn("Part photo", width="small")

    st.markdown(
        f"""
        <section class="cv19-hero">
          <div class="cv19-eyebrow">Across BOMs</div>
          <div class="cv19-title">Portfolio Intelligence</div>
          <div class="cv19-copy">
            Parts, suppliers, and lifecycle risks that show up on more than one saved BOM.
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    render_kpi_row_safe(
        [
            MetricCard(label="Saved Projects", value=str(intelligence["total_projects"]), tone="info", icon="folder-archive"),
            MetricCard(label="Component Records", value=str(intelligence["total_component_records"]), tone="info", icon="package"),
            MetricCard(label="Shared Components", value=str(intelligence["shared_component_count"]), tone="warning", icon="git-branch"),
            MetricCard(label="Single-Source Records", value=str(intelligence["single_source_count"]), tone="danger", icon="triangle-alert"),
            MetricCard(label="Lifecycle Exposure", value=str(intelligence["lifecycle_count"]), tone="warning", icon="clock-3"),
        ],
        columns=4,
    )

    left, right = st.columns([1.45, 1])

    with left:
        st.markdown('<div class="cv19-section">Cross-Project Priorities</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="cv19-subtitle">Components used across multiple saved BOMs create the largest portfolio-wide impact.</div>',
            unsafe_allow_html=True,
        )
        shared = intelligence["shared_components"][:5]
        if not shared:
            st.info("No component is currently recorded across multiple saved projects.")
        for index, row in enumerate(shared):
            photo = part_image_markup(row.get("Image URL"), row["Part Number"], size=64, part=row)
            st.markdown(
                f"""
                <section class="cv19-card cv-part-card-layout">
                  {photo}<div>
                  <div class="cv19-card-title">{html.escape(row['Part Number'])}</div>
                  <div class="cv19-card-copy">
                    Used in {row['Projects Using Part']} projects. One sourcing or replacement decision
                    may reduce exposure across multiple designs.
                  </div>
                  <div class="cv19-meta">
                    <span>Risk {row['Highest Risk Score']}/100</span>
                    <span>Lowest stock {row['Lowest Stock']:,}</span>
                    <span>{row['Minimum Supplier Sources']} source(s)</span>
                    <span>{html.escape(row['Lifecycle'])}</span>
                  </div></div>
                </section>
                """,
                unsafe_allow_html=True,
            )
            action_cols = st.columns(2)
            with action_cols[0]:
                internal_nav_button(
                    "Analyze Design Impact",
                    "Design Impact Analyzer",
                    key=f"portfolio_impact_{index}",
                    use_container_width=True,
                    part=row["Part Number"],
                )
            with action_cols[1]:
                internal_nav_button(
                    "Find Replacement",
                    "Alternative Finder",
                    key=f"portfolio_alt_{index}",
                    use_container_width=True,
                    original_part=row["Part Number"],
                    source_page="portfolio_intelligence",
                )

        with st.expander("View all shared components", expanded=False):
            if intelligence["shared_components"]:
                cadivor_engineering_dataframe(
                    pd.DataFrame(intelligence["shared_components"]),
                    column_config={"Image URL": photo_column},
                )

    with right:
        st.markdown('<div class="cv19-section">Portfolio Exposure</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <section class="cv19-exposure">
              <strong>{intelligence['portfolio_exposure']}/100</strong>
              <span>Recorded portfolio exposure</span>
            </section>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="cv19-section">Supplier Concentration</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <section class="cv19-card">
              <div class="cv19-card-title">{html.escape(intelligence['top_manufacturer'])}</div>
              <div class="cv19-card-copy">
                Approximately {intelligence['manufacturer_concentration']}% of recorded component usage
                comes from this manufacturer.
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="cv19-section">Recommended Portfolio Actions</div>', unsafe_allow_html=True)
        for recommendation in intelligence["recommendations"]:
            st.markdown(
                f'<div class="cv19-recommendation">✓ {html.escape(recommendation)}</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="cv19-section">Project Health Comparison</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="cv19-subtitle">The least healthy saved projects appear first.</div>',
        unsafe_allow_html=True,
    )
    if intelligence["project_health"]:
        project_df = pd.DataFrame(intelligence["project_health"])
        cadivor_engineering_dataframe(
            project_df[["Project", "Health", "High-Risk", "Components"]],
            column_config={
                "Health": st.column_config.NumberColumn(format="%d"),
                "High-Risk": st.column_config.NumberColumn(format="%d"),
                "Components": st.column_config.NumberColumn(format="%d"),
            },
        )
    else:
        st.info("No saved project health records are available.")

    exposure_tab, lifecycle_tab, alerts_tab = st.tabs(
        ["Sourcing Exposure", "Lifecycle Exposure", "Recurring Alerts"]
    )
    with exposure_tab:
        rows = intelligence["single_source"]
        if rows:
            cadivor_engineering_dataframe(
                pd.DataFrame(rows)[
                    ["Project", "Part Number", "Image URL", "Manufacturer", "Supplier Sources", "Available Stock", "Risk Score"]
                ],
                column_config={"Image URL": photo_column},
            )
        else:
            st.success("No single-source component record is currently identified.")

    with lifecycle_tab:
        rows = intelligence["lifecycle_exposed"]
        if rows:
            cadivor_engineering_dataframe(
                pd.DataFrame(rows)[
                    ["Project", "Part Number", "Image URL", "Manufacturer", "Lifecycle", "Risk Score"]
                ],
                column_config={"Image URL": photo_column},
            )
        else:
            st.success("No lifecycle-exposed component record is currently identified.")

    with alerts_tab:
        rows = intelligence["recurring_alerts"]
        if rows:
            cadivor_engineering_dataframe(pd.DataFrame(rows))
        else:
            st.success("No component has multiple recorded monitoring alerts.")

    st.markdown('<div class="cv19-section">Continue Your Review</div>', unsafe_allow_html=True)
    shortcuts = st.columns(7)
    with shortcuts[0]:
        internal_nav_button("Engineering Overview", "Dashboard", key="portfolio_dashboard", use_container_width=True)
    with shortcuts[1]:
        internal_nav_button("Design Impact", "Design Impact Analyzer", key="portfolio_design_impact", use_container_width=True)
    with shortcuts[2]:
        internal_nav_button("Cost Optimization", "Cost Optimization", key="portfolio_cost", use_container_width=True)
    with shortcuts[3]:
        internal_nav_button("Supply Scenario", "Supply Risk Scenario", key="portfolio_scenario", use_container_width=True)
    with shortcuts[4]:
        internal_nav_button("Engineering Decisions", "Engineering Decisions", key="portfolio_decisions", use_container_width=True)
    with shortcuts[5]:
        internal_nav_button("Procurement Advisor", "Procurement Advisor", key="portfolio_procurement", use_container_width=True)
    with shortcuts[6]:
        internal_nav_button("Reports", "Reports", key="portfolio_reports", use_container_width=True)


def render_portfolio_intelligence_dashboard(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
) -> None:
    """Render a live portfolio dashboard without synthetic trend deltas."""
    st.markdown(
        """
        <style id="cadivor-portfolio-mockup-v1" data-cadivor-layout-style="true">
          .st-key-approved_page_canvas_standard_portfolio_intelligence{
            box-sizing:border-box!important;width:100%!important;max-width:1440px!important;
            margin:0 auto!important;padding:28px 0 36px!important
          }
          .cv-pi-head{display:flex;align-items:flex-end;justify-content:space-between;gap:22px;margin:0 0 18px}
          .cv-pi-kicker{margin:0 0 5px;color:#64748b;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
          .cv-pi-title{margin:0 0 5px;color:#0f172a;font-size:32px;font-weight:820;line-height:1.12;letter-spacing:-.035em}
          .cv-pi-subtitle{margin:0;color:#64748b;font-size:14px;line-height:1.5}
          .cv-pi-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:0 0 16px}
          .cv-pi-kpi{box-sizing:border-box;min-width:0;min-height:140px;padding:17px 17px 14px;border:1px solid #dce7f5;border-radius:15px;background:#f7faff}
          .cv-pi-kpi-icon{display:block;margin:0 0 12px;color:#2670e8;font-size:21px;line-height:1}
          .cv-pi-kpi-label{color:#52647b;font-size:12px;font-weight:700;line-height:1.3}
          .cv-pi-kpi-value{margin-top:8px;color:#0f172a;font-size:27px;font-weight:850;line-height:1.05;letter-spacing:-.035em}
          .cv-pi-kpi-note{margin-top:8px;color:#74839a;font-size:11px;line-height:1.35}
          .cv-pi-kpi-delta{display:flex;align-items:center;gap:4px;margin-top:7px;font-size:10px;font-weight:750;line-height:1.3}
          .cv-pi-kpi-delta.positive{color:#16804a}.cv-pi-kpi-delta.negative{color:#d0444a}.cv-pi-kpi-delta.neutral{color:#8190a4}
          .cv-pi-chart-grid{display:grid;grid-template-columns:minmax(0,1.58fr) minmax(360px,.95fr);gap:14px;margin:0 0 15px}
          .cv-pi-panel{box-sizing:border-box;min-width:0;border:1px solid #dce5f0;border-radius:15px;background:#fff;padding:17px 18px;box-shadow:0 3px 10px rgba(15,23,42,.025)}
          .cv-pi-panel h2{margin:0;color:#17243d;font-size:17px;font-weight:780;letter-spacing:-.02em}
          .cv-pi-panel-sub{margin:4px 0 10px;color:#74839a;font-size:12px;line-height:1.45}
          .st-key-portfolio_risk_trend_panel,.st-key-portfolio_risk_distribution_panel{box-sizing:border-box!important;min-width:0!important;border:1px solid #dce5f0!important;border-radius:15px!important;background:#fff!important;padding:14px 16px!important;box-shadow:0 3px 10px rgba(15,23,42,.025)!important}
          .st-key-portfolio_risk_trend_panel>[data-testid="stVerticalBlock"],.st-key-portfolio_risk_distribution_panel>[data-testid="stVerticalBlock"]{gap:.15rem!important}
          .st-key-portfolio_risk_trend_panel .cv-pi-panel,.st-key-portfolio_risk_distribution_panel .cv-pi-panel{border:0!important;border-radius:0!important;background:transparent!important;padding:0!important;box-shadow:none!important}
          .cv-pi-table-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:7px 0 11px}
          .cv-pi-table-head h2{margin:0;color:#17243d;font-size:19px;font-weight:800;letter-spacing:-.025em}
          .cv-pi-table-head p{margin:4px 0 0;color:#74839a;font-size:12px}
          .cv-pi-table-card{width:100%;overflow-x:auto;border:1px solid #dce5f0;border-radius:13px;background:#fff;box-shadow:0 3px 10px rgba(15,23,42,.025)}
          .cv-pi-table{width:100%;min-width:980px;border-collapse:collapse;color:#334155;font-size:11px}
          .cv-pi-table th{padding:11px 10px;background:#f4f7fb;border-bottom:1px solid #dfe7f1;color:#64748b;text-align:left;font-size:9px;font-weight:850;letter-spacing:.055em;text-transform:uppercase;white-space:nowrap}
          .cv-pi-table td{padding:10px;border-bottom:1px solid #edf1f6;line-height:1.35;vertical-align:middle}
          .cv-pi-table tbody tr:last-child td{border-bottom:0}
          .cv-pi-table tbody tr:hover{background:#f8fbff}
          .cv-pi-table .cv-pi-project{display:block;color:#1e293b;font-size:11px;font-weight:750;white-space:normal}
          .cv-pi-table .cv-pi-bom{display:block;margin-top:3px;color:#74839a;font-size:10px;overflow-wrap:anywhere}
          .cv-pi-risk-pill{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-weight:750}
          .cv-pi-risk-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#94a3b8}
          .cv-pi-risk-pill.high .cv-pi-risk-dot{background:#ef4444}
          .cv-pi-risk-pill.medium .cv-pi-risk-dot{background:#f59e0b}
          .cv-pi-risk-pill.low .cv-pi-risk-dot{background:#2670e8}
          @media(max-width:1200px){.cv-pi-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}.cv-pi-chart-grid{grid-template-columns:1fr}}
          @media(max-width:720px){.cv-pi-head{display:block}.cv-pi-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.cv-pi-title{font-size:27px}}
          @media(max-width:480px){.cv-pi-kpis{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )
    top_left, top_right = st.columns([4.2, 1.15], vertical_alignment="bottom")
    with top_left:
        st.markdown(
            '<div class="cv-pi-head"><div><p class="cv-pi-kicker">Portfolio</p>'
            '<h1 class="cv-pi-title">Portfolio intelligence</h1>'
            '<p class="cv-pi-subtitle">A cross-project view of engineering data, supply-chain risk, and lifecycle exposure.</p></div></div>',
            unsafe_allow_html=True,
        )
    with top_right:
        st.selectbox(
            "Date range",
            ["Last 30 days", "Last 90 days", "Last 12 months", "All time"],
            index=["Last 30 days", "Last 90 days", "Last 12 months", "All time"].index(
                intelligence.get("time_window", "Last 12 months")
            ),
            key="portfolio_time_window",
            label_visibility="collapsed",
        )

    window = str(intelligence.get("time_window") or "Last 12 months")
    current_period = window.casefold()
    note_map = {
        "Saved Projects": f"Saved BOMs in {current_period}",
        "Component Records": f"Component entries in {current_period}",
        "Shared Components": "Recorded on multiple saved BOMs",
        "Single-Source Records": "Only where supplier count is recorded",
        "Lifecycle Exposure": "Obsolete, NRND, or EOL status recorded",
    }
    metrics = [
        ("▱", "Saved Projects", intelligence["total_projects"], note_map["Saved Projects"]),
        ("◇", "Component Records", intelligence["total_component_records"], note_map["Component Records"]),
        ("⌘", "Shared Components", intelligence["shared_component_count"], note_map["Shared Components"]),
        ("⚠", "Single-Source Records", intelligence["single_source_count"], note_map["Single-Source Records"]),
        ("◷", "Lifecycle Exposure", intelligence["lifecycle_count"], note_map["Lifecycle Exposure"]),
    ]
    comparison = intelligence.get("period_comparison") or {}
    exposure_metrics = {"Single-Source Records", "Lifecycle Exposure"}
    cards = ""
    for icon, label, value, note in metrics:
        change = comparison.get(label) if isinstance(comparison, dict) else None
        delta_markup = '<div class="cv-pi-kpi-delta neutral">No prior-period baseline</div>'
        if isinstance(change, dict):
            current_value = int(_number(change.get("current"), value))
            previous_value = int(_number(change.get("previous"), 0))
            delta = current_value - previous_value
            if previous_value == 0 and current_value > 0:
                delta_text = "↑ New in period"
            elif delta == 0:
                delta_text = "→ No change"
            else:
                percent = round((delta / previous_value) * 100) if previous_value else None
                delta_text = f"{'↑' if delta > 0 else '↓'} {delta:+,}"
                if percent is not None:
                    delta_text += f" ({percent:+d}%)"
            is_adverse = label in exposure_metrics
            is_positive = (delta <= 0) if is_adverse else (delta >= 0)
            tone = "positive" if is_positive else "negative"
            delta_markup = (
                f'<div class="cv-pi-kpi-delta {tone}">{html.escape(delta_text)} '
                "<span>vs. previous period</span></div>"
            )
        cards += (
            f'<article class="cv-pi-kpi"><span class="cv-pi-kpi-icon">{icon}</span>'
            f'<div class="cv-pi-kpi-label">{html.escape(label)}</div>'
            f'<div class="cv-pi-kpi-value">{int(value):,}</div>'
            f'<div class="cv-pi-kpi-note">{html.escape(note)}</div>{delta_markup}</article>'
        )
    st.markdown(f'<section class="cv-pi-kpis">{cards}</section>', unsafe_allow_html=True)

    if intelligence.get("time_window_note"):
        st.caption(str(intelligence["time_window_note"]))
    if comparison:
        st.caption("Period deltas compare saved analysis timestamps with the immediately preceding window.")

    chart_left, chart_right = st.columns([1.58, .95], gap="small")
    with chart_left:
        with st.container(key="portfolio_risk_trend_panel"):
            trend_heading, trend_filter_col = st.columns([4, 1.25], vertical_alignment="center")
            with trend_heading:
                st.markdown(
                    '<div class="cv-pi-panel"><h2>Portfolio risk trend</h2>'
                    '<p class="cv-pi-panel-sub">Count of recorded at-risk components across saved BOMs.</p></div>',
                    unsafe_allow_html=True,
                )
            with trend_filter_col:
                selected_risk_level = st.selectbox(
                    "Component risk level",
                    ["All risk levels", "High risk", "Medium risk", "Low risk"],
                    key="portfolio_risk_trend_level",
                    label_visibility="collapsed",
                )
            trend_rows = intelligence.get("monthly_risk_trend") or []
            if trend_rows:
                try:
                    import plotly.graph_objects as go

                    figure = go.Figure()
                    palette = {
                        "Low risk": ("#2670e8", "rgba(38,112,232,.55)"),
                        "Medium risk": ("#f59e0b", "rgba(245,158,11,.48)"),
                        "High risk": ("#e34f55", "rgba(227,79,85,.45)"),
                    }
                    month_labels = []
                    for row in trend_rows:
                        raw_month = str(row.get("Month") or "")
                        parsed_month = pd.to_datetime(raw_month, format="%Y-%m", errors="coerce")
                        month_labels.append(parsed_month.strftime("%b %y") if pd.notna(parsed_month) else raw_month)
                    visible_risk_levels = (
                        ("Low risk", "Medium risk", "High risk")
                        if selected_risk_level == "All risk levels"
                        else (selected_risk_level,)
                    )
                    for risk_label in visible_risk_levels:
                        line, fill = palette[risk_label]
                        is_stacked = selected_risk_level == "All risk levels"
                        figure.add_trace(go.Scatter(
                            x=month_labels,
                            y=[row.get(risk_label, 0) for row in trend_rows],
                            name=risk_label,
                            mode="lines+markers",
                            stackgroup="risk" if is_stacked else None,
                            fill=None if is_stacked else "tozeroy",
                            line={"color": line, "width": 1.5},
                            fillcolor=fill,
                            hovertemplate=f"%{{x}} · {risk_label}: %{{y:,}} components<extra></extra>",
                        ))
                    figure.update_layout(
                        height=268,
                        margin={"l": 12, "r": 8, "t": 10, "b": 8},
                        paper_bgcolor="white",
                        plot_bgcolor="white",
                        legend={"orientation": "h", "y": -0.18, "x": .5, "xanchor": "center"},
                        hovermode="x unified",
                        font={"family": "Inter, system-ui, sans-serif", "size": 11, "color": "#64748b"},
                        xaxis={"title": None, "type": "category", "gridcolor": "#edf1f6", "showline": False, "categoryorder": "array", "categoryarray": month_labels},
                        yaxis={"title": None, "gridcolor": "#edf1f6", "rangemode": "tozero", "zeroline": False},
                    )
                    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})
                except Exception:
                    st.dataframe(pd.DataFrame(trend_rows), hide_index=True, use_container_width=True)
            else:
                st.info("No dated risk snapshots are available in this range yet. As saved BOM analyses are added, the trend will populate.")
    with chart_right:
        with st.container(key="portfolio_risk_distribution_panel"):
            st.markdown(
                '<div class="cv-pi-panel"><h2>Risk distribution</h2>'
                '<p class="cv-pi-panel-sub">Assessed component records by current risk classification.</p></div>',
                unsafe_allow_html=True,
            )
            distribution = intelligence.get("risk_distribution") or {}
            values = [
                int(distribution.get(label) or 0)
                for label in ("High risk", "Medium risk", "Low risk", "Unassessed")
            ]
            if sum(values):
                try:
                    import plotly.graph_objects as go

                    figure = go.Figure(data=[go.Pie(
                        labels=[
                            f"High risk · {values[0]:,}",
                            f"Medium risk · {values[1]:,}",
                            f"Low risk · {values[2]:,}",
                            f"Unassessed · {values[3]:,}",
                        ],
                        values=values,
                        hole=.63,
                        sort=False,
                        marker={"colors": ["#e34f55", "#f59e0b", "#2670e8", "#cbd5e1"], "line": {"color": "#ffffff", "width": 2}},
                        textinfo="percent",
                        textposition="inside",
                        hovertemplate="%{label}<br>%{percent} of component records<extra></extra>",
                    )])
                    assessed = int(intelligence.get("assessed_component_records") or 0)
                    figure.update_layout(
                        height=268,
                        margin={"l": 8, "r": 8, "t": 8, "b": 8},
                        paper_bgcolor="white",
                        showlegend=True,
                        legend={"x": 1.02, "y": .5, "font": {"size": 11}},
                        annotations=[{"text": f"{assessed:,}<br><span style='font-size:11px'>assessed</span>", "x": .36, "y": .5, "showarrow": False, "font": {"size": 21, "color": "#17243d"}}],
                    )
                    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})
                except Exception:
                    st.dataframe(pd.DataFrame([{"Risk level": label, "Components": value} for label, value in distribution.items()]), hide_index=True, use_container_width=True)
            else:
                st.info("No component risk classifications are recorded in this period.")

    table_left, table_right = st.columns([5, 1], vertical_alignment="center")
    with table_left:
        st.markdown(
            '<div class="cv-pi-table-head"><div><h2>At-risk BOMs</h2>'
            '<p>BOMs with the highest concentration of recorded component exposure.</p></div></div>',
            unsafe_allow_html=True,
        )
    with table_right:
        if st.button("View all BOMs  ›", key="portfolio_view_all_boms", use_container_width=True):
            navigate = intelligence.get("navigate")
            if callable(navigate):
                navigate("BOM Analyzer", show_saved_analyses="1")
    bom_rows = intelligence.get("at_risk_boms") or []
    if not bom_rows:
        st.success("No at-risk BOMs are recorded in this time range.")
    else:
        visible = bom_rows[:5]
        body_rows = []
        for row in visible:
            level = str(row.get("Risk Level") or "Unknown")
            level_class = level.casefold() if level.casefold() in {"high", "medium", "low"} else "unknown"
            updated = str(row.get("Last Updated") or "Not recorded")
            updated = updated[:10] if updated != "Not recorded" else "—"
            body_rows.append(
                "<tr>"
                f'<td><span class="cv-pi-project">{html.escape(str(row.get("Project") or "Saved BOM"))}</span></td>'
                f'<td><span class="cv-pi-bom">{html.escape(str(row.get("BOM") or "Saved BOM"))}</span></td>'
                f'<td>{int(_number(row.get("Total Components"), 0)):,}</td>'
                f'<td><strong>{int(_number(row.get("At-Risk Components"), 0)):,}</strong></td>'
                f'<td><span class="cv-pi-risk-pill {level_class}"><i class="cv-pi-risk-dot"></i>{html.escape(level)}</span></td>'
                f'<td>{html.escape(str(row.get("Primary Risk Driver") or "Not recorded"))}</td>'
                f'<td>{html.escape(updated)}</td></tr>'
            )
        st.markdown(
            '<div class="cv-pi-table-card"><table class="cv-pi-table"><thead><tr>'
            '<th>Project</th><th>BOM name</th><th>Total components</th><th>At-risk components</th>'
            '<th>Risk level</th><th>Primary risk driver</th><th>Last updated</th></tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table></div>',
            unsafe_allow_html=True,
        )
        if len(bom_rows) > len(visible):
            st.caption(f"Showing {len(visible)} of {len(bom_rows):,} at-risk BOMs. Use View all BOMs to open the complete saved analysis list.")
        opener = intelligence.get("open_saved_bom")
        if callable(opener):
            open_options = {
                str(row["Analysis ID"]): f'{row["Project"]} — {row["BOM"]}'
                for row in bom_rows
                if row.get("Analysis ID")
            }
            if open_options:
                open_cols = st.columns([5, 1], vertical_alignment="bottom")
                with open_cols[0]:
                    chosen_id = st.selectbox(
                        "Open a saved BOM",
                        list(open_options),
                        format_func=lambda analysis_id: open_options[analysis_id],
                        key="portfolio_open_bom_selection",
                    )
                with open_cols[1]:
                    if st.button("Open BOM →", key="portfolio_open_selected_bom", type="primary", use_container_width=True):
                        opener(str(chosen_id), _rerun=True)
