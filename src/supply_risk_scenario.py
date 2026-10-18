"""Cadivor Milestone 22.0 — Supply Risk Scenario Planner.

Provides what-if analysis for stock loss, supplier loss, lifecycle exposure,
and demand growth across saved BOM records.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import html
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system import cadivor_engineering_dataframe
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


def _optional_number(value: Any) -> float | None:
    if value is None or str(value).strip().casefold() in {"", "nan", "none", "<na>"}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if pd.notna(number) else None


def _lead_time_increase(row: Dict[str, Any]) -> float | None:
    """Return only an explicitly recorded disruption delta; never invent weeks."""
    return _optional_number(
        _first(
            row,
            "lead_time_increase_weeks",
            "scenario_lead_time_increase_weeks",
            "disruption_lead_time_delta_weeks",
        )
    )


def _first(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def build_supply_scenario(
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    *,
    build_quantity: int = 100,
    stock_reduction_percent: int = 0,
    supplier_loss: int = 0,
    demand_growth_percent: int = 0,
    include_lifecycle_event: bool = False,
) -> Dict[str, Any]:
    analyses = list(analyses or [])
    parts = list(parts or [])

    analysis_lookup = {
        _text(row.get("id")): {
            "Project": _text(
                row.get("project_name") or row.get("name") or row.get("filename"),
                "Saved BOM",
            ),
            "Health": int(_number(row.get("health_score"), 0)),
        }
        for row in analyses
    }

    normalized: List[Dict[str, Any]] = []
    for part_index, row in enumerate(parts):
        analysis_id = _text(row.get("analysis_id"))
        qty = max(1, int(_number(_first(row, "quantity", "qty", "required_quantity"), 1)))
        raw_stock = _first(row, "stock_available", "stock", default=None)
        stock_value = _optional_number(raw_stock)
        stock_recorded = stock_value is not None
        stock = max(0, int(stock_value)) if stock_value is not None else None
        raw_suppliers = _first(row, "supplier_count", default=None)
        supplier_value = _optional_number(raw_suppliers)
        sources_recorded = supplier_value is not None
        suppliers = max(0, int(supplier_value)) if supplier_value is not None else None
        raw_price = _first(row, "unit_price", "price", "best_price", "estimated_unit_price", default=None)
        price_value = _optional_number(raw_price)
        price_recorded = price_value is not None
        unit_price = max(0.0, price_value) if price_value is not None else 0.0
        lifecycle = _text(row.get("lifecycle_status"), "Unknown")
        raw_risk_score = _first(row, "risk_score", "risk", default=None)
        risk_score_value = _optional_number(raw_risk_score)
        risk_score = int(risk_score_value) if risk_score_value is not None else 0

        adjusted_stock = None
        if stock_recorded:
            stock_factor = 1 - max(0, min(100, stock_reduction_percent)) / 100
            # With a primary supplier disruption, estimate remaining stock by
            # supplier share only when a supplier count is recorded. This is
            # an explicit scenario assumption, not a claim about the lost
            # distributor's exact inventory.
            if sources_recorded and suppliers and supplier_loss > 0:
                stock_factor *= max(0, suppliers - max(0, supplier_loss)) / suppliers
            adjusted_stock = max(0, int(round(stock * stock_factor)))
        adjusted_suppliers = (
            max(0, suppliers - max(0, supplier_loss))
            if sources_recorded
            else None
        )
        adjusted_quantity = max(
            1,
            int(round(qty * max(1, build_quantity) * (1 + max(0, demand_growth_percent) / 100))),
        )
        shortage = (
            max(0, adjusted_quantity - adjusted_stock)
            if adjusted_stock is not None
            else None
        )

        lifecycle_exposed = any(
            term in lifecycle.lower()
            for term in ("obsolete", "replacement", "nrnd", "not recommended", "eol")
        )
        if include_lifecycle_event and risk_score >= 40:
            lifecycle_exposed = True

        risk_score_recorded = risk_score_value is not None
        scenario_score = risk_score if risk_score_recorded else None
        if scenario_score is None and (stock_recorded or sources_recorded or lifecycle_exposed):
            scenario_score = 0
        if shortage is not None and shortage > 0:
            scenario_score = int(scenario_score or 0)
            scenario_score += 35
        elif adjusted_stock is not None and adjusted_stock < adjusted_quantity * 2:
            scenario_score = int(scenario_score or 0)
            scenario_score += 15
        if adjusted_suppliers is not None and adjusted_suppliers <= 0:
            scenario_score = int(scenario_score or 0)
            scenario_score += 30
        elif adjusted_suppliers == 1:
            scenario_score = int(scenario_score or 0)
            scenario_score += 15
        if lifecycle_exposed:
            scenario_score = int(scenario_score or 0)
            scenario_score += 20
        if scenario_score is not None:
            scenario_score = min(100, scenario_score)

        lead_time_increase = _lead_time_increase(row)

        normalized.append(
            {
                "Analysis ID": analysis_id,
                "Component Record Key": f"{analysis_id}:{part_index}",
                "Project": analysis_lookup.get(analysis_id, {}).get(
                    "Project", _text(row.get("project_name"), "Saved BOM")
                ),
                "Project Health": analysis_lookup.get(analysis_id, {}).get("Health", 0),
                "Part Number": _text(_first(row, "mpn", "MPN", "part_number"), "Unknown"),
                "Image URL": normalize_supplier_image_url(
                    _first(row, "image_url", "Image URL", "photo_url")
                ),
                "Manufacturer": _text(row.get("manufacturer"), "Unknown"),
                "Lifecycle": lifecycle,
                "Original Stock": stock,
                "Scenario Stock": adjusted_stock,
                "Stock Recorded": stock_recorded,
                "Original Sources": suppliers,
                "Scenario Sources": adjusted_suppliers,
                "Sources Recorded": sources_recorded,
                "Required Units": adjusted_quantity,
                "Shortage Units": shortage,
                "Unit Price": unit_price,
                "Price Recorded": price_recorded,
                "Estimated Shortage Value": (
                    shortage * unit_price if shortage is not None else None
                ),
                "Current Risk": risk_score,
                "Scenario Risk": scenario_score,
                "Risk Score Recorded": risk_score_recorded,
                "Lifecycle Event": lifecycle_exposed,
                "Lead Time Weeks": _optional_number(_first(row, "lead_time_weeks", "lead_time")),
                "Lead Time Increase Weeks": lead_time_increase,
            }
        )

    # Supplier stock is one catalog pool per manufacturer part number, even
    # when that part appears on several saved BOMs. Aggregate project demand
    # first and count that stock pool once; otherwise duplicate BOM rows can
    # make a shared part appear to have enough stock when the combined demand
    # exceeds it. When snapshots disagree, use the lowest recorded stock/source
    # count as a conservative planning assumption.
    source_rows = normalized
    component_groups: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        part_number_key = (
            row["Component Record Key"]
            if row["Part Number"].strip().casefold() in {"", "unknown", "n/a", "nan"}
            else row["Part Number"].casefold()
        )
        component_groups[(part_number_key, row["Manufacturer"].casefold())].append(row)
    normalized = []
    for group in component_groups.values():
        first = group[0]
        projects = list(dict.fromkeys(row["Project"] for row in group))
        analysis_projects = list(dict.fromkeys(
            (row["Analysis ID"], row["Project"])
            for row in group
            if row["Analysis ID"] or row["Project"]
        ))
        analysis_ids = list(dict.fromkeys(
            analysis_id for analysis_id, _project in analysis_projects if analysis_id
        ))
        stock_values = [row["Original Stock"] for row in group if row["Stock Recorded"]]
        supplier_values = [row["Original Sources"] for row in group if row["Sources Recorded"]]
        price_values = [row["Unit Price"] for row in group if row["Price Recorded"]]
        base_stock = min(stock_values) if stock_values else None
        base_sources = min(supplier_values) if supplier_values else None
        stock_recorded = bool(stock_values)
        sources_recorded = bool(supplier_values)
        stock_factor = 1 - max(0, min(100, stock_reduction_percent)) / 100
        if sources_recorded and base_sources and supplier_loss > 0:
            stock_factor *= max(0, base_sources - max(0, supplier_loss)) / base_sources
        scenario_stock = max(0, int(round(base_stock * stock_factor))) if stock_recorded else None
        scenario_sources = (
            max(0, base_sources - max(0, supplier_loss)) if sources_recorded else None
        )
        required_units = sum(row["Required Units"] for row in group)
        shortage = max(0, required_units - scenario_stock) if scenario_stock is not None else None
        price_recorded = bool(price_values)
        unit_price = max(price_values) if price_values else 0.0
        raw_score_values = [row["Current Risk"] for row in group if row["Risk Score Recorded"]]
        risk_score_recorded = bool(raw_score_values)
        current_risk = max(raw_score_values) if raw_score_values else 0
        lifecycle_exposed = any(row["Lifecycle Event"] for row in group)
        if include_lifecycle_event and current_risk >= 40:
            lifecycle_exposed = True
        scenario_score = current_risk if risk_score_recorded else None
        if scenario_score is None and (stock_recorded or sources_recorded or lifecycle_exposed):
            scenario_score = 0
        if shortage is not None and shortage > 0:
            scenario_score = int(scenario_score or 0) + 35
        elif scenario_stock is not None and scenario_stock < required_units * 2:
            scenario_score = int(scenario_score or 0) + 15
        if scenario_sources is not None and scenario_sources <= 0:
            scenario_score = int(scenario_score or 0) + 30
        elif scenario_sources == 1:
            scenario_score = int(scenario_score or 0) + 15
        if lifecycle_exposed:
            scenario_score = int(scenario_score or 0) + 20
        if scenario_score is not None:
            scenario_score = min(100, scenario_score)
        lead_time_increases = [
            row["Lead Time Increase Weeks"] for row in group
            if row["Lead Time Increase Weeks"] is not None
        ]
        lead_times = [row["Lead Time Weeks"] for row in group if row["Lead Time Weeks"] is not None]
        normalized.append({
            **first,
            "Analysis ID": analysis_ids[0] if analysis_ids else first["Analysis ID"],
            "Analysis IDs": analysis_ids,
            "Projects": projects,
            "Analysis Projects": analysis_projects,
            "Project Count": len(analysis_projects) or 1,
            "Project": (
                analysis_projects[0][1]
                if len(analysis_projects) == 1
                else f"Shared across {len(analysis_projects):,} BOMs"
            ),
            "Project Health": min((row["Project Health"] for row in group), default=0),
            "Original Stock": base_stock,
            "Scenario Stock": scenario_stock,
            "Stock Recorded": stock_recorded,
            "Original Sources": base_sources,
            "Scenario Sources": scenario_sources,
            "Sources Recorded": sources_recorded,
            "Required Units": required_units,
            "Shortage Units": shortage,
            "Unit Price": unit_price,
            "Price Recorded": price_recorded,
            "Estimated Shortage Value": shortage * unit_price if shortage is not None and price_recorded else None,
            "Current Risk": current_risk,
            "Scenario Risk": scenario_score,
            "Risk Score Recorded": risk_score_recorded,
            "Lifecycle Event": lifecycle_exposed,
            "Lead Time Weeks": min(lead_times) if lead_times else None,
            "Lead Time Increase Weeks": max(lead_time_increases) if lead_time_increases else None,
        })

    impacted = [
        row for row in normalized
        if (row["Shortage Units"] or 0) > 0
        or (row["Sources Recorded"] and (row["Scenario Sources"] or 0) <= 1)
        or row["Lifecycle Event"]
        or (row["Scenario Risk"] is not None and row["Scenario Risk"] >= 60)
    ]
    impacted.sort(
        key=lambda row: (
            -(row["Scenario Risk"] if row["Scenario Risk"] is not None else -1),
            -(row["Shortage Units"] or 0),
            row["Project Health"],
        )
    )

    project_rows: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        analysis_projects = row.get("Analysis Projects") or [(row["Analysis ID"], row["Project"])]
        for analysis_id, project in analysis_projects:
            project_rows[(analysis_id, project)].append(row)

    project_impact = []
    for (analysis_id, project), rows in project_rows.items():
        shortage_parts = sum(1 for row in rows if (row["Shortage Units"] or 0) > 0)
        single_source = sum(
            1 for row in rows
            if row["Sources Recorded"] and (row["Scenario Sources"] or 0) <= 1
        )
        lifecycle_parts = sum(1 for row in rows if row["Lifecycle Event"])
        known_scores = [row["Scenario Risk"] for row in rows if row["Scenario Risk"] is not None]
        max_risk = max(known_scores, default=None)
        shortage_value = sum(
            row["Estimated Shortage Value"] / max(1, len(row.get("Analysis Projects") or [(analysis_id, project)]))
            for row in rows
            if row["Estimated Shortage Value"] is not None
        )
        project_impact.append(
            {
                "Project": project,
                "Analysis ID": analysis_id,
                "Impacted Components": sum(
                    1 for row in rows
                    if (row["Scenario Risk"] is not None and row["Scenario Risk"] >= 60)
                    or (row["Shortage Units"] or 0) > 0
                    or (row["Sources Recorded"] and (row["Scenario Sources"] or 0) <= 1)
                    or row["Lifecycle Event"]
                ),
                "Shortage Components": shortage_parts,
                "Single-Source Components": single_source,
                "Lifecycle Components": lifecycle_parts,
                "Highest Scenario Risk": max_risk,
                "Estimated Shortage Value": shortage_value,
            }
        )
    project_impact.sort(
        key=lambda row: (
            -(row["Highest Scenario Risk"] if row["Highest Scenario Risk"] is not None else -1),
            -row["Impacted Components"],
        )
    )

    shortage_components = sum(
        1 for row in normalized if (row["Shortage Units"] or 0) > 0
    )
    single_source_components = sum(
        1 for row in normalized
        if row["Sources Recorded"] and (row["Scenario Sources"] or 0) <= 1
    )
    lifecycle_components = sum(1 for row in normalized if row["Lifecycle Event"])
    critical_components = sum(
        1 for row in normalized
        if row["Scenario Risk"] is not None and row["Scenario Risk"] >= 80
    )
    shortage_value = sum(
        row["Estimated Shortage Value"]
        for row in normalized
        if row["Estimated Shortage Value"] is not None
    )
    lead_time_deltas = [
        row["Lead Time Increase Weeks"]
        for row in normalized
        if row["Lead Time Increase Weeks"] is not None
    ]
    known_stock = [row for row in normalized if row["Stock Recorded"]]
    known_source_rows = [row for row in normalized if row["Sources Recorded"]]
    known_stock_required_units = sum(
        row["Required Units"] for row in known_stock
    )
    affected_projects = sum(1 for row in project_impact if row["Impacted Components"] > 0)

    recommendations = []
    scenario_summary = (
        f"{build_quantity:,} planned build(s), "
        f"{stock_reduction_percent}% stock reduction, "
        f"{supplier_loss} supplier(s) lost, "
        f"{demand_growth_percent}% demand growth"
    )
    if impacted:
        top = impacted[0]
        if (top["Shortage Units"] or 0) > 0:
            recommendations.append(
                f"First priority under this scenario: resolve the {top['Shortage Units']:,}-unit "
                f"shortage for {top['Part Number']} in {top['Project']}."
            )
        elif top["Scenario Sources"] is not None and top["Scenario Sources"] <= 1:
            recommendations.append(
                f"First priority under this scenario: restore sourcing coverage for "
                f"{top['Part Number']} in {top['Project']}."
            )
        elif top["Lifecycle Event"]:
            recommendations.append(
                f"First priority under this scenario: begin replacement qualification for "
                f"{top['Part Number']} in {top['Project']}."
            )
    if shortage_components:
        recommendations.append(
            f"{shortage_components} component record(s) fall short of modeled demand. "
            f"Secure inventory, reduce demand, or approve substitutes."
        )
    if single_source_components:
        if supplier_loss > 0:
            recommendations.append(
                f"Losing {supplier_loss} supplier(s) leaves {single_source_components} component "
                f"record(s) with one or fewer sources. Prioritize alternate-source qualification."
            )
        else:
            recommendations.append(
                f"{single_source_components} component record(s) already have one or fewer sources. "
                f"Add authorized sourcing coverage before production."
            )
    if lifecycle_components:
        lifecycle_reason = (
            "including the modeled lifecycle disruption"
            if include_lifecycle_event else "based on recorded lifecycle status"
        )
        recommendations.append(
            f"{lifecycle_components} lifecycle-exposed component record(s) require replacement "
            f"planning, {lifecycle_reason}."
        )
    if demand_growth_percent > 0:
        recommendations.append(
            f"Demand growth of {demand_growth_percent}% raises modeled requirements. "
            f"Confirm purchase quantities and safety stock before release."
        )
    if stock_reduction_percent > 0:
        recommendations.append(
            f"A {stock_reduction_percent}% stock reduction is modeled. Review the components "
            f"with the lowest remaining coverage first."
        )
    if not recommendations:
        recommendations.append(
            "The selected scenario does not create a major recorded supply or lifecycle exception."
        )
    recommendations = recommendations[:5]

    return {
        "rows": normalized,
        "impacted": impacted,
        "project_impact": project_impact,
        "build_quantity": max(1, build_quantity),
        "stock_reduction_percent": stock_reduction_percent,
        "supplier_loss": supplier_loss,
        "demand_growth_percent": demand_growth_percent,
        "include_lifecycle_event": include_lifecycle_event,
        "affected_projects": affected_projects,
        "shortage_components": shortage_components,
        "single_source_components": single_source_components,
        "lifecycle_components": lifecycle_components,
        "critical_components": critical_components,
        "shortage_value": shortage_value,
        "projected_stock_gap": sum(row["Shortage Units"] or 0 for row in normalized),
        "exposed_components": len(impacted),
        "known_stock_components": len(known_stock),
        "unknown_stock_components": len(normalized) - len(known_stock),
        "known_source_components": len(known_source_rows),
        "unknown_source_components": len(normalized) - len(known_source_rows),
        "recorded_stock_total": sum(row["Original Stock"] or 0 for row in known_stock),
        "scenario_stock_total": sum(row["Scenario Stock"] or 0 for row in known_stock),
        "required_units_total": sum(row["Required Units"] for row in normalized),
        "required_units_known_stock_total": known_stock_required_units,
        "lead_time_increase_weeks": (
            sum(lead_time_deltas) / len(lead_time_deltas) if lead_time_deltas else None
        ),
        "lead_time_evidence_count": len(lead_time_deltas),
        "recommendations": recommendations,
        "scenario_summary": scenario_summary,
        "component_count": len(normalized),
        "source_component_record_count": len(source_rows),
    }


def _css() -> None:
    st.markdown(
        """
        <style id="cadivor-scenario-planner-22" data-cadivor-layout-style="true">
          .cv22-hero{
            border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eef5ff);
            border-radius:24px;padding:25px;margin-bottom:18px;
            box-shadow:0 16px 42px rgba(37,99,235,.07)
          }
          .cv22-eyebrow{font-size:11px;font-weight:900;color:#2563eb;letter-spacing:.11em;text-transform:uppercase}
          .cv22-title{font-size:30px;font-weight:950;color:#0f172a;letter-spacing:-.045em;margin:7px 0}
          .cv22-copy{font-size:14px;font-weight:680;color:#52647a;line-height:1.58;max-width:1100px}
          .cv22-section{font-size:22px;font-weight:950;color:#0f172a;letter-spacing:-.03em;margin:22px 0 5px}
          .cv22-subtitle{font-size:13px;font-weight:650;color:#64748b;margin-bottom:12px}
          .cv22-card{
            border:1px solid #dbe3ef;background:#fff;border-radius:17px;padding:17px;
            margin-bottom:11px;box-shadow:0 8px 24px rgba(15,23,42,.04)
          }
          .cv22-card-title{font-size:16px;font-weight:950;color:#0f172a}
          .cv22-card-copy{font-size:13px;font-weight:680;color:#475569;line-height:1.52;margin-top:6px}
          .cv22-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}
          .cv22-meta span{
            font-size:10px;font-weight:850;color:#1d4ed8;background:#eff6ff;
            border:1px solid #dbeafe;border-radius:999px;padding:5px 8px
          }
          .cv22-recommendation{
            border-left:4px solid #2563eb;background:#f8fbff;border-radius:0 14px 14px 0;
            padding:14px 16px;margin-bottom:10px;font-size:13px;font-weight:740;
            color:#334155;line-height:1.5
          }
          .cv22-kpi-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:18px 0 24px}
          .cv22-kpi{border:1px solid #dbe3ef;background:#fff;border-radius:18px;padding:16px 17px;box-shadow:0 8px 24px rgba(15,23,42,.04);min-height:104px}
          .cv22-kpi-label{font-size:12px;font-weight:850;color:#64748b;line-height:1.25}
          .cv22-kpi-value{font-size:31px;font-weight:950;color:#0f172a;letter-spacing:-.04em;margin-top:10px;line-height:1}
          .cv22-kpi-note{font-size:11px;font-weight:700;color:#64748b;margin-top:8px;line-height:1.35}
          .cv22-kpi.alert{border-color:#fecaca;background:#fff7f7}.cv22-kpi.alert .cv22-kpi-value{color:#b91c1c}
          .cv22-kpi.warn{border-color:#fde68a;background:#fffbeb}.cv22-kpi.warn .cv22-kpi-value{color:#a16207}
          .cv22-kpi.info{border-color:#bfdbfe;background:#f8fbff}
          .cv22-scenario-strip{border:1px solid #bfdbfe;background:#eff6ff;border-radius:14px;padding:12px 14px;margin:0 0 16px;font-size:12px;font-weight:800;color:#1e40af}
          @media (max-width:1100px){.cv22-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
          .cv22-result-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:14px;margin:0 0 24px}
          .cv22-result-card{border:1px solid #fecaca;background:linear-gradient(135deg,#fff7f7,#fff1f2);border-radius:20px;padding:20px;min-height:148px;box-shadow:0 10px 28px rgba(185,28,28,.06)}
          .cv22-result-label{font-size:12px;font-weight:900;color:#9f1239;text-transform:uppercase;letter-spacing:.08em}
          .cv22-result-value{font-size:38px;font-weight:950;color:#b91c1c;letter-spacing:-.05em;margin-top:12px;line-height:1}
          .cv22-result-note{font-size:12px;font-weight:760;color:#be123c;margin-top:10px;line-height:1.45}
          .cv22-response-card{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f8fbff);border-radius:20px;padding:20px;min-height:148px;box-shadow:0 10px 28px rgba(37,99,235,.05)}
          .cv22-response-title{font-size:18px;font-weight:950;color:#0f172a;letter-spacing:-.025em}
          .cv22-badges{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
          .cv22-badge{font-size:11px;font-weight:850;color:#1e40af;background:#eff6ff;border:1px solid #bfdbfe;border-radius:999px;padding:6px 9px}
          @media (max-width:1100px){.cv22-result-grid{grid-template-columns:1fr}}
          .cv22-warning{
            border:1px solid #fecaca;background:#fff1f2;border-radius:18px;padding:18px
          }
          .cv22-warning strong{font-size:31px;color:#b91c1c;letter-spacing:-.04em}
          .cv22-warning span{display:block;font-size:12px;font-weight:800;color:#be123c;margin-top:3px}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_supply_scenario_header() -> None:
    st.markdown(
        """
        <section class="cv22-hero">
          <div class="cv22-eyebrow">Supply</div>
          <div class="cv22-title">Supply Scenario</div>
          <div class="cv22-copy">
            Test how demand growth, stock loss, supplier loss, or a lifecycle event could affect
            saved projects before the disruption occurs. Cadivor converts the scenario into
            prioritized engineering and procurement actions.
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_supply_scenario(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
    show_header: bool = True,
) -> None:
    _css()
    photo_column = st.column_config.ImageColumn("Part photo", width="small")
    if show_header:
        render_supply_scenario_header()

    lifecycle_badge = (
        '<span class="cv22-badge">Lifecycle disruption modeled</span>'
        if intelligence["include_lifecycle_event"]
        else '<span class="cv22-badge">Recorded lifecycle only</span>'
    )
    st.markdown(
        f"""
        <section class="cv22-scenario-strip">
          <strong>Current Scenario</strong>
          <div class="cv22-badges">
            <span class="cv22-badge">{intelligence["build_quantity"]:,} planned builds</span>
            <span class="cv22-badge">{intelligence["stock_reduction_percent"]}% stock reduction</span>
            <span class="cv22-badge">{intelligence["supplier_loss"]} supplier(s) lost</span>
            <span class="cv22-badge">{intelligence["demand_growth_percent"]}% demand growth</span>
            {lifecycle_badge}
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <section class="cv22-kpi-grid">
          <div class="cv22-kpi info"><div class="cv22-kpi-label">Affected Projects</div><div class="cv22-kpi-value">{intelligence["affected_projects"]}</div><div class="cv22-kpi-note">Projects with at least one modeled exception</div></div>
          <div class="cv22-kpi alert"><div class="cv22-kpi-label">Projected Shortages</div><div class="cv22-kpi-value">{intelligence["shortage_components"]}</div><div class="cv22-kpi-note">Records where demand exceeds stock</div></div>
          <div class="cv22-kpi warn"><div class="cv22-kpi-label">Single-Source Exposure</div><div class="cv22-kpi-value">{intelligence["single_source_components"]}</div><div class="cv22-kpi-note">Records left with one or fewer suppliers</div></div>
          <div class="cv22-kpi warn"><div class="cv22-kpi-label">Lifecycle Exposure</div><div class="cv22-kpi-value">{intelligence["lifecycle_components"]}</div><div class="cv22-kpi-note">Records requiring replacement planning</div></div>
          <div class="cv22-kpi alert"><div class="cv22-kpi-label">Critical Components</div><div class="cv22-kpi-value">{intelligence["critical_components"]}</div><div class="cv22-kpi-note">Scenario risk score of 80 or higher</div></div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    primary_recommendation = (
        intelligence["recommendations"][0]
        if intelligence["recommendations"]
        else "No major response is required for this scenario."
    )

    st.markdown(
        f"""
        <section class="cv22-result-grid">
          <div class="cv22-result-card">
            <div class="cv22-result-label">Scenario Exposure</div>
            <div class="cv22-result-value">${intelligence['shortage_value']:,.2f}</div>
            <div class="cv22-result-note">Estimated value of uncovered demand using recorded unit prices</div>
          </div>
          <div class="cv22-response-card">
            <div class="cv22-response-title">Recommended Response for This Scenario</div>
            <div class="cv22-card-copy">{html.escape(primary_recommendation)}</div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if len(intelligence["recommendations"]) > 1:
        with st.expander(f"View all recommended responses ({len(intelligence['recommendations'])})"):
            for recommendation in intelligence["recommendations"]:
                st.markdown(f'<div class="cv22-recommendation">✓ {html.escape(recommendation)}</div>', unsafe_allow_html=True)

    st.markdown('<div class="cv22-section">Highest-Impact Components</div>', unsafe_allow_html=True)
    st.markdown('<div class="cv22-subtitle">Components are ranked by projected scenario risk and shortage exposure.</div>', unsafe_allow_html=True)
    if not intelligence["impacted"]:
        st.success("No material component impact is identified under this scenario.")
    for index, row in enumerate(intelligence["impacted"][:6]):
        action = (
            "Resolve projected shortage" if row["Shortage Units"] > 0 else
            "Add sourcing coverage" if row["Scenario Sources"] <= 1 else
            "Prepare replacement plan" if row["Lifecycle Event"] else
            "Review component risk"
        )
        photo = part_image_markup(row.get("Image URL"), row["Part Number"], size=64, part=row)
        st.markdown(
            f"""<section class="cv22-card cv-part-card-layout">
              {photo}<div><div class="cv22-card-title">{html.escape(row['Part Number'])}</div>
              <div class="cv22-card-copy">{html.escape(row['Project'])} · {html.escape(action)}</div>
              <div class="cv22-meta">
                <span>Scenario risk {row['Scenario Risk']}/100</span><span>Required {row['Required Units']:,}</span>
                <span>Stock {row['Scenario Stock']:,}</span><span>Shortage {row['Shortage Units']:,}</span>
                <span>{row['Scenario Sources']} source(s)</span><span>{html.escape(row['Lifecycle'])}</span>
              </div></div></section>""", unsafe_allow_html=True)
        actions=st.columns(2)
        with actions[0]:
            internal_nav_button("Find Alternative","Alternative Finder",key=f"scenario_alt_{index}",use_container_width=True,original_part=row["Part Number"],source_page="supply_risk_scenario")
        with actions[1]:
            internal_nav_button("Open Monitoring","Monitoring",key=f"scenario_monitor_{index}",use_container_width=True)

    st.markdown(
        '<div class="cv22-section">Project Impact</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="cv22-subtitle">Projects with the highest scenario risk appear first.</div>',
        unsafe_allow_html=True,
    )
    if intelligence["project_impact"]:
        project_df = pd.DataFrame(intelligence["project_impact"])
        cadivor_engineering_dataframe(
            project_df,
            column_config={
                "Estimated Shortage Value": st.column_config.NumberColumn(format="$%.2f"),
            },
        )

    shortage_tab, sourcing_tab, lifecycle_tab, all_tab = st.tabs(
        ["Projected Shortages", "Supplier Exposure", "Lifecycle Exposure", "All Scenario Records"]
    )

    with shortage_tab:
        rows = [
            row for row in intelligence["rows"]
            if (row["Shortage Units"] or 0) > 0
        ]
        if rows:
            df = pd.DataFrame(rows)
            cadivor_engineering_dataframe(
                df[
                    [
                        "Project",
                        "Part Number",
                        "Image URL",
                        "Manufacturer",
                        "Required Units",
                        "Scenario Stock",
                        "Shortage Units",
                        "Estimated Shortage Value",
                        "Scenario Risk",
                    ]
                ],
                column_config={
                    "Image URL": photo_column,
                    "Estimated Shortage Value": st.column_config.NumberColumn(format="$%.2f"),
                },
            )
        else:
            st.success("No projected component shortage is identified.")

    with sourcing_tab:
        rows = [
            row for row in intelligence["rows"]
            if row["Sources Recorded"] and (row["Scenario Sources"] or 0) <= 1
        ]
        if rows:
            df = pd.DataFrame(rows)
            cadivor_engineering_dataframe(
                df[
                    [
                        "Project",
                        "Part Number",
                        "Image URL",
                        "Manufacturer",
                        "Original Sources",
                        "Scenario Sources",
                        "Scenario Stock",
                        "Scenario Risk",
                    ]
                ],
                column_config={"Image URL": photo_column},
            )
        else:
            st.success("Every recorded component retains more than one source.")

    with lifecycle_tab:
        rows = [row for row in intelligence["rows"] if row["Lifecycle Event"]]
        if rows:
            df = pd.DataFrame(rows)
            cadivor_engineering_dataframe(
                df[
                    [
                        "Project",
                        "Part Number",
                        "Image URL",
                        "Manufacturer",
                        "Lifecycle",
                        "Scenario Risk",
                    ]
                ],
                column_config={"Image URL": photo_column},
            )
        else:
            st.success("No lifecycle exposure is modeled in this scenario.")

    with all_tab:
        if intelligence["rows"]:
            cadivor_engineering_dataframe(
                pd.DataFrame(intelligence["rows"])[
                    [
                        "Project",
                        "Part Number",
                        "Image URL",
                        "Manufacturer",
                        "Required Units",
                        "Scenario Stock",
                        "Scenario Sources",
                        "Shortage Units",
                        "Lifecycle",
                        "Current Risk",
                        "Scenario Risk",
                    ]
                ],
                column_config={"Image URL": photo_column},
            )

    st.markdown(
        '<div class="cv22-section">Continue Your Review</div>',
        unsafe_allow_html=True,
    )
    actions = st.columns(5)
    with actions[0]:
        internal_nav_button(
            "Monitoring",
            "Monitoring",
            key="scenario_monitoring",
            use_container_width=True,
        )
    with actions[1]:
        internal_nav_button(
            "Procurement Advisor",
            "Procurement Advisor",
            key="scenario_procurement",
            use_container_width=True,
        )
    with actions[2]:
        internal_nav_button(
            "Portfolio Intelligence",
            "Portfolio Intelligence",
            key="scenario_portfolio",
            use_container_width=True,
        )
    with actions[3]:
        internal_nav_button(
            "Design Impact",
            "Design Impact Analyzer",
            key="scenario_design",
            use_container_width=True,
        )
    with actions[4]:
        internal_nav_button(
            "Reports",
            "Reports",
            key="scenario_reports",
            use_container_width=True,
        )


def render_supply_scenario_dashboard(
    *,
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    internal_nav_button: Callable[..., Any],
) -> None:
    """Render the scenario workspace using saved BOM and supplier evidence."""
    _css()
    analyses = list(analyses or [])
    parts = list(parts or [])
    presets = {
        "Primary supplier disruption": (0, 1, 0, False),
        "Component availability reduction": (25, 0, 0, False),
        "Demand increase": (0, 0, 25, False),
        "Lifecycle event": (0, 0, 0, True),
        "No disruption": (0, 0, 0, False),
    }
    choice_options = list(presets)
    active = st.session_state.get("supply_scenario_active") or {
        "choice": choice_options[0],
        "horizon": 90,
        "build_quantity": 1,
        "customize": False,
        "stock_reduction": 0,
        "supplier_loss": 1,
        "demand_growth": 0,
        "lifecycle_event": False,
    }
    if active.get("choice") not in presets:
        active["choice"] = choice_options[0]
    active_defaults = presets[active["choice"]]

    st.markdown(
        """
        <style id="cadivor-scenario-mockup-v1" data-cadivor-layout-style="true">
          .st-key-approved_page_canvas_standard_supply_risk_scenario{
            box-sizing:border-box!important;width:100%!important;max-width:1440px!important;
            margin:0 auto!important;padding:28px 0 36px!important
          }
          .cv-sr-page{color:#17243d}
          .cv-sr-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin:0 0 18px}
          .cv-sr-kicker{margin:0 0 5px;color:#64748b;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
          .cv-sr-title{margin:0 0 5px;color:#0f172a;font-size:32px;font-weight:820;line-height:1.12;letter-spacing:-.035em}
          .cv-sr-subtitle{margin:0;color:#64748b;font-size:14px;line-height:1.5}
          .cv-sr-controls{margin:0 0 16px}
          .cv-sr-controls [data-testid="stForm"]{border:0!important;padding:0!important}
          .cv-sr-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 16px}
          .cv-sr-kpi{display:flex;align-items:flex-start;gap:12px;min-height:118px;padding:17px 16px;border:1px solid #dce7f5;border-radius:15px;background:#f7faff}
          .cv-sr-kpi-icon{display:flex;flex:0 0 42px;align-items:center;justify-content:center;width:42px;height:42px;border-radius:12px;background:#e8f1ff;color:#2563eb;font-size:20px;font-weight:800}
          .cv-sr-kpi-label{color:#52647b;font-size:12px;font-weight:720;line-height:1.3}
          .cv-sr-kpi-value{margin-top:8px;color:#0f172a;font-size:26px;font-weight:850;line-height:1.05;letter-spacing:-.035em}
          .cv-sr-kpi-note{margin-top:7px;color:#74839a;font-size:11px;line-height:1.35}
          .cv-sr-grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);gap:14px;margin:0 0 15px}
          .cv-sr-panel{box-sizing:border-box;min-width:0;border:1px solid #dce5f0;border-radius:15px;background:#fff;padding:17px 18px;box-shadow:0 3px 10px rgba(15,23,42,.025)}
          .cv-sr-panel h2{margin:0;color:#17243d;font-size:17px;font-weight:780;letter-spacing:-.02em}
          .cv-sr-panel-sub{margin:4px 0 13px;color:#74839a;font-size:12px;line-height:1.45}
          .cv-sr-chart{display:block;width:100%;height:auto;min-height:235px}
          .cv-sr-legend{display:flex;flex-wrap:wrap;justify-content:center;gap:18px;margin:7px 0 0;color:#64748b;font-size:11px}
          .cv-sr-legend span{display:inline-flex;align-items:center;gap:6px}
          .cv-sr-swatch{display:inline-block;width:18px;height:3px;border-radius:4px;background:#2563eb}
          .cv-sr-swatch.disrupted{background:#e34f55}
          .cv-sr-swatch.demand{background:#64748b}
          .cv-sr-table{width:100%;border-collapse:collapse;font-size:12px}
          .cv-sr-table th{padding:9px 8px;text-align:left;color:#687991;background:#f5f8fc;border-bottom:1px solid #e5ebf3;font-size:10px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}
          .cv-sr-table td{padding:10px 8px;vertical-align:top;color:#36465d;border-bottom:1px solid #edf1f6;line-height:1.35}
          .cv-sr-table tr:last-child td{border-bottom:0}
          .cv-sr-table strong{display:block;color:#17243d;font-size:12px}
          .cv-sr-table small{display:block;margin-top:3px;color:#74839a;font-size:10px}
          .cv-sr-gap{color:#d9414a!important;font-weight:800;white-space:nowrap}
          .cv-sr-section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:7px 0 12px}
          .cv-sr-section-head h2{margin:0;color:#17243d;font-size:19px;font-weight:800;letter-spacing:-.025em}
          .cv-sr-section-head p{margin:4px 0 0;color:#74839a;font-size:12px}
          .cv-sr-actions{border:1px solid #dce5f0;border-radius:15px;background:#fff;overflow:hidden}
          .cv-sr-action-head{display:grid;grid-template-columns:1.45fr .95fr 1.2fr 1.3fr .58fr .9fr 1fr;gap:8px;align-items:center;padding:11px 13px;background:#f5f8fc;border-bottom:1px solid #e5ebf3;color:#687991;font-size:10px;font-weight:800;letter-spacing:.035em;text-transform:uppercase}
          .cv-sr-action-row{display:grid;grid-template-columns:1.45fr .95fr 1.2fr 1.3fr .58fr .9fr 1fr;gap:8px;align-items:center;padding:8px 10px 8px 13px;border-bottom:1px solid #edf1f6;color:#36465d;font-size:11px}
          .cv-sr-action-row:last-child{border-bottom:0}
          .cv-sr-action-row strong{color:#17243d;font-size:12px}
          [class*="st-key-cv_sr_action_row_"]{padding:2px 10px 2px 13px;border-bottom:1px solid #edf1f6}
          [class*="st-key-cv_sr_action_row_"]:last-child{border-bottom:0}
          [class*="st-key-cv_sr_action_row_"] [data-testid="stHorizontalBlock"]{align-items:center!important;gap:8px!important}
          [class*="st-key-cv_sr_action_row_"] [data-testid="stVerticalBlock"]{gap:0!important}
          [class*="st-key-cv_sr_action_row_"] [data-testid="stElementContainer"]{margin:0!important;padding:0!important}
          .cv-sr-tag{display:inline-flex;align-items:center;border-radius:999px;padding:5px 8px;background:#eaf2ff;color:#2762bd;font-size:10px;font-weight:750;white-space:nowrap}
          .cv-sr-note{margin:10px 0 0;color:#74839a;font-size:11px;line-height:1.45}
          @media(max-width:1150px){.cv-sr-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.cv-sr-grid{grid-template-columns:1fr}.cv-sr-actions{overflow-x:auto}.cv-sr-action-head,.cv-sr-action-row{min-width:980px}}
          @media(max-width:650px){.cv-sr-kpis{grid-template-columns:1fr}.cv-sr-title{font-size:27px}.cv-sr-head{display:block}}
        </style>
        <div class="cv-sr-page">
          <header class="cv-sr-head"><div><p class="cv-sr-kicker">Supply chain</p>
          <h1 class="cv-sr-title">Supply scenario</h1>
          <p class="cv-sr-subtitle">Model supplier, component, and demand disruptions to understand impact and evaluate mitigation options.</p></div></header>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("supply_scenario_mockup_controls", border=False):
        control_cols = st.columns([1.45, 1, .62], vertical_alignment="bottom")
        with control_cols[0]:
            selected_choice = st.selectbox(
                "Scenario", choice_options,
                index=choice_options.index(active["choice"]),
                key="supply_scenario_draft_choice",
            )
        with control_cols[1]:
            selected_horizon = st.selectbox(
                "Time horizon", [30, 60, 90],
                format_func=lambda value: f"{value} days",
                index=[30, 60, 90].index(int(active.get("horizon", 90))),
                key="supply_scenario_draft_horizon",
            )
        with control_cols[2]:
            run_scenario = st.form_submit_button(
                "▶  Run new scenario", type="primary", use_container_width=True
            )
        with st.expander("Scenario assumptions", expanded=False):
            custom_assumptions = st.checkbox(
                "Customize the preset assumptions",
                value=bool(active.get("customize", False)),
                key="supply_scenario_draft_customize",
            )
            assumption_cols = st.columns(4)
            with assumption_cols[0]:
                build_quantity = st.number_input(
                    "Planned builds per BOM", min_value=1, max_value=1_000_000,
                    value=max(1, int(active.get("build_quantity", 1))), step=1,
                    key="supply_scenario_draft_build_quantity",
                )
            with assumption_cols[1]:
                stock_reduction = st.slider(
                    "Stock reduction", 0, 100,
                    int(active.get("stock_reduction", active_defaults[0])), step=5,
                    key="supply_scenario_draft_stock_reduction",
                )
            with assumption_cols[2]:
                supplier_loss = st.number_input(
                    "Suppliers lost", 0, 10,
                    int(active.get("supplier_loss", active_defaults[1])), step=1,
                    key="supply_scenario_draft_supplier_loss",
                )
            with assumption_cols[3]:
                demand_growth = st.slider(
                    "Demand growth", 0, 300,
                    int(active.get("demand_growth", active_defaults[2])), step=5,
                    key="supply_scenario_draft_demand_growth",
                )
            lifecycle_event = st.checkbox(
                "Include a lifecycle disruption",
                value=bool(active.get("lifecycle_event", active_defaults[3])),
                key="supply_scenario_draft_lifecycle_event",
            )

    if run_scenario:
        selected_defaults = presets[selected_choice]
        st.session_state["supply_scenario_active"] = {
            "choice": selected_choice,
            "horizon": int(selected_horizon),
            "build_quantity": max(1, int(build_quantity)),
            "customize": bool(custom_assumptions),
            "stock_reduction": int(stock_reduction) if custom_assumptions else selected_defaults[0],
            "supplier_loss": int(supplier_loss) if custom_assumptions else selected_defaults[1],
            "demand_growth": int(demand_growth) if custom_assumptions else selected_defaults[2],
            "lifecycle_event": bool(lifecycle_event) if custom_assumptions else selected_defaults[3],
        }
        st.session_state["supply_scenario_last_run"] = selected_choice
        st.rerun()

    active = st.session_state.get("supply_scenario_active") or active
    selected_choice = active["choice"]
    stock_reduction, supplier_loss, demand_growth, lifecycle_event = presets[selected_choice]
    if active.get("customize"):
        stock_reduction = int(active.get("stock_reduction", stock_reduction))
        supplier_loss = int(active.get("supplier_loss", supplier_loss))
        demand_growth = int(active.get("demand_growth", demand_growth))
        lifecycle_event = bool(active.get("lifecycle_event", lifecycle_event))
    intelligence = build_supply_scenario(
        analyses, parts,
        build_quantity=max(1, int(active.get("build_quantity", 1))),
        stock_reduction_percent=stock_reduction,
        supplier_loss=supplier_loss,
        demand_growth_percent=demand_growth,
        include_lifecycle_event=lifecycle_event,
    )
    horizon = int(active.get("horizon", 90))

    def _metric(value: Any, empty: str = "—") -> str:
        if value is None:
            return empty
        return f"{int(value):,}" if float(value).is_integer() else f"{float(value):,.1f}"

    lead_time_metric = intelligence.get("lead_time_increase_weeks")
    lead_time_value = (
        f"+{lead_time_metric:g} weeks" if lead_time_metric is not None else "—"
    )
    gap_note = (
        f"across {intelligence['shortage_components']:,} component records"
        if intelligence["shortage_components"]
        else "No recorded stock shortfall under these assumptions"
    )
    lead_note = (
        f"Based on {intelligence['lead_time_evidence_count']:,} recorded change(s)"
        if intelligence["lead_time_evidence_count"]
        else "No disruption lead-time change is recorded"
    )
    st.markdown(
        f"""
        <section class="cv-sr-kpis">
          <article class="cv-sr-kpi"><span class="cv-sr-kpi-icon">▣</span><div><div class="cv-sr-kpi-label">Exposed components</div><div class="cv-sr-kpi-value">{intelligence['exposed_components']:,}</div><div class="cv-sr-kpi-note">Components with a recorded modeled exception</div></div></article>
          <article class="cv-sr-kpi"><span class="cv-sr-kpi-icon">◇</span><div><div class="cv-sr-kpi-label">Projected stock gap</div><div class="cv-sr-kpi-value">{_metric(intelligence['projected_stock_gap'])} units</div><div class="cv-sr-kpi-note">{html.escape(gap_note)}</div></div></article>
          <article class="cv-sr-kpi"><span class="cv-sr-kpi-icon">◷</span><div><div class="cv-sr-kpi-label">Lead-time increase</div><div class="cv-sr-kpi-value">{html.escape(lead_time_value)}</div><div class="cv-sr-kpi-note">{html.escape(lead_note)}</div></div></article>
          <article class="cv-sr-kpi"><span class="cv-sr-kpi-icon">▤</span><div><div class="cv-sr-kpi-label">BOMs affected</div><div class="cv-sr-kpi-value">{intelligence['affected_projects']:,}</div><div class="cv-sr-kpi-note">of {len(analyses):,} saved BOMs in this workspace</div></div></article>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if intelligence["unknown_stock_components"] or (
        supplier_loss > 0 and intelligence["unknown_source_components"]
    ):
        missing_notes = []
        if intelligence["unknown_stock_components"]:
            missing_notes.append(
                f"{intelligence['unknown_stock_components']:,} of {intelligence['component_count']:,} unique components have no recorded stock snapshot"
            )
        if supplier_loss > 0 and intelligence["unknown_source_components"]:
            missing_notes.append(
                f"supplier-loss impact is unavailable for {intelligence['unknown_source_components']:,} component(s) without a recorded source count"
            )
        st.info(
            "Scenario coverage: " + "; ".join(missing_notes) + ". Results below include only recorded evidence."
        )

    stock_total = intelligence.get("recorded_stock_total")
    scenario_stock = intelligence.get("scenario_stock_total")
    demand_total = intelligence.get("required_units_known_stock_total")
    if not intelligence["known_stock_components"]:
        chart_markup = (
            '<div class="cv-sr-panel"><h2>Projected supply vs. demand</h2>'
            f'<p class="cv-sr-panel-sub">Total across saved BOMs · {horizon}-day horizon</p>'
            '<div style="min-height:205px;display:grid;place-items:center;color:#74839a;text-align:center">'
            '<div><strong style="display:block;color:#36465d;margin-bottom:5px">Stock evidence is not available</strong>'
            'Supplier stock counts are required to plot supply. Add verified stock data to the saved BOM to model this chart.</div></div></div>'
        )
    else:
        maximum = max(float(stock_total or 0), float(scenario_stock or 0), float(demand_total or 0), 1.0)
        chart_w, chart_h = 700, 242
        plot_left, plot_top, plot_w, plot_h = 54, 26, 606, 170
        mid = horizon / 2
        labels = [f"Day 0", f"Day {int(mid)}", f"Day {horizon}"]
        x_points = [plot_left, plot_left + plot_w / 2, plot_left + plot_w]
        def _xy(value: float) -> float:
            return plot_top + plot_h - (value / maximum * plot_h)
        base_y = _xy(float(stock_total or 0))
        scenario_y = _xy(float(scenario_stock or 0))
        demand_y = _xy(float(demand_total or 0))
        baseline_points = f"{x_points[0]},{base_y:.1f} {x_points[1]},{base_y:.1f} {x_points[2]},{base_y:.1f}"
        disrupted_points = f"{x_points[0]},{base_y:.1f} {x_points[1]},{base_y:.1f} {x_points[2]},{scenario_y:.1f}"
        demand_points = f"{x_points[0]},{demand_y:.1f} {x_points[1]},{demand_y:.1f} {x_points[2]},{demand_y:.1f}"
        grid = []
        for fraction in (0, .5, 1):
            y = plot_top + plot_h * (1 - fraction)
            label = int(maximum * fraction)
            grid.append(f'<line x1="{plot_left}" y1="{y:.1f}" x2="{plot_left+plot_w}" y2="{y:.1f}" stroke="#e7edf4"/>')
            grid.append(f'<text x="{plot_left-8}" y="{y+4:.1f}" text-anchor="end" fill="#7b8ba2" font-size="11">{label:,}</text>')
        tick_markup = "".join(
            f'<text x="{x}" y="220" text-anchor="middle" fill="#73829a" font-size="11">{label}</text>'
            for x, label in zip(x_points, labels)
        )
        chart_markup = (
            '<div class="cv-sr-panel"><h2>Projected supply vs. demand</h2>'
            f'<p class="cv-sr-panel-sub">Total across components with recorded stock · {horizon}-day horizon</p>'
            f'<svg class="cv-sr-chart" viewBox="0 0 {chart_w} {chart_h}" role="img" aria-label="Modeled supply and demand over {horizon} days">'
            f'{"".join(grid)}<line x1="{plot_left+plot_w/2}" y1="{plot_top}" x2="{plot_left+plot_w/2}" y2="{plot_top+plot_h}" stroke="#aab8c9" stroke-dasharray="4 4"/>'
            f'<polyline points="{baseline_points}" fill="none" stroke="#2670e8" stroke-width="3"/>'
            f'<polyline points="{disrupted_points}" fill="none" stroke="#e34f55" stroke-width="3" stroke-dasharray="7 5"/>'
            f'<polyline points="{demand_points}" fill="none" stroke="#64748b" stroke-width="2.5" stroke-dasharray="4 5"/>'
            f'{tick_markup}</svg>'
            '<div class="cv-sr-legend"><span><i class="cv-sr-swatch"></i>Baseline supply</span>'
            '<span><i class="cv-sr-swatch disrupted"></i>Disrupted supply</span>'
            '<span><i class="cv-sr-swatch demand"></i>Demand (forecast)</span></div>'
            '<p class="cv-sr-note">Modeled from saved BOM demand and the lowest recorded supplier-stock snapshot for each unique part number. Stock coverage assumes planned builds are spread evenly across the selected horizon. Supplier stock is a catalog snapshot, not inventory owned by the workspace; shared parts are counted once.</p></div>'
        )

    impacted_rows = intelligence["impacted"][:5]
    if impacted_rows:
        table_rows = []
        for row in impacted_rows:
            if row["Stock Recorded"] and row["Required Units"] > 0:
                coverage_days = row["Original Stock"] / row["Required Units"] * horizon
                current_stock = f"{coverage_days:,.1f} days"
            else:
                current_stock = "Not recorded" if not row["Stock Recorded"] else "—"
            gap = row["Shortage Units"]
            gap_cell = f'<span class="cv-sr-gap">{gap:,}</span>' if gap is not None and gap > 0 else "—"
            lead_delta = row["Lead Time Increase Weeks"]
            lead_cell = f"+{lead_delta:g} wks" if lead_delta is not None else "—"
            part_label = html.escape(row["Part Number"])
            project_label = html.escape(row["Project"])
            table_rows.append(
                f'<tr><td><strong>{part_label}</strong><small>{project_label}</small></td>'
                f'<td>{current_stock}</td><td>{gap_cell}</td><td>{lead_cell}</td></tr>'
            )
        top_table = (
            '<div class="cv-sr-panel"><h2>Top affected components</h2>'
            '<p class="cv-sr-panel-sub">Ranked by shortage, source loss, and recorded lifecycle status.</p>'
            '<div style="overflow-x:auto"><table class="cv-sr-table"><thead><tr>'
            '<th>Component</th><th>Current stock (days)</th><th>Projected gap</th><th>Lead-time change</th>'
            f'</tr></thead><tbody>{"".join(table_rows)}</tbody></table></div></div>'
        )
    else:
        top_table = (
            '<div class="cv-sr-panel"><h2>Top affected components</h2>'
            '<p class="cv-sr-panel-sub">No component has a recorded exception under the selected assumptions.</p>'
            '<div style="min-height:170px;display:grid;place-items:center;color:#74839a">No modeled impact to display.</div></div>'
        )
    st.markdown(
        f'<section class="cv-sr-grid">{chart_markup}{top_table}</section>',
        unsafe_allow_html=True,
    )

    # The generated actions are derived from current saved BOM evidence; status
    # edits and custom action drafts remain local to the user session.
    actions: List[Dict[str, Any]] = []
    for row in intelligence["impacted"][:8]:
        if (row["Shortage Units"] or 0) > 0:
            action_type = "Inventory"
            title = "Secure additional stock"
            impact = f"Cover {row['Shortage Units']:,}-unit gap"
            effort = "Medium"
        elif row["Lifecycle Event"]:
            action_type = "Replacement"
            title = "Qualify a replacement"
            impact = "Reduce lifecycle exposure"
            effort = "High"
        elif row["Sources Recorded"] and (row["Scenario Sources"] or 0) <= 1:
            action_type = "Alternative supply"
            title = "Qualify alternate supplier"
            impact = "Add sourcing coverage"
            effort = "Medium"
        else:
            action_type = "Engineering review"
            title = "Review component risk"
            impact = "Confirm mitigation path"
            effort = "Medium"
        actions.append({
            "id": f"generated:{row['Analysis ID']}:{row['Part Number']}:{action_type}",
            "Action": title,
            "Type": action_type,
            "Component": row["Part Number"],
            "Project": row["Project"],
            "Expected impact": impact,
            "Effort": effort,
            "Analysis ID": row["Analysis ID"],
        })
    custom_actions = st.session_state.get("supply_scenario_custom_actions") or []
    if isinstance(custom_actions, list):
        actions.extend(custom_actions)

    heading_cols = st.columns([5, 1], vertical_alignment="center")
    with heading_cols[0]:
        st.markdown(
            '<div class="cv-sr-section-head"><div><h2>Mitigation actions</h2>'
            '<p>Recommended actions to reduce impact and improve supply resilience.</p></div></div>',
            unsafe_allow_html=True,
        )
    with heading_cols[1]:
        if st.button("＋ Add action", key="supply_scenario_add_action_toggle", use_container_width=True):
            st.session_state["supply_scenario_add_action_open"] = not bool(
                st.session_state.get("supply_scenario_add_action_open")
            )

    if st.session_state.get("supply_scenario_add_action_open"):
        with st.form("supply_scenario_add_action_form"):
            action_cols = st.columns([1.5, 1.2, 1, .8])
            with action_cols[0]:
                new_action_title = st.text_input("Action", placeholder="e.g. Expedite open purchase order")
            with action_cols[1]:
                component_options = [
                    f"{row['Part Number']} — {row['Project']}" for row in intelligence["rows"]
                ] or ["No saved components"]
                new_action_target = st.selectbox("Target component", component_options)
            with action_cols[2]:
                new_action_type = st.selectbox("Type", ["Inventory", "Alternative supply", "Logistics", "Engineering review"])
            with action_cols[3]:
                new_action_effort = st.selectbox("Effort", ["Low", "Medium", "High"])
            submit_action = st.form_submit_button("Save action", type="primary")
        if submit_action:
            if not new_action_title.strip():
                st.error("Enter an action before saving it.")
            elif component_options == ["No saved components"]:
                st.error("A saved BOM component is required for this action.")
            else:
                selected_part, _, selected_project = new_action_target.partition(" — ")
                matched = next(
                    (row for row in intelligence["rows"] if row["Part Number"] == selected_part and row["Project"] == selected_project),
                    {},
                )
                current_actions = list(st.session_state.get("supply_scenario_custom_actions") or [])
                current_actions.append({
                    "id": f"custom:{len(current_actions)+1}:{selected_part}",
                    "Action": new_action_title.strip(),
                    "Type": new_action_type,
                    "Component": selected_part,
                    "Project": selected_project,
                    "Expected impact": "User-defined mitigation action",
                    "Effort": new_action_effort,
                    "Analysis ID": matched.get("Analysis ID", ""),
                })
                st.session_state["supply_scenario_custom_actions"] = current_actions
                st.session_state["supply_scenario_add_action_open"] = False
                st.rerun()

    action_header = (
        '<div class="cv-sr-actions"><div class="cv-sr-action-head">'
        '<span>Action</span><span>Type</span><span>Target components</span>'
        '<span>Expected impact</span><span>Effort</span><span>Status</span>'
        '<span>Next step</span></div></div>'
    )
    if not actions:
        st.info("No mitigation actions are suggested because the selected scenario has no recorded component exceptions.")
    else:
        st.markdown(action_header, unsafe_allow_html=True)
        for index, action in enumerate(actions):
            identifier = str(action["id"])
            state_key = "supply_scenario_action_status_" + hashlib.sha1(
                identifier.encode("utf-8")
            ).hexdigest()[:12]
            status_options = ["Not started", "Planned", "In progress", "Complete"]
            current_status = str(st.session_state.get(state_key) or "Planned")
            if current_status not in status_options:
                current_status = "Planned"
            with st.container(key=f"cv_sr_action_row_{index}"):
                row_cols = st.columns([1.45, .95, 1.2, 1.3, .58, .9, 1])
                with row_cols[0]:
                    st.markdown(f"<strong>{html.escape(action['Action'])}</strong>", unsafe_allow_html=True)
                with row_cols[1]:
                    st.markdown(f'<span class="cv-sr-tag">{html.escape(action["Type"])}</span>', unsafe_allow_html=True)
                with row_cols[2]:
                    st.markdown(f"{html.escape(action['Component'])}<small>{html.escape(action['Project'])}</small>", unsafe_allow_html=True)
                with row_cols[3]:
                    st.markdown(html.escape(action["Expected impact"]), unsafe_allow_html=True)
                with row_cols[4]:
                    st.markdown(html.escape(action["Effort"]), unsafe_allow_html=True)
                with row_cols[5]:
                    st.selectbox(
                        "Status", status_options, index=status_options.index(current_status),
                        key=state_key, label_visibility="collapsed",
                    )
                with row_cols[6]:
                    target_route = "Alternative Finder" if action["Type"] in {"Alternative supply", "Replacement"} else "Monitoring"
                    internal_nav_button(
                        "Review →", target_route,
                        key=f"supply_scenario_action_review_{index}",
                        type="tertiary", use_container_width=True,
                        **({"original_part": action["Component"], "source_page": "supply_risk_scenario"} if target_route == "Alternative Finder" else {}),
                    )
    st.caption("Action status and custom mitigation drafts are saved for this browser session. Recording an approved change remains part of the BOM review workflow.")
