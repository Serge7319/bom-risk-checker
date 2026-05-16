from integrations.mouser_client import search_mouser_by_part_number


def search_supplier_alternatives(part_number):
    """
    Search supplier APIs for possible alternative parts.

    First version:
    - Looks up the selected part in Mouser
    - Returns normalized supplier intelligence
    """

    results = []

    mouser_data = search_mouser_by_part_number(part_number)

    if mouser_data and mouser_data.get("manufacturer_part_number"):
        results.append(
            {
                "Supplier": "Mouser",
                "Part Number": mouser_data.get("manufacturer_part_number", ""),
                "Manufacturer": mouser_data.get("manufacturer", ""),
                "Lifecycle": mouser_data.get("lifecycle_status", "Unknown"),
                "Stock": mouser_data.get("stock_total", 0),
                "Description": mouser_data.get("description", ""),
                "Product URL": mouser_data.get("product_detail_url", ""),
            }
        )

    return results