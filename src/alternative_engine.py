import pandas as pd

from integrations.supplier_aggregator import get_best_part_data
from src.risk_engine import calculate_risk
from integrations.supplier_aggregator import search_supplier_alternatives
from src.datasheet_comparison import (
    apply_comparison_evidence_to_scores,
    build_datasheet_comparison,
)
import streamlit as st

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
    stock = int(candidate.get("Stock", 0))
    supplier = str(candidate.get("Supplier", "")).strip()
    unit_price = float(candidate.get("Unit Price", 0.0))

    architecture = str(candidate.get("Architecture", "")).lower()
    package = str(candidate.get("Package", "")).lower()
    pin_count = int(candidate.get("Pin Count", 0) or 0)
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


def calculate_drop_in_confidence(original: dict, candidate: dict) -> int:
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

    original_pin_count = int(
        original.get("Pin Count", original.get("pin_count", 0)) or 0
    )

    candidate_pin_count = int(
        candidate.get("Pin Count", candidate.get("pin_count", 0)) or 0
    )

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
    reasons = []


    original_architecture = str(original.get("Architecture", original.get("architecture", ""))).lower()
    candidate_architecture = str(candidate.get("Architecture", candidate.get("architecture", ""))).lower()

    original_function = str(original.get("Function", original.get("function", ""))).strip()
    candidate_function = str(candidate.get("Function", candidate.get("function", ""))).strip()

    original_package = str(original.get("Package", original.get("package", ""))).strip()
    candidate_package = str(candidate.get("Package", candidate.get("package", ""))).strip()

    original_pin_count = int(original.get("Pin Count", original.get("pin_count", 0)) or 0)
    candidate_pin_count = int(candidate.get("Pin Count", candidate.get("pin_count", 0)) or 0)

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


