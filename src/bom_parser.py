import pandas as pd

from src.normalizer import normalize_column_name, normalize_part_number


REQUIRED_COLUMNS = ["mpn"]


def bom_metadata_text(*values) -> str:
    """Return the first useful BOM text value, ignoring spreadsheet nulls."""
    for value in values:
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        text = str(value or "").strip()
        if text.casefold() not in {"", "nan", "none", "null", "<na>"}:
            return text
    return ""


def load_bom(file_path: str) -> pd.DataFrame:
    """
    Loads a BOM file from CSV or Excel and returns a cleaned DataFrame.
    """

    if file_path.endswith(".csv"):
        df = pd.read_csv(file_path)

    elif file_path.endswith(".xlsx"):
        df = pd.read_excel(file_path)

    else:
        raise ValueError("Unsupported file type. Please use CSV or XLSX.")

    df = normalize_bom_columns(df)
    df = validate_bom(df)
    df = clean_bom_data(df)

    return df


def normalize_bom_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standardizes BOM column names.
    Example: 'Qty' becomes 'quantity'
    """

    normalized = pd.DataFrame(index=df.index)
    for source_column in df.columns:
        target_column = normalize_column_name(source_column)
        source_values = df[source_column]
        if target_column not in normalized:
            normalized[target_column] = source_values
            continue
        # Files sometimes include two aliases for the same field. Coalesce
        # them instead of creating duplicate labels that later become a
        # DataFrame where a Series is expected.
        existing = normalized[target_column]
        empty = existing.isna() | existing.astype(str).str.strip().str.casefold().isin(
            {"", "nan", "none", "null", "<na>"}
        )
        normalized[target_column] = existing.where(~empty, source_values)
    return normalized


def aggregate_bom_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Merge duplicate MPN rows while retaining BOM-supplied metadata.

    Quantities are summed. For fields such as manufacturer and description,
    retain the first non-empty value so the analysis still has the user's
    source metadata after duplicate line items are combined.
    """
    if df.empty or "mpn" not in df.columns:
        return df.copy()
    rows: list[dict] = []
    for _mpn, group in df.groupby("mpn", sort=False, dropna=False):
        first = group.iloc[0].to_dict()
        if "quantity" in group.columns:
            quantity_values = pd.to_numeric(group["quantity"], errors="coerce")
            # Blank/invalid duplicate quantities contribute zero, matching the
            # upload cleaner's existing treatment without erasing valid rows.
            first["quantity"] = quantity_values.fillna(0).sum()
        for column in group.columns:
            if column in {"mpn", "quantity", "mpn_normalized"}:
                continue
            values = group[column]
            value = next(
                (
                    item
                    for item in values.tolist()
                    if not pd.isna(item)
                    and str(item).strip().casefold()
                    not in {"", "nan", "none", "null", "<na>"}
                ),
                None,
            )
            first[column] = value
        rows.append(first)
    return pd.DataFrame(rows).reset_index(drop=True)


def validate_bom(df: pd.DataFrame) -> pd.DataFrame:
    """
    Checks that the BOM has the minimum required columns.
    """

    missing_columns = []

    for column in REQUIRED_COLUMNS:
        if column not in df.columns:
            missing_columns.append(column)

    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    return df


def clean_bom_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans important BOM fields before risk analysis.
    """

    df["mpn_normalized"] = df["mpn"].apply(normalize_part_number)

    if "quantity" in df.columns:
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)

    return df
