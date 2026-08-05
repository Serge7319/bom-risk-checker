"""Sprint 70 — Collaborative engineering decision workspace components."""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from src.ui.decision_workspace._utils import INSUFFICIENT_EVIDENCE, esc, number, text

WORKFLOW_STATES: tuple[str, ...] = (
    "Draft",
    "Needs Review",
    "Approved",
    "In Progress",
    "Completed",
    "Released",
)

STATUS_BADGES: tuple[str, ...] = (
    "Awaiting Review",
    "Blocked",
    "Waiting Supplier",
    "Approved",
    "Released",
    "Rejected",
)

FILTER_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("all", "All"),
    ("high-confidence", "High Confidence"),
    ("highest-roi", "Highest ROI"),
    ("quick-wins", "Quick Wins"),
    ("production-blockers", "Production Blockers"),
    ("low-effort", "Low Effort"),
    ("awaiting-review", "Awaiting Review"),
)


def _confidence_percent(action: Mapping[str, Any]) -> int:
    raw = text(action.get("confidence"))
    match = re.search(r"\d+", raw)
    return int(match.group()) if match else 0


def _effort_hours(action: Mapping[str, Any]) -> int:
    dep = action.get("dependency") or {}
    hours = int(number(dep.get("effort_hours"), 0))
    if hours:
        return hours
    raw = text(dep.get("estimated_effort") or action.get("effort"))
    match = re.search(r"\d+", raw)
    return int(match.group()) if match else 0


def _roi_score(action: Mapping[str, Any]) -> float:
    dep = action.get("dependency") or {}
    return number((dep.get("engineering_roi") or {}).get("score"), 0)


def infer_status_badge(action: Mapping[str, Any]) -> str:
    priority = text(action.get("priority")).lower()
    bucket = text(action.get("priority_bucket")).lower()
    reason = text(action.get("reason")).lower()
    if "reject" in reason:
        return "Rejected"
    if priority in {"critical", "high"} and "before production" in bucket:
        return "Blocked"
    if any(term in reason for term in ("supplier", "sourcing", "stock", "inventory")):
        return "Waiting Supplier"
    if priority == "critical":
        return "Awaiting Review"
    return "Awaiting Review"


def status_badge_class(status: str) -> str:
    slug = status.lower().replace(" ", "-")
    return f"cv70-status cv70-status--{slug}"


def card_filter_attributes(action: Mapping[str, Any], *, index: int) -> str:
    confidence = _confidence_percent(action)
    roi = _roi_score(action)
    effort = _effort_hours(action)
    priority = text(action.get("priority")).lower()
    bucket = text(action.get("priority_bucket")).lower()
    status = infer_status_badge(action)
    quick_win = roi >= 1.0 and effort <= 4
    production_blocker = priority in {"critical", "high"} or "before production" in bucket
    return (
        f'data-cv70-index="{index}" '
        f'data-confidence="{confidence}" '
        f'data-roi="{roi:g}" '
        f'data-effort="{effort}" '
        f'data-priority="{esc(priority)}" '
        f'data-status="{esc(status.lower())}" '
        f'data-quick-win="{"1" if quick_win else "0"}" '
        f'data-production-blocker="{"1" if production_blocker else "0"}" '
        f'data-awaiting-review="{"1" if status == "Awaiting Review" else "0"}"'
    )


def decision_health_meter(action: Mapping[str, Any]) -> str:
    breakdown = list(action.get("confidence_breakdown") or [])
    available = sum(1 for row in breakdown if row.get("available"))
    total = len(breakdown) or 1
    evidence_pct = int(round(available / total * 100))

    dep = action.get("dependency") or {}
    validation_count = len(dep.get("validation_required") or [])
    validation_pct = min(100, validation_count * 14)

    confidence_pct = _confidence_percent(action)
    supplier_pct = 72
    impact = action.get("decision_impact") or {}
    single = impact.get("single_source_exposure") or {}
    before = number(single.get("before"), 1)
    after = number(single.get("after"), before)
    if before:
        supplier_pct = int(max(35, min(100, (after / before) * 100)))

    review_pct = 55
    dimensions = [
        ("Confidence", confidence_pct),
        ("Evidence", evidence_pct),
        ("Validation", validation_pct),
        ("Supplier coverage", supplier_pct),
        ("Review readiness", review_pct),
    ]
    overall = int(round(sum(score for _, score in dimensions) / len(dimensions)))

    bars = "".join(
        f'<div class="cv70-health-dim">'
        f"<span>{esc(label)}</span>"
        f'<div class="cv70-health-track"><i style="width:{score}%"></i></div>'
        f"<strong>{score}%</strong></div>"
        for label, score in dimensions
    )
    tone = "high" if overall >= 75 else "medium" if overall >= 55 else "low"
    return f"""
    <section class="cv70-decision-health cv70-decision-health--{tone}">
      <div class="cv70-section-head">
        <h4>Decision health</h4>
        <strong>{overall}%</strong>
      </div>
      <div class="cv70-health-meter"><i style="width:{overall}%"></i></div>
      <div class="cv70-health-grid">{bars}</div>
    </section>
    """