@st.cache_data(ttl=1800, show_spinner=False)
def suggest_alternatives_v2(original_part_number: str) -> list:
    """
    Suggest candidate alternatives using supplier-derived metadata.

    Strategy:
    - Use supplier description
    - Identify part family
    - Return candidate parts from that family
    """

    original_data = get_best_part_data(original_part_number)

    original_feature_text = " ".join(
        [
            str(original_data.get("manufacturer_part_number", "")),
            str(original_data.get("architecture", "")),
            str(original_data.get("description", "")),
        ]
    )

    original_data["Feature Tags"] = infer_feature_tags(original_feature_text)


    description = original_data.get("description", "").lower()

    candidates = []

    supplier_results = search_supplier_alternatives(original_part_number)
    supplier_candidates = []
    for result in supplier_results:
        candidate_part = str(result.get("manufacturer_part_number") or "").strip()
        if not candidate_part:
            continue
        evidence_type = str(result.get("evidence_type") or "Supplier candidate").strip()
        substitute_type = str(result.get("substitute_type") or "Candidate").strip()
        is_explicit_substitute = evidence_type.casefold() == "distributor-listed substitute"
        supplier_candidates.append(
            {
                "Alternative Part": candidate_part,
                "Category": (
                    "Distributor-listed substitute"
                    if is_explicit_substitute
                    else "Distributor catalog candidate"
                ),
                "Supplier": str(result.get("source") or "DigiKey"),
                "Manufacturer": str(result.get("manufacturer") or ""),
                "Stock": result.get("stock_total", 0),
                "Unit Price": result.get("unit_price", 0.0),
                "Lifecycle": "Unknown",
                "Estimated Risk": "Unknown",
                "Evidence Type": evidence_type,
                "Substitute Type": substitute_type,
                "Product URL": str(result.get("product_detail_url") or ""),
                "Recommendation": (
                    f"DigiKey lists this as a {substitute_type.lower()} substitute; engineering review required"
                    if is_explicit_substitute
                    else "DigiKey catalog match; verify functional, electrical, footprint, and qualification compatibility before approval"
                ),
                "Recommendation Score": (
                    78 if substitute_type.casefold() == "direct" else 62
                ) if is_explicit_substitute else 45,
                "Compatibility Notes": (
                    "Supplier-listed candidate only. Verify electrical characteristics, footprint, "
                    "dimensions/height, temperature range, qualification, and datasheet compatibility before approval."
                ),
            }
        )

    # Timer family detection
    if "timer" in description or "555" in original_part_number.upper():
        candidates = [
            "NE555P",
            "TLC555CP",
            "LMC555CN/NOPB",
            "NA555DR",
            "ICM7555IPA"
        ]

    # Voltage regulator family detection
    elif (
        "voltage regulator" in description
        or "linear regulator" in description
        or "7805" in original_part_number.lower()
        or "lm1117" in original_part_number.lower()
        or "ams1117" in original_part_number.lower()
        or "lm317" in original_part_number.lower()
    ):
        candidates = [
            {
                "Alternative Part": "MC7805CTG",
                "Category": "5V Linear Regulator",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Closest 7805-style replacement",
                "Recommendation Score": 88,
                "Architecture": "Linear Regulator",
                "Package": "TO-220",
                "Pin Count": 3,
                "Voltage Range": "5V fixed output",
                "Compatibility Notes": "Review pinout, current rating, thermal dissipation, and package fit before substitution.",
            },
            {
                "Alternative Part": "L7805CV",
                "Category": "5V Linear Regulator",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common 7805 alternative",
                "Recommendation Score": 86,
                "Architecture": "Linear Regulator",
                "Package": "TO-220",
                "Pin Count": 3,
                "Voltage Range": "5V fixed output",
                "Compatibility Notes": "Common 7805-family option; verify manufacturer pinout and thermal requirements.",
            },
            {
                "Alternative Part": "LM1117T-5.0",
                "Category": "5V LDO Regulator",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Lower-dropout alternative",
                "Recommendation Score": 78,
                "Architecture": "LDO Regulator",
                "Package": "TO-220",
                "Pin Count": 3,
                "Voltage Range": "5V fixed output",
                "Compatibility Notes": "May not be pin-compatible with 7805 parts. Review dropout voltage, capacitor requirements, and pinout.",
            },
            {
                "Alternative Part": "AMS1117-5.0",
                "Category": "5V LDO Regulator",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Board-level LDO alternative",
                "Recommendation Score": 74,
                "Architecture": "LDO Regulator",
                "Package": "SOT-223",
                "Pin Count": 3,
                "Voltage Range": "5V fixed output",
                "Compatibility Notes": "Useful for redesigns, but package and pinout differ from TO-220 regulators.",
            },
            {
                "Alternative Part": "LM317T",
                "Category": "Adjustable Linear Regulator",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Adjustable regulator option",
                "Recommendation Score": 70,
                "Architecture": "Adjustable Linear Regulator",
                "Package": "TO-220",
                "Pin Count": 3,
                "Voltage Range": "Adjustable output",
                "Compatibility Notes": "Not a direct fixed-output drop-in. Requires resistor network and design review.",
            },
        ]

    # Op-amp / comparator family detection
    elif (
        "operational amplifier" in description
        or "op amp" in description
        or "op-amp" in description
        or "amplifier" in description
        or "comparator" in description
        or "lm358" in original_part_number.lower()
        or "lm324" in original_part_number.lower()
        or "tl072" in original_part_number.lower()
        or "lm393" in original_part_number.lower()
        or "lm339" in original_part_number.lower()
    ):
        candidates = [
            {
                "Alternative Part": "LM358N",
                "Category": "Dual Op-Amp",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common dual op-amp alternative",
                "Recommendation Score": 86,
                "Architecture": "Operational Amplifier",
                "Package": "DIP-8",
                "Pin Count": 8,
                "Voltage Range": "3V to 32V",
                "Supply Voltage Min": 3.0,
                "Supply Voltage Max": 32.0,
                "Compatibility Notes": "Review supply voltage range, input common-mode range, output swing, bandwidth, and pinout.",
            },
            {
                "Alternative Part": "LM358P",
                "Category": "Dual Op-Amp",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common LM358-family option",
                "Recommendation Score": 84,
                "Architecture": "Operational Amplifier",
                "Package": "PDIP-8",
                "Pin Count": 8,
                "Voltage Range": "3V to 32V",
                "Supply Voltage Min": 3.0,
                "Supply Voltage Max": 32.0,
                "Compatibility Notes": "Similar LM358-family part; verify package, manufacturer pinout, and electrical specs.",
            },
            {
                "Alternative Part": "LM324N",
                "Category": "Quad Op-Amp",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Quad op-amp alternative",
                "Recommendation Score": 76,
                "Architecture": "Operational Amplifier",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "Single/Dual supply",
                "Compatibility Notes": "Not pin-compatible with dual op-amps. Useful when redesigning around a quad amplifier.",
            },
            {
                "Alternative Part": "TL072CP",
                "Category": "Dual JFET Op-Amp",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Higher-input-impedance option",
                "Recommendation Score": 74,
                "Architecture": "JFET Operational Amplifier",
                "Package": "DIP-8",
                "Pin Count": 8,
                "Voltage Range": "Dual supply typical",
                "Compatibility Notes": "JFET input device; verify supply rails, input range, offset, noise, and bandwidth before substitution.",
            },
            {
                "Alternative Part": "LM393N",
                "Category": "Dual Comparator",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Comparator-family option",
                "Recommendation Score": 72,
                "Architecture": "Comparator",
                "Package": "DIP-8",
                "Pin Count": 8,
                "Voltage Range": "Single/Dual supply",
                "Compatibility Notes": "Comparator, not an op-amp. Only use when the original function is comparator-based.",
            },
            {
                "Alternative Part": "LM339N",
                "Category": "Quad Comparator",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Quad comparator option",
                "Recommendation Score": 70,
                "Architecture": "Comparator",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "Single/Dual supply",
                "Compatibility Notes": "Quad comparator; not pin-compatible with dual comparators or op-amps. Requires design review.",
            },
        ]

    # Logic IC family detection — stricter functional matching
    elif (
        "74hc04" in original_part_number.lower()
        or "74hct04" in original_part_number.lower()
        or "74ls04" in original_part_number.lower()
        or "hex inverter" in description
    ):
        candidates = [
            {
                "Alternative Part": "SN74HC04N",
                "Category": "Hex Inverter",
                "Function": "Hex Inverter",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Same-function hex inverter candidate",
                "Recommendation Score": 88,
                "Architecture": "Hex Inverter Logic",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Same logic function. Verify package, pinout, voltage family, propagation delay, and drive current.",
            },
            {
                "Alternative Part": "CD74HC04E",
                "Category": "Hex Inverter",
                "Function": "Hex Inverter",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Same-function 74HC04-family inverter",
                "Recommendation Score": 86,
                "Architecture": "Hex Inverter Logic",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Same logic function. Verify package, pinout, voltage family, timing, and manufacturer specs.",
            },
            {
                "Alternative Part": "M74HC04B1R",
                "Category": "Hex Inverter",
                "Function": "Hex Inverter",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Same-function hex inverter option",
                "Recommendation Score": 84,
                "Architecture": "Hex Inverter Logic",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Same inverter function. Verify pinout, package, supply voltage, timing, and output drive.",
            },
        ]

    elif (
        "74hc595" in original_part_number.lower()
        or "74hct595" in original_part_number.lower()
        or "shift register" in description
    ):
        candidates = [
            {
                "Alternative Part": "SN74HC595N",
                "Category": "8-Bit Shift Register",
                "Function": "Shift Register",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Same-function serial-to-parallel shift register",
                "Recommendation Score": 88,
                "Architecture": "Shift Register Logic",
                "Package": "DIP-16",
                "Pin Count": 16,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Same shift-register function. Verify pinout, timing, latch behavior, voltage family, and output drive.",
            },
            {
                "Alternative Part": "CD74HC595E",
                "Category": "8-Bit Shift Register",
                "Function": "Shift Register",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Same-function 74HC595-family shift register",
                "Recommendation Score": 86,
                "Architecture": "Shift Register Logic",
                "Package": "DIP-16",
                "Pin Count": 16,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Same function. Verify timing, pinout, package, latch behavior, and output drive.",
            },
        ]
    
    # MOSFET / transistor family detection
    elif (
        "mosfet" in description
        or "field effect transistor" in description
        or "fet" in description
        or "irlz44" in original_part_number.replace("-", "").lower()
        or "irf540" in original_part_number.replace("-", "").lower()
        or "irfz44" in original_part_number.replace("-", "").lower()
        or "ao3400" in original_part_number.replace("-", "").lower()
        or "2n7000" in original_part_number.replace("-", "").lower()
        or "bs170" in original_part_number.replace("-", "").lower()
    ):
        candidates = [
            {
                "Alternative Part": "IRLZ44N",
                "Category": "Logic-Level N-Channel MOSFET",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common logic-level power MOSFET",
                "Recommendation Score": 86,
                "Architecture": "N-Channel MOSFET",
                "Package": "TO-220",
                "Pin Count": 3,
                "Voltage Range": "55V class",
                "Compatibility Notes": "Verify Vds, Id, Rds(on), gate threshold, gate drive voltage, package, and thermal limits.",
            },
            {
                "Alternative Part": "IRF540N",
                "Category": "N-Channel Power MOSFET",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Common power MOSFET option",
                "Recommendation Score": 78,
                "Architecture": "N-Channel MOSFET",
                "Package": "TO-220",
                "Pin Count": 3,
                "Voltage Range": "100V class",
                "Compatibility Notes": "Not always logic-level. Verify gate drive voltage and Rds(on) at your actual gate voltage.",
            },
            {
                "Alternative Part": "IRFZ44N",
                "Category": "N-Channel Power MOSFET",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Power MOSFET alternative",
                "Recommendation Score": 76,
                "Architecture": "N-Channel MOSFET",
                "Package": "TO-220",
                "Pin Count": 3,
                "Voltage Range": "55V class",
                "Compatibility Notes": "Verify gate drive voltage, current rating, Rds(on), and thermal dissipation.",
            },
            {
                "Alternative Part": "AO3400A",
                "Category": "Small-Signal N-Channel MOSFET",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Compact SMD MOSFET option",
                "Recommendation Score": 74,
                "Architecture": "N-Channel MOSFET",
                "Package": "SOT-23",
                "Pin Count": 3,
                "Voltage Range": "30V class",
                "Compatibility Notes": "Not a TO-220 replacement. Useful for board redesigns or small-load switching.",
            },
            {
                "Alternative Part": "2N7000",
                "Category": "Small-Signal N-Channel MOSFET",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Low-current switching option",
                "Recommendation Score": 72,
                "Architecture": "N-Channel MOSFET",
                "Package": "TO-92",
                "Pin Count": 3,
                "Voltage Range": "60V class",
                "Compatibility Notes": "Low-current MOSFET. Not suitable for high-current power switching.",
            },
            {
                "Alternative Part": "BS170",
                "Category": "Small-Signal N-Channel MOSFET",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Small-signal MOSFET option",
                "Recommendation Score": 70,
                "Architecture": "N-Channel MOSFET",
                "Package": "TO-92",
                "Pin Count": 3,
                "Voltage Range": "60V class",
                "Compatibility Notes": "Verify current rating, package pinout, gate threshold, and switching requirements.",
            },
        ]

    # Resistor family detection
    elif (
        "resistor" in description
        or "chip resistor" in description
        or "thick film resistor" in description
        or "thin film resistor" in description
        or original_part_number.upper().startswith("RC")
        or original_part_number.upper().startswith("CR")
        or original_part_number.upper().startswith("ERJ")
        or original_part_number.upper().startswith("RK")
    ):
        candidates = [
            {
                "Alternative Part": "RC0603FR-0710KL",
                "Category": "Chip Resistor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Spec-matched candidate",
                "Recommendation Score": 88,
                "Architecture": "Thick Film Resistor",
                "Package": "0603",
                "Pin Count": 2,
                "Voltage Range": "Verify resistance and power rating",
                "Compatibility Notes": "Verify resistance value, tolerance, power rating, temperature coefficient, and package size before substitution.",
            },
            {
                "Alternative Part": "CRCW060310K0FKEA",
                "Category": "Chip Resistor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common Vishay alternative",
                "Recommendation Score": 86,
                "Architecture": "Thick Film Resistor",
                "Package": "0603",
                "Pin Count": 2,
                "Voltage Range": "Verify resistance and power rating",
                "Compatibility Notes": "Check resistance value, package size, tolerance, and power rating.",
            },
            {
                "Alternative Part": "ERJ-3EKF1002V",
                "Category": "Chip Resistor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Panasonic resistor family",
                "Recommendation Score": 84,
                "Architecture": "Thick Film Resistor",
                "Package": "0603",
                "Pin Count": 2,
                "Voltage Range": "Verify resistance and power rating",
                "Compatibility Notes": "Confirm package, value, tolerance, and power dissipation.",
            },
        ]

    # Capacitor family detection
    elif (
        "capacitor" in description
        or "ceramic capacitor" in description
        or "mlcc" in description
        or "tantalum capacitor" in description
        or "aluminum electrolytic" in description
        or original_part_number.upper().startswith("CL")
        or original_part_number.upper().startswith("GRM")
        or original_part_number.upper().startswith("CGA")
        or original_part_number.upper().startswith("CC")
    ):
        candidates = [
            {
                "Alternative Part": "GRM188R71H104KA93D",
                "Category": "Ceramic Capacitor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Spec-matched MLCC candidate",
                "Recommendation Score": 86,
                "Architecture": "MLCC Ceramic Capacitor",
                "Package": "0603",
                "Pin Count": 2,
                "Voltage Range": "Verify capacitance and voltage rating",
                "Compatibility Notes": "Verify capacitance, voltage rating, dielectric type, tolerance, temperature rating, and package size before substitution.",
            },
            {
                "Alternative Part": "CL10B104KB8NNNC",
                "Category": "Ceramic Capacitor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common Samsung MLCC option",
                "Recommendation Score": 84,
                "Architecture": "MLCC Ceramic Capacitor",
                "Package": "0603",
                "Pin Count": 2,
                "Voltage Range": "Verify capacitance and voltage rating",
                "Compatibility Notes": "Confirm capacitance, voltage rating, dielectric, tolerance, and DC-bias behavior.",
            },
            {
                "Alternative Part": "C0603C104K5RACTU",
                "Category": "Ceramic Capacitor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common KEMET MLCC option",
                "Recommendation Score": 82,
                "Architecture": "MLCC Ceramic Capacitor",
                "Package": "0603",
                "Pin Count": 2,
                "Voltage Range": "Verify capacitance and voltage rating",
                "Compatibility Notes": "Check package, capacitance, dielectric, voltage rating, tolerance, and temperature characteristics.",
            },
        ]

    # Inductor family detection
    elif (
        "inductor" in description
        or "power inductor" in description
        or "chip inductor" in description
        or "wirewound inductor" in description
        or "shielded inductor" in description
        or original_part_number.upper().startswith("LQH")
        or original_part_number.upper().startswith("SRN")
        or original_part_number.upper().startswith("IHLP")
        or original_part_number.upper().startswith("744")
    ):
        candidates = [
            {
                "Alternative Part": "LQH32CN100K53L",
                "Category": "Chip Inductor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Spec-matched inductor candidate",
                "Recommendation Score": 84,
                "Architecture": "Wirewound Inductor",
                "Package": "1210 / 3225",
                "Pin Count": 2,
                "Voltage Range": "Verify inductance and current rating",
                "Compatibility Notes": "Verify inductance, tolerance, saturation current, rated current, DCR, shielding, and package size before substitution.",
            },
            {
                "Alternative Part": "SRN4018-100M",
                "Category": "Shielded Power Inductor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common shielded power inductor option",
                "Recommendation Score": 82,
                "Architecture": "Shielded Power Inductor",
                "Package": "4.0mm x 4.0mm",
                "Pin Count": 2,
                "Voltage Range": "Verify inductance and current rating",
                "Compatibility Notes": "Check saturation current, RMS current, DCR, height, footprint, and switching regulator requirements.",
            },
            {
                "Alternative Part": "IHLP2525CZER100M01",
                "Category": "Power Inductor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "High-current power inductor candidate",
                "Recommendation Score": 80,
                "Architecture": "Shielded Power Inductor",
                "Package": "2525",
                "Pin Count": 2,
                "Voltage Range": "Verify inductance and current rating",
                "Compatibility Notes": "Useful for DC-DC converters. Verify inductance, saturation current, RMS current, DCR, footprint, and thermal limits.",
            },
            {
                "Alternative Part": "74438335100",
                "Category": "Power Inductor",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Wurth power inductor candidate",
                "Recommendation Score": 78,
                "Architecture": "Shielded Power Inductor",
                "Package": "Verify package",
                "Pin Count": 2,
                "Voltage Range": "Verify inductance and current rating",
                "Compatibility Notes": "Verify footprint, inductance, rated current, saturation current, DCR, shielding, and height before substitution.",
            },
        ]

    # Diode family detection
    elif (
        "diode" in description
        or "rectifier" in description
        or "schottky" in description
        or "zener" in description
        or "tvs" in description
        or original_part_number.upper().startswith("1N")
        or original_part_number.upper().startswith("SS")
        or original_part_number.upper().startswith("BAV")
        or original_part_number.upper().startswith("BAT")
    ):
        candidates = [
            {
                "Alternative Part": "1N4148",
                "Category": "Signal Diode",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common small-signal diode candidate",
                "Recommendation Score": 84,
                "Architecture": "Signal Diode",
                "Package": "DO-35 / SMD variants available",
                "Pin Count": 2,
                "Voltage Range": "Verify reverse voltage and current",
                "Compatibility Notes": "Verify package, reverse voltage, forward current, forward voltage, switching speed, and power dissipation.",
            },
            {
                "Alternative Part": "1N4007",
                "Category": "Rectifier Diode",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common rectifier diode option",
                "Recommendation Score": 82,
                "Architecture": "Rectifier Diode",
                "Package": "DO-41",
                "Pin Count": 2,
                "Voltage Range": "1000V class",
                "Compatibility Notes": "Use for rectifier applications. Verify current rating, voltage rating, package, and recovery speed.",
            },
            {
                "Alternative Part": "SS14",
                "Category": "Schottky Diode",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common Schottky diode option",
                "Recommendation Score": 80,
                "Architecture": "Schottky Diode",
                "Package": "SMA",
                "Pin Count": 2,
                "Voltage Range": "40V class",
                "Compatibility Notes": "Verify reverse voltage, average current, forward voltage drop, leakage current, and package.",
            },
            {
                "Alternative Part": "BAV99",
                "Category": "Dual Switching Diode",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Dual small-signal diode candidate",
                "Recommendation Score": 76,
                "Architecture": "Switching Diode Array",
                "Package": "SOT-23",
                "Pin Count": 3,
                "Voltage Range": "Verify reverse voltage and current",
                "Compatibility Notes": "Dual diode configuration. Verify pinout, diode arrangement, package, and switching requirements.",
            },
            {
                "Alternative Part": "BAT54",
                "Category": "Schottky Signal Diode",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Small-signal Schottky option",
                "Recommendation Score": 74,
                "Architecture": "Schottky Diode",
                "Package": "SOT-23",
                "Pin Count": 3,
                "Voltage Range": "Verify reverse voltage and current",
                "Compatibility Notes": "Verify package, pinout, forward voltage, leakage current, and current rating.",
            },
        ]

    # BJT transistor family detection
    elif (
        "bjt" in description
        or "bipolar transistor" in description
        or "npn transistor" in description
        or "pnp transistor" in description
        or "small signal transistor" in description
        or original_part_number.upper().startswith("2N2222")
        or original_part_number.upper().startswith("2N3904")
        or original_part_number.upper().startswith("2N3906")
        or original_part_number.upper().startswith("BC547")
        or original_part_number.upper().startswith("BC557")
        or original_part_number.upper().startswith("MMBT")
    ):
        candidates = [
            {
                "Alternative Part": "2N3904",
                "Category": "NPN Small-Signal Transistor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common NPN transistor candidate",
                "Recommendation Score": 84,
                "Architecture": "NPN BJT",
                "Package": "TO-92 / SMD variants available",
                "Pin Count": 3,
                "Voltage Range": "Verify Vceo and current rating",
                "Compatibility Notes": "Verify polarity, pinout, Vceo, collector current, gain range, power rating, package, and frequency response.",
            },
            {
                "Alternative Part": "2N2222A",
                "Category": "NPN Switching Transistor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common NPN switching transistor",
                "Recommendation Score": 82,
                "Architecture": "NPN BJT",
                "Package": "TO-92 / metal can / SMD variants",
                "Pin Count": 3,
                "Voltage Range": "Verify Vceo and current rating",
                "Compatibility Notes": "Verify pinout, collector current, gain, saturation voltage, package, and power dissipation.",
            },
            {
                "Alternative Part": "MMBT3904",
                "Category": "NPN Small-Signal Transistor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "SMD NPN transistor candidate",
                "Recommendation Score": 80,
                "Architecture": "NPN BJT",
                "Package": "SOT-23",
                "Pin Count": 3,
                "Voltage Range": "Verify Vceo and current rating",
                "Compatibility Notes": "SMD alternative; verify footprint, pinout, gain, voltage, current, and thermal limits.",
            },
            {
                "Alternative Part": "2N3906",
                "Category": "PNP Small-Signal Transistor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common PNP transistor candidate",
                "Recommendation Score": 78,
                "Architecture": "PNP BJT",
                "Package": "TO-92 / SMD variants available",
                "Pin Count": 3,
                "Voltage Range": "Verify Vceo and current rating",
                "Compatibility Notes": "Only use for PNP applications. Verify polarity, pinout, gain, current rating, voltage rating, and package.",
            },
            {
                "Alternative Part": "MMBT3906",
                "Category": "PNP Small-Signal Transistor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "SMD PNP transistor candidate",
                "Recommendation Score": 76,
                "Architecture": "PNP BJT",
                "Package": "SOT-23",
                "Pin Count": 3,
                "Voltage Range": "Verify Vceo and current rating",
                "Compatibility Notes": "SMD PNP option; verify footprint, pinout, gain, voltage, current, and power dissipation.",
            },
        ]

    # Crystal / oscillator family detection
    elif (
        "crystal" in description
        or "oscillator" in description
        or "resonator" in description
        or original_part_number.upper().startswith("ABM")
        or original_part_number.upper().startswith("ECS")
        or original_part_number.upper().startswith("NX")
        or original_part_number.upper().startswith("CX")
    ):
        candidates = [
            {
                "Alternative Part": "ABM8-16.000MHZ-B2-T",
                "Category": "Crystal",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common 16 MHz crystal candidate",
                "Recommendation Score": 84,
                "Architecture": "Quartz Crystal",
                "Package": "3225",
                "Pin Count": 4,
                "Voltage Range": "Verify frequency and load capacitance",
                "Compatibility Notes": "Verify frequency, load capacitance, ESR, tolerance, package, and stability requirements.",
            },
            {
                "Alternative Part": "ECS-160-20-5PXDU",
                "Category": "Crystal",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common microcontroller crystal",
                "Recommendation Score": 82,
                "Architecture": "Quartz Crystal",
                "Package": "HC49",
                "Pin Count": 2,
                "Voltage Range": "Verify frequency and load capacitance",
                "Compatibility Notes": "Verify frequency, ESR, package, tolerance, and startup requirements.",
            },
            {
                "Alternative Part": "NX3225SA-16MHZ",
                "Category": "Crystal",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Compact SMD crystal option",
                "Recommendation Score": 80,
                "Architecture": "Quartz Crystal",
                "Package": "3225",
                "Pin Count": 4,
                "Voltage Range": "Verify frequency and load capacitance",
                "Compatibility Notes": "Check footprint, frequency, ESR, load capacitance, and stability specifications.",
            },
        ]

        # Optocoupler / optoisolator family detection
    elif (
        "optocoupler" in description
        or "optoisolator" in description
        or "optical isolator" in description
        or "phototransistor" in description
        or original_part_number.upper().startswith("PC817")
        or original_part_number.upper().startswith("LTV")
        or original_part_number.upper().startswith("4N")
        or original_part_number.upper().startswith("TLP")
    ):
        candidates = [
            {
                "Alternative Part": "PC817",
                "Category": "Phototransistor Optocoupler",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common general-purpose optocoupler",
                "Recommendation Score": 84,
                "Architecture": "Phototransistor Optocoupler",
                "Package": "DIP-4 / SMD variants",
                "Pin Count": 4,
                "Voltage Range": "Verify isolation and CTR",
                "Compatibility Notes": "Verify CTR, isolation voltage, package, pinout, input current, output transistor rating, and creepage/clearance.",
            },
            {
                "Alternative Part": "LTV-817",
                "Category": "Phototransistor Optocoupler",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common PC817-style alternative",
                "Recommendation Score": 82,
                "Architecture": "Phototransistor Optocoupler",
                "Package": "DIP-4 / SMD variants",
                "Pin Count": 4,
                "Voltage Range": "Verify isolation and CTR",
                "Compatibility Notes": "Review CTR rank, isolation voltage, input current, package, and safety approvals.",
            },
            {
                "Alternative Part": "4N35",
                "Category": "Phototransistor Optocoupler",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Legacy general-purpose optocoupler",
                "Recommendation Score": 78,
                "Architecture": "Phototransistor Optocoupler",
                "Package": "DIP-6",
                "Pin Count": 6,
                "Voltage Range": "Verify isolation and CTR",
                "Compatibility Notes": "Not always pin-compatible with 4-pin optocouplers. Verify package, CTR, isolation, and speed.",
            },
            {
                "Alternative Part": "TLP291",
                "Category": "Transistor Output Optocoupler",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Compact transistor-output optocoupler",
                "Recommendation Score": 76,
                "Architecture": "Phototransistor Optocoupler",
                "Package": "SO-4",
                "Pin Count": 4,
                "Voltage Range": "Verify isolation and CTR",
                "Compatibility Notes": "Verify CTR, isolation voltage, creepage, package footprint, and safety agency requirements.",
            },
        ]

    # Connector family detection
    elif (
        "connector" in description
        or "header" in description
        or "terminal block" in description
        or "receptacle" in description
        or "plug" in description
        or original_part_number.upper().startswith("JST")
        or original_part_number.upper().startswith("B")
        or original_part_number.upper().startswith("MOLEX")
        or original_part_number.upper().startswith("TE")
        or original_part_number.upper().startswith("PHOENIX")
        or original_part_number.upper().startswith("SAMTEC")
    ):
        candidates = [
            {
                "Alternative Part": "B2B-PH-K-S",
                "Category": "Wire-to-Board Connector",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common JST PH series connector",
                "Recommendation Score": 86,
                "Architecture": "Wire-to-Board Connector",
                "Package": "Through-Hole",
                "Pin Count": 2,
                "Voltage Range": "Verify current and voltage rating",
                "Compatibility Notes": "Verify pitch, mating connector, pin count, current rating, mounting style, and locking features.",
            },
            {
                "Alternative Part": "22-23-2021",
                "Category": "Board Header",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common Molex header",
                "Recommendation Score": 84,
                "Architecture": "Board Connector",
                "Package": "Through-Hole",
                "Pin Count": 2,
                "Voltage Range": "Verify current and voltage rating",
                "Compatibility Notes": "Verify pitch, mating compatibility, mounting style, and current rating.",
            },
            {
                "Alternative Part": "1757242",
                "Category": "Terminal Block",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Phoenix Contact terminal block",
                "Recommendation Score": 80,
                "Architecture": "Terminal Block",
                "Package": "PCB Mount",
                "Pin Count": 2,
                "Voltage Range": "Verify voltage and current rating",
                "Compatibility Notes": "Verify pitch, wire size, current rating, mounting style, and footprint.",
            },
        ]

    # Relay family detection
    elif (
        "relay" in description
        or "power relay" in description
        or "signal relay" in description
        or "electromechanical relay" in description
        or original_part_number.upper().startswith("SRD")
        or original_part_number.upper().startswith("G5LE")
        or original_part_number.upper().startswith("G2R")
        or original_part_number.upper().startswith("T9A")
    ):
        candidates = [
            {
                "Alternative Part": "SRD-05VDC-SL-C",
                "Category": "General Purpose Relay",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common PCB relay option",
                "Recommendation Score": 86,
                "Architecture": "Electromechanical Relay",
                "Package": "PCB Through-Hole",
                "Pin Count": 5,
                "Voltage Range": "5V Coil",
                "Compatibility Notes": "Verify coil voltage, contact arrangement, contact current, footprint, and isolation requirements.",
            },
            {
                "Alternative Part": "G5LE-1-DC5",
                "Category": "Power Relay",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Industrial power relay option",
                "Recommendation Score": 84,
                "Architecture": "Electromechanical Relay",
                "Package": "PCB Through-Hole",
                "Pin Count": 5,
                "Voltage Range": "5V Coil",
                "Compatibility Notes": "Verify coil voltage, contact rating, footprint, switching current, and mounting requirements.",
            },
            {
                "Alternative Part": "G2R-1A-DC24",
                "Category": "Industrial Relay",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Industrial control relay",
                "Recommendation Score": 82,
                "Architecture": "Electromechanical Relay",
                "Package": "Socket / PCB",
                "Pin Count": 5,
                "Voltage Range": "24V Coil",
                "Compatibility Notes": "Verify coil voltage, contact form, current rating, socket compatibility, and footprint.",
            },
            {
                "Alternative Part": "T9AS1D12-5",
                "Category": "High Current Relay",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "High-current switching relay",
                "Recommendation Score": 80,
                "Architecture": "Electromechanical Relay",
                "Package": "PCB Through-Hole",
                "Pin Count": 5,
                "Voltage Range": "5V Coil",
                "Compatibility Notes": "Verify contact current, coil power, isolation requirements, footprint, and operating environment.",
            },
        ]

    # Switch family detection
    elif (
        "switch" in description
        or "pushbutton" in description
        or "tactile switch" in description
        or "toggle switch" in description
        or "slide switch" in description
        or "dip switch" in description
        or original_part_number.upper().startswith("TL")
        or original_part_number.upper().startswith("PTS")
        or original_part_number.upper().startswith("SK")
    ):
        candidates = [
            {
                "Alternative Part": "TL1105SPF160Q",
                "Category": "Tactile Switch",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common tactile switch option",
                "Recommendation Score": 86,
                "Architecture": "Momentary Pushbutton",
                "Package": "Through-Hole",
                "Pin Count": 4,
                "Voltage Range": "Verify contact rating",
                "Compatibility Notes": "Verify footprint, actuator height, operating force, contact rating, and mounting style.",
            },
            {
                "Alternative Part": "PTS645SM43SMTR92",
                "Category": "Tactile Switch",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common SMD tactile switch",
                "Recommendation Score": 84,
                "Architecture": "Momentary Pushbutton",
                "Package": "SMD",
                "Pin Count": 4,
                "Voltage Range": "Verify contact rating",
                "Compatibility Notes": "Verify footprint, height, travel, operating force, and actuator style.",
            },
            {
                "Alternative Part": "SK12D07VG4",
                "Category": "Slide Switch",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common slide switch option",
                "Recommendation Score": 82,
                "Architecture": "SPDT Slide Switch",
                "Package": "Through-Hole",
                "Pin Count": 3,
                "Voltage Range": "Verify contact rating",
                "Compatibility Notes": "Verify footprint, contact arrangement, travel, current rating, and mounting style.",
            },
        ]




    # LED family detection
    elif (
        "led" in description
        or "light emitting diode" in description
        or "indicator" in description
        or "rgb led" in description
        or "smd led" in description
        or original_part_number.upper().startswith("LTST")
        or original_part_number.upper().startswith("APT")
        or original_part_number.upper().startswith("WP")
        or original_part_number.upper().startswith("CLM")
    ):
        candidates = [
            {
                "Alternative Part": "LTST-C190KRKT",
                "Category": "SMD Indicator LED",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common red SMD indicator LED",
                "Recommendation Score": 86,
                "Architecture": "LED Indicator",
                "Package": "0603",
                "Pin Count": 2,
                "Voltage Range": "Verify forward voltage and current",
                "Compatibility Notes": "Verify color, wavelength, luminous intensity, forward voltage, current rating, polarity, and package size.",
            },
            {
                "Alternative Part": "APT1608SURCK",
                "Category": "SMD Indicator LED",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common red 0603 LED candidate",
                "Recommendation Score": 84,
                "Architecture": "LED Indicator",
                "Package": "0603",
                "Pin Count": 2,
                "Voltage Range": "Verify forward voltage and current",
                "Compatibility Notes": "Check color, package size, forward voltage, brightness, viewing angle, and polarity.",
            },
            {
                "Alternative Part": "WP710A10ID",
                "Category": "Through-Hole Indicator LED",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common through-hole red LED",
                "Recommendation Score": 80,
                "Architecture": "LED Indicator",
                "Package": "T-1 3/4",
                "Pin Count": 2,
                "Voltage Range": "Verify forward voltage and current",
                "Compatibility Notes": "Verify lens size, color, brightness, forward voltage, current rating, and mounting style.",
            },
            {
                "Alternative Part": "CLM3C-WKW-CWBYA453",
                "Category": "White SMD LED",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "White SMD LED candidate",
                "Recommendation Score": 76,
                "Architecture": "LED Indicator",
                "Package": "PLCC",
                "Pin Count": 2,
                "Voltage Range": "Verify forward voltage and current",
                "Compatibility Notes": "Verify color temperature, luminous intensity, forward voltage, thermal behavior, package, and polarity.",
            },
        ]


    
    # EEPROM / Flash memory family detection
    elif (
        "eeprom" in description
        or "flash memory" in description
        or "serial flash" in description
        or "memory ic" in description
        or original_part_number.upper().startswith("24LC")
        or original_part_number.upper().startswith("AT24")
        or original_part_number.upper().startswith("W25Q")
        or original_part_number.upper().startswith("MX25")
    ):
        candidates = [
            {
                "Alternative Part": "24LC256-I/P",
                "Category": "I2C EEPROM",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common I2C EEPROM candidate",
                "Recommendation Score": 84,
                "Architecture": "I2C EEPROM",
                "Package": "DIP-8 / SOIC-8 variants",
                "Pin Count": 8,
                "Voltage Range": "Verify operating voltage",
                "Compatibility Notes": "Verify memory size, bus protocol, address pins, package, voltage range, write endurance, and timing.",
            },
            {
                "Alternative Part": "AT24C256C-SSHL-T",
                "Category": "I2C EEPROM",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common serial EEPROM option",
                "Recommendation Score": 82,
                "Architecture": "I2C EEPROM",
                "Package": "SOIC-8",
                "Pin Count": 8,
                "Voltage Range": "Verify operating voltage",
                "Compatibility Notes": "Confirm memory density, I2C address behavior, voltage range, package, and write-cycle timing.",
            },
            {
                "Alternative Part": "W25Q64JVSSIQ",
                "Category": "SPI NOR Flash",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common SPI flash option",
                "Recommendation Score": 80,
                "Architecture": "SPI NOR Flash",
                "Package": "SOIC-8",
                "Pin Count": 8,
                "Voltage Range": "Verify operating voltage",
                "Compatibility Notes": "Verify memory size, SPI mode, voltage range, package, erase sector size, and firmware compatibility.",
            },
            {
                "Alternative Part": "MX25L6406EM2I-12G",
                "Category": "SPI NOR Flash",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "SPI flash candidate",
                "Recommendation Score": 76,
                "Architecture": "SPI NOR Flash",
                "Package": "SOIC-8",
                "Pin Count": 8,
                "Voltage Range": "Verify operating voltage",
                "Compatibility Notes": "Verify capacity, voltage, command set, package, erase/write behavior, and firmware support.",
            },
        ]

    # Sensor family detection
    elif (
        "sensor" in description
        or "temperature sensor" in description
        or "humidity sensor" in description
        or "pressure sensor" in description
        or "accelerometer" in description
        or original_part_number.upper().startswith("TMP")
        or original_part_number.upper().startswith("LM35")
        or original_part_number.upper().startswith("BME")
        or original_part_number.upper().startswith("MPU")
    ):
        candidates = [
            {
                "Alternative Part": "TMP36GT9Z",
                "Category": "Temperature Sensor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Analog temperature sensor candidate",
                "Recommendation Score": 82,
                "Architecture": "Analog Temperature Sensor",
                "Package": "TO-92",
                "Pin Count": 3,
                "Voltage Range": "Verify supply/output range",
                "Compatibility Notes": "Verify sensor type, output scaling, supply voltage, accuracy, package, and calibration requirements.",
            },
            {
                "Alternative Part": "LM35DZ/NOPB",
                "Category": "Temperature Sensor",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common analog temperature sensor",
                "Recommendation Score": 80,
                "Architecture": "Analog Temperature Sensor",
                "Package": "TO-92",
                "Pin Count": 3,
                "Voltage Range": "Verify supply/output range",
                "Compatibility Notes": "Verify output scale, accuracy, supply voltage, operating range, and package pinout.",
            },
            {
                "Alternative Part": "BME280",
                "Category": "Environmental Sensor",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Digital environmental sensor candidate",
                "Recommendation Score": 76,
                "Architecture": "I2C/SPI Environmental Sensor",
                "Package": "LGA",
                "Pin Count": 8,
                "Voltage Range": "Verify interface voltage",
                "Compatibility Notes": "Not a direct replacement for analog sensors. Verify interface, firmware, package, and measurement requirements.",
            },
            {
                "Alternative Part": "MPU-6050",
                "Category": "Motion Sensor",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Common IMU candidate",
                "Recommendation Score": 72,
                "Architecture": "I2C IMU",
                "Package": "QFN",
                "Pin Count": 24,
                "Voltage Range": "Verify interface voltage",
                "Compatibility Notes": "Verify sensor axes, interface, register compatibility, voltage, package, and firmware support.",
            },
        ]

    # Fuse family detection
    elif (
        "fuse" in description
        or "resettable fuse" in description
        or "polyfuse" in description
        or "ptc" in description
        or original_part_number.upper().startswith("MF")
        or original_part_number.upper().startswith("SMD")
        or original_part_number.upper().startswith("RXE")
    ):
        candidates = [
            {
                "Alternative Part": "MF-R050",
                "Category": "Resettable Fuse",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common resettable fuse candidate",
                "Recommendation Score": 82,
                "Architecture": "PTC Resettable Fuse",
                "Package": "Radial",
                "Pin Count": 2,
                "Voltage Range": "Verify hold current and voltage",
                "Compatibility Notes": "Verify hold current, trip current, voltage rating, resistance, package, and operating temperature.",
            },
            {
                "Alternative Part": "MF-NSMF050-2",
                "Category": "SMD Resettable Fuse",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "SMD resettable fuse candidate",
                "Recommendation Score": 80,
                "Architecture": "PTC Resettable Fuse",
                "Package": "SMD",
                "Pin Count": 2,
                "Voltage Range": "Verify hold current and voltage",
                "Compatibility Notes": "Verify footprint, hold current, trip current, voltage rating, resistance, and thermal behavior.",
            },
            {
                "Alternative Part": "RXE050",
                "Category": "Resettable Fuse",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Radial PTC fuse option",
                "Recommendation Score": 78,
                "Architecture": "PTC Resettable Fuse",
                "Package": "Radial",
                "Pin Count": 2,
                "Voltage Range": "Verify hold current and voltage",
                "Compatibility Notes": "Verify current ratings, voltage rating, package, resistance, and reset behavior.",
            },
        ]

    # Fan family detection
    elif (
        "fan" in description
        or "blower" in description
        or "dc fan" in description
        or "cooling fan" in description
        or original_part_number.upper().startswith("AFB")
        or original_part_number.upper().startswith("MF")
        or original_part_number.upper().startswith("OD")
    ):
        candidates = [
            {
                "Alternative Part": "AFB0412SHB",
                "Category": "DC Cooling Fan",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common 40mm DC fan candidate",
                "Recommendation Score": 80,
                "Architecture": "Brushless DC Fan",
                "Package": "40mm",
                "Pin Count": 2,
                "Voltage Range": "12V",
                "Compatibility Notes": "Verify voltage, airflow, current, noise, connector, mounting holes, dimensions, and tach/PWM requirements.",
            },
            {
                "Alternative Part": "MF40101V1-1000U-A99",
                "Category": "DC Cooling Fan",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common 40mm cooling fan option",
                "Recommendation Score": 78,
                "Architecture": "Brushless DC Fan",
                "Package": "40mm",
                "Pin Count": 2,
                "Voltage Range": "12V",
                "Compatibility Notes": "Verify airflow, voltage, connector, dimensions, bearing type, noise, and current draw.",
            },
            {
                "Alternative Part": "OD4010-12HB",
                "Category": "DC Cooling Fan",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Cooling fan candidate",
                "Recommendation Score": 76,
                "Architecture": "Brushless DC Fan",
                "Package": "40mm",
                "Pin Count": 2,
                "Voltage Range": "12V",
                "Compatibility Notes": "Verify physical size, airflow, static pressure, voltage, connector, and mounting compatibility.",
            },
        ]

    # Cable / harness family detection
    elif (
        "cable" in description
        or "wire harness" in description
        or "harness" in description
        or "jumper wire" in description
        or "ribbon cable" in description
        or original_part_number.upper().startswith("A")
        or original_part_number.upper().startswith("H")
        or original_part_number.upper().startswith("WM")
    ):
        candidates = [
            {
                "Alternative Part": "A02SR02SR30K152B",
                "Category": "Wire Harness",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Harness candidate",
                "Recommendation Score": 74,
                "Architecture": "Wire Harness",
                "Package": "Cable Assembly",
                "Pin Count": 2,
                "Voltage Range": "Verify wire/current rating",
                "Compatibility Notes": "Verify connector series, pitch, pin count, cable length, wire gauge, current rating, latch style, and pinout.",
            },
            {
                "Alternative Part": "WM2002-ND",
                "Category": "Cable Assembly",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Cable assembly candidate",
                "Recommendation Score": 70,
                "Architecture": "Cable Assembly",
                "Package": "Assembly",
                "Pin Count": 2,
                "Voltage Range": "Verify connector/current rating",
                "Compatibility Notes": "Verify mating connector, wire length, pinout, gauge, insulation, current rating, and environmental requirements.",
            },
        ]

    # Fastener family detection
    elif (
        "screw" in description
        or "fastener" in description
        or "standoff" in description
        or "nut" in description
        or "washer" in description
        or "spacer" in description
        or original_part_number.upper().startswith("M3")
        or original_part_number.upper().startswith("M4")
        or original_part_number.upper().startswith("932")
    ):
        candidates = [
            {
                "Alternative Part": "M3X8MM-SCREW",
                "Category": "Machine Screw",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Mechanical fastener candidate",
                "Recommendation Score": 70,
                "Architecture": "Fastener",
                "Package": "Mechanical",
                "Pin Count": 0,
                "Voltage Range": "N/A",
                "Compatibility Notes": "Verify thread size, length, head style, drive type, material, finish, strength grade, and clearance.",
            },
            {
                "Alternative Part": "M3-STANDOFF-10MM",
                "Category": "Standoff",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Mechanical spacing candidate",
                "Recommendation Score": 68,
                "Architecture": "Mechanical Hardware",
                "Package": "Mechanical",
                "Pin Count": 0,
                "Voltage Range": "N/A",
                "Compatibility Notes": "Verify thread, length, material, gender, diameter, installation method, and mechanical stackup.",
            },
            {
                "Alternative Part": "M3-WASHER",
                "Category": "Washer",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Mechanical hardware candidate",
                "Recommendation Score": 66,
                "Architecture": "Mechanical Hardware",
                "Package": "Mechanical",
                "Pin Count": 0,
                "Voltage Range": "N/A",
                "Compatibility Notes": "Verify inner diameter, outer diameter, thickness, material, finish, and mechanical requirements.",
            },
        ]

    # AVR microcontroller family detection
    elif "atmega328" in original_part_number.lower():
        candidates = [
            {
                "Alternative Part": "ATMEGA328P-AU",
                "Category": "Direct AVR Alternative",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Best Drop-In",
                "Recommendation Score": 95,
                "Architecture": "AVR",
                "Package": "TQFP-32",
                "Pin Count": 32,
                "Voltage Range": "1.8V-5.5V",
                "Compatibility Notes": "Same AVR family; likely closest drop-in option.",
            },
            {
                "Alternative Part": "ATMEGA168PA-PU",
                "Category": "Lower Feature AVR",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Reduced resources",
                "Recommendation Score": 80,
                "Architecture": "AVR",
                "Package": "DIP-28",
                "Pin Count": 28,
                "Voltage Range": "1.8V-5.5V",
                "Compatibility Notes": "Same AVR family but reduced memory/resources.",
            },
            {
                "Alternative Part": "ATMEGA32U4-AU",
                "Category": "USB AVR Upgrade",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "USB-capable upgrade",
                "Recommendation Score": 78,
                "Architecture": "AVR",
                "Package": "TQFP-44",
                "Pin Count": 44,
                "Voltage Range": "2.7V-5.5V",
                "Compatibility Notes": "Same AVR ecosystem with USB support; board and firmware changes may be needed.",
            },
            {
                "Alternative Part": "PIC16F877A-I/P",
                "Category": "Microchip Alternative",
                "Lifecycle": "Mature",
                "Estimated Risk": "Medium",
                "Recommendation": "Firmware redesign needed",
                "Recommendation Score": 76,
                "Architecture": "PIC",
                "Package": "DIP-40",
                "Pin Count": 40,
                "Voltage Range": "2.0V-5.5V",
                "Compatibility Notes": "Different MCU architecture; firmware redesign required.",
            },
            {
                "Alternative Part": "STM32F103C8T6",
                "Category": "ARM Cortex-M Alternative",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Higher-performance option",
                "Recommendation Score": 72,
                "Architecture": "ARM Cortex-M3",
                "Package": "LQFP-48",
                "Pin Count": 48,
                "Voltage Range": "2.0V-3.6V",
                "Compatibility Notes": "ARM Cortex-M migration; significant firmware and hardware review required.",
            },
        ]

    # Do not expose hard-coded family examples as market alternatives. All
    # user-facing candidates must come from a supplier relationship and retain
    # its evidence and classification regardless of component category.
    candidates = supplier_candidates

    MAX_LIVE_SUPPLIER_LOOKUPS = 5

    for index, candidate in enumerate(candidates):

        if isinstance(candidate, str):
            candidate = {
                "Alternative Part": candidate,
                "Category": "Suggested Alternative",
                "Lifecycle": "Unknown",
                "Estimated Risk": "Medium",
                "Recommendation": "Review compatibility",
                "Recommendation Score": 70,
            }

        alt_part_number = candidate.get("Alternative Part", "")

        if not alt_part_number:
            continue

        try:
            exact_supplier_data = get_best_part_data(alt_part_number) or {}
        except Exception:
            exact_supplier_data = {}
        if exact_supplier_data.get("supplier_data_verified"):
            candidate["Supplier"] = exact_supplier_data.get("source") or candidate.get("Supplier", "")
            candidate["Stock"] = exact_supplier_data.get("stock_total", candidate.get("Stock", 0))
            candidate["Unit Price"] = exact_supplier_data.get("unit_price", candidate.get("Unit Price", 0.0))
            if exact_supplier_data.get("lifecycle_status"):
                candidate["Lifecycle"] = exact_supplier_data.get("lifecycle_status")
            for candidate_key, supplier_key in (
                ("Package", "package"),
                ("Pin Count", "pin_count"),
                ("Mounting Style", "mounting_style"),
                ("Architecture", "architecture"),
                ("Channel Count", "channel_count"),
                ("Datasheet URL", "datasheet_url"),
            ):
                if exact_supplier_data.get(supplier_key) not in (None, "", 0):
                    candidate[candidate_key] = exact_supplier_data.get(supplier_key)


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

     

        candidate_part_number = candidate.get("Alternative Part", "")

        if candidate_index < MAX_LIVE_SUPPLIER_LOOKUPS:
            candidate_supplier_data = get_best_part_data(candidate_part_number)
        else:
            candidate_supplier_data = {}

        candidate["Supply Voltage Min"] = candidate.get("Supply Voltage Min") or candidate_supplier_data.get("supply_voltage_min")
        candidate["Supply Voltage Max"] = candidate.get("Supply Voltage Max") or candidate_supplier_data.get("supply_voltage_max")
        candidate["Voltage Range"] = candidate.get("Voltage Range") or candidate_supplier_data.get("voltage_range", "")
        candidate["Datasheet URL"] = candidate.get("Datasheet URL") or candidate_supplier_data.get("datasheet_url", "")

        for field_name, config in ELECTRICAL_FIELDS.items():
            candidate[config["display_key"]] = (
                candidate.get(config["display_key"])
                or candidate_supplier_data.get(field_name)
            )
        
        feature_text = " ".join(
            [
                str(candidate.get("Alternative Part", "")),
                str(candidate.get("Category", "")),
                str(candidate.get("Architecture", "")),
                str(candidate.get("Recommendation", "")),
                str(candidate.get("Compatibility Notes", "")),
                str(candidate_supplier_data.get("description", "")),
            ]
        )

        candidate["Feature Tags"] = infer_feature_tags(feature_text)
        

        original_candidate = {
            "Alternative Part": original_part_number,
            "Architecture": original_data.get("architecture", ""),
            "Package": original_data.get("package", "")
            or (
                "SMD-8"
                if original_data.get("mounting_style") == "SMD"
                and original_data.get("pin_count") == 8
                else ""
            ),
            "Pin Count": original_data.get("pin_count", 0),
            "Voltage Range": original_data.get("voltage_range", ""),
            "Channel Count": original_data.get("channel_count", 0),
            "Supply Voltage Min": original_data.get(
                "supply_voltage_min"
            ),
            "Supply Voltage Max": original_data.get(
                "supply_voltage_max"
            ),
            "Bandwidth MHz": original_data.get("bandwidth_mhz"),
            "Slew Rate V/us": original_data.get("slew_rate_v_us"),
            "Input Offset mV": original_data.get("input_offset_mv"),
            "Quiescent Current mA": original_data.get("quiescent_current_ma"),
            "Input Bias nA": original_data.get("input_bias_na"),
            "GBW MHz": original_data.get("gbw_mhz"),
            "Feature Tags": original_data.get("Feature Tags", set()),
           }

        candidate["Drop-In Confidence"] = calculate_drop_in_confidence(
            original_candidate,
            candidate,
        )

        candidate["Drop-In Rating"] = get_drop_in_rating(
            candidate["Drop-In Confidence"]
        )

        candidate["Drop-In Reasons"] = get_drop_in_reasons(
            original_candidate,
            candidate,
        )

        candidate["Recommendation Score"] = calculate_recommendation_score(candidate)

        # A supplier catalogue result must not retain a perfect compatibility
        # score when the retrieved engineering data contains differences or
        # gaps.  Preserve the transparent counts for the UI and apply them to
        # the sourcing score only after all supplier fields are present.
        candidate_comparison_data = dict(candidate_supplier_data or {})
        candidate_comparison_data.update({
            "description": candidate_comparison_data.get("description", ""),
            "architecture": candidate.get("Architecture", candidate_comparison_data.get("architecture", "")),
            "package": candidate.get("Package", candidate_comparison_data.get("package", "")),
            "pin_count": candidate.get("Pin Count", candidate_comparison_data.get("pin_count")),
            "mounting_style": candidate.get("Mounting", candidate_comparison_data.get("mounting_style", "")),
            "voltage_range": candidate.get("Voltage Range", candidate_comparison_data.get("voltage_range", "")),
            "channel_count": candidate.get("Channel Count", candidate_comparison_data.get("channel_count")),
        })
        for field_name, config in ELECTRICAL_FIELDS.items():
            candidate_comparison_data[field_name] = candidate.get(
                config["display_key"],
                candidate_comparison_data.get(field_name),
            )

        comparison = build_datasheet_comparison(original_data, candidate_comparison_data)
        comparison_counts = comparison["counts"]
        is_explicit_substitute = (
            str(candidate.get("Evidence Type", "")).strip().casefold()
            == "distributor-listed substitute"
        )
        score, confidence = apply_comparison_evidence_to_scores(
            candidate["Recommendation Score"],
            candidate["Drop-In Confidence"],
            comparison_counts,
            is_explicit_substitute=is_explicit_substitute,
        )
        candidate["Recommendation Score"] = score
        candidate["Drop-In Confidence"] = confidence
        candidate["Drop-In Rating"] = get_drop_in_rating(confidence)
        candidate["Datasheet Match Count"] = comparison_counts["Match"]
        candidate["Datasheet Difference Count"] = comparison_counts["Different"]
        candidate["Datasheet Needs Data Count"] = comparison_counts["Needs data"]

        normalized_candidates.append(candidate)

    candidates = normalized_candidates

    filtered_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("Alternative Part", "").strip().lower()
        != original_part_number.strip().lower()
    ]

    sorted_candidates = sorted(
        filtered_candidates,
        key=lambda x: x["Recommendation Score"],
        reverse=True,
    )

    return sorted_candidates[:5]

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
