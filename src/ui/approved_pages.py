"""Approved page bodies for the Cadivor mockups.

Live workspace records fill the layout. Sample names from the mockups are not
invented when the workspace has different BOMs.
"""

from __future__ import annotations

import html
import io
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

from src.saved_bom_project import (
    NEW_PROJECT_CHOICE,
    analysis_title_for_upload,
    assign_project,
    project_choices,
    resolve_project_choice,
    split_project_and_bom,
)
from src.ui.cadivor_design_system.icons import lucide
from src.ui.navigation import internal_nav_button, navigate_to


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


_CANDIDATE_BLANK = {"", "—", "-", "–", "nan", "none", "n/a", "not available", "null"}


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
        "package": _part_field(row, "package", "Package"),
        "pin_count": row.get("pin_count") or row.get("Pin Count") or 0,
        "mounting_style": _part_field(row, "mounting_style", "Mounting Style"),
        "voltage_range": _part_field(row, "voltage_range", "Voltage Range"),
        "temperature_range": _part_field(row, "temperature_range", "Temperature Range"),
        "channel_count": row.get("channel_count") or row.get("Channel Count") or 0,
        "architecture": _part_field(row, "architecture", "Architecture"),
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
        "field_sources": row.get("field_sources") if isinstance(row.get("field_sources"), dict) else {},
        "manufacturer_part_number": _candidate_mpn(row),
    }


