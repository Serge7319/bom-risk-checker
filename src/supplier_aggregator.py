from integrations.mouser_client import search_mouser_by_part_number
from integrations.digikey_client import search_digikey_by_part_number


def search_supplier_alternatives(part_number):
    """
    Search supplier APIs for supplier verification data.

    Current version:
    - Mouser lookup
    - DigiKey lookup
    - Returns normalized supplier intelligence
    """

    results = []

    # Mouser search
    try:
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

    except Exception as e:
        print(f"Mouser supplier lookup failed for {part_number}: {e}")

    # DigiKey search
    try:
        digikey_data = search_digikey_by_part_number(part_number)

        if digikey_data and digikey_data.get("manufacturer_part_number"):
            results.append(
                {
                    "Supplier": "DigiKey",
                    "Part Number": digikey_data.get("manufacturer_part_number", ""),
                    "Manufacturer": digikey_data.get("manufacturer", ""),
                    "Lifecycle": digikey_data.get("lifecycle_status", "Unknown"),
                    "Stock": digikey_data.get("stock_total", 0),
                    "Description": digikey_data.get("description", ""),
                    "Product URL": digikey_data.get("product_detail_url", ""),
                }
            )

    except Exception as e:
        print(f"DigiKey supplier lookup failed for {part_number}: {e}")

    return results