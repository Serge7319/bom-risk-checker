def calculate_risk(part_data: dict) -> dict:
    """
    Calculates a 0–100 risk score for one BOM component.
    """

    score = 0
    reasons = []

    lifecycle_status = part_data.get("lifecycle_status", "Unknown")
    stock_total = part_data.get("stock_total", 0)
    supplier_count = part_data.get("supplier_count", 0)
    lead_time_weeks = part_data.get("lead_time_weeks", None)
    has_alternates = part_data.get("has_alternates", False)

    if lifecycle_status in ["EOL", "Obsolete"]:
        score += 45
        reasons.append("Part is end-of-life or obsolete")

    elif lifecycle_status == "NRND":
        score += 30
        reasons.append("Part is not recommended for new designs")

    elif lifecycle_status == "Unknown":
        score += 15
        reasons.append("Lifecycle status is unknown")

    if stock_total == 0:
        score += 45
        reasons.append("No stock available")

    elif stock_total < part_data.get("quantity", 0):
        score += 20
        reasons.append("Stock is below required BOM quantity")

    if supplier_count <= 1:
        score += 20
        reasons.append("Single-source supply risk")

    if lead_time_weeks is not None:
        if lead_time_weeks > 16:
            score += 20
            reasons.append("Lead time is greater than 16 weeks")
        elif lead_time_weeks >= 8:
            score += 10
            reasons.append("Lead time is between 8 and 16 weeks")

    if not has_alternates:
        score += 20
        reasons.append("No alternate parts found")

    score = min(score, 100)

    if score >= 66:
        risk_level = "High"
    elif score >= 31:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    return {
        "risk_score": score,
        "risk_level": risk_level,
        "risk_reasons": reasons,
    }