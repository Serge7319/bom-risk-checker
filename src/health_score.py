import pandas as pd


def calculate_bom_health_score(results_df: pd.DataFrame) -> dict:
    """
    Calculates an overall BOM health score from 0–100.

    Higher score = healthier BOM.
    Lower score = riskier BOM.
    """

    if results_df.empty:
        return {
            "health_score": 0,
            "health_status": "No Data",
            "summary_message": "No BOM data available.",
        }

    average_risk_score = results_df["Risk Score"].mean()
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

    no_stock_count = len(results_df[results_df["Stock Available"] == 0])

    bullets = [
        f"{high_count} high-risk components require immediate review.",
        f"{medium_count} medium-risk components should be monitored.",
        f"{low_count} components are currently low risk.",
        f"{obsolete_count} components are marked obsolete or end-of-life.",
        f"{unknown_lifecycle_count} components have unknown lifecycle status.",
        f"{no_stock_count} components currently show no stock available.",
    ]

    return bullets