"""Predictable BOM intake for CSV and XLSX files.

This module turns an uploaded spreadsheet into reviewable rows *before* any
analysis runs. It is deliberately conservative:

* every raw cell value is preserved next to its normalized value;
* column mapping is suggested with an explicit confidence, never silently
  guessed -- ambiguous headers stay unassigned until the user chooses;
* part number and quantity are required, manufacturer is recommended, and a
  supplier is required only for supplier-specific sourcing;
* missing, duplicate, malformed, and ambiguous values are flagged per row with
  a stable issue code, and nothing is silently discarded or defaulted.

It makes no supplier, stock, price, or lifecycle claims. It only describes what
the uploaded file says.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

from src.normalizer import normalize_part_number

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
MAX_DATA_ROWS = 50_000
MAX_COLUMNS = 200
MAX_PREVIEW_ROWS = 500
MAX_ROWS_LISTED_PER_ISSUE = 25
HEADER_SEARCH_ROWS = 10
LARGE_QUANTITY = 1_000_000

IGNORE = "ignore"
# Fields a user may correct per row before analysis.
CORRECTABLE_FIELDS = ("mpn", "quantity", "manufacturer", "supplier", "description")
MAX_CORRECTIONS = 5_000

# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------
FIELD_DEFINITIONS: dict[str, dict[str, str]] = {
    "mpn": {
        "label": "Part number (MPN)",
        "requirement": "required",
        "help": "Manufacturer part number. Required for every row.",
    },
    "quantity": {
        "label": "Quantity",
        "requirement": "required",
        "help": "Whole-number quantity per BOM line. Required for every row.",
    },
    "manufacturer": {
        "label": "Manufacturer",
        "requirement": "recommended",
        "help": "Recommended. Without it, part matching is less specific.",
    },
    "supplier": {
        "label": "Supplier",
        "requirement": "supplier_specific",
        "help": "Required only when you are sourcing from specific suppliers.",
    },
    "supplier_part_number": {
        "label": "Supplier part number",
        "requirement": "optional",
        "help": "A distributor order code or SKU. Kept for reference; never used as the MPN.",
    },
    "description": {
        "label": "Description",
        "requirement": "optional",
        "help": "Free-text part description.",
    },
    "reference_designators": {
        "label": "Reference designators",
        "requirement": "optional",
        "help": "Board references such as R1, R2. Checked against quantity when present.",
    },
    "parent_mpn": {
        "label": "Parent MPN",
        "requirement": "optional",
        "help": "Parent assembly for multi-level BOMs.",
    },
    "line_type": {
        "label": "Line type",
        "requirement": "optional",
        "help": "For example assembly or component, for multi-level BOMs.",
    },
    "bom_level": {
        "label": "BOM level",
        "requirement": "optional",
        "help": "Indent level for multi-level BOMs.",
    },
}
FIELD_ORDER = list(FIELD_DEFINITIONS)
REQUIRED_FIELDS = ["mpn", "quantity"]

# ---------------------------------------------------------------------------
# Header aliases. Keys are normalized with ``header_key``.
# "strong" aliases are specific enough to assign automatically. "weak" aliases
# are generic (for example a bare "Part Number", which is often an internal
# number or a distributor SKU) and are only used when nothing stronger exists.
# ---------------------------------------------------------------------------
_STRONG: dict[str, set[str]] = {
    "mpn": {
        "mpn",
        "mpn number",
        "manufacturer part number",
        "manufacturer part number mpn",
        "manufacturer part no",
        "manufacturer part",
        "manufacturer pn",
        "manufacturer p n",
        "manufacturers part number",
        "mfr part number",
        "mfr part no",
        "mfr part",
        "mfr pn",
        "mfr p n",
        "mfr no",
        "mfg part number",
        "mfg part no",
        "mfg part",
        "mfg pn",
        "mfg no",
        "part number mpn",
    },
    "quantity": {
        "qty",
        "quantity",
        "bom quantity",
        "bom qty",
        "order qty",
        "order quantity",
        "required qty",
        "required quantity",
        "qty per",
        "qty per parent",
        "quantity per parent",
    },
    "manufacturer": {
        "manufacturer",
        "manufacturer name",
        "component manufacturer",
        "system manufacturer",
        "mfr name",
        "mfg name",
        "mfr",
        "mfg",
        "mfr s name",
    },
    "supplier": {
        "supplier",
        "supplier name",
        "distributor",
        "distributor name",
        "preferred supplier",
        "preferred distributor",
    },
    "supplier_part_number": {
        "digi key part number",
        "digikey part number",
        "digi key pn",
        "digikey pn",
        "digi key part",
        "digikey part",
        "digi key part no",
        "dk part number",
        "mouser part number",
        "mouser part no",
        "mouser no",
        "mouser pn",
        "mouser part",
        "newark part number",
        "newark part no",
        "newark pn",
        "newark part",
        "farnell part number",
        "farnell part no",
        "farnell pn",
        "element14 part number",
        "element14 pn",
        "order code",
        "supplier part number",
        "supplier part no",
        "supplier pn",
        "distributor part number",
        "distributor part no",
        "vendor part number",
        "vendor part no",
    },
    "description": {
        "description",
        "desc",
        "part description",
        "component description",
        "component name",
        "part name",
        "product description",
        "item description",
    },
    "reference_designators": {
        "refdes",
        "ref des",
        "reference designator",
        "reference designators",
        "designator",
        "designators",
        "references",
    },
    "parent_mpn": {
        "parent mpn",
        "parent part",
        "parent part number",
        "assembly mpn",
        "parent",
    },
    "line_type": {"line type", "item type", "bom line type"},
    "bom_level": {"level", "bom level", "indent level"},
}

_WEAK: dict[str, set[str]] = {
    "mpn": {"part number", "part no", "item number", "item no"},
}

# Headers that could legitimately be more than one field. They are never
# auto-assigned; the user chooses.
_AMBIGUOUS_HEADERS: dict[str, tuple[str, ...]] = {
    "vendor": ("manufacturer", "supplier"),
    "vendor name": ("manufacturer", "supplier"),
}

_QUANTITY_HINT = re.compile(r"^(qty|quantity)\b")
_QUANTITY_NOT = re.compile(
    r"available|avail|backorder|stock|extended|ext\b|per pack|pack\b|moq|multiple|min\b|minimum"
)

_PLACEHOLDERS = {
    "",
    "n/a",
    "na",
    "n a",
    "none",
    "null",
    "nan",
    "<na>",
    "-",
    "--",
    "?",
    "tbd",
    "tba",
    "unknown",
    "dnp",
    "dnf",
}

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u2060"), None)
_KICAD_BOARDTEXT_WRAPPER = re.compile(
    r"^BoardText\(value=(?P<value>.*?),\s*position=Vector2\([^)]*\),\s*layer=.*\)$",
    re.DOTALL,
)

_DIGIKEY_SKU = re.compile(r"-ND$", re.IGNORECASE)
_SCI_NOTATION = re.compile(r"^\d+(\.\d+)?[eE][+-]?\d+$")
_USUAL_MPN_CHARS = re.compile(r"^[A-Za-z0-9 .\-_/#+,()%*:&=@\\']+$")
_INT_RE = re.compile(r"^\+?\d+$")
_DEC_RE = re.compile(r"^\+?(\d+)\.(\d+)$")
_NEG_RE = re.compile(r"^-\s*\d+(\.\d+)?$")


class BomIntakeError(ValueError):
    """Raised when a BOM cannot be read or analyzed; may carry the preview payload."""

    def __init__(
        self,
        message: str,
        preview: dict[str, Any] | None = None,
        code: str = "unreadable_file",
    ):
        super().__init__(message)
        self.preview = preview or {}
        self.code = code


# Short, value-free labels used when many rows share one issue.
_CODE_LABELS = {
    "kicad_mpn_unwrapped": "Legacy KiCad part-number wrappers were removed",
    "kicad_manufacturer_unwrapped": "Legacy KiCad manufacturer wrappers were removed",
    "missing_mpn": "Part number is blank",
    "placeholder_mpn": "Part number is a placeholder",
    "mpn_supplier_sku": "Part number looks like a Digi-Key order code",
    "mpn_numeric_conversion": "Part number may have been reformatted by a spreadsheet",
    "mpn_contains_spaces": "Part number contains spaces",
    "mpn_unusual_characters": "Part number has unusual characters or length",
    "missing_quantity": "Quantity is blank",
    "quantity_malformed": "Quantity is not a number",
    "quantity_ambiguous_format": "Quantity format is ambiguous",
    "quantity_not_whole": "Quantity is not a whole number",
    "quantity_not_positive": "Quantity is zero or negative",
    "quantity_large": "Quantity is unusually large",
    "missing_manufacturer": "Manufacturer is blank (recommended)",
    "missing_supplier": "Supplier is blank (needed for supplier-specific sourcing)",
    "duplicate_mpn": "Part appears on more than one row; quantities are combined",
    "possible_duplicate_variant": "Part may be a differently written duplicate",
    "duplicate_conflicting_manufacturer": "Duplicate rows list different manufacturers",
    "refdes_quantity_mismatch": "Reference designator count does not match quantity",
    "parent_not_in_bom": "Parent assembly is not a line in this BOM",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def clean_text(value: Any) -> str:
    """Remove invisible characters and unwrap legacy KiCad text reprs."""
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").translate(_ZERO_WIDTH)
    # Older versions of the KiCad plugin uploaded the repr() of IPC BoardText
    # objects. Recover only this exact, recognizable wrapper; arbitrary values
    # remain untouched and the intake preview records that an unwrap occurred.
    match = _KICAD_BOARDTEXT_WRAPPER.fullmatch(text.strip())
    if match:
        text = match.group("value").strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            text = text[1:-1]
    return text.strip()


def header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def _issue(code: str, severity: str, message: str, field_name: str | None = None, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if field_name:
        item["field"] = field_name
    item.update(extra)
    return item


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Reading files into a raw grid
# ---------------------------------------------------------------------------
@dataclass
class RawGrid:
    rows: list[list[str]]
    file_format: str
    encoding: str = ""
    delimiter: str = ""
    sheet: str = ""
    sheets: list[str] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)


def _decode_text(payload: bytes, notes: list[dict[str, Any]]) -> tuple[str, str]:
    try:
        return payload.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        text = payload.decode("cp1252", errors="replace")
        notes.append(
            _issue(
                "encoding_fallback",
                "warning",
                "The file is not UTF-8, so it was read as Windows-1252. "
                "Check part numbers and manufacturer names for changed special characters.",
            )
        )
        return text, "cp1252"


def _detect_delimiter(text: str) -> str:
    sample_lines = [line for line in text.splitlines()[:25] if line.strip()][:10]
    if not sample_lines:
        return ","
    best, best_score = ",", 0
    for delimiter in (",", ";", "\t", "|"):
        counts = [len(next(csv.reader([line], delimiter=delimiter), [])) for line in sample_lines]
        modal, frequency = Counter(counts).most_common(1)[0]
        if modal < 2:
            continue
        score = modal * frequency
        if score > best_score or (score == best_score and delimiter == ","):
            best, best_score = delimiter, score
    return best


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        return repr(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _read_csv_grid(payload: bytes) -> RawGrid:
    notes: list[dict[str, Any]] = []
    if b"\x00" in payload[:4096]:
        raise BomIntakeError(
            "This does not look like a text CSV file. Export the BOM as CSV or XLSX.",
            code="unsupported_file_type",
        )
    text, encoding = _decode_text(payload, notes)
    delimiter = _detect_delimiter(text)
    if delimiter != ",":
        label = {";": "semicolon", "\t": "tab", "|": "pipe"}[delimiter]
        notes.append(_issue("delimiter_detected", "info", f"Columns were split on a {label} delimiter."))
    rows: list[list[str]] = []
    for record in csv.reader(io.StringIO(text), delimiter=delimiter):
        if len(rows) > MAX_DATA_ROWS + HEADER_SEARCH_ROWS:
            raise BomIntakeError(
                f"This BOM has more than {MAX_DATA_ROWS:,} rows. Split it into smaller files."
            )
        rows.append([cell for cell in record])
    return RawGrid(rows=rows, file_format="csv", encoding=encoding, delimiter=delimiter, notes=notes)


def _read_xlsx_grid(payload: bytes) -> RawGrid:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise BomIntakeError("XLSX support is not available on this server.") from exc
    notes: list[dict[str, Any]] = []
    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many types
        raise BomIntakeError(
            "The XLSX file could not be opened. It may be corrupt or password protected."
        ) from exc
    try:
        visible = [
            ws for ws in workbook.worksheets if getattr(ws, "sheet_state", "visible") == "visible"
        ] or list(workbook.worksheets)
        chosen = None
        chosen_rows: list[list[str]] = []
        populated: list[str] = []
        for worksheet in visible:
            rows: list[list[str]] = []
            for values in worksheet.iter_rows(values_only=True):
                if len(rows) > MAX_DATA_ROWS + HEADER_SEARCH_ROWS:
                    raise BomIntakeError(
                        f"This BOM has more than {MAX_DATA_ROWS:,} rows. Split it into smaller files."
                    )
                cells = [_cell_text(value) for value in values]
                while cells and not clean_text(cells[-1]):
                    cells.pop()
                rows.append(cells)
            if any(any(clean_text(cell) for cell in row) for row in rows):
                populated.append(worksheet.title)
                if chosen is None:
                    chosen, chosen_rows = worksheet.title, rows
        sheet_names = list(workbook.sheetnames)
    finally:
        workbook.close()
    if chosen is None:
        return RawGrid(rows=[], file_format="xlsx", sheets=sheet_names, notes=notes)
    if len(populated) > 1:
        others = ", ".join(f"“{name}”" for name in populated[1:])
        notes.append(
            _issue(
                "multiple_