def impact_summary(action: Mapping[str, Any], brief: Mapping[str, Any]) -> str:
    impact = action.get("decision_impact") or {}
    dep = action.get("dependency") or {}
    health = impact.get("health") or dep.get("projected_bom_health") or {}
    supply = impact.get("supply_risk") or {}
    cards = [
        (
            "Engineering",
            f"Health {int(number(health.get('before'), 0))} → {int(number(health.get('after'), 0))}",
        ),
        (
            "Supply chain",
            f"Risk {int(number(supply.get('before'), 0))} → {int(number(supply.get('after'), 0))}",
        ),
        (
            "Manufacturing",
            esc(impact.get("manufacturing_readiness"), "Maintains current readiness"),
        ),
        (
            "Documentation",
            "Update required" if any(
                item.get("domain") == "Documentation"
                for item in (dep.get("engineering_impact") or [])
            ) else "No change expected",
        ),
        (
            "Schedule",
            f"~{int(number(impact.get('schedule_improvement_weeks'), 0))} week improvement",
        ),
    ]
    business = brief.get("business_impact") or {}
    if business.get("schedule"):
        cards[4] = ("Schedule", esc(business.get("schedule"))[:80])
    kpi_html = "".join(
        f'<article class="cv70-impact-kpi"><span>{esc(title)}</span><strong>{value}</strong></article>'
        for title, value in cards
    )
    return f"""
    <section class="cv70-impact-summary">
      <div class="cv70-section-head"><h4>Executive impact summary</h4></div>
      <div class="cv70-impact-grid">{kpi_html}</div>
    </section>
    """


def decision_header(action: Mapping[str, Any], *, index: int) -> str:
    dep = action.get("dependency") or {}
    roi = dep.get("engineering_roi") or {}
    health = dep.get("projected_bom_health") or {}
    status = infer_status_badge(action)
    return f"""
    <header class="cv70-decision-header" data-cv70-header-index="{index}">
      <div class="cv70-decision-header-main">
        <div class="cv70-decision-topline">
          <span class="cv70-decision-component">{esc(action.get('part_number'), 'Component')}</span>
          <span class="{status_badge_class(status)}">{esc(status)}</span>
        </div>
        <h3 class="cv70-decision-title">{esc(action.get('action'), INSUFFICIENT_EVIDENCE)}</h3>
        <div class="cv70-decision-meta">
          <span><em>Priority</em>{esc(action.get('priority'))}</span>
          <span><em>Owner</em>{esc(action.get('owner'))}</span>
          <span><em>Confidence</em>{esc(action.get('confidence'))}</span>
          <span><em>Effort</em>{esc(dep.get('estimated_effort') or action.get('effort'))}</span>
          <span><em>ROI</em>{esc(roi.get('label'))} ({number(roi.get('score'), 0):g})</span>
          <span><em>Projected health</em>{int(number(health.get('before'), 0))} → {int(number(health.get('after'), 0))}</span>
        </div>
      </div>
      <div class="cv70-decision-actions">
        <button type="button" class="cv70-action-btn cv70-action-btn--primary" data-cv70-action="approve" data-cv70-index="{index}">Approve</button>
        <button type="button" class="cv70-action-btn" data-cv70-action="assign" data-cv70-index="{index}">Assign</button>
        <button type="button" class="cv70-action-btn" data-cv70-action="comment" data-cv70-index="{index}">Comment</button>
        <button type="button" class="cv70-action-btn" data-cv70-action="export" data-cv70-index="{index}">Export</button>
        <button type="button" class="cv70-action-btn" data-cv70-action="share" data-cv70-index="{index}">Share</button>
      </div>
    </header>
    """


def workflow_tracker(*, index: int, initial_state: str = "Draft") -> str:
    initial_idx = WORKFLOW_STATES.index(initial_state) if initial_state in WORKFLOW_STATES else 0
    steps = []
    for step_idx, state in enumerate(WORKFLOW_STATES):
        active = " is-active" if step_idx == initial_idx else ""
        complete = " is-complete" if step_idx < initial_idx else ""
        steps.append(
            f'<button type="button" class="cv70-workflow-step{active}{complete}" '
            f'data-cv70-workflow-state="{esc(state)}" data-cv70-index="{index}">{esc(state)}</button>'
        )
    return f"""
    <nav class="cv70-workflow-tracker" aria-label="Decision workflow" data-cv70-index="{index}">
      <div class="cv70-workflow-track">{''.join(steps)}</div>
    </nav>
    """


