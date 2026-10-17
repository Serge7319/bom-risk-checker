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
import streamlit.components.v1 as components

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
            "BOM": _text(row.get("filename") or row.get("file_name"), "Saved BOM"),
            "Health": int(_number(row.get("health_score"), 0)),
            "Updated": _text(row.get("updated_at") or row.get("created_at"), "Not recorded"),
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
                "Updated": analysis_lookup.get(analysis_id, {}).get("Updated", "Not recorded"),
                "BOM": analysis_lookup.get(analysis_id, {}).get(
                    "BOM", _text(_first(row, "filename", "file_name"), "Saved BOM")
                ),
                "Part Number": _text(_first(row, "mpn", "MPN", "part_number"), "Unknown"),
                "Image URL": _text(_first(row, "image_url", "Image URL", "photo_url"), ""),
                "Description": _text(_first(row, "description", "part_description", "description_raw"), ""),
                "Category": _text(_first(row, "category", "category_raw", "device_type"), ""),
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

    catalog_by_mpn: Dict[str, Dict[str, Any]] = {}
    for row in normalized:
        part_number = row["Part Number"]
        if not part_number or part_number == "Unknown":
            continue
        catalog_key = part_number.casefold()
        catalog_row = catalog_by_mpn.setdefault(
            catalog_key,
            {
                "Part Number": part_number,
                "Image URL": "",
                "Manufacturer Values": set(),
                "Lifecycle Values": set(),
                "Project Values": set(),
                "BOM Values": set(),
                "Analysis IDs": set(),
                "Description": "",
                "Category": "",
                "Risk Score": 0,
            },
        )
        if not catalog_row["Image URL"] and row["Image URL"]:
            catalog_row["Image URL"] = row["Image URL"]
        if row["Manufacturer"] and row["Manufacturer"] != "Unknown":
            catalog_row["Manufacturer Values"].add(row["Manufacturer"])
        if row["Lifecycle"] and row["Lifecycle"] != "Unknown":
            catalog_row["Lifecycle Values"].add(row["Lifecycle"])
        if row["Project"]:
            catalog_row["Project Values"].add(row["Project"])
        if row["BOM"]:
            catalog_row["BOM Values"].add(row["BOM"])
        if row["Analysis ID"]:
            catalog_row["Analysis IDs"].add(row["Analysis ID"])
        if not catalog_row["Description"] and row["Description"]:
            catalog_row["Description"] = row["Description"]
        if not catalog_row["Category"] and row["Category"]:
            catalog_row["Category"] = row["Category"]
        catalog_row["Risk Score"] = max(catalog_row["Risk Score"], row["Risk Score"])

    component_catalog = []
    for row in catalog_by_mpn.values():
        manufacturer_values = sorted(row["Manufacturer Values"])
        lifecycle_values = sorted(row["Lifecycle Values"])
        project_values = sorted(row["Project Values"])
        bom_count = len(row["Analysis IDs"] or row["BOM Values"])
        risk_score = int(row["Risk Score"])
        component_catalog.append(
            {
                "Part Number": row["Part Number"],
                "Image URL": row["Image URL"],
                "Manufacturer": (
                    manufacturer_values[0]
                    if len(manufacturer_values) == 1
                    else "Multiple" if manufacturer_values else "Unknown"
                ),
                "Saved BOMs": bom_count,
                "Projects": len(project_values),
                "Project Names": project_values,
                "BOM Names": sorted(row["BOM Values"]),
                "Risk Score": risk_score,
                "Risk Level": _impact_level(risk_score),
                "Lifecycle": (
                    lifecycle_values[0]
                    if len(lifecycle_values) == 1
                    else "Mixed" if lifecycle_values else "Unknown"
                ),
                "Description": row["Description"],
                "Category": row["Category"],
                "Search Text": " ".join(
                    [
                        row["Part Number"],
                        *manufacturer_values,
                        *lifecycle_values,
                        *project_values,
                        *sorted(row["BOM Values"]),
                        row["Description"],
                        row["Category"],
                    ]
                ).casefold(),
            }
        )
    component_catalog.sort(
        key=lambda row: (-row["Risk Score"], -row["Saved BOMs"], row["Part Number"].upper())
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

    def _bom_key(row: Dict[str, Any]) -> tuple[str, ...]:
        analysis_id = str(row.get("Analysis ID") or "").strip()
        if analysis_id:
            return ("analysis", analysis_id)
        return (
            "file",
            str(row.get("Project") or "Saved BOM").strip().casefold(),
            str(row.get("BOM") or "Saved BOM").strip().casefold(),
        )

    affected_bom_count = len({_bom_key(row) for row in affected})
    grouped_by_project: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in affected:
        project_key = str(row.get("Project") or "Saved BOM").strip().casefold()
        grouped_by_project[project_key].append(row)

    affected_projects: List[Dict[str, Any]] = []
    for project_rows in grouped_by_project.values():
        project_rows.sort(
            key=lambda row: (
                row.get("Updated") != "Not recorded",
                str(row.get("Updated") or ""),
            ),
            reverse=True,
        )
        latest_row = project_rows[0]
        analysis_ids = sorted(
            {str(row.get("Analysis ID") or "").strip() for row in project_rows if row.get("Analysis ID")}
        )
        bom_keys = {_bom_key(row) for row in project_rows}
        bom_names = sorted(
            {str(row.get("BOM") or "").strip() for row in project_rows if row.get("BOM")}
        )
        manufacturer_values = sorted(
            {str(row.get("Manufacturer") or "").strip() for row in project_rows
             if row.get("Manufacturer") and row.get("Manufacturer") != "Unknown"}
        )
        lifecycle_values = sorted(
            {str(row.get("Lifecycle") or "").strip() for row in project_rows
             if row.get("Lifecycle") and row.get("Lifecycle") != "Unknown"}
        )
        package_values = sorted(
            {str(row.get("Package") or "").strip() for row in project_rows
             if row.get("Package") and row.get("Package") not in ("Unknown", "Not recorded")}
        )
        project_row = dict(latest_row)
        saved_bom_count = len(bom_keys)
        project_row.update(
            {
                "Analysis ID": latest_row.get("Analysis ID", ""),
                "Analysis IDs": analysis_ids,
                "BOM Names": bom_names,
                "BOM": (
                    bom_names[0]
                    if saved_bom_count == 1 and bom_names
                    else f"{saved_bom_count} saved BOMs"
                ),
                "Saved BOMs": saved_bom_count,
                "Project Health": min(int(row.get("Project Health") or 0) for row in project_rows),
                "Risk Score": max(int(row.get("Risk Score") or 0) for row in project_rows),
                "Quantity": sum(max(1, int(row.get("Quantity") or 1)) for row in project_rows),
                "Supplier Sources": min(int(row.get("Supplier Sources") or 0) for row in project_rows),
                "Available Stock": min(int(row.get("Available Stock") or 0) for row in project_rows),
                "Lifecycle": (
                    lifecycle_values[0]
                    if len(lifecycle_values) == 1
                    else "Mixed" if lifecycle_values else "Unknown"
                ),
                "Manufacturer": (
                    manufacturer_values[0]
                    if len(manufacturer_values) == 1
                    else "Multiple" if manufacturer_values else "Unknown"
                ),
                "Package": (
                    package_values[0]
                    if len(package_values) == 1
                    else "Mixed" if package_values else "Not recorded"
                ),
                "Pin Count": max(int(row.get("Pin Count") or 0) for row in project_rows),
            }
        )
        affected_projects.append(project_row)

    affected_projects.sort(key=lambda row: (row["Project Health"], -row["Risk Score"], row["Project"].casefold()))
    project_count = len(affected_projects)
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
                f"Used in {project_count} unique project(s) across {affected_bom_count} saved BOM(s)."
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
            "Finding": f"Used in {project_count} unique projects across {affected_bom_count} saved BOMs.",
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
        "component_catalog": component_catalog,
        "affected_projects": affected_projects,
        "affected_bom_count": affected_bom_count,
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
        "image_url": _text(reference.get("Image URL"), ""),
        "description": _text(reference.get("Description") or reference.get("description"), ""),
        "category": _text(reference.get("Category") or reference.get("category"), ""),
        "lifecycle": _text(reference.get("Lifecycle"), "Unknown"),
        "package": _text(reference.get("Package"), "Not recorded"),
        "pin_count": int(_number(reference.get("Pin Count"), 0)),
        "impact_categories": impact_categories,
        "recommendations": recommendations[:5],
    }


