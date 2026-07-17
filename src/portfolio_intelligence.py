"""Cadivor Milestone 19.0 — Portfolio Intelligence.

Turns saved BOM and component records into cross-project engineering,
lifecycle, and supplier intelligence without requiring a new database schema.
"""
from __future__ import annotations

from collections import Counter, defaultdict
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
            }
        )
    project_health.sort(key=lambda row: (row["Health"], -row["High-Risk"]))

    normalized = []
    for row in parts:
        mpn = _text(_first(row, "mpn", "MPN", "part_number"), "Unknown")
        analysis_id = _text(row.get("analysis_id"))
        lifecycle = _text(row.get("lifecycle_status"), "Unknown")
        supplier_count = int(_number(row.get("supplier_count"), 0))
        stock = int(_number(_first(row, "stock_available", "stock"), 0))
        risk_score = int(_number(row.get("risk_score"), 0))
        risk_level = _text(row.get("risk_level"), "Unknown")
        manufacturer = _text(row.get("manufacturer"), "Unknown")
        normalized.append(
            {
                "Analysis ID": analysis_id,
                "Project": analysis_names.get(analysis_id, _text(row.get("project_name"), "Saved BOM")),
                "Part Number": mpn,
                "Manufacturer": manufacturer,
                "Lifecycle": lifecycle,
                "Supplier Sources": supplier_count,
                "Available Stock": stock,
                "Risk Score": risk_score,
                "Risk Level": risk_level,
            }
        )

    mpn_projects: Dict[str, set] = defaultdict(set)
    mpn_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    manufacturer_counts = Counter()
    for row in normalized:
        key = row["Part Number"].upper()
        mpn_projects[key].add(row["Project"])
        mpn_rows[key].append(row)
        manufacturer_counts[row["Manufacturer"]] += 1

    shared_components = []
    for key, projects in mpn_projects.items():
        rows = mpn_rows[key]
        if len(projects) < 2:
            continue
        worst = max(rows, key=lambda row: row["Risk Score"])
        shared_components.append(
            {
                "Part Number": worst["Part Number"],
                "Manufacturer": worst["Manufacturer"],
                "Projects Using Part": len(projects),
                "Highest Risk Score": max(row["Risk Score"] for row in rows),
                "Lowest Stock": min(row["Available Stock"] for row in rows),
                "Minimum Supplier Sources": min(row["Supplier Sources"] for row in rows),
                "Lifecycle": worst["Lifecycle"],
            }
        )
    shared_components.sort(
        key=lambda row: (-row["Projects Using Part"], -row["Highest Risk Score"])
    )

    single_source = [row for row in normalized if row["Supplier Sources"] <= 1]
    no_stock = [row for row in normalized if row["Available Stock"] <= 0]
    lifecycle_exposed = [
        row for row in normalized
        if any(
            term in row["Lifecycle"].lower()
            for term in ("obsolete", "replacement", "nrnd", "not recommended", "eol")
        )
    ]
    high_risk = [
        row for row in normalized
        if row["Risk Score"] >= 60 or row["Risk Level"].lower() == "high"
    ]

    total_parts = len(normalized)
    concentration = 0
    top_manufacturer = "No data"
    if manufacturer_counts:
        top_manufacturer, top_count = manufacturer_counts.most_common(1)[0]
        concentration = round((top_count / max(1, total_parts)) * 100)

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
        exposure = (
            len(single_source) + len(no_stock) + len(lifecycle_exposed) + len(high_risk)
        )
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
        "shared_component_count": len(shared_components),
        "single_source_count": len(single_source),
        "lifecycle_count": len(lifecycle_exposed),
        "manufacturer_concentration": concentration,
        "top_manufacturer": top_manufacturer,
        "portfolio_exposure": opportunity_score,
    }


def _css() -> None:
    st.markdown(
        """
        <style id="cadivor-portfolio-intelligence-19">
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

    st.markdown(
        f"""
        <section class="cv19-hero">
          <div class="cv19-eyebrow">Cross-Project Intelligence</div>
          <div class="cv19-title">Portfolio Intelligence</div>
          <div class="cv19-copy">
            Understand which components, suppliers, and lifecycle risks affect multiple projects.
            Cadivor uses your saved BOM records to identify portfolio-wide exposure and the actions
            that can reduce risk across more than one design.
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Saved Projects", intelligence["total_projects"])
    k2.metric("Component Records", intelligence["total_component_records"])
    k3.metric("Shared Components", intelligence["shared_component_count"])
    k4.metric("Single-Source Records", intelligence["single_source_count"])
    k5.metric("Lifecycle Exposure", intelligence["lifecycle_count"])

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
            st.markdown(
                f"""
                <section class="cv19-card">
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
                  </div>
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
                )

        with st.expander("View all shared components", expanded=False):
            if intelligence["shared_components"]:
                st.dataframe(
                    pd.DataFrame(intelligence["shared_components"]),
                    hide_index=True,
                    use_container_width=True,
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
        st.dataframe(
            project_df[["Project", "Health", "High-Risk", "Components"]],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No saved project health records are available.")

    exposure_tab, lifecycle_tab, alerts_tab = st.tabs(
        ["Sourcing Exposure", "Lifecycle Exposure", "Recurring Alerts"]
    )
    with exposure_tab:
        rows = intelligence["single_source"]
        if rows:
            st.dataframe(
                pd.DataFrame(rows)[
                    ["Project", "Part Number", "Manufacturer", "Supplier Sources", "Available Stock", "Risk Score"]
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("No single-source component record is currently identified.")

    with lifecycle_tab:
        rows = intelligence["lifecycle_exposed"]
        if rows:
            st.dataframe(
                pd.DataFrame(rows)[
                    ["Project", "Part Number", "Manufacturer", "Lifecycle", "Risk Score"]
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("No lifecycle-exposed component record is currently identified.")

    with alerts_tab:
        rows = intelligence["recurring_alerts"]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
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
