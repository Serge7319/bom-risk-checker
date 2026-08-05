"""Reusable HTML components for the Sprint 69 recommendation workspace."""
from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional, Sequence

from src.ui.decision_workspace._utils import INSUFFICIENT_EVIDENCE, esc, number, text
from src.ui.decision_workspace.workflow_components import (
    activity_feed,
    card_filter_attributes,
    decision_header,
    decision_health_meter,
    discussion_panel,
    engineering_notes,
    impact_summary,
    infer_status_badge,
    status_badge_class,
    workflow_tracker,
)


def timing_badge_label(bucket: str) -> str:
    normalized = text(bucket, "Can Wait")
    if normalized == "Do Before Production":
        return "Before Production"
    if normalized == "Do Now":
        return "Do This Week"
    return normalized


def timing_badge_class(bucket: str) -> str:
    normalized = text(bucket, "Can Wait")
    if normalized in {"Do Now", "Do This Week"}:
        return "cv69-timing cv69-timing--week"
    if normalized == "Do Before Production":
        return "cv69-timing cv69-timing--production"
    return "cv69-timing cv69-timing--wait"


def projected_improvement_rows(action: Mapping[str, Any]) -> List[tuple[str, str]]:
    impact = action.get("decision_impact") or {}
    if not impact:
        return []
    health = impact.get("health") or {}
    supply = impact.get("supply_risk") or {}
    lifecycle = impact.get("lifecycle_risk") or {}
    single = impact.get("single_source_exposure") or {}
    return [
        ("Health", f"{int(number(health.get('before'), 0))} → {int(number(health.get('after'), 0))}"),
        ("Supply risk", f"{int(number(supply.get('before'), 0))} → {int(number(supply.get('after'), 0))}"),
        ("Lifecycle risk", f"{text(lifecycle.get('before'))} → {text(lifecycle.get('after'))}"),
        (
            "Single-source exposure",
            f"{int(number(single.get('before'), 0))} → {int(number(single.get('after'), 0))}",
        ),
        ("Schedule improvement", f"~{int(number(impact.get('schedule_improvement_weeks'), 0))} week(s)"),
        ("Procurement effort", f"~{int(number(impact.get('procurement_effort_hours'), 0))} hour(s)"),
    ]


def confidence_breakdown_list(breakdown: Iterable[Mapping[str, Any]]) -> str:
    rows = list(breakdown or [])
    if not rows:
        return ""
    items = []
    for row in rows:
        available = bool(row.get("available"))
        icon = "✔" if available else "✖"
        state = "available" if available else "missing"
        items.append(
            f'<li class="cv69-confidence-item cv69-confidence-item--{state}">'
            f'<span class="cv69-confidence-icon">{icon}</span>'
            f"<span>{esc(row.get('label'))}</span></li>"
        )
    return f'<ul class="cv69-confidence-breakdown">{"".join(items)}</ul>'


def recommendation_summary(
    actions: Sequence[Mapping[str, Any]],
    *,
    report: Mapping[str, Any],
    brief: Mapping[str, Any],
) -> str:
    rows = list(actions or [])
    summary = report.get("summary") or {}
    count = len(rows)
    total_effort = int(number(summary.get("total_effort_hours"), 0))
    if not total_effort:
        total_effort = sum(
            int(number((row.get("dependency") or {}).get("effort_hours"), 0)) for row in rows
        )

    intelligence = brief.get("intelligence") or {}
    readiness = brief.get("production_readiness") or {}
    health_before = int(
        number(
            intelligence.get("bom_health_score"),
            number(readiness.get("score"), 0),
        )
    )
    health_gain = int(number(summary.get("combined_health_gain"), 0))
    if not health_gain:
        health_gain = sum(
            int(
                number(
                    (row.get("dependency") or {}).get("projected_bom_health", {}).get("gain"),
                    0,
                )
            )
            for row in rows
        )
    health_after = min(100, health_before + health_gain)

    top = rows[0] if rows else {}
    top_part = esc(top.get("part_number"), "—")

    confidence = brief.get("confidence") or {}
    confidence_label = esc(confidence.get("label"), "Moderate")
    confidence_score = int(number(confidence.get("score"), 0))

    return f"""
    <header class="cv69-recommendation-summary">
      <div class="cv69-summary-kicker">Engineering Actions</div>
      <div class="cv69-summary-grid">
        <article class="cv69-summary-stat">
          <span>Recommendations</span>
          <strong>{count}</strong>
        </article>
        <article class="cv69-summary-stat">
          <span>Highest priority</span>
          <strong>{top_part}</strong>
        </article>
        <article class="cv69-summary-stat">
          <span>Estimated effort</span>
          <strong>{total_effort} hrs</strong>
        </article>
        <article class="cv69-summary-stat">
          <span>Potential health</span>
          <strong>{health_before} → {health_after}</strong>
        </article>
        <article class="cv69-summary-stat">
          <span>Confidence</span>
          <strong>{confidence_label}</strong>
          <small>{confidence_score}% portfolio confidence</small>
        </article>
      </div>
    </header>
    """