def engineering_notes(*, index: int) -> str:
    return f"""
    <section class="cv70-engineering-notes" data-cv70-index="{index}">
      <div class="cv70-section-head"><h4>Engineering notes</h4></div>
      <textarea class="cv70-notes-input" rows="3" placeholder="Capture decision rationale, validation context, or release constraints..." data-cv70-index="{index}"></textarea>
      <button type="button" class="cv70-action-btn cv70-action-btn--primary" data-cv70-notes-save="{index}">Save note</button>
      <ul class="cv70-notes-history" data-cv70-notes-history="{index}"></ul>
    </section>
    """


def activity_feed(*, index: int, action: Mapping[str, Any]) -> str:
    seed = [
        {
            "type": "recommendation",
            "message": f"Recommendation generated for {text(action.get('part_number'), 'component')}.",
        },
        {
            "type": "evidence",
            "message": f"Evidence attached: {text(action.get('evidence'), INSUFFICIENT_EVIDENCE)[:120]}",
        },
    ]
    items = "".join(
        f'<li class="cv70-activity-item cv70-activity-item--{esc(item["type"])}">'
        f"<span>{esc(item['message'])}</span></li>"
        for item in seed
    )
    return f"""
    <section class="cv70-activity-feed" data-cv70-index="{index}">
      <div class="cv70-section-head"><h4>Decision activity</h4></div>
      <ol class="cv70-activity-list" data-cv70-activity-list="{index}">{items}</ol>
    </section>
    """


def discussion_panel(*, index: int) -> str:
    return f"""
    <section class="cv70-discussion-panel" data-cv70-index="{index}">
      <div class="cv70-section-head"><h4>Engineering discussions</h4></div>
      <div class="cv70-discussion-thread" data-cv70-discussion-thread="{index}">
        <article class="cv70-discussion-entry">
          <strong>System</strong>
          <p>Thread opened for collaborative review. Use @mentions in a future release.</p>
        </article>
      </div>
      <textarea class="cv70-discussion-input" rows="2" placeholder="Add a discussion note. @mentions coming soon." data-cv70-index="{index}"></textarea>
      <button type="button" class="cv70-action-btn" data-cv70-discussion-post="{index}">Post</button>
    </section>
    """


def comparison_view(actions: Sequence[Mapping[str, Any]]) -> str:
    payload = []
    for index, action in enumerate(actions):
        dep = action.get("dependency") or {}
        health = dep.get("projected_bom_health") or {}
        payload.append(
            {
                "index": index,
                "part_number": text(action.get("part_number")),
                "title": text(action.get("action")),
                "confidence": _confidence_percent(action),
                "roi": _roi_score(action),
                "health_gain": int(number(health.get("gain"), 0)),
                "effort": _effort_hours(action),
                "validation": [
                    text(item.get("step"))
                    for item in (dep.get("validation_required") or [])
                ],
                "tradeoffs": [
                    text(item.get("option"))
                    for item in (action.get("tradeoffs") or [])[:3]
                ],
                "timeline": [
                    text(item.get("phase"))
                    for item in (action.get("decision_timeline") or [])
                ],
            }
        )
    data_json = json.dumps(payload).replace("</", "<\\/")
    return f"""
    <section class="cv70-comparison-view" hidden data-cv70-comparison-root>
      <div class="cv70-section-head">
        <h4>Recommendation comparison</h4>
        <button type="button" class="cv70-action-btn" data-cv70-comparison-close>Close</button>
      </div>
      <div class="cv70-comparison-controls">
        <label>A<select data-cv70-compare-a></select></label>
        <label>B<select data-cv70-compare-b></select></label>
      </div>
      <div class="cv70-comparison-grid" data-cv70-comparison-grid></div>
      <script type="application/json" data-cv70-comparison-data>{data_json}</script>
    </section>
    """


def workspace_toolbar() -> str:
    filters = "".join(
        f'<button type="button" class="cv70-filter-btn{" is-active" if key == "all" else ""}" '
        f'data-cv70-filter="{esc(key)}">{esc(label)}</button>'
        for key, label in FILTER_DEFINITIONS
    )
    return f"""
    <div class="cv70-workspace-toolbar">
      <div class="cv70-filter-bar">{filters}</div>
      <div class="cv70-toolbar-actions">
        <div class="cv70-view-toggle" role="group" aria-label="View mode">
          <button type="button" class="cv70-view-btn" data-cv70-view="executive">Executive view</button>
          <button type="button" class="cv70-view-btn is-active" data-cv70-view="engineering">Engineering view</button>
        </div>
        <button type="button" class="cv70-action-btn" data-cv70-compare-open>Compare</button>
      </div>
    </div>
    """
