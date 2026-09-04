"""Evidence-led datasheet comparison for Alternative Finder.

The module is deliberately conservative: a matching catalog field is useful
evidence, but is never an automatic approval.  Datasheet PDFs are fetched only
from supplier-provided HTTPS/HTTP links, parsed on demand, and the UI shows
when a value is unavailable rather than inventing a comparison.

Family field matrices, DigiKey aliases, and comparison modes come from
``src.component_family_profiles`` so every family shares one declarative
registry across normalization, scoring, UI, and PDF output.
"""
from __future__ import annotations

from io import BytesIO
import re
from typing import Any, Mapping
from urllib.parse import urlparse

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


def _display_value(value) -> str:
    if value is None or str(value).strip() in {"", "None", "Unknown", "nan"}:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).strip()


def _display_pin_count(part: dict) -> str:
    from integrations.pin_count import effective_pin_count

    count = effective_pin_count(part)
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
        status, note = compare_field_values(original_value, candidate_value, spec)
        counts[status] += 1
        rows.append({
            "Attribute": spec.label,
            "Key": spec.key,
            "Required": bool(spec.required),
            "CompareMode": spec.compare,
            "ValueRole": spec.value_role,
            "Original": original_value or "Not available",
            "Candidate": candidate_value or "Not available",
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


def extract_datasheet_text(url: str) -> dict:
    """Retrieve an official PDF and return page-addressable text evidence.

    This returns a safe failure state for non-PDF links or inaccessible files;
    callers must present it as unavailable evidence, never as a successful
    comparison.
    """
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return {"available": False, "reason": "No valid datasheet URL was provided.", "pages": []}
    try:
        from pypdf import PdfReader

        response = requests.get(url, timeout=20, headers={"Accept": "application/pdf"}, stream=True)
        response.raise_for_status()
        payload = b""
        for block in response.iter_content(65536):
            payload += block
            if len(payload) > MAX_DATASHEET_BYTES:
                return {"available": False, "reason": "Datasheet exceeds the safe analysis size limit.", "pages": []}
        if not payload.startswith(b"%PDF"):
            return {"available": False, "reason": "The supplier link did not return a PDF datasheet.", "pages": []}
        reader = PdfReader(BytesIO(payload))
        pages = []
        for page_number, page in enumerate(reader.pages[:MAX_DATASHEET_PAGES], start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append({"page": page_number, "text": text[:5000]})
        return {"available": bool(pages), "reason": "" if pages else "No readable text was extracted from the datasheet.", "pages": pages}
    except Exception:
        return {"available": False, "reason": "Cadivor could not retrieve a readable official datasheet right now.", "pages": []}


def _find_pdf_evidence(pdf_result: dict, labels: tuple[str, ...]) -> tuple[str, str]:
    for page in pdf_result.get("pages") or []:
        for line in str(page.get("text") or "").splitlines():
            compact = " ".join(line.split())
            if any(label in compact.casefold() for label in labels):
                return compact[:280], f"p. {page.get('page', '?')}"
    return "", ""



def build_pdf_field_evidence(original_pdf: dict, candidate_pdf: dict, family: str) -> list[dict]:
    """Extract page-cited relevant fields from two readable official PDFs."""
    profile = get_family_profile(family)
    fields = comparison_fields(profile)
    rows = []
    for spec in fields:
        aliases = tuple(alias.casefold() for alias in (spec.pdf_aliases or (spec.label.casefold(),)))
        original_value, original_page = _find_pdf_evidence(original_pdf, aliases)
        candidate_value, candidate_page = _find_pdf_evidence(candidate_pdf, aliases)
        status, note = compare_field_values(original_value, candidate_value, spec)
        rows.append({
            "Attribute": spec.label,
            "Key": spec.key,
            "Required": bool(spec.required),
            "Original PDF evidence": original_value or "Not found",
            "Candidate PDF evidence": candidate_value or "Not found",
            "Source pages": " / ".join(value for value in (original_page, candidate_page) if value) or "Not available",
            "Status": status,
            "Evidence": note,
        })
    return rows
