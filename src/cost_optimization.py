"""Cadivor Milestone 21.0 — Cost Optimization.

Uses saved BOM component records to identify priced spend, purchasing
leverage, missing cost data, and estimated cost-reduction opportunities.
No database migration is required.
"""
from __future__ import annotations

from collections import defaultdict
import html
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system import cadivor_engineering_dataframe


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


def build_cost_optimization(
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    build_quantity: int = 100,
) -> Dict[str, Any]:
    analyses = list(analyses or [])
    parts = list(parts or [])

    analysis_lookup = {
        _text(row.get("id")): _text(
            row.get("project_name") or row.get("name") or row.get("filename"),
            "Saved BOM",
        )
        for row in analyses
    }

    normalized: List[Dict[str, Any]] = []
    for row in parts:
        analysis_id = _text(row.get("analysis_id"))
        qty = max(1, int(_number(_first(row, "quantity", "qty", "required_quantity"), 1)))
        unit_price = max(
            0.0,
            _number(
                _first(
                    row,
                    "unit_price",
                    "price",
                    "best_price",
                    "estimated_unit_price",
                    default=0,
                ),
                0,
            ),
        )
        suppliers = int(_number(row.get("supplier_count"), 0))
        stock = int(_number(_first(row, "stock_available", "stock"), 0))
        risk_score = int(_number(row.get("risk_score"), 0))
        normalized.append(
            {
                "Analysis ID": analysis_id,
                "Project": analysis_lookup.get(
                    analysis_id,
                    _text(row.get("project_name"), "Saved BOM"),
                ),
                "Part Number": _text(
                    _first(row, "mpn", "MPN", "part_number"),
                    "Unknown",
                ),
                "Manufacturer": _text(row.get("manufacturer"), "Unknown"),
                "Supplier": _text(
                    _first(row, "primary_supplier", "supplier", "best_source"),
                    "Not recorded",
                ),
                "Quantity per Build": qty,
                "Unit Price": unit_price,
                "Extended Cost per Build": qty * unit_price,
                "Supplier Sources": suppliers,
                "Available Stock": stock,
                "Lifecycle": _text(row.get("lifecycle_status"), "Unknown"),
                "Risk Score": risk_score,
            }
        )

    priced = [row for row in normalized if row["Unit Price"] > 0]
    missing_price = [row for row in normalized if row["Unit Price"] <= 0]

    current_cost_per_build = sum(row["Extended Cost per Build"] for row in priced)
    production_run_cost = current_cost_per_build * max(1, build_quantity)
    pricing_coverage = (
        round((len(priced) / max(1, len(normalized))) * 100)
        if normalized else 0
    )

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        grouped[row["Part Number"].upper()].append(row)

    opportunities: List[Dict[str, Any]] = []
    for _, rows in grouped.items():
        reference = rows[0]
        unit_price = max(row["Unit Price"] for row in rows)
        if unit_price <= 0:
            continue

        project_count = len({row["Project"] for row in rows})
        total_qty_per_build = sum(row["Quantity per Build"] for row in rows)
        suppliers = min(row["Supplier Sources"] for row in rows)
        risk_score = max(row["Risk Score"] for row in rows)
        stock = min(row["Available Stock"] for row in rows)

        savings_rate = 0.0
        reason = ""
        category = ""

        if project_count >= 2 and total_qty_per_build >= 2:
            savings_rate = 0.08
            category = "Volume Consolidation"
            reason = (
                f"Used across {project_count} projects. Consolidated purchasing may improve "
                "pricing leverage."
            )
        elif suppliers >= 2:
            savings_rate = 0.05
            category = "Supplier Competition"
            reason = (
                f"{suppliers} supplier sources are recorded. Competitive quoting may reduce cost."
            )
        elif total_qty_per_build >= 10:
            savings_rate = 0.06
            category = "Quantity Break"
            reason = (
                f"{total_qty_per_build} units are required across the recorded build set. "
                "Review distributor price breaks."
            )

        if savings_rate <= 0:
            continue

        current_run_cost = unit_price * total_qty_per_build * max(1, build_quantity)
        estimated_savings = current_run_cost * savings_rate
        opportunities.append(
            {
                "Part Number": reference["Part Number"],
                "Manufacturer": reference["Manufacturer"],
                "Category": category,
                "Projects": project_count,
                "Units per Build": total_qty_per_build,
                "Current Unit Price": unit_price,
                "Estimated Target Price": unit_price * (1 - savings_rate),
                "Estimated Run Savings": estimated_savings,
                "Savings Rate": savings_rate,
                "Supplier Sources": suppliers,
                "Lowest Stock": stock,
                "Risk Score": risk_score,
                "Reason": reason,
            }
        )

    opportunities.sort(
        key=lambda row: (-row["Estimated Run Savings"], -row["Risk Score"])
    )

    estimated_savings = sum(
        row["Estimated Run Savings"] for row in opportunities
    )
    estimated_optimized_cost = max(0.0, production_run_cost - estimated_savings)

    top_cost_parts = sorted(
        priced,
        key=lambda row: -row["Extended Cost per Build"],
    )[:10]

    sourcing_risk_cost = sum(
        row["Extended Cost per Build"] * max(1, build_quantity)
        for row in priced
        if row["Supplier Sources"] <= 1 or row["Available Stock"] <= 0
    )

    recommendations = []
    if opportunities:
        top = opportunities[0]
        recommendations.append(
            f"Start with {top['Part Number']}: the estimated production-run savings opportunity "
            f"is ${top['Estimated Run Savings']:,.2f}."
        )
    if missing_price:
        recommendations.append(
            f"Add current pricing for {len(missing_price)} component record(s) to improve "
            "cost-analysis coverage."
        )
    if sourcing_risk_cost > 0:
        recommendations.append(
            f"${sourcing_risk_cost:,.2f} of modeled production-run spend is attached to "
            "single-source or no-stock records."
        )
    if not recommendations:
        recommendations.append(
            "No clear cost-reduction opportunity is available from the currently recorded pricing."
        )

    return {
        "rows": normalized,
        "priced_rows": priced,
        "missing_price_rows": missing_price,
        "opportunities": opportunities,
        "top_cost_parts": top_cost_parts,
        "build_quantity": max(1, build_quantity),
        "current_cost_per_build": current_cost_per_build,
        "production_run_cost": production_run_cost,
        "estimated_savings": estimated_savings,
        "estimated_optimized_cost": estimated_optimized_cost,
        "pricing_coverage": pricing_coverage,
        "sourcing_risk_cost": sourcing_risk_cost,
        "recommendations": recommendations[:4],
        "project_count": len(analyses),
        "component_count": len(normalized),
    }