def recommendation_card(action: Mapping[str, Any], *, index: int) -> str:
    bucket = text(action.get("priority_bucket"), "Can Wait")
    dep = action.get("dependency") or {}
    roi = dep.get("engineering_roi") or {}
    health = dep.get("projected_bom_health") or {}
    roi_label = esc(roi.get("label"))
    health_before = int(number(health.get("before"), 0))
    health_after = int(number(health.get("after"), 0))
    health_gain = int(number(health.get("gain"), 0))
    effort = esc(dep.get("estimated_effort") or action.get("effort"), "—")
    confidence = esc(action.get("confidence"))
    status = infer_status_badge(action)
    filters = card_filter_attributes(action, index=index)

    return f"""
    <button
      type="button"
      class="cv69-recommendation-card"
      {filters}
      aria-selected="false"
      aria-controls="cv69-detail-panel"
    >
      <div class="cv69-card-topline">
        <span class="cv69-component">{esc(action.get("part_number"), "Component")}</span>
        <span class="{timing_badge_class(bucket)}">{esc(timing_badge_label(bucket))}</span>
      </div>
      <div class="cv70-card-status-row">
        <span class="{status_badge_class(status)}">{esc(status)}</span>
      </div>
      <p class="cv69-card-title">{esc(action.get("action"), INSUFFICIENT_EVIDENCE)}</p>
      <div class="cv69-card-metrics">
        <div><span>Priority</span><strong>{esc(action.get("priority"))}</strong></div>
        <div><span>Owner</span><strong>{esc(action.get("owner"))}</strong></div>
        <div><span>Effort</span><strong>{effort}</strong></div>
        <div><span>Confidence</span><strong>{confidence}</strong></div>
        <div><span>ROI</span><strong>{roi_label}</strong></div>
        <div class="cv69-card-health">
          <span>Projected health</span>
          <strong>{health_before} → {health_after}</strong>
          <small>+{health_gain}</small>
        </div>
      </div>
      <span class="cv69-card-expand">Expand</span>
    </button>
    """


def confidence_panel(action: Mapping[str, Any]) -> str:
    confidence = esc(action.get("confidence"), INSUFFICIENT_EVIDENCE)
    breakdown = confidence_breakdown_list(action.get("confidence_breakdown") or [])
    if not breakdown:
        return (
            f'<section class="cv69-confidence-panel">'
            f'<div class="cv69-confidence-head"><span>Confidence</span><strong>{confidence}</strong></div>'
            f"</section>"
        )
    return f"""
    <section class="cv69-confidence-panel">
      <div class="cv69-confidence-head">
        <span>Confidence</span>
        <strong>{confidence}</strong>
      </div>
      <details class="cv69-confidence-disclosure">
        <summary>Show supporting evidence</summary>
        <div class="cv69-confidence-body cv69-fade-in">{breakdown}</div>
      </details>
    </section>
    """


