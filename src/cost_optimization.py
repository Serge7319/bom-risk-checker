"""Cadivor Milestone 21.0 — Cost Optimization.

Uses saved BOM component records to identify priced spend, purchasing
leverage, missing cost data, and estimated cost-reduction opportunities. Part
photos are optional and appear when saved records contain a trusted image URL.
"""
from __future__ import annotations

from collections import defaultdict
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
                "Description": _text(
                    _first(row, "description", "Description", "part_description", "product_description"),
                    "",
                ),
                "Image URL": normalize_supplier_image_url(
                    _first(row, "image_url", "Image URL", "photo_url")
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
                "Description": reference["Description"],
                "Image URL": reference["Image URL"],
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
        <style id="cadivor-cost-optimization-22">
          .cv21-page{width:100%;max-width:1420px;margin:0 auto;box-sizing:border-box}
          .cv21-heading{display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,250px);align-items:end;gap:24px;margin:0 0 20px}
          .cv21-eyebrow{margin:0 0 8px;color:#2563eb;font-size:12px;font-weight:850;letter-spacing:.08em;text-transform:uppercase}
          .cv21-title{margin:0 0 8px;color:#0f172a;font-size:34px;line-height:1.12;font-weight:900;letter-spacing:-.04em}
          .cv21-copy{margin:0;color:#52647a;font-size:14px;font-weight:600;line-height:1.55;max-width:900px}
          .cv21-kpi-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:22px 0 28px}
          .cv21-kpi{display:flex;align-items:center;gap:16px;min-height:132px;padding:20px 21px;border:1px solid #d9e8fb;border-radius:18px;background:linear-gradient(135deg,#f5faff 0%,#edf6ff 100%);box-sizing:border-box}
          .cv21-kpi-icon{display:inline-flex;align-items:center;justify-content:center;width:58px;height:58px;flex:0 0 58px;border-radius:50%;background:#dbeafe;color:#2563eb}
          .cv21-kpi-icon svg{display:block;width:26px;height:26px}
          .cv21-kpi-label{color:#475569;font-size:13px;font-weight:750;line-height:1.35}
          .cv21-kpi-value{margin-top:8px;color:#0f172a;font-size:30px;font-weight:900;line-height:1.05;letter-spacing:-.04em}
          .cv21-kpi-note{margin-top:7px;color:#64748b;font-size:12px;font-weight:600;line-height:1.4}
          .cv21-section-heading{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:0 0 12px}
          .cv21-section-title{margin:0;color:#0f172a;font-size:21px;font-weight:850;letter-spacing:-.025em;line-height:1.25}
          .cv21-section-subtitle{margin:5px 0 0;color:#64748b;font-size:13px;font-weight:600;line-height:1.45}
          .cv21-table-card{width:100%;border:1px solid #dbe3ef;border-radius:16px;background:#fff;overflow:hidden;box-shadow:0 6px 20px rgba(15,23,42,.035);box-sizing:border-box}
          .cv21-table-scroll{width:100%;overflow-x:auto}
          .cv21-table{width:100%;min-width:930px;border-collapse:separate;border-spacing:0;color:#0f172a}
          .cv21-table th{height:42px;padding:10px 12px;background:#f1f5f9;border-bottom:1px solid #dce4ee;color:#64748b;text-align:left;font-size:10px;font-weight:850;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap}
          .cv21-table td{height:64px;padding:10px 12px;border-bottom:1px solid #e5eaf1;vertical-align:middle;text-align:left;font-size:12px;font-weight:620;line-height:1.35}
          .cv21-table tbody tr:last-child td{border-bottom:0}
          .cv21-table tbody tr:hover{background:#f8fbff}
          .cv21-rank{width:42px;color:#64748b;font-weight:800}
          .cv21-component{display:flex;align-items:center;gap:12px;min-width:210px}
          .cv21-component .cv-part-photo{width:48px;height:48px;flex:0 0 48px;margin:0;border-radius:10px}
          .cv21-component .cv-part-photo__placeholder svg{width:30px;height:30px}
          .cv21-component-copy{min-width:0}
          .cv21-component-name{overflow:hidden;color:#0f172a;font-size:13px;font-weight:800;text-overflow:ellipsis;white-space:nowrap}
          .cv21-component-mpn{margin-top:3px;color:#64748b;font-size:11px;font-weight:600;line-height:1.3;overflow-wrap:anywhere}
          .cv21-price{white-space:nowrap;font-variant-numeric:tabular-nums;font-weight:750}
          .cv21-path-title{color:#0f172a;font-size:12px;font-weight:780}
          .cv21-path-copy{display:-webkit-box;max-width:260px;margin-top:4px;overflow:hidden;color:#64748b;font-size:11px;font-weight:550;line-height:1.35;-webkit-box-orient:vertical;-webkit-line-clamp:2}
          .cv21-savings-amount{display:flex;align-items:center;justify-content:space-between;gap:8px;color:#0f172a;font-size:12px;font-weight:850;font-variant-numeric:tabular-nums;white-space:nowrap}
          .cv21-savings-rate{color:#64748b;font-size:10px;font-weight:700}
          .cv21-progress{width:100%;height:7px;margin-top:7px;border-radius:999px;background:#e6eef8;overflow:hidden}
          .cv21-progress span{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#3b82f6,#2563eb)}
          .cv21-review-pill{display:inline-flex;align-items:center;justify-content:center;padding:6px 9px;border:1px solid #bfdbfe;border-radius:8px;background:#eff6ff;color:#1d4ed8;font-size:10px;font-weight:800;white-space:nowrap}
          .cv21-empty{margin:0;padding:24px;border:1px dashed #cbd5e1;border-radius:14px;background:#f8fafc;color:#64748b;font-size:13px;font-weight:620;line-height:1.5}
          .cv21-data-note{margin:12px 0 18px;color:#64748b;font-size:12px;font-weight:600;line-height:1.5}
          .cv21-detail-heading{margin:0 0 12px;color:#0f172a;font-size:17px;font-weight:850}
          @media(max-width:1100px){
            .cv21-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
            .cv21-kpi:last-child{grid-column:1/-1}
            .cv21-heading{grid-template-columns:minmax(0,1fr) minmax(170px,220px)}
            .cv21-title{font-size:30px}
          }
          @media(max-width:760px){
            .cv21-kpi-grid{grid-template-columns:1fr;gap:10px;margin:16px 0 22px}
            .cv21-kpi,.cv21-kpi:last-child{grid-column:auto;min-height:104px;padding:16px}
            .cv21-heading{grid-template-columns:1fr;gap:12px}
            .cv21-title{font-size:27px}
            .cv21-section-heading{align-items:flex-start;flex-direction:column}
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _opportunity_table_markup(rows: List[Dict[str, Any]]) -> str:
    """Render the ranked opportunity table with the same safe component art as Compare Parts."""
    if not rows:
        return ""

    maximum_savings = max(
        (_number(row.get("Estimated Run Savings"), 0.0) for row in rows),
        default=0.0,
    )
    body = []
    for index, row in enumerate(rows, start=1):
        part_number = _text(row.get("Part Number"), "Component")
        description = _text(row.get("Description"), "")
        manufacturer = _text(row.get("Manufacturer"), "")
        if description:
            component_name = description
            component_meta = part_number
        elif manufacturer and manufacturer.casefold() != "unknown":
            component_name = manufacturer
            component_meta = part_number
        else:
            component_name = part_number
            component_meta = "Part number"

        safe_name = html.escape(component_name)
        safe_part_number = html.escape(component_meta)
        safe_category = html.escape(_text(row.get("Category"), "Cost review"))
        reason = html.escape(_text(row.get("Reason"), ""))
        photo = part_image_markup(
            row.get("Image URL"),
            part_number,
            size=48,
            part={
                "description": description,
                "manufacturer": manufacturer,
                "category": row.get("Category"),
            },
        )
        unit_price = _number(row.get("Current Unit Price"), 0.0)
        estimated_savings = _number(row.get("Estimated Run Savings"), 0.0)
        savings_rate = max(0, min(100, int(round(_number(row.get("Savings Rate"), 0.0) * 100))))
        bar_width = (
            max(0, min(100, int(round(estimated_savings / maximum_savings * 100))))
            if maximum_savings > 0 else 0
        )
        body.append(
            "<tr>"
            f"<td class='cv21-rank'>{index}</td>"
            "<td><div class='cv21-component'>"
            f"{photo}<div class='cv21-component-copy'><div class='cv21-component-name'>{safe_name}</div>"
            f"<div class='cv21-component-mpn'>{safe_part_number}</div></div></div></td>"
            f"<td class='cv21-price'>{'$' + format(unit_price, ',.4f')}</td>"
            f"<td><div class='cv21-path-title'>{safe_category}</div>"
            f"<div class='cv21-path-copy'>{reason}</div></td>"
            "<td><div class='cv21-savings-amount'>"
            f"<span>{'$' + format(estimated_savings, ',.2f')}</span>"
            f"<span class='cv21-savings-rate'>{savings_rate}%</span></div>"
            f"<div class='cv21-progress' role='presentation'><span style='width:{bar_width}%'></span></div></td>"
            "<td><span class='cv21-review-pill' title='Review this optimization with engineering before adopting it'>Review</span></td>"
            "</tr>"
        )
    return (
        "<div class='cv21-page'><div class='cv21-table-card'><div class='cv21-table-scroll'>"
        "<table class='cv21-table'><thead><tr>"
        "<th>#</th><th>Component</th><th>Current unit price</th>"
        "<th>Optimization path</th><th>Estimated savings</th><th>Fit</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></div></div>"
    )


def _currency(value: Any, *, show_zero: bool = True) -> str:
    amount = _number(value, 0.0)
    if not show_zero and amount <= 0:
        return "—"
    return "$" + format(amount, ",.2f")


def render_cost_optimization(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
    control: Callable[[], Any] | None = None,
) -> None:
    from src.ui.approved_pages import begin_approved_page
    from src.ui.cadivor_design_system.icons import lucide

    begin_approved_page()
    _css()

    heading_col, control_col = st.columns([4.0, 1.25], vertical_alignment="bottom")
    with heading_col:
        st.markdown(
            """
            <div class="cv-ap cv21-page">
              <p class="cv21-eyebrow">Cost optimization</p>
              <h1 class="cv21-title">Cost optimization</h1>
              <p class="cv21-copy">Identify lower-cost opportunities, reduce spend, and optimize your bill of materials without compromising performance.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with control_col:
        if control is not None:
            control()

    component_count = int(intelligence.get("component_count", 0) or 0)
    priced_count = len(intelligence.get("priced_rows") or [])
    pricing_coverage = int(intelligence.get("pricing_coverage", 0) or 0)
    has_priced_components = component_count > 0 and priced_count > 0
    savings_text = _currency(intelligence.get("estimated_savings"), show_zero=has_priced_components)
    spend_text = _currency(intelligence.get("production_run_cost"), show_zero=has_priced_components)
    opportunities = list(intelligence.get("opportunities") or [])
    opportunity_count = len(opportunities)
    build_quantity = int(intelligence.get("build_quantity", 1) or 1)

    if has_priced_components:
        savings_note = f"Modeled for {build_quantity:,} builds from saved BOM prices"
        spend_note = f"{priced_count} of {component_count} components have current prices"
    else:
        savings_note = "Saved BOM pricing is needed to model savings"
        spend_note = "No current component prices are available"

    if opportunity_count:
        opportunity_note = "Ranked by estimated savings using saved supplier and quantity data"
    else:
        opportunity_note = "No eligible savings opportunities from current data"

    kpis = [
        ("Estimated savings", savings_text, savings_note, "dollar-sign"),
        ("Addressable spend", spend_text, spend_note, "chart"),
        ("Opportunities", f"{opportunity_count:,}", opportunity_note, "lightbulb"),
    ]
    kpi_markup = []
    for label, value, note, icon_name in kpis:
        icon = lucide(icon_name, size=24)
        kpi_markup.append(
            "<article class='cv21-kpi'><span class='cv21-kpi-icon' aria-hidden='true'>"
            + icon
            + "</span><div><div class='cv21-kpi-label'>"
            + html.escape(label)
            + "</div><div class='cv21-kpi-value'>"
            + html.escape(value)
            + "</div><div class='cv21-kpi-note'>"
            + html.escape(note)
            + "</div></div></article>"
        )
    st.markdown(
        "<div class='cv-ap cv21-page'><section class='cv21-kpi-grid'>"
        + "".join(kpi_markup)
        + "</section></div>",
        unsafe_allow_html=True,
    )

    if component_count == 0:
        st.info("Upload and analyze a BOM to populate cost optimization with your saved component data.")
    elif pricing_coverage < 100:
        st.caption(
            f"Current spend reflects components with recorded prices ({pricing_coverage}% pricing coverage). "
            "Savings remain estimates based on the saved BOM data."
        )

    category_options = sorted(
        {
            _text(row.get("Category"), "Cost review")
            for row in opportunities
        }
    )
    filter_key = "cost_optimization_category_filter"
    filter_options = ["All opportunities", *category_options]
    if st.session_state.get(filter_key) not in filter_options:
        st.session_state[filter_key] = filter_options[0]

    title_col, filter_col = st.columns([3.4, 1.15], vertical_alignment="center")
    with title_col:
        st.markdown(
            """
            <div class="cv-ap cv21-page cv21-section-heading">
              <div>
                <h2 class="cv21-section-title">Top cost optimization opportunities</h2>
                <p class="cv21-section-subtitle">Ranked by estimated savings from the current saved BOM data.</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with filter_col:
        selected_category = st.selectbox(
            "Filter opportunities",
            filter_options,
            key=filter_key,
            label_visibility="collapsed",
            disabled=not category_options,
        )

    filtered_opportunities = (
        opportunities
        if selected_category == "All opportunities"
        else [row for row in opportunities if _text(row.get("Category"), "Cost review") == selected_category]
    )
    visible_opportunities = filtered_opportunities[:8]
    if visible_opportunities:
        st.markdown(
            _opportunity_table_markup(visible_opportunities),
            unsafe_allow_html=True,
        )
        if len(filtered_opportunities) > len(visible_opportunities):
            st.caption(
                f"Showing the top {len(visible_opportunities)} of {len(filtered_opportunities)} opportunities."
            )

        labels = [
            f"{_text(row.get('Part Number'), 'Component')} · {_text(row.get('Category'), 'Cost review')}"
            for row in filtered_opportunities
        ]
        option_map = dict(zip(labels, filtered_opportunities))
        action_key = "cost_optimization_selected_opportunity"
        if st.session_state.get(action_key) not in option_map:
            st.session_state[action_key] = labels[0]
        selected_label = st.selectbox(
            "Choose an opportunity to review",
            labels,
            key=action_key,
            label_visibility="collapsed",
        )
        selected_row = option_map[selected_label]
        action_cols = st.columns(2)
        with action_cols[0]:
            internal_nav_button(
                "Find alternatives",
                "Alternative Finder",
                key="cost_selected_find_alternatives",
                original_part=selected_row["Part Number"],
                source_page="cost_optimization",
            )
        with action_cols[1]:
            internal_nav_button(
                "Review sourcing",
                "Procurement Advisor",
                key="cost_selected_review_sourcing",
                original_part=selected_row["Part Number"],
            )
    elif opportunities:
        st.markdown(
            "<div class='cv21-page'><p class='cv21-empty'>No opportunities match this filter. Select another opportunity type to continue.</p></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='cv21-page'><p class='cv21-empty'>No priced component currently meets the saved supplier, quantity, or shared-demand criteria for a modeled savings opportunity.</p></div>",
            unsafe_allow_html=True,
        )

    with st.expander("Cost data quality and detailed records"):
        st.markdown('<div class="cv21-detail-heading">Cost data quality</div>', unsafe_allow_html=True)
        quality_cols = st.columns(2)
        with quality_cols[0]:
            st.markdown(
                f"<div class='cv21-kpi'><div><div class='cv21-kpi-label'>Pricing coverage</div>"
                f"<div class='cv21-kpi-value'>{pricing_coverage}%</div>"
                f"<div class='cv21-kpi-note'>{priced_count} of {component_count} saved component records have a positive unit price</div></div></div>",
                unsafe_allow_html=True,
            )
        with quality_cols[1]:
            st.markdown(
                f"<div class='cv21-kpi'><div><div class='cv21-kpi-label'>Single-source or no-stock spend</div>"
                f"<div class='cv21-kpi-value'>{html.escape(_currency(intelligence.get('sourcing_risk_cost'), show_zero=has_priced_components))}</div>"
                f"<div class='cv21-kpi-note'>Modeled production-run spend requiring sourcing review</div></div></div>",
                unsafe_allow_html=True,
            )

        photo_column = st.column_config.ImageColumn("Part photo", width="small")
        if intelligence.get("top_cost_parts"):
            st.markdown('<div class="cv21-detail-heading">Highest recorded component costs</div>', unsafe_allow_html=True)
            top_df = pd.DataFrame(intelligence["top_cost_parts"])
            cadivor_engineering_dataframe(
                top_df[
                    [
                        "Project",
                        "Part Number",
                        "Image URL",
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
                    "Image URL": photo_column,
                    "Unit Price": st.column_config.NumberColumn(format="$%.4f"),
                    "Extended Cost per Build": st.column_config.NumberColumn(format="$%.2f"),
                },
            )
        missing_tab, all_tab = st.tabs(["Missing price data", "All cost records"])
        with missing_tab:
            if intelligence.get("missing_price_rows"):
                missing_df = pd.DataFrame(intelligence["missing_price_rows"])
                cadivor_engineering_dataframe(
                    missing_df[
                        [
                            "Project",
                            "Part Number",
                            "Image URL",
                            "Manufacturer",
                            "Quantity per Build",
                            "Supplier Sources",
                            "Available Stock",
                            "Risk Score",
                        ]
                    ],
                    column_config={"Image URL": photo_column},
                )
            else:
                st.success("Every saved component record contains pricing data.")
        with all_tab:
            if intelligence.get("rows"):
                all_df = pd.DataFrame(intelligence["rows"])
                cadivor_engineering_dataframe(
                    all_df[
                        [
                            "Project",
                            "Part Number",
                            "Image URL",
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
                        "Image URL": photo_column,
                        "Unit Price": st.column_config.NumberColumn(format="$%.4f"),
                        "Extended Cost per Build": st.column_config.NumberColumn(format="$%.2f"),
                    },
                )
            else:
                st.info("No saved component records are available.")

    review_cols = st.columns(4)
    with review_cols[0]:
        internal_nav_button("Procurement Advisor", "Procurement Advisor", key="cost_procurement", use_container_width=True)
    with review_cols[1]:
        internal_nav_button("Portfolio Intelligence", "Portfolio Intelligence", key="cost_portfolio", use_container_width=True)
    with review_cols[2]:
        internal_nav_button("Design Impact", "Design Impact Analyzer", key="cost_design_impact", use_container_width=True)
    with review_cols[3]:
        internal_nav_button("Reports", "Reports", key="cost_reports", use_container_width=True)
