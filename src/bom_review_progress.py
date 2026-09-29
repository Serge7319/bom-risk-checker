"""Conservative progress rollup for a saved BOM's component review decisions.

The saved analysis risk counts describe parts that require review, while the
engineering review items contain a human's recorded disposition. Neither a
part approval nor a completed review session is a BOM release authorization.
"""
from __future__ import annotations

from html import escape
from typing import Any, Mapping

from src.engineering_review_service import get_latest_review_session, list_review_items


MAX_PART_ROWS = 500
PROGRESS_CACHE_SECONDS = 30.0
ACTION_ORDER = {"Not reviewed": 0, "Skip": 1, "Needs Investigation": 2, "Reject": 3, "Approve": 4}
NEXT_ACTIONS = {
    "Not reviewed": "Record a component review decision",
    "Skip": "Review this skipped risk",
    "Needs Investigation": "Finish investigation and document a mitigation",
    "Reject": "Qualify an acceptable alternative or document a resolution",
    "Approve": "Confirm supporting evidence for the BOM release decision",
}


def bom_review_progress_cache_key(user_id: str, workspace_id: str | None) -> str:
    """Keep queue snapshots isolated by account and workspace."""
    return f"engineering_decision_state_{user_id}_{workspace_id or 'personal'}_bom_progress"


