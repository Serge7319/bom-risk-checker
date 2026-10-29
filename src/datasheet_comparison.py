"""Evidence-led datasheet comparison for Alternative Finder.

The module is deliberately conservative: a matching catalog field is useful
evidence, but is never an automatic approval. Datasheet PDFs are fetched from
validated public HTTPS links or uploaded by the reviewer, parsed on demand, and the UI shows
when a value is unavailable rather than inventing a comparison.

Family field matrices, DigiKey aliases, and comparison modes come from
``src.component_family_profiles`` so every family shares one declarative
registry across normalization, scoring, UI, and PDF output. User-provided PDF
uploads are parsed in the reviewer session.
"""
from __future__ import annotations

from html.parser import HTMLParser
from io import BytesIO
import ipaddress
import re
import socket
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests

from src.component_family_profiles import (
    PASSIVE_FAMILY_IDS,
    comparison_fields,
    get_family_profile,
    infer_family_id,
    legacy_family_fields,
    pdf_label_aliases,
)
from src.parametric_compare import (
    compare_field_values,
    engineering_confidence_from_rows,
    normalize_mounting_style,
)


MAX_DATASHEET_BYTES = 8 * 1024 * 1024
MAX_DATASHEET_PAGES = 40
MAX_DATASHEET_REDIRECTS = 5
MAX_DATASHEET_PAGE_BYTES = 2 * 1024 * 1024
MAX_DATASHEET_URL_ATTEMPTS = 4

USER_FACING_COMPARISON_COLUMNS = (
    "Attribute",
    "Original",
    "Candidate",
    "Result",
    "Evidence",
)
INTERNAL_COMPARISON_METADATA_COLUMNS = (
    "Key",
    "Required",
    "CompareMode",
    "ValueRole",
)


def user_may_view_comparison_diagnostics(
    *,
    role: str | None = None,
    is_admin: bool = False,
) -> bool:
    """Server-side guard: developer comparison diagnostics are admin-only.

    Non-admin roles must never receive the expander, metadata columns, or
    diagnostic table in the rendered page tree.
    """
    if bool(is_admin):
        return True
    return str(role or "").strip().casefold() == "admin"

# Back-compat exports used across the Alternative Finder stack.
PASSIVE_FAMILIES = PASSIVE_FAMILY_IDS
COMMON_FIELDS = (
    ("Package", "package"),
    ("Pin count", "pin_count"),
    ("Mounting", "mounting_style"),
    ("Supply voltage", "voltage_range"),
)
FAMILY_FIELDS = legacy_family_fields()
PDF_LABEL_ALIASES = pdf_label_aliases()

PASSIVE_PARAMETRIC_KEYS = (
    "capacitance",
    "resistance",
    "inductance",
    "tolerance",
    "rated_voltage",
    "dielectric",
    "power_rating",
    "temperature_coefficient",
    "esr",
    "dcr",
    "rated_current",
    "saturation_current",
    "mounting_style",
    "package",
    "device_type",
    "collector_emitter_voltage",
    "collector_current",
    "dc_current_gain",
    "power_dissipation",
    "transition_frequency",
    "vce_saturation",
    "drain_source_voltage",
    "continuous_drain_current",
    "rds_on",
    "gate_threshold",
    "reverse_voltage",
    "forward_current",
    "forward_voltage",
    "output_voltage",
    "dropout_voltage",
    "pinout",
    "temperature_range",
    "polarity",
    "ripple_current",
    "srf",
    "shielding",
    "positions",
    "pitch",
    "mating_style",
    "coil_voltage",
    "logic_resources",
    "memory_size",
    "io_count",
    "peripherals",
    "interface",
    "measurement_range",
    "accuracy",
    "frequency_tolerance",
    "load_capacitance",
    "recovery_time",
    "gate_charge",
    "thermal_resistance",
    "switching_frequency",
    "collector_base_voltage",
    "collector_cutoff_current",
)


def infer_component_family(part: dict) -> str:
    return infer_family_id(part)


def family_for_datasheet_review(part: Mapping[str, Any] | None, *documents: Mapping[str, Any]) -> str:
    """Use the part record first, then extracted datasheet text if the record is general.

    Datasheet wording can identify a rheostat when the catalog description does not.
    It never replaces a family that was already identified from the part record.
    """
    identified = infer_component_family(dict(part or {}))
    if identified != "General electronic component":
        return identified
    excerpts: list[str] = []
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        for page in document.get("pages") or []:
            if isinstance(page, Mapping):
                excerpts.append(str(page.get("text") or "")[:2000])
    if not excerpts:
        return identified
    enriched = dict(part or {})
    enriched["description"] = f"{enriched.get('description') or ''} {' '.join(excerpts)}".strip()
    return infer_component_family(enriched)


_NOT_STATED = "Not stated in retrieved evidence"
_CATALOG_SOURCE = " Supplier listings are used where available; no manufacturer document is cited."


def _display_value(value) -> str:
    if value is None or str(value).strip() in {"", "None", "Unknown", "nan"}:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).strip()


def _lifecycle_record_text(part: Mapping[str, Any]) -> str:
    evidence = part.get("lifecycle_evidence") or []
    if not isinstance(evidence, list):
        return ""
    bits = []
    for row in evidence:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "Supplier").strip() or "Supplier"
        status = str(row.get("status") or row.get("normalized_status") or "status not recorded").strip()
        when = str(row.get("retrieved_at") or "time not recorded").strip()
        bits.append(f"{source}: {status} ({when})")
    return "; ".join(bits)


def _lifecycle_is_conflict(part: Mapping[str, Any], value: str) -> bool:
    return bool(part.get("lifecycle_conflict")) or value.casefold() == "conflicting supplier data"


def mpn_search_plan(raw_mpn: str) -> dict[str, Any]:
    """Search aliases for an exact entered MPN.

    Punctuation may be ignored while searching. The raw identifier is kept,
    and a suffix is never removed, so RES10K does not become RES10KE.
    """
    raw = str(raw_mpn or "").strip()
    normalized = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    aliases: list[str] = []
    hyphenated = re.sub(r"^([A-Z]+)(\d)", r"\1-\2", normalized)
    if hyphenated and hyphenated != normalized and hyphenated != raw.upper():
        aliases.append(hyphenated)
    return {
        "raw": raw,
        "normalized": normalized,
        "search_aliases": aliases,
        "identity_preserved": True,
    }


_BLANK_COMPARE_VALUES = {
    "",
    "not stated in retrieved evidence",
    "not stated in this datasheet",
    "not available",
    "not found",
    "not recorded",
    "n/a",
    "none",
    "nan",
    "unknown",
    "—",
    "-",
    "–",
}


def cited_compare_value(value: object) -> str:
    """Return a comparison value only when it is an actual recorded value."""
    text = str(value or "").strip()
    if text.casefold() in _BLANK_COMPARE_VALUES:
        return ""
    return text


