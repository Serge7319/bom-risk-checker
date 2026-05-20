import pandas as pd

from integrations.supplier_aggregator import get_best_part_data
from src.risk_engine import calculate_risk
from src.supplier_aggregator import search_supplier_alternatives

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
    score = int(candidate.get("Recommendation Score", 70))
    reasons = []

    lifecycle = str(candidate.get("Lifecycle", "")).lower()
    stock = int(candidate.get("Stock", 0))
    supplier = str(candidate.get("Supplier", "")).strip()
    unit_price = float(candidate.get("Unit Price", 0.0))

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
    if supplier:
        score += 5
        reasons.append("Supplier verified")

    # Price bonus
    if unit_price > 0 and unit_price < 3:
        score += 5
        reasons.append("Low unit price")

    score = max(0, min(score, 100))

    candidate["Score Reasons"] = "; ".join(reasons)

    return score

def suggest_alternatives_v2(original_part_number: str) -> list:
    """
    Suggest candidate alternatives using supplier-derived metadata.

    Strategy:
    - Use supplier description
    - Identify part family
    - Return candidate parts from that family
    """

    original_data = get_best_part_data(original_part_number)

    description = original_data.get("description", "").lower()

    candidates = []

    supplier_results = search_supplier_alternatives(original_part_number)

    # Timer family detection
    if "timer" in description or "555" in original_part_number.upper():
        candidates = [
            "NE555P",
            "TLC555CP",
            "LMC555CN/NOPB",
            "NA555DR",
            "ICM7555IPA"
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
                "Compatibility Notes": "Same AVR family; likely closest drop-in option.",
            },
            {
                "Alternative Part": "ATMEGA168PA-PU",
                "Category": "Lower Feature AVR",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Reduced resources",
                "Recommendation Score": 80,
                "Compatibility Notes": "Same AVR family but reduced memory/resources.",
            },
            {
                "Alternative Part": "ATMEGA32U4-AU",
                "Category": "USB AVR Upgrade",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "USB-capable upgrade",
                "Recommendation Score": 78,
                "Compatibility Notes": "Same AVR ecosystem with USB support; board and firmware changes may be needed.",
            },
            {
                "Alternative Part": "PIC16F877A-I/P",
                "Category": "Microchip Alternative",
                "Lifecycle": "Mature",
                "Estimated Risk": "Medium",
                "Recommendation": "Firmware redesign needed",
                "Recommendation Score": 76,
                "Compatibility Notes": "Different MCU architecture; firmware redesign required.",
            },
            {
                "Alternative Part": "STM32F103C8T6",
                "Category": "ARM Cortex-M Alternative",
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Recommendation": "Higher-performance option",
                "Recommendation Score": 72,
                "Compatibility Notes": "ARM Cortex-M migration; significant firmware and hardware review required.",
            },
        ]

    if supplier_results:
        for result in supplier_results:
            candidates.append(
                {
                    "Alternative Part": result.get("Part Number", ""),
                    "Category": "Live Supplier Verification",
                    "Supplier": result.get("Supplier", ""),
                    "Stock": result.get("Stock", 0),
                    "Lifecycle": result.get("Lifecycle", "Unknown"),
                    "Estimated Risk": (
                        "Low"
                        if result.get("Stock", 0) > 1000
                        else "Medium"
                    ),
                    "Recommendation": "Current part verified through supplier data",
                    "Recommendation Score": (
                        90
                        if result.get("Stock", 0) > 1000
                        else 70
                    ),
                }
            )
    # Future: add more families here
    # e.g., op-amps, regulators, microcontrollers
    for candidate in candidates:
        alt_part_number = candidate.get("Alternative Part", "")

        if not alt_part_number:
            continue

        supplier_matches = search_supplier_alternatives(alt_part_number)

        if supplier_matches:
            best_match = max(
                supplier_matches,
                key=lambda x: x.get("Stock", 0)
            )

            candidate["Supplier"] = best_match.get("Supplier", "")
            candidate["Stock"] = best_match.get("Stock", 0)
            candidate["Unit Price"] = best_match.get("Unit Price", 0.0)

            if best_match.get("Lifecycle"):
                candidate["Lifecycle"] = best_match.get("Lifecycle")

    for candidate in candidates:
        candidate["Recommendation Score"] = calculate_recommendation_score(candidate)

    sorted_candidates = sorted(
        candidates,
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