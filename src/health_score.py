import math
import pandas as pd


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

    levels = (
        results_df["Risk Level"].fillna("").astype(str).str.casefold()
        if "Risk Level" in results_df.columns
        else pd.Series("", index=results_df.index)
    )
    needs_verification = levels.eq("needs verification")
    if "Supplier Data Verified" in results_df.columns:
        verified = results_df["Supplier Data Verified"].fillna(False).astype(bool)
        needs_verification = needs_verification | ~verified
    if "Stock Data Complete" in results_df.columns:
        stock_complete = results_df["Stock Data Complete"].fillna(False).astype(bool)
        needs_verification = needs_verification | ~stock_complete
    needs_verification_count = int(needs_verification.sum())
    coverage = (len(results_df) - needs_verification_count) / max(1, len(results_df))
    if needs_verification_count:
        return {
            "health_score": None,
            "health_status": "Needs verification",
            "summary_message": (
                f"An overall health score is withheld because supplier evidence is missing "
                f"for {needs_verification_count} of {len(results_df)} component(s)."
            ),
            "assessment_coverage": coverage,
            "needs_verification_count": needs_verification_count,
        }

    if "Risk Score" not in results_df.columns:
        return {
            "health_score": None,
            "health_status": "Needs verification",
            "summary_message": "Risk scores are not available for this BOM.",
            "assessment_coverage": coverage,
            "needs_verification_count": len(results_df),
        }
    risk_scores = pd.to_numeric(results_df["Risk Score"], errors="coerce")
    if risk_scores.notna().sum() == 0:
        return {
            "health_score": None,
            "health_status": "Needs verification",
            "summary_message": "Risk scores are not available for this BOM.",
            "assessment_coverage": 0.0,
            "needs_verification_count": len(results_df),
        }
    average_risk_score = risk_scores.mean()
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

    high_count = len(results_df[results_df["Risk Level"] == "High"])
    medium_count = len(results_df[results_df["Risk Level"] == "Medium"])
    low_count = len(results_df[results_df["Risk Level"] == "Low"])

    obsolete_count = len(
        results_df[
            results_df["Lifecycle Status"].isin(["Obsolete", "EOL"])
        ]
    )

    unknown_lifecycle_count = len(
        results_df[results_df["Lifecycle Status"] == "Unknown"]
    )

    stock = pd.to_numeric(results_df.get("Stock Available", pd.Series(index=results_df.index, dtype=float)), errors="coerce")
    stock_verified = (
        results_df["Supplier Data Verified"].fillna(False).astype(bool)
        if "Supplier Data Verified" in results_df.columns
        else stock.notna()
    )
    no_stock_count = int((stock.eq(0) & stock_verified).sum())
    needs_verification_count = int(
        (results_df.get("Risk Level", pd.Series(index=results_df.index, dtype=str))
         .fillna("").astype(str).str.casefold() == "needs verification").sum()
    )

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