def verify_datasheet_identity(
    document: Mapping[str, Any] | None,
    *,
    manufacturer: str = "",
    mpn: str = "",
) -> dict[str, Any]:
    """Accept datasheet values only when the text names this manufacturer and MPN."""
    data = dict(document or {})
    attached = bool(data)
    pages = data.get("pages") or []
    manufacturer_text = str(manufacturer or "").strip()
    mpn_text = str(mpn or "").strip()
    if not attached:
        return {
            "attached": False,
            "verified": False,
            "mpn_verified": False,
            "manufacturer_verified": False,
            "reason": "No datasheet was attached for this part.",
        }
    if not pages:
        return {
            "attached": True,
            "verified": False,
            "mpn_verified": False,
            "manufacturer_verified": False,
            "reason": str(data.get("reason") or "The datasheet has no extractable text. OCR is not supported."),
        }
    mpn_verified = bool(mpn_text) and _pdf_mentions_exact_part(data, mpn_text)
    manufacturer_verified = True
    if manufacturer_text:
        manufacturer_verified = _pdf_mentions_exact_part(data, manufacturer_text)
    if not mpn_text:
        reason = "No manufacturer part number was available to verify this datasheet."
    elif not mpn_verified:
        reason = f"The extracted text does not name the exact MPN {mpn_text}."
    elif manufacturer_text and not manufacturer_verified:
        reason = f"The extracted text does not name the manufacturer {manufacturer_text}."
    else:
        named = f"{manufacturer_text} {mpn_text}".strip()
        reason = f"Extracted text names {named}."
    return {
        "attached": True,
        "verified": bool(mpn_verified and manufacturer_verified),
        "mpn_verified": mpn_verified,
        "manufacturer_verified": manufacturer_verified,
        "reason": reason,
    }


def _review_warning_for_unstated(labels: list[str], *, datasheets_verified: bool) -> str:
    if len(labels) == 1:
        named = labels[0]
    elif len(labels) == 2:
        named = f"{labels[0]} and {labels[1]}"
    else:
        named = ", ".join(labels[:-1]) + ", and " + labels[-1]
    source = "the verified datasheet" if datasheets_verified else "the retrieved evidence"
    verb = "is" if len(labels) == 1 else "are"
    return (
        f"Drop-in fit is unverified: {named} {verb} not stated in {source}. "
        "Those values were not inferred."
    )


def _evidence_source_label(document: Mapping[str, Any] | None) -> str:
    data = dict(document or {})
    source_type = str(data.get("source_type") or "").casefold()
    if source_type in {"manufacturer_product_page", "manufacturer_catalog_path"}:
        return "manufacturer product page"
    if source_type.endswith("_authorized_product_page"):
        name = str(data.get("source_name") or "").strip()
        return f"{name} product page" if name else "supplier product page"
    if source_type in {"manufacturer_pdf", "datasheet_pdf", "uploaded_datasheet"}:
        return "datasheet" if source_type != "uploaded_datasheet" else "uploaded datasheet"
    if "authorized_distributor_api" in source_type:
        name = str(data.get("source_name") or "supplier").strip()
        supplier = name.split()[0] if name else "Supplier"
        return f"{supplier} product record"
    method = str(data.get("extraction_method") or "").casefold()
    if method in {"native_pdf_text", "native pdf text", ""} and data.get("pages"):
        # Attached PDF fixtures and legacy documents default to datasheet wording.
        if "product" not in str(data.get("source_name") or "").casefold():
            return "datasheet"
    name = str(data.get("source_name") or "").strip()
    if "api" in name.casefold():
        supplier = name.split()[0] if name else "Supplier"
        return f"{supplier} product record"
    return name or "datasheet"


def _evidence_extraction_method(document: Mapping[str, Any] | None) -> str:
    data = dict(document or {})
    method = str(data.get("extraction_method") or "").strip()
    if method == "manufacturer_product_html":
        return "manufacturer product HTML"
    if method == "authorized_distributor_product_html":
        return "authorized distributor product HTML"
    if method:
        return method.replace("_", " ")
    source_type = str(data.get("source_type") or "").casefold()
    if source_type.endswith("_authorized_product_page"):
        return "authorized distributor product HTML"
    if "product" in source_type:
        return "manufacturer product HTML"
    return "native PDF text"


def merge_verified_datasheet_rows(
    rows: list[dict],
    *,
    family: str,
    document_a: Mapping[str, Any] | None,
    document_b: Mapping[str, Any] | None,
    manufacturer_a: str = "",
    manufacturer_b: str = "",
    mpn_a: str = "",
    mpn_b: str = "",
) -> tuple[list[dict], dict[str, Any], list[str]]:
    """Fill comparison cells from page-cited datasheet text after an identity check.

    A value from one part is never copied onto the other. A document that does
    not name the entered manufacturer and exact MPN contributes no values.
    """
    identity = {
        "part_a": verify_datasheet_identity(document_a, manufacturer=manufacturer_a, mpn=mpn_a),
        "part_b": verify_datasheet_identity(document_b, manufacturer=manufacturer_b, mpn=mpn_b),
    }
    if document_a is None and document_b is None:
        return list(rows or []), identity, []

    profile = get_family_profile(family)
    specs = {spec.key: spec for spec in comparison_fields(profile)}
    pdf_rows: list[dict] = []
    if identity["part_a"]["verified"] or identity["part_b"]["verified"]:
        pdf_rows = build_pdf_field_evidence(
            dict(document_a or {"pages": []}),
            dict(document_b or {"pages": []}),
            family,
            original_mpn=mpn_a if identity["part_a"]["verified"] else "",
            candidate_mpn=mpn_b if identity["part_b"]["verified"] else "",
        )
    pdf_by_key = {str(row.get("Key") or ""): row for row in pdf_rows if isinstance(row, dict)}
    label_a = _evidence_source_label(document_a)
    label_b = _evidence_source_label(document_b)
    def _citation_note(side: str, *, label: str, page: str, excerpt: str) -> str:
        page_text = str(page or "").strip()
        if "api" in page_text.casefold():
            page_text = ""
        if re.fullmatch(r"\d+", page_text):
            citation = f"{label}, p. {page_text}"
        elif re.search(r"\bp\.\s*\d+", page_text, flags=re.IGNORECASE):
            citation = page_text
        elif page_text and page_text.casefold() not in {"product page", "listing", "record"}:
            citation = f"{label}, {page_text}"
        else:
            citation = label
        note = f"{side}: {citation}"
        excerpt_text = " ".join(str(excerpt or "").split())
        if excerpt_text:
            note += f" — “{excerpt_text[:280]}”"
        return note + "."

    def _identity_gap(identity_row: Mapping[str, Any], *, manufacturer: str, mpn: str) -> str:
        if not identity_row.get("mpn_verified"):
            return f"The document does not name the exact part number {mpn}."
        if manufacturer and not identity_row.get("manufacturer_verified"):
            return f"The document does not name {manufacturer}."
        return "The document could not be verified for this part."

    merged: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        current = dict(row)
        spec = specs.get(str(current.get("Key") or ""))
        pdf = pdf_by_key.get(str(current.get("Key") or "")) or {}
        catalog_a = cited_compare_value(current.get("Original"))
        catalog_b = cited_compare_value(current.get("Candidate"))
        pdf_a = cited_compare_value(pdf.get("Original PDF value")) if identity["part_a"]["verified"] else ""
        pdf_b = cited_compare_value(pdf.get("Candidate PDF value")) if identity["part_b"]["verified"] else ""
        page_a = str(pdf.get("Original PDF page") or "").strip() if pdf_a else ""
        page_b = str(pdf.get("Candidate PDF page") or "").strip() if pdf_b else ""
        excerpt_a = str(pdf.get("Original PDF evidence") or "").strip() if pdf_a else ""
        excerpt_b = str(pdf.get("Candidate PDF evidence") or "").strip() if pdf_b else ""
        if page_a.casefold() in _BLANK_COMPARE_VALUES:
            page_a = ""
            pdf_a = ""
        if page_b.casefold() in _BLANK_COMPARE_VALUES:
            page_b = ""
            pdf_b = ""

        notes: list[str] = []
        conflict = False
        display_a = catalog_a
        display_b = catalog_b
        source_a = "catalog" if catalog_a else "none"
        source_b = "catalog" if catalog_b else "none"
        if pdf_a:
            display_a = pdf_a
            source_a = "evidence"
            notes.append(
                _citation_note(
                    "Part A",
                    label=label_a,
                    page=page_a,
                    excerpt=excerpt_a,
                )
            )
            if catalog_a and spec is not None:
                side_status, _side_note = compare_field_values(pdf_a, catalog_a, spec)
                if side_status == "Different":
                    conflict = True
                    notes.append(f"Supplier listing also reports {catalog_a}; it differs from the cited document.")
            elif catalog_a:
                notes.append(f"Supplier listing also reports {catalog_a}.")
        elif identity["part_a"]["attached"] and identity["part_a"]["verified"]:
            notes.append(f"Part A: {label_a} does not list this field.")
            if catalog_a:
                notes.append(f"Supplier listing reports {catalog_a}; the document does not confirm it.")
        elif identity["part_a"]["attached"]:
            notes.append(
                f"Part A: {_identity_gap(identity['part_a'], manufacturer=manufacturer_a, mpn=mpn_a)}"
            )
        elif catalog_a:
            notes.append(f"Part A: supplier listing reports {catalog_a}; no manufacturer document is cited.")

        if pdf_b:
            display_b = pdf_b
            source_b = "evidence"
            notes.append(
                _citation_note(
                    "Part B",
                    label=label_b,
                    page=page_b,
                    excerpt=excerpt_b,
                )
            )
            if catalog_b and spec is not None:
                side_status, _side_note = compare_field_values(pdf_b, catalog_b, spec)
                if side_status == "Different":
                    conflict = True
                    notes.append(f"Supplier listing also reports {catalog_b}; it differs from the cited document.")
            elif catalog_b:
                notes.append(f"Supplier listing also reports {catalog_b}.")
        elif identity["part_b"]["attached"] and identity["part_b"]["verified"]:
            notes.append(f"Part B: {label_b} does not list this field.")
            if catalog_b:
                notes.append(f"Supplier listing reports {catalog_b}; the document does not confirm it.")
        elif identity["part_b"]["attached"]:
            notes.append(
                f"Part B: {_identity_gap(identity['part_b'], manufacturer=manufacturer_b, mpn=mpn_b)}"
            )
        elif catalog_b:
            notes.append(f"Part B: supplier listing reports {catalog_b}; no manufacturer document is cited.")

        if spec is not None:
            status, compare_note = compare_field_values(display_a, display_b, spec)
        else:
            status = str(current.get("Status") or "Needs data")
            compare_note = str(current.get("Evidence") or "")
        if conflict:
            status = "Different"
        if not notes:
            notes.append(compare_note)
        blank_a = (
            f"Not stated in this {label_a}"
            if identity["part_a"]["verified"]
            else _NOT_STATED
        )
        blank_b = (
            f"Not stated in this {label_b}"
            if identity["part_b"]["verified"]
            else _NOT_STATED
        )
        current["Original"] = display_a or blank_a
        current["Candidate"] = display_b or blank_b
        current["OriginalSource"] = source_a if display_a else "none"
        current["CandidateSource"] = source_b if display_b else "none"
        current["Status"] = status
        current["Evidence"] = " ".join(notes)
        merged.append(current)

    warnings: list[str] = []
    for side, label in (("part_a", "Part A"), ("part_b", "Part B")):
        if identity[side]["attached"] and not identity[side]["verified"]:
            warnings.append(f"{label}: {identity[side]['reason']}")
    unstated = [str(row.get("Attribute") or "") for row in merged if row.get("Status") == "Needs data"]
    unstated = [label for label in unstated if label]
    if unstated:
        warnings.append(
            _review_warning_for_unstated(
                unstated,
                datasheets_verified=bool(identity["part_a"]["verified"] or identity["part_b"]["verified"]),
            )
        )
    return merged, identity, warnings


