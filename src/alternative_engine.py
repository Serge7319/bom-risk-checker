import pickle
import re
from typing import Any, Mapping, Optional

import pandas as pd

from integrations.pin_count import effective_pin_count
from integrations.stock_coercion import coerce_stock_total
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
    refine_classification_after_comparison,
)
import streamlit as st

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
                "Category": classification,
                "Classification": classification,
                "Supplier": str(result.get("source") or "DigiKey"),
                "Manufacturer": str(result.get("manufacturer") or ""),
                "Stock": coerce_stock_total(result.get("stock_total", 0)),
                "Unit Price": result.get("unit_price", 0.0),
                "Lifecycle": "Unknown",
                "Estimated Risk": "Unknown",
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
            }
        )
    return prepare_candidates_for_session_and_cache(salvage)


def assert_candidates_cache_serializable(candidates: list[dict[str, Any]]) -> None:
    """Raise when candidate payloads cannot be cached by Streamlit."""
    pickle.dumps(prepare_candidates_for_session_and_cache(candidates))

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

    # Lifecycle scoring
    if "active" in lifecycle:
        score += 10
        reasons.append("Active lifecycle")

    if "not recommended" in lifecycle or "nrnd" in lifecycle:
        score -= 15
        reasons.append("Lifecycle caution")

    if "obsolete" in lifecycle:
        score -= 40
        reasons.append("Obsolete lifecycle")

    # Stock scoring
    if stock > 10000:
        score += 10
        reasons.append("High stock")

    elif stock > 1000:
        score += 5
        reasons.append("Good stock")

    elif stock == 0:
        score -= 15
        reasons.append("No stock")

    # Supplier availability bonus
    if supplier and candidate.get("Category") != "Live Supplier Verification":
        score += 5
        reasons.append("Supplier verified")

    # Price bonus
    if (
        unit_price > 0
        and unit_price < 3
        and candidate.get("Category") != "Live Supplier Verification"
    ):
        score += 5
        reasons.append("Low unit price")

    # Engineering compatibility scoring
    if architecture == "avr":
        score += 20
        reasons.append("Compatible MCU architecture")

    elif "operational amplifier" in architecture:
        score += 5
        reasons.append("Operational amplifier candidate")

    elif architecture:
        score -= 10
        reasons.append("Architecture requires review")

    elif architecture:
        score -= 20
        reasons.append("Different MCU architecture")

    # Package / pin-count compatibility scoring
    if pin_count in [28, 32]:
        score += 5
        reasons.append("Similar pin count")

    elif pin_count >= 40:
        score -= 5
        reasons.append("Higher pin-count migration")

    # Voltage compatibility scoring
    if "5.5v" in voltage_range:
        score += 5
        reasons.append("Wide voltage compatibility")

    elif "3.6v" in voltage_range:
        score -= 3
        reasons.append("Lower voltage ceiling")
    
    # Package compatibility scoring
    if "tqfp" in package:
        score += 5
        reasons.append("Surface-mount package")

    elif "dip" in package:
        score -= 3
        reasons.append("Package change likely")
    
    recommendation = str(candidate.get("Recommendation", "")).lower()

    if "lm358-family" in recommendation:
        score += 10
        reasons.append("Same LM358 family")

    elif "common dual op-amp alternative" in recommendation:
        score += 5
        reasons.append("General dual op-amp alternative")

    if "best drop-in" in recommendation:
        score += 15
        reasons.append("Best drop-in candidate")

    elif "reduced resources" in recommendation:
        score -= 5
        reasons.append("Reduced resource capacity")

    elif "usb-capable" in recommendation:
        score -= 3
        reasons.append("Board/firmware changes likely")

    drop_in_confidence = int(
        candidate.get("Drop-In Confidence", 0) or 0
    )

    score += round(drop_in_confidence * 0.2)

    score = max(0, min(score, 98))

    if "best drop-in" in recommendation:
        score = 100

    candidate["Score Reasons"] = "; ".join(reasons)

    return score


def _enrich_part_data_from_suppliers(part_data: dict) -> dict:
    """Preserve passive parametrics from any configured supplier response."""
    enriched = dict(part_data or {})
    valid_results = [
        result
        for result in (enriched.get("all_supplier_results") or [])
        if result.get("provider_status") == "available"
    ]
    for field_name in PASSIVE_PARAMETRIC_KEYS:
        if enriched.get(field_name) not in (None, "", 0):
            continue
        for result in valid_results:
            value = result.get(field_name)
            if value not in (None, "", 0):
                enriched[field_name] = value
                break
    return enriched


def _merge_supplier_part_data(*sources: dict) -> dict:
    merged: dict = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if value not in (None, "", 0):
                merged[key] = value
    return _enrich_part_data_from_suppliers(merged)


_SMD_PACKAGE_CODES = frozenset(
    {"01005", "0201", "0204", "0402", "0603", "0805", "1206", "1210", "1812", "2010", "2512"}
)


def _mlcc_tolerance_from_mpn(mpn: str) -> str:
    """Infer MLCC tolerance letter codes from capacitor MPNs only.

    Must never be applied to resistors/inductors/ICs — EIA digit+letter patterns
    appear in many non-capacitor ordering codes.
    """
    upper = str(mpn or "").upper()
    for index in range(max(len(upper) - 3, 0)):
        digits = upper[index : index + 3]
        suffix = upper[index + 3 : index + 4]
        if len(digits) == 3 and digits.isdigit() and suffix.isalpha():
            tolerance = {
                "G": "±2%",
                "J": "±5%",
                "K": "±10%",
                "M": "±20%",
                "Z": "±80%",
            }.get(suffix)
            if tolerance:
                return tolerance
    return ""


