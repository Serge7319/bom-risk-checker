"""Unit normalization and family-aware attribute comparison rules."""
from __future__ import annotations

import re
from typing import Any

from src.component_family_profiles import (
    COMPARE_EXACT,
    COMPARE_LIMIT_GE,
    COMPARE_LIMIT_LE,
    COMPARE_MOUNTING,
    COMPARE_NOMINAL,
    COMPARE_TYPE,
    FieldSpec,
)


_PREFIX = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6,
    "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
}

_UNIT_ALIASES = {
    "ohm": "Ohm", "ohms": "Ohm", "ω": "Ohm", "Ω": "Ohm",
    "v": "V", "volt": "V", "volts": "V",
    "a": "A", "amp": "A", "amps": "A",
    "w": "W", "watt": "W", "watts": "W",
    "f": "F", "farad": "F",
    "h": "H", "henry": "H",
    "hz": "Hz", "hertz": "Hz",
    "s": "s", "sec": "s", "second": "s",
    "c": "C", "°c": "C",
    "m": "m", "mm": "m", "in": "m",
}


def normalize_mounting_style(value: str) -> str:
    text = re.sub(r"[^a-z0-9]", "", str(value or "").casefold())
    if not text:
        return ""
    if text in {"smd", "smt"} or text.startswith("surfacemount"):
        return "smd"
    if "throughhole" in text or text in {"th", "tht"}:
        return "throughhole"
    return text


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9.+-]", "", str(value or "").casefold())


def parse_numeric_with_unit(text: object, *, preferred_unit: str = "") -> tuple[float | None, str]:
    """Parse the first magnitude from supplier text into SI base units where possible."""
    raw = str(text or "").strip()
    if not raw:
        return None, ""
    # Prefer explicit metric pitch/size in parentheses: 0.100" (2.54mm)
    paren_metric = re.search(
        r"\((\s*[+-]?\d+(?:\.\d+)?\s*mm\s*)\)",
        raw,
        flags=re.IGNORECASE,
    )
    if paren_metric and preferred_unit in {"", "m"}:
        return parse_numeric_with_unit(paren_metric.group(1), preferred_unit="m")
    # Ranges like "100 @ 10mA, 1V" — take leading magnitude.
    match = re.search(
        r"([+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*([pnuµμmkKMG]?)\s*([A-Za-zΩω°/μµ]*)",
        raw.replace(",", ""),
    )
    if not match:
        return None, ""
    number = float(match.group(1))
    prefix = match.group(2) or ""
    unit_token = (match.group(3) or "").strip()
    scale = _PREFIX.get(prefix, 1.0)
    # Special-case: "mOhm", "mA", "mW", "mH", "mV" use milli when letter present.
    unit_key = unit_token.casefold()
    canonical = _UNIT_ALIASES.get(unit_key, unit_token)
    if preferred_unit and not canonical:
        canonical = preferred_unit
    # Frequency already in MHz stored as float elsewhere — leave as Hz when unit says MHz.
    if unit_key in {"mhz"}:
        return number * 1e6, "Hz"
    if unit_key in {"khz"}:
        return number * 1e3, "Hz"
    if unit_key in {"ghz"}:
        return number * 1e9, "Hz"
    if unit_key in {"uf", "µf", "μf"}:
        return number * 1e-6, "F"
    if unit_key in {"nf"}:
        return number * 1e-9, "F"
    if unit_key in {"pf"}:
        return number * 1e-12, "F"
    if unit_key in {"uh", "µh", "μh"}:
        return number * 1e-6, "H"
    if unit_key in {"mh"}:
        return number * 1e-3, "H"
    if unit_key in {"nh"}:
        return number * 1e-9, "H"
    if unit_key in {"kohm", "kω", "kΩ"}:
        return number * 1e3, "Ohm"
    if unit_key in {"mohm", "mω", "mΩ"}:
        return number * 1e-3, "Ohm"
    if unit_key in {"mm"}:
        return number * 1e-3, "m"
    if preferred_unit == "Ohm" and not unit_token and prefix.lower() == "k":
        return number * 1e3, "Ohm"
    if preferred_unit == "Ohm" and not unit_token and prefix.lower() == "m":
        # Ambiguous milli vs mega — prefer milli for resistance suffixes like 100m
        return number * 1e-3, "Ohm"
    value = number * scale
    if canonical in {"V", "A", "W", "F", "H", "Hz", "s", "C", "Ohm", "m"}:
        return value, canonical
    if preferred_unit:
        return value, preferred_unit
    return value, canonical or preferred_unit