def classify_distributor_cross_reference(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep a distributor substitute claim separate from a fit decision."""
    data = dict(record or {})
    return {
        "kind": "distributor_cross_reference",
        "source": str(data.get("source") or "").strip(),
        "relationship": str(data.get("relationship") or "").strip(),
        "retrieved_at": str(data.get("retrieved_at") or "").strip(),
        "manufacturer_approval": False,
        "drop_in_verified": False,
        "note": (
            "A distributor cross-reference is not manufacturer approval "
            "and is not a verified drop-in fit."
        ),
    }


def datasheet_extraction_summary(document: Mapping[str, Any] | None) -> str:
    """Describe what was actually extracted, including any page limit."""
    data = dict(document or {})
    if not data.get("available"):
        reason = str(
            data.get("reason")
            or "No readable PDF text was extracted. Open the linked PDF and review its drawings directly."
        )
        if data.get("page_cap_applied"):
            examined = int(data.get("pages_examined") or MAX_DATASHEET_PAGES)
            document_pages = int(data.get("document_page_count") or examined)
            reason = (
                f"{reason} Only the first {examined} of {document_pages} pages were examined "
                f"(limit {MAX_DATASHEET_PAGES}). This is not a full-document search."
            )
        return reason
    text_pages = int(data.get("text_page_count") or data.get("page_count") or 0)
    sentences = [f"Readable text extracted from {text_pages} PDF page(s)."]
    document_pages = data.get("document_page_count")
    if document_pages not in (None, "") and int(document_pages) != text_pages:
        sentences.append(f"The PDF has {int(document_pages)} page(s).")
    if data.get("page_cap_applied"):
        examined = int(data.get("pages_examined") or MAX_DATASHEET_PAGES)
        sentences.append(
            f"Only the first {examined} pages were examined "
            f"(limit {MAX_DATASHEET_PAGES}). This is not a full-document search."
        )
    if data.get("text_truncated"):
        sentences.append("Some page text was truncated at 5,000 characters.")
    image_only = int(data.get("image_only_page_count") or 0)
    if image_only:
        sentences.append(
            f"{image_only} examined page(s) had no extractable text. OCR is not supported."
        )
    sentences.append("Extraction method: native PDF text. OCR is not supported.")
    return " ".join(sentences)


def _display_pin_count(part: dict) -> str:
    from integrations.pin_count import effective_footprint_pad_count

    count = effective_footprint_pad_count(part)
    return str(count) if count > 0 else ""


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9.+-]", "", value.casefold())


def _field_status(original_value: str, candidate_value: str, *, attribute: str = "") -> tuple[str, str]:
    """Legacy helper retained for PDF text-line compares without FieldSpec."""
    if not original_value or not candidate_value:
        return "Needs data", "One or both values were not available from the retrieved evidence."
    if attribute == "Mounting":
        original_norm = normalize_mounting_style(original_value)
        candidate_norm = normalize_mounting_style(candidate_value)
        if original_norm and candidate_norm:
            if original_norm == candidate_norm:
                return "Match", "The retrieved mounting styles are equivalent for surface-mount comparison."
            return "Different", "The retrieved mounting styles differ; engineer review is required."
    if _normalize(original_value) == _normalize(candidate_value):
        return "Match", "The retrieved values match exactly."
    return "Different", "The retrieved values differ; engineer review is required."


def build_datasheet_comparison(original: dict, candidate: dict) -> dict:
    """Build a transparent family-aware comparison from retrieved evidence."""
    family = infer_component_family(original)
    profile = get_family_profile(family)
    fields = comparison_fields(profile)
    rows, counts = [], {"Match": 0, "Different": 0, "Needs data": 0}
    for spec in fields:
        if spec.key == "pin_count":
            original_value = _display_pin_count(original)
            candidate_value = _display_pin_count(candidate)
        else:
            original_value = _display_value(original.get(spec.key))
            candidate_value = _display_value(candidate.get(spec.key))
        original_conflict = spec.key == "lifecycle_status" and _lifecycle_is_conflict(original, original_value)
        candidate_conflict = spec.key == "lifecycle_status" and _lifecycle_is_conflict(candidate, candidate_value)
        if original_conflict:
            original_value = _lifecycle_record_text(original)
        if candidate_conflict:
            candidate_value = _lifecycle_record_text(candidate)
        status, note = compare_field_values(original_value, candidate_value, spec)
        if original_conflict or candidate_conflict:
            status = "Different"
            if original_value or candidate_value:
                note = (
                    "Conflicting supplier records are listed in the value cells with source and time. "
                    "They are not a single lifecycle status."
                )
            else:
                original_value = original_value or "Lifecycle conflict — underlying supplier records were not retained"
                candidate_value = candidate_value or "Lifecycle conflict — underlying supplier records were not retained"
                note = (
                    "A lifecycle conflict was reported, but the individual supplier records were not retained."
                )
        note = f"{note}{_CATALOG_SOURCE}"
        counts[status] += 1
        rows.append({
            "Attribute": spec.label,
            "Key": spec.key,
            "Required": bool(spec.required),
            "CompareMode": spec.compare,
            "ValueRole": spec.value_role,
            "Original": original_value or _NOT_STATED,
            "Candidate": candidate_value or _NOT_STATED,
            "Status": status,
            "Evidence": note,
        })
    return {
        "family": family,
        "family_display_name": profile.display_name,
        "scoring_mode": profile.scoring_mode,
        "requires_pinout_for_dropin": profile.requires_pinout_for_dropin,
        "rows": rows,
        "counts": counts,
    }


def user_facing_comparison_rows(rows: list | None) -> list[dict]:
    """Project comparison rows to the standard end-user column set.

    Internal schema metadata (Key / Required / CompareMode / ValueRole) is
    omitted. Status is exposed as Result for the user-facing table.
    """
    projected: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        projected.append(
            {
                "Attribute": row.get("Attribute", ""),
                "Original": row.get("Original", ""),
                "Candidate": row.get(
                    "Candidate",
                    row.get("Selected Alternative", ""),
                ),
                "Result": row.get("Result", row.get("Status", "")),
                "Evidence": row.get("Evidence", ""),
            }
        )
    return projected


def user_facing_pdf_evidence_rows(rows: list | None) -> list[dict]:
    """Project PDF evidence rows without internal Key/Required metadata."""
    projected: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        projected.append(
            {
                "Attribute": row.get("Attribute", ""),
                "Original": row.get("Original PDF evidence", row.get("Original", "")),
                "Candidate": row.get(
                    "Candidate PDF evidence",
                    row.get("Candidate", ""),
                ),
                "Result": row.get("Result", row.get("Status", "")),
                "Evidence": row.get("Evidence", ""),
                "Source pages": row.get("Source pages", ""),
            }
        )
    return projected


def diagnostic_comparison_rows(rows: list | None) -> list[dict]:
    """Full comparison rows including internal schema metadata for admins."""
    return [dict(row) for row in (rows or []) if isinstance(row, dict)]


def build_engineering_evidence_assessment(
    counts: Mapping[str, Any],
    *,
    classification: str = "",
    substitute_type: str = "",
    supplier_relationship_evidence: list | None = None,
    evidence_source: str = "",
    comparison_rows: list | None = None,
    family: str = "",
) -> dict:
    """Summarize engineering comparison coverage separately from supplier classification."""
    profile = get_family_profile(family) if family else None
    if comparison_rows:
        base = engineering_confidence_from_rows(
            list(comparison_rows),
            requires_pinout_for_dropin=bool(profile.requires_pinout_for_dropin) if profile else False,
        )
        matches = base["matches"]
        differences = base["differences"]
        needs_data = base["needs_data"]
        compared_fields = base["compared_fields"]
        status = base["engineering_evidence_status"]
        summary = base["engineering_evidence_summary"]
        coverage_percent = base["engineering_coverage_percent"]
        engineering_confidence = base["engineering_comparison_confidence"]
    else:
        matches = max(0, int(counts.get("Match", 0) or 0))
        differences = max(0, int(counts.get("Different", 0) or 0))
        needs_data = max(0, int(counts.get("Needs data", 0) or 0))
        compared_fields = matches + differences + needs_data

        if differences > 0:
            status = "conflicts documented"
        elif compared_fields == 0:
            status = "incomplete"
        elif needs_data == 0 and matches > 0:
            status = "complete"
        elif matches <= 1 and needs_data >= 5:
            status = "incomplete"
        elif matches >= max(1, compared_fields - 1):
            status = "substantial"
        else:
            status = "partial"

        match_label = "match" if matches == 1 else "matches"
        field_label = "field" if needs_data == 1 else "fields"
        summary = (
            f"Engineering evidence: {status} — {matches} confirmed {match_label}, "
            f"{needs_data} {field_label} need verification"
        )
        coverage_percent = round((matches / compared_fields) * 100) if compared_fields else 0

        if differences > 0:
            engineering_confidence = max(5, 55 - differences * 18)
        elif compared_fields == 0:
            engineering_confidence = 30
        else:
            coverage_ratio = matches / compared_fields
            engineering_confidence = round(35 + coverage_ratio * 58)
            if (
                needs_data <= 1
                and matches >= max(1, compared_fields - 1)
                and differences == 0
            ):
                engineering_confidence = min(95, engineering_confidence + 6)
        engineering_confidence = max(0, min(100, engineering_confidence))

    from src.alternative_classification import (
        CLASS_SUPPLIER_SIMILAR,
        CLASS_SUPPLIER_UPGRADE,
        CLASS_VERIFIED_DIRECT,
        SUBSTITUTE_TYPE_DIRECT,
        SUBSTITUTE_TYPE_SIMILAR,
        SUBSTITUTE_TYPE_UPGRADE,
        normalize_substitute_type,
        relationship_evidence_summary,
    )

    evidence_rows = [
        row for row in (supplier_relationship_evidence or []) if isinstance(row, dict)
    ]
    normalized_type = normalize_substitute_type(substitute_type)
    supplier_relationship_confidence = 0
    if evidence_rows:
        supplier_relationship_summary = relationship_evidence_summary(evidence_rows)
        digikey_direct = any(
            str(row.get("supplier") or "").casefold() == "digikey"
            and normalize_substitute_type(row.get("substitute_type")) == SUBSTITUTE_TYPE_DIRECT
            for row in evidence_rows
        )
        if digikey_direct and classification == CLASS_VERIFIED_DIRECT:
            supplier_relationship_confidence = 95
        elif classification == CLASS_VERIFIED_DIRECT:
            supplier_relationship_confidence = 90
        elif classification == CLASS_SUPPLIER_UPGRADE or normalized_type == SUBSTITUTE_TYPE_UPGRADE:
            supplier_relationship_confidence = 70
        elif classification == CLASS_SUPPLIER_SIMILAR or normalized_type == SUBSTITUTE_TYPE_SIMILAR:
            supplier_relationship_confidence = 55
        else:
            supplier_relationship_confidence = 40
    else:
        supplier_relationship_confidence = 0
        supplier_relationship_summary = (
            "No exact supplier substitute relationship was retained for this candidate."
        )

    return {
        "engineering_evidence_status": status,
        "engineering_evidence_summary": summary,
        "engineering_coverage_percent": coverage_percent,
        "engineering_comparison_confidence": engineering_confidence,
        "supplier_relationship_confidence": supplier_relationship_confidence,
        "supplier_relationship_summary": supplier_relationship_summary,
        "matches": matches,
        "differences": differences,
        "needs_data": needs_data,
        "compared_fields": compared_fields,
    }


def build_recommendation_score_breakdown(
    sourcing_score: int,
    compatibility_confidence: int,
    counts: dict,
    *,
    is_explicit_substitute: bool,
) -> dict:
    """Calculate an explainable, engineering-first recommendation score.

    Engineering compatibility carries 55% of the result, retrieved comparison
    evidence 30%, and sourcing signals 15%. This prevents a generic catalog
    candidate from tying a closely matched alternative simply because both
    have similar lifecycle or stock signals.
    """
    matches = max(0, int(counts.get("Match", 0) or 0))
    differences = max(0, int(counts.get("Different", 0) or 0))
    needs_data = max(0, int(counts.get("Needs data", 0) or 0))

    # A recorded difference has more impact than an unknown. Matches improve
    # quality, but do not erase a documented conflict.
    evidence_quality = 100 - (differences * 16) - (needs_data * 7)
    evidence_quality += min(matches, 8) * 2
    evidence_quality = max(0, min(evidence_quality, 100))

    evidence_cap = 100 - (differences * 12) - (needs_data * 6)
    if not is_explicit_substitute:
        evidence_cap = min(evidence_cap, 95)
    adjusted_confidence = max(
        0,
        min(int(compatibility_confidence or 0), evidence_cap),
    )
    normalized_sourcing = max(0, min(int(sourcing_score or 0), 100))
    recommendation = round(
        (adjusted_confidence * 0.55)
        + (evidence_quality * 0.30)
        + (normalized_sourcing * 0.15)
    )
    recommendation = max(0, min(recommendation, 98 if is_explicit_substitute else 95))

    # DigiKey Direct is supplier-relationship evidence only. Floor the blended
    # recommendation when engineering coverage is already substantial, but never
    # invent high engineering compatibility from Direct + packaging alone.
    if (
        is_explicit_substitute
        and differences == 0
        and matches >= 4
        and needs_data <= 2
    ):
        recommendation = max(recommendation, 85)

    return {
        "recommendation_score": recommendation,
        "compatibility_confidence": adjusted_confidence,
        "engineering_compatibility": adjusted_confidence,
        "evidence_quality": evidence_quality,
        "sourcing_signal": normalized_sourcing,
        "matches": matches,
        "differences": differences,
        "needs_data": needs_data,
    }


class _DatasheetLinkParser(HTMLParser):
    """Collect clearly labeled PDF links from distributor product pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._anchor: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "a" and attributes.get("href"):
            self._anchor = (attributes["href"], [attributes.get("title", "")])

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._anchor is not None:
            href, labels = self._anchor
            self.links.append((href, " ".join(labels)))
            self._anchor = None


def _datasheet_links_from_product_page(payload: bytes, page_url: str) -> list[str]:
    parser = _DatasheetLinkParser()
    try:
        parser.feed(payload.decode("utf-8", errors="replace"))
    except Exception:
        return []
    candidates: list[str] = []
    for href, label in parser.links:
        absolute = _canonical_datasheet_url(urljoin(page_url, href.strip()))
        path = urlparse(absolute).path.casefold()
        description = f"{path} {label}".casefold()
        if not path.endswith(".pdf") and not (
            "datasheet" in description or "data sheet" in description
        ):
            continue
        # Only follow clearly labeled PDF files from product pages, not HTML
        # section anchors or directory indexes that happen to mention datasheet.
        if not path.endswith(".pdf"):
            continue
        if _public_datasheet_url(absolute) and absolute not in candidates:
            candidates.append(absolute)
        if len(candidates) >= MAX_DATASHEET_URL_ATTEMPTS - 1:
            break
    return candidates


def _read_limited_response(response: Any, limit: int) -> bytes:
    payload = bytearray()
    for block in response.iter_content(65536):
        if block:
            payload.extend(block)
            if len(payload) > limit:
                raise ValueError("The linked document exceeds the safe analysis size limit.")
    return bytes(payload)


def _parse_datasheet_pdf(payload: bytes, current_url: str) -> dict[str, Any]:
    if not payload.startswith(b"%PDF"):
        return {
            "available": False,
            "reason": "The link did not return a PDF. Cadivor is checking the linked product page for its datasheet.",
            "pages": [],
            "is_product_page": True,
        }
    if len(payload) > MAX_DATASHEET_BYTES:
        return {"available": False, "reason": "Datasheet exceeds the safe analysis size limit.", "pages": []}
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(payload))
    document_page_count = len(reader.pages)
    pages_examined = min(document_page_count, MAX_DATASHEET_PAGES)
    pages = []
    image_only_page_count = 0
    text_truncated = False
    for page_number, page in enumerate(reader.pages[:MAX_DATASHEET_PAGES], start=1):
        raw_text = page.extract_text() or ""
        text = raw_text.strip()
        if len(text) > 5000:
            text_truncated = True
            text = text[:5000]
        if text:
            pages.append({"page": page_number, "text": text})
        else:
            image_only_page_count += 1
    page_cap_applied = document_page_count > MAX_DATASHEET_PAGES
    return {
        "available": bool(pages),
        "reason": "" if pages else "The PDF was retrieved, but it contains no extractable text. Inspect the PDF drawings directly. OCR is not supported.",
        "pages": pages,
        "page_count": len(pages),
        "document_page_count": document_page_count,
        "pages_examined": pages_examined,
        "text_page_count": len(pages),
        "image_only_page_count": image_only_page_count,
        "page_cap_applied": page_cap_applied,
        "text_truncated": text_truncated,
        "search_complete": not page_cap_applied,
        "extraction_method": "native_pdf_text" if pages else "none",
        "ocr_supported": False,
        "final_url": current_url,
    }