def _discovery_row_to_part_data(row: dict) -> dict:
    """Build comparison-ready supplier fields from DigiKey discovery evidence."""
    from src.datasheet_comparison import infer_component_family

    mpn = str(row.get("manufacturer_part_number") or "").strip()
    description = str(row.get("description") or "").strip()
    package = str(row.get("package") or "").strip()
    family = infer_component_family(
        {
            "description": description,
            "manufacturer_part_number": mpn,
            "architecture": str(row.get("architecture") or "").strip(),
        }
    )
    # C-prefix EIA size codes are capacitor ordering conventions only.
    if (
        not package
        and family == "Capacitor"
        and mpn.upper().startswith("C")
        and len(mpn) >= 4
    ):
        size_code = mpn[1:5]
        if size_code.isdigit():
            package = size_code
    passive_fields = _passive_fields_from_description(description)
    for key in PASSIVE_PARAMETRIC_KEYS:
        value = row.get(key)
        if value not in (None, "", 0):
            passive_fields[key] = value
    if package in _SMD_PACKAGE_CODES:
        passive_fields.setdefault("mounting_style", "Surface Mount")
    if family == "Capacitor":
        mlcc_tolerance = _mlcc_tolerance_from_mpn(mpn)
        if mlcc_tolerance:
            passive_fields.setdefault("tolerance", mlcc_tolerance)
    return {
        "manufacturer_part_number": mpn,
        "manufacturer": str(row.get("manufacturer") or "").strip(),
        "description": description,
        "stock_total": coerce_stock_total(row.get("stock_total", 0)),
        "unit_price": row.get("unit_price", 0.0),
        "datasheet_url": str(row.get("datasheet_url") or "").strip(),
        "package": package or passive_fields.get("package", ""),
        "mounting_style": str(row.get("mounting_style") or passive_fields.get("mounting_style", "")).strip(),
        "pin_count": effective_pin_count(
            {
                "pin_count": row.get("pin_count", 0),
                "package": package or passive_fields.get("package", ""),
            }
        ),
        "architecture": str(row.get("architecture") or "").strip(),
        "channel_count": row.get("channel_count", 0),
        "voltage_range": str(row.get("voltage_range") or "").strip(),
        "lifecycle_status": str(row.get("lifecycle_status") or row.get("Lifecycle") or "").strip(),
        "source": str(row.get("source") or "DigiKey"),
        "supplier_data_verified": bool(mpn),
        **passive_fields,
    }


def _passive_fields_from_description(description: str) -> dict:
    """Extract coarse Cap/R/L parametrics from distributor product descriptions."""
    fields: dict = {}
    text = str(description or "").strip()
    if not text:
        return fields
    lowered = text.casefold()
    if "surface mount" in lowered or "mlcc" in lowered or "smd" in lowered:
        fields["mounting_style"] = "Surface Mount"
    for token in text.replace(",", " ").split():
        normalized = token.strip("()[]")
        token_lower = normalized.casefold()
        if token_lower.endswith("uf") and any(ch.isdigit() for ch in normalized):
            value = normalized[:-2]
            fields.setdefault("capacitance", f"{value} µF")
        elif token_lower.endswith(("µf", "μf")) and any(ch.isdigit() for ch in normalized):
            value = normalized[:-2]
            fields.setdefault("capacitance", f"{value} µF")
        if (
            token_lower.endswith("ohm")
            or normalized.endswith("Ω")
            or normalized.endswith("Ω")
            or token_lower.endswith("ω")
        ) and any(ch.isdigit() for ch in normalized):
            fields.setdefault("resistance", normalized)
        elif re.fullmatch(r"\d+(\.\d+)?k", token_lower):
            fields.setdefault("resistance", f"{normalized[:-1]} kΩ")
        elif re.fullmatch(r"\d+(\.\d+)?r", token_lower):
            fields.setdefault("resistance", f"{normalized[:-1]} Ω")
        if token_lower.endswith(("uh", "µh", "μh")) and any(ch.isdigit() for ch in normalized):
            value = normalized[:-2]
            fields.setdefault("inductance", f"{value} µH")
        elif token_lower.endswith("mh") and any(ch.isdigit() for ch in normalized):
            value = normalized[:-2]
            fields.setdefault("inductance", f"{value} mH")
        elif token_lower.endswith("nh") and any(ch.isdigit() for ch in normalized):
            value = normalized[:-2]
            fields.setdefault("inductance", f"{value} nH")
        if token_lower.endswith("v") and token_lower[:-1].replace(".", "").isdigit():
            fields.setdefault("rated_voltage", normalized.upper())
        if token_lower.endswith("w") and token_lower[:-1].replace(".", "").isdigit():
            fields.setdefault("power_rating", normalized.upper())
        if token_lower in {"x7r", "x5r", "c0g", "np0", "y5v"}:
            fields.setdefault("dielectric", normalized.upper())
            fields.setdefault("temperature_coefficient", normalized.upper())
        if token_lower in {"±10%", "±5%", "±1%", "10%", "5%", "1%"}:
            fields.setdefault("tolerance", normalized)
        if normalized.isdigit() and len(normalized) == 4 and normalized.startswith(("0", "1", "2")):
            fields.setdefault("package", normalized)
    return fields


def _passive_compatibility_confidence(counts: dict, *, classification: str = "", substitute_type: str = "") -> int:
    assessment = build_engineering_evidence_assessment(
        counts,
        classification=classification,
        substitute_type=substitute_type,
    )
    return int(assessment["engineering_comparison_confidence"])


def _passive_drop_in_reasons(rows: list) -> str:
    parts = []
    for row in rows or []:
        attribute = str(row.get("Attribute") or "").strip()
        status = str(row.get("Status") or "").strip()
        if not attribute:
            continue
        if status == "Match":
            parts.append(f"✓ {attribute} matches")
        elif status == "Different":
            parts.append(f"⚠ {attribute} differs")
        elif status == "Needs data":
            parts.append(f"ℹ {attribute} needs verification from retrieved evidence")
    return "; ".join(parts)