def _css() -> None:
    st.markdown(
        """
        <style id="cadivor-cost-optimization-21">
          .cv21-hero{
            border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eef5ff);
            border-radius:24px;padding:25px;margin-bottom:18px;
            box-shadow:0 16px 42px rgba(37,99,235,.07)
          }
          .cv21-eyebrow{font-size:11px;font-weight:900;color:#2563eb;letter-spacing:.11em;text-transform:uppercase}
          .cv21-title{font-size:30px;font-weight:950;color:#0f172a;letter-spacing:-.045em;margin:7px 0}
          .cv21-copy{font-size:14px;font-weight:680;color:#52647a;line-height:1.58;max-width:1080px}
          .cv21-note{
            border:1px solid #fde68a;background:#fffbeb;border-radius:14px;
            padding:12px 14px;margin:12px 0 18px;font-size:12px;font-weight:680;
            color:#92400e;line-height:1.5
          }
          .cv21-section{font-size:22px;font-weight:950;color:#0f172a;letter-spacing:-.03em;margin:22px 0 5px}
          .cv21-subtitle{font-size:13px;font-weight:650;color:#64748b;margin-bottom:12px}
          .cv21-card{
            border:1px solid #dbe3ef;background:#fff;border-radius:17px;padding:17px;
            margin-bottom:11px;box-shadow:0 8px 24px rgba(15,23,42,.04)
          }
          .cv21-card-title{font-size:16px;font-weight:950;color:#0f172a}
          .cv21-card-copy{font-size:13px;font-weight:680;color:#475569;line-height:1.52;margin-top:6px}
          .cv21-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}
          .cv21-meta span{
            font-size:10px;font-weight:850;color:#1d4ed8;background:#eff6ff;
            border:1px solid #dbeafe;border-radius:999px;padding:5px 8px
          }
          .cv21-kpi-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:18px 0 24px}
          .cv21-kpi{border:1px solid #dbe3ef;background:#fff;border-radius:18px;padding:16px 17px;box-shadow:0 8px 24px rgba(15,23,42,.04);min-height:104px}
          .cv21-kpi-label{font-size:12px;font-weight:850;color:#64748b;line-height:1.25}
          .cv21-kpi-value{font-size:30px;font-weight:950;color:#0f172a;letter-spacing:-.04em;margin-top:10px;line-height:1}
          .cv21-kpi-note{font-size:11px;font-weight:700;color:#64748b;margin-top:8px;line-height:1.35}
          .cv21-kpi.good{border-color:#a7f3d0;background:#f0fdf4}.cv21-kpi.good .cv21-kpi-value{color:#047857}
          .cv21-kpi.warn{border-color:#fde68a;background:#fffbeb}.cv21-kpi.warn .cv21-kpi-value{color:#a16207}
          .cv21-primary-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:14px;margin:0 0 24px}
          .cv21-primary-card{border:1px solid #a7f3d0;background:linear-gradient(135deg,#fff,#ecfdf5);border-radius:20px;padding:20px;min-height:148px}
          .cv21-primary-label{font-size:12px;font-weight:900;color:#047857;text-transform:uppercase;letter-spacing:.08em}
          .cv21-primary-value{font-size:38px;font-weight:950;color:#047857;letter-spacing:-.05em;margin-top:12px;line-height:1}
          .cv21-primary-note{font-size:12px;font-weight:760;color:#047857;margin-top:10px;line-height:1.45}
          .cv21-action-card{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f8fbff);border-radius:20px;padding:20px;min-height:148px}
          .cv21-action-title{font-size:18px;font-weight:950;color:#0f172a;letter-spacing:-.025em}
          @media (max-width:1100px){.cv21-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cv21-primary-grid{grid-template-columns:1fr}}
          .cv21-savings{
            border:1px solid #a7f3d0;background:#ecfdf5;border-radius:18px;padding:18px
          }
          .cv21-savings strong{font-size:31px;color:#047857;letter-spacing:-.04em}
          .cv21-savings span{display:block;font-size:12px;font-weight:800;color:#047857;margin-top:3px}
          .cv21-recommendation{
            border-left:4px solid #2563eb;background:#f8fbff;border-radius:0 14px 14px 0;
            padding:14px 16px;margin-bottom:10px;font-size:13px;font-weight:740;
            color:#334155;line-height:1.5
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_cost_optimization(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
) -> None:
    _css()

    st.markdown(
        '<div class="cv21-note">Estimated savings are planning guidance based on recorded prices, '
        'BOM quantities, supplier coverage, and conservative optimization assumptions. Confirm '
        'all pricing with authorized suppliers before making purchasing decisions.</div>',
        unsafe_allow_html=True,
    )

    if intelligence["pricing_coverage"] == 0:
        st.warning(
            "The build quantity is changing correctly, but all modeled values remain $0 because "
            "none of the saved component records currently contains a positive unit price. "
            "Run the SQL migration included with Milestone 21.1, then re-analyze a BOM so Cadivor "
            "can save quantity and supplier pricing. Existing saved BOMs do not automatically gain "
            "historical prices."
        )
    elif intelligence["pricing_coverage"] < 100:
        st.info(
            f"Pricing is available for {intelligence['pricing_coverage']}% of component records. "
            "The production model uses only priced records, so totals are currently partial."
        )
    else:
        st.success(
            "Pricing data is available for every saved component record. "
            "Changing the build quantity will update modeled cost and savings."
        )

    coverage_class = "good" if intelligence["pricing_coverage"] >= 80 else "warn"
    st.markdown(
        f"""<section class="cv21-kpi-grid">
          <div class="cv21-kpi"><div class="cv21-kpi-label">Cost per Build</div><div class="cv21-kpi-value">${intelligence['current_cost_per_build']:,.2f}</div><div class="cv21-kpi-note">Recorded component cost for one modeled build</div></div>
          <div class="cv21-kpi"><div class="cv21-kpi-label">Production Cost</div><div class="cv21-kpi-value">${intelligence['production_run_cost']:,.2f}</div><div class="cv21-kpi-note">{intelligence['build_quantity']:,} build production run</div></div>
          <div class="cv21-kpi good"><div class="cv21-kpi-label">Estimated Savings</div><div class="cv21-kpi-value">${intelligence['estimated_savings']:,.2f}</div><div class="cv21-kpi-note">Modeled opportunity across priced records</div></div>
          <div class="cv21-kpi {coverage_class}"><div class="cv21-kpi-label">Pricing Coverage</div><div class="cv21-kpi-value">{intelligence['pricing_coverage']}%</div><div class="cv21-kpi-note">{len(intelligence['priced_rows'])} of {intelligence['component_count']} records priced</div></div>
          <div class="cv21-kpi"><div class="cv21-kpi-label">Cost Opportunities</div><div class="cv21-kpi-value">{len(intelligence['opportunities'])}</div><div class="cv21-kpi-note">Components with modeled savings potential</div></div>
        </section>""", unsafe_allow_html=True)

    primary_recommendation = (intelligence["recommendations"][0] if intelligence["recommendations"] else "No major cost optimization action is required.")
    st.markdown(
        f"""<section class="cv21-primary-grid">
          <div class="cv21-primary-card"><div class="cv21-primary-label">Modeled Result</div><div class="cv21-primary-value">${intelligence['estimated_optimized_cost']:,.2f}</div><div class="cv21-primary-note">Estimated optimized production-run cost after modeled savings</div></div>
          <div class="cv21-action-card"><div class="cv21-action-title">Recommended Action</div><div class="cv21-card-copy">{html.escape(primary_recommendation)}</div></div>
        </section>""", unsafe_allow_html=True)
    if len(intelligence["recommendations"]) > 1:
        with st.expander(f"View all recommended actions ({len(intelligence['recommendations'])})"):
            for recommendation in intelligence["recommendations"]:
                st.markdown(f'<div class="cv21-recommendation">✓ {html.escape(recommendation)}</div>', unsafe_allow_html=True)
    st.markdown('<div class="cv21-section">Highest-Value Opportunities</div>', unsafe_allow_html=True)
    st.markdown('<div class="cv21-subtitle">Opportunities are ranked by estimated savings for the selected production run.</div>', unsafe_allow_html=True)
    if not intelligence["opportunities"]:
        st.info("No priced component currently meets the volume, supplier, or shared-demand criteria for a modeled savings opportunity.")
    for index,row in enumerate(intelligence["opportunities"][:6]):
        st.markdown(f"""<section class="cv21-card"><div class="cv21-card-title">{html.escape(row['Part Number'])}</div><div class="cv21-card-copy">{html.escape(row['Reason'])}</div><div class="cv21-meta"><span>{html.escape(row['Category'])}</span><span>{row['Projects']} project(s)</span><span>{row['Units per Build']} unit(s)/build</span><span>Current ${row['Current Unit Price']:,.4f}</span><span>Target ${row['Estimated Target Price']:,.4f}</span><span>Est. savings ${row['Estimated Run Savings']:,.2f}</span></div></section>""", unsafe_allow_html=True)
        cols=st.columns(2)
        with cols[0]: internal_nav_button("Review Sourcing","Procurement Advisor",key=f"cost_procurement_{index}",use_container_width=True)
        with cols[1]: internal_nav_button("Find Alternatives","Alternative Finder",key=f"cost_alternative_{index}",use_container_width=True,original_part=row["Part Number"])
    st.markdown('<div class="cv21-section">Cost Data Quality</div>', unsafe_allow_html=True)
    q=st.columns(2)
    with q[0]:
        st.markdown(f"""<section class="cv21-card"><div class="cv21-card-title">{intelligence['pricing_coverage']}% priced</div><div class="cv21-card-copy">{len(intelligence['priced_rows'])} of {intelligence['component_count']} component records contain a positive unit price. {len(intelligence['missing_price_rows'])} record(s) still need pricing.</div></section>""", unsafe_allow_html=True)
    with q[1]:
        st.markdown(f"""<section class="cv21-card"><div class="cv21-card-title">${intelligence['sourcing_risk_cost']:,.2f}</div><div class="cv21-card-copy">Modeled production-run spend attached to single-source or no-stock records.</div></section>""", unsafe_allow_html=True)

    st.markdown(
        '<div class="cv21-section">Highest Recorded Component Costs</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="cv21-subtitle">Extended cost is calculated from recorded quantity and unit price for one build.</div>',
        unsafe_allow_html=True,
    )
    if intelligence["top_cost_parts"]:
        top_df = pd.DataFrame(intelligence["top_cost_parts"])
        cadivor_engineering_dataframe(
            top_df[
                [
                    "Project",
                    "Part Number",
                    "Manufacturer",
                    "Quantity per Build",
                    "Unit Price",
                    "Extended Cost per Build",
                    "Supplier Sources",
                    "Available Stock",
                    "Risk Score",
                ]
            ],
            column_config={
                "Unit Price": st.column_config.NumberColumn(format="$%.4f"),
                "Extended Cost per Build": st.column_config.NumberColumn(format="$%.2f"),
            },
        )
    else:
        st.info("No positive component prices are currently recorded.")

    opportunity_tab, missing_tab, all_tab = st.tabs(
        ["Savings Opportunities", "Missing Price Data", "All Cost Records"]
    )

    with opportunity_tab:
        if intelligence["opportunities"]:
            opportunity_df = pd.DataFrame(intelligence["opportunities"])
            cadivor_engineering_dataframe(
                opportunity_df[
                    [
                        "Part Number",
                        "Manufacturer",
                        "Category",
                        "Projects",
                        "Units per Build",
                        "Current Unit Price",
                        "Estimated Target Price",
                        "Estimated Run Savings",
                        "Supplier Sources",
                        "Risk Score",
                    ]
                ],
                column_config={
                    "Current Unit Price": st.column_config.NumberColumn(format="$%.4f"),
                    "Estimated Target Price": st.column_config.NumberColumn(format="$%.4f"),
                    "Estimated Run Savings": st.column_config.NumberColumn(format="$%.2f"),
                },
            )
        else:
            st.info("No savings opportunities are currently modeled.")

    with missing_tab:
        if intelligence["missing_price_rows"]:
            missing_df = pd.DataFrame(intelligence["missing_price_rows"])
            cadivor_engineering_dataframe(
                missing_df[
                    [
                        "Project",
                        "Part Number",
                        "Manufacturer",
                        "Quantity per Build",
                        "Supplier Sources",
                        "Available Stock",
                        "Risk Score",
                    ]
                ],
            )
        else:
            st.success("Every component record contains pricing data.")

    with all_tab:
        if intelligence["rows"]:
            all_df = pd.DataFrame(intelligence["rows"])
            cadivor_engineering_dataframe(
                all_df[
                    [
                        "Project",
                        "Part Number",
                        "Manufacturer",
                        "Quantity per Build",
                        "Unit Price",
                        "Extended Cost per Build",
                        "Supplier Sources",
                        "Available Stock",
                        "Lifecycle",
                        "Risk Score",
                    ]
                ],
                column_config={
                    "Unit Price": st.column_config.NumberColumn(format="$%.4f"),
                    "Extended Cost per Build": st.column_config.NumberColumn(format="$%.2f"),
                },
            )

    st.markdown(
        '<div class="cv21-section">Continue Your Review</div>',
        unsafe_allow_html=True,
    )
    actions = st.columns(4)
    with actions[0]:
        internal_nav_button(
            "Procurement Advisor",
            "Procurement Advisor",
            key="cost_procurement",
            use_container_width=True,
        )
    with actions[1]:
        internal_nav_button(
            "Portfolio Intelligence",
            "Portfolio Intelligence",
            key="cost_portfolio",
            use_container_width=True,
        )
    with actions[2]:
        internal_nav_button(
            "Design Impact",
            "Design Impact Analyzer",
            key="cost_design_impact",
            use_container_width=True,
        )
    with actions[3]:
        internal_nav_button(
            "Reports",
            "Reports",
            key="cost_reports",
            use_container_width=True,
        )
