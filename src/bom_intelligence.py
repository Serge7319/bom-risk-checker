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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
import math
import re

import pandas as pd

from integrations.pin_count import effective_pin_count


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
    """Return risk dimensions only when their own supplier evidence verifies."""
    from apps.api.evidence_contract import EVIDENCE_LIVE, classify_part_evidence
    from src.risk_engine import calculate_risk, _coverage_complete

    evidence = classify_part_evidence(part)
    fields = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}

    def verified(name: str) -> dict[str, Any]:
        value = fields.get(name)
        return value if isinstance(value, dict) and value.get("evidence_class") == EVIDENCE_LIVE else {}

    assessment = calculate_risk(part)
    lifecycle = verified("lifecycle")
    stock = verified("stock")
    lead = verified("lead_time")
    identity = verified("identity")
    coverage_complete, _ = _coverage_complete(part)
    supplier_count = _num(_get(part, "Supplier Count", "supplier_count", default=None), default=float("nan"))
    if not math.isfinite(supplier_count) or not (identity and coverage_complete):
        supplier_count = None
    lifecycle_value = _clean_text(_get(part, "Lifecycle", "lifecycle_status", "Lifecycle Status", default=""))
    stock_value = stock.get("observed_total") if stock and stock.get("complete") else None
    lead_value = _num(_get(part, "Lead Time Weeks", "lead_time_weeks", default=None), default=float("nan"))
    if not lead or not math.isfinite(lead_value):
        lead_value = None

    lifecycle_risk = None
    if lifecycle:
        text = lifecycle_value.casefold()
        lifecycle_risk = 90 if _contains_any(text, HIGH_RISK_LIFECYCLE_TERMS) else 35 if _contains_any(text, MEDIUM_RISK_LIFECYCLE_TERMS) else 0
    inventory_risk = None
    if stock_value is not None:
        qty = _num(_get(part, "Effective Quantity", "effective_quantity", "Quantity", "quantity", default=None), default=0)
        inventory_risk = 90 if stock_value == 0 else 60 if qty > 0 and stock_value < qty else 25 if stock_value < 100 else 0
    supply_risk = None if supplier_count is None else (90 if supplier_count <= 1 else 50 if supplier_count == 2 else 10)
    lead_risk = None if lead_value is None else (80 if lead_value >= 26 else 60 if lead_value >= 12 else 25 if lead_value >= 6 else 0)
    single_source_risk = supply_risk
    compliance_fields = fields.get("compliance") if isinstance(fields.get("compliance"), dict) else {}
    compliance_values = [
        item for item in compliance_fields.values()
        if isinstance(item, dict) and item.get("evidence_class") == EVIDENCE_LIVE
    ]
    compliance_risk = None
    if compliance_values:
        statuses = [str(item.get("reported_value") or "").casefold() for item in compliance_values]
        compliance_risk = 90 if any(value in {"no", "false", "non-compliant", "not compliant"} for value in statuses) else 0

    reasons = list(assessment.get("risk_reasons") or [])
    dims = {
        "Lifecycle": lifecycle_risk,
        "Supply Chain": supply_risk,
        "Inventory": inventory_risk,
        "Lead Time": lead_risk,
        "Single Source": single_source_risk,
        "Compliance": compliance_risk,
        "Manufacturer": None,
    }
    stars = {
        key: _score_to_stars(value) if value is not None else "Not assessed"
        for key, value in dims.items()
    }
    return {
        "lifecycle_risk": lifecycle_risk,
        "supply_chain_risk": supply_risk,
        "inventory_risk": inventory_risk,
        "lead_time_risk": lead_risk,
        "single_source_risk": single_source_risk,
        "compliance_risk": compliance_risk,
        "manufacturer_risk": None,
        "overall_risk": assessment.get("risk_score"),
        "risk_score": assessment.get("risk_score"),
        "risk_level": assessment.get("risk_level") or "Needs verification",
        "reasons": reasons,
        "dimension_stars": stars,
    }


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

    original_pins = effective_pin_count(original if isinstance(original, dict) else {})
    candidate_pins = effective_pin_count(candidate if isinstance(candidate, dict) else {})

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

    unknown_checks = sum(check["status"] == "Unknown" for check in checks)
    compatibility_score = None if unknown_checks else round(_clamp(score), 1)

    if compatibility_score is None:
        recommendation = "Needs engineering verification; required package, pin, voltage, or architecture data is missing."
        compatibility_level = "Needs verification"
    elif compatibility_score >= 90:
        recommendation = "Likely drop-in replacement, pending datasheet verification."
        compatibility_level = "High"
    elif compatibility_score >= 75:
        recommendation = "Strong candidate; engineering validation recommended."
        compatibility_level = "High"
    elif compatibility_score >= 55:
        recommendation = "Possible candidate; schematic, PCB, and datasheet review required."
        compatibility_level = "Medium"
    else:
        recommendation = "High migration risk; do not treat as drop-in."
        compatibility_level = "Low"

    return {
        "compatibility_score": compatibility_score,
        "compatibility_level": compatibility_level,
        "recommendation": recommendation,
        "checks": checks,
    }