def calculate_drop_in_confidence(original: dict, candidate: dict) -> int:
    family = str(
        candidate.get("Comparison Family")
        or infer_component_family(original)
    )
    profile = get_family_profile(family)
    if family in PASSIVE_FAMILIES or profile.scoring_mode in {
        "parametric_matrix",
        "resource_device",
    } or family in DISCRETE_PARAMETRIC_FAMILY_IDS:
        counts = candidate.get("Comparison Counts")
        rows = candidate.get("Comparison Rows")
        if not isinstance(rows, list) or not isinstance(counts, dict):
            comparison = build_datasheet_comparison(original, candidate)
            rows = comparison.get("rows", [])
            counts = comparison.get("counts", {})
            family = comparison.get("family") or family
        assessment = build_engineering_evidence_assessment(
            counts if isinstance(counts, dict) else {},
            classification=str(candidate.get("Classification") or ""),
            substitute_type=str(candidate.get("Substitute Type") or ""),
            comparison_rows=rows if isinstance(rows, list) else None,
            family=family,
        )
        return int(assessment["engineering_comparison_confidence"])
    score = 0

    original_architecture = str(
        original.get("Architecture", original.get("architecture", ""))
    ).lower()

    candidate_architecture = str(
        candidate.get("Architecture", candidate.get("architecture", ""))
    ).lower()

    original_function = str(
        original.get("Function", original.get("function", ""))
    ).lower()

    candidate_function = str(
        candidate.get("Function", candidate.get("function", ""))
    ).lower()

    original_package = str(
        original.get("Package", original.get("package", ""))
    ).lower()

    candidate_package = str(
        candidate.get("Package", candidate.get("package", ""))
    ).lower()

    original_pin_count = effective_pin_count(original)

    candidate_pin_count = effective_pin_count(candidate)

    original_channel_count = int(
        original.get("Channel Count", original.get("channel_count", 0)) or 0
    )

    candidate_channel_count = int(
        candidate.get("Channel Count", candidate.get("channel_count", 0)) or 0
    )

    original_voltage_min = original.get(
        "Supply Voltage Min",
        original.get("supply_voltage_min"),
    )

    original_voltage_max = original.get(
        "Supply Voltage Max",
        original.get("supply_voltage_max"),
    )

    candidate_voltage_min = candidate.get(
        "Supply Voltage Min",
        candidate.get("supply_voltage_min"),
    )

    candidate_voltage_max = candidate.get(
        "Supply Voltage Max",
        candidate.get("supply_voltage_max"),
    )

    original_voltage_min = float(original_voltage_min) if original_voltage_min is not None else None
    original_voltage_max = float(original_voltage_max) if original_voltage_max is not None else None
    candidate_voltage_min = float(candidate_voltage_min) if candidate_voltage_min is not None else None
    candidate_voltage_max = float(candidate_voltage_max) if candidate_voltage_max is not None else None


    candidate_voltage = str(
        candidate.get("Voltage Range", candidate.get("voltage_range", ""))
    ).lower()

    # Function match is most important for logic ICs.
    if "logic" in original_architecture or "logic" in candidate_architecture:
        if original_function and candidate_function:
            if original_function == candidate_function:
                score += SCORING_WEIGHTS["logic_function_match"]
            else:
                return 0
        else:
            score += SCORING_WEIGHTS["unknown_logic_function"]

    elif original_architecture and candidate_architecture:
        incompatible_pairs = [
            ("operational amplifier", "comparator"),
            ("comparator", "operational amplifier"),
            ("linear regulator", "ldo regulator"),
            ("ldo regulator", "linear regulator"),
        ]

        for original_type, candidate_type in incompatible_pairs:
            if original_type in original_architecture and candidate_type in candidate_architecture:
                return 0

        if original_architecture == candidate_architecture:
            score += SCORING_WEIGHTS["architecture_exact_match"]
        elif (
            "operational amplifier" in original_architecture
            and "operational amplifier" in candidate_architecture
        ):
            score += SCORING_WEIGHTS["architecture_opamp_family_match"]
        else:
            score += SCORING_WEIGHTS["architecture_partial_match"]

    normalized_original_package = normalize_package_name(original_package)
    normalized_candidate_package = normalize_package_name(candidate_package)

    if normalized_original_package and normalized_candidate_package:
        if normalized_original_package == normalized_candidate_package:
            score += SCORING_WEIGHTS["package_exact_match"]
        elif (
            normalized_original_package.endswith("-8")
            and normalized_candidate_package.endswith("-8")
        ):
            score += SCORING_WEIGHTS["same_pin_package_penalty"]
        else:
            score += SCORING_WEIGHTS["package_mismatch_penalty"]

    original_package_family = package_family(original_package)
    candidate_package_family = package_family(candidate_package)

    if original_package_family and candidate_package_family:
        if original_package_family == candidate_package_family:
            score += SCORING_WEIGHTS["package_family_match"]
        else:
            score += SCORING_WEIGHTS["package_family_mismatch_penalty"]

    if original_pin_count and candidate_pin_count:
        if original_pin_count == candidate_pin_count:
            score += SCORING_WEIGHTS["pin_count_match"]
        else:
            score += SCORING_WEIGHTS["pin_count_mismatch_penalty"]

    if original_channel_count and candidate_channel_count:
        if original_channel_count == candidate_channel_count:
            score += SCORING_WEIGHTS["channel_count_match"]
        else:
            score += SCORING_WEIGHTS["channel_count_mismatch_penalty"]

    if (
        original_voltage_min is not None
        and original_voltage_max is not None
        and candidate_voltage_min is not None
        and candidate_voltage_max is not None
    ):
        if candidate_voltage_min <= original_voltage_min and candidate_voltage_max >= original_voltage_max:
            score += SCORING_WEIGHTS["voltage_full_coverage"]
        elif candidate_voltage_min <= original_voltage_max and candidate_voltage_max >= original_voltage_min:
            score += SCORING_WEIGHTS["voltage_partial_overlap"]
        else:
            score += SCORING_WEIGHTS["voltage_mismatch_penalty"]
    elif candidate_voltage and candidate_voltage not in ["none", "n/a"]:
        score += SCORING_WEIGHTS["voltage_available_bonus"]

    for field_name, config in ELECTRICAL_FIELDS.items():
        original_value = safe_float(
            original.get(config["display_key"], original.get(field_name))
        )
        candidate_value = safe_float(
            candidate.get(config["display_key"], candidate.get(field_name))
        )

        if original_value is None or candidate_value is None:
            continue

        if config["higher_is_better"]:
            if candidate_value >= original_value:
                score += config["weight"]
            else:
                score -= config["weight"]
        else:
            if candidate_value <= original_value:
                score += config["weight"]
            else:
                score -= config["weight"]

    original_tags = original.get("Feature Tags", set()) or set()
    candidate_tags = candidate.get("Feature Tags", set()) or set()

    for tag_name, config in FEATURE_TAGS.items():
        original_has_tag = tag_name in original_tags
        candidate_has_tag = tag_name in candidate_tags

        if original_has_tag and candidate_has_tag:
            score += config["positive_weight"]

        elif original_has_tag and not candidate_has_tag:
            score -= config["mismatch_penalty"]

        elif candidate_has_tag and not original_has_tag:
            score += SCORING_WEIGHTS["bonus_extra_feature"]

    return max(0, min(score, 100))

    
