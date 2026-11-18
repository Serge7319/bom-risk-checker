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
    """Remove invisible characters and normalise non-breaking spaces."""
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").translate(_ZERO_WIDTH)
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
                "multiple_sheets",
                "warning",
                f"This workbook has {len(populated)} sheets with data. Only “{chosen}” was read; "
                f"these sheets were not used: {others}.",
            )
        )
    return RawGrid(rows=chosen_rows, file_format="xlsx", sheet=chosen, sheets=sheet_names, notes=notes)


def read_grid(filename: str, payload: bytes) -> RawGrid:
    lower = (filename or "").lower()
    is_zip = payload[:4] == b"PK\x03\x04"
    if lower.endswith(".xls") and not is_zip:
        raise BomIntakeError(
            "Legacy .xls files are not supported. Save the BOM as .xlsx or .csv.",
            code="unsupported_file_type",
        )
    if is_zip or lower.endswith((".xlsx", ".xlsm")):
        if not is_zip:
            raise BomIntakeError(
                "The file has an Excel extension but is not a valid XLSX workbook.",
                code="unsupported_file_type",
            )
        grid = _read_xlsx_grid(payload)
        if not lower.endswith((".xlsx", ".xlsm")):
            grid.notes.append(
                _issue("extension_mismatch", "info", "The file contents are an Excel workbook; it was read as XLSX.")
            )
        return grid
    if lower.endswith((".csv", ".txt", ".tsv")) or "." not in lower.rsplit("/", 1)[-1]:
        return _read_csv_grid(payload)
    raise BomIntakeError("Unsupported file type. Upload a .csv or .xlsx BOM.", code="unsupported_file_type")


# ---------------------------------------------------------------------------
# Header detection and column mapping
# ---------------------------------------------------------------------------
def _recognised_fields(key: str) -> set[str]:
    found: set[str] = set()
    for field_name, aliases in _STRONG.items():
        if key in aliases:
            found.add(field_name)
    for field_name, aliases in _WEAK.items():
        if key in aliases:
            found.add(field_name)
    if key in _AMBIGUOUS_HEADERS:
        found.update(_AMBIGUOUS_HEADERS[key])
    return found


def _locate_header_row(rows: list[list[str]]) -> int:
    """Return the header row index, scanning a few rows past title lines."""
    first = next((i for i, row in enumerate(rows) if any(clean_text(c) for c in row)), 0)
    if _recognised_fields(header_key(rows[first][0])) or any(
        _recognised_fields(header_key(cell)) for cell in rows[first]
    ):
        return first
    for index in range(first + 1, min(len(rows), first + HEADER_SEARCH_ROWS)):
        recognised = set()
        for cell in rows[index]:
            recognised |= _recognised_fields(header_key(cell))
        if len(recognised) >= 2:
            return index
    return first


SUPPLIER_PROFILES = {
    "digikey": "Digi-Key BOM export",
    "mouser": "Mouser BOM export",
    "newark": "Newark / element14 export",
}


def detect_supplier_profile(headers: list[str]) -> dict[str, Any]:
    """Recognise the shape of a distributor export. Informational only."""
    keys = [header_key(h) for h in headers]
    keyset = set(keys)
    evidence: dict[str, list[str]] = defaultdict(list)

    def hit(profile: str, key: str) -> None:
        for source, candidate in zip(headers, keys):
            if candidate == key:
                evidence[profile].append(clean_text(source))

    for key in ("digi key part number", "digikey part number", "digi key pn", "digikey pn"):
        if key in keyset:
            hit("digikey", key)
    if {"customer reference", "manufacturer part number"} <= keyset:
        hit("digikey", "customer reference")
    if "mfg std lead time" in keyset:
        hit("digikey", "mfg std lead time")
    for key in ("mouser part number", "mouser no", "mouser pn", "mouser part no"):
        if key in keyset:
            hit("mouser", key)
    for key in ("newark part number", "newark part no", "newark pn", "farnell part number", "element14 part number"):
        if key in keyset:
            hit("newark", key)
    if not evidence:
        return {"id": "generic", "label": "Generic spreadsheet", "evidence": []}
    profile = max(evidence, key=lambda p: len(evidence[p]))
    return {
        "id": profile,
        "label": SUPPLIER_PROFILES[profile],
        "evidence": sorted(set(evidence[profile])),
    }


@dataclass
class ColumnInfo:
    index: int
    source: str
    key: str
    suggested_field: str | None
    confidence: str  # recognized | supplier-export | confirm | choose | not-used
    candidates: list[str]
    note: str = ""


def _quantity_hint(key: str) -> bool:
    return bool(_QUANTITY_HINT.match(key)) and not _QUANTITY_NOT.search(key)


