import pandas as pd

from src.normalizer import normalize_column_name, normalize_part_number


REQUIRED_COLUMNS = ["mpn"]


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

    df = df.rename(columns=lambda col: normalize_column_name(col))

    return df


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