def get_drop_in_rating(confidence: int) -> str:
    if confidence >= 80:
        return "🟢 High"

    elif confidence >= 50:
        return "🟡 Medium"

    return "🔴 Low"


def get_drop_in_reasons(original: dict, candidate: dict) -> str:
    family = str(
        candidate.get("Comparison Family")
        or infer_component_family(original)
    )
    comparison_rows = candidate.get("Comparison Rows")
    if family in PASSIVE_FAMILIES and isinstance(comparison_rows, list) and comparison_rows:
        return _passive_drop_in_reasons(comparison_rows)

    reasons = []


    original_architecture = str(original.get("Architecture", original.get("architecture", ""))).lower()
    candidate_architecture = str(candidate.get("Architecture", candidate.get("architecture", ""))).lower()

    original_function = str(original.get("Function", original.get("function", ""))).strip()
    candidate_function = str(candidate.get("Function", candidate.get("function", ""))).strip()

    original_package = str(original.get("Package", original.get("package", ""))).strip()
    candidate_package = str(candidate.get("Package", candidate.get("package", ""))).strip()

    original_pin_count = effective_pin_count(original)
    candidate_pin_count = effective_pin_count(candidate)

    original_channel_count = int(
    original.get("Channel Count", original.get("channel_count", 0)) or 0
    )

    candidate_channel_count = int(
        candidate.get("Channel Count", candidate.get("channel_count", 0)) or 0
    )

    original_voltage_min = original.get(
        "Supply Voltage Min",
        original.get("supply_voltage_min"),
    )

    original_voltage_max = original.get(
        "Supply Voltage Max",
        original.get("supply_voltage_max"),
    )

    candidate_voltage_min = candidate.get(
        "Supply Voltage Min",
        candidate.get("supply_voltage_min"),
    )

    candidate_voltage_max = candidate.get(
        "Supply Voltage Max",
        candidate.get("supply_voltage_max"),
    )

    original_voltage_min = (
        float(original_voltage_min)
        if original_voltage_min is not None
        else None
    )

    original_voltage_max = (
        float(original_voltage_max)
        if original_voltage_max is not None
        else None
    )

    candidate_voltage_min = (
        float(candidate_voltage_min)
        if candidate_voltage_min is not None
        else None
    )

    candidate_voltage_max = (
        float(candidate_voltage_max)
        if candidate_voltage_max is not None
        else None
    )

    candidate_voltage = str(candidate.get("Voltage Range", candidate.get("voltage_range", ""))).strip()

    if original_function and candidate_function:
        if original_function.lower() == candidate_function.lower():
            reasons.append(f"✓ Same function ({candidate_function})")
        else:
            reasons.append(f"⚠ Function differs ({candidate_function})")

    if original_architecture and candidate_architecture:
        if original_architecture == candidate_architecture:
            reasons.append(
                f"✓ Same architecture ({candidate.get('Architecture', candidate.get('architecture', ''))})")
        else:
            reasons.append("⚠ Architecture differs")

    if not original_function and not original_architecture:
        reasons.append("⚠ Original architecture could not be verified")

    normalized_original_package = normalize_package_name(original_package)
    normalized_candidate_package = normalize_package_name(candidate_package)

    if normalized_original_package and normalized_candidate_package:
        if normalized_original_package == normalized_candidate_package:
            reasons.append(f"✓ Same package ({normalized_candidate_package})")
        else:
            reasons.append(
                f"⚠ Package differs: original {normalized_original_package}, alternative {normalized_candidate_package}"
            )

    original_package_family = package_family(original_package)
    candidate_package_family = package_family(candidate_package)

    if original_package_family and candidate_package_family:
        if original_package_family == candidate_package_family:
            reasons.append(
                f"✓ Same package family ({candidate_package_family})"
            )
        else:
            reasons.append(
                f"⚠ Package mounting style differs: original {original_package_family}, alternative {candidate_package_family}"
            )


    if not normalized_original_package:
        reasons.append("ℹ Package compatibility could not be verified from supplier data")

    if original_pin_count and candidate_pin_count:
        if original_pin_count == candidate_pin_count:
            reasons.append(f"✓ Same pin count ({candidate_pin_count})")
        else:
            reasons.append(f"⚠ Pin count differs: original {original_pin_count}, alternative {candidate_pin_count}")

    if original_channel_count and candidate_channel_count:
        if original_channel_count == candidate_channel_count:
            reasons.append(
                f"✓ Same channel count ({candidate_channel_count})"
            )
        else:
            reasons.append(
                f"⚠ Channel count differs: original {original_channel_count}, alternative {candidate_channel_count}"
            )

    original_voltage = str(
        original.get("Voltage Range", original.get("voltage_range", ""))
    ).strip()

    candidate_voltage = str(
        candidate.get("Voltage Range", candidate.get("voltage_range", ""))
    ).strip()

    original_min_v, original_max_v = extract_voltage_limits(original_voltage)
    candidate_min_v, candidate_max_v = extract_voltage_limits(candidate_voltage)

    if original_min_v and original_max_v and candidate_min_v and candidate_max_v:
        if candidate_min_v <= original_min_v and candidate_max_v >= original_max_v:
            reasons.append(
                f"✓ Supply voltage range covers original ({candidate_voltage})"
            )
        elif candidate_min_v <= original_max_v and candidate_max_v >= original_min_v:
            reasons.append(
                f"⚠ Supply voltage range partially overlaps original ({candidate_voltage})"
            )
        else:
            reasons.append(
                f"⚠ Supply voltage range may not be compatible ({candidate_voltage})"
            )
    elif candidate_voltage and candidate_voltage.lower() not in ["none", "n/a"]:
        reasons.append(
            f"ℹ Candidate voltage range listed ({candidate_voltage}); verify against original requirements"
        )

    for field_name, config in ELECTRICAL_FIELDS.items():
        original_value = safe_float(
            original.get(config["display_key"], original.get(field_name))
        )
        candidate_value = safe_float(
            candidate.get(config["display_key"], candidate.get(field_name))
        )

        if original_value is None or candidate_value is None:
            continue

        label = config["label"]
        unit = config["unit"]

        if config["higher_is_better"]:
            if candidate_value >= original_value:
                reasons.append(
                    f"✓ {label} meets or exceeds original ({candidate_value} {unit} vs {original_value} {unit})"
                )
            else:
                reasons.append(
                    f"⚠ {label} is lower than original ({candidate_value} {unit} vs {original_value} {unit})"
                )
        else:
            if candidate_value <= original_value:
                reasons.append(
                    f"✓ {label} meets or improves original ({candidate_value} {unit} vs {original_value} {unit})"
                )
            else:
                reasons.append(
                    f"⚠ {label} is higher than original ({candidate_value} {unit} vs {original_value} {unit})"
                )

    original_tags = original.get("Feature Tags", set()) or set()
    candidate_tags = candidate.get("Feature Tags", set()) or set()

    for tag_name, config in FEATURE_TAGS.items():
        original_has_tag = tag_name in original_tags
        candidate_has_tag = tag_name in candidate_tags

        if original_has_tag and candidate_has_tag:
            reasons.append(f"✓ Shared feature: {config['label']}")

        elif original_has_tag and not candidate_has_tag:
            reasons.append(f"⚠ Original has {config['label']} feature, but candidate does not")

        elif candidate_has_tag and not original_has_tag:
            reasons.append(f"＋ Candidate adds {config['label']} capability")

    return "; ".join(reasons)

