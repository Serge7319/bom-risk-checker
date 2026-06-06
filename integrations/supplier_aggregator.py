from integrations.mouser_client import search_mouser_by_part_number
from integrations.digikey_client import search_digikey_by_part_number
import streamlit as st

def get_supplier_results(part_number: str) -> list:
    """
    Searches all available supplier APIs for a part number.

    Right now we only have Mouser connected.
    Later we will add DigiKey, Newark, and Nexar here.
    """

    results = []

    # Mouser lookup
    try:
        mouser_result = search_mouser_by_part_number(part_number)
        results.append(mouser_result)
    except Exception as error:
        results.append({
            "source": "Mouser",
            "error": str(error),
            "lifecycle_status": "Unknown",
            "stock_total": 0,
            "supplier_count": 0,
            "lead_time_weeks": None,
            "has_alternates": False,
            "manufacturer": "",
            "description": "",
            "mouser_part_number": "",
            "manufacturer_part_number": "",
            "product_detail_url": "",
        })

        # DigiKey lookup
    try:
        digikey_result = search_digikey_by_part_number(part_number)
        results.append(digikey_result)
    except Exception as error:
        results.append({
            "source": "DigiKey",
            "error": str(error),
            "lifecycle_status": "Unknown",
            "stock_total": 0,
            "supplier_count": 0,
            "lead_time_weeks": None,
            "has_alternates": False,
            "manufacturer": "",
            "description": "",
            "mouser_part_number": "",
            "manufacturer_part_number": "",
            "product_detail_url": "",
        })
    return results

@st.cache_data(ttl=3600, show_spinner = False)
def get_best_part_data(part_number: str) -> dict:
    """
    Returns the best supplier result for scoring/display.

    Current logic:
    - Search all connected suppliers
    - Ignore suppliers that returned errors
    - Choose supplier with highest stock as best source

    Added outputs:
    - supplier_count
    - total_market_stock
    - sources_available

    Later we can improve selection using:
    price, lead time, lifecycle, preferred supplier, region
    """

    # Get list of all supplier responses
    supplier_results = get_supplier_results(part_number)

    # Keep only successful supplier lookups
    valid_results = [
        result for result in supplier_results
        if "error" not in result
    ]

    # If every supplier failed, return safe fallback result
    if not valid_results:
        return default_aggregated_result(part_number, supplier_results)

    # Choose supplier with highest available stock
    best_result = max(
        valid_results,
        key=lambda result: result.get("stock_total", 0)
    )

    # Sum stock across all successful suppliers
    total_market_stock = sum(
        result.get("stock_total", 0)
        for result in valid_results
    )

    # Build readable supplier name list
    source_names = [
        result.get("source", "")
        for result in valid_results
    ]

    # Add useful aggregated fields
    best_result["supplier_count"] = len(valid_results)
    best_result["total_market_stock"] = total_market_stock
    best_result["sources_available"] = ", ".join(source_names)

    # Keep raw supplier responses for future comparison tables
    best_result["all_supplier_results"] = supplier_results

    return best_result


def default_aggregated_result(part_number: str, supplier_results: list) -> dict:
    """
    Fallback result if every supplier lookup fails.
    """

    return {
        "source": "Aggregator",
        "searched_part_number": part_number,
        "lifecycle_status": "Unknown",
        "stock_total": 0,
        "supplier_count": 0,
        "lead_time_weeks": None,
        "has_alternates": False,
        "manufacturer": "",
        "description": "",
        "mouser_part_number": "",
        "manufacturer_part_number": "",
        "product_detail_url": "",
        "all_supplier_results": supplier_results,
    }