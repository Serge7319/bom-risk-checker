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
    if supplier:
        score += 5
        reasons.append("Supplier verified")

    # Price bonus
    if unit_price > 0 and unit_price < 3:
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

    # Logic IC family detection
    elif (
        "logic" in description
        or "gate" in description
        or "counter" in description
        or "shift register" in description
        or "74hc" in original_part_number.lower()
        or "74ls" in original_part_number.lower()
        or "74hct" in original_part_number.lower()
        or "cd40" in original_part_number.lower()
    ):
        candidates = [
            {
                "Alternative Part": "SN74HC00N",
                "Category": "Quad NAND Gate",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common 74HC NAND logic option",
                "Recommendation Score": 86,
                "Architecture": "CMOS Logic",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Verify logic family, voltage levels, propagation delay, package, and pinout.",
            },
            {
                "Alternative Part": "SN74HC04N",
                "Category": "Hex Inverter",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common 74HC inverter option",
                "Recommendation Score": 84,
                "Architecture": "CMOS Logic",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Use only for inverter applications. Verify pinout and drive requirements.",
            },
            {
                "Alternative Part": "SN74HC08N",
                "Category": "Quad AND Gate",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common 74HC AND gate option",
                "Recommendation Score": 82,
                "Architecture": "CMOS Logic",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Use only for AND-gate replacement. Verify logic thresholds and pin compatibility.",
            },
            {
                "Alternative Part": "SN74HC14N",
                "Category": "Hex Schmitt-Trigger Inverter",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Useful for noisy digital inputs",
                "Recommendation Score": 80,
                "Architecture": "CMOS Logic",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Schmitt-trigger inverter; not identical to a standard inverter. Verify input behavior.",
            },
            {
                "Alternative Part": "SN74HC32N",
                "Category": "Quad OR Gate",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common 74HC OR gate option",
                "Recommendation Score": 80,
                "Architecture": "CMOS Logic",
                "Package": "DIP-14",
                "Pin Count": 14,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Use only for OR-gate replacement. Verify logic thresholds and pinout.",
            },
            {
                "Alternative Part": "SN74HC595N",
                "Category": "8-Bit Shift Register",
                "Lifecycle": "Active",
                "Estimated Risk": "Low",
                "Recommendation": "Common serial-to-parallel shift register",
                "Recommendation Score": 78,
                "Architecture": "CMOS Logic",
                "Package": "DIP-16",
                "Pin Count": 16,
                "Voltage Range": "2V-6V",
                "Compatibility Notes": "Verify timing, output drive, latch behavior, package, and pinout.",
            },
        ]
    
    # MOSFET / transistor family detection
    elif (
        "mosfet" in description
        or "field effect transistor" in description
        or "fet" in description
        or "transistor" in description
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

            if result_part_number.strip().lower() == original_part_number.strip().lower():
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
                        90
                        if result.get("Stock", 0) > 1000
                        else 70
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
        normalized_candidates.append(candidate)

    candidates = normalized_candidates

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