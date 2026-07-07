"""
Cadivor / BOM Risk Checker
Milestone 3 — BOM Intelligence 2.0

Drop this file into: src/bom_intelligence.py

What this adds:
- Advanced multi-factor risk dimensions
- Engineering-weighted alternative ranking
- Compatibility explanation
- Supplier intelligence
- Manufacturer health scoring
- BOM-level intelligence
- Action recommendations
- Risk forecasting
- Executive summary generation
- Engineering insights

This module is intentionally defensive: it works with partial distributor data,
unknown fields, and the current BOM analyzer dataframe format.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple
import math
import re

import pandas as pd


# -----------------------------------------------------------------------------
# Basic helpers
# -----------------------------------------------------------------------------

HIGH_RISK_LIFECYCLE_TERMS = (
    "obsolete",
    "end of life",
    "eol",
    "not recommended",
    "nrnd",
    "discontinued",
    "last time buy",
)

MEDIUM_RISK_LIFECYCLE_TERMS = (
    "unknown",
    "limited",
    "mature",
    "replacement",
    "not for new design",
)

HEALTHY_LIFECYCLE_TERMS = (
    "active",
    "new",
    "production",
    "recommended",
)

KNOWN_STRONG_MANUFACTURERS = {
    "texas instruments",
    "ti",
    "analog devices",
    "adi",
    "microchip",
    "microchip technology",
    "stmicroelectronics",
    "st",
    "nxp",
    "infineon",
    "onsemi",
    "on semiconductor",
    "renesas",
    "rohm",
    "vishay",
    "yageo",
    "murata",
    "tdk",
    "kemet",
    "kyocera avx",
    "te connectivity",
    "molex",
    "amphenol",
    "bourns",
    "panasonic",
    "samsung electro-mechanics",
    "kyocera",
}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("$", "").strip()
            if value == "":
                return default
        result = float(value)
        if math.isnan(result):
            return default
        return result
    except Exception:
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _contains_any(text: Any, terms: Iterable[str]) -> bool:
    lower = _clean_text(text).lower()
    return any(term in lower for term in terms)


def _risk_level(score: float) -> str:
    if score >= 75:
        return "High"
    if score >= 45:
        return "Medium"
    return "Low"


def _health_label(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Healthy"
    if score >= 60:
        return "Moderate Risk"
    if score >= 40:
        return "High Risk"
    return "Critical"


def _score_to_stars(score: float) -> str:
    filled = int(round(_clamp(score) / 20))
    return "★" * filled + "☆" * (5 - filled)


def _column(df: pd.DataFrame, *names: str) -> Optional[str]:
    normalized = {c.lower().strip(): c for c in df.columns}
    for name in names:
        key = name.lower().strip()
        if key in normalized:
            return normalized[key]
    return None


def _get(row: Any, *names: str, default: Any = "") -> Any:
    if isinstance(row, dict):
        lower = {str(k).lower().strip(): k for k in row.keys()}
        for name in names:
            key = name.lower().strip()
            if key in lower:
                return row.get(lower[key], default)
        return default

    for name in names:
        try:
            if name in row:
                return row[name]
        except Exception:
            pass
    return default


# -----------------------------------------------------------------------------
# 3.1 Advanced Risk Engine
# -----------------------------------------------------------------------------

@dataclass
class RiskDimensions:
    lifecycle_risk: float
    supply_chain_risk: float
    inventory_risk: float
    lead_time_risk: float
    single_source_risk: float
    compliance_risk: float
    manufacturer_risk: float
    overall_risk: float
    risk_level: str
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["dimension_stars"] = {
            "Lifecycle": _score_to_stars(self.lifecycle_risk),
            "Supply Chain": _score_to_stars(self.supply_chain_risk),
            "Inventory": _score_to_stars(self.inventory_risk),
            "Lead Time": _score_to_stars(self.lead_time_risk),
            "Single Source": _score_to_stars(self.single_source_risk),
            "Compliance": _score_to_stars(self.compliance_risk),
            "Manufacturer": _score_to_stars(self.manufacturer_risk),
        }
        return data


def calculate_advanced_risk(part: Dict[str, Any]) -> Dict[str, Any]:
    lifecycle = _get(part, "Lifecycle Status", "lifecycle_status", default="Unknown")
    total_stock = _num(_get(part, "Total Market Stock", "Stock Available", "stock_available", "stock_total", default=0))
    supplier_count = _num(_get(part, "Supplier Count", "supplier_count", default=0))
    lead_time = _num(_get(part, "Lead Time Weeks", "lead_time_weeks", default=0))
    compliance = _clean_text(_get(part, "Compliance", "RoHS", "rohs", default="Unknown"))
    manufacturer = _clean_text(_get(part, "Manufacturer", "manufacturer", default=""))

    reasons: List[str] = []

    if _contains_any(lifecycle, HIGH_RISK_LIFECYCLE_TERMS):
        lifecycle_risk = 95
        reasons.append("Lifecycle status indicates obsolete, EOL, NRND, or discontinued risk.")
    elif _contains_any(lifecycle, MEDIUM_RISK_LIFECYCLE_TERMS):
        lifecycle_risk = 60
        reasons.append("Lifecycle status requires verification before production release.")
    elif _contains_any(lifecycle, HEALTHY_LIFECYCLE_TERMS):
        lifecycle_risk = 10
    else:
        lifecycle_risk = 55
        reasons.append("Lifecycle status is unclear or unavailable.")

    if supplier_count <= 0:
        supply_chain_risk = 95
        reasons.append("No distributor source was confirmed.")
    elif supplier_count == 1:
        supply_chain_risk = 75
        reasons.append("Only one supplier source is visible.")
    elif supplier_count == 2:
        supply_chain_risk = 40
    else:
        supply_chain_risk = 15

    if total_stock <= 0:
        inventory_risk = 95
        reasons.append("No available market stock was found.")
    elif total_stock < 100:
        inventory_risk = 75
        reasons.append("Available stock is very limited.")
    elif total_stock < 1000:
        inventory_risk = 45
    else:
        inventory_risk = 10

    if lead_time <= 0:
        lead_time_risk = 35
    elif lead_time >= 26:
        lead_time_risk = 90
        reasons.append("Lead time is very long.")
    elif lead_time >= 12:
        lead_time_risk = 65
        reasons.append("Lead time is elevated.")
    elif lead_time >= 6:
        lead_time_risk = 35
    else:
        lead_time_risk = 10

    if supplier_count <= 1:
        single_source_risk = 90
    elif supplier_count == 2:
        single_source_risk = 55
    else:
        single_source_risk = 15

    if compliance.lower() in {"yes", "y", "true", "rohs", "rohs compliant", "compliant"}:
        compliance_risk = 10
    elif compliance.lower() in {"no", "false", "non-compliant", "not compliant"}:
        compliance_risk = 90
        reasons.append("Compliance field suggests a possible RoHS/compliance issue.")
    else:
        compliance_risk = 45

    manufacturer_key = manufacturer.lower()
    if not manufacturer_key:
        manufacturer_risk = 55
    elif manufacturer_key in KNOWN_STRONG_MANUFACTURERS:
        manufacturer_risk = 10
    else:
        manufacturer_risk = 35

    weights = {
        "lifecycle_risk": 0.30,
        "supply_chain_risk": 0.20,
        "inventory_risk": 0.15,
        "lead_time_risk": 0.10,
        "single_source_risk": 0.10,
        "compliance_risk": 0.05,
        "manufacturer_risk": 0.10,
    }

    overall = (
        lifecycle_risk * weights["lifecycle_risk"]
        + supply_chain_risk * weights["supply_chain_risk"]
        + inventory_risk * weights["inventory_risk"]
        + lead_time_risk * weights["lead_time_risk"]
        + single_source_risk * weights["single_source_risk"]
        + compliance_risk * weights["compliance_risk"]
        + manufacturer_risk * weights["manufacturer_risk"]
    )

    result = RiskDimensions(
        lifecycle_risk=round(_clamp(lifecycle_risk), 1),
        supply_chain_risk=round(_clamp(supply_chain_risk), 1),
        inventory_risk=round(_clamp(inventory_risk), 1),
        lead_time_risk=round(_clamp(lead_time_risk), 1),
        single_source_risk=round(_clamp(single_source_risk), 1),
        compliance_risk=round(_clamp(compliance_risk), 1),
        manufacturer_risk=round(_clamp(manufacturer_risk), 1),
        overall_risk=round(_clamp(overall), 1),
        risk_level=_risk_level(overall),
        reasons=reasons or ["No major risk driver detected from available data."],
    )
    return result.to_dict()


# -----------------------------------------------------------------------------
# 3.2 Alternative Ranking AI + 3.3 Compatibility Report
# -----------------------------------------------------------------------------

def _normalize_package(value: Any) -> str:
    text = _clean_text(value).lower().replace(" ", "")
    text = text.replace("-", "").replace("_", "")
    return text


def _parse_voltage_range(value: Any) -> Tuple[Optional[float], Optional[float]]:
    text = _clean_text(value).lower().replace("v", "")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
    if len(nums) >= 2:
        return min(nums), max(nums)
    if len(nums) == 1:
        return nums[0], nums[0]
    return None, None


def explain_compatibility(original: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    score = 100.0

    original_pkg = _normalize_package(_get(original, "Package", "package", default=""))
    candidate_pkg = _normalize_package(_get(candidate, "Package", "package", default=""))

    if original_pkg and candidate_pkg:
        if original_pkg == candidate_pkg:
            checks.append({"field": "Package", "status": "Compatible", "note": "Package appears to match."})
        else:
            checks.append({"field": "Package", "status": "Review", "note": f"Original package {original_pkg}; candidate package {candidate_pkg}."})
            score -= 20
    else:
        checks.append({"field": "Package", "status": "Unknown", "note": "Package data is incomplete."})
        score -= 8

    original_pins = _num(_get(original, "Pin Count", "pin_count", default=0))
    candidate_pins = _num(_get(candidate, "Pin Count", "pin_count", default=0))

    if original_pins and candidate_pins:
        if int(original_pins) == int(candidate_pins):
            checks.append({"field": "Pin Count", "status": "Compatible", "note": "Pin count matches."})
        else:
            checks.append({"field": "Pin Count", "status": "Review", "note": f"Original has {int(original_pins)} pins; candidate has {int(candidate_pins)} pins."})
            score -= 20
    else:
        checks.append({"field": "Pin Count", "status": "Unknown", "note": "Pin-count data is incomplete."})
        score -= 8

    o_min, o_max = _parse_voltage_range(_get(original, "Voltage Range", "voltage_range", "Voltage", default=""))
    c_min, c_max = _parse_voltage_range(_get(candidate, "Voltage Range", "voltage_range", "Voltage", default=""))

    if o_min is not None and c_min is not None:
        if c_min <= o_min and c_max >= o_max:
            checks.append({"field": "Voltage", "status": "Compatible", "note": "Candidate voltage range covers the original requirement."})
        else:
            checks.append({"field": "Voltage", "status": "Review", "note": "Candidate voltage range may not fully cover the original requirement."})
            score -= 25
    else:
        checks.append({"field": "Voltage", "status": "Unknown", "note": "Voltage data is incomplete."})
        score -= 8

    original_arch = _clean_text(_get(original, "Architecture", "architecture", "Category", "category", default="")).lower()
    candidate_arch = _clean_text(_get(candidate, "Architecture", "architecture", "Category", "category", default="")).lower()

    if original_arch and candidate_arch:
        if original_arch == candidate_arch or original_arch in candidate_arch or candidate_arch in original_arch:
            checks.append({"field": "Architecture", "status": "Compatible", "note": "Architecture/category appears similar."})
        else:
            checks.append({"field": "Architecture", "status": "Review", "note": "Architecture/category differs and should be checked."})
            score -= 15
    else:
        checks.append({"field": "Architecture", "status": "Unknown", "note": "Architecture/category data is incomplete."})
        score -= 5

    compatibility_score = round(_clamp(score), 1)

    if compatibility_score >= 90:
        recommendation = "Likely drop-in replacement, pending datasheet verification."
    elif compatibility_score >= 75:
        recommendation = "Strong candidate; engineering validation recommended."
    elif compatibility_score >= 55:
        recommendation = "Possible candidate; schematic, PCB, and datasheet review required."
    else:
        recommendation = "High migration risk; do not treat as drop-in."

    return {
        "compatibility_score": compatibility_score,
        "compatibility_level": "High" if compatibility_score >= 80 else "Medium" if compatibility_score >= 55 else "Low",
        "recommendation": recommendation,
        "checks": checks,
    }


def rank_alternative_candidates(original: Dict[str, Any], candidates: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []

    for candidate in candidates:
        compatibility = explain_compatibility(original, candidate)
        risk = calculate_advanced_risk(candidate)

        stock = _num(_get(candidate, "Total Market Stock", "Stock Available", "stock", "stock_available", default=0))
        supplier_count = _num(_get(candidate, "Supplier Count", "supplier_count", default=0))
        lead_time = _num(_get(candidate, "Lead Time Weeks", "lead_time_weeks", default=0))
        unit_price = _num(_get(candidate, "Unit Price", "unit_price", "Price", default=0))

        availability_score = 100 if stock >= 1000 else 75 if stock >= 100 else 45 if stock > 0 else 5
        supplier_score = 100 if supplier_count >= 3 else 75 if supplier_count == 2 else 35 if supplier_count == 1 else 5
        lead_time_score = 100 if lead_time and lead_time <= 4 else 75 if lead_time <= 8 else 45 if lead_time <= 16 else 25
        price_score = 70 if unit_price <= 0 else 100 if unit_price <= 0.5 else 85 if unit_price <= 2 else 70 if unit_price <= 10 else 45
        risk_score_inverse = 100 - _num(risk.get("overall_risk"), 50)

        final_score = (
            compatibility["compatibility_score"] * 0.40
            + availability_score * 0.15
            + supplier_score * 0.15
            + lead_time_score * 0.10
            + price_score * 0.05
            + risk_score_inverse * 0.15
        )

        rows.append(
            {
                "Alternative Part": _get(candidate, "Alternative Part", "MPN", "mpn", "part_number", default=""),
                "Manufacturer": _get(candidate, "Manufacturer", "manufacturer", default=""),
                "Recommendation Score": round(_clamp(final_score), 1),
                "Compatibility Score": compatibility["compatibility_score"],
                "Compatibility Level": compatibility["compatibility_level"],
                "Engineering Recommendation": compatibility["recommendation"],
                "Risk Score": risk["overall_risk"],
                "Risk Level": risk["risk_level"],
                "Supplier Count": int(supplier_count),
                "Total Market Stock": int(stock),
                "Lead Time Weeks": lead_time if lead_time else None,
                "Unit Price": unit_price if unit_price else None,
                "Compatibility Checks": compatibility["checks"],
                "Risk Reasons": "; ".join(risk["reasons"]),
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("Recommendation Score", ascending=False).reset_index(drop=True)


# -----------------------------------------------------------------------------
# 3.4 Supplier Intelligence + 3.5 Manufacturer Health
# -----------------------------------------------------------------------------

def supplier_intelligence(part: Dict[str, Any]) -> Dict[str, Any]:
    supplier_count = int(_num(_get(part, "Supplier Count", "supplier_count", default=0)))
    stock = int(_num(_get(part, "Total Market Stock", "Stock Available", "stock_available", "stock_total", default=0)))
    sources = _clean_text(_get(part, "Sources Available", "sources_available", "Best Source", "source", default=""))

    if supplier_count >= 4:
        diversity = "Excellent"
        supplier_risk = "Low"
    elif supplier_count >= 2:
        diversity = "Good"
        supplier_risk = "Medium"
    elif supplier_count == 1:
        diversity = "Weak"
        supplier_risk = "High"
    else:
        diversity = "Unknown"
        supplier_risk = "High"

    return {
        "supplier_count": supplier_count,
        "total_market_stock": stock,
        "sources_available": sources,
        "supplier_diversity": diversity,
        "supplier_risk": supplier_risk,
        "summary": f"{supplier_count} supplier source(s), {stock:,} units visible, supplier diversity: {diversity}.",
    }


def manufacturer_health(part: Dict[str, Any]) -> Dict[str, Any]:
    manufacturer = _clean_text(_get(part, "Manufacturer", "manufacturer", default=""))
    key = manufacturer.lower()
    supplier_count = _num(_get(part, "Supplier Count", "supplier_count", default=0))
    lifecycle = _get(part, "Lifecycle Status", "lifecycle_status", default="Unknown")

    score = 60.0
    notes: List[str] = []

    if not manufacturer:
        score -= 15
        notes.append("Manufacturer is missing or unknown.")
    elif key in KNOWN_STRONG_MANUFACTURERS:
        score += 25
        notes.append("Manufacturer appears to be a major established component supplier.")
    else:
        notes.append("Manufacturer health is based on available sourcing and lifecycle signals.")

    if supplier_count >= 3:
        score += 10
    elif supplier_count <= 1:
        score -= 15
        notes.append("Limited distributor visibility lowers confidence.")

    if _contains_any(lifecycle, HIGH_RISK_LIFECYCLE_TERMS):
        score -= 30
        notes.append("Lifecycle status reduces manufacturer/part support confidence.")
    elif _contains_any(lifecycle, HEALTHY_LIFECYCLE_TERMS):
        score += 10

    score = round(_clamp(score), 1)
    label = "Very Stable" if score >= 85 else "Stable" if score >= 70 else "Moderate" if score >= 50 else "Weak"

    return {
        "manufacturer": manufacturer or "Unknown",
        "manufacturer_health_score": score,
        "manufacturer_health": label,
        "notes": notes,
    }


# -----------------------------------------------------------------------------
# 3.6 BOM-Level Intelligence + 3.7 Recommendations + 3.8 Forecasting
# -----------------------------------------------------------------------------

def classify_component_type(row: Dict[str, Any]) -> str:
    text = " ".join(
        [
            _clean_text(_get(row, "Description", "description", default="")),
            _clean_text(_get(row, "MPN", "mpn", default="")),
        ]
    ).lower()

    rules = [
        ("Power", ("regulator", "ldo", "buck", "boost", "converter", "pmic", "mosfet", "power")),
        ("MCU/Processor", ("mcu", "microcontroller", "processor", "cpu", "atmega", "stm32", "esp32")),
        ("Analog", ("op amp", "op-amp", "amplifier", "adc", "dac", "sensor", "analog")),
        ("Logic", ("logic", "gate", "buffer", "flip flop", "74hc", "74ls")),
        ("Memory", ("flash", "eeprom", "sram", "dram", "memory")),
        ("Passive", ("resistor", "capacitor", "inductor", "ferrite", "crystal")),
        ("Connector", ("connector", "header", "terminal", "usb", "jack")),
    ]

    for label, terms in rules:
        if any(term in text for term in terms):
            return label
    return "Other"


def forecast_part_risk(part: Dict[str, Any]) -> Dict[str, Any]:
    risk = calculate_advanced_risk(part)
    lifecycle = _get(part, "Lifecycle Status", "lifecycle_status", default="Unknown")
    lead_time = _num(_get(part, "Lead Time Weeks", "lead_time_weeks", default=0))
    supplier_count = _num(_get(part, "Supplier Count", "supplier_count", default=0))
    stock = _num(_get(part, "Total Market Stock", "Stock Available", "stock_available", default=0))

    future_score = risk["overall_risk"]
    drivers: List[str] = []

    if _contains_any(lifecycle, MEDIUM_RISK_LIFECYCLE_TERMS):
        future_score += 10
        drivers.append("Lifecycle status may worsen if not verified.")
    if supplier_count <= 1:
        future_score += 8
        drivers.append("Single-source exposure can become critical quickly.")
    if stock < 100:
        future_score += 8
        drivers.append("Low inventory increases near-term shortage risk.")
    if lead_time >= 12:
        future_score += 7
        drivers.append("Long lead time increases future procurement risk.")

    future_score = round(_clamp(future_score), 1)

    return {
        "current_risk": risk["overall_risk"],
        "current_level": risk["risk_level"],
        "forecast_12_month_risk": future_score,
        "forecast_12_month_level": _risk_level(future_score),
        "forecast_drivers": drivers or ["No strong future risk escalation signal detected from available data."],
    }


def analyze_bom_intelligence(results_df: pd.DataFrame) -> Dict[str, Any]:
    if results_df is None or results_df.empty:
        return {
            "bom_health_score": 0,
            "health_label": "No Data",
            "risk_distribution": {},
            "component_mix": {},
            "recommendations": ["Upload and analyze a BOM to generate intelligence."],
            "executive_summary": "No BOM data is available yet.",
            "engineering_insights": [],
            "top_risks": pd.DataFrame(),
            "enriched_parts": pd.DataFrame(),
        }

    enriched_rows: List[Dict[str, Any]] = []
    for _, row in results_df.iterrows():
        record = row.to_dict()
        risk = calculate_advanced_risk(record)
        supplier = supplier_intelligence(record)
        mfg = manufacturer_health(record)
        forecast = forecast_part_risk(record)
        component_type = classify_component_type(record)

        record.update(
            {
                "Advanced Risk Score": risk["overall_risk"],
                "Advanced Risk Level": risk["risk_level"],
                "Lifecycle Risk": risk["lifecycle_risk"],
                "Supply Chain Risk": risk["supply_chain_risk"],
                "Inventory Risk": risk["inventory_risk"],
                "Lead Time Risk": risk["lead_time_risk"],
                "Single Source Risk": risk["single_source_risk"],
                "Compliance Risk": risk["compliance_risk"],
                "Manufacturer Risk": risk["manufacturer_risk"],
                "Advanced Risk Reasons": "; ".join(risk["reasons"]),
                "Supplier Diversity": supplier["supplier_diversity"],
                "Supplier Risk": supplier["supplier_risk"],
                "Manufacturer Health": mfg["manufacturer_health"],
                "Manufacturer Health Score": mfg["manufacturer_health_score"],
                "Component Type": component_type,
                "Forecast 12 Month Risk": forecast["forecast_12_month_risk"],
                "Forecast 12 Month Level": forecast["forecast_12_month_level"],
                "Forecast Drivers": "; ".join(forecast["forecast_drivers"]),
            }
        )
        enriched_rows.append(record)

    enriched = pd.DataFrame(enriched_rows)

    avg_risk = float(enriched["Advanced Risk Score"].mean())
    bom_health = int(round(_clamp(100 - avg_risk)))
    health_label = _health_label(bom_health)

    risk_distribution = enriched["Advanced Risk Level"].value_counts().to_dict()
    component_mix = enriched["Component Type"].value_counts(normalize=True).mul(100).round(1).to_dict()

    high_risk = int((enriched["Advanced Risk Level"] == "High").sum())
    medium_risk = int((enriched["Advanced Risk Level"] == "Medium").sum())
    single_source = int((_num_series(enriched["Supplier Count"]) <= 1).sum()) if "Supplier Count" in enriched else 0
    no_stock = int((_num_series(enriched.get("Stock Available", pd.Series([0] * len(enriched)))) <= 0).sum())
    obsolete_like = int(enriched.get("Lifecycle Status", pd.Series(dtype=str)).astype(str).str.lower().apply(lambda x: any(t in x for t in HIGH_RISK_LIFECYCLE_TERMS)).sum()) if "Lifecycle Status" in enriched else 0

    recommendations: List[str] = []
    if high_risk:
        recommendations.append(f"Review {high_risk} high-risk component(s) before production release.")
    if obsolete_like:
        recommendations.append(f"Prioritize replacement search for {obsolete_like} obsolete/EOL/NRND component(s).")
    if no_stock:
        recommendations.append(f"Escalate sourcing for {no_stock} component(s) with no visible stock.")
    if single_source:
        recommendations.append(f"Add secondary-source strategy for {single_source} single-source component(s).")
    if medium_risk and not high_risk:
        recommendations.append(f"Monitor {medium_risk} medium-risk component(s) over the next 3–6 months.")
    if not recommendations:
        recommendations.append("No immediate critical actions detected; continue periodic lifecycle and stock monitoring.")

    top_risks = enriched.sort_values("Advanced Risk Score", ascending=False).head(10)

    insights = generate_engineering_insights(enriched)
    executive_summary = generate_intelligence_executive_summary(
        total_parts=len(enriched),
        bom_health=bom_health,
        health_label=health_label,
        high_risk=high_risk,
        medium_risk=medium_risk,
        no_stock=no_stock,
        single_source=single_source,
        obsolete_like=obsolete_like,
    )

    return {
        "bom_health_score": bom_health,
        "health_label": health_label,
        "average_risk_score": round(avg_risk, 1),
        "risk_distribution": risk_distribution,
        "component_mix": component_mix,
        "recommendations": recommendations,
        "executive_summary": executive_summary,
        "engineering_insights": insights,
        "top_risks": top_risks,
        "enriched_parts": enriched,
    }


def _num_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce").fillna(0)


def generate_engineering_insights(enriched: pd.DataFrame) -> List[str]:
    insights: List[str] = []
    if enriched.empty:
        return insights

    if "Component Type" in enriched:
        type_counts = enriched["Component Type"].value_counts()
        if not type_counts.empty:
            top_type = type_counts.index[0]
            top_pct = round(type_counts.iloc[0] / len(enriched) * 100, 1)
            insights.append(f"{top_type} components represent {top_pct}% of the BOM.")

    if "Manufacturer" in enriched:
        mfg_counts = enriched["Manufacturer"].replace("", "Unknown").value_counts()
        if not mfg_counts.empty and mfg_counts.iloc[0] / len(enriched) >= 0.4:
            insights.append(f"Manufacturer concentration is high: {mfg_counts.index[0]} appears in {round(mfg_counts.iloc[0] / len(enriched) * 100, 1)}% of parts.")

    if "Advanced Risk Level" in enriched:
        high_df = enriched[enriched["Advanced Risk Level"] == "High"]
        if not high_df.empty and "Component Type" in high_df:
            top_risk_type = high_df["Component Type"].value_counts().index[0]
            insights.append(f"High risk is concentrated most strongly in {top_risk_type} components.")

    if "Supplier Diversity" in enriched:
        weak_count = int((enriched["Supplier Diversity"].isin(["Weak", "Unknown"])).sum())
        if weak_count:
            insights.append(f"{weak_count} component(s) have weak or unknown supplier diversity.")

    if "Forecast 12 Month Level" in enriched:
        future_high = int((enriched["Forecast 12 Month Level"] == "High").sum())
        current_high = int((enriched["Advanced Risk Level"] == "High").sum())
        if future_high > current_high:
            insights.append(f"Forecasting suggests {future_high - current_high} additional component(s) may become high risk within 12 months.")

    if not insights:
        insights.append("No unusual engineering concentration or future escalation pattern was detected from available data.")

    return insights


def generate_intelligence_executive_summary(
    total_parts: int,
    bom_health: int,
    health_label: str,
    high_risk: int,
    medium_risk: int,
    no_stock: int,
    single_source: int,
    obsolete_like: int,
) -> str:
    summary = (
        f"This BOM contains {total_parts} component(s) with an overall health score of "
        f"{bom_health}/100, classified as {health_label}. "
    )

    concerns: List[str] = []
    if high_risk:
        concerns.append(f"{high_risk} high-risk component(s)")
    if obsolete_like:
        concerns.append(f"{obsolete_like} obsolete/EOL/NRND component(s)")
    if no_stock:
        concerns.append(f"{no_stock} component(s) with no visible stock")
    if single_source:
        concerns.append(f"{single_source} single-source component(s)")

    if concerns:
        summary += "Primary concerns include " + ", ".join(concerns) + ". "
        summary += "Immediate engineering and sourcing review is recommended before production release."
    elif medium_risk:
        summary += f"No critical blockers were found, but {medium_risk} medium-risk component(s) should remain under monitoring."
    else:
        summary += "No major sourcing or lifecycle issues were detected from the available data."

    return summary


# -----------------------------------------------------------------------------
# Streamlit rendering helper — optional, but makes integration faster
# -----------------------------------------------------------------------------

def render_bom_intelligence_panel(st_module: Any, results_df: pd.DataFrame) -> Dict[str, Any]:
    """Render Milestone 3 intelligence inside Streamlit.

    Usage in streamlit_app.py after results_df exists:

        from src.bom_intelligence import render_bom_intelligence_panel
        intelligence = render_bom_intelligence_panel(st, st.session_state["results_df"])

    Returns the full intelligence dictionary so it can also be exported.
    """

    intelligence = analyze_bom_intelligence(results_df)

    st_module.subheader("BOM Intelligence 2.0")
    st_module.caption("Advanced risk dimensions, supplier resilience, future risk, and engineering recommendations.")

    col1, col2, col3, col4 = st_module.columns(4)
    col1.metric("BOM Health", f"{intelligence['bom_health_score']}/100", intelligence["health_label"])
    col2.metric("Avg Risk", intelligence.get("average_risk_score", 0))
    col3.metric("High Risk", intelligence["risk_distribution"].get("High", 0))
    col4.metric("Medium Risk", intelligence["risk_distribution"].get("Medium", 0))

    st_module.info(intelligence["executive_summary"])

    rec_col, insight_col = st_module.columns(2)

    with rec_col:
        st_module.markdown("#### Recommended Actions")
        for item in intelligence["recommendations"]:
            st_module.write(f"• {item}")

    with insight_col:
        st_module.markdown("#### Engineering Insights")
        for item in intelligence["engineering_insights"]:
            st_module.write(f"• {item}")

    st_module.markdown("#### Top Risk Drivers")
    top_risks = intelligence["top_risks"]
    display_cols = [
        c for c in [
            "MPN",
            "Manufacturer",
            "Component Type",
            "Advanced Risk Score",
            "Advanced Risk Level",
            "Lifecycle Risk",
            "Supply Chain Risk",
            "Inventory Risk",
            "Supplier Diversity",
            "Forecast 12 Month Level",
            "Advanced Risk Reasons",
        ] if c in top_risks.columns
    ]

    if display_cols:
        st_module.dataframe(top_risks[display_cols], use_container_width=True, hide_index=True)

    return intelligence
