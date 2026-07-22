"""Premium user-facing Engineering Copilot panel."""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlencode, quote

import streamlit as st

from src.services.ai_entitlements import consume_ai_credits, get_ai_usage_status
from src.services.engineering_ai import EngineeringAI, EngineeringAIError
from src.services.copilot_conversation import (
    append_turn,
    clear_thread,
    compact_history,
    follow_up_suggestions,
    get_thread,
)

SUGGESTIONS = [
    "What should I review first in this BOM?",
    "Explain the highest component risks.",
    "Is this BOM ready for production release?",
    "Which components need alternative qualification?",
    "Summarize the supplier and lifecycle exposure.",
]



def _clear_review_state() -> None:
    """Clear the prior copilot result when the user starts a new question."""
    for key in (
        "cv35_last_answer",
        "cv35_last_question",
        "cv35_last_error",
        "cv35_provider_connected",
    ):
        st.session_state.pop(key, None)


def _secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default) or default)
    except Exception:
        return default


def _usage_banner(status) -> None:
    if status.is_admin:
        text = "Admin access · AI usage limits are bypassed"
        cls = "normal"
    else:
        text = f"{status.remaining:,} of {status.allowance:,} AI credits remaining this month"
        cls = status.warning_level
    st.markdown(
        f'<div class="cv35-usage {cls}"><strong>AI usage</strong><span>{html.escape(text)}</span></div>',
        unsafe_allow_html=True,
    )
    if status.warning_level in {"notice", "high", "critical"}:
        st.info(
            f"You have used {status.percent_used}% of this month's AI allowance. "
            "Compare plans before your allowance is exhausted."
        )
    elif status.warning_level == "reached":
        st.warning(
            "Your monthly AI allowance has been reached. Your saved engineering data is safe. "
            "Upgrade your plan to continue using the Engineering Assistant now."
        )
        st.link_button("Compare plans", "?page=Pricing", use_container_width=False)


