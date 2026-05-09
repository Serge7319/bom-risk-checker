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

    col = column_name.strip().lower()            # Normalize incoming column label before checking aliases

    column_map = {
        # Part Number
        "mpn": "mpn",
        "part number": "mpn",
        "manufacturer part number": "mpn",
        "mfr part number": "mpn",
        "manufacturer pn": "mpn",

        # Manufacturer
        "manufacturer": "manufacturer",
        "mfr": "manufacturer",
        "mfg": "manufacturer",

        # Quantity
        "qty": "quantity",
        "quantity": "quantity",

        # Description
        "description": "description",
        "desc": "description",

        # Reference Designators
        "refdes": "reference_designators",
        "reference designator": "reference_designators",
        "reference designators": "reference_designators",
    }

    return column_map.get(col, col)