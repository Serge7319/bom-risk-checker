"""Cadivor Milestone 22.0 — Supply Risk Scenario Planner.

Provides what-if analysis for stock loss, supplier loss, lifecycle exposure,
and demand growth across saved BOM records.
"""
from __future__ import annotations

from collections import defaultdict
import html
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd
import streamlit as st


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
    for row in parts:
        analysis_id = _text(row.get("analysis_id"))
        qty = max(1, int(_number(_first(row, "quantity", "qty", "required_quantity"), 1)))
        stock = max(0, int(_number(_first(row, "stock_available", "stock"), 0)))
        suppliers = max(0, int(_number(row.get("supplier_count"), 0)))
        unit_price = max(
            0.0,
            _number(
                _first(row, "unit_price", "price", "best_price", "estimated_unit_price"),
                0,
            ),
        )
        lifecycle = _text(row.get("lifecycle_status"), "Unknown")
        risk_score = int(_number(row.get("risk_score"), 0))

        adjusted_stock = max(
            0,
            int(round(stock * (1 - max(0, min(100, stock_reduction_percent)) / 100))),
        )
        adjusted_suppliers = max(0, suppliers - max(0, supplier_loss))
        adjusted_quantity = max(
            1,
            int(round(qty * max(1, build_quantity) * (1 + max(0, demand_growth_percent) / 100))),
        )
        shortage = max(0, adjusted_quantity - adjusted_stock)

        lifecycle_exposed = any(
            term in lifecycle.lower()
            for term in ("obsolete", "replacement", "nrnd", "not recommended", "eol")
        )
        if include_lifecycle_event and risk_score >= 40:
            lifecycle_exposed = True

        scenario_score = risk_score
        if shortage > 0:
            scenario_score += 35
        elif adjusted_stock < adjusted_quantity * 2:
            scenario_score += 15
        if adjusted_suppliers <= 0:
            scenario_score += 30
        elif adjusted_suppliers == 1:
            scenario_score += 15
        if lifecycle_exposed:
            scenario_score += 20
        scenario_score = min(100, scenario_score)

        normalized.append(
            {
                "Analysis ID": analysis_id,
                "Project": analysis_lookup.get(analysis_id, {}).get(
                    "Project", _text(row.get("project_name"), "Saved BOM")
                ),
                "Project Health": analysis_lookup.get(analysis_id, {}).get("Health", 0),
                "Part Number": _text(_first(row, "mpn", "MPN", "part_number"), "Unknown"),
                "Manufacturer": _text(row.get("manufacturer"), "Unknown"),
                "Lifecycle": lifecycle,
                "Original Stock": stock,
                "Scenario Stock": adjusted_stock,
                "Original Sources": suppliers,
                "Scenario Sources": adjusted_suppliers,
                "Required Units": adjusted_quantity,
                "Shortage Units": shortage,
                "Unit Price": unit_price,
                "Estimated Shortage Value": shortage * unit_price,
                "Current Risk": risk_score,
                "Scenario Risk": scenario_score,
                "Lifecycle Event": lifecycle_exposed,
            }
        )

    impacted = [
        row for row in normalized
        if row["Shortage Units"] > 0
        or row["Scenario Sources"] <= 1
        or row["Lifecycle Event"]
        or row["Scenario Risk"] >= 60
    ]
    impacted.sort(
        key=lambda row: (
            -row["Scenario Risk"],
            -row["Shortage Units"],
            row["Project Health"],
        )
    )

    project_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        project_rows[row["Project"]].append(row)

    project_impact = []
    for project, rows in project_rows.items():
        shortage_parts = sum(1 for row in rows if row["Shortage Units"] > 0)
        single_source = sum(1 for row in rows if row["Scenario Sources"] <= 1)
        lifecycle_parts = sum(1 for row in rows if row["Lifecycle Event"])
        max_risk = max((row["Scenario Risk"] for row in rows), default=0)
        shortage_value = sum(row["Estimated Shortage Value"] for row in rows)
        project_impact.append(
            {
                "Project": project,
                "Impacted Components": sum(
                    1 for row in rows
                    if row["Scenario Risk"] >= 60
                    or row["Shortage Units"] > 0
                    or row["Scenario Sources"] <= 1
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
            -row["Highest Scenario Risk"],
            -row["Impacted Components"],
        )
    )

    shortage_components = sum(1 for row in normalized if row["Shortage Units"] > 0)
    single_source_components = sum(1 for row in normalized if row["Scenario Sources"] <= 1)
    lifecycle_components = sum(1 for row in normalized if row["Lifecycle Event"])
    critical_components = sum(1 for row in normalized if row["Scenario Risk"] >= 80)
    shortage_value = sum(row["Estimated Shortage Value"] for row in normalized)
    affected_projects = sum(1 for row in project_impact if row["Impacted Components"] > 0)

    recommendations = []
    if impacted:
        top = impacted[0]
        if top["Shortage Units"] > 0:
            recommendations.append(
                f"Resolve the projected shortage for {top['Part Number']} first: "
                f"{top['Shortage Units']:,} unit(s) are uncovered in this scenario."
            )
        elif top["Scenario Sources"] <= 1:
            recommendations.append(
                f"Add another authorized source for {top['Part Number']} before the scenario occurs."
            )
        elif top["Lifecycle Event"]:
            recommendations.append(
                f"Begin replacement qualification for {top['Part Number']} across every affected project."
            )
    if shortage_components:
        recommendations.append(
            f"Secure inventory or approved substitutes for {shortage_components} component record(s) with projected shortages."
        )
    if single_source_components:
        recommendations.append(
            f"Increase sourcing coverage for {single_source_components} component record(s) with one or fewer remaining sources."
        )
    if lifecycle_components:
        recommendations.append(
            f"Prepare replacement plans for {lifecycle_components} lifecycle-exposed component record(s)."
        )
    if not recommendations:
        recommendations.append(
            "The selected scenario does not create a major recorded supply or lifecycle exception."
        )

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
        "recommendations": recommendations[:5],
        "component_count": len(normalized),
    }


