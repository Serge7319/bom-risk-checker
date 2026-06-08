from integrations.mouser_client import search_mouser_by_part_number
from integrations.digikey_client import search_digikey_by_part_number
import streamlit as st

try:
    from integrations.newark_client import search_newark_by_part_number
except Exception:
    search_newark_by_part_number = None


def _safe_supplier_lookup(source_name, lookup_func, part_number):
    try:
        if lookup_func is None:
            return {
                "source": source_name,
                "error": f"{source_name} client not available",
            }

        result = lookup_func(part_number)

        if not result:
            return {
                "source": source_name,
                "error": f"No result from {source_name}",
            }

        result["source"] = source_name
        return result

    except Exception as e:
        return {
            "source": source_name,
            "error": str(e),
        }


def get_supplier_results(part_number):
    suppliers = [
        ("Mouser", search_mouser_by_part_number),
        ("DigiKey", search_digikey_by_part_number),
        ("Newark", search_newark_by_part_number),
    ]

    results = []

    for source_name, lookup_func in suppliers:
        results.append(
            _safe_supplier_lookup(source_name, lookup_func, part_number)
        )

    return results


@st.cache_data(ttl=3600, show_spinner=False)
def get_best_part_data(part_number):
    supplier_results = get_supplier_results(part_number)

    valid_results = [
        result for result in supplier_results
        if not result.get("error")
        and result.get("manufacturer_part_number")
    ]

    if not valid_results:
        return default_aggregated_result(part_number, supplier_results)

    total_market_stock = sum(
        int(result.get("stock_total", 0) or 0)
        for result in valid_results
    )

    sources_available = ", ".join(
        result.get("source", "")
        for result in valid_results
        if result.get("source")
    )

    supplier_count = len(valid_results)

    best_result = max(
        valid_results,
        key=lambda result: int(result.get("stock_total", 0) or 0),
    )

    best_result["supplier_count"] = supplier_count
    best_result["total_market_stock"] = total_market_stock
    best_result["sources_available"] = sources_available
    best_result["all_supplier_results"] = supplier_results

    return best_result


def search_supplier_alternatives(part_number):
    supplier_results = get_supplier_results(part_number)

    results = []

    for supplier_data in supplier_results:
        if supplier_data.get("error"):
            continue

        if supplier_data.get("manufacturer_part_number"):
            results.append(
                {
                    "Supplier": supplier_data.get("source", ""),
                    "Part Number": supplier_data.get("manufacturer_part_number", ""),
                    "Manufacturer": supplier_data.get("manufacturer", ""),
                    "Lifecycle": supplier_data.get("lifecycle_status", "Unknown"),
                    "Stock": supplier_data.get("stock_total", 0),
                    "Unit Price": supplier_data.get("unit_price", 0.0),
                    "Description": supplier_data.get("description", ""),
                    "Product URL": supplier_data.get("product_detail_url", ""),
                }
            )

    return results


def default_aggregated_result(part_number, supplier_results):
    return {
        "source": "No supplier match",
        "searched_part_number": part_number,
        "mpn": part_number,
        "manufacturer_part_number": part_number,
        "manufacturer": "",
        "description": "",
        "lifecycle_status": "Unknown",
        "stock_total": 0,
        "supplier_count": 0,
        "lead_time_weeks": None,
        "unit_price": 0.0,
        "has_alternates": False,
        "product_detail_url": "",
        "total_market_stock": 0,
        "sources_available": "",
        "all_supplier_results": supplier_results,
    }