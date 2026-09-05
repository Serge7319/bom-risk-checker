"""Neutral engineering comparison of any two manufacturer part numbers.

This is not Alternative Finder. It reuses family profiles, parametric compare,
and supplier aggregation without recommending substitutes or exposing provider
diagnostics to customers.
"""
from __future__ import annotations

import time
from typing import Any, Mapping, MutableMapping

from src.component_family_profiles import get_family_profile, infer_family_id
from src.datasheet_comparison import (
    build_datasheet_comparison,
    build_engineering_evidence_assessment,
    diagnostic_comparison_rows,
    user_facing_comparison_rows,
    user_may_view_comparison_diagnostics,
)
from src.parametric_compare import engineering_confidence_from_rows


FINDING_COMPATIBLE = "Compatible on available evidence"
FINDING_MATERIAL = "Material difference"
FINDING_NEEDS_DATA = "Needs data / engineering validation"

COMPARE_PARTS_RESULT_KEY = "compare_parts_result"
COMPARE_PARTS_LAST_SUBMIT_KEY = "compare_parts_last_submit"
COMPARE_PARTS_LAST_SUBMIT_AT_KEY = "compare_parts_last_submit_at"
COMPARE_PARTS_SUBMIT_DEBOUNCE_SECONDS = 2.0

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

USER_FACING_COMPARE_COLUMNS = (
    "Attribute",
    "Part A",
    "Part B",
    "Assessment",
    "Evidence",
)


def _normalize_mpn(value: Any) -> str:
    return str(value or "").strip().upper()


def claim_compare_parts_submit(
    session_state: MutableMapping[str, Any],
    part_a: str,
    part_b: str,
    *,
    debounce_seconds: float = COMPARE_PARTS_SUBMIT_DEBOUNCE_SECONDS,
    now: float | None = None,
) -> bool:
    """Claim one Compare Parts submit; reject empty, in-flight, or duplicate bursts."""
    a = _normalize_mpn(part_a)
    b = _normalize_mpn(part_b)
    if not a or not b:
        return False
    token = f"{a}|{b}"
    result = session_state.get(COMPARE_PARTS_RESULT_KEY)
    if isinstance(result, dict) and str(result.get("status") or "") == STATUS_RUNNING:
        prior = f"{_normalize_mpn(result.get('part_a'))}|{_normalize_mpn(result.get('part_b'))}"
        if prior == token:
            return False
    current = float(time.time() if now is None else now)
    last_token = str(session_state.get(COMPARE_PARTS_LAST_SUBMIT_KEY) or "")
    try:
        last_at = float(session_state.get(COMPARE_PARTS_LAST_SUBMIT_AT_KEY) or 0.0)
    except (TypeError, ValueError):
        last_at = 0.0
    if last_token == token and last_at > 0.0 and (current - last_at) < float(debounce_seconds):
        return False
    session_state[COMPARE_PARTS_LAST_SUBMIT_KEY] = token
    session_state[COMPARE_PARTS_LAST_SUBMIT_AT_KEY] = current
    return True


def map_status_to_assessment(status: str) -> str:
    normalized = str(status or "").strip()
    if normalized == "Match":
        return FINDING_COMPATIBLE
    if normalized == "Different":
        return FINDING_MATERIAL
    return FINDING_NEEDS_DATA


def user_facing_compare_rows(rows: list | None) -> list[dict]:
    """Project comparison rows to Part A / Part B columns without internal metadata."""
    projected: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("Status") or row.get("Result") or "")
        projected.append(
            {
                "Attribute": row.get("Attribute", ""),
                "Part A": row.get("Original", row.get("Part A", "")),
                "Part B": row.get(
                    "Candidate",
                    row.get("Part B", row.get("Selected Alternative", "")),
                ),
                "Assessment": map_status_to_assessment(status),
                "Evidence": row.get("Evidence", ""),
            }
        )
    return projected