def suggest_mapping(
    headers: list[str],
    profile: dict[str, Any] | None = None,
    labels: list[str] | None = None,
) -> list[ColumnInfo]:
    """Suggest a field for each header without guessing between candidates.

    ``headers`` are the original header texts (used for matching); ``labels``
    are the display names, which differ only when headers are duplicated.
    """
    profile_id = (profile or {}).get("id", "generic")
    labels = labels or [clean_text(h) or "(blank header)" for h in headers]
    keys = [header_key(h) for h in headers]
    strong_cols: dict[str, list[int]] = defaultdict(list)
    weak_cols: dict[str, list[int]] = defaultdict(list)
    ambiguous_cols: dict[int, tuple[str, ...]] = {}
    for index, key in enumerate(keys):
        if not key:
            continue
        matched = False
        for field_name, aliases in _STRONG.items():
            if key in aliases:
                strong_cols[field_name].append(index)
                matched = True
        for field_name, aliases in _WEAK.items():
            if key in aliases:
                weak_cols[field_name].append(index)
                matched = True
        if key in _AMBIGUOUS_HEADERS:
            ambiguous_cols[index] = _AMBIGUOUS_HEADERS[key]
            matched = True
        if not matched and _quantity_hint(key):
            weak_cols["quantity"].append(index)

    info: dict[int, ColumnInfo] = {}

    def set_info(index: int, **kwargs: Any) -> None:
        info[index] = ColumnInfo(index=index, source=labels[index], key=keys[index], **kwargs)

    for field_name in FIELD_ORDER:
        strong = strong_cols.get(field_name, [])
        weak = weak_cols.get(field_name, [])
        label = FIELD_DEFINITIONS[field_name]["label"]
        if len(strong) == 1:
            index = strong[0]
            confidence = "supplier-export" if field_name == "supplier_part_number" and profile_id != "generic" else "recognized"
            set_info(index, suggested_field=field_name, confidence=confidence, candidates=[field_name])
            for shadowed in weak:
                if shadowed not in info:
                    set_info(
                        shadowed,
                        suggested_field=None,
                        confidence="not-used",
                        candidates=[field_name],
                        note=(
                            f"Not used for {label} because “{labels[index]}” is a more specific match. "
                            "Choose a role for this column if it matters."
                        ),
                    )
        elif len(strong) > 1:
            for index in strong:
                set_info(
                    index,
                    suggested_field=None,
                    confidence="choose",
                    candidates=[field_name],
                    note=f"Several columns could be {label}. Choose which one to use.",
                )
        elif len(weak) == 1:
            index = weak[0]
            note = (
                f"Matched {label} from a generic header. Confirm it is the manufacturer part number, "
                "not an internal number or distributor code."
                if field_name == "mpn"
                else f"Matched {label} from a loosely named header. Confirm it is the right column."
            )
            set_info(index, suggested_field=field_name, confidence="confirm", candidates=[field_name], note=note)
        elif len(weak) > 1:
            for index in weak:
                set_info(
                    index,
                    suggested_field=None,
                    confidence="choose",
                    candidates=[field_name],
                    note=f"Several columns could be {label}. Choose which one to use.",
                )
    for index, candidates in ambiguous_cols.items():
        if index in info:
            continue
        names = " or ".join(FIELD_DEFINITIONS[c]["label"].lower() for c in candidates)
        set_info(
            index,
            suggested_field=None,
            confidence="choose",
            candidates=list(candidates),
            note=f"“{labels[index]}” could be {names}. Choose which one it is.",
        )
    result: list[ColumnInfo] = []
    for index, source in enumerate(labels):
        result.append(
            info.get(
                index,
                ColumnInfo(
                    index=index,
                    source=source,
                    key=keys[index],
                    suggested_field=None,
                    confidence="not-used",
                    candidates=[],
                    note="Not recognized, so it is not used. Pick a role if it matters.",
                ),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Cell normalisation
# ---------------------------------------------------------------------------
def parse_quantity(raw: str) -> tuple[int | None, list[dict[str, Any]]]:
    """Parse a quantity without guessing. Returns (value, issues)."""
    text = clean_text(raw)
    shown = text if len(text) <= 40 else text[:37] + "…"
    if not text:
        return None, [_issue("missing_quantity", "error", "Quantity is blank.", "quantity")]
    if text.casefold() in _PLACEHOLDERS:
        return None, [
            _issue("quantity_malformed", "error", f"Quantity “{shown}” is a placeholder, not a number.", "quantity")
        ]
    if _NEG_RE.match(text):
        return None, [
            _issue("quantity_not_positive", "error", f"Quantity “{shown}” must be greater than zero.", "quantity")
        ]
    if "," in text or re.search(r"\d\s+\d", text):
        return None, [
            _issue(
                "quantity_ambiguous_format",
                "error",
                f"Quantity “{shown}” is ambiguous (thousands separator or decimal comma). "
                "Use digits only, for example 1000.",
                "quantity",
            )
        ]
    if _INT_RE.match(text):
        value = int(text.lstrip("+"))
        if value == 0:
            return None, [
                _issue("quantity_not_positive", "error", "Quantity is zero. Enter a positive whole number.", "quantity")
            ]
        issues = []
        if value > LARGE_QUANTITY:
            issues.append(
                _issue("quantity_large", "warning", f"Quantity {value:,} is unusually large. Confirm it is correct.", "quantity")
            )
        return value, issues
    decimal = _DEC_RE.match(text)
    if decimal:
        whole, fraction = decimal.group(1), decimal.group(2)
        if int(fraction) == 0:
            return int(whole), [
                _issue(
                    "quantity_decimal_whole",
                    "info",
                    f"Quantity “{shown}” was read as the whole number {int(whole)}.",
                    "quantity",
                )
            ]
        return None, [
            _issue("quantity_not_whole", "error", f"Quantity “{shown}” is not a whole number.", "quantity")
        ]
    return None, [
        _issue(
            "quantity_malformed",
            "error",
            f"Quantity “{shown}” is not a number. Remove units or text and use digits only.",
            "quantity",
        )
    ]


def _normalise_mpn(raw: str) -> tuple[str, list[dict[str, Any]]]:
    text = clean_text(raw)
    collapsed = re.sub(r"\s+", " ", text)
    issues: list[dict[str, Any]] = []
    if not collapsed:
        return "", [_issue("missing_mpn", "error", "Part number is blank.", "mpn")]
    if collapsed.casefold() in _PLACEHOLDERS:
        return "", [
            _issue(
                "placeholder_mpn",
                "error",
                f"Part number “{collapsed}” is a placeholder or do-not-populate marker, not a part number.",
                "mpn",
            )
        ]
    if raw != collapsed:
        issues.append(
            _issue("mpn_trimmed", "info", "Leading, trailing, or repeated whitespace was removed from the part number.", "mpn")
        )
    if _DIGIKEY_SKU.search(collapsed):
        issues.append(
            _issue(
                "mpn_supplier_sku",
                "warning",
                f"“{collapsed}” looks like a Digi-Key order code, not a manufacturer part number. "
                "Check that the right column is mapped to part number.",
                "mpn",
            )
        )
    if _SCI_NOTATION.match(collapsed):
        issues.append(
            _issue(
                "mpn_numeric_conversion",
                "warning",
                f"“{collapsed}” looks like a number a spreadsheet may have reformatted. Check the original value.",
                "mpn",
            )
        )
    if " " in collapsed:
        issues.append(
            _issue(
                "mpn_contains_spaces",
                "warning",
                f"Part number “{collapsed}” contains spaces. It is kept as written; confirm it is one part.",
                "mpn",
            )
        )
    if not _USUAL_MPN_CHARS.match(collapsed) or len(collapsed) > 64:
        issues.append(
            _issue(
                "mpn_unusual_characters",
                "warning",
                f"Part number “{collapsed[:40]}” has unusual characters or length. Confirm it is correct.",
                "mpn",
            )
        )
    return collapsed, issues


def _refdes_tokens(raw: str) -> list[str] | None:
    """Return designators, or None when ranges make a count unreliable."""
    text = clean_text(raw)
    if not text:
        return []
    tokens = [t for t in re.split(r"[,\s;]+", text) if t]
    if any(re.search(r"[-:~]", t) for t in tokens):
        return None
    return tokens


# ---------------------------------------------------------------------------
# Intake result
# ---------------------------------------------------------------------------
@dataclass
class IntakeRow:
    row_number: int
    cells: list[str]
    source: dict[str, str]
    raw: dict[str, str]
    normalized: dict[str, Any]
    issues: list[dict[str, Any]] = field(default_factory=list)
    excluded: bool = False
    corrections: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def has_error(self) -> bool:
        return any(i["severity"] == "error" for i in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(i["severity"] == "warning" for i in self.issues)

    @property
    def status(self) -> str:
        if self.excluded:
            return "excluded"
        if self.has_error:
            return "error"
        if self.has_warning:
            return "warning"
        return "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "status": self.status,
            "raw": self.raw,
            "normalized": self.normalized,
            "source": self.source,
            "corrections": self.corrections,
            "issues": self.issues,
        }


@dataclass
class IntakeResult:
    filename: str
    grid: RawGrid | None
    header_row: int = 0
    columns: list[ColumnInfo] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=lambda: {"id": "generic", "label": "Generic spreadsheet", "evidence": []})
    assigned: dict[int, str] = field(default_factory=dict)
    mapping_source: str = "auto"
    file_issues: list[dict[str, Any]] = field(default_factory=list)
    rows: list[IntakeRow] = field(default_factory=list)
    blank_rows_skipped: int = 0
    supplier_specific: bool = False
    default_supplier: str = ""
    exclude_invalid_rows: bool = False
    row_corrections: dict[int, dict[str, str]] = field(default_factory=dict)
    hierarchical: bool = False
    fatal: str = ""

    # -- derived views ----------------------------------------------------
    @property
    def included_rows(self) -> list[IntakeRow]:
        return [r for r in self.rows if not r.excluded and not r.has_error]

    @property
    def error_rows(self) -> list[IntakeRow]:
        return [r for r in self.rows if r.has_error]

    @property
    def file_errors(self) -> list[dict[str, Any]]:
        return [i for i in self.file_issues if i["severity"] == "error"]

    @property
    def can_analyze(self) -> bool:
        if self.fatal or self.file_errors:
            return False
        if not self.included_rows:
            return False
        if self.error_rows and not self.exclude_invalid_rows:
            return False
        return True

    def _groups(self) -> "dict[tuple[str, str], list[IntakeRow]]":
        groups: dict[tuple[str, str], list[IntakeRow]] = {}
        for row in self.included_rows:
            mpn = str(row.normalized.get("mpn") or "")
            parent = str(row.normalized.get("parent_mpn") or "") if self.hierarchical else ""
            groups.setdefault((mpn.casefold(), parent.casefold()), []).append(row)
        return groups

    def dataframe(self) -> pd.DataFrame:
        """Analysis frame built only from reviewed, included rows."""
        mapped = set(self.assigned.values())
        records: list[dict[str, Any]] = []
        for rows in self._groups().values():
            first = rows[0]
            record: dict[str, Any] = {
                "mpn": first.normalized["mpn"],
                "quantity": int(sum(int(r.normalized["quantity"]) for r in rows)),
            }
            for field_name in ("manufacturer", "description", "parent_mpn", "line_type", "bom_level"):
                if field_name in mapped:
                    record[field_name] = next(
                        (r.normalized.get(field_name) for r in rows if r.normalized.get(field_name)), ""
                    )
            if self.supplier_specific:
                record["supplier"] = next(
                    (r.normalized.get("supplier") for r in rows if r.normalized.get("supplier")), ""
                )
            if "reference_designators" in mapped:
                seen: list[str] = []
                for r in rows:
                    for token in re.split(r"[,;\s]+", str(r.normalized.get("reference_designators") or "")):
                        if token and token not in seen:
                            seen.append(token)
                record["reference_designators"] = ", ".join(seen)
            record["mpn_normalized"] = normalize_part_number(record["mpn"])
            records.append(record)
        frame = pd.DataFrame(records)
        if frame.empty:
            frame = pd.DataFrame(columns=["mpn", "quantity", "mpn_normalized"])
        return frame.reset_index(drop=True)

    def source_rows_by_part(self) -> dict[tuple[str, str], list[dict[str, Any]]]:
        out: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for key, rows in self._groups().items():
            out[key] = [
                {
                    "row_number": r.row_number,
                    "raw": r.raw,
                    "normalized": r.normalized,
                    "corrections": r.corrections,
                    "issues": [i["code"] for i in r.issues],
                }
                for r in rows
            ]
        return out

    def excluded_rows_record(self) -> list[dict[str, Any]]:
        if not self.exclude_invalid_rows:
            return []
        return [
            {
                "row_number": r.row_number,
                "raw": r.raw,
                "source": r.source,
                "reasons": [i["message"] for i in r.issues if i["severity"] == "error"],
                "codes": [i["code"] for i in r.issues if i["severity"] == "error"],
            }
            for r in self.error_rows
        ]

    def intake_record(self) -> dict[str, Any]:
        """Compact, JSON-safe provenance stored with the saved analysis."""
        return {
            "version": 1,
            "filename": self.filename,
            "format": self.grid.file_format if self.grid else "",
            "sheet": self.grid.sheet if self.grid else "",
            "header_row": self.header_row + 1,
            "supplier_profile": self.profile,
            "mapping_source": self.mapping_source,
            "mapping": [
                {
                    "index": c.index,
                    "source": c.source,
                    "field": self.assigned.get(c.index, IGNORE),
                    "confidence": "user" if self.mapping_source == "user" else c.confidence,
                }
                for c in self.columns
            ],
            "row_count": len(self.rows),
            "part_count": len(self._groups()),
            "supplier_specific": self.supplier_specific,
            "corrections": [
                {"row_number": r.row_number, "field": f, **change}
                for r in self.rows
                for f, change in r.corrections.items()
            ],
            "rows_excluded": self.excluded_rows_record(),
            "issue_summary": [
                {"code": item["code"], "severity": item["severity"], "count": item["count"]}
                for item in self.row_issue_summary()
            ]
            + [
                {"code": i["code"], "severity": i["severity"], "count": 1}
                for i in self.file_issues
            ],
        }

    # -- issue aggregation ------------------------------------------------
    def row_issue_summary(self) -> list[dict[str, Any]]:
        by_code: dict[str, dict[str, Any]] = {}
        for row in self.rows:
            for item in row.issues:
                entry = by_code.setdefault(
                    item["code"],
                    {
                        "code": item["code"],
                        "severity": item["severity"],
                        "field": item.get("field"),
                        "message": item["message"],
                        "count": 0,
                        "rows": [],
                    },
                )
                entry["count"] += 1
                if len(entry["rows"]) < MAX_ROWS_LISTED_PER_ISSUE:
                    entry["rows"].append(row.row_number)
        order = {"error": 0, "warning": 1, "info": 2}
        return sorted(by_code.values(), key=lambda e: (order.get(e["severity"], 3), -e["count"], e["code"]))

    def _issue_lines(self, severity: str) -> list[str]:
        lines = [i["message"] for i in self.file_issues if i["severity"] == severity]
        for entry in self.row_issue_summary():
            if entry["severity"] != severity:
                continue
            rows = entry["rows"]
            listed = ", ".join(str(n) for n in rows[:10])
            hidden = entry["count"] - min(len(rows), 10)
            if entry["count"] == 1:
                # A single row: the specific message already names the value.
                lines.append(f"Row {listed}: {entry['message']}")
            else:
                label = _CODE_LABELS.get(entry["code"], entry["message"])
                more = f" and {hidden} more" if hidden > 0 else ""
                lines.append(f"{label} on {entry['count']} rows (rows {listed}{more}).")
        return lines

    def counts(self) -> dict[str, int]:
        return {
            "rows_with_errors": sum(1 for r in self.rows if r.has_error),
            "rows_with_warnings": sum(1 for r in self.rows if not r.has_error and r.has_warning),
            "rows_clean": sum(1 for r in self.rows if not r.has_error and not r.has_warning),
            "rows_excluded": len(self.error_rows) if self.exclude_invalid_rows else 0,
            "file_errors": len(self.file_errors),
            "file_warnings": sum(1 for i in self.file_issues if i["severity"] == "warning"),
        }

    # -- API preview ------------------------------------------------------
    def preview(self) -> dict[str, Any]:
        columns = []
        for col in self.columns:
            samples = []
            if self.grid:
                for row in self.rows[:200]:
                    if col.index < len(row.cells) and clean_text(row.cells[col.index]):
                        samples.append(row.cells[col.index])
                    if len(samples) >= 3:
                        break
            assigned = self.assigned.get(col.index, IGNORE)
            columns.append(
                {
                    "index": col.index,
                    "source": col.source,
                    "suggested_field": col.suggested_field,
                    "assigned_field": assigned,
                    "confidence": "user" if self.mapping_source == "user" and assigned != col.suggested_field else col.confidence,
                    "candidates": col.candidates,
                    "note": col.note,
                    "sample": samples,
                }
            )
        mapped_fields = set(self.assigned.values())
        missing_required = [f for f in REQUIRED_FIELDS if f not in mapped_fields]
        flagged = [r for r in self.rows if r.has_error or r.has_warning]
        clean = [r for r in self.rows if not (r.has_error or r.has_warning)]
        shown = flagged[:MAX_PREVIEW_ROWS]
        shown += clean[: max(0, MAX_PREVIEW_ROWS - len(shown))]
        shown.sort(key=lambda r: r.row_number)
        counts = self.counts()
        groups = self._groups()
        # Parts that will be analyzed once the file is ready; while errors are
        # still open, count every row that has a usable part number so the
        # number does not silently shrink because of rows awaiting a fix.
        counted = self.included_rows if self.can_analyze else [
            r
            for r in self.rows
            if r.normalized.get("mpn") and not r.excluded
        ]
        unique_keys = {
            normalize_part_number(str(r.normalized.get("mpn") or "")) or str(r.normalized.get("mpn") or "").casefold()
            for r in counted
        }
        errors = self._issue_lines("error")
        if self.error_rows and not self.exclude_invalid_rows and not self.file_errors:
            errors.append(
                f"{len(self.error_rows)} row{'s' if len(self.error_rows) != 1 else ''} "
                "cannot be analyzed as written. Fix the file and re-upload, or choose to exclude them from this analysis."
            )
        if not errors and not self.can_analyze and not self.fatal:
            errors.append("No analyzable rows were found.")
        warnings = self._issue_lines("warning")
        return {
            "ok": self.can_analyze,
            "can_analyze": self.can_analyze,
            "filename": self.filename,
            "format": self.grid.file_format if self.grid else "",
            "sheet": self.grid.sheet if self.grid else "",
            "sheets": self.grid.sheets if self.grid else [],
            "encoding": self.grid.encoding if self.grid else "",
            "delimiter": self.grid.delimiter if self.grid else "",
            "header_row": self.header_row + 1,
            "detected_columns": [
                {"source": c["source"], "normalized": c["assigned_field"] if c["assigned_field"] != IGNORE else ""}
                for c in columns
            ],
            "columns": columns,
            "supplier_profile": self.profile,
            "fields": [{"id": name, **FIELD_DEFINITIONS[name]} for name in FIELD_ORDER],
            "applied_mapping": {str(c.index): self.assigned.get(c.index, IGNORE) for c in self.columns},
            "mapping_source": self.mapping_source,
            "required_columns": list(REQUIRED_FIELDS),
            "missing_required": missing_required,
            "row_count": len(self.rows),
            "blank_rows_skipped": self.blank_rows_skipped,
            "unique_part_count": len(unique_keys),
            "parsed_row_count": len(groups),
            "rows": [r.as_dict() for r in shown],
            "rows_total": len(self.rows),
            "rows_shown": len(shown),
            "rows_truncated": len(self.rows) > len(shown),
            "issues": self.file_issues,
            "row_issue_summary": self.row_issue_summary(),
            "counts": counts,
            "excluded_row_numbers": [r.row_number for r in self.error_rows] if self.exclude_invalid_rows else [],
            "errors": errors,
            "warnings": warnings,
            "supplier_specific": self.supplier_specific,
            "default_supplier": self.default_supplier,
            "exclude_invalid_rows": self.exclude_invalid_rows,
            "corrections_applied": sum(len(r.corrections) for r in self.rows),
            "has_hierarchy_columns": bool(self.hierarchical),
        }


# ---------------------------------------------------------------------------
# Building an IntakeResult
# ---------------------------------------------------------------------------
def _failure(filename: str, message: str, code: str = "unreadable_file") -> IntakeResult:
    result = IntakeResult(filename=filename or "bom.csv", grid=None, fatal=message)
    result.file_issues.append(_issue(code, "error", message))
    return result


def _load_corrections(result: IntakeResult, raw: dict[Any, dict[str, Any]] | None) -> None:
    if not raw:
        return
    total = 0
    for raw_row, fields in raw.items():
        try:
            number = int(raw_row)
        except (TypeError, ValueError):
            result.file_issues.append(_issue("invalid_correction", "error", f"Correction row “{raw_row}” is not a row number."))
            continue
        if not isinstance(fields, dict):
            result.file_issues.append(_issue("invalid_correction", "error", f"Corrections for row {number} are not valid."))
            continue
        for field_name, value in fields.items():
            total += 1
            if total > MAX_CORRECTIONS:
                result.file_issues.append(_issue("invalid_correction", "error", f"More than {MAX_CORRECTIONS:,} corrections were sent."))
                return
            if field_name not in CORRECTABLE_FIELDS:
                result.file_issues.append(
                    _issue("invalid_correction", "error", f"“{field_name}” cannot be corrected on row {number}.")
                )
                continue
            result.row_corrections.setdefault(number, {})[field_name] = str(value if value is not None else "")[:500]


def _unique_headers(headers: list[str]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for header in headers:
        label = clean_text(header) or "(blank header)"
        seen[label] += 1
        out.append(label if seen[label] == 1 else f"{label} ({seen[label]})")
    return out


def _apply_user_mapping(
    suggestions: list[ColumnInfo],
    user_mapping: dict[str, str] | None,
    file_issues: list[dict[str, Any]],
) -> tuple[dict[int, str], str]:
    assigned = {c.index: c.suggested_field for c in suggestions if c.suggested_field}
    if not user_mapping:
        return assigned, "auto"
    source = "user"
    for raw_index, raw_field in user_mapping.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            file_issues.append(_issue("invalid_mapping", "error", f"Column mapping key “{raw_index}” is not a column number."))
            continue
        if not 0 <= index < len(suggestions):
            file_issues.append(_issue("invalid_mapping", "error", f"Column mapping refers to column {index}, which is not in the file."))
            continue
        target = str(raw_field or "").strip() or IGNORE
        if target == IGNORE:
            assigned.pop(index, None)
            continue
        if target not in FIELD_DEFINITIONS:
            file_issues.append(_issue("invalid_mapping", "error", f"“{target}” is not a recognized column role."))
            continue
        assigned[index] = target
    return assigned, source


def _mapping_issues(
    result: IntakeResult,
    headers: list[str],
    suggestions: list[ColumnInfo],
) -> None:
    by_field: dict[str, list[int]] = defaultdict(list)
    for index, field_name in result.assigned.items():
        by_field[field_name].append(index)
    for field_name, indexes in by_field.items():
        if len(indexes) > 1:
            names = ", ".join(f"“{headers[i]}”" for i in sorted(indexes))
            result.file_issues.append(
                _issue(
                    "mapping_duplicate_field",
                    "error",
                    f"More than one column is mapped to {FIELD_DEFINITIONS[field_name]['label']}: {names}. "
                    "Choose one and set the others to “Don't use”.",
                    field_name,
                )
            )
    suggestion_by_index = {c.index: c for c in suggestions}
    for field_name in REQUIRED_FIELDS:
        if field_name in by_field:
            continue
        label = FIELD_DEFINITIONS[field_name]["label"]
        candidates = [c for c in suggestions if field_name in c.candidates and c.confidence == "choose"]
        if candidates:
            names = ", ".join(f"“{c.source}”" for c in candidates)
            result.file_issues.append(
                _issue(
                    f"mapping_ambiguous_{field_name}",
                    "error",
                    f"{label} is ambiguous: {names} could all be it. Choose one column.",
                    field_name,
                )
            )
        else:
            result.file_issues.append(
                _issue(
                    f"mapping_required_{field_name}",
                    "error",
                    f"No column is mapped to {label}. Map a column to continue.",
                    field_name,
                )
            )
    for index, field_name in result.assigned.items():
        suggestion = suggestion_by_index[index]
        if field_name == "mpn" and suggestion.suggested_field == "supplier_part_number":
            result.file_issues.append(
                _issue(
                    "mapping_supplier_column_as_mpn",
                    "warning",
                    f"“{headers[index]}” is a distributor part-number column but is mapped as the MPN. "
                    "Distributor order codes are not manufacturer part numbers.",
                    "mpn",
                )
            )
        if suggestion.confidence == "confirm" and suggestion.suggested_field == field_name and result.mapping_source == "auto":
            result.file_issues.append(
                _issue(
                    "mapping_needs_confirmation",
                    "warning",
                    f"“{headers[index]}” was mapped to {FIELD_DEFINITIONS[field_name]['label']} from a generic header. "
                    "Confirm the mapping below.",
                    field_name,
                )
            )
    for suggestion in suggestions:
        if suggestion.index in result.assigned:
            continue
        if suggestion.confidence == "choose":
            if any(f in by_field for f in suggestion.candidates):
                continue  # the user already resolved this
            if any(f in REQUIRED_FIELDS for f in suggestion.candidates):
                continue  # reported above as a required-field error
            result.file_issues.append(
                _issue(
                    "mapping_ambiguous_optional",
                    "warning",
                    suggestion.note or f"“{suggestion.source}” needs a role.",
                )
            )
        elif suggestion.confidence == "not-used" and suggestion.candidates:
            result.file_issues.append(
                _issue("mapping_column_not_used", "info", f"“{suggestion.source}”: {suggestion.note}")
            )
    if "manufacturer" not in by_field:
        result.file_issues.append(
            _issue(
                "manufacturer_column_missing",
                "warning",
                "No manufacturer column is mapped. Manufacturer is recommended; part matching will be less specific.",
                "manufacturer",
            )
        )
    if result.supplier_specific and "supplier" not in by_field and not result.default_supplier:
        result.file_issues.append(
            _issue(
                "supplier_column_required",
                "error",
                "Supplier-specific sourcing needs a supplier. Map a supplier column or enter the supplier for all rows.",
                "supplier",
            )
        )


def _build_rows(result: IntakeResult, data_rows: list[tuple[int, list[str]]], headers: list[str]) -> None:
    assigned = result.assigned
    field_columns: dict[str, int] = {}
    for index, field_name in assigned.items():
        field_columns.setdefault(field_name, index)
    for row_number, cells in data_rows:
        padded = list(cells) + [""] * (len(headers) - len(cells))
        source = {headers[i]: padded[i] for i in range(len(headers)) if clean_text(padded[i])}
        raw: dict[str, str] = {}
        normalized: dict[str, Any] = {}
        issues: list[dict[str, Any]] = []
        for field_name in FIELD_ORDER:
            index = field_columns.get(field_name)
            if index is None:
                continue
            raw[field_name] = padded[index]
        # User corrections replace the *input* to normalisation. The original
        # raw value stays on the row so both are always visible.
        values = dict(raw)
        applied: dict[str, dict[str, str]] = {}
        for field_name, corrected in result.row_corrections.get(row_number, {}).items():
            original = raw.get(field_name, "")
            if clean_text(corrected) == clean_text(original):
                continue
            values[field_name] = corrected
            applied[field_name] = {"original": original, "corrected": corrected}
            issues.append(
                _issue(
                    "value_corrected",
                    "info",
                    f"{FIELD_DEFINITIONS[field_name]['label']} was corrected by you from “{clean_text(original) or 'blank'}” "
                    f"to “{clean_text(corrected) or 'blank'}”.",
                    field_name,
                )
            )
        # part number
        if "mpn" in values:
            value, found = _normalise_mpn(values["mpn"])
            normalized["mpn"] = value
            normalized["mpn_key"] = normalize_part_number(value) if value else ""
            issues.extend(found)
        # quantity
        if "quantity" in values:
            qty, found = parse_quantity(values["quantity"])
            normalized["quantity"] = qty
            issues.extend(found)
        # manufacturer
        if "manufacturer" in values:
            manufacturer = re.sub(r"\s+", " ", clean_text(values["manufacturer"]))
            if manufacturer.casefold() in _PLACEHOLDERS:
                normalized["manufacturer"] = ""
                issues.append(
                    _issue(
                        "missing_manufacturer",
                        "warning",
                        "Manufacturer is blank or a placeholder; part matching will be less specific.",
                        "manufacturer",
                    )
                )
            else:
                normalized["manufacturer"] = manufacturer
        elif "mpn" in values:
            normalized["manufacturer"] = ""
        # supplier (required only for supplier-specific sourcing)
        supplier = re.sub(r"\s+", " ", clean_text(values.get("supplier", "")))
        if supplier.casefold() in _PLACEHOLDERS:
            supplier = ""
        if result.supplier_specific:
            if not supplier and result.default_supplier:
                normalized["supplier"] = result.default_supplier
                issues.append(
                    _issue(
                        "supplier_from_default",
                        "info",
                        f"Supplier was not in the file; “{result.default_supplier}” was entered by you for all rows.",
                        "supplier",
                    )
                )
            elif not supplier:
                normalized["supplier"] = ""
                issues.append(_issue("missing_supplier", "error", "Supplier is blank, and this BOM is for supplier-specific sourcing.", "supplier"))
            else:
                normalized["supplier"] = supplier
        elif "supplier" in values:
            normalized["supplier"] = supplier
        # passthrough text fields
        for field_name in ("supplier_part_number", "description", "parent_mpn", "line_type", "bom_level"):
            if field_name in values:
                normalized[field_name] = re.sub(r"\s+", " ", clean_text(values[field_name]))
        if "reference_designators" in values:
            normalized["reference_designators"] = re.sub(r"\s+", " ", clean_text(raw["reference_designators"]))
            tokens = _refdes_tokens(raw["reference_designators"])
            qty_value = normalized.get("quantity")
            if tokens and isinstance(qty_value, int) and len(tokens) != qty_value:
                issues.append(
                    _issue(
                        "refdes_quantity_mismatch",
                        "warning",
                        f"{len(tokens)} reference designator{'s' if len(tokens) != 1 else ''} listed but quantity is {qty_value}.",
                        "reference_designators",
                    )
                )
        result.rows.append(
            IntakeRow(
                row_number=row_number,
                cells=padded,
                source=source,
                raw=raw,
                normalized=normalized,
                issues=issues,
                corrections=applied,
            )
        )


def _flag_duplicates(result: IntakeResult) -> None:
    rows = [r for r in result.rows if r.normalized.get("mpn") and not any(i["code"] in {"missing_mpn", "placeholder_mpn"} for i in r.issues)]
    result.hierarchical = any(str(r.normalized.get("parent_mpn") or "").strip() for r in result.rows)
    exact: dict[tuple[str, str], list[IntakeRow]] = defaultdict(list)
    by_key: dict[str, list[IntakeRow]] = defaultdict(list)
    for row in rows:
        mpn = str(row.normalized["mpn"])
        parent = str(row.normalized.get("parent_mpn") or "") if result.hierarchical else ""
        exact[(mpn.casefold(), parent.casefold())].append(row)
        by_key[str(row.normalized.get("mpn_key") or mpn.casefold())].append(row)
    for group in exact.values():
        if len(group) < 2:
            continue
        numbers = [r.row_number for r in group]
        quantities = [r.normalized.get("quantity") for r in group]
        valid = [q for q in quantities if isinstance(q, int)]
        combined = f"{' + '.join(str(q) for q in valid)} = {sum(valid)}" if valid else "no valid quantities"
        if len(valid) < len(quantities):
            combined += "; rows with an unusable quantity are not counted"
        manufacturers = {
            str(r.normalized.get("manufacturer") or "").casefold()
            for r in group
            if r.normalized.get("manufacturer")
        }
        for row in group:
            others = ", ".join(str(n) for n in numbers if n != row.row_number)
            row.issues.append(
                _issue(
                    "duplicate_mpn",
                    "warning",
                    f"Part {row.normalized['mpn']} also appears on row {others}. "
                    f"Quantities are combined into one part ({combined}).",
                    "mpn",
                )
            )
            if len(manufacturers) > 1:
                row.issues.append(
                    _issue(
                        "duplicate_conflicting_manufacturer",
                        "warning",
                        f"Rows for {row.normalized['mpn']} list different manufacturers; the first non-blank one is used.",
                        "manufacturer",
                    )
                )
    for group in by_key.values():
        spellings = {str(r.normalized["mpn"]).casefold() for r in group}
        if len(spellings) < 2:
            continue
        for row in group:
            mine = str(row.normalized["mpn"]).casefold()
            others = [r for r in group if str(r.normalized["mpn"]).casefold() != mine]
            listed = ", ".join(f"{r.row_number} (“{r.normalized['mpn']}”)" for r in others[:5])
            row.issues.append(
                _issue(
                    "possible_duplicate_variant",
                    "warning",
                    f"“{row.normalized['mpn']}” may be the same part as row {listed}, written differently. "
                    "They were not combined; check which spelling is correct.",
                    "mpn",
                )
            )
    if result.hierarchical:
        known = {str(r.normalized.get("mpn_key") or "") for r in rows}
        for row in rows:
            parent = str(row.normalized.get("parent_mpn") or "").strip()
            if parent and (normalize_part_number(parent) or parent.casefold()) not in known:
                row.issues.append(
                    _issue(
                        "parent_not_in_bom",
                        "warning",
                        f"Parent {parent} is not a line in this BOM, so roll-up cannot reach it.",
                        "parent_mpn",
                    )
                )
    elif "parent_mpn" in set(result.assigned.values()):
        result.file_issues.append(
            _issue("parent_column_empty", "info", "A Parent MPN column is mapped but empty, so the BOM stays flat.", "parent_mpn")
        )


def parse_intake(
    filename: str,
    payload: bytes,
    *,
    column_mapping: dict[str, str] | None = None,
    supplier_specific: bool = False,
    default_supplier: str = "",
    exclude_invalid_rows: bool = False,
    row_corrections: dict[Any, dict[str, Any]] | None = None,
) -> IntakeResult:
    """Read, map, and normalise a BOM without analysing it.

    ``row_corrections`` maps a spreadsheet row number to ``{field: value}``;
    only the fields in ``CORRECTABLE_FIELDS`` can be corrected.
    """
    filename = filename or "bom.csv"
    if not payload:
        return _failure(filename, "Empty file", "empty_file")
    try:
        grid = read_grid(filename, payload)
    except BomIntakeError as exc:
        return _failure(filename, str(exc), exc.code)
    except Exception as exc:  # noqa: BLE001
        return _failure(filename, f"Could not read the BOM file: {exc}")
    if not any(any(clean_text(cell) for cell in row) for row in grid.rows):
        result = _failure(filename, "The file has no data. Add a header row and at least one part.", "no_data_rows")
        result.grid = grid
        return result
    header_index = _locate_header_row(grid.rows)
    raw_headers = list(grid.rows[header_index])
    body = grid.rows[header_index + 1 :]
    widest = max([len(raw_headers)] + [len(row) for row in body])
    if widest > MAX_COLUMNS:
        return _failure(filename, f"This file has more than {MAX_COLUMNS} columns. Check the delimiter or remove unused columns.")
    raw_headers = raw_headers + [""] * (widest - len(raw_headers))
    headers = _unique_headers(raw_headers)
    result = IntakeResult(
        filename=filename,
        grid=grid,
        header_row=header_index,
        supplier_specific=bool(supplier_specific),
        default_supplier=clean_text(default_supplier)[:120],
        exclude_invalid_rows=bool(exclude_invalid_rows),
    )
    _load_corrections(result, row_corrections)
    result.file_issues.extend(grid.notes)
    if header_index > 0:
        result.file_issues.append(
            _issue(
                "header_row_offset",
                "info",
                f"The header row was found on row {header_index + 1}. The {header_index} row{'s' if header_index != 1 else ''} above it were not read as data.",
            )
        )
    result.profile = detect_supplier_profile(headers)
    clean_header_counts = Counter(clean_text(h) for h in raw_headers if clean_text(h))
    for label, count in clean_header_counts.items():
        if count > 1:
            result.file_issues.append(
                _issue("duplicate_header", "warning", f"Two or more columns are named “{label}”. They are mapped by position, not by name.")
            )
    suggestions = suggest_mapping(raw_headers, result.profile, labels=headers)
    result.columns = suggestions
    result.assigned, result.mapping_source = _apply_user_mapping(suggestions, column_mapping, result.file_issues)
    _mapping_issues(result, headers, suggestions)

    data_rows: list[tuple[int, list[str]]] = []
    blank = 0
    for offset, cells in enumerate(body):
        if not any(clean_text(cell) for cell in cells):
            blank += 1
            continue
        data_rows.append((header_index + 2 + offset, cells))
    result.blank_rows_skipped = blank
    if blank:
        result.file_issues.append(
            _issue("blank_rows_skipped", "info", f"{blank} blank row{'s' if blank != 1 else ''} in the file {'were' if blank != 1 else 'was'} skipped.")
        )
    if not data_rows:
        result.file_issues.append(_issue("no_data_rows", "error", "The file has a header but no part rows."))
        return result
    if len(data_rows) > MAX_DATA_ROWS:
        return _failure(filename, f"This BOM has more than {MAX_DATA_ROWS:,} rows. Split it into smaller files.")

    unusable_mapping = any(
        i["code"] in {"invalid_mapping", "mapping_duplicate_field"} for i in result.file_issues
    )
    if unusable_mapping:
        # The mapping contradicts itself, so normalising would guess. Show raw
        # rows only so the user can correct the mapping.
        _build_rows_unmapped(result, data_rows, headers)
        return result

    known_rows = {number for number, _ in data_rows}
    for number in sorted(set(result.row_corrections) - known_rows):
        result.file_issues.append(
            _issue(
                "correction_row_not_found",
                "warning",
                f"A correction for row {number} was ignored because that row is not in the file.",
            )
        )
    _build_rows(result, data_rows, headers)
    _flag_duplicates(result)
    if result.exclude_invalid_rows:
        for row in result.error_rows:
            row.excluded = True
        if result.error_rows:
            count = len(result.error_rows)
            result.file_issues.append(
                _issue(
                    "rows_excluded",
                    "warning",
                    f"{count} row{'s' if count != 1 else ''} with errors will be left out of this analysis "
                    "and listed in the saved report.",
                )
            )
    mapped = set(result.assigned.values())
    if not result.included_rows and all(f in mapped for f in REQUIRED_FIELDS):
        result.file_issues.append(
            _issue("no_valid_rows", "error", "No rows have both a usable part number and quantity.")
        )
    return result


def _build_rows_unmapped(result: IntakeResult, data_rows: Iterable[tuple[int, list[str]]], headers: list[str]) -> None:
    """Rows for an unusable mapping: raw cells only, no normalisation or errors."""
    for row_number, cells in data_rows:
        padded = list(cells) + [""] * (len(headers) - len(cells))
        result.rows.append(
            IntakeRow(
                row_number=row_number,
                cells=padded,
                source={headers[i]: padded[i] for i in range(len(headers)) if clean_text(padded[i])},
                raw={},
                normalized={},
            )
        )
