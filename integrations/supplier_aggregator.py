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