def tradeoff_cards(action: Mapping[str, Any]) -> str:
    tradeoffs = list(action.get("tradeoffs") or [])
    if not tradeoffs:
        return ""
    cards = "".join(
        f'<article class="cv69-tradeoff-card">'
        f'<div class="cv69-tradeoff-label">{esc(item.get("option"))}</div>'
        f'<div class="cv69-tradeoff-summary">{esc(item.get("summary"))}</div>'
        f'<p>{esc(item.get("detail"))}</p>'
        f"</article>"
        for item in tradeoffs[:3]
    )
    return (
        f'<section class="cv69-disclosure-section">'
        f"<h4>Trade-off analysis</h4>"
        f'<div class="cv69-tradeoff-row">{cards}</div>'
        f"</section>"
    )


def decision_timeline(action: Mapping[str, Any]) -> str:
    timeline = list(action.get("decision_timeline") or [])
    if not timeline:
        return ""
    nodes = []
    for index, item in enumerate(timeline):
        phase = esc(item.get("phase"))
        owner = esc(item.get("owner"))
        detail = esc(item.get("detail"))
        nodes.append(
            f'<div class="cv69-timeline-node">'
            f'<div class="cv69-timeline-dot"></div>'
            f'<div class="cv69-timeline-content">'
            f"<strong>{phase}</strong>"
            f"<span>{owner}</span>"
            f"<small>{detail}</small>"
            f"</div></div>"
        )
        if index < len(timeline) - 1:
            nodes.append('<div class="cv69-timeline-connector" aria-hidden="true">↓</div>')
    return (
        f'<section class="cv69-disclosure-section">'
        f"<h4>Decision timeline</h4>"
        f'<div class="cv69-timeline-flow">{"".join(nodes)}</div>'
        f"</section>"
    )


def dependency_chain(action: Mapping[str, Any]) -> str:
    dependencies = [_text for step in (action.get("dependencies") or []) if (_text := text(step))]
    if not dependencies:
        return ""
    nodes = []
    for index, step in enumerate(dependencies, start=1):
        nodes.append(
            f'<div class="cv69-workflow-node">'
            f'<span class="cv69-workflow-index">{index}</span>'
            f"<strong>{esc(step)}</strong>"
            f"</div>"
        )
        if index < len(dependencies):
            nodes.append('<div class="cv69-workflow-connector" aria-hidden="true">↓</div>')
    return (
        f'<section class="cv69-disclosure-section">'
        f"<h4>Dependency chain</h4>"
        f'<div class="cv69-workflow-track">{"".join(nodes)}</div>'
        f"</section>"
    )


