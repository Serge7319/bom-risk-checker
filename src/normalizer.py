import re


#Accepts a raw part number and returns cleaned standardized part number
def normalize_part_number(mpn: str) -> str:
    """
    Cleans manufacturer part numbers so they are easier to compare.

    Example:
    ' lm-7805 ' -> 'LM7805'
    """

    if not isinstance(mpn, str):                 #Protect against bad inputs like None, numbers, blanks
        return ""

    return (                                     # Standardize formatting so supplier APIs can match better
        mpn.upper()
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )


def normalize_column_name(column_name: str) -> str:
    """
    Converts messy BOM column names into standard names.
    """

    col = str(column_name or "").strip().lower()
    # Treat common punctuation and spacing variants as the same spreadsheet
    # label (for example, "Mfr. Part No." and "Manufacturer_Part_Number").
    alias_key = re.sub(r"[^a-z0-9]+", " ", col).strip()

    column_map = {
        # Part Number
        "mpn": "mpn",
        "part number": "mpn",
        "manufacturer part number": "mpn",
        "manufacturer part no": "mpn",
        "manufacturer part": "mpn",
        "manufacturer pn": "mpn",
        "manufacturer p n": "mpn",
        "mfr part number": "mpn",
        "mfr part no": "mpn",
        "mfr pn": "mpn",
        "mfr p n": "mpn",
        "mfg part number": "mpn",
        "mfg part no": "mpn",
        "mfg pn": "mpn",
        "part no": "mpn",
        "part number mpn": "mpn",
        "item number": "mpn",
        "item no": "mpn",

        # Manufacturer
        "manufacturer": "manufacturer",
        "manufacturer name": "manufacturer",
        "component manufacturer": "manufacturer",
        "system manufacturer": "manufacturer",
        "mfr name": "manufacturer",
        "mfg name": "manufacturer",
        "mfr": "manufacturer",
        "mfg": "manufacturer",

        # Quantity
        "qty": "quantity",
        "quantity": "quantity",
        "bom quantity": "quantity",

        # Description
        "description": "description",
        "desc": "description",
        "part description": "description",
        "component description": "description",
        "component name": "description",
        "part name": "description",
        "product description": "description",
        "item description": "description",

        # Reference Designators
        "refdes": "reference_designators",
        "reference designator": "reference_designators",
        "reference designators": "reference_designators",
    }

    return column_map.get(alias_key, col)
