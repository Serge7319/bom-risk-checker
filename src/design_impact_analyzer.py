"""Cadivor Milestone 20.0 — Design Impact Analyzer.

Shows where a component is used, what engineering work a change may create,
and which projects should be reviewed first.
"""
from __future__ import annotations

from collections import defaultdict
import html
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system import MetricCard, cadivor_engineering_dataframe, cadivor_section_header, render_kpi_row_safe


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


def _impact_level(score: int) -> str:
    if score >= 75:
        return "High"
    if score >= 45:
        return "Moderate"
    return "Low"


def build_design_impact(
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    selected_mpn: str = "",
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
            "Updated": _text(row.get("created_at") or row.get("updated_at"), "Not recorded"),
        }
        for row in analyses
    }

    normalized: List[Dict[str, Any]] = []
    for row in parts:
        analysis_id = _text(row.get("analysis_id"))
        normalized.append(
            {
                "Analysis ID": analysis_id,
                "Project": analysis_lookup.get(analysis_id, {}).get(
                    "Project",
                    _text(row.get("project_name"), "Saved BOM"),
                ),
                "Project Health": analysis_lookup.get(analysis_id, {}).get("Health", 0),
                "Part Number": _text(_first(row, "mpn", "MPN", "part_number"), "Unknown"),
                "Manufacturer": _text(row.get("manufacturer"), "Unknown"),
                "Lifecycle": _text(row.get("lifecycle_status"), "Unknown"),
                "Package": _text(row.get("package"), "Not recorded"),
                "Pin Count": int(_number(_first(row, "pin_count", "pins"), 0)),
                "Supplier Sources": int(_number(row.get("supplier_count"), 0)),
                "Available Stock": int(_number(_first(row, "stock_available", "stock"), 0)),
                "Risk Score": int(_number(row.get("risk_score"), 0)),
                "Risk Level": _text(row.get("risk_level"), "Unknown"),
                "Quantity": int(_number(_first(row, "quantity", "qty", "required_quantity"), 1)),
            }
        )

    available_mpns = sorted(
        {
            row["Part Number"]
            for row in normalized
            if row["Part Number"] and row["Part Number"] != "Unknown"
        },
        key=str.upper,
    )

    if selected_mpn and selected_mpn not in available_mpns:
        selected_mpn = ""

    if not selected_mpn:
        ranked: Dict[str, int] = defaultdict(int)
        for row in normalized:
            score = row["Risk Score"]
            if row["Supplier Sources"] <= 1:
                score += 20
            if row["Available Stock"] <= 0:
                score += 25
            if any(
                term in row["Lifecycle"].lower()
                for term in ("obsolete", "replacement", "nrnd", "not recommended", "eol")
            ):
                score += 20
            ranked[row["Part Number"]] = max(ranked[row["Part Number"]], score)
        selected_mpn = max(ranked, key=ranked.get) if ranked else ""

    affected = [
        row for row in normalized
        if row["Part Number"].upper() == selected_mpn.upper()
    ] if selected_mpn else []

    affected.sort(key=lambda row: (row["Project Health"], -row["Risk Score"]))

    reference = affected[0] if affected else {}
    project_count = len({row["Project"] for row in affected})
    total_quantity = sum(max(1, row["Quantity"]) for row in affected)
    minimum_stock = min((row["Available Stock"] for row in affected), default=0)
    minimum_sources = min((row["Supplier Sources"] for row in affected), default=0)
    maximum_risk = max((row["Risk Score"] for row in affected), default=0)

    lifecycle_exposed = any(
        any(term in row["Lifecycle"].lower() for term in (
            "obsolete", "replacement", "nrnd", "not recommended", "eol"
        ))
        for row in affected
    )
    package_unknown = any(
        row["Package"].lower() in ("", "unknown", "not recorded", "n/a")
        for row in affected
    )
    package_variants = len({row["Package"] for row in affected if row["Package"]})
    pin_variants = len({row["Pin Count"] for row in affected if row["Pin Count"] > 0})

    impact_score_drivers = [
        {
            "label": "Component risk",
            "points": maximum_risk,
            "detail": f"Highest recorded component risk is {maximum_risk}/100.",
        },
        {
            "label": "Cross-project exposure",
            "points": min(25, max(0, project_count - 1) * 10),
            "detail": (
                f"Used in {project_count} saved project(s)."
                if project_count > 1
                else "Used in one saved project."
            ),
        },
        {
            "label": "Inventory evidence",
            "points": 20 if minimum_stock <= 0 else 0,
            "detail": (
                "No available stock is recorded."
                if minimum_stock <= 0
                else f"{minimum_stock:,} units are recorded as available."
            ),
        },
        {
            "label": "Supplier coverage",
            "points": 15 if minimum_sources <= 1 else 0,
            "detail": f"Minimum recorded coverage is {minimum_sources} source(s).",
        },
        {
            "label": "Lifecycle exposure",
            "points": 15 if lifecycle_exposed else 0,
            "detail": (
                "Lifecycle exposure is recorded."
                if lifecycle_exposed
                else "No lifecycle exposure is recorded."
            ),
        },
    ]
    impact_score_raw = sum(driver["points"] for driver in impact_score_drivers)
    impact_score = min(100, impact_score_raw)

    engineering_hours = max(
        1,
        project_count * (
            2
            + (2 if lifecycle_exposed else 0)
            + (2 if package_variants > 1 or pin_variants > 1 else 0)
        ),
    )

    impact_categories = []
    if project_count > 1:
        impact_categories.append({
            "Area": "Cross-project usage",
            "Finding": f"Used in {project_count} saved projects.",
            "Impact": "One component decision may affect multiple designs.",
            "Severity": "High" if project_count >= 3 else "Moderate",
        })
    if minimum_stock <= 0:
        impact_categories.append({
            "Area": "Supply continuity",
            "Finding": "No available stock is recorded.",
            "Impact": "A build may be delayed without authorized inventory or a substitute.",
            "Severity": "High",
        })
    if minimum_sources <= 1:
        impact_categories.append({
            "Area": "Supplier coverage",
            "Finding": f"Minimum recorded coverage is {minimum_sources} source(s).",
            "Impact": "The portfolio has limited sourcing resilience.",
            "Severity": "High" if minimum_sources == 0 else "Moderate",
        })
    if lifecycle_exposed:
        impact_categories.append({
            "Area": "Lifecycle",
            "Finding": "At least one record shows lifecycle exposure.",
            "Impact": "Replacement qualification may be required before production.",
            "Severity": "High",
        })
    if package_variants > 1 or pin_variants > 1:
        impact_categories.append({
            "Area": "Engineering compatibility",
            "Finding": "Package or pin-count records vary across projects.",
            "Impact": "A replacement may require project-specific validation.",
            "Severity": "Moderate",
        })
    if package_unknown:
        impact_categories.append({
            "Area": "Data completeness",
            "Finding": "Package data is missing for at least one affected project.",
            "Impact": "Compatibility confidence is reduced until specifications are confirmed.",
            "Severity": "Moderate",
        })
    if not impact_categories:
        impact_categories.append({
            "Area": "Engineering review",
            "Finding": "No major cross-project exception is currently recorded.",
            "Impact": "Continue controlled monitoring and confirm compatibility before change approval.",
            "Severity": "Low",
        })

    recommendations = []
    if minimum_stock <= 0:
        recommendations.append(
            f"Secure authorized inventory or identify a qualified substitute for {selected_mpn} before the next build."
        )
    if minimum_sources <= 1:
        recommendations.append(
            f"Qualify an additional authorized source for {selected_mpn}."
        )
    if lifecycle_exposed:
        recommendations.append(
            f"Start replacement qualification for {selected_mpn} and review every affected project."
        )
    if project_count > 1:
        recommendations.append(
            f"Use one coordinated engineering change plan across all {project_count} affected projects."
        )
    if package_unknown or package_variants > 1 or pin_variants > 1:
        recommendations.append(
            "Confirm package, pin count, and footprint compatibility before approving a replacement."
        )
    if not recommendations:
        recommendations.append(
            "Continue monitoring and document the approved component selection for future reviews."
        )

    return {
        "selected_mpn": selected_mpn,
        "available_mpns": available_mpns,
        "affected_projects": affected,
        "project_count": project_count,
        "total_quantity": total_quantity,
        "minimum_stock": minimum_stock,
        "minimum_sources": minimum_sources,
        "maximum_risk": maximum_risk,
        "impact_score": impact_score,
        "impact_score_raw": impact_score_raw,
        "impact_score_capped": impact_score_raw > 100,
        "impact_score_drivers": impact_score_drivers,
        "impact_level": _impact_level(impact_score),
        "engineering_hours": engineering_hours,
        "manufacturer": _text(reference.get("Manufacturer"), "Unknown"),
        "lifecycle": _text(reference.get("Lifecycle"), "Unknown"),
        "package": _text(reference.get("Package"), "Not recorded"),
        "pin_count": int(_number(reference.get("Pin Count"), 0)),
        "impact_categories": impact_categories,
        "recommendations": recommendations[:5],
    }


