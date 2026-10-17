Warning: truncated output (original token count: 82339)
Total output lines: 6360

"""Approved page bodies for the Cadivor mockups.

Live workspace records fill the layout. Sample names from the mockups are not
invented when the workspace has different BOMs.
"""

from __future__ import annotations

import html
import hashlib
import io
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

from src.bom_upload_flow import (
    prepare_new_approved_bom_analysis,
    should_render_approved_bom_upload_form,
    should_stop_approved_bom_renderer,
)
from src.saved_bom_project import (
    NEW_PROJECT_CHOICE,
    analysis_title_for_upload,
    assign_project,
    project_choices,
    resolve_project_choice,
    split_project_and_bom,
)
from src.ui.cadivor_design_system.icons import lucide
from src.compatibility_gate import (
    CRITICAL_FIRMWARE_WARNING,
    CRITICAL_PHYSICAL_WARNING,
    assess_part_compatibility,
    comparison_row_part_values,
    package_document_conflicts,
)
from src.ui.navigation import (
    internal_nav_button,
    navigate_to,
    navigate_to_alternative_finder,
)


PROJECT_ICON = (
    '<span class="cv-ap-project-icon" aria-hidden="true">'
    f"{lucide('layers', 22)}"
    "</span>"
)

SAVED_BOM_EDIT_STATE = "approved_saved_bom_edit_id"
SAVED_BOM_DELETE_STATE = "approved_saved_bom_delete_id"
SAVED_BOM_EDIT_REVISION_STATE = "approved_saved_bom_edit_revision"


DOC = (
    '<svg class="cv-ap-chip" width="28" height="28" viewBox="0 0 32 32" aria-hidden="true" '
    'style="width:28px;height:28px;display:inline-block;vertical-align:middle;margin-right:8px">'
    '<rect width="32" height="32" rx="8" fill="#eef2ff"/>'
    '<path d="M10 8h8l4 4v12H10z" fill="#fff" stroke="#2563eb" stroke-width="1.4"/>'
    '<path d="M18 8v4h4" fill="none" stroke="#2563eb" stroke-width="1.4"/>'
    "</svg>"
)


def part_mark(seed: str = "") -> str:
    """Illustration for a live part. The workspace does not store product photos."""
    text = str(seed or "").casefold()
    if any(token in text for token in ("cap", "grm", "ceramic", "murata")):
        body = (
            '<rect x="8" y="14" width="32" height="20" rx="3" fill="#d6d3d1"/>'
            '<rect x="14" y="18" width="20" height="12" rx="1" fill="#a8a29e"/>'
            '<path d="M12 14v-6M36 14v-6" stroke="#78716c" stroke-width="2"/>'
        )
    elif any(token in text for token in ("reg", "tps", "buck", "converter")):
        body = (
            '<rect x="10" y="12" width="28" height="28" rx="4" fill="#1e293b"/>'
            '<circle cx="24" cy="26" r="6" fill="#334155"/>'
            '<path d="M16 12v-4M24 12v-4M32 12v-4M16 40v4M24 40v4M32 40v4" stroke="#94a3b8" stroke-width="2"/>'
        )
    else:
        body = (
            '<rect x="12" y="14" width="24" height="24" rx="2" fill="#0f172a"/>'
            '<path d="M16 14v-5M22 14v-5M26 14v-5M32 14v-5M16 38v5M22 38v5M26 38v5M32 38v5" stroke="#64748b" stroke-width="1.6"/>'
            '<path d="M12 20h-4M12 26h-4M12 32h-4M36 20h4M36 26h4M36 32h4" stroke="#64748b" stroke-width="1.6"/>'
        )
    return (
        '<svg class="cv-ap-chip" width="42" height="42" viewBox="0 0 48 48" aria-hidden="true" '
        'style="width:42px;height:42px;display:inline-block;vertical-align:middle;margin-right:8px">'
        f'<rect width="48" height="48" rx="10" fill="#f8fafc"/>{body}</svg>'
    )


CHIP = (
    '<svg class="cv-ap-chip" width="36" height="36" viewBox="0 0 48 48" aria-hidden="true" '
    'style="width:36px;height:36px;display:inline-block;vertical-align:middle">'
    '<rect width="48" height="48" rx="10" fill="#eef2ff"/>'
    '<rect x="16" y="16" width="16" height="16" rx="2" fill="#334155"/>'
    '<path d="M20 10v6M28 10v6M20 32v6M28 32v6M10 20h6M10 28h6M32 20h6M32 28h6" stroke="#64748b" stroke-width="2"/>'
    "</svg>"
)