def _css() -> None:
    st.markdown(
        """
        <style id="cadivor-design-impact-20" data-cadivor-layout-style="true">
          .st-key-approved_home_page{
            box-sizing:border-box!important;width:100%!important;max-width:1440px!important;
            margin-left:auto!important;margin-right:auto!important;padding:48px 0 28px!important
          }
          .st-key-approved_home_page > [data-testid="stVerticalBlock"]{gap:22px!important}
          @media(max-width:1600px){.st-key-approved_home_page{padding:36px 0 24px!important}}
          @media(max-width:1250px){.st-key-approved_home_page{padding:22px 0 20px!important}}
          @media(max-width:700px){.st-key-approved_home_page{padding:24px 0!important}}
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
          .cv20-detail-anchor{scroll-margin-top:100px}
          .cv-ap-card{background:#fff;border:1px solid #dbe3ef;border-radius:16px;padding:8px 8px 4px;margin:10px 0 16px;box-shadow:0 8px 24px rgba(15,23,42,.04)}
          .cv-ap-card h2{font-size:16px;font-weight:900;color:#0f172a;margin:4px 6px 8px}
          .cv20-section{font-size:22px;font-weight:950;color:#0f172a;letter-spacing:-.03em;margin:22px 0 5px}
          .cv20-subtitle{font-size:13px;font-weight:650;color:#64748b;margin-bottom:12px}
          .cv20-card{
            border:1px solid #dbe3ef;background:#fff;border-radius:17px;padding:17px;
            margin-bottom:11px;box-shadow:0 8px 24px rgba(15,23,42,.04)
          }
          .cv20-card-title{font-size:16px;font-weight:950;color:#0f172a}
          .cv20-card-copy{font-size:13px;font-weight:680;color:#475569;line-height:1.52;margin-top:6px}
          .cv20-bom-list{font-size:12px!important;font-weight:600!important;color:#64748b!important;overflow-wrap:anywhere}
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
          .cv20-validation{
            border:1px solid #cbdcf4;background:#f8fbff;border-radius:16px;padding:16px 18px;
            margin:10px 0 14px
          }
          .cv20-validation strong{display:block;color:#0f172a;font-size:13px;margin:0 0 5px}
          .cv20-validation p,.cv20-validation li{
            color:#52647a;font-size:12px;line-height:1.5
          }
          .cv20-validation p{margin:4px 0 8px}
          .cv20-validation ul{margin:6px 0 0;padding-left:18px}
          .cv20-validation li{margin:4px 0}
          .cv20-score-expander{border:1px solid #dbe3ef;border-radius:14px;padding:2px 14px;background:#fff}
          .cv20-score-expander summary{font-weight:850;color:#1e293b}
        
        </style>
        """,
        unsafe_allow_html=True,
    )


