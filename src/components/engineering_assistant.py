"""Premium user-facing Engineering Copilot panel."""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlencode, quote

import streamlit as st
import streamlit.components.v1 as components

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




def _normalize_submitted_question(value: Any) -> str:
    """Return one active question and discard accidental duplicated history text."""
    text = str(value or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    # Follow-up questions are submitted as one prompt. If stale widget state has
    # concatenated prior prompts, use the final non-empty paragraph only.
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    candidate = paragraphs[-1] if paragraphs else text
    lines = [line.strip() for line in candidate.splitlines() if line.strip()]
    if len(lines) > 1 and all(line.endswith(("?", ".")) for line in lines):
        candidate = lines[-1]
    return candidate[:1200]


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
    """Normalize Sprint 47 and Sprint 47.1 reports into one renderer profile."""
    explicit_intent=_section(sections, "Intent").strip()
    intent_map={
        "Procurement":("procurement","Procurement assessment","Secure the purchasing window"),
        "Supplier Qualification":("supplier_qualification","Supplier qualification assessment","Qualify the preferred supplier"),
        "Single Source Exposure":("single_source","Single-source exposure assessment","Reduce sourcing concentration"),
        "Schedule Resilience":("schedule_resilience","Schedule resilience assessment","Strengthen production continuity"),
        "Lifecycle":("lifecycle","Lifecycle assessment","Mitigate lifecycle exposure"),
        "Inventory":("inventory","Inventory assessment","Protect material availability"),
        "Production Readiness":("production_readiness","Production readiness assessment","Close release blockers"),
        "General Engineering Review":("general","Engineering assessment","Review before release"),
        "Recommendation Rationale":("recommendation_rationale","Recommendation rationale","Explain the priority"),
        "Evidence Sensitivity":("evidence_sensitivity","Evidence sensitivity assessment","Identify decision-changing evidence"),
        "Engineering Owner Action Plan":("owner_action_plan","Engineering owner action plan","Execute the next controlled action"),
        "Owner Action Plan":("owner_action_plan","Engineering owner action plan","Execute the next controlled action"),
        "Component Risk":("component_risk","Component risk assessment","Highest component risks"),
        "Evidence Gap Priority":("evidence_gap_priority","Evidence gap priority","Close the highest-impact evidence gap"),
    }
    if explicit_intent in intent_map:
        intent,label,status=intent_map[explicit_intent]
        return {"intent":intent,"label":label,"status":status,"assessment":_section(sections,"Direct Answer","Executive Summary"),"evidence":_section(sections,"Evidence","Supporting Evidence"),"actions":_section(sections,"Recommended Actions","Recommended action"),"confidence":_section(sections,"Confidence"),"rankings":_section(sections,"Rankings"),"workflow":_section(sections,"Workflow"),"followups":_section(sections,"Follow-up Questions")}
    ordered=[key for key,value in sections.items() if str(value or "").strip()]
    first=ordered[0] if ordered else "Engineering Assessment"; first_l=first.lower()
    if "schedule resilience" in first_l: intent,label,status="schedule_resilience","Schedule resilience assessment","Strengthen production continuity"
    elif "procurement" in first_l: intent,label,status="procurement","Procurement assessment","Secure the purchasing window"
    elif "lifecycle" in first_l: intent,label,status="lifecycle","Lifecycle assessment","Address lifecycle exposure"
    elif "release" in first_l: intent,label,status="production_readiness","Release readiness assessment","Review before release"
    elif "supplier" in first_l or "second-source" in first_l: intent,label,status="supplier_qualification","Supplier qualification assessment","Build sourcing resilience"
    else: intent,label,status="general","Engineering assessment","Review before release"
    return {"intent":intent,"label":label,"status":status,"assessment":sections.get(first,"") or _section(sections,"Engineering Assessment","Assessment"),"evidence":_section(sections,"Supporting Evidence","Evidence","Procurement Evidence","Schedule Resilience Evidence","Supplier Evidence","Lifecycle Evidence","Release Evidence"),"actions":_section(sections,"Recommended Actions","Recommended action"),"confidence":_section(sections,"Confidence"),"rankings":"","workflow":"","followups":""}


def _direct_answer_title(assessment: str, fallback: str) -> str:
    plain = str(assessment or "").strip()
    match = re.match(r"\*\*(.+?)\*\*\.\s*", plain)
    if match:
        return _plain_markdown(match.group(1)).strip() or fallback
    return fallback

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
    components = list(context.get("components") or [])
    known = {
        str(row.get("part_number") or row.get("mpn") or "").strip().upper():
        str(row.get("part_number") or row.get("mpn") or "").strip()
        for row in components
        if str(row.get("part_number") or row.get("mpn") or "").strip()
    }
    for title, _ in _evidence_items(evidence):
        if title.strip().upper() in known:
            return known[title.strip().upper()]
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


def _metric_display(label: str) -> tuple[str, str]:
    """Return a compact semantic icon and user-facing evidence label."""
    normalized = str(label or "Signal").strip().lower()
    if "recommendation score" in normalized:
        return "★", "Recommendation score"
    if normalized == "recommendation" or "ai recommendation" in normalized:
        return "✓", "Cadivor recommendation"
    if "priority" in normalized:
        return "↑", "Qualification priority"
    if normalized == "status":
        return "✓", "Validation status"
    if normalized == "verify":
        return "□", "Verification required"
    if "risk" in normalized:
        return "!", "Risk score"
    if normalized == "signal":
        return "•", "Evidence"
    if "lifecycle" in normalized:
        return "◷", "Lifecycle"
    if "supplier coverage" in normalized or "source coverage" in normalized:
        return "S", "Supplier coverage"
    if "supplier" in normalized or "source" in normalized:
        return "S", "Sources"
    if "stock" in normalized or "inventory" in normalized or "units" in normalized:
        return "□", "Inventory"
    if "lead" in normalized or "week" in normalized:
        return "↗", "Lead time"
    if "rationale" in normalized or "reason" in normalized:
        return "i", "Why it qualifies"
    if "package" in normalized or "footprint" in normalized:
        return "◇", "Package / footprint"
    if "voltage" in normalized or "electrical" in normalized:
        return "~", "Electrical"
    return "•", str(label or "Evidence").strip().title()




def _confidence_drivers(context: dict[str, Any], evidence: str) -> list[tuple[str, str, str]]:
    """Return concrete positive and limiting confidence signals."""
    coverage = context.get("coverage") or {}
    components = list(context.get("components") or [])
    evidence_items = _evidence_items(evidence)
    decisions = context.get("decisions") or context.get("engineering_decisions") or []
    alternatives = context.get("alternatives") or context.get("saved_alternatives") or []
    lifecycle_known = sum(bool(str(row.get("lifecycle_status") or "").strip()) for row in components)
    supplier_known = sum(int(row.get("supplier_count") or 0) > 0 for row in components)
    lead_known = sum(float(row.get("lead_time_weeks") or 0) > 0 for row in components)
    inventory_known = sum(row.get("stock_available") not in (None, "") for row in components)
    total = len(components)
    drivers: list[tuple[str, str, str]] = []
    if lifecycle_known:
        drivers.append(("Verified", f"Lifecycle recorded for {lifecycle_known}/{total}", "Raises confidence in lifecycle-related recommendations"))
    if supplier_known:
        drivers.append(("Verified", f"Supplier coverage for {supplier_known}/{total}", "Supports sourcing-diversity conclusions"))
    if inventory_known:
        drivers.append(("Verified", f"Inventory recorded for {inventory_known}/{total}", "Supports near-term availability assessment"))
    if evidence_items:
        drivers.append(("Verified", f"{len(evidence_items)} structured evidence signal(s)", "Directly supports the current recommendation"))
    if lead_known < total:
        drivers.append(("Missing", f"Lead time missing for {max(0, total-lead_known)} component(s)", "Limits schedule-risk precision"))
    if not decisions:
        drivers.append(("Missing", "No saved decision history", "No prior approval or risk-acceptance evidence"))
    if not alternatives:
        drivers.append(("Missing", "No saved qualified alternatives", "Replacement and second-source confidence remains limited"))
    score = int(coverage.get("score") or 0)
    if score < 75:
        drivers.append(("Coverage", f"Overall evidence coverage is {score}%", "Additional verified fields would raise confidence"))
    return drivers[:6]


def _recommendation_explanation(assessment: str, evidence: str, priority_part: str) -> tuple[str, list[str]]:
    """Create a readable explanation without inventing evidence."""
    summary = _plain_markdown(assessment)
    items = _evidence_items(evidence)
    selected_detail = ""
    for title, detail in items:
        if priority_part and title.strip().upper() == priority_part.strip().upper():
            selected_detail = detail
            break
    if not selected_detail and items:
        selected_detail = items[0][1]
    drivers: list[str] = []
    for label, value in _split_evidence_detail(selected_detail):
        normalized = label.lower()
        if any(token in normalized for token in ("rationale", "reason")):
            drivers.extend([piece.strip().rstrip(".") for piece in value.split(",") if piece.strip()])
        elif any(token in normalized for token in ("recommendation score", "priority", "risk", "lifecycle", "supplier coverage", "lead time", "inventory")):
            drivers.append(f"{label}: {value.rstrip('.')}" )
    if not drivers and selected_detail:
        drivers = [selected_detail.rstrip(".")]
    return summary, drivers[:5]


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



def _intent_kpis(context: dict[str, Any], *, intent: str, priority_part: str, confidence_score: int, complete: int, total: int) -> list[tuple[str, str]]:
    components = list(context.get("components") or [])
    alternatives = list(context.get("alternatives") or context.get("saved_alternatives") or [])
    decisions = list(context.get("decisions") or context.get("engineering_decisions") or [])
    monitoring = list(context.get("monitoring") or [])
    priority = next((r for r in components if str(r.get("part_number") or r.get("mpn") or "").upper() == str(priority_part).upper()), {})
    suppliers = int(priority.get("supplier_count") or 0) if priority else 0
    stock = int(priority.get("stock_available") or 0) if priority else 0
    lead = float(priority.get("lead_time_weeks") or 0) if priority else 0
    lifecycle = str(priority.get("lifecycle_status") or priority.get("lifecycle") or "Unknown") if priority else "Unknown"
    low_source = sum(1 for r in components if int(r.get("supplier_count") or 0) <= 1)
    lifecycle_exposed = sum(1 for r in components if any(x in str(r.get("lifecycle_status") or r.get("lifecycle") or "").lower() for x in ("obsolete","eol","nrnd","replacement","not recommended")))
    long_lead = sum(1 for r in components if float(r.get("lead_time_weeks") or 0) >= 12)
    no_stock = sum(1 for r in components if int(r.get("stock_available") or 0) <= 0)
    maps = {
        "procurement": [("Purchasing priority", priority_part or "Evidence required"), ("Recorded stock", f"{stock:,}"), ("Lead time", f"{lead:g} weeks"), ("Source coverage", f"{suppliers} source(s)")],
        "supplier_qualification": [("Qualification target", priority_part or "No candidate"), ("Candidate sources", str(suppliers)), ("Qualified alternatives", str(len(alternatives))), ("Supplier confidence", f"{confidence_score}%")],
        "single_source": [("Highest exposure", priority_part or "Evidence required"), ("Single-source parts", str(low_source)), ("Source coverage", f"{suppliers} source(s)"), ("Mitigation confidence", f"{confidence_score}%")],
        "schedule_resilience": [("Critical-path part", priority_part or "Evidence required"), ("Lead time", f"{lead:g} weeks"), ("Long-lead parts", str(long_lead)), ("Schedule confidence", f"{confidence_score}%")],
        "lifecycle": [("Migration priority", priority_part or "Evidence required"), ("Lifecycle status", lifecycle), ("Exposed parts", str(lifecycle_exposed)), ("Lifecycle confidence", f"{confidence_score}%")],
        "inventory": [("Lowest-coverage part", priority_part or "Evidence required"), ("Recorded stock", f"{stock:,}"), ("No-stock parts", str(no_stock)), ("Inventory confidence", f"{confidence_score}%")],
        "production_readiness": [("Leading blocker", priority_part or "Evidence required"), ("Open decisions", str(max(0, len(components)-len(decisions)))), ("Evidence coverage", f"{confidence_score}%"), ("Release checks", f"{complete} of {total}")],
        "evidence_sensitivity": [("Decision affected", priority_part or "BOM release"), ("Evidence coverage", f"{confidence_score}%"), ("Saved decisions", str(len(decisions))), ("Active monitoring", str(len(monitoring)))],
        "evidence_gap_priority": [("Evidence target", priority_part or "BOM evidence"), ("Evidence coverage", f"{confidence_score}%"), ("Qualified alternatives", str(len(alternatives))), ("Saved decisions", str(len(decisions)))],
    }
    return maps.get(intent, [("Priority component", priority_part or "No priority component"), ("BOM components", str(len(components))), ("Decision confidence", f"{confidence_score}%"), ("Review progress", f"{complete} of {total}")])


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
    if intent in {"schedule", "schedule_resilience"}:
        if intent == "schedule_resilience":
            return [("Source paths", f"{suppliers} → {max(suppliers + 1, 2)}", "After a qualified second source is approved"), ("Replenishment continuity", "Single path → Dual path", "Reduces dependency on one supplier route"), ("Lead-time exposure", f"{lead:g} weeks → Diversified", "Alternate commercial lead time provides recovery capacity"), ("Schedule posture", "Exposed → More resilient", "After capacity, compatibility, and quality validation")]
        return [("Replenishment exposure", f"{lead:g} weeks → Validate", "Confirm with authorized suppliers"), ("Schedule risk", "Elevated → Reduced", "After allocation or alternate qualification"), ("Inventory coverage", f"{stock:,} recorded", "Compare against production demand"), ("Source resilience", f"{suppliers} source(s) → Improve", "Qualify an alternate or second source")]
    if intent == "supplier":
        return [("Supplier coverage", f"{suppliers} → {max(suppliers+1,2)}", "If a second source is qualified"), ("Concentration risk", "Current → Reduced", "After authorized-source validation"), ("Priority risk", f"{score}/100 → Reduced", "After mitigation or acceptance")]
    if intent == "second_source":
        target_sources = max(suppliers + 1, 2)
        return [("Approved-source coverage", f"{suppliers} → {target_sources}", "After alternate supplier qualification"), ("Supply continuity", "Exposed → Resilient", "After dual-source approval"), ("Lead-time exposure", f"{lead:g} weeks → Diversified", "Compare alternate replenishment windows"), ("Procurement confidence", "Conditional → Improved", "After authorization and commercial validation")]
    if intent == "second_source_validation":
        return [("Electrical equivalence", "Unverified → Documented", "Approved datasheet comparison"), ("Footprint compatibility", "Unverified → Confirmed", "Package and PCB review"), ("Authorized sourcing", "Pending → Approved", "Traceability and supplier authorization"), ("Production validation", "Pending → Complete", "Prototype and manufacturing evidence")]
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
        "schedule_resilience": ["Map source dependency", "Confirm alternate capacity", "Validate compatibility", "Approve dual sourcing", "Monitor continuity"],
        "supplier": ["Verify sources", "Check authorization", "Qualify second source", "Set monitoring", "Record mitigation"],
        "second_source": ["Confirm approved sources", "Identify authorized alternate", "Validate compatibility", "Approve supplier", "Release dual-source plan"],
        "second_source_validation": ["Compare datasheets", "Verify pinout and footprint", "Validate prototype", "Approve quality and sourcing", "Release second source"],
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
        message = _plain_markdown(evidence) or "No structured evidence was returned. Verify that component records are saved and re-run the review."
        st.markdown(f'<div class="cv46-empty-evidence">{html.escape(message)}</div>', unsafe_allow_html=True)
        return
    cards: list[str] = []
    for title, detail in items[:8]:
        metrics = _split_evidence_detail(detail)
        metric_blocks = []
        for label, value in metrics[:4]:
            icon, display_label = _metric_display(label)
            metric_blocks.append(
                f'<div class="cv46-evidence-metric"><span><i>{html.escape(icon)}</i>{html.escape(display_label)}</span><strong>{html.escape(value)}</strong></div>'
            )
        status = "Priority" if any(token in detail.lower() for token in ("qualify immediately", "high", "obsolete", "replacement", "single-source")) else "Review"
        cards.append(
            f'<article class="cv46-evidence-card"><header><strong>{html.escape(title)}</strong><em>{status}</em></header>'
            f'<div class="cv46-evidence-metrics">{"".join(metric_blocks)}</div></article>'
        )
    st.markdown(f'<div class="cv46-evidence-board">{"".join(cards)}</div>', unsafe_allow_html=True)


def _render_quick_actions(context: dict[str, Any], priority_part: str, *, intent: str = "general") -> None:
    analysis = context.get("analysis") or {}
    analysis_id = str(analysis.get("analysis_id") or "")
    if not analysis_id:
        return
    st.markdown('<div class="cv35-section-label">Continue the workflow</div>', unsafe_allow_html=True)
    part_label = priority_part or "component"
    component_url = _href("Analysis Details", analysis_id=analysis_id, tab="components", component=priority_part, focus="component-risk")
    alternative_url = _href("Alternative Finder", original_part=priority_part, analysis_id=analysis_id)
    monitoring_url = _href("Monitoring", mpn=priority_part, analysis_id=analysis_id)
    decision_url = _href("Engineering Decisions", analysis_id=analysis_id, part_number=priority_part)
    procurement_url = _href("Procurement Advisor", analysis_id=analysis_id, part_number=priority_part)

    action_sets = {
        "procurement": [("Open procurement review", procurement_url), (f"Review {part_label}", component_url), (f"Find {part_label} alternative", alternative_url), ("Record sourcing decision", decision_url)],
        "supplier_qualification": [("Open supplier review", procurement_url), (f"Review {part_label}", component_url), (f"Find qualified alternative", alternative_url), ("Record supplier approval", decision_url)],
        "single_source": [(f"Review {part_label}", component_url), ("Find independent backup", alternative_url), (f"Monitor {part_label}", monitoring_url), ("Record source mitigation", decision_url)],
        "schedule_resilience": [(f"Review {part_label}", component_url), ("Find recovery source", alternative_url), (f"Monitor delivery risk", monitoring_url), ("Record recovery plan", decision_url)],
        "lifecycle": [(f"Review {part_label}", component_url), ("Find lifecycle successor", alternative_url), (f"Monitor lifecycle", monitoring_url), ("Record migration decision", decision_url)],
        "inventory": [("Open procurement review", procurement_url), (f"Review {part_label}", component_url), ("Find replenishment option", alternative_url), (f"Monitor stock", monitoring_url)],
        "production_readiness": [(f"Review blocker", component_url), ("Resolve alternative path", alternative_url), ("Monitor release blocker", monitoring_url), ("Record release decision", decision_url)],
        "evidence_sensitivity": [(f"Open evidence source", component_url), ("Validate alternate evidence", alternative_url), ("Monitor evidence changes", monitoring_url), ("Update engineering record", decision_url)],
        "evidence_gap_priority": [(f"Open evidence source", component_url), ("Collect alternate evidence", alternative_url), ("Monitor evidence closure", monitoring_url), ("Record evidence decision", decision_url)],
    }
    actions = action_sets.get(intent, [(f"Open {part_label}", component_url), (f"Find {part_label} alternative", alternative_url), (f"Monitor {part_label}", monitoring_url), ("Create engineering record", decision_url)])
    cols = st.columns(4)
    for col, (label, url) in zip(cols, actions):
        col.link_button(label, url, use_container_width=True)




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


def _queue_follow_up(question: str) -> None:
    clean = str(question or "").strip()
    if not clean:
        return
    st.session_state["cv36_pending_followup"] = clean
    st.session_state["cv47_followup_question"] = clean
    st.session_state["cv47_scroll_pending"] = True
    # Preserve the authenticated workspace across the rerun. Streamlit normally
    # keeps these values, but an explicit snapshot prevents a transient follow-up
    # rerun from falling through to the public landing route.
    # Capture everything required to survive the top-level Streamlit rerun.
    # The app's authentication gate executes before this component renders, so
    # the snapshot must be complete enough for streamlit_app.py to restore the
    # authenticated Analysis Details route before it considers the public page.
    try:
        route_snapshot = {key: value for key, value in st.query_params.items()}
    except Exception:
        route_snapshot = {}
    st.session_state["cv48_auth_snapshot"] = {
        key: st.session_state.get(key) for key in (
            "user", "access_token", "refresh_token", "app_mode",
            "pending_app_mode", "analysis_id", "selected_analysis",
            "current_analysis", "active_analysis_id",
        ) if st.session_state.get(key) is not None
    }
    st.session_state["cv4801_route_snapshot"] = route_snapshot
    st.session_state["cv4801_followup_inflight"] = True
    st.session_state["cv4801_auth_retry_count"] = 0
    _clear_review_state()
    st.rerun()


def _render_follow_ups(*, question: str, answer: str, context: dict[str, Any]) -> None:
    suggestions = follow_up_suggestions(question, answer, context)
    if suggestions:
        st.markdown('<div class="cv35-section-label">Suggested follow-ups</div>', unsafe_allow_html=True)
        cols = st.columns(2)
        for index, suggestion in enumerate(suggestions):
            button_label = f"↳  {suggestion}"
            if cols[index % 2].button(
                button_label,
                key=f"cv36_followup_{index}_{abs(hash(suggestion))}",
                use_container_width=True,
            ):
                _queue_follow_up(suggestion)

    st.markdown('<div class="cv35-section-label">Ask a different follow-up</div>', unsafe_allow_html=True)
    st.caption("Ask any new engineering question about this assessment or the BOM. You are not limited to the suggested questions.")
    with st.form("cv47_custom_followup_form", clear_on_submit=True):
        custom = st.text_area(
            "Your follow-up question",
            key="cv47_custom_followup_text",
            height=76,
            placeholder="For example: How would a 10-week delivery commitment change this recommendation?",
            label_visibility="collapsed",
        )
        submit_custom = st.form_submit_button("Ask follow-up", type="primary")
    if submit_custom:
        if str(custom or "").strip():
            _queue_follow_up(custom)
        else:
            st.warning("Enter a follow-up question before submitting.")


def _first_sentence(text: str) -> str:
    plain = _plain_markdown(text).strip()
    if not plain:
        return "Cadivor completed the engineering review."
    match = re.search(r"^(.+?[.!?])(?:\s|$)", plain)
    return (match.group(1) if match else plain).strip()


def _conversational_headline(intent: str, assessment: str, priority_part: str) -> str:
    plain = _plain_markdown(assessment).strip()
    lower = plain.lower()
    if intent == "production_readiness":
        if any(token in lower for token in ("not ready", "only after", "close", "blocker", "before release")):
            return "Not ready yet."
        if "ready with" in lower or "conditional" in lower:
            return "Ready with conditions."
        return "Production readiness requires review."
    if intent == "supplier_qualification":
        if any(token in lower for token in ("cannot recommend", "no supplier", "no named", "missing")):
            return "No supplier can be recommended yet."
        return f"Qualify {priority_part} first." if priority_part else "A supplier qualification priority is available."
    if intent == "evidence_sensitivity":
        return "This evidence is most likely to change the recommendation."
    if intent == "evidence_gap_priority":
        return "Close the highest-impact evidence gap first."
    if intent == "procurement":
        return f"Procurement should address {priority_part} first." if priority_part else "Procurement action is required."
    if intent == "schedule_resilience":
        return f"{priority_part} creates the greatest schedule exposure." if priority_part else "Schedule exposure requires review."
    if intent == "lifecycle":
        return f"{priority_part} has the leading lifecycle concern." if priority_part else "Lifecycle exposure requires review."
    if intent == "inventory":
        return f"{priority_part} has the most urgent inventory concern." if priority_part else "Inventory exposure requires review."
    if intent == "recommendation_rationale":
        return f"{priority_part} is ranked first for a specific evidence-based reason." if priority_part else "The priority is driven by the available evidence."
    if priority_part:
        return f"Review {priority_part} first."
    return "Cadivor cannot make a reliable component recommendation yet."


def _next_action(actions: str, workflow_text: str) -> str:
    for source in (actions, workflow_text):
        for line in str(source or "").splitlines():
            clean = _plain_markdown(line.lstrip("-* 0123456789.").strip())
            if clean:
                return _first_sentence(clean)
    return "Review the supporting evidence and assign an accountable engineering owner."


def _response_type_meta(intent: str) -> tuple[str, str]:
    mapping = {
        "component_risk": ("Recommendation", "recommendation"),
        "general": ("Recommendation", "recommendation"),
        "recommendation_rationale": ("Explanation", "explanation"),
        "evidence_sensitivity": ("Evidence review", "evidence"),
        "evidence_gap_priority": ("Evidence priority", "evidence"),
        "production_readiness": ("Release assessment", "release"),
        "supplier_qualification": ("Supplier assessment", "supplier"),
        "procurement": ("Procurement recommendation", "procurement"),
        "schedule_resilience": ("Schedule assessment", "schedule"),
        "lifecycle": ("Lifecycle assessment", "lifecycle"),
        "inventory": ("Inventory assessment", "inventory"),
        "single_source": ("Sourcing exposure", "supplier"),
        "owner_action_plan": ("Action plan", "action"),
    }
    return mapping.get(intent, ("Engineering response", "engineering"))


def _render_response_scroll_anchor(*, response_token: str) -> None:
    """Mount a self-locating scroll controller at the exact response start.

    Searching the parent document by a reused HTML id became unreliable after
    Streamlit began retaining and replacing conversation fragments.  This
    controller instead scrolls to the Streamlit element that owns its own iframe,
    so it cannot accidentally select an older response.
    """
    safe_token = html.escape(str(response_token or "response"))
    components.html(
        f"""
        <script data-cadivor-response-token="{safe_token}">
        (function(){{
          const parentWindow = window.parent;
          const parentDocument = parentWindow.document;
          const frame = window.frameElement;
          if (!frame) return;
          const host = frame.closest('[data-testid="stElementContainer"]') || frame.parentElement || frame;
          const OFFSET = 72;
          let attempts = 0;
          let stable = 0;
          let observer = null;

          function blurActiveInput(){{
            try {{
              const active = parentDocument.activeElement;
              if (active && typeof active.blur === 'function') active.blur();
            }} catch (_) {{}}
          }}

          function place(){{
            attempts += 1;
            if (!host || host.getClientRects().length === 0) {{
              if (attempts < 60) parentWindow.setTimeout(place, 100);
              return;
            }}
            blurActiveInput();
            const desired = Math.max(0, host.getBoundingClientRect().top + parentWindow.scrollY - OFFSET);
            parentWindow.scrollTo({{top: desired, behavior: attempts <= 2 ? 'smooth' : 'auto'}});
            const actualTop = Math.round(host.getBoundingClientRect().top);
            stable = Math.abs(actualTop - OFFSET) <= 18 ? stable + 1 : 0;
            if (stable >= 3 || attempts >= 60) {{
              if (observer) observer.disconnect();
              return;
            }}
            parentWindow.setTimeout(place, attempts < 12 ? 100 : 180);
          }}

          try {{
            observer = new MutationObserver(function(){{
              parentWindow.requestAnimationFrame(place);
            }});
            observer.observe(parentDocument.body, {{childList:true, subtree:true, attributes:true}});
          }} catch (_) {{}}

          parentWindow.requestAnimationFrame(function(){{
            parentWindow.requestAnimationFrame(place);
          }});
          [180, 350, 650, 1000, 1600, 2400, 3400].forEach(ms => parentWindow.setTimeout(place, ms));
        }})();
        </script>
        """,
        height=0,
    )


def _render_conversation_exchange(*, question: str, intent: str) -> None:
    response_label, response_class = _response_type_meta(intent)
    st.markdown(
        f'''
        <section id="cv50-conversation-start" tabindex="-1" data-cadivor-conversation-start="true" class="cv50-exchange">
          <div class="cv50-exchange-top">
            <div class="cv50-you-asked"><span>You asked</span><strong>{html.escape(question)}</strong></div>
            <div class="cv50-exchange-badges">
              <span class="cv50-type cv50-type-{html.escape(response_class)}">{html.escape(response_label)}</span>
              <span class="cv50-saved">✓ Review auto-saved</span>
            </div>
          </div>
        </section>
        ''',
        unsafe_allow_html=True,
    )


def _render_conversational_answer(*, intent: str, assessment: str, priority_part: str,
                                  confidence_score: int, drivers: list[str],
                                  actions: str, workflow_text: str) -> None:
    headline = _conversational_headline(intent, assessment, priority_part)
    answer_text = _plain_markdown(assessment).strip() or "The saved evidence is not sufficient for a reliable conclusion."
    reason_items = [str(item).strip() for item in drivers if str(item).strip()][:4]
    if not reason_items:
        reason_items = [answer_text]
    reasons_html = "".join(
        f'<li><span>✓</span><p>{html.escape(reason)}</p></li>' for reason in reason_items
    )
    next_action = _next_action(actions, workflow_text)
    st.markdown(
        f"""
        <section class="cv49-answer-card">
          <div class="cv49-answer-kicker">Cadivor Answer</div>
          <div class="cv49-answer-grid">
            <div class="cv49-answer-main">
              <h2>{html.escape(headline)}</h2>
              <p>{html.escape(answer_text)}</p>
              <ul>{reasons_html}</ul>
            </div>
            <aside class="cv49-answer-side">
              <span>Confidence</span><strong>{confidence_score}%</strong>
              <div class="cv49-answer-track"><i style="width:{max(0,min(100,confidence_score))}%"></i></div>
              <span>Recommended next action</span><p>{html.escape(next_action)}</p>
            </aside>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_response(*, question: str, answer: str, context: dict[str, Any], auto_scroll: bool = False) -> None:
    sections = _parse_report(answer)
    profile = _assessment_profile(sections)
    assessment = profile["assessment"]
    display_title = _direct_answer_title(assessment, profile["status"])
    assessment_body = re.sub(r"^\*\*.+?\*\*\.\s*", "", str(assessment or ""), count=1).strip() or _plain_markdown(assessment)
    evidence = profile["evidence"]
    actions = profile["actions"]
    confidence = profile["confidence"]
    rankings = profile.get("rankings", "")
    workflow_text = profile.get("workflow", "")
    intent = profile["intent"]
    priority_part = _priority_component(context, evidence)
    confidence_label, confidence_score, confidence_detail = _confidence_data(confidence, context)
    confidence_class = "high" if confidence_score >= 75 else "medium" if confidence_score >= 45 else "low"
    decision = _decision_summary(context, assessment_body, confidence_score, priority_part, intent=intent, preferred_status=display_title)
    impact = _projected_impact(context, priority_part, intent=intent)
    complete, total, progress = _review_progress(context)
    explanation, recommendation_drivers = _recommendation_explanation(assessment_body, evidence, priority_part)
    confidence_drivers = _confidence_drivers(context, evidence)

    if auto_scroll:
        response_token = f"{abs(hash((question, answer))) :x}"
        _render_response_scroll_anchor(response_token=response_token)

    _render_conversation_exchange(question=question, intent=intent)

    _render_conversational_answer(
        intent=intent,
        assessment=assessment_body,
        priority_part=priority_part,
        confidence_score=confidence_score,
        drivers=recommendation_drivers,
        actions=actions,
        workflow_text=workflow_text,
    )

    st.markdown(
        '<div class="cv50-supporting-divider"><span>Supporting engineering assessment</span><i></i></div>',
        unsafe_allow_html=True,
    )

    kpis = _intent_kpis(context, intent=intent, priority_part=priority_part, confidence_score=confidence_score, complete=complete, total=total)
    kpi_html = "".join(f'<div><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>' for label, value in kpis)
    progress_label = {
        "production_readiness": "Release-readiness review",
        "procurement": "Procurement review",
        "supplier_qualification": "Supplier qualification review",
        "schedule_resilience": "Schedule-resilience review",
        "lifecycle": "Lifecycle review",
        "inventory": "Inventory review",
        "evidence_sensitivity": "Evidence-confidence review",
    }.get(intent, "Engineering review progress")
    st.markdown(
        f"""
        <div class="cv39-decision-card {decision['tone']}">
          <div class="cv39-decision-top">
            <div><div class="cv35-answer-label">{html.escape(profile["label"])}</div><h2>{html.escape(decision['status'])}</h2></div>
            <span class="cv39-status-badge">{html.escape(decision['risk'])} risk</span>
          </div>
          <div class="cv39-decision-grid">{kpi_html}</div>
          <p>{html.escape(decision['assessment'])}</p>
        </div>
        <div class="cv39-progress-wrap"><div><strong>{html.escape(progress_label)}</strong><span>{progress}%</span></div><div class="cv39-progress"><i style="width:{progress}%"></i></div></div>
        """,
        unsafe_allow_html=True,
    )

    driver_html = "".join(f'<li><span>{index}</span><p>{html.escape(driver)}</p></li>' for index, driver in enumerate(recommendation_drivers, start=1))
    if driver_html:
        st.markdown(
            f'<section class="cv46-why"><div><span>Why Cadivor recommends this</span><h3>{html.escape(decision["status"])}</h3><p>{html.escape(explanation)}</p></div><ol>{driver_html}</ol></section>',
            unsafe_allow_html=True,
        )

    impact_col, confidence_col = st.columns([1.18, 1])
    with impact_col:
        st.markdown('<div class="cv35-section-label">Projected engineering impact</div>', unsafe_allow_html=True)
        impact_html = "".join(
            f'<div class="cv39-impact-row"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong><small>{html.escape(note)}</small></div>'
            for label, value, note in impact
        )
        st.markdown(f'<div class="cv39-impact-card">{impact_html}<p>Projections are directional estimates based on saved evidence, not measured outcomes.</p></div>', unsafe_allow_html=True)
    with confidence_col:
        st.markdown('<div class="cv35-section-label">Decision confidence</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="cv35-confidence-card {confidence_class}">
              <div class="cv35-confidence-top"><span>Evidence confidence</span><strong>{confidence_score}%</strong></div>
              <div class="cv35-confidence-track"><div style="width:{confidence_score}%"></div></div>
              <div class="cv35-confidence-label">{html.escape(confidence_label)}</div>
              <div class="cv35-confidence-detail">{html.escape(confidence_detail)}</div>
              <div class="cv46-confidence-drivers">{''.join(f'<div><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong><small>{html.escape(note)}</small></div>' for label, value, note in confidence_drivers[:6])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if rankings:
        st.markdown('<div class="cv35-section-label">Engineering priority ranking</div>', unsafe_allow_html=True)
        ranking_items=_evidence_items(rankings)
        ranking_html="".join(f'<div class="cv47-ranking-row"><b>{idx}</b><div><strong>{html.escape(title)}</strong><span>{html.escape(detail)}</span></div></div>' for idx,(title,detail) in enumerate(ranking_items,1))
        st.markdown(f'<div class="cv47-ranking-board">{ranking_html}</div>', unsafe_allow_html=True)

    st.markdown('<div class="cv35-section-label">Evidence breakdown</div>', unsafe_allow_html=True)
    _render_evidence_cards(evidence)

    st.markdown('<div class="cv35-section-label">Priority timeline</div>', unsafe_allow_html=True)
    if workflow_text:
        workflow = []
        for line in workflow_text.splitlines():
            clean = line.strip()
            if not clean.startswith(("-", "*")):
                continue
            clean = clean[1:].strip()
            if " | " in clean:
                label, detail = clean.split(" | ", 1)
            else:
                label, detail = clean, "Complete this step using the current BOM evidence and recorded engineering controls."
            workflow.append((_plain_markdown(label), _plain_markdown(detail)))
        workflow = workflow[:5]
    else:
        workflow = _workflow_steps(actions, priority_part, intent=intent)
    workflow_cols = st.columns(len(workflow))
    for idx, ((label, detail), col) in enumerate(zip(workflow, workflow_cols), start=1):
        col.markdown(
            f'<div class="cv39-timeline-step"><b>{idx}</b><strong>{html.escape(label)}</strong><p>{html.escape(detail)}</p></div>',
            unsafe_allow_html=True,
        )
    _render_quick_actions(context, priority_part, intent=intent)

def render_engineering_assistant(
    *,
    current_user: dict[str, Any],
    engineering_context: Any,
    selected_component: str = "",
) -> None:
    snapshot = st.session_state.get("cv48_auth_snapshot")
    if isinstance(snapshot, dict):
        for key, value in snapshot.items():
            if value is not None and st.session_state.get(key) is None:
                st.session_state[key] = value
    context = engineering_context.compact(max_components=15) if hasattr(engineering_context, "compact") else dict(engineering_context or {})
    status = get_ai_usage_status(st.session_state, current_user)

    st.markdown(
        """
        <style id="cadivor-engineering-assistant-43">
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

        .cv39-decision-card{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f5f9ff);border-radius:22px;padding:20px 21px;margin:16px 0 10px;box-shadow:0 16px 42px rgba(15,23,42,.06)}.cv39-decision-card.ready{border-color:#86efac;background:linear-gradient(135deg,#fff,#ecfdf5)}.cv39-decision-card.critical{border-color:#fca5a5;background:linear-gradient(135deg,#fff,#fff1f2)}.cv39-decision-top{display:flex;align-items:flex-start;justify-content:space-between;gap:15px}.cv39-decision-top h2{font-size:26px;color:#0f172a!important;letter-spacing:-.035em;margin:6px 0 12px}.cv39-status-badge{border:1px solid #fbbf24;background:#fef3c7;color:#78350f;border-radius:999px;padding:7px 11px;font-size:10px;font-weight:950;box-shadow:0 2px 8px rgba(146,64,14,.08)}.cv39-decision-card.ready .cv39-status-badge{border-color:#34d399;background:#d1fae5;color:#065f46}.cv39-decision-card.critical .cv39-status-badge{border-color:#f87171;background:#fee2e2;color:#991b1b}.cv39-decision-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:4px 0 14px}.cv39-decision-grid div{border:1px solid #dbeafe;background:rgba(255,255,255,.9);border-radius:13px;padding:11px 12px}.cv39-decision-grid span{display:block;font-size:9px;text-transform:uppercase;letter-spacing:.07em;color:#64748b;font-weight:900}.cv39-decision-grid strong{display:block;color:#0f172a;font-size:14px;margin-top:5px}.cv39-decision-card>p{margin:0;color:#334155;font-size:13px;line-height:1.6;font-weight:650}.cv39-progress-wrap{border:1px solid #dbeafe;background:#fff;border-radius:14px;padding:10px 14px;margin-bottom:8px}.cv39-progress-wrap>div:first-child{display:flex;justify-content:space-between;font-size:11px;color:#334155}.cv39-progress{height:8px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin-top:7px}.cv39-progress i{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:999px}.cv39-impact-card{border:1px solid #dbeafe;background:#fff;border-radius:18px;padding:13px 16px;margin-bottom:8px}.cv39-impact-row{display:grid;grid-template-columns:1fr auto;gap:4px 12px;border-bottom:1px solid #eef2f7;padding:9px 0}.cv39-impact-row:last-of-type{border-bottom:0}.cv39-impact-row span{font-size:11px;color:#64748b;font-weight:850}.cv39-impact-row strong{font-size:12px;color:#0f172a}.cv39-impact-row small{grid-column:1/-1;color:#64748b;font-size:9px}.cv39-impact-card>p{font-size:9px;color:#64748b;margin:9px 0 0}.cv39-timeline-step{min-height:118px;border:1px solid #dbeafe;background:#fff;border-radius:15px;padding:11px 11px;position:relative;box-shadow:0 5px 16px rgba(15,23,42,.025)}.cv39-timeline-step b{display:grid;place-items:center;width:22px;height:22px;border-radius:999px;background:#2563eb;color:#fff;font-size:9px;margin-bottom:8px}.cv39-timeline-step strong{display:block;color:#0f172a;font-size:11px}.cv39-timeline-step p{font-size:10px;line-height:1.38;color:#64748b;margin:6px 0 0}
        .cv35-evidence-head span{border:1px solid #93c5fd!important;background:#dbeafe!important;color:#1d4ed8!important;padding:5px 9px!important}.cv35-evidence-card{min-height:138px!important;margin-bottom:8px!important}.cv35-section-label{margin:14px 0 8px!important}
        div[data-testid="stForm"] button[kind="primary"],div[data-testid="stForm"] button[data-testid="stFormSubmitButton"]{background:#2563eb!important;border:1px solid #2563eb!important;color:#fff!important;font-weight:800!important;box-shadow:0 8px 20px rgba(37,99,235,.22)!important;opacity:1!important}div[data-testid="stForm"] button[kind="primary"] p,div[data-testid="stForm"] button[kind="primary"] span,div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] p,div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] span{color:#fff!important;opacity:1!important}div[data-testid="stForm"] button[kind="primary"]:hover,div[data-testid="stForm"] button[data-testid="stFormSubmitButton"]:hover{background:#1d4ed8!important;border-color:#1d4ed8!important;color:#fff!important}div[data-testid="stForm"] button[kind="primary"]:focus,div[data-testid="stForm"] button[kind="primary"]:active,div[data-testid="stForm"] button[data-testid="stFormSubmitButton"]:focus,div[data-testid="stForm"] button[data-testid="stFormSubmitButton"]:active{background:#1e40af!important;border-color:#1e40af!important;color:#fff!important;box-shadow:0 0 0 3px rgba(96,165,250,.35)!important}div[data-testid="stForm"] button:disabled{background:#93c5fd!important;border-color:#93c5fd!important;color:#fff!important;opacity:.9!important}div[data-testid="stForm"] button:disabled p,div[data-testid="stForm"] button:disabled span{color:#fff!important;opacity:1!important}
        /* Sprint 43 final polish */
        .cv39-progress-wrap{margin-bottom:4px!important}.cv35-section-label{margin:11px 0 7px!important}
        .cv39-impact-card,.cv35-confidence-card{min-height:160px;height:100%;margin-top:0!important}
        .cv35-evidence-card{min-height:126px!important;padding:13px 14px!important;transition:border-color .16s ease,transform .16s ease,box-shadow .16s ease}.cv35-evidence-card:hover{box-shadow:0 12px 28px rgba(37,99,235,.08)}
        .cv38-evidence-metric span{display:flex!important;align-items:center;gap:5px}.cv38-evidence-metric span i{display:inline-grid;place-items:center;width:16px;height:16px;border-radius:5px;background:#eff6ff;color:#2563eb;font-size:9px;font-style:normal;font-weight:950;flex:0 0 auto}.cv38-evidence-metric strong{font-size:11px!important}
        .cv39-timeline-step{min-height:102px!important;padding:10px!important}.cv39-timeline-step b{width:20px!important;height:20px!important;margin-bottom:6px!important}.cv39-timeline-step p{font-size:9.5px!important;line-height:1.34!important;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
        div[data-testid="stFormSubmitButton"] button,div[data-testid="stForm"] div[data-testid="stFormSubmitButton"] button,.stFormSubmitButton button{background:#2563eb!important;border-color:#2563eb!important;color:#fff!important;-webkit-text-fill-color:#fff!important;font-weight:850!important}
        div[data-testid="stFormSubmitButton"] button *,div[data-testid="stForm"] div[data-testid="stFormSubmitButton"] button *,.stFormSubmitButton button *{color:#fff!important;-webkit-text-fill-color:#fff!important;fill:#fff!important;stroke:#fff!important;opacity:1!important}
        div[data-testid="stFormSubmitButton"] button:hover,div[data-testid="stFormSubmitButton"] button:focus,div[data-testid="stFormSubmitButton"] button:active{background:#1d4ed8!important;border-color:#1d4ed8!important;color:#fff!important;-webkit-text-fill-color:#fff!important}
        div[data-testid="stFormSubmitButton"] button:disabled,div[data-testid="stFormSubmitButton"] button[disabled]{background:#60a5fa!important;border-color:#60a5fa!important;color:#fff!important;-webkit-text-fill-color:#fff!important;opacity:1!important}
        div[data-testid="stFormSubmitButton"] button:disabled *,div[data-testid="stFormSubmitButton"] button[disabled] *{color:#fff!important;-webkit-text-fill-color:#fff!important;opacity:1!important}
        div[data-testid="stForm"]{border-color:#dbeafe!important;background:#fbfdff!important}
        /* Sprint 45 readability: responsive type scale for laptop and small-screen use. */
        .cv35-kicker,.cv35-answer-label,.cv35-section-label,.cv35-card-kicker{font-size:clamp(10px,.72vw,12px)!important}
        .cv39-decision-top h2{font-size:clamp(27px,2vw,34px)!important}.cv39-decision-card>p{font-size:clamp(14px,.95vw,16px)!important;line-height:1.65!important}
        .cv39-decision-grid span,.cv38-evidence-metric span{font-size:clamp(10px,.68vw,11px)!important}.cv39-decision-grid strong{font-size:clamp(14px,.95vw,16px)!important}
        .cv38-evidence-metric strong{font-size:clamp(12px,.82vw,14px)!important;line-height:1.45!important}.cv35-evidence-part{font-size:clamp(14px,.95vw,16px)!important}
        .cv39-impact-row span{font-size:clamp(11px,.75vw,13px)!important}.cv39-impact-row strong{font-size:clamp(12px,.82vw,14px)!important}.cv39-impact-row small{font-size:clamp(10px,.68vw,11px)!important}
        .cv39-timeline-step strong{font-size:clamp(11px,.75vw,13px)!important}.cv39-timeline-step p{font-size:clamp(10px,.68vw,12px)!important;line-height:1.45!important}
        .cv35-confidence-top{font-size:clamp(11px,.75vw,13px)!important}.cv35-confidence-label{font-size:clamp(15px,1vw,17px)!important}.cv35-confidence-detail{font-size:clamp(11px,.75vw,13px)!important}
        div[data-testid="stForm"] label,div[data-testid="stTextArea"] label{font-size:14px!important} div[data-testid="stTextArea"] textarea{font-size:15px!important;line-height:1.5!important}
        @media(max-width:1100px){.cv35-evidence-card{padding:14px!important}.cv39-decision-card{padding:18px!important}.cv39-timeline-step{min-height:auto!important}}
        @media(max-width:900px){.cv38-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cv38-evidence-grid{grid-template-columns:1fr}.cv39-decision-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cv39-decision-top{display:block}.cv39-status-badge{display:inline-block;margin-bottom:8px}.cv39-timeline-step{min-height:auto}.cv35-review-heading{display:block}.cv35-review-status{display:inline-block;margin-top:6px}.cv35-evidence-card{min-height:auto!important}}

        /* Sprint 49 — conversational answer-first experience */
        .cv50-exchange{scroll-margin-top:76px;margin:12px 0 10px;border:1px solid #bfdbfe;border-radius:17px;background:linear-gradient(135deg,#eff6ff 0%,#f8fbff 100%);padding:14px 17px;box-shadow:0 8px 24px rgba(37,99,235,.055)}
        .cv50-exchange-top{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}.cv50-you-asked{min-width:0}.cv50-you-asked span{display:block;font-size:9px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#2563eb;margin-bottom:4px}.cv50-you-asked strong{display:block;font-size:clamp(14px,1vw,17px);line-height:1.42;color:#0f172a;overflow-wrap:anywhere}.cv50-exchange-badges{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}.cv50-type,.cv50-saved{display:inline-flex;align-items:center;min-height:26px;border-radius:999px;padding:5px 10px;font-size:10px;font-weight:850;white-space:nowrap}.cv50-type{border:1px solid #bfdbfe;background:#fff;color:#1d4ed8}.cv50-saved{border:1px solid #d1fae5;background:#ecfdf5;color:#047857}.cv50-type-release{border-color:#ddd6fe;color:#6d28d9;background:#f5f3ff}.cv50-type-evidence{border-color:#bae6fd;color:#0369a1;background:#f0f9ff}.cv50-type-supplier{border-color:#fed7aa;color:#c2410c;background:#fff7ed}.cv50-type-procurement{border-color:#fde68a;color:#a16207;background:#fffbeb}.cv50-type-schedule{border-color:#c7d2fe;color:#4338ca;background:#eef2ff}.cv50-type-lifecycle{border-color:#fecdd3;color:#be123c;background:#fff1f2}.cv50-type-inventory{border-color:#bbf7d0;color:#15803d;background:#f0fdf4}.cv50-type-explanation{border-color:#e2e8f0;color:#475569;background:#f8fafc}
        .cv50-supporting-divider{display:flex;align-items:center;gap:12px;margin:18px 2px 12px}.cv50-supporting-divider span{font-size:10px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#64748b;white-space:nowrap}.cv50-supporting-divider i{display:block;height:1px;background:#dbeafe;flex:1}
        @media(max-width:760px){.cv50-exchange-top{flex-direction:column}.cv50-exchange-badges{justify-content:flex-start}.cv50-saved{display:none}}
        .cv49-answer-card{margin:12px 0 16px;border:1px solid #93c5fd;border-radius:22px;background:linear-gradient(135deg,#eff6ff 0%,#ffffff 58%,#f8fafc 100%);padding:22px 24px;box-shadow:0 12px 34px rgba(37,99,235,.08)}
        .cv49-answer-kicker{font-size:clamp(10px,.72vw,12px);font-weight:950;letter-spacing:.11em;text-transform:uppercase;color:#2563eb;margin-bottom:10px}
        .cv49-answer-grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(260px,.45fr);gap:26px;align-items:start}
        .cv49-answer-main h2{margin:0 0 8px;font-size:clamp(25px,1.8vw,34px);line-height:1.12;letter-spacing:-.035em;color:#0f172a}
        .cv49-answer-main>p{margin:0 0 13px;font-size:clamp(14px,.96vw,16px);line-height:1.62;color:#334155;font-weight:610}
        .cv49-answer-main ul{list-style:none;margin:0;padding:0;display:grid;gap:7px}.cv49-answer-main li{display:flex;gap:9px;align-items:flex-start}.cv49-answer-main li span{display:grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#dbeafe;color:#1d4ed8;font-size:11px;font-weight:950;flex:0 0 auto}.cv49-answer-main li p{margin:0;font-size:clamp(12px,.82vw,14px);line-height:1.48;color:#475569;font-weight:650}
        .cv49-answer-side{border-left:1px solid #bfdbfe;padding-left:22px;display:grid;gap:6px}.cv49-answer-side span{font-size:10px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;color:#64748b}.cv49-answer-side strong{font-size:clamp(28px,2vw,38px);line-height:1;color:#0f172a}.cv49-answer-side>p{margin:1px 0 0;font-size:clamp(12px,.82vw,14px);line-height:1.48;color:#334155;font-weight:700}.cv49-answer-track{height:7px;border-radius:999px;background:#dbeafe;overflow:hidden;margin:2px 0 12px}.cv49-answer-track i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#2563eb,#60a5fa)}
        @media(max-width:900px){.cv49-answer-grid{grid-template-columns:1fr}.cv49-answer-side{border-left:0;border-top:1px solid #bfdbfe;padding-left:0;padding-top:15px}}

        /* Sprint 46 — explainability, compact evidence, responsive readability */
        .cv46-why{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(280px,.9fr);gap:18px;border:1px solid #c7d2fe;background:linear-gradient(135deg,#f8faff,#eef4ff);border-radius:20px;padding:18px 20px;margin:10px 0 14px}.cv46-why>div>span{font-size:clamp(10px,.7vw,12px);font-weight:950;letter-spacing:.09em;text-transform:uppercase;color:#2563eb}.cv46-why h3{font-size:clamp(18px,1.35vw,24px);line-height:1.2;letter-spacing:-.025em;color:#0f172a;margin:5px 0 7px}.cv46-why>div>p{font-size:clamp(13px,.88vw,15px);line-height:1.62;color:#475569;margin:0}.cv46-why ol{list-style:none;padding:0;margin:0;display:grid;gap:7px}.cv46-why li{display:flex;gap:9px;align-items:flex-start;border:1px solid #dbeafe;background:rgba(255,255,255,.86);border-radius:11px;padding:8px 10px}.cv46-why li span{display:grid;place-items:center;width:20px;height:20px;border-radius:6px;background:#2563eb;color:#fff;font-size:10px;font-weight:950;flex:0 0 auto}.cv46-why li p{margin:1px 0 0;font-size:clamp(11px,.76vw,13px);line-height:1.42;color:#334155;font-weight:720}
        .cv46-confidence-drivers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:12px}.cv46-confidence-drivers>div{border-top:1px solid #e2e8f0;padding-top:7px;min-width:0}.cv46-confidence-drivers span{display:block;font-size:clamp(9px,.62vw,10px);font-weight:900;text-transform:uppercase;letter-spacing:.05em;color:#64748b}.cv46-confidence-drivers strong{display:block;font-size:clamp(12px,.84vw,14px);color:#0f172a;margin:2px 0}.cv46-confidence-drivers small{display:block;font-size:clamp(9px,.62vw,11px);line-height:1.35;color:#64748b}
        .cv46-evidence-board{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin-bottom:8px}.cv46-evidence-card{border:1px solid #dbeafe;background:#fff;border-radius:15px;padding:12px;min-width:0;box-shadow:0 6px 18px rgba(15,23,42,.035);transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease}.cv46-evidence-card:hover{transform:translateY(-1px);border-color:#93c5fd;box-shadow:0 10px 24px rgba(37,99,235,.075)}.cv46-evidence-card header{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;padding-bottom:8px;border-bottom:1px solid #eef2f7}.cv46-evidence-card header strong{font-size:clamp(12px,.85vw,15px);line-height:1.28;color:#0f172a;overflow-wrap:anywhere}.cv46-evidence-card header em{font-style:normal;font-size:9px;font-weight:900;color:#1d4ed8;background:#eff6ff;border-radius:999px;padding:4px 7px;white-space:nowrap}.cv46-evidence-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:8px}.cv46-evidence-metric{min-width:0}.cv46-evidence-metric span{display:flex;align-items:center;gap:4px;font-size:clamp(9px,.62vw,10px);font-weight:850;color:#64748b;text-transform:uppercase;letter-spacing:.04em}.cv46-evidence-metric i{display:grid;place-items:center;width:15px;height:15px;border-radius:4px;background:#eff6ff;color:#2563eb;font-style:normal;font-size:8px;flex:0 0 auto}.cv46-evidence-metric strong{display:block;font-size:clamp(11px,.76vw,13px);line-height:1.35;color:#334155;margin-top:3px;overflow-wrap:anywhere}.cv46-empty-evidence{border:1px dashed #cbd5e1;background:#f8fafc;border-radius:14px;padding:14px;color:#475569;font-size:13px;line-height:1.55}
        .cv35-confidence-card{min-height:0!important}.cv39-impact-card{min-height:0!important}.cv39-decision-card>p{max-width:1100px}.cv39-timeline-step p{-webkit-line-clamp:unset!important;overflow:visible!important}
        .cv47-ranking-board{display:grid;gap:8px;margin-bottom:10px}.cv47-ranking-row{display:flex;gap:10px;align-items:flex-start;border:1px solid #dbeafe;background:#fff;border-radius:13px;padding:10px 12px}.cv47-ranking-row>b{display:grid;place-items:center;width:23px;height:23px;border-radius:7px;background:#2563eb;color:#fff;font-size:10px;flex:0 0 auto}.cv47-ranking-row strong{display:block;font-size:13px;color:#0f172a}.cv47-ranking-row span{display:block;font-size:11px;color:#64748b;margin-top:2px}.cv47-question-banner{border:1px solid #bfdbfe;background:#eff6ff;border-radius:14px;padding:11px 14px;margin:12px 0 10px}.cv47-question-banner span{display:block;font-size:9px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;color:#2563eb}.cv47-question-banner strong{display:block;margin-top:3px;font-size:clamp(13px,.9vw,16px);line-height:1.4;color:#0f172a}.cv46-confidence-drivers>div strong:first-of-type{font-weight:900}.cv46-confidence-drivers>div:has(strong:first-of-type){border-radius:8px}
        @media(max-width:1180px){.cv46-evidence-board{grid-template-columns:repeat(2,minmax(0,1fr))}.cv46-why{grid-template-columns:1fr}.cv46-why ol{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:760px){.cv46-evidence-board,.cv46-why ol,.cv46-confidence-drivers{grid-template-columns:1fr}.cv46-evidence-metrics{grid-template-columns:1fr 1fr}.cv46-why{padding:15px}.cv39-decision-grid{grid-template-columns:1fr!important}.cv39-decision-card{border-radius:18px;padding:16px!important}.cv35-hero{padding:17px;border-radius:19px}.cv35-hero h2{font-size:clamp(23px,7vw,30px)!important}.cv39-decision-top h2{font-size:clamp(23px,7vw,30px)!important}}
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

    cleaned_question = _normalize_submitted_question(question)
    manual_submit_requested = bool(manual_submit and status.can_use and cleaned_question)
    if manual_submit and not cleaned_question:
        st.warning("Enter an engineering question before submitting.")
    if manual_submit_requested:
        _clear_review_state()
        st.session_state["cv47_scroll_pending"] = True

    can_submit = status.can_use and bool(cleaned_question)
    submit_requested = bool(manual_submit_requested or (auto_execute_followup and can_submit))
    submitted_question = cleaned_question
    if submit_requested:
        api = EngineeringAI(
            api_key=_secret("OPENAI_API_KEY"),
            model=_secret("OPENAI_MODEL", "gpt-4.1-mini"),
            base_url=_secret("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        st.session_state.pop("cv35_last_error", None)
        st.markdown('<div id="cv47-processing-anchor"></div>', unsafe_allow_html=True)
        if st.session_state.pop("cv47_scroll_pending", False):
            components.html("""<script>(function(){const d=window.parent.document,w=window.parent;function go(){const e=d.getElementById('cv47-processing-anchor');if(e){w.scrollTo({top:Math.max(0,e.getBoundingClientRect().top+w.pageYOffset-92),behavior:'auto'});}}go();setTimeout(go,80);setTimeout(go,240);</script>""", height=0)
        with st.status("Cadivor is reviewing the saved engineering evidence...", expanded=True) as progress:
            try:
                response = api.ask(question=submitted_question, context=context, history=compact_history(thread))
                consume_ai_credits(st.session_state, current_user, action="question")
                st.session_state["cv35_last_answer"] = response.answer
                st.session_state["cv35_last_question"] = submitted_question
                st.session_state["cv35_provider_connected"] = api.configured
                st.session_state["cv47_scroll_to_assessment"] = True
                if st.session_state.pop("cv47_followup_question", None):
                    st.session_state["cv47_followup_answered"] = submitted_question
                thread = append_turn(
                    st.session_state,
                    context,
                    question=submitted_question,
                    answer=response.answer,
                    provider_connected=api.configured,
                )
                # Follow-up completed inside the authenticated workspace. The
                # recovery snapshot is no longer needed after the answer and
                # active route are safely stored.
                st.session_state.pop("cv4801_followup_inflight", None)
                st.session_state.pop("cv4801_auth_retry_count", None)
                st.session_state.pop("cv48_auth_snapshot", None)
                st.session_state.pop("cv4801_route_snapshot", None)
                st.session_state.pop("cv36_pending_followup", None)
                st.session_state.pop("cv47_followup_question", None)
                st.session_state.pop("cv41_pending_manual", None)
                st.session_state[prompt_key] = ""
                progress.update(label="Engineering review complete", state="complete")
            except EngineeringAIError as exc:
                st.session_state["cv35_last_error"] = exc
                progress.update(label="Cadivor could not complete the review", state="error")
            except Exception as exc:
                # A response may already have been generated and saved before a
                # secondary operation (history persistence, cleanup, etc.) fails.
                # Do not show a false red failure banner when the visible answer
                # belongs to the submitted question. Preserve the successful
                # answer, log a quiet diagnostic, and complete the review.
                saved_question = _normalize_submitted_question(st.session_state.get("cv35_last_question"))
                saved_answer = str(st.session_state.get("cv35_last_answer") or "").strip()
                if saved_answer and saved_question == submitted_question:
                    st.session_state.pop("cv35_last_error", None)
                    st.session_state["cv49_nonfatal_warning"] = repr(exc)
                    st.session_state["cv47_scroll_to_assessment"] = True
                    progress.update(label="Engineering review complete", state="complete")
                else:
                    st.session_state["cv35_last_error"] = EngineeringAIError(
                        "Cadivor could not complete this assessment from the saved evidence. "
                        "The previous assessment remains available; refresh the BOM evidence and try again."
                    )
                    progress.update(label="Cadivor safely stopped the review", state="error")
                st.session_state.pop("cv4801_followup_inflight", None)
                st.session_state.pop("cv36_pending_followup", None)
                st.session_state.pop("cv47_followup_question", None)

    answered_followup = st.session_state.pop("cv47_followup_answered", None)
    if answered_followup:
        st.success(f'Follow-up answered: "{answered_followup}". The latest assessment below has been regenerated for this question.')
        st.session_state['cv47_scroll_to_assessment'] = True

    thread = get_thread(st.session_state, context)
    current_answer = st.session_state.get("cv35_last_answer")
    _render_conversation_history(thread, exclude_latest=bool(current_answer))

    error_message = st.session_state.get("cv35_last_error")
    if isinstance(error_message, EngineeringAIError):
        _render_error(error_message)

    answer = st.session_state.get("cv35_last_answer")
    if answer:
        last_question = _normalize_submitted_question(st.session_state.get("cv35_last_question") or "Engineering review")
        question_changed = st.session_state.get("cv50_last_scrolled_question") != last_question
        should_scroll = st.session_state.pop("cv47_scroll_to_assessment", False) or question_changed
        _render_response(question=last_question, answer=answer, context=context, auto_scroll=should_scroll)
        if should_scroll:
            st.session_state["cv50_last_scrolled_question"] = last_question
            # Sprint 50.1 scrolls from the exact response-start iframe mounted
            # inside _render_response; no document-wide id lookup is required.
        _render_follow_ups(question=last_question, answer=answer, context=context)
        if not st.session_state.get("cv35_provider_connected", False):
            st.markdown(
                '<div class="cv35-mode-note">This assessment is grounded in the engineering evidence saved with the BOM. Validate final release, sourcing, and compatibility decisions against current approved datasheets and organizational requirements.</div>',
                unsafe_allow_html=True,
            )