def public_part_card(part: Mapping[str, Any] | None, *, family: str = "") -> dict[str, Any]:
    """Customer-safe identity fields only (no provider diagnostics)."""
    data = dict(part or {})
    profile = get_family_profile(family or infer_family_id(data))
    mpn = str(
        data.get("manufacturer_part_number")
        or data.get("Manufacturer Part Number")
        or ""
    ).strip()
    datasheet = str(data.get("datasheet_url") or "").strip()
    detail = str(data.get("product_detail_url") or "").strip()
    return {
        "mpn": mpn,
        "manufacturer": str(data.get("manufacturer") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "family": profile.id,
        "family_display_name": profile.display_name,
        "package": str(data.get("package") or "").strip(),
        "lifecycle_status": str(data.get("lifecycle_status") or "Unknown").strip() or "Unknown",
        "datasheet_url": datasheet if datasheet.startswith(("http://", "https://")) else "",
        "supplier_url": detail if detail.startswith(("http://", "https://")) else "",
        "found": bool(mpn),
    }


def resolve_comparison_family(part_a: Mapping[str, Any], part_b: Mapping[str, Any]) -> dict[str, Any]:
    """Choose the shared family profile used for attribute comparison."""
    family_a = infer_family_id(part_a)
    family_b = infer_family_id(part_b)
    if family_a == family_b:
        return {
            "family": family_a,
            "family_mismatch": False,
            "family_a": family_a,
            "family_b": family_b,
        }
    if family_a == "General" and family_b != "General":
        return {
            "family": family_b,
            "family_mismatch": False,
            "family_a": family_a,
            "family_b": family_b,
        }
    if family_b == "General" and family_a != "General":
        return {
            "family": family_a,
            "family_mismatch": False,
            "family_a": family_a,
            "family_b": family_b,
        }
    return {
        "family": "General",
        "family_mismatch": True,
        "family_a": family_a,
        "family_b": family_b,
    }


def derive_overall_finding(
    *,
    matches: int,
    differences: int,
    needs_data: int,
    evidence_status: str,
    family_mismatch: bool,
    requires_pinout_for_dropin: bool,
    pinout_matched: bool,
    required_missing: int = 0,
    required_differences: int = 0,
) -> str:
    """Map engineering coverage to a clear customer finding. Never invent a match."""
    if family_mismatch:
        return FINDING_MATERIAL
    if differences > 0 or required_differences > 0:
        return FINDING_MATERIAL
    if requires_pinout_for_dropin and not pinout_matched:
        return FINDING_NEEDS_DATA
    if matches <= 0 or required_missing > 0:
        return FINDING_NEEDS_DATA
    # Required attributes matched and no material differences: compatible on what
    # is available. Optional gaps remain visible as Needs data in the matrix.
    if differences == 0 and matches > 0:
        return FINDING_COMPATIBLE
    status = str(evidence_status or "").strip().casefold()
    if status in {"incomplete"} or (matches <= 1 and needs_data >= 5):
        return FINDING_NEEDS_DATA
    return FINDING_NEEDS_DATA


def _pinout_matched(rows: list[dict]) -> bool:
    for row in rows or []:
        key = str(row.get("Key") or "")
        label = str(row.get("Attribute") or "").casefold()
        if key == "pinout" or "pinout" in label:
            return str(row.get("Status") or "") == "Match"
    return False


def build_parts_comparison(
    part_a: Mapping[str, Any],
    part_b: Mapping[str, Any],
    *,
    part_a_mpn: str = "",
    part_b_mpn: str = "",
) -> dict[str, Any]:
    """Build a neutral family-aware comparison between two retrieved parts."""
    family_meta = resolve_comparison_family(part_a, part_b)
    family = str(family_meta["family"])
    profile = get_family_profile(family)

    # Force family used by datasheet comparison by tagging Part A when families align
    # through General fallback; build_datasheet_comparison infers from Part A.
    part_a_for_compare = dict(part_a)
    if not family_meta["family_mismatch"] and infer_family_id(part_a_for_compare) == "General":
        part_a_for_compare["description"] = (
            f"{part_a_for_compare.get('description') or ''} {profile.display_name}"
        ).strip()

    comparison = build_datasheet_comparison(dict(part_a_for_compare), dict(part_b))
    if family_meta["family_mismatch"]:
        # Re-run on General so only shared mechanical fields are compared.
        from src.component_family_profiles import comparison_fields
        from src.parametric_compare import compare_field_values

        fields = comparison_fields(get_family_profile("General"))
        rows: list[dict] = []
        counts = {"Match": 0, "Different": 0, "Needs data": 0}
        for spec in fields:
            a_val = str(part_a.get(spec.key) or "").strip()
            b_val = str(part_b.get(spec.key) or "").strip()
            if spec.key == "pin_count":
                from integrations.pin_count import effective_pin_count

                a_count = effective_pin_count(part_a)
                b_count = effective_pin_count(part_b)
                a_val = str(a_count) if a_count > 0 else ""
                b_val = str(b_count) if b_count > 0 else ""
            status, note = compare_field_values(a_val, b_val, spec)
            counts[status] += 1
            rows.append(
                {
                    "Attribute": spec.label,
                    "Key": spec.key,
                    "Required": bool(spec.required),
                    "CompareMode": spec.compare,
                    "ValueRole": spec.value_role,
                    "Original": a_val or "Not available",
                    "Candidate": b_val or "Not available",
                    "Status": status,
                    "Evidence": note,
                }
            )
        # Leading family-mismatch row is explicit and never inferred as a match.
        rows.insert(
            0,
            {
                "Attribute": "Component family",
                "Key": "family",
                "Required": True,
                "CompareMode": "exact",
                "ValueRole": "identity",
                "Original": get_family_profile(family_meta["family_a"]).display_name,
                "Candidate": get_family_profile(family_meta["family_b"]).display_name,
                "Status": "Different",
                "Evidence": (
                    "Part A and Part B resolve to different component families; "
                    "family-specific electrical attributes are not compared as equivalents."
                ),
            }
        )
        counts["Different"] += 1
        comparison = {
            "family": "General",
            "family_display_name": get_family_profile("General").display_name,
            "scoring_mode": get_family_profile("General").scoring_mode,
            "requires_pinout_for_dropin": False,
            "rows": rows,
            "counts": counts,
        }

    rows = list(comparison.get("rows") or [])
    counts = dict(comparison.get("counts") or {})
    confidence = engineering_confidence_from_rows(
        rows,
        requires_pinout_for_dropin=bool(comparison.get("requires_pinout_for_dropin")),
    )
    assessment = build_engineering_evidence_assessment(
        counts,
        comparison_rows=rows,
        family=str(comparison.get("family") or family),
    )
    finding = derive_overall_finding(
        matches=int(confidence.get("matches") or 0),
        differences=int(confidence.get("differences") or 0),
        needs_data=int(confidence.get("needs_data") or 0),
        evidence_status=str(confidence.get("engineering_evidence_status") or ""),
        family_mismatch=bool(family_meta["family_mismatch"]),
        requires_pinout_for_dropin=bool(comparison.get("requires_pinout_for_dropin")),
        pinout_matched=_pinout_matched(rows),
        required_missing=int(confidence.get("required_missing") or 0),
        required_differences=int(confidence.get("required_differences") or 0),
    )

    card_a = public_part_card(part_a, family=str(family_meta["family_a"]))
    card_b = public_part_card(part_b, family=str(family_meta["family_b"]))
    if part_a_mpn and not card_a["mpn"]:
        card_a["mpn"] = _normalize_mpn(part_a_mpn)
    if part_b_mpn and not card_b["mpn"]:
        card_b["mpn"] = _normalize_mpn(part_b_mpn)

    user_rows = user_facing_compare_rows(rows)
    return {
        "part_a": card_a,
        "part_b": card_b,
        "family": str(comparison.get("family") or family),
        "family_display_name": str(
            comparison.get("family_display_name")
            or get_family_profile(family).display_name
        ),
        "family_mismatch": bool(family_meta["family_mismatch"]),
        "finding": finding,
        "engineering_evidence_summary": assessment.get("engineering_evidence_summary", ""),
        "engineering_evidence_status": assessment.get("engineering_evidence_status", ""),
        "counts": {
            "compatible": int(counts.get("Match") or 0),
            "material_difference": int(counts.get("Different") or 0),
            "needs_data": int(counts.get("Needs data") or 0),
        },
        "rows": user_rows,
        "diagnostic_rows": diagnostic_comparison_rows(rows),
        "supplier_substitute_claim": False,
        "notes": [
            "Engineering compatibility is separate from any supplier substitute relationship.",
            "Missing attributes stay missing; Cadivor does not infer a match.",
        ],
    }


def lookup_part_for_compare(part_number: str) -> dict[str, Any]:
    """Retrieve normalized supplier data without requiring Octopart."""
    from integrations.supplier_aggregator import get_best_part_data

    requested = str(part_number or "").strip()
    if not requested:
        return {}
    result = get_best_part_data(requested) or {}
    # Strip diagnostics / raw provider payloads before they can reach the UI layer.
    sanitized = {
        key: value
        for key, value in result.items()
        if not str(key).startswith("diagnostic_")
        and key
        not in {
            "provider_health",
            "all_supplier_results",
            "octopart_sellers",
            "error",
            "failure_category",
        }
    }
    return sanitized


def run_compare_parts(part_a_mpn: str, part_b_mpn: str) -> dict[str, Any]:
    """End-to-end Compare Parts run used by the authenticated page."""
    a = str(part_a_mpn or "").strip()
    b = str(part_b_mpn or "").strip()
    if not a or not b:
        return {
            "status": STATUS_FAILED,
            "error": "Enter both Part A and Part B manufacturer part numbers.",
            "part_a": a,
            "part_b": b,
        }
    if _normalize_mpn(a) == _normalize_mpn(b):
        return {
            "status": STATUS_FAILED,
            "error": "Part A and Part B must be different manufacturer part numbers.",
            "part_a": a,
            "part_b": b,
        }
    data_a = lookup_part_for_compare(a)
    data_b = lookup_part_for_compare(b)
    comparison = build_parts_comparison(
        data_a,
        data_b,
        part_a_mpn=a,
        part_b_mpn=b,
    )
    if not comparison["part_a"]["found"] and not comparison["part_b"]["found"]:
        return {
            "status": STATUS_FAILED,
            "error": "Cadivor could not retrieve supplier data for either part.",
            "part_a": a,
            "part_b": b,
            "comparison": comparison,
        }
    return {
        "status": STATUS_COMPLETED,
        "part_a": a,
        "part_b": b,
        "comparison": comparison,
        "error": "",
    }


def generate_parts_comparison_pdf(comparison: Mapping[str, Any]) -> bytes:
    """Build a concise downloadable PDF using the same user-facing fields as the screen."""
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    part_a = dict(comparison.get("part_a") or {})
    part_b = dict(comparison.get("part_b") or {})
    finding = str(comparison.get("finding") or FINDING_NEEDS_DATA)
    rows = list(comparison.get("rows") or [])

    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=48,
        bottomMargin=42,
        title=f"Cadivor Parts Comparison: {part_a.get('mpn')} vs {part_b.get('mpn')}",
        author="Cadivor",
    )
    styles = getSampleStyleSheet()
    title = styles["Title"].clone("cp_title")
    title.fontName = "Helvetica-Bold"
    title.fontSize = 18
    title.leading = 22
    title.textColor = colors.HexColor("#0B1220")
    title.alignment = 0
    body = styles["BodyText"].clone("cp_body")
    body.fontName = "Helvetica"
    body.fontSize = 9
    body.leading = 12
    body.textColor = colors.HexColor("#334155")
    section = styles["Heading2"].clone("cp_section")
    section.fontName = "Helvetica-Bold"
    section.fontSize = 12
    section.textColor = colors.HexColor("#0F172A")

    story = [
        Paragraph("Cadivor Parts Comparison", title),
        Spacer(1, 8),
        Paragraph(
            f"<b>Finding:</b> {finding}",
            body,
        ),
        Paragraph(
            str(comparison.get("engineering_evidence_summary") or ""),
            body,
        ),
        Spacer(1, 10),
        Paragraph("Part identity", section),
        Paragraph(
            (
                f"<b>Part A:</b> {part_a.get('mpn') or '—'} · "
                f"{part_a.get('manufacturer') or '—'} · "
                f"{part_a.get('family_display_name') or '—'} · "
                f"Package {part_a.get('package') or '—'} · "
                f"Lifecycle {part_a.get('lifecycle_status') or '—'}"
            ),
            body,
        ),
        Paragraph(
            (
                f"<b>Part B:</b> {part_b.get('mpn') or '—'} · "
                f"{part_b.get('manufacturer') or '—'} · "
                f"{part_b.get('family_display_name') or '—'} · "
                f"Package {part_b.get('package') or '—'} · "
                f"Lifecycle {part_b.get('lifecycle_status') or '—'}"
            ),
            body,
        ),
        Spacer(1, 10),
        Paragraph("Attribute comparison", section),
    ]

    table_data = [["Attribute", "Part A", "Part B", "Assessment", "Evidence"]]
    for row in rows[:40]:
        table_data.append(
            [
                Paragraph(str(row.get("Attribute") or ""), body),
                Paragraph(str(row.get("Part A") or ""), body),
                Paragraph(str(row.get("Part B") or ""), body),
                Paragraph(str(row.get("Assessment") or ""), body),
                Paragraph(str(row.get("Evidence") or ""), body),
            ]
        )
    table = Table(table_data, colWidths=[78, 88, 88, 100, 140])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "Engineering compatibility is separate from supplier substitute relationships. "
            "Missing data was not inferred as a match.",
            body,
        )
    )
    document.build(story)
    return buffer.getvalue()


# Re-export for page/admin gating tests.
__all__ = [
    "FINDING_COMPATIBLE",
    "FINDING_MATERIAL",
    "FINDING_NEEDS_DATA",
    "USER_FACING_COMPARE_COLUMNS",
    "build_parts_comparison",
    "claim_compare_parts_submit",
    "derive_overall_finding",
    "generate_parts_comparison_pdf",
    "lookup_part_for_compare",
    "map_status_to_assessment",
    "public_part_card",
    "run_compare_parts",
    "user_facing_compare_rows",
    "user_may_view_comparison_diagnostics",
    "user_facing_comparison_rows",
]
