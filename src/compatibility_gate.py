"""Conservative footprint and processor-architecture checks for alternatives.

Supplier relationship labels are not engineering fit.  This module turns
recorded package, pin-count, and architecture fields into explicit review
flags used by both Alternative Finder and Compare Parts.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from integrations.pin_count import effective_pin_count
from src.component_family_profiles import get_family_profile, infer_family_id


CRITICAL_PHYSICAL_WARNING = "CRITICAL: Physical footprint change required."
CRITICAL_FIRMWARE_WARNING = (
    "CRITICAL: Software/Firmware binary incompatible. Firmware rewrite required."
)

_BLANK = {"", "—", "-", "–", "not available", "not recorded", "n/a", "none", "nan", "unknown"}

_PACKAGE_KEYS = (
    "package", "package_case", "package / case", "case_package", "case / package",
    "supplier_device_package", "package_geometry", "package_dimensions", "footprint",
)
_PIN_KEYS = ("pin_count", "pin count", "number_of_pins", "number of pins", "pins", "pin total")
_ARCHITECTURE_KEYS = (
    "architecture", "device_family_architecture", "device family / architecture",
    "cpu_architecture", "isa", "instruction_set", "core", "core_processor",
    "core processor", "processor_family", "device_family", "device family",
)

def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in _BLANK else text


def _first(part: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _clean(part.get(key))
        if value:
            return value
    folded = {str(key).strip().casefold().replace("-", "_"): value for key, value in part.items()}
    for key in keys:
        value = _clean(folded.get(key.casefold().replace("-", "_")))
        if value:
            return value
    # Supplier responses sometimes vary only in punctuation/case.
    compact = {
        re.sub(r"[^a-z0-9]", "", str(key).casefold()): value
        for key, value in part.items()
    }
    for key in keys:
        value = _clean(compact.get(re.sub(r"[^a-z0-9]", "", key.casefold())))
        if value:
            return value
    return ""


def _pin_count(part: Mapping[str, Any], package: str) -> int:
    pin = _first(part, _PIN_KEYS)
    try:
        explicit_count = int(float(pin)) if pin else 0
    except (TypeError, ValueError):
        explicit_count = 0
    if explicit_count > 0:
        return explicit_count
    # LCC/QFP/QFN/through-hole package descriptions often encode the count
    # without the words "pin" or "pins" (for example, "52-LCC (J-Lead)").
    package_text = package.casefold()
    package_types = r"(?:lcc|plcc|qfp|tqfp|lqfp|qfn|dfn|soic|ssop|tssop|dip|pdip|bga|csp)"
    patterns = (
        rf"\b(\d{{1,3}})\s*[- ]?{package_types}\b",
        rf"\b{package_types}\s*[- ]?(\d{{1,3}})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, package_text)
        if match:
            return int(match.group(1))
    candidate = dict(part)
    candidate["pin_count"] = pin or candidate.get("pin_count") or candidate.get("Pin Count") or 0
    candidate["package"] = package or candidate.get("package") or candidate.get("Package") or ""
    return effective_pin_count(candidate)


def _package_geometry(value: str) -> tuple[str, ...]:
    # Normalize case and punctuation only. Package-size codes such as 0402
    # are ambiguous across metric/imperial systems, so do not equate them
    # without explicit dimension evidence.
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?", value.casefold())
    return tuple(sorted(tokens))


def package_document_conflicts(recorded_package: Any, documented_package: Any) -> bool:
    """Check a catalog package against a manufacturer package designation.

    Package-family aliases such as PowerSOIC and HSOIC are common across
    distributor and manufacturer descriptions. Treat the same recognized
    family and pin count as wording requiring drawing review, not as a proven
    conflict. Different families or explicit pin counts remain blockers.
    """
    recorded = _clean(recorded_package)
    documented = _clean(documented_package)
    if not recorded or not documented:
        return False
    if _package_geometry(recorded) == _package_geometry(documented):
        return False

    unit_factors = {
        "mm": 1.0,
        "cm": 10.0,
        "in": 25.4,
        "inch": 25.4,
        "inches": 25.4,
        '"': 25.4,
        "mil": 0.0254,
        "mils": 0.0254,
    }
    dimension_pattern = re.compile(
        r"(?:(?P<label_before>body\s*)?(?P<name_before>length|width|height|pitch|spacing|span|diameter)"
        r"\s*[:=]?\s*(?P<number_before>\d+(?:\.\d+)?)\s*(?P<unit_before>inches|inch|mm|cm|mils?|in|\"))"
        r"|(?:(?P<number_after>\d+(?:\.\d+)?)\s*(?P<unit_after>inches|inch|mm|cm|mils?|in|\")\s*"
        r"(?P<label_after>body\s*)?(?P<name_after>length|width|height|pitch|spacing|span|diameter)\b)",
        re.IGNORECASE,
    )

    def dimensions(value: str) -> dict[str, float]:
        output: dict[str, float] = {}
        for match in dimension_pattern.finditer(value):
            name = match.group("name_before") or match.group("name_after") or ""
            number = match.group("number_before") or match.group("number_after") or ""
            unit = (match.group("unit_before") or match.group("unit_after") or "").casefold()
            if name and number and unit in unit_factors:
                output[name.casefold()] = float(number) * unit_factors[unit]
        return output

    recorded_dimensions = dimensions(recorded)
    documented_dimensions = dimensions(documented)
    for name in set(recorded_dimensions) & set(documented_dimensions):
        left, right = recorded_dimensions[name], documented_dimensions[name]
        tolerance = max(0.01, max(abs(left), abs(right)) * 0.01)
        if abs(left - right) > tolerance:
            return True

    family_patterns = (
        ("SOIC", r"\b(?:power\s*soic|hsoic|hsop|soic)\b"),
        ("TSSOP", r"\btssop\b"),
        ("SSOP", r"\bssop\b"),
        ("MSOP", r"\bmsop\b"),
        ("QFN", r"\bqfn\b"),
        ("DFN", r"\bdfn\b"),
        ("QFP", r"\b(?:lqfp|tqfp|qfp)\b"),
        ("DIP", r"\b(?:pdip|dip)\b"),
        ("LCC", r"\b(?:plcc|lcc)\b"),
        ("BGA", r"\b(?:bga|csp)\b"),
        ("SOT", r"\bsot\b"),
        ("TO", r"\bto\s*[- ]?\s*\d+\b"),
    )

    def identity(value: str) -> tuple[str, int | None]:
        family = next(
            (name for name, pattern in family_patterns if re.search(pattern, value, re.IGNORECASE)),
            "",
        )
        pin_match = re.search(r"\b(\d{1,3})\s*[- ]?\s*pins?\b", value, re.IGNORECASE)
        if not pin_match:
            pin_match = re.search(
                r"\b(\d{1,3})\s*[- ]?\s*(?:power\s*soic|hsoic|hsop|soic|tssop|ssop|msop|qfn|dfn|lqfp|tqfp|qfp|pdip|dip|plcc|lcc|bga|csp)\b",
                value,
                re.IGNORECASE,
            )
        if not pin_match:
            pin_match = re.search(
                r"\b(?:power\s*soic|hsoic|hsop|soic|tssop|ssop|msop|qfn|dfn|lqfp|tqfp|qfp|pdip|dip|plcc|lcc|bga|csp)\s*[- ]?\s*(\d{1,3})\b",
                value,
                re.IGNORECASE,
            )
        return family, int(pin_match.group(1)) if pin_match else None

    recorded_family, recorded_pins = identity(recorded)
    documented_family, documented_pins = identity(documented)
    if recorded_family and documented_family:
        if recorded_family != documented_family:
            return True
        return bool(
            recorded_pins is not None
            and documented_pins is not None
            and recorded_pins != documented_pins
        )
    return True


def _isa_identity(value: str) -> str:
    text = value.casefold()
    patterns = (
        ("HC11", r"\b(?:(?:mc|m)?68\s*[- ]?hc\s*[- ]?11|hc\s*[- ]?11)(?!\d)"),
        ("8051", r"\b(?:mcs\s*[- ]?51|turbo\s*[- ]?51|i8051|8051|8052)\b"),
        ("RISC-V", r"\brisc\s*[- ]?v\b"),
        ("MSP430", r"\bmsp\s*[- ]?430\b"),
        ("AVR", r"\b(?:mega|tiny|xmega)?avr\b"),
        ("PIC16", r"\bpic\s*[- ]?16\w*\b"),
        ("PIC18", r"\bpic\s*[- ]?18\w*\b"),
        ("PIC", r"\bpic\b"),
        ("Z80", r"\bz80\b"),
        ("HC08", r"\bhc\s*[- ]?08\b"),
        ("ARM", r"\barm\b|\bcortex\s*[- ]?[mar]\s*[- ]?\d+\b"),
        ("MIPS", r"\bmips\b"),
    )
    for identity, pattern in patterns:
        if re.search(pattern, text):
            if identity == "ARM":
                core = re.search(r"cortex\s*[- ]?([mar])\s*[- ]?(\d+)\b", text)
                return f"ARM Cortex-{core.group(1).upper()}" if core else identity
            return identity
    return re.sub(r"[^a-z0-9]", "", text)


def _recognized_isa(value: str) -> str:
    identity = _isa_identity(value)
    recognized = {"HC11", "8051", "RISC-V", "MSP430", "AVR", "PIC16", "PIC18", "PIC", "Z80", "HC08", "ARM", "MIPS"}
    return identity if identity in recognized or identity.startswith("ARM Cortex-") else ""


def _infer_isa_from_part(part: Mapping[str, Any]) -> str:
    for key in (
        "description", "Description", "device_description", "manufacturer_part_number",
        "Manufacturer Part Number", "mpn", "MPN", "part_number",
    ):
        identity = _recognized_isa(_clean(part.get(key)))
        if identity:
            return identity
    return ""


def _architecture_value(part: Mapping[str, Any]) -> str:
    value = _first(part, _ARCHITECTURE_KEYS)
    if value:
        return value
    return _infer_isa_from_part(part)


def _architecture_is_meaningful(original: Mapping[str, Any], *values: str) -> bool:
    try:
        profile = get_family_profile(infer_family_id(dict(original)))
        family_name = str(profile.display_name or profile.id).casefold()
        if "mcu" in family_name or "processor" in family_name or "microcontroller" in family_name:
            return True
    except Exception:
        pass
    return any(_recognized_isa(value) for value in values) or bool(_infer_isa_from_part(original))


def _interface_profile(part: Mapping[str, Any]):
    from src.component_family_profiles import get_family_profile, infer_family_id

    return get_family_profile(infer_family_id(part))


def assess_part_compatibility(
    original: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Assess known physical/ISA blockers without inferring missing evidence."""
    source = dict(original or {})
    alternate = dict(candidate or {})
    source_profile = _interface_profile(source)
    candidate_profile = _interface_profile(alternate)
    # Leave the package and pin-count gate in place unless both parts are in a
    # family that explicitly uses a different mechanical interface.
    semiconductor_interface = bool(
        source_profile.uses_semiconductor_interface
        or candidate_profile.uses_semiconductor_interface
    )
    source_package = _first(source, _PACKAGE_KEYS)
    candidate_package = _first(alternate, _PACKAGE_KEYS)
    source_pins = _pin_count(source, source_package) if semiconductor_interface else 0
    candidate_pins = _pin_count(alternate, candidate_package) if semiconductor_interface else 0

    package_mismatch = bool(
        source_package
        and candidate_package
        and _package_geometry(source_package) != _package_geometry(candidate_package)
    )
    pin_mismatch = bool(source_pins and candidate_pins and source_pins != candidate_pins)
    physical_mismatch = package_mismatch or pin_mismatch
    physical_missing = []
    interface_checks: list[dict[str, str]] = []
    if semiconductor_interface:
        if not source_package or not candidate_package:
            physical_missing.append("package")
        if not source_pins or not candidate_pins:
            physical_missing.append("pin count")
        interface_checks = [
            {"label": "package / case", "source": source_package, "candidate": candidate_package},
            {
                "label": "pin count",
                "source": str(source_pins or ""),
                "candidate": str(candidate_pins or ""),
            },
        ]
    else:
        # Panel rheostats and potentiometers are not checked as IC packages.
        package_mismatch = False
        pin_mismatch = False
        physical_mismatch = False
        for label, keys in (
            ("mounting", ("mounting_style", "Mounting", "Mounting Style", "mounting")),
            ("terminal style", ("terminal_style", "Terminal style", "termination", "Termination Style")),
            ("shaft", ("shaft", "Shaft", "shaft_diameter", "Shaft Diameter")),
        ):
            source_value = _first(source, keys)
            candidate_value = _first(alternate, keys)
            interface_checks.append(
                {"label": label, "source": source_value, "candidate": candidate_value}
            )
            if not source_value or not candidate_value:
                physical_missing.append(label)
            elif _clean(source_value).casefold() != _clean(candidate_value).casefold():
                physical_mismatch = True

    source_architecture = _architecture_value(source)
    candidate_architecture = _architecture_value(alternate)
    architecture_meaningful = _architecture_is_meaningful(
        source, source_architecture, candidate_architecture
    )
    source_isa = _isa_identity(source_architecture) if source_architecture else ""
    candidate_isa = _isa_identity(candidate_architecture) if candidate_architecture else ""
    source_recognized_isa = _recognized_isa(source_architecture)
    candidate_recognized_isa = _recognized_isa(candidate_architecture)
    ambiguous_arm_detail = bool(
        source_recognized_isa
        and candidate_recognized_isa
        and source_isa != candidate_isa
        and source_isa.startswith("ARM")
        and candidate_isa.startswith("ARM")
    )
    architecture_mismatch = bool(
        architecture_meaningful
        and source_architecture
        and candidate_architecture
        and source_recognized_isa
        and candidate_recognized_isa
        and not ambiguous_arm_detail
        and source_isa != candidate_isa
    )
    architecture_missing = bool(
        architecture_meaningful
        and semiconductor_interface
        and (
            not (source_recognized_isa and candidate_recognized_isa)
            or ambiguous_arm_detail
        )
    )
    if not semiconductor_interface:
        architecture_meaningful = False
        architecture_mismatch = False
        architecture_missing = False

    critical_warnings = []
    if physical_mismatch and semiconductor_interface:
        critical_warnings.append(CRITICAL_PHYSICAL_WARNING)
    elif physical_mismatch:
        critical_warnings.append(
            "CRITICAL: The recorded mechanical interface does not match. "
            "Do not treat this as a drop-in replacement."
        )
    if architecture_mismatch:
        critical_warnings.append(CRITICAL_FIRMWARE_WARNING)

    review_warnings = []
    if physical_missing and semiconductor_interface:
        review_warnings.append(
            "Drop-in fit is unverified: package and pin-count evidence must match before approval."
        )
    elif physical_missing:
        if len(physical_missing) == 1:
            missing_text = physical_missing[0]
        elif len(physical_missing) == 2:
            missing_text = f"{physical_missing[0]} and {physical_missing[1]}"
        else:
            missing_text = ", ".join(physical_missing[:-1]) + ", and " + physical_missing[-1]
        review_warnings.append(
            "Drop-in fit is unverified: "
            f"{missing_text} evidence must be cited from the datasheet or manufacturer record before approval."
        )
    if architecture_missing:
        review_warnings.append(
            "Processor architecture/ISA is not confirmed for both parts; firmware compatibility is unverified."
        )

    requires_acknowledgement = bool(review_warnings) and not physical_mismatch and not architecture_mismatch
    blocked_from_drop_in_approval = physical_mismatch or architecture_mismatch
    if blocked_from_drop_in_approval:
        drop_in_status = "Not a drop-in replacement"
    elif requires_acknowledgement:
        drop_in_status = "Not verified — engineering review required"
    elif architecture_meaningful:
        drop_in_status = "Package, pin count, and processor family match; pinout/electrical review still required"
    elif not semiconductor_interface:
        drop_in_status = (
            "Recorded mechanical interface matches; electrical and remaining datasheet review still required"
        )
    else:
        drop_in_status = "Package and pin count match; electrical review still required"

    return {
        "source_package": source_package,
        "candidate_package": candidate_package,
        "source_pin_count": source_pins or None,
        "candidate_pin_count": candidate_pins or None,
        "package_mismatch": package_mismatch,
        "pin_count_mismatch": pin_mismatch,
        "physical_mismatch": physical_mismatch,
        "physical_missing": physical_missing,
        "pin_count_applicable": semiconductor_interface,
        "package_applicable": semiconductor_interface,
        "interface_checks": interface_checks,
        "source_architecture": source_architecture,
        "candidate_architecture": candidate_architecture,
        "architecture_meaningful": architecture_meaningful,
        "architecture_mismatch": architecture_mismatch,
        "architecture_missing": architecture_missing,
        "critical_warnings": critical_warnings,
        "review_warnings": review_warnings,
        "requires_acknowledgement": requires_acknowledgement,
        "blocked_from_drop_in_approval": blocked_from_drop_in_approval,
        "drop_in_status": drop_in_status,
    }