def _comparison_table(rows: list[tuple]) -> str:
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
        body.append(
            "<tr>"
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
        if key == "architecture" and status == "Different" and original_value and candidate_value:
            status = "Needs review"
            evidence = "The supplier category labels differ. This is not a verified functional conflict."
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
        "<p class='cv-candidate-section'>Does it technically fit?</p>"
        f"{_comparison_table(technical)}"
        "<p class='cv-candidate-section'>Supply and lifecycle risk</p>"
        f"{_comparison_table(supply_rows)}"
        f"{risk_html}"
        f"<p><strong>Next step.</strong> {_esc(next_step)}</p>"
        f"<p class='cv-candidate-links'>{links}</p>"
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
        <style>
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
        .cv-part-photo{width:72px;height:72px;border-radius:12px;background:#f1f5f9;border:1px solid #e2e8f0;display:inline-block;object-fit:cover;vertical-align:middle;margin-right:10px}
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
        .st-key-approved_home_page{box-sizing:border-box!important;width:100%!important;max-width:1440px!important;margin-left:auto!important;margin-right:auto!important;padding:48px 0 28px!important}
        .st-key-approved_home_page > [data-testid="stVerticalBlock"]{gap:22px!important}
        .cv-ap-home-kpis{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:16px!important;margin:44px 0 0!important}
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
        .st-key-approved_monitoring_alert_card{box-sizing:border-box!important;width:100%!important;margin:8px 0 20px!important;overflow-x:auto!important;border:1px solid #cbd8e8!important;border-radius:16px!important;background:#fff!important;box-shadow:0 3px 12px rgba(15,23,42,.045)!important}
        .st-key-approved_monitoring_alert_card>[data-testid="stVerticalBlock"]{gap:0!important}
        .cv-ap-monitoring-table-head{display:grid!important;grid-template-columns:.8fr 1.3fr 1.6fr .9fr 1.2fr!important;align-items:center!important;gap:12px!important;box-sizing:border-box!important;min-height:56px!important;padding:0 20px!important;background:#f7f9fc!important;border-bottom:1px solid #dce4ef!important}
        .cv-ap-monitoring-table-head [role="columnheader"]{display:flex!important;align-items:center!important;min-width:0!important;min-height:44px!important;color:#64748b!important;font-size:12px!important;font-weight:750!important;letter-spacing:.035em!important;text-transform:uppercase!important}
        .cv-ap-monitoring-table-head [role="columnheader"]:first-child,.cv-ap-monitoring-table-head [role="columnheader"]:nth-child(4),.cv-ap-monitoring-table-head [role="columnheader"]:last-child{justify-content:center!important;text-align:center!important}
        [class*="st-key-approved_monitoring_alert_row_"]{box-sizing:border-box!important;min-height:68px!important;margin:0!important;padding:9px 20px!important;border-bottom:1px solid #e5ebf3!important;background:#fff!important}
        [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stVerticalBlock"]{gap:0!important}
        [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stHorizontalBlock"]{align-items:center!important;gap:12px!important}
        [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stColumn"],[class*="st-key-approved_monitoring_alert_row_"] [data-testid="column"]{box-sizing:border-box!important;min-width:0!important;padding:4px 5px!important;display:flex!important;align-items:center!important}
        [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stMarkdownContainer"] p{margin:0!important;color:#52647b!important;font-size:13px!important;line-height:1.4!important;overflow-wrap:anywhere!important}
        [class*="st-key-approved_monitoring_alert_row_"] .cv-ap-meta{margin-top:3px!important;font-size:11px!important}
        .cv-ap-monitoring-detected{width:100%;color:#52647b;text-align:center;font-size:12px;line-height:1.35}
        [class*="st-key-approved_alert_action_"] button{min-height:34px!important;height:auto!important;padding:6px 8px!important;white-space:normal!important;font-size:12px!important}
        .cv-ap-table-center{width:100%;display:flex;align-items:center;justify-content:center;text-align:center}
        @media(max-width:1100px){
          .cv-ap-monitoring-table-head{gap:8px!important;padding:0 14px!important}
          [class*="st-key-approved_monitoring_alert_row_"]{padding:8px 14px!important}
          [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stHorizontalBlock"]{gap:8px!important}
          [class*="st-key-approved_monitoring_alert_row_"] [data-testid="stMarkdownContainer"] p{font-size:12px!important}
        }
        @media(max-width:760px){
          .cv-ap-monitoring-table-head,[class*="st-key-approved_monitoring_alert_row_"]{min-width:720px!important}
        }
        .cv-pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:3px 8px;font-size:12px;font-weight:750}
        .cv-pill-dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex:0 0 7px}
        .cv-pill.high{background:#ffe4e6;color:#be123c}
        .cv-pill.medium{background:#fef3c7;color:#b45309}
        .cv-pill.low{background:#dcfce7;color:#15803d}
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
        .cv-finding.unknown{background:#f1f5f9;color:#475569}
        .cv-candidate-unverified{margin:0 0 10px;color:#92400e;background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:8px 10px;font-size:13px}
        .cv-candidate-verified{margin:0 0 10px;color:#1e3a8a;background:#eff6ff;border:1px solid #dbeafe;border-radius:10px;padding:8px 10px;font-size:13px}
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
        [class*="st-key-approved_bom_toolbar"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap;align-items:flex-end}
        @media(max-width:1100px){
          [class*="st-key-approved_bom_toolbar"] [data-testid="stHorizontalBlock"]{flex-wrap:wrap}
          [class*="st-key-approved_bom_toolbar"] [data-testid="stColumn"]{flex:1 1 180px !important;width:auto !important;min-width:160px}
        }
        @media(max-width:900px){.cv-ap-kpis,.cv-ap-cards,.cv-ap-split{display:block}}
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
            with st.popover("⋯", help="More actions: open, edit, or delete this BOM."):
                if st.button(
                    "Open",
                    key=f"approved_{scope}_action_open_{row_key}",
                    use_container_width=True,
                ):
                    navigate_to("Analysis Details", analysis_id=target, arm_opening=False)
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


def render_saved_bom_settings(records: list[dict[str, Any]] | None, user_id: str = "") -> None:
    """Render the standalone settings page for a selected saved BOM."""
    begin_approved_page()
    rows = _rows_with_project_edits(_records(records))
    query_id = ""
    query_action = ""
    try:
        query_id = str(st.query_params.get("saved_bom_id", "") or "").strip()
        query_action = str(st.query_params.get("saved_bom_action", "") or "").strip().casefold()
    except Exception:
        pass
    edit_id = str(st.session_state.get(SAVED_BOM_EDIT_STATE) or query_id).strip()
    delete_id = str(st.session_state.get(SAVED_BOM_DELETE_STATE) or "").strip()
    if not delete_id and query_action == "delete":
        delete_id = query_id
    target_id = delete_id or edit_id
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
    if any(token in folded for token in ("resolv", "closed", "approved", "accepted")):
        return "Resolved"
    if "review" in folded:
        return "In review"
    if "over" in folded:
        return "Overdue"
    due = _parse_timestamp(_first(row, "due_date", "due_at", fallback=None))
    if due is not None and due.date() < today and "resolv" not in folded:
        return "Overdue"
    return "Open"


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
    affected = len({
        str(_first(row, "analysis_id", fallback="") or "")
        for row, _status in prepared
        if str(_first(row, "analysis_id", fallback="") or "").strip()
    })
    needle = query.strip().casefold()
    visible = []
    for row, status in prepared:
        if scope == "boms" and not str(_first(row, "analysis_id", fallback="") or "").strip():
            continue
        if status_filter != "All statuses" and status_filter.casefold() != status.casefold():
            continue
        blob = " ".join(
            str(_first(row, key, fallback="") or "")
            for key in ("mpn", "part_number", "title", "summary", "alert_message", "owner", "assignee")
        ).casefold()
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
    }


def decision_action_label(row: dict[str, Any], status: str) -> str:
    recorded = _first(row, "decision", "resolution", "decision_text", fallback=None)
    if status in {"In review", "Resolved"} or recorded:
        return "Review"
    return "Record decision"


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
) -> None:
    begin_approved_page()
    rows = _rows_with_project_edits(_records(analyses))
    high = sum(_num(_first(row, "high_risk_count")) for row in rows)
    review = sum(1 for row in rows if _num(_first(row, "high_risk_count")) or _num(_first(row, "health_score"), 100) < 80)
    health_values = [_num(_first(row, "health_score")) for row in rows]
    average = round(sum(health_values) / len(health_values)) if health_values else 0
    greeting = name or "there"
    notice = f"<p class='cv-ap-sub'>{_esc(plan_notice)}</p>" if plan_notice else ""
    with st.container(key="approved_home_page"):
        with st.container(key="approved_home_header"):
            title_col, action_col = st.columns([4.8, 1], vertical_alignment="top")
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
                    st.session_state["cadivor_bom_upload_open"] = True
                    navigate_to("BOM Analyzer")

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
                <div class="cv-ap-home-kpi-copy"><span class="cv-ap-home-kpi-label">Needs review</span><strong>{review}</strong>{review_delta}</div>
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
                with st.container(key=f"approved_home_row_{index}"):
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


def render_bom_catalog(records: list[dict[str, Any]] | None, user_id: str = "") -> None:
    begin_approved_page()
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
    with st.container(key="approved_bom_title"):
        title_col, manage_col, action_col = st.columns([4.2, 1.6, 1.6], vertical_alignment="center")
        with title_col:
            st.markdown(
                """
                <div class="cv-ap">
                  <h1>BOMs</h1>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with manage_col:
            if st.button("Manage saved BOMs", key="approved_bom_manage", type="tertiary"):
                st.session_state["cadivor_manage_saved_boms"] = True
                st.rerun()
        with action_col:
            if st.button("+ New BOM analysis", key="approved_bom_new", type="primary"):
                st.session_state["cadivor_bom_upload_open"] = True
                st.rerun()
    if st.session_state.get("cadivor_manage_saved_boms"):
        st.caption("Open a saved analysis below. New files use Analyze BOM.")
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
    with st.container(key="approved_home_recent_card"):
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
    if st.session_state.get("cadivor_bom_upload_open"):
        choices = [*project_choices(rows), NEW_PROJECT_CHOICE]
        selected_project = st.selectbox(
            "Project",
            choices,
            key="approved_bom_project_choice",
            help="Choose a saved project, or enter a new name. Leave a new name blank to use General.",
        )
        typed_project = ""
        if selected_project == NEW_PROJECT_CHOICE:
            typed_project = st.text_input(
                "New project name",
                key="approved_bom_project_name",
                placeholder="Leave blank to use General",
            )
        bom_name = st.text_input("BOM name", key="approved_bom_name")
        uploaded = st.file_uploader(
            "Upload your BOM file",
            type=["csv", "xlsx"],
            key="bom_file_uploader",
            help="CSV or Excel with MPN and Quantity columns.",
        )
        if st.button("Analyze BOM", key="approved_bom_analyze", type="primary") and uploaded is not None:
            st.session_state["cadivor_bom_analysis_ready"] = True
            st.session_state["cadivor_pending_upload"] = uploaded
            st.session_state["cadivor_pending_project"] = resolve_project_choice(
                selected_project,
                typed_project,
                blank_uses_general=True,
            )
            st.session_state["cadivor_pending_bom_name"] = bom_name
            return
        if uploaded is None:
            st.caption("Choose a CSV or Excel file to run the existing BOM analysis.")
    if st.session_state.get("cadivor_bom_analysis_ready"):
        return
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
          <p class="cv-ap-sub">Track and resolve key engineering decisions that impact your products, BOMs and supply chain.</p>
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
                        st.rerun()
    with st.container(key="approved_decision_queue"):
        heading, search_col, filter_col, sort_col = st.columns(
            [1.5, 2.1, 0.9, 0.9],
            vertical_alignment="bottom",
        )
        with search_col:
            query = st.text_input(
                "Search",
                key="approved_decision_search",
                placeholder="Search components, decisions or owners",
                label_visibility="collapsed",
            )
        with filter_col:
            status_filter = st.selectbox(
                "Filter",
                ["All statuses", "Open", "Overdue", "In review", "Resolved"],
                key="approved_decision_filter",
                on_change=lambda: st.session_state.__setitem__("approved_decision_scope", ""),
            )
        with sort_col:
            sort_by = st.selectbox(
                "Sort",
                ["Due date", "Risk level", "Component"],
                key="approved_decision_sort",
            )
        view = decision_queue_view(
            records,
            query=query,
            status_filter=status_filter,
            sort_by=sort_by,
            scope=str(st.session_state.get("approved_decision_scope") or ""),
            today=date.today(),
        )
        with heading:
            st.markdown(f"<h2>Decision queue ({len(view['rows'])})</h2>", unsafe_allow_html=True)
        widths = [1.6, 1.7, 0.8, 1.0, 0.9, 0.9, 1.1]
        header = st.columns(widths)
        for column, label in zip(header, ("Component", "Title", "Risk level", "Decision status", "Owner", "Due date", "Actions")):
            column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
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
            owner = _first(row, "owner", "assignee", fallback=None)
            owner_label = "Unassigned" if owner is None else _esc(owner)
            mpn = str(_first(row, "mpn", "part_number", "component", fallback="Not recorded"))
            detail = _first(row, "description", "part_description", fallback=None)
            subtitle = f"<div class='cv-ap-meta'>{_esc(detail)}</div>" if detail else ""
            due = _first(row, "due_date", "due_at", fallback=None)
            if not due:
                due_label = "Not recorded"
            else:
                due_text = analyzed_label(due).split("<br>", 1)[0]
                due_label = f"<span class='cv-due-late'>{due_text}</span>" if status == "Overdue" else due_text
            title = _first(row, "title", "summary", "alert_message", fallback=None)
            title_label = "Not recorded" if title is None else _esc(title)
            photo = part_photo(str(_first(row, "image_url", "photo_url", "image", fallback="") or ""), size=40, part=row)
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
                analysis_id = str(row.get("analysis_id") or "")
                action = decision_action_label(row, status)
                with cells[6]:
                    button_type = "primary" if action == "Review" else "secondary"
                    button_key = (
                        f"approved_decision_review_{index}"
                        if action == "Review"
                        else f"approved_decision_record_{index}"
                    )
                    if st.button(action, key=button_key, type=button_type):
                        st.session_state["cadivor_decision_focus_mpn"] = mpn
                        if analysis_id:
                            st.session_state["cadivor_active_analysis_id"] = analysis_id
                            st.session_state["analysis_id"] = analysis_id
                            if action == "Record decision":
                                st.session_state["cadivor_pending_analysis_section"] = "Engineering Decisions"
                                st.session_state["cadivor_pending_analysis_section_id"] = analysis_id
                                navigate_to(
                                    "Analysis Details",
                                    analysis_id=analysis_id,
                                    analysis_tab="Engineering Decisions",
                                    component=mpn,
                                )
                            else:
                                navigate_to("Analysis Details", analysis_id=analysis_id)
    end_approved_page()


def _alert_slots(source: list[dict[str, Any]], predicate) -> list[float | None]:
    counts: dict[str, int] = {}
    for item in source:
        if not predicate(item):
            continue
        day = str(_first(item, "created_at", fallback=""))[:10]
        if not day:
            continue
        counts[day] = counts.get(day, 0) + 1
    slots: list[float | None] = [None] * 12
    for index, day in enumerate(sorted(counts)[:12]):
        slots[index] = float(counts[day])
    return slots


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


def _next_action(row: dict[str, Any]) -> tuple[str, str]:
    category = _alert_category(row)
    if category == "Lifecycle":
        return "Review alternatives", "Alternative Finder"
    if category == "Stock & supply":
        return "View suppliers", "Procurement Advisor"
    if category == "Price movement":
        return "View pricing", "Cost Optimization"
    return "View details", "Monitoring"


def render_monitoring(alerts: list[dict[str, Any]] | None) -> None:
    begin_approved_page()
    source = _records(alerts)
    st.markdown(
        """
        <div class="cv-ap">
          <h1>Alerts & monitoring</h1>
          <p class="cv-ap-sub">Stay ahead of changes in component availability, lifecycle status, pricing and supplier activity.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    selected = st.segmented_control(
        "Show",
        ["All alerts", "Stock & supply", "Lifecycle", "Price movement", "Supplier", "Quality", "Regulatory"],
        default="All alerts",
        key="approved_alert_category",
    )
    period = st.selectbox("Time period", ["All recorded", "Last 30 days"], key="approved_alert_period")
    rows = source
    if selected and selected != "All alerts":
        rows = [row for row in rows if _alert_category(row) == selected]
    if period == "Last 30 days":
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        rows = [row for row in rows if str(_first(row, "created_at", fallback=""))[:10] >= cutoff]
    rows = rows[:8]
    high = sum(1 for row in source if "high" in str(_first(row, "severity", fallback="")).casefold())
    lifecycle_count = sum(1 for row in source if _alert_category(row) == "Lifecycle")
    inventory_count = sum(1 for row in source if _alert_category(row) == "Stock & supply")
    active_spark = spark_slots(_alert_slots(source, lambda _row: True), "#2563eb")
    high_spark = spark_slots(_alert_slots(source, lambda row: "high" in str(_first(row, "severity", fallback="")).casefold()), "#e11d48")
    life_spark = spark_slots(_alert_slots(source, lambda row: _alert_category(row) == "Lifecycle"), "#d97706")
    stock_spark = spark_slots(_alert_slots(source, lambda row: _alert_category(row) == "Stock & supply"), "#16a34a")
    st.markdown(
        f"""
        <div class="cv-ap">
          <section class="cv-ap-kpis">
            <article class="cv-ap-kpi cv-ap-kpi-row"><div><span>Active alerts</span><strong>{len(source)}</strong></div>{active_spark}</article>
            <article class="cv-ap-kpi cv-ap-kpi-row"><div><span>High priority</span><strong>{high}</strong></div>{high_spark}</article>
            <article class="cv-ap-kpi cv-ap-kpi-row"><div><span>Lifecycle changes</span><strong>{lifecycle_count}</strong></div>{life_spark}</article>
            <article class="cv-ap-kpi cv-ap-kpi-row"><div><span>Inventory updates</span><strong>{inventory_count}</strong></div>{stock_spark}</article>
          </section>
          <p class="cv-ap-meta">Each sparkline is a 12-bucket frame. Only recorded alert dates are drawn. Empty buckets are a data limitation: no alert history is stored for those periods.</p>
          <h2>Recent alerts</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )
    monitoring_widths = [0.8, 1.3, 1.6, 0.9, 1.2]
    with st.container(key="approved_monitoring_alert_card"):
        header_labels = ("Severity", "Component", "Signal", "Detected", "Next action")
        header_cells = "".join(
            f"<span role='columnheader'>{_esc(label)}</span>"
            for label in header_labels
        )
        st.markdown(
            f"<div class='cv-ap-monitoring-table-head' role='row'>{header_cells}</div>",
            unsafe_allow_html=True,
        )
        if not rows:
            st.markdown(
                "<div class='cv-ap-home-empty'>No alerts in the selected period.</div>",
                unsafe_allow_html=True,
            )
        for index, row in enumerate(rows):
            severity = str(_first(row, "severity", fallback="Low"))
            kind = "high" if "high" in severity.casefold() else ("medium" if "med" in severity.casefold() else "low")
            action_label, destination = _next_action(row)
            with st.container(key=f"approved_monitoring_alert_row_{index}"):
                cells = st.columns(monitoring_widths, vertical_alignment="center")
                cells[0].markdown(
                    f"<span class='cv-pill {kind}'>{_esc(severity)}</span>",
                    unsafe_allow_html=True,
                )
                cells[1].markdown(
                    f"<div class='cv-ap-name'>{_esc(_first(row, 'mpn', 'part_number', fallback='Component'))}</div>",
                    unsafe_allow_html=True,
                )
                cells[2].markdown(
                    f"<div class='cv-ap-name'>{_esc(_first(row, 'alert_type', fallback='Update'))}</div>"
                    f"<div class='cv-ap-meta'>{_esc(_first(row, 'alert_message', fallback=''))}</div>",
                    unsafe_allow_html=True,
                )
                cells[3].markdown(
                    f"<div class='cv-ap-monitoring-detected'>{_esc(str(_first(row, 'created_at', fallback=''))[:10])}</div>",
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
    end_approved_page()


def render_reports_list(records: list[dict[str, Any]] | None) -> None:
    begin_approved_page()
    rows = _records(records)[:8]
    templates = (
        ("Executive BOM Report", "High-level summary of cost, supply risk and key insights for stakeholders.", ("DOCX", "XLSX", "PPTX")),
        ("Engineering Risk Review", "Detailed assessment of supply, obsolescence and compliance risks across your BOM.", ("DOCX", "XLSX")),
        ("Sourcing Summary", "Supplier options, cost comparison and recommended sourcing strategies.", ("XLSX", "PPTX")),
    )
    cards = []
    for title, copy, formats in templates:
        chips = "".join(f"<span class='cv-ap-chip'>{fmt}</span>" for fmt in formats)
        cards.append(f"<article class='cv-ap-template'><h3>{title}</h3><p>{copy}</p><div>Formats {chips}</div></article>")
    st.markdown(
        f"""
        <div class="cv-ap">
          <p class="cv-ap-kicker">REPORTS</p>
          <h1>Engineering reports</h1>
          <p class="cv-ap-sub">Create tailored reports from your engineering data and analysis results.</p>
          <h2>Report templates</h2>
          <section class="cv-ap-cards">{''.join(cards)}</section>
          <h2>Recent report sources</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="approved_report_head"):
        header = st.columns([1.8, 1.4, 1.1, 0.9, 1, 0.6])
        for column, label in zip(header, ("Name", "Source", "Last updated", "Health score", "High-risk parts", "Actions")):
            column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
    if not rows:
        st.caption("Upload a BOM analysis to populate recent report sources.")
    for index, row in enumerate(rows):
        score = _num(_first(row, "health_score"))
        with st.container(key=f"approved_report_row_{index}"):
            cells = st.columns([1.8, 1.4, 1.1, 0.9, 1, 0.6], vertical_alignment="center")
            cells[0].markdown(
                f"<div class='cv-ap-name'>{_esc(_first(row, 'project_name', 'name', fallback='Saved BOM'))}</div><div class='cv-ap-meta'>BOM Analysis</div>",
                unsafe_allow_html=True,
            )
            cells[1].markdown(_esc(_first(row, "filename", fallback="—")))
            cells[2].markdown(_esc(str(_first(row, "created_at", fallback=""))[:10]))
            cells[3].markdown(str(score))
            cells[4].markdown(str(_num(_first(row, "high_risk_count"))))
            analysis_id = str(row.get("id") or "")
            with cells[5]:
                if analysis_id:
                    internal_nav_button(
                        "Open",
                        "Analysis Details",
                        key=f"approved_report_open_{index}",
                        type="primary",
                        analysis_id=analysis_id,
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


def part_photo(url: str = "", size: int = 72, part: dict[str, Any] | None = None) -> str:
    """Supplier photo, or a category illustration labeled as artwork."""
    from src.part_images import part_image_markup

    return part_image_markup(url, "", size=size, part=part)


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
    """Twelve-bucket sparkline frame. None leaves that period empty; it is not drawn as zero."""
    buckets = 12
    slots = list(values[:buckets])
    while len(slots) < buckets:
        slots.append(None)
    recorded = [value for value in slots if value is not None]
    peak = max(recorded) if recorded else 1.0
    marks = [
        '<rect x="0" y="0" width="84" height="36" rx="8" fill="#f8fafc"/>',
        '<line x1="4" y1="30" x2="80" y2="30" stroke="#e2e8f0" stroke-width="1"/>',
    ]
    for index, value in enumerate(slots):
        x = 4 + index * 6.5
        if value is None:
            continue
        height = max(8.0, 22.0 * (float(value) / (peak or 1.0)))
        marks.append(
            f'<rect x="{x:.1f}" y="{30 - height:.1f}" width="3" height="{height:.1f}" rx="1" fill="{color}"/>'
        )
    return (
        f'<svg class="cv-ap-spark" viewBox="0 0 84 36" width="84" height="36" aria-hidden="true">{"".join(marks)}</svg>'
    )


ICO_DOC = '<svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="1.8"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/></svg>'
ICO_WARN = '<svg viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="1.8"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>'
ICO_RISK = '<svg viewBox="0 0 24 24" fill="none" stroke="#e11d48" stroke-width="1.8"><path d="M12 3l7 3v6c0 5-3 8-7 9-4-1-7-4-7-9V6z"/></svg>'
ICO_HEALTH = '<svg viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="1.8"><path d="M3 12h4l2-5 4 10 2-5h6"/></svg>'


def impact_map_html(
    *,
    part: str,
    projects: list[tuple[str, str]],
    supplier: str = "",
    supplier_count: str = "",
    lifecycle: str = "",
) -> str:
    """Node diagram. Connectors join only the live part, project, BOM, supplier, and lifecycle."""
    nodes = []
    y = 24
    for project, bom in projects[:4]:
        nodes.append((220, y, project or "Project not recorded", "#eef2ff", "#6366f1"))
        nodes.append((460, y, bom or "BOM file not recorded", "#f5f3ff", "#7c3aed"))
        y += 64
    supplier_label = supplier or ("Supplier name not recorded" if supplier_count else "Not recorded")
    if supplier or supplier_count:
        nodes.append((220, y, supplier_label, "#ecfdf5", "#059669"))
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
            f'<rect x="{x}" y="{node_y}" width="180" height="44" rx="10" fill="{fill}" stroke="{stroke}"/>'
            f'<text x="{x+12}" y="{node_y+27}" font-size="12" fill="#0f172a">{html.escape(label)[:26]}</text>'
        )
    return (
        "<section class='cv-ap-card'><h2>Impact map</h2>"
        f'<svg viewBox="0 0 680 {height}" width="100%" height="{height}" role="img" aria-label="Impact map">'
        f'{"".join(paths)}{"".join(boxes)}</svg></section>'
    )


def procurement_header_html(part: dict[str, Any]) -> str:
    """Specification strip. Missing price and savings stay unavailable."""
    mpn = html.escape(str(part.get("mpn") or part.get("part_number") or "Part"))
    maker = html.escape(str(part.get("manufacturer") or "Not recorded"))
    description = html.escape(str(part.get("description") or "Not recorded"))
    lifecycle = html.escape(str(part.get("lifecycle_status") or "Not recorded"))
    category = html.escape(str(part.get("category") or "Not recorded"))
    price = part.get("unit_price")
    price_label = "Not recorded" if price in (None, "") else html.escape(str(price))
    photo = part_photo(str(part.get("image_url") or part.get("photo_url") or ""), part=part)
    savings = "Not recorded" if price in (None, "") else "Recorded price has no savings comparison"
    fields = (
        ("MPN", mpn),
        ("Manufacturer", maker),
        ("Description", description),
        ("Lifecycle", lifecycle),
        ("Category", category),
        ("Unit price", price_label),
        ("Last updated", "Not recorded"),
    )
    cells = "".join(
        f"<div><p class='cv-ap-meta'>{label}</p><strong>{value}</strong></div>"
        for label, value in fields
    )
    return (
        "<section class='cv-part-head' style='display:flex;gap:16px;align-items:center;background:#fff;border:1px solid #e6edf5;border-radius:16px;padding:16px 18px;margin-bottom:12px'>"
        f"{photo}<div style='display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:12px;flex:1'>{cells}</div></section>"
        "<section class='cv-ap-banner'><p class='cv-ap-meta'>Recommendation</p><h2>Review supplier coverage</h2>"
        f"<p>Savings {savings}. No second-source price is stored for this part.</p></section>"
    )


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


def render_replacement_search() -> None:
    """Find-a-replacement layout wired to the live alternative search."""
    begin_approved_page()
    st.session_state.setdefault(
        "approved_replacement_query",
        str(st.session_state.get("cadivor_replacement_query") or ""),
    )
    search_col, button_col = st.columns([4, 1], vertical_alignment="bottom")
    with search_col:
        query = st.text_input("Search MPN", key="approved_replacement_query")
    with button_col:
        run = st.button("Search", key="approved_replacement_search", type="primary")
    query = str(query or st.session_state.get("approved_replacement_query") or "").strip()
    result = st.session_state.get("alternative_finder_result")
    if run and query:
        from src.alternative_finder_search import run_alternative_finder_search

        run_alternative_finder_search(st.session_state, query)
        result = st.session_state.get("alternative_finder_result")
    original = {}
    candidates: list[dict[str, Any]] = []
    if isinstance(result, dict):
        original = result.get("original_data") if isinstance(result.get("original_data"), dict) else {}
        raw_candidates = result.get("candidates") or result.get("alternative_candidates") or []
        candidates = [row for row in raw_candidates if isinstance(row, dict)]
    fit_filter, life_filter, stock_filter, risk_filter, sort_by = st.columns(5)
    with fit_filter:
        fit_choice = st.selectbox("Parametric fit", ["All"], key="approved_fit_filter")
    with life_filter:
        life_choice = st.selectbox("Lifecycle", ["All", "Active", "NRND", "Obsolete"], key="approved_life_filter")
    with stock_filter:
        stock_choice = st.selectbox("Stock", ["All", "In stock", "No stock"], key="approved_stock_filter")
    with risk_filter:
        risk_choice = st.selectbox("Risk", ["All", "High", "Medium", "Low"], key="approved_risk_filter")
    with sort_by:
        sort_choice = st.selectbox("Sort by", ["Overall match", "Stock", "Risk"], key="approved_replacement_sort")
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
    candidates = named
    del fit_choice
    mpn = _esc(original.get("manufacturer_part_number") or original.get("mpn") or (query or "Search an MPN"))
    manufacturer = _esc(original.get("manufacturer") or original.get("Manufacturer") or original.get("manufacturer_name") or "—")
    description = _esc(original.get("description") or original.get("category") or "")
    notice = ""
    lookup_error = ""
    search_error = ""
    candidate_status = ""
    if isinstance(result, dict):
        lookup_error = str(result.get("lookup_error") or "").strip()
        search_error = str(result.get("search_error") or "").strip()
        discovery = result.get("discovery_metadata")
        if isinstance(discovery, dict):
            candidate_status = str(discovery.get("candidate_status") or "").strip()
    source_notice = lookup_error
    candidate_notice = ""
    if query.strip() and isinstance(result, dict) and not candidates:
        candidate_notice = search_error or candidate_status or "No replacement candidates were returned for this part."
    elif dropped:
        candidate_notice = (
            f"{dropped} supplier row{'s' if dropped != 1 else ''} had no part number "
            f"and {'were' if dropped != 1 else 'was'} left out."
        )
    notice = candidate_notice
    shown = candidates[:25]
    if len(candidates) > len(shown) and not notice:
        notice = f"Showing {len(shown)} of {len(candidates)} supplier alternatives."
    notice_html = f"<p class='cv-ap-sub'>{_esc(notice)}</p>" if notice and shown else ""
    if not shown and not notice:
        notice_html = "<p class='cv-ap-sub'>Search a manufacturer part number. Results come from the live supplier search.</p>"
    elif not shown and notice:
        notice_html = f"<p class='cv-ap-sub'>{_esc(notice)}</p>"
    source_html = f"<p class='cv-ap-sub'>{_esc(source_notice)}</p>" if source_notice else ""
    st.markdown(
        f"""
        <div class="cv-ap">
          <h1>Find a replacement</h1>
          <p class="cv-ap-sub">Search for a part to find compatible alternatives across suppliers.</p>
          {source_html}
          <section class="cv-ap-card">
            <div class="cv-ap-meta">Source part</div>
            <div class="cv-ei-part">{part_photo(str(original.get('image_url') or original.get('photo_url') or ''), part=original)}<span class="cv-ei-part-copy"><span class="cv-ap-name">{mpn}</span><span class="cv-ei-meta">{description}</span></span></div>
            <p>Manufacturer {manufacturer}</p>
          </section>
          {notice_html}
          <h2>Replacement options ({len(candidates)})</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )
    from src.part_images import part_image_markup

    header = st.columns([2.4, 1.3, 1.8, 0.9, 0.8, 0.9, 0.7])
    for column, label in zip(
        header,
        ("Candidate MPN", "Manufacturer", "Parametric fit", "Lifecycle", "Stock", "Suppliers", "Risk"),
    ):
        column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
    selected = str(st.session_state.get("cadivor_replacement_open_mpn") or "")
    for index, row in enumerate(shown):
        candidate_mpn = _candidate_mpn(row)
        is_open = candidate_mpn == selected
        level = _candidate_field(row, "Estimated Risk", "risk_level", "risk", fallback="Unknown")
        pill = ""
        if "high" in level.casefold():
            pill = "high"
        elif "low" in level.casefold():
            pill = "low"
        elif "medium" in level.casefold():
            pill = "medium"
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
                cells[2].markdown(_candidate_field(row, "Classification", "Category", "fit", "parametric_fit"))
                cells[3].markdown(_candidate_field(row, "Lifecycle", "lifecycle_status", "lifecycle"))
                cells[4].markdown(_candidate_field(row, "Stock", "stock_total", "stock_available"))
                cells[5].markdown(_candidate_field(row, "Supplier", "supplier_count", "supplier"))
                cells[6].markdown(level_html, unsafe_allow_html=True)
            if is_open:
                st.markdown(_candidate_detail_html(row, original), unsafe_allow_html=True)
    for index, row in enumerate(candidates[:5]):
        candidate = _candidate_mpn(row)
        if candidate and st.button(f"Compare {candidate}", key=f"approved_replacement_compare_{index}"):
            st.session_state["cadivor_compare_part_a"] = str(original.get("manufacturer_part_number") or query or "")
            st.session_state["cadivor_compare_part_b"] = candidate
            navigate_to("Compare Parts")
    end_approved_page()


def render_compare_live() -> None:
    """Compare-parts layout wired to the live two-part comparison."""
    begin_approved_page()
    from src.parts_compare import resolve_compare_parts_submitted_mpn, run_compare_parts

    st.session_state.setdefault("approved_compare_a", str(st.session_state.get("cadivor_compare_part_a") or ""))
    st.session_state.setdefault("approved_compare_b", str(st.session_state.get("cadivor_compare_part_b") or ""))
    st.markdown(
        """
        <div class="cv-ap">
          <p class="cv-ap-kicker">PARTS</p>
          <h1>Compare parts</h1>
          <p class="cv-ap-sub">Compare key parameters, identify differences, and find the best fit for your design.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("approved_compare_form", clear_on_submit=False):
        left, right = st.columns(2)
        with left:
            entered_a = st.text_input("Part A", key="approved_compare_a")
        with right:
            entered_b = st.text_input("Part B", key="approved_compare_b")
        submitted = st.form_submit_button(
            "Compare parts",
            type="primary",
            key="approved_compare_run",
        )
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
    if submitted:
        if part_a and part_b:
            try:
                st.session_state["cadivor_compare_result"] = run_compare_parts(part_a, part_b)
            except Exception:
                st.session_state["cadivor_compare_result"] = {
                    "status": "failed",
                    "part_a": part_a,
                    "part_b": part_b,
                    "error": "Cadivor could not complete this comparison right now. Please try again.",
                }
        else:
            st.session_state["cadivor_compare_result"] = {
                "status": "failed",
                "part_a": part_a,
                "part_b": part_b,
                "error": "Enter both Part A and Part B manufacturer part numbers.",
            }
    result = st.session_state.get("cadivor_compare_result")
    comparison = result.get("comparison") if isinstance(result, dict) else {}
    if not isinstance(comparison, dict):
        comparison = {}
    counts = comparison.get("counts") if isinstance(comparison.get("counts"), dict) else {}
    card_a = comparison.get("part_a") if isinstance(comparison.get("part_a"), dict) else {}
    card_b = comparison.get("part_b") if isinstance(comparison.get("part_b"), dict) else {}
    rows = comparison.get("rows") if isinstance(comparison.get("rows"), list) else []
    body = []
    missing = {"", "—", "-", "–", "not available", "not recorded", "n/a", "none", "nan"}

    def _recorded(row: dict[str, Any], *keys: str) -> str:
        for key in keys:
            text = str(row.get(key) or "").strip()
            if text and text.casefold() not in missing:
                return text
        return ""

    for row in rows[:24]:
        if not isinstance(row, dict):
            continue
        label = _recorded(row, "Attribute", "label", "parameter", "field")
        if not label or label.casefold() == "parameter":
            continue
        raw_a = _recorded(row, "Part A", "part_a", "a", "value_a", "Original")
        raw_b = _recorded(row, "Part B", "part_b", "b", "value_b", "Candidate")
        if not raw_a and not raw_b:
            continue
        value_a = _esc(raw_a or "Not recorded")
        value_b = _esc(raw_b or "Not recorded")
        highlight = " style='background:#eff6ff'" if raw_a != raw_b else ""
        assessment = _recorded(row, "Assessment", "Result", "Status")
        note = f"<div class='cv-ap-meta'>{_esc(assessment)}</div>" if assessment else ""
        body.append(
            f"<tr><td>{_esc(label)}{note}</td><td{highlight}>{value_a}</td><td{highlight}>{value_b}</td><td></td></tr>"
        )
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
            empty = "Enter two manufacturer part numbers. The third column stays empty until another part is added."
    else:
        empty = ""
    submitted_a = str(result.get("part_a") or "") if isinstance(result, dict) else ""
    submitted_b = str(result.get("part_b") or "") if isinstance(result, dict) else ""
    name_a = _esc(card_a.get("mpn") or submitted_a or part_a or "Part A")
    name_b = _esc(card_b.get("mpn") or submitted_b or part_b or "Part B")
    notice = ""
    table = (
        f"<p class='cv-ap-sub'>{_esc(empty)}</p>"
        if empty
        else (
            "<section class='cv-ap-card'><table class='cv-ap-table'><thead><tr>"
            f"<th>Parameter</th><th>{name_a}</th><th>{name_b}</th><th>Part C</th>"
            f"</tr></thead><tbody>{''.join(body)}</tbody></table></section>"
        )
    )
    figures = ""
    if comparison:
        figures = (
            "<section class='cv-ap-kpis three'>"
            f"<article class='cv-ap-kpi'><span>Compatible fields</span><strong>{_esc(counts.get('compatible', '—'))}</strong></article>"
            f"<article class='cv-ap-kpi'><span>Material differences</span><strong>{_esc(counts.get('material_difference', '—'))}</strong></article>"
            f"<article class='cv-ap-kpi'><span>Needs validation</span><strong>{_esc(counts.get('needs_data', '—'))}</strong></article>"
            "</section>"
        )
    st.markdown(
        f"""
        <div class="cv-ap">
          {notice}
          {figures}
          <section class="cv-ap-cards">
            <article class="cv-ap-template"><div class="cv-ei-part">{part_photo(str(card_a.get('image_url') or card_a.get('photo_url') or ''), size=48, part=card_a)}<span class="cv-ei-part-copy"><h3>{name_a}</h3><p>{_esc(card_a.get('description') or card_a.get('manufacturer') or 'Not recorded')}</p></span></div></article>
            <article class="cv-ap-template"><div class="cv-ei-part">{part_photo(str(card_b.get('image_url') or card_b.get('photo_url') or ''), size=48, part=card_b)}<span class="cv-ei-part-copy"><h3>{name_b}</h3><p>{_esc(card_b.get('description') or card_b.get('manufacturer') or 'Not recorded')}</p></span></div></article>
            <article class="cv-ap-template"><div class="cv-ei-part">{part_photo('', size=48)}<span class="cv-ei-part-copy"><h3>Add part</h3><p>No third candidate is selected.</p></span></div></article>
          </section>
          {table}
        </div>
        """,
        unsafe_allow_html=True,
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