def _render_error(exc: EngineeringAIError) -> None:
    title_by_code = {
        "configuration": "Engineering Assistant unavailable",
        "busy": "Engineering Assistant is busy",
        "timeout": "Request timed out",
        "validation": "Question required",
    }
    title = title_by_code.get(getattr(exc, "code", ""), "Unable to complete the review")
    st.markdown(
        f"""
        <div class="cv35-message cv35-message-error">
          <div class="cv35-message-icon">!</div>
          <div><strong>{html.escape(title)}</strong><p>{html.escape(str(exc))}</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _parse_report(answer: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    active = "Engineering Assessment"
    sections[active] = []
    for raw_line in str(answer or "").splitlines():
        line = raw_line.strip()
        match = re.match(r"^#{1,4}\s+(.+?)\s*$", line)
        if match:
            active = match.group(1).strip()
            sections.setdefault(active, [])
            continue
        sections.setdefault(active, []).append(raw_line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _section(sections: dict[str, str], *names: str) -> str:
    lowered = {key.lower(): value for key, value in sections.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return ""



def _assessment_profile(sections: dict[str, str]) -> dict[str, str]:
    """Normalize question-specific report sections into a renderer profile."""
    ordered = [key for key, value in sections.items() if str(value or "").strip()]
    first = ordered[0] if ordered else (next(iter(sections), "Engineering Assessment"))
    first_l = first.lower()
    if "schedule" in first_l:
        intent, label, status = "schedule", "Schedule risk assessment", "Protect the production schedule"
        evidence_names = ("Schedule Evidence", "Supporting Evidence", "Evidence")
    elif "supplier" in first_l:
        intent, label, status = "supplier", "Supplier risk assessment", "Reduce sourcing concentration"
        evidence_names = ("Supplier Evidence", "Supporting Evidence", "Evidence")
    elif "compatibility" in first_l:
        intent, label, status = "compatibility", "Compatibility review", "Validate before substitution"
        evidence_names = ("Required Evidence", "Supporting Evidence", "Evidence")
    elif "lifecycle" in first_l:
        intent, label, status = "lifecycle", "Lifecycle assessment", "Address lifecycle exposure"
        evidence_names = ("Lifecycle Evidence", "Supporting Evidence", "Evidence")
    elif "procurement" in first_l:
        intent, label, status = "procurement", "Procurement assessment", "Secure the purchasing window"
        evidence_names = ("Procurement Evidence", "Supporting Evidence", "Evidence")
    elif "release" in first_l:
        intent, label, status = "release", "Release readiness assessment", "Review before release"
        evidence_names = ("Release Evidence", "Supporting Evidence", "Evidence")
    else:
        intent, label, status = "general", "Engineering assessment", "Review before release"
        evidence_names = ("Supporting Evidence", "Evidence", "Engineering Evidence")
    assessment = sections.get(first, "") or _section(sections, "Engineering Assessment", "Assessment")
    evidence = _section(sections, *evidence_names)
    actions = _section(sections, "Recommended Actions", "Recommended action")
    confidence = _section(sections, "Confidence")
    return {"intent": intent, "label": label, "status": status, "assessment": assessment, "evidence": evidence, "actions": actions, "confidence": confidence}

def _plain_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or ""))
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


def _evidence_items(evidence: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for line in str(evidence or "").splitlines():
        clean = line.strip()
        if not clean.startswith(("-", "*")):
            continue
        clean = clean[1:].strip()
        match = re.match(r"\*\*(.+?)\*\*\s*[—-]\s*(.+)", clean)
        if match:
            items.append((match.group(1).strip(), _plain_markdown(match.group(2))))
        else:
            items.append(("Engineering evidence", _plain_markdown(clean)))
    return items


def _priority_component(context: dict[str, Any], evidence: str = "") -> str:
    evidence_items = _evidence_items(evidence)
    if evidence_items and evidence_items[0][0] != "Engineering evidence":
        return evidence_items[0][0]
    components = list(context.get("components") or [])
    components.sort(key=lambda row: int(row.get("risk_score") or 0), reverse=True)
    if components:
        return str(components[0].get("part_number") or components[0].get("mpn") or "")
    return ""


def _confidence_data(confidence: str, context: dict[str, Any]) -> tuple[str, int, str]:
    plain = _plain_markdown(confidence)
    label_match = re.match(r"(High|Medium|Limited|Low)", plain, re.IGNORECASE)
    label = (label_match.group(1).title() if label_match else "Medium")
    percent_match = re.search(r"(\d{1,3})%", plain)
    if percent_match:
        score = max(0, min(100, int(percent_match.group(1))))
    else:
        score = int((context.get("coverage") or {}).get("score") or 0)
    detail = plain
    if detail.lower().startswith(label.lower()):
        detail = detail[len(label):].lstrip(". ")
    return label, score, detail


def _href(page: str, **params: Any) -> str:
    payload = {"page": page}
    payload.update({key: value for key, value in params.items() if value not in (None, "")})
    return "?" + urlencode(payload, quote_via=quote)



def _split_evidence_detail(detail: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for segment in [item.strip() for item in str(detail or "").split(";") if item.strip()]:
        if ":" in segment:
            label, value = segment.split(":", 1)
            pairs.append((label.strip().title(), value.strip()))
        else:
            pairs.append(("Signal", segment))
    return pairs[:6]


def _action_steps(actions: str) -> list[str]:
    plain = _plain_markdown(actions)
    if not plain:
        return []
    parts = re.split(r"(?:\.|;|, then |, and then )\s+", plain)
    steps = [part.strip(" .") for part in parts if part.strip(" .")]
    return steps[:4] or [plain]


def _assessment_kpis(context: dict[str, Any], confidence_score: int) -> list[tuple[str, str, str]]:
    analysis = context.get("analysis") or {}
    summary = context.get("summary") or {}
    risk = context.get("risk_summary") or context.get("risk") or {}
    components = list(context.get("components") or [])
    health = summary.get("health_score") or analysis.get("health_score") or context.get("health_score") or context.get("score") or "—"
    posture = summary.get("release_posture") or analysis.get("release_posture") or context.get("release_posture") or "Focused review"
    high = risk.get("high") if isinstance(risk, dict) else None
    if high is None:
        high = sum(1 for row in components if str(row.get("risk_level") or "").lower() == "high")
    return [
        ("BOM health", f"{health}/100" if str(health).isdigit() else str(health), "Current analysis score"),
        ("Release status", str(posture).replace("_", " ").title(), "Current engineering posture"),
        ("Priority risks", str(high or 0), "High-risk components"),
        ("Confidence", f"{confidence_score}%", "Evidence-supported review"),
    ]



def _decision_summary(context: dict[str, Any], assessment: str, confidence_score: int, priority_part: str, *, intent: str = "general", preferred_status: str = "") -> dict[str, str]:
    analysis = context.get("analysis") or {}
    summary = context.get("summary") or {}
    risk = context.get("risk_summary") or context.get("risk") or {}
    components = list(context.get("components") or [])
    high = int(risk.get("high") or 0) if isinstance(risk, dict) else 0
    medium = int(risk.get("medium") or 0) if isinstance(risk, dict) else 0
    lifecycle_exposed = sum(1 for row in components if str(row.get("lifecycle") or row.get("lifecycle_status") or "").lower() not in {"", "active", "production", "unknown"})
    status = preferred_status or ("Action required" if high else "Review before release" if medium or lifecycle_exposed else "Ready for controlled release")
    tone = "critical" if high else "review" if medium or lifecycle_exposed else "ready"
    health = summary.get("health_score") or analysis.get("health_score") or context.get("health_score") or context.get("score") or "—"
    return {"status": status, "tone": tone, "risk": "High" if high else "Medium" if medium or lifecycle_exposed else "Low", "priority": priority_part or "No priority component", "confidence": f"{confidence_score}%", "health": f"{health}/100" if str(health).isdigit() else str(health), "assessment": _plain_markdown(assessment), "intent": intent}

def _projected_impact(context: dict[str, Any], priority_part: str, *, intent: str = "general") -> list[tuple[str, str, str]]:
    analysis = context.get("analysis") or {}; summary = context.get("summary") or {}
    components = list(context.get("components") or [])
    priority = next((row for row in components if str(row.get("part_number") or row.get("mpn") or "").upper() == str(priority_part).upper()), {})
    score = int(priority.get("risk_score") or 0) if priority else 0
    suppliers = int(priority.get("supplier_count") or priority.get("suppliers") or 0) if priority else 0
    lead = float(priority.get("lead_time_weeks") or 0) if priority else 0
    stock = int(priority.get("stock_available") or 0) if priority else 0
    if intent == "schedule":
        return [("Replenishment exposure", f"{lead:g} weeks → Validate", "Confirm with authorized suppliers"), ("Schedule risk", "Elevated → Reduced", "After allocation or alternate qualification"), ("Inventory coverage", f"{stock:,} recorded", "Compare against production demand"), ("Source resilience", f"{suppliers} source(s) → Improve", "Qualify an alternate or second source")]
    if intent == "supplier":
        return [("Supplier coverage", f"{suppliers} → {max(suppliers+1,2)}", "If a second source is qualified"), ("Concentration risk", "Current → Reduced", "After authorized-source validation"), ("Priority risk", f"{score}/100 → Reduced", "After mitigation or acceptance")]
    if intent == "compatibility":
        return [("Electrical equivalence", "Unverified → Documented", "Approved datasheet comparison"), ("Footprint compatibility", "Unverified → Confirmed", "PCB and package review"), ("Validation status", "Pending → Complete", "Bench or prototype evidence")]
    health_raw = summary.get("health_score") or analysis.get("health_score") or context.get("health_score") or context.get("score")
    try: health=int(float(health_raw))
    except Exception: health=None
    impact=[]
    if health is not None: impact.append(("BOM health", f"{health} → {min(100,health+max(2,min(7,round(score/10))))}", "Projected after mitigation"))
    impact.append(("Release readiness", "Focused review → Ready", "Expected after evidence closure"))
    if priority_part: impact.append(("Priority risk", f"{score}/100 → Reduced", "After qualification or acceptance"))
    if suppliers: impact.append(("Supplier coverage", f"{suppliers} → {suppliers+1}", "If a second source is qualified"))
    return impact[:4]

def _workflow_steps(actions: str, priority_part: str, *, intent: str = "general") -> list[tuple[str, str]]:
    base = _action_steps(actions)
    labels_by_intent = {
        "schedule": ["Confirm demand", "Verify lead time", "Secure allocation", "Qualify alternate", "Protect commitment"],
        "supplier": ["Verify sources", "Check authorization", "Qualify second source", "Set monitoring", "Record mitigation"],
        "compatibility": ["Compare datasheets", "Review pinout", "Confirm footprint", "Validate prototype", "Approve substitution"],
        "lifecycle": ["Confirm lifecycle", "Review notices", "Select successor", "Qualify replacement", "Record decision"],
        "procurement": ["Confirm demand", "Review inventory", "Contact suppliers", "Secure purchasing", "Monitor exposure"],
        "release": ["Validate evidence", "Close blockers", "Review sourcing", "Record decision", "Approve release"],
    }
    labels=labels_by_intent.get(intent,["Validate evidence","Review sourcing","Evaluate mitigation","Record decision","Approve release"])
    steps=[]
    for i,label in enumerate(labels):
        detail=base[i] if i<len(base) else (f"Complete the required review for {priority_part}." if priority_part and i<4 else "Confirm the applicable engineering criteria are satisfied.")
        steps.append((label,detail))
    return steps

def _review_progress(context: dict[str, Any]) -> tuple[int, int, int]:
    coverage = int((context.get("coverage") or {}).get("score") or 0)
    complete = max(1, min(10, round(coverage / 10)))
    return complete, 10, complete * 10

def _render_evidence_cards(evidence: str) -> None:
    items = _evidence_items(evidence)
    if not items:
        if str(evidence or "").strip():
            st.markdown(f'<div class="cv39-impact-card"><p>{html.escape(_plain_markdown(evidence))}</p></div>', unsafe_allow_html=True)
        else:
            st.info("No structured evidence was returned for this review. Re-run the analysis or verify that component records are saved.")
        return
    columns = st.columns(2)
    for index, (title, detail) in enumerate(items[:6]):
        metrics = _split_evidence_detail(detail)
        metric_html = "".join(
            f'<div class="cv38-evidence-metric"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
            for label, value in metrics[:5]
        )
        with columns[index % 2]:
            st.markdown(
                f"""
                <div class="cv35-evidence-card">
                  <div class="cv35-evidence-head"><div class="cv35-evidence-part">{html.escape(title)}</div><span>Needs review</span></div>
                  <div class="cv38-evidence-grid">{metric_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander(f"More evidence · {title}", expanded=False):
                for label, value in metrics:
                    st.markdown(f"**{label}:** {value}")
                st.caption("Review current approved datasheets, authorized-source records, monitoring history, and saved engineering decisions before final approval.")


def _render_quick_actions(context: dict[str, Any], priority_part: str) -> None:
    analysis = context.get("analysis") or {}
    analysis_id = str(analysis.get("analysis_id") or "")
    if not analysis_id:
        return
    st.markdown('<div class="cv35-section-label">Continue the workflow</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    component_url = _href(
        "Analysis Details",
        analysis_id=analysis_id,
        tab="components",
        component=priority_part,
        focus="component-risk",
    )
    alternative_url = _href("Alternative Finder", original_part=priority_part, analysis_id=analysis_id)
    monitoring_url = _href("Monitoring", mpn=priority_part, analysis_id=analysis_id)
    decision_url = _href("Engineering Decisions", analysis_id=analysis_id, part_number=priority_part)
    part_label = priority_part or "component"
    cols[0].link_button(f"Open {part_label}", component_url, use_container_width=True)
    cols[1].link_button(f"Find {part_label} alternative", alternative_url, use_container_width=True)
    cols[2].link_button(f"Monitor {part_label}", monitoring_url, use_container_width=True)
    cols[3].link_button("Create engineering record", decision_url, use_container_width=True)




def _render_conversation_history(thread: list[dict[str, Any]], *, exclude_latest: bool = False) -> None:
    turns = thread[:-1] if exclude_latest and thread else thread
    if not turns:
        return
    with st.expander(f"Engineering session · {len(turns)} prior review{'s' if len(turns) != 1 else ''}", expanded=False):
        for index, turn in enumerate(turns, start=1):
            question = html.escape(str(turn.get("question") or "Engineering question"))
            answer_sections = _parse_report(str(turn.get("answer") or ""))
            assessment = html.escape(_plain_markdown(_assessment_profile(answer_sections)["assessment"]))
            st.markdown(
                f"""
                <div class="cv36-history-turn">
                  <div class="cv36-history-number">{index}</div>
                  <div><small>Review {index}</small><strong>{question}</strong><p>{assessment}</p></div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_follow_ups(*, question: str, answer: str, context: dict[str, Any]) -> None:
    suggestions = follow_up_suggestions(question, answer, context)
    if not suggestions:
        return
    st.markdown('<div class="cv35-section-label">Suggested follow-ups</div>', unsafe_allow_html=True)
    cols = st.columns(2)
    for index, suggestion in enumerate(suggestions):
        if cols[index % 2].button(
            suggestion,
            key=f"cv36_followup_{index}_{abs(hash(suggestion))}",
            use_container_width=True,
        ):
            # The question widget has already been instantiated in this run, so
            # queue the follow-up and apply it before the widget is created on
            # the next run. This avoids Streamlit's widget-state mutation error.
            st.session_state["cv36_pending_followup"] = suggestion
            _clear_review_state()
            st.rerun()


def _render_response(*, question: str, answer: str, context: dict[str, Any]) -> None:
    sections = _parse_report(answer)
    profile = _assessment_profile(sections)
    assessment = profile["assessment"]
    evidence = profile["evidence"]
    actions = profile["actions"]
    confidence = profile["confidence"]
    intent = profile["intent"]
    priority_part = _priority_component(context, evidence)
    confidence_label, confidence_score, confidence_detail = _confidence_data(confidence, context)
    confidence_class = "high" if confidence_score >= 75 else "medium" if confidence_score >= 45 else "low"
    decision = _decision_summary(context, assessment, confidence_score, priority_part, intent=intent, preferred_status=profile["status"])
    impact = _projected_impact(context, priority_part, intent=intent)
    complete, total, progress = _review_progress(context)

    st.markdown(
        f"""
        <div class="cv39-decision-card {decision['tone']}">
          <div class="cv39-decision-top">
            <div><div class="cv35-answer-label">{html.escape(profile["label"])}</div><h2>{html.escape(decision['status'])}</h2></div>
            <span class="cv39-status-badge">{html.escape(decision['risk'])} risk</span>
          </div>
          <div class="cv39-decision-grid">
            <div><span>Priority component</span><strong>{html.escape(decision['priority'])}</strong></div>
            <div><span>BOM health</span><strong>{html.escape(decision['health'])}</strong></div>
            <div><span>Decision confidence</span><strong>{html.escape(decision['confidence'])}</strong></div>
            <div><span>Review progress</span><strong>{complete} of {total}</strong></div>
          </div>
          <p>{html.escape(decision['assessment'])}</p>
        </div>
        <div class="cv39-progress-wrap"><div><strong>Engineering review progress</strong><span>{progress}%</span></div><div class="cv39-progress"><i style="width:{progress}%"></i></div></div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.25, 1])
    with left:
        st.markdown('<div class="cv35-section-label">Evidence breakdown</div>', unsafe_allow_html=True)
        _render_evidence_cards(evidence)
    with right:
        st.markdown('<div class="cv35-section-label">Projected engineering impact</div>', unsafe_allow_html=True)
        impact_html = "".join(
            f'<div class="cv39-impact-row"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong><small>{html.escape(note)}</small></div>'
            for label, value, note in impact
        )
        st.markdown(f'<div class="cv39-impact-card">{impact_html}<p>Projections are directional estimates based on saved evidence, not measured outcomes.</p></div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="cv35-confidence-card {confidence_class}">
              <div class="cv35-confidence-top"><span>Decision confidence</span><strong>{confidence_score}%</strong></div>
              <div class="cv35-confidence-track"><div style="width:{confidence_score}%"></div></div>
              <div class="cv35-confidence-label">{html.escape(confidence_label)}</div>
              <div class="cv35-confidence-detail">{html.escape(confidence_detail)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="cv35-section-label">Priority timeline</div>', unsafe_allow_html=True)
    workflow = _workflow_steps(actions, priority_part, intent=intent)
    workflow_cols = st.columns(len(workflow))
    for idx, ((label, detail), col) in enumerate(zip(workflow, workflow_cols), start=1):
        col.markdown(
            f'<div class="cv39-timeline-step"><b>{idx}</b><strong>{html.escape(label)}</strong><p>{html.escape(detail)}</p></div>',
            unsafe_allow_html=True,
        )
    _render_quick_actions(context, priority_part)

def render_engineering_assistant(
    *,
    current_user: dict[str, Any],
    engineering_context: Any,
    selected_component: str = "",
) -> None:
    context = engineering_context.compact(max_components=15) if hasattr(engineering_context, "compact") else dict(engineering_context or {})
    status = get_ai_usage_status(st.session_state, current_user)

    st.markdown(
        """
        <style id="cadivor-engineering-assistant-38">
        .cv35-hero{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f6f9ff 62%,#eaf2ff);border-radius:24px;padding:22px;margin:2px 0 14px;box-shadow:0 18px 50px rgba(37,99,235,.08)}
        .cv35-kicker,.cv35-answer-label,.cv35-section-label,.cv35-card-kicker{font-size:10px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#2563eb!important}.cv35-hero h2{font-size:27px;line-height:1.1;letter-spacing:-.035em;color:#0f172a!important;margin:0 0 8px}.cv35-hero p{font-size:13px;line-height:1.6;color:#52647a!important;font-weight:700;margin:0;max-width:900px}
        .cv35-usage{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:11px 13px;margin:0 0 12px}.cv35-usage strong{font-size:11px;color:#0f172a!important}.cv35-usage span{font-size:10px;color:#52647a!important;font-weight:800}.cv35-usage.high,.cv35-usage.critical{border-color:#fde68a;background:#fffbeb}.cv35-usage.reached{border-color:#fecaca;background:#fef2f2}
        .cv35-message{display:flex;align-items:flex-start;gap:12px;border-radius:16px;padding:14px 15px;margin-top:14px}.cv35-message-error{border:1px solid #fecaca;background:#fff7f7}.cv35-message-icon{display:grid;place-items:center;width:24px;height:24px;border-radius:999px;background:#fee2e2;color:#b91c1c;font-weight:950;flex:0 0 auto}.cv35-message strong{display:block;color:#7f1d1d!important;font-size:13px;margin-bottom:3px}.cv35-message p{margin:0;color:#7f1d1d!important;font-size:12px;line-height:1.5}
        .cv35-review-shell{border:1px solid #bfdbfe;background:linear-gradient(145deg,#fff,#f8fbff);border-radius:22px;padding:20px 21px;margin:18px 0 16px;box-shadow:0 16px 42px rgba(15,23,42,.06)}
        .cv35-question{border-left:4px solid #60a5fa;background:#f3f8ff;border-radius:12px;padding:12px 14px;margin-bottom:18px;color:#0f172a;font-size:13px;font-weight:800}.cv35-question small{display:block;color:#64748b;font-size:9px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px}.cv35-review-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.cv35-review-heading h2{font-size:24px;letter-spacing:-.035em;color:#0f172a!important;margin:7px 0 8px}.cv35-review-status{border:1px solid #bbf7d0;background:#ecfdf5;color:#047857;border-radius:999px;padding:7px 10px;font-size:10px;font-weight:900;white-space:nowrap}.cv35-assessment-copy{font-size:14px;line-height:1.7;color:#334155;font-weight:650;max-width:1100px}
        .cv35-section-label{margin:18px 0 9px}.cv35-evidence-card{min-height:150px;border:1px solid #dbeafe;background:#fff;border-radius:17px;padding:15px 16px;margin-bottom:10px;box-shadow:0 9px 24px rgba(15,23,42,.04)}.cv35-evidence-card:hover{border-color:#93c5fd;transform:translateY(-1px)}.cv35-evidence-part{font-size:14px;font-weight:950;color:#0f172a;margin-bottom:7px}.cv35-evidence-detail{font-size:12px;line-height:1.58;color:#52647a;font-weight:650}
        .cv35-action-card,.cv35-confidence-card{height:100%;min-height:165px;border:1px solid #dbeafe;background:#fff;border-radius:19px;padding:17px 18px;margin-top:10px}.cv35-action-copy{font-size:13px;line-height:1.65;color:#334155;font-weight:680;margin-top:10px}.cv35-confidence-top{display:flex;align-items:center;justify-content:space-between;color:#475569;font-size:11px;font-weight:900}.cv35-confidence-top strong{font-size:24px;color:#0f172a}.cv35-confidence-track{height:9px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin:13px 0 10px}.cv35-confidence-track div{height:100%;border-radius:999px;background:linear-gradient(90deg,#2563eb,#60a5fa)}.cv35-confidence-card.high .cv35-confidence-track div{background:linear-gradient(90deg,#059669,#34d399)}.cv35-confidence-card.low .cv35-confidence-track div{background:linear-gradient(90deg,#d97706,#fbbf24)}.cv35-confidence-label{font-size:15px;font-weight:950;color:#0f172a;margin-bottom:6px}.cv35-confidence-detail{font-size:11px;line-height:1.5;color:#64748b;font-weight:650}
        .cv35-mode-note{border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:11px 13px;margin-top:12px;color:#52647a;font-size:11px;font-weight:700}
        .cv36-history-turn{display:flex;gap:12px;border-bottom:1px solid #e2e8f0;padding:13px 2px}.cv36-history-turn:last-child{border-bottom:0}.cv36-history-number{display:grid;place-items:center;width:25px;height:25px;border-radius:999px;background:#eff6ff;color:#2563eb;font-size:10px;font-weight:950;flex:0 0 auto}.cv36-history-turn small{display:block;color:#64748b;font-size:9px;text-transform:uppercase;letter-spacing:.08em}.cv36-history-turn strong{display:block;color:#0f172a;font-size:12px;margin:3px 0 5px}.cv36-history-turn p{color:#52647a;font-size:11px;line-height:1.5;margin:0}.cv36-followup-note{border:1px solid #bfdbfe;background:#eff6ff;border-radius:14px;padding:11px 13px;margin:10px 0;color:#1e40af;font-size:11px;font-weight:800}

        .cv38-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:18px}.cv38-kpi{border:1px solid #dbeafe;background:#fff;border-radius:14px;padding:12px 13px}.cv38-kpi span{display:block;font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;font-weight:900}.cv38-kpi strong{display:block;font-size:17px;color:#0f172a;margin:5px 0 2px}.cv38-kpi small{font-size:10px;color:#64748b;font-weight:650}
        .cv35-evidence-head{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:10px}.cv35-evidence-head span{font-size:9px;font-weight:900;color:#2563eb;background:#eff6ff;border-radius:999px;padding:5px 8px}.cv38-evidence-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.cv38-evidence-metric{border-top:1px solid #eef2f7;padding-top:7px}.cv38-evidence-metric span{display:block;font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:#64748b;font-weight:850}.cv38-evidence-metric strong{display:block;font-size:11px;color:#334155;margin-top:3px;line-height:1.35}
        .cv38-action-panel{margin-top:18px!important}.cv38-action-list{margin-top:12px}.cv38-action-step{display:flex;gap:10px;align-items:flex-start;border-bottom:1px solid #eef2f7;padding:10px 0}.cv38-action-step:last-child{border-bottom:0}.cv38-action-step span{display:grid;place-items:center;width:23px;height:23px;border-radius:999px;background:#eff6ff;color:#2563eb;font-size:10px;font-weight:950;flex:0 0 auto}.cv38-action-step p{margin:1px 0 0;font-size:12px;line-height:1.5;color:#334155;font-weight:700}

        .cv39-decision-card{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f5f9ff);border-radius:22px;padding:20px 21px;margin:18px 0 12px;box-shadow:0 16px 42px rgba(15,23,42,.06)}.cv39-decision-card.ready{border-color:#a7f3d0;background:linear-gradient(135deg,#fff,#ecfdf5)}.cv39-decision-card.critical{border-color:#fecaca;background:linear-gradient(135deg,#fff,#fff1f2)}.cv39-decision-top{display:flex;align-items:flex-start;justify-content:space-between;gap:15px}.cv39-decision-top h2{font-size:26px;color:#0f172a!important;letter-spacing:-.035em;margin:6px 0 12px}.cv39-status-badge{border:1px solid #fde68a;background:#fffbeb;color:#92400e;border-radius:999px;padding:7px 10px;font-size:10px;font-weight:950}.cv39-decision-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:4px 0 14px}.cv39-decision-grid div{border:1px solid #dbeafe;background:rgba(255,255,255,.85);border-radius:13px;padding:11px 12px}.cv39-decision-grid span{display:block;font-size:9px;text-transform:uppercase;letter-spacing:.07em;color:#64748b;font-weight:900}.cv39-decision-grid strong{display:block;color:#0f172a;font-size:14px;margin-top:5px}.cv39-decision-card>p{margin:0;color:#334155;font-size:13px;line-height:1.65;font-weight:650}.cv39-progress-wrap{border:1px solid #dbeafe;background:#fff;border-radius:14px;padding:12px 14px;margin-bottom:12px}.cv39-progress-wrap>div:first-child{display:flex;justify-content:space-between;font-size:11px;color:#334155}.cv39-progress{height:8px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin-top:8px}.cv39-progress i{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:999px}.cv39-impact-card{border:1px solid #dbeafe;background:#fff;border-radius:18px;padding:14px 16px;margin-bottom:10px}.cv39-impact-row{display:grid;grid-template-columns:1fr auto;gap:4px 12px;border-bottom:1px solid #eef2f7;padding:10px 0}.cv39-impact-row:last-of-type{border-bottom:0}.cv39-impact-row span{font-size:11px;color:#64748b;font-weight:850}.cv39-impact-row strong{font-size:12px;color:#0f172a}.cv39-impact-row small{grid-column:1/-1;color:#64748b;font-size:9px}.cv39-impact-card>p{font-size:9px;color:#64748b;margin:10px 0 0}.cv39-timeline-step{min-height:150px;border:1px solid #dbeafe;background:#fff;border-radius:16px;padding:13px 12px;position:relative}.cv39-timeline-step b{display:grid;place-items:center;width:24px;height:24px;border-radius:999px;background:#2563eb;color:#fff;font-size:10px;margin-bottom:10px}.cv39-timeline-step strong{display:block;color:#0f172a;font-size:12px}.cv39-timeline-step p{font-size:10px;line-height:1.45;color:#64748b;margin:7px 0 0}
        @media(max-width:900px){.cv38-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cv38-evidence-grid{grid-template-columns:1fr}.cv39-decision-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cv39-decision-top{display:block}.cv39-status-badge{display:inline-block;margin-bottom:8px}.cv39-timeline-step{min-height:auto}.cv35-review-heading{display:block}.cv35-review-status{display:inline-block;margin-top:6px}.cv35-evidence-card{min-height:auto}}
        </style>
        <div class="cv35-hero"><div class="cv35-kicker">Engineering Copilot</div><h2>Ask Cadivor about this BOM</h2><p>Type any engineering question about this BOM. Cadivor interprets the request, evaluates the saved evidence, and recommends the next engineering action.</p></div>
        """,
        unsafe_allow_html=True,
    )
    _usage_banner(status)
    thread = get_thread(st.session_state, context)
    if thread:
        utility_left, utility_right = st.columns([1, 4])
        if utility_left.button("New conversation", key="cv36_new_conversation", use_container_width=True):
            clear_thread(st.session_state, context)
            _clear_review_state()
            st.session_state["cv35_question"] = ""
            st.session_state.pop("cv36_pending_followup", None)
            st.rerun()
        utility_right.caption(f"{len(thread)} review{'s' if len(thread) != 1 else ''} in this BOM conversation")

    prompt_key = "cv35_question"
    auto_execute_followup = False
    pending_manual = st.session_state.pop("cv41_pending_manual", None)
    pending_followup = st.session_state.pop("cv36_pending_followup", None)
    if pending_manual:
        st.session_state[prompt_key] = str(pending_manual)
        auto_execute_followup = True
    elif pending_followup:
        # Apply queued follow-ups before the text-area widget is instantiated.
        st.session_state[prompt_key] = str(pending_followup)
        auto_execute_followup = True
    elif prompt_key not in st.session_state:
        st.session_state[prompt_key] = ""
    suggestion_cols = st.columns(3)
    for idx, suggestion in enumerate(SUGGESTIONS):
        if suggestion_cols[idx % 3].button(suggestion, key=f"cv35_suggestion_{idx}", use_container_width=True):
            st.session_state[prompt_key] = suggestion
            _clear_review_state()
            st.rerun()

    # A form submits the browser's current text-area value and the button click
    # in one transaction. This prevents pasted text from requiring a first click
    # merely to synchronize the widget before the button becomes enabled.
    with st.form("cv41_engineering_question_form", clear_on_submit=False):
        question = st.text_area(
            "Engineering question",
            key=prompt_key,
            height=88,
            placeholder="Ask your own question, for example: What evidence is missing before release approval?",
        )
        component_note = f" Current component focus: {selected_component}." if selected_component else ""
        st.caption("Ask in your own words. Cadivor uses the saved evidence in this analysis and identifies uncertainty when supporting data is incomplete." + component_note)
        manual_submit = st.form_submit_button(
            "Ask Engineering Copilot",
            type="primary",
            disabled=not status.can_use,
            use_container_width=False,
        )

    cleaned_question = str(question or "").strip()
    manual_submit_requested = bool(manual_submit and status.can_use and cleaned_question)
    if manual_submit and not cleaned_question:
        st.warning("Enter an engineering question before submitting.")
    if manual_submit_requested:
        _clear_review_state()

    can_submit = status.can_use and bool(cleaned_question)
    submit_requested = bool(manual_submit_requested or (auto_execute_followup and can_submit))
    if submit_requested:
        api = EngineeringAI(
            api_key=_secret("OPENAI_API_KEY"),
            model=_secret("OPENAI_MODEL", "gpt-4.1-mini"),
            base_url=_secret("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        st.session_state.pop("cv35_last_error", None)
        with st.status("Cadivor is reviewing the saved engineering evidence...", expanded=False) as progress:
            try:
                response = api.ask(question=question, context=context, history=compact_history(thread))
                consume_ai_credits(st.session_state, current_user, action="question")
                st.session_state["cv35_last_answer"] = response.answer
                st.session_state["cv35_last_question"] = question
                st.session_state["cv35_provider_connected"] = api.configured
                thread = append_turn(
                    st.session_state,
                    context,
                    question=question,
                    answer=response.answer,
                    provider_connected=api.configured,
                )
                progress.update(label="Engineering review complete", state="complete")
            except EngineeringAIError as exc:
                st.session_state["cv35_last_error"] = exc
                progress.update(label="Cadivor could not complete the review", state="error")

    thread = get_thread(st.session_state, context)
    current_answer = st.session_state.get("cv35_last_answer")
    _render_conversation_history(thread, exclude_latest=bool(current_answer))

    error_message = st.session_state.get("cv35_last_error")
    if isinstance(error_message, EngineeringAIError):
        _render_error(error_message)

    answer = st.session_state.get("cv35_last_answer")
    if answer:
        last_question = str(st.session_state.get("cv35_last_question") or "Engineering review")
        _render_response(question=last_question, answer=answer, context=context)
        _render_follow_ups(question=last_question, answer=answer, context=context)
        if not st.session_state.get("cv35_provider_connected", False):
            st.markdown(
                '<div class="cv35-mode-note">This assessment is grounded in the engineering evidence saved with the BOM. Validate final release, sourcing, and compatibility decisions against current approved datasheets and organizational requirements.</div>',
                unsafe_allow_html=True,
            )
