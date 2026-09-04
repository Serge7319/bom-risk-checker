"""Evidence-led datasheet comparison for Alternative Finder.

The module is deliberately conservative: a matching catalog field is useful
evidence, but is never an automatic approval.  Datasheet PDFs are fetched only
from supplier-provided HTTPS/HTTP links, parsed on demand, and the UI shows
when a value is unavailable rather than inventing a comparison.
"""
from __future__ import annotations

from io import BytesIO
import re
from urllib.parse import urlparse

import requests


MAX_DATASHEET_BYTES = 8 * 1024 * 1024
MAX_DATASHEET_PAGES = 40


COMMON_FIELDS = (
    ("Package", "package"),
    ("Pin count", "pin_count"),
    ("Mounting", "mounting_style"),
    ("Supply voltage", "voltage_range"),
)

FAMILY_FIELDS = {
    "Resistor": (
        ("Resistance", "resistance"),
        ("Tolerance", "tolerance"),
        ("Power rating", "power_rating"),
        ("Temperature coefficient", "temperature_coefficient"),
        ("Voltage rating", "rated_voltage"),
    ),
    "Capacitor": (
        ("Capacitance", "capacitance"),
        ("Tolerance", "tolerance"),
        ("Rated voltage", "rated_voltage"),
        ("Dielectric", "dielectric"),
        ("Temperature characteristic", "temperature_coefficient"),
        ("ESR", "esr"),
    ),
    "Inductor": (
        ("Inductance", "inductance"),
        ("Tolerance", "tolerance"),
        ("DCR", "dcr"),
        ("Rated current", "rated_current"),
        ("Saturation current", "saturation_current"),
        ("Shielding", "shielding"),
        ("Height", "height"),
    ),
    "Transformer": (("Turns ratio", "turns_ratio"), ("Isolation voltage", "isolation_voltage"), ("Power rating", "power_rating"), ("Inductance", "inductance")),
    "Diode / protection": (("Reverse voltage", "reverse_voltage"), ("Forward current", "forward_current"), ("Forward voltage", "forward_voltage"), ("Recovery time", "recovery_time")),
    "Transistor / MOSFET": (("Device type", "device_type"), ("Vds / Vce", "drain_or_collector_voltage"), ("Current", "rated_current"), ("Rds(on) / gain", "on_resistance_or_gain"), ("Gate threshold", "gate_threshold")),
    "Operational amplifier": (("Channels", "channel_count"), ("Supply voltage", "voltage_range"), ("Bandwidth", "bandwidth_mhz"), ("Slew rate", "slew_rate_v_us"), ("Input offset", "input_offset_mv"), ("Input bias", "input_bias_na")),
    "Regulator": (("Input voltage", "voltage_range"), ("Output voltage", "output_voltage"), ("Output current", "rated_current"), ("Dropout voltage", "dropout_voltage"), ("Quiescent current", "quiescent_current_ma")),
    "Logic / processor": (
        ("Architecture", "architecture"),
        ("Pin count", "pin_count"),
        ("Pinout evidence", "pinout"),
        ("Supply voltage", "voltage_range"),
        ("Frequency", "frequency_mhz"),
        ("Channel count", "channel_count"),
    ),
    "Oscillator / crystal": (("Frequency", "frequency_mhz"), ("Frequency tolerance", "frequency_tolerance"), ("Load capacitance", "load_capacitance")),
    "Sensor": (("Measurement range", "measurement_range"), ("Accuracy", "accuracy"), ("Interface", "interface"), ("Supply voltage", "voltage_range")),
    "Connector / electromechanical": (("Positions", "positions"), ("Pitch", "pitch"), ("Current rating", "rated_current"), ("Voltage rating", "rated_voltage")),
}

PDF_LABEL_ALIASES = {
    "Package": ("package", "case", "footprint"), "Pin count": ("pin count", "number of pins"),
    "Mounting": ("mounting",), "Supply voltage": ("supply voltage", "operating voltage"),
    "Resistance": ("resistance",), "Tolerance": ("tolerance",), "Power rating": ("power rating", "rated power"),
    "Temperature coefficient": ("temperature coefficient", "tcr"), "Capacitance": ("capacitance",),
    "Rated voltage": ("rated voltage", "voltage rating"), "Dielectric": ("dielectric",), "ESR": ("esr", "equivalent series resistance"),
    "Inductance": ("inductance",), "DCR": ("dcr", "dc resistance"), "Rated current": ("rated current", "current rating"),
    "Saturation current": ("saturation current",), "Turns ratio": ("turns ratio",), "Isolation voltage": ("isolation voltage",),
    "Reverse voltage": ("reverse voltage",), "Forward current": ("forward current",), "Forward voltage": ("forward voltage",),
    "Recovery time": ("recovery time",), "Device type": ("device type",), "Vds / Vce": ("vds", "vce", "drain-source voltage"),
    "Current": ("drain current", "collector current", "current rating"), "Rds(on) / gain": ("rds(on)", "rds on", "dc current gain"),
    "Gate threshold": ("gate threshold",), "Channels": ("channels", "number of circuits"), "Bandwidth": ("bandwidth", "gain bandwidth"),
    "Slew rate": ("slew rate",), "Input offset": ("input offset",), "Input bias": ("input bias",),
    "Input voltage": ("input voltage",), "Output voltage": ("output voltage",), "Output current": ("output current",),
    "Dropout voltage": ("dropout voltage",), "Quiescent current": ("quiescent current",), "Architecture": ("architecture",),
    "Frequency": ("frequency",), "Frequency tolerance": ("frequency tolerance",), "Load capacitance": ("load capacitance",),
    "Measurement range": ("measurement range", "measurement range"), "Accuracy": ("accuracy",), "Interface": ("interface",),
    "Positions": ("positions", "number of positions"), "Pitch": ("pitch",), "Current rating": ("current rating",), "Voltage rating": ("voltage rating",),
}