def normalize_package_name(package: str) -> str:
    package = str(package or "").upper().strip()

    if not package:
        return ""

    package = package.replace(" ", "-")

    if any(term in package for term in ["PDIP", "NPDIP", "DIP"]):
        if "16" in package:
            return "DIP-16"
        if "14" in package:
            return "DIP-14"
        if "8" in package:
            return "DIP-8"
        if "4" in package:
            return "DIP-4"

    if "TO-220" in package:
        return "TO-220"

    if "SOT-223" in package:
        return "SOT-223"

    if "SOIC" in package and "8" in package:
        return "SOIC-8"

    if "SOIC" in package and "14" in package:
        return "SOIC-14"

    return package


def infer_architecture_from_description(description: str) -> str:
    description = str(description).lower()

    if "op amp" in description or "operational amplifier" in description:
        return "Operational Amplifier"

    if "comparator" in description:
        return "Comparator"

    if "shift register" in description:
        return "Shift Register"

    if "inverter" in description:
        return "Hex Inverter"

    if "flip flop" in description:
        return "Flip-Flop"

    if "voltage regulator" in description:
        return "Voltage Regulator"

    return ""

def infer_channel_count_from_description(description: str) -> int:
    description = str(description or "").lower()

    if "dual" in description or "2 channels" in description or "2-channel" in description:
        return 2

    if "quad" in description or "4 channels" in description or "4-channel" in description:
        return 4

    if "single" in description or "1 channel" in description or "1-channel" in description:
        return 1

    return 0

import re

def extract_voltage_limits(voltage_text: str) -> tuple:
    text = str(voltage_text or "").lower().replace(" ", "")

    matches = re.findall(r"(\d+(?:\.\d+)?)v", text)

    if len(matches) >= 2:
        return float(matches[0]), float(matches[1])

    if len(matches) == 1:
        value = float(matches[0])
        return value, value

    return 0.0, 0.0

def package_family(package: str) -> str:
    normalized = normalize_package_name(package)

    if not normalized:
        return ""

    if "DIP" in normalized or "TO-220" in normalized or "TO-92" in normalized:
        return "Through-Hole"

    if (
        "SOIC" in normalized
        or "SOT" in normalized
        or "QFN" in normalized
        or "TQFP" in normalized
        or "LQFP" in normalized
        or "SMD" in normalized
        or "SMT" in normalized
    ):
        return "Surface-Mount"

    return "Unknown"


    return fields


