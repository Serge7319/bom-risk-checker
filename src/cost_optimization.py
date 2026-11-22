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
from src.part_images import part_image_markup, part_image_source


def _verified_stock(row: Dict[str, Any], mpn: str) -> int | None:
    """Reconcile stock only from exact, timestamped authorized supplier rows."""
    from datetime import datetime
    from integrations.stock_coercion import parse_stock_total
    from src.normalizer import normalize_part_number

    observations = _first(row, "stock_evidence", "Stock Evidence", default=[]) or []
    if isinstance(observations, dict):
        observations = [observations]
    trusted = []
    authorized = {"digikey", "digikeyelectronics", "mouser", "mouserelectronics", "newark", "element14", "farnell", "nexarsupply"}
    for item in observations if isinstance(observations, (list, tuple)) else []:
        if not isinstance(item, dict):
            continue
        source = "".join(ch for ch in str(item.get("source") or item.get("supplier") or "").casefold() if ch.isalnum())
        try:
            retrieved = datetime.fromisoformat(str(item.get("retrieved_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if (
            source not in authorized
            or not item.get("mpn")
            or normalize_part_number(str(item.get("mpn"))) != normalize_part_number(mpn)
            or retrieved.tzinfo is None
        ):
            continue
        quantity = parse_stock_total(item.get("stock", item.get("stock_total")))
        if quantity is not None:
            trusted.append(int(quantity))
    reported = parse_stock_total(_first(row, "stock_available", "Stock Available", "Total Market Stock", "total_market_stock", "stock"))
    if trusted and reported is not None and sum(trusted) == reported:
        return int(reported)
    return None


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


def _format_money(value: Any, currency: str = "") -> str:
    amount = _number(value, 0.0)
    code = _text(currency).upper()
    if code == "USD":
        return "$" + format(amount, ",.2f")
    return f"{code or 'Currency not recorded'} {amount:,.2f}"


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

    from src.saved_bom_cost import normalize_saved_offers, select_supplier_offer, distributor_comparison, extended_cost

    normalized: List[Dict[str, Any]] = []
    for row in parts:
        analysis_id = _text(row.get("analysis_id"))
        raw_qty = _number(_first(row, "effective_quantity", "Effective Quantity", "quantity", "Quantity", "qty", "required_quantity"), 0)
        qty = max(0, int(raw_qty))
        part_number = _text(_first(row, "mpn", "MPN", "part_number"), "Unknown")
        raw_offers = _first(row, "supplier_offers", "Supplier Offers", default=[])
        offers = normalize_saved_offers(raw_offers, mpn=part_number)
        quantity_offers = []
        for offer in offers:
            selected = select_supplier_offer(
                [offer],
                mpn=part_number,
                supplier=str(offer.get("distributor") or ""),
                unit_price=offer.get("unit_price"),
                currency=offer.get("currency"),
                quantity=qty if qty > 0 else None,
            )
            if selected and selected.get("quantity_break_applies") is True:
                quantity_offers.append(selected)
        selected_supplier = _text(_first(row, "price_source", "Price Source", "primary_supplier", "supplier", "best_source"))
        raw_price = _first(row, "unit_price", "Unit Price", "price", "best_price")
        raw_currency = _text(_first(row, "unit_price_currency", "Unit Price Currency", "currency", "Currency")).upper()
        matched_current = select_supplier_offer(
            quantity_offers,
            mpn=part_number,
            supplier=selected_supplier,
            unit_price=raw_price,
            currency=raw_currency,
            quantity=qty if qty > 0 else None,
        ) if raw_price not in (None, "") else None
        current_quote = matched_current or min(
            quantity_offers,
            key=lambda offer: float(offer["unit_price"]),
            default=None,
        )
        unit_price = float(current_quote["unit_price"]) if current_quote else 0.0
        currency = str(current_quote.get("currency") or "") if current_quote else ""
        verified_supplier = str(current_quote.get("distributor") or "") if current_quote else ""
        suppliers = len({str(offer.get("distributor") or "").casefold() for offer in quantity_offers})
        stock_value = _verified_stock(row, part_number)
        stock = int(stock_value) if stock_value is not None else None
        from src.risk_engine import calculate_risk

        scored_risk = calculate_risk(row).get("risk_score")
        risk_score = int(scored_risk) if scored_risk is not None else None
        description = _text(
            _first(row, "description", "Description", "part_description", "product_description"),
            "",
        )
        category = _text(
            _first(
                row,
                "category_raw",
                "category",
                "part_category",
                "component_category",
                "device_type",
            ),
            "",
        )
        manufacturer = _text(row.get("manufacturer"), "Unknown")
        image_context = {
            "description": description,
            "category": category,
            "manufacturer": manufacturer,
        }
        for key in (
            "package", "package_type", "package type", "package_case",
            "case_package", "case", "mounting_type", "mounting type",
            "mount_type", "mounting", "through_hole", "is_through_hole",
            "tht", "is_tht", "surface_mount", "is_surface_mount", "smd", "smt",
            "architecture", "device_type",
        ):
            value = row.get(key)
            if value is not None and str(value).strip():
                image_context[key] = value
        image_url = part_image_source(
            _first(row, "image_url", "Image URL", "photo_url"),
            part_number,
            size=48,
            part=image_context,
        )
        normalized.append(
            {
                "Analysis ID": analysis_id,
                "Project": analysis_lookup.get(
                    analysis_id,
                    _text(row.get("project_name"), "Saved BOM"),
                ),
                "Part Number": part_number,
                "Description": description,
                "Component Category": category,
                "Image URL": image_url,
                "Image Context": image_context,
                "Manufacturer": manufacturer,
                "Supplier": verified_supplier or "Not recorded",
                "Quantity per Build": qty,
                "Unit Price": unit_price,
                "Currency": currency,
                "Extended Cost per Build": extended_cost(unit_price, qty),
                "Supplier Sources": suppliers,
                "Available Stock": stock,
                "Lifecycle": _text(row.get("lifecycle_status"), "Unknown"),
                "Risk Score": risk_score,
                "Verified Offers": quantity_offers,
            }
        )
    priced = [row for row in normalized if row["Unit Price"] > 0 and row["Currency"]]
    missing_price = [row for row in normalized if row not in priced]
    currencies = {row["Currency"] for row in priced}
    current_cost_per_build = (
        sum(float(row["Extended Cost per Build"] or 0) for row in priced)
        if (
            priced
            and len(priced) == len(normalized)
            and len(currencies) == 1
            and all(row["Extended Cost per Build"] is not None for row in priced)
        )
        else None
    )
    production_run_cost = current_cost_per_build * max(1, build_quantity) if current_cost_per_build is not None else None
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
        project_count = len({row["Project"] for row in rows})
        analysis_ids = {row["Analysis ID"] for row in rows if row["Analysis ID"]}
        total_qty_per_build = sum(row["Quantity per Build"] for row in rows)
        suppliers = max(row["Supplier Sources"] for row in rows)
        risk_scores = [row["Risk Score"] for row in rows if row["Risk Score"] is not None]
        risk_score = max(risk_scores) if risk_scores else None
        stock_values = [row["Available Stock"] for row in rows if row["Available Stock"] is not None]
        stock = min(stock_values) if stock_values else None
        exact_offers = [offer for row in rows for offer in row["Verified Offers"]]
        if total_qty_per_build <= 0 or len({str(offer.get("distributor") or "").casefold() for offer in exact_offers}) < 2:
            continue
        comparison_quantity = total_qty_per_build * max(1, build_quantity)
        comparison = distributor_comparison(
            exact_offers,
            mpn=reference["Part Number"],
            bom_quantity=comparison_quantity,
        )
        if comparison.get("savings_per_unit") is None:
            continue
        unit_price = float(comparison["higher_price"])
        target_price = float(comparison["lower_price"])
        currency = str(comparison.get("currency") or "")
        estimated_savings = float(comparison["savings_per_unit"]) * comparison_quantity
        savings_rate = (unit_price - target_price) / unit_price if unit_price > 0 else 0
        category = "Comparable supplier quote"
        reason = (
            f"Exact-MPN snapshots from {comparison['higher_distributor']} and "
            f"{comparison['lower_distributor']} differ by {currency} "
            f"{float(comparison['savings_per_unit']):,.4g} per unit at quantity {comparison_quantity:,}. "
            "Catalog snapshots are not checkout quotes; freight, tax, MOQ, and qualification are excluded."
        )
        opportunities.append(
            {
                "Part Number": reference["Part Number"],
                "Analysis ID": reference["Analysis ID"] if len(analysis_ids) == 1 else "",
                "Project": reference["Project"] if len(analysis_ids) == 1 else "",
                "Description": reference["Description"],
                "Component Category": reference["Component Category"],
                "Image URL": reference["Image URL"],
                "Image Context": reference["Image Context"],
                "Manufacturer": reference["Manufacturer"],
                "Category": category,
                "Projects": project_count,
                "Units per Build": total_qty_per_build,
                "Current Unit Price": unit_price,
                "Estimated Target Price": target_price,
                "Estimated Run Savings": estimated_savings,
                "Savings Rate": savings_rate,
                "Currency": currency,
                "Supplier Sources": suppliers,
                "Lowest Stock": stock,
                "Risk Score": risk_score,
                "Reason": reason,
            }
        )

    opportunities.sort(
        key=lambda row: (
            -row["Estimated Run Savings"],
            -(row["Risk Score"] if row["Risk Score"] is not None else -1),
        )
    )

    savings_currencies = {row["Currency"] for row in opportunities}
    estimated_savings = (
        sum(row["Estimated Run Savings"] for row in opportunities)
        if opportunities and len(savings_currencies) == 1
        else 0.0 if not opportunities else None
    )
    estimated_optimized_cost = (
        max(0.0, production_run_cost - estimated_savings)
        if production_run_cost is not None and estimated_savings is not None
        and (not savings_currencies or savings_currencies == currencies)
        else None
    )

    top_cost_parts = []
    for currency_code in sorted(currencies):
        top_cost_parts.extend(
            sorted(
                [
                    row for row in priced
                    if row["Currency"] == currency_code
                    and row["Extended Cost per Build"] is not None
                ],
                key=lambda row: -row["Extended Cost per Build"],
            )[:10]
        )

    sourcing_risk_cost = sum(
        float(row["Extended Cost per Build"] or 0) * max(1, build_quantity)
        for row in priced
        if row["Extended Cost per Build"] is not None
        and (row["Supplier Sources"] <= 1 or (row["Available Stock"] is not None and row["Available Stock"] <= 0))
    ) if len(currencies) == 1 else None

    recommendations = []
    if opportunities:
        top = opportunities[0]
        recommendations.append(
            f"Start with {top['Part Number']}: the estimated production-run savings opportunity "
            f"is {_format_money(top['Estimated Run Savings'], top['Currency'])} based on saved distributor snapshots, not a confirmed checkout quote."
        )
    if missing_price:
        recommendations.append(
            f"Add current pricing for {len(missing_price)} component record(s) to improve "
            "cost-analysis coverage."
        )
    if sourcing_risk_cost is not None and sourcing_risk_cost > 0:
        recommendations.append(
            f"{_format_money(sourcing_risk_cost, next(iter(currencies)))} of recorded production-run spend is attached to "
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
        "currency": next(iter(currencies)) if len(currencies) == 1 else "",
        "currencies": sorted(currencies),
        "mixed_currency_totals": {
            code: sum(float(row["Extended Cost per Build"] or 0) for row in priced if row["Currency"] == code) * max(1, build_quantity)
            for code in sorted(currencies)
        },
        "pricing_coverage": pricing_coverage,
        "sourcing_risk_cost": sourcing_risk_cost,
        "recommendations": recommendations[:4],
        "project_count": len(analyses),
        "component_count": len(normalized),
    }


def _css() -> None:
    st.markdown(
        """
        <style id="cadivor-cost-optimization-22" data-cadivor-layout-style="true">
          .st-key-cost_optimization_workspace{width:100%;max-width:1500px;margin:0 auto;box-sizing:border-box}
          .cv21-page{width:100%;max-width:1500px;margin:0 auto;box-sizing:border-box}
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
          .cv21-table{width:100%;min-width:900px;border-collapse:separate;border-spacing:0;color:#0f172a}
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
          .cv21-review-pill{display:inline-flex;align-items:center;justify-content:center;padding:6px 9px;border:1px solid #fde68a;border-radius:8px;background:#fffbeb;color:#a16207;font-size:10px;font-weight:800;white-space:nowrap}
          .cv21-review-cell{display:flex;flex-direction:column;align-items:flex-start;gap:6px}
          .cv21-row-action{color:#2563eb;font-size:11px;font-weight:750;text-decoration:none;white-space:nowrap}
          .cv21-row-action:hover{text-decoration:underline;text-underline-offset:3px}
          .cv21-empty{margin:0;padding:24px;border:1px dashed #cbd5e1;border-radius:14px;background:#f8fafc;color:#64748b;font-size:13px;font-weight:620;line-height:1.5}
          .cv21-data-note{margin:12px 0 18px;color:#64748b;font-size:12px;font-weight:600;line-height:1.5}
          .cv21-detail-heading{margin:0 0 12px;color:#0f172a;font-size:17px;font-weight:850}
          .st-key-cost_optimization_opportunities{width:100%;max-width:none;margin:0 0 22px;padding:18px;border:1px solid #dbe3ef;border-radius:18px;background:#fff;box-shadow:0 8px 24px rgba(15,23,42,.04);box-sizing:border-box}
          .st-key-cost_optimization_opportunities .cv21-table-card{border:0;border-radius:12px;box-shadow:none}
          .st-key-cost_optimization_opportunities .cv21-table-scroll{border:1px solid #e5eaf1;border-radius:12px}
          .cv21-table th:first-child{width:42px}.cv21-table th:nth-child(2){width:25%}.cv21-table th:nth-child(3){width:13%}.cv21-table th:nth-child(4){width:24%}.cv21-table th:nth-child(5){width:18%}.cv21-table th:nth-child(6){width:120px}
          .st-key-cost_optimization_opportunities [data-testid="stButton"] button{min-height:40px;border-radius:9px;font-weight:750;white-space:nowrap}
          @media(max-width:1100px){
            .cv21-page{max-width:100%}
            .st-key-cost_optimization_opportunities{padding:14px}

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
            part=row.get("Image Context") or {
                "description": description,
                "manufacturer": manufacturer,
                "category": row.get("Component Category"),
            },
        )
        unit_price = _number(row.get("Current Unit Price"), 0.0)
        estimated_savings = _number(row.get("Estimated Run Savings"), 0.0)
        currency = _text(row.get("Currency"))
        savings_rate = max(0, min(100, int(round(_number(row.get("Savings Rate"), 0.0) * 100))))
        bar_width = (
            max(0, min(100, int(round(estimated_savings / maximum_savings * 100))))
            if maximum_savings > 0 else 0
        )
        from src.ui.navigation import alternative_finder_href

        alternative_url = alternative_finder_href(
            mpn=part_number,
            manufacturer=manufacturer,
            description=description,
            risk=str(row.get("Risk Score") or ""),
            analysis_id=str(row.get("Analysis ID") or ""),
            return_analysis_id=str(row.get("Analysis ID") or ""),
            source_page="cost_optimization",
            project_name=str(row.get("Project") or ""),
            bom_name=str(row.get("Project") or ""),
        )
        body.append(
            "<tr>"
            f"<td class='cv21-rank'>{index}</td>"
            "<td><div class='cv21-component'>"
            f"{photo}<div class='cv21-component-copy'><div class='cv21-component-name'>{safe_name}</div>"
            f"<div class='cv21-component-mpn'>{safe_part_number}</div></div></div></td>"
            f"<td class='cv21-price'>{html.escape(_format_money(unit_price, currency))}</td>"
            f"<td><div class='cv21-path-title'>{safe_category}</div>"
            f"<div class='cv21-path-copy'>{reason}</div></td>"
            "<td><div class='cv21-savings-amount'>"
            f"<span>{html.escape(_format_money(estimated_savings, currency))}</span>"
            f"<span class='cv21-savings-rate'>{savings_rate}%</span></div>"
            f"<div class='cv21-progress' role='presentation'><span style='width:{bar_width}%'></span></div></td>"
            "<td class='cv21-review-cell'>"
            "<span class='cv21-review-pill' title='Calculated from timestamped exact-part supplier API snapshots; confirm the supplier quote and engineering fit before action'>Confirm quote</span>"
            f"<a class='cv21-row-action' href='{html.escape(alternative_url, quote=True)}' target='_self'>Find alternatives</a></td>"
            "</tr>"
        )
    return (
        "<div class='cv21-table-card'><div class='cv21-table-scroll'>"
        "<table class='cv21-table'><thead><tr>"
        "<th>#</th><th>Component</th><th>Higher saved quote</th>"
        "<th>Evidence and quantity</th><th>Saved quote spread</th><th>Review status</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div></div>"
    )


def _currency(value: Any, *, currency: str = "", show_zero: bool = True) -> str:
    if value is None:
        return "Not comparable"
    amount = _number(value, 0.0)
    if not show_zero and amount <= 0:
        return "—"
    return _format_money(amount, currency)


def render_cost_optimization(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
    control: Callable[[], Any] | None = None,
) -> None:
    from src.ui.approved_pages import begin_approved_page, end_approved_page
    from src.ui.cadivor_design_system.icons import lucide

    begin_approved_page()
    _css()

    with st.container(key="cost_optimization_workspace"):
        heading_col, control_col = st.columns([4.0, 1.25], vertical_alignment="bottom")
        with heading_col:
            st.markdown(
                """
                <div class="cv-ap cv21-page">
                  <p class="cv21-eyebrow">Cost optimization</p>
                  <h1 class="cv21-title">Cost optimization</h1>
                  <p class="cv21-copy">Compare exact-part, timestamped supplier price snapshots and quantity breaks. Cadivor only calculates a price spread when the saved offers are comparable.</p>
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
        currency = str(intelligence.get("currency") or "")
        mixed_currency = len(intelligence.get("currencies") or []) > 1
        savings_text = (
            "Multiple currencies" if mixed_currency and intelligence.get("estimated_savings") is None
            else _currency(intelligence.get("estimated_savings"), currency=currency, show_zero=bool(intelligence.get("opportunities")))
        )
        spend_text = (
            "Multiple currencies" if mixed_currency and intelligence.get("production_run_cost") is None
            else _currency(intelligence.get("production_run_cost"), currency=currency, show_zero=has_priced_components)
        )
        opportunities = list(intelligence.get("opportunities") or [])
        opportunity_count = len(opportunities)
        build_quantity = int(intelligence.get("build_quantity", 1) or 1)

        if has_priced_components:
            savings_note = (
                f"Saved distributor price spread across {build_quantity:,} builds; excludes freight, tax, MOQ, and checkout"
                if opportunity_count else "Requires two comparable exact-part supplier offers at the BOM quantity"
            )
            spend_note = f"{priced_count} of {component_count} components have exact-part, timestamped price snapshots"
        else:
            savings_note = "No comparable supplier price spread is available"
            spend_note = "No exact-part, timestamped supplier price snapshots are available"

        if opportunity_count:
            opportunity_note = "Ranked by exact-part saved supplier price spread at the stated quantity"
        else:
            opportunity_note = "Two comparable supplier snapshots are required"

        kpis = [
            ("Comparable quote spread", savings_text, savings_note, "dollar-sign"),
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
                f"{pricing_coverage}% of component lines have exact-part, timestamped supplier API price snapshots. "
                "Catalog snapshots can differ from checkout prices."
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

        with st.container(key="cost_optimization_opportunities"):
            title_col, filter_col = st.columns([3.4, 1.15], vertical_alignment="center")
            with title_col:
                st.markdown(
                    """
                    <div class="cv21-section-heading">
                      <div>
                        <h2 class="cv21-section-title">Comparable supplier quote spreads</h2>
                        <p class="cv21-section-subtitle">Differences use exact-MPN saved API snapshots in one currency at a stated quantity; confirm with the supplier before purchasing.</p>
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
                    for row in visible_opportunities
                ]
                option_map = dict(zip(labels, visible_opportunities))
                action_key = "cost_optimization_selected_opportunity"
                if st.session_state.get(action_key) not in option_map:
                    st.session_state[action_key] = labels[0]
                action_cols = st.columns([4.6, 1.2, 1.2], vertical_alignment="center")
                with action_cols[0]:
                    selected_label = st.selectbox(
                        "Choose an opportunity to review",
                        labels,
                        key=action_key,
                        label_visibility="collapsed",
                    )
                selected_row = option_map[selected_label]
                with action_cols[1]:
                    internal_nav_button(
                        "Find alternatives",
                        "Alternative Finder",
                        key="cost_selected_find_alternatives",
                        original_part=selected_row["Part Number"],
                        manufacturer=selected_row.get("Manufacturer", ""),
                        description=selected_row.get("Description", ""),
                        risk=str(selected_row.get("Risk Score") or ""),
                        analysis_id=selected_row.get("Analysis ID", ""),
                        return_analysis_id=selected_row.get("Analysis ID", ""),
                        project_name=selected_row.get("Project", ""),
                        bom_name=selected_row.get("Project", ""),
                        source_page="cost_optimization",
                        use_container_width=True,
                    )
                with action_cols[2]:
                    internal_nav_button(
                        "Review sourcing",
                        "Procurement Advisor",
                        key="cost_selected_review_sourcing",
                        original_part=selected_row["Part Number"],
                        use_container_width=True,
                    )
            elif opportunities:
                st.markdown(
                    "<p class='cv21-empty'>No opportunities match this filter. Select another opportunity type to continue.</p>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<p class='cv21-empty'>No exact-part, timestamped supplier offers currently support a same-currency price comparison at a known quantity. Record a supplier quote or rerun the analysis to add evidence.</p>",
                    unsafe_allow_html=True,
                )

        with st.expander("Cost data quality and detailed records"):
            st.markdown('<div class="cv21-detail-heading">Cost data quality</div>', unsafe_allow_html=True)
            quality_cols = st.columns(2)
            with quality_cols[0]:
                st.markdown(
                    f"<div class='cv21-kpi'><div><div class='cv21-kpi-label'>Pricing coverage</div>"
                    f"<div class='cv21-kpi-value'>{pricing_coverage}%</div>"
                    f"<div class='cv21-kpi-note'>{priced_count} of {component_count} rows have an exact-part, timestamped supplier price snapshot</div></div></div>",
                    unsafe_allow_html=True,
                )
            with quality_cols[1]:
                st.markdown(
                    f"<div class='cv21-kpi'><div><div class='cv21-kpi-label'>Single-source or no-stock spend</div>"
                    f"<div class='cv21-kpi-value'>{html.escape(_currency(intelligence.get('sourcing_risk_cost'), currency=currency, show_zero=has_priced_components))}</div>"
                    f"<div class='cv21-kpi-note'>Saved price snapshot spend with one quote source or a timestamped zero-stock observation</div></div></div>",
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
                        "Currency",
                            "Extended Cost per Build",
                            "Supplier Sources",
                            "Available Stock",
                            "Risk Score",
                        ]
                    ],
                    column_config={
                        "Image URL": photo_column,
                        "Unit Price": st.column_config.NumberColumn(format="%.4f"),
                        "Extended Cost per Build": st.column_config.NumberColumn(format="%.2f"),
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
                                "Currency",
                                "Extended Cost per Build",
                                "Supplier Sources",
                                "Available Stock",
                                "Lifecycle",
                                "Risk Score",
                            ]
                        ],
                        column_config={
                            "Image URL": photo_column,
                            "Unit Price": st.column_config.NumberColumn(format="%.4f"),
                            "Extended Cost per Build": st.column_config.NumberColumn(format="%.2f"),
                        },
                    )
                else:
                    st.info("No saved component records are available.")
        end_approved_page()