def recommendation_intelligence_details(action: Mapping[str, Any]) -> str:
    dep = action.get("dependency") or {}
    roi = dep.get("engineering_roi") or {}
    health = dep.get("projected_bom_health") or {}

    exec_summary = (
        f"{esc(action.get('action'), INSUFFICIENT_EVIDENCE)} "
        f"for {esc(action.get('part_number'), 'this component')} — "
        f"{esc(action.get('reason'), INSUFFICIENT_EVIDENCE)}"
    )

    impact_items = dep.get("engineering_impact") or []
    engineering_impact_html = ""
    if impact_items:
        engineering_impact_html = "".join(
            f"<li><strong>{esc(item.get('domain'))}</strong> — {esc(item.get('explanation'))}</li>"
            for item in impact_items
        )

    validation_items = dep.get("validation_required") or []
    validation_html = ""
    if validation_items:
        validation_html = "".join(
            f"<li><strong>{esc(item.get('step'))}</strong> — {esc(item.get('explanation'))}</li>"
            for item in validation_items
        )

    projected_rows = projected_improvement_rows(action)
    projected_html = "".join(
        f"<div><span>{esc(label)}</span><strong>{esc(value)}</strong></div>"
        for label, value in projected_rows
    )

    inaction = list(action.get("inaction_consequences") or [])
    inaction_html = "".join(f"<li>{esc(item)}</li>" for item in inaction[:4])

    tradeoffs_html = tradeoff_cards(action)
    timeline_html = decision_timeline(action)
    dependency_html = dependency_chain(action)
    confidence_html = confidence_panel(action)

    engineering_section = ""
    if engineering_impact_html or validation_html or dep:
        engineering_section = f"""
        <details class="cv69-disclosure cv69-disclosure--level2">
          <summary>Engineering analysis</summary>
          <div class="cv69-disclosure-body cv69-fade-in">
            {f'<section class="cv69-disclosure-section"><h4>Engineering impact</h4><ul class="cv69-detail-list">{engineering_impact_html}</ul></section>' if engineering_impact_html else ''}
            {f'<section class="cv69-disclosure-section"><h4>Validation required</h4><ul class="cv69-detail-list">{validation_html}</ul></section>' if validation_html else ''}
            <div class="cv69-analysis-grid">
              <div><span>Difficulty</span><strong>{esc(dep.get('change_difficulty'))}</strong></div>
              <div><span>Engineering ROI</span><strong>{esc(roi.get('label'))} ({number(roi.get('score'), 0):g})</strong></div>
              <div><span>Estimated effort</span><strong>{esc(dep.get('estimated_effort') or action.get('effort'))}</strong></div>
              <div><span>Projected health</span><strong>{int(number(health.get('before'), 0))} → {int(number(health.get('after'), 0))}</strong></div>
            </div>
          </div>
        </details>
        """

    outcome_section = f"""
    <details class="cv69-disclosure cv69-disclosure--level3">
      <summary>Outcome</summary>
      <div class="cv69-disclosure-body cv69-fade-in">
        {f'<section class="cv69-disclosure-section"><h4>Expected result if completed</h4><div class="cv68-impact-grid">{projected_html}</div></section>' if projected_html else ''}
        {f'<section class="cv69-disclosure-section"><h4>If no action is taken</h4><ul class="cv69-detail-list">{inaction_html}</ul></section>' if inaction_html else ''}
      </div>
    </details>
    """

    support_bits = [tradeoffs_html, dependency_html, timeline_html]
    support_html = "".join(bit for bit in support_bits if bit)
    support_section = ""
    if support_html:
        support_section = f"""
        <details class="cv69-disclosure cv69-disclosure--level4">
          <summary>Decision support</summary>
          <div class="cv69-disclosure-body cv69-fade-in">{support_html}</div>
        </details>
        """

    confidence_section = f"""
    <details class="cv69-disclosure cv69-disclosure--level5">
      <summary>Confidence basis</summary>
      <div class="cv69-disclosure-body cv69-fade-in">{confidence_html}</div>
    </details>
    """

    return f"""
    <div class="cv69-recommendation-details">
      <section class="cv69-disclosure-section cv69-disclosure-section--executive cv69-fade-in">
        <h4>Executive summary</h4>
        <p>{exec_summary}</p>
        <div class="cv69-executive-grid">
          <div><span>Reason</span><p>{esc(action.get('reason'), INSUFFICIENT_EVIDENCE)}</p></div>
          <div><span>Evidence</span><p>{esc(action.get('evidence'), INSUFFICIENT_EVIDENCE)}</p></div>
          <div><span>Confidence</span><p>{esc(action.get('confidence'), INSUFFICIENT_EVIDENCE)}</p></div>
          <div><span>Impact</span><p>{esc(action.get('impact'), INSUFFICIENT_EVIDENCE)}</p></div>
          <div class="cv69-executive-wide"><span>Expected result</span><p>{esc(action.get('expected_result'), INSUFFICIENT_EVIDENCE)}</p></div>
        </div>
      </section>
      {engineering_section}
      {outcome_section}
      {support_section}
      {confidence_section}
    </div>
    """


def recommendation_details(
    action: Mapping[str, Any],
    *,
    index: int = 0,
    brief: Optional[Mapping[str, Any]] = None,
) -> str:
    """Sprint 70 decision workspace shell wrapping Sprint 69 intelligence."""
    brief = brief or {}
    intelligence = recommendation_intelligence_details(action)
    return f"""
    <div class="cv70-decision-shell cv70-view-engineering" data-cv70-detail-index="{index}">
      {decision_header(action, index=index)}
      {workflow_tracker(index=index)}
      {impact_summary(action, brief)}
      {decision_health_meter(action)}
      <div class="cv70-decision-layout">
        <div class="cv70-decision-main cv70-s69-intelligence">{intelligence}</div>
        <aside class="cv70-decision-sidebar cv71-defer">
          {engineering_notes(index=index)}
          {activity_feed(index=index, action=action)}
          {discussion_panel(index=index)}
        </aside>
      </div>
    </div>
    """
