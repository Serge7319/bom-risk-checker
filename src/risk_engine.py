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

    lifecycle_text = str(lifecycle_status).lower()

    if "obsolete" in lifecycle_text or "eol" in lifecycle_text:
        score += 50
        reasons.append("Part is end-of-life or obsolete")

    elif "not recommended" in lifecycle_text or "nrnd" in lifecycle_text:
        score += 35
        reasons.append("Part is not recommended for new designs")

    elif "replacement suggested" in lifecycle_text:
        score += 20
        reasons.append("Supplier suggests a replacement part")

    elif "factory special order" in lifecycle_text:
        score += 20
        reasons.append("Part requires factory special order")

    elif "unknown" in lifecycle_text:
        score += 15
        reasons.append("Lifecycle status is unknown")

    if stock_total == 0:
        score += 45
        reasons.append("No stock available")

    elif stock_total < part_data.get("quantity", 0):
        score += 20
        reasons.append("Stock is below required BOM quantity")

    if lead_time_weeks is not None:
    try:
        lead_time = float(lead_time_weeks)

        if lead_time >= 52:
            score += 35
            reasons.append("Extremely long lead time")

        elif lead_time >= 26:
            score += 25
            reasons.append("Very long lead time")

        elif lead_time >= 12:
            score += 15
            reasons.append("Moderate lead time risk")

    except:
        pass

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

    if score >= 60:
        risk_level = "High"
    elif score >= 30:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    return {
        "risk_score": score,
        "risk_level": risk_level,
        "risk_reasons": reasons,
    }