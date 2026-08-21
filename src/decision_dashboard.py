"""Compact rendering helpers for Cadivor Milestone 13.1."""
from __future__ import annotations

import html
from typing import Any, Dict


def decision_tone(score: int) -> str:
    if score >= 85:
        return "bad"
    if score >= 60:
        return "warn"
    return "good"


def decision_card_html(decision: Dict[str, Any]) -> str:
    tone = decision_tone(int(decision.get("priority_score", 0)))
    aging_tone = str(decision.get("aging_tone", "good"))
    progress = int(decision.get("workflow_progress", 10))
    return f"""
    <section class="cv130-decision-card cv131-compact">
      <div class="cv130-decision-head">
        <div class="cv131-card-main">
          <div class="cv130-eyebrow">{html.escape(str(decision.get('decision_type', 'Engineering Decision')))}</div>
          <div class="cv130-decision-title">{html.escape(str(decision.get('title', 'Review decision')))}</div>
          <div class="cv130-reason">{html.escape(str(decision.get('reason', '')))}</div>
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


def packet_header_html(decision: Dict[str, Any]) -> str:
    tone = decision_tone(int(decision.get("priority_score", 0)))
    progress = int(decision.get("workflow_progress", 10))
    return f"""
    <section class="cv130-packet">
      <div class="cv130-decision-head">
        <div>
          <div class="cv130-eyebrow">Engineering Decision Packet</div>
          <div class="cv130-packet-title">{html.escape(str(decision.get('title', 'Decision review')))}</div>
          <div class="cv130-reason">{html.escape(str(decision.get('reason', '')))}</div>
        </div>
        <span class="cv130-badge {tone}">{html.escape(str(decision.get('status', 'New')))}</span>
      </div>
      <div class="cv131-progress packet"><div style="width:{max(0, min(100, progress))}%"></div></div>
      <div class="cv131-next">Workflow completion: {progress}% · Next: {html.escape(str(decision.get('next_required_action', 'Confirm next action.')))}</div>
    </section>
    """
