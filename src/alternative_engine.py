import pickle
import re
from typing import Any, Mapping, Optional

import pandas as pd

from integrations.pin_count import effective_footprint_pad_count, effective_pin_count
from integrations.stock_coercion import coerce_stock_total, parse_stock_total
from integrations.supplier_aggregator import get_best_part_data
from src.risk_engine import calculate_risk
from integrations.supplier_aggregator import (
    discover_alternative_candidates,
    search_supplier_alternatives,
)
from integrations.digikey_client import resolve_engineering_part_identity
from src.datasheet_comparison import (
    build_datasheet_comparison,
    build_engineering_evidence_assessment,
    build_recommendation_score_breakdown,
    infer_component_family,
    PASSIVE_FAMILIES,
    PASSIVE_PARAMETRIC_KEYS,
    normalize_mounting_style,
)
from src.component_family_profiles import (
    DISCRETE_PARAMETRIC_FAMILY_IDS,
    all_parametric_keys,
    get_family_profile,
)
from src.alternative_classification import (
    CLASS_CATALOG_INSUFFICIENT,
    CLASS_VERIFIED_DIRECT,
    apply_classification_result_cap,
    apply_suitability_score_adjustment,
    build_classification_recommendation,
    classification_sort_key,
    classify_from_supplier_evidence,
    classify_recommendation_suitability,
    is_non_component_catalog_candidate,
    refine_classification_after_comparison,
)
from src.runtime_cache import cache_data

_LAST_ALTERNATIVE_DISCOVERY: dict = {}


def get_alternative_discovery_metadata() -> dict:
    return dict(_LAST_ALTERNATIVE_DISCOVERY)


def _normalize_feature_tags(value: Any) -> list[str]:
    if isinstance(value, set):
        items = value
    elif isinstance(value, (list, tuple)):
        items = value
    elif value in (None, ""):
        return []
    else:
        return [str(value).strip()] if str(value).strip() else []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return sorted(normalized)


