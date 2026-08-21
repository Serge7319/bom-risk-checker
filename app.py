from src.bom_parser import load_bom
from src.risk_engine import calculate_risk
from src.report_generator import save_results_to_csv
from src.report_generator import save_results_to_csv, save_results_to_excel
from src.cadivor_design_system import apply_cadivor_design_system

apply_cadivor_design_system()

def get_mock_part_data(row):
    """
    Temporary fake supplier/lifecycle data.
    Later, this will be replaced with real API data.
    """

    mock_database = {
        "LM555": {
            "lifecycle_status": "Active",
            "stock_total": 5000,
            "supplier_count": 5,
            "lead_time_weeks": 4,
            "has_alternates": True,
        },
        "NE555": {
            "lifecycle_status": "NRND",
            "stock_total": 75,
            "supplier_count": 2,
            "lead_time_weeks": 10,
            "has_alternates": True,
        },
        "ABC123": {
            "lifecycle_status": "Obsolete",
            "stock_total": 0,
            "supplier_count": 1,
            "lead_time_weeks": 24,
            "has_alternates": False,
        },
        "XYZ789": {
            "lifecycle_status": "Active",
            "stock_total": 20,
            "supplier_count": 1,
            "lead_time_weeks": 18,
            "has_alternates": False,
        },
    }

    part_number = row["mpn_normalized"]

    part_data = mock_database.get(part_number, {
        "lifecycle_status": "Unknown",
        "stock_total": 0,
        "supplier_count": 0,
        "lead_time_weeks": None,
        "has_alternates": False,
    })

    part_data["quantity"] = row.get("quantity", 0)

    return part_data


def main():
    bom = load_bom("data/sample_bom.csv")

    results = []

    for _, row in bom.iterrows():
        part_data = get_mock_part_data(row)
        risk_result = calculate_risk(part_data)

        results.append({
            "mpn": row["mpn"],
            "mpn_normalized": row["mpn_normalized"],
            "quantity": row.get("quantity", 0),
            "lifecycle_status": part_data["lifecycle_status"],
            "stock_total": part_data["stock_total"],
            "supplier_count": part_data["supplier_count"],
            "lead_time_weeks": part_data["lead_time_weeks"],
            "risk_score": risk_result["risk_score"],
            "risk_level": risk_result["risk_level"],
            "risk_reasons": "; ".join(risk_result["risk_reasons"]) or "No major risk found",
        })

    for result in results:
        print(result)

    save_results_to_csv(results, "reports/bom_risk_report.csv")
    print("Report saved to reports/bom_risk_report.csv")
    save_results_to_excel(results, "reports/bom_risk_report.xlsx")
    print("Excel report saved to reports/bom_risk_report.xlsx")

if __name__ == "__main__":
    main()