def normalize_type_token(value: object) -> str:
    text = _compact(value)
    replacements = (
        ("npn", "npn"), ("pnp", "pnp"),
        ("nchannel", "nchannel"), ("pchannel", "pchannel"),
        ("enhancement", "enhancement"), ("depletion", "depletion"),
        ("schottky", "schottky"), ("zener", "zener"), ("tvs", "tvs"),
        ("rectifier", "rectifier"), ("led", "led"),
        ("ldo", "ldo"), ("buck", "buck"), ("boost", "boost"),
    )
    for marker, token in replacements:
        if marker in text:
            return token
    return text


def compare_field_values(
    original_value: object,
    candidate_value: object,
    spec: FieldSpec,
) -> tuple[str, str]:
    """Return Match / Different / Needs data with an evidence note."""
    original_text = str(original_value or "").strip()
    candidate_text = str(candidate_value or "").strip()
    if not original_text or not candidate_text:
        return (
            "Needs data",
            "One or both values were not available from the retrieved evidence.",
        )

    mode = spec.compare
    if mode == COMPARE_MOUNTING:
        o = normalize_mounting_style(original_text)
        c = normalize_mounting_style(candidate_text)
        if o and c:
            if o == c:
                return "Match", "The retrieved mounting styles are equivalent for comparison."
            return "Different", "The retrieved mounting styles differ; engineer review is required."
        return "Needs data", "Mounting style could not be normalized from retrieved evidence."

    if mode == COMPARE_TYPE:
        o = normalize_type_token(original_text)
        c = normalize_type_token(candidate_text)
        if not o or not c:
            return "Needs data", "Type/polarity could not be normalized from retrieved evidence."
        if o == c or o in c or c in o:
            return "Match", "The retrieved type/polarity values are equivalent."
        return "Different", "The retrieved type/polarity values differ; engineer review is required."

    if mode in {COMPARE_NOMINAL, COMPARE_LIMIT_GE, COMPARE_LIMIT_LE}:
        o_num, o_unit = parse_numeric_with_unit(original_text, preferred_unit=spec.unit)
        c_num, c_unit = parse_numeric_with_unit(candidate_text, preferred_unit=spec.unit)
        if o_num is None or c_num is None:
            # Fall back to exact compact compare when parsing fails.
            if _compact(original_text) == _compact(candidate_text):
                return "Match", "The retrieved values match exactly."
            return "Different", "The retrieved values differ or use incomparable formats; engineer review is required."
        if o_unit and c_unit and o_unit != c_unit and spec.unit and o_unit != spec.unit and c_unit != spec.unit:
            return "Needs data", "Units are incomparable for this family attribute."

        if mode == COMPARE_NOMINAL:
            # Relative tolerance for floating SI equality.
            denom = max(abs(o_num), abs(c_num), 1e-30)
            if abs(o_num - c_num) / denom <= 0.02:
                return "Match", "Normalized values match within engineering tolerance."
            return "Different", "Normalized nominal values differ; engineer review is required."

        if mode == COMPARE_LIMIT_GE:
            if c_num + 1e-12 >= o_num:
                return "Match", "Candidate limit meets or exceeds the original requirement."
            return "Different", "Candidate limit is below the original requirement."

        if mode == COMPARE_LIMIT_LE:
            if c_num - 1e-12 <= o_num:
                return "Match", "Candidate limit is equal to or better than the original."
            return "Different", "Candidate limit is worse than the original requirement."

    # Default exact compare.
    if _compact(original_text) == _compact(candidate_text):
        return "Match", "The retrieved values match exactly."
    return "Different", "The retrieved values differ; engineer review is required."