def _design_impact_kpis(intelligence: Dict[str, Any]) -> List[MetricCard]:
    """Explain the saved-BOM measures and provide direct links to their evidence."""
    return [
        MetricCard(
            label="Projects using this part",
            value=str(intelligence["project_count"]),
            detail="Unique saved project names containing this part.",
            tone="info",
            icon="briefcase-business",
            href="#impact-affected-projects",
            action_label="View projects",
        ),
        MetricCard(
            label="Saved BOM analyses",
            value=str(intelligence["affected_bom_count"]),
            detail="Distinct saved analyses that include this part.",
            tone="info",
            icon="folder-open",
            href="#impact-affected-projects",
            action_label="View BOM usage",
        ),
        MetricCard(
            label="Review priority",
            value=f"{intelligence['impact_score']}/100",
            detail="Triage score from saved evidence, not a failure probability.",
            tone="warning",
            icon="target",
            href="#impact-score-drivers",
            action_label="See score factors",
        ),
        MetricCard(
            label="Recorded BOM quantity",
            value=f"{intelligence['total_quantity']:,}",
            detail="Sum of this part's quantities across the saved BOM analyses.",
            tone="monitoring",
            icon="package",
            href="#impact-affected-projects",
            action_label="View quantities",
        ),
    ]


def _impact_details_scroll_script() -> str:
    """Return the small browser-side scroll used after a component row is selected."""
    return """
    <script>
    (() => {
      const parentWindow = window.parent;
      const doc = parentWindow.document;
      const scrollToDetails = () => {
        const target = doc.getElementById("design-impact-review-details");
        if (!target) return;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        try { target.focus({ preventScroll: true }); } catch (error) {}
      };
      [0, 100, 320, 700, 1200].forEach((delay) =>
        parentWindow.setTimeout(scrollToDetails, delay)
      );
    })();
    </script>
    """


