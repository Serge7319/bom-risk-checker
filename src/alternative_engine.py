import pandas as pd

from integrations.supplier_aggregator import get_best_part_data
from src.risk_engine import calculate_risk
from integrations.supplier_aggregator import search_supplier_alternatives

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

    if "best drop-in" in recommendation:
        score += 15
        reasons.append("Best drop-in candidate")

    elif "reduced resources" in recommendation:
        score -= 5
        reasons.append("Reduced resource capacity")

    elif "usb-capable" in recommendation:
        score -= 3
        reasons.append("Board/firmware changes likely")

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

    candidate_voltage = str(
        candidate.get("Voltage Range", candidate.get("voltage_range", ""))
    ).lower()

    # Function match is most important for logic ICs.
    if "logic" in original_architecture or "logic" in candidate_architecture:
        if original_function and candidate_function:
            if original_function == candidate_function:
                score += 60
            else:
                return 0
        else:
            score += 10

    elif original_architecture and candidate_architecture:
        if original_architecture == candidate_architecture:
            score += 40
        else:
            score += 10

    normalized_original_package = normalize_package_name(original_package)
    normalized_candidate_package = normalize_package_name(candidate_package)

    if normalized_original_package and normalized_candidate_package:
        if normalized_original_package == normalized_candidate_package:
            score += 25
        else:
            score -= 15

    if original_pin_count and candidate_pin_count:
        if original_pin_count == candidate_pin_count:
            score += 20
        else:
            score -= 20

    if candidate_voltage and candidate_voltage not in ["none", "n/a"]:
        score += 5

    return max(0, min(score, 100))

def get_drop_in_rating(confidence: int) -> str:
    if confidence >= 90:
        return "🟢 High"

    elif confidence >= 70:
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
    if not normalized_original_package:
        reasons.append("⚠ Original package could not be verified")

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

    if candidate_voltage and candidate_voltage.lower() not in ["none", "n/a"]:
        reasons.append(f"✓ Compatible operating voltage range ({candidate_voltage})")

    return "; ".join(reasons)

def normalize_package_name(package: str) -> str:
    package = str(package or "").upper().strip()

    if not package:
        return ""

    if "DIP" in package and "16" in package:
        return "DIP-16"

    if "DIP" in package and "14" in package:
        return "DIP-14"

    if "DIP" in package and "8" in package:
        return "DIP-8"

    if "DIP" in package and "4" in package:
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
                "Voltage Range": "Single/Dual supply",
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
                "Voltage Range": "Single/Dual supply",
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

    if supplier_results:
        for result in supplier_results:
            result_part_number = result.get("Part Number", "")
            
            normalized_result = result_part_number.strip().upper()
            normalized_original = original_part_number.strip().upper()

            if normalized_result == normalized_original:
                continue

            if normalized_original not in normalized_result and normalized_result not in normalized_original:
                continue

            if (
                len(normalized_original) >= 5
                and len(normalized_result) > len(normalized_original) * 3
            ):
                continue

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
                        65
                        if result.get("Stock", 0) > 1000
                        else 55
                    ),
                }
            )
    # Future: add more families here
    # e.g., op-amps, regulators, microcontrollers
    for candidate in candidates:

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

    normalized_candidates = []

    for candidate in candidates:
        if isinstance(candidate, str):
            candidate = {
                "Alternative Part": candidate,
                "Category": "Suggested Alternative",
                "Lifecycle": "Unknown",
                "Estimated Risk": "Medium",
                "Recommendation": "Review compatibility",
                "Recommendation Score": 70,
            }

        candidate["Recommendation Score"] = calculate_recommendation_score(candidate)

        original_candidate = {
            "Alternative Part": original_part_number,
            "Architecture": original_data.get("architecture", ""),
            "Package": original_data.get("package", ""),
            "Pin Count": original_data.get("pin_count", 0),
            "Voltage Range": original_data.get("voltage_range", ""),
            "Channel Count": original_data.get("channel_count", 0),
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