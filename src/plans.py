PLANS = {
    "Starter": {
        "monthly_bom_limit": 5,
        "max_parts_per_bom": 10,
        "price": "$29/mo",
        "upgrade_to": "Pro",
        "description": "For small BOM checks and early users.",
    },
    "Pro": {
        "monthly_bom_limit": 10,
        "max_parts_per_bom": 20,
        "price": "$99/mo",
        "upgrade_to": "Business",
        "description": "For engineers reviewing multiple BOMs.",
    },
    "Business": {
        "monthly_bom_limit": 25,
        "max_parts_per_bom": 100,
        "price": "$299/mo",
        "upgrade_to": None,
        "description": "For teams reviewing larger BOMs.",
    },
}


def get_plan(plan_name: str) -> dict:
    return PLANS.get(plan_name, PLANS["Starter"])


def validate_bom_against_plan(bom_df, plan: dict, current_monthly_uploads: int) -> tuple:
    """
    Checks whether a user is allowed to analyze this BOM under their selected plan.

    Returns:
    - allowed: True/False
    - message: explanation
    """

    part_count = len(bom_df)

    if current_monthly_uploads >= plan["monthly_bom_limit"]:
        return (
            False,
            f"Monthly BOM limit reached. Your plan allows {plan['monthly_bom_limit']} BOMs per month.",
        )

    if part_count > plan["max_parts_per_bom"]:
        return (
            False,
            f"This BOM has {part_count} parts. Your plan allows up to {plan['max_parts_per_bom']} parts per BOM.",
        )

    return True, "BOM is within plan limits."