PASSIVE_FAMILIES = frozenset({"Capacitor", "Resistor", "Inductor"})

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
)


def normalize_mounting_style(value: str) -> str:
    """Normalize mounting values for comparison without hiding genuine TH vs SMD differences."""
    text = re.sub(r"[^a-z0-9]", "", str(value or "").casefold())
    if not text:
        return ""
    if text in {"smd", "smt"} or text.startswith("surfacemount"):
        return "smd"
    if "throughhole" in text or text in {"th", "tht"}:
        return "throughhole"
    return text


def infer_component_family(part: dict) -> str:
    text = " ".join(
        str(part.get(key) or "")
        for key in ("description", "architecture", "manufacturer_part_number")
    ).casefold()
    checks = (
        ("transform", "Transformer"), ("inductor", "Inductor"), ("choke", "Inductor"),
        ("capacitor", "Capacitor"), ("cap ", "Capacitor"), ("resistor", "Resistor"),
        ("mosfet", "Transistor / MOSFET"), ("transistor", "Transistor / MOSFET"),
        ("diode", "Diode / protection"), ("tvs", "Diode / protection"), ("rectifier", "Diode / protection"),
        ("operational amplifier", "Operational amplifier"), (" op amp", "Operational amplifier"),
        ("regulator", "Regulator"), ("ldo", "Regulator"),
        ("microcontroller", "Logic / processor"), ("logic", "Logic / processor"), ("memory", "Logic / processor"),
        ("oscillator", "Oscillator / crystal"), ("crystal", "Oscillator / crystal"),
        ("sensor", "Sensor"), ("connector", "Connector / electromechanical"),
        ("relay", "Connector / electromechanical"), ("switch", "Connector / electromechanical"),
    )
    for marker, family in checks:
        if marker in text:
            return family
    return "General electronic component"


def _display_value(value) -> str:
    if value is None or str(value).strip() in {"", "None", "Unknown", "nan"}:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).strip()


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9.+-]", "", value.casefold())


def _field_status(original_value: str, candidate_value: str, *, attribute: str = "") -> tuple[str, str]:
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
    # "Supply voltage" is an IC attribute. Passive parts use their rated
    # voltage, which is both electrically meaningful and present in their
    # supplier/datasheet evidence.
    common_fields = list(COMMON_FIELDS)
    if family in PASSIVE_FAMILIES:
        common_fields = [field for field in common_fields if field[1] != "pin_count"]
    if family in {"Capacitor", "Resistor", "Inductor", "Transformer", "Diode / protection", "Transistor / MOSFET"}:
        common_fields = [field for field in common_fields if field[1] != "voltage_range"]
    fields = common_fields + list(FAMILY_FIELDS.get(family, ()))
    rows, counts = [], {"Match": 0, "Different": 0, "Needs data": 0}
    for label, key in fields:
        original_value = _display_value(original.get(key))
        candidate_value = _display_value(candidate.get(key))
        status, note = _field_status(original_value, candidate_value, attribute=label)
        counts[status] += 1
        rows.append({
            "Attribute": label,
            "Original": original_value or "Not available",
            "Candidate": candidate_value or "Not available",
            "Status": status,
            "Evidence": note,
        })
    return {"family": family, "rows": rows, "counts": counts}


def build_engineering_evidence_assessment(
    counts: Mapping[str, Any],
    *,
    classification: str = "",
    substitute_type: str = "",
    supplier_relationship_evidence: list | None = None,
    evidence_source: str = "",
) -> dict:
    """Summarize engineering comparison coverage separately from supplier classification."""
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
    elif classification == CLASS_SUPPLIER_UPGRADE or normalized_type == SUBSTITUTE_TYPE_UPGRADE:
        source_label = str(evidence_source or "Supplier").strip() or "Supplier"
        supplier_relationship_confidence = 70
        supplier_relationship_summary = f"{source_label} substitute type: Upgrade"
    elif classification == CLASS_SUPPLIER_SIMILAR or normalized_type == SUBSTITUTE_TYPE_SIMILAR:
        source_label = str(evidence_source or "Supplier").strip() or "Supplier"
        supplier_relationship_confidence = 55
        supplier_relationship_summary = f"{source_label} substitute type: Similar"
    else:
        # Never invent "substitute type: Direct" from classification alone.
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

    # DigiKey's explicit Direct relationship is meaningful evidence. It must
    # not be demoted solely because a distributor did not expose every field;
    # a documented electrical conflict still wins and prevents this floor.
    if is_explicit_substitute and differences == 0:
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
    fields = list(COMMON_FIELDS) + list(FAMILY_FIELDS.get(family, ()))
    rows = []
    for label, _key in fields:
        aliases = tuple(alias.casefold() for alias in PDF_LABEL_ALIASES.get(label, (label.casefold(),)))
        original_value, original_page = _find_pdf_evidence(original_pdf, aliases)
        candidate_value, candidate_page = _find_pdf_evidence(candidate_pdf, aliases)
        status, note = _field_status(original_value, candidate_value)
        rows.append({
            "Attribute": label,
            "Original PDF evidence": original_value or "Not found",
            "Candidate PDF evidence": candidate_value or "Not found",
            "Source pages": " / ".join(value for value in (original_page, candidate_page) if value) or "Not available",
            "Status": status,
            "Evidence": note,
        })
    return rows
