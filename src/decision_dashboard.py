"""Compact rendering helpers for Cadivor Milestone 13.1."""
from __future__ import annotations

import html
from typing import Any, Dict

from src.decision_engine import decision_target_context, decision_target_label


def decision_tone(score: int) -> str:
    if score >= 85:
        return "bad"
    if score >= 60:
        return "warn"
    return "good"


def _packet_text(value: Any, fallback: str = "") -> str:
    text = "" if value is None else str(value).strip()
    return fallback if text.casefold() in {"", "nan", "none", "<na>"} else text


def decision_card_html(decision: Dict[str, Any]) -> str:
    tone = decision_tone(int(decision.get("priority_score", 0)))
    aging_tone = str(decision.get("aging_tone", "good"))
    progress = int(decision.get("workflow_progress", 10))
    target_label = decision_target_label(decision)
    target_context = decision_target_context(decision)
    return f"""
    <section class="cv130-decision-card cv131-compact">
      <div class="cv130-decision-head">
        <div class="cv131-card-main">
          <div class="cv130-eyebrow">{html.escape(str(decision.get('decision_type', 'Engineering Decision')))}</div>
          <div class="cv130-decision-title">{html.escape(str(decision.get('title', 'Review decision')))}</div>
          <div class="cv130-reason">{html.escape(str(decision.get('reason', '')))}</div>
          <div class="cv131-target-context"><strong>{html.escape(target_label)}</strong> · {html.escape(target_context)}</div>
        </div>
        <div class="cv131-card-badges">
          <span class="cv130-badge {tone}">{html.escape(str(decision.get('priority', 'Medium')))} · {int(decision.get('priority_score', 0))}/100</span>
          <span class="cv131-age {aging_tone}">{int(decision.get('days_open', 0))} day(s) open</span>
        </div>
      </div>
      <div class="cv131-summary-grid">
        <div><span>Owner</span><strong>{html.escape(str(decision.get('assigned_owner', decision.get('owner', 'Engineering'))))}</strong></div>
        <div><span>Stage</span><strong>{html.escape(str(decision.get('status', 'New')))}</strong></div>
        <div><span>Due</span><strong>{html.escape(str(decision.get('due_date', 'This week')))}</strong></div>
        <div><span>Effort</span><strong>{int(decision.get('estimated_effort_hours', 0))} hrs</strong></div>
        <div><span>Confidence</span><strong>{int(decision.get('confidence', 0))}%</strong></div>
      </div>
      <div class="cv131-progress"><div style="width:{max(0, min(100, progress))}%"></div></div>
      <div class="cv131-next">Next: {html.escape(str(decision.get('next_required_action', 'Confirm the next action.')))}</div>
    </section>
    """


