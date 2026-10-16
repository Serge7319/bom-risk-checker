import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter


def save_results_to_csv(results: list, output_path: str) -> None:
    df = pd.DataFrame(results)
    df.to_csv(output_path, index=False)


def save_results_to_excel(
    results: list,
    output_path,
    *,
    bom_name: str = "",
    source_filename: str = "",
    analyzed_on: str = "",
) -> None:
    """Write the same evidence-aware workbook for one-time and saved reports."""
    from src.ui.detailed_risk_export import detailed_risk_excel_bytes

    records = [record for record in results if isinstance(record, dict)]
    first = records[0] if records else {}
    report_bom_name = str(bom_name or "").strip() or next(
        (
            str(first.get(key)).strip()
            for key in ("project_name", "Project Name", "BOM Name", "filename", "Filename")
            if first.get(key) not in (None, "")
        ),
        "BOM analysis",
    )
    report = detailed_risk_excel_bytes(
        records,
        bom_name=report_bom_name,
        source_filename=source_filename,
        analyzed_on=analyzed_on,
    )
    if hasattr(output_path, "write"):
        output_path.seek(0)
        output_path.truncate(0)
        output_path.write(report)
        output_path.seek(0)
        return
    with open(output_path, "wb") as target:
        target.write(report)


def format_excel_report(output_path: str) -> None:
    if hasattr(output_path, "seek"):
        output_path.seek(0)
    workbook = load_workbook(output_path)

    header_fill = PatternFill("solid", fgColor="1F2937")
    header_font = Font(color="FFFFFF", bold=True)
    high_fill = PatternFill("solid", fgColor="FECACA")
    medium_fill = PatternFill("solid", fgColor="FEF3C7")
    low_fill = PatternFill("solid", fgColor="DCFCE7")
    thin_border = Border(
        left=Side(style="thin", color="D1D5DB"),
        right=Side(style="thin", color="D1D5DB"),
        top=Side(style="thin", color="D1D5DB"),
        bottom=Side(style="thin", color="D1D5DB"),
    )

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"

        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
            cell.border = thin_border

        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.border = thin_border
                cell.alignment = Alignment(vertical="top", wrap_text=True)

        autofit_columns(sheet)

    if "Summary" in workbook.sheetnames:
        format_summary_sheet(workbook["Summary"])

    if "Detailed Results" in workbook.sheetnames:
        apply_risk_formatting(workbook["Detailed Results"], high_fill, medium_fill, low_fill)

    if "High Risk Parts" in workbook.sheetnames:
        apply_risk_formatting(workbook["High Risk Parts"], high_fill, medium_fill, low_fill)

    if hasattr(output_path, "seek"):
        output_path.seek(0)
        output_path.truncate(0)
    workbook.save(output_path)


def apply_risk_formatting(sheet, high_fill, medium_fill, low_fill):
    headers = [cell.value for cell in sheet[1]]

    if "Risk Level" not in headers:
        return

    risk_col_index = headers.index("Risk Level") + 1

    for row in sheet.iter_rows(min_row=2):
        risk_value = row[risk_col_index - 1].value

        if risk_value == "High":
            fill = high_fill
        elif risk_value == "Medium":
            fill = medium_fill
        elif risk_value == "Low":
            fill = low_fill
        else:
            continue

        for cell in row:
            cell.fill = fill


def autofit_columns(sheet):
    for column_cells in sheet.columns:
        max_length = 0
        column_letter = get_column_letter(column_cells[0].column)

        for cell in column_cells:
            value = str(cell.value) if cell.value is not None else ""
            max_length = max(max_length, len(value))

        adjusted_width = min(max_length + 2, 45)
        sheet.column_dimensions[column_letter].width = adjusted_width


def format_summary_sheet(sheet):
    """
    Makes the Summary tab look like an executive dashboard.
    """

    # Sheet title
    sheet.insert_rows(1, 2)
    sheet["A1"] = "Cadivor Report"
    sheet["A1"].font = Font(size=20, bold=True, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="111827")
    sheet["A1"].alignment = Alignment(horizontal="center")

    sheet.merge_cells("A1:B1")

    sheet["A2"] = "Executive Summary"
    sheet["A2"].font = Font(size=12, bold=True, color="374151")
    sheet["A2"].alignment = Alignment(horizontal="center")
    sheet.merge_cells("A2:B2")

    # Format key dashboard rows
    for row in range(4, sheet.max_row + 1):
        category = sheet[f"A{row}"].value

        if category == "BOM Health Score":
            sheet[f"A{row}"].font = Font(bold=True, size=14)
            sheet[f"B{row}"].font = Font(bold=True, size=18, color="2563EB")

        elif category == "Overall Status":
            sheet[f"A{row}"].font = Font(bold=True)
            sheet[f"B{row}"].font = Font(bold=True, color="FFFFFF")

            status = str(sheet[f"B{row}"].value)

            if status == "Healthy":
                sheet[f"B{row}"].fill = PatternFill("solid", fgColor="16A34A")
            elif status == "Moderate Risk":
                sheet[f"B{row}"].fill = PatternFill("solid", fgColor="F59E0B")
            elif status == "High Risk":
                sheet[f"B{row}"].fill = PatternFill("solid", fgColor="DC2626")

        elif category == "Metric":
            sheet[f"A{row}"].font = Font(bold=True, color="FFFFFF")
            sheet[f"B{row}"].font = Font(bold=True, color="FFFFFF")
            sheet[f"A{row}"].fill = PatternFill("solid", fgColor="374151")
            sheet[f"B{row}"].fill = PatternFill("solid", fgColor="374151")

        elif category == "Executive Summary":
            sheet[f"A{row}"].font = Font(bold=True, size=14, color="111827")
            sheet[f"A{row}"].fill = PatternFill("solid", fgColor="E5E7EB")
            sheet[f"B{row}"].fill = PatternFill("solid", fgColor="E5E7EB")

    # Better sizing
    sheet.column_dimensions["A"].width = 42
    sheet.column_dimensions["B"].width = 35

    for row in range(1, sheet.max_row + 1):
        sheet.row_dimensions[row].height = 24