def _css() -> None:
    st.markdown(
        """
        <style id="cadivor-scenario-planner-22">
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
          .cv22-warning{
            border:1px solid #fecaca;background:#fff1f2;border-radius:18px;padding:18px
          }
          .cv22-warning strong{font-size:31px;color:#b91c1c;letter-spacing:-.04em}
          .cv22-warning span{display:block;font-size:12px;font-weight:800;color:#be123c;margin-top:3px}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_supply_scenario(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
) -> None:
    _css()

    st.markdown(
        """
        <section class="cv22-hero">
          <div class="cv22-eyebrow">Supply Continuity Intelligence</div>
          <div class="cv22-title">Supply Risk Scenario Planner</div>
          <div class="cv22-copy">
            Test how demand growth, stock loss, supplier loss, or a lifecycle event could affect
            saved projects before the disruption occurs. Cadivor converts the scenario into
            prioritized engineering and procurement actions.
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Affected Projects", intelligence["affected_projects"])
    k2.metric("Projected Shortages", intelligence["shortage_components"])
    k3.metric("Single-Source Exposure", intelligence["single_source_components"])
    k4.metric("Lifecycle Exposure", intelligence["lifecycle_components"])
    k5.metric("Critical Components", intelligence["critical_components"])

    left, right = st.columns([1.4, 1])

    with left:
        st.markdown(
            '<div class="cv22-section">Highest-Impact Components</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="cv22-subtitle">Components are ranked by projected scenario risk and shortage exposure.</div>',
            unsafe_allow_html=True,
        )

        if not intelligence["impacted"]:
            st.success("No material component impact is identified under this scenario.")

        for index, row in enumerate(intelligence["impacted"][:6]):
            action = (
                "Resolve projected shortage"
                if row["Shortage Units"] > 0
                else "Add sourcing coverage"
                if row["Scenario Sources"] <= 1
                else "Prepare replacement plan"
                if row["Lifecycle Event"]
                else "Review component risk"
            )
            st.markdown(
                f"""
                <section class="cv22-card">
                  <div class="cv22-card-title">{html.escape(row['Part Number'])}</div>
                  <div class="cv22-card-copy">
                    {html.escape(row['Project'])} · {html.escape(action)}
                  </div>
                  <div class="cv22-meta">
                    <span>Scenario risk {row['Scenario Risk']}/100</span>
                    <span>Required {row['Required Units']:,}</span>
                    <span>Stock {row['Scenario Stock']:,}</span>
                    <span>Shortage {row['Shortage Units']:,}</span>
                    <span>{row['Scenario Sources']} source(s)</span>
                    <span>{html.escape(row['Lifecycle'])}</span>
                  </div>
                </section>
                """,
                unsafe_allow_html=True,
            )
            actions = st.columns(2)
            with actions[0]:
                internal_nav_button(
                    "Find Alternative",
                    "Alternative Finder",
                    key=f"scenario_alt_{index}",
                    use_container_width=True,
                    original_part=row["Part Number"],
                )
            with actions[1]:
                internal_nav_button(
                    "Open Monitoring",
                    "Monitoring",
                    key=f"scenario_monitor_{index}",
                    use_container_width=True,
                )

    with right:
        st.markdown(
            '<div class="cv22-section">Scenario Exposure</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <section class="cv22-warning">
              <strong>${intelligence['shortage_value']:,.2f}</strong>
              <span>Estimated value of uncovered demand using recorded unit prices</span>
            </section>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="cv22-section">Recommended Response</div>',
            unsafe_allow_html=True,
        )
        for recommendation in intelligence["recommendations"]:
            st.markdown(
                f'<div class="cv22-recommendation">✓ {html.escape(recommendation)}</div>',
                unsafe_allow_html=True,
            )

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
        st.dataframe(
            project_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Estimated Shortage Value": st.column_config.NumberColumn(format="$%.2f"),
            },
        )

    shortage_tab, sourcing_tab, lifecycle_tab, all_tab = st.tabs(
        ["Projected Shortages", "Supplier Exposure", "Lifecycle Exposure", "All Scenario Records"]
    )

    with shortage_tab:
        rows = [row for row in intelligence["rows"] if row["Shortage Units"] > 0]
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df[
                    [
                        "Project",
                        "Part Number",
                        "Manufacturer",
                        "Required Units",
                        "Scenario Stock",
                        "Shortage Units",
                        "Estimated Shortage Value",
                        "Scenario Risk",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Estimated Shortage Value": st.column_config.NumberColumn(format="$%.2f"),
                },
            )
        else:
            st.success("No projected component shortage is identified.")

    with sourcing_tab:
        rows = [row for row in intelligence["rows"] if row["Scenario Sources"] <= 1]
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df[
                    [
                        "Project",
                        "Part Number",
                        "Manufacturer",
                        "Original Sources",
                        "Scenario Sources",
                        "Scenario Stock",
                        "Scenario Risk",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("Every recorded component retains more than one source.")

    with lifecycle_tab:
        rows = [row for row in intelligence["rows"] if row["Lifecycle Event"]]
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df[
                    [
                        "Project",
                        "Part Number",
                        "Manufacturer",
                        "Lifecycle",
                        "Scenario Risk",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("No lifecycle exposure is modeled in this scenario.")

    with all_tab:
        if intelligence["rows"]:
            st.dataframe(
                pd.DataFrame(intelligence["rows"])[
                    [
                        "Project",
                        "Part Number",
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
                hide_index=True,
                use_container_width=True,
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