def _css() -> None:
    st.markdown(
        """
        <style id="cadivor-design-impact-20">
          .cv20-hero{
            border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eef5ff);
            border-radius:24px;padding:25px;margin-bottom:18px;
            box-shadow:0 16px 42px rgba(37,99,235,.07)
          }
          .cv20-eyebrow{font-size:11px;font-weight:900;color:#2563eb;letter-spacing:.11em;text-transform:uppercase}
          .cv20-title{font-size:30px;font-weight:950;color:#0f172a;letter-spacing:-.045em;margin:7px 0}
          .cv20-copy{font-size:14px;font-weight:680;color:#52647a;line-height:1.58;max-width:1080px}
          .cv20-summary{
            border:1px solid #dbe3ef;background:#fff;border-radius:18px;padding:18px;
            box-shadow:0 8px 24px rgba(15,23,42,.04);margin:12px 0 18px
          }
          .cv20-summary-title{font-size:22px;font-weight:950;color:#0f172a;letter-spacing:-.03em}
          .cv20-summary-copy{font-size:13px;font-weight:680;color:#52647a;line-height:1.55;margin-top:7px}
          .cv20-section{font-size:22px;font-weight:950;color:#0f172a;letter-spacing:-.03em;margin:22px 0 5px}
          .cv20-subtitle{font-size:13px;font-weight:650;color:#64748b;margin-bottom:12px}
          .cv20-card{
            border:1px solid #dbe3ef;background:#fff;border-radius:17px;padding:17px;
            margin-bottom:11px;box-shadow:0 8px 24px rgba(15,23,42,.04)
          }
          .cv20-card-title{font-size:16px;font-weight:950;color:#0f172a}
          .cv20-card-copy{font-size:13px;font-weight:680;color:#475569;line-height:1.52;margin-top:6px}
          .cv20-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}
          .cv20-meta span{
            font-size:10px;font-weight:850;color:#1d4ed8;background:#eff6ff;
            border:1px solid #dbeafe;border-radius:999px;padding:5px 8px
          }
          .cv20-impact{
            border-left:4px solid #2563eb;background:#f8fbff;border-radius:0 14px 14px 0;
            padding:14px 16px;margin-bottom:10px
          }
          .cv20-impact strong{font-size:13px;color:#0f172a}
          .cv20-impact p{font-size:12px;color:#52647a;line-height:1.5;margin:5px 0 0}
          .cv20-recommendation{
            border-left:4px solid #2563eb;background:#f8fbff;border-radius:0 14px 14px 0;
            padding:14px 16px;margin-bottom:10px;font-size:13px;font-weight:740;color:#334155;line-height:1.5
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_design_impact(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
    return_analysis_id: str = "",
    return_section: str = "Components",
    has_monitoring: bool = False,
    has_decision: bool = False,
) -> None:
    _css()

    st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)
    cadivor_section_header(
        "Design Impact Analyzer",
        eyebrow="Engineering Change Intelligence",
        description=(
            "See where a component is used, how a sourcing or lifecycle change may affect saved projects, "
            "and which engineering reviews should happen before approving a replacement."
        ),
        icon="git-compare-arrows",
    )

    if return_analysis_id:
        internal_nav_button(
            "← Back to Analysis Details",
            "Analysis Details",
            key="impact_back_to_analysis_details",
            type="secondary",
            analysis_id=return_analysis_id,
            analysis_tab=return_section,
            component=intelligence.get("selected_mpn", ""),
            focus="component-risk",
        )

    options = intelligence["available_mpns"]
    if not options:
        st.info("No component records are available for impact analysis.")
        return

    current = intelligence["selected_mpn"]
    selected = st.selectbox(
        "Component to analyze",
        options,
        index=options.index(current) if current in options else 0,
        key="design_impact_component",
    )

    if selected != current:
        st.session_state["design_impact_mpn"] = selected
        st.rerun()

    st.markdown(
        f"""
        <section class="cv20-summary">
          <div class="cv20-summary-title">{html.escape(current)}</div>
          <div class="cv20-summary-copy">
            {html.escape(intelligence['manufacturer'])} · {html.escape(intelligence['lifecycle'])} ·
            {html.escape(intelligence['package'])}
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    render_kpi_row_safe(
        [
            MetricCard(label="Affected Projects", value=str(intelligence["project_count"]), tone="info", icon="briefcase-business"),
            MetricCard(label="Impact Score", value=f"{intelligence['impact_score']}/100", tone="warning", icon="target"),
            MetricCard(label="Available Stock", value=f"{intelligence['minimum_stock']:,}", tone="monitoring", icon="package"),
            MetricCard(label="Supplier Sources", value=str(intelligence["minimum_sources"]), tone="info", icon="factory"),
            MetricCard(label="Estimated Review", value=f"{intelligence['engineering_hours']} hrs", tone="confidence", icon="clock-3"),
        ],
        columns=4,
    )

    left, right = st.columns([1.35, 1])

    with left:
        st.markdown('<div class="cv20-section">Affected Projects</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="cv20-subtitle">Projects are ordered by lowest health and highest component risk.</div>',
            unsafe_allow_html=True,
        )
        for index, row in enumerate(intelligence["affected_projects"]):
            st.markdown(
                f"""
                <section class="cv20-card">
                  <div class="cv20-card-title">{html.escape(row['Project'])}</div>
                  <div class="cv20-card-copy">
                    This project uses {html.escape(row['Part Number'])} and should be included in any
                    sourcing, replacement, or lifecycle review.
                  </div>
                  <div class="cv20-meta">
                    <span>Project health {row['Project Health']}/100</span>
                    <span>Component risk {row['Risk Score']}/100</span>
                    <span>Quantity {row['Quantity']}</span>
                    <span>{html.escape(row['Lifecycle'])}</span>
                    <span>{row['Supplier Sources']} source(s)</span>
                  </div>
                </section>
                """,
                unsafe_allow_html=True,
            )
            if row["Analysis ID"]:
                internal_nav_button(
                    "Open Project",
                    "Analysis Details",
                    key=f"impact_project_{index}",
                    use_container_width=True,
                    analysis_id=row["Analysis ID"],
                )

    with right:
        st.markdown('<div class="cv20-section">Impact Assessment</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <section class="cv20-card">
              <div class="cv20-card-title">{html.escape(intelligence['impact_level'])} Design Impact</div>
              <div class="cv20-card-copy">
                Cadivor calculated an impact score of {intelligence['impact_score']}/100 using
                cross-project usage, risk, lifecycle, stock, and supplier coverage.
              </div>
              <div class="cv20-card-copy"><b>What this means:</b> higher scores indicate a change is more likely to affect release readiness, because more projects are exposed or the component has weaker lifecycle, inventory, or supplier evidence.</div>
            </section>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="cv20-section">Impact score drivers</div>', unsafe_allow_html=True)
        if intelligence.get("impact_score_capped"):
            st.caption(
                f"The evidence signals total {intelligence['impact_score_raw']} points; "
                "Cadivor caps the reported Impact Score at 100/100."
            )
        for driver in intelligence["impact_score_drivers"]:
            st.markdown(
                f"""
                <div class="cv20-impact">
                  <strong>{html.escape(driver['label'])} · +{int(driver['points'])} points</strong>
                  <p>{html.escape(driver['detail'])}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        for item in intelligence["impact_categories"]:
            st.markdown(
                f"""
                <div class="cv20-impact">
                  <strong>{html.escape(item['Area'])} · {html.escape(item['Severity'])}</strong>
                  <p>{html.escape(item['Finding'])}<br>{html.escape(item['Impact'])}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown('<div class="cv20-section">Recommended Change Plan</div>', unsafe_allow_html=True)
        for recommendation in intelligence["recommendations"]:
            st.markdown(
                f'<div class="cv20-recommendation">✓ {html.escape(recommendation)}</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="cv20-section">Cross-Project Evidence</div>', unsafe_allow_html=True)
    if intelligence["affected_projects"]:
        evidence_df = pd.DataFrame(intelligence["affected_projects"])
        cadivor_engineering_dataframe(
            evidence_df[
                [
                    "Project",
                    "Part Number",
                    "Manufacturer",
                    "Lifecycle",
                    "Package",
                    "Pin Count",
                    "Supplier Sources",
                    "Available Stock",
                    "Risk Score",
                ]
            ],
            column_config={
                "Part Number": st.column_config.TextColumn(width="medium"),
                "Available Stock": st.column_config.NumberColumn(format="%,d"),
                "Risk Score": st.column_config.NumberColumn(format="%d"),
            },
        )

    st.markdown('<div class="cv20-section">Continue the Engineering Review</div>', unsafe_allow_html=True)
    actions = st.columns(4)
    with actions[0]:
        internal_nav_button(
            "Find Replacement",
            "Alternative Finder",
            key="impact_find_replacement",
            use_container_width=True,
            original_part=current,
            source_page="design_impact",
            return_page="Design Impact Analyzer",
            return_mpn=current,
        )
    with actions[1]:
        if has_monitoring:
            internal_nav_button("Open Monitoring", "Monitoring", key="impact_monitoring", use_container_width=True, mpn=current)
        else:
            st.caption("No monitoring record exists for this component yet.")
    with actions[2]:
        if has_decision:
            internal_nav_button("Engineering Decisions", "Engineering Decisions", key="impact_decisions", use_container_width=True, focus_part=current)
        else:
            st.caption("No engineering decision exists for this component yet.")
    with actions[3]:
        internal_nav_button(
            "Portfolio Intelligence",
            "Portfolio Intelligence",
            key="impact_portfolio",
            use_container_width=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)