def packet_header_html(
    decision: Dict[str, Any],
    *,
    alert: Dict[str, Any] | None = None,
    saved_bom_label: str = "",
    saved_bom_linked: bool | None = None,
) -> str:
    """Render the approved, evidence-first Engineering Decision packet heading."""
    if alert is None:
        tone = decision_tone(int(decision.get("priority_score", 0)))
        progress = int(decision.get("workflow_progress", 10))
        target_label = decision_target_label(decision)
        target_context = decision_target_context(decision)
        return f"""
        <section class="cv130-packet">
          <div class="cv130-decision-head">
            <div>
              <div class="cv130-eyebrow">Engineering Decision Packet</div>
              <div class="cv130-packet-title">{html.escape(str(decision.get('title', 'Decision review')))}</div>
              <div class="cv130-reason">{html.escape(str(decision.get('reason', '')))}</div>
              <div class="cv131-target-context"><strong>{html.escape(target_label)}</strong> · {html.escape(target_context)}</div>
            </div>
            <span class="cv130-badge {tone}">{html.escape(str(decision.get('status', 'New')))}</span>
          </div>
          <div class="cv131-progress packet"><div style="width:{max(0, min(100, progress))}%"></div></div>
          <div class="cv131-next">Workflow completion: {progress}% · Next: {html.escape(str(decision.get('next_required_action', 'Confirm next action.')))}</div>
        </section>
        """
    alert = alert if isinstance(alert, dict) else {}
    target_label = decision_target_label(decision)
    alert_type = (
        _packet_text(alert.get("alert_type"))
        or _packet_text(decision.get("decision_type"))
        or "Engineering review"
    )
    alert_text = " ".join(
        _packet_text(value) for value in (alert_type, alert.get("alert_message"))
    ).casefold()
    if "lifecycle" in alert_text or any(
        marker in alert_text for marker in ("obsolete", "eol", "end of life", "nrnd")
    ):
        page_title = "Review lifecycle alert"
        alert_label = "Lifecycle changed"
    elif any(marker in alert_text for marker in ("stock", "inventory", "supply")):
        page_title = "Review supply alert"
        alert_label = "Supply availability changed"
    elif "price" in alert_text or "cost" in alert_text:
        page_title = "Review pricing alert"
        alert_label = "Pricing changed"
    else:
        page_title = "Review engineering decision"
        alert_label = alert_type or "Engineering review"

    previous_value = _packet_text(alert.get("previous_value"))
    current_value = _packet_text(alert.get("current_value"))
    if saved_bom_linked is None:
        saved_bom_linked = bool(
            decision.get("analysis_id")
            or decision.get("context_analysis_id")
            or decision.get("related_boms")
        )
    bom_label = str(saved_bom_label or "").strip()
    if not bom_label:
        bom_label = "Linked BOM" if saved_bom_linked else "Not linked"
    bom_detail = (
        "This alert is attached to a saved BOM."
        if saved_bom_linked
        else "This alert is not attached to a saved BOM."
    )
    status = _packet_text(decision.get("status"), "Open")
    is_resolved = status.casefold() in {"closed", "resolved", "rejected"}
    status_label = "RESOLVED" if is_resolved else "OPEN"
    risk = _packet_text(decision.get("priority"), "HIGH").upper()
    if "RISK" not in risk:
        risk = f"{risk} RISK"
    risk_tone = decision_tone(int(decision.get("priority_score", 0)))
    before_after = ""
    if previous_value or current_value:
        before_after = (
            '<div class="cv-dp-change">'
            f'<span class="cv-dp-change-old">{html.escape(previous_value or "Not recorded")}</span>'
            '<span class="cv-dp-change-arrow" aria-hidden="true">→</span>'
            f'<span class="cv-dp-change-new">{html.escape(current_value or "Not recorded")}</span>'
            "</div>"
        )
    component_detail = "Component · Engineering review required"
    return f"""
    <header class="cv-dp-heading">
      <div class="cv-dp-heading-copy">
        <div class="cv-dp-eyebrow">Decision review</div>
        <h1>{html.escape(page_title)}</h1>
        <p>Inspect the evidence, then record how this alert will be addressed.</p>
      </div>
      <span class="cv-dp-status {'resolved' if is_resolved else 'open'}"><i></i>{status_label}</span>
    </header>
    <section class="cv-dp-identity" aria-label="Alert summary">
      <div class="cv-dp-identity-item cv-dp-component">
        <span>Component</span>
        <strong>{html.escape(target_label)}</strong>
        <small>{html.escape(component_detail)}</small>
      </div>
      <div class="cv-dp-identity-item cv-dp-alert">
        <span>Alert</span>
        <strong>{html.escape(alert_label)}</strong>
        {before_after}
      </div>
      <div class="cv-dp-identity-item cv-dp-bom">
        <span>Saved BOM</span>
        <strong>{html.escape(bom_label)}</strong>
        <small>{html.escape(bom_detail)}</small>
      </div>
      <span class="cv-dp-risk {risk_tone}">{html.escape(risk)}</span>
    </section>
    <ol class="cv-dp-steps" aria-label="Review steps">
      <li class="{'complete' if is_resolved else 'current'}"><span>1</span><div><strong>Review evidence</strong><small>{'Complete' if is_resolved else 'Current step'}</small></div></li>
      <li class="{'complete' if is_resolved else ''}"><span>2</span><div><strong>Choose mitigation</strong><small>Link an approved alternate or verified inventory</small></div></li>
      <li class="{'complete' if is_resolved else ''}"><span>3</span><div><strong>Record outcome</strong><small>Close the alert with evidence</small></div></li>
    </ol>
    """
