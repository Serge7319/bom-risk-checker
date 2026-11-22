import math
import pandas as pd


def _bool_value(value: object) -> bool:
    """Parse persisted booleans without treating the string 'false' as true."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "complete", "completed"}


def normalize_saved_health_score(value: object) -> int | None:
    """Parse a persisted score while keeping missing or invalid scores unknown."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return int(numeric) if math.isfinite(numeric) else None


def calculate_bom_health_score(results_df: pd.DataFrame) -> dict:
    """
    Calculates an overall BOM health score from 0–100.

    Higher score = healthier BOM.
    Lower score = riskier BOM.
    """

    if results_df is None or results_df.empty:
        return {
            "health_score": None,
            "health_status": "No Data",
            "summary_message": "No BOM data available.",
            "assessment_coverage": 0.0,
            "needs_verification_count": 0,
        }

    # Recalculate every row from its source records. Saved scores and boolean
    # flags can outlive the supplier snapshot that originally produced them.
    from src.risk_engine import calculate_risk

    assessments = [
        calculate_risk(row.to_dict())
        for _, row in results_df.iterrows()
    ]
    complete = [
        bool(item.get("evidence_coverage_complete"))
        and item.get("risk_score") is not None
        for item in assessments
    ]
    needs_verification_count = sum(not item for item in complete)
    coverage = sum(complete) / max(1, len(complete))
    if needs_verification_count:
        return {
            "health_score": None,
            "health_status": "Needs verification",
            "summary_message": (
                f"An overall health score is withheld because exact-part supplier evidence, "
                f"inventory coverage, or configured-source checks are incomplete for "
                f"{needs_verification_count} of {len(results_df)} component(s)."
            ),
            "assessment_coverage": coverage,
            "needs_verification_count": needs_verification_count,
        }

    risk_scores = [float(item["risk_score"]) for item in assessments]
    average_risk_score = sum(risk_scores) / len(risk_scores)
    health_score = round(100 - average_risk_score)

    if health_score >= 85:
        health_status = "Healthy"
        summary_message = "This BOM appears healthy with limited supply chain risk."
    elif health_score >= 60:
        health_status = "Moderate Risk"
        summary_message = "This BOM has some risk areas that should be reviewed."
    else:
        health_status = "High Risk"
        summary_message = "This BOM has significant risk and needs immediate review."

    return {
        "health_score": health_score,
        "health_status": health_status,
        "summary_message": summary_message,
        "assessment_coverage": coverage,
        "needs_verification_count": 0,
    }


def generate_executive_summary(results_df: pd.DataFrame) -> list:
    """
    Generates plain-English executive summary bullets.
    """

    from apps.api.evidence_contract import EVIDENCE_LIVE, classify_part_evidence
    from src.risk_engine import calculate_risk

    assessments = [calculate_risk(row.to_dict()) for _, row in results_df.iterrows()]
    high_count = sum(item.get("risk_level") == "High" for item in assessments)
    medium_count = sum(item.get("risk_level") == "Medium" for item in assessments)
    low_count = sum(item.get("risk_level") == "Low" for item in assessments)
    obsolete_count = 0
    unknown_lifecycle_count = 0
    no_stock_count = 0
    needs_verification_count = 0
    for (_, row), assessment in zip(results_df.iterrows(), assessments):
        part = row.to_dict()
        fields = (classify_part_evidence(part).get("fields") or {})
        lifecycle_field = fields.get("lifecycle") or {}
        stock_field = fields.get("stock") or {}
        lifecycle_live = lifecycle_field.get("evidence_class") == EVIDENCE_LIVE
        stock_live = stock_field.get("evidence_class") == EVIDENCE_LIVE
        lifecycle_value = str(
            part.get("Lifecycle") or part.get("lifecycle_status")
            or part.get("Lifecycle Status") or ""
        ).casefold()
        if lifecycle_live and any(
            token in lifecycle_value for token in ("obsolete", "eol", "end of life", "discontinued")
        ):
            obsolete_count += 1
        if not lifecycle_live:
            unknown_lifecycle_count += 1
        if (
            stock_live
            and bool(stock_field.get("complete"))
            and stock_field.get("observed_total") == 0
        ):
            no_stock_count += 1
        if not assessment.get("evidence_coverage_complete"):
            needs_verification_count += 1

    bullets = [
        f"{high_count} high-risk components require immediate review.",
        f"{medium_count} medium-risk components should be monitored.",
        f"{low_count} components are currently low risk.",
        f"{obsolete_count} components are marked obsolete or end-of-life.",
        f"{unknown_lifecycle_count} components have unknown lifecycle status.",
        f"{no_stock_count} components have a confirmed zero on-hand stock report.",
        f"{needs_verification_count} components need supplier evidence verification.",
    ]

    return bullets
