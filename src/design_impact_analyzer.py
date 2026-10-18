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

from src.ui.cadivor_design_system import MetricCard, cadivor_section_header, render_kpi_row_safe


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
    """Parse a recorded numeric value without treating missing evidence as zero."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "unknown", "not recorded", "n/a", "—", "-"}:
        return None
    try:
        return float(text.replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _first(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def _impact_level(score: int) -> str:
    if score >= 60:
        return "High"
    if score >= 45:
        return "Moderate"
    return "Low"


def _recorded_risk_rank(value: str) -> int:
    normalized = str(value or "").casefold()
    if "critical" in normalized or "very high" in normalized:
        return 5
    if "high" in normalized:
        return 4
    if "moderate" in normalized or "medium" in normalized or "elevated" in normalized:
        return 3
    if "low" in normalized:
        return 2
    return 0


def build_design_impact(
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    selected_mpn: str = "",
    *,
    select_recommended_when_empty: bool = True,
) -> Dict[str, Any]:
    analyses = list(analyses or [])
    parts = list(parts or [])
    analysis_lookup = {
        _text(row.get("id")): {
            "Project": _text(row.get("project_name") or row.get("name") or row.get("filename"), "Saved BOM"),
            "BOM": _text(row.get("filename") or row.get("file_name"), "Saved BOM"),
            "Health": int(_number(row.get("health_score"), 0)),
            "Updated": _text(row.get("updated_at") or row.get("created_at"), "Not recorded"),
            "Design Phase": _text(_first(row, "design_phase", "project_phase", "phase"), "Not recorded"),
        }
        for row in analyses
    }

    normalized: List[Dict[str, Any]] = []
    for row in parts:
        analysis_id = _text(row.get("analysis_id"))
        meta = analysis_lookup.get(analysis_id, {})
        normalized.append({
            "Analysis ID": analysis_id,
            "Project": meta.get("Project", _text(row.get("project_name"), "Saved BOM")),
            "Project Health": meta.get("Health", 0),
            "Updated": meta.get("Updated", "Not recorded"),
            "BOM": meta.get("BOM", _text(_first(row, "filename", "file_name"), "Saved BOM")),
            "Part Number": _text(_first(row, "mpn", "MPN", "part_number"), "Unknown"),
            "Image URL": _text(_first(row, "image_url", "Image URL", "photo_url"), ""),
            "Description": _text(_first(row, "description", "part_description", "description_raw"), ""),
            "Category": _text(_first(row, "category", "category_raw", "device_type"), ""),
            "Device Subtype": _text(_first(row, "device_subtype", "device_type", "technology", "architecture"), "Not recorded"),
            "Manufacturer": _text(_first(row, "manufacturer", "Manufacturer"), "Unknown"),
            "Lifecycle": _text(_first(row, "lifecycle_status", "Lifecycle Status", "lifecycle"), "Unknown"),
            "Package": _text(_first(row, "package", "Package", "package_type"), "Not recorded"),
            "Pin Count": int(_number(_first(row, "pin_count", "pins", "Pin Count"), 0)),
            "Package Dimensions": _text(_first(row, "package_dimensions", "package_dimension", "body_dimensions", "package_geometry"), "Not recorded"),
            "Design Phase": _text(_first(row, "design_phase", "project_phase", "phase"), meta.get("Design Phase", "Not recorded")),
            "Lead Time Weeks": _optional_number(_first(row, "lead_time_weeks", "Lead Time Weeks", "lead_time")),
            "Datasheet URL": _text(_first(row, "datasheet_url", "datasheet", "datasheet_link"), ""),
            "Source URL": _text(_first(row, "source_url", "source_link", "product_url"), ""),
            "Supplier Sources": _optional_number(_first(row, "supplier_count", "Supplier Count", "authorized_supplier_count")),
            "Available Stock": _optional_number(_first(row, "stock_available", "stock", "Stock Available", "total_market_stock")),
            "Unit Price": _optional_number(_first(row, "unit_price", "Unit Price", "unit_price_usd", "price")),
            "Price Currency": _text(_first(row, "unit_price_currency", "currency", "Currency"), "USD"),
            "Part Updated": _text(_first(row, "last_updated", "updated_at", "modified_at"), "Not recorded"),
            "Risk Score": int(_number(_first(row, "risk_score", "Risk Score"), 0)),
            "Risk Level": _text(_first(row, "risk_level", "Risk Level"), "Unknown"),
            "Quantity": int(_number(_first(row, "quantity", "qty", "required_quantity"), 1)),
        })

    available_mpns = sorted({
        row["Part Number"] for row in normalized
        if row["Part Number"] and row["Part Number"] != "Unknown"
    }, key=str.upper)

    catalog_by_mpn: Dict[str, Dict[str, Any]] = {}
    for row in normalized:
        part_number = row["Part Number"]
        if not part_number or part_number == "Unknown":
            continue
        catalog_row = catalog_by_mpn.setdefault(part_number.casefold(), {
            "Part Number": part_number, "Image URL": "", "Manufacturer Values": set(),
            "Lifecycle Values": set(), "Risk Level Values": set(), "Project Values": set(), "BOM Values": set(),
            "Analysis IDs": set(), "Description": "", "Category": "", "Risk Score": 0,
            "Unit Price": None, "Part Updated": "Not recorded", "Stock Values": [], "Source Values": [],
            "Lead Times": [], "Datasheet URLs": set(), "Source URLs": set(),
        })
        if not catalog_row["Image URL"] and row["Image URL"]:
            catalog_row["Image URL"] = row["Image URL"]
        for field, value in (("Manufacturer Values", row["Manufacturer"]), ("Lifecycle Values", row["Lifecycle"]), ("Risk Level Values", row["Risk Level"])):
            if value and value != "Unknown":
                catalog_row[field].add(value)
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
        if catalog_row["Unit Price"] is None and row["Unit Price"] is not None:
            catalog_row["Unit Price"] = row["Unit Price"]
        if row["Part Updated"] != "Not recorded" and row["Part Updated"] > catalog_row["Part Updated"]:
            catalog_row["Part Updated"] = row["Part Updated"]
        if row["Available Stock"] is not None:
            catalog_row["Stock Values"].append(row["Available Stock"])
        if row["Supplier Sources"] is not None:
            catalog_row["Source Values"].append(row["Supplier Sources"])
        if row["Lead Time Weeks"] is not None:
            catalog_row["Lead Times"].append(row["Lead Time Weeks"])
        if row["Datasheet URL"]:
            catalog_row["Datasheet URLs"].add(row["Datasheet URL"])
        if row["Source URL"]:
            catalog_row["Source URLs"].add(row["Source URL"])
        catalog_row["Risk Score"] = max(catalog_row["Risk Score"], row["Risk Score"])

    component_catalog = []
    for row in catalog_by_mpn.values():
        manufacturers = sorted(row["Manufacturer Values"])
        lifecycles = sorted(row["Lifecycle Values"])
        risk_levels = sorted(row["Risk Level Values"], key=lambda value: (-_recorded_risk_rank(value), value.casefold()))
        projects = sorted(row["Project Values"])
        risk_score = int(row["Risk Score"])
        component_catalog.append({
            "Part Number": row["Part Number"],
            "Image URL": row["Image URL"],
            "Manufacturer": manufacturers[0] if len(manufacturers) == 1 else "Multiple" if manufacturers else "Unknown",
            "Saved BOMs": len(row["Analysis IDs"] or row["BOM Values"]),
            "Projects": len(projects),
            "Project Names": projects,
            "BOM Names": sorted(row["BOM Values"]),
            "Risk Score": risk_score,
            "Risk Level": risk_levels[0] if risk_levels else (_impact_level(risk_score) if risk_score else "Unknown"),
            "Lifecycle": lifecycles[0] if len(lifecycles) == 1 else "Mixed" if lifecycles else "Unknown",
            "Description": row["Description"],
            "Category": row["Category"],
            "Unit Price": row["Unit Price"],
            "Last Updated": row["Part Updated"],
            "Available Stock": min(row["Stock Values"]) if row["Stock Values"] else None,
            "Supplier Sources": min(row["Source Values"]) if row["Source Values"] else None,
            "Lead Time Weeks": max(row["Lead Times"]) if row["Lead Times"] else None,
            "Datasheet URLs": sorted(row["Datasheet URLs"]),
            "Source URLs": sorted(row["Source URLs"]),
            "Search Text": " ".join([row["Part Number"], *manufacturers, *lifecycles, *projects,
                *sorted(row["BOM Values"]), row["Description"], row["Category"]]).casefold(),
        })
    component_catalog.sort(key=lambda row: (-row["Risk Score"], -row["Saved BOMs"], row["Part Number"].upper()))

    if selected_mpn and selected_mpn.casefold() not in {value.casefold() for value in available_mpns}:
        selected_mpn = ""
    if not selected_mpn and select_recommended_when_empty:
        ranked: Dict[str, int] = defaultdict(int)
        for row in normalized:
            score = row["Risk Score"]
            if row["Supplier Sources"] is not None and row["Supplier Sources"] <= 1:
                score += 20
            if row["Available Stock"] is not None and row["Available Stock"] <= 0:
                score += 25
            if any(term in row["Lifecycle"].casefold() for term in ("obsolete", "replacement", "nrnd", "not recommended", "eol")):
                score += 20
            ranked[row["Part Number"]] = max(ranked[row["Part Number"]], score)
        selected_mpn = max(ranked, key=ranked.get) if ranked else ""

    affected = [row for row in normalized if row["Part Number"].casefold() == selected_mpn.casefold()] if selected_mpn else []
    affected.sort(key=lambda row: (row["Project Health"], -row["Risk Score"]))
    reference = affected[0] if affected else {}

    def _bom_key(row: Dict[str, Any]) -> tuple[str, ...]:
        analysis_id = str(row.get("Analysis ID") or "").strip()
        if analysis_id:
            return ("analysis", analysis_id)
        return ("file", str(row.get("Project") or "Saved BOM").strip().casefold(), str(row.get("BOM") or "Saved BOM").strip().casefold())

    affected_bom_count = len({_bom_key(row) for row in affected})
    grouped_by_project: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in affected:
        grouped_by_project[str(row.get("Project") or "Saved BOM").strip().casefold()].append(row)

    affected_projects: List[Dict[str, Any]] = []
    for project_rows in grouped_by_project.values():
        project_rows.sort(key=lambda row: (row.get("Updated") != "Not recorded", str(row.get("Updated") or "")), reverse=True)
        latest_row = project_rows[0]
        analysis_ids = sorted({str(row.get("Analysis ID") or "").strip() for row in project_rows if row.get("Analysis ID")})
        bom_keys = {_bom_key(row) for row in project_rows}
        bom_names = sorted({str(row.get("BOM") or "").strip() for row in project_rows if row.get("BOM")})
        manufacturer_values = sorted({row["Manufacturer"] for row in project_rows if row["Manufacturer"] != "Unknown"})
        lifecycle_values = sorted({row["Lifecycle"] for row in project_rows if row["Lifecycle"] != "Unknown"})
        package_values = sorted({row["Package"] for row in project_rows if row["Package"] not in ("Unknown", "Not recorded")})
        design_phase_values = sorted({row["Design Phase"] for row in project_rows if row["Design Phase"] != "Not recorded"})
        stocks = [row["Available Stock"] for row in project_rows if row["Available Stock"] is not None]
        sources = [row["Supplier Sources"] for row in project_rows if row["Supplier Sources"] is not None]
        lead_times = [row["Lead Time Weeks"] for row in project_rows if row["Lead Time Weeks"] is not None]
        project_row = dict(latest_row)
        saved_bom_count = len(bom_keys)
        project_row.update({
            "Analysis ID": latest_row.get("Analysis ID", ""),
            "Analysis IDs": analysis_ids,
            "BOM Names": bom_names,
            "BOM": bom_names[0] if saved_bom_count == 1 and bom_names else f"{saved_bom_count} saved BOMs",
            "Saved BOMs": saved_bom_count,
            "Project Health": min(int(row.get("Project Health") or 0) for row in project_rows),
            "Risk Score": max(int(row.get("Risk Score") or 0) for row in project_rows),
            "Quantity": sum(max(1, int(row.get("Quantity") or 1)) for row in project_rows),
            "Supplier Sources": min(sources) if sources else None,
            "Available Stock": min(stocks) if stocks else None,
            "Lifecycle": lifecycle_values[0] if len(lifecycle_values) == 1 else "Mixed" if lifecycle_values else "Unknown",
            "Manufacturer": manufacturer_values[0] if len(manufacturer_values) == 1 else "Multiple" if manufacturer_values else "Unknown",
            "Package": package_values[0] if len(package_values) == 1 else "Mixed" if package_values else "Not recorded",
            "Pin Count": max(int(row.get("Pin Count") or 0) for row in project_rows),
            "Design Phase": design_phase_values[0] if len(design_phase_values) == 1 else "Mixed" if design_phase_values else "Not recorded",
            "Lead Time Weeks": max(lead_times) if lead_times else None,
        })
        affected_projects.append(project_row)

    affected_projects.sort(key=lambda row: (row["Project Health"], -row["Risk Score"], row["Project"].casefold()))
    project_count = len(affected_projects)
    total_quantity = sum(max(1, row["Quantity"]) for row in affected)
    recorded_stock = [row["Available Stock"] for row in affected if row["Available Stock"] is not None]
    recorded_sources = [row["Supplier Sources"] for row in affected if row["Supplier Sources"] is not None]
    recorded_lead_times = [row["Lead Time Weeks"] for row in affected if row["Lead Time Weeks"] is not None]
    minimum_stock = min(recorded_stock) if recorded_stock else None
    minimum_sources = min(recorded_sources) if recorded_sources else None
    maximum_risk = max((row["Risk Score"] for row in affected), default=0)
    recorded_risk_levels = sorted(
        {row["Risk Level"] for row in affected if row["Risk Level"] and row["Risk Level"].casefold() != "unknown"},
        key=lambda value: (-_recorded_risk_rank(value), value.casefold()),
    )
    selected_risk_level = recorded_risk_levels[0] if recorded_risk_levels else (_impact_level(maximum_risk) if maximum_risk else "Not recorded")
    lifecycle_exposed = any(any(term in row["Lifecycle"].casefold() for term in ("obsolete", "replacement", "nrnd", "not recommended", "eol")) for row in affected)
    package_unknown = any(row["Package"].casefold() in ("", "unknown", "not recorded", "n/a") for row in affected)
    package_variants = len({row["Package"] for row in affected if row["Package"]})
    pin_variants = len({row["Pin Count"] for row in affected if row["Pin Count"] > 0})

    impact_score_drivers = [
        {"label": "Component risk", "points": maximum_risk, "detail": f"Highest recorded component risk is {maximum_risk}/100."},
        {"label": "Cross-project exposure", "points": min(25, max(0, project_count - 1) * 10), "detail": f"Used in {project_count} unique project(s) across {affected_bom_count} saved BOM(s)."},
        {"label": "Inventory evidence", "points": 20 if minimum_stock is not None and minimum_stock <= 0 else 0,
         "detail": "Inventory coverage is not recorded." if minimum_stock is None else "No available stock is recorded." if minimum_stock <= 0 else f"{int(minimum_stock):,} units are recorded as available."},
        {"label": "Supplier coverage", "points": 15 if minimum_sources is not None and minimum_sources <= 1 else 0,
         "detail": "Supplier coverage is not recorded." if minimum_sources is None else f"Minimum recorded coverage is {int(minimum_sources)} source(s)."},
        {"label": "Lifecycle exposure", "points": 15 if lifecycle_exposed else 0,
         "detail": "Lifecycle exposure is recorded." if lifecycle_exposed else "No lifecycle exposure is recorded."},
    ]
    impact_score_raw = sum(driver["points"] for driver in impact_score_drivers)
    impact_score = min(100, impact_score_raw)
    engineering_hours = max(1, project_count * (2 + (2 if lifecycle_exposed else 0) + (2 if package_variants > 1 or pin_variants > 1 else 0)))

    impact_categories = []
    if project_count > 1:
        impact_categories.append({"Area": "Cross-project usage", "Finding": f"Used in {project_count} unique projects across {affected_bom_count} saved BOMs.", "Impact": "One component decision may affect multiple designs.", "Severity": "High" if project_count >= 3 else "Moderate"})
    if minimum_stock is None:
        impact_categories.append({"Area": "Inventory data", "Finding": "Available stock is not recorded for the selected part.", "Impact": "Confirm authorized inventory before making a sourcing decision.", "Severity": "Informational"})
    elif minimum_stock <= 0:
        impact_categories.append({"Area": "Supply continuity", "Finding": "No available stock is recorded.", "Impact": "A build may be delayed without authorized inventory or a substitute.", "Severity": "High"})
    if minimum_sources is None:
        impact_categories.append({"Area": "Supplier data", "Finding": "Supplier source coverage is not recorded for the selected part.", "Impact": "Confirm authorized source availability before making a sourcing decision.", "Severity": "Informational"})
    elif minimum_sources <= 1:
        impact_categories.append({"Area": "Supplier coverage", "Finding": f"Minimum recorded coverage is {int(minimum_sources)} source(s).", "Impact": "The portfolio has limited sourcing resilience.", "Severity": "High" if minimum_sources == 0 else "Moderate"})
    if lifecycle_exposed:
        impact_categories.append({"Area": "Lifecycle", "Finding": "At least one record shows lifecycle exposure.", "Impact": "Replacement qualification may be required before production.", "Severity": "High"})
    if package_variants > 1 or pin_variants > 1:
        impact_categories.append({"Area": "Engineering compatibility", "Finding": "Package or pin-count records vary across projects.", "Impact": "A replacement may require project-specific validation.", "Severity": "Moderate"})
    if package_unknown:
        impact_categories.append({"Area": "Data completeness", "Finding": "Package data is missing for at least one affected project.", "Impact": "Compatibility confidence is reduced until specifications are confirmed.", "Severity": "Moderate"})
    if not impact_categories:
        impact_categories.append({"Area": "Engineering review", "Finding": "No major cross-project exception is currently recorded.", "Impact": "Continue controlled monitoring and confirm compatibility before change approval.", "Severity": "Low"})

    recommendations = []
    if minimum_stock is None:
        recommendations.append(f"Verify authorized inventory coverage for {selected_mpn} before making a sourcing decision.")
    elif minimum_stock <= 0:
        recommendations.append(f"Secure authorized inventory or identify a qualified substitute for {selected_mpn} before the next build.")
    if minimum_sources is None:
        recommendations.append(f"Confirm authorized supplier coverage for {selected_mpn}.")
    elif minimum_sources <= 1:
        recommendations.append(f"Qualify an additional authorized source for {selected_mpn}.")
    if lifecycle_exposed:
        recommendations.append(f"Start replacement qualification for {selected_mpn} and review every affected project.")
    if project_count > 1:
        recommendations.append(f"Use one coordinated engineering change plan across all {project_count} affected projects.")
    if package_unknown or package_variants > 1 or pin_variants > 1:
        recommendations.append("Confirm package, pin count, and footprint compatibility before approving a replacement.")
    if not recommendations:
        recommendations.append("Continue monitoring and document the approved component selection for future reviews.")

    last_updated_values = [row["Part Updated"] for row in affected if row["Part Updated"] != "Not recorded"]
    last_updated = max(last_updated_values, default=_text(reference.get("Updated"), "Not recorded"))
    unit_price = next((row["Unit Price"] for row in affected if row["Unit Price"] is not None), None)
    return {
        "selected_mpn": selected_mpn, "available_mpns": available_mpns, "component_catalog": component_catalog,
        "affected_projects": affected_projects, "affected_bom_count": affected_bom_count, "project_count": project_count,
        "total_quantity": total_quantity, "minimum_stock": minimum_stock, "minimum_sources": minimum_sources,
        "maximum_lead_time_weeks": max(recorded_lead_times) if recorded_lead_times else None,
        "maximum_risk": maximum_risk, "impact_score": impact_score, "impact_score_raw": impact_score_raw,
        "impact_score_capped": impact_score_raw > 100, "impact_score_drivers": impact_score_drivers,
        "impact_level": _impact_level(impact_score), "engineering_hours": engineering_hours,
        "manufacturer": _text(reference.get("Manufacturer"), "Unknown"), "image_url": _text(reference.get("Image URL"), ""),
        "description": _text(reference.get("Description") or reference.get("description"), ""),
        "category": _text(reference.get("Category") or reference.get("category"), ""),
        "unit_price": unit_price, "price_currency": _text(reference.get("Price Currency"), "USD"),
        "last_updated": last_updated,
        "lifecycle": _text(reference.get("Lifecycle"), "Unknown"), "package": _text(reference.get("Package"), "Not recorded"),
        "pin_count": int(_number(reference.get("Pin Count"), 0)),
        "package_dimensions": _text(reference.get("Package Dimensions"), "Not recorded"),
        "device_subtype": _text(reference.get("Device Subtype"), "Not recorded"),
        "design_phase": _text(reference.get("Design Phase"), "Not recorded"),
        "datasheet_url": _text(reference.get("Datasheet URL"), ""),
        "source_url": _text(reference.get("Source URL"), ""),
        "risk_level": selected_risk_level,
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
          .cv20-page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin:0 0 22px}
          .cv20-breadcrumb{margin:0 0 8px;color:#7b8798;font-size:12px;font-weight:650}
          .cv20-page-title{margin:0;color:#14233c;font-size:32px;font-weight:780;line-height:1.15;letter-spacing:-.035em}
          .cv20-page-copy{margin:8px 0 0;color:#64748b;font-size:14px;line-height:1.5}
          .cv20-selected-part{display:flex;align-items:center;gap:18px;min-width:0;padding:18px 20px;border:1px solid #dbe5f0;border-radius:14px;background:#fff;margin:0 0 16px}
          .cv20-selected-part__image{display:flex;flex:0 0 72px;width:72px;height:72px;align-items:center;justify-content:center;overflow:hidden;border:1px solid #e4ebf4;border-radius:12px;background:#f8fafc}
          .cv20-selected-part__image img{max-width:100%;max-height:100%;object-fit:contain}
          .cv20-selected-part__body{min-width:0;flex:1}
          .cv20-selected-part__mpn{margin:0;color:#14233c;font-size:19px;font-weight:800;line-height:1.25;overflow-wrap:anywhere}
          .cv20-selected-part__description{margin:4px 0 0;color:#617188;font-size:12px;line-height:1.45}
          .cv20-selected-part__facts{display:flex;flex-wrap:wrap;gap:7px 16px;margin-top:10px;color:#45566d;font-size:11px}
          .cv20-selected-part__facts b{color:#253953;font-weight:750}
          .cv20-selected-part__links{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:12px}
          .cv20-selected-part__links a{font-size:12px;font-weight:720;color:#2563eb;text-decoration:none}
          .cv20-selected-part__links a:hover{text-decoration:underline;text-underline-offset:3px}
          .cv20-status{display:inline-flex;padding:3px 9px;border-radius:999px;font-style:normal;font-weight:760}
          .cv20-status--success{color:#147a47;background:#eaf8f0}
          .cv20-status--danger{color:#b42318;background:#fff0ee}
          .cv20-status--muted{color:#596a7e;background:#f1f5f9}
          .cv20-section-title{margin:0 0 4px;color:#17253e;font-size:19px;font-weight:760;letter-spacing:-.02em}
          .cv20-section-copy{margin:0 0 12px;color:#708096;font-size:12px;line-height:1.45}
          .cv20-map-card,.cv20-factors-card,.cv20-project-card{height:100%;padding:18px;border:1px solid #dbe5f0;border-radius:14px;background:#fff}
          .cv20-map-card .cv-ap-card{margin:0;border:0;padding:0;box-shadow:none}
          .cv20-map-card .cv-ap-card h2{margin:0 0 13px;font-size:16px;font-weight:760;color:#17253e}
          .cv20-impact-map__header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin:0 0 12px}
          .cv20-impact-map__header h2{margin:0 0 4px!important}
          .cv20-impact-map__header p{margin:0;color:#708096;font-size:11px;line-height:1.4}
          .cv20-map-legend{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px 12px;max-width:300px}
          .cv20-map-legend__item{display:inline-flex;align-items:center;gap:5px;color:#64748b;font-size:10px;white-space:nowrap}
          .cv20-map-legend__item i{width:8px;height:8px;border-radius:50%;background:var(--legend-color);display:inline-block}
          .cv20-map-card svg{display:block;max-width:100%;height:auto}
          .cv20-factor-list{display:grid;gap:0}
          .cv20-factor{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:12px 0;border-bottom:1px solid #edf1f6}
          .cv20-factor:last-child{border-bottom:0}
          .cv20-factor__label{color:#64748b;font-size:11px;font-weight:650}
          .cv20-factor__value{color:#263850;font-size:12px;font-weight:750;text-align:right;overflow-wrap:anywhere}
          .cv20-factor__value--warning{color:#b45309}.cv20-factor__value--danger{color:#b42318}.cv20-factor__value--success{color:#16804a}.cv20-factor__value--muted{color:#7b8798}
          .cv20-impact-score-note{margin:13px 0 0;padding:11px 12px;border-radius:9px;background:#f3f7fd;color:#65758b;font-size:11px;line-height:1.45}
          .cv20-search-heading{margin:25px 0 10px;color:#17253e;font-size:19px;font-weight:760}
          .cv20-project-table{margin-top:7px}
          .cv20-project-links{display:flex;flex-wrap:wrap;gap:9px;margin-top:12px}
          .cv20-recommendation-list{display:grid;gap:8px;margin-top:10px}
          .cv20-recommendation{margin:0;padding:11px 13px;border:1px solid #e3ebf5;border-left:3px solid #5289e6;border-radius:8px;background:#f9fbfe;color:#3e526d;font-size:12px;line-height:1.45}
          .cv20-browse-summary{margin:2px 0 18px;padding:16px 18px;border:1px solid #dbe5f0;border-radius:12px;background:#fff}
          .cv20-browse-summary strong{color:#1d2f49;font-size:14px}
          .cv20-browse-summary span{display:block;margin-top:4px;color:#64748b;font-size:12px}
          .cv20-selected-note{display:flex;align-items:center;gap:8px;margin:2px 0 14px;padding:10px 13px;border:1px solid #dbeafe;border-radius:10px;background:#eff6ff;color:#365678;font-size:12px}
          .cv20-selected-note strong{color:#173f70}
          .cv20-selected-note span{color:#52677f}
          .cv20-evidence-note{margin:10px 0 0;color:#64748b;font-size:11px;line-height:1.45}
          .st-key-approved_home_page .stButton button[kind="primary"]{min-height:40px;border-radius:8px;background:#2563eb;border-color:#2563eb;font-weight:720}
          .st-key-design_impact_start_review .stButton button::after{content:"→";margin-left:10px;font-size:16px}
          .st-key-design_impact_start_review .stButton button::after{content:"→";margin-left:10px;font-size:16px}
          .st-key-approved_home_page .stButton button[kind="secondary"]{min-height:38px;border-radius:8px;font-weight:680}
          .st-key-approved_home_page [data-testid="stDataFrame"]{border:1px solid #e2e8f0;border-radius:10px;overflow:hidden}
          .cv20-impact-steps{display:flex;align-items:center;gap:14px;min-height:60px;margin:0 0 22px;padding:12px 16px;border:1px solid #cfe0ff;border-radius:12px;background:#f1f6ff;color:#52677f;font-size:12px}
          .cv20-impact-step{display:inline-flex;align-items:center;gap:10px;white-space:nowrap}
          .cv20-impact-step b{display:inline-flex;width:27px;height:27px;align-items:center;justify-content:center;border-radius:50%;background:#d4dce8;color:#fff;font-size:13px}
          .cv20-impact-step--active{color:#1d3f70;font-weight:760}
          .cv20-impact-step--active b{background:#2b66f6}
          .cv20-impact-step-arrow{color:#93a3b8;font-size:18px}
          .cv20-impact-step-note{margin-left:auto;color:#667991;line-height:1.4}
          .cv20-browser-title{margin:0 0 4px;color:#17253e;font-size:19px;font-weight:780}
          .cv20-browser-subtitle{margin:0 0 15px;color:#708096;font-size:11px;line-height:1.4}
          .st-key-design_impact_component_table{overflow:hidden;border:1px solid #dbe5f0;border-radius:14px;background:#fff}
          .st-key-design_impact_component_table_head{padding:0 17px;background:#f8fafc;color:#71829b;font-size:9px;font-weight:850;letter-spacing:.04em;text-transform:uppercase}
          .st-key-design_impact_component_table_head [data-testid="stHorizontalBlock"]{min-height:42px;align-items:center!important;gap:10px!important}
          .st-key-design_impact_component_browser{padding:19px 20px 6px;border:1px solid #dbe5f0;border-radius:15px;background:#fff;box-shadow:0 8px 24px rgba(15,23,42,.035)}
          .st-key-design_impact_home_filters{margin-bottom:13px}
          .st-key-design_impact_component_table_head [data-testid="stMarkdownContainer"] p{margin:0;color:#71829b;font-size:9px;font-weight:850;letter-spacing:.04em;text-transform:uppercase}
          [class*="st-key-design_impact_component_row_"]{padding:0 17px;border-bottom:1px solid #e8edf4;background:#fff}
          [class*="st-key-design_impact_component_row_"]:last-child{border-bottom:0}
          [class*="st-key-design_impact_component_row_"] [data-testid="stHorizontalBlock"]{min-height:82px;align-items:center!important;gap:10px!important}
          [class*="st-key-design_impact_component_row_"] [data-testid="stMarkdownContainer"] p{margin:0;color:#344762;font-size:11px;line-height:1.35}
          [class*="st-key-design_impact_component_row_selected_"]{border-left:4px solid #2d66f5!important;background:#f0f6ff!important}
          [class*="st-key-design_impact_component_row_selected_"] [data-testid="stHorizontalBlock"]{background:#f0f6ff!important}
          [class*="st-key-design_impact_component_row_"] .stButton button{min-height:26px!important;width:26px!important;min-width:26px!important;padding:0!important;border:1px solid #c8d4e3!important;border-radius:50%!important;background:#fff!important;color:#2563eb!important;font-size:13px!important;line-height:1!important}
          [class*="st-key-design_impact_component_row_"] .stButton button[kind="primary"]{border:4px solid #2d66f5!important;background:#fff!important;color:transparent!important}
          .cv20-component-cell{display:flex;align-items:center;gap:11px;min-width:0}
          .cv20-component-cell__image{display:flex;flex:0 0 46px;width:46px;height:46px;align-items:center;justify-content:center;overflow:hidden;border:1px solid #dce6f3;border-radius:10px;background:#f3f7fc;color:#2865ed;font-size:19px}
          .cv20-component-cell__image img{width:100%;height:100%;object-fit:contain}
          .cv20-component-cell__copy{min-width:0}
          .cv20-component-cell__mpn{color:#17253e;font-size:13px;font-weight:800;line-height:1.35;overflow-wrap:anywhere}
          .cv20-component-cell__description{margin-top:3px;color:#708096;font-size:9px;line-height:1.35;overflow-wrap:anywhere}
          .cv20-lifecycle{display:inline-flex;align-items:center;gap:5px;padding:5px 8px;border-radius:999px;background:#f1f5f9;color:#74849a;font-size:9px;font-weight:800;white-space:nowrap}
          .cv20-lifecycle:before{width:7px;height:7px;border-radius:50%;background:currentColor;content:""}
          .cv20-lifecycle--active{background:#eaf8f0;color:#16804a}
          .cv20-lifecycle--alert{background:#fff0ee;color:#c24136}
          .cv20-lifecycle--unknown{background:#f1f5f9;color:#77879d}
          .cv20-selected-for-review{display:flex;align-items:center;gap:26px;min-height:78px;margin:13px 17px 0;padding:12px 16px;border:1px solid #cfe0ff;border-radius:11px;background:#f8fbff}
          .cv20-selected-for-review__lead{min-width:135px}
          .cv20-selected-for-review__eyebrow{color:#2865ed;font-size:9px;font-weight:850;text-transform:uppercase}
          .cv20-selected-for-review__mpn{margin-top:5px;color:#17253e;font-size:14px;font-weight:850}
          .cv20-selected-for-review__item{color:#52677f;font-size:10px;line-height:1.4}
          .cv20-selected-for-review__item strong{color:#263c5b}
          .cv20-home-table-note{margin:9px 17px 11px;color:#8795a8;font-size:9px}
          .cv20-home-filter-row [data-testid="stHorizontalBlock"]{align-items:center!important;gap:12px!important}
          .cv20-home-filter-row [data-testid="stTextInput"] input,.cv20-home-filter-row [data-baseweb="select"]>div{min-height:38px!important;border-color:#d5dfed!important;border-radius:8px!important;background:#fff!important;font-size:11px!important}
          .cv20-home-filter-row [data-testid="stTextInput"] [data-testid="stWidgetLabel"],.cv20-home-filter-row [data-testid="stSelectbox"] [data-testid="stWidgetLabel"]{display:none!important}
          .cv20-home-filter-row{margin:3px 0 15px}
          .st-key-approved_home_page .cv20-page-head{margin-bottom:20px}
          @media(max-width:760px){.cv20-page-head{align-items:stretch;flex-direction:column}.cv20-selected-part{align-items:flex-start}.cv20-page-title{font-size:27px}}
          @media(max-width:900px){.cv20-impact-steps{flex-wrap:wrap}.cv20-impact-step-note{flex-basis:100%;margin-left:0}.cv20-selected-for-review{flex-wrap:wrap;gap:10px}.st-key-design_impact_component_table [data-testid="stHorizontalBlock"]{gap:6px!important}}
          @media(max-width:700px){.st-key-design_impact_component_browser{padding:15px 12px 6px}.st-key-design_impact_component_table_head{display:none}.st-key-design_impact_component_table [data-testid="column"]:nth-child(4),.st-key-design_impact_component_table [data-testid="column"]:nth-child(6),.st-key-design_impact_component_table [data-testid="column"]:nth-child(7),.st-key-design_impact_component_table [data-testid="column"]:nth-child(8){display:none}.cv20-component-cell__image{flex-basis:36px;width:36px;height:36px}.cv20-selected-for-review{margin-left:8px;margin-right:8px;padding:10px}.cv20-impact-steps{gap:8px;padding:10px;font-size:10px}.cv20-impact-step{gap:6px}.cv20-impact-step b{width:22px;height:22px}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _design_impact_kpis(intelligence: Dict[str, Any]) -> List[MetricCard]:
    """Live summary metrics from the saved BOM and recorded sourcing evidence."""
    stock = intelligence.get("minimum_stock")
    sources = intelligence.get("minimum_sources")
    currency = _text(intelligence.get("price_currency"), "USD")
    hours = int(_number(intelligence.get("engineering_hours"), 1))
    return [
        MetricCard(
            label="Affected projects",
            value=str(intelligence["project_count"]),
            detail="Unique saved projects containing this component.",
            tone="info",
            icon="briefcase-business",
            href="#impact-affected-projects",
            action_label="View projects",
        ),
        MetricCard(
            label="Impact score",
            value=f"{intelligence['impact_score']}/100",
            detail="Review priority from saved evidence, not a failure probability.",
            tone="info",
            icon="target",
            href="#impact-key-factors",
            action_label="Review factors",
        ),
        MetricCard(
            label="Available stock",
            value="Not recorded" if stock is None else f"{int(stock):,}",
            detail="Lowest recorded inventory across affected BOM rows.",
            tone="warning" if stock is None or stock <= 0 else "success",
            icon="package",
            href="#impact-key-factors",
            action_label="View evidence",
        ),
        MetricCard(
            label="Supplier sources",
            value="Not recorded" if sources is None else str(int(sources)),
            detail="Minimum source count recorded for the selected component.",
            tone="warning" if sources is None or sources <= 1 else "success",
            icon="shopping-cart",
            href="#impact-key-factors",
            action_label="View coverage",
        ),
        MetricCard(
            label="Estimated review",
            value=f"{hours} hrs",
            detail="Planning estimate based on affected projects and recorded exceptions.",
            tone="monitoring",
            icon="clock-3",
            href="#impact-affected-projects",
            action_label="View projects",
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
    options = intelligence.get("available_mpns") or []
    current = str(intelligence.get("selected_mpn") or "").strip()
    # The approved first screen shows a selected row as the starting point, but
    # keeps the detailed impact packet closed until the reviewer starts it.
    if not review_started and not current and options:
        catalog = intelligence.get("component_catalog") or []
        first_catalog_mpn = catalog[0].get("Part Number") if catalog else ""
        current = str(first_catalog_mpn or options[0] or "").strip()
        if current:
            st.session_state["design_impact_mpn"] = current
    st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)

    header_cols = st.columns([5.2, 1.55, 1.25] if review_started else [6.5, 1.8])
    with header_cols[0]:
        st.markdown(
            '<div class="cv20-breadcrumb">Engineering Intelligence&nbsp; / &nbsp;Design impact</div>'
            '<h1 class="cv20-page-title">Design impact</h1>'
            '<p class="cv20-page-copy">Select a component to see where it is used and review the saved-BOM evidence before making a change.</p>',
            unsafe_allow_html=True,
        )
    if review_started:
        with header_cols[1]:
            if st.button("Update impact review", key="design_impact_update_review", type="primary", use_container_width=True):
                st.session_state["design_impact_review_started_mpn"] = current
                st.rerun()
        with header_cols[2]:
            if st.button("Change component", key="design_impact_change_component", type="secondary", use_container_width=True):
                st.session_state.pop("design_impact_review_started_mpn", None)
                st.rerun()
    else:
        with header_cols[1]:
            if st.button("Start impact review", key="design_impact_start_review", type="primary", use_container_width=True, disabled=not bool(current)):
                st.session_state["design_impact_mpn"] = current
                st.session_state["design_impact_review_started_mpn"] = current
                st.session_state.pop("design_impact_pending_mpn", None)
                st.rerun()

    if return_analysis_id:
        internal_nav_button(
            "← Back to Analysis Details", "Analysis Details", key="impact_back_to_analysis_details",
            type="secondary", analysis_id=return_analysis_id, analysis_tab=return_section,
            component=current, focus="component-risk",
        )

    if not options:
        st.info("No component records are available yet. Upload and analyze a BOM to start a design impact review.")
        internal_nav_button("Upload a BOM", "BOM Analyzer", key="impact_upload_bom", type="primary", use_container_width=True, new_analysis="1")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    def _stock_label(value: Any) -> str:
        return "Not recorded" if value is None else f"{int(value):,} units"

    def _source_label(value: Any) -> str:
        if value is None:
            return "Not recorded"
        return f"{int(value)} source" + ("" if int(value) == 1 else "s")

    from src.part_images import part_image_markup, part_image_source

    selected_photo_markup = part_image_markup(
        intelligence.get("image_url"), current or "Component", size=72, part=intelligence
    )
    unit_price = intelligence.get("unit_price")
    price_currency = _text(intelligence.get("price_currency"), "USD")
    price_label = "Not recorded" if unit_price is None else f"{price_currency} {float(unit_price):,.2f}"
    category = _text(intelligence.get("category"), "Not recorded")
    description = _text(intelligence.get("description"), "Description not recorded")
    last_updated = _text(intelligence.get("last_updated"), "Not recorded")
    package_pins = _text(intelligence.get("package"), "Not recorded")
    pin_count = int(_number(intelligence.get("pin_count"), 0))
    if pin_count > 0:
        package_pins += f" · {pin_count} pins"
    package_dimensions = _text(intelligence.get("package_dimensions"), "Not recorded")
    lifecycle_text = _text(intelligence.get("lifecycle"), "Not recorded")
    lifecycle_class = "success" if lifecycle_text.casefold() == "active" else "danger" if any(term in lifecycle_text.casefold() for term in ("obsolete", "eol", "nrnd", "not recommended")) else "muted"

    def _evidence_link(label: str, raw_url: Any) -> str:
        url = _text(raw_url)
        if not url:
            return ""
        from urllib.parse import urlparse
        if urlparse(url).scheme not in {"http", "https"}:
            return ""
        return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(label)} ↗</a>'

    document_links = "".join(filter(None, [
        _evidence_link("View datasheet", intelligence.get("datasheet_url")),
        _evidence_link("Open source record", intelligence.get("source_url")),
    ]))
    links_markup = f'<div class="cv20-selected-part__links">{document_links}</div>' if document_links else ""
    summary_markup = (
        '<section class="cv20-selected-part">'
        f'<div class="cv20-selected-part__image">{selected_photo_markup}</div>'
        '<div class="cv20-selected-part__body">'
        f'<h2 class="cv20-selected-part__mpn">{html.escape(current)}</h2>'
        f'<div class="cv20-selected-part__description">{html.escape(description)}</div>'
        '<div class="cv20-selected-part__facts">'
        f'<span><b>Manufacturer</b> {html.escape(_text(intelligence.get("manufacturer"), "Not recorded"))}</span>'
        f'<span><b>Category</b> {html.escape(category)}</span>'
        f'<span><b>Device type</b> {html.escape(_text(intelligence.get("device_subtype"), "Not recorded"))}</span>'
        f'<span><b>Package / pins</b> {html.escape(package_pins)}</span>'
        f'<span><b>Package dimensions</b> {html.escape(package_dimensions)}</span>'
        f'<span><b>Lifecycle</b> <i class="cv20-status cv20-status--{lifecycle_class}">{html.escape(lifecycle_text)}</i></span>'
        f'<span><b>Unit price</b> {html.escape(price_label)}</span>'
        f'<span><b>Updated</b> {html.escape(last_updated)}</span>'
        f'</div>{links_markup}</div></section>'
    )

    if not review_started:
        st.markdown(
            '<div class="cv20-impact-steps">'
            '<span class="cv20-impact-step cv20-impact-step--active"><b>1</b> Choose a component</span>'
            '<span class="cv20-impact-step-arrow">›</span>'
            '<span class="cv20-impact-step"><b>2</b> Review impact</span>'
            '<span class="cv20-impact-step-arrow">›</span>'
            '<span class="cv20-impact-step"><b>3</b> Record decision</span>'
            '<span class="cv20-impact-step-note">The review shows impact and evidence; it does not modify the source BOM.</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        catalog = list(intelligence.get("component_catalog") or [])
        normalized_query = ""
        def _browser_status(value: Any) -> str:
            status = _text(value, "Not recorded")
            return "Not recorded" if status.casefold() in {"unknown", "none", "n/a", "not available"} else status

        with st.container(key="design_impact_component_browser"):
            st.markdown(
                '<div class="cv20-browser-title">Components across saved BOMs</div>'
                '<div class="cv20-browser-subtitle">Choose one component, then start its impact review.</div>',
                unsafe_allow_html=True,
            )
            lifecycle_values = sorted({_browser_status(row.get("Lifecycle")) for row in catalog}, key=str.casefold)
            risk_values = sorted({_browser_status(row.get("Risk Level")) for row in catalog}, key=lambda value: (-_recorded_risk_rank(value), value.casefold()))
            project_values = sorted({project for row in catalog for project in (row.get("Project Names") or []) if project}, key=str.casefold)
            filter_options = {
                "design_impact_lifecycle_filter": ["All lifecycle", *lifecycle_values],
                "design_impact_risk_filter": ["All impact levels", *risk_values],
                "design_impact_project_filter": ["All projects", *project_values],
            }
            for filter_key, choices in filter_options.items():
                if st.session_state.get(filter_key) not in choices:
                    st.session_state[filter_key] = choices[0]
            with st.container(key="design_impact_home_filters"):
                filter_cols = st.columns([2.55, 1, 1.05, .9])
                with filter_cols[0]:
                    search_query = st.text_input(
                        "Search components", placeholder="⌕   Search MPN, manufacturer, project, or BOM",
                        key="design_impact_search", label_visibility="collapsed",
                    )
                with filter_cols[1]:
                    lifecycle_filter = st.selectbox("Lifecycle filter", filter_options["design_impact_lifecycle_filter"], key="design_impact_lifecycle_filter", label_visibility="collapsed")
                with filter_cols[2]:
                    risk_filter = st.selectbox("Impact level filter", filter_options["design_impact_risk_filter"], key="design_impact_risk_filter", label_visibility="collapsed")
                with filter_cols[3]:
                    project_filter = st.selectbox("Project filter", filter_options["design_impact_project_filter"], key="design_impact_project_filter", label_visibility="collapsed")

            normalized_query = str(search_query or "").strip().casefold()
            matching_rows = []
            for row in catalog:
                row_lifecycle = _browser_status(row.get("Lifecycle"))
                row_risk = _browser_status(row.get("Risk Level"))
                row_projects = row.get("Project Names") or []
                if normalized_query and normalized_query not in str(row.get("Search Text") or "").casefold():
                    continue
                if lifecycle_filter != "All lifecycle" and row_lifecycle.casefold() != str(lifecycle_filter).casefold():
                    continue
                if risk_filter != "All impact levels" and row_risk.casefold() != str(risk_filter).casefold():
                    continue
                if project_filter != "All projects" and project_filter not in row_projects:
                    continue
                matching_rows.append(row)
            table_rows = matching_rows[:10]
            visible_mpns = {str(row.get("Part Number") or "").casefold() for row in table_rows}
            if table_rows and current.casefold() not in visible_mpns:
                current = str(table_rows[0].get("Part Number") or "").strip()
                if current:
                    st.session_state["design_impact_mpn"] = current
            with st.container(key="design_impact_component_table"):
                with st.container(key="design_impact_component_table_head"):
                    header_columns = st.columns([.22, 2.35, 1.45, 1.42, 1.03, .58, 1.08, .72])
                    with header_columns[1]: st.markdown("COMPONENT")
                    with header_columns[2]: st.markdown("MANUFACTURER")
                    with header_columns[3]: st.markdown("CATEGORY")
                    with header_columns[4]: st.markdown("LIFECYCLE")
                    with header_columns[5]: st.markdown("PROJECTS")
                    with header_columns[6]: st.markdown("STOCK")
                    with header_columns[7]: st.markdown("SOURCES")

                if not table_rows:
                    st.info("No components match these filters. Try a different MPN, lifecycle, impact level, or project.")
                else:
                    for row_index, row in enumerate(table_rows):
                        mpn = str(row.get("Part Number") or "").strip()
                        is_selected = mpn.casefold() == current.casefold()
                        row_key = f"design_impact_component_row_selected_{row_index}" if is_selected else f"design_impact_component_row_{row_index}"
                        with st.container(key=row_key):
                            row_columns = st.columns([.22, 2.35, 1.45, 1.42, 1.03, .58, 1.08, .72])
                            with row_columns[0]:
                                if st.button("●" if is_selected else "○", key=f"design_impact_select_row_{row_index}", help=f"Select {mpn}", type="primary" if is_selected else "secondary"):
                                    if mpn:
                                        st.session_state["design_impact_mpn"] = mpn
                                        st.session_state["design_impact_pending_mpn"] = mpn
                                        st.session_state.pop("design_impact_review_started_mpn", None)
                                        st.rerun()
                            with row_columns[1]:
                                image_src = part_image_source(row.get("Image URL"), mpn, size=46, category=row.get("Category"), part=row)
                                image_markup = f'<img src="{html.escape(str(image_src), quote=True)}" alt="" />' if image_src else "▣"
                                component_markup = (
                                    '<div class="cv20-component-cell"><div class="cv20-component-cell__image">'
                                    f'{image_markup}</div><div class="cv20-component-cell__copy">'
                                    f'<div class="cv20-component-cell__mpn">{html.escape(mpn)}</div>'
                                    f'<div class="cv20-component-cell__description">{html.escape(_text(row.get("Description") or row.get("Category"), "Description not recorded"))}</div>'
                                    '</div></div>'
                                )
                                st.markdown(component_markup, unsafe_allow_html=True)
                            with row_columns[2]: st.markdown(html.escape(_text(row.get("Manufacturer"), "Not recorded")))
                            with row_columns[3]: st.markdown(html.escape(_text(row.get("Category"), "Not recorded")))
                            with row_columns[4]:
                                lifecycle_text = _browser_status(row.get("Lifecycle"))
                                lifecycle_lower = lifecycle_text.casefold()
                                lifecycle_style = "active" if lifecycle_lower == "active" else "alert" if any(word in lifecycle_lower for word in ("obsolete", "eol", "nrnd", "not recommended")) else "unknown"
                                st.markdown(f'<span class="cv20-lifecycle cv20-lifecycle--{lifecycle_style}">{html.escape(lifecycle_text)}</span>', unsafe_allow_html=True)
                            with row_columns[5]: st.markdown(f'**{int(_number(row.get("Projects"), 0))}**')
                            with row_columns[6]: st.markdown(_stock_label(row.get("Available Stock")))
                            with row_columns[7]: st.markdown(_source_label(row.get("Supplier Sources")))

                selected_row = next((row for row in catalog if str(row.get("Part Number") or "").casefold() == current.casefold()), None)
                if selected_row:
                    selected_lifecycle = _browser_status(selected_row.get("Lifecycle"))
                    lifecycle_lower = selected_lifecycle.casefold()
                    lifecycle_color = "#b42318" if any(word in lifecycle_lower for word in ("obsolete", "eol", "nrnd", "not recommended")) else "#16804a" if lifecycle_lower == "active" else "#73839a"
                    coverage = f"Stock: {_stock_label(selected_row.get('Available Stock'))} · Supplier sources: {_source_label(selected_row.get('Supplier Sources'))}"
                    if selected_row.get("Available Stock") is None and selected_row.get("Supplier Sources") is None:
                        coverage = "Stock and supplier coverage are not recorded"
                    elif selected_row.get("Available Stock") is not None and selected_row.get("Supplier Sources") is not None:
                        coverage = f"{_stock_label(selected_row.get('Available Stock'))} available · {_source_label(selected_row.get('Supplier Sources'))}"
                    selected_markup = (
                        '<div class="cv20-selected-for-review"><div class="cv20-selected-for-review__lead">'
                        '<div class="cv20-selected-for-review__eyebrow">Selected for review</div>'
                        f'<div class="cv20-selected-for-review__mpn">{html.escape(current)}</div></div>'
                        f'<div class="cv20-selected-for-review__item"><strong style="color:{lifecycle_color}">Lifecycle: {html.escape(selected_lifecycle)}</strong></div>'
                        f'<div class="cv20-selected-for-review__item">{int(_number(selected_row.get("Projects"), 0))} affected projects</div>'
                        f'<div class="cv20-selected-for-review__item">{html.escape(coverage)}</div></div>'
                    )
                    st.markdown(selected_markup, unsafe_allow_html=True)
                st.markdown('<div class="cv20-home-table-note">Live rows and evidence are sourced from the saved BOM analyses in this workspace.</div>', unsafe_allow_html=True)
        st.caption("A review opens component details, impact mapping, saved-BOM usage, and recorded evidence. Missing supplier or lifecycle data stays marked as not recorded.")
        st.caption("The impact review summarizes saved-BOM evidence. It does not inspect PCB layouts, schematics, firmware, or test plans.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(summary_markup, unsafe_allow_html=True)
    render_kpi_row_safe(_design_impact_kpis(intelligence), columns=5)

    def _factor_row(label: str, value: str, state: str = "muted") -> str:
        return (
            '<div class="cv20-factor"><span class="cv20-factor__label">' + html.escape(label) + '</span>'
            f'<span class="cv20-factor__value cv20-factor__value--{state}">{html.escape(value)}</span></div>'
        )

    stock = intelligence.get("minimum_stock")
    sources = intelligence.get("minimum_sources")
    lifecycle_value = _text(intelligence.get("lifecycle"), "Unknown")
    lifecycle_state = "danger" if any(term in lifecycle_value.casefold() for term in ("obsolete", "eol", "nrnd", "not recommended")) else "success" if lifecycle_value.casefold() == "active" else "muted"
    stock_state = "muted" if stock is None else "danger" if stock <= 0 else "success"
    source_state = "muted" if sources is None else "warning" if sources <= 1 else "success"
    exposure_state = "warning" if int(intelligence.get("project_count") or 0) > 1 else "muted"
    risk_score = int(_number(intelligence.get("maximum_risk"), 0))
    risk_label = _text(intelligence.get("risk_level"), "Not recorded")
    if risk_label.casefold() in {"unknown", "not recorded"} and risk_score:
        risk_label = _impact_level(risk_score)
    lead_time = intelligence.get("maximum_lead_time_weeks")
    lead_time_label = "Not recorded" if lead_time is None else f"Up to {float(lead_time):g} weeks"
    factor_markup = (
        '<div id="impact-key-factors" class="cv20-factors-card">'
        '<h2 class="cv20-section-title">Key factors</h2>'
        '<p class="cv20-section-copy">Evidence currently recorded for this component and its saved BOMs.</p>'
        '<div class="cv20-factor-list">'
        + _factor_row("Supply risk", f"{risk_label} · {risk_score}/100" if risk_score else risk_label, "danger" if _recorded_risk_rank(risk_label) >= 4 else "warning" if _recorded_risk_rank(risk_label) == 3 else "success" if _recorded_risk_rank(risk_label) == 2 else "muted")
        + _factor_row("Lifecycle status", lifecycle_value, lifecycle_state)
        + _factor_row("Lead time", lead_time_label, "warning" if lead_time is not None and lead_time >= 16 else "muted")
        + _factor_row("Price trend", "Not recorded", "muted")
        + _factor_row("Available stock", _stock_label(stock), stock_state)
        + _factor_row("Supplier sources", _source_label(sources), source_state)
        + _factor_row("Alternatives", "Review in replacement comparison", "muted")
        + '</div>'
        + '<p class="cv20-evidence-note">Price history and alternative compatibility are not inferred from the BOM. Review those in the sourcing comparison before acting.</p>'
        + f'<p class="cv20-impact-score-note">Impact score: {intelligence.get("impact_level", "Low")} review priority ({intelligence.get("impact_score", 0)}/100). This is a triage score, not a failure probability.</p>'
        + '</div>'
    )

    left, right = st.columns([1.3, 1], gap="medium")
    with left:
        st.markdown('<div class="cv20-map-card">' + (impact_map_markup or '<h2 class="cv20-section-title">Impact map</h2><p class="cv20-section-copy">No project map data is recorded.</p>') + '</div>', unsafe_allow_html=True)
    with right:
        st.markdown(factor_markup, unsafe_allow_html=True)
        internal_nav_button(
            "Open replacement comparison", "Alternative Finder", key="design_impact_compare_alternatives",
            type="secondary", use_container_width=True, original_part=current,
            source_page="design_impact", return_page="Design Impact Analyzer", return_mpn=current,
        )

    st.markdown('<h2 id="impact-affected-projects" class="cv20-search-heading">Affected projects</h2>', unsafe_allow_html=True)
    st.markdown('<p class="cv20-section-copy">Saved BOM records containing this component, grouped by project.</p>', unsafe_allow_html=True)
    project_rows = []
    for row in intelligence.get("affected_projects") or []:
        bom_names = row.get("BOM Names") or []
        score = int(row.get("Risk Score") or 0)
        row_risk_level = _text(row.get("Risk Level"), "Unknown")
        if row_risk_level.casefold() == "unknown" and score:
            row_risk_level = _impact_level(score)
        project_rows.append({
            "Project": row.get("Project", "Project"),
            "BOM": ", ".join(bom_names) if bom_names else row.get("BOM", "Not recorded"),
            "Usage": f"{int(row.get('Quantity') or 0):,} units",
            "Design phase": _text(row.get("Design Phase"), "Not recorded"),
            "Impact": f"{row_risk_level} · {score}/100" if score else (row_risk_level if row_risk_level.casefold() != "unknown" else "Not recorded"),
        })
    if project_rows:
        st.dataframe(pd.DataFrame(project_rows), hide_index=True, use_container_width=True, key="design_impact_affected_projects")
    else:
        st.info("No saved project records are linked to this component.")

    analysis_rows = [row for row in intelligence.get("affected_projects") or [] if row.get("Analysis ID")]
    if analysis_rows:
        with st.expander("Open an affected BOM", expanded=False):
            for index, row in enumerate(analysis_rows):
                label = f"{row.get('Project', 'Project')} · {row.get('BOM', 'Saved BOM')}"
                internal_nav_button(
                    f"View BOM Risk · {label}", "Analysis Details", key=f"impact_project_{index}",
                    type="secondary", use_container_width=True, analysis_id=row["Analysis ID"],
                )

    with st.expander("Recommendations and score details", expanded=False):
        st.markdown('<h3 class="cv20-section-title">Recommended next steps</h3>', unsafe_allow_html=True)
        recommendation_markup = ''.join(
            f'<div class="cv20-recommendation">{html.escape(str(item))}</div>'
            for item in intelligence.get("recommendations", [])
        )
        st.markdown(f'<div class="cv20-recommendation-list">{recommendation_markup}</div>', unsafe_allow_html=True)
        st.caption("Confirm electrical function, package, footprint, pinout, and design constraints in the source engineering files before approving a component change.")
        if intelligence.get("impact_score_capped"):
            st.caption(f"Driver points total {intelligence['impact_score_raw']}; the displayed score is capped at 100/100.")
        else:
            st.caption(f"The impact score totals {intelligence.get('impact_score', 0)}/100 from the factors below.")
        for driver in intelligence.get("impact_score_drivers", []):
            st.markdown(
                f'<div class="cv20-impact"><strong>{html.escape(driver["label"])} · +{int(driver["points"])} points</strong>'
                f'<p>{html.escape(driver["detail"])}</p></div>', unsafe_allow_html=True,
            )

    st.caption(
        f"Evidence coverage: {intelligence.get('affected_bom_count', 0)} saved BOM(s) across "
        f"{intelligence.get('project_count', 0)} project(s). Package / pins: {package_pins}."
    )
    with st.expander("Continue the engineering workflow", expanded=False):
        actions = st.columns(4)
        with actions[0]:
            internal_nav_button(
                "Find replacement", "Alternative Finder", key="impact_find_replacement", use_container_width=True,
                original_part=current, source_page="design_impact", return_page="Design Impact Analyzer", return_mpn=current,
            )
        with actions[1]:
            if has_monitoring:
                internal_nav_button("Open monitoring", "Monitoring", key="impact_monitoring", use_container_width=True, mpn=current)
            else:
                st.caption("No monitoring record exists for this component yet.")
        with actions[2]:
            if has_decision:
                internal_nav_button("Engineering Decisions", "Engineering Decisions", key="impact_decisions", use_container_width=True, focus_part=current)
            else:
                st.caption("No engineering decision exists for this component yet.")
        with actions[3]:
            internal_nav_button("Portfolio Intelligence", "Portfolio Intelligence", key="impact_portfolio", use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)
