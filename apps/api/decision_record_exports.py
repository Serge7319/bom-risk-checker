"""Draft decision-record CSV layouts for regulated-industry review.

These are export layouts, not compliance templates or approved records. The
human-review notice is included in every row so the CSV cannot be mistaken for
a certification or an approved regulatory artifact.
"""
from __future__ import annotations

import csv
from io import StringIO
from typing import Any


TEMPLATES = {
    "medical-device": "Medical device design decision (draft)",
    "aerospace": "Aerospace engineering decision (draft)",
}

_COLUMNS = (
    "Template",
    "Review status",
    "Decision ID",
    "Created at",
    "Project",
    "BOM",
    "Revision",
    "Part A",
    "Manufacturer A",
    "Part B",
    "Manufacturer B",
    "Candidate alternatives",
    "Decision",
    "Rationale",
    "Validation checks recorded",
    "Follow-up action",
    "Follow-up owner",
    "Follow-up due date",
    "Residual risk",
    "Evidence summary",
    "Review notice",
)

_NOTICE = (
    "Draft export layout. Compliance review and approval are required before "
    "use in a regulated submission. This is not a certification."
)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        text = "; ".join(str(item) for item in value) if isinstance(value, (list, tuple)) else str(value)
    else:
        text = str(value)
    # Keep untrusted record text from becoming a spreadsheet formula.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def build_decision_record_export(records: list[dict[str, Any]], template: str) -> bytes:
    normalized = str(template or "").strip().lower()
    if normalized not in TEMPLATES:
        raise ValueError("Choose medical-device or aerospace.")
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        if not isinstance(record, dict):
            continue
        snapshot = record.get("comparison_snapshot")
        evidence_summary = ""
        candidate_mpns = record.get("decision_candidate_mpns")
        if not isinstance(candidate_mpns, list) or not candidate_mpns:
            candidate_mpns = [record.get("part_b")]
        candidate_brands = (
            snapshot.get("multi_candidate_manufacturers")
            if isinstance(snapshot, dict) and isinstance(snapshot.get("multi_candidate_manufacturers"), dict)
            else {}
        )
        candidate_alternatives = "; ".join(
            f"{str(mpn).strip()} · {str(candidate_brands.get(str(mpn).strip()) or '').strip()}".rstrip(" ·")
            for mpn in candidate_mpns
            if str(mpn or "").strip()
        )
        if isinstance(snapshot, dict):
            evidence_summary = "; ".join(
                f"{key}: {value}" for key, value in snapshot.items()
                if isinstance(value, (str, int, float, bool)) and str(value).strip()
            )
        writer.writerow({
            "Template": TEMPLATES[normalized],
            "Review status": "Draft — compliance review required",
            "Decision ID": _cell(record.get("id") or record.get("decision_id")),
            "Created at": _cell(record.get("created_at")),
            "Project": _cell(record.get("project_name")),
            "BOM": _cell(record.get("bom_name")),
            "Revision": _cell(record.get("revision")),
            "Part A": _cell(record.get("part_a")),
            "Manufacturer A": _cell(record.get("manufacturer_a")),
            "Part B": _cell(record.get("part_b")),
            "Manufacturer B": _cell(record.get("manufacturer_b")),
            "Candidate alternatives": _cell(candidate_alternatives),
            "Decision": _cell(record.get("decision_label") or record.get("decision")),
            "Rationale": _cell(record.get("rationale")),
            "Validation checks recorded": _cell(record.get("validation_checks")),
            "Follow-up action": _cell(record.get("follow_up_action")),
            "Follow-up owner": _cell(record.get("follow_up_owner")),
            "Follow-up due date": _cell(record.get("follow_up_due_date")),
            "Residual risk": _cell(record.get("residual_risk")),
            "Evidence summary": _cell(evidence_summary),
            "Review notice": _NOTICE,
        })
    return output.getvalue().encode("utf-8-sig")
