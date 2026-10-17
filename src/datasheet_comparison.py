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

from io import BytesIO
import ipaddress
import re
import socket
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

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
    """Retrieve a supplier-linked public HTTPS PDF and return cited text evidence.

    Redirects are followed one hop at a time and every destination is checked.
    Private, loopback, link-local, and local-network hosts are rejected. This
    returns an unavailable state for non-PDF links or inaccessible files;
    callers must never present that as successful evidence.
    """
    current_url = str(url or "").strip()
    if not _public_datasheet_url(current_url):
        return {
            "available": False,
            "reason": "Only public HTTPS datasheet links can be reviewed.",
            "pages": [],
        }
    try:
        from pypdf import PdfReader

        response = None
        for _ in range(MAX_DATASHEET_REDIRECTS + 1):
            response = requests.get(
                current_url,
                timeout=(5, 20),
                headers={"Accept": "application/pdf"},
                stream=True,
                allow_redirects=False,
            )
            if int(getattr(response, "status_code", 200) or 200) not in {301, 302, 303, 307, 308}:
                break
            location = str((getattr(response, "headers", {}) or {}).get("Location") or "").strip()
            close = getattr(response, "close", None)
            if callable(close):
                close()
            if not location:
                return {
                    "available": False,
                    "reason": "The datasheet link redirected without a destination.",
                    "pages": [],
                }
            current_url = urljoin(current_url, location)
            if not _public_datasheet_url(current_url):
                return {
                    "available": False,
                    "reason": "The datasheet redirected to a non-public or insecure URL.",
                    "pages": [],
                }
        else:
            return {
                "available": False,
                "reason": "The datasheet link redirected too many times.",
                "pages": [],
            }
        if response is None:
            return {"available": False, "reason": "No datasheet response was received.", "pages": []}
        response.raise_for_status()
        payload = bytearray()
        try:
            for block in response.iter_content(65536):
                if not block:
                    continue
                payload.extend(block)
                if len(payload) > MAX_DATASHEET_BYTES:
                    return {"available": False, "reason": "Datasheet exceeds the safe analysis size limit.", "pages": []}
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if not payload.startswith(b"%PDF"):
            return {"available": False, "reason": "The supplier link did not return a PDF datasheet.", "pages": []}
        reader = PdfReader(BytesIO(bytes(payload)))
        pages = []
        for page_number, page in enumerate(reader.pages[:MAX_DATASHEET_PAGES], start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append({"page": page_number, "text": text[:5000]})
        return {
            "available": bool(pages),
            "reason": "" if pages else "No readable text was extracted from the datasheet.",
            "pages": pages,
            "page_count": len(pages),
            "final_url": current_url,
        }
    except Exception:
        return {"available": False, "reason": "Cadivor could not retrieve a readable official datasheet right now.", "pages": []}


def _public_datasheet_url(url: str) -> bool:
    """Reject insecure and non-public destinations before making PDF requests."""
    parsed = urlparse(str(url or "").strip())
    hostname = str(parsed.hostname or "").rstrip(".").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
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
            excerpt_lines = [line]
            for following in lines[index + 1:index + 4]:
                if _DATASHEET_DIMENSION_TOPIC_RE.search(following) and not _DATASHEET_DIMENSION_VALUE_RE.search(following):
                    break
                if _DATASHEET_DIMENSION_VALUE_RE.search(following) or re.search(r"\d", following):
                    excerpt_lines.append(following)
            excerpt = " · ".join(excerpt_lines)[:420]
            if excerpt and excerpt.casefold() not in seen:
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
    after = compact[match.end():].strip(" \t:;=|–—-()[]")
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


def _find_pdf_evidence(
    pdf_result: dict,
    labels: tuple[str, ...],
) -> tuple[str, str, str]:
    for page in pdf_result.get("pages") or []:
        for line in str(page.get("text") or "").splitlines():
            compact = " ".join(line.split())
            if not compact or not any(
                re.search(
                    r"(?<![A-Za-z0-9])" + re.escape(label) + r"(?![A-Za-z0-9])",
                    compact,
                    re.IGNORECASE,
                )
                for label in labels
            ):
                continue
            value = _pdf_value_after_label(compact, labels)
            if not value:
                continue
            page_number = str(page.get("page", "?") or "?")
            document = str(page.get("document") or "").strip()
            citation = f"{document} p. {page_number}" if document else f"p. {page_number}"
            return value, citation, compact[:280]
    return "", "", ""



def build_pdf_field_evidence(original_pdf: dict, candidate_pdf: dict, family: str) -> list[dict]:
    """Extract page-cited relevant fields from two readable official PDFs."""
    profile = get_family_profile(family)
    fields = comparison_fields(profile)
    rows = []
    for spec in fields:
        aliases = tuple(alias.casefold() for alias in (spec.pdf_aliases or (spec.label.casefold(),)))
        original_value, original_page, original_excerpt = _find_pdf_evidence(original_pdf, aliases)
        candidate_value, candidate_page, candidate_excerpt = _find_pdf_evidence(candidate_pdf, aliases)
        status, note = compare_field_values(original_value, candidate_value, spec)
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