def apply_supplier_enrichment_to_candidate(
    *,
    original_data: dict,
    candidate: dict,
    candidate_supplier_data: dict,
    canonical_part_number: str,
) -> dict:
    """Apply supplier evidence to one candidate and rebuild comparison metadata."""
    enriched = dict(candidate)
    supplier_data = dict(candidate_supplier_data or {})

    for candidate_key, supplier_key in (
        ("Package", "package"),
        ("Pin Count", "pin_count"),
        ("Mounting Style", "mounting_style"),
        ("Architecture", "architecture"),
    ):
        if supplier_data.get(supplier_key) not in (None, "", 0):
            enriched[candidate_key] = supplier_data.get(supplier_key)

    enriched["Pin Count"] = effective_pin_count(
        {
            "pin_count": enriched.get("Pin Count", 0),
            "package": enriched.get("Package", ""),
        }
    )

    enriched["Supply Voltage Min"] = enriched.get("Supply Voltage Min") or supplier_data.get("supply_voltage_min")
    enriched["Supply Voltage Max"] = enriched.get("Supply Voltage Max") or supplier_data.get("supply_voltage_max")
    enriched["Voltage Range"] = enriched.get("Voltage Range") or supplier_data.get("voltage_range", "")
    enriched["Datasheet URL"] = enriched.get("Datasheet URL") or supplier_data.get("datasheet_url", "")

    for field_name, config in ELECTRICAL_FIELDS.items():
        enriched[config["display_key"]] = (
            enriched.get(config["display_key"])
            or supplier_data.get(field_name)
        )

    feature_text = " ".join(
        [
            str(enriched.get("Alternative Part", "")),
            str(enriched.get("Category", "")),
            str(enriched.get("Architecture", "")),
            str(enriched.get("Recommendation", "")),
            str(enriched.get("Compatibility Notes", "")),
            str(supplier_data.get("description", "")),
        ]
    )
    enriched["Feature Tags"] = infer_feature_tags(feature_text)

    original_candidate = {
        "Alternative Part": canonical_part_number,
        "Architecture": original_data.get("architecture", ""),
        "Package": original_data.get("package", "")
        or (
            "SMD-8"
            if original_data.get("mounting_style") == "SMD"
            and original_data.get("pin_count") == 8
            else ""
        ),
        "Pin Count": effective_pin_count(original_data),
        "Voltage Range": original_data.get("voltage_range", ""),
        "Channel Count": original_data.get("channel_count", 0),
        "Supply Voltage Min": original_data.get("supply_voltage_min"),
        "Supply Voltage Max": original_data.get("supply_voltage_max"),
        "Bandwidth MHz": original_data.get("bandwidth_mhz"),
        "Slew Rate V/us": original_data.get("slew_rate_v_us"),
        "Input Offset mV": original_data.get("input_offset_mv"),
        "Quiescent Current mA": original_data.get("quiescent_current_ma"),
        "Input Bias nA": original_data.get("input_bias_na"),
        "GBW MHz": original_data.get("gbw_mhz"),
        "capacitance": original_data.get("capacitance", ""),
        "resistance": original_data.get("resistance", ""),
        "inductance": original_data.get("inductance", ""),
        "tolerance": original_data.get("tolerance", ""),
        "rated_voltage": original_data.get("rated_voltage", ""),
        "dielectric": original_data.get("dielectric", ""),
        "power_rating": original_data.get("power_rating", ""),
        "temperature_coefficient": original_data.get("temperature_coefficient", ""),
        "esr": original_data.get("esr", ""),
        "dcr": original_data.get("dcr", ""),
        "rated_current": original_data.get("rated_current", ""),
        "saturation_current": original_data.get("saturation_current", ""),
        "Feature Tags": original_data.get("Feature Tags", set()),
    }

    candidate_comparison_data = dict(supplier_data or {})
    candidate_comparison_data.update({
        "description": candidate_comparison_data.get("description", ""),
        "architecture": enriched.get("Architecture", candidate_comparison_data.get("architecture", "")),
        "package": enriched.get("Package", candidate_comparison_data.get("package", "")),
        "pin_count": enriched.get("Pin Count", candidate_comparison_data.get("pin_count")),
        "mounting_style": enriched.get(
            "Mounting Style", candidate_comparison_data.get("mounting_style", "")
        ),
        "voltage_range": enriched.get("Voltage Range", candidate_comparison_data.get("voltage_range", "")),
        "channel_count": enriched.get("Channel Count", candidate_comparison_data.get("channel_count")),
    })
    for field_name, config in ELECTRICAL_FIELDS.items():
        candidate_comparison_data[field_name] = enriched.get(
            config["display_key"], candidate_comparison_data.get(field_name)
        )
    for parametric_key in all_parametric_keys(include_common=True):
        if candidate_comparison_data.get(parametric_key) not in (None, "", 0):
            continue
        if supplier_data.get(parametric_key) not in (None, "", 0):
            candidate_comparison_data[parametric_key] = supplier_data.get(parametric_key)
            continue
        if original_data.get(parametric_key) not in (None, "", 0):
            # Do not copy original values onto the candidate — leave Needs data.
            continue
        display_map = {
            "package": "Package",
            "pin_count": "Pin Count",
            "mounting_style": "Mounting Style",
            "architecture": "Architecture",
            "voltage_range": "Voltage Range",
        }
        display_key = display_map.get(parametric_key)
        if display_key and enriched.get(display_key) not in (None, "", 0):
            candidate_comparison_data[parametric_key] = enriched.get(display_key)
    comparison_result = build_datasheet_comparison(original_data, candidate_comparison_data)
    comparison_counts = comparison_result["counts"]
    enriched["Comparison Family"] = comparison_result.get("family", "")
    enriched["Comparison Rows"] = comparison_result.get("rows", [])
    enriched["Comparison Counts"] = comparison_counts
    classification = refine_classification_after_comparison(
        str(enriched.get("Classification") or CLASS_CATALOG_INSUFFICIENT),
        comparison_counts,
    )
    enriched["Classification"] = classification
    enriched["Category"] = classification
    from src.alternative_classification import pair_relationship_evidence_rows

    pair_evidence = pair_relationship_evidence_rows(
        {
            "supplier_relationship_evidence": list(
                enriched.get("Supplier Relationship Evidence")
                or enriched.get("supplier_relationship_evidence")
                or []
            ),
            "manufacturer_part_number": str(
                enriched.get("Alternative Part") or enriched.get("manufacturer_part_number") or ""
            ),
        },
        original_mpn=str(
            original_data.get("manufacturer_part_number")
            or enriched.get("Original MPN")
            or ""
        ),
        candidate_mpn=str(
            enriched.get("Alternative Part") or enriched.get("manufacturer_part_number") or ""
        ),
    )
    evidence_assessment = build_engineering_evidence_assessment(
        comparison_counts,
        classification=classification,
        substitute_type=str(enriched.get("Substitute Type") or ""),
        supplier_relationship_evidence=pair_evidence,
        evidence_source=str(enriched.get("Evidence Source") or ""),
        comparison_rows=comparison_result.get("rows"),
        family=str(comparison_result.get("family") or ""),
    )
    enriched["Engineering Evidence Assessment"] = evidence_assessment
    enriched["Engineering Evidence Summary"] = evidence_assessment["engineering_evidence_summary"]
    enriched["Engineering Comparison Confidence"] = evidence_assessment[
        "engineering_comparison_confidence"
    ]
    enriched["Supplier Relationship Confidence"] = evidence_assessment[
        "supplier_relationship_confidence"
    ]
    enriched["Supplier Relationship Summary"] = evidence_assessment[
        "supplier_relationship_summary"
    ]
    enriched["Drop-In Confidence"] = calculate_drop_in_confidence(
        original_candidate,
        enriched,
    )
    enriched["Drop-In Rating"] = get_drop_in_rating(enriched["Drop-In Confidence"])
    enriched["Drop-In Reasons"] = get_drop_in_reasons(original_candidate, enriched)
    score_evidence = build_recommendation_score_breakdown(
        enriched.get("Recommendation Score", 0),
        enriched["Drop-In Confidence"],
        comparison_counts,
        is_explicit_substitute=(classification == CLASS_VERIFIED_DIRECT),
    )
    enriched["Recommendation Score"] = score_evidence["recommendation_score"]
    enriched["Drop-In Confidence"] = score_evidence["compatibility_confidence"]
    comparison_family = str(enriched.get("Comparison Family") or "")
    profile = get_family_profile(comparison_family)
    if (
        comparison_family in PASSIVE_FAMILIES
        or comparison_family in DISCRETE_PARAMETRIC_FAMILY_IDS
        or profile.scoring_mode in {"parametric_matrix", "resource_device"}
    ):
        enriched["Drop-In Confidence"] = int(
            evidence_assessment["engineering_comparison_confidence"]
        )
    enriched["Drop-In Rating"] = get_drop_in_rating(enriched["Drop-In Confidence"])
    enriched["Datasheet Match Count"] = score_evidence["matches"]
    enriched["Datasheet Difference Count"] = score_evidence["differences"]
    enriched["Datasheet Needs Data Count"] = score_evidence["needs_data"]
    score_evidence["classification"] = classification
    score_evidence["evidence_source"] = enriched.get("Evidence Source", "")
    score_evidence["evidence_type"] = enriched.get("Evidence Type", "")
    score_evidence["substitute_type"] = enriched.get("Substitute Type", "")
    score_evidence.update(evidence_assessment)

    if supplier_data.get("supplier_data_verified"):
        enriched["Supplier"] = supplier_data.get("source") or enriched.get("Supplier", "")
        enriched["Sources Available"] = supplier_data.get("sources_available", "")
        enriched["Supplier Count"] = supplier_data.get("supplier_count", 0)
        enriched["Stock"] = coerce_stock_total(
            supplier_data.get("stock_total", enriched.get("Stock", 0))
        )
        enriched["Unit Price"] = supplier_data.get("unit_price", enriched.get("Unit Price", 0.0))
        if supplier_data.get("lifecycle_status"):
            enriched["Lifecycle"] = supplier_data.get("lifecycle_status")

    suitability = classify_recommendation_suitability(
        str(enriched.get("Lifecycle") or ""),
        source=str(enriched.get("Supplier") or enriched.get("Evidence Source") or ""),
    )
    suitability_adjustment = apply_suitability_score_adjustment(
        enriched.get("Recommendation Score", 0),
        suitability,
    )
    enriched["Recommendation Suitability"] = suitability
    enriched["Recommendation Score"] = suitability_adjustment["recommendation_score"]
    score_evidence["recommendation_score"] = suitability_adjustment["recommendation_score"]
    score_evidence["recommendation_suitability"] = suitability
    score_evidence["suitability_penalty"] = suitability_adjustment["suitability_penalty"]
    score_evidence["suitability_capped"] = bool(suitability_adjustment["suitability_capped"])
    enriched["Recommendation"] = build_classification_recommendation(
        classification,
        substitute_type=str(enriched.get("Substitute Type") or ""),
        suitability=suitability,
        lifecycle=str(enriched.get("Lifecycle") or ""),
        source=str(enriched.get("Supplier") or enriched.get("Evidence Source") or ""),
    )
    enriched["Recommendation Score Evidence"] = score_evidence

    return enriched