def _canonical_datasheet_url(url: str) -> str:
    """Drop fragments so HTML anchors are not treated as distinct PDF targets."""
    parsed = urlparse(str(url or "").strip())
    return urlunparse(parsed._replace(fragment=""))


def _pdf_gate_bypass_url(url: str) -> str:
    """Some manufacturer hosts return an HTML gate for bare .pdf URLs.

    Ohmite serves the actual PDF when the same public HTTPS path is requested
    with ``r=false``. Only rewrite URLs whose path ends in ``.pdf``.
    """
    parsed = urlparse(_canonical_datasheet_url(url))
    if not parsed.path.casefold().endswith(".pdf"):
        return ""
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    if any(key.casefold() == "r" for key, _value in query_items):
        return ""
    query_items.append(("r", "false"))
    return urlunparse(parsed._replace(query=urlencode(query_items), fragment=""))


def extract_datasheet_text(url: str) -> dict:
    """Retrieve a PDF from a public HTTPS link or a linked product page.

    Product pages returned by distributor catalogs often hold the PDF link one
    click deeper. Cadivor follows only clearly labeled datasheet/PDF links,
    validates each redirect and destination, and never treats HTML or a failed
    request as evidence.
    """
    start_url = str(url or "").strip()
    if not _public_datasheet_url(start_url):
        return {"available": False, "reason": "Only public HTTPS datasheet links can be reviewed.", "pages": []}

    pending = [_canonical_datasheet_url(start_url)]
    visited: set[str] = set()
    last_reason = "Cadivor could not retrieve a readable official datasheet. Open the product page or use the optional PDF fallback."
    headers = {
        "Accept": "application/pdf, application/octet-stream, text/html;q=0.9, */*;q=0.7",
        "User-Agent": "CadivorEngineeringReview/1.0 (+https://cadivor.com)",
    }
    while pending and len(visited) < MAX_DATASHEET_URL_ATTEMPTS:
        current_url = _canonical_datasheet_url(pending.pop(0))
        if current_url in visited:
            continue
        visited.add(current_url)
        if not _public_datasheet_url(current_url):
            last_reason = "A linked document used a non-public or insecure URL and was skipped."
            continue
        response = None
        try:
            for redirect_number in range(MAX_DATASHEET_REDIRECTS + 1):
                response = requests.get(
                    current_url,
                    timeout=(5, 15),
                    headers={**headers, "Referer": start_url},
                    stream=True,
                    allow_redirects=False,
                )
                status_code = int(getattr(response, "status_code", 200) or 200)
                if status_code not in {301, 302, 303, 307, 308}:
                    break
                location = str((getattr(response, "headers", {}) or {}).get("Location") or "").strip()
                close = getattr(response, "close", None)
                if callable(close):
                    close()
                response = None
                if not location:
                    last_reason = "The datasheet link redirected without a destination."
                    break
                current_url = _canonical_datasheet_url(urljoin(current_url, location))
                if not _public_datasheet_url(current_url):
                    last_reason = "The datasheet redirected to a non-public or insecure URL."
                    break
            else:
                last_reason = "The datasheet link redirected too many times."
                continue
            if response is None:
                continue
            response.raise_for_status()
            content_type = str((getattr(response, "headers", {}) or {}).get("Content-Type") or "").casefold()
            payload = _read_limited_response(response, MAX_DATASHEET_BYTES)
            if not payload.startswith(b"%PDF") and len(payload) > MAX_DATASHEET_PAGE_BYTES:
                raise ValueError("The linked product page exceeds the safe analysis size limit.")
            result = _parse_datasheet_pdf(payload, current_url)
            if result.get("available"):
                result["requested_url"] = start_url
                result["retrieval_path"] = (
                    "direct_pdf"
                    if _canonical_datasheet_url(current_url).split("?", 1)[0]
                    == _canonical_datasheet_url(start_url).split("?", 1)[0]
                    else "product_page_pdf_link"
                )
                return result
            if result.get("is_product_page") or "html" in content_type or payload.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                discovered = list(_datasheet_links_from_product_page(payload, current_url))
                # Bare manufacturer .pdf links sometimes return an HTML gate.
                # Queue the same path with the public r=false bypass when present.
                gate_bypass = _pdf_gate_bypass_url(current_url)
                if gate_bypass:
                    discovered.insert(0, gate_bypass)
                for discovered_url in discovered:
                    candidate = _canonical_datasheet_url(discovered_url)
                    bypass = _pdf_gate_bypass_url(candidate)
                    for item in (candidate, bypass):
                        if item and item not in visited and item not in pending:
                            pending.append(item)
                if not pending:
                    last_reason = "The product page loaded, but Cadivor found no clearly labeled datasheet PDF link. Use the optional PDF fallback if you have the official document."
            else:
                last_reason = str(result.get("reason") or last_reason)
        except Exception as exc:
            message = str(exc or "").strip()
            if "403" in message:
                last_reason = "The supplier blocked automated PDF retrieval (HTTP 403). Open the supplier page or use the optional PDF fallback."
            elif "404" in message:
                last_reason = "The linked datasheet was not found (HTTP 404). Cadivor will check another available product link."
            elif "timed out" in message.casefold() or "timeout" in message.casefold():
                last_reason = "The datasheet host timed out. Retry the analysis or use the optional PDF fallback."
            elif isinstance(exc, ValueError):
                last_reason = message
            else:
                last_reason = "Cadivor could not read this link as a PDF. Open the supplier page or use the optional PDF fallback."
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    return {"available": False, "reason": last_reason, "pages": [], "attempted_urls": sorted(visited)}