def comparison_row_part_values(rows: list[dict[str, Any]], slot: str) -> dict[str, str]:
    """Build a compatibility-only part mapping from a side-by-side matrix."""
    result: dict[str, str] = {}
    if slot not in {"Part A", "Part B", "Part C"}:
        return result
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        label = _clean(row.get("Attribute") or row.get("label")).casefold()
        if not label:
            continue
        value = _clean(row.get(slot))
        if value.casefold() in {
            "not stated in retrieved evidence",
            "not stated in this datasheet",
            "not available",
            "not found",
            "not recorded",
            "lifecycle conflict — underlying supplier records were not retained",
        }:
            continue
        if label in {"package", "package / case", "case package", "package/case"}:
            result["package"] = value
        elif label in {"pin count", "number of pins", "pins"}:
            result["pin_count"] = value
        elif "architecture" in label or label in {"device family", "core"}:
            result["architecture"] = value
        elif "lifecycle" in label or "product status" in label:
            result["lifecycle_status"] = value
        elif label in {"mounting", "mounting style"}:
            result["mounting_style"] = value
        elif label in {"terminal style", "termination", "termination style"}:
            result["terminal_style"] = value
        elif label in {"shaft", "shaft diameter", "shaft length"}:
            result["shaft"] = value
    return result