def prepare_candidates_for_session_and_cache(candidates: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize candidate payloads for Streamlit cache and session persistence."""
    prepared: list[dict[str, Any]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, Mapping):
            continue
        row = dict(candidate)
        row.pop("_discovery_row", None)
        if "Feature Tags" in row:
            row["Feature Tags"] = _normalize_feature_tags(row.get("Feature Tags"))
        if "Stock" in row:
            row["Stock"] = coerce_stock_total(row.get("Stock"))
        prepared.append(row)
    return prepared


def build_salvage_candidates_from_discovery(
    discovery: Optional[Mapping[str, Any]],
    *,
    canonical_mpn: str,
    original_part_number: str,
) -> list[dict[str, Any]]:
    """Build minimal candidate rows when full enrichment or persistence fails."""
    canonical = str(canonical_mpn or "").strip()
    original = str(original_part_number or canonical).strip()
    salvage: list[dict[str, Any]] = []
    for result in (discovery or {}).get("candidates") or []:
        if not isinstance(result, dict):
            continue
        if is_non_component_catalog_candidate(result):
            continue
        candidate_part = str(result.get("manufacturer_part_number") or "").strip()
        if not candidate_part:
            continue
        if candidate_part.casefold() in {canonical.casefold(), original.casefold()}:
            continue
        classification = classify_from_supplier_evidence(
            result,
            original_mpn=canonical or original,
            original_manufacturer=str(result.get("manufacturer") or ""),
        )
        substitute_type = str(result.get("substitute_type") or "Candidate").strip()
        salvage.append(
            {
                "Alternative Part": candidate_part,
                "description": str(result.get("description") or "").strip(),
                "architecture": str(result.get("architecture") or "").strip(),
                "package": result.get("package") or "",
                "pin_count": result.get("pin_count") or 0,
                "mounting_style": result.get("mounting_style") or "",
                "voltage_range": result.get("voltage_range") or "",
                "temperature_range": result.get("temperature_range") or "",
                "channel_count": result.get("channel_count") or 0,
                "lead_time_weeks": result.get("lead_time_weeks"),
                "lead_time_source": result.get("source") or "",
                "lead_time_retrieved_at": result.get("retrieved_at") or "",
                "bandwidth_mhz": result.get("bandwidth_mhz"),
                "slew_rate_v_us": result.get("slew_rate_v_us"),
                "input_offset_mv": result.get("input_offset_mv"),
                "input_bias_na": result.get("input_bias_na"),
                "quiescent_current_ma": result.get("quiescent_current_ma"),
                "gbw_mhz": result.get("gbw_mhz"),
                "unit_price": result.get("unit_price", 0.0),
                "unit_price_currency": result.get("unit_price_currency") or result.get("currency") or "",
                "retrieved_at": result.get("retrieved_at") or "",
                "compliance_evidence": dict(result.get("compliance_evidence") or {})
                if isinstance(result.get("compliance_evidence"), dict) else {},
                "product_detail_url": result.get("product_detail_url") or "",
                "field_sources": dict(result.get("field_sources") or {}),
                "image_url": str(result.get("image_url") or result.get("photo_url") or "").strip(),
                "Primary Category": str(
                    result.get("primary_category") or result.get("PrimaryCategory") or ""
                ).strip(),
                "Category": classification,
                "Classification": classification,
                "Supplier": str(result.get("source") or "DigiKey"),
                "Manufacturer": str(result.get("manufacturer") or ""),
                "Stock": coerce_stock_total(result.get("stock_total", 0)),
                "Unit Price": result.get("unit_price", 0.0),
                "Lifecycle": str(
                    result.get("lifecycle_status") or result.get("Lifecycle") or "Unknown"
                ).strip() or "Unknown",
                **_candidate_risk_metadata(result),
                "Evidence Type": str(result.get("evidence_type") or "Supplier candidate"),
                "Substitute Type": substitute_type,
                "Evidence Source": str(result.get("source") or "DigiKey"),
                "Retrieval Status": str(result.get("retrieval_status") or "ok"),
                "Retrieved At": str(result.get("retrieved_at") or ""),
                "Product URL": str(result.get("product_detail_url") or ""),
                "Datasheet URL": str(result.get("datasheet_url") or ""),
                "Recommendation": build_classification_recommendation(
                    classification,
                    substitute_type=substitute_type,
                ),
                "Recommendation Score": 78 if substitute_type.casefold() == "direct" else 45,
                "Feature Tags": [],
                # Keep catalog vs explicit channel so retained-count refresh reconciles.
                "discovery_channel": str(result.get("discovery_channel") or "catalog"),
            }
        )
    return prepare_candidates_for_session_and_cache(salvage)


def assert_candidates_cache_serializable(candidates: list[dict[str, Any]]) -> None:
    """Raise when candidate payloads cannot be cached by Streamlit."""
    pickle.dumps(prepare_candidates_for_session_and_cache(candidates))


def _candidate_risk_metadata(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Score candidate lifecycle and distributor availability from recorded evidence."""
    lifecycle = str(
        candidate.get("lifecycle_status")
        or candidate.get("Lifecycle")
        or candidate.get("Lifecycle Status")
        or "Unknown"
    ).strip() or "Unknown"
    risk_inputs: dict[str, Any] = {
        "lifecycle_status": lifecycle,
        "lifecycle_conflict": bool(candidate.get("lifecycle_conflict")),
        "lead_time_weeks": candidate.get("lead_time_weeks"),
    }
    stock = parse_stock_total(candidate.get("stock_total", candidate.get("Stock")))
    if stock is not None:
        risk_inputs["stock_total"] = stock
        risk_inputs["stock_data_complete"] = bool(
            candidate.get("stock_data_complete", True)
        )
    risk = calculate_risk(risk_inputs)
    reasons = list(risk.get("risk_reasons") or [])
    lifecycle_unknown = lifecycle.casefold() in {
        "", "unknown", "unverified", "n/a", "not available", "unavailable",
    }
    risk_level = risk.get("risk_level") or "Needs verification"
    if lifecycle_unknown:
        note = "Manufacturer lifecycle status is not confirmed by the retrieved supplier record."
        if note not in reasons:
            reasons.append(note)
        # A healthy distributor stock snapshot cannot substitute for lifecycle
        # evidence. Preserve a concrete medium/high supply warning when present;
        # otherwise require verification instead of presenting a reassuring Low.
        if risk_level == "Low":
            risk_level = "Needs verification"
    return {
        "Estimated Risk": risk_level,
        "Estimated Risk Score": risk.get("risk_score"),
        "Risk Reasons": reasons,
    }

ELECTRICAL_FIELDS = {
    "bandwidth_mhz": {
        "label": "Bandwidth",
        "display_key": "Bandwidth MHz",
        "unit": "MHz",
        "higher_is_better": True,
        "weight": 8,
    },
    "slew_rate_v_us": {
        "label": "Slew rate",
        "display_key": "Slew Rate V/us",
        "unit": "V/µs",
        "higher_is_better": True,
        "weight": 8,
    },
    "input_offset_mv": {
        "label": "Input offset voltage",
        "display_key": "Input Offset mV",
        "unit": "mV",
        "higher_is_better": False,
        "weight": 5,
    },
    "input_bias_na": {
        "label": "Input bias current",
        "display_key": "Input Bias nA",
        "unit": "nA",
        "higher_is_better": False,
        "weight": 5,
    },
    "quiescent_current_ma": {
        "label": "Quiescent current",
        "display_key": "Quiescent Current mA",
        "unit": "mA",
        "higher_is_better": False,
        "weight": 4,
    },
    "gbw_mhz": {
        "label": "Gain bandwidth",
        "display_key": "GBW MHz",
        "unit": "MHz",
        "higher_is_better": True,
        "weight": 6,
    },
}

FEATURE_TAGS = {
    "rail_to_rail": {
        "label": "Rail-to-rail",
        "positive_weight": 8,
        "mismatch_penalty": 6,
    },
    "low_noise": {
        "label": "Low-noise",
        "positive_weight": 6,
        "mismatch_penalty": 4,
    },
    "low_power": {
        "label": "Low-power",
        "positive_weight": 5,
        "mismatch_penalty": 4,
    },
    "jfet_input": {
        "label": "JFET input",
        "positive_weight": 5,
        "mismatch_penalty": 5,
    },
    "cmos_input": {
        "label": "CMOS input",
        "positive_weight": 5,
        "mismatch_penalty": 5,
    },
    "automotive_grade": {
        "label": "Automotive-grade",
        "positive_weight": 6,
        "mismatch_penalty": 5,
    },
    "precision": {
        "label": "Precision",
        "positive_weight": 6,
        "mismatch_penalty": 4,
    },
}

SCORING_WEIGHTS = {
    "logic_function_match": 60,
    "unknown_logic_function": 10,

    "architecture_exact_match": 40,
    "architecture_opamp_family_match": 25,
    "architecture_partial_match": 10,

    "package_exact_match": 25,
    "same_pin_package_penalty": -8,
    "package_mismatch_penalty": -15,

    "package_family_match": 10,
    "package_family_mismatch_penalty": -25,

    "pin_count_match": 20,
    "pin_count_mismatch_penalty": -20,

    "channel_count_match": 15,
    "channel_count_mismatch_penalty": -25,

    "voltage_full_coverage": 15,
    "voltage_partial_overlap": 5,
    "voltage_mismatch_penalty": -20,
    "voltage_available_bonus": 3,
    "bonus_extra_feature": 2,
}

def safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        return None

def infer_feature_tags(text: str) -> set:
    text = str(text or "").lower()
    tags = set()

    if "rail-to-rail" in text or "rail to rail" in text or "rrio" in text:
        tags.add("rail_to_rail")

    if "low noise" in text or "low-noise" in text:
        tags.add("low_noise")

    if "low power" in text or "low-power" in text or "micropower" in text:
        tags.add("low_power")

    if "jfet" in text or "fet input" in text:
        tags.add("jfet_input")

    if "cmos" in text:
        tags.add("cmos_input")

    if "automotive" in text or "aec-q100" in text or "aec q100" in text:
        tags.add("automotive_grade")

    if "precision" in text or "low offset" in text:
        tags.add("precision")

    return tags

def compare_parts(original_part_number: str, alternative_part_numbers: list) -> pd.DataFrame:
    """
    Compares an original component against user-provided alternative parts.

    This is v1:
    - User provides the alternative MPNs manually
    - App pulls supplier data
    - App calculates risk
    - App builds side-by-side comparison table
    """

    all_parts = [original_part_number] + alternative_part_numbers

    comparison_results = []

    for index, part_number in enumerate(all_parts):
        part_data = get_best_part_data(part_number)

        part_data["quantity"] = 1
        risk_result = calculate_risk(part_data)

        comparison_results.append(
            {
                "Role": "Original" if index == 0 else "Alternative",
                "MPN Searched": part_number,
                "Matched MPN": part_data.get("manufacturer_part_number", ""),
                "Manufacturer": part_data.get("manufacturer", ""),
                "Description": part_data.get("description", ""),
                "Best Source": part_data.get("source", ""),
                "Supplier Count": part_data.get("supplier_count", 0),
                "Total Market Stock": part_data.get("total_market_stock", 0),
                "Stock Available": part_data.get("stock_total", 0),
                "Lifecycle Status": part_data.get("lifecycle_status", "Unknown"),
                "Risk Score": risk_result["risk_score"],
                "Risk Level": risk_result["risk_level"],
                "Risk Reasons": "; ".join(risk_result["risk_reasons"]) or "No major risk found",
                "Product URL": part_data.get("product_detail_url", ""),
            }
        )

    return pd.DataFrame(comparison_results)

def suggest_alternatives_v1(original_part_number: str) -> list:
    """
    Suggests alternative part numbers using a simple rule-based approach.

    V1 is intentionally conservative:
    - It does NOT guarantee form-fit-function compatibility.
    - It provides common candidate alternatives for testing the workflow.
    - Later, this will be replaced with supplier search + datasheet/spec matching.
    """

    known_alternatives = {
        "LM555CN/NOPB": ["NE555P", "TLC555CP", "LMC555CN/NOPB"],
        "LM555": ["NE555P", "TLC555CP", "LMC555CN/NOPB"],
        "NE555P": ["LM555CN/NOPB", "TLC555CP", "LMC555CN/NOPB"],
    }

    normalized_part = original_part_number.strip().upper()

    return known_alternatives.get(normalized_part, [])

def calculate_recommendation_score(candidate: dict) -> int:
    base_score = int(candidate.get("Recommendation Score", 70))
    score = round(base_score * 0.3)
    reasons = []

    lifecycle = str(candidate.get("Lifecycle", "")).lower()
    stock = coerce_stock_total(candidate.get("Stock", 0))
    supplier = str(candidate.get("Supplier", "")).strip()
    unit_price = float(candidate.get("Unit Price", 0.0))

    architecture = str(candidate.get("Architecture", "")).lower()
    package = str(candidate.get("Package", "")).lower()
    pin_count = effective_pin_count(candidate)
    voltage_range = str(candidate.get("Voltage Range", "")).lower()

    # Lif