_SPAN_RE = re.compile(
    r"([+-]?\d+(?:\.\d+)?)\s*v?\s*(?:~|–|—|-|to)\s*([+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_supply_span(text: object) -> tuple[float, float] | None:
    """Return the low and high ends of a supply span, in the text's voltage unit."""
    raw = str(text or "").replace("–", "-").replace("—", "-")
    match = _SPAN_RE.search(raw)
    if not match:
        return None
    low = float(match.group(1))
    high = float(match.group(2))
    if high < low:
        low, high = high, low
    return low, high


def supply_range_finding(original: object, candidate: object) -> tuple[str, str] | None:
    """Compare supply spans by coverage. A wider covering range is not a conflict."""
    original_span = parse_supply_span(original)
    candidate_span = parse_supply_span(candidate)
    if original_span is None or candidate_span is None:
        return None
    original_min, original_max = original_span
    candidate_min, candidate_max = candidate_span
    same_min = abs(candidate_min - original_min) <= 1e-9
    same_max = abs(candidate_max - original_max) <= 1e-9
    if same_min and same_max:
        return None
    covers = candidate_min <= original_min + 1e-9 and candidate_max >= original_max - 1e-9
    if covers:
        differences = []
        if candidate_max > original_max + 1e-9:
            differences.append("a wider maximum")
        if candidate_min < original_min - 1e-9:
            differences.append("a lower minimum")
        detail = " and ".join(differences) or "the same endpoints"
        return (
            "Needs review",
            "The candidate range covers the original range, with "
            f"{detail}. This is a specification difference, not a known conflict.",
        )
    return (
        "Different",
        "The candidate supply range does not cover the original range.",
    )


def _condition_label(text: object) -> str:
    folded = str(text or "").casefold()
    if "typ" in folded:
        return "typical"
    if re.search(r"\bmax(?:imum)?\b", folded):
        return "maximum"
    return ""


def bias_condition_finding(
    original: object,
    candidate: object,
    *,
    design_limit: object = None,
) -> tuple[str, str] | None:
    """A higher bias current is a review item unless it breaks an explicit design limit."""
    original_text = str(original or "").strip()
    candidate_text = str(candidate or "").strip()
    original_value, _original_unit = parse_numeric_with_unit(original_text, preferred_unit="A")
    candidate_value, _candidate_unit = parse_numeric_with_unit(candidate_text, preferred_unit="A")
    if original_value is None or candidate_value is None:
        return None
    if abs(candidate_value - original_value) <= max(abs(original_value), abs(candidate_value), 1e-30) * 0.02:
        return None
    original_condition = _condition_label(original_text)
    candidate_condition = _condition_label(candidate_text)
    if original_condition and candidate_condition and original_condition != candidate_condition:
        condition = (
            f"The original value is labeled {original_condition} and the candidate value is labeled "
            f"{candidate_condition}, so the conditions are not comparable."
        )
    elif original_condition and original_condition == candidate_condition:
        condition = f"Both values are labeled {original_condition}."
    else:
        condition = (
            "The supplier records do not state whether these are typical or maximum values, "
            "so the conditions are not confirmed to be comparable."
        )
    if candidate_value <= original_value:
        return (
            "Needs review",
            f"The candidate input bias is lower than the retrieved original value. {condition}",
        )
    limit_value = None
    limit_text = str(design_limit or "").strip()
    if limit_text and limit_text.casefold() not in {"none", "nan"}:
        limit_value, _limit_unit = parse_numeric_with_unit(limit_text, preferred_unit="A")
    if limit_value is not None and candidate_value > limit_value + 1e-15:
        return (
            "Different",
            "The candidate input bias exceeds the explicit design limit "
            f"({limit_text}). {condition}",
        )
    return (
        "Needs review",
        "The candidate has higher input bias than the retrieved original value. "
        f"{condition} This is not a confirmed design-limit conflict.",
    )


def engineering_confidence_from_rows(
    rows: list[dict[str, Any]],
    *,
    required_keys: set[str] | None = None,
    requires_pinout_for_dropin: bool = False,
) -> dict[str, Any]:
    """Score engineering completeness with required-field awareness."""
    matches = differences = needs_data = 0
    required_matches = required_missing = required_diff = 0
    pinout_status = ""
    for row in rows or []:
        status = str(row.get("Status") or "")
        key = str(row.get("Key") or "")
        label = str(row.get("Attribute") or "")
        if status == "Match":
            matches += 1
        elif status == "Different":
            differences += 1
        else:
            needs_data += 1
        is_required = bool(row.get("Required")) or (required_keys and key in required_keys)
        if is_required:
            if status == "Match":
                required_matches += 1
            elif status == "Different":
                required_diff += 1
            else:
                required_missing += 1
        if "pinout" in label.casefold() or key == "pinout":
            pinout_status = status

    compared = matches + differences + needs_data
    if differences > 0 or required_diff > 0:
        status = "conflicts documented"
    elif compared == 0:
        status = "incomplete"
    elif needs_data == 0 and matches > 0:
        status = "complete"
    elif required_missing >= 2 or (requires_pinout_for_dropin and pinout_status != "Match"):
        status = "incomplete"
    elif matches <= 1 and needs_data >= 5:
        status = "incomplete"
    elif matches >= max(1, compared - 1):
        status = "substantial"
    else:
        status = "partial"

    required_total = required_matches + required_diff + required_missing
    if compared == 0:
        confidence = 30
    elif differences > 0 or required_diff > 0:
        confidence = max(5, 50 - differences * 14 - required_diff * 10)
    elif required_total > 0:
        # Required-family coverage drives engineering confidence. Optional
        # Needs data remains visible in the matrix but does not collapse a
        # complete required-attribute match (e.g. Cap C/V/tolerance/dielectric).
        req_coverage = required_matches / required_total
        confidence = round(42 + req_coverage * 50)
        if required_missing == 0 and required_diff == 0:
            confidence = min(95, confidence + 8)
            if status == "incomplete" and not (
                requires_pinout_for_dropin and pinout_status != "Match"
            ):
                status = "substantial" if needs_data else "complete"
        else:
            confidence = min(confidence, max(15, 58 - required_missing * 12))
        if requires_pinout_for_dropin and pinout_status != "Match":
            confidence = min(confidence, 45)
            status = "incomplete"
    else:
        coverage = matches / compared
        confidence = round(30 + coverage * 55)
        if needs_data <= 1 and differences == 0:
            confidence = min(95, confidence + 8)

    confidence = max(0, min(100, int(confidence)))
    summary = (
        f"Engineering evidence: {status} — {matches} confirmed "
        f"{'match' if matches == 1 else 'matches'}, "
        f"{needs_data} {'field' if needs_data == 1 else 'fields'} need verification"
    )
    if required_missing:
        summary += f"; {required_missing} required family fields lack data"
    if requires_pinout_for_dropin and pinout_status != "Match":
        summary += "; pinout/footprint confirmation required before drop-in readiness"

    return {
        "engineering_evidence_status": status,
        "engineering_evidence_summary": summary,
        "engineering_coverage_percent": round((matches / compared) * 100) if compared else 0,
        "engineering_comparison_confidence": confidence,
        "matches": matches,
        "differences": differences,
        "needs_data": needs_data,
        "compared_fields": compared,
        "required_matches": required_matches,
        "required_missing": required_missing,
        "required_differences": required_diff,
    }
