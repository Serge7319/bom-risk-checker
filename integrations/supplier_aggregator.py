from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st

from integrations.mouser_client import search_mouser_by_part_number
from integrations.digikey_client import search_digikey_by_part_number

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
                "lifecycle_status": "Unknown",
                "stock_total": 0,
                "supplier_count": 0,
                "lead_time_weeks": None,
                "unit_price": 0.0,
                "has_alternates": False,
                "manufacturer": "",
                "description": "",
                "mouser_part_number": "",
                "manufacturer_part_number": "",
                "product_detail_url": "",
                "package": "",
                "pin_count": 0,
                "mounting_style": "",
            }

        result = lookup_func(part_number)

        if not result:
            return {
                "source": source_name,
                "error": f"No result from {source_name}",
                "lifecycle_status": "Unknown",
                "stock_total": 0,
                "supplier_count": 0,
                "lead_time_weeks": None,
                "unit_price": 0.0,
                "has_alternates": False,
                "manufacturer": "",
                "description": "",
                "mouser_part_number": "",
                "manufacturer_part_number": "",
                "product_detail_url": "",
                "package": "",
                "pin_count": 0,
                "mounting_style": "",
                "voltage_range": "",
                "architecture": "",
                "channel_count": 0,
                "supply_voltage_min": None,
                "supply_voltage_max": None,
            }

        result["source"] = source_name
        result.setdefault("package", "")
        result.setdefault("pin_count", 0)
        result.setdefault("mounting_style", "")
        result.setdefault("voltage_range", "")
        result.setdefault("architecture", "")
        result.setdefault("channel_count", 0)
        result.setdefault("supply_voltage_min", None)
        result.setdefault("supply_voltage_max", None)

        return result

    except Exception as error:
        print(f"{source_name} lookup failed:", error)

        return {
            "source": source_name,
            "error": str(error),
            "lifecycle_status": "Unknown",
            "stock_total": 0,
            "supplier_count": 0,
            "lead_time_weeks": None,
            "unit_price": 0.0,
            "has_alternates": False,
            "manufacturer": "",
            "description": "",
            "mouser_part_number": "",
            "manufacturer_part_number": "",
            "product_detail_url": "",
            "package": "",
            "pin_count": 0,
            "mounting_style": "",
        }


def get_supplier_results(part_number):
    suppliers = [
        ("Mouser", search_mouser_by_part_number),
        ("DigiKey", search_digikey_by_part_number),
        ("Newark", search_newark_by_part_number),
    ]

    results = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_supplier = {
            executor.submit(
                _safe_supplier_lookup,
                source_name,
                lookup_func,
                part_number,
            ): source_name
            for source_name, lookup_func in suppliers
        }

        for future in as_completed(future_to_supplier):
            results.append(future.result())

    return results


@st.cache_data(ttl=1, show_spinner=False)
def get_best_part_data(part_number: str) -> dict:
    supplier_results = get_supplier_results(part_number)
    
    valid_results = [
        result for result in supplier_results
        if not result.get("error")
        and result.get("manufacturer_part_number")
    ]

    if not valid_results:
        return default_aggregated_result(part_number, supplier_results)

    best_result = max(
        valid_results,
        key=lambda result: int(result.get("stock_total", 0) or 0),
    )

    total_market_stock = sum(
        int(result.get("stock_total", 0) or 0)
        for result in valid_results
    )

    source_names = [
        result.get("source", "")
        for result in valid_results
        if result.get("source")
    ]

    best_result["supplier_count"] = len(valid_results)
    best_result["total_market_stock"] = total_market_stock
    best_result["sources_available"] = ", ".join(source_names)
    best_result["all_supplier_results"] = supplier_results

    # Borrow missing package / pin-count / mounting-style data
    # from any other supplier that has it.
    if not best_result.get("package"):
        for result in valid_results:
            if result.get("package"):
                best_result["package"] = result.get("package")
                break

    if not best_result.get("pin_count"):
        for result in valid_results:
            if result.get("pin_count"):
                best_result["pin_count"] = result.get("pin_count")
                break

    if not best_result.get("mounting_style"):
        for result in valid_results:
            if result.get("mounting_style"):
                best_result["mounting_style"] = result.get("mounting_style")
                break

    if not best_result.get("voltage_range"):
        for result in valid_results:
            if result.get("voltage_range"):
                best_result["voltage_range"] = result.get("voltage_range")
                break

    if best_result.get("supply_voltage_min") is None:
        for result in valid_results:
            if result.get("supply_voltage_min") is not None:
                best_result["supply_voltage_min"] = result.get("supply_voltage_min")
                break

    if best_result.get("supply_voltage_max") is None:
        for result in valid_results:
            if result.get("supply_voltage_max") is not None:
                best_result["supply_voltage_max"] = result.get("supply_voltage_max")
                break

    if not best_result.get("architecture"):
        for result in valid_results:
            if result.get("architecture"):
                best_result["architecture"] = result.get("architecture")
                break

    if not best_result.get("channel_count"):
        for result in valid_results:
            if result.get("channel_count"):
                best_result["channel_count"] = result.get("channel_count")
                break

    best_result.setdefault("package", "")
    best_result.setdefault("pin_count", 0)
    best_result.setdefault("mounting_style", "")
    best_result.setdefault("voltage_range", "")
    best_result.setdefault("architecture", "")
    best_result.setdefault("channel_count", 0)
    best_result.setdefault("supply_voltage_min", None)
    best_result.setdefault("supply_voltage_max", None)

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
                    "Package": supplier_data.get("package", ""),
                    "Pin Count": supplier_data.get("pin_count", 0),
                    "Mounting Style": supplier_data.get("mounting_style", ""),
                }
            )

    return results


def default_aggregated_result(part_number: str, supplier_results: list) -> dict:
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
        "package": "",
        "pin_count": 0,
        "mounting_style": "",
        "total_market_stock": 0,
        "sources_available": "",
        "all_supplier_results": supplier_results,
        "voltage_range": "",
        "architecture": "",
        "channel_count": 0,
        "supply_voltage_min": None,
        "supply_voltage_max": None,
    }