@st.cache_data(ttl=300, show_spinner=False)
def suggest_alternatives_v2(original_part_number: str) -> list:
    """
    Suggest candidate alternatives using supplier-derived metadata.

    Strategy:
    - Discover explicit distributor substitutes and catalog candidates
    - Classify each candidate conservatively from supplier evidence
    - Score and rank with verified direct substitutes first
    """
    global _LAST_ALTERNATIVE_DISCOVERY

    identity = resolve_engineering_part_identity(original_part_number)
    canonical_part_number = str(
        identity.get("manufacturer_part_number") or original_part_number
    ).strip()

    try:
        original_data = _enrich_part_data_from_suppliers(get_best_part_data(original_part_number))
    except Exception:
        original_data = {
            "manufacturer_part_number": canonical_part_number,
            "searched_part_number": original_part_number,
            "supplier_data_verified": False,
        }
    discovery = discover_alternative_candidates(canonical_part_number)
    _LAST_ALTERNATIVE_DISCOVERY = discovery
    supplier_results = list(discovery.get("candidates") or [])

    original_feature_text = " ".join(
        [
            str(original_data.get("manufacturer_part_number", "")),
            str(original_data.get("architecture", "")),
            str(original_data.get("description", "")),
        ]
    )

    original_data["Feature Tags"] = infer_feature_tags(original_feature_text)

    supplier_candidates = []
    for result in supplier_results:
        candidate_part = str(result.get("manufacturer_part_number") or "").strip()
        if not candidate_part:
            continue
        evidence_type = str(result.get("evidence_type") or "Supplier candidate").strip()
        substitute_type = str(result.get("substitute_type") or "Unknown").strip()
        relationship_evidence = result.get("supplier_relationship_evidence")
        if not isinstance(relationship_evidence, list):
            relationship_evidence = []
        classification = classify_from_supplier_evidence(
            result,
            original_mpn=canonical_part_number,
            original_manufacturer=str(original_data.get("manufacturer") or ""),
        )
        is_explicit_substitute = classification == CLASS_VERIFIED_DIRECT
        lifecycle = str(result.get("lifecycle_status") or "Unknown").strip() or "Unknown"
        suitability = classify_recommendation_suitability(
            lifecycle,
            source=str(result.get("source") or "DigiKey"),
        )
        supplier_candidates.append(
            {
                "Alternative Part": candidate_part,
                "Category": classification,
                "Classification": classification,
                "Supplier": str(result.get("source") or "DigiKey"),
                "Manufacturer": str(result.get("manufacturer") or ""),
                "Stock": coerce_stock_total(result.get("stock_total", 0)),
                "Unit Price": result.get("unit_price", 0.0),
                "Lifecycle": lifecycle,
                "Estimated Risk": "Unknown",
                "Evidence Type": evidence_type,
                "Substitute Type": substitute_type,
                "Evidence Source": str(result.get("source") or "DigiKey"),
                "Supplier Relationship Evidence": [
                    dict(row) for row in relationship_evidence if isinstance(row, dict)
                ],
                "Supplier Part ID": str(
                    result.get("supplier_part_id")
                    or result.get("digikey_part_number")
                    or ""
                ),
                "Source URL": str(
                    result.get("source_url") or result.get("product_detail_url") or ""
                ),
                "Original MPN": str(result.get("original_mpn") or canonical_part_number),
                "Retrieval Status": str(result.get("retrieval_status") or "ok"),
                "Retrieved At": str(result.get("retrieved_at") or discovery.get("retrieved_at") or ""),
                "Product URL": str(result.get("product_detail_url") or ""),
                "Datasheet URL": str(result.get("datasheet_url") or ""),
                "Recommendation Suitability": suitability,
                "Recommendation": build_classification_recommendation(
                    classification,
                    substitute_type=substitute_type,
                    suitability=suitability,
                    lifecycle=lifecycle,
                    source=str(result.get("source") or "DigiKey"),
                ),
                "Recommendation Score": (
                    78 if substitute_type.casefold() == "direct" else 62
                ) if is_explicit_substitute else (
                    58 if substitute_type.casefold() == "upgrade" else 45
                ),
                "Compatibility Notes": (
                    "Supplier-listed candidate only. Verify electrical characteristics, footprint, "
                    "dimensions/height, temperature range, qualification, and datasheet compatibility before approval."
                ),
                "_discovery_row": dict(result),
            }
        )

    candidates = supplier_candidates

    normalized_candidates = []

    for candidate_index, candidate in enumerate(candidates):
        if isinstance(candidate, str):
            candidate = {
                "Alternative Part": candidate,
                "Category": "Suggested Alternative",
                "Lifecycle": "Unknown",
                "Estimated Risk": "Medium",
                "Recommendation": "Review compatibility",
                "Recommendation Score": 70,
            }

        description_for_channel = " ".join(
            [
                str(candidate.get("Category", "")),
                str(candidate.get("Architecture", "")),
                str(candidate.get("Recommendation", "")),
                str(candidate.get("Compatibility Notes", "")),
            ]
        )

        candidate["Channel Count"] = candidate.get(
            "Channel Count", 0
        ) or infer_channel_count_from_description(description_for_channel)

        discovery_row = candidate.pop("_discovery_row", None)
        if not isinstance(discovery_row, dict):
            discovery_row = {}
        candidate_supplier_data = _discovery_row_to_part_data(discovery_row)

        base_candidate = dict(candidate)
        try:
            candidate = apply_supplier_enrichment_to_candidate(
                original_data=original_data,
                candidate=candidate,
                candidate_supplier_data=candidate_supplier_data,
                canonical_part_number=canonical_part_number,
            )
        except Exception:
            candidate = base_candidate

        normalized_candidates.append(candidate)

    candidates = normalized_candidates

    filtered_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("Alternative Part", "").strip().lower()
        != canonical_part_number.strip().lower()
        and candidate.get("Alternative Part", "").strip().lower()
        != original_part_number.strip().lower()
    ]

    sorted_candidates = sorted(
        filtered_candidates,
        key=classification_sort_key,
    )

    finalized = apply_classification_result_cap(sorted_candidates)
    return prepare_candidates_for_session_and_cache(finalized)