def _public_datasheet_url(url: str) -> bool:
    """Reject insecure and non-public destinations before making PDF requests."""
    try:
        parsed = urlparse(str(url or "").strip())
        hostname = str(parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or hostname == "localhost"
        or hostname.endswith((".localhost", ".local", ".internal", ".test"))
    ):
        return False
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(item[4][0].split("%", 1)[0])
                for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            ]
        except (OSError, ValueError):
            return False
    return bool(addresses) and all(address.is_global for address in addresses)


_DATASHEET_DIMENSION_TOPIC_RE = re.compile(
    r"\b(?:dimension|outline|mechanical|package|footprint|land pattern|"
    r"body size|lead pitch|pin pitch|terminal pitch|package drawing)\b",
    re.IGNORECASE,
)
_DATASHEET_DIMENSION_VALUE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mm|millimet(?:er|re)s?|cm|in(?:ch(?:es)?)?|mil|µm|um)\b",
    re.IGNORECASE,
)


def extract_datasheet_dimension_evidence(pdf_result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return page-cited text around package and mechanical-dimension labels.

    This intentionally does not infer a footprint match from snippets. Many
    datasheets put the actual outline in a drawing or raster image, which needs
    direct human inspection in the linked PDF.
    """
    output: list[dict[str, Any]] = []
    document = pdf_result if isinstance(pdf_result, Mapping) else {}
    for page in document.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        lines = [" ".join(str(line).split()) for line in str(page.get("text") or "").splitlines()]
        lines = [line for line in lines if line]
        seen: set[str] = set()
        for index, line in enumerate(lines):
            if not _DATASHEET_DIMENSION_TOPIC_RE.search(line):
                continue
            excerpt_lines = []
            for candidate_line in lines[index:index + 5]:
                if candidate_line != line and _DATASHEET_DIMENSION_TOPIC_RE.search(candidate_line):
                    break
                if not _DATASHEET_DIMENSION_VALUE_RE.search(candidate_line):
                    continue
                if not re.search(
                    r"\b(?:length|width|height|pitch|spacing|diameter|thickness|span|size|body|overall|terminal|lead)\b",
                    candidate_line,
                    re.IGNORECASE,
                ) and not re.search(r"\bpackage\s+dimensions?\b", line, re.IGNORECASE):
                    continue
                excerpt_lines.append(candidate_line)
            if not excerpt_lines:
                continue
            excerpt = " · ".join(excerpt_lines)[:420]
            if not excerpt or excerpt.casefold() in seen:
                continue
            seen.add(excerpt.casefold())
            output.append({
                "document": str(page.get("document") or "").strip(),
                "page": page.get("page", "?"),
                "excerpt": excerpt,
            })
            if len(output) >= 12:
                return output
    return output


_DIMENSION_MEASURE_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>millimeters?|millimetres?|mm|cm|inches|inch|in|mils?|µm|um)\b",
    re.IGNORECASE,
)
_PHYSICAL_DIMENSION_LABELS = frozenset(
    {"length", "width", "height", "pitch", "spacing", "diameter", "thickness", "span"}
)


def compare_datasheet_dimension_evidence(
    source_excerpts: list[Mapping[str, Any]] | None,
    candidate_excerpts: list[Mapping[str, Any]] | None,
) -> list[str]:
    """Flag clear text-extracted dimension conflicts with matching labels.

    This is a conservative cross-check. It does not treat absent labels or
    image-only drawings as a match; the reviewer still inspects the PDF.
    """
    unit_to_mm = {
        "mm": 1.0,
        "millimeter": 1.0,
        "millimeters": 1.0,
        "millimetre": 1.0,
        "millimetres": 1.0,
        "cm": 10.0,
        "in": 25.4,
        "inch": 25.4,
        "inches": 25.4,
        "mil": 0.0254,
        "mils": 0.0254,
        "um": 0.001,
        "µm": 0.001,
    }

    def measurements(excerpts: list[Mapping[str, Any]] | None) -> dict[str, float]:
        result: dict[str, float] = {}
        for item in excerpts or []:
            if not isinstance(item, Mapping):
                continue
            for segment in str(item.get("excerpt") or "").split("·"):
                match = _DIMENSION_MEASURE_RE.search(segment)
                if not match:
                    continue
                label_tokens = re.findall(r"[a-z]+", segment[:match.start()].casefold())
                meaningful = [
                    token
                    for token in label_tokens
                    if token in _PHYSICAL_DIMENSION_LABELS
                    or token in {"body", "lead", "terminal", "overall", "package", "centerline"}
                ]
                if not meaningful:
                    continue
                key = " ".join(meaningful)
                unit = match.group("unit").casefold()
                number = float(match.group("value")) * unit_to_mm[unit]
                # Keep the first occurrence for a repeated label within a PDF;
                # later repeated headings can come from a different package option.
                result.setdefault(key, number)
        return result

    source = measurements(source_excerpts)
    candidate = measurements(candidate_excerpts)
    findings = []
    for key in sorted(set(source) & set(candidate)):
        source_value, candidate_value = source[key], candidate[key]
        tolerance = max(0.005, max(abs(source_value), abs(candidate_value)) * 0.001)
        if abs(source_value - candidate_value) > tolerance:
            findings.append(
                f"The source and candidate datasheets report different {key} dimensions "
                f"({source_value:g} mm vs {candidate_value:g} mm)."
            )
    return findings


def build_datasheet_review_evidence(
    original_pdf: Mapping[str, Any] | None,
    candidate_pdf: Mapping[str, Any] | None,
    family: str,
) -> dict[str, Any]:
    """Build a compact, cited evidence record without converting excerpts to facts."""
    original = dict(original_pdf or {})
    candidate = dict(candidate_pdf or {})
    rows = build_pdf_field_evidence(original, candidate, family)
    return {
        "source": {
            "available": bool(original.get("available")),
            "page_count": int(original.get("page_count") or len(original.get("pages") or [])),
            "reason": str(original.get("reason") or ""),
            "dimension_evidence": extract_datasheet_dimension_evidence(original),
        },
        "candidate": {
            "available": bool(candidate.get("available")),
            "page_count": int(candidate.get("page_count") or len(candidate.get("pages") or [])),
            "reason": str(candidate.get("reason") or ""),
            "dimension_evidence": extract_datasheet_dimension_evidence(candidate),
        },
        "field_evidence": rows,
        "interpretation": (
            "Page-cited PDF text is supporting evidence. Confirm package-outline drawings, "
            "pinout, and application limits in the original datasheets; extracted text alone "
            "does not establish drop-in compatibility."
        ),
    }


def _pdf_value_after_label(line: str, labels: tuple[str, ...]) -> str:
    """Extract a value beside a field label without treating the label as data."""
    compact = " ".join(str(line or "").split())
    matches = []
    for label in sorted((str(value).strip() for value in labels if str(value).strip()), key=len, reverse=True):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(label) + r"(?![A-Za-z0-9])"
        match = re.search(pattern, compact, re.IGNORECASE)
        if match:
            matches.append(match)
    if not matches:
        return ""
    match = min(matches, key=lambda item: item.start())
    after = compact[match.end():].strip(" \t:;=|–—-")
    # Distributor labels often keep the unit in parentheses on the label side,
    # e.g. "Resistance Value (Ohm): 10K" or "Maximum Voltage Rating (V): 305".
    # Strip that marker so the value stays "10K" / "305" without inventing units.
    unit_marker = re.match(r"^\(([^)]{1,16})\)\s*[:|=]?\s*(.*)$", after)
    if unit_marker:
        after = unit_marker.group(2).strip()
    after = after.strip(" \t:;=|–—-()[]")
    before = compact[:match.start()].strip(" \t:;=|–—-()[]")
    value = after or before
    # A heading such as "Package dimensions (mm)" is not a measured value.
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    if normalized in {
        "", "mm", "cm", "um", "micron", "microns", "mil", "mils",
        "in", "inch", "inches", "dimensions", "dimension", "outline",
        "dimensionsmm", "dimensionmm", "dimensionscm", "dimensioncm",
        "dimensionsin", "dimensionin", "mechanicaldimensions", "packagedimensions",
        "packagedrawing", "outline drawing", "outlinemm", "outlinein",
        "v", "mv", "kv", "a", "ma", "ua", "w", "mw", "ohm", "kohm",
        "mohm", "f", "uf", "nf", "pf", "h", "uh", "mh", "hz", "khz",
        "mhz", "ghz", "s", "ms", "us", "c", "degc", "degf",
    }:
        return ""
    return value[:280]


_PACKAGE_FAMILY_RE = re.compile(
    r"\b(?:power\s*soic|hsoic|soic|tssop|ssop|msop|qfn|dfn|lqfp|tqfp|qfp|"
    r"dip|pdip|plcc|lcc|bga|csp|vson|wson|sot|to)\s*[- ]?\s*\d{1,3}\b"
    r"|\b\d{1,3}\s*[- ]?\s*(?:pins?\s*[- ]?\s*)?(?:power\s*soic|hsoic|soic|tssop|ssop|msop|qfn|"
    r"dfn|lqfp|tqfp|qfp|dip|pdip|plcc|lcc|bga|csp|vson|wson|sot|to)\b",
    re.IGNORECASE,
)


def _is_specific_package_designation(value: str) -> bool:
    """Return whether extracted package text names a recognizable footprint.

    Datasheets often contain broad marketing phrases such as "PowerPAD
    integrated circuit package". Those phrases are useful context, but they
    are not package codes or geometry and must not be compared as if they
    contradict a distributor's explicit package field.
    """
    return bool(_PACKAGE_FAMILY_RE.search(" ".join(str(value or "").split())))


def _is_specific_pdf_field_value(field_spec: Any, value: str) -> bool:
    """Reject narrative fragments that happen to contain a field label."""
    text = " ".join(str(value or "").split()).strip(" :;,.—–-")
    if not text or len(text) > 140:
        return False
    if re.search(r"\b(?:depending|delivering|implementation|consumption|selecting|described|provides)\b", text, re.IGNORECASE):
        return False
    key = str(getattr(field_spec, "key", "") or "")
    if key == "package":
        return _is_specific_package_designation(text)
    if key == "pin_count":
        return bool(re.fullmatch(r"\d{1,3}(?:\s*[- ]?\s*(?:pins?|balls?))?", text, re.IGNORECASE))
    if key == "mounting_style":
        return bool(re.search(
            r"\b(?:surface[- ]mount|smd|smt|through[- ]hole|tht|axial|radial|panel[- ]mount|chassis[- ]mount)\b",
            text,
            re.IGNORECASE,
        ))
    if key == "lifecycle_status":
        return bool(re.fullmatch(
            r"(?:active|in production|nrnd|not recommended for new designs|obsolete|discontinued|end of life|eol|ltb|last time buy)",
            text,
            re.IGNORECASE,
        ))
    if key == "temperature_range":
        return bool(re.search(r"-?\d+(?:\.\d+)?\s*(?:°\s*[CF]|deg(?:rees?)?\s*[CF])", text, re.IGNORECASE))
    if key in {"architecture", "device_type"}:
        return bool(re.search(
            r"\b(?:arm|cortex|8051|hc11|avr|pic\d*|risc[- ]?v|mips|powerpc|fpga|cpld|microcontroller|microprocessor|amplifier|comparator|regulator|transceiver|mosfet|npn|pnp|logic|diode|schottky|tvs)\b",
            text,
            re.IGNORECASE,
        ))
    if key == "memory_size":
        return bool(re.search(r"\b\d+(?:\s*(?:or|to|[-–/])\s*\d+)?\s*(?:K|M|G)?\s*(?:B|bit|byte)s?\b", text, re.IGNORECASE))
    if key == "io_count":
        return bool(re.search(r"\b\d+\s*(?:fast\s*)?(?:I/O\s*)?(?:ports?|pins?)\b", text, re.IGNORECASE))
    unit = str(getattr(field_spec, "unit", "") or "").strip()
    if unit:
        unit_aliases = {
            "V": r"(?:V|mV|kV)",
            "A": r"(?:A|mA|uA|µA)",
            "F": r"(?:F|mF|uF|µF|nF|pF)",
            "Ohm": r"(?:ohms?|Ω|mΩ|kΩ|MΩ|kOhms?|mOhms?)",
            "W": r"(?:W|mW)",
            "Hz": r"(?:Hz|kHz|MHz|GHz)",
            "C": r"(?:°s*[CF]|deg(?:rees?)?s*[CF])",
            "s": r"(?:s|ms|us|µs|ns)",
        }
        unit_pattern = unit_aliases.get(unit)
        if unit_pattern and re.search(rf"\d+(?:\.\d+)?\s*{unit_pattern}\b", text, re.IGNORECASE):
            return True
        # Manufacturer/distributor attribute tables often put the unit in the
        # column label (Ohms Value, Resistance Value (Ohm), Watts, Volts) and
        # leave a bare number or SI shorthand (10K) in the cell. Accept that
        # token without inventing a unit suffix in the displayed value.
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return True
        if unit == "Ohm" and re.fullmatch(
            r"\d+(?:\.\d+)?\s*[kKmMgG](?:\s*(?:ohms?|Ω))?",
            text,
            re.IGNORECASE,
        ):
            return True
        return False
    # Free-form engineering labels are accepted only when they yield a short
    # value, not a sentence fragment from surrounding explanatory prose.
    return not re.search(r"[.!?]{2,}|\b(?:the|this|these|with|from|while|which|that)\b", text, re.IGNORECASE)


def _find_pdf_evidence(
    pdf_result: dict,
    labels: tuple[str, ...],
    *,
    require_specific_package: bool = False,
    field_spec: Any = None,
) -> tuple[str, str, str]:
    package_matches: dict[str, tuple[str, str, str]] = {}
    generic_package_fallback: tuple[str, str, str] | None = None
    for page in pdf_result.get("pages") or []:
        lines = [" ".join(line.split()) for line in str(page.get("text") or "").splitlines()]
        lines = [line for line in lines if line]
        for index, compact in enumerate(lines):
            if not any(
                re.search(
                    r"(?<![A-Za-z0-9])" + re.escape(label) + r"(?![A-Za-z0-9])",
                    compact,
                    re.IGNORECASE,
                )
                for label in labels
            ):
                continue
            value = _pdf_value_after_label(compact, labels)
            excerpt_line = compact
            if not value and index + 1 < len(lines):
                # A label at the end of a wrapped line can leave the value on
                # the next line. Accept that line only when it is itself a
                # specific field value, not surrounding prose.
                following = lines[index + 1]
                if field_spec is not None and _is_specific_pdf_field_value(field_spec, following):
                    value = following
                    excerpt_line = f"{compact} {following}"
            if not value:
                continue
            if field_spec is not None and not _is_specific_pdf_field_value(field_spec, value):
                continue
            page_number = str(page.get("page", "?") or "?")
            document = str(page.get("document") or "").strip()
            citation = f"{document} p. {page_number}" if document else f"p. {page_number}"
            if require_specific_package and not _is_specific_package_designation(value):
                if generic_package_fallback is None:
                    generic_package_fallback = (value, citation, excerpt_line[:280])
                continue
            if require_specific_package:
                package_key = re.sub(r"[^a-z0-9]", "", value.casefold())
                package_matches.setdefault(package_key, (value, citation, excerpt_line[:280]))
                continue
            return value, citation, excerpt_line[:280]
    if require_specific_package:
        # Family datasheets often contain drawings for several packages. The
        # first package mentioned is not evidence for the selected order code.
        # Only expose a package when the extracted PDF names one unique option.
        if len(package_matches) == 1:
            return next(iter(package_matches.values()))
        return "", "", ""
    if generic_package_fallback is not None:
        return generic_package_fallback
    return "", "", ""


def _pdf_mentions_exact_part(pdf_result: Mapping[str, Any], part_number: str) -> bool:
    key = re.sub(r"[^A-Z0-9]", "", str(part_number or "").upper())
    if not key:
        return False
    for page in pdf_result.get("pages") or []:
        text = str(page.get("text") or "")
        for line in text.splitlines():
            # Normalize punctuation so `LM317D-CYR` and `LM317DCYR` can be
            # compared, but retain source offsets to reject a code that is
            # merely the prefix of a longer orderable MPN.
            normalized_chars = []
            source_offsets = []
            for offset, char in enumerate(line.upper()):
                if char.isalnum():
                    normalized_chars.append(char)
                    source_offsets.append(offset)
            normalized_line = "".join(normalized_chars)
            for match in re.finditer(re.escape(key), normalized_line):
                source_start = source_offsets[match.start()]
                source_end = source_offsets[match.end() - 1] + 1
                before = line[source_start - 1] if source_start > 0 else ""
                after = line[source_end] if source_end < len(line) else ""
                if before.isalnum() or after.isalnum():
                    continue
                return True
    return False


def build_pdf_field_evidence(
    original_pdf: dict,
    candidate_pdf: dict,
    family: str,
    *,
    original_mpn: str = "",
    candidate_mpn: str = "",
) -> list[dict]:
    """Extract page-cited relevant fields from two readable official PDFs."""
    profile = get_family_profile(family)
    fields = comparison_fields(profile)
    rows = []
    original_has_exact_identity = _pdf_mentions_exact_part(original_pdf, original_mpn)
    candidate_has_exact_identity = _pdf_mentions_exact_part(candidate_pdf, candidate_mpn)
    for spec in fields:
        aliases = tuple(alias.casefold() for alias in (spec.pdf_aliases or (spec.label.casefold(),)))
        original_value, original_page, original_excerpt = _find_pdf_evidence(
            original_pdf,
            aliases,
            require_specific_package=spec.key == "package",
            field_spec=spec,
        )
        candidate_value, candidate_page, candidate_excerpt = _find_pdf_evidence(
            candidate_pdf,
            aliases,
            require_specific_package=spec.key == "package",
            field_spec=spec,
        )
        if spec.key == "package":
            # A family-level PDF can contain package drawings for unrelated
            # orderable variants. Do not attribute any outline to this exact
            # MPN unless its code appears in the extracted PDF text.
            if original_mpn and not original_has_exact_identity:
                original_value = original_page = original_excerpt = ""
            if candidate_mpn and not candidate_has_exact_identity:
                candidate_value = candidate_page = candidate_excerpt = ""
        original_package_specific = (
            spec.key != "package" or _is_specific_package_designation(original_value)
        )
        candidate_package_specific = (
            spec.key != "package" or _is_specific_package_designation(candidate_value)
        )
        if spec.key == "package":
            # Keep broad wording visible in the cited excerpt, but don't
            # present it as an exact package value or an automatic match.
            if not original_package_specific:
                original_value = ""
            if not candidate_package_specific:
                candidate_value = ""
        status, note = compare_field_values(original_value, candidate_value, spec)
        if spec.key == "package" and (not original_package_specific or not candidate_package_specific):
            note = (
                "No unique package designation tied to the exact orderable part was found in the extracted text. "
                "A family PDF may contain outlines for multiple variants. Inspect the manufacturer package-outline drawing and confirm dimensions and pin pitch."
            )
        rows.append({
            "Attribute": spec.label,
            "Key": spec.key,
            "Required": bool(spec.required),
            "Original PDF evidence": original_excerpt or "Not found",
            "Candidate PDF evidence": candidate_excerpt or "Not found",
            "Original PDF value": original_value or "Not found",
            "Candidate PDF value": candidate_value or "Not found",
            "Original PDF page": original_page or "Not available",
            "Candidate PDF page": candidate_page or "Not available",
            "Source pages": " / ".join(value for value in (original_page, candidate_page) if value) or "Not available",
            "Status": status,
            "Evidence": note,
        })
    return rows