def render_design_impact(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
    return_analysis_id: str = "",
    return_section: str = "Components",
    has_monitoring: bool = False,
    has_decision: bool = False,
    review_started: bool = False,
    impact_map_markup: str = "",
) -> None:
    _css()
    with st.container(key="approved_home_page"):
        _render_design_impact_workspace(
            intelligence=intelligence,
            internal_nav_button=internal_nav_button,
            return_analysis_id=return_analysis_id,
            return_section=return_section,
            has_monitoring=has_monitoring,
            has_decision=has_decision,
            review_started=review_started,
            impact_map_markup=impact_map_markup,
        )


def _render_design_impact_workspace(
    *,
    intelligence: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
    return_analysis_id: str = "",
    return_section: str = "Components",
    has_monitoring: bool = False,
    has_decision: bool = False,
    review_started: bool = False,
    impact_map_markup: str = "",
) -> None:
    st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)
    cadivor_section_header(
        "Design Impact",
        eyebrow="Where used",
        description="Select a part to see where it is used across saved BOMs and review its recorded risk, lifecycle, inventory, and supplier evidence.",
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
        st.info("No component records are available yet. Upload and analyze a BOM to start a design impact review.")
        internal_nav_button(
            "Upload a BOM",
            "BOM Analyzer",
            key="impact_upload_bom",
            type="primary",
            use_container_width=True,
            new_analysis="1",
        )
        return

    current = intelligence["selected_mpn"]
    if impact_map_markup:
        st.markdown(impact_map_markup, unsafe_allow_html=True)
    else:
        st.info("Select a component below to preview its saved-BOM impact.")

    st.markdown(
        '<div class="cv20-section">Components across saved BOMs</div>',
        unsafe_allow_html=True,
    )
    search_query = st.text_input(
        "Search components",
        placeholder="Search MPN, manufacturer, project, or BOM",
        key="design_impact_search",
    )
    catalog = list(intelligence.get("component_catalog") or [])
    normalized_query = str(search_query or "").strip().casefold()
    matching_rows = [
        row
        for row in catalog
        if not normalized_query or normalized_query in str(row.get("Search Text") or "").casefold()
    ]
    table_rows = matching_rows[:10]

    if not matching_rows:
        st.info("No components match that search. Try another MPN, project, or BOM name.")
    else:
        st.caption(
            f"Showing {len(table_rows)} of {len(matching_rows)} matching components. "
            "Select a row to load its assessment below; the page will scroll to the results."
        )
        from src.part_images import part_image_source

        display_rows = [
            {
                "Part photo": part_image_source(
                    row.get("Image URL"),
                    row.get("Part Number"),
                    size=64,
                    category=row.get("Category"),
                    part=row,
                ),
                "Part Number": row.get("Part Number", ""),
                "Manufacturer": row.get("Manufacturer", "Unknown"),
                "Saved BOMs": int(row.get("Saved BOMs", 0)),
                "Projects": int(row.get("Projects", 0)),
                "Risk": f"{row.get('Risk Level', 'Unknown')} · {int(row.get('Risk Score', 0))}/100",
            }
            for row in table_rows
        ]
        query_key = normalized_query or "all"
        table_event = st.dataframe(
            pd.DataFrame(display_rows),
            column_config={
                "Part photo": st.column_config.ImageColumn("Component", width="small"),
                "Part Number": st.column_config.TextColumn("MPN", width="medium"),
                "Manufacturer": st.column_config.TextColumn(width="medium"),
                "Saved BOMs": st.column_config.NumberColumn(format="%d"),
                "Projects": st.column_config.NumberColumn(format="%d"),
                "Risk": st.column_config.TextColumn(width="small"),
            },
            hide_index=True,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"design_impact_component_table_{query_key}",
        )
        selection = getattr(table_event, "selection", None)
        if selection is None and isinstance(table_event, dict):
            selection = table_event.get("selection")
        if isinstance(selection, dict):
            selected_rows = selection.get("rows") or []
        else:
            selected_rows = getattr(selection, "rows", []) or []
        if selected_rows:
            selected_index = int(selected_rows[0])
            if 0 <= selected_index < len(table_rows):
                selected_mpn = str(table_rows[selected_index].get("Part Number") or "").strip()
                if selected_mpn and (
                    not review_started
                    or selected_mpn.casefold() != str(current or "").casefold()
                ):
                    st.session_state["design_impact_mpn"] = selected_mpn
                    st.session_state.pop("design_impact_pending_mpn", None)
                    st.session_state["design_impact_scroll_pending"] = True
                    st.rerun()

    st.caption(
        "Click any component row to open or update its review. "
        "The results below use saved-BOM evidence and do not inspect PCB layouts, schematics, firmware, or test plans."
    )

    if not review_started:
        return

    from src.part_images import part_image_markup
    selected_photo_markup = part_image_markup(
        intelligence.get("image_url"), current, size=76, part=intelligence
    )
    st.markdown(
        f"""
        <div id="design-impact-review-details" class="cv20-detail-anchor" tabindex="-1"></div>
        <section class="cv20-summary cv20-summary--with-photo">
          {selected_photo_markup}
          <div>
          <div class="cv20-summary-title">{html.escape(current)}</div>
          <div class="cv20-summary-copy">
            {html.escape(intelligence['manufacturer'])} · {html.escape(intelligence['lifecycle'])} ·
            {html.escape(intelligence['package'])}
          </div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    render_kpi_row_safe(_design_impact_kpis(intelligence), columns=4)

    left, right = st.columns([1.35, 1])

    with left:
        st.markdown('<div id="impact-affected-projects" class="cv20-section">Affected Projects</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="cv20-subtitle">One summary per project; repeated part rows are combined across its saved BOMs.</div>',
            unsafe_allow_html=True,
        )
        for index, row in enumerate(intelligence["affected_projects"]):
            saved_bom_count = int(row.get("Saved BOMs", 0))
            bom_names = ", ".join(row.get("BOM Names") or [])
            st.markdown(
                f"""
                <section class="cv20-card">
                  <div class="cv20-card-title">{html.escape(row['Project'])}</div>
                  <div class="cv20-card-copy">
                    {html.escape(row['Part Number'])} appears in {saved_bom_count} saved BOM
                    {'analysis' if saved_bom_count == 1 else 'analyses'} for this project.
                  </div>
                  <div class="cv20-card-copy cv20-bom-list">
                    BOM files: {html.escape(bom_names or 'Name not recorded')}
                  </div>
                  <div class="cv20-meta">
                    <span>{saved_bom_count} saved BOM(s)</span>
                    <span>Health {row['Project Health']}/100</span>
                    <span>Highest part risk {row['Risk Score']}/100</span>
                    <span>Recorded quantity {row['Quantity']}</span>
                    <span>{html.escape(row['Lifecycle'])}</span>
                    <span>{row['Supplier Sources']} source(s)</span>
                  </div>
                </section>
                """,
                unsafe_allow_html=True,
            )
            if row.get("Analysis ID"):
                internal_nav_button(
                    "View BOM Risk",
                    "Analysis Details",
                    key=f"impact_project_{index}",
                    use_container_width=True,
                    analysis_id=row["Analysis ID"],
                )

    with right:
        st.markdown('<div id="impact-assessment" class="cv20-section">Impact Assessment</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <section class="cv20-card">
              <div class="cv20-card-title">{html.escape(intelligence['impact_level'])} review priority</div>
              <div class="cv20-card-copy">
                This score is a portfolio triage measure based on saved-BOM risk, supply, lifecycle, and cross-project evidence.
                It helps decide what to review first; it is not a failure probability or a design simulation.
              </div>
              <div class="cv20-card-copy">
                <b>Assessment scope:</b> Cadivor can show where this part appears and summarize recorded component risk,
                quantity, stock, supplier coverage, lifecycle, package, and pin-count data.
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="cv20-section">Recommended Change Plan</div>', unsafe_allow_html=True)
        for recommendation in intelligence["recommendations"]:
            st.markdown(
                f'<div class="cv20-recommendation">✓ {html.escape(recommendation)}</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="cv20-section">Design validation required</div>', unsafe_allow_html=True)
        st.markdown(
            """
            <section class="cv20-validation">
              <strong>Use this review to prioritize work, then validate the change in the source design.</strong>
              <p>Saved BOM records do not include the schematic, PCB layout, netlist, firmware, or mechanical constraints needed to calculate redesign impact.</p>
              <ul>
                <li>Compare the candidate's electrical ratings and function with the original part.</li>
                <li>Confirm package, pinout, footprint, and clearance in every affected project.</li>
                <li>Check thermal, mechanical, firmware, test, and manufacturing effects where applicable.</li>
                <li>Record engineering approval and update each affected BOM before release.</li>
              </ul>
            </section>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div id="impact-score-drivers" class="cv20-detail-anchor"></div>', unsafe_allow_html=True)
        with st.expander("Why this score", expanded=False):
            if intelligence.get("impact_score_capped"):
                st.caption(
                    f"The driver points total {intelligence['impact_score_raw']}; "
                    "the displayed score is capped at 100/100."
                )
            else:
                st.caption(
                    f"The driver points total {intelligence['impact_score']}/100."
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

        scored_areas = {
            "Cross-project usage",
            "Supply continuity",
            "Supplier coverage",
            "Lifecycle",
            "Engineering review",
        }
        additional_checks = [
            item for item in intelligence["impact_categories"]
            if item.get("Area") not in scored_areas
        ]
        if additional_checks:
            st.markdown('<div class="cv20-section">Additional engineering checks (not scored)</div>', unsafe_allow_html=True)
            for item in additional_checks:
                st.markdown(
                    f"""
                    <div class="cv20-impact">
                      <strong>{html.escape(item['Area'])} · {html.escape(item['Severity'])}</strong>
                      <p>{html.escape(item['Finding'])}<br>{html.escape(item['Impact'])}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    st.caption(
        f"Coverage is summarized across {intelligence['affected_bom_count']} saved BOM(s) "
        f"and {intelligence['project_count']} unique project(s)."
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

    if st.session_state.pop("design_impact_scroll_pending", False):
        components.html(_impact_details_scroll_script(), height=0, width=0)

    st.markdown("</div>", unsafe_allow_html=True)
