"""Rendering helpers for Cadivor Milestone 13.0."""
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
    return f"""
    <section class="cv130-decision-card">
      <div class="cv130-decision-head">
        <div>
          <div class="cv130-eyebrow">{html.escape(str(decision.get('decision_type', 'Engineering Decision')))}</div>
          <div class="cv130-decision-title">{html.escape(str(decision.get('title', 'Review decision')))}</div>
          <div class="cv130-reason">{html.escape(str(decision.get('reason', '')))}</div>
        </div>
        <span class="cv130-badge {tone}">{html.escape(str(decision.get('priority', 'Medium')))} · {int(decision.get('priority_score', 0))}/100</span>
      </div>
      <div class="cv130-meta">
        <span>Owner: {html.escape(str(decision.get('assigned_owner', decision.get('owner', 'Engineering'))))}</span>
        <span>Status: {html.escape(str(decision.get('status', 'Open')))}</span>
        <span>Due: {html.escape(str(decision.get('due_date', 'This week')))}</span>
        <span>Effort: {int(decision.get('estimated_effort_hours', 0))} hrs</span>
        <span>Confidence: {int(decision.get('confidence', 0))}%</span>
      </div>
    </section>
    """


def packet_header_html(decision: Dict[str, Any]) -> str:
    tone = decision_tone(int(decision.get("priority_score", 0)))
    return f"""
    <section class="cv130-packet">
      <div class="cv130-decision-head">
        <div>
          <div class="cv130-eyebrow">Engineering Decision Packet</div>
          <div class="cv130-packet-title">{html.escape(str(decision.get('title', 'Decision review')))}</div>
          <div class="cv130-reason">{html.escape(str(decision.get('reason', '')))}</div>
        </div>
        <span class="cv130-badge {tone}">{html.escape(str(decision.get('status', 'Open')))}</span>
      </div>
    </section>
    """