def rank_alternatives(alternative_part_numbers: list) -> pd.DataFrame:
    """
    Ranks alternative parts using supplier data and risk score.

    Lower risk score is better.
    Higher total market stock is better.
    Higher supplier count is better.
    """

    ranked_results = []

    for part_number in alternative_part_numbers:
        part_data = get_best_part_data(part_number)
        part_data["quantity"] = 1

        risk_result = calculate_risk(part_data)

        ranked_results.append(
            {
                "MPN": part_number,
                "Matched MPN": part_data.get("manufacturer_part_number", ""),
                "Manufacturer": part_data.get("manufacturer", ""),
                "Best Source": part_data.get("source", ""),
                "Supplier Count": part_data.get("supplier_count", 0),
                "Total Market Stock": part_data.get("total_market_stock", 0),
                "Lifecycle Status": part_data.get("lifecycle_status", "Unknown"),
                "Risk Score": risk_result["risk_score"],
                "Risk Level": risk_result["risk_level"],
            }
        )

    ranked_df = pd.DataFrame(ranked_results)

    if ranked_df.empty:
        return ranked_df

    ranked_df = ranked_df.sort_values(
        by=["Risk Score", "Total Market Stock", "Supplier Count"],
        ascending=[True, False, False],
    )

    ranked_df["Rank"] = range(1, len(ranked_df) + 1)

    return ranked_df