def _esc(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return fallback
    return html.escape(text)


def _num(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _first(row: dict[str, Any], *keys: str, fallback: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() not in {"", "nan", "None"}:
            return value
    return fallback


def _candidate_mpn(row: dict[str, Any]) -> str:
    """Read the supplier candidate part number. Blank means the row is not a part."""
    for key in (
        "Alternative Part",
        "mpn",
        "MPN",
        "alternative_mpn",
        "manufacturer_part_number",
        "part_number",
        "Part Number",
    ):
        text = str(row.get(key) or "").strip()
        if text and text.casefold() not in {"nan", "none", "—", "-"}:
            return text
    return ""


def _candidate_field(row: dict[str, Any], *keys: str, fallback: str = "—") -> str:
    for key in keys:
        if key not in row or row.get(key) is None:
            continue
        text = str(row.get(key)).strip()
        if not text or text.casefold() in {"nan", "none"}:
            continue
        return html.escape(text)
    return fallback


def _candidate_stock(row: dict[str, Any]) -> int:
    for key in ("Stock", "stock_total", "stock_available"):
        if key in row and row.get(key) not in (None, ""):
            return _num(row.get(key))
    return 0


_CANDIDATE_BLANK = {
    "", "—", "-", "–", "nan", "none", "n/a", "not available", "not recorded",
    "not found", "unknown", "unavailable", "null",
}


def _candidate_recorded(row: dict[str, Any], *keys: str, missing: str = "Not recorded") -> str:
    for key in keys:
        if key not in row or row.get(key) is None:
            continue
        text = str(row.get(key)).strip()
        if text and text.casefold() not in _CANDIDATE_BLANK:
            return text
    return missing


def _candidate_http_url(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower().startswith(("https://", "http://")):
        return text
    return ""


def _part_field(part: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key not in part or part.get(key) is None:
            continue
        if key in {"pin_count", "channel_count", "Pin Count"}:
            try:
                number = int(float(part.get(key)))
            except (TypeError, ValueError):
                continue
            if number <= 0:
                continue
            return str(number)
        text = str(part.get(key)).strip()
        if text and text.casefold() not in _CANDIDATE_BLANK and text not in {"0", "0.0"}:
            return text
    return ""


def _field_source(part: dict[str, Any], key: str, fallback: str = "") -> str:
    sources = part.get("field_sources") if isinstance(part.get("field_sources"), dict) else {}
    source = str(sources.get(key) or fallback or part.get("source") or "").strip()
    return source


def _finding_label(status: str, original: str, candidate: str, evidence: str = "") -> tuple[str, str]:
    note = str(evidence or "").strip()
    if original and candidate and status == "Match":
        if note and "match exactly" not in note.casefold() and "equivalent" not in note.casefold():
            return "Compatible", f"{note} This is not an approval to use the part."
        return "Compatible", "The retrieved values match. This is not an approval to use the part."
    if original and candidate and status == "Different":
        return "Known conflict", note or "The retrieved values differ. Review this difference before use."
    if original and candidate and status == "Needs review":
        return (
            "Needs review",
            note or "Both values were retrieved and they differ. This is not proof of electrical fit.",
        )
    if not original and not candidate:
        return "Unknown", "Neither supplier record included this attribute."
    missing = "original" if not original else "candidate"
    return "Needs review", f"The {missing} record does not include this attribute, so fit cannot be confirmed."


def _value_cell(value: str, source: str, note: str = "") -> str:
    if not value:
        shown = "Unknown"
        detail = note or "Not in the retrieved supplier record."
    else:
        shown = value
        detail = source or "Supplier record"
    extra = f"<small>{_esc(detail)}</small>"
    if note and value:
        extra += f"<small>{_esc(note)}</small>"
    return f"<div>{_esc(shown)}{extra}</div>"


def _candidate_part_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": _part_field(row, "description", "Description"),
        "manufacturer": _part_field(row, "Manufacturer", "manufacturer"),
        "package": _part_field(row, "package", "Package", "Package / Case", "package_case"),
        "pin_count": _first(
            row,
            "pin_count",
            "Pin Count",
            "Number of Pins",
            "number_of_pins",
            "pins",
            fallback=0,
        ),
        "mounting_style": _part_field(row, "mounting_style", "Mounting Style"),
        "voltage_range": _part_field(row, "voltage_range", "Voltage Range"),
        "temperature_range": _part_field(row, "temperature_range", "Temperature Range"),
        "channel_count": row.get("channel_count") or row.get("Channel Count") or 0,
        "architecture": _part_field(
            row,
            "architecture",
            "Architecture",
            "Device family / architecture",
            "device_family_architecture",
            "device_family",
            "core",
            "ISA",
        ),
        "lifecycle_status": _part_field(row, "Lifecycle", "lifecycle_status"),
        "stock_total": row.get("Stock", row.get("stock_total")),
        "unit_price": row.get("unit_price", row.get("Unit Price")),
        "lead_time_weeks": row.get("lead_time_weeks"),
        "bandwidth_mhz": row.get("bandwidth_mhz"),
        "slew_rate_v_us": row.get("slew_rate_v_us"),
        "input_offset_mv": row.get("input_offset_mv"),
        "input_bias_na": row.get("input_bias_na"),
        "quiescent_current_ma": row.get("quiescent_current_ma"),
        "gbw_mhz": row.get("gbw_mhz"),
        "source": _part_field(row, "Supplier", "source") or "DigiKey",
        "datasheet_url": _first(
            row,
            "datasheet_url",
            "Datasheet URL",
            "datasheetUrl",
            "Data Sheet URL",
            fallback="",
        ),
        "field_sources": row.get("field_sources") if isinstance(row.get("field_sources"), dict) else {},
        "manufacturer_part_number": _candidate_mpn(row),
    }


def _comparison_table(
    rows: list[tuple], compatibility: dict[str, Any] | None = None
) -> str:
    compatibility = compatibility if isinstance(compatibility, dict) else {}
    critical_keys = set()
    if compatibility.get("package_mismatch"):
        critical_keys.add("package")
    if compatibility.get("pin_count_mismatch"):
        critical_keys.add("pin count")
    if compatibility.get("architecture_mismatch"):
        critical_keys.add("architecture")
    body = []
    for row in rows:
        label, original, original_source, candidate, candidate_source, status = row[:6]
        note = row[6] if len(row) > 6 else ""
        evidence = row[7] if len(row) > 7 else ""
        finding, why = _finding_label(status, original, candidate, evidence)
        if finding == "Unknown":
            why = (
                f"{label} was not in either supplier record. "
                "Check the datasheet or product page before treating it as a match."
            )
        kind = {
            "Compatible": "compatible",
            "Needs review": "review",
            "Known conflict": "conflict",
        }.get(finding, "unknown")
        normalized_label = str(label or "").casefold()
        critical = (
            ("package" in critical_keys and "package" in normalized_label)
            or (
                "pin count" in critical_keys
                and normalized_label in {"pin count", "number of pins", "pins"}
            )
            or (
                "architecture" in critical_keys
                and (
                    "architecture" in normalized_label
                    or "device family" in normalized_label
                    or normalized_label in {"core", "instruction set"}
                )
            )
        )
        if critical:
            kind = "critical"
        row_class = " class='cv-compat-critical-row'" if critical else ""
        body.append(
            f"<tr{row_class}>"
            f"<td>{_esc(label)}</td>"
            f"<td>{_value_cell(original, original_source, note)}</td>"
            f"<td>{_value_cell(candidate, candidate_source)}</td>"
            f"<td><span class='cv-finding {kind}'>{_esc(finding)}</span><small>{_esc(why)}</small></td>"
            "</tr>"
        )
    return (
        "<table class='cv-candidate-compare'><thead><tr>"
        "<th>Attribute</th><th>Original</th><th>Candidate</th><th>Finding</th>"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def _candidate_detail_html(row: dict[str, Any], original: dict[str, Any] | None = None) -> str:
    """Compare one candidate with the original using retrieved supplier evidence."""
    from src.datasheet_comparison import build_datasheet_comparison
    from src.risk_engine import recorded_supply_factors

    original = original if isinstance(original, dict) else {}
    candidate = _candidate_part_payload(row)
    compatibility = assess_part_compatibility(original, candidate)
    mpn = _candidate_mpn(row)
    original_mpn = _part_field(original, "manufacturer_part_number", "mpn") or "Original"
    classification = _part_field(row, "Classification", "Category")
    verified = classification == "Verified direct substitute"
    comparison = build_datasheet_comparison(original, candidate)
    technical = []
    for item in comparison.get("rows") or []:
        key = str(item.get("Key") or "")
        if key == "lifecycle_status":
            continue
        label = str(item.get("Attribute") or key)
        original_value = str(item.get("Original") or "")
        candidate_value = str(item.get("Candidate") or "")
        if original_value.casefold() in _CANDIDATE_BLANK or original_value.casefold() == "not available":
            original_value = ""
        if candidate_value.casefold() in _CANDIDATE_BLANK or candidate_value.casefold() == "not available":
            candidate_value = ""
        status = str(item.get("Status") or "")
        evidence = str(item.get("Evidence") or "")
        if key == "package" and compatibility.get("package_mismatch"):
            original_value = str(compatibility.get("source_package") or original_value)
            candidate_value = str(compatibility.get("candidate_package") or candidate_value)
        if key == "pin_count" and compatibility.get("pin_count_mismatch"):
            original_value = str(compatibility.get("source_pin_count") or original_value)
            candidate_value = str(compatibility.get("candidate_pin_count") or candidate_value)
        if key == "architecture" and compatibility.get("architecture_mismatch"):
            original_value = str(compatibility.get("source_architecture") or original_value)
            candidate_value = str(compatibility.get("candidate_architecture") or candidate_value)
        if key == "architecture" and status == "Different" and original_value and candidate_value:
            if compatibility.get("architecture_mismatch"):
                evidence = CRITICAL_FIRMWARE_WARNING
            else:
                status = "Needs review"
                evidence = "The supplier category labels differ. This is not a verified functional conflict."
        if key == "package" and compatibility.get("package_mismatch"):
            status = "Different"
            evidence = CRITICAL_PHYSICAL_WARNING
        if key == "pin_count" and compatibility.get("pin_count_mismatch"):
            status = "Different"
            evidence = CRITICAL_PHYSICAL_WARNING
        if key == "voltage_range" and original_value and candidate_value:
            from src.parametric_compare import supply_range_finding

            covered = supply_range_finding(original_value, candidate_value)
            if covered:
                status, evidence = covered
        if key == "input_bias_na" and original_value and candidate_value:
            from src.parametric_compare import bias_condition_finding

            judged = bias_condition_finding(
                original_value,
                candidate_value,
                design_limit=original.get("input_bias_design_limit")
                or original.get("design_limit_input_bias"),
            )
            if judged:
                status, evidence = judged
        if key == "temperature_range" and original_value and candidate_value:
            import re

            stripped = [
                re.sub(r"\s*\([^)]*\)", "", value).strip()
                for value in (original_value, candidate_value)
            ]
            if stripped[0].casefold() == stripped[1].casefold():
                status = "Match"
                evidence = "The temperature ranges match. A parenthetical note such as (TA) is the measurement condition, not a second limit."
        notes = original.get("field_source_notes") if isinstance(original.get("field_source_notes"), dict) else {}
        technical.append((
            label,
            original_value,
            _field_source(original, key),
            candidate_value,
            _field_source(candidate, key, candidate.get("source") or "DigiKey"),
            status,
            str(notes.get(key) or ""),
            evidence,
        ))
    # Some supplier matrices omit identity fields even when the returned part
    # records contain them. Keep a critical mismatch visible in the detail table.
    present_labels = {str(item[0] or "").casefold() for item in technical}
    present_keys = set(present_labels)
    if any("package" in item for item in present_labels):
        present_keys.add("package")
    if any("pin count" in item or "number of pins" in item for item in present_labels):
        present_keys.add("pin count")
    if any("architecture" in item or "device family" in item for item in present_labels):
        present_keys.add("architecture")
    for key, label, left, right, mismatch, evidence in (
        (
            "package",
            "Package",
            compatibility.get("source_package"),
            compatibility.get("candidate_package"),
            compatibility.get("package_mismatch"),
            CRITICAL_PHYSICAL_WARNING,
        ),
        (
            "pin count",
            "Pin count",
            compatibility.get("source_pin_count"),
            compatibility.get("candidate_pin_count"),
            compatibility.get("pin_count_mismatch"),
            CRITICAL_PHYSICAL_WARNING,
        ),
        (
            "architecture",
            "Device family / architecture",
            compatibility.get("source_architecture"),
            compatibility.get("candidate_architecture"),
            compatibility.get("architecture_mismatch"),
            CRITICAL_FIRMWARE_WARNING,
        ),
    ):
        if mismatch and key not in present_keys:
            technical.append(
                (
                    label,
                    str(left or ""),
                    _field_source(original, key),
                    str(right or ""),
                    _field_source(candidate, key, candidate.get("source") or "Supplier record"),
                    "Different",
                    "",
                    evidence,
                )
            )
    conflicts = [
        item[0]
        for item in technical
        if _finding_label(item[5], item[1], item[3], item[7] if len(item) > 7 else "")[0] == "Known conflict"
    ]
    if conflicts:
        fit = (
            "Technical fit is not established. Known conflicts: "
            + ", ".join(conflicts)
            + ". Part-number or family similarity is not compatibility evidence."
        )
    else:
        fit = (
            "Technical fit is not established. No retrieved attribute was a known conflict, "
            "but missing evidence still has to be checked. Part-number or family similarity "
            "is not compatibility evidence."
        )
    if verified:
        relationship = (
            "The supplier recorded this as a verified direct substitute. "
            "That relationship is not an approval to use the part."
        )
    else:
        relationship = "Compatibility is not verified."
        if classification:
            relationship += f" Supplier classification: {classification}."
    recommendation = _part_field(row, "Recommendation")
    next_step = recommendation or "Check the datasheet, footprint, and qualification before use."

    supply_rows = []
    supply_specs = (
        ("Manufacturer", "manufacturer", "manufacturer"),
        ("Lifecycle", "lifecycle_status", "lifecycle_status"),
        ("Stock", "stock_total", "stock_total"),
        ("Lead time", "lead_time_weeks", "lead_time_weeks"),
        ("Unit price", "unit_price", "unit_price"),
        ("Distributor", "source", "source"),
    )
    for label, original_key, candidate_key in supply_specs:
        original_value = _part_field(original, original_key)
        candidate_value = _part_field(candidate, candidate_key)
        if original_key == "stock_total" and original.get("stock_total") not in (None, ""):
            original_value = f"{_num(original.get('stock_total')):,}"
        if candidate_key == "stock_total" and candidate.get("stock_total") not in (None, ""):
            candidate_value = f"{_num(candidate.get('stock_total')):,}"
        if original_key == "lead_time_weeks" and _evidence_number(original.get("lead_time_weeks")):
            original_value = f"{original.get('lead_time_weeks')} weeks"
        if candidate_key == "lead_time_weeks" and _evidence_number(candidate.get("lead_time_weeks")):
            candidate_value = f"{candidate.get('lead_time_weeks')} weeks"
        if original_key == "unit_price" and _evidence_number(original.get("unit_price"), positive=True):
            original_value = f"${float(original.get('unit_price')):.4f}".rstrip("0").rstrip(".")
        if candidate_key == "unit_price" and _evidence_number(candidate.get("unit_price"), positive=True):
            candidate_value = f"${float(candidate.get('unit_price')):.4f}".rstrip("0").rstrip(".")
        status = "Match" if original_value and candidate_value and original_value.casefold() == candidate_value.casefold() else "Different"
        if label in {"Stock", "Unit price", "Distributor", "Manufacturer", "Lead time"} and original_value and candidate_value and status == "Different":
            status = "Needs review"
        supply_evidence = ""
        if label == "Lead time" and status == "Needs review":
            supply_evidence = (
                "Both records include a lead time. The difference is schedule evidence, "
                "not electrical compatibility."
            )
        elif label == "Lifecycle" and status == "Different":
            supply_evidence = (
                "Lifecycle status differs. This is supply evidence and is separate from electrical fit."
            )
        supply_rows.append((
            label,
            original_value,
            _field_source(original, original_key, str(original.get("source") or "")),
            candidate_value,
            _field_source(candidate, candidate_key, str(candidate.get("source") or "")),
            status,
            "",
            supply_evidence,
        ))

    factors = recorded_supply_factors({
        "lifecycle_status": candidate.get("lifecycle_status"),
        "stock_total": candidate.get("stock_total"),
        "lead_time_weeks": candidate.get("lead_time_weeks"),
        "source": candidate.get("source") or "DigiKey",
        "quantity": 0,
    })
    factor_html = []
    applied_points = 0
    for factor in factors:
        reasons = factor["reasons"] or ["Cadivor's recorded-data rules did not add a penalty for this value."]
        if factor["factor"] == "Stock" and not factor["reasons"]:
            reasons = ["No BOM quantity was supplied, so shortage rules were not applied."]
        applied_points += int(factor["points"])
        factor_html.append(
            f"<li><strong>{_esc(factor['factor'])}:</strong> {_esc(factor['recorded'])} "
            f"({_esc(factor['source'] or 'Supplier')}). {_esc(' '.join(reasons))}</li>"
        )
    if candidate.get("lead_time_weeks") in (None, ""):
        factor_html.append(
            "<li><strong>Lead time:</strong> Unknown. DigiKey's manufacturer lead time was not in this record. "
            "Use the product page or datasheet before judging schedule risk.</li>"
        )
    factor_html.append(
        "<li><strong>Supplier diversity:</strong> Unknown. This row is one distributor listing, "
        "not a manufacturer source count, so Cadivor's single-source rule was not applied.</li>"
    )
    risk_html = (
        "<p>Supply and lifecycle risk is separate from technical fit. "
        f"Recorded-factor points under Cadivor's existing rules: {applied_points}. "
        "Rules without evidence were not scored.</p>"
        f"<ul>{''.join(factor_html)}</ul>"
    )
    links = _detail_links(original, row)
    return (
        f'<div class="cv-candidate-detail" data-candidate-mpn="{_esc(mpn)}">'
        f'<p class="cv-candidate-title">{_esc(mpn)} compared with {_esc(original_mpn)}</p>'
        f"<p class='cv-candidate-unverified'>{_esc(relationship)} {_esc(fit)}</p>"
        f"{_compatibility_banner_html(compatibility)}"
        "<p class='cv-candidate-section'>Does it technically fit?</p>"
        f"{_comparison_table(technical, compatibility)}"
        "<p class='cv-candidate-section'>Supply and lifecycle risk</p>"
        f"{_comparison_table(supply_rows)}"
        f"{risk_html}"
        f"<p><strong>Next step.</strong> {_esc(next_step)}</p>"
        f"<p class='cv-candidate-links'>{links}</p>"
        "</div>"
    )


def _compatibility_banner_html(compatibility: dict[str, Any] | None) -> str:
    """Render prominent compatibility blockers and missing-evidence gates."""
    compatibility = compatibility if isinstance(compatibility, dict) else {}
    critical = list(compatibility.get("critical_warnings") or [])
    review = list(compatibility.get("review_warnings") or [])
    if critical:
        return (
            "<div class='cv-compat-banner critical' role='alert'>"
            "<strong>CRITICAL COMPATIBILITY BLOCK — NOT A DROP-IN REPLACEMENT</strong>"
            f"<ul>{''.join(f'<li>{_esc(item)}</li>' for item in critical)}</ul>"
            "<span>Do not approve this candidate as a drop-in replacement. A physical redesign and/or firmware rewrite may be required.</span>"
            "</div>"
        )
    if review:
        return (
            "<div class='cv-compat-banner review' role='status'>"
            "<strong>DROP-IN COMPATIBILITY NOT VERIFIED</strong>"
            f"<ul>{''.join(f'<li>{_esc(item)}</li>' for item in review)}</ul>"
            "</div>"
        )
    return (
        "<div class='cv-compat-banner review' role='status'>"
        "<strong>Engineering review required</strong>"
        f"<span>{_esc(compatibility.get('drop_in_status') or 'Electrical fit and pinout still require engineering review.')}</span>"
        "</div>"
    )


def _evidence_number(value: Any, positive: bool = False) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number > 0 if positive else True


def _detail_links(original: dict[str, Any], row: dict[str, Any]) -> str:
    links = []
    for label, source in (
        (f"{_part_field(original, 'manufacturer_part_number') or 'Original'} product page", original),
        (f"{_candidate_mpn(row)} product page", row),
        (f"{_candidate_mpn(row)} datasheet", row),
    ):
        url = ""
        for key in ("product_detail_url", "Product URL", "Source URL", "datasheet_url", "Datasheet URL"):
            if "datasheet" in label.casefold() and "data" not in key.casefold() and "Datasheet" not in key:
                continue
            if "product page" in label.casefold() and "data" in key.casefold():
                continue
            url = _candidate_http_url(source.get(key) if isinstance(source, dict) else "")
            if url:
                break
        if url and url not in {item[1] for item in links}:
            links.append((label, url))
    if not links:
        return "No supplier or datasheet link was recorded."
    return " ".join(
        f'<a href="{html.escape(url, quote=True)}" rel="noopener noreferrer">{_esc(label)}</a>'
        for label, url in links
    )


def begin_approved_page() -> None:
    st.markdown(
        """
        <style data-cadivor-layout-style="true">
        .cv-ap{color:#0f172a;font-family:Inter,"Segoe UI",sans-serif}
        .cv-ap-kicker{margin:0 0 6px;color:#64748b;font-size:12px;font-weight:700;letter-spacing:.08em}
        .cv-ap h1{margin:0 0 6px;font-size:32px;line-height:1.15;letter-spacing:-.03em}
        .cv-ap-sub{margin:0 0 18px;color:#64748b;font-size:14px}
        .cv-ap-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 18px}
        .cv-ap-kpis.three{grid-template-columns:repeat(3,minmax(0,1fr))}
        .cv-ap-kpis.five{grid-template-columns:repeat(5,minmax(0,1fr))}
        .cv-ap-kpi{background:#fff;border:1px solid #e6edf5;border-radius:16px;padding:12px 14px;min-height:92px}
        .cv-ap-kpi-top{display:flex;align-items:center;gap:8px}
        .cv-ap-kpi-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
        .cv-ap-ico{width:40px;height:40px;border-radius:12px;display:inline-flex;align-items:center;justify-content:center;background:#eff6ff;flex:0 0 40px}
        .cv-ap-ico svg{width:20px;height:20px;display:block}
        .cv-ap-ico.warn{background:#fff7ed}
        .cv-ap-ico.risk{background:#fff1f2}
        .cv-ap-ico.ok{background:#ecfdf5}
        .cv-ap-project{display:flex;align-items:center;gap:10px;min-height:40px}
        .cv-ap-project-icon{width:40px;height:40px;flex:0 0 40px;display:inline-flex;align-items:center;justify-content:center;border-radius:10px;background:#eef2ff;color:#2563eb}
        .cv-ap-project-icon svg{width:22px;height:22px;display:block;stroke:#2563eb}
        .cv-ed-queue{border:1px solid #e6edf5;border-radius:16px;background:#fff;padding:14px 14px 6px;margin-top:8px}
        .cv-ed-queue h2{margin:0;font-size:16px}
        .cv-pill.review{background:#ede9fe;color:#6d28d9}
        [class*="st-key-approved_home_open_"] button,
        [class*="st-key-approved_bom_row_open_"] button{
          background:#f1f5f9 !important;background-color:#f1f5f9 !important;color:#2563eb !important;
          border:1px solid #e2e8f0 !important;border-radius:8px !important;
          min-height:32px !important;height:32px !important;min-width:0 !important;width:auto !important;
          padding:0 14px !important;font-weight:700 !important;box-shadow:none !important;outline:none
        }
        [class*="st-key-approved_home_open_"] button *,
        [class*="st-key-approved_bom_row_open_"] button *{
          background:transparent !important;border:0 !important;box-shadow:none !important;
          color:#2563eb !important;height:auto !important;min-height:0 !important;padding:0 !important
        }
        [class*="st-key-approved_home_open_"] button:focus-visible,
        [class*="st-key-approved_bom_row_open_"] button:focus-visible,
        [class*="st-key-approved_decision_record_"] button:focus-visible{
          outline:2px solid #2563eb !important;outline-offset:2px !important;box-shadow:none !important
        }
        [class*="st-key-approved_decision_record_"] button{
          background:#fff !important;color:#2563eb !important;border:1px solid #bfdbfe !important;
          border-radius:8px !important;min-height:32px !important;height:32px !important;
          min-width:0 !important;width:auto !important;padding:0 12px !important;font-weight:700 !important;
          box-shadow:none !important;outline:none
        }
        [class*="st-key-approved_decision_record_"] button *{
          background:transparent !important;border:0 !important;box-shadow:none !important;
          color:#2563eb !important;height:auto !important;min-height:0 !important;padding:0 !important
        }
        [class*="st-key-approved_home_menu_"] [data-testid="stPopover"] > button,[class*="st-key-approved_bom_menu_"] [data-testid="stPopover"] > button,[class*="st-key-approved_report_menu_"] [data-testid="stPopover"] > button,[class*="st-key-approved_decision_menu_"] [data-testid="stPopover"] > button{width:32px!important;min-width:32px!important;max-width:32px!important;height:32px!important;min-height:32px!important;padding:0!important;border-radius:8px!important}
        [class*="st-key-approved_home_menu_"] [data-testid="stPopover"] > button svg,[class*="st-key-approved_bom_menu_"] [data-testid="stPopover"] > button svg,[class*="st-key-approved_report_menu_"] [data-testid="stPopover"] > button svg,[class*="st-key-approved_decision_menu_"] [data-testid="stPopover"] > button svg{display:none!important}
        [class*="st-key-approved_home_row_"],[class*="st-key-approved_bom_row_"],[class*="st-key-approved_report_row_"]{border-top:1px solid #eef2f7;padding:0;margin:0}
        [class*="st-key-approved_settings_screen"] h1{font-size:28px;margin:0 0 8px}
        [class*="st-key-approved_settings_screen"] [data-testid="stForm"]{border:0;padding:0}
        [class*="st-key-approved_settings_screen"] [data-testid="stVerticalBlock"]{gap:0.4rem}
        .cv-ap-kpi span{display:block;color:#64748b;font-size:13px;font-weight:650}
        .cv-ap-kpi strong{display:block;margin-top:8px;font-size:28px;letter-spacing:-.03em}
        .cv-ap-kpi em{display:block;margin-top:4px;font-style:normal;font-size:12px;color:#16a34a}
        .cv-ap-kpi em.down{color:#e11d48}
        .cv-ap-kpi em.muted{color:#94a3b8}
        .cv-ap-card{background:#fff;border:1px solid #e6edf5;border-radius:16px;padding:8px 8px 4px;margin-bottom:12px}
        .cv-ap-table{width:100%;border-collapse:separate;border-spacing:0}
        .cv-ap-table th{text-align:left;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#94a3b8;padding:8px 10px}
        .cv-ap-table td{padding:8px 10px;border-top:1px solid #eef2f7;font-size:13px;vertical-align:middle}
        .cv-ap-table td.cv-compare-compat-critical{background:#fff1f2!important;color:#991b1b!important;font-weight:800;border-top-color:#fecdd3!important}
        .cv-ap-table td.cv-compare-diff{background:#eff6ff;color:#1d4ed8}
        .cv-part-photo{box-sizing:border-box;flex:0 0 var(--cv-part-photo-size,72px);width:var(--cv-part-photo-size,72px);height:var(--cv-part-photo-size,72px);border-radius:12px;background:#f1f5f9;border:1px solid #e2e8f0;display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;overflow:hidden;margin-right:10px;color:#64748b}
        .cv-part-photo img{display:block;width:100%;height:100%;padding:4px;box-sizing:border-box;object-fit:contain}
        .cv-part-photo__placeholder{display:flex;width:100%;height:100%;align-items:center;justify-content:center}
        .cv-part-photo__placeholder svg{display:block;width:62%;height:62%}
        .cv-part-photo[data-illustration="generic"]{background:#f0f9ff;border-color:#bae6fd;color:#0369a1}
        .cv-part-photo[data-illustration="ic"]{background:#eff6ff;border-color:#dbeafe;color:#2563eb}
        .cv-part-photo[data-illustration="capacitor"]{background:#f5f3ff;border-color:#e9d5ff;color:#7c3aed}
        .cv-part-photo[data-illustration="resistor"]{background:#fff7ed;border-color:#fed7aa;color:#c2410c}
        .cv-part-photo[data-illustration="inductor"]{background:#f0fdfa;border-color:#ccfbf1;color:#0f766e}
        .cv-part-photo[data-illustration="connector"]{background:#ecfeff;border-color:#cffafe;color:#0e7490}
        .cv-part-photo[data-illustration="diode"]{background:#fff1f2;border-color:#ffe4e6;color:#be123c}
        .cv-part-photo[data-illustration="transistor"]{background:#f0fdf4;border-color:#dcfce7;color:#15803d}
        .cv-part-photo[data-illustration="sensor"]{background:#ecfeff;border-color:#cffafe;color:#0891b2}
        .cv-part-photo[data-illustration="switch"]{background:#fffbeb;border-color:#fef3c7;color:#b45309}
        .cv-ei-part{display:flex;align-items:center;gap:9px;min-width:0}
        .cv-ei-part .cv-part-photo{flex:0 0 var(--cv-part-photo-size,48px);margin:0}
        .cv-ei-part-copy{display:flex;flex-direction:column;gap:2px;min-width:0}
        .cv-ei-part-copy .cv-ap-name{display:block;overflow-wrap:anywhere}
        .cv-map{display:grid;grid-template-columns:180px 1fr;gap:18px;align-items:center;padding:8px 8px 16px}
        .cv-map-part{border:1px solid #bfdbfe;background:#eff6ff;border-radius:12px;padding:12px}
        .cv-map-branches{display:grid;gap:10px;border-left:2px solid #cbd5e1;padding-left:16px}
        .cv-map-branch{display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:#fff;border:1px solid #e6edf5;border-radius:12px;padding:8px 10px}
        .cv-set-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:14px}
        .cv-security-row{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid #eef2f7}
        .cv-plan-card{background:#eff6ff;border:1px solid #dbeafe;border-radius:16px;padding:16px 18px}
        .cv-ap-name{font-weight:750}
        .cv-ap-meta{color:#64748b;font-size:12px}
        .st-key-approved_home_recent_card{margin:0 0 16px!important;padding:0!important;border:1px solid #c5d1df!important;border-radius:16px!important;background:#fff!important;box-shadow:0 3px 12px rgba(15,23,42,.055)!important}
        .st-key-approved_home_recent_card [data-testid="stVerticalBlock"]{gap:0!important}
        .cv-ap-home-recent-heading{padding:18px 20px 14px}
        .cv-ap-home-recent-heading h2{margin:0 0 4px;color:#0f172a;font-size:21px;font-weight:760;letter-spacing:-.02em}
        .cv-ap-home-recent-heading p{margin:0;color:#64748b;font-size:13px}
        [class*="st-key-approved_home_row_"]{min-height:66px!important;margin:0!important;padding:7px 20px!important;border-top:0!important;border-bottom:1px solid #e5ebf3!important;background:#fff!important}
        [class*="st-key-approved_home_row_"] [data-testid="stHorizontalBlock"]{align-items:center!important}
        .cv-ap-home-bom{display:flex;align-items:center;min-width:0;min-height:40px}
        .cv-ap-home-bom-copy{display:flex;flex:1;flex-direction:column;min-width:0}
        .cv-ap-home-bom .cv-ap-name{display:block;overflow:hidden;color:#17253e;font-size:13px;font-weight:750;text-overflow:ellipsis;white-space:nowrap}
        .cv-ap-home-bom small{display:block;margin-top:3px;overflow:hidden;color:#74839a;font-size:11px;text-overflow:ellipsis;white-space:nowrap}
        .cv-ap-home-project{display:block;overflow:hidden;color:#52647b;font-size:13px;line-height:1.4;text-overflow:ellipsis;white-space:nowrap}
        /* Route canvas widths mirror Home by default; table-heavy views get a bounded wider canvas. */
        section[data-testid="stMain"] [class*="st-key-approved_page_canvas_standard_"]{
          box-sizing:border-box!important;width:100%!important;max-width:1440px!important;min-width:0!important;
          margin-left:auto!important;margin-right:auto!important
        }
        …62339 tokens truncated…ngs") or compatibility.get("review_warnings")
            else relationship_label
        )
        level = _candidate_field(row, "Estimated Risk", "risk_level", "risk", fallback="Unknown")
        pill = ""
        if "high" in level.casefold():
            pill = "high"
        elif "low" in level.casefold():
            pill = "low"
        elif "medium" in level.casefold():
            pill = "medium"
        elif "verification" in level.casefold():
            pill = "verify"
        level_html = f"<span class='cv-pill {pill}'>{level}</span>" if pill else level
        discovery = row.get("_discovery_row") if isinstance(row.get("_discovery_row"), dict) else {}
        image = str(
            row.get("image_url")
            or row.get("photo_url")
            or row.get("Image URL")
            or discovery.get("image_url")
            or discovery.get("photo_url")
            or ""
        )
        row_key = f"cv_candidate_row_{'open' if is_open else 'shut'}_{index}"
        with st.container(key=row_key):
            with st.container(key=f"cv_candidate_hit_{index}"):
                cells = st.columns([2.4, 1.3, 1.8, 0.9, 0.8, 0.9, 0.7], vertical_alignment="center")
                with cells[0]:
                    photo_col, name_col = st.columns([0.35, 1.5], vertical_alignment="center")
                    photo_col.markdown(
                        part_image_markup(image, candidate_mpn, size=48, part=row),
                        unsafe_allow_html=True,
                    )
                    if name_col.button(
                        candidate_mpn,
                        key=f"cv_candidate_open_{index}",
                        help=(
                            f"Show recorded details for {candidate_mpn}. "
                            "Press Enter or Space."
                        ),
                    ):
                        st.session_state["cadivor_replacement_open_mpn"] = "" if is_open else candidate_mpn
                        st.rerun()
                cells[1].markdown(_candidate_field(row, "Manufacturer", "manufacturer"))
                cells[2].markdown(relationship_html, unsafe_allow_html=True)
                cells[3].markdown(_candidate_field(row, "Lifecycle", "lifecycle_status", "lifecycle"))
                cells[4].markdown(_candidate_field(row, "Stock", "stock_total", "stock_available"))
                cells[5].markdown(_candidate_field(row, "Supplier", "supplier_count", "supplier"))
                cells[6].markdown(level_html, unsafe_allow_html=True)
            if is_open:
                st.markdown(_candidate_detail_html(row, original), unsafe_allow_html=True)
                _render_bom_replacement_approvals(
                    source_context=source_context,
                    query=query,
                    original=original,
                    candidate=row,
                )

    from src.normalizer import normalize_part_number

    compare_source_mpn = str(original.get("manufacturer_part_number") or query or "").strip()
    compare_source_token = normalize_part_number(compare_source_mpn) or compare_source_mpn.upper()
    if st.session_state.get("approved_replacement_compare_source") != compare_source_token:
        st.session_state["approved_replacement_compare_source"] = compare_source_token
        st.session_state["approved_replacement_compare_candidates"] = []
    compare_candidates = [
        str(item or "").strip()
        for item in st.session_state.get("approved_replacement_compare_candidates", [])
        if str(item or "").strip()
    ]
    eligible_compare_keys = {part_key(_candidate_mpn(row)) for row in candidates[:5]}
    compare_candidates = [
        item for item in compare_candidates if part_key(item) in eligible_compare_keys
    ][:2]
    st.session_state["approved_replacement_compare_candidates"] = compare_candidates

    def _toggle_compare_candidate(candidate_mpn: str) -> None:
        current = st.session_state.get("approved_replacement_compare_candidates") or []
        st.session_state["approved_replacement_compare_candidates"] = (
            toggle_comparison_candidate(current, candidate_mpn, limit=2)
        )
    if shown and compare_source_mpn:
        selected_candidate_text = " · ".join(_esc(item) for item in compare_candidates)
        selected_candidate_line = (
            f"<p class='cv-ap-meta'>Selected replacements: {selected_candidate_text}</p>"
            if selected_candidate_text
            else ""
        )
        st.markdown(
            "<section class='cv-ap-card'><h3>Compare up to 3 parts</h3>"
            f"<p class='cv-ap-sub'>Part A: {_esc(compare_source_mpn)}. Add up to two replacement candidates, then compare them with the source part.</p>"
            f"<p class='cv-ap-meta'>{len(compare_candidates) + 1} of 3 parts selected</p>"
            f"{selected_candidate_line}</section>",
            unsafe_allow_html=True,
        )
        for index, row in enumerate(candidates[:5]):
            candidate = _candidate_mpn(row)
            if not candidate:
                continue
            candidate_token = part_key(candidate)
            selected = any(
                part_key(item) == candidate_token
                for item in compare_candidates
            )
            toggle_cols = st.columns([2.5, 1], vertical_alignment="center")
            with toggle_cols[0]:
                st.caption(candidate)
            with toggle_cols[1]:
                st.button(
                    "Remove" if selected else "Add to comparison",
                    key=(
                        "approved_replacement_compare_toggle_"
                        + hashlib.sha1(candidate_token.encode("utf-8")).hexdigest()[:12]
                    ),
                    disabled=not selected and len(compare_candidates) >= 2,
                    use_container_width=True,
                    on_click=_toggle_compare_candidate,
                    args=(candidate,),
                )
        selected_compare_candidates = list(compare_candidates)
        if selected_compare_candidates:
            if st.button(
                f"Compare {len(selected_compare_candidates) + 1} parts",
                key="approved_replacement_compare_selected",
                type="primary",
            ):
                source_mpn = compare_source_mpn
                candidate_b = selected_compare_candidates[0]
                candidate_c = selected_compare_candidates[1] if len(selected_compare_candidates) > 1 else ""
                st.session_state["cadivor_compare_part_a"] = source_mpn
                st.session_state["cadivor_compare_part_b"] = candidate_b
                st.session_state["cadivor_compare_part_c"] = candidate_c
                selected_keys = {part_key(candidate_b), part_key(candidate_c)}
                candidate_snapshots = [
                    dict(row)
                    for row in candidates
                    if part_key(_candidate_mpn(row)) in selected_keys
                ]
                # Widget state is cleaned up at the end of this Finder run.
                # Stage values under non-widget keys and apply them on the
                # Compare page before its text inputs are created.
                st.session_state["cadivor_compare_pending_handoff"] = {
                    "part_numbers": [
                        source_mpn,
                        candidate_b,
                        *([candidate_c] if candidate_c else []),
                    ],
                    "auto_run": True,
                    "decision_context": {
                        "source_context": dict(source_context),
                        "original": dict(original),
                        "candidates": candidate_snapshots,
                    },
                }
                st.session_state.pop("cadivor_compare_result", None)
                navigate_to("Compare Parts")
    elif query.strip() and isinstance(result, dict):
        st.info(
            "No supplier candidates were returned for this part. You can still compare manufacturer part numbers manually; missing evidence will stay visible."
        )
        if st.button(
            "Compare part numbers manually",
            key="approved_replacement_manual_compare",
            type="secondary",
        ):
            source_mpn = str(original.get("manufacturer_part_number") or query).strip()
            st.session_state["cadivor_compare_part_a"] = source_mpn
            st.session_state["cadivor_compare_part_b"] = ""
            st.session_state["cadivor_compare_part_c"] = ""
            st.session_state["cadivor_compare_pending_handoff"] = {
                "part_numbers": [source_mpn],
                "auto_run": False,
                "decision_context": {
                    "source_context": dict(source_context),
                    "original": dict(original),
                    "candidates": [],
                },
            }
            st.session_state.pop("cadivor_compare_result", None)
            navigate_to("Compare Parts")
    end_approved_page()




def render_compare_live() -> None:
    """Compare up to three parts, with each candidate checked against Part A."""
    begin_approved_page()
    from src.approved_alternatives import part_key
    from src.parts_compare import resolve_compare_parts_submitted_mpn, run_compare_parts_many
    from src.ui.navigation import reveal_authenticated_page_body

    pending_handoff = st.session_state.pop("cadivor_compare_pending_handoff", None)
    if isinstance(pending_handoff, dict):
        pending_parts = [
            str(value or "").strip()
            for value in pending_handoff.get("part_numbers", [])
            if str(value or "").strip()
        ][:3]
        st.session_state["approved_compare_a"] = pending_parts[0] if pending_parts else ""
        st.session_state["approved_compare_b"] = pending_parts[1] if len(pending_parts) > 1 else ""
        st.session_state["approved_compare_c"] = pending_parts[2] if len(pending_parts) > 2 else ""
        st.session_state["approved_compare_show_c"] = len(pending_parts) > 2
        st.session_state["cadivor_compare_part_a"] = pending_parts[0] if pending_parts else ""
        st.session_state["cadivor_compare_part_b"] = pending_parts[1] if len(pending_parts) > 1 else ""
        st.session_state["cadivor_compare_part_c"] = pending_parts[2] if len(pending_parts) > 2 else ""
        decision_context = pending_handoff.get("decision_context")
        if isinstance(decision_context, dict):
            decision_context = dict(decision_context)
            decision_context["part_numbers"] = pending_parts
            st.session_state["cadivor_compare_decision_context"] = decision_context
        else:
            st.session_state.pop("cadivor_compare_decision_context", None)
        if pending_handoff.get("auto_run") and len(pending_parts) >= 2:
            st.session_state["approved_compare_auto_run_pending"] = True
        else:
            st.session_state.pop("approved_compare_auto_run_pending", None)
        st.session_state.pop("cadivor_compare_result", None)

    st.session_state.setdefault("approved_compare_a", str(st.session_state.get("cadivor_compare_part_a") or ""))
    st.session_state.setdefault("approved_compare_b", str(st.session_state.get("cadivor_compare_part_b") or ""))
    st.session_state.setdefault("approved_compare_c", str(st.session_state.get("cadivor_compare_part_c") or ""))
    st.session_state.setdefault("approved_compare_show_c", bool(st.session_state.get("approved_compare_c")))

    def _show_third_part() -> None:
        st.session_state["approved_compare_show_c"] = True

    def _remove_third_part() -> None:
        st.session_state["approved_compare_show_c"] = False
        st.session_state["approved_compare_c"] = ""
        st.session_state["cadivor_compare_part_c"] = ""
        st.session_state.pop("cadivor_compare_result", None)

    compare_handoff = st.session_state.get("cadivor_compare_decision_context")
    if isinstance(compare_handoff, dict):
        source_context = compare_handoff.get("source_context")
        source_context = source_context if isinstance(source_context, dict) else {}
        if source_context.get("mpn"):
            return_params = {
                key: source_context.get(key)
                for key in (
                    "analysis_id",
                    "part_id",
                    "source_page",
                    "return_analysis_id",
                    "return_page",
                    "return_mpn",
                    "return_decision_id",
                    "project_name",
                    "bom_name",
                    "prefill_id",
                    "manufacturer",
                    "description",
                    "lifecycle",
                    "risk",
                )
                if source_context.get(key)
            }
            return_params.update(
                {
                    "original_part": str(source_context.get("mpn") or ""),
                    "intent": "find_alternatives",
                }
            )
            if st.button(
                "← Back to replacement search",
                key="approved_compare_back_to_replacement_search",
                type="secondary",
            ):
                navigate_to("Alternative Finder", **return_params)

    st.markdown(
        """
        <div class="cv-ap">
          <p class="cv-ap-kicker">PARTS</p>
          <h1>Compare parts</h1>
          <p class="cv-ap-sub">Compare two or three parts side by side. Part B and Part C are each checked against Part A using available supplier and datasheet evidence.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("approved_compare_form", clear_on_submit=False):
        if st.session_state.get("approved_compare_show_c"):
            input_cols = st.columns(3)
        else:
            input_cols = st.columns(2)
        with input_cols[0]:
            entered_a = st.text_input("Part A", key="approved_compare_a", placeholder="Manufacturer part number")
        with input_cols[1]:
            entered_b = st.text_input("Part B", key="approved_compare_b", placeholder="Manufacturer part number")
        entered_c = ""
        if st.session_state.get("approved_compare_show_c"):
            with input_cols[2]:
                entered_c = st.text_input("Part C", key="approved_compare_c", placeholder="Manufacturer part number")
        submitted = st.form_submit_button(
            "Compare parts",
            type="primary",
            key="approved_compare_run",
        )
    # The compare form is now visibly mounted. Close the navigation cover before
    # supplier lookups begin so progress does not dim the full page.
    reveal_authenticated_page_body("Compare Parts")
    part_a = resolve_compare_parts_submitted_mpn(
        entered_a,
        st.session_state.get("approved_compare_a"),
        st.session_state.get("cadivor_compare_part_a"),
    )
    part_b = resolve_compare_parts_submitted_mpn(
        entered_b,
        st.session_state.get("approved_compare_b"),
        st.session_state.get("cadivor_compare_part_b"),
    )
    part_c = resolve_compare_parts_submitted_mpn(
        entered_c,
        st.session_state.get("approved_compare_c"),
        st.session_state.get("cadivor_compare_part_c"),
    ) if st.session_state.get("approved_compare_show_c") else ""
    has_part_c = bool(str(part_c or "").strip())
    requested_parts = [part for part in (part_a, part_b, part_c) if str(part or "").strip()]
    auto_run = bool(st.session_state.pop("approved_compare_auto_run_pending", False))
    if submitted or auto_run:
        if len(requested_parts) >= 2:
            try:
                with st.spinner("Comparing recorded supplier and datasheet evidence…"):
                    st.session_state["cadivor_compare_result"] = run_compare_parts_many(requested_parts)
                st.session_state["cadivor_compare_part_c"] = part_c
            except Exception:
                st.session_state["cadivor_compare_result"] = {
                    "status": "failed",
                    "part_a": part_a,
                    "part_b": part_b,
                    "part_c": part_c,
                    "part_numbers": requested_parts,
                    "error": "Cadivor could not complete this comparison right now. Please try again.",
                }
        else:
            st.session_state["cadivor_compare_result"] = {
                "status": "failed",
                "part_a": part_a,
                "part_b": part_b,
                "part_c": part_c,
                "part_numbers": requested_parts,
                "error": "Enter Part A and Part B manufacturer part numbers.",
            }
    if st.session_state.get("approved_compare_show_c"):
        st.button("Remove Part C", key="approved_compare_remove_c", on_click=_remove_third_part)
    else:
        st.button(
            "＋ Add part",
            key="approved_compare_add_c",
            type="secondary",
            on_click=_show_third_part,
        )

    result = st.session_state.get("cadivor_compare_result")
    if isinstance(result, dict):
        result_parts = result.get("part_numbers")
        if result_parts is None:
            result_parts = [result.get("part_a"), result.get("part_b")]
        normalize = lambda value: str(value or "").strip().casefold()
        if [normalize(value) for value in result_parts] != [normalize(value) for value in requested_parts]:
            result = None
    comparison = result.get("comparison") if isinstance(result, dict) else {}
    if not isinstance(comparison, dict):
        comparison = {}
    counts = comparison.get("counts") if isinstance(comparison.get("counts"), dict) else {}
    card_a = comparison.get("part_a") if isinstance(comparison.get("part_a"), dict) else {}
    card_b = comparison.get("part_b") if isinstance(comparison.get("part_b"), dict) else {}
    card_c = comparison.get("part_c") if isinstance(comparison.get("part_c"), dict) else {}
    rows = comparison.get("rows") if isinstance(comparison.get("rows"), list) else []
    body = []
    rendered_compatibility_labels: set[str] = set()
    missing = {"", "—", "-", "–", "not available", "not recorded", "n/a", "none", "nan"}

    def _recorded(row: dict[str, Any], *keys: str) -> str:
        for key in keys:
            text = str(row.get(key) or "").strip()
            if text and text.casefold() not in missing:
                return text
        return ""

    def _compare_part_evidence(card: dict[str, Any], slot: str) -> dict[str, Any]:
        part = {
            "manufacturer_part_number": card.get("mpn") or "",
            "manufacturer": card.get("manufacturer") or "",
            "description": card.get("description") or "",
            "package": card.get("package") or "",
        }
        part.update(
            {
                key: value
                for key, value in comparison_row_part_values(rows, slot).items()
                if value
            }
        )
        return part

    compatibility_by_slot: dict[str, dict[str, Any]] = {}
    if comparison and card_a and card_b:
        compare_original = _compare_part_evidence(card_a, "Part A")
        compatibility_by_slot["Part B"] = assess_part_compatibility(
            compare_original,
            _compare_part_evidence(card_b, "Part B"),
        )
        if has_part_c and card_c:
            compatibility_by_slot["Part C"] = assess_part_compatibility(
                compare_original,
                _compare_part_evidence(card_c, "Part C"),
            )
    compatibility_notices = []
    for slot, card in (("Part B", card_b), ("Part C", card_c)):
        assessment = compatibility_by_slot.get(slot, {})
        if not assessment:
            continue
        mpn_label = _esc(card.get("mpn") or slot)
        if assessment.get("critical_warnings"):
            compatibility_notices.append(
                "<div class='cv-compat-banner critical' role='alert'>"
                f"<strong>{slot} · {mpn_label} — NOT A DROP-IN REPLACEMENT</strong>"
                f"<ul>{''.join(f'<li>{_esc(item)}</li>' for item in assessment['critical_warnings'])}</ul>"
                "Do not approve this as a drop-in replacement. A physical redesign and/or firmware rewrite may be required."
                "</div>"
            )
        elif assessment.get("review_warnings"):
            compatibility_notices.append(
                "<div class='cv-compat-banner review' role='status'>"
                f"<strong>{slot} · {mpn_label} — DROP-IN FIT NOT VERIFIED</strong>"
                f"<ul>{''.join(f'<li>{_esc(item)}</li>' for item in assessment['review_warnings'])}</ul>"
                "</div>"
            )

    for row in rows[:24]:
        if not isinstance(row, dict):
            continue
        label = _recorded(row, "Attribute", "label", "parameter", "field")
        if not label or label.casefold() == "parameter":
            continue
        raw_a = _recorded(row, "Part A", "part_a", "a", "value_a", "Original")
        raw_b = _recorded(row, "Part B", "part_b", "b", "value_b", "Candidate")
        raw_c = _recorded(row, "Part C", "part_c", "c", "value_c")
        if not raw_a and not raw_b and not raw_c:
            continue
        label_key = label.casefold()

        def critical_for(slot: str) -> bool:
            assessment = compatibility_by_slot.get(slot, {})
            if "package" in label_key:
                return bool(assessment.get("package_mismatch"))
            if label_key in {"pin count", "number of pins", "pins"}:
                return bool(assessment.get("pin_count_mismatch"))
            if "architecture" in label_key or label_key in {"device family", "core", "instruction set"}:
                return bool(assessment.get("architecture_mismatch"))
            return False

        def compare_cell(value: str, slot: str, base_value: str) -> str:
            critical = critical_for(slot)
            if critical:
                return f"<td class='cv-compare-compat-critical'>{_esc(value or 'Not recorded')}</td>"
            if value and base_value != value:
                return f"<td class='cv-compare-diff'>{_esc(value)}</td>"
            return f"<td>{_esc(value or 'Not recorded')}</td>"

        cells = [
            f"<td>{_esc(raw_a or 'Not recorded')}</td>",
            compare_cell(raw_b, "Part B", raw_a),
        ]
        if has_part_c:
            cells.append(compare_cell(raw_c, "Part C", raw_a))
        body.append(f"<tr><td>{_esc(label)}</td>{''.join(cells)}</tr>")
        rendered_compatibility_labels.add(label_key)
    compatibility_fields = (
        ("package", "Package", "package_mismatch", "source_package", "candidate_package"),
        ("pin count", "Pin count", "pin_count_mismatch", "source_pin_count", "candidate_pin_count"),
        (
            "architecture",
            "Device family / architecture",
            "architecture_mismatch",
            "source_architecture",
            "candidate_architecture",
        ),
    )
    for normalized, label, mismatch_key, source_key, candidate_key in compatibility_fields:
        already_rendered = any(
            normalized in value
            or (normalized == "pin count" and "number of pins" in value)
            or (normalized == "architecture" and "device family" in value)
            for value in rendered_compatibility_labels
        )
        if already_rendered or not any(
            row.get(mismatch_key) for row in compatibility_by_slot.values()
        ):
            continue
        source_assessment = compatibility_by_slot.get("Part B", {})
        source_value = source_assessment.get(source_key)
        part_b_assessment = compatibility_by_slot.get("Part B", {})
        part_b_value = part_b_assessment.get(candidate_key)
        if source_value in (None, ""):
            source_value = "Not recorded"
        if part_b_value in (None, ""):
            part_b_value = "Not recorded"
        part_b_cell = (
            f"<td class='cv-compare-compat-critical'>{_esc(part_b_value)}</td>"
            if part_b_assessment.get(mismatch_key)
            else f"<td>{_esc(part_b_value)}</td>"
        )
        cells = [f"<td>{_esc(source_value)}</td>", part_b_cell]
        if has_part_c:
            part_c_assessment = compatibility_by_slot.get("Part C", {})
            part_c_value = part_c_assessment.get(candidate_key)
            if part_c_value in (None, ""):
                part_c_value = "Not recorded"
            part_c_cell = (
                f"<td class='cv-compare-compat-critical'>{_esc(part_c_value)}</td>"
                if part_c_assessment.get(mismatch_key)
                else f"<td>{_esc(part_c_value)}</td>"
            )
            cells.append(part_c_cell)
        body.append(f"<tr><td>{_esc(label)}</td>{''.join(cells)}</tr>")
    ran = isinstance(result, dict) and str(result.get("status") or "") in {"completed", "failed"}
    error = str(result.get("error") if isinstance(result, dict) else "").strip()
    if not body:
        if ran and error and error != "—":
            empty = error
        elif ran or comparison:
            empty = "No comparable attributes were recorded for these parts."
        elif part_a.strip() and part_b.strip():
            empty = "No comparison is available yet. Run Compare parts to load recorded attributes."
        else:
            empty = "Enter Part A and Part B manufacturer part numbers to compare."
    else:
        empty = ""
    submitted_a = str(result.get("part_a") or "") if isinstance(result, dict) else ""
    submitted_b = str(result.get("part_b") or "") if isinstance(result, dict) else ""
    name_a = _esc(card_a.get("mpn") or submitted_a or part_a or "Part A")
    name_b = _esc(card_b.get("mpn") or submitted_b or part_b or "Part B")
    submitted_c = str(result.get("part_c") or "") if isinstance(result, dict) else ""
    name_c = _esc(card_c.get("mpn") or submitted_c or part_c or "Part C")
    notice = "".join(compatibility_notices)
    headers = f"<th>Parameter</th><th>{name_a}</th><th>{name_b}</th>"
    if has_part_c:
        headers += f"<th>{name_c}</th>"
    table = (
        f"<p class='cv-ap-sub'>{_esc(empty)}</p>"
        if empty
        else (
            "<section class='cv-ap-card'><table class='cv-ap-table'><thead><tr>"
            f"{headers}"
            f"</tr></thead><tbody>{''.join(body)}</tbody></table></section>"
        )
    )
    figures = ""
    if comparison:
        figures = (
            "<section class='cv-ap-kpis three'>"
            f"<article class='cv-ap-kpi'><span>Compatible checks</span><strong>{_esc(counts.get('compatible', '—'))}</strong></article>"
            f"<article class='cv-ap-kpi'><span>Differences found</span><strong>{_esc(counts.get('material_difference', '—'))}</strong></article>"
            f"<article class='cv-ap-kpi'><span>Needs validation</span><strong>{_esc(counts.get('needs_data', '—'))}</strong></article>"
            "</section>"
        )
    st.markdown(
        f"""
        <div class="cv-ap">
          {notice}
          {figures}
        </div>
        """,
        unsafe_allow_html=True,
    )
    card_specs = [(card_a, name_a, part_a), (card_b, name_b, part_b)]
    if has_part_c:
        card_specs.append((card_c, name_c, part_c))
    card_cols = st.columns(len(card_specs), gap="small")
    for col, (card, title, current_mpn) in zip(card_cols, card_specs):
        with col:
            part_info = card or {"manufacturer_part_number": current_mpn}
            title = _esc(part_info.get("mpn") or title)
            image = str(part_info.get("image_url") or part_info.get("photo_url") or "")
            details = _esc(part_info.get("description") or part_info.get("manufacturer") or "Not recorded")
            st.markdown(
                "<article class='cv-ap-template'><div class='cv-ei-part'>"
                f"{part_photo(image, size=48, part=part_info)}<span class='cv-ei-part-copy'>"
                f"<h3>{title}</h3><p>{details}</p></span></div></article>",
                unsafe_allow_html=True,
            )
    st.markdown(table, unsafe_allow_html=True)
    handoff_context = st.session_state.get("cadivor_compare_decision_context")
    if (
        isinstance(handoff_context, dict)
        and isinstance(result, dict)
        and str(result.get("status") or "") == "completed"
    ):
        handoff_parts = [
            str(value or "").strip().casefold()
            for value in handoff_context.get("part_numbers", [])
            if str(value or "").strip()
        ]
        current_parts = [str(value or "").strip().casefold() for value in requested_parts]
        if handoff_parts == current_parts:
            decision_source = handoff_context.get("source_context")
            decision_source = decision_source if isinstance(decision_source, dict) else {}
            decision_original = handoff_context.get("original")
            decision_original = decision_original if isinstance(decision_original, dict) else {}
            candidate_rows = handoff_context.get("candidates")
            candidate_rows = candidate_rows if isinstance(candidate_rows, list) else []
            expected_candidate_keys = {part_key(value) for value in requested_parts[1:]}
            approved_candidates = [
                row
                for row in candidate_rows
                if isinstance(row, dict)
                and part_key(_candidate_mpn(row)) in expected_candidate_keys
            ]
            if approved_candidates:
                st.markdown("### Choose a replacement for this BOM")
                st.caption(
                    "Review the comparison, then approve the replacement you want to keep. "
                    "Saved approvals appear in this BOM’s Alternatives and BOM Risk views."
                )
                for candidate in approved_candidates:
                    st.markdown(f"#### {_esc(_candidate_mpn(candidate))}")
                    candidate_slot = (
                        "Part C"
                        if card_c and part_key(_candidate_mpn(candidate)) == part_key(card_c.get("mpn"))
                        else "Part B"
                    )
                    _render_bom_replacement_approvals(
                        source_context=decision_source,
                        query=part_a,
                        original=decision_original,
                        candidate=candidate,
                        recorded_from="Compare parts",
                        comparison_evidence={"comparison": comparison, "slot": candidate_slot},
                    )
    end_approved_page()


def render_datasheet_live() -> None:
    """Datasheet Q&A layout wired to the existing PDF question flow."""
    from src.datasheet_qa import (
        DATASHEET_QA_DOC_KEY,
        DATASHEET_QA_THREAD_KEY,
        extract_uploaded_datasheet,
        store_document_in_session,
    )
    from src.pages.datasheet_qa import _execute_datasheet_question

    begin_approved_page()
    document = st.session_state.get(DATASHEET_QA_DOC_KEY)
    ready = isinstance(document, dict) and bool(document.get("available"))
    uploaded = st.file_uploader("Change document", type=["pdf"], key="datasheet_qa_uploader")
    if uploaded is not None and not ready:
        extracted = extract_uploaded_datasheet(uploaded.getvalue(), filename=str(uploaded.name or ""))
        store_document_in_session(st.session_state, extracted)
        document = st.session_state.get(DATASHEET_QA_DOC_KEY)
        ready = isinstance(document, dict) and bool(document.get("available"))
        if not ready:
            st.warning(str((extracted or {}).get("reason") or "Could not read this PDF."))
    question = st.text_input("Your question", key="approved_datasheet_question", disabled=not ready)
    if st.button("Ask", key="approved_datasheet_ask", type="primary", disabled=not ready) and question.strip() and ready:
        thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
        _execute_datasheet_question(document=document, question=question.strip(), thread=thread)
    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    latest = thread[-1] if thread and isinstance(thread[-1], dict) else {}
    answer = _esc(latest.get("answer") or latest.get("text") or "")
    filename = _esc((document or {}).get("filename") if isinstance(document, dict) else "No document selected")
    evidence = latest.get("evidence") or latest.get("sources") or []
    evidence_rows = []
    if isinstance(evidence, list):
        for item in evidence[:6]:
            if isinstance(item, dict):
                evidence_rows.append(
                    "<tr>"
                    f"<td>{_esc(item.get('parameter') or item.get('label') or item.get('text') or 'Source')}</td>"
                    f"<td>{_esc(item.get('value') or item.get('excerpt') or '')}</td>"
                    f"<td>{_esc(item.get('page') or '')}</td>"
                    "</tr>"
                )
    if not evidence_rows:
        evidence_rows.append("<tr><td colspan='3'>Upload a text-searchable PDF and ask a question to see cited evidence.</td></tr>")
    answer_block = (
        f"<section class='cv-ap-banner'><h2>Answer</h2><p>{answer}</p></section>"
        if answer and answer != "—"
        else ""
    )
    st.markdown(
        f"""
        <div class="cv-ap">
          <p class="cv-ap-kicker">DATASHEET Q&A</p>
          <h1>Ask a datasheet</h1>
          <p class="cv-ap-sub">Get precise answers from technical documents, with source citations.</p>
          <section class="cv-ap-card"><div class="cv-ap-meta">Selected document</div><div class="cv-ap-name">{filename}</div></section>
          {answer_block}
          <section class="cv-ap-card"><table class="cv-ap-table"><thead><tr>
            <th>Source</th><th>Evidence</th><th>Page</th>
          </tr></thead><tbody>{''.join(evidence_rows)}</tbody></table></section>
        </div>
        """,
        unsafe_allow_html=True,
    )
    end_approved_page()


def render_settings_workspace(profile: dict[str, Any], plan_name: str) -> None:
    """Profile, notifications, security, and billing on one screen."""
    begin_approved_page()
    profile = profile if isinstance(profile, dict) else {}
    name = _esc(profile.get("full_name") or profile.get("email") or "Account")
    email = _esc(profile.get("email") or "")
    company = _esc(profile.get("company") or profile.get("company_name") or "Not recorded")
    role = _esc(profile.get("role_title") or profile.get("role") or "Not recorded")
    timezone = _esc(profile.get("timezone") or "Not recorded")
    workspace = _esc(profile.get("workspace_name") or company)
    plan = _esc(plan_name or profile.get("plan") or "Not recorded")
    with st.container(key="approved_settings_screen"):
        _render_settings_panels(profile, name, email, company, role, timezone, workspace, plan)
    end_approved_page()


def _render_settings_panels(profile, name, email, company, role, timezone, workspace, plan) -> None:
    st.markdown("<div class='cv-ap'><h1>Settings</h1></div>", unsafe_allow_html=True)
    left, right = st.columns(2)
    with left:
        st.markdown(
            f"""
            <div class="cv-ap"><section class="cv-ap-card"><h2>Profile</h2>
            <p class="cv-ap-name">{name}</p><p>{email}</p>
            <div class="cv-security-row"><span>Organization</span><strong>{company}</strong></div>
            <div class="cv-security-row"><span>Role</span><strong>{role}</strong></div>
            <div class="cv-security-row"><span>Workspace</span><strong>{workspace}</strong></div>
            </section></div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("approved_profile_form"):
            name_col, company_col, role_col = st.columns(3)
            full_name = name_col.text_input("Full name", value=str(profile.get("full_name") or ""))
            company_input = company_col.text_input("Organization", value=str(profile.get("company") or profile.get("company_name") or ""))
            role_input = role_col.text_input("Role", value=str(profile.get("role_title") or ""))
            submitted = st.form_submit_button("Save profile")
        if submitted:
            from src.authenticated_runtime import update_user_profile_fields

            user_id = str(profile.get("id") or st.session_state.get("user_id") or "")
            allowed, skipped = update_user_profile_fields(
                user_id,
                {"full_name": full_name, "company": company_input, "role_title": role_input},
            )
            if allowed:
                st.success("Profile updated.")
            elif skipped:
                st.info("Those profile fields are not stored on this account.")
        st.markdown(
            """
            <div class="cv-ap"><section class="cv-ap-card"><h2>Security</h2>
            <div class="cv-security-row"><span>Password</span><strong>Managed by your sign-in provider</strong></div>
            <div class="cv-security-row"><span>Two-factor authentication</span><strong>Not recorded</strong></div>
            <div class="cv-security-row"><span>Active sessions</span><strong>This browser session</strong></div>
            <div class="cv-security-row"><span>Connected accounts</span><strong>Not recorded</strong></div>
            </section></div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"""
            <div class="cv-ap"><section class="cv-ap-card"><h2>Account preferences</h2>
            <p class="cv-ap-meta">Email notifications use this account. Timezone {timezone}</p>
            </section></div>
            """,
            unsafe_allow_html=True,
        )
        st.toggle("Project activity", key="approved_notify_project")
        st.toggle("Simulation results", key="approved_notify_simulation")
        st.toggle("Team activity", key="approved_notify_team")
        st.toggle("Product updates", key="approved_notify_product")
        st.toggle("Marketing emails", key="approved_notify_marketing")
        st.text_input("Timezone", key="approved_settings_timezone", placeholder=str(profile.get("timezone") or "Not recorded"))
        st.markdown(
            f"""
            <div class="cv-ap"><section class="cv-plan-card"><p class="cv-ap-meta">Current plan</p>
            <h2>{plan}</h2>
            <p>Plan limits come from the signed-in subscription. Features that are not on this account stay blank.</p>
            </section></div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Manage plan", key="approved_settings_manage_plan", type="primary"):
            navigate_to("Pricing")


# Apply one centered page canvas to every approved page renderer. Dense data views
# use a slightly wider cap; each canvas remains fluid below its max-width.
def _with_approved_page_canvas(width_variant: str):
    def decorate(renderer):
        @wraps(renderer)
        def wrapped(*args, **kwargs):
            key = f"approved_page_canvas_{width_variant}_{renderer.__name__}"
            with st.container(key=key):
                return renderer(*args, **kwargs)
        return wrapped
    return decorate


for _renderer_name, _width_variant in (
    ("render_saved_bom_settings", "standard"),
    ("render_home", "standard"),
    ("render_bom_catalog", "wide"),
    ("render_decision_queue", "standard"),
    ("render_monitoring", "wide"),
    ("render_reports_list", "wide"),
    ("render_simple_workspace", "wide"),
    ("render_replacement_search", "wide"),
    ("render_compare_live", "wide"),
    ("render_datasheet_live", "standard"),
    ("render_settings_workspace", "standard"),
):
    globals()[_renderer_name] = _with_approved_page_canvas(_width_variant)(
        globals()[_renderer_name]
    )