def select_bom_review_parts(ranked_parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve the original five review slots and include every saved risk part.

    Historical sessions covered just five ranked components. Keeping those
    slots avoids hiding an existing review, while adding every high/medium
    part gives the whole-BOM review a path to a complete disposition. A part
    number has one saved decision even if it appears on several BOM lines.
    """
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, part in enumerate(ranked_parts):
        level = _text(part.get("stored_risk_level") or part.get("risk_level")).casefold()
        if index >= 5 and level not in {"high", "high risk", "critical", "medium", "medium risk", "moderate"}:
            continue
        mpn = _text(part.get("mpn"))
        key = mpn.casefold()
        if not key or key in seen:
            continue
        selected.append(part)
        seen.add(key)
    return selected


def _text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in {"nan", "none", "<na>"} else text


def _count(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _risk_level(part: Mapping[str, Any]) -> str:
    label = _text(part.get("risk_level") or part.get("Risk Level")).casefold()
    if label in {"high", "high risk", "critical"}:
        return "High"
    if label in {"medium", "moderate", "medium risk"}:
        return "Medium"
    if label:
        return ""
    # Legacy rows may have a score but no saved label. Use the risk engine's
    # stored thresholds rather than the newer display-only priority floors.
    score = _count(part.get("risk_score") or part.get("Risk Score"))
    return "High" if score >= 60 else "Medium" if score >= 30 else ""


def summarize_bom_review_progress(
    analysis: Mapping[str, Any],
    parts: list[dict[str, Any]],
    review_items: list[dict[str, Any]],
    *,
    review_session: Mapping[str, Any] | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    """Match risk lines to saved decisions by MPN within one authorized BOM.

    Missing saved component rows, unknown MPNs, and truncated reads never turn
    into an all-clear state. Repeated MPNs are one review target with a visible
    occurrence count; the BOM summary still counts all risk lines.
    """
    analysis_id = _text(analysis.get("id"))
    expected_high = _count(analysis.get("high_risk_count"))
    expected_medium = _count(analysis.get("medium_risk_count"))
    expected_lines = expected_high + expected_medium

    items_by_mpn: dict[str, dict[str, Any]] = {}
    for item in review_items:
        item_analysis_id = _text(item.get("analysis_id"))
        if item_analysis_id and item_analysis_id != analysis_id:
            continue
        mpn = _text(item.get("mpn")).casefold()
        # The review service returns newest first; keep the latest saved item.
        if mpn and mpn not in items_by_mpn:
            items_by_mpn[mpn] = item

    grouped: dict[str, dict[str, Any]] = {}
    risk_lines = 0
    for position, part in enumerate(parts):
        if _text(part.get("analysis_id")) not in {"", analysis_id}:
            continue
        risk = _risk_level(part)
        if not risk:
            continue
        risk_lines += 1
        mpn = _text(part.get("mpn") or part.get("part_number"))
        key = mpn.casefold() if mpn else f"unknown-part-{position}"
        if key in grouped:
            grouped[key]["occurrences"] += 1
            if risk == "High":
                grouped[key]["risk"] = "High"
            continue
        saved = items_by_mpn.get(key, {}) if mpn else {}
        decision = _text(saved.get("decision"))
        if decision not in ACTION_ORDER:
            decision = "Not reviewed"
        grouped[key] = {
            "mpn": mpn or "Unknown part number",
            "risk": risk,
            "decision": decision,
            "next_action": NEXT_ACTIONS[decision],
            "owner": _text(saved.get("assignee_name") or saved.get("owner")),
            "occurrences": 1,
            "can_open": bool(mpn),
        }

    matched = sorted(
        grouped.values(),
        key=lambda row: (ACTION_ORDER[row["decision"]], row["risk"] != "High", row["mpn"].casefold()),
    )
    approved = sum(row["decision"] == "Approve" for row in matched)
    investigating = sum(row["decision"] == "Needs Investigation" for row in matched)
    rejected = sum(row["decision"] == "Reject" for row in matched)
    skipped = sum(row["decision"] == "Skip" for row in matched)
    recorded = approved + investigating + rejected
    missing_lines = max(0, expected_lines - risk_lines)
    evidence_complete = bool(matched) and not truncated and risk_lines == expected_lines and all(
        row["can_open"] for row in matched
    )
    needs_action = len(matched) - approved + missing_lines
    return {
        "parts": matched,
        "total": len(matched),
        "risk_lines": risk_lines,
        "expected_lines": expected_lines,
        "missing_lines": missing_lines,
        "truncated": truncated,
        "evidence_complete": evidence_complete,
        "approved": approved,
        "investigating": investigating,
        "rejected": rejected,
        "skipped": skipped,
        "unreviewed": len(matched) - recorded,
        "recorded": recorded,
        "needs_action": needs_action,
        "session_status": _text((review_session or {}).get("status")) or "not started",
        "session_locked": bool((review_session or {}).get("is_locked")),
        "release_review_needed": True,
    }


def load_bom_review_progress(
    supabase: Any,
    *,
    analysis: Mapping[str, Any],
    user_id: str,
    workspace_id: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Load one already-authorized saved analysis only when its row expands."""
    analysis_id = _text(analysis.get("id"))
    if not analysis_id or not user_id:
        return None, "Saved BOM identity is unavailable."

    def _parts(*, include_workspace: bool) -> list[dict[str, Any]]:
        query = (
            supabase.table("analysis_parts")
            .select("analysis_id,mpn,risk_level,risk_score,manufacturer")
            .eq("analysis_id", analysis_id)
            .eq("user_id", user_id)
        )
        if include_workspace and workspace_id:
            query = query.eq("workspace_id", workspace_id)
        return query.limit(MAX_PART_ROWS + 1).execute().data or []

    try:
        rows = _parts(include_workspace=True)
        # Historical saved parts can lack a workspace_id. The parent analysis
        # was already authorized, and this fallback still checks user + ID.
        if not rows and workspace_id:
            rows = _parts(include_workspace=False)
    except Exception:
        return None, "Saved component data could not be loaded."

    session, error = get_latest_review_session(
        supabase,
        analysis_id=analysis_id,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    if error:
        return None, "Saved engineering review data could not be loaded."
    items: list[dict[str, Any]] = []
    if session:
        items, error = list_review_items(
            supabase,
            session_id=session["id"],
            user_id=user_id,
            workspace_id=workspace_id,
        )
        if error:
            return None, "Saved component decisions could not be loaded."

    return summarize_bom_review_progress(
        analysis,
        rows[:MAX_PART_ROWS],
        items,
        review_session=session,
        truncated=len(rows) > MAX_PART_ROWS,
    ), None


def bom_review_progress_html(progress: Mapping[str, Any], *, bom_status: str) -> str:
    """Display actual part decisions without claiming a BOM is release ready."""
    total = _count(progress.get("total"))
    recorded = _count(progress.get("recorded"))
    approved = _count(progress.get("approved"))
    percent = round(100 * recorded / total) if total else 0
    attention = _count(progress.get("needs_action"))
    evidence_complete = bool(progress.get("evidence_complete"))
    missing = _count(progress.get("missing_lines"))
    risk_lines = _count(progress.get("risk_lines"))
    expected = _count(progress.get("expected_lines"))

    if not evidence_complete:
        if progress.get("truncated"):
            next_step = "The component list is too large to verify here. Open the saved BOM before making a release decision."
        elif missing:
            next_step = (
                f"{missing} risk line{'s' if missing != 1 else ''} in the saved summary could not be matched "
                "to a component record. Verify the saved BOM before release."
            )
        else:
            next_step = "Saved risk counts and component records do not match. Verify the BOM before release."
    elif attention:
        next_step = (
            f"{attention} affected part{'s' if attention != 1 else ''} still need an "
            "approved component decision or mitigation."
        )
    else:
        next_step = (
            "Each affected part has a recorded approval. Confirm its mitigation evidence "
            "and record the separate whole-BOM release decision."
        )
    if bom_status in {"Approved", "Production Approved", "Production Ready"} and (attention or not evidence_complete):
        next_step = (
            "The BOM is marked approved while affected parts still need action or verification. "
            "Recheck that release decision against the saved part evidence."
        )
    elif progress.get("session_locked") and attention:
        next_step += " Reopen the locked engineering review to update their decisions."

    metrics = "".join(
        f'<div><strong>{_count(progress.get(key))}</strong><span>{label}</span></div>'
        for key, label in (
            ("approved", "Part approvals"),
            ("investigating", "Investigating"),
            ("rejected", "Rejected"),
            ("unreviewed", "No decision"),
        )
    )
    scope = f"{risk_lines} high/medium risk lines in this saved BOM"
    if risk_lines != expected:
        scope += f" · {expected} in saved analysis summary"
    if risk_lines != total:
        scope += " · repeated part numbers count as one review target"
    if _count(progress.get("skipped")):
        scope += f" · {progress['skipped']} skipped, still needing review"
    return (
        '<section class="cv-ed-bom-progress">'
        '<div class="cv-ed-bom-progress__head"><div><span>Saved component decisions</span>'
        '<h4>What remains before the BOM release decision</h4></div>'
        f'<strong>{recorded} of {total} recorded</strong></div>'
        f'<div class="cv-ed-bom-progress__bar" role="progressbar" aria-label="Component decisions recorded" '
        f'aria-valuenow="{recorded}" aria-valuemin="0" aria-valuemax="{total}">'
        f'<span style="width:{percent}%"></span></div>'
        f'<div class="cv-ed-bom-progress__metrics">{metrics}</div>'
        f'<p class="cv-ed-bom-progress__next">{escape(next_step)}</p>'
        f'<small>{escape(scope)}. BOM workflow: {escape(_text(bom_status) or "New")}. '
        'The engineering review can also include other priority parts. '
        'Part approvals document review; they do not grant BOM release approval.</small>'
        '</section>'
    )


def bom_review_parts_html(parts: list[dict[str, Any]]) -> str:
    """Compact per-part evidence, ordered by the next action needed."""
    rows = []
    for part in parts:
        decision = _text(part.get("decision")) or "Not reviewed"
        tone = (
            "good" if decision == "Approve"
            else "bad" if decision == "Reject"
            else "warn"
        )
        occurrence = _count(part.get("occurrences"))
        quantity = f" · {occurrence} BOM lines" if occurrence > 1 else ""
        owner = _text(part.get("owner"))
        owner_copy = f" · {owner}" if owner else ""
        rows.append(
            '<div class="cv-ed-bom-part">'
            f'<div><strong>{escape(_text(part.get("mpn")))}</strong>'
            f'<small>{escape(_text(part.get("risk")))} risk{escape(quantity)}</small></div>'
            f'<span class="cv-ed-bom-part__status cv-ed-bom-part__status--{tone}">'
            f'{escape(decision)}</span>'
            f'<p>{escape(_text(part.get("next_action")) + owner_copy)}</p>'
            '</div>'
        )
    return '<div class="cv-ed-bom-parts">' + "".join(rows) + '</div>'
