from integrations.supplier_aggregator import get_supplier_results, get_best_part_data

part_number = "LM555CN/NOPB"

print("ALL SUPPLIER RESULTS:")
for result in get_supplier_results(part_number):
    print(result["source"], result.get("stock_total"), result.get("error"))

print("\nBEST RESULT:")
print(get_best_part_data(part_number))