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
from pypdf import PdfReader


MAX_DATASHEET_BYTES = 8 * 1024 * 1024
MAX_DATASHEET_PAGES = 40


COMMON_FIELDS = (
    ("Package", "package"),
    ("Pin count", "pin_count"),
    ("Mounting", "mounting_style"),
    ("Supply voltage", "voltage_range"),
)

FAMILY_FIELDS = {
    "Resistor": (("Resistance", "resistance"), ("Tolerance", "tolerance"), ("Power rating", "power_rating"), ("Temperature coefficient", "temperature_coefficient")),
    "Capacitor": (("Capacitance", "capacitance"), ("Tolerance", "tolerance"), ("Rated voltage", "rated_voltage"), ("Dielectric", "dielectric"), ("ESR", "esr")),
    "Inductor": (("Inductance", "inductance"), ("Tolerance", "tolerance"), ("DCR", "dcr"), ("Rated current", "rated_current"), ("Saturation current", "saturation_current")),
    "Transformer": (("Turns ratio", "turns_ratio"), ("Isolation voltage", "isolation_voltage"), ("Power rating", "power_rating"), ("Inductance", "inductance")),
    "Diode / protection": (("Reverse voltage", "reverse_voltage"), ("Forward current", "forward_current"), ("Forward voltage", "forward_voltage"), ("Recovery time", "recovery_time")),
    "Transistor / MOSFET": (("Device type", "device_type"), ("Vds / Vce", "drain_or_collector_voltage"), ("Current", "rated_current"), ("Rds(on) / gain", "on_resistance_or_gain"), ("Gate threshold", "gate_threshold")),
    "Operational amplifier": (("Channels", "channel_count"), ("Supply voltage", "voltage_range"), ("Bandwidth", "bandwidth_mhz"), ("Slew rate", "slew_rate_v_us"), ("Input offset", "input_offset_mv"), ("Input bias", "input_bias_na")),
    "Regulator": (("Input voltage", "voltage_range"), ("Output voltage", "output_voltage"), ("Output current", "rated_current"), ("Dropout voltage", "dropout_voltage"), ("Quiescent current", "quiescent_current_ma")),
    "Logic / processor": (("Architecture", "architecture"), ("Pin count", "pin_count"), ("Supply voltage", "voltage_range"), ("Frequency", "frequency_mhz")),
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


def _field_status(original_value: str, candidate_value: str) -> tuple[str, str]:
    if not original_value or not candidate_value:
        return "Needs data", "One or both values were not available from the retrieved evidence."
    if _normalize(original_value) == _normalize(candidate_value):
        return "Match", "The retrieved values match exactly."
    return "Different", "The retrieved values differ; engineer review is required."


def build_datasheet_comparison(original: dict, candidate: dict) -> dict:
    """Build a transparent family-aware comparison from retrieved evidence."""
    family = infer_component_family(original)
    fields = list(COMMON_FIELDS) + list(FAMILY_FIELDS.get(family, ()))
    rows, counts = [], {"Match": 0, "Different": 0, "Needs data": 0}
    for label, key in fields:
        original_value = _display_value(original.get(key))
        candidate_value = _display_value(candidate.get(key))
        status, note = _field_status(original_value, candidate_value)
        counts[status] += 1
        rows.append({
            "Attribute": label,
            "Original": original_value or "Not available",
            "Candidate": candidate_value or "Not available",
            "Status": status,
            "Evidence": note,
        })
    return {"family": family, "rows": rows, "counts": counts}


def apply_comparison_evidence_to_scores(
    recommendation_score: int,
    compatibility_confidence: int,
    counts: dict,
    *,
    is_explicit_substitute: bool,
) -> tuple[int, int]:
    """Apply retrieved comparison evidence to a candidate's displayed scores.

    The sourcing score remains useful, but cannot outweigh evidence that the
    engineering fields differ or are unavailable.  Catalog matches are capped
    below 100% because a distributor search result is not a certified drop-in
    substitute.
    """
    matches = int(counts.get("Match", 0) or 0)
    differences = int(counts.get("Different", 0) or 0)
    needs_data = int(counts.get("Needs data", 0) or 0)

    adjusted_recommendation = int(recommendation_score) + min(matches, 10)
    adjusted_recommendation -= differences * 8
    adjusted_recommendation -= needs_data * 4

    evidence_confidence = 100 - (differences * 12) - (needs_data * 6)
    if not is_explicit_substitute:
        evidence_confidence = min(evidence_confidence, 95)

    return (
        max(0, min(adjusted_recommendation, 98)),
        max(0, min(int(compatibility_confidence), evidence_confidence)),
    )


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
