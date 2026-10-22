"""Approved page bodies for the Cadivor mockups.

Live workspace records fill the layout. Sample names from the mockups are not
invented when the workspace has different BOMs.
"""

from __future__ import annotations

import html
import hashlib
import io
from functools import wraps
from datetime import date, datetime, timedelta, timezone
from typing import Any

import streamlit as st

from src.bom_upload_flow import (
    prepare_new_approved_bom_analysis,
    should_render_approved_bom_upload_form,
    should_stop_approved_bom_renderer,
    should_disable_bom_analyze_button,
    stage_approved_bom_submission,
)
from src.approval_evidence import has_document_page_citation
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
    evidence_type = str(row.get("Evidence Type") or "").strip()
    discovery_query = str(row.get("Discovery Query") or "").strip()
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
    if evidence_type.casefold() == "distributor family search match":
        query_note = f" for {_esc(discovery_query)}" if discovery_query else ""
        evidence_html = (
            "<p class='cv-candidate-evidence'><strong>Discovery evidence:</strong> "
            f"DigiKey catalog family search{query_note}. This identifies a related family only; "
            "it does not establish compatibility or a drop-in relationship.</p>"
        )
    elif evidence_type:
        evidence_html = (
            "<p class='cv-candidate-evidence'><strong>Discovery evidence:</strong> "
            f"{_esc(evidence_type)}. This is not compatibility evidence.</p>"
        )
    else:
        evidence_html = ""
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
        f"{evidence_html}"
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
        .cv-ap-flow{display:flex;align-items:center;gap:14px;box-sizing:border-box;width:100%;margin:0 0 16px;padding:15px 18px;background:#fff;border:1px solid #dfe7f1;border-radius:11px;color:#718096}
        .cv-ap-flow-step{display:flex;align-items:center;gap:10px;white-space:nowrap;font-size:12px;font-weight:600}
        .cv-ap-flow-node{display:inline-flex;align-items:center;justify-content:center;flex:0 0 26px;width:26px;height:26px;border:1px solid #d9e2ee;border-radius:50%;background:#f1f5f9;color:#718096;font-size:11px;font-weight:750}
        .cv-ap-flow-step.current{color:#1c3c70;font-weight:750}
        .cv-ap-flow-step.current .cv-ap-flow-node{border-color:#2865ed;background:#2865ed;color:#fff}
        .cv-ap-flow-step.complete{color:#52647b}
        .cv-ap-flow-step.complete .cv-ap-flow-node{border-color:#b9e4cc;background:#eaf8f0;color:#147a47}
        .cv-ap-flow-line{flex:1 1 36px;min-width:18px;height:2px;background:#d8e1ed}
        .cv-ap-flow-status{margin-left:auto;padding:6px 12px;border-radius:999px;background:#eef5ff;color:#2865ed;font-size:9px;font-weight:800;letter-spacing:.04em;white-space:nowrap}
        .cv-ap-entry-heading{display:flex;align-items:center;gap:12px;min-height:44px;margin:0 0 10px}
        .cv-ap-entry-icon{display:inline-flex;align-items:center;justify-content:center;flex:0 0 44px;width:44px;height:44px;border-radius:9px;background:#eef5ff;color:#2865ed}
        .cv-ap-entry-icon svg{width:23px;height:23px;display:block}
        .cv-ap-entry-heading>div{display:flex;flex-direction:column;justify-content:center;min-height:44px}
        .cv-ap-entry-heading p{margin:0 0 4px!important;color:#8491a3;font-size:9px;font-weight:800;letter-spacing:.07em;line-height:1.1}
        .cv-ap-entry-heading h2{margin:0!important;color:#172942;font-size:18px;line-height:1.2;font-weight:760;letter-spacing:-.02em}
        .cv-ap-entry-copy{margin:0 0 12px;color:#6d7d92;font-size:12px}
        .st-key-approved_replacement_search_card,.st-key-approved_datasheet_upload_card{box-sizing:border-box;width:100%;margin:0 0 16px;padding:18px 20px 14px;background:#fff;border:1px solid #dfe7f1;border-radius:12px}
        .st-key-approved_datasheet_search_card{box-sizing:border-box;width:100%;margin:0 0 14px;padding:15px 18px 13px;background:#fff;border:1px solid #dfe7f1;border-radius:12px}
        .cv-dq-lookup-heading{display:grid;gap:4px;margin:0 0 10px}.cv-dq-lookup-heading strong{color:#172942;font-size:13px;font-weight:760}.cv-dq-lookup-heading span{color:#718096;font-size:11px;line-height:1.45}
        .st-key-approved_datasheet_search_card [data-testid="stWidgetLabel"] p{margin-bottom:4px;color:#728198;font-size:9px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
        .st-key-approved_datasheet_search_card [data-baseweb="input"]{min-height:44px;background:#fff!important;border:1px solid #b8c6d8!important;border-radius:8px!important}
        .st-key-approved_datasheet_search_card input{color:#172942!important;caret-color:#2865ed!important}
        .st-key-approved_datasheet_search_card button[kind="primary"]{min-height:42px!important;height:42px!important;border-radius:8px!important;white-space:nowrap!important}
        .st-key-approved_replacement_search_card>[data-testid="stVerticalBlock"],.st-key-approved_datasheet_upload_card>[data-testid="stVerticalBlock"]{gap:.55rem}
        .st-key-approved_replacement_search_card [data-testid="stWidgetLabel"] p,.st-key-approved_datasheet_question_panel [data-testid="stWidgetLabel"] p{margin-bottom:4px;color:#728198;font-size:9px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
        .st-key-approved_replacement_search_card [data-testid="stTextInput"] [data-baseweb="input"]{box-sizing:border-box!important;min-height:48px!important;background:#fff!important;border:1.5px solid #9aabc0!important;outline:1px solid #d3deeb!important;outline-offset:-1px!important;border-radius:9px!important;box-shadow:0 1px 2px rgba(20,40,70,.05)!important}
        .st-key-approved_replacement_search_card [data-testid="stTextInput"] [data-baseweb="input"]>div{background:transparent!important;border:0!important;box-shadow:none!important}
        .st-key-approved_replacement_search_card [data-testid="stTextInput"] input{min-height:46px!important;background:transparent!important;border:0!important;border-radius:8px!important;color:#172942!important;caret-color:#2865ed!important;font-size:14px!important}
        .st-key-approved_replacement_search_card [data-testid="stTextInput"] input::placeholder{color:#8a98aa!important;opacity:1!important}
        .st-key-approved_replacement_search_card [data-testid="stTextInput"] [data-baseweb="input"]:focus-within{border-color:#2865ed!important;outline-color:#2865ed!important;box-shadow:0 0 0 3px rgba(40,101,237,.13)!important}
        .st-key-approved_replacement_search_card button[kind="primary"],.st-key-approved_datasheet_question_panel button[kind="primary"]{min-height:44px!important;height:44px!important;border-radius:8px!important}
        .cv-ap-replacement-note{margin:2px 0 8px;color:#8391a4;font-size:11px}
        .cv-ap-context-note{display:flex;align-items:flex-start;gap:9px;margin:3px 0 0;padding:11px 12px;border-top:1px solid #edf1f6;color:#65758b;font-size:11px;line-height:1.45}
        .cv-ap-context-note svg{flex:0 0 18px;width:18px;height:18px;color:#8796aa}
        .cv-ap-waiting{box-sizing:border-box;width:100%;margin:0 0 14px;padding:16px 20px 20px;background:#fff;border:1px solid #dfe7f1;border-radius:12px}
        .cv-ap-waiting-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-bottom:12px;border-bottom:1px solid #edf1f6}
        .cv-ap-waiting-head h2{margin:0;color:#172942;font-size:15px;font-weight:750}
        .cv-ap-waiting-status{padding:5px 9px;border-radius:999px;background:#f1f5f9;color:#718096;font-size:8px;font-weight:800;letter-spacing:.03em;white-space:nowrap}
        .cv-ap-waiting-intro{display:flex;align-items:center;gap:16px;margin:22px 2px 28px}
        .cv-ap-waiting-icon{display:inline-flex;align-items:center;justify-content:center;flex:0 0 72px;width:72px;height:72px;border:1px solid #e4ebf4;border-radius:16px;background:#f3f7fd;color:#7d8ba0}
        .cv-ap-waiting-icon svg{width:25px;height:25px}
        .cv-ap-waiting-intro h3{margin:0 0 5px;color:#263a56;font-size:16px;font-weight:730}
        .cv-ap-waiting-intro p{margin:0;color:#78879b;font-size:11px}
        .cv-ap-review-label{margin:0 0 9px;color:#7c8a9e;font-size:9px;font-weight:800;letter-spacing:.05em;text-transform:uppercase}
        .cv-ap-review-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
        .cv-ap-review-item{min-height:80px;padding:13px 14px;background:#f8fafc;border:1px solid #edf1f6;border-radius:8px}
        .cv-ap-review-item-head{display:flex;align-items:center;gap:8px;margin-bottom:7px;color:#3c4f68;font-size:11px;font-weight:750}
        .cv-ap-review-item-head svg{width:18px;height:18px;color:#2865ed}
        .cv-ap-review-item p{margin:0;color:#738299;font-size:10px;line-height:1.45}
        .st-key-approved_datasheet_upload_card [data-testid="stWidgetLabel"] p{margin:2px 0 7px;color:#77869a;font-size:10px;font-weight:650}
        .st-key-approved_datasheet_upload_card [data-testid="stFileUploader"]{margin:0!important}
        .st-key-approved_datasheet_upload_card [data-testid="stFileUploaderDropzone"]{box-sizing:border-box;min-height:154px!important;border:1px dashed #b9c8dc!important;border-radius:10px!important;background:#fbfcfe!important;padding:24px 30px!important}
        .st-key-approved_datasheet_upload_card [data-testid="stFileUploaderDropzone"] button{min-height:38px!important;height:38px!important;border:1px solid #d5deea!important;border-radius:8px!important;background:#fff!important;color:#32445e!important;box-shadow:none!important}
        .st-key-approved_datasheet_upload_card [data-testid="stFileUploaderDropzoneInstructions"]{color:#738299!important}
        .st-key-approved_datasheet_upload_card [data-testid="stFileUploaderDropzoneInstructions"] p{font-size:11px!important}
        .cv-ap-document-state{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:0 0 16px;padding:9px 14px;background:#f8fafc;border:1px solid #edf1f6;border-radius:6px;color:#7d8ca0;font-size:10px}
        .cv-ap-document-state strong{color:#3c4f68;font-weight:700}
        .cv-ap-document-state .ready{color:#147a47;font-weight:700}
        .cv-ap-document-state .pending{color:#7d8ca0;font-weight:600}
        .st-key-approved_datasheet_question_panel,.st-key-approved_datasheet_source_panel{box-sizing:border-box;width:100%;margin:0 0 16px;padding:14px 16px 12px;background:#fff;border:1px solid #dfe7f1;border-radius:12px}
        .st-key-approved_datasheet_question_panel>[data-testid="stVerticalBlock"]{gap:.25rem}
        .st-key-approved_datasheet_question_panel [data-testid="stTextInput"] input{min-height:42px!important;border-radius:8px!important}
        .st-key-approved_datasheet_workspace{box-sizing:border-box;width:100%;max-width:1440px;margin:0 auto}
        .cv-dq-open-pdf-wrap{display:flex;width:100%;justify-content:flex-end}
        .cv-dq-document{display:flex;align-items:center;gap:12px;min-width:0;padding:12px 14px;border:1px solid #dfe7f1;border-radius:11px;background:#fff}
        .cv-dq-document-icon{display:flex;align-items:center;justify-content:center;flex:0 0 38px;width:38px;height:38px;border-radius:9px;background:#eff5ff;color:#2865ed;font-size:10px;font-weight:850}
        .cv-dq-document-copy{min-width:0;flex:1}.cv-dq-document-copy strong{display:block;overflow:hidden;color:#172942;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.cv-dq-document-copy span{display:block;margin-top:4px;color:#77869a;font-size:10px}
        .cv-dq-private{flex:0 0 auto;padding:5px 8px;border-radius:999px;background:#edf8f1;color:#147a47;font-size:9px;font-weight:750}
        .cv-dq-question-head{margin:0 0 8px}.cv-dq-question-head h2{margin:0 0 5px;color:#172942;font-size:15px;font-weight:760}.cv-dq-question-head p{margin:0;color:#78879b;font-size:11px;line-height:1.5}
        .cv-dq-current-question{margin:7px 0 12px;padding:11px 13px;border:1px solid #d6e0ee;border-radius:9px;background:#fff;color:#344a68;font-size:11px;line-height:1.45}
        .cv-dq-current-question small{display:block;margin-bottom:5px;color:#8291a7;font-size:8px;font-weight:800;letter-spacing:.06em}
        .cv-dq-follow-up-label{margin:14px 0 6px;color:#7d8ca1;font-size:9px;font-weight:800;letter-spacing:.05em}
        .st-key-approved_datasheet_question_panel .st-key-approved_datasheet_follow_up{box-sizing:border-box!important;width:100%!important;min-width:0!important}
        .st-key-approved_datasheet_question_panel .st-key-approved_datasheet_follow_up [data-testid="stElementContainer"]{display:flex!important;justify-content:flex-end!important;width:100%!important;min-width:0!important}
        .st-key-approved_datasheet_question_panel .st-key-approved_datasheet_follow_up button{box-sizing:border-box!important;width:100%!important;max-width:136px!important;min-width:0!important;min-height:40px!important;height:40px!important;padding:0 9px!important;border-radius:8px!important;font-size:10px!important;white-space:nowrap!important}
        .cv-dq-source-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:8px}.cv-dq-source-head p{margin:3px 0 0}
        .cv-dq-source-badge{padding:5px 8px;border-radius:999px;background:#eaf8f0;color:#147a47;font-size:9px;font-weight:750;white-space:nowrap}
        .cv-dq-viewer{overflow:hidden;border:1px solid #e1e8f1;border-radius:9px;background:#f4f7fb}
        .cv-dq-viewer-empty{display:flex;min-height:380px;align-items:center;justify-content:center;padding:24px;color:#7a8799;text-align:center;font-size:12px;line-height:1.5}
        .cv-dq-evidence-label{margin:15px 0 7px;color:#7c8a9e;font-size:9px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
        .cv-dq-limit-note{margin:8px 0 0;color:#8996a8;font-size:10px;line-height:1.45}
        .st-key-approved_datasheet_upload_card [data-testid="stFileUploaderDropzone"]{min-height:168px!important}
        .cv-ap-question-help{margin:2px 0 0;color:#8794a7;font-size:10px}
        .cv-ap-evidence-panel{box-sizing:border-box;width:100%;margin:0 0 14px;padding:14px 18px 10px;background:#fff;border:1px solid #dfe7f1;border-radius:12px}
        .cv-ap-evidence-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 9px}
        .cv-ap-evidence-head h2{margin:0;color:#172942;font-size:15px;font-weight:750}
        .cv-ap-evidence-head p{margin:0;color:#8391a4;font-size:10px;text-align:right}
        .cv-ap-evidence-panel .cv-ap-table th{background:#f8fafc}
        .cv-ap-datasheet-statuses{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:12px 0}
        .cv-ap-doc-status{display:flex;align-items:flex-start;gap:10px;min-width:0;padding:12px 14px;border:1px solid #dfe7f1;border-radius:10px;background:#fff}
        .cv-ap-doc-status__icon{display:flex;align-items:center;justify-content:center;flex:0 0 28px;width:28px;height:28px;border-radius:8px;background:#eaf8f0;color:#147a47;font-size:14px;font-weight:800}
        .cv-ap-doc-status.limited .cv-ap-doc-status__icon{background:#fff6df;color:#9a6500}
        .cv-ap-doc-status__copy{min-width:0;flex:1}
        .cv-ap-doc-status__copy strong{display:block;color:#273b57;font-size:11px;font-weight:760;overflow-wrap:anywhere}
        .cv-ap-doc-status__copy p{margin:4px 0 0;color:#718096;font-size:10px;line-height:1.45;overflow-wrap:anywhere}
        .cv-ap-doc-status__badge{flex:0 0 auto;padding:4px 7px;border-radius:999px;background:#eaf8f0;color:#147a47;font-size:8px;font-weight:850;letter-spacing:.035em;white-space:nowrap}
        .cv-ap-doc-status.limited .cv-ap-doc-status__badge{background:#fff6df;color:#9a6500}
        .cv-ap-no-text{margin:10px 0;padding:13px 15px;border:1px solid #f1d99a;border-radius:10px;background:#fffaf0;color:#705519;font-size:11px;line-height:1.5}
        .cv-ap-no-text strong{display:block;margin-bottom:3px;color:#654b10;font-size:12px}
        .cv-ap-field-table-wrap{overflow-x:auto;border:1px solid #dfe7f1;border-radius:10px;background:#fff}
        .cv-ap-field-table-wrap .cv-ap-table{min-width:720px}
        .cv-ap-field-table-wrap .cv-ap-table th{background:#f6f8fb;border-bottom:1px solid #dfe7f1}
        .cv-ap-field-table-wrap .cv-ap-table td{color:#34445a}
        @media(max-width:720px){.cv-ap-datasheet-statuses{grid-template-columns:1fr}}
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
        .cv-part-photo[data-illustration="generic"]{background:#f5f7fa;border-color:#dbe3ec;color:#53657b}
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
        section[data-testid="stMain"] [class*="st-key-approved_page_canvas_wide_"]{
          box-sizing:border-box!important;width:100%!important;max-width:1560px!important;min-width:0!important;
          margin-left:auto!important;margin-right:auto!important
        }
        section[data-testid="stMain"] [class*="st-key-approved_page_canvas_standard_"]>[data-testid="stVerticalBlock"],
        section[data-testid="stMain"] [class*="st-key-approved_page_canvas_wide_"]>[data-testid="stVerticalBlock"]{
          box-sizing:border-box!important;width:100%!important;max-width:100%!important;min-width:0!important
        }
        .st-key-approved_home_page{box-sizing:border-box!important;width:100%!important;max-width:1440px!important;margin-left:auto!important;margin-right:auto!important;padding:48px 0 28px!important}
        .st-key-approved_home_page > [data-testid="stVerticalBlock"]{gap:22px!important}
        .cv-ap-home-kpis{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:16px!important;margin:44px 0 0!important}
        /* Home CTA alignment is finalized in the late workspace stylesheet. */
        .cv-ap-home-kpi{display:flex!important;align-items:flex-start!important;gap:18px!important;box-sizing:border-box!important;min-height:190px!important;padding:24px 22px!important;border:1px solid #dce7f5!important;border-radius:16px!important;background:#f9fbff!important;box-shadow:0 2px 7px rgba(15,23,42,.035)!important}
        .cv-ap-home-kpi .cv-ap-home-icon{display:flex!important;align-items:center!important;justify-content:center!important;flex:0 0 60px!important;width:60px!important;height:60px!important;border-radius:50%!important;background:#e8f1ff!important;margin:0!important}
        .cv-ap-home-icon svg{width:30px!important;height:30px!important}
        .cv-ap-home-icon.warn{background:#fff3d5!important}
        .cv-ap-home-icon.risk{background:#fee9ed!important}
        .cv-ap-home-icon.ok{background:#e7f8ee!important}
        .cv-ap-home-kpi-copy{display:flex;flex:1;flex-direction:column;min-width:0;min-height:132px;padding-top:4px}
        .cv-ap-home-kpi .cv-ap-home-kpi-label{display:block!important;color:#64748b!important;font-size:16px!important;font-weight:650!important;line-height:1.3!important;white-space:nowrap}
        .cv-ap-home-kpi-copy strong{display:block!important;margin-top:8px!important;color:#0f172a!important;font-size:36px!important;font-weight:780!important;line-height:1.05!important;letter-spacing:-.04em!important;white-space:nowrap}
        .cv-ap-home-kpi-copy em{display:block!important;margin-top:auto!important;padding-top:14px!important;font-size:15px!important;line-height:1.25!important}
        .st-key-approved_home_recent_card{margin:26px 0 0!important;padding:0!important;border:1px solid #cbd8e8!important;border-radius:16px!important;background:#fff!important;box-shadow:0 3px 12px rgba(15,23,42,.045)!important}
        .st-key-approved_home_recent_card [data-testid="stVerticalBlock"]{gap:0!important}
        .st-key-approved_home_recent_card [data-testid="stElementContainer"]{margin:0!important;padding:0!important}
        .cv-ap-home-table-head{display:grid!important;grid-template-columns:2.25fr 1.35fr .76fr .84fr 1fr 1.18fr .68fr!important;align-items:center!important;gap:16px!important;box-sizing:border-box!important;min-height:68px!important;padding:0 30px!important;background:#f7f9fc!important;border-top:1px solid #e5ebf3!important;border-bottom:1px solid #dce4ef!important}
        .cv-ap-home-table-head [role="columnheader"]{display:flex;align-items:center;min-width:0;min-height:48px;overflow:visible;color:#64748b;font-size:14px;font-weight:750;line-height:1.25;letter-spacing:.035em;text-transform:uppercase;white-space:normal;overflow-wrap:anywhere}
        .cv-ap-home-table-head [role="columnheader"]:nth-child(n+3){justify-content:center!important;text-align:center}
        .st-key-approved_home_recent_heading{margin:0!important;padding:22px 26px 16px!important}
        .st-key-approved_home_recent_heading [data-testid="stVerticalBlock"]{gap:0!important}
        .st-key-approved_home_recent_heading [data-testid="stHorizontalBlock"]{align-items:center!important}
        .st-key-approved_home_recent_heading [data-testid="stHorizontalBlock"]>div:first-child{box-sizing:border-box!important;flex:1 1 0%!important;width:auto!important;min-width:0!important}
        .st-key-approved_home_recent_heading [data-testid="stHorizontalBlock"]>div:last-child{box-sizing:border-box!important;flex:0 0 128px!important;width:128px!important;min-width:128px!important}
        .st-key-approved_home_recent_heading [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"]{align-items:flex-end!important}
        .cv-ap-home-recent-heading{padding:0!important}
        .cv-ap-home-recent-heading h2{margin:0 0 5px!important;color:#0f172a!important;font-size:28px!important;font-weight:760!important;line-height:1.2!important;letter-spacing:-.025em!important}
        .st-key-approved_home_view_all_wrap [data-testid="stVerticalBlock"]{width:100%!important}
        .st-key-approved_home_view_all_wrap [data-testid="stElementContainer"]{display:flex!important;justify-content:flex-end!important;width:100%!important}
        [class*="st-key-approved_home_view_all"] button,[class*="st-key-approved_home_view_all"] button *{color:#2563eb!important}
        .cv-ap-home-recent-heading p{margin:0!important;color:#64748b!important;font-size:16px!important;line-height:1.4!important}
        [class*="st-key-approved_home_view_all"] button{width:108px!important;max-width:108px!important;min-width:100px!important;height:48px!important;min-height:48px!important;margin-left:auto!important;padding:0 12px!important;border:1px solid #bfdbfe!important;border-radius:10px!important;background:#eaf2ff!important;color:#2563eb!important;box-shadow:none!important;font-size:15px!important;font-weight:700!important}
        [class*="st-key-approved_home_view_all"] button *,[class*="st-key-approved_home_view_all"] button p,[class*="st-key-approved_home_view_all"] button span{color:#2563eb!important}
        [class*="st-key-approved_home_view_all"] button:hover{background:#dbeafe!important;border-color:#93b4ee!important}
        [class*="st-key-approved_home_new_bom"] button,[class*="st-key-approved_home_new_bom"] button p,[class*="st-key-approved_home_new_bom"] button span{white-space:nowrap!important}
        [class*="st-key-approved_home_row_"]{box-sizing:border-box!important;min-height:120px!important;margin:0!important;padding:18px 30px!important;border-top:0!important;border-bottom:1px solid #e5ebf3!important;background:#fff!important}
        .st-key-approved_home_recent_card .st-key-approved_home_row_last{border-radius:0 0 15px 15px!important;border-bottom:0!important;background:#fff!important}
        [class*="st-key-approved_home_row_"] [data-testid="stVerticalBlock"]{display:flex!important;flex-direction:column!important;gap:0!important;justify-content:center!important;min-height:84px!important}
        [class*="st-key-approved_home_row_"] [data-testid="stElementContainer"]{margin:0!important;padding:0!important}
        [class*="st-key-approved_home_row_"] [data-testid="stHorizontalBlock"]{align-items:stretch!important;min-height:84px!important}
        [class*="st-key-approved_home_row_"] [data-testid="column"]{align-self:stretch!important;display:flex!important;align-items:center!important;justify-content:center!important;min-height:84px!important}
        [class*="st-key-approved_home_row_"] [data-testid="column"]:nth-child(-n+2){justify-content:flex-start!important}
        [class*="st-key-approved_home_row_"] [data-testid="column"] [data-testid="stMarkdownContainer"]{width:100%!important}
        [class*="st-key-approved_home_row_"] [data-testid="column"]:nth-child(n+3) [data-testid="stVerticalBlock"]{align-items:center!important}
        .cv-ap-home-cell-center{display:flex;align-items:center;justify-content:center;width:100%;min-height:38px;text-align:center;line-height:1.25}
        [class*="st-key-approved_home_row_"] [data-testid="stVerticalBlock"]{justify-content:center!important}
        [class*="st-key-approved_home_row_"] [data-testid="stMarkdownContainer"] p{margin:0!important;color:#52647b!important;font-size:14px!important;line-height:1.35!important}
        .cv-ap-home-bom{display:flex;align-items:center;gap:16px;min-width:0;min-height:84px}
        .cv-ap-home-row-icon{display:inline-flex;align-items:center;justify-content:center;flex:0 0 48px;width:48px;height:48px;border-radius:50%;background:#edf4ff;color:#2563eb}
        .cv-ap-home-row-icon svg{width:24px;height:24px;display:block}
        .cv-ap-home-bom-copy{display:flex;flex:1;flex-direction:column;min-width:0}
        .cv-ap-home-bom .cv-ap-name{display:block;min-width:0;color:#17253e;font-size:15px;font-weight:750;line-height:1.28;white-space:normal;overflow-wrap:anywhere}
        .cv-ap-home-bom small{display:block;margin-top:4px;overflow:hidden;color:#74839a;font-size:13px;line-height:1.25;text-overflow:ellipsis;white-space:nowrap}
        .cv-ap-home-project{display:flex;align-items:center;min-width:0;min-height:84px;overflow:visible;color:#52647b;font-size:14px;line-height:1.3;white-space:normal;overflow-wrap:anywhere}
        .st-key-approved_home_recent_card .cv-pill{min-height:40px;padding:8px 12px;font-size:14px;font-weight:750}
        .st-key-approved_home_recent_card .cv-pill-dot{width:8px;height:8px;flex-basis:8px}
        .cv-home-risk-count{display:inline-flex;align-items:center;justify-content:center;min-width:52px;min-height:40px;padding:0 12px;border-radius:12px;background:#fee9ed;color:#d81b43;font-size:16px;font-weight:750;line-height:1}
        .cv-home-risk-count.clear{background:#dcfce7;color:#15803d}
        [class*="st-key-approved_home_menu_"] [data-testid="stPopover"] button[aria-expanded]{display:inline-flex!important;align-items:center!important;justify-content:center!important;width:44px!important;min-width:44px!important;height:44px!important;min-height:44px!important;padding:0!important;border:0!important;border-radius:10px!important;background:transparent!important;color:#64748b!important;box-shadow:none!important;font-size:22px!important;font-weight:750!important;line-height:1!important}
        [class*="st-key-approved_home_menu_"] [data-testid="stPopover"] button[aria-expanded] svg,[class*="st-key-approved_home_menu_"] [data-testid="stPopover"] button[aria-expanded] [data-testid="stIconMaterial"]{display:none!important}
        [class*="st-key-approved_home_row_"] [data-testid="stColumn"]:last-child{text-align:right}
        .cv-ap-home-empty{padding:26px 24px;color:#64748b;font-size:16px}
        @media(max-width:1600px){
          .st-key-approved_home_page{padding:36px 0 24px!important}
          .st-key-approved_home_header .cv-ap h1{font-size:30px!important;line-height:1.12!important}
          .st-key-approved_home_header .cv-ap-sub{font-size:17px!important}
          [class*="st-key-approved_home_new_bom"] button,[class*="st-key-approved_home_open_reports"] button{min-height:48px!important;height:48px!important;padding:0 14px!important;font-size:14px!important}
          .cv-ap-home-kpis{gap:12px!important;margin-top:30px!important}
          .cv-ap-home-kpi{gap:12px!important;min-height:150px!important;padding:18px 16px!important}
          .cv-ap-home-kpi .cv-ap-home-icon{flex-basis:52px!important;width:52px!important;height:52px!important}
          .cv-ap-home-icon svg{width:26px!important;height:26px!important}
          .cv-ap-home-kpi-copy{min-height:100px}
          .cv-ap-home-kpi .cv-ap-home-kpi-label{font-size:15px!important}
          .cv-ap-home-kpi-copy strong{margin-top:8px!important;font-size:34px!important}
          .cv-ap-home-kpi-copy em{padding-top:8px!important;font-size:13px!important}
          .st-key-approved_home_recent_card{margin-top:18px!important}
          .st-key-approved_home_recent_heading{padding:16px 18px 12px!important}
          .cv-ap-home-recent-heading h2{font-size:20px!important}
          .cv-ap-home-recent-heading p{font-size:13px!important}
          [class*="st-key-approved_home_view_all"] button{width:92px!important;max-width:92px!important;min-width:86px!important;height:40px!important;min-height:40px!important;padding:0 10px!important;font-size:13px!important}
          .cv-ap-home-table-head{gap:12px!important;min-height:56px!important;padding:0 16px!important}
          .cv-ap-home-table-head [role="columnheader"]{font-size:12px!important;letter-spacing:.025em!important}
          [class*="st-key-approved_home_row_"]{min-height:112px!important;padding:18px 22px!important}
          [class*="st-key-approved_home_row_"] [data-testid="stHorizontalBlock"]{align-items:stretch!important;gap:12px!important;min-height:76px!important}
          [class*="st-key-approved_home_row_"] [data-testid="column"]{min-height:76px!important}
          [class*="st-key-approved_home_row_"] [data-testid="stVerticalBlock"]{min-height:76px!important}
          [class*="st-key-approved_home_row_"] [data-testid="stMarkdownContainer"] p{font-size:14px!important}
          .cv-ap-home-bom{gap:16px!important;min-height:76px}
          .cv-ap-home-row-icon{flex-basis:48px;width:48px;height:48px}
          .cv-ap-home-row-icon svg{width:24px;height:24px}
          .cv-ap-home-bom .cv-ap-name{font-size:14px}
          .cv-ap-home-bom small{font-size:11px}
          .cv-ap-home-project{min-height:76px;font-size:14px}
          .st-key-approved_home_recent_card .cv-pill{min-height:38px;padding:8px 10px;font-size:14px}
          .st-key-approved_home_recent_card .cv-pill-dot{width:7px;height:7px;flex-basis:7px}
          .cv-home-risk-count{min-width:48px;min-height:38px;padding:0 10px;font-size:16px}
          [class*="st-key-approved_home_menu_"] [data-testid="stPopover"] button[aria-expanded]{width:36px!important;min-width:36px!important;height:36px!important;min-height:36px!important;font-size:18px!important}
          .cv-ap-home-empty{padding:18px 16px;font-size:14px}
        }
        @media(max-width:1250px){
          .st-key-approved_home_page{padding:22px 0 20px!important}
          .st-key-approved_home_header .cv-ap h1{font-size:26px!important;line-height:1.14!important}
          .st-key-approved_home_header .cv-ap-sub{font-size:15px!important}
          [class*="st-key-approved_home_new_bom"] button,[class*="st-key-approved_home_open_reports"] button{min-height:42px!important;height:42px!important;padding:0 10px!important;font-size:13px!important}
          .cv-ap-home-kpis{gap:10px!important;margin-top:18px!important}
          .cv-ap-home-kpi{gap:10px!important;min-height:124px!important;padding:12px 10px!important}
          .cv-ap-home-kpi .cv-ap-home-icon{flex-basis:40px!important;width:40px!important;height:40px!important}
          .cv-ap-home-icon svg{width:20px!important;height:20px!important}
          .cv-ap-home-kpi-copy{min-height:88px;padding-top:1px}
          .cv-ap-home-kpi .cv-ap-home-kpi-label{font-size:12px!important}
          .cv-ap-home-kpi-copy strong{margin-top:6px!important;font-size:26px!important}
          .cv-ap-home-kpi-copy em{padding-top:6px!important;font-size:11px!important}
          .st-key-approved_home_recent_card{margin-top:14px!important}
          .st-key-approved_home_recent_heading{padding:12px!important}
          .cv-ap-home-recent-heading h2{font-size:19px!important}
          .cv-ap-home-recent-heading p{font-size:12px!important}
          [class*="st-key-approved_home_view_all"] button{width:78px!important;max-width:78px!important;min-width:76px!important;height:34px!important;min-height:34px!important;padding:0 6px!important;font-size:11px!important}
          .cv-ap-home-table-head{gap:8px!important;min-height:44px!important;padding:0 12px!important}
          .cv-ap-home-table-head [role="columnheader"]{font-size:10px!important;letter-spacing:.015em!important}
          [class*="st-key-approved_home_row_"]{min-height:96px!important;padding:16px!important}
          [class*="st-key-approved_home_row_"] [data-testid="stHorizontalBlock"]{align-items:stretch!important;gap:8px!important;min-height:64px!important}
          [class*="st-key-approved_home_row_"] [data-testid="column"]{min-height:64px!important}
          [class*="st-key-approved_home_row_"] [data-testid="stVerticalBlock"]{min-height:64px!important}
          [class*="st-key-approved_home_row_"] [data-testid="stMarkdownContainer"] p{font-size:12px!important}
          .cv-ap-home-bom{gap:12px!important;min-height:64px}
          .cv-ap-home-row-icon{flex-basis:38px;width:38px;height:38px}
          .cv-ap-home-row-icon svg{width:20px;height:20px}
          .cv-ap-home-bom .cv-ap-name{font-size:12px}
          .cv-ap-home-bom small{font-size:10px}
          .cv-ap-home-project{min-height:64px;font-size:12px}
          .st-key-approved_home_recent_card .cv-pill{min-height:30px;padding:6px 8px;font-size:12px}
          .st-key-approved_home_recent_card .cv-pill-dot{width:6px;height:6px;flex-basis:6px}
          .cv-home-risk-count{min-width:38px;min-height:30px;padding:0 8px;font-size:14px}
          [class*="st-key-approved_home_menu_"] [data-testid="stPopover"] button[aria-expanded]{width:32px!important;min-width:32px!important;height:32px!important;min-height:32px!important;font-size:16px!important}
          .cv-ap-home-empty{padding:14px 12px;font-size:13px}
        }
        @media(max-width:900px){.st-key-approved_home_header .cv-ap h1{font-size:24px!important}}
        @media(max-width:1100px){.st-key-approved_home_page{padding:22px 0 20px!important}.cv-ap-home-kpis{grid-template-columns:repeat(2,minmax(0,1fr))!important}.cv-ap-home-kpi{min-height:124px!important}.cv-ap-home-kpi-copy{min-height:88px}}

        @media(max-width:700px){.st-key-approved_home_page{padding:24px 0!important}.st-key-approved_home_header [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}.st-key-approved_home_header .cv-ap h1{font-size:34px!important}.st-key-approved_home_header .cv-ap-sub{font-size:16px!important}.cv-ap-home-kpis{grid-template-columns:1fr!important;gap:12px!important}.cv-ap-home-kpi{min-height:132px!important;padding:18px!important}.cv-ap-home-kpi-copy{min-height:90px}.st-key-approved_home_recent_heading{padding:18px 16px 14px!important}[class*="st-key-approved_home_row_"]{padding:12px 16px!important}}
        .st-key-approved_saved_bom_settings_page{box-sizing:border-box!important;width:100%!important;max-width:760px!important;margin:0 auto 24px!important;padding:0!important}
        .st-key-approved_saved_bom_settings_page>[data-testid="stVerticalBlock"]{gap:12px!important}
        .st-key-approved_saved_bom_edit_screen,.st-key-approved_saved_bom_delete_screen{box-sizing:border-box!important;width:100%!important;max-width:none!important;margin:0 auto!important;padding:22px!important;border:1px solid #d7e0eb!important;border-radius:16px!important;background:#fff!important}
        .st-key-approved_saved_bom_delete_screen button[kind="primary"]{background:#be123c!important;border-color:#be123c!important}
        .st-key-approved_monitoring_kpi_grid{box-sizing:border-box!important;width:100%!important;margin:0 0 20px!important}
        .st-key-approved_monitoring_kpi_grid>[data-testid="stVerticalBlock"]{gap:0!important}
        .st-key-approved_monitoring_kpi_grid [data-testid="stHorizontalBlock"]{display:flex!important;flex-flow:row nowrap!important;justify-content:flex-start!important;gap:16px!important;align-items:stretch!important}
        .st-key-approved_monitoring_kpi_grid [data-testid="column"]{box-sizing:border-box!important;display:flex!important;flex:1 1 0!important;width:0!important;max-width:none!important;min-width:0!important;padding:0!important}
        .st-key-approved_monitoring_kpi_grid [data-testid="column"]>[data-testid="stVerticalBlock"]{box-sizing:border-box!important;width:100%!important;max-width:none!important;min-width:0!important}
        .st-key-approved_monitoring_kpi_active,.st-key-approved_monitoring_kpi_high,.st-key-approved_monitoring_kpi_lifecycle,.st-key-approved_monitoring_kpi_inventory{position:relative!important;box-sizing:border-box!important;display:block!important;flex:1 1 0!important;width:100%!important;max-width:none!important;min-width:0!important}
        .st-key-approved_monitoring_kpi_active>[data-testid="stVerticalBlock"],.st-key-approved_monitoring_kpi_high>[data-testid="stVerticalBlock"],.st-key-approved_monitoring_kpi_lifecycle>[data-testid="stVerticalBlock"],.st-key-approved_monitoring_kpi_inventory>[data-testid="stVerticalBlock"]{box-sizing:border-box!important;position:relative!important;display:block!important;width:100%!important;max-width:none!important;min-width:0!important;min-height:188px!important;gap:0!important}
        .cv-ap-monitoring-kpi{display:grid!important;grid-template-columns:minmax(0,1fr) 116px!important;grid-template-rows:58px auto!important;align-items:center!important;column-gap:12px!important;row-gap:12px!important;box-sizing:border-box!important;width:100%!important;min-width:0!important;min-height:188px!important;padding:20px 24px!important;border:1px solid #e3ebf6!important;border-radius:14px!important;background:linear-gradient(135deg,#fbfdff 0%,#f7faff 100%)!important;box-shadow:0 2px 7px rgba(15,23,42,.035)!important}
        .cv-ap-monitoring-icon{grid-column:1;grid-row:1;display:inline-flex!important;align-items:center!important;justify-content:center!important;width:52px!important;height:52px!important;border-radius:50%!important}
        .cv-ap-monitoring-icon svg{width:28px!important;height:28px!important;display:block!important}
        .cv-ap-monitoring-kpi--blue .cv-ap-monitoring-icon{background:#e6f0ff!important;color:#2563eb!important}
        .cv-ap-monitoring-kpi--red .cv-ap-monitoring-icon{background:#ffe9e9!important;color:#ef4444!important}
        .cv-ap-monitoring-kpi--violet .cv-ap-monitoring-icon{background:#f1eaff!important;color:#8b5cf6!important}
        .cv-ap-monitoring-kpi--green .cv-ap-monitoring-icon{background:#e3f8ed!important;color:#16a34a!important}
        .cv-ap-monitoring-copy{grid-column:1;grid-row:2;min-width:0;align-self:start}
        .cv-ap-monitoring-copy>span{display:block;overflow:hidden;color:#52647b!important;font-size:18px!important;font-weight:600!important;line-height:1.3!important;text-overflow:ellipsis;white-space:nowrap}
        .cv-ap-monitoring-copy strong{display:flex!important;align-items:center!important;gap:12px!important;margin-top:5px;color:#12213b!important;font-size:40px!important;font-weight:650!important;line-height:1!important;letter-spacing:-.035em!important}
        .cv-ap-monitoring-chevron{color:#64748b!important;font-size:34px!important;font-weight:400!important;line-height:1!important}
        .cv-ap-monitoring-kpi .cv-ap-spark{grid-column:2;grid-row:1/3;align-self:center;width:112px!important;max-width:100%!important;height:56px!important}
        .st-key-approved_monitoring_kpi_active [class*="st-key-approved_monitoring_action_"],.st-key-approved_monitoring_kpi_high [class*="st-key-approved_monitoring_action_"],.st-key-approved_monitoring_kpi_lifecycle [class*="st-key-approved_monitoring_action_"],.st-key-approved_monitoring_kpi_inventory [class*="st-key-approved_monitoring_action_"]{position:absolute!important;inset:0!important;z-index:3!important;margin:0!important;padding:0!important;opacity:0!important}
        .st-key-approved_monitoring_kpi_active [class*="st-key-approved_monitoring_action_"] button,.st-key-approved_monitoring_kpi_high [class*="st-key-approved_monitoring_action_"] button,.st-key-approved_monitoring_kpi_lifecycle [class*="st-key-approved_monitoring_action_"] button,.st-key-approved_monitoring_kpi_inventory [class*="st-key-approved_monitoring_action_"] button{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;min-height:188px!important;cursor:pointer!important}
        .st-key-approved_monitoring_kpi_active [class*="st-key-approved_monitoring_action_"]:focus-within,.st-key-approved_monitoring_kpi_high [class*="st-key-approved_monitoring_action_"]:focus-within,.st-key-approved_monitoring_kpi_lifecycle [class*="st-key-approved_monitoring_action_"]:focus-within,.st-key-approved_monitoring_kpi_inventory [class*="st-key-approved_monitoring_action_"]:focus-within{opacity:1!important}
        .st-key-approved_monitoring_kpi_active [class*="st-key-approved_monitoring_action_"] button:focus-visible,.st-key-approved_monitoring_kpi_high [class*="st-key-approved_monitoring_action_"] button:focus-visible,.st-key-approved_monitoring_kpi_lifecycle [class*="st-key-approved_monitoring_action_"] button:focus-visible,.st-key-approved_monitoring_kpi_inventory [class*="st-key-approved_monitoring_action_"] button:focus-visible{opacity:1!important;color:transparent!important;background:rgba(255,255,255,.04)!important;outline:3px solid #2563eb!important;outline-offset:-4px!important}
        .st-key-approved_monitoring_filters{box-sizing:border-box!important;width:100%!important;margin:0 0 22px!important;padding:14px 20px!important;border:1px solid #e3ebf6!important;border-radius:12px!important;background:#fff!important;box-shadow:0 2px 7px rgba(15,23,42,.025)!important}
        .st-key-approved_monitoring_filters>[data-testid="stVerticalBlock"]{gap:0!important}
        .st-key-approved_monitoring_filters [data-testid="stHorizontalBlock"]{align-items:center!important;gap:10px!important}
        .st-key-approved_monitoring_filters [data-testid="stWidgetLabel"] p{margin:0 0 5px!important;color:#52647b!important;font-size:12px!important;font-weight:700!important}
        .cv-ap-monitoring-show-label{display:flex;align-items:center;min-height:42px;color:#52647b;font-size:12px;font-weight:700}
        .cv-ap-monitoring-period-label{display:flex;align-items:center;min-height:42px;color:#52647b;font-size:14px;font-weight:650;white-space:nowrap}
        .st-key-approved_monitoring_category_row{box-sizing:border-box!important;width:100%!important;min-width:0!important}
        .st-key-approved_monitoring_category_row [data-testid="stPills"],.st-key-approved_monitoring_category_row [role="radiogroup"],.st-key-approved_monitoring_category_row [data-baseweb="button-group"]{display:flex!important;flex-flow:row wrap!important;justify-content:flex-start!important;align-items:center!important;gap:8px!important;width:100%!important;min-width:0!important}
        .st-key-approved_monitoring_category_row button,.st-key-approved_monitoring_category_row [role="radio"],.st-key-approved_monitoring_category_row [role="option"]{box-sizing:border-box!important;flex:0 0 auto!important;width:auto!important;min-width:0!important;min-height:42px!important;height:42px!important;padding:0 13px!important;border:1px solid #dce4ef!important;border-radius:999px!important;background:#fff!important;color:#52647b!important;box-shadow:none!important;font-size:12px!important;font-weight:600!important;white-space:nowrap!important}
        .st-key-approved_monitoring_category_row button:hover,.st-key-approved_monitoring_category_row [role="radio"]:hover,.st-key-approved_monitoring_category_row [role="option"]:hover{border-color:#9bbdf5!important;background:#f8fbff!important;color:#2563eb!important}
        .st-key-approved_monitoring_category_row button[aria-checked="true"],.st-key-approved_monitoring_category_row button[aria-pressed="true"],.st-key-approved_monitoring_category_row [role="radio"][aria-checked="true"],.st-key-approved_monitoring_category_row [role="option"][aria-selected="true"]{border-color:#70a4ff!important;background:#edf5ff!important;color:#2563eb!important}
        .st-key-approved_monitoring_period_control{box-sizing:border-box!important;width:100%!important}
        .st-key-approved_monitoring_period_control>[data-testid="stVerticalBlock"]{gap:0!important}
        .cv-ap-monitoring-calendar{display:flex;align-items:center;justify-content:center;min-height:42px;color:#52647b}
        .cv-ap-monitoring-calendar svg{width:18px;height:18px}
        .st-key-approved_monitoring_filters [data-testid="stSelectbox"] [data-baseweb="select"]>div{min-height:42px!important;border:1px solid #d9e2ee!important;border-radius:9px!important;background:#fff!important}
        .st-key-approved_monitoring_alert_heading{box-sizing:border-box!important;width:100%!important;margin:0!important;padding:18px 20px 12px!important}
        .st-key-approved_monitoring_alert_heading>[data-testid="stVerticalBlock"]{gap:0!important}
        .cv-ap-monitoring-heading h2{margin:0!important;color:#14233d!important;font-size:20px!important;font-weight:760!important;line-height:1.25!important;letter-spacing:-.02em!important}
        .cv-ap-monitoring-heading p{margin:4px 0 0!important;color:#64748b!important;font-size:12px!important}
        .cv-ap-monitoring-count{color:#64748b!important;font-size:12px!important;text-align:right!important;white-space:nowrap}
        .cv-ap-monitoring-table-head{display:grid!important;grid-template-columns:.8fr 1.3fr 1.9fr 1.2fr 1.2fr .28fr!important;align-items:center!important;gap:12px!important;box-sizing:border-box!important;min-height:54px!important;margin:0 20px 4px!important;padding:0 14px!important;border-radius:10px!important;background:#f0f4f9!important}
        .cv-ap-monitoring-table-head [role="columnheader"]{display:flex!important;align-items:center!important;gap:5px!important;min-width:0!important;min-height:44px!important;color:#52647b!important;font-size:14px!important;font-weight:600!important;letter-spacing:0!important;text-transform:none!important;text-align:left!important;white-space:nowrap!important}
        .cv-ap-monitoring-sort{color:#718199!important;font-size:16px!important;font-weight:500!important;line-height:1!important}
        [class*="st-key-approved_monitoring_alert_row_"]{box-sizing:border-box!important;min-height:76px!important;margin:0 20px!important;padding:10px 14px!important;border-bottom:1px solid #e5ebf3!important;background:#fff!important}
        [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stVerticalBlock"]{gap:0!important}
        [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stHorizontalBlock"]{align-items:center!important;gap:12px!important}
        [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stColumn"],[class*="st-key-approved_monitoring_alert_row_"] [data-testid="column"]{box-sizing:border-box!important;min-width:0!important;padding:4px 5px!important;display:flex!important;align-items:center!important}
        [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stMarkdownContainer"] p{margin:0!important;color:#52647b!important;font-size:13px!important;line-height:1.4!important;overflow-wrap:anywhere!important}
        [class*="st-key-approved_monitoring_alert_row_"] .cv-ap-meta{margin-top:3px!important;font-size:11px!important}
        .cv-ap-monitoring-detected{width:100%;color:#52647b;text-align:left;font-size:12px;line-height:1.35}
        .cv-ap-monitoring-detected strong{display:block;color:#34445d;font-size:12px;font-weight:650}
        .cv-ap-monitoring-detected small{display:block;margin-top:3px;color:#8090a5;font-size:10px}
        [class*="st-key-approved_alert_action_"] button{min-height:42px!important;height:auto!important;padding:7px 12px!important;border:1px solid #8db7ff!important;border-radius:9px!important;background:#fff!important;color:#2563eb!important;white-space:normal!important;font-size:14px!important;font-weight:650!important;box-shadow:none!important}
        [class*="st-key-approved_alert_action_"] button:hover{border-color:#5b96f5!important;background:#f4f8ff!important}
        [class*="st-key-approved_alert_more_"] [data-testid="stPopover"]>button{display:flex!important;align-items:center!important;justify-content:center!important;width:40px!important;min-width:40px!important;height:40px!important;min-height:40px!important;padding:0!important;border:0!important;border-radius:8px!important;background:transparent!important;color:#64748b!important;font-size:22px!important;box-shadow:none!important}
        [class*="st-key-approved_alert_more_"] [data-testid="stPopover"]>button:hover{background:#f1f5f9!important;color:#2563eb!important}
        .cv-ap-alert-popover{min-width:220px;max-width:340px;padding:2px 1px;color:#34445d;font-size:13px;line-height:1.45}
        .cv-ap-alert-popover strong,.cv-ap-alert-popover span{display:block;color:#172942;font-size:14px;font-weight:750}
        .cv-ap-alert-popover span{margin-top:3px;color:#53647d;font-size:12px;font-weight:650}
        .cv-ap-alert-popover p{margin:8px 0;color:#52647b;font-size:12px}
        .cv-ap-alert-popover small{color:#8794a7;font-size:10px}
        .cv-ap-table-center{width:100%;display:flex;align-items:center;justify-content:center;text-align:center}
        @media(max-width:1100px){[class*="st-key-approved_home_new_bom"],[class*="st-key-approved_home_open_reports"]{left:0!important}}
        @media(max-width:1100px){.st-key-approved_monitoring_kpi_grid [data-testid="stHorizontalBlock"]{gap:12px!important}.st-key-approved_monitoring_kpi_grid [data-testid="column"]{flex:1 1 0!important;width:0!important;max-width:none!important}.cv-ap-monitoring-kpi{min-height:164px!important;padding:16px!important;grid-template-columns:minmax(0,1fr) 76px!important}.cv-ap-monitoring-copy>span{font-size:14px!important}.cv-ap-monitoring-copy strong{font-size:32px!important;gap:8px!important}.cv-ap-monitoring-chevron{font-size:26px!important}.st-key-approved_monitoring_kpi_active>[data-testid="stVerticalBlock"],.st-key-approved_monitoring_kpi_high>[data-testid="stVerticalBlock"],.st-key-approved_monitoring_kpi_lifecycle>[data-testid="stVerticalBlock"],.st-key-approved_monitoring_kpi_inventory>[data-testid="stVerticalBlock"]{min-height:164px!important}.st-key-approved_monitoring_kpi_active [class*="st-key-approved_monitoring_action_"] button,.st-key-approved_monitoring_kpi_high [class*="st-key-approved_monitoring_action_"] button,.st-key-approved_monitoring_kpi_lifecycle [class*="st-key-approved_monitoring_action_"] button,.st-key-approved_monitoring_kpi_inventory [class*="st-key-approved_monitoring_action_"] button{min-height:164px!important}.cv-ap-monitoring-kpi .cv-ap-spark{width:76px!important}.st-key-approved_monitoring_filters [data-testid="stHorizontalBlock"]{gap:8px!important}}
        @media(max-width:1200px){
          .st-key-approved_monitoring_filters [data-testid="stHorizontalBlock"]:has(.st-key-approved_monitoring_category_row){display:grid!important;grid-template-columns:42px minmax(0,1fr)!important;align-items:start!important;gap:8px!important}
          .st-key-approved_monitoring_filters [data-testid="stHorizontalBlock"]:has(.st-key-approved_monitoring_category_row)>[data-testid="column"]{box-sizing:border-box!important;width:auto!important;max-width:none!important;min-width:0!important;flex:none!important;padding:0!important}
          .st-key-approved_monitoring_filters [data-testid="column"]:has(.cv-ap-monitoring-show-label){grid-column:1!important;grid-row:1!important;align-self:start!important}
          .st-key-approved_monitoring_filters [data-testid="column"]:has(.st-key-approved_monitoring_category_row){grid-column:2!important;grid-row:1!important}
          .st-key-approved_monitoring_filters [data-testid="column"]:has(.st-key-approved_monitoring_period_control){grid-column:1 / -1!important;grid-row:2!important}
          .st-key-approved_monitoring_period_control{width:340px!important;max-width:100%!important;margin-left:auto!important}
          .cv-ap-monitoring-show-label{font-size:11px!important}
        }
        @media(max-width:900px){.st-key-approved_monitoring_filters{padding:12px!important}.st-key-approved_monitoring_alert_heading{padding:14px 14px 10px!important}.cv-ap-monitoring-heading h2{font-size:18px!important}}
        @media(max-width:640px){.st-key-approved_monitoring_period_control{width:100%!important}.st-key-approved_monitoring_filters [data-testid="column"]:has(.cv-ap-monitoring-show-label){align-self:start!important}.st-key-approved_monitoring_category_row button,.st-key-approved_monitoring_category_row [role="radio"],.st-key-approved_monitoring_category_row [role="option"]{min-height:38px!important;height:38px!important;padding:0 10px!important;font-size:11px!important}}
        @media(max-width:640px){.st-key-approved_monitoring_kpi_grid [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}.st-key-approved_monitoring_kpi_grid [data-testid="column"]{flex:1 1 calc(50% - 8px)!important;width:auto!important}.cv-ap-monitoring-kpi{min-height:150px!important}.st-key-approved_monitoring_alert_heading{padding:14px 14px 10px!important}.cv-ap-monitoring-heading h2{font-size:18px!important}}
        @media(max-width:1100px){
          .cv-ap-monitoring-table-head{gap:8px!important;padding:0 12px!important;margin-left:14px!important;margin-right:14px!important}
          [class*="st-key-approved_monitoring_alert_row_"]{padding:8px 12px!important;margin-left:14px!important;margin-right:14px!important}
          [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stHorizontalBlock"]{gap:8px!important}
          [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stMarkdownContainer"] p{font-size:12px!important}
        }
        @media(max-width:760px){
          .cv-ap-monitoring-table-head,[class*="st-key-approved_monitoring_alert_row_"]{min-width:790px!important}
        }
        .cv-pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:3px 8px;font-size:12px;font-weight:750}
        .cv-pill-dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex:0 0 7px}
        .cv-pill.high{background:#ffe4e6;color:#be123c}
        .cv-pill.medium{background:#fef3c7;color:#b45309}
        .cv-pill.low{background:#dcfce7;color:#15803d}
        .cv-pill.verify{background:#e2e8f0;color:#475569}
        .cv-pill.open{background:#dbeafe;color:#1d4ed8}
        .cv-ap-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:22px}
        .cv-ap-template{background:#f8fafc;border:1px solid #e6edf5;border-radius:16px;padding:18px}
        .cv-ap-template h3{margin:8px 0 6px;font-size:16px}
        .cv-ap-template p{margin:0 0 12px;color:#64748b;font-size:13px}
        .cv-ap-chip{display:inline-flex;margin-right:6px;padding:2px 8px;border-radius:999px;background:#e0e7ff;color:#3730a3;font-size:11px;font-weight:750}
        .cv-ap-chip-icon{width:36px;height:36px;vertical-align:middle;margin-right:8px}
        [class*="st-key-cv_candidate_hit_"]{position:relative;border-radius:12px;transition:background .15s ease,box-shadow .15s ease}
        [class*="st-key-cv_candidate_hit_"]:hover{background:#f8fbff}
        [class*="st-key-cv_candidate_hit_"]:has(button:focus-visible){background:#f8fbff;box-shadow:inset 0 0 0 2px #bfdbfe}
        [class*="st-key-cv_candidate_row_open_"] [class*="st-key-cv_candidate_hit_"]{background:#f8fbff}
        [class*="st-key-cv_candidate_hit_"] [data-testid="stHorizontalBlock"],[class*="st-key-cv_candidate_hit_"] [data-testid="stColumn"],[class*="st-key-cv_candidate_hit_"] [data-testid="column"],[class*="st-key-cv_candidate_hit_"] [class*="st-key-cv_candidate_open_"],[class*="st-key-cv_candidate_hit_"] [data-testid="stButton"]{position:static !important;overflow:visible !important}
        [class*="st-key-cv_candidate_open_"] button{position:static !important;background:transparent !important;border:0 !important;box-shadow:none !important;color:#2563eb !important;font-weight:750 !important;padding:0 !important;min-height:0 !important;height:auto !important;justify-content:flex-start !important;text-align:left !important}
        [class*="st-key-cv_candidate_open_"] button p,[class*="st-key-cv_candidate_open_"] button span{color:#2563eb !important}
        [class*="st-key-cv_candidate_hit_"]:hover [class*="st-key-cv_candidate_open_"] button{text-decoration:underline;text-underline-offset:3px}
        [class*="st-key-cv_candidate_open_"] button::before{content:"";position:absolute;inset:0;z-index:2;cursor:pointer}
        .cv-candidate-detail{margin:4px 0 12px;padding:14px 16px;border:1px solid #e6edf5;border-radius:14px;background:#fff}
        .cv-candidate-title,.cv-candidate-section{margin:12px 0 6px;font-size:16px;font-weight:750;color:#0f172a}
        .cv-candidate-compare{width:100%;border-collapse:collapse;margin:0 0 8px}
        .cv-candidate-compare th,.cv-candidate-compare td{text-align:left;vertical-align:top;padding:8px 10px;border-top:1px solid #e6edf5;font-size:13px}
        .cv-candidate-compare th{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:#64748b}
        .cv-candidate-compare small{display:block;color:#64748b;font-size:11px;margin-top:3px}
        .cv-finding{display:inline-flex;border-radius:999px;padding:2px 8px;font-size:12px;font-weight:750}
        .cv-finding.compatible{background:#dcfce7;color:#166534}
        .cv-finding.review{background:#fef3c7;color:#92400e}
        .cv-finding.conflict{background:#ffe4e6;color:#9f1239}
        .cv-finding.critical{background:#991b1b;color:#fff}
        .cv-finding.unknown{background:#f1f5f9;color:#475569}
        .cv-candidate-compare tr.cv-compat-critical-row td{background:#fff1f2!important;color:#9f1239;border-top-color:#fecdd3;font-weight:700}
        .cv-candidate-compare tr.cv-compat-critical-row small{color:#9f1239}
        .cv-compat-banner{margin:10px 0 14px;padding:12px 14px;border-radius:10px;font-size:13px;line-height:1.45}
        .cv-compat-banner strong{display:block;margin-bottom:5px;font-size:13px;letter-spacing:.015em}
        .cv-compat-banner ul{margin:4px 0 6px;padding-left:20px}
        .cv-compat-banner.critical{color:#7f1d1d;background:#fff1f2;border:2px solid #dc2626;box-shadow:0 0 0 2px rgba(220,38,38,.08)}
        .cv-compat-banner.critical li{color:#991b1b;font-weight:750}
        .cv-compat-banner.review{color:#854d0e;background:#fffbeb;border:1px solid #f59e0b}
        .cv-compat-pill{display:inline-flex;align-items:center;border-radius:999px;padding:3px 8px;font-size:10px;font-weight:850;letter-spacing:.02em}
        .cv-compat-pill.critical{color:#fff;background:#b91c1c}
        .cv-compat-pill.review{color:#854d0e;background:#fef3c7}
        .cv-compat-inline-critical{margin-top:4px;color:#991b1b;font-size:11px;font-weight:750;line-height:1.35}
        .cv-candidate-unverified{margin:0 0 10px;color:#92400e;background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:8px 10px;font-size:13px}
        .cv-candidate-verified{margin:0 0 10px;color:#1e3a8a;background:#eff6ff;border:1px solid #dbeafe;border-radius:10px;padding:8px 10px;font-size:13px}
        .cv-candidate-evidence{margin:0 0 10px;padding:8px 10px;border:1px solid #dbeafe;border-radius:9px;background:#eff6ff;color:#334155;font-size:12px;line-height:1.45}
        .cv-candidate-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 18px;margin:0}
        .cv-candidate-facts div{font-size:13px}
        .cv-candidate-facts span{display:block;color:#64748b;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase}
        .cv-candidate-links a{color:#2563eb}
        .cv-ap-banner{background:#eff6ff;border:1px solid #dbeafe;border-radius:16px;padding:18px 20px;margin-bottom:14px}
        .cv-ap-split{display:grid;grid-template-columns:1.4fr .8fr;gap:14px}
        .cv-ap-chart{background:#fff;border:1px solid #e6edf5;border-radius:16px;padding:14px 16px 8px;margin:0 0 14px}
        .cv-ap-chart h3{margin:0 0 8px;font-size:14px}
        .cv-ap-charts{display:grid;grid-template-columns:1.4fr .8fr;gap:14px;margin-bottom:14px}
        .cv-ed-card{display:flex;align-items:center;gap:14px;background:transparent;border:0;padding:16px 18px;min-height:0;height:100%;box-sizing:border-box}
        .cv-ed-card .cv-ap-ico{width:48px;height:48px;flex:0 0 48px;border-radius:50%}
        .cv-ed-card .cv-ap-ico svg{width:24px;height:24px}
        [class*="st-key-approved_decision_cardwrap_"]{position:relative;border:1px solid #e6edf5;border-radius:16px;background:#fff;padding:0;overflow:hidden;box-sizing:border-box;height:112px;min-height:112px}
        [class*="st-key-approved_decision_cardwrap_"]:has(.is-active),
        [class*="st-key-approved_decision_cardwrap_"]:has(button:focus-visible){border-color:#93c5fd;box-shadow:0 0 0 2px #bfdbfe}
        .cv-ed-card .cv-ed-copy{flex:1;min-width:0}
        .cv-ed-card .cv-ed-copy span{display:block;color:#64748b;font-size:14px;font-weight:650}
        .cv-ed-card .cv-ed-copy strong{display:flex;align-items:center;gap:8px;margin-top:4px;font-size:32px;letter-spacing:-.03em;color:#0f172a}
        .cv-ed-chevron{width:18px;height:18px;flex:0 0 18px;display:block}
        .cv-due-late{color:#be123c;font-weight:700}
        [class*="st-key-approved_decision_cardwrap_"] [data-testid="stHorizontalBlock"]{align-items:center}
        [class*="st-key-approved_decision_queue"]{border:1px solid #e6edf5;border-radius:16px;background:#fff;padding:10px 12px 6px;margin-top:8px}
        /* BOM list frame and title/toolbar actions share the same right edge. */
        .st-key-approved_bom_catalog_table{box-sizing:border-box!important;margin:14px 0 16px!important;padding:0!important;border:1px solid #cbd8e8!important;border-radius:16px!important;background:#fff!important;box-shadow:0 3px 12px rgba(15,23,42,.045)!important}
        .st-key-approved_bom_catalog_table>[data-testid="stVerticalBlock"]{gap:0!important}
        .st-key-approved_bom_catalog_table [data-testid="stElementContainer"]{margin:0!important;padding:0!important}
        .st-key-approved_bom_catalog_table .cv-ap-home-table-head{border-top:0!important;border-radius:15px 15px 0 0!important}
        .st-key-approved_bom_title [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"],
        .st-key-approved_bom_toolbar [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"]{align-items:flex-end!important}
        .st-key-approved_bom_title [data-testid="stColumn"]:last-child [data-testid="stElementContainer"],
        .st-key-approved_bom_toolbar [data-testid="stColumn"]:last-child [data-testid="stElementContainer"]{display:flex!important;justify-content:flex-end!important;width:100%!important}
        .st-key-approved_bom_title [data-testid="stColumn"]:last-child button{white-space:nowrap!important}
        .st-key-approved_bom_toolbar [data-testid="stColumn"]:last-child button{white-space:nowrap!important}
        .st-key-approved_bom_upload_panel{box-sizing:border-box!important;width:100%!important;max-width:none!important;margin:22px auto 0!important;padding:24px 36px 28px!important;border:1px solid #dce5f0!important;border-radius:18px!important;background:#fff!important;box-shadow:0 4px 18px rgba(15,23,42,.055)!important}
        .st-key-approved_bom_upload_panel>[data-testid="stVerticalBlock"]{gap:.85rem!important}
        .cv-bom-upload-heading{margin:0 0 1px!important;padding:0 0 15px!important;border-bottom:1px solid #e5ebf3!important}
        .cv-bom-upload-heading h2{margin:0 0 5px!important;color:#142239!important;font-size:23px!important;font-weight:750!important;letter-spacing:-.02em!important}
        .cv-bom-upload-heading p{margin:0!important;color:#64748b!important;font-size:14px!important;line-height:1.45!important}
        .st-key-approved_bom_upload_form{box-sizing:border-box!important;width:100%!important;padding:0!important;border:0!important;background:transparent!important}
        .st-key-approved_bom_upload_form>[data-testid="stVerticalBlock"]{gap:.82rem!important}
        .st-key-approved_bom_upload_form [data-testid="stWidgetLabel"] p{margin:0 0 6px!important;color:#34445d!important;font-size:13px!important;font-weight:700!important;line-height:1.3!important}
        .st-key-approved_bom_upload_form .st-key-approved_bom_project_name [data-testid="stWidgetLabel"] p:after{content:" (optional)";color:#8492a6;font-weight:500}
        .st-key-approved_bom_upload_form .st-key-approved_bom_name [data-testid="stWidgetLabel"] p:after{content:" *";color:#dc3545;font-weight:800}
        .st-key-approved_bom_upload_form [data-testid="stTextInput"] input{box-sizing:border-box!important;min-height:46px!important;border:1px solid #b8c7dc!important;border-radius:10px!important;background:#fbfdff!important;color:#172942!important;font-size:14px!important;box-shadow:none!important}
        .st-key-approved_bom_upload_form [data-testid="stTextInput"] input:focus{border-color:#2865ed!important;box-shadow:0 0 0 3px rgba(40,101,237,.12)!important}
        .st-key-approved_bom_upload_form [data-testid="stCaptionContainer"] p{margin:0!important;color:#718198!important;font-size:12px!important;line-height:1.45!important}
        .st-key-approved_bom_upload_form .st-key-bom_file_uploader [data-testid="stWidgetLabel"] p{margin:0 0 9px!important;color:#34445d!important;font-size:13px!important;font-weight:700!important}
        .st-key-approved_bom_upload_form .st-key-bom_file_uploader [data-testid="stFileUploader"]{box-sizing:border-box!important;margin:0!important;padding:0!important;border:0!important;border-radius:0!important;background:transparent!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploader"]{margin:0!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzone"]{box-sizing:border-box!important;display:flex!important;align-items:center!important;justify-content:center!important;min-height:108px!important;border:1.5px dashed #8aabf5!important;border-radius:12px!important;background:#f8fbff!important;padding:14px 22px!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzone"]>div{display:flex!important;flex-direction:row!important;align-items:center!important;justify-content:center!important;gap:18px!important;width:100%!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzoneInstructions"]{flex:0 1 auto!important;text-align:left!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzone"] svg{color:#2865ed!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzoneInstructions"]{color:#52647d!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzoneInstructions"] p{margin:0!important;color:#34445d!important;font-size:15px!important;font-weight:700!important;line-height:1.4!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzoneInstructions"] small{color:#718198!important;font-size:12px!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzone"] button{flex:0 0 auto!important;min-height:40px!important;height:40px!important;border:1px solid #c8d5e8!important;border-radius:9px!important;background:#fff!important;color:#225bd7!important;box-shadow:none!important;font-size:13px!important;font-weight:700!important}
        .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzone"] button:hover{border-color:#8eafff!important;background:#f5f8ff!important}
        .st-key-approved_bom_submit_row [data-testid="stHorizontalBlock"]{align-items:center!important;gap:16px!important}
        .st-key-approved_bom_submit_row [data-testid="stCaptionContainer"] p{color:#718198!important;font-size:12px!important}
        [class*="st-key-approved_bom_analyze"] button{width:auto!important;min-width:148px!important;max-width:100%!important;min-height:44px!important}
        [class*="st-key-approved_bom_analyze"] button:disabled{border:1px solid #d7dfeb!important;background:#e9eef6!important;color:#8996a8!important;box-shadow:none!important;opacity:1!important;cursor:not-allowed!important}
        [class*="st-key-approved_bom_analyze"] button:disabled *{color:#8996a8!important}
        [class*="st-key-approved_bom_analyze"] button:disabled:hover{transform:none!important;filter:none!important;box-shadow:none!important}
        /* Engineering decision cards and controls follow the approved light-tint dashboard style. */
        .st-key-approved_decision_cardwrap_open{background:#f2f7ff!important;border-color:#dbeafe!important}
        .st-key-approved_decision_cardwrap_overdue{background:#fff4f5!important;border-color:#ffe0e6!important}
        .st-key-approved_decision_cardwrap_resolved{background:#effaf3!important;border-color:#d8f3e2!important}
        .st-key-approved_decision_cardwrap_boms{background:#f2f7ff!important;border-color:#dbeafe!important}
        .st-key-approved_decision_toolbar [data-testid="stHorizontalBlock"]{align-items:center!important;gap:10px!important}
        .st-key-approved_decision_queue [data-testid="stTextInput"] input{box-sizing:border-box!important;height:42px!important;min-height:42px!important;border:1px solid #d8e1ed!important;border-radius:9px!important;background-color:#fff!important;padding-left:38px!important;color:#17253e!important;font-size:14px!important;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='18' height='18' viewBox='0 0 24 24' fill='none' stroke='%2364778b' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='11' cy='11' r='7'/%3E%3Cpath d='m20 20-4-4'/%3E%3C/svg%3E")!important;background-repeat:no-repeat!important;background-position:12px center!important;background-size:16px 16px!important}
        .st-key-approved_decision_queue [data-testid="stPopover"]>button{display:flex!important;align-items:center!important;justify-content:center!important;gap:8px!important;width:100%!important;min-width:0!important;height:42px!important;min-height:42px!important;padding:0 12px!important;border:1px solid #d8e1ed!important;border-radius:9px!important;background:#fff!important;color:#334155!important;box-shadow:none!important;font-size:13px!important;font-weight:650!important;white-space:nowrap!important}
        .st-key-approved_decision_queue [data-testid="stPopover"]>button:hover{border-color:#aebfd2!important;background:#f8fafc!important}
        .st-key-approved_decision_queue [data-testid="stPopover"]>button p{margin:0!important;color:#334155!important;font-size:13px!important;font-weight:650!important}
        .st-key-approved_decision_queue [data-testid="stPopover"]>button svg{width:16px!important;height:16px!important;color:#64748b!important}
        .st-key-approved_decision_table_head{margin:7px -12px 0!important;padding:0 12px!important;border-top:1px solid #e5ebf3!important;border-bottom:1px solid #e5ebf3!important;background:#f5f7fa!important}
        .st-key-approved_decision_table_head>[data-testid="stVerticalBlock"]{gap:0!important}
        .st-key-approved_decision_table_head [data-testid="stHorizontalBlock"]{align-items:center!important;min-height:46px!important}
        .cv-decision-table-heading{color:#64748b;font-size:11px;font-weight:750;line-height:1.25;letter-spacing:.055em;text-transform:uppercase;overflow-wrap:anywhere}
        [class*="st-key-approved_decision_row_"]{margin:0!important;padding:10px 0!important;border-bottom:1px solid #e8edf3!important}
        [class*="st-key-approved_decision_row_"] [data-testid="stHorizontalBlock"]{align-items:center!important}
        [class*="st-key-approved_decision_row_"] [data-testid="stVerticalBlock"]{gap:0!important}
        [class*="st-key-approved_bom_toolbar"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap;align-items:flex-end}
        @media(max-width:1100px){
          [class*="st-key-approved_bom_toolbar"] [data-testid="stHorizontalBlock"]{flex-wrap:wrap}
          [class*="st-key-approved_bom_toolbar"] [data-testid="stColumn"]{flex:1 1 180px !important;width:auto !important;min-width:160px}
          .st-key-approved_decision_cards>[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important;gap:12px!important}
          .st-key-approved_decision_cards>[data-testid="stHorizontalBlock"]>[data-testid="column"]{flex:1 1 calc(50% - 12px)!important;width:auto!important;min-width:245px!important}
          .st-key-approved_decision_toolbar [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}
          .st-key-approved_decision_toolbar [data-testid="stColumn"]:first-child{flex:1 1 100%!important;width:100%!important}
          .st-key-approved_decision_toolbar [data-testid="stColumn"]:not(:first-child){flex:1 1 155px!important;width:auto!important;min-width:140px!important}
          .st-key-approved_bom_upload_panel{padding:22px 24px 28px!important}
        }
        @media(max-width:620px){
          .st-key-approved_bom_upload_panel{padding:18px 16px 22px!important}
          .st-key-approved_bom_upload_fields [data-testid="stHorizontalBlock"],
          .st-key-approved_bom_submit_row [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important;gap:10px!important}
          .st-key-approved_bom_upload_fields [data-testid="column"]{flex:1 1 100%!important;width:100%!important}
          .st-key-approved_bom_submit_row [data-testid="column"]{flex:1 1 100%!important;width:100%!important}
          .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzone"]{min-height:96px!important;padding:12px 10px!important}
          .st-key-approved_bom_upload_form [data-testid="stFileUploaderDropzone"]>div{gap:10px!important}
          .st-key-approved_decision_cards>[data-testid="stHorizontalBlock"]>[data-testid="column"]{flex:1 1 100%!important;min-width:0!important}
          .st-key-approved_bom_title [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important;gap:10px!important}
          .st-key-approved_bom_title [data-testid="stColumn"]:first-child{flex:1 1 100%!important;width:100%!important}
          .st-key-approved_bom_title [data-testid="stColumn"]:last-child{flex:1 1 auto!important;width:auto!important}
          .st-key-approved_bom_upload_panel{padding:18px 16px 14px!important}
        }
        @media(max-width:900px){.cv-ap-kpis,.cv-ap-cards,.cv-ap-split{display:block}}
        @media(max-width:900px){.cv-ap-review-grid{grid-template-columns:1fr}.cv-ap-flow{gap:8px;padding:12px}.cv-ap-flow-line{min-width:8px}}
        @media(max-width:620px){.cv-ap-flow{flex-wrap:wrap}.cv-ap-flow-status{margin-left:0}.cv-ap-waiting-intro{align-items:flex-start}.cv-ap-document-state,.cv-ap-evidence-head{align-items:flex-start;flex-direction:column}.cv-ap-evidence-head p{text-align:left}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def end_approved_page() -> None:
    """Stop the script so the previous workspace renderer does not run."""
    from src.authenticated_runtime import (
        reveal_authenticated_page_body,
        stop_authenticated_page,
    )

    route = str(st.session_state.get("cadivor_route") or st.session_state.get("app_mode") or "")
    reveal_authenticated_page_body(route)
    stop_authenticated_page()


def legacy_tools_open(page: str) -> bool:
    return st.session_state.get("cadivor_show_legacy_tools") == page


def _open_legacy(page: str) -> None:
    st.session_state["cadivor_show_legacy_tools"] = page


def render_legacy_back(page: str) -> None:
    if st.button("Back to approved view", key=f"approved_back_{page}"):
        st.session_state.pop("cadivor_show_legacy_tools", None)
        st.rerun()


def _health_pill(score: int) -> str:
    if score >= 80:
        kind = "low"
    elif score >= 70:
        kind = "medium"
    else:
        kind = "high"
    return f'<span class="cv-pill {kind}"><span class="cv-pill-dot" aria-hidden="true"></span>{score}/100</span>'


def _rows_with_project_edits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edits = st.session_state.get("cadivor_saved_project_titles") or {}
    if not isinstance(edits, dict) or not edits:
        return rows
    merged = []
    for row in rows:
        title = edits.get(str(row.get("id") or ""))
        merged.append({**row, "project_name": title} if title else row)
    return merged


def _update_home_saved_analysis_cache(
    analysis_id: str,
    user_id: str,
    *,
    stored_title: str | None = None,
    filename: str | None = None,
    deleted: bool = False,
) -> None:
    """Keep Home's last-known rows in sync with a saved BOM edit."""
    from src.pages.home_workspace import SAVED_ANALYSES_CACHE_KEY

    cache = st.session_state.get(SAVED_ANALYSES_CACHE_KEY)
    if not isinstance(cache, dict) or str(cache.get("user_id") or "") != str(user_id or ""):
        return
    analysis_key = str(analysis_id or "")
    updated_rows = []
    for row in list(cache.get("rows") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "") != analysis_key:
            updated_rows.append(row)
            continue
        if deleted:
            continue
        updated = dict(row)
        if stored_title is not None:
            updated["project_name"] = stored_title
        if filename is not None:
            updated["filename"] = filename
        updated_rows.append(updated)
    st.session_state[SAVED_ANALYSES_CACHE_KEY] = {**cache, "rows": updated_rows}


def _persist_project_title(
    analysis_id: str,
    user_id: str,
    stored_title: str,
    *,
    filename: str | None = None,
) -> None:
    """Persist the project/BOM label and, when supplied, its displayed source filename."""
    from src.authenticated_runtime import supabase

    updates = {"project_name": stored_title}
    if filename is not None and str(filename).strip():
        updates["filename"] = str(filename).strip()
    response = (
        supabase.table("analyses")
        .update(updates)
        .eq("id", analysis_id)
        .eq("user_id", user_id)
        .select("id")
        .execute()
    )
    if not getattr(response, "data", None):
        raise RuntimeError("The saved BOM could not be found for this user.")
    supabase.table("analysis_parts").update({"project_name": stored_title}).eq(
        "analysis_id", analysis_id
    ).eq("user_id", user_id).execute()

def _render_project_editor(row: dict[str, Any], scope: str, rows: list[dict[str, Any]], user_id: str) -> None:
    analysis_id = str(row.get("id") or "")
    current, _bom = split_project_and_bom(row)
    choices = project_choices(rows)
    if current and current not in choices:
        choices = [current, *[name for name in choices if name != current]]
    options = [*choices, NEW_PROJECT_CHOICE]
    selected = st.selectbox(
        "Project",
        options,
        index=options.index(current) if current in options else 0,
        key=f"{scope}_project_choice_{analysis_id}",
    )
    typed = ""
    if selected == NEW_PROJECT_CHOICE:
        typed = st.text_input(
            "New project name",
            key=f"{scope}_project_typed_{analysis_id}",
            placeholder="Project name",
        )
    save_col, cancel_col = st.columns([1, 1])
    with save_col:
        if st.button("Save project", key=f"{scope}_project_save_{analysis_id}", type="primary"):
            project = resolve_project_choice(selected, typed, blank_uses_general=not current)
            if not project:
                st.caption("Enter a project name to save this assignment.")
            else:
                updated = assign_project(row, project)
                if user_id and analysis_id:
                    _persist_project_title(analysis_id, user_id, updated["project_name"])
                titles = dict(st.session_state.get("cadivor_saved_project_titles") or {})
                titles[analysis_id] = updated["project_name"]
                st.session_state["cadivor_saved_project_titles"] = titles
                _update_home_saved_analysis_cache(
                    analysis_id,
                    user_id,
                    stored_title=updated["project_name"],
                )
                st.session_state.pop("approved_project_editor", None)
                st.rerun()
    with cancel_col:
        if st.button("Cancel", key=f"{scope}_project_cancel_{analysis_id}"):
            st.session_state.pop("approved_project_editor", None)
            st.rerun()


def _render_project_cell(
    column,
    row: dict[str, Any],
    scope: str,
    rows: list[dict[str, Any]],
    user_id: str,
) -> None:
    """Render project text without placing row actions inside the Project column."""
    project, _bom = split_project_and_bom(row)
    with column:
        st.markdown(
            f"<span class='cv-ap-home-project'>{_esc(project or '—')}</span>",
            unsafe_allow_html=True,
        )


def _queue_saved_bom_action(analysis_id: str, action: str) -> None:
    """Open a specific saved BOM in the manager, editor, or delete confirmation."""
    target = str(analysis_id or "").strip()
    if not target or action not in {"edit", "delete"}:
        return
    st.session_state.pop(SAVED_BOM_EDIT_STATE, None)
    st.session_state.pop(SAVED_BOM_DELETE_STATE, None)
    if action == "edit":
        revision = int(st.session_state.get(SAVED_BOM_EDIT_REVISION_STATE) or 0) + 1
        st.session_state[SAVED_BOM_EDIT_REVISION_STATE] = revision
        st.session_state[SAVED_BOM_EDIT_STATE] = target
    else:
        st.session_state[SAVED_BOM_DELETE_STATE] = target
    navigate_to(
        "BOM Settings",
        saved_bom_id=target,
        saved_bom_action=action,
        arm_opening=False,
    )


def _render_saved_bom_actions(column, analysis_id: str, *, scope: str, row_key: str) -> None:
    target = str(analysis_id or "").strip()
    if not target:
        return
    with column:
        with st.container(key=f"approved_{scope}_menu_{row_key}"):
            with st.popover("⋯", help="Open, view the detailed risk report, edit, or delete this BOM."):
                if st.button(
                    "Open",
                    key=f"approved_{scope}_action_open_{row_key}",
                    use_container_width=True,
                ):
                    navigate_to(
                        "BOM Settings",
                        saved_bom_id=target,
                        saved_bom_action="open",
                        arm_opening=False,
                    )
                if st.button(
                    "Engineering Intelligence",
                    key=f"approved_{scope}_action_bom_risk_{row_key}",
                    use_container_width=True,
                ):
                    st.session_state["cadivor_show_detailed_risk"] = False
                    st.session_state["cadivor_ei_report_tab"] = "BOM Risk"
                    st.session_state["cadivor_active_analysis_id"] = target
                    st.session_state["analysis_id"] = target
                    st.session_state["cadivor_pending_analysis_section"] = "Engineering Intelligence"
                    st.session_state["cadivor_pending_analysis_section_id"] = target
                    navigate_to(
                        "Analysis Details",
                        analysis_id=target,
                        analysis_tab="Engineering Intelligence",
                        arm_opening=False,
                    )
                if st.button(
                    "Detailed Risk Report",
                    key=f"approved_{scope}_action_risk_report_{row_key}",
                    use_container_width=True,
                ):
                    st.session_state["cadivor_show_detailed_risk"] = True
                    st.session_state["cadivor_active_analysis_id"] = target
                    st.session_state["analysis_id"] = target
                    st.session_state[f"cadivor_detailed_risk_mpn_{target}"] = ""
                    st.session_state["cadivor_pending_analysis_section"] = "Engineering Intelligence"
                    st.session_state["cadivor_pending_analysis_section_id"] = target
                    navigate_to(
                        "Analysis Details",
                        analysis_id=target,
                        analysis_tab="Engineering Intelligence",
                        arm_opening=False,
                    )
                if st.button(
                    "Edit project and file name",
                    key=f"approved_{scope}_action_edit_{row_key}",
                    use_container_width=True,
                ):
                    _queue_saved_bom_action(target, "edit")
                if st.button(
                    "Delete",
                    key=f"approved_{scope}_action_delete_{row_key}",
                    use_container_width=True,
                ):
                    _queue_saved_bom_action(target, "delete")


def _delete_saved_bom(analysis_id: str, user_id: str) -> None:
    """Delete one user-owned analysis and its associated saved records."""
    from src.authenticated_runtime import supabase

    supabase.table("analysis_parts").delete().eq("analysis_id", analysis_id).eq(
        "user_id", user_id
    ).execute()
    try:
        supabase.table("part_monitor_history").delete().eq(
            "analysis_id", analysis_id
        ).execute()
    except Exception:
        pass
    supabase.table("analyses").delete().eq("id", analysis_id).eq(
        "user_id", user_id
    ).execute()


def _render_saved_bom_edit_page(row: dict[str, Any], user_id: str) -> None:
    analysis_id = str(row.get("id") or "").strip()
    project, bom_name = split_project_and_bom(row)
    source_filename = str(_first(row, "filename", "source_filename", fallback="") or "").strip()
    if source_filename in {"—", "-"}:
        source_filename = ""
    nonce = int(st.session_state.get(SAVED_BOM_EDIT_REVISION_STATE) or 0)
    with st.container(key="approved_saved_bom_settings_page"):
        st.markdown(
            """
            <div class="cv-ap">
              <p class="cv-ap-kicker">BOM SETTINGS</p>
              <h1>Edit saved BOM</h1>
              <p class="cv-ap-sub">Update the project, BOM name, or uploaded file name for this saved analysis.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.container(key="approved_saved_bom_edit_screen"):
            with st.form(key=f"approved_saved_bom_edit_form_{analysis_id}_{nonce}"):
                project_value = st.text_input(
                    "Project name",
                    value=project or "General",
                    key=f"approved_saved_bom_project_{analysis_id}_{nonce}",
                )
                bom_value = st.text_input(
                    "BOM name",
                    value=bom_name,
                    key=f"approved_saved_bom_name_{analysis_id}_{nonce}",
                )
                filename_value = st.text_input(
                    "Uploaded file name",
                    value=source_filename,
                    key=f"approved_saved_bom_filename_{analysis_id}_{nonce}",
                    help="This changes the file name shown in Cadivor. It does not replace the uploaded file contents.",
                )
                st.caption("Changing these labels does not rerun the analysis or replace its uploaded contents.")
                save_col, cancel_col = st.columns([1, 1])
                with save_col:
                    save = st.form_submit_button(
                        "Save changes",
                        type="primary",
                        use_container_width=True,
                    )
                with cancel_col:
                    cancel = st.form_submit_button(
                        "Cancel",
                        use_container_width=True,
                    )
            if cancel:
                st.session_state.pop(SAVED_BOM_EDIT_STATE, None)
                navigate_to("BOM Analyzer", show_saved_analyses="1", arm_opening=False)
            if save:
                clean_bom_name = str(bom_value or "").strip()
                clean_filename = str(filename_value or "").strip()
                if not clean_bom_name:
                    st.error("Enter a BOM name before saving.")
                else:
                    stored_title = analysis_title_for_upload(project_value, clean_bom_name)
                    try:
                        _persist_project_title(
                            analysis_id,
                            user_id,
                            stored_title,
                            filename=clean_filename or None,
                        )
                    except Exception:
                        st.error("Cadivor couldn't save these changes. Please try again.")
                    else:
                        titles = dict(st.session_state.get("cadivor_saved_project_titles") or {})
                        titles[analysis_id] = stored_title
                        st.session_state["cadivor_saved_project_titles"] = titles
                        _update_home_saved_analysis_cache(
                            analysis_id,
                            user_id,
                            stored_title=stored_title,
                            filename=clean_filename or None,
                        )
                        st.session_state.pop(SAVED_BOM_EDIT_STATE, None)
                        navigate_to("BOM Analyzer", show_saved_analyses="1", arm_opening=False)
            st.divider()
            if st.button(
                "Delete this BOM",
                key=f"approved_saved_bom_edit_delete_{analysis_id}",
                type="secondary",
            ):
                _queue_saved_bom_action(analysis_id, "delete")


def _render_saved_bom_open_page(
    row: dict[str, Any],
    components: list[dict[str, Any]] | None,
) -> None:
    """Edit the saved MPN/quantity rows and rerun the normal BOM analysis."""
    import pandas as pd

    analysis_id = str(row.get("id") or "").strip()
    project, bom_name = split_project_and_bom(row)
    source_filename = str(_first(row, "filename", "source_filename", fallback="") or "").strip()
    rows = []
    for part in components or []:
        mpn = str(_first(part, "mpn", "manufacturer_part_number", "part_number", fallback="") or "").strip()
        if not mpn:
            continue
        quantity = _first(part, "quantity", "qty", "Quantity", fallback=1)
        rows.append({"MPN": mpn, "Quantity": quantity})
    initial = pd.DataFrame(rows, columns=["MPN", "Quantity"])
    nonce = int(st.session_state.get(SAVED_BOM_EDIT_REVISION_STATE) or 0)
    with st.container(key="approved_saved_bom_original_editor"):
        st.markdown(
            """
            <div class="cv-ap">
              <p class="cv-ap-kicker">BOM EDITOR</p>
              <h1>Open original BOM</h1>
              <p class="cv-ap-sub">Update component numbers or quantities, then rerun the analysis.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        rerun_notice = st.session_state.pop("cadivor_bom_rerun_complete_notice", None)
        if (
            isinstance(rerun_notice, dict)
            and str(rerun_notice.get("analysis_id") or "").strip() == analysis_id
        ):
            st.success(
                "The updated analysis is saved. This editor now shows its revised BOM rows; "
                "select View BOM Risk whenever you want to review the results."
            )
        st.info(
            "Cadivor rebuilds these rows from the saved analyzed components. "
            "Rerunning creates a new saved analysis and keeps this report available."
        )
        if not rows:
            st.warning(
                "No saved component rows were found for this BOM. Add rows below or return to BOMs and upload the source file."
            )
        with st.form(key=f"approved_saved_bom_original_form_{analysis_id}_{nonce}"):
            project_value = st.text_input(
                "Project name",
                value=project or "General",
                key=f"approved_saved_bom_original_project_{analysis_id}_{nonce}",
            )
            bom_value = st.text_input(
                "BOM name",
                value=bom_name or source_filename or "Saved BOM",
                key=f"approved_saved_bom_original_name_{analysis_id}_{nonce}",
            )
            edited = st.data_editor(
                initial,
                key=f"approved_saved_bom_original_rows_{analysis_id}_{nonce}",
                num_rows="dynamic",
                hide_index=True,
                use_container_width=True,
                column_config={
                    "MPN": st.column_config.TextColumn("Manufacturer part number", required=True),
                    "Quantity": st.column_config.NumberColumn(
                        "Quantity", min_value=1, step=1, required=True,
                    ),
                },
            )
            rerun = st.form_submit_button(
                "Rerun analysis with updates",
                type="primary",
                use_container_width=True,
            )
        back_col, risk_col = st.columns(2)
        with back_col:
            if st.button("Back to BOMs", key=f"approved_saved_bom_original_back_{analysis_id}"):
                navigate_to("BOM Analyzer", show_saved_analyses="1", arm_opening=False)
        with risk_col:
            if st.button("View BOM Risk", key=f"approved_saved_bom_original_risk_{analysis_id}"):
                st.session_state["cadivor_show_detailed_risk"] = False
                st.session_state["cadivor_ei_report_tab"] = "BOM Risk"
                st.session_state["cadivor_active_analysis_id"] = analysis_id
                st.session_state["analysis_id"] = analysis_id
                navigate_to(
                    "Analysis Details",
                    analysis_id=analysis_id,
                    analysis_tab="Engineering Intelligence",
                    arm_opening=False,
                )
        if rerun:
            from src.saved_bom_editor import normalize_saved_bom_rows, saved_bom_csv_bytes

            normalized, validation_error = normalize_saved_bom_rows(
                edited.to_dict(orient="records")
            )
            if validation_error:
                st.error(validation_error)
            elif not str(bom_value or "").strip():
                st.error("Enter a BOM name before rerunning this analysis.")
            else:
                upload = io.BytesIO(saved_bom_csv_bytes(normalized))
                file_stem = source_filename.rsplit(".", 1)[0] if source_filename else str(bom_value).strip()
                upload.name = f"{file_stem}_updated.csv"
                upload.seek(0)
                st.session_state["cadivor_bom_analysis_ready"] = True
                st.session_state["cadivor_pending_upload"] = upload
                st.session_state["cadivor_pending_project"] = str(project_value or "").strip() or "General"
                st.session_state["cadivor_pending_bom_name"] = str(bom_value or "").strip()
                # Keep the rerun in the BOM workspace. The runtime consumes this
                # one-shot submission before drawing the new-upload form.
                st.session_state["cadivor_saved_bom_rerun_pending"] = True
                st.session_state["cadivor_bom_upload_open"] = False
                from src.ui.main_transition import arm_bom_analysis_transition

                arm_bom_analysis_transition(st.session_state, "rerun")
                navigate_to("BOM Analyzer", new_analysis="1", arm_opening=False)


def _render_saved_bom_delete_page(row: dict[str, Any], user_id: str) -> None:
    analysis_id = str(row.get("id") or "").strip()
    _project, bom_name = split_project_and_bom(row)
    display_name = bom_name or str(row.get("filename") or "Saved BOM")
    with st.container(key="approved_saved_bom_settings_page"):
        st.markdown(
            """
            <div class="cv-ap">
              <p class="cv-ap-kicker">BOM SETTINGS</p>
              <h1>Delete saved BOM</h1>
              <p class="cv-ap-sub">Confirm before removing this analysis.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.container(key="approved_saved_bom_delete_screen"):
            st.warning(
                f"Delete “{display_name}” and its saved component records? "
                "This action cannot be undone."
            )
            cancel_col, delete_col = st.columns([1, 1])
            with cancel_col:
                if st.button(
                    "Cancel",
                    key="approved_saved_bom_delete_cancel",
                    use_container_width=True,
                ):
                    st.session_state.pop(SAVED_BOM_DELETE_STATE, None)
                    navigate_to("BOM Analyzer", show_saved_analyses="1", arm_opening=False)
            with delete_col:
                if st.button(
                    "Delete permanently",
                    key="approved_saved_bom_delete_confirm",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        _delete_saved_bom(analysis_id, user_id)
                    except Exception:
                        st.error("Cadivor couldn't delete this BOM. Please try again.")
                    else:
                        titles = dict(st.session_state.get("cadivor_saved_project_titles") or {})
                        titles.pop(analysis_id, None)
                        st.session_state["cadivor_saved_project_titles"] = titles
                        _update_home_saved_analysis_cache(
                            analysis_id,
                            user_id,
                            deleted=True,
                        )
                        st.session_state.pop(SAVED_BOM_DELETE_STATE, None)
                        st.session_state.pop(SAVED_BOM_EDIT_STATE, None)
                        navigate_to("BOM Analyzer", show_saved_analyses="1", arm_opening=False)


def render_saved_bom_settings(
    records: list[dict[str, Any]] | None,
    user_id: str = "",
    components: list[dict[str, Any]] | None = None,
) -> None:
    """Render the standalone settings page for a selected saved BOM."""
    from src.ui.navigation import current_navigation_query_value

    begin_approved_page()
    rows = _rows_with_project_edits(_records(records))
    query_id = ""
    query_action = ""
    try:
        query_id = current_navigation_query_value(
            "saved_bom_id", "", route="BOM Settings"
        ).strip()
        query_action = current_navigation_query_value(
            "saved_bom_action", "", route="BOM Settings"
        ).strip().casefold()
    except Exception:
        pass
    edit_id = str(st.session_state.get(SAVED_BOM_EDIT_STATE) or query_id).strip()
    delete_id = str(st.session_state.get(SAVED_BOM_DELETE_STATE) or "").strip()
    open_id = query_id if query_action == "open" else ""
    if not delete_id and query_action == "delete":
        delete_id = query_id
    target_id = delete_id or open_id or edit_id
    target_row = next(
        (row for row in rows if str(row.get("id") or "").strip() == target_id),
        None,
    )
    if target_row is None:
        st.markdown(
            "<div class='cv-ap'><p class='cv-ap-kicker'>BOM SETTINGS</p>"
            "<h1>Saved BOM settings</h1><p class='cv-ap-sub'>Select a saved BOM from the BOMs page to edit its details.</p></div>",
            unsafe_allow_html=True,
        )
        if st.button("Return to BOMs", key="approved_saved_bom_settings_back"):
            st.session_state.pop(SAVED_BOM_EDIT_STATE, None)
            st.session_state.pop(SAVED_BOM_DELETE_STATE, None)
            navigate_to("BOM Analyzer", show_saved_analyses="1", arm_opening=False)
    elif delete_id:
        _render_saved_bom_delete_page(target_row, user_id)
    elif open_id:
        _render_saved_bom_open_page(target_row, components)
    else:
        _render_saved_bom_edit_page(target_row, user_id)
    end_approved_page()


def catalog_health_label(score: int, high_risk: int) -> str:
    if high_risk >= 20 or score < 55:
        return "At risk"
    if high_risk >= 5 or score < 80:
        return "Review"
    return "Healthy"


def _parse_timestamp(value: Any):
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "—"}:
        return None
    from datetime import date, datetime

    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(normalized[:10]), datetime.min.time())
        except ValueError:
            return None


def analyzed_label(value: Any) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        text = str(value or "").strip()
        if not text or text.lower() in {"nan", "none"}:
            return "Not recorded"
        return text[:10]
    label = parsed.strftime("%b %d, %Y").replace(" 0", " ")
    if parsed.hour or parsed.minute or parsed.second:
        clock = parsed.strftime("%I:%M %p").lstrip("0")
        label = f"{label}<br>{clock}"
    return label


def within_analyzed_range(value: Any, date_range: str, today) -> bool:
    if date_range == "All time":
        return True
    parsed = _parse_timestamp(value)
    if parsed is None:
        return False
    window = 30 if "30" in date_range else 90
    analyzed = parsed.date()
    return 0 <= (today - analyzed).days <= window


def catalog_project_options(rows: list[dict[str, Any]]) -> list[str]:
    names = []
    for row in rows:
        project, _bom = split_project_and_bom(row)
        if project and project not in names:
            names.append(project)
    return ["All projects", *sorted(names)]


def reset_catalog_filters(state: dict[str, Any]) -> None:
    """New widget keys restore Search, Project, Health, and Date range to their defaults."""
    state["approved_bom_filter_nonce"] = int(state.get("approved_bom_filter_nonce") or 0) + 1


def decision_status_label(row: dict[str, Any], today) -> str:
    status = str(_first(row, "status", "decision_status", fallback="Open") or "Open")
    folded = status.casefold()
    if any(token in folded for token in ("resolv", "closed", "accepted")):
        return "Resolved"
    if str(row.get("source") or "").casefold() == "monitoring":
        if folded not in {"new", "open", "overdue"}:
            # An engineering workflow can be progressing or a candidate can be
            # rejected while the underlying supply alert is still active.
            return "In review"
    if "review" in folded:
        return "In review"
    if "over" in folded:
        return "Overdue"
    due = _parse_timestamp(_first(row, "due_date", "due_at", fallback=None))
    if due is not None and due.date() < today and "resolv" not in folded:
        return "Overdue"
    return "Open"


def _decision_affected_bom_rows(rows: list[tuple[dict[str, Any], str]]) -> list[dict[str, Any]]:
    """Collapse component alerts into one actionable row per saved BOM."""
    grouped: dict[str, dict[str, Any]] = {}
    for row, status in rows:
        related_boms = row.get("related_boms") or []
        candidates: dict[str, dict[str, Any]] = {}
        for related in related_boms:
            if not isinstance(related, dict):
                continue
            analysis_id = str(related.get("id") or "").strip()
            if analysis_id:
                candidates[analysis_id] = dict(related)

        direct_id = str(
            _first(row, "analysis_id", "context_analysis_id", fallback="") or ""
        ).strip()
        if direct_id:
            candidate = candidates.setdefault(direct_id, {})
            candidate.setdefault("id", direct_id)
            for key, value in (
                ("project_name", _first(row, "project_name", "project", fallback="")),
                ("bom_name", _first(row, "bom_name", "bom", fallback="")),
                ("filename", _first(row, "filename", "source_filename", fallback="")),
            ):
                if value and not candidate.get(key):
                    candidate[key] = value

        for analysis_id, candidate in candidates.items():
            project = str(candidate.get("project_name") or candidate.get("project") or "").strip()
            bom_name = str(candidate.get("bom_name") or candidate.get("bom") or "").strip()
            name = str(candidate.get("name") or "").strip()
            if not name:
                if project and bom_name and not project.casefold().endswith(bom_name.casefold()):
                    name = f"{project} · {bom_name}"
                else:
                    name = bom_name or project or str(candidate.get("filename") or "Saved BOM")

            record = grouped.setdefault(
                analysis_id,
                {
                    "id": analysis_id,
                    "name": name,
                    "component_keys": set(),
                    "event_keys": set(),
                    "open_decisions": 0,
                },
            )
            if record["name"] == "Saved BOM" and name != "Saved BOM":
                record["name"] = name

            mpn = str(_first(row, "mpn", "part_number", "component", fallback="") or "").strip()
            part_id = str(_first(row, "part_id", "analysis_part_id", fallback="") or "").strip()
            if mpn or part_id:
                record["component_keys"].add((mpn or part_id).casefold())
            event_key = str(_first(row, "decision_id", "id", fallback="") or "").strip()
            if not event_key:
                event_values = [
                    str(_first(row, key, fallback="") or "").strip()
                    for key in ("mpn", "part_number", "alert_message", "title", "created_at")
                ]
                event_key = "|".join(value for value in event_values if value)
                if not event_key:
                    event_key = f"unidentified-event-{len(record['event_keys'])}"
            if event_key not in record["event_keys"]:
                record["event_keys"].add(event_key)
                if status != "Resolved":
                    record["open_decisions"] += 1

    result = []
    for record in grouped.values():
        result.append(
            {
                "id": record["id"],
                "name": record["name"],
                "affected_components": len(record["component_keys"]),
                "open_decisions": record["open_decisions"],
                "status": "Needs review" if record["open_decisions"] else "Resolved",
            }
        )
    return sorted(result, key=lambda item: (item["name"].casefold(), item["id"]))


def decision_queue_view(
    records: list[dict[str, Any]] | None,
    *,
    query: str = "",
    status_filter: str = "All statuses",
    sort_by: str = "Due date",
    scope: str = "",
    today=None,
) -> dict[str, Any]:
    """Counts use every loaded record. Search, status, and card scope filter the queue."""
    from datetime import date

    today = today or date.today()
    source = _records(records)
    prepared = []
    for row in source:
        status = decision_status_label(row, today)
        prepared.append((row, status))
    open_count = sum(1 for _row, status in prepared if status == "Open")
    overdue = sum(1 for _row, status in prepared if status == "Overdue")
    resolved_month = 0
    for row, status in prepared:
        if status != "Resolved":
            continue
        stamp = _parse_timestamp(
            _first(row, "resolved_at", "updated_at", "created_at", fallback=None)
        )
        if stamp is not None and stamp.year == today.year and stamp.month == today.month:
            resolved_month += 1
    affected_analysis_ids: set[str] = set()
    for row, _status in prepared:
        direct_id = str(
            _first(row, "analysis_id", "context_analysis_id", fallback="") or ""
        ).strip()
        if direct_id:
            affected_analysis_ids.add(direct_id)
        for related_bom in row.get("related_boms") or []:
            if isinstance(related_bom, dict):
                related_id = str(related_bom.get("id") or "").strip()
                if related_id:
                    affected_analysis_ids.add(related_id)
    affected = len(affected_analysis_ids)
    needle = query.strip().casefold()
    visible = []
    for row, status in prepared:
        if scope == "boms":
            direct_id = str(
                _first(row, "analysis_id", "context_analysis_id", fallback="") or ""
            ).strip()
            has_related = any(
                isinstance(bom, dict) and str(bom.get("id") or "").strip()
                for bom in (row.get("related_boms") or [])
            )
            if not direct_id and not has_related:
                continue
        if status_filter != "All statuses" and status_filter.casefold() != status.casefold():
            continue
        search_values = [
            str(_first(row, key, fallback="") or "")
            for key in (
                "mpn", "part_number", "title", "summary", "alert_message",
                "owner", "assigned_owner", "assignee", "resolution", "project_name",
                "bom_name", "filename",
            )
        ]
        search_values.extend(
            str(bom.get(key) or "")
            for bom in (row.get("related_boms") or [])
            if isinstance(bom, dict)
            for key in ("name", "project_name", "bom_name", "filename")
        )
        blob = " ".join(search_values).casefold()
        if needle and needle not in blob:
            continue
        visible.append((row, status))
    risk_rank = {"high": 0, "medium": 1, "low": 2}

    def _risk_key(item):
        level = str(_first(item[0], "risk_level", "severity", fallback="")).casefold()
        for name, rank in risk_rank.items():
            if name in level:
                return rank
        return 3

    if sort_by == "Component":
        visible.sort(key=lambda item: str(_first(item[0], "mpn", "part_number", fallback="")).casefold())
    elif sort_by == "Risk level":
        visible.sort(key=_risk_key)
    else:
        visible.sort(key=lambda item: str(_first(item[0], "due_date", "created_at", fallback="") or "9999"))
    return {
        "open": open_count,
        "overdue": overdue,
        "resolved_month": resolved_month,
        "affected": affected,
        "rows": visible,
        "boms": _decision_affected_bom_rows(visible) if scope == "boms" else [],
    }


def decision_action_label(row: dict[str, Any], status: str) -> str:
    recorded = _first(row, "decision", "resolution", "decision_text", fallback=None)
    if status in {"In review", "Resolved"} or recorded:
        return "Review"
    return "Record decision"


def _render_decision_affected_boms(rows: list[dict[str, Any]]) -> None:
    """Show BOM-level impact when the affected-BOM KPI is selected."""
    st.markdown(
        f"<h2 class='cv-decision-bom-title'>Affected saved BOMs ({len(rows)})</h2>"
        "<p class='cv-decision-bom-subtitle'>Each saved BOM appears once, with its affected components and open decisions.</p>",
        unsafe_allow_html=True,
    )
    widths = [2.2, 0.9, 0.9, 1.0, 0.8]
    with st.container(key="approved_decision_bom_table"):
        with st.container(key="approved_decision_bom_table_head"):
            header = st.columns(widths, vertical_alignment="center")
            for column, label in zip(
                header,
                ("Saved BOM", "Affected components", "Open decisions", "Status", "Action"),
            ):
                column.markdown(
                    f"<div class='cv-decision-table-heading' role='columnheader'>{_esc(label)}</div>",
                    unsafe_allow_html=True,
                )
        if not rows:
            st.caption("No saved BOMs match the current search and status filters.")
            return
        for index, row in enumerate(rows):
            with st.container(key=f"approved_decision_bom_row_{index}"):
                cells = st.columns(widths, vertical_alignment="center")
                cells[0].markdown(
                    f"<div class='cv-decision-bom-name'>{_esc(row.get('name') or 'Saved BOM')}</div>",
                    unsafe_allow_html=True,
                )
                affected_components = int(row.get("affected_components") or 0)
                open_decisions = int(row.get("open_decisions") or 0)
                cells[1].markdown(
                    f"{affected_components} component{'s' if affected_components != 1 else ''}"
                )
                cells[2].markdown(
                    f"{open_decisions} open" if open_decisions else "None"
                )
                status_kind = "open" if open_decisions else "low"
                cells[3].markdown(
                    f"<span class='cv-pill {status_kind}'>{_esc(row.get('status') or 'Resolved')}</span>",
                    unsafe_allow_html=True,
                )
                with cells[4]:
                    analysis_id = str(row.get("id") or "").strip()
                    if st.button(
                        "Open BOM",
                        key=f"approved_decision_bom_open_{index}",
                        use_container_width=True,
                        disabled=not analysis_id,
                    ):
                        navigate_to(
                            "BOM Settings",
                            saved_bom_id=analysis_id,
                            saved_bom_action="open",
                            arm_opening=False,
                        )


def _records(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [row for row in rows or [] if isinstance(row, dict)]


def live_bar_chart(title: str, points: list[tuple[str, float]], color: str = "#2563eb") -> str:
    """Bar chart of live numeric records. Empty input renders nothing."""
    clean = [(str(label), float(value)) for label, value in points if label]
    if not clean:
        return ""
    peak = max(value for _, value in clean) or 1.0
    width = 560
    slot = width / len(clean[:8])
    marks = []
    for index, (label, value) in enumerate(clean[:8]):
        height = 112 * (value / peak)
        x = 12 + index * slot
        bar = max(10.0, slot - 22)
        marks.append(
            f'<rect x="{x:.1f}" y="{132 - height:.1f}" width="{bar:.1f}" height="{max(height, 2):.1f}" rx="5" fill="{color}"/>'
            f'<text x="{x:.1f}" y="154" font-size="11" fill="#64748b">{html.escape(label[:12])}</text>'
        )
    return (
        f'<article class="cv-ap-chart"><h3>{html.escape(title)}</h3>'
        f'<svg viewBox="0 0 {width} 168" width="100%" height="168" role="img" aria-label="{html.escape(title)}">'
        f'{"".join(marks)}</svg></article>'
    )


def series_chart(title: str, series: list[tuple[str, str, list[tuple[str, float]]]]) -> str:
    """Line chart. Each series is (name, color, points). Missing points stay off the line."""
    prepared = []
    for name, color, points in series:
        clean = [(str(label), float(value)) for label, value in points if label]
        if clean:
            prepared.append((name, color, clean))
    if not prepared:
        return (
            f'<article class="cv-ap-chart"><h3>{html.escape(title)}</h3>'
            '<p class="cv-ap-meta">No supply or demand values are recorded for this scenario.</p></article>'
        )
    labels = [label for label, _value in prepared[0][2]]
    peak = max(value for _name, _color, points in prepared for _label, value in points) or 1.0
    width = 640
    slot = width / max(len(labels), 1)

    def _point(index: int, value: float) -> str:
        x = 28 + index * slot
        y = 128 - (108 * (value / peak))
        return f"{x:.1f},{y:.1f}"

    lines = []
    legend = []
    for name, color, points in prepared:
        coords = " ".join(_point(index, value) for index, (_label, value) in enumerate(points))
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{coords}"/>')
        legend.append(f'<span style="color:{color}">{html.escape(name)}</span>')
    axis = "".join(
        f'<text x="{28 + index * slot:.1f}" y="150" font-size="11" fill="#64748b">{html.escape(label[:10])}</text>'
        for index, label in enumerate(labels[:8])
    )
    return (
        f'<article class="cv-ap-chart"><h3>{html.escape(title)}</h3>'
        f'<svg viewBox="0 0 {width} 168" width="100%" height="168" role="img" aria-label="{html.escape(title)}">'
        f'{"".join(lines)}{axis}</svg><p class="cv-ap-meta">{" · ".join(legend)}</p></article>'
    )


def sparkline(values: list[float], color: str = "#2563eb") -> str:
    """Small trend line from recorded values. A single value draws one point, not a made-up history."""
    if not values:
        return '<svg class="cv-ap-spark" viewBox="0 0 88 28" width="88" height="28" aria-hidden="true"></svg>'
    peak = max(values) or 1.0
    slot = 80 / max(len(values) - 1, 1)
    coords = []
    for index, value in enumerate(values[:12]):
        x = 4 + index * slot
        y = 24 - (18 * (value / peak))
        coords.append(f"{x:.1f},{y:.1f}")
    marks = f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(coords)}"/>'
    if len(coords) == 1:
        marks += f'<circle cx="{coords[0].split(",")[0]}" cy="{coords[0].split(",")[1]}" r="2.5" fill="{color}"/>'
    return f'<svg class="cv-ap-spark" viewBox="0 0 88 28" width="88" height="28" aria-hidden="true">{marks}</svg>'


def risk_mix_chart(parts: list[dict[str, Any]] | None) -> str:
    counts = {"High": 0, "Medium": 0, "Low": 0}
    for part in _records(parts):
        level = str(_first(part, "risk_level", "severity", fallback="")).casefold()
        if "high" in level:
            counts["High"] += 1
        elif "med" in level:
            counts["Medium"] += 1
        elif "low" in level:
            counts["Low"] += 1
    total = sum(counts.values())
    if not total:
        return ""
    colors = {"High": "#e11d48", "Medium": "#d97706", "Low": "#16a34a"}
    start = 0.0
    slices = []
    for label, count in counts.items():
        if not count:
            continue
        end = start + (count / total) * 100
        slices.append(
            f'<circle cx="70" cy="70" r="42" fill="none" stroke="{colors[label]}" stroke-width="18" '
            f'pathLength="100" stroke-dasharray="{count / total * 100:.2f} {100 - count / total * 100:.2f}" '
            f'stroke-dashoffset="{-start:.2f}"/>'
        )
        start = end
    legend = "".join(
        f'<div><span class="cv-pill {"high" if label=="High" else "medium" if label=="Medium" else "low"}">{label}</span> {count}</div>'
        for label, count in counts.items()
        if count
    )
    return (
        '<article class="cv-ap-chart"><h3>Risk distribution</h3>'
        f'<svg viewBox="0 0 140 140" width="140" height="140" role="img" aria-label="Risk distribution">{"".join(slices)}</svg>'
        f'<div class="cv-ap-meta">{legend}</div></article>'
    )


def render_home(
    *,
    name: str,
    analyses: list[dict[str, Any]] | None,
    plan_notice: str = "",
    pause_new_analyses: bool = False,
    user_id: str = "",
    saved_boms_stale: bool = False,
) -> None:
    begin_approved_page()
    from src.pages.home_workspace import remember_saved_analyses_for_session

    remember_saved_analyses_for_session(
        st.session_state,
        user_id=user_id,
        rows=analyses,
    )
    rows = _rows_with_project_edits(_records(analyses))
    high = sum(_num(_first(row, "high_risk_count")) for row in rows)
    review = sum(1 for row in rows if _num(_first(row, "high_risk_count")) or _num(_first(row, "health_score"), 100) < 80)
    health_values = [_num(_first(row, "health_score")) for row in rows]
    average = round(sum(health_values) / len(health_values)) if health_values else 0
    greeting = name or "there"
    notice = f"<p class='cv-ap-sub'>{_esc(plan_notice)}</p>" if plan_notice else ""
    with st.container(key="approved_home_page"):
        if saved_boms_stale:
            st.info("Showing the saved BOM list from this session. Cadivor couldn’t refresh it just now.")
            if st.button("Retry saved BOMs", key="home_retry_saved_boms"):
                st.rerun()
        with st.container(key="approved_home_header"):
            title_col, action_col = st.columns([3.1, 1], vertical_alignment="top")
            with title_col:
                st.markdown(
                    f"""
                    <div class="cv-ap">
                      <p class="cv-ap-kicker">HOME</p>
                      <h1>Good afternoon, {_esc(greeting)}</h1>
                      <p class="cv-ap-sub">Here's what's happening with your BOMs today.</p>
                      {notice}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with action_col:
                if pause_new_analyses:
                    if st.button("Open reports", key="approved_home_open_reports", type="primary"):
                        navigate_to("Reports")
                elif st.button(
                    "+ New BOM analysis",
                    key="approved_home_new_bom",
                    type="primary",
                    width="stretch",
                ):
                    prepare_new_approved_bom_analysis(st.session_state)
                    navigate_to("BOM Analyzer", new_analysis="1")

        saved_delta = _home_weekly_delta(rows, "saved_boms")
        review_delta = _home_weekly_delta(rows, "needs_review")
        risk_delta = _home_weekly_delta(rows, "high_risk_parts")
        health_delta = _home_weekly_delta(rows, "average_health")
        st.markdown(
            f"""
            <section class="cv-ap cv-ap-kpis cv-ap-home-kpis">
              <article class="cv-ap-kpi cv-ap-home-kpi">
                <span class="cv-ap-ico cv-ap-home-icon">{ICO_DOC}</span>
                <div class="cv-ap-home-kpi-copy"><span class="cv-ap-home-kpi-label">Saved BOMs</span><strong>{len(rows)}</strong>{saved_delta}</div>
              </article>
              <article class="cv-ap-kpi cv-ap-home-kpi">
                <span class="cv-ap-ico cv-ap-home-icon warn">{ICO_WARN}</span>
                <div class="cv-ap-home-kpi-copy"><span class="cv-ap-home-kpi-label">BOMs needing review</span><strong>{review}</strong>{review_delta}</div>
              </article>
              <article class="cv-ap-kpi cv-ap-home-kpi">
                <span class="cv-ap-ico cv-ap-home-icon risk">{ICO_RISK}</span>
                <div class="cv-ap-home-kpi-copy"><span class="cv-ap-home-kpi-label">High-risk parts</span><strong>{high}</strong>{risk_delta}</div>
              </article>
              <article class="cv-ap-kpi cv-ap-home-kpi">
                <span class="cv-ap-ico cv-ap-home-icon ok">{ICO_HEALTH}</span>
                <div class="cv-ap-home-kpi-copy"><span class="cv-ap-home-kpi-label">Average health</span><strong>{average}/100</strong>{health_delta}</div>
              </article>
            </section>
            """,
            unsafe_allow_html=True,
        )

        home_widths = [2.25, 1.35, 0.76, 0.84, 1.0, 1.18, 0.68]
        with st.container(key="approved_home_recent_card"):
            with st.container(key="approved_home_recent_heading"):
                heading_col, view_all_col = st.columns([10, 1], vertical_alignment="center")
                with heading_col:
                    st.markdown(
                        "<div class='cv-ap-home-recent-heading'><h2>Recent BOMs</h2>"
                        "<p>Your latest analyses and their current status.</p></div>",
                        unsafe_allow_html=True,
                    )
                with view_all_col:
                    with st.container(key="approved_home_view_all_wrap"):
                        if st.button(
                            ":blue[View all]",
                            key="approved_home_view_all",
                            type="secondary",
                            width="stretch",
                        ):
                            navigate_to("BOM Analyzer", show_saved_analyses="1", arm_opening=False)
            header_labels = ("Name", "Project", "Part count", "Health", "High-risk parts", "Last analyzed", "Actions")
            header_cells = "".join(
                f"<span role='columnheader'>{_esc(label)}</span>"
                for label in header_labels
            )
            st.markdown(
                f"<div class='cv-ap-home-table-head' role='row'>{header_cells}</div>",
                unsafe_allow_html=True,
            )
            if not rows:
                st.markdown(
                    "<div class='cv-ap-home-empty'>No saved BOMs yet. Start a new BOM analysis to fill this workspace.</div>",
                    unsafe_allow_html=True,
                )
            for index, row in enumerate(rows[:3]):
                project, bom_name = split_project_and_bom(row)
                source_filename = str(_first(row, "filename", "source_filename", fallback="") or "").strip()
                parts = _num(_first(row, "total_parts"))
                score = _num(_first(row, "health_score"))
                risk = _num(_first(row, "high_risk_count"))
                risk_html = (
                    f"<span class='cv-home-risk-count high'>{risk}</span>"
                    if risk
                    else "<span class='cv-home-risk-count clear'>0</span>"
                )
                updated = analyzed_label(_first(row, "created_at", "updated_at", fallback=""))
                analysis_id = str(row.get("id") or "")
                display_bom_name = bom_name or source_filename or "Saved BOM"
                if not bom_name and display_bom_name.casefold().endswith(".csv"):
                    display_bom_name = display_bom_name[:-4]
                row_key = "approved_home_row_last" if index == min(len(rows), 3) - 1 else f"approved_home_row_{index}"
                with st.container(key=row_key):
                    cells = st.columns(home_widths, vertical_alignment="center")
                    cells[0].markdown(
                        f"<div class='cv-ap-home-bom'><span class='cv-ap-home-row-icon'>{lucide('file-text', 24)}</span>"
                        f"<span class='cv-ap-home-bom-copy'><strong class='cv-ap-name'>{_esc(display_bom_name)}</strong></span></div>",
                        unsafe_allow_html=True,
                    )
                    _render_project_cell(cells[1], row, "home", rows, user_id)
                    cells[2].markdown(
                        f"<div class='cv-ap-home-cell-center'>{parts}</div>", unsafe_allow_html=True
                    )
                    cells[3].markdown(
                        f"<div class='cv-ap-home-cell-center'>{_health_pill(score)}</div>",
                        unsafe_allow_html=True,
                    )
                    cells[4].markdown(
                        f"<div class='cv-ap-home-cell-center'>{risk_html}</div>",
                        unsafe_allow_html=True,
                    )
                    cells[5].markdown(
                        f"<div class='cv-ap-home-cell-center'>{updated}</div>",
                        unsafe_allow_html=True,
                    )
                    _render_saved_bom_actions(cells[6], analysis_id, scope="home", row_key=str(index))
        if plan_notice and st.button("Compare plans", key="approved_home_compare_plans"):
            navigate_to("Pricing")
    end_approved_page()


def _render_approved_bom_upload_name_fields() -> None:
    """Keep text entry reruns inside a small fragment, away from page chrome."""
    with st.container(key="approved_bom_upload_fields"):
        project_col, bom_col = st.columns(2, gap="large")
        with project_col:
            st.text_input(
                "Project name",
                key="approved_bom_project_name",
                placeholder="Example: Motor Controller",
                help="Enter a new name or reuse an existing project name. Leave blank to use General.",
                autocomplete="off",
            )
        with bom_col:
            st.text_input(
                "BOM name",
                key="approved_bom_name",
                placeholder="Example: Motor Controller Rev A",
                autocomplete="off",
            )


def render_bom_catalog(records: list[dict[str, Any]] | None, user_id: str = "") -> None:
    begin_approved_page()
    analysis_error = st.session_state.pop("cadivor_bom_analysis_error", "")
    if analysis_error:
        st.error("The BOM analysis could not complete. Your upload is still here; review it and try again.")
    from src.pages.home_workspace import remember_saved_analyses_for_session

    remember_saved_analyses_for_session(
        st.session_state,
        user_id=user_id,
        rows=records,
    )
    rows = _rows_with_project_edits(_records(records))
    edit_id = str(st.session_state.get(SAVED_BOM_EDIT_STATE) or "").strip()
    delete_id = str(st.session_state.get(SAVED_BOM_DELETE_STATE) or "").strip()
    action_id = delete_id or edit_id
    if action_id:
        target_row = next((row for row in rows if str(row.get("id") or "").strip() == action_id), None)
        if target_row is None:
            st.error("This saved BOM is no longer available in the current workspace.")
            if st.button("Return to BOMs", key="approved_saved_bom_action_back"):
                st.session_state.pop(SAVED_BOM_EDIT_STATE, None)
                st.session_state.pop(SAVED_BOM_DELETE_STATE, None)
                navigate_to("BOM Analyzer", show_saved_analyses="1", arm_opening=False)
        elif delete_id:
            _render_saved_bom_delete_page(target_row, user_id)
        else:
            _render_saved_bom_edit_page(target_row, user_id)
        end_approved_page()
        return
    analysis_running = bool(
        st.session_state.get("bom8_analysis_future")
        or st.session_state.get("bom8_analysis_pending")
        or st.session_state.get("bom8_analysis_in_progress")
        or st.session_state.get("cadivor_bom_pipeline_active")
    )
    catalog_requested = bool(
        st.session_state.get("cadivor_bom_catalog_requested")
        or st.session_state.get("cadivor_show_saved_boms")
    ) and not analysis_running
    upload_mode = bool(st.session_state.get("cadivor_bom_upload_open")) and not catalog_requested
    analysis_results = st.session_state.get("results_df")
    results_visible = bool(
        not catalog_requested
        and analysis_results is not None
        and not getattr(analysis_results, "empty", True)
    )
    if analysis_running and not results_visible:
        # The analysis pipeline can inherit the browser's previous scroll
        # offset. Use st.html so this reset runs in the app document;
        # components.html runs inside a sandboxed iframe and cannot reliably
        # scroll the parent page.
        try:
            from src.ui.navigation import NAV_SCROLL_RESET_TOKEN_KEY

            scroll_token = int(
                st.session_state.get("cadivor_bom_analysis_scroll_token")
                or st.session_state.get(NAV_SCROLL_RESET_TOKEN_KEY)
                or 0
            )
        except (ImportError, TypeError, ValueError):
            scroll_token = 0
        st.markdown(
            '<div id="cadivor-bom-analysis-top-anchor" '
            f'data-scroll-token="{scroll_token}" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        st.html(
            """
            <script>
            (() => {
              const doc = document;
              const anchor = doc.getElementById('cadivor-bom-analysis-top-anchor');
              const token = anchor?.getAttribute('data-scroll-token') || '0';
              const root = doc.documentElement;
              const activeKey = '__cadivorBomAnalysisScrollLock';
              const existing = root[activeKey];
              if (existing && existing.token === token && existing.timer) {
                existing.reset();
                return;
              }
              if (existing) existing.stop();

              const state = { token, userInteracted: false, timer: null, missingSince: 0, startedAt: Date.now() };
              const stop = () => {
                if (state.timer) window.clearInterval(state.timer);
                state.timer = null;
                doc.removeEventListener('wheel', cancelOnScroll, true);
                doc.removeEventListener('touchmove', cancelOnScroll, true);
                doc.removeEventListener('keydown', cancelOnNavigationKey, true);
                if (root[activeKey] === state) delete root[activeKey];
              };
              const cancelOnScroll = () => {
                state.userInteracted = true;
                stop();
              };
              const cancelOnNavigationKey = (event) => {
                const target = event.target;
                if (target && target.closest && target.closest('input, textarea, select, [contenteditable="true"]')) return;
                if (['PageUp', 'PageDown', 'Home', 'End', 'ArrowUp', 'ArrowDown', ' '].includes(event.key)) cancelOnScroll();
              };
              state.stop = stop;
              state.reset = () => {
                if (state.userInteracted) return;
                const progress = doc.querySelector('.st-key-bom8_analysis_progress_card');
                const marker = doc.getElementById('cadivor-bom-analysis-top-anchor');
                if (!progress || !marker) {
                  if (!state.missingSince) state.missingSince = Date.now();
                  // Streamlit can temporarily replace the progress subtree during
                  // a full rerun. Keep the lock through that short unmount window.
                  if (Date.now() - state.missingSince > 10000) stop();
                  return;
                }
                state.missingSince = 0;
                const main = doc.querySelector('section[data-testid="stMain"]');
                const candidates = [
                  main && main.querySelector('[data-testid="stMainBlockContainer"]'),
                  main && main.querySelector('.main'),
                  main,
                  doc.querySelector('section.main'),
                  doc.querySelector('[data-testid="stAppViewContainer"]'),
                  doc.scrollingElement,
                  doc.documentElement,
                  doc.body
                ].filter(Boolean);
                for (const element of candidates) {
                  try {
                    if (Math.abs(element.scrollTop) > 24) element.scrollTop = 0;
                  } catch (error) {}
                }
                try {
                  const rect = marker.getBoundingClientRect();
                  if (rect.top < -24 || rect.top > 32) marker.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'auto' });
                } catch (error) {}
                try { window.scrollTo({ top: 0, left: 0, behavior: 'auto' }); } catch (error) {}
                if (Date.now() - state.startedAt > 600000) stop();
              };
              root[activeKey] = state;
              doc.addEventListener('wheel', cancelOnScroll, { capture: true, passive: true });
              doc.addEventListener('touchmove', cancelOnScroll, { capture: true, passive: true });
              doc.addEventListener('keydown', cancelOnNavigationKey, true);
              state.reset();
              state.timer = window.setInterval(state.reset, 350);
            })();
            </script>
            """,
            unsafe_allow_javascript=True,
        )
    with st.container(key="approved_bom_title"):
        title_col, action_col = st.columns([5.2, 1.8], vertical_alignment="center")
        with title_col:
            st.markdown(
                f"""
                <div class="cv-ap">
                  <h1>{_esc("Analyzing BOM" if analysis_running else ("BOM analysis results" if results_visible else "BOMs"))}</h1>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with action_col:
            if analysis_running:
                pass
            elif upload_mode and not results_visible:
                if st.button(
                    "Manage saved BOMs",
                    key="approved_bom_manage",
                    type="tertiary",
                    disabled=analysis_running,
                ):
                    st.session_state["cadivor_bom_upload_open"] = False
                    st.session_state["cadivor_manage_saved_boms"] = False
                    st.session_state.pop("cadivor_bom_pipeline_active", None)
                    st.session_state.pop("bom8_analysis_upload_file", None)
                    st.rerun()
            else:
                if st.button(
                    "+ New BOM analysis",
                    key="approved_bom_new",
                    type="primary",
                    disabled=analysis_running,
                ):
                    prepare_new_approved_bom_analysis(st.session_state)
                    st.rerun()
    if analysis_running and not results_visible:
        with st.container(key="approved_bom_upload_progress"):
            active_name = str(st.session_state.get("bom8_bom_name") or "this BOM").strip()
            st.caption(
                f"Preparing or checking supplier data for {active_name}. Your report will open when the analysis is complete."
            )
    elif should_render_approved_bom_upload_form(
        upload_mode=upload_mode,
        analysis_running=analysis_running,
        results_visible=results_visible,
    ):
        with st.container(key="approved_bom_upload_panel"):
            st.markdown(
                """
                <div class="cv-bom-upload-heading">
                  <h2>New BOM analysis</h2>
                  <p>Choose a project, name your analysis, and upload a BOM file to review its risk.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            # Keep the file uploader outside a Streamlit form. Form widgets are
            # submitted in one batch, which can leave the browser showing a
            # selected file before the server has the UploadedFile object. A
            # standalone uploader reruns as soon as the upload reaches the
            # server, so Analyze is enabled only once the file is available.
            with st.container(key="approved_bom_upload_form"):
                # Text inputs otherwise request a full Streamlit rerun on each
                # keystroke. Keep their repaint local; the standalone uploader
                # and Analyze action stay on the normal full-page workflow so
                # the selected UploadedFile is available when submitted.
                fragment = getattr(st, "fragment", None)
                if callable(fragment):
                    fragment(_render_approved_bom_upload_name_fields)()
                else:
                    _render_approved_bom_upload_name_fields()
                typed_project = str(st.session_state.get("approved_bom_project_name") or "")
                bom_name = str(st.session_state.get("approved_bom_name") or "")
                st.caption("Use a project to group related BOM revisions. BOM name is required.")
                uploaded = st.file_uploader(
                    "Upload your BOM file",
                    type=["csv", "xlsx"],
                    key="bom_file_uploader",
                    help="CSV or Excel with MPN and Quantity columns.",
                    disabled=analysis_running,
                )
                upload_state_file = uploaded if uploaded is not None else st.session_state.get(
                    "bom_file_uploader"
                )
                upload_available = upload_state_file is not None
                uploaded_name = str(getattr(upload_state_file, "name", "") or "")
                if upload_available:
                    st.session_state.pop("cadivor_bom_submission_error", None)
                with st.container(key="approved_bom_submit_row"):
                    submit_col, guidance_col = st.columns([0.12, 0.88], gap="small", vertical_alignment="center")
                    with submit_col:
                        submitted = st.button(
                            "Analyzing BOM…" if analysis_running else "Analyze BOM",
                            key="approved_bom_analyze",
                            type="primary",
                            disabled=should_disable_bom_analyze_button(
                                analysis_running=analysis_running,
                                upload_available=upload_available,
                            ),
                        )
                    with guidance_col:
                        if upload_available:
                            st.caption(
                                f"✓ {uploaded_name or 'File'} is fully uploaded and ready. "
                                "Select Analyze BOM to start."
                            )
                        else:
                            st.markdown(
                                """
                                <div class="cadivor-bom-upload-waiting" role="status" aria-live="polite">
                                  <span class="cadivor-bom-upload-spinner" aria-hidden="true"></span>
                                  <span>Select a CSV or Excel file above. Cadivor is waiting for the complete upload; Analyze BOM activates when the file is ready.</span>
                                </div>
                                <style>
                                @keyframes cadivor-bom-upload-spin { to { transform: rotate(360deg); } }
                                .cadivor-bom-upload-waiting {
                                  display: flex;
                                  align-items: center;
                                  gap: .45rem;
                                  min-height: 1.2rem;
                                  color: #5b6777;
                                  font-size: .82rem;
                                  line-height: 1.3;
                                }
                                .cadivor-bom-upload-spinner {
                                  width: .75rem;
                                  height: .75rem;
                                  flex: 0 0 .75rem;
                                  border: 2px solid #d6e1f0;
                                  border-top-color: #2563eb;
                                  border-radius: 50%;
                                  animation: cadivor-bom-upload-spin .8s linear infinite;
                                }
                                @media (prefers-reduced-motion: reduce) {
                                  .cadivor-bom-upload-spinner { animation: none; }
                                }
                                </style>
                                """,
                                unsafe_allow_html=True,
                            )
                if submitted:
                    staged = stage_approved_bom_submission(
                        st.session_state,
                        submitted=True,
                        uploaded_file=uploaded,
                        project_name=resolve_project_choice(
                            NEW_PROJECT_CHOICE,
                            typed_project,
                            blank_uses_general=True,
                        ),
                        bom_name=bom_name,
                    )
                    if staged:
                        return
                    st.error(st.session_state["cadivor_bom_submission_error"])
                elif st.session_state.get("cadivor_bom_submission_error"):
                    st.error(st.session_state["cadivor_bom_submission_error"])

    elif results_visible:
        pass
    else:
        from datetime import date

        project_options = catalog_project_options(rows)
        filter_nonce = int(st.session_state.get("approved_bom_filter_nonce") or 0)
        project_key = f"approved_bom_project_{filter_nonce}"
        if st.session_state.get(project_key) not in project_options and project_key in st.session_state:
            st.session_state[project_key] = "All projects"
        with st.container(key="approved_bom_toolbar"):
            search_col, project_col, health_col, date_col, clear_col = st.columns(
                [1.7, 1.05, 1, 1.05, 0.85],
                vertical_alignment="bottom",
            )
            with search_col:
                query = st.text_input(
                    "Search",
                    key=f"approved_bom_search_{filter_nonce}",
                    placeholder="Search BOMs, projects, or files",
                    label_visibility="collapsed",
                )
            with project_col:
                project_filter = st.selectbox("Project", project_options, key=project_key)
            with health_col:
                health_filter = st.selectbox(
                    "Health",
                    ["All health", "Healthy", "Review", "At risk"],
                    key=f"approved_bom_health_{filter_nonce}",
                )
            with date_col:
                date_filter = st.selectbox(
                    "Date range",
                    ["Last 90 days", "Last 30 days", "All time"],
                    key=f"approved_bom_dates_{filter_nonce}",
                )
            with clear_col:
                if st.button("Clear filters", key="approved_bom_clear"):
                    reset_catalog_filters(st.session_state)
                    st.rerun()
        needle = query.strip().casefold()
        today = date.today()
        visible = []
        for row in rows:
            project_name, bom_name = split_project_and_bom(row)
            filename = str(_first(row, "filename", "source_filename", fallback="") or "")
            if needle and needle not in f"{project_name} {bom_name} {filename}".casefold():
                continue
            if project_filter != "All projects" and project_name != project_filter:
                continue
            score = _num(_first(row, "health_score"))
            high = _num(_first(row, "high_risk_count"))
            label = catalog_health_label(score, high)
            if health_filter != "All health" and label != health_filter:
                continue
            if not within_analyzed_range(_first(row, "created_at", "updated_at", fallback=""), date_filter, today):
                continue
            visible.append((row, label, project_name, bom_name))
        bom_widths = [2.25, 1.35, 0.76, 0.84, 1.0, 1.18, 0.68]
        with st.container(key="approved_bom_catalog_table"):
            header_labels = ("Name", "Project", "Part count", "Health", "High-risk parts", "Last analyzed", "Actions")
            header_cells = "".join(
                f"<span role='columnheader'>{_esc(label)}</span>"
                for label in header_labels
            )
            st.markdown(
                f"<div class='cv-ap-home-table-head' role='row'>{header_cells}</div>",
                unsafe_allow_html=True,
            )
            if not visible:
                st.markdown(
                    "<div class='cv-ap-home-empty'>No BOMs match these filters.</div>",
                    unsafe_allow_html=True,
                )
            for index, (row, label, project_name, bom_name) in enumerate(visible[:12]):
                kind = {"Healthy": "low", "Review": "medium", "At risk": "high"}[label]
                analysis_id = str(row.get("id") or "")
                high = _num(_first(row, "high_risk_count"))
                source_filename = str(_first(row, "filename", "source_filename", fallback="") or "").strip()
                display_bom_name = bom_name or source_filename or "Saved BOM"
                if not bom_name and display_bom_name.casefold().endswith(".csv"):
                    display_bom_name = display_bom_name[:-4]
                risk_html = (
                    f"<span class='cv-home-risk-count high'>{high}</span>"
                    if high
                    else "<span class='cv-home-risk-count clear'>0</span>"
                )
                analyzed = analyzed_label(_first(row, "created_at", "updated_at", fallback=""))
                with st.container(key=f"approved_home_row_{index}"):
                    cells = st.columns(bom_widths, vertical_alignment="center")
                    cells[0].markdown(
                        f"<div class='cv-ap-home-bom'><span class='cv-ap-home-row-icon'>{lucide('file-text', 24)}</span>"
                        f"<span class='cv-ap-home-bom-copy'><strong class='cv-ap-name'>{_esc(display_bom_name)}</strong></span></div>",
                        unsafe_allow_html=True,
                    )
                    _render_project_cell(cells[1], row, "home", rows, user_id)
                    cells[2].markdown(
                        f"<div class='cv-ap-home-project cv-ap-table-center'>{_num(_first(row, 'total_parts'))}</div>",
                        unsafe_allow_html=True,
                    )
                    cells[3].markdown(
                        f"<div class='cv-ap-table-center'>{_health_pill(_num(_first(row, 'health_score')))}</div>",
                        unsafe_allow_html=True,
                    )
                    cells[4].markdown(
                        f"<div class='cv-ap-table-center'>{risk_html}</div>",
                        unsafe_allow_html=True,
                    )
                    cells[5].markdown(
                        f"<div class='cv-ap-home-project cv-ap-table-center'>{analyzed}</div>",
                        unsafe_allow_html=True,
                    )
                    _render_saved_bom_actions(
                        cells[6],
                        analysis_id,
                        scope="home",
                        row_key=str(index),
                    )
    if st.session_state.get("cadivor_bom_analysis_ready"):
        return
    # On ordinary visits this renderer owns the page and stops the legacy route.
    # A submitted upload must continue through the same runtime so it can parse,
    # analyze, save, and render the result on subsequent Streamlit reruns.
    if should_stop_approved_bom_renderer(
        st.session_state,
        upload_mode=upload_mode,
        results_visible=results_visible,
    ):
        end_approved_page()


def render_decision_queue(records: list[dict[str, Any]] | None) -> None:
    begin_approved_page()
    from datetime import date

    counts = decision_queue_view(records, today=date.today())
    st.markdown(
        """
        <div class="cv-ap">
          <p class="cv-ap-kicker">ENGINEERING</p>
          <h1>Engineering decisions</h1>
          <p class="cv-ap-sub">This queue tracks individual monitoring alerts and BOM reviews. An approved alternate stays linked here until you explicitly record how it resolves the alert.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    icon_open = '<svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="1.8"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/></svg>'
    icon_over = '<svg viewBox="0 0 24 24" fill="none" stroke="#e11d48" stroke-width="1.8"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>'
    icon_ok = '<svg viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="1.8"><circle cx="12" cy="12" r="8"/><path d="M8 12l3 3 5-6"/></svg>'
    icon_boms = '<svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="1.8"><path d="M12 3l8 4-8 4-8-4z"/><path d="M4 12l8 4 8-4"/><path d="M4 16l8 4 8-4"/></svg>'
    cards = (
        ("open", "Open decisions", counts["open"], "Open", "", icon_open, ""),
        ("overdue", "Overdue", counts["overdue"], "Overdue", "", icon_over, "risk"),
        ("resolved", "Resolved this month", counts["resolved_month"], "Resolved", "", icon_ok, "ok"),
        ("boms", "BOMs affected", counts["affected"], "All statuses", "boms", icon_boms, ""),
    )
    active_filter = str(st.session_state.get("approved_decision_filter") or "All statuses")
    active_scope = str(st.session_state.get("approved_decision_scope") or "")
    with st.container(key="approved_decision_cards"):
        card_cols = st.columns(4)
        for column, (key, label, count, status, scope, icon, tone) in zip(card_cols, cards):
            selected = active_scope == scope and (
                scope == "boms" or active_filter == status
            )
            selected_class = " is-active" if selected and (scope or status != "All statuses") else ""
            with column:
                with st.container(key=f"approved_decision_cardwrap_{key}"):
                    st.markdown(
                        f"<article class='cv-ed-card{selected_class}'>"
                        f"<span class='cv-ap-ico {tone}'>{icon}</span>"
                        f"<div class='cv-ed-copy'><span>{label}</span>"
                        f"<strong>{count}<svg class='cv-ed-chevron' width='18' height='18' viewBox='0 0 24 24' fill='none' stroke='#94a3b8' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='m9 18 6-6-6-6'/></svg></strong></div>"
                        f"</article>",
                        unsafe_allow_html=True,
                    )
                    if st.button(label, key=f"approved_decision_drill_{key}"):
                        st.session_state["approved_decision_filter"] = status
                        st.session_state["approved_decision_scope"] = scope
                        if scope == "boms":
                            st.session_state["approved_decision_search"] = ""
                        st.rerun()
    with st.container(key="approved_decision_queue"):
        with st.container(key="approved_decision_toolbar"):
            heading, search_col, filter_col, sort_col = st.columns(
                [1.55, 2.35, 0.85, 0.85],
                vertical_alignment="center",
            )
            with search_col:
                query = st.text_input(
                    "Search",
                    key="approved_decision_search",
                    placeholder="Search components, decisions or owners",
                    label_visibility="collapsed",
                )
            with filter_col:
                with st.popover(
                    "Filter",
                    icon=":material/filter_list:",
                    key="approved_decision_filter_popover",
                ):
                    status_filter = st.selectbox(
                        "Status",
                        ["All statuses", "Open", "Overdue", "In review", "Resolved"],
                        key="approved_decision_filter",
                        label_visibility="collapsed",
                        on_change=lambda: st.session_state.__setitem__("approved_decision_scope", ""),
                    )
            with sort_col:
                with st.popover(
                    "Sort",
                    icon=":material/sort:",
                    key="approved_decision_sort_popover",
                ):
                    sort_by = st.selectbox(
                        "Sort by",
                        ["Due date", "Risk level", "Component"],
                        key="approved_decision_sort",
                        label_visibility="collapsed",
                    )
        view = decision_queue_view(
            records,
            query=query,
            status_filter=status_filter,
            sort_by=sort_by,
            scope=str(st.session_state.get("approved_decision_scope") or ""),
            today=date.today(),
        )
        if str(st.session_state.get("approved_decision_scope") or "") == "boms":
            _render_decision_affected_boms(view["boms"])
            end_approved_page()
            return
        with heading:
            st.markdown(f"<h2>Decision queue ({len(view['rows'])})</h2>", unsafe_allow_html=True)
        widths = [1.55, 1.55, 0.75, 1.0, 0.8, 0.85, 1.5]
        with st.container(key="approved_decision_table_head"):
            header = st.columns(widths, vertical_alignment="center")
            for column, label in zip(header, ("Component", "Title", "Risk level", "Decision status", "Owner", "Due date", "Actions")):
                heading_modifier = {
                    "Owner": " owner",
                    "Due date": " due-date",
                    "Actions": " actions",
                }.get(label, "")
                column.markdown(
                    f"<div class='cv-decision-table-heading{heading_modifier}' role='columnheader'>{_esc(label)}</div>",
                    unsafe_allow_html=True,
                )
        if not view["rows"]:
            st.caption("No engineering decisions match this view.")
        for index, (row, status) in enumerate(view["rows"][:20]):
            level = _first(row, "risk_level", "severity", fallback=None)
            if not level:
                level_html = "Not recorded"
            else:
                folded = str(level).casefold()
                kind = "high" if "high" in folded else ("low" if "low" in folded else "medium")
                level_html = f"<span class='cv-pill {kind}'>{_esc(level)}</span>"
            status_kind = {"Open": "open", "Overdue": "high", "In review": "review", "Resolved": "low"}.get(status, "open")
            owner = _first(row, "assigned_owner", "owner", "assignee", fallback=None)
            owner_label = "Unassigned" if owner is None else _esc(owner)
            mpn = str(_first(row, "mpn", "part_number", "component", fallback="Not recorded"))
            detail = _first(row, "description", "part_description", fallback=None)
            resolution = _first(row, "resolution", fallback=None)
            subtitle_parts = []
            if detail:
                subtitle_parts.append(f"<div class='cv-ap-meta'>{_esc(detail)}</div>")
            if resolution:
                subtitle_parts.append(
                    f"<div class='cv-ap-meta' style='color:#047857;font-weight:750'>"
                    f"{_esc(resolution)}</div>"
                )
            subtitle = "".join(subtitle_parts)
            due = _first(row, "due_date", "due_at", fallback=None)
            if not due:
                due_label = "Not recorded"
            else:
                due_text = analyzed_label(due).split("<br>", 1)[0]
                due_label = f"<span class='cv-due-late'>{due_text}</span>" if status == "Overdue" else due_text
            title = _first(row, "alert_message", "title", "summary", fallback=None)
            title_label = "Not recorded" if title is None else _esc(title)
            image_source = _first(
                row,
                "image_url",
                "product_image_url",
                "primary_image_url",
                "supplier_image_url",
                "photo_url",
                "PhotoUrl",
                "photoUrl",
                "ImageURL",
                "ImageUrl",
                "PrimaryPhoto",
                "image",
                fallback="",
            )
            photo = part_photo(
                image_source,
                size=60,
                part=row,
                part_number=mpn,
            )
            with st.container(key=f"approved_decision_row_{index}"):
                cells = st.columns(widths, vertical_alignment="center")
                cells[0].markdown(
                    f"<div class='cv-ei-part'>{photo}<span class='cv-ei-part-copy'><span class='cv-ap-name'>{_esc(mpn)}</span>{subtitle}</span></div>",
                    unsafe_allow_html=True,
                )
                cells[1].markdown(title_label)
                cells[2].markdown(level_html, unsafe_allow_html=True)
                cells[3].markdown(f"<span class='cv-pill {status_kind}'>{_esc(status)}</span>", unsafe_allow_html=True)
                cells[4].markdown(owner_label)
                cells[5].markdown(due_label, unsafe_allow_html=True)
                analysis_id = str(
                    row.get("analysis_id")
                    or row.get("context_analysis_id")
                    or ""
                )
                action = decision_action_label(row, status)
                with cells[6]:
                    action_col, overflow_col = st.columns(
                        [1, 0.28],
                        gap="small",
                        vertical_alignment="center",
                    )
                    button_type = "primary" if action == "Review" else "secondary"
                    button_key = (
                        f"approved_decision_review_{index}"
                        if action == "Review"
                        else f"approved_decision_record_{index}"
                    )
                    with action_col:
                        if st.button(
                            action,
                            key=button_key,
                            type=button_type,
                            use_container_width=True,
                            help="Open this exact monitoring event to review its evidence and record the outcome.",
                        ):
                            st.session_state["cadivor_decision_focus_mpn"] = mpn
                            from src.decision_engine import monitoring_decision_id

                            decision_id = str(
                                row.get("decision_id") or monitoring_decision_id(row)
                            )
                            navigate_to(
                                "Engineering Decisions",
                                decision_id=decision_id,
                            )
                    with overflow_col:
                        with st.container(key=f"approved_decision_menu_{index}"):
                            with st.popover(
                                "⋯",
                                help="Open the original BOM, Engineering Intelligence, the detailed report, or find a replacement.",
                            ):
                                if analysis_id:
                                    if st.button(
                                        "Open original BOM",
                                        key=f"approved_decision_action_open_{index}",
                                        use_container_width=True,
                                    ):
                                        navigate_to(
                                            "BOM Settings",
                                            saved_bom_id=analysis_id,
                                            saved_bom_action="open",
                                            arm_opening=False,
                                        )
                                    if st.button(
                                        "Engineering Intelligence",
                                        key=f"approved_decision_action_risk_{index}",
                                        use_container_width=True,
                                    ):
                                        st.session_state["cadivor_show_detailed_risk"] = False
                                        st.session_state["cadivor_ei_report_tab"] = "BOM Risk"
                                        st.session_state["cadivor_active_analysis_id"] = analysis_id
                                        st.session_state["analysis_id"] = analysis_id
                                        st.session_state["cadivor_pending_analysis_section"] = "Engineering Intelligence"
                                        st.session_state["cadivor_pending_analysis_section_id"] = analysis_id
                                        navigate_to(
                                            "Analysis Details",
                                            analysis_id=analysis_id,
                                            analysis_tab="Engineering Intelligence",
                                            arm_opening=False,
                                        )
                                    if st.button(
                                        "Detailed Risk Report",
                                        key=f"approved_decision_action_report_{index}",
                                        use_container_width=True,
                                    ):
                                        st.session_state["cadivor_show_detailed_risk"] = True
                                        st.session_state["cadivor_active_analysis_id"] = analysis_id
                                        st.session_state["analysis_id"] = analysis_id
                                        st.session_state[f"cadivor_detailed_risk_mpn_{analysis_id}"] = ""
                                        st.session_state["cadivor_pending_analysis_section"] = "Engineering Intelligence"
                                        st.session_state["cadivor_pending_analysis_section_id"] = analysis_id
                                        navigate_to(
                                            "Analysis Details",
                                            analysis_id=analysis_id,
                                            analysis_tab="Engineering Intelligence",
                                            arm_opening=False,
                                        )
                                if mpn and mpn != "Not recorded":
                                    if st.button(
                                        "Find replacement",
                                        key=f"approved_decision_action_alternative_{index}",
                                        use_container_width=True,
                                    ):
                                        project_name = str(
                                            _first(row, "project_name", "project", fallback="") or ""
                                        )
                                        bom_name = str(
                                            _first(row, "bom_name", "filename", fallback="") or ""
                                        )
                                        navigate_to_alternative_finder(
                                            mpn=mpn,
                                            manufacturer=str(
                                                _first(row, "manufacturer", "manufacturer_name", fallback="") or ""
                                            ),
                                            description=str(detail or ""),
                                            lifecycle=str(
                                                _first(row, "lifecycle_status", "lifecycle", fallback="") or ""
                                            ),
                                            risk=str(level or ""),
                                            analysis_id=analysis_id,
                                            part_id=str(
                                                _first(row, "part_id", "analysis_part_id", fallback="") or ""
                                            ),
                                            source_page=(
                                                "engineering_intelligence_review"
                                                if analysis_id
                                                else ""
                                            ),
                                            return_analysis_id=analysis_id,
                                            project_name=project_name,
                                            bom_name=bom_name,
                                        )
                                if not analysis_id:
                                    st.caption(
                                "No single saved BOM is linked to this alert. Open Record decision to review the event and choose a BOM context when available."
                                    )
    end_approved_page()


def _alert_slots(
    source: list[dict[str, Any]],
    predicate,
    period: str = "Last 30 days",
    today: date | None = None,
) -> list[float | None]:
    """Group real alert records into six chronological spark-bar buckets."""
    dates = [
        recorded
        for item in source
        if predicate(item)
        if (recorded := _alert_recorded_date(item)) is not None
    ]
    if not dates:
        return [None] * 6

    end = today or max(dates)
    if period == "All recorded":
        start = min(dates)
        end = max(dates)
        if start == end:
            start = end - timedelta(days=5)
    else:
        days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}.get(period, 30)
        start = end - timedelta(days=days - 1)

    span_days = max(1, (end - start).days + 1)
    counts = [0] * 6
    for recorded in dates:
        if recorded < start or recorded > end:
            continue
        bucket = min(5, max(0, ((recorded - start).days * 6) // span_days))
        counts[bucket] += 1
    return [float(count) if count else None for count in counts]


def _alert_category(row: dict[str, Any]) -> str:
    text = f"{_first(row, 'alert_type', fallback='')} {_first(row, 'alert_message', fallback='')}".casefold()
    if "life" in text:
        return "Lifecycle"
    if "price" in text or "cost" in text:
        return "Price movement"
    if "stock" in text or "invent" in text:
        return "Stock & supply"
    if "supplier" in text:
        return "Supplier"
    if "qual" in text:
        return "Quality"
    if "regulat" in text or "compliance" in text:
        return "Regulatory"
    return "Other"


def _is_high_priority_alert(row: dict[str, Any]) -> bool:
    severity = str(_first(row, "severity", fallback="")).casefold()
    return any(token in severity for token in ("high", "critical", "urgent"))


def _next_action(row: dict[str, Any]) -> tuple[str, str]:
    category = _alert_category(row)
    if category == "Lifecycle":
        return "Review alternatives", "Alternative Finder"
    if category == "Stock & supply":
        return "View suppliers", "Procurement Advisor"
    if category == "Price movement":
        return "View pricing", "Cost Optimization"
    return "View details", "Monitoring"


def _alert_recorded_date(row: dict[str, Any]) -> date | None:
    raw = str(_first(row, "created_at", fallback="") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None



def _alerts_in_period(source: list[dict[str, Any]], period: str, today: date) -> list[dict[str, Any]]:
    if period == "All recorded":
        return list(source)
    days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}.get(period, 30)
    cutoff = today - timedelta(days=days - 1)
    return [
        row
        for row in source
        if (recorded := _alert_recorded_date(row)) is not None and cutoff <= recorded <= today
    ]


def _alert_detected_labels(row: dict[str, Any], now: datetime | None = None) -> tuple[str, str]:
    raw = str(_first(row, "created_at", fallback="") or "").strip()
    recorded_date = _alert_recorded_date(row)
    if recorded_date is None:
        return "Date unavailable", ""

    has_time = "T" in raw or (" " in raw and ":" in raw)
    if not has_time:
        age_days = max(0, ((now or datetime.now(timezone.utc)).date() - recorded_date).days)
        relative = "Today" if age_days == 0 else ("Yesterday" if age_days == 1 else f"{age_days} days ago")
        return relative, f"{recorded_date.strftime('%b')} {recorded_date.day}, {recorded_date.year}"

    try:
        timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return f"{recorded_date.strftime('%b')} {recorded_date.day}", f"{recorded_date.year}"
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    age_seconds = max(0, (current.astimezone(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds())
    if age_seconds < 60:
        relative = "Just now"
    elif age_seconds < 3600:
        minutes = int(age_seconds // 60)
        relative = f"{minutes} {'min' if minutes == 1 else 'mins'} ago"
    elif age_seconds < 86400:
        hours = int(age_seconds // 3600)
        relative = f"{hours} {'hour' if hours == 1 else 'hours'} ago"
    else:
        age_days = int(age_seconds // 86400)
        relative = "Yesterday" if age_days == 1 else f"{age_days} days ago"
    local_stamp = timestamp.astimezone(timezone.utc)
    exact = f"{local_stamp.strftime('%b')} {local_stamp.day}, {local_stamp.year} {local_stamp.strftime('%H:%M')} UTC"
    return relative, exact


def render_monitoring(alerts: list[dict[str, Any]] | None) -> None:
    begin_approved_page()
    source = _records(alerts)
    st.markdown(
        """
        <div class="cv-ap cv-ap-monitoring-page-header">
          <h1>Alerts & monitoring</h1>
          <p class="cv-ap-sub">Stay ahead of changes in component availability, lifecycle status, pricing and supplier activity.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    categories = ["All alerts", "Stock & supply", "Lifecycle", "Price movement", "Supplier", "Quality", "Regulatory"]
    period_options = ["Last 30 days", "Last 7 days", "Last 90 days", "All recorded"]
    today = datetime.now(timezone.utc).date()
    active_period = str(st.session_state.get("approved_alert_period") or "Last 30 days")
    period_source = _alerts_in_period(source, active_period, today)
    active_alert_count = len(period_source)
    high = sum(1 for row in period_source if _is_high_priority_alert(row))
    lifecycle_count = sum(1 for row in period_source if _alert_category(row) == "Lifecycle")
    inventory_count = sum(1 for row in period_source if _alert_category(row) == "Stock & supply")
    active_spark = spark_slots(
        _alert_slots(period_source, lambda _row: True, active_period, today),
        "#91bfff",
    )
    high_spark = spark_slots(
        _alert_slots(period_source, _is_high_priority_alert, active_period, today),
        "#f5a1a1",
    )
    life_spark = spark_slots(
        _alert_slots(
            period_source,
            lambda row: _alert_category(row) == "Lifecycle",
            active_period,
            today,
        ),
        "#c4a5ff",
    )
    stock_spark = spark_slots(
        _alert_slots(
            period_source,
            lambda row: _alert_category(row) == "Stock & supply",
            active_period,
            today,
        ),
        "#9bdfbb",
    )
    monitoring_cards = (
        (
            "active",
            "Active alerts",
            active_alert_count,
            "blue",
            "bell",
            active_spark,
            "All alerts",
            "All",
        ),
        (
            "high",
            "High priority",
            high,
            "red",
            "triangle-alert",
            high_spark,
            "All alerts",
            "High",
        ),
        (
            "lifecycle",
            "Lifecycle changes",
            lifecycle_count,
            "violet",
            "refresh-cw",
            life_spark,
            "Lifecycle",
            "All",
        ),
        (
            "inventory",
            "Inventory updates",
            inventory_count,
            "green",
            "package",
            stock_spark,
            "Stock & supply",
            "All",
        ),
    )
    with st.container(key="approved_monitoring_kpi_grid"):
        card_columns = st.columns(4, gap="small")
        for column, (
            slug,
            label,
            value,
            tone,
            icon,
            spark,
            target_category,
            target_severity,
        ) in zip(card_columns, monitoring_cards):
            with column:
                with st.container(key=f"approved_monitoring_kpi_{slug}"):
                    st.markdown(
                        f"<article class='cv-ap-kpi cv-ap-monitoring-kpi cv-ap-monitoring-kpi--{tone}'>"
                        f"<span class='cv-ap-monitoring-icon' aria-hidden='true'>{lucide(icon, 26)}</span>"
                        f"<div class='cv-ap-monitoring-copy'><span>{_esc(label)}</span>"
                        f"<strong>{_esc(value)}<span class='cv-ap-monitoring-chevron' aria-hidden='true'>›</span></strong></div>"
                        f"{spark}</article>",
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        f"Show {label}",
                        key=f"approved_monitoring_action_{slug}",
                        help=f"Filter recent alerts to {label.casefold()}.",
                        type="tertiary",
                        width="stretch",
                    ):
                        st.session_state["approved_alert_category"] = target_category
                        st.session_state["approved_alert_severity"] = target_severity
                        st.rerun()

    with st.container(key="approved_monitoring_filters"):
        if st.session_state.get("approved_alert_category") not in categories:
            st.session_state["approved_alert_category"] = "All alerts"

        def _reset_monitoring_severity() -> None:
            st.session_state["approved_alert_severity"] = "All"

        label_col, show_col, period_col = st.columns(
            [0.42, 8.45, 3.1],
            vertical_alignment="center",
            gap="small",
        )
        with label_col:
            st.markdown("<div class='cv-ap-monitoring-show-label'>Show</div>", unsafe_allow_html=True)
        with show_col:
            with st.container(key="approved_monitoring_category_row"):
                selected = st.pills(
                    "Alert category",
                    categories,
                    selection_mode="single",
                    required=True,
                    key="approved_alert_category",
                    on_change=_reset_monitoring_severity,
                    label_visibility="collapsed",
                    width="stretch",
                )
        with period_col:
            period_label_col, period_select_col = st.columns([.78, 1.5], vertical_alignment="center", gap="small")
            with period_label_col:
                st.markdown("<div class='cv-ap-monitoring-period-label'>Time period</div>", unsafe_allow_html=True)
            with period_select_col:
                with st.container(key="approved_monitoring_period_control"):
                    calendar_col, select_col = st.columns([.18, 1], vertical_alignment="center", gap="small")
                    with calendar_col:
                        st.markdown(
                            f"<div class='cv-ap-monitoring-calendar' aria-hidden='true'>{lucide('calendar-clock', 18)}</div>",
                            unsafe_allow_html=True,
                        )
                    with select_col:
                        period = st.selectbox(
                            "Time period",
                            period_options,
                            index=0,
                            key="approved_alert_period",
                            label_visibility="collapsed",
                        )

        selected = str(selected or "All alerts")
        severity_filter = str(st.session_state.get("approved_alert_severity") or "All")

    rows = source
    if selected and selected != "All alerts":
        rows = [row for row in rows if _alert_category(row) == selected]
    rows = _alerts_in_period(rows, str(period or "Last 30 days"), today)
    if severity_filter == "High":
        rows = [row for row in rows if _is_high_priority_alert(row)]
    filtered_total = len(rows)
    rows = rows[:8]

    with st.container(key="approved_monitoring_alert_card"):
        with st.container(key="approved_monitoring_alert_heading"):
            heading_col, count_col = st.columns([5, 1], vertical_alignment="center")
            with heading_col:
                st.markdown(
                    "<div class='cv-ap-monitoring-heading'><h2>Recent alerts</h2></div>",
                    unsafe_allow_html=True,
                )
            with count_col:
                shown_start = 1 if rows else 0
                st.markdown(
                    f"<div class='cv-ap-monitoring-count'>{shown_start}–{len(rows)} of {filtered_total} alerts</div>",
                    unsafe_allow_html=True,
                )
        header_labels = ("Severity", "Component", "Signal", "Detected", "Next action")
        header_cells = "".join(
            f"<span role='columnheader'>{_esc(label)}<span class='cv-ap-monitoring-sort' aria-hidden='true'>{'↕' if label in {'Severity', 'Detected'} else ''}</span></span>"
            for label in header_labels
        ) + "<span role='columnheader' aria-label='More actions'></span>"
        st.markdown(
            f"<div class='cv-ap-monitoring-table-head' role='row'>{header_cells}</div>",
            unsafe_allow_html=True,
        )
        if not rows:
            st.markdown(
                "<div class='cv-ap-home-empty'>No alerts match the selected filters.</div>",
                unsafe_allow_html=True,
            )
        for index, row in enumerate(rows):
            severity = str(_first(row, "severity", fallback="Low"))
            kind = "high" if "high" in severity.casefold() else ("medium" if "med" in severity.casefold() else "low")
            action_label, destination = _next_action(row)
            mpn = _first(row, "mpn", "part_number", fallback="Component")
            manufacturer = _first(row, "manufacturer", "manufacturer_name", "brand", fallback="")
            detected_relative, detected_exact = _alert_detected_labels(row)
            with st.container(key=f"approved_monitoring_alert_row_{index}"):
                cells = st.columns([0.8, 1.3, 1.9, 1.2, 1.2, .28], vertical_alignment="center", gap="small")
                cells[0].markdown(
                    f"<span class='cv-pill {kind}'><i class='cv-pill-dot'></i>{_esc(severity)}</span>",
                    unsafe_allow_html=True,
                )
                component_detail = f"<div class='cv-ap-meta'>{_esc(manufacturer)}</div>" if manufacturer else ""
                cells[1].markdown(
                    f"<div class='cv-ap-name'>{_esc(mpn)}</div>{component_detail}",
                    unsafe_allow_html=True,
                )
                cells[2].markdown(
                    f"<div class='cv-ap-name'>{_esc(_first(row, 'alert_type', fallback='Update'))}</div>"
                    f"<div class='cv-ap-meta'>{_esc(_first(row, 'alert_message', fallback=''))}</div>",
                    unsafe_allow_html=True,
                )
                cells[3].markdown(
                    f"<div class='cv-ap-monitoring-detected'><strong>{_esc(detected_relative)}</strong>"
                    f"<small>{_esc(detected_exact)}</small></div>",
                    unsafe_allow_html=True,
                )
                with cells[4]:
                    if st.button(
                        action_label,
                        key=f"approved_alert_action_{index}",
                        type="secondary",
                        use_container_width=True,
                    ):
                        navigate_to(destination)
                with cells[5]:
                    with st.container(key=f"approved_alert_more_{index}"):
                        with st.popover(
                            "⋯",
                            help=f"View alert details for {mpn}.",
                            key=f"approved_alert_popover_{index}",
                        ):
                            st.markdown(
                                f"<div class='cv-ap-alert-popover'><strong>{_esc(mpn)}</strong>"
                                f"<span>{_esc(_first(row, 'alert_type', fallback='Update'))}</span>"
                                f"<p>{_esc(_first(row, 'alert_message', fallback='No additional signal details were recorded.'))}</p>"
                                f"<small>{_esc(manufacturer or 'Manufacturer not recorded')} · {_esc(severity)}</small></div>",
                                unsafe_allow_html=True,
                            )
    end_approved_page()


def render_reports_list(records: list[dict[str, Any]] | None) -> None:
    begin_approved_page()
    rows = _records(records)[:8]
    templates = (
        (
            "Executive BOM Report",
            "High-level summary of cost, supply risk and key insights for stakeholders.",
            "file-text",
            ("DOCX", "XLSX", "PPTX"),
        ),
        (
            "Engineering Risk Review",
            "Detailed assessment of supply, obsolescence and compliance risks across your BOM.",
            "shield",
            ("DOCX", "XLSX"),
        ),
        (
            "Sourcing Summary",
            "Supplier options, cost comparison and recommended sourcing strategies.",
            "shopping-cart",
            ("XLSX", "PPTX"),
        ),
    )
    cards = []
    for title, copy, icon_name, formats in templates:
        chips = "".join(
            f"<span class='cv-ap-report-format'>{_esc(fmt)}</span>"
            for fmt in formats
        )
        cards.append(
            "<article class='cv-ap-report-template'>"
            "<div class='cv-ap-report-template-main'>"
            f"<span class='cv-ap-report-template-icon' aria-hidden='true'>{lucide(icon_name, 26)}</span>"
            "<div class='cv-ap-report-template-copy'>"
            f"<h3>{_esc(title)}</h3><p>{_esc(copy)}</p>"
            "</div></div>"
            "<div class='cv-ap-report-template-footer'>"
            f"<span class='cv-ap-report-formats-label'>Formats</span>{chips}"
            "</div></article>"
        )

    st.markdown(
        """
        <style data-cadivor-layout-style="true">
          .st-key-approved_page_canvas_wide_render_reports_list>[data-testid="stVerticalBlock"]{gap:0!important}
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report{
            color:#0f172a;font-family:Inter,"Segoe UI",sans-serif
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report h1{
            margin:0 0 7px;color:#14233c;font-size:34px;font-weight:760;line-height:1.15;letter-spacing:-.035em
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-kicker{
            margin:0 0 8px;color:#64748b;font-size:12px;font-weight:750;letter-spacing:.09em
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-sub{
            margin:0 0 38px;color:#64748b;font-size:15px;line-height:1.45
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-section-title{
            margin:0 0 15px;color:#17253e;font-size:21px;font-weight:750;line-height:1.25;letter-spacing:-.02em
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-cards{
            display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:0 0 40px
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-template{
            box-sizing:border-box;display:flex;flex-direction:column;justify-content:space-between;min-width:0;min-height:206px;
            padding:22px 28px 18px;border:1px solid #dbeafe;border-radius:12px;background:#f8fbff
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-template-main{
            display:flex;align-items:flex-start;gap:22px;min-width:0
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-template-icon{
            box-sizing:border-box;display:inline-flex;align-items:center;justify-content:center;flex:0 0 72px;
            width:72px;height:72px;border-radius:14px;background:#e8f1ff;color:#2563eb
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-template-icon svg{
            width:28px;height:28px;stroke:currentColor
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-template-copy{min-width:0}
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-template h3{
            margin:7px 0 7px;color:#14233c;font-size:19px;font-weight:750;line-height:1.3;letter-spacing:-.015em
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-template p{
            margin:0;color:#64748b;font-size:15px;line-height:1.5
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-template-footer{
            display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding-top:15px;margin-top:18px;border-top:1px solid #dce8f7
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-formats-label{
            margin-right:8px;color:#64748b;font-size:13px;font-weight:650
          }
          .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-format{
            display:inline-flex;align-items:center;justify-content:center;min-height:32px;padding:0 12px;
            border:1px solid #d9e7fb;border-radius:8px;background:#eaf2ff;color:#2563eb;font-size:13px;font-weight:750
          }
          .st-key-approved_page_canvas_wide_render_reports_list .st-key-approved_report_table{
            box-sizing:border-box;width:100%;overflow:hidden;border:1px solid #dce5f0;border-radius:12px;background:#fff
          }
          .st-key-approved_page_canvas_wide_render_reports_list .st-key-approved_report_table > [data-testid="stVerticalBlock"]{
            gap:0!important
          }
          .st-key-approved_page_canvas_wide_render_reports_list .st-key-approved_report_table_header{
            box-sizing:border-box;width:100%;min-height:58px;margin:0;padding:0 18px;
            border-bottom:1px solid #dce4ef;background:#f5f7fa
          }
          .st-key-approved_page_canvas_wide_render_reports_list .st-key-approved_report_table_header>[data-testid="stVerticalBlock"]{
            gap:0!important;min-height:58px;justify-content:center
          }
          .st-key-approved_page_canvas_wide_render_reports_list .st-key-approved_report_table_header [data-testid="stHorizontalBlock"]{
            align-items:center!important;gap:12px!important;min-height:56px
          }
          .cv-ap-report-header-label{
            color:#64748b;font-size:12px;font-weight:750;line-height:1.25;letter-spacing:.045em;text-transform:uppercase
          }
          .cv-ap-report-header-help{margin-left:4px;color:#94a3b8;font-size:13px;font-weight:700}
          .st-key-approved_page_canvas_wide_render_reports_list [class*="st-key-approved_report_row_"]{
            box-sizing:border-box;min-height:84px;margin:0;padding:12px 18px;border-bottom:1px solid #e5ebf3;background:#fff
          }
          .st-key-approved_page_canvas_wide_render_reports_list [class*="st-key-approved_report_row_"]:last-child{border-bottom:0}
          .st-key-approved_page_canvas_wide_render_reports_list [class*="st-key-approved_report_row_"] > [data-testid="stVerticalBlock"]{
            gap:0!important;min-height:60px;justify-content:center
          }
          .st-key-approved_page_canvas_wide_render_reports_list [class*="st-key-approved_report_row_"] [data-testid="stHorizontalBlock"]{
            align-items:center!important;gap:12px!important;min-height:58px
          }
          .st-key-approved_page_canvas_wide_render_reports_list [class*="st-key-approved_report_row_"] [data-testid="column"],
          .st-key-approved_page_canvas_wide_render_reports_list .st-key-approved_report_table_header [data-testid="column"]{
            box-sizing:border-box;display:flex;align-items:center;min-width:0;padding:4px 4px
          }
          .cv-ap-report-name-cell{display:flex;align-items:center;gap:13px;min-width:0}
          .cv-ap-report-row-icon{
            box-sizing:border-box;display:inline-flex;align-items:center;justify-content:center;flex:0 0 28px;width:28px;height:28px;
            border-radius:0;background:transparent;color:#475569
          }
          .cv-ap-report-row-icon svg{width:26px;height:26px}
          .cv-ap-report-name-copy{display:flex;flex-direction:column;min-width:0}
          .cv-ap-report-name-copy strong{display:block;overflow:hidden;color:#17253e;font-size:15px;font-weight:750;line-height:1.3;text-overflow:ellipsis;white-space:nowrap}
          .cv-ap-report-name-copy small{display:block;margin-top:3px;color:#74839a;font-size:13px;line-height:1.25}
          .cv-ap-report-source,.cv-ap-report-date{display:block;overflow:hidden;max-width:100%;color:#52647b;font-size:13px;line-height:1.4;text-overflow:ellipsis;white-space:nowrap}
          .cv-ap-report-health{display:inline-flex;align-items:center;justify-content:flex-start;gap:10px;color:#17253e;font-size:15px}
          .cv-ap-report-health strong{font-weight:700}
          .cv-ap-report-dot{display:inline-block;flex:0 0 13px;width:13px;height:13px;border-radius:50%;background:#cbd5e1}
          .cv-ap-report-dot.good{background:#22a447}
          .cv-ap-report-dot.watch{background:#f5b313}
          .cv-ap-report-dot.risk{background:#e85b59}
          .cv-ap-report-risk{text-align:left;color:#e34f55;font-size:15px;font-weight:700}
          .cv-ap-report-empty{padding:22px 18px;color:#64748b;font-size:13px}
          @media(max-width:1050px){
            .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-cards{grid-template-columns:repeat(2,minmax(0,1fr))}
            .st-key-approved_page_canvas_wide_render_reports_list [class*="st-key-approved_report_row_"]{padding:8px 12px}
          }
          @media(max-width:760px){
            .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report h1{font-size:28px}
            .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-cards{grid-template-columns:1fr;gap:12px}
            .st-key-approved_page_canvas_wide_render_reports_list .cv-ap-report-template{min-height:0}
            .st-key-approved_page_canvas_wide_render_reports_list .st-key-approved_report_table{overflow-x:auto}
            .st-key-approved_page_canvas_wide_render_reports_list .st-key-approved_report_table_header,
            .st-key-approved_page_canvas_wide_render_reports_list [class*="st-key-approved_report_row_"]{min-width:820px}
          }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="cv-ap-report">
          <p class="cv-ap-report-kicker">REPORTS</p>
          <h1>Engineering reports</h1>
          <p class="cv-ap-report-sub">Create tailored reports from your engineering data and analysis results.</p>
          <h2 class="cv-ap-report-section-title">Report templates</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        "<section class='cv-ap-report-cards'>" + "".join(cards) + "</section>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<h2 class='cv-ap-report-section-title'>Recent report sources</h2>",
        unsafe_allow_html=True,
    )

    widths = [2.05, 1.1, 1.1, 1.15, 1.1, 0.65]
    with st.container(key="approved_report_table"):
        with st.container(key="approved_report_table_header"):
            header_cells = st.columns(widths, vertical_alignment="center")
            for header_cell, label in zip(
                header_cells,
                ("Name", "Source", "Last updated", "", "High-risk parts", "Action"),
            ):
                if label:
                    header_cell.markdown(
                        f"<span class='cv-ap-report-header-label'>{_esc(label)}</span>",
                        unsafe_allow_html=True,
                    )
            header_cells[3].markdown(
                "<span class='cv-ap-report-header-label'>Health score "
                "<span class='cv-ap-report-header-help' title='Health score from the latest saved BOM analysis.'>ⓘ</span></span>",
                unsafe_allow_html=True,
            )
        if not rows:
            st.markdown(
                "<div class='cv-ap-report-empty'>Upload a BOM analysis to populate recent report sources.</div>",
                unsafe_allow_html=True,
            )
        for index, row in enumerate(rows):
            raw_health = _first(row, "health_score")
            has_health = raw_health is not None
            score = _num(raw_health) if has_health else None
            health_state = (
                "good" if score is not None and score >= 80 else
                "watch" if score is not None and score >= 60 else
                "risk" if score is not None else ""
            )
            health_text = str(score) if score is not None else "—"
            high_risk_raw = _first(row, "high_risk_count", "high_risk_parts")
            high_risk_text = str(_num(high_risk_raw)) if high_risk_raw is not None else "—"
            project_name = _first(row, "project_name", "name", fallback="Saved BOM")
            source_name = _first(
                row,
                "source_reference",
                "source_id",
                "filename",
                "uploaded_file",
                "file_name",
                fallback="—",
            )
            source_text = _esc(source_name)
            source_title = _esc(source_name)
            updated = str(
                _first(row, "created_at", "updated_at", "analyzed_at", "date", fallback="—")
            ).strip()
            updated = updated.replace("T", " ")[:10] if updated not in {"", "—"} else "—"
            analysis_id = str(row.get("id") or "")
            with st.container(key=f"approved_report_row_{index}"):
                cells = st.columns(widths, vertical_alignment="center")
                cells[0].markdown(
                    f"<div class='cv-ap-report-name-cell'>"
                    f"<span class='cv-ap-report-row-icon' aria-hidden='true'>{lucide('package', 21)}</span>"
                    f"<span class='cv-ap-report-name-copy'><strong>{_esc(project_name)}</strong>"
                    "<small>BOM Analysis</small></span></div>",
                    unsafe_allow_html=True,
                )
                cells[1].markdown(
                    f"<span class='cv-ap-report-source' title='{source_title}'>{source_text}</span>",
                    unsafe_allow_html=True,
                )
                cells[2].markdown(
                    f"<span class='cv-ap-report-date'>{_esc(updated)}</span>",
                    unsafe_allow_html=True,
                )
                cells[3].markdown(
                    f"<span class='cv-ap-report-health'><i class='cv-ap-report-dot {health_state}'></i>"
                    f"<strong>{_esc(health_text)}</strong></span>",
                    unsafe_allow_html=True,
                )
                cells[4].markdown(
                    f"<div class='cv-ap-report-risk'>{_esc(high_risk_text)}</div>",
                    unsafe_allow_html=True,
                )
                with cells[5]:
                    if analysis_id:
                        internal_nav_button(
                            "Open\u00a0\u00a0>",
                            "Analysis Details",
                            key=f"approved_report_open_{index}",
                            type="tertiary",
                            analysis_id=analysis_id,
                        )
    # Reports sometimes returns to a remembered scroll offset after a route
    # swap. Run the reset in the app document (not a component iframe), then
    # align this canvas at the top so the title and template cards are visible.
    st.html(
        """
        <script>
        (() => {
          const canvasSelector = '.st-key-approved_page_canvas_wide_render_reports_list';
          const resetReportsScroll = () => {
            const canvas = document.querySelector(canvasSelector);
            if (!canvas) return;
            for (let node = canvas; node && node !== document.documentElement; node = node.parentElement) {
              const overflowY = getComputedStyle(node).overflowY;
              if (node.scrollHeight > node.clientHeight || overflowY === 'auto' || overflowY === 'scroll') {
                node.scrollTop = 0;
                if (typeof node.scrollTo === 'function') node.scrollTo({top: 0, left: 0, behavior: 'auto'});
              }
            }
            window.scrollTo({top: 0, left: 0, behavior: 'auto'});
            canvas.scrollIntoView({block: 'start', behavior: 'auto'});
          };
          [0, 80, 240, 500].forEach((delay) => window.setTimeout(resetReportsScroll, delay));
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )
    end_approved_page()


def render_simple_workspace(
    *,
    kicker: str,
    title: str,
    subtitle: str,
    kpis: list[tuple[str, str]],
    headers: list[str],
    table_rows: list[list[str]],
    legacy_page: str = "",
    legacy_label: str = "Open workspace tools",
    chart_html: str = "",
    lead_html: str = "",
    control=None,
    kpi_details: dict[str, dict[str, Any]] | None = None,
) -> None:
    begin_approved_page()
    kpi_html = "".join(
        f"<article class='cv-ap-kpi'><span>{_esc(label)}</span><strong>{_esc(value)}</strong></article>"
        for label, value in kpis
    )
    head = "".join(f"<th>{_esc(header)}</th>" for header in headers)
    body = []
    for row in table_rows[:8]:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append(f"<tr><td colspan='{max(1, len(headers))}'>No saved records for this workspace yet.</td></tr>")
    if len(kpis) == 5:
        columns = "five"
    elif len(kpis) == 3:
        columns = "three"
    else:
        columns = "four"
    charts = f'<div class="cv-ap-charts">{chart_html}</div>' if chart_html else ""
    st.markdown(
        f"""
        <div class="cv-ap">
          <p class="cv-ap-kicker">{_esc(kicker)}</p>
          <h1>{_esc(title)}</h1>
          <p class="cv-ap-sub">{_esc(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if control is not None:
        control()

    if kpi_details:
        st.markdown(
            """
            <style id="cv-ap-clickable-kpis" data-cadivor-layout-style="true">
              .st-key-approved_simple_workspace_kpis button{
                width:100%;min-height:92px;border:1px solid #dbe3ef!important;
                border-radius:16px!important;background:#fff!important;color:#0f172a!important;
                padding:14px 16px!important;text-align:left!important;white-space:normal!important;
                box-shadow:0 8px 24px rgba(15,23,42,.035)!important;transition:all .15s ease
              }
              .st-key-approved_simple_workspace_kpis button:hover{
                border-color:#93c5fd!important;background:#f8fbff!important;color:#0f172a!important
              }
              .st-key-approved_simple_workspace_kpis button[kind="primary"]{
                border-color:#60a5fa!important;background:#eff6ff!important;color:#0f172a!important
              }
              .st-key-approved_simple_workspace_kpis button p{
                margin:0!important;white-space:normal!important;line-height:1.25!important
              }
              .st-key-approved_simple_workspace_kpis button p:first-child{
                color:#64748b!important;font-size:11px!important;font-weight:800!important
              }
              .st-key-approved_simple_workspace_kpis button p:last-child{
                color:#0f172a!important;font-size:25px!important;font-weight:900!important;
                letter-spacing:-.035em!important;margin-top:7px!important
              }
              .st-key-approved_workspace_kpi_detail{
                border:1px solid #dbe3ef;border-radius:16px;background:#fff;
                padding:16px;margin:12px 0 18px;box-shadow:0 8px 24px rgba(15,23,42,.035)
              }
              .cv-ap-risk-disclosure summary{
                cursor:pointer;display:inline-flex;align-items:center;gap:8px;list-style:none;
                color:#1d4ed8;font-size:12px;font-weight:800;white-space:nowrap
              }
              .cv-ap-risk-disclosure summary::-webkit-details-marker{display:none}
              .cv-ap-risk-disclosure summary::after{content:"⌄";font-size:14px;color:#64748b}
              .cv-ap-risk-disclosure[open] summary::after{content:"⌃"}
              .cv-ap-risk-disclosure ul{margin:8px 0 2px;padding:0 0 0 16px;min-width:190px}
              .cv-ap-risk-disclosure li{margin:5px 0;color:#334155;font-size:11px;line-height:1.4}
              .cv-ap-risk-zero{
                display:inline-flex;align-items:center;justify-content:center;min-width:27px;
                border:1px solid #bbf7d0;border-radius:999px;background:#ecfdf5;color:#047857;
                font-size:12px;font-weight:850;padding:3px 8px
              }
              .cv-ap-risk-missing{max-width:220px;color:#64748b;font-size:11px;line-height:1.4;white-space:normal}
            </style>
            """,
            unsafe_allow_html=True,
        )
        selected_key = "approved_workspace_kpi_detail_selection"
        selected_label = str(st.session_state.get(selected_key) or "")
        with st.container(key="approved_simple_workspace_kpis"):
            card_columns = st.columns(len(kpis), gap="small")
            for index, (label, value) in enumerate(kpis):
                with card_columns[index]:
                    active = selected_label == label
                    if st.button(
                        f"**{label}**  \n\n{value}",
                        key=f"approved_simple_workspace_kpi_{index}",
                        type="primary" if active else "secondary",
                        use_container_width=True,
                        help=f"Show the records behind {label.lower()}",
                    ):
                        st.session_state[selected_key] = "" if active else label

        selected_label = str(st.session_state.get(selected_key) or "")
        detail = kpi_details.get(selected_label)
        if detail is not None:
            with st.container(key="approved_workspace_kpi_detail"):
                title_col, close_col = st.columns([5, 1], vertical_alignment="center")
                with title_col:
                    st.markdown(
                        f"<h3>{_esc(selected_label)}</h3><p>{_esc(str(detail.get('description') or 'Related saved records.'))}</p>",
                        unsafe_allow_html=True,
                    )
                with close_col:
                    if st.button("Close", key="approved_workspace_kpi_detail_close", type="secondary"):
                        st.session_state.pop(selected_key, None)
                        st.rerun()
                rows = list(detail.get("rows") or [])
                total = len(rows)
                visible_rows = rows[:200]
                if visible_rows:
                    import pandas as pd

                    columns_in_order = list(detail.get("headers") or [])
                    frame = pd.DataFrame(visible_rows)
                    if columns_in_order:
                        frame = frame.reindex(columns=columns_in_order)
                    st.dataframe(
                        frame,
                        hide_index=True,
                        use_container_width=True,
                        height=min(460, max(200, 42 + min(len(frame), 10) * 35)),
                    )
                    if total > len(visible_rows):
                        st.caption(f"Showing the first {len(visible_rows)} of {total:,} records.")
                else:
                    st.info(str(detail.get("empty_message") or "No matching records are available."))
        st.markdown(
            f"""
            <div class="cv-ap">
              {lead_html}
              {charts}
              <section class="cv-ap-card"><table class="cv-ap-table"><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></section>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="cv-ap">
              {lead_html}
              <section class="cv-ap-kpis {columns}">{kpi_html}</section>
              {charts}
              <section class="cv-ap-card"><table class="cv-ap-table"><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></section>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if legacy_page and st.button(legacy_label, key=f"approved_legacy_{legacy_page}"):
        _open_legacy(legacy_page)
        st.rerun()
    end_approved_page()

def part_photo(
    url: Any = "",
    size: int = 72,
    part: dict[str, Any] | None = None,
    part_number: str = "",
) -> str:
    """Supplier photo, or a category illustration labeled as artwork."""
    from src.part_images import part_image_markup

    number = part_number or str(
        _first(
            part or {},
            "mpn",
            "MPN",
            "manufacturer_part_number",
            "part_number",
            "component",
            fallback="",
        )
        or ""
    )
    return part_image_markup(url, number, size=size, part=part)



def render_bom_component_table(records: Any) -> None:
    """Render BOM risk results as a compact, image-led component register."""
    if hasattr(records, "to_dict"):
        rows = records.to_dict("records")
    else:
        rows = list(records or [])
    if not rows:
        st.info("No components match the selected filters.")
        return

    def value(row: dict[str, Any], *keys: str, default: str = "Not recorded") -> str:
        for key in keys:
            raw = row.get(key)
            if raw is None:
                continue
            text = str(raw).strip()
            if text.casefold() not in {"", "nan", "none", "<na>"}:
                return text
        return default

    def count_label(raw: str) -> str:
        try:
            return f"{int(float(raw)):,}"
        except (TypeError, ValueError, OverflowError):
            return "Not recorded"

    body = []
    for row in rows:
        mpn = value(row, "MPN", "mpn", "part_number", "component")
        maker = value(row, "Manufacturer", "manufacturer", default="")
        image_url = value(
            row,
            "Photo", "image_url", "product_image_url", "primary_image_url",
            "supplier_image_url", "photo_url", "PhotoUrl", "photoUrl",
            "ImageURL", "ImageUrl", "PrimaryPhoto", default="",
        )
        photo = part_photo(image_url, size=64, part=row, part_number=mpn)
        stock = count_label(value(row, "Stock Available", "stock_available", default=""))
        supplier_count = count_label(value(row, "Supplier Count", "supplier_count", default=""))
        lifecycle = value(row, "Lifecycle Status", "lifecycle_status")
        risk = value(row, "Risk Level", "risk_level")
        folded_risk = risk.casefold()
        risk_tone = "high" if "high" in folded_risk else (
            "low" if "low" in folded_risk else ("medium" if "medium" in folded_risk else "unknown")
        )
        score = value(row, "Risk Score", "risk_score")
        source = value(row, "Best Source", "best_source", "preferred_supplier")
        maker_html = f"<span>{html.escape(maker)}</span>" if maker else ""
        body.append(
            "<tr>"
            f"<td><div class='cv-bom-component'>{photo}<div class='cv-bom-component-copy'>"
            f"<strong>{html.escape(mpn)}</strong>{maker_html}</div></div></td>"
            f"<td><strong>{html.escape(stock)}</strong><span>{html.escape(supplier_count)} suppliers</span></td>"
            f"<td>{html.escape(lifecycle)}</td>"
            f"<td><div class='cv-bom-risk-cell'><strong>{html.escape(score)}</strong>"
            f"<span class='cv-bom-risk cv-bom-risk--{risk_tone}'>{html.escape(risk)}</span></div></td>"
            f"<td>{html.escape(source)}</td>"
            "</tr>"
        )

    st.markdown(
        """
        <style>
          .cv-bom-results-scroll{width:100%;overflow-x:auto;border:1px solid #e2e8f0;border-radius:14px;background:#fff}
          .cv-bom-results{width:100%;min-width:760px;border-collapse:separate;border-spacing:0;table-layout:fixed}
          .cv-bom-results th{padding:12px 14px;text-align:left;background:#f8fafc;color:#475569;font-size:11px;font-weight:750;letter-spacing:.045em;text-transform:uppercase;border-bottom:1px solid #e2e8f0}
          .cv-bom-results td{padding:10px 14px;vertical-align:middle;border-bottom:1px solid #edf2f7;color:#334155;font-size:13px;line-height:1.35;overflow-wrap:anywhere}
          .cv-bom-results tr:last-child td{border-bottom:0}
          .cv-bom-results th:first-child{width:34%}.cv-bom-results th:nth-child(2){width:19%}.cv-bom-results th:nth-child(3){width:17%}.cv-bom-results th:nth-child(4){width:15%}.cv-bom-results th:nth-child(5){width:15%}
          .cv-bom-component{display:flex;align-items:center;gap:12px;min-height:64px}
          .cv-bom-component .cv-part-photo{display:inline-flex;flex:0 0 auto;width:var(--cv-part-photo-size);height:var(--cv-part-photo-size);align-items:center;justify-content:center;overflow:hidden;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc;color:#64748b}
          .cv-bom-component .cv-part-photo img{width:100%;height:100%;object-fit:contain;display:block}
          .cv-bom-component .cv-part-photo__placeholder svg{width:28px;height:28px}
          .cv-bom-component-copy{display:flex;min-width:0;flex-direction:column;gap:3px}.cv-bom-component-copy strong{color:#0f172a;font-size:13px;line-height:1.3;overflow-wrap:anywhere}.cv-bom-component-copy span,.cv-bom-results td>span{color:#64748b;font-size:11px}
          .cv-bom-risk-cell{display:flex;flex-direction:column;align-items:flex-start;gap:5px}.cv-bom-risk-cell strong{color:#0f172a;font-variant-numeric:tabular-nums}
          .cv-bom-risk{display:inline-flex;align-items:center;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:700;white-space:nowrap}
          .cv-bom-risk--high{background:#fff1f2;color:#be123c}.cv-bom-risk--medium{background:#fffbeb;color:#b45309}.cv-bom-risk--low{background:#ecfdf5;color:#047857}.cv-bom-risk--unknown{background:#f1f5f9;color:#475569}
          @media(max-width:820px){.cv-bom-results{min-width:700px}.cv-bom-results th,.cv-bom-results td{padding-left:10px;padding-right:10px}}
        </style>
        <div class="cv-bom-results-scroll" role="region" aria-label="BOM component register" tabindex="0">
          <table class="cv-bom-results"><thead><tr><th>Component</th><th>Stock / suppliers</th><th>Lifecycle</th><th>Risk</th><th>Preferred source</th></tr></thead>
          <tbody>__ROWS__</tbody></table>
        </div>
        """.replace("__ROWS__", "".join(body)),
        unsafe_allow_html=True,
    )

def part_thumbnail(seed: str = "", url: str = "") -> str:
    return part_photo(url)


def _prior_delta(rows: list[dict[str, Any]], *prior_keys: str) -> str:
    values = []
    for row in rows:
        raw = _first(row, *prior_keys, fallback=None)
        if raw is None:
            continue
        values.append(_num(raw))
    if not values:
        return "<em class='muted'>Not recorded</em>"
    return f"<em>{sum(values)}</em>"


def _home_weekly_delta(
    rows: list[dict[str, Any]],
    metric: str,
    *,
    now: datetime | None = None,
) -> str:
    """Compare live BOM records from the latest 7 days with the 7 days before."""
    point = now or datetime.now(timezone.utc)
    if point.tzinfo is None:
        point = point.replace(tzinfo=timezone.utc)
    point = point.astimezone(timezone.utc)
    current_start = point - timedelta(days=7)
    previous_start = point - timedelta(days=14)
    current_rows: list[dict[str, Any]] = []
    previous_rows: list[dict[str, Any]] = []

    for row in rows:
        recorded_at = _parse_timestamp(_first(row, "created_at", fallback=None))
        if recorded_at is None:
            continue
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        recorded_at = recorded_at.astimezone(timezone.utc)
        if current_start <= recorded_at < point:
            current_rows.append(row)
        elif previous_start <= recorded_at < current_start:
            previous_rows.append(row)

    if not current_rows and not previous_rows:
        if metric == "saved_boms":
            return (
                "<em class='muted' title='No BOMs were analyzed in the last 14 days.'>"
                "No new BOMs in the past 14 days</em>"
            )
        if metric == "average_health":
            if rows:
                return (
                    f"<em class='muted' title='Portfolio health averaged across all saved BOMs; "
                    f"no two recent weekly groups are available.'>Across {len(rows)} saved BOMs</em>"
                )
            return "<em class='muted'>No saved BOMs to compare</em>"
        return (
            "<em class='muted' title='No BOMs were analyzed in the last 14 days.'>"
            "No recent analyses to compare</em>"
        )

    if metric == "saved_boms":
        current_value = len(current_rows)
        previous_value = len(previous_rows)
        detail = "BOMs analyzed in the latest 7 days compared with the 7 days before"
        higher_is_better = True
    elif metric == "needs_review":
        current_value = sum(
            1
            for row in current_rows
            if _num(_first(row, "high_risk_count")) > 0
            or _num(_first(row, "health_score"), 100) < 80
        )
        previous_value = sum(
            1
            for row in previous_rows
            if _num(_first(row, "high_risk_count")) > 0
            or _num(_first(row, "health_score"), 100) < 80
        )
        detail = "BOMs needing review in the latest 7 days compared with the 7 days before"
        higher_is_better = False
    elif metric == "high_risk_parts":
        current_value = sum(_num(_first(row, "high_risk_count")) for row in current_rows)
        previous_value = sum(_num(_first(row, "high_risk_count")) for row in previous_rows)
        detail = "High-risk parts in BOMs analyzed in the latest 7 days compared with the 7 days before"
        higher_is_better = False
    elif metric == "average_health":
        current_scores = [
            _num(_first(row, "health_score"))
            for row in current_rows
            if _first(row, "health_score", fallback=None) is not None
        ]
        previous_scores = [
            _num(_first(row, "health_score"))
            for row in previous_rows
            if _first(row, "health_score", fallback=None) is not None
        ]
        if not current_scores or not previous_scores:
            return (
                f"<em class='muted' title='No health scores are available in both weekly groups.'>"
                f"Across {len(rows)} saved BOMs</em>"
            )
        current_value = round(sum(current_scores) / len(current_scores))
        previous_value = round(sum(previous_scores) / len(previous_scores))
        detail = "Average health for BOMs analyzed in the latest 7 days compared with the 7 days before"
        higher_is_better = True
    else:
        return "<em class='muted'>Trend unavailable</em>"

    delta = current_value - previous_value
    if delta == 0:
        return f"<em class='muted' title='{detail}'>→ 0 from last week</em>"

    favorable = (delta > 0) == higher_is_better
    tone = "" if favorable else "down"
    arrow = "↗" if delta > 0 else "↘"
    signed = f"+{delta}" if delta > 0 else f"−{abs(delta)}"
    return f"<em class='{tone}' title='{detail}'>{arrow} {signed} from last week</em>"


def spark_slots(values: list[float | None], color: str = "#2563eb") -> str:
    """Six-bucket spark bar chart. Empty periods remain blank instead of implying zero data."""
    buckets = 6
    slots = list(values[:buckets])
    while len(slots) < buckets:
        slots.append(None)
    recorded = [value for value in slots if value is not None]
    peak = max(recorded) if recorded else 1.0
    marks = [
        '<line x1="4" y1="50" x2="108" y2="50" stroke="#edf1f6" stroke-width="1"/>',
    ]
    for index, value in enumerate(slots):
        x = 7 + index * 17
        if value is None:
            continue
        height = max(10.0, 39.0 * (float(value) / (peak or 1.0)))
        marks.append(
            f'<rect x="{x:.1f}" y="{50 - height:.1f}" width="8" height="{height:.1f}" rx="2" fill="{color}" opacity=".62"/>'
        )
    return (
        f'<svg class="cv-ap-spark" viewBox="0 0 116 56" width="116" height="56" aria-hidden="true">{"".join(marks)}</svg>'
    )


ICO_DOC = '<svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="1.8"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/></svg>'
ICO_WARN = '<svg viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="1.8"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>'
ICO_RISK = '<svg viewBox="0 0 24 24" fill="none" stroke="#e11d48" stroke-width="1.8"><path d="M12 3l7 3v6c0 5-3 8-7 9-4-1-7-4-7-9V6z"/></svg>'
ICO_HEALTH = '<svg viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="1.8"><path d="M3 12h4l2-5 4 10 2-5h6"/></svg>'


def impact_map_html(
    *,
    part: str,
    projects: list[tuple[str, str]],
    manufacturer: str = "",
    supplier: str = "",
    supplier_count: str = "",
    lifecycle: str = "",
) -> str:
    """Node diagram of the live part, its saved BOMs, and recorded evidence."""
    nodes = []
    y = 24
    for project, bom in projects[:4]:
        nodes.append((220, y, project or "Project not recorded", "#eef2ff", "#6366f1"))
        nodes.append((460, y, bom or "BOM file not recorded", "#f5f3ff", "#7c3aed"))
        y += 64
    manufacturer_label = manufacturer or supplier
    if manufacturer_label:
        nodes.append((220, y, f"Manufacturer: {manufacturer_label}", "#ecfdf5", "#059669"))
        y += 64
    if supplier_count:
        nodes.append((220, y, f"Supplier sources: {supplier_count}", "#ecfdf5", "#059669"))
        y += 64
    if lifecycle:
        nodes.append((220, y, lifecycle, "#fff7ed", "#ea580c"))
        y += 64
    height = max(180, y + 20)
    paths = []
    boxes = [
        f'<rect x="16" y="{(height/2)-28:.0f}" width="150" height="56" rx="12" fill="#eff6ff" stroke="#2563eb"/>'
        f'<text x="28" y="{(height/2)-6:.0f}" font-size="11" fill="#64748b">Component</text>'
        f'<text x="28" y="{(height/2)+12:.0f}" font-size="13" font-weight="700" fill="#0f172a">{html.escape(part or "Component")[:22]}</text>'
    ]
    part_y = height / 2
    for index, (x, node_y, label, fill, stroke) in enumerate(nodes):
        paths.append(
            f'<path d="M166 {part_y:.0f} C 190 {part_y:.0f}, 190 {node_y+22}, {x} {node_y+22}" fill="none" stroke="{stroke}" stroke-width="2"/>'
        )
        if x > 300 and index:
            paths.append(
                f'<path d="M370 {node_y+22} H {x}" fill="none" stroke="{stroke}" stroke-width="2"/>'
            )
        boxes.append(
            f'<g><title>{html.escape(label)}</title>'
            f'<rect x="{x}" y="{node_y}" width="180" height="44" rx="10" fill="{fill}" stroke="{stroke}"/>'
            f'<text x="{x+12}" y="{node_y+27}" font-size="12" fill="#0f172a">{html.escape(label[:26])}</text></g>'
        )
    legend = "".join(
        f'<span class="cv20-map-legend__item"><i style="--legend-color:{color}"></i>{label}</span>'
        for label, color in (
            ("Project", "#2563eb"), ("BOM", "#7c3aed"),
            ("Supply chain", "#059669"), ("Lifecycle", "#ea580c"),
        )
    )
    return (
        "<section class='cv-ap-card cv20-impact-map'>"
        '<header class="cv20-impact-map__header"><div><h2>Impact map</h2>'
        f'<p>Saved-BOM usage and recorded supply evidence for {html.escape(part or "this component")}.</p>'
        f'</div><div class="cv20-map-legend" aria-label="Impact map legend">{legend}</div></header>'
        f'<svg viewBox="0 0 680 {height}" width="100%" height="{height}" role="img" aria-label="Impact map for {html.escape(part or "component", quote=True)}">'
        f'{"".join(paths)}{"".join(boxes)}</svg></section>'
    )


def procurement_header_html(
    part: dict[str, Any],
    recommendation: dict[str, Any] | None = None,
) -> str:
    """Compatibility export for the reusable procurement workspace markup."""
    from src.procurement_advisor import procurement_header_html as render_header

    return render_header(part, recommendation)


def portfolio_charts_html(parts: list[dict[str, Any]] | None) -> str:
    """Trend frame stays empty without monthly history. The donut uses live risk counts."""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    ticks = "".join(
        f'<text x="{24 + index * 46}" y="132" font-size="10" fill="#94a3b8">{label}</text>'
        for index, label in enumerate(months)
    )
    trend = (
        '<article class="cv-ap-chart"><h3>Portfolio risk trend</h3>'
        '<svg viewBox="0 0 580 148" width="100%" height="148" role="img" aria-label="Portfolio risk trend">'
        '<line x1="20" y1="16" x2="20" y2="112" stroke="#e2e8f0"/>'
        '<line x1="20" y1="112" x2="560" y2="112" stroke="#e2e8f0"/>'
        f'{ticks}</svg><p class="cv-ap-meta">Monthly history is not recorded.</p></article>'
    )
    mix = risk_mix_chart(parts) or (
        '<article class="cv-ap-chart"><h3>Risk distribution</h3><p class="cv-ap-meta">Not recorded</p></article>'
    )
    return f'<div class="cv-ap-charts">{trend}{mix}</div>'


def _dual_scale_supply_chart(
    labels: list[str],
    *,
    baseline: float,
    disrupted_values: list[float] | None,
    demand: float,
    disrupted_label: str,
    demand_label: str,
) -> str:
    """Stock stays on the left axis. Demand uses a labeled index scale so it stays visible."""
    width = 640
    slot = (width - 70) / max(len(labels) - 1, 1)
    stock_peak = max([baseline, * (disrupted_values or [baseline])]) or 1.0
    stock_peak = stock_peak * 1.15

    def stock_y(value: float) -> float:
        return 118 - (96 * (value / stock_peak))

    demand_y = 78.0
    stock_line = " ".join(f"{36 + index * slot:.1f},{stock_y(baseline):.1f}" for index in range(len(labels)))
    lines = [f'<polyline fill="none" stroke="#2563eb" stroke-width="2.5" points="{stock_line}"/>']
    if disrupted_values:
        disrupted_line = " ".join(
            f"{36 + index * slot:.1f},{stock_y(value):.1f}" for index, value in enumerate(disrupted_values)
        )
        lines.append(f'<polyline fill="none" stroke="#e11d48" stroke-width="2.5" points="{disrupted_line}"/>')
    demand_line = " ".join(f"{36 + index * slot:.1f},{demand_y:.1f}" for index in range(len(labels)))
    lines.append(
        f'<polyline fill="none" stroke="#64748b" stroke-width="2.5" stroke-dasharray="6 4" points="{demand_line}"/>'
    )
    grid = []
    for fraction, label in ((0, "0"), (0.5, _compact_units(stock_peak * 0.5)), (1, _compact_units(stock_peak))):
        y = 118 - (96 * fraction)
        grid.append(f'<line x1="36" y1="{y:.1f}" x2="610" y2="{y:.1f}" stroke="#e2e8f0"/>')
        grid.append(f'<text x="2" y="{y + 4:.1f}" font-size="10" fill="#64748b">{label}</text>')
    grid.append(f'<text x="612" y="{demand_y + 4:.1f}" font-size="10" fill="#64748b">{_compact_units(demand)}</text>')
    grid.append('<text x="36" y="14" font-size="10" fill="#64748b">Recorded stock (units)</text>')
    grid.append('<text x="430" y="14" font-size="10" fill="#64748b">Required units (index scale)</text>')
    axis = "".join(
        f'<text x="{36 + index * slot:.1f}" y="138" font-size="11" fill="#64748b">{html.escape(label)}</text>'
        for index, label in enumerate(labels)
    )
    legend = (
        '<p class="cv-ap-meta">'
        '<span style="color:#2563eb">Baseline supply (modeled)</span> · '
        f'<span style="color:#e11d48">{html.escape(disrupted_label)}</span> · '
        f'<span style="color:#64748b">{html.escape(demand_label)}</span>'
        "</p>"
    )
    return (
        '<article class="cv-ap-chart"><h3>Projected supply vs. demand</h3>'
        f'<svg viewBox="0 0 {width} 150" width="100%" height="168" role="img" aria-label="Projected supply vs. demand">'
        f'{"".join(grid)}{"".join(lines)}{axis}</svg>{legend}</article>'
    )


def _compact_units(value: float) -> str:
    number = float(value)
    if abs(number) >= 1000:
        return f"{number / 1000:.1f}k"
    if abs(number - round(number)) < 0.05:
        return str(int(round(number)))
    return f"{number:.1f}"


def modeled_supply_chart(
    *,
    baseline: float | None,
    disrupted: float | None,
    demand: float | None,
    stock_reduction_percent: int = 0,
    demand_growth_percent: int = 0,
    disrupted_label: str = "",
    assumption: str = "",
) -> str:
    """90-day scenario lines. These are modeled projections, not observed history."""
    labels = ["Day 0", "Day 15", "Day 30", "Day 45", "Day 60", "Day 75", "Day 90"]
    series = []
    if baseline is not None:
        series.append(("Baseline supply (modeled)", "#2563eb", [(label, baseline) for label in labels]))
    if disrupted is not None and baseline is not None:
        points = []
        for index, label in enumerate(labels):
            points.append((label, baseline if index < 3 else disrupted))
        series.append((disrupted_label or f"Disrupted supply (modeled, {stock_reduction_percent}% stock cut)", "#e11d48", points))
    if demand is not None:
        series.append(
            (
                "Demand forecast (modeled, required units held flat)" if demand_growth_percent == 0 else f"Demand forecast (modeled, {demand_growth_percent}% growth)",
                "#64748b",
                [(label, demand) for label in labels],
            )
        )
    if demand is not None and baseline is not None:
        disrupted_values = [baseline if index < 3 else disrupted for index in range(len(labels))]
        chart = _dual_scale_supply_chart(
            labels,
            baseline=baseline,
            disrupted_values=disrupted_values if disrupted is not None else None,
            demand=demand,
            disrupted_label=disrupted_label or "Disrupted supply (modeled)",
            demand_label="Demand forecast (modeled, required units)",
        )
    else:
        chart = series_chart("Projected supply vs. demand", series)
    detail = assumption or (
        "Baseline holds recorded stock flat for 90 days. "
        f"Disrupted supply applies the {stock_reduction_percent}% stock-reduction slider after day 45. "
        f"Demand holds required units flat, including the {demand_growth_percent}% demand-growth slider."
    )
    note = (
        "<p class='cv-ap-meta'>Modeled scenario, not observed history. "
        f"{detail} Demand is plotted on a labeled index scale so required units stay visible beside recorded stock. "
        "The quantities themselves are unchanged. Days without a recorded input stay off the line.</p>"
    )
    return chart + note


def supply_scenario_chart(parts: list[dict[str, Any]] | None, scenario: dict[str, Any] | None, choice: str) -> str:
    """90-day lines for the reference scenario control. Disruption uses recorded supplier counts."""
    baseline_total = 0.0
    disrupted_total = 0.0
    have_stock = False
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        raw = part.get("stock_available")
        if raw is None or str(raw).strip() == "":
            continue
        try:
            stock = float(raw)
        except (TypeError, ValueError):
            continue
        have_stock = True
        baseline_total += stock
        count = None
        suppliers = part.get("supplier_count")
        try:
            if suppliers not in (None, ""):
                count = int(float(suppliers))
        except (TypeError, ValueError):
            count = None
        if choice == "Primary supplier disruption" and count and count > 0:
            disrupted_total += stock * max(count - 1, 0) / count
        else:
            disrupted_total += stock
    demand = None
    rows = (scenario or {}).get("rows") or []
    if rows:
        try:
            demand = sum(float(row.get("Required Units") or 0) for row in rows if isinstance(row, dict))
        except (TypeError, ValueError):
            demand = None
    if choice == "Primary supplier disruption":
        assumption = (
            "Primary supplier disruption, 90-day horizon. "
            "After day 45, each part with a recorded supplier count loses one supplier's even share of recorded stock. "
            "Parts without a supplier count keep recorded stock. Demand is required units, held flat."
        )
        disrupted_label = "Disrupted supply (modeled, one supplier share removed)"
    else:
        assumption = "No disruption selected. Disrupted supply matches recorded stock across the 90-day horizon. Demand is required units, held flat."
        disrupted_label = "Disrupted supply (modeled, no disruption)"
    return modeled_supply_chart(
        baseline=baseline_total if have_stock else None,
        disrupted=disrupted_total if have_stock else None,
        demand=demand,
        disrupted_label=disrupted_label,
        assumption=assumption,
    )


def excel_bytes(rows: list[dict[str, Any]]) -> bytes:
    import pandas as pd

    frame = pd.DataFrame(rows)
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False)
    return buffer.getvalue()


def _navigate_back_to_bom_review(context: dict[str, Any]) -> bool:
    """Restore the BOM report that launched the current replacement search."""
    analysis_id = str(context.get("analysis_id") or "").strip()
    if not analysis_id:
        return False

    from src.ui.navigation import navigate_to

    source_page = str(context.get("source_page") or "")
    st.session_state["cadivor_active_analysis_id"] = analysis_id
    st.session_state["analysis_id"] = analysis_id
    st.session_state["cadivor_pending_analysis_section"] = "Engineering Intelligence"
    st.session_state["cadivor_pending_analysis_section_id"] = analysis_id
    if source_page == "engineering_intelligence_review":
        st.session_state["cadivor_show_detailed_risk"] = False
        st.session_state["cadivor_ei_report_tab"] = "BOM Risk"
    elif source_page == "detailed_risk_report":
        st.session_state["cadivor_show_detailed_risk"] = True
        source_mpn = str(context.get("mpn") or context.get("original_part") or "").strip()
        if source_mpn:
            st.session_state[f"cadivor_detailed_risk_mpn_{analysis_id}"] = source_mpn

    navigate_to(
        "Analysis Details",
        analysis_id=analysis_id,
        analysis_tab="Engineering Intelligence",
        _rerun=False,
        arm_opening=False,
    )
    return True


def _datasheet_url(part: dict[str, Any] | None) -> str:
    part = part if isinstance(part, dict) else {}
    for key in ("datasheet_url", "Datasheet URL", "datasheetUrl", "Data Sheet URL"):
        url = _candidate_http_url(part.get(key))
        if url:
            return url
    discovery = part.get("_discovery_row")
    if isinstance(discovery, dict):
        for key in ("datasheet_url", "Datasheet URL", "datasheetUrl", "Data Sheet URL"):
            url = _candidate_http_url(discovery.get(key))
            if url:
                return url
    return ""


def _datasheet_source_urls(part: dict[str, Any] | None) -> list[str]:
    """Return datasheet and exact-part product links in retrieval priority order."""
    part = part if isinstance(part, dict) else {}
    discovery = part.get("_discovery_row")
    discovery = discovery if isinstance(discovery, dict) else {}
    datasheet_keys = ("datasheet_url", "Datasheet URL", "datasheetUrl", "Data Sheet URL")
    product_keys = (
        "product_detail_url", "Product URL", "product_url", "product_page_url",
        "source_url", "Source URL", "supplier_url",
    )
    datasheet_urls: list[str] = []
    product_urls: list[str] = []
    for mapping in (part, discovery):
        for key in datasheet_keys:
            value = _candidate_http_url(mapping.get(key))
            if value and value not in datasheet_urls:
                datasheet_urls.append(value)
        for key in product_keys:
            value = _candidate_http_url(mapping.get(key))
            if value and value not in product_urls:
                product_urls.append(value)
    urls: list[str] = []
    for value in (datasheet_urls[:1] + product_urls[:1] + datasheet_urls[1:2] + product_urls[1:2]):
        if value and value not in urls:
            urls.append(value)
    return urls[:4]


def _datasheet_evidence_key(
    source_mpn: str,
    candidate_mpn: str,
    source_url: str,
    candidate_url: str,
    source_upload_fingerprint: str = "",
    candidate_upload_fingerprint: str = "",
) -> str:
    material = "|".join(
        value.strip().casefold()
        for value in (
            source_mpn,
            candidate_mpn,
            source_url,
            candidate_url,
            source_upload_fingerprint,
            candidate_upload_fingerprint,
        )
    )
    return "cadivor_alt_datasheet_review_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _request_datasheet_review(session_state_key: str) -> None:
    """Queue PDF extraction from the approval panel's direct review action."""
    st.session_state[session_state_key] = True


def _render_datasheet_evidence_review(
    *,
    original: dict[str, Any],
    candidate: dict[str, Any],
    source_mpn: str,
    candidate_mpn: str,
    key_suffix: str,
) -> dict[str, Any]:
    """Automatically analyze linked manufacturer PDFs and collect reviewer citations."""
    source_url = _datasheet_url(original)
    candidate_url = _datasheet_url(candidate)
    source_url_candidates = _datasheet_source_urls(original)
    candidate_url_candidates = _datasheet_source_urls(candidate)
    source_upload = None
    candidate_upload = None
    source_upload_bytes = b""
    candidate_upload_bytes = b""
    source_upload_fingerprint = ""
    candidate_upload_fingerprint = ""
    uploaded_source = None
    uploaded_candidate = None
    review_key = _datasheet_evidence_key(
        source_mpn,
        candidate_mpn,
        " | ".join(source_url_candidates),
        " | ".join(candidate_url_candidates),
    )
    review_request_key = f"cadivor_alt_datasheet_review_request_{key_suffix}"
    with st.expander("Datasheet & documentation review", expanded=True):
        st.caption(
            "Cadivor automatically retrieves and analyzes available supplier/manufacturer PDFs, then shows page-cited findings. Review the linked documents and package drawings before approving; an upload is only a fallback when no working link is available."
        )
        link_cols = st.columns(2)
        for column, label, url in (
            (
                link_cols[0],
                "Open source datasheet" if source_url else "Open source supplier page",
                source_url or (source_url_candidates[0] if source_url_candidates else ""),
            ),
            (
                link_cols[1],
                "Open candidate datasheet" if candidate_url else "Open candidate supplier page",
                candidate_url or (candidate_url_candidates[0] if candidate_url_candidates else ""),
            ),
        ):
            with column:
                if url:
                    st.link_button(label, url, use_container_width=True)
                else:
                    st.caption(label.replace("Open ", "") + " not supplied by the catalog.")

        product_link_cols = st.columns(2)
        for column, label, candidates, datasheet_link in (
            (product_link_cols[0], "Open exact source product page", source_url_candidates, source_url),
            (product_link_cols[1], "Open exact candidate product page", candidate_url_candidates, candidate_url),
        ):
            primary_link = datasheet_link or next(iter(candidates), "")
            product_url = next((item for item in candidates if item and item != primary_link), "")
            if product_url:
                column.link_button(label, product_url, use_container_width=True)

        with st.expander("Optional: upload or replace a datasheet", expanded=False):
            st.caption(
                "You do not need to upload a file when Cadivor has a working supplier/manufacturer PDF link. Use this only when a link is missing, outdated, or points to the wrong document."
            )
            upload_cols = st.columns(2)
            with upload_cols[0]:
                uploaded_source = st.file_uploader(
                    "Optional source PDF",
                    type=["pdf"],
                    key=f"cadivor_alt_source_pdf_{key_suffix}",
                    help="Fallback for a missing or outdated source datasheet link.",
                )
            with upload_cols[1]:
                uploaded_candidate = st.file_uploader(
                    "Optional candidate PDF",
                    type=["pdf"],
                    key=f"cadivor_alt_candidate_pdf_{key_suffix}",
                    help="Fallback for a missing or outdated candidate datasheet link.",
                )

        source_upload_bytes = uploaded_source.getvalue() if uploaded_source is not None else b""
        candidate_upload_bytes = uploaded_candidate.getvalue() if uploaded_candidate is not None else b""
        if uploaded_source is not None:
            st.download_button(
                "Download source PDF to inspect drawings",
                data=source_upload_bytes,
                file_name=str(getattr(uploaded_source, "name", "source-datasheet.pdf") or "source-datasheet.pdf"),
                mime="application/pdf",
                key=f"cadivor_alt_source_pdf_download_{key_suffix}",
            )
        if uploaded_candidate is not None:
            st.download_button(
                "Download candidate PDF to inspect drawings",
                data=candidate_upload_bytes,
                file_name=str(getattr(uploaded_candidate, "name", "candidate-datasheet.pdf") or "candidate-datasheet.pdf"),
                mime="application/pdf",
                key=f"cadivor_alt_candidate_pdf_download_{key_suffix}",
            )
        source_upload_fingerprint = hashlib.sha256(source_upload_bytes).hexdigest()[:16] if source_upload_bytes else ""
        candidate_upload_fingerprint = hashlib.sha256(candidate_upload_bytes).hexdigest()[:16] if candidate_upload_bytes else ""
        review_key = _datasheet_evidence_key(
            source_mpn,
            candidate_mpn,
            " | ".join(source_url_candidates),
            " | ".join(candidate_url_candidates),
            source_upload_fingerprint,
            candidate_upload_fingerprint,
        )
        review_state = st.session_state.get(review_key)
        if not isinstance(review_state, dict):
            review_state = {}
        has_documents = bool(
            source_url_candidates or candidate_url_candidates or source_upload_bytes or candidate_upload_bytes
        )
        if not has_documents:
            st.info(
                "No supplier datasheet or exact-part product link was returned. Cadivor cannot retrieve an unlinked document; use the optional PDF fallback or cite the controlled documents you reviewed."
            )

        review_state = review_state if isinstance(review_state, dict) else {}
        review_requested = bool(st.session_state.pop(review_request_key, False))
        review_clicked = False
        if has_documents and review_state.get("review_completed"):
            review_clicked = st.button(
                "Refresh datasheet analysis",
                key=f"cadivor_alt_datasheet_extract_{key_suffix}",
                type="secondary",
                help="Re-fetch linked PDFs and refresh page-cited text. You must still inspect package drawings and pinout yourself.",
            )
        auto_review_requested = bool(
            has_documents and not review_state.get("review_completed")
        )
        if has_documents and (
            auto_review_requested or review_requested or review_clicked
        ):
            from src.datasheet_comparison import (
                build_datasheet_review_evidence,
                extract_datasheet_text,
                infer_component_family,
            )
            from src.datasheet_qa import extract_uploaded_datasheet
            from concurrent.futures import ThreadPoolExecutor

            def extract_documents(
                urls: list[str], uploaded: Any, upload_bytes: bytes, side: str
            ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
                documents: list[dict[str, Any]] = []
                pages: list[dict[str, Any]] = []
                reasons: list[str] = []
                for index, document_url in enumerate(urls[:4]):
                    label = "Supplier-linked datasheet" if index == 0 else "Additional supplier/catalog link"
                    result = extract_datasheet_text(document_url)
                    result = result if isinstance(result, dict) else {}
                    readable = result.get("pages") if isinstance(result.get("pages"), list) else []
                    documents.append(
                        {
                            "name": label,
                            "url": document_url,
                            "resolved_url": str(result.get("final_url") or ""),
                            "available": bool(result.get("available")),
                            "page_count": len(readable),
                            "reason": str(result.get("reason") or ""),
                            "retrieval_path": str(result.get("retrieval_path") or ""),
                            "side": side,
                        }
                    )
                    if result.get("available"):
                        pages.extend(
                            {**page, "document": label}
                            for page in readable
                            if isinstance(page, dict)
                        )
                        break
                    if result.get("reason"):
                        reasons.append(f"{label}: {result['reason']}")
                if uploaded is not None and upload_bytes:
                    filename = str(getattr(uploaded, "name", "manufacturer-datasheet.pdf") or "manufacturer-datasheet.pdf")
                    result = extract_uploaded_datasheet(upload_bytes, filename=filename)
                    result = result if isinstance(result, dict) else {}
                    readable = result.get("pages") if isinstance(result.get("pages"), list) else []
                    documents.append(
                        {
                            "name": filename,
                            "url": "",
                            "resolved_url": "",
                            "available": bool(result.get("available")),
                            "page_count": len(readable),
                            "reason": str(result.get("reason") or ""),
                            "side": side,
                        }
                    )
                    for page in readable:
                        if isinstance(page, dict):
                            pages.append({**page, "document": filename})
                    if result.get("reason"):
                        reasons.append(f"{filename}: {result['reason']}")
                combined = {
                    "available": bool(pages),
                    "reason": "; ".join(reasons) if not pages else "",
                    "pages": pages,
                    "page_count": len(pages),
                }
                return combined, documents

            with st.spinner("Cadivor is fetching linked datasheets and extracting page-cited evidence…"):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    source_future = pool.submit(
                        extract_documents,
                        source_url_candidates,
                        uploaded_source,
                        source_upload_bytes,
                        "Source",
                    )
                    candidate_future = pool.submit(
                        extract_documents,
                        candidate_url_candidates,
                        uploaded_candidate,
                        candidate_upload_bytes,
                        "Candidate",
                    )
                    source_pdf, source_documents = source_future.result()
                    candidate_pdf, candidate_documents = candidate_future.result()
            evidence = build_datasheet_review_evidence(
                source_pdf,
                candidate_pdf,
                infer_component_family(original or candidate),
            )
            evidence.update(
                {
                    "source_url": source_url,
                    "candidate_url": candidate_url,
                    "source_documents": source_documents,
                    "candidate_documents": candidate_documents,
                    "source_upload_fingerprint": source_upload_fingerprint,
                    "candidate_upload_fingerprint": candidate_upload_fingerprint,
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "source_pdf": source_pdf,
                    "candidate_pdf": candidate_pdf,
                    "review_completed": True,
                }
            )
            st.session_state[review_key] = evidence
            review_state = evidence

        if review_state:
            document_status_cards: list[str] = []
            has_extractable_text = False
            for label, side_key, docs_key in (
                ("Source", "source_pdf", "source_documents"),
                ("Candidate", "candidate_pdf", "candidate_documents"),
            ):
                documents = [
                    item for item in review_state.get(docs_key) or [] if isinstance(item, dict)
                ]
                if documents:
                    for document in documents:
                        name = str(document.get("name") or "PDF")
                        readable = bool(document.get("available"))
                        has_extractable_text = has_extractable_text or readable
                        page_count = int(document.get("page_count") or 0)
                        reason = str(
                            document.get("reason")
                            or "Open the linked PDF and review its package drawings directly."
                        )
                        detail = (
                            f"Readable text extracted from {page_count} PDF page(s)."
                            if readable
                            else reason
                        )
                        status_class = "" if readable else " limited"
                        badge = "TEXT EXTRACTED" if readable else "MANUAL REVIEW"
                        icon = "✓" if readable else "!"
                        document_status_cards.append(
                            f"<article class='cv-ap-doc-status{status_class}'>"
                            f"<span class='cv-ap-doc-status__icon'>{icon}</span>"
                            f"<div class='cv-ap-doc-status__copy'><strong>{_esc(label)} · {_esc(name)}</strong>"
                            f"<p>{_esc(detail)}</p></div>"
                            f"<span class='cv-ap-doc-status__badge'>{badge}</span></article>"
                        )
                else:
                    document = review_state.get(side_key) or {}
                    readable = bool(document.get("available"))
                    page_count = len(document.get("pages") or [])
                    has_extractable_text = has_extractable_text or readable
                    detail = (
                        f"Readable text extracted from {page_count} PDF page(s)."
                        if readable
                        else "No readable PDF text was extracted. Open the linked PDF and review its drawings directly."
                    )
                    document_status_cards.append(
                        f"<article class='cv-ap-doc-status{' ' if readable else ' limited'}'>"
                        f"<span class='cv-ap-doc-status__icon'>{'✓' if readable else '!'}</span>"
                        f"<div class='cv-ap-doc-status__copy'><strong>{_esc(label)} datasheet</strong>"
                        f"<p>{_esc(detail)}</p></div>"
                        f"<span class='cv-ap-doc-status__badge'>{'TEXT EXTRACTED' if readable else 'MANUAL REVIEW'}</span></article>"
                    )

            if document_status_cards:
                st.markdown(
                    "<div class='cv-ap-datasheet-statuses'>"
                    + "".join(document_status_cards)
                    + "</div>",
                    unsafe_allow_html=True,
                )
            resolved_pdf_links = []
            for label, docs_key in (("Source PDF analyzed", "source_documents"), ("Candidate PDF analyzed", "candidate_documents")):
                resolved_url = next(
                    (
                        str(item.get("resolved_url") or "").strip()
                        for item in review_state.get(docs_key) or []
                        if isinstance(item, dict) and item.get("resolved_url")
                    ),
                    "",
                )
                if resolved_url:
                    resolved_pdf_links.append((label, resolved_url))
            if resolved_pdf_links:
                resolved_cols = st.columns(2)
                for index, (label, url) in enumerate(resolved_pdf_links[:2]):
                    resolved_cols[index].link_button(label, url, use_container_width=True)

            fields = review_state.get("field_evidence") or []
            if fields and has_extractable_text:
                rows_html = []
                for row in fields:
                    source_value = str(row.get("Original PDF value") or "").strip() or "Not found"
                    candidate_value = str(row.get("Candidate PDF value") or "").strip() or "Not found"
                    citation = " / ".join(
                        value
                        for value in (
                            str(row.get("Original PDF page") or "").strip(),
                            str(row.get("Candidate PDF page") or "").strip(),
                        )
                        if value and value != "Not available"
                    ) or "Not available"
                    rows_html.append(
                        "<tr>"
                        f"<td>{_esc(row.get('Attribute') or '')}</td>"
                        f"<td>{_esc(source_value)}</td>"
                        f"<td>{_esc(candidate_value)}</td>"
                        f"<td>{_esc(citation)}</td>"
                        f"<td>{_esc(row.get('Status') or 'Needs data')}</td>"
                        "</tr>"
                    )
                st.markdown(
                    "<div class='cv-ap-field-table-wrap'><table class='cv-ap-table'><thead><tr>"
                    "<th>Attribute</th><th>Source datasheet value</th><th>Candidate datasheet value</th>"
                    f"<th>Document citations</th><th>Finding</th></tr></thead><tbody>{''.join(rows_html)}"
                    "</tbody></table></div>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    "Values appear only when the extracted text contains a field-specific value. Narrative text is not used as a package, pin-count, or compatibility result."
                )
            elif fields:
                st.markdown(
                    "<div class='cv-ap-no-text'><strong>Datasheets linked; evidence needs direct review</strong>"
                    "Cadivor could not extract readable text from these PDFs, so it has no page-cited package or pin evidence to compare. "
                    "Open each datasheet above and inspect the package outline, dimensions, pin pitch, and pinout before approving.</div>",
                    unsafe_allow_html=True,
                )

            has_dimension_excerpts = False
            for label, document_key in (("Source", "source"), ("Candidate", "candidate")):
                document_evidence = review_state.get(document_key) or {}
                excerpts = document_evidence.get("dimension_evidence") or []
                if not excerpts:
                    continue
                has_dimension_excerpts = True
                with st.expander(
                    f"{label} package / dimension excerpts ({len(excerpts)})",
                    expanded=False,
                ):
                    for excerpt in excerpts:
                        doc_label = str(excerpt.get("document") or "Datasheet")
                        st.markdown(
                            f"**{_esc(doc_label)} · page {_esc(excerpt.get('page') or '?')}** · "
                            f"{_esc(excerpt.get('excerpt') or '')}"
                        )
            if has_extractable_text and not has_dimension_excerpts:
                st.caption(
                    "No text-based package or dimension excerpt was found. Drawings or scanned pages may require direct visual review."
                )
            st.caption(
                "These citations point to extracted text; they are not an automatic fit verdict. Confirm the package-outline drawing, dimensions, pin pitch, and pinout in the original manufacturer documents. Image-only pages require direct visual review."
            )

        st.markdown("**Record values verified from the cited documents**")
        st.caption(
            "Cadivor only uses these entries to fill missing catalog or comparison values. A known mismatch cannot be overridden here."
        )

        def recorded_value(part: dict[str, Any], *keys: str) -> str:
            return _part_field(part, *keys)

        source_columns = st.columns(2)
        with source_columns[0]:
            source_package = st.text_input(
                "Source package / case",
                value=recorded_value(original, "package", "Package", "Package / Case"),
                key=f"cadivor_alt_source_package_{key_suffix}",
                disabled=bool(recorded_value(original, "package", "Package", "Package / Case")),
                help="A recorded value is locked so a known mismatch cannot be edited away.",
            )
            source_pins = st.text_input(
                "Source pin count",
                value=recorded_value(original, "pin_count", "Pin Count", "Number of Pins", "pins"),
                key=f"cadivor_alt_source_pins_{key_suffix}",
                disabled=bool(recorded_value(original, "pin_count", "Pin Count", "Number of Pins", "pins")),
                help="A recorded value is locked so a known mismatch cannot be edited away.",
            )
            source_architecture = st.text_input(
                "Source processor family / ISA (if applicable)",
                value=recorded_value(original, "architecture", "Device family / architecture", "device_family", "core", "ISA"),
                key=f"cadivor_alt_source_architecture_{key_suffix}",
                disabled=bool(recorded_value(original, "architecture", "Device family / architecture", "device_family", "core", "ISA")),
                help="A recorded value is locked so a known mismatch cannot be edited away.",
            )
        with source_columns[1]:
            candidate_package = st.text_input(
                "Candidate package / case",
                value=recorded_value(candidate, "package", "Package", "Package / Case"),
                key=f"cadivor_alt_candidate_package_{key_suffix}",
                disabled=bool(recorded_value(candidate, "package", "Package", "Package / Case")),
                help="A recorded value is locked so a known mismatch cannot be edited away.",
            )
            candidate_pins = st.text_input(
                "Candidate pin count",
                value=recorded_value(candidate, "pin_count", "Pin Count", "Number of Pins", "pins"),
                key=f"cadivor_alt_candidate_pins_{key_suffix}",
                disabled=bool(recorded_value(candidate, "pin_count", "Pin Count", "Number of Pins", "pins")),
                help="A recorded value is locked so a known mismatch cannot be edited away.",
            )
            candidate_architecture = st.text_input(
                "Candidate processor family / ISA (if applicable)",
                value=recorded_value(candidate, "architecture", "Device family / architecture", "device_family", "core", "ISA"),
                key=f"cadivor_alt_candidate_architecture_{key_suffix}",
                disabled=bool(recorded_value(candidate, "architecture", "Device family / architecture", "device_family", "core", "ISA")),
                help="A recorded value is locked so a known mismatch cannot be edited away.",
            )
            extracted_candidate_lifecycle = next(
                (
                    str(row.get("Candidate PDF value") or "").strip()
                    for row in review_state.get("field_evidence") or []
                    if isinstance(row, dict) and str(row.get("Key") or "") == "lifecycle_status"
                ),
                "",
            )
            if extracted_candidate_lifecycle.casefold() in _CANDIDATE_BLANK:
                extracted_candidate_lifecycle = ""
            recorded_candidate_lifecycle = _part_field(
                candidate,
                "Lifecycle",
                "Lifecycle Status",
                "lifecycle_status",
                "lifecycle",
                "product_status",
            )
            candidate_lifecycle_default = recorded_candidate_lifecycle or extracted_candidate_lifecycle
            candidate_lifecycle = st.text_input(
                "Candidate lifecycle status",
                value=candidate_lifecycle_default,
                key=f"cadivor_alt_candidate_lifecycle_{key_suffix}",
                disabled=bool(recorded_candidate_lifecycle),
                help="Unknown lifecycle is not treated as Active. Enter the manufacturer-confirmed status and cite its document/page.",
            )

        citation_cols = st.columns(2)
        with citation_cols[0]:
            source_reference = st.text_input(
                "Source citation · document and PDF page(s)",
                placeholder=f"{source_mpn} datasheet, Rev. [revision], pp. [actual pages]",
                key=f"cadivor_alt_source_reference_{key_suffix}",
                help="Enter the manufacturer document or part number, revision if shown, and actual PDF page numbers you reviewed. “NA”, blanks, and page numbers without a document identifier do not count.",
            )
            if source_reference and not has_document_page_citation(source_reference):
                st.caption("Add the source document or part number and exact PDF page number(s); “NA” is not a valid citation.")
        with citation_cols[1]:
            candidate_reference = st.text_input(
                "Candidate citation · document and PDF page(s)",
                placeholder=f"{candidate_mpn} datasheet, Rev. [revision], pp. [actual pages]",
                key=f"cadivor_alt_candidate_reference_{key_suffix}",
                help="Enter the manufacturer document or part number, revision if shown, and actual PDF page numbers you reviewed. “NA”, blanks, and page numbers without a document identifier do not count.",
            )
            if candidate_reference and not has_document_page_citation(candidate_reference):
                st.caption("Add the candidate document or part number and exact PDF page number(s); “NA” is not a valid citation.")

    attested = bool(
        st.session_state.get(f"cadivor_alt_document_attestation_{key_suffix}", False)
    )
    review_state = dict(review_state or {})
    review_state["verified_values"] = {
        "source_package": source_package,
        "source_pin_count": source_pins,
        "source_architecture": source_architecture,
        "candidate_package": candidate_package,
        "candidate_pin_count": candidate_pins,
        "candidate_architecture": candidate_architecture,
        "candidate_lifecycle_status": candidate_lifecycle,
    }
    review_state["reviewer_attestation"] = {
        "confirmed": bool(attested),
        "source_reference": str(source_reference or "").strip(),
        "candidate_reference": str(candidate_reference or "").strip(),
        "recorded_at": datetime.now(timezone.utc).isoformat() if attested else "",
    }
    review_state["review_complete"] = bool(
        attested
        and has_document_page_citation(source_reference)
        and has_document_page_citation(candidate_reference)
    )
    review_state["review_completed"] = bool(review_state.get("review_completed"))
    review_state["datasheet_review_required"] = has_documents
    review_state["source_url"] = source_url
    review_state["candidate_url"] = candidate_url
    review_state["review_request_key"] = review_request_key
    return review_state


def _approval_evidence_for_comparison(
    original: dict[str, Any],
    candidate: dict[str, Any],
    comparison_evidence: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Fill missing approval fields from the comparison result for this BOM handoff."""
    source = dict(original or {})
    alternate = dict(candidate or {})
    conflicts: list[str] = []
    evidence = comparison_evidence if isinstance(comparison_evidence, dict) else {}
    comparison = evidence.get("comparison") if isinstance(evidence.get("comparison"), dict) else {}
    slot = str(evidence.get("slot") or "Part B")
    if slot not in {"Part B", "Part C"}:
        return source, alternate, conflicts
    card_key = "part_b" if slot == "Part B" else "part_c"
    source_card = comparison.get("part_a") if isinstance(comparison.get("part_a"), dict) else {}
    candidate_card = comparison.get(card_key) if isinstance(comparison.get(card_key), dict) else {}
    rows = comparison.get("rows") if isinstance(comparison.get("rows"), list) else []
    from src.compatibility_gate import comparison_row_part_values

    source_values = comparison_row_part_values(rows, "Part A")
    candidate_values = comparison_row_part_values(rows, slot)

    def is_missing(value: Any) -> bool:
        return str(value or "").strip().casefold() in {
            "", "—", "-", "–", "unknown", "not recorded", "not available", "n/a", "none", "nan", "0", "0.0"
        }

    def package_token(value: Any) -> tuple[str, ...]:
        import re

        return tuple(sorted(re.findall(r"[a-z]+|\d+(?:\.\d+)?", str(value or "").casefold())))

    for target, values, card, label in (
        (source, source_values, source_card, "source"),
        (alternate, candidate_values, candidate_card, "candidate"),
    ):
        for key in ("package", "pin_count", "architecture", "lifecycle_status"):
            matrix_value = values.get(key) or card.get(key)
            if is_missing(matrix_value):
                continue
            current = target.get(key)
            if not is_missing(current):
                same = (
                    package_token(current) == package_token(matrix_value)
                    if key == "package"
                    else str(current).strip().casefold() == str(matrix_value).strip().casefold()
                )
                if not same and key in {"package", "pin_count", "architecture", "lifecycle_status"}:
                    conflicts.append(
                        f"{label.title()} {key.replace('_', ' ')} evidence differs between the alternative search and comparison data."
                    )
                continue
            target[key] = matrix_value
        if label == "source":
            if is_missing(target.get("datasheet_url")) and source_card.get("datasheet_url"):
                target["datasheet_url"] = source_card.get("datasheet_url")
        else:
            if is_missing(target.get("datasheet_url")) and candidate_card.get("datasheet_url"):
                target["datasheet_url"] = candidate_card.get("datasheet_url")
            if is_missing(target.get("manufacturer_part_number")) and candidate_card.get("mpn"):
                target["manufacturer_part_number"] = candidate_card.get("mpn")
            if is_missing(target.get("description")) and candidate_card.get("description"):
                target["description"] = candidate_card.get("description")
            if is_missing(target.get("manufacturer")) and candidate_card.get("manufacturer"):
                target["manufacturer"] = candidate_card.get("manufacturer")
    return source, alternate, list(dict.fromkeys(conflicts))


def _approval_datasheet_snapshot(review: dict[str, Any] | None) -> dict[str, Any]:
    """Persist a concise evidence trail, never the full PDF text."""
    review = review if isinstance(review, dict) else {}

    def document_rows(key: str) -> list[dict[str, Any]]:
        output = []
        for item in review.get(key) or []:
            if not isinstance(item, dict):
                continue
            output.append(
                {
                    "name": str(item.get("name") or "PDF"),
                    "url": str(item.get("url") or ""),
                    "available": bool(item.get("available")),
                    "page_count": int(item.get("page_count") or 0),
                    "reason": str(item.get("reason") or "")[:240],
                }
            )
        return output[:4]

    def excerpt_rows(key: str) -> list[dict[str, Any]]:
        output = []
        side = review.get(key) if isinstance(review.get(key), dict) else {}
        for item in (side.get("dimension_evidence") or [])[:4]:
            if not isinstance(item, dict):
                continue
            output.append(
                {
                    "document": str(item.get("document") or "PDF"),
                    "page": str(item.get("page") or "?"),
                    "excerpt": str(item.get("excerpt") or "")[:200],
                }
            )
        return output

    fields = []
    for row in (review.get("field_evidence") or [])[:12]:
        if not isinstance(row, dict):
            continue
        fields.append(
            {
                "attribute": str(row.get("Attribute") or "")[:80],
                "key": str(row.get("Key") or "")[:80],
                "source_value": str(row.get("Original PDF value") or "")[:100],
                "candidate_value": str(row.get("Candidate PDF value") or "")[:100],
                "source_excerpt": str(row.get("Original PDF evidence") or "")[:180],
                "candidate_excerpt": str(row.get("Candidate PDF evidence") or "")[:180],
                "source_page": str(row.get("Original PDF page") or "")[:120],
                "candidate_page": str(row.get("Candidate PDF page") or "")[:120],
                "pages": str(row.get("Source pages") or "")[:120],
                "status": str(row.get("Status") or "Needs data")[:40],
            }
        )
    return {
        "source_url": str(review.get("source_url") or ""),
        "candidate_url": str(review.get("candidate_url") or ""),
        "source_documents": document_rows("source_documents"),
        "candidate_documents": document_rows("candidate_documents"),
        "source_dimensions": excerpt_rows("source"),
        "candidate_dimensions": excerpt_rows("candidate"),
        "field_evidence": fields,
        "document_findings": [str(value)[:240] for value in review.get("document_findings") or []][:8],
        "verified_values": dict(review.get("verified_values") or {}),
        "reviewer_attestation": dict(review.get("reviewer_attestation") or {}),
        "review_complete": bool(review.get("review_complete")),
        "review_completed": bool(review.get("review_completed")),
        "reviewed_at": str(review.get("reviewed_at") or ""),
        "interpretation": str(review.get("interpretation") or "")[:500],
    }


def _render_bom_replacement_approvals(
    *,
    source_context: Any,
    query: str,
    original: dict[str, Any],
    candidate: dict[str, Any],
    recorded_from: str = "Find a replacement",
    comparison_evidence: dict[str, Any] | None = None,
) -> None:
    """Show approval and saved-decision status inside one expanded candidate."""
    from src.approved_alternatives import (
        approved_records_for_part,
        candidate_lifecycle_is_blocked,
        candidate_lifecycle_is_approval_eligible,
        candidate_lifecycle_is_nrnd,
        part_key,
        project_decision_context_key,
    )
    from src.normalizer import normalize_part_number

    context = source_context if isinstance(source_context, dict) else {}
    source_mpn = str(context.get("mpn") or original.get("manufacturer_part_number") or "").strip()
    candidate_mpn = _candidate_mpn(candidate)
    query_key = normalize_part_number(query) or str(query or "").strip().upper()
    source_key = normalize_part_number(source_mpn) or source_mpn.upper()
    if not query_key or not source_key or query_key != source_key:
        if query_key:
            st.info(
                "To save an approval to a BOM, open Find a replacement from that BOM’s “Review alternative parts” action."
            )
        return

    analysis_id = str(
        context.get("analysis_id")
        or st.session_state.get("cadivor_active_analysis_id")
        or st.session_state.get("analysis_id")
        or ""
    ).strip()
    project_name = str(
        context.get("project_name")
        or context.get("bom_name")
        or st.session_state.get("project_name")
        or analysis_id
    ).strip()
    if not analysis_id:
        st.info(
            "This search is not linked to a saved BOM. Open Find a replacement from the BOM Risk page to record an approval."
        )
        return
    if not candidate_mpn:
        return

    auth_user = st.session_state.get("user")
    user_id = (
        auth_user.get("id")
        if isinstance(auth_user, dict)
        else getattr(auth_user, "id", "")
    ) or st.session_state.get("user_id")
    user_id = str(user_id or "").strip()
    if not user_id:
        st.warning("Sign in again before saving replacement approvals.")
        return

    candidate_key = part_key(candidate_mpn)
    widget_suffix = hashlib.sha1(
        f"{project_decision_context_key(project_name, analysis_id)}|{part_key(source_mpn)}|{candidate_key}".encode("utf-8")
    ).hexdigest()[:12]
    approval_anchor = f"cadivor-approval-checklist-{widget_suffix}"
    st.markdown(
        f"<a class='cv-approval-jump' href='#{approval_anchor}'>Skip the evidence details and go to review &amp; approval ↓</a>",
        unsafe_allow_html=True,
    )
    approval_original, approval_candidate, comparison_conflicts = _approval_evidence_for_comparison(
        original,
        candidate,
        comparison_evidence,
    )
    datasheet_review = _render_datasheet_evidence_review(
        original=approval_original,
        candidate=approval_candidate,
        source_mpn=source_mpn,
        candidate_mpn=candidate_mpn,
        key_suffix=widget_suffix,
    )
    verified_values = datasheet_review.get("verified_values") or {}

    def _missing_approval_value(value: Any) -> bool:
        return str(value or "").strip().casefold() in {
            "", "—", "-", "–", "unknown", "not recorded", "not available", "not found", "n/a", "none", "nan", "unavailable", "0", "0.0"
        }

    for target, side in ((approval_original, "source"), (approval_candidate, "candidate")):
        for field, verified_key in (
            ("package", f"{side}_package"),
            ("pin_count", f"{side}_pin_count"),
            ("architecture", f"{side}_architecture"),
        ):
            if _missing_approval_value(target.get(field)) and not _missing_approval_value(verified_values.get(verified_key)):
                target[field] = verified_values[verified_key]
                sources = dict(target.get("field_sources") or {})
                sources[field] = "Reviewer-entered value from cited manufacturer documentation"
                target["field_sources"] = sources
    if _missing_approval_value(approval_candidate.get("lifecycle_status")) and not _missing_approval_value(
        verified_values.get("candidate_lifecycle_status")
    ):
        approval_candidate["lifecycle_status"] = verified_values["candidate_lifecycle_status"]
        approval_candidate["Lifecycle"] = verified_values["candidate_lifecycle_status"]

    document_values: dict[str, dict[str, str]] = {"source": {}, "candidate": {}}
    for row in datasheet_review.get("field_evidence") or []:
        if not isinstance(row, dict):
            continue
        field = str(row.get("Key") or "")
        if field not in {"package", "pin_count", "architecture", "lifecycle_status"}:
            continue
        for side, value_key in (
            ("source", "Original PDF value"),
            ("candidate", "Candidate PDF value"),
        ):
            value = str(row.get(value_key) or "").strip()
            if not _missing_approval_value(value):
                document_values[side].setdefault(field, value)

    document_source_conflicts = []
    for target, side in ((approval_original, "source"), (approval_candidate, "candidate")):
        recorded_payload = _candidate_part_payload(target)
        for field, extracted_value in document_values[side].items():
            recorded_value = recorded_payload.get(field)
            if _missing_approval_value(recorded_value):
                target[field] = extracted_value
                if side == "candidate" and field == "lifecycle_status" and _missing_approval_value(target.get("Lifecycle")):
                    target["Lifecycle"] = extracted_value
                sources = dict(target.get("field_sources") or {})
                sources[field] = "Page-cited manufacturer PDF text"
                target["field_sources"] = sources
                continue
            probe = dict(recorded_payload)
            probe[field] = extracted_value
            discrepancy = assess_part_compatibility(recorded_payload, probe)
            mismatch = (
                package_document_conflicts(recorded_value, extracted_value)
                if field == "package"
                else discrepancy.get("pin_count_mismatch")
                if field == "pin_count"
                else discrepancy.get("architecture_mismatch")
                if field == "architecture"
                else False
            )
            if mismatch:
                document_source_conflicts.append(
                    f"The {side} catalog/comparison value for {field.replace('_', ' ')} conflicts with its manufacturer datasheet."
                )
            elif field == "lifecycle_status" and str(recorded_value or "").strip().casefold() != extracted_value.casefold():
                document_source_conflicts.append(
                    f"The {side} catalog/comparison lifecycle status conflicts with its manufacturer datasheet."
                )

    # A documented explicit lifecycle status can fill a missing supplier status;
    # it can also block a candidate when the manufacturer PDF says EOL/obsolete.
    candidate_lifecycle_evidence = next(
        (
            str(row.get("Candidate PDF value") or "").strip()
            for row in datasheet_review.get("field_evidence") or []
            if isinstance(row, dict) and str(row.get("Key") or "") == "lifecycle_status"
        ),
        "",
    )
    if _missing_approval_value(approval_candidate.get("lifecycle_status")) and candidate_lifecycle_evidence:
        approval_candidate["lifecycle_status"] = candidate_lifecycle_evidence
        if _missing_approval_value(approval_candidate.get("Lifecycle")):
            approval_candidate["Lifecycle"] = candidate_lifecycle_evidence

    compatibility = assess_part_compatibility(
        approval_original,
        _candidate_part_payload(approval_candidate),
    )
    from src.datasheet_comparison import compare_datasheet_dimension_evidence

    datasheet_conflicts = document_source_conflicts + compare_datasheet_dimension_evidence(
        (datasheet_review.get("source") or {}).get("dimension_evidence") or [],
        (datasheet_review.get("candidate") or {}).get("dimension_evidence") or [],
    )
    datasheet_conflicts = list(dict.fromkeys(datasheet_conflicts))
    datasheet_review["document_findings"] = datasheet_conflicts
    datasheet_lifecycle_blocked = candidate_lifecycle_is_blocked(
        {"lifecycle_status": candidate_lifecycle_evidence}
    ) if candidate_lifecycle_evidence else False
    compatibility_blocked = bool(
        compatibility.get("blocked_from_drop_in_approval")
        or compatibility.get("requires_acknowledgement")
        or comparison_conflicts
        or datasheet_conflicts
    )
    source_identity_verified = candidate.get("Source Identity Verified") is not False
    st.markdown(f"<div id='{approval_anchor}'></div>", unsafe_allow_html=True)
    st.markdown("#### Engineering approval")
    st.info(
        "**Approval requires all of these:** the source MPN verified against an exact distributor record; candidate lifecycle verified as Active or NRND; "
        "matching source/candidate package and pin count; compatible processor family/ISA when "
        "applicable; an actual document identifier and PDF page citation for both parts; and your "
        "review confirmation. An obsolete/EOL part or known physical/architecture mismatch cannot "
        "be approved as a direct replacement. NRND also requires a supply-continuity plan. "
        "Stock and price inform sourcing, but do not establish engineering compatibility."
    )
    st.caption(
        "Use the source and candidate citation fields above for the manufacturer document/part number and exact PDF page numbers. If Cadivor linked a datasheet, analyze it and inspect the PDF; upload is only a fallback when the link is missing or wrong."
    )
    if not source_identity_verified:
        source_identity_attested = st.checkbox(
            f"I confirmed {source_mpn} is the exact orderable part on the manufacturer document, not just a family-level match.",
            key=f"cadivor_alt_source_identity_attestation_{widget_suffix}",
        )
        source_reference = str(
            (datasheet_review.get("reviewer_attestation") or {}).get("source_reference") or ""
        ).strip()
        source_identity_verified = bool(
            source_identity_attested and has_document_page_citation(source_reference)
        )
        if source_identity_attested and not has_document_page_citation(source_reference):
            st.caption("Add the source manufacturer document and exact PDF page citation before this identity check can count.")

    attested = st.checkbox(
        "I reviewed both documents, including package dimensions, pinout, and applicable electrical or firmware requirements.",
        key=f"cadivor_alt_document_attestation_{widget_suffix}",
    )
    st.caption("This checkbox records your review. It does not approve the part by itself.")
    reviewer_attestation = dict(datasheet_review.get("reviewer_attestation") or {})
    reviewer_attestation["confirmed"] = bool(attested)
    reviewer_attestation["recorded_at"] = (
        datetime.now(timezone.utc).isoformat() if attested else ""
    )
    datasheet_review["reviewer_attestation"] = reviewer_attestation
    datasheet_review["review_complete"] = bool(
        attested
        and has_document_page_citation(reviewer_attestation.get("source_reference"))
        and has_document_page_citation(reviewer_attestation.get("candidate_reference"))
    )
    review_references_complete = bool(datasheet_review.get("review_complete"))
    linked_documents_reviewed = bool(
        not datasheet_review.get("datasheet_review_required")
        or datasheet_review.get("review_completed")
    )
    lifecycle_blocked = bool(
        candidate_lifecycle_is_blocked(approval_candidate)
        or datasheet_lifecycle_blocked
    )
    lifecycle_verified = candidate_lifecycle_is_approval_eligible(approval_candidate)
    lifecycle_nrnd = candidate_lifecycle_is_nrnd(approval_candidate)

    context_key = project_decision_context_key(project_name, analysis_id)
    try:
        from src.authenticated_runtime import load_analysis_decisions

        records: list[dict[str, Any]] = []
        for decision_context in dict.fromkeys((context_key, analysis_id)):
            records.extend(
                load_analysis_decisions(
                    user_id,
                    analysis_id=decision_context,
                    limit=500,
                )
                or []
            )
        records.extend(
            load_analysis_decisions(
                user_id,
                project_name=project_name,
                limit=500,
            )
            or []
        )
    except Exception as exc:
        st.error(f"Could not load saved approvals for this BOM: {exc}")
        return

    existing_records = [
        row
        for row in records
        if isinstance(row, dict)
        and str(row.get("decision") or "").strip().casefold() == "approved"
        and part_key(row.get("original_part")) == part_key(source_mpn)
        and part_key(row.get("alternative_part"))
        and part_key(row.get("alternative_part")) != part_key(source_mpn)
    ]
    existing = approved_records_for_part(
        existing_records,
        source_mpn,
        project_name=project_name,
        analysis_id=analysis_id,
    )
    flash = st.session_state.pop("cadivor_approved_alternatives_flash", "")
    if flash:
        st.success(str(flash))

    current = next(
        (row for row in existing if part_key(row.get("alternative_part")) == candidate_key),
        None,
    )
    approved_names = [
        str(row.get("alternative_part") or "").strip()
        for row in existing
        if str(row.get("alternative_part") or "").strip()
    ]
    if approved_names:
        st.caption(
            f"Approved for this BOM ({len(approved_names)}/3): "
            + ", ".join(approved_names)
        )
    if current:
        if compatibility_blocked:
            st.error(
                f"A saved approval for {candidate_mpn} is blocked by the current compatibility gate. "
                "Review the mismatch and remove the saved approval if it is no longer valid."
            )
        else:
            st.success(f"{candidate_mpn} is approved for {project_name}.")
        saved_note = str(current.get("engineering_note") or "").strip()
        if saved_note:
            st.caption(f"Saved review note: {saved_note}")
    st.caption(
        "This records your team’s decision; it does not certify electrical or mechanical compatibility."
    )
    st.caption(
        "Saved approvals stay with this BOM across analysis reruns and appear in its Risk and Alternatives views."
    )

    previous_note = str(current.get("engineering_note") or "") if current else ""
    note_value = st.text_area(
        "Engineering approval note (supply continuity plan required for NRND)" if lifecycle_nrnd else "Engineering approval note (optional)",
        value=previous_note,
        placeholder=(
            "Record the supply-continuity plan for this NRND part."
            if lifecycle_nrnd
            else "For example: datasheet, package, pinout, and operating range reviewed."
        ),
        height=72,
        key=f"cadivor_approved_alternative_note_{widget_suffix}",
    )
    can_approve = (
        source_identity_verified
        and not lifecycle_blocked
        and lifecycle_verified
        and (not lifecycle_nrnd or bool(str(note_value or "").strip()))
        and not compatibility_blocked
        and not compatibility.get("physical_missing")
        and not compatibility.get("architecture_missing")
        and review_references_complete
        and linked_documents_reviewed
        and (current is not None or len(approved_names) < 3)
    )
    reviewer_attestation = datasheet_review.get("reviewer_attestation") or {}
    reviewer_attestation = reviewer_attestation if isinstance(reviewer_attestation, dict) else {}
    missing_review_steps = []
    if not source_identity_verified:
        missing_review_steps.append(
            "verify the original MPN against an exact manufacturer or distributor record; current catalog results are discovery leads only"
        )
    if not has_document_page_citation(reviewer_attestation.get("source_reference")):
        missing_review_steps.append(
            "cite the source document or part number and the actual PDF page(s) reviewed (for example, “part datasheet Rev. B, pp. 8–10”; “NA” does not count)"
        )
    if not has_document_page_citation(reviewer_attestation.get("candidate_reference")):
        missing_review_steps.append(
            "cite the candidate document or part number and the actual PDF page(s) reviewed (for example, “part datasheet Rev. A, pp. 5–7”; “NA” does not count)"
        )
    if not reviewer_attestation.get("confirmed"):
        missing_review_steps.append("confirm your review in this approval section")
    if lifecycle_nrnd and not str(note_value or "").strip():
        missing_review_steps.append("record the NRND supply-continuity plan")
    if current is None and len(approved_names) >= 3:
        missing_review_steps.append("remove one approved alternative; this BOM is at the three-part limit")

    blockers: list[str] = []
    if not source_identity_verified:
        blockers.append(
            "The source MPN is not verified against an exact manufacturer or distributor record. This catalog lead can be compared for investigation, but cannot be approved yet."
        )
    if datasheet_review.get("review_completed"):
        source_document_readable = bool((datasheet_review.get("source") or {}).get("available"))
        candidate_document_readable = bool((datasheet_review.get("candidate") or {}).get("available"))
        source_manual_values_missing = bool(
            not compatibility.get("source_package")
            or not compatibility.get("source_pin_count")
            or (
                compatibility.get("architecture_meaningful")
                and not compatibility.get("source_architecture")
            )
        )
        candidate_manual_values_missing = bool(
            not compatibility.get("candidate_package")
            or not compatibility.get("candidate_pin_count")
            or (
                compatibility.get("architecture_meaningful")
                and not compatibility.get("candidate_architecture")
            )
        )
        if not source_document_readable and (
            source_manual_values_missing
            or not has_document_page_citation(reviewer_attestation.get("source_reference"))
        ):
            blockers.append(
                "Cadivor could not extract a readable source PDF. Open the official source document or use the optional PDF fallback, then enter its package, pin count, and page citation."
            )
        if not candidate_document_readable and (
            candidate_manual_values_missing
            or not has_document_page_citation(reviewer_attestation.get("candidate_reference"))
        ):
            blockers.append(
                "Cadivor could not extract a readable candidate PDF. Open the exact candidate's official document or use the optional PDF fallback, then enter its package, pin count, processor family/ISA if applicable, and page citation."
            )
    if lifecycle_blocked:
        blockers.append(
            "This candidate is obsolete, discontinued, end of life, or explicitly inactive. Choose a different candidate."
        )
    elif not lifecycle_verified:
        blockers.append(
            "Candidate lifecycle is not verified as Active or NRND. Confirm it from a manufacturer source."
        )
    if compatibility.get("blocked_from_drop_in_approval"):
        blockers.extend(compatibility.get("critical_warnings") or [
            "The physical package or processor architecture is incompatible. Choose another candidate."
        ])
    else:
        physical_blocker_start = len(blockers)
        for side, label, field_value in (
            ("source", "package / case", compatibility.get("source_package")),
            ("candidate", "package / case", compatibility.get("candidate_package")),
            ("source", "pin count", compatibility.get("source_pin_count")),
            ("candidate", "pin count", compatibility.get("candidate_pin_count")),
        ):
            if not field_value:
                blockers.append(
                    f"Enter the {side} {label} from its official document; the source and candidate values must match."
                )
        if compatibility.get("architecture_missing"):
            blockers.append(
                "Enter the source and candidate processor family/ISA from their official documents and confirm firmware compatibility."
            )
        blockers.extend(comparison_conflicts + datasheet_conflicts)
        if compatibility.get("requires_acknowledgement") and len(blockers) == physical_blocker_start:
            blockers.extend(compatibility.get("review_warnings") or [
                "Package, pin count, or processor architecture still needs verification."
            ])
    if not linked_documents_reviewed:
        blockers.append("Wait for the linked datasheet analysis, then inspect both documents.")
    blockers.extend(missing_review_steps)

    with st.container(key=f"cadivor_approval_actions_{widget_suffix}"):
        st.markdown("**Approval status**")
        if can_approve:
            next_action = "Update approval" if current else "Approve this alternative"
            st.success(
                f"Review complete. Click “{next_action}” below to save the decision to this BOM."
            )
        elif compatibility.get("blocked_from_drop_in_approval") or lifecycle_blocked:
            st.error("This candidate cannot be approved as a direct replacement.")
        else:
            st.warning("Approval is locked. Complete the items below; the button will enable when they pass.")
        if blockers:
            st.markdown("\n".join(f"- {item}" for item in dict.fromkeys(blockers)))
        if not linked_documents_reviewed:
            review_request_key = str(datasheet_review.get("review_request_key") or "")
            if review_request_key:
                st.button(
                    "Analyze linked datasheets",
                    key=f"cadivor_alt_datasheet_review_bottom_{widget_suffix}",
                    type="secondary",
                    on_click=_request_datasheet_review,
                    args=(review_request_key,),
                    help="Analyze the available supplier PDFs before continuing.",
                )
        st.caption(
            "Your checkbox confirms the review; it does not save the BOM decision. Saved approvals appear in this BOM’s Risk and Alternatives views."
        )

        st.markdown(
            f"""
            <style id="cadivor-approval-actions-style-{widget_suffix}" data-cadivor-layout-style="true">
            html body section[data-testid="stMain"] .st-key-cadivor_approval_actions_{widget_suffix} .stButton > button[kind="primary"]:disabled {{
              background:#e2e8f0 !important; background-color:#e2e8f0 !important;
              border:1px solid #cbd5e1 !important; color:#64748b !important;
              box-shadow:none !important; opacity:1 !important; cursor:not-allowed !important;
              transform:none !important;
            }}
            html body section[data-testid="stMain"] .st-key-cadivor_approval_actions_{widget_suffix} .stButton > button[kind="primary"]:disabled * {{
              color:#64748b !important; background:transparent !important;
            }}
            .cv-approval-jump {{
              display:inline-block; margin:4px 0 12px; padding:8px 12px;
              color:#1d4ed8; background:#eff6ff; border:1px solid #bfdbfe;
              border-radius:8px; font-size:13px; font-weight:700; text-decoration:none;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
        save_clicked = st.button(
            (
                "Update approval" if current else "Approve this alternative"
            ) if can_approve else "Approval locked — resolve the items above",
            key=f"cadivor_approved_alternative_save_{widget_suffix}",
            type="primary",
            disabled=not can_approve,
            use_container_width=True,
        )
    remove_clicked = False
    if current:
        remove_clicked = st.button(
            "Remove approval",
            key=f"cadivor_approved_alternative_remove_{widget_suffix}",
            use_container_width=True,
        )

    if save_clicked and (
        lifecycle_blocked
        or not lifecycle_verified
        or (lifecycle_nrnd and not str(note_value or "").strip())
        or compatibility_blocked
        or compatibility.get("physical_missing")
        or compatibility.get("architecture_missing")
        or not review_references_complete
        or not linked_documents_reviewed
    ):
        st.error("Cadivor blocked this approval because required compatibility or documentation review checks are incomplete.")
        return
    if not save_clicked and not remove_clicked:
        return

    from src.authenticated_runtime import archive_analysis_decision, save_analysis_decision

    if remove_clicked:
        try:
            for row in existing_records:
                if (
                    part_key(row.get("alternative_part")) == candidate_key
                    and row.get("id")
                ):
                    archive_analysis_decision(user_id, row["id"])
        except Exception as exc:
            st.error(f"Could not remove this approval: {exc}")
            return
        st.session_state["cadivor_approved_alternatives_flash"] = (
            f"Approval for {candidate_mpn} removed from {project_name}."
        )
        if _navigate_back_to_bom_review(context):
            st.rerun()
            return
        st.rerun()
        return

    profile = st.session_state.get("profile")
    profile = profile if isinstance(profile, dict) else {}
    user_metadata = getattr(auth_user, "user_metadata", {}) or {}
    if not isinstance(user_metadata, dict):
        user_metadata = {}
    engineer_name = str(
        profile.get("full_name")
        or profile.get("name")
        or user_metadata.get("full_name")
        or user_metadata.get("name")
        or (auth_user.get("email") if isinstance(auth_user, dict) else getattr(auth_user, "email", ""))
        or "Cadivor user"
    ).strip()

    def _number_value(row: dict[str, Any], *keys: str) -> float:
        for key in keys:
            try:
                number = float(row.get(key))
            except (TypeError, ValueError):
                continue
            if number == number and number not in (float("inf"), float("-inf")):
                return number
        return 0.0

    supplier = str(
        candidate.get("Supplier")
        or candidate.get("supplier")
        or candidate.get("Manufacturer")
        or candidate.get("manufacturer")
        or ""
    ).strip()
    comparison_rows_snapshot = []
    comparison = comparison_evidence.get("comparison") if isinstance(comparison_evidence, dict) else {}
    comparison_rows = comparison.get("rows") if isinstance(comparison, dict) else []
    for row in comparison_rows or []:
        if not isinstance(row, dict):
            continue
        comparison_rows_snapshot.append(
            {
                "attribute": str(row.get("Attribute") or "")[:100],
                "part_a": str(row.get("Part A") or "")[:120],
                "part_b": str(row.get("Part B") or "")[:120],
                "part_c": str(row.get("Part C") or "")[:120],
                "assessment": str(row.get("Assessment") or row.get("Status") or "")[:60],
                "evidence": str(row.get("Evidence") or "")[:200],
            }
        )
        if len(comparison_rows_snapshot) >= 24:
            break
    compatibility_warnings = list(
        dict.fromkeys(
            list(compatibility.get("critical_warnings") or [])
            + list(compatibility.get("review_warnings") or [])
            + comparison_conflicts
            + datasheet_conflicts
        )
    )
    payload = {
        "analysis_id": analysis_id,
        "context_key": context_key,
        "project_name": project_name,
        "engineer_name": engineer_name,
        "original_part": source_mpn,
        "alternative_part": candidate_mpn,
        "decision": "Approved",
        "engineering_note": str(note_value or "").strip(),
        "recommendation_score": int(_number_value(candidate, "Recommendation Score", "recommendation_score")),
        "recommendation_rating": "User approved",
        "compatibility_confidence": int(_number_value(candidate, "Compatibility Confidence", "compatibility_confidence")),
        "compatibility_rating": "User decision; compatibility not independently certified",
        "lifecycle": str(approval_candidate.get("Lifecycle") or approval_candidate.get("lifecycle_status") or ""),
        "risk": str(candidate.get("Estimated Risk") or candidate.get("risk_level") or candidate.get("risk") or ""),
        "supplier": supplier,
        "stock": int(_number_value(candidate, "Stock", "stock_total", "stock_available")),
        "unit_price": _number_value(candidate, "Unit Price", "unit_price", "price"),
        "package": str(approval_candidate.get("Package") or approval_candidate.get("package") or ""),
        "source_snapshot": {
            "original": approval_original,
            "selected_alternative": approval_candidate,
        },
        "comparison_snapshot": {
            "recorded_from": str(recorded_from or "Find a replacement"),
            "comparison_slot": str(comparison_evidence.get("slot") or "") if isinstance(comparison_evidence, dict) else "",
            "comparison_matrix": comparison_rows_snapshot,
            "comparison_data_conflicts": comparison_conflicts,
            "datasheet_review": _approval_datasheet_snapshot(datasheet_review),
            "compatibility_review": {
                "summary": str(compatibility.get("drop_in_status") or ""),
                "warnings": compatibility_warnings,
                "source_package": compatibility.get("source_package"),
                "candidate_package": compatibility.get("candidate_package"),
                "source_pin_count": compatibility.get("source_pin_count"),
                "candidate_pin_count": compatibility.get("candidate_pin_count"),
                "source_architecture": compatibility.get("source_architecture"),
                "candidate_architecture": compatibility.get("candidate_architecture"),
                "datasheet_package_or_isa_conflicts": datasheet_conflicts,
                "reviewer_attested": review_references_complete,
            },
        },
    }
    try:
        saved = save_analysis_decision(user_id, payload)
        saved_id = saved.get("id") if isinstance(saved, dict) else None
        for row in existing_records:
            if (
                part_key(row.get("alternative_part")) == candidate_key
                and row.get("id")
                and row.get("id") != saved_id
            ):
                archive_analysis_decision(user_id, row["id"])
    except Exception as exc:
        st.error(f"Could not save the approved alternative: {exc}")
        return

    st.session_state["cadivor_approved_alternatives_flash"] = (
        f"{candidate_mpn} approved for {project_name} and saved to this BOM."
    )
    if _navigate_back_to_bom_review(context):
        st.rerun()
        return
    st.rerun()


def _approved_flow_stepper_markup(labels: tuple[str, ...], active_step: int = 1) -> str:
    """Render the non-interactive progress indicator for the approved workflows."""
    parts: list[str] = []
    for index, label in enumerate(labels, start=1):
        active = index == active_step
        complete = index < active_step
        state = " current" if active else " complete" if complete else ""
        aria_current = " aria-current='step'" if active else ""
        node = "✓" if complete else str(index)
        parts.append(
            f"<span class='cv-ap-flow-step{state}'{aria_current}>"
            f"<span class='cv-ap-flow-node'>{node}</span>"
            f"<span>{_esc(label)}</span></span>"
        )
        if index < len(labels):
            parts.append("<span class='cv-ap-flow-line' aria-hidden='true'></span>")
    return (
        "<nav class='cv-ap-flow' aria-label='Workflow steps'>"
        + "".join(parts)
        + f"<span class='cv-ap-flow-status'>STEP {active_step} OF {len(labels)}</span></nav>"
    )


def _render_replacement_search_waiting_state() -> None:
    """Show the empty Finder state without implying that the search has run."""
    search_icon = (
        "<svg viewBox='0 0 24 24' aria-hidden='true'><circle cx='10.5' cy='10.5' r='6.5' "
        "fill='none' stroke='currentColor' stroke-width='1.8'/><path d='m15.5 15.5 5 5' "
        "fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round'/></svg>"
    )
    shield_icon = (
        "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 3 20 6v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z' "
        "fill='none' stroke='currentColor' stroke-width='1.8' stroke-linejoin='round'/></svg>"
    )
    package_icon = (
        "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='m12 3 9 5v8l-9 5-9-5V8zM3.5 8 12 13l8.5-5M12 13v8' "
        "fill='none' stroke='currentColor' stroke-width='1.8' stroke-linejoin='round'/></svg>"
    )
    book_icon = (
        "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M4 4h12a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3zM7 4v16M10 9h6M10 13h6' "
        "fill='none' stroke='currentColor' stroke-width='1.8' stroke-linejoin='round'/></svg>"
    )
    st.markdown(
        f"""
        <section class="cv-ap-waiting" aria-label="Replacement candidates">
          <div class="cv-ap-waiting-head"><h2>Replacement candidates</h2>
            <span class="cv-ap-waiting-status">WAITING FOR SEARCH</span></div>
          <div class="cv-ap-waiting-intro"><span class="cv-ap-waiting-icon">{search_icon}</span>
            <div><h3>Search for a part to begin</h3>
              <p>Supplier-backed candidate rows will appear here after the MPN search finishes.</p></div>
          </div>
          <p class="cv-ap-review-label">Review before approval</p>
          <div class="cv-ap-review-grid">
            <article class="cv-ap-review-item"><div class="cv-ap-review-item-head">{shield_icon}Compatibility evidence</div>
              <p>Package, pin count, and architecture need engineering review.</p></article>
            <article class="cv-ap-review-item"><div class="cv-ap-review-item-head">{package_icon}Supplier evidence</div>
              <p>Lifecycle, stock, and source links appear when available.</p></article>
            <article class="cv-ap-review-item"><div class="cv-ap-review-item-head">{book_icon}Datasheet review</div>
              <p>Check cited dimensions and source documents before sign-off.</p></article>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _queue_replacement_search(widget_key: str = "") -> None:
    """Capture the submitted MPN before the next Finder render starts."""
    query = str(
        st.session_state.get(widget_key)
        or st.session_state.get("approved_replacement_query")
        or ""
    ).strip()
    if query:
        st.session_state["cadivor_replacement_search_pending"] = query


def render_replacement_search() -> None:
    """Find-a-replacement layout wired to the live alternative search."""
    from src.approved_alternatives import (
        candidate_lifecycle_is_blocked,
        part_key,
        toggle_comparison_candidate,
    )
    from src.alternative_finder_state import (
        get_alternative_finder_original_part_input_config,
        has_durable_search_for_mpn,
        init_alternative_finder_state,
    )
    from src.ui.navigation import (
        ALT_FINDER_RETURN_DECISION_ID_KEY,
        ALT_FINDER_RETURN_MPN_KEY,
        ALT_FINDER_RETURN_PAGE_KEY,
        apply_alternative_finder_prefill,
        consume_alternative_finder_context,
        reveal_authenticated_page_body,
    )

    init_alternative_finder_state(st.session_state)

    def _query_param(key: str, default: str = "") -> str:
        try:
            from src.ui.navigation import current_navigation_query_value

            value = current_navigation_query_value(
                key, default, route="Alternative Finder"
            )
        except Exception:
            return default
        if isinstance(value, (list, tuple)):
            value = value[-1] if value else default
        return str(value or default)

    navigation_context = consume_alternative_finder_context(_query_param)
    if navigation_context:
        apply_alternative_finder_prefill(navigation_context)
        source_context = dict(
            st.session_state.get("alternative_prefill_source_context") or {}
        )
        for context_key in (
            "description",
            "source_page",
            "analysis_id",
            "project_name",
            "bom_name",
            "mpn",
            "prefill_id",
            "return_analysis_id",
            "return_page",
            "return_mpn",
            "return_decision_id",
        ):
            if navigation_context.get(context_key):
                source_context[context_key] = navigation_context[context_key]
        st.session_state["alternative_prefill_source_context"] = source_context
    source_context = st.session_state.get("alternative_prefill_source_context")
    source_context = source_context if isinstance(source_context, dict) else {}
    pending_query = str(
        st.session_state.pop("cadivor_replacement_search_pending", "") or ""
    ).strip()
    input_widget_key, _input_default = get_alternative_finder_original_part_input_config(
        st.session_state
    )
    query = pending_query or str(st.session_state.get(input_widget_key) or "").strip()
    prefilled_search_pending = bool(
        st.session_state.pop("alternative_prefill_search_pending", False)
    )
    begin_approved_page()

    return_target = str(source_context.get("source_page") or "")
    return_page = str(source_context.get("return_page") or "").strip()
    return_decision_id = str(source_context.get("return_decision_id") or "").strip()
    return_analysis_id = str(
        source_context.get("return_analysis_id") or source_context.get("analysis_id") or ""
    ).strip()
    return_label = {
        "engineering_intelligence_review": "← Back to BOM Risk",
        "detailed_risk_report": "← Back to Detailed Risk Report",
    }.get(return_target, "← Back to BOM")
    if return_page == "Engineering Decisions" and return_decision_id:
        if st.button(
            "← Back to decision review",
            key=(
                "cadivor_replacement_return_decision_"
                f"{hashlib.sha1(return_decision_id.encode('utf-8')).hexdigest()[:12]}"
            ),
            type="secondary",
        ):
            for state_key in (
                ALT_FINDER_RETURN_PAGE_KEY,
                ALT_FINDER_RETURN_MPN_KEY,
                ALT_FINDER_RETURN_DECISION_ID_KEY,
            ):
                st.session_state.pop(state_key, None)
            navigate_to("Engineering Decisions", decision_id=return_decision_id)
            st.rerun()
    elif return_analysis_id and st.button(
        return_label,
        key=f"cadivor_replacement_return_{hashlib.sha1(return_analysis_id.encode('utf-8')).hexdigest()[:12]}",
        type="secondary",
    ):
        if _navigate_back_to_bom_review(source_context):
            st.rerun()
    st.markdown(
        "<div class='cv-ap'><h1>Find a replacement</h1>"
        "<p class='cv-ap-sub'>Search a source part, then review supplier evidence and compare compatible candidates.</p></div>",
        unsafe_allow_html=True,
    )
    flow_stepper = st.empty()
    flow_stepper.markdown(
        _approved_flow_stepper_markup(
            ("Enter part", "Review candidates", "Compare and record"),
            active_step=1,
        ),
        unsafe_allow_html=True,
    )
    with st.container(key="approved_replacement_search_card"):
        st.markdown(
            "<div class='cv-ap-entry-heading'><span class='cv-ap-entry-icon'>"
            "<svg viewBox='0 0 24 24' aria-hidden='true'><circle cx='10.5' cy='10.5' r='6.5' "
            "fill='none' stroke='currentColor' stroke-width='1.8'/><path d='m15.5 15.5 5 5' "
            "fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round'/></svg>"
            "</span><div><p>SOURCE COMPONENT</p><h2>Find alternatives for a part</h2></div></div>"
            "<p class='cv-ap-entry-copy'>Enter the manufacturer part number to search supplier catalogs.</p>",
            unsafe_allow_html=True,
        )
        search_col, button_col = st.columns([5, 1], vertical_alignment="bottom")
        with search_col:
            query = st.text_input(
                "Manufacturer part number",
                key=input_widget_key,
                placeholder="e.g., LM7805ACT",
            )
        with button_col:
            st.button(
                "Search",
                key="approved_replacement_search",
                type="primary",
                on_click=_queue_replacement_search,
                args=(input_widget_key,),
            )
        st.markdown(
            "<p class='cv-ap-replacement-note'>Search results appear after the search completes.</p>"
            "<div class='cv-ap-context-note'><svg viewBox='0 0 24 24' aria-hidden='true'>"
            "<path d='M12 3 21 8v8l-9 5-9-5V8z' fill='none' stroke='currentColor' stroke-width='1.8'/>"
            "</svg><span>Working from a saved BOM? Start from the component action menu to keep this search linked to that analysis.</span></div>",
            unsafe_allow_html=True,
        )
    # Mount the destination before supplier I/O. Deep links must show the selected
    # MPN and the Finder workspace immediately while the catalog search runs.
    reveal_authenticated_page_body("Alternative Finder")
    query = str(query or st.session_state.get(input_widget_key) or "").strip()
    if query and (pending_query or prefilled_search_pending):
        from src.alternative_finder_search import run_alternative_finder_search

        with st.spinner(f"Searching supplier catalogs for {query}…"):
            run_alternative_finder_search(st.session_state, query)
    result = st.session_state.get("alternative_finder_result")
    original = {}
    candidates: list[dict[str, Any]] = []
    if isinstance(result, dict):
        original = result.get("original_data") if isinstance(result.get("original_data"), dict) else {}
        raw_candidates = result.get("candidates") or result.get("alternative_candidates") or []
        candidates = [row for row in raw_candidates if isinstance(row, dict)]
    if isinstance(source_context, dict) and query:
        from src.normalizer import normalize_part_number

        context_mpn = str(source_context.get("mpn") or "").strip()
        if (
            context_mpn
            and (normalize_part_number(context_mpn) or context_mpn.upper())
            == (normalize_part_number(query) or query.upper())
        ):
            # Keep the clicked source visible even when a supplier has no exact
            # catalog record for it.
            original = dict(original)
            original["manufacturer_part_number"] = context_mpn
            for field, context_field in (
                ("manufacturer", "manufacturer"),
                ("description", "description"),
                ("lifecycle", "lifecycle"),
                ("risk_level", "risk"),
            ):
                if not str(original.get(field) or "").strip():
                    original[field] = source_context.get(context_field) or ""
    search_completed = has_durable_search_for_mpn(st.session_state, query)
    flow_stepper.markdown(
        _approved_flow_stepper_markup(
            ("Enter part", "Review candidates", "Compare and record"),
            active_step=2 if search_completed else 1,
        ),
        unsafe_allow_html=True,
    )
    if not search_completed:
        # The initial Finder view is only a search form. Keep a stale prior
        # result hidden while the user edits a new query; show results and
        # filters only after that exact MPN has finished searching.
        st.session_state["approved_replacement_compare_candidates"] = []
        _render_replacement_search_waiting_state()
        return
    supplier_candidate_count = len(candidates)
    if supplier_candidate_count:
        fit_filter, life_filter, stock_filter, risk_filter, sort_by = st.columns(5)
        with fit_filter:
            fit_choice = st.selectbox("Parametric fit", ["All"], key="approved_fit_filter")
        with life_filter:
            life_choice = st.selectbox("Lifecycle", ["All", "Active", "NRND", "Obsolete"], key="approved_life_filter")
        with stock_filter:
            stock_choice = st.selectbox("Stock", ["All", "In stock", "No stock"], key="approved_stock_filter")
        with risk_filter:
            risk_choice = st.selectbox(
                "Risk",
                ["All", "High", "Medium", "Low", "Needs verification"],
                key="approved_risk_filter",
            )
        with sort_by:
            sort_choice = st.selectbox("Sort by", ["Overall match", "Stock", "Risk"], key="approved_replacement_sort")
    else:
        # Don't show inert filter controls when the supplier search returned no
        # component rows. The empty state below explains what the user can do.
        fit_choice = life_choice = stock_choice = risk_choice = sort_choice = "All"
    filtered = []
    for row in candidates:
        level = str(row.get("Estimated Risk") or row.get("risk_level") or row.get("risk") or "")
        lifecycle = str(row.get("Lifecycle") or row.get("lifecycle_status") or row.get("lifecycle") or "")
        stock_value = _candidate_stock(row)
        if life_choice != "All" and life_choice.casefold() not in lifecycle.casefold():
            continue
        if risk_choice != "All" and risk_choice.casefold() not in level.casefold():
            continue
        if stock_choice == "In stock" and stock_value <= 0:
            continue
        if stock_choice == "No stock" and stock_value > 0:
            continue
        filtered.append(row)
    if sort_choice == "Stock":
        filtered.sort(key=_candidate_stock, reverse=True)
    elif sort_choice == "Risk":
        filtered.sort(key=lambda row: str(row.get("Estimated Risk") or row.get("risk_level") or ""))
    named = [row for row in filtered if _candidate_mpn(row)]
    dropped = len(filtered) - len(named)
    excluded_obsolete = [row for row in named if candidate_lifecycle_is_blocked(row)]
    # Explicit obsolete/EOL records can be inspected, but must never appear as
    # replacement-ready choices or enter comparison/approval selection.
    candidates = (
        []
        if life_choice.casefold() == "obsolete"
        else [row for row in named if not candidate_lifecycle_is_blocked(row)]
    )
    del fit_choice
    mpn = _esc(original.get("manufacturer_part_number") or original.get("mpn") or (query or "Search an MPN"))
    manufacturer = _esc(original.get("manufacturer") or original.get("Manufacturer") or original.get("manufacturer_name") or "—")
    description = _esc(original.get("description") or original.get("category") or "")
    notice = ""
    lookup_error = ""
    search_error = ""
    discovery: dict[str, Any] = {}
    if isinstance(result, dict):
        lookup_error = str(result.get("lookup_error") or "").strip()
        search_error = str(result.get("search_error") or "").strip()
        raw_discovery = result.get("discovery_metadata")
        if isinstance(raw_discovery, dict):
            discovery = raw_discovery
    source_notice = (
        "Supplier records could not verify this source part. Confirm the MPN and retry."
        if lookup_error
        else ""
    )
    candidate_notice = ""
    empty_title = "No replacement candidates confirmed"
    empty_detail = ""
    if query.strip() and isinstance(result, dict) and not candidates and excluded_obsolete:
        candidate_notice = (
            f"{len(excluded_obsolete)} supplier match{'es' if len(excluded_obsolete) != 1 else ''} "
            "marked obsolete or end of life. Cadivor excluded these from replacement selection."
        )
    elif query.strip() and isinstance(result, dict) and not supplier_candidate_count:
        from src.alternative_finder_search import replacement_search_empty_state

        empty_title, empty_detail = replacement_search_empty_state(
            discovery if isinstance(discovery, dict) else {},
            lookup_error=lookup_error,
            search_error=search_error,
        )
        candidate_notice = empty_detail
    elif dropped:
        candidate_notice = (
            f"{dropped} supplier row{'s' if dropped != 1 else ''} had no part number "
            f"and {'were' if dropped != 1 else 'was'} left out."
        )
    elif excluded_obsolete:
        candidate_notice = (
            f"{len(excluded_obsolete)} obsolete or end-of-life supplier match"
            f"{'es' if len(excluded_obsolete) != 1 else ''} excluded from replacement selection."
        )
    notice = candidate_notice
    shown = candidates[:25]
    if len(candidates) > len(shown) and not notice:
        notice = f"Showing {len(shown)} of {len(candidates)} supplier alternatives."
    notice_html = f"<p class='cv-ap-sub'>{_esc(notice)}</p>" if notice and shown else ""
    source_html = f"<p class='cv-ap-sub'>{_esc(source_notice)}</p>" if source_notice else ""
    st.markdown(
        f"""
        <div class="cv-ap">
          <h2>Source component</h2>
          {source_html}
          <section class="cv-ap-card">
            <div class="cv-ap-meta">Source part</div>
            <div class="cv-ei-part">{part_photo(str(original.get('image_url') or original.get('photo_url') or ''), part=original)}<span class="cv-ei-part-copy"><span class="cv-ap-name">{mpn}</span><span class="cv-ei-meta">{description}</span></span></div>
            <p>Manufacturer {manufacturer}</p>
          </section>
          {notice_html}
          <h2>Replacement candidates</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if discovery:
        from src.alternative_finder_search import supplier_search_coverage_rows

        coverage_rows = supplier_search_coverage_rows(discovery)
        if coverage_rows:
            with st.container(key="approved_replacement_search_coverage"):
                st.markdown(
                    "**Supplier search coverage**  \n"
                    "Candidate rows identify suppliers that returned a part. This list also shows catalogs that were checked but returned no leads, failed, or are not configured. Catalog leads are not compatibility approvals."
                )
                for provider_name, coverage_detail in coverage_rows:
                    st.markdown(
                        f"**{_esc(provider_name)}** · {_esc(coverage_detail)}",
                        unsafe_allow_html=True,
                    )
    if excluded_obsolete:
        with st.expander(
            f"View {len(excluded_obsolete)} excluded obsolete / end-of-life record"
            f"{'s' if len(excluded_obsolete) != 1 else ''}",
            expanded=False,
        ):
            st.caption("These supplier records are shown for context only; they cannot be compared or approved as replacements.")
            for row in excluded_obsolete:
                st.markdown(
                    f"- **{_esc(_candidate_mpn(row))}** · "
                    f"{_esc(_candidate_field(row, 'Manufacturer', 'manufacturer'))} · "
                    f"{_esc(_candidate_field(row, 'Lifecycle', 'Lifecycle Status', 'lifecycle_status', 'lifecycle'))}",
                    unsafe_allow_html=False,
                )
    if not shown:
        st.session_state["approved_replacement_compare_candidates"] = []
        st.session_state.pop("cadivor_replacement_open_mpn", None)
        if excluded_obsolete:
            empty_title = "No replacement-ready candidates"
            empty_detail = candidate_notice
        elif dropped:
            empty_title = "Supplier results need part-number verification"
            empty_detail = candidate_notice
        elif supplier_candidate_count:
            empty_title = "No candidates match the selected filters"
            empty_detail = "Broaden the filters above or search this part again."
        elif not empty_detail:
            from src.alternative_finder_search import replacement_search_empty_state

            empty_title, empty_detail = replacement_search_empty_state(
                discovery if isinstance(discovery, dict) else {},
                lookup_error=lookup_error,
                search_error=search_error,
            )
        st.markdown(
            f"<section class='cv-ap-card cv-ap-empty-state'>"
            f"<h3>{_esc(empty_title)}</h3><p>{_esc(empty_detail)}</p></section>",
            unsafe_allow_html=True,
        )
        if query.strip() and not supplier_candidate_count and st.button(
            "Retry supplier search",
            key=(
                "approved_replacement_retry_"
                + hashlib.sha1(query.casefold().encode("utf-8")).hexdigest()[:12]
            ),
            type="secondary",
        ):
            st.session_state["cadivor_replacement_search_pending"] = query
            st.rerun()
        return
    from src.part_images import part_image_markup

    header = st.columns([2.4, 1.3, 1.8, 0.9, 0.8, 0.9, 0.7])
    for column, label in zip(
        header,
        ("Candidate MPN", "Manufacturer", "Supplier relationship", "Lifecycle", "Stock", "Suppliers", "Risk"),
    ):
        column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
    selected = str(st.session_state.get("cadivor_replacement_open_mpn") or "")
    for index, row in enumerate(shown):
        candidate_mpn = _candidate_mpn(row)
        is_open = candidate_mpn == selected
        compatibility = assess_part_compatibility(
            original,
            _candidate_part_payload(row),
        )
        if compatibility.get("critical_warnings"):
            compatibility_label = (
                "<span class='cv-compat-pill critical'>NOT DROP-IN</span>"
                "<div class='cv-compat-inline-critical'>"
                + "<br>".join(_esc(item) for item in compatibility["critical_warnings"])
                + "</div>"
            )
        elif compatibility.get("review_warnings"):
            compatibility_label = (
                "<span class='cv-compat-pill review'>NOT VERIFIED</span>"
            )
        else:
            compatibility_label = (
                "<span class='cv-compat-pill review'>ENGINEERING REVIEW</span>"
            )
        relationship_label = _candidate_field(
            row,
            "Classification",
            "Category",
            "fit",
            "parametric_fit",
            fallback="Supplier catalog result",
        )
        relationship_html = (
            f"{compatibility_label}<small>{relationship_label}</small>"
            if compatibility.get("critical_warnings") or compatibility.get("review_warnings")
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
    """Datasheet Q&A workspace styled to the approved review mockup."""
    import base64

    from src.datasheet_qa import (
        DATASHEET_QA_CLEAR_QUESTION_KEY,
        DATASHEET_QA_DOC_KEY,
        DATASHEET_QA_FOLLOW_UP_WIDGET_KEY,
        DATASHEET_QA_PENDING_QUESTION_KEY,
        DATASHEET_QA_QUESTION_WIDGET_KEY,
        DATASHEET_QA_STATUS_KEY,
        DATASHEET_QA_THREAD_KEY,
        DATASHEET_QA_UPLOAD_SIGNATURE_KEY,
        STATUS_PROCESSING,
        apply_datasheet_question_clear,
        clear_datasheet_document,
        consume_datasheet_pending_question,
        datasheet_document_matches_part,
        datasheet_upload_signature,
        document_fingerprint,
        extract_uploaded_datasheet,
        render_datasheet_page_png,
        store_document_in_session,
    )
    from src.datasheet_comparison import (
        MAX_DATASHEET_BYTES,
        MAX_DATASHEET_PAGES,
        extract_datasheet_text,
    )
    from src.pages.datasheet_qa import (
        _execute_datasheet_question,
        _inject_datasheet_qa_styles,
        _render_ask_next_chips,
        _render_thread_turn,
        _typed_ask_click,
        _typed_follow_up_click,
    )

    def store_new_upload(uploaded: Any) -> dict[str, Any] | None:
        if uploaded is None:
            return None
        payload = uploaded.getvalue()
        filename = str(uploaded.name or "datasheet.pdf")
        signature = datasheet_upload_signature(payload, filename=filename)
        if signature == str(st.session_state.get(DATASHEET_QA_UPLOAD_SIGNATURE_KEY) or ""):
            return None
        current = st.session_state.get(DATASHEET_QA_DOC_KEY)
        # Migrate an already-active document into the signature scheme without
        # re-extracting it on the first render after this release.
        if (
            isinstance(current, dict)
            and str(current.get("filename") or "") == filename
            and str(current.get("content_fingerprint") or "") == hashlib.sha256(payload).hexdigest()[:16]
        ):
            st.session_state[DATASHEET_QA_UPLOAD_SIGNATURE_KEY] = signature
            return None
        extracted = extract_uploaded_datasheet(payload, filename=filename)
        store_document_in_session(st.session_state, extracted)
        st.session_state[DATASHEET_QA_UPLOAD_SIGNATURE_KEY] = signature
        st.session_state[DATASHEET_QA_QUESTION_WIDGET_KEY] = ""
        st.session_state.pop(DATASHEET_QA_FOLLOW_UP_WIDGET_KEY, None)
        st.session_state.pop(DATASHEET_QA_CLEAR_QUESTION_KEY, None)
        st.session_state.pop("approved_datasheet_source_page", None)
        return extracted

    def on_datasheet_upload_change() -> None:
        uploaded_file = st.session_state.get("datasheet_qa_uploader")
        extracted_document = store_new_upload(uploaded_file)
        if uploaded_file is not None and (
            extracted_document is not None
            or datasheet_upload_signature(
                uploaded_file.getvalue(), filename=str(uploaded_file.name or "datasheet.pdf")
            )
            == str(st.session_state.get(DATASHEET_QA_UPLOAD_SIGNATURE_KEY) or "")
        ):
            st.session_state["datasheet_qa_show_picker"] = False

    def on_remove_datasheet() -> None:
        clear_datasheet_document(st.session_state)
        st.session_state.pop("datasheet_qa_uploader", None)
        st.session_state.pop("datasheet_qa_show_picker", None)
        st.session_state.pop("approved_datasheet_source_page", None)
        st.session_state.pop(DATASHEET_QA_QUESTION_WIDGET_KEY, None)
        st.session_state.pop(DATASHEET_QA_FOLLOW_UP_WIDGET_KEY, None)
        st.session_state.pop(DATASHEET_QA_PENDING_QUESTION_KEY, None)
        st.session_state.pop(DATASHEET_QA_CLEAR_QUESTION_KEY, None)

    def change_source_page(delta: int) -> None:
        try:
            current = int(st.session_state.get("approved_datasheet_source_page") or active_page)
        except (TypeError, ValueError):
            current = active_page
        st.session_state["approved_datasheet_source_page"] = max(
            1, min(max(page_count, 1), current + int(delta))
        )

    begin_approved_page()
    _inject_datasheet_qa_styles()
    apply_datasheet_question_clear(st.session_state)
    pdf_limit = f"{MAX_DATASHEET_BYTES / (1024 * 1024):g} MB"
    with st.container(key="approved_datasheet_workspace"):
        document = st.session_state.get(DATASHEET_QA_DOC_KEY)
        uploaded = st.session_state.get("datasheet_qa_uploader")
        extracted = store_new_upload(uploaded)
        if extracted is not None and not extracted.get("available"):
            st.error(str(extracted.get("reason") or "Could not read this PDF."))
        st.markdown(
            '<div class="dq-marker" aria-hidden="true"></div>'
            "<header class='dq-hero'>"
            "<p class='dq-breadcrumb'>Engineering Intelligence / Datasheet Q&amp;A</p>"
            "<h1 class='dq-title'>Datasheet Q&amp;A</h1>"
            "<p class='dq-sub'>Ask precise questions about technical documents and inspect the supporting source pages.</p>"
            "</header>",
            unsafe_allow_html=True,
        )

        # A part-number lookup makes this workflow discoverable and retrieves
        # exact supplier-linked PDFs when available. A public web search is
        # shown only as a lead; it is never treated as verified evidence.
        from src.ui.navigation import current_navigation_query_value

        route_mpn = str(
            current_navigation_query_value("mpn", "", route="Datasheet Q&A") or ""
        ).strip()
        route_prefill_id = str(
            current_navigation_query_value("prefill_id", "", route="Datasheet Q&A") or ""
        ).strip()
        route_token = f"{route_mpn.casefold()}::{route_prefill_id}"
        route_prefill_changed = bool(
            route_mpn
            and st.session_state.get("datasheet_qa_search_route_token") != route_token
        )
        if route_prefill_changed:
            st.session_state["approved_datasheet_part_query"] = route_mpn
            st.session_state["datasheet_qa_search_route_token"] = route_token
        with st.container(key="approved_datasheet_search_card"):
            st.markdown(
                "<div class='cv-dq-lookup-heading'><strong>Find a datasheet by part number</strong>"
                "<span>Cadivor checks exact supplier records and loads a readable linked PDF for cited Q&amp;A. If none is available, search the web or upload the manufacturer PDF below.</span></div>",
                unsafe_allow_html=True,
            )
            with st.form("approved_datasheet_lookup_form", clear_on_submit=False):
                search_col, button_col = st.columns([5, 1], vertical_alignment="bottom")
                with search_col:
                    datasheet_query = st.text_input(
                        "Manufacturer part number",
                        key="approved_datasheet_part_query",
                        placeholder="e.g., DHT11",
                    )
                with button_col:
                    find_datasheet_clicked = st.form_submit_button(
                        "Find datasheet",
                        type="primary",
                        use_container_width=True,
                    )
            # A part-number deep link means the engineer already asked for this
            # document. Start the exact lookup on the first page render so the
            # datasheet and supplier evidence appear without a second click.
            if find_datasheet_clicked or route_prefill_changed:
                requested_mpn = str(
                    route_mpn if route_prefill_changed else datasheet_query or ""
                ).strip()
                lookup_result: dict[str, Any] = {
                    "mpn": requested_mpn,
                    "supplier": "",
                    "datasheet_url": "",
                    "web_search_url": "",
                    "message": "",
                    "loaded": False,
                }
                if not requested_mpn:
                    lookup_result["message"] = "Enter a manufacturer part number to search."
                else:
                    active_document = st.session_state.get(DATASHEET_QA_DOC_KEY)
                    if (
                        isinstance(active_document, dict)
                        and not datasheet_document_matches_part(
                            active_document,
                            requested_mpn,
                        )
                    ):
                        # Do not let a failed lookup for a new part leave an
                        # unrelated old datasheet active for cited Q&A.
                        clear_datasheet_document(st.session_state)
                        st.session_state.pop("datasheet_qa_uploader", None)
                        st.session_state.pop(DATASHEET_QA_QUESTION_WIDGET_KEY, None)
                        st.session_state.pop(DATASHEET_QA_CLEAR_QUESTION_KEY, None)
                        st.session_state.pop("approved_datasheet_source_page", None)

                    from src.decision_packet_evidence import (
                        exact_supplier_evidence,
                        public_datasheet_search_url,
                    )
                    from src.datasheet_qa import _chunk_page_text

                    try:
                        from integrations.supplier_aggregator import get_first_exact_supplier_result

                        with st.spinner(f"Checking exact supplier datasheets for {requested_mpn}…"):
                            supplier_record = get_first_exact_supplier_result(requested_mpn)
                    except Exception:
                        supplier_record = {}
                    evidence = exact_supplier_evidence(requested_mpn, supplier_record)
                    datasheet_url = str((evidence or {}).get("datasheet_url") or "").strip()
                    if datasheet_url:
                        lookup_result["supplier"] = str((evidence or {}).get("source") or "Supplier")
                        lookup_result["datasheet_url"] = datasheet_url
                        with st.spinner("Loading page-cited datasheet text…"):
                            linked_pdf = extract_datasheet_text(datasheet_url)
                        pages = [
                            page for page in (linked_pdf.get("pages") or [])
                            if isinstance(page, dict) and str(page.get("text") or "").strip()
                        ]
                        chunks = []
                        for page in pages:
                            page_number = int(page.get("page") or 0)
                            for chunk in _chunk_page_text(page_number, str(page.get("text") or "")):
                                chunks.append({
                                    "chunk_id": chunk.chunk_id,
                                    "page": chunk.page,
                                    "text": chunk.text,
                                    "start_char": chunk.start_char,
                                })
                        if pages and chunks:
                            page_count = max(int(page.get("page") or 0) for page in pages)
                            fingerprint_payload = datasheet_url + "\0" + "\n".join(
                                str(page.get("text") or "") for page in pages
                            )
                            document = {
                                "available": True,
                                "reason": "",
                                "pages": pages,
                                "chunks": chunks,
                                "filename": f"{requested_mpn}-datasheet.pdf",
                                "page_count": page_count,
                                "source_page_count": page_count,
                                "byte_count": 0,
                                "content_fingerprint": hashlib.sha256(
                                    fingerprint_payload.encode("utf-8")
                                ).hexdigest()[:16],
                                "source_url": str(linked_pdf.get("final_url") or datasheet_url),
                                "source_supplier": lookup_result["supplier"],
                                "requested_mpn": requested_mpn,
                            }
                            store_document_in_session(st.session_state, document)
                            st.session_state.pop("approved_datasheet_source_page", None)
                            lookup_result["loaded"] = True
                            lookup_result["message"] = (
                                f"Loaded a readable datasheet from {lookup_result['supplier']}. "
                                "You can ask cited questions below."
                            )
                        else:
                            lookup_result["message"] = (
                                str(linked_pdf.get("reason") or "The supplier link did not return readable PDF text.")
                            )
                    else:
                        lookup_result["message"] = (
                            "No exact supplier record included a datasheet link."
                        )
                    lookup_result["web_search_url"] = public_datasheet_search_url(requested_mpn)
                st.session_state["datasheet_qa_search_result"] = lookup_result

            lookup_result = st.session_state.get("datasheet_qa_search_result")
            from src.normalizer import normalize_part_number

            visible_lookup_query = normalize_part_number(str(datasheet_query or ""))
            result_lookup_mpn = normalize_part_number(
                str(lookup_result.get("mpn") or "")
                if isinstance(lookup_result, dict)
                else ""
            )
            if (
                isinstance(lookup_result, dict)
                and visible_lookup_query
                and visible_lookup_query == result_lookup_mpn
            ):
                if lookup_result.get("loaded"):
                    st.success(str(lookup_result.get("message") or "Datasheet loaded."))
                else:
                    st.info(str(lookup_result.get("message") or "No exact linked datasheet was found."))
                result_link = str(lookup_result.get("datasheet_url") or "").strip()
                result_link_col, web_link_col = st.columns(2)
                with result_link_col:
                    if result_link.startswith("https://"):
                        st.link_button(
                            f"Open {lookup_result.get('mpn')} datasheet",
                            result_link,
                            use_container_width=True,
                        )
                with web_link_col:
                    web_search_url = str(lookup_result.get("web_search_url") or "").strip()
                    if web_search_url.startswith("https://"):
                        st.link_button(
                            f"Search public datasheets for {lookup_result.get('mpn')}",
                            web_search_url,
                            use_container_width=True,
                        )

        document = st.session_state.get(DATASHEET_QA_DOC_KEY)
        ready = isinstance(document, dict) and bool(document.get("available"))
        filename = str(document.get("filename") or "") if isinstance(document, dict) else ""
        page_count = int(
            document.get("source_page_count") or document.get("page_count") or 0
        ) if isinstance(document, dict) else 0
        thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
        pending_question = consume_datasheet_pending_question(st.session_state) if ready else ""
        if pending_question:
            _execute_datasheet_question(
                document=document,
                question=pending_question,
                thread=list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or []),
            )
            st.session_state[DATASHEET_QA_FOLLOW_UP_WIDGET_KEY] = ""
        thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
        latest = thread[-1] if thread and isinstance(thread[-1], dict) else {}
        active_page = 1
        primary = latest.get("primary_evidence") if isinstance(latest.get("primary_evidence"), dict) else {}
        try:
            active_page = max(1, min(page_count or 1, int(primary.get("page") or 1)))
        except (TypeError, ValueError):
            active_page = 1
        page_key = "approved_datasheet_source_page"
        if pending_question:
            st.session_state[page_key] = active_page
        if page_key in st.session_state:
            try:
                current_page = int(st.session_state[page_key])
            except (TypeError, ValueError):
                current_page = 1
                st.session_state[page_key] = active_page
            if current_page < 1 or current_page > max(page_count, 1):
                st.session_state[page_key] = active_page
        try:
            source_page = max(
                1,
                min(max(page_count, 1), int(st.session_state.get(page_key) or active_page)),
            )
        except (TypeError, ValueError):
            source_page = active_page
            st.session_state[page_key] = active_page

        if not ready:
            with st.container(key="approved_datasheet_upload_card"):
                st.markdown(
                    "<div class='cv-dq-upload-heading'><span class='cv-dq-document-icon' aria-hidden='true'>"
                    "<svg viewBox='0 0 24 24'><path d='M6 3.8h8l4 4V20H6zM14 3.8v4h4M9 12h6M9 15.5h6' "
                    "fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'/></svg>"
                    "</span><div><p>SELECTED DATASHEET</p><h2>Choose a datasheet PDF</h2>"
                    "<span>Upload a text-searchable manufacturer document to begin a cited review.</span></div></div>",
                    unsafe_allow_html=True,
                )
                uploaded = st.file_uploader(
                    "Choose a datasheet PDF",
                    type=["pdf"],
                    key="datasheet_qa_uploader",
                    on_change=on_datasheet_upload_change,
                    help=f"PDF only · up to {pdf_limit} · up to {MAX_DATASHEET_PAGES} pages · text-searchable pages required.",
                )
                st.markdown(
                    f"<p class='cv-dq-limit-note'>PDF only · up to {_esc(pdf_limit)} · up to {MAX_DATASHEET_PAGES} pages · text-searchable pages required · private session. Scanned image-only PDFs are not supported yet.</p>",
                    unsafe_allow_html=True,
                )
            if isinstance(document, dict) and document.get("reason"):
                st.warning(str(document.get("reason")))
            end_approved_page()
            return

        payload = uploaded.getvalue() if uploaded is not None else b""
        if payload and hashlib.sha256(payload).hexdigest()[:16] != str(document.get("content_fingerprint") or ""):
            payload = b""
        size_text = f"{len(payload) / 1024:,.0f} KB · " if payload else ""
        analyzed_pages = int(document.get("page_count") or page_count)
        metadata = (
            f"{size_text}{page_count} page{'s' if page_count != 1 else ''} · {analyzed_pages} analyzed"
            if analyzed_pages != page_count
            else f"{size_text}{page_count} page{'s' if page_count != 1 else ''}"
        )
        document_cols = st.columns([5.2, 1.25, 1.35], gap="small", vertical_alignment="center")
        with document_cols[0]:
            st.markdown(
                "<div class='cv-dq-document'><span class='cv-dq-document-icon' aria-hidden='true'>"
                "<svg viewBox='0 0 24 24'><path d='M6 3.8h8l4 4V20H6zM14 3.8v4h4M9 12h6M9 15.5h6' "
                "fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'/></svg>"
                f"</span><span class='cv-dq-document-copy'><small>SELECTED DATASHEET</small><strong>{_esc(filename or 'Active datasheet')}</strong><span>{_esc(metadata)}</span></span>"
                "<span class='cv-dq-private'>Text extracted</span></div>",
                unsafe_allow_html=True,
            )
        with document_cols[1]:
            if st.button(
                "Change document",
                key="approved_datasheet_change_document",
                type="secondary",
                use_container_width=True,
            ):
                st.session_state["datasheet_qa_show_picker"] = True
        with document_cols[2]:
            if payload:
                encoded_pdf = base64.b64encode(payload).decode("ascii")
                st.markdown(
                    "<div class='cv-dq-open-pdf-wrap'><a class='cv-dq-doc-link' target='_blank' rel='noopener noreferrer' "
                    f"href='data:application/pdf;base64,{encoded_pdf}#page={source_page}'>Open PDF ↗</a></div>",
                    unsafe_allow_html=True,
                )
            elif str(document.get("source_url") or "").startswith("https://"):
                st.link_button(
                    "Open PDF ↗",
                    str(document.get("source_url") or ""),
                    use_container_width=True,
                )
            else:
                st.markdown("<div class='cv-dq-open-pdf-wrap'><span class='cv-dq-doc-link is-disabled'>PDF unavailable</span></div>", unsafe_allow_html=True)

        picker_open = bool(st.session_state.get("datasheet_qa_show_picker"))
        if picker_open:
            st.markdown('<div class="dq-picker-open" aria-hidden="true"></div>', unsafe_allow_html=True)
            st.markdown(
                "<p class='cv-dq-picker-label'>Choose a replacement PDF. The previous conversation will be cleared when the new document is ready.</p>",
                unsafe_allow_html=True,
            )
            if st.button("Cancel", key="approved_datasheet_cancel_change", type="secondary"):
                st.session_state["datasheet_qa_show_picker"] = False
                st.rerun()
        else:
            st.markdown('<div class="dq-hide-picker" aria-hidden="true"></div>', unsafe_allow_html=True)
        st.file_uploader(
            "Change document",
            type=["pdf"],
            key="datasheet_qa_uploader",
            on_change=on_datasheet_upload_change,
            label_visibility="collapsed" if ready else "visible",
            help=f"PDF only · up to {pdf_limit} · up to {MAX_DATASHEET_PAGES} pages · text-searchable pages required.",
        )
        if picker_open:
            picker_actions = st.columns([1, 1, 5])
            with picker_actions[0]:
                st.button(
                    "Remove document",
                    key="approved_datasheet_remove",
                    type="secondary",
                    on_click=on_remove_datasheet,
                    use_container_width=True,
                )
            with picker_actions[1]:
                if st.button("Done", key="approved_datasheet_done_picker", type="secondary", use_container_width=True):
                    st.session_state["datasheet_qa_show_picker"] = False
                    st.rerun()

        left, right = st.columns([0.92, 1.08], gap="medium")
        with left:
            with st.container(key="approved_datasheet_question_panel"):
                st.markdown(
                    "<div class='cv-dq-question-head'><h2>Ask this datasheet</h2>"
                    "<p>Answers include page citations so you can verify the source directly.</p></div>",
                    unsafe_allow_html=True,
                )
                is_processing = str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or "") == STATUS_PROCESSING
                if thread:
                    st.markdown(
                        f"<div class='cv-dq-current-question'><small>YOUR QUESTION</small>{_esc(latest.get('question'))}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown("<p class='cv-dq-field-label'>YOUR QUESTION</p>", unsafe_allow_html=True)
                    st.text_area(
                        "Question",
                        key=DATASHEET_QA_QUESTION_WIDGET_KEY,
                        placeholder="Example: What package dimensions and land pattern does the datasheet specify?",
                        height=64,
                        label_visibility="collapsed",
                        disabled=is_processing,
                    )
                    ask_cols = st.columns([3.2, 1], gap="small", vertical_alignment="center")
                    with ask_cols[0]:
                        st.markdown("<span aria-hidden='true'></span>", unsafe_allow_html=True)
                    with ask_cols[1]:
                        st.button(
                            "Ask Cadivor",
                            key="approved_datasheet_ask",
                            type="primary",
                            on_click=_typed_ask_click,
                            disabled=is_processing,
                            use_container_width=True,
                        )
                fingerprint = document_fingerprint(document) or "doc"
                latest_suggestions = [
                    str(item).strip()
                    for item in list(latest.get("suggestions") or [])
                    if str(item).strip()
                ]
                if not latest_suggestions:
                    latest_suggestions = [
                        "Package dimensions",
                        "Pin 1 orientation",
                        "Absolute max ratings",
                    ]
                _render_ask_next_chips(
                    latest_suggestions,
                    turn_index=len(thread),
                    fingerprint=fingerprint,
                    disabled=str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or "") == STATUS_PROCESSING,
                    title="Suggested questions",
                )
                if not thread:
                    st.markdown(
                        "<div class='cv-dq-answer-empty'><strong>Your answer and evidence will appear here.</strong>"
                        "<span>Start with package dimensions, pinout, ratings, or device identity.</span></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    _render_thread_turn(
                        latest,
                        turn_index=len(thread) - 1,
                        fingerprint=fingerprint,
                        disabled=str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or "") == STATUS_PROCESSING,
                        show_follow_ups=False,
                        show_question=False,
                        show_question_reference=False,
                    )
                    if len(thread) > 1:
                        with st.expander(f"Earlier questions ({len(thread) - 1})", expanded=False):
                            for turn_index, turn in enumerate(thread[:-1]):
                                if isinstance(turn, dict):
                                    _render_thread_turn(
                                        turn,
                                        turn_index=turn_index,
                                        fingerprint=fingerprint,
                                        disabled=True,
                                        show_follow_ups=False,
                                    )
                st.markdown(
                    "<p class='cv-dq-answer-caution'>AI-generated answers can miss context. Check each citation against the full datasheet before design sign-off.</p>",
                    unsafe_allow_html=True,
                )
                if thread:
                    st.markdown("<p class='cv-dq-follow-up-label'>ASK A FOLLOW-UP</p>", unsafe_allow_html=True)
                    follow_cols = st.columns([4, 1.35], gap="small", vertical_alignment="bottom")
                    with follow_cols[0]:
                        st.text_input(
                            "Ask a follow-up",
                            key=DATASHEET_QA_FOLLOW_UP_WIDGET_KEY,
                            placeholder="Ask about a cited value…",
                            label_visibility="collapsed",
                            disabled=is_processing,
                        )
                    with follow_cols[1]:
                        st.button(
                            "Ask Cadivor",
                            key="approved_datasheet_follow_up",
                            type="primary",
                            on_click=_typed_follow_up_click,
                            disabled=is_processing,
                            use_container_width=True,
                        )

        with right:
            with st.container(key="approved_datasheet_source_panel"):
                st.markdown(
                    "<div class='cv-dq-source-head'><div><h2>Document evidence</h2>"
                    f"<p>Cited page from {_esc(filename or 'Active datasheet')}</p></div>"
                    f"<span class='cv-dq-page-badge'>PAGE {source_page} / {max(page_count, 1)}</span></div>",
                    unsafe_allow_html=True,
                )
                if payload:
                    preview_png = render_datasheet_page_png(payload, source_page)
                    if preview_png:
                        encoded_preview = base64.b64encode(preview_png).decode("ascii")
                        st.markdown(
                            "<div class='cv-dq-page-preview-frame'>"
                            f"<img class='cv-dq-page-preview' alt='Original datasheet page {source_page}' src='data:image/png;base64,{encoded_preview}'>"
                            "</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            "<div class='cv-dq-page-fallback'>The original page preview could not be rendered. "
                            "Open the PDF to inspect the source directly.</div>",
                            unsafe_allow_html=True,
                        )
                else:
                    pages = document.get("pages") if isinstance(document, dict) else []
                    source_text = next(
                        (str(item.get("text") or "") for item in pages or [] if isinstance(item, dict) and int(item.get("page") or 0) == source_page),
                        "",
                    )
                    if source_text:
                        st.markdown(
                            f"<div class='cv-dq-page-fallback'><strong>Extracted source text · Page {source_page}</strong><br><br>{_esc(source_text[:2400])}</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            "<div class='cv-dq-page-fallback'>Re-select the PDF to preview this original page. "
                            "The extracted text and citations are still available in this session.</div>",
                            unsafe_allow_html=True,
                        )
                nav_cols = st.columns([1.35, 1.45, 4], gap="small", vertical_alignment="center")
                with nav_cols[0]:
                    st.button(
                        "← Previous page",
                        key="approved_datasheet_previous_page",
                        type="tertiary",
                        disabled=source_page <= 1,
                        on_click=change_source_page,
                        args=(-1,),
                    )
                with nav_cols[1]:
                    st.button(
                        "Next page →",
                        key="approved_datasheet_next_page",
                        type="tertiary",
                        disabled=source_page >= max(page_count, 1),
                        on_click=change_source_page,
                        args=(1,),
                    )
                if st.session_state.pop("datasheet_qa_empty_ask", False):
                    st.warning("Enter a question about this datasheet.")
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
    ("render_bom_catalog", "standard"),
    ("render_decision_queue", "standard"),
    ("render_monitoring", "standard"),
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