def rank_alternative_candidates(original: Dict[str, Any], candidates: List[Dict[str, Any]]) -> pd.DataFrame:
    from apps.api.evidence_contract import EVIDENCE_LIVE, classify_part_evidence
    from src.risk_engine import calculate_risk, _coverage_complete

    rows: List[Dict[str, Any]] = []

    for candidate in candidates:
        compatibility = explain_compatibility(original, candidate)
        risk = calculate_risk(candidate)
        evidence = classify_part_evidence(candidate)
        fields = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
        identity = fields.get("identity") if isinstance(fields.get("identity"), dict) else {}
        stock_field = fields.get("stock") if isinstance(fields.get("stock"), dict) else {}
        price_field = fields.get("price") if isinstance(fields.get("price"), dict) else {}
        lead_field = fields.get("lead_time") if isinstance(fields.get("lead_time"), dict) else {}
        coverage_complete, _ = _coverage_complete(candidate)
        sourcing_complete = bool(
            identity.get("evidence_class") == EVIDENCE_LIVE
            and coverage_complete
            and stock_field.get("evidence_class") == EVIDENCE_LIVE
            and stock_field.get("complete")
            and price_field.get("evidence_class") == EVIDENCE_LIVE
            and price_field.get("quantity_break_applies") is True
            and lead_field.get("evidence_class") == EVIDENCE_LIVE
        )
        stock = stock_field.get("observed_total") if stock_field.get("evidence_class") == EVIDENCE_LIVE and stock_field.get("complete") else None
        supplier_count = _num(_get(candidate, "Supplier Count", "supplier_count", default=None), default=float("nan"))
        if not math.isfinite(supplier_count) or not coverage_complete or identity.get("evidence_class") != EVIDENCE_LIVE:
            supplier_count = None
        lead_time = _num(_get(candidate, "Lead Time Weeks", "lead_time_weeks", default=None), default=float("nan"))
        if lead_field.get("evidence_class") != EVIDENCE_LIVE or not math.isfinite(lead_time):
            lead_time = None
        unit_price = price_field.get("reported_value") if price_field.get("evidence_class") == EVIDENCE_LIVE and price_field.get("quantity_break_applies") is True else None
        final_score = None
        if compatibility.get("compatibility_score") is not None and sourcing_complete and risk.get("risk_score") is not None:
            availability_score = 100 if stock >= 1000 else 75 if stock >= 100 else 45 if stock > 0 else 5
            supplier_score = 100 if supplier_count >= 3 else 75 if supplier_count == 2 else 35
            lead_score = 100 if lead_time <= 4 else 75 if lead_time <= 8 else 45 if lead_time <= 16 else 25
            price_score = 100 if unit_price <= 0.5 else 85 if unit_price <= 2 else 70 if unit_price <= 10 else 45
            risk_inverse = 100 - float(risk["risk_score"])
            final_score = round(_clamp(
                compatibility["compatibility_score"] * 0.40
                + availability_score * 0.15
                + supplier_score * 0.15
                + lead_score * 0.10
                + price_score * 0.05
                + risk_inverse * 0.15
            ), 1)

        rows.append(
            {
                "Alternative Part": _get(candidate, "Alternative Part", "MPN", "mpn", "part_number", default=""),
                "Manufacturer": _get(candidate, "Manufacturer", "manufacturer", default=""),
                "Recommendation Score": final_score,
                "Ranking Status": "Ranked from complete evidence" if final_score is not None else "Needs verification",
                "Compatibility Score": compatibility["compatibility_score"],
                "Compatibility Level": compatibility["compatibility_level"],
                "Engineering Recommendation": compatibility["recommendation"],
                "Risk Score": risk.get("risk_score"),
                "Risk Level": risk.get("risk_level", "Needs verification"),
                "Supplier Count": int(supplier_count) if supplier_count is not None else None,
                "Total Market Stock": int(stock) if stock is not None else None,
                "Lead Time Weeks": lead_time,
                "Unit Price": unit_price,
                "Compatibility Checks": compatibility["checks"],
                "Risk Reasons": "; ".join(risk.get("risk_reasons") or []),
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(
        "Recommendation Score", ascending=False, na_position="last"
    ).reset_index(drop=True)


# -----------------------------------------------------------------------------
# 3.4 Supplier Intelligence + 3.5 Manufacturer Health
# -----------------------------------------------------------------------------

def supplier_intelligence(part: Dict[str, Any]) -> Dict[str, Any]:
    from apps.api.evidence_contract import EVIDENCE_LIVE, classify_part_evidence
    from src.risk_engine import _coverage_complete

    evidence = classify_part_evidence(part)
    fields = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
    identity = fields.get("identity") if isinstance(fields.get("identity"), dict) else {}
    stock_field = fields.get("stock") if isinstance(fields.get("stock"), dict) else {}
    coverage_complete, _ = _coverage_complete(part)
    verified_count = identity.get("evidence_class") == EVIDENCE_LIVE and coverage_complete
    supplier_count = _num(_get(part, "Supplier Count", "supplier_count", default=None), default=float("nan")) if verified_count else float("nan")
    supplier_count = int(supplier_count) if math.isfinite(supplier_count) else None
    stock = (
        int(stock_field["observed_total"])
        if stock_field.get("evidence_class") == EVIDENCE_LIVE
        and stock_field.get("complete")
        and stock_field.get("observed_total") is not None
        else None
    )
    source_rows = stock_field.get("sources") if isinstance(stock_field.get("sources"), list) else []
    sources = ", ".join(sorted({str(row.get("source") or "").strip() for row in source_rows if isinstance(row, dict) and str(row.get("source") or "").strip()}))

    if supplier_count is None:
        diversity, supplier_risk = "Not assessed", "Not assessed"
    elif supplier_count >= 4:
        diversity = "Excellent"
        supplier_risk = "Low"
    elif supplier_count >= 2:
        diversity = "Good"
        supplier_risk = "Medium"
    elif supplier_count == 1:
        diversity = "Weak"
        supplier_risk = "High"
    else:
        diversity = "Not found in completed source checks"
        supplier_risk = "High"

    return {
        "supplier_count": supplier_count,
        "total_market_stock": stock,
        "sources_available": sources or "Not reported",
        "supplier_diversity": diversity,
        "supplier_risk": supplier_risk,
        "summary": (
            f"{supplier_count} exact-part supplier source(s) returned."
            if supplier_count is not None
            else "Supplier diversity was not assessed because exact-part identity or source coverage is incomplete."
        ),
    }


def manufacturer_health(part: Dict[str, Any]) -> Dict[str, Any]:
    manufacturer = _clean_text(_get(part, "Manufacturer", "manufacturer", default=""))
    return {
        "manufacturer": manufacturer or "Unknown",
        "manufacturer_health_score": None,
        "manufacturer_health": "Not assessed",
        "notes": ["Cadivor has no validated manufacturer financial or quality-risk dataset for this supplier."],
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
    return {
        "current_risk": calculate_advanced_risk(part).get("overall_risk"),
        "current_level": calculate_advanced_risk(part).get("risk_level"),
        "forecast_12_month_risk": None,
        "forecast_12_month_level": "Not forecast",
        "forecast_drivers": ["A defensible forecast requires dated historical supplier and lifecycle observations."],
    }


def analyze_bom_intelligence(results_df: pd.DataFrame) -> Dict[str, Any]:
    if results_df is None or results_df.empty:
        return {
            "bom_health_score": None,
            "health_label": "No Data",
            "risk_distribution": {},
            "component_mix": {},
            "recommendations": ["Upload and analyze a BOM to generate intelligence."],
            "executive_summary": "No BOM data is available yet.",
            "engineering_insights": [],
            "top_risks": pd.DataFrame(),
            "enriched_parts": pd.DataFrame(),
        }

    from apps.api.evidence_contract import EVIDENCE_LIVE, classify_part_evidence
    from src.health_score import calculate_bom_health_score
    from src.risk_engine import calculate_risk

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
                "Advanced Risk Score": risk.get("risk_score"),
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
                "Verified Supplier Count": supplier["supplier_count"],
                "Verified Stock": supplier["total_market_stock"],
                "Manufacturer Health": mfg["manufacturer_health"],
                "Manufacturer Health Score": mfg["manufacturer_health_score"],
                "Component Type": component_type,
                "Forecast 12 Month Risk": forecast["forecast_12_month_risk"],
                "Forecast 12 Month Level": forecast["forecast_12_month_level"],
                "Forecast Drivers": "; ".join(forecast["forecast_drivers"]),
            }
        )
        evidence = classify_part_evidence(record)
        fields = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
        identity = fields.get("identity") if isinstance(fields.get("identity"), dict) else {}
        stock = fields.get("stock") if isinstance(fields.get("stock"), dict) else {}
        from src.risk_engine import _coverage_complete

        coverage_complete, _ = _coverage_complete(record)
        assessed = calculate_risk(record)
        record.update({
            "Supplier Data Verified": identity.get("evidence_class") == EVIDENCE_LIVE,
            "Stock Data Complete": stock.get("evidence_class") == EVIDENCE_LIVE and bool(stock.get("complete")),
            "Supplier Coverage Complete": identity.get("evidence_class") == EVIDENCE_LIVE and coverage_complete,
            "Risk Score": assessed.get("risk_score"),
            "Risk Level": assessed.get("risk_level"),
        })
        enriched_rows.append(record)

    enriched = pd.DataFrame(enriched_rows)
    health_result = calculate_bom_health_score(enriched)
    bom_health = health_result.get("health_score")
    health_label = health_result.get("health_status") or "Needs verification"

    risk_distribution = enriched["Advanced Risk Level"].value_counts().to_dict()
    component_mix = enriched["Component Type"].value_counts(normalize=True).mul(100).round(1).to_dict()

    high_risk = int((enriched["Advanced Risk Level"] == "High").sum())
    medium_risk = int((enriched["Advanced Risk Level"] == "Medium").sum())
    needs_verification = int((enriched["Advanced Risk Level"] == "Needs verification").sum())
    verified_supplier_counts = [
        item.get("Verified Supplier Count") for item in enriched_rows
        if item.get("Verified Supplier Count") is not None
    ]
    single_source = sum(value == 1 for value in verified_supplier_counts)
    no_stock = sum(
        item.get("Verified Stock") == 0
        for item in enriched_rows
        if item.get("Verified Stock") is not None
    )
    obsolete_like = 0
    for record in enriched_rows:
        fields = (classify_part_evidence(record).get("fields") or {})
        lifecycle_field = fields.get("lifecycle") if isinstance(fields.get("lifecycle"), dict) else {}
        lifecycle_value = str(record.get("Lifecycle") or record.get("lifecycle_status") or record.get("Lifecycle Status") or "")
        if lifecycle_field.get("evidence_class") == EVIDENCE_LIVE and _contains_any(lifecycle_value, HIGH_RISK_LIFECYCLE_TERMS):
            obsolete_like += 1

    recommendations: List[str] = []
    if needs_verification:
        recommendations.append(
            f"Verify exact-part identity, lifecycle, inventory, and source coverage for {needs_verification} component(s) before relying on an overall BOM health score."
        )
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
        recommendations.append("No verified high or medium risk signal was found in the completed supplier checks.")

    scored = enriched[enriched["Advanced Risk Score"].notna()]
    avg_risk = float(scored["Advanced Risk Score"].mean()) if not scored.empty else None
    top_risks = scored.sort_values("Advanced Risk Score", ascending=False).head(10) if not scored.empty else enriched.head(0)

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
        "average_risk_score": round(avg_risk, 1) if avg_risk is not None else None,
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
        weak_count = int((enriched["Supplier Diversity"] == "Weak").sum())
        if weak_count:
            insights.append(f"{weak_count} component(s) have weak or unknown supplier diversity.")

    if "Forecast 12 Month Level" in enriched and enriched["Forecast 12 Month Level"].ne("Not forecast").any():
        future_high = int((enriched["Forecast 12 Month Level"] == "High").sum())
        current_high = int((enriched["Advanced Risk Level"] == "High").sum())
        if future_high > current_high:
            insights.append(f"Forecasting suggests {future_high - current_high} additional component(s) may become high risk within 12 months.")

    if "Advanced Risk Level" in enriched:
        needs_verification = int((enriched["Advanced Risk Level"] == "Needs verification").sum())
        if needs_verification:
            insights.append(f"Supplier evidence is incomplete for {needs_verification} component(s); no overall health conclusion is available yet.")

    if not insights:
        insights.append("No unusual component concentration was identified from the saved BOM data.")

    return insights


def generate_intelligence_executive_summary(
    total_parts: int,
    bom_health: int | None,
    health_label: str,
    high_risk: int,
    medium_risk: int,
    no_stock: int,
    single_source: int,
    obsolete_like: int,
) -> str:
    if bom_health is None:
        summary = (
            f"This BOM contains {total_parts} component(s). Overall BOM health is not scored "
            f"because supplier evidence coverage is incomplete ({health_label}). "
        )
    else:
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
# Sprint 68 — Cross-component relationship inference
# -----------------------------------------------------------------------------

_RELATED_COMPONENT_HINTS: Dict[str, tuple[str, ...]] = {
    "mcu": ("clock", "crystal", "oscillator", "regulator", "ldo", "bootloader", "programming"),
    "microcontroller": ("clock", "crystal", "oscillator", "regulator", "ldo", "bootloader", "programming"),
    "processor": ("clock", "crystal", "regulator", "memory", "flash"),
    "fpga": ("clock", "regulator", "configuration", "programming"),
    "regulator": ("capacitor", "inductor", "filter", "ferrite"),
    "power": ("capacitor", "inductor", "regulator", "mosfet"),
    "connector": ("cable", "harness", "mating", "contact"),
    "sensor": ("adc", "amplifier", "filter", "connector"),
}


def _part_descriptor(row: Mapping[str, Any]) -> str:
    blob = " ".join(
        str(row.get(key) or "")
        for key in ("mpn", "MPN", "part_number", "description", "Component Type", "component_type")
    ).lower()
    return blob


def infer_cross_component_relationships(
    part: Mapping[str, Any],
    all_parts: Iterable[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """Infer downstream design relationships for a component within the same BOM."""
    source_mpn = str(
        _get(part, "mpn", "MPN", "part_number", default="Component")
    ).strip() or "Component"
    source_blob = _part_descriptor(part)
    related: List[Dict[str, str]] = []
    seen = set()

    hint_terms: List[str] = []
    for keyword, terms in _RELATED_COMPONENT_HINTS.items():
        if keyword in source_blob:
            hint_terms.extend(terms)

    if not hint_terms:
        if any(term in source_blob for term in ("obsolete", "nrnd", "eol", "lifecycle")):
            hint_terms = ("validation", "test", "fixture", "firmware")

    for row in all_parts or []:
        target_mpn = str(
            _get(row, "mpn", "MPN", "part_number", default="")
        ).strip()
        if not target_mpn or target_mpn == source_mpn or target_mpn in seen:
            continue
        target_blob = _part_descriptor(row)
        if not hint_terms:
            continue
        if any(term in target_blob for term in hint_terms):
            seen.add(target_mpn)
            relationship = "May require revalidation"
            if any(t in target_blob for t in ("clock", "crystal", "oscillator")):
                relationship = "Timing chain affected"
            elif any(t in target_blob for t in ("regulator", "ldo", "power")):
                relationship = "Power architecture affected"
            elif any(t in target_blob for t in ("programming", "bootloader", "flash")):
                relationship = "Firmware or programming affected"
            related.append(
                {
                    "component": target_mpn,
                    "relationship": relationship,
                }
            )
        if len(related) >= 5:
            break

    return related


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
    health_score = intelligence.get("bom_health_score")
    average_risk = intelligence.get("average_risk_score")
    col1.metric("BOM Health", f"{health_score}/100" if health_score is not None else "Not scored", intelligence["health_label"])
    col2.metric("Avg Risk", average_risk if average_risk is not None else "Not assessed")
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
