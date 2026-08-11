"""Premium user-facing Engineering Copilot panel."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable

import streamlit as st
import streamlit.components.v1 as components

from src.urls import internal_app_href
from src.ui.navigation import alternative_finder_href, internal_nav_button, ALTERNATIVE_FINDER_PAGE
from src.ui.cadivor_design_system import (
    MetricCard,
    cadivor_badge,
    cadivor_meta_row,
    render_kpi_row_safe,
    render_subsection_header,
)

from src.services.ai_entitlements import consume_ai_credits, get_ai_usage_status
from src.services.copilot_response_depth import wants_detailed_response as _wants_detailed_response
from src.services.engineering_ai import EngineeringAI, EngineeringAIError, log_ai_config
from src.services.copilot_conversation import (
    append_turn,
    clear_thread,
    compact_history,
    follow_up_suggestions,
    get_thread,
)


def _normalize_presentation_html(markup: str) -> str:
    """Normalize trusted Cadivor HTML so Streamlit Markdown cannot treat it as a code block."""
    normalized = dedent(str(markup or "")).strip()
    if not normalized:
        return ""
    normalized = re.sub(r"\n[ \t]+", " ", normalized)
    normalized = re.sub(r">\s+<", "><", normalized)
    return normalized


def _render_presentation_html(markup: str) -> None:
    """Render static trusted Cadivor HTML in the main Streamlit DOM."""
    normalized = _normalize_presentation_html(markup)
    if not normalized:
        return
    st.markdown(normalized, unsafe_allow_html=True)


SUGGESTIONS = [
    "What should I review first in this BOM?",
    "Explain the highest component risks.",
    "Is this BOM ready for production release?",
    "Which components need alternative qualification?",
    "Summarize the supplier and lifecycle exposure.",
]

ASK_CADIVOR_TAB = "Ask Cadivor"

PENDING_ANALYSIS_SECTION_KEY = "cadivor_pending_analysis_section"
PENDING_ANALYSIS_SECTION_ID_KEY = "cadivor_pending_analysis_section_id"


_COPILOT_WORKFLOW_KEYS = (
    "cv41_pending_manual",
    "cv36_pending_followup",
    "cv47_followup_question",
    "cv47_scroll_pending",
    "cv7142_ask_inflight",
    "cadivor_route",
    "app_mode",
    "analysis_id",
    "active_analysis_id",
    "cadivor_active_analysis_id",
    "cadivor_active_analysis_tab",
)

_COPILOT_PROCESSING_LABEL = "Cadivor is analyzing this BOM…"
_CLEAR_PROMPT_ON_NEXT_RUN_KEY = "cv7144_clear_prompt_on_next_run"
_DECISION_COLUMN_RATIO = [0.85, 1.15]
_CONCISE_REASON_LIMIT = 3
_CONCISE_ACTION_LIMIT = 3


def _schedule_prompt_clear_on_next_run() -> None:
    """Defer clearing a widget-bound prompt until before the next text_area mount."""
    st.session_state[_CLEAR_PROMPT_ON_NEXT_RUN_KEY] = True


def _apply_deferred_prompt_clear(prompt_key: str) -> None:
    """Clear the prompt widget value before it is instantiated on a later rerun."""
    if st.session_state.pop(_CLEAR_PROMPT_ON_NEXT_RUN_KEY, False):
        st.session_state[prompt_key] = ""


def _log_ask_cadivor(event: str, **details: Any) -> None:
    """Safe stdout diagnostics for Ask Cadivor execution (metadata only)."""
    parts = [f"ASK_CADIVOR {event}"]
    for key, value in details.items():
        parts.append(f"{key}={value}")
    print(" ".join(parts), flush=True)


def _log_ask_cadivor_state(event: str, *, reason: str = "") -> None:
    """Log presence/length metadata for copilot workflow keys (never prompt/answer text)."""
    pending_manual = st.session_state.get("cv41_pending_manual")
    pending_followup = st.session_state.get("cv36_pending_followup")
    last_answer = st.session_state.get("cv35_last_answer")
    details: dict[str, Any] = {
        "pending_manual_present": bool(pending_manual),
        "pending_manual_len": len(str(pending_manual or "")),
        "pending_followup_present": bool(pending_followup),
        "inflight": bool(st.session_state.get("cv7142_ask_inflight")),
        "snapshot_present": bool(st.session_state.get("cv48_copilot_snapshot")),
        "followup_inflight_flag": bool(st.session_state.get("cv4801_followup_inflight")),
        "last_answer_present": bool(str(last_answer or "").strip()),
        "last_answer_len": len(str(last_answer or "")),
        "active_tab": str(st.session_state.get("cadivor_active_analysis_tab") or ""),
        "analysis_id": str(
            st.session_state.get("cadivor_active_analysis_id")
            or st.session_state.get("analysis_id")
            or ""
        ),
    }
    if reason:
        details["reason"] = reason
    _log_ask_cadivor(event, **details)


def _log_ask_cadivor_state_clear(key: str, *, reason: str) -> None:
    """Log when a copilot workflow key is cleared (metadata only)."""
    _log_ask_cadivor("state_cleared", key=key, reason=reason)


def _log_ask_render(event: str, **details: Any) -> None:
    """Safe stdout diagnostics for Ask Cadivor presentation render boundaries."""
    parts = [f"ASK_RENDER {event}"]
    for key, value in details.items():
        parts.append(f"{key}={value}")
    print(" ".join(parts), flush=True)


def _pin_ask_cadivor_tab(*, source: str = "unknown", analysis_id: str = "") -> None:
    """Keep authoritative section/query on Ask Cadivor without mutating bound nav widgets."""
    st.session_state["cadivor_active_analysis_tab"] = ASK_CADIVOR_TAB
    try:
        st.query_params["analysis_tab"] = ASK_CADIVOR_TAB
    except Exception:
        pass
    target_analysis_id = analysis_id or str(
        st.session_state.get("cadivor_active_analysis_id")
        or st.session_state.get("analysis_id")
        or ""
    )
    st.session_state[PENDING_ANALYSIS_SECTION_KEY] = ASK_CADIVOR_TAB
    if target_analysis_id:
        st.session_state[PENDING_ANALYSIS_SECTION_ID_KEY] = target_analysis_id
    _log_ask_cadivor(
        "tab_pinned",
        source=source,
        analysis_id=target_analysis_id or analysis_id or "active",
    )


def _log_copilot_workflow(event: str, **details: Any) -> None:
    from src.auth_state import log_auth_diagnostic

    log_auth_diagnostic(event, **details)


def _capture_copilot_workflow_snapshot() -> dict[str, Any]:
    """Capture pending copilot workflow keys for reruns within one Streamlit session."""
    snapshot: dict[str, Any] = {}
    try:
        for key in _COPILOT_WORKFLOW_KEYS:
            value = st.session_state.get(key)
            if value is not None:
                snapshot[key] = value
    except Exception:
        return {}
    return snapshot


def _restore_copilot_workflow_snapshot(snapshot: Any) -> None:
    if not isinstance(snapshot, dict):
        return
    restored_keys: list[str] = []
    try:
        for key, value in snapshot.items():
            if not key or value is None:
                continue
            if st.session_state.get(key) is None:
                st.session_state[key] = value
                restored_keys.append(str(key))
    except Exception:
        return
    if restored_keys:
        _log_ask_cadivor(
            "workflow_snapshot_restored",
            keys=",".join(restored_keys),
            key_count=len(restored_keys),
        )


def _recover_stale_copilot_inflight() -> None:
    """Drop orphaned inflight flags that would block one-click suggestions forever."""
    if not st.session_state.get("cv7142_ask_inflight"):
        return
    if st.session_state.get("cv41_pending_manual") or st.session_state.get("cv36_pending_followup"):
        return
    snapshot = st.session_state.get("cv48_copilot_snapshot") or {}
    if isinstance(snapshot, dict) and (
        snapshot.get("cv41_pending_manual") or snapshot.get("cv36_pending_followup")
    ):
        return
    _log_ask_cadivor_state("inflight_stale_detected", reason="no_pending_question")
    st.session_state.pop("cv7142_ask_inflight", None)
    st.session_state.pop("cv4801_followup_inflight", None)


def _clear_copilot_workflow_snapshot() -> None:
    try:
        st.session_state.pop("cv48_copilot_snapshot", None)
    except Exception:
        pass


def _clear_copilot_workflow_protection() -> None:
    """Drop copilot workflow recovery state after a submission completes."""
    for key in ("cv4801_followup_inflight", "cv4801_route_snapshot", "cv7142_ask_inflight"):
        if key in st.session_state:
            _log_ask_cadivor_state_clear(key, reason="copilot_workflow_complete")
            st.session_state.pop(key, None)
    _clear_copilot_workflow_snapshot()


def _copilot_submission_inflight() -> bool:
    return bool(
        st.session_state.get("cv7142_ask_inflight")
        or st.session_state.get("cv41_pending_manual")
        or st.session_state.get("cv36_pending_followup")
    )


def _block_duplicate_submission(*, kind: str, analysis_id: str = "") -> bool:
    """Return True when a copilot request is already queued or executing."""
    if not _copilot_submission_inflight():
        return False
    _log_ask_cadivor(
        "duplicate_submission_blocked",
        kind=kind,
        analysis_id=analysis_id or "active",
    )
    return True


def _arm_copilot_workflow_snapshot(*, reason: str) -> None:
    """Persist pending copilot workflow before a rerun in the same Streamlit session."""
    try:
        route_snapshot = {key: value for key, value in st.query_params.items()}
    except Exception:
        route_snapshot = {}
    snapshot = _capture_copilot_workflow_snapshot()
    st.session_state["cv48_copilot_snapshot"] = snapshot
    st.session_state["cv4801_route_snapshot"] = route_snapshot
    st.session_state["cv4801_followup_inflight"] = True
    _log_copilot_workflow(
        "copilot_workflow_snapshot_created",
        reason=reason,
        key_count=len(snapshot),
    )


def _clear_review_state() -> None:
    """Clear the prior copilot result when the user starts a new question."""
    for key in (
        "cv35_last_answer",
        "cv35_last_question",
        "cv35_last_error",
        "cv35_provider_connected",
    ):
        if key in st.session_state:
            _log_ask_cadivor_state_clear(key, reason="new_question_queued")
            st.session_state.pop(key, None)
    _clear_followup_ui_state()


def _clear_followup_ui_state() -> None:
    """Drop cached follow-up labels and button widget keys to avoid blank controls."""
    st.session_state.pop("cv36_followup_options", None)
    st.session_state.pop("cv36_followup_ready_for", None)
    st.session_state.pop("cv36_followup_analysis_id", None)
    for key in list(st.session_state.keys()):
        if str(key).startswith("cv36_pick_btn_"):
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
    from src.secrets import get_secret

    value = get_secret(name, default=default)
    return str(value or default)


def _render_context_header(context: dict[str, Any]) -> None:
    summary = context.get("summary") or {}
    project = html.escape(str(context.get("project_name") or "Saved BOM"))
    health = html.escape(str(summary.get("health_score") or "—"))
    parts = html.escape(str(summary.get("total_parts") or "—"))
    posture = html.escape(str(summary.get("release_posture") or "Engineering review"))
    _render_presentation_html(
        f"""
        <header class="cv-assistant-context-header">
          <div class="cv-assistant-context-main">
            <div class="cv-assistant-eyebrow">Ask Cadivor</div>
            <h2 class="cv-assistant-context-title">Engineering copilot for this saved BOM</h2>
            <p class="cv-assistant-context-copy">Cadivor interprets saved evidence and recommends next engineering actions for this analysis.</p>
          </div>
          <div class="cv-assistant-context-meta">
            <span class="cv-badge cv-badge-neutral">{project}</span>
            <span class="cv-assistant-meta-item">Health {health}</span>
            <span class="cv-assistant-meta-item">{parts} parts</span>
            <span class="cv-assistant-meta-item">{posture}</span>
          </div>
        </header>
        """
    )


def _usage_banner(status) -> None:
    if status.is_admin:
        text = "Admin access · AI usage limits bypassed"
        cls = "normal"
    else:
        text = f"{status.remaining:,} of {status.allowance:,} AI credits remaining this month"
        cls = status.warning_level
    st.markdown(
        f'<div class="cv35-usage cv-assistant-usage {cls}"><strong>AI usage</strong><span>{html.escape(text)}</span></div>',
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
    _render_presentation_html(
        f"""
        <div class="cv35-message cv35-message-error">
          <div class="cv35-message-icon">!</div>
          <div><strong>{html.escape(title)}</strong><p>{html.escape(str(exc))}</p></div>
        </div>
        """
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
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


_ENUMERATION_ONLY_RE = re.compile(r"^\d+[\).\s]*$")
_ACTION_PREFIX_RE = re.compile(r"^(?:[-*•]\s*)?\d+[\).\s]+")


def _is_enumeration_only(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return True
    if _ENUMERATION_ONLY_RE.fullmatch(clean):
        return True
    return len(clean) <= 2 and clean.isdigit()


def _strip_action_prefix(text: str) -> str:
    clean = str(text or "").strip()
    clean = re.sub(r"^[-*•]\s+", "", clean)
    while True:
        updated = _ACTION_PREFIX_RE.sub("", clean, count=1).strip()
        if updated == clean:
            break
        clean = updated
    return clean.strip(" .")


def _normalize_action_items(actions: str, *, limit: int = _CONCISE_ACTION_LIMIT) -> list[str]:
    """Normalize recommended actions without producing enumeration-only rows."""
    plain = _plain_markdown(actions)
    if not plain:
        return []

    items: list[str] = []
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    if len(lines) > 1:
        pending_number: str | None = None
        for line in lines:
            if _is_enumeration_only(line):
                pending_number = line
                continue
            stripped = _strip_action_prefix(line)
            if stripped and not _is_enumeration_only(stripped):
                items.append(stripped)
                pending_number = None
            elif pending_number and stripped:
                combined = _strip_action_prefix(f"{pending_number} {stripped}")
                if combined and not _is_enumeration_only(combined):
                    items.append(combined)
                pending_number = None
        if items:
            return items[:limit]

    inline_markers = len(re.findall(r"(?:^|\s)\d+[.)]\s+", plain))
    if inline_markers >= 2:
        for part in re.split(r"\s+(?=\d+[.)]\s+)", plain):
            candidate = _strip_action_prefix(part.strip(" ."))
            if candidate and not _is_enumeration_only(candidate):
                items.append(candidate)
        if items:
            return items[:limit]

    parts = re.split(r"(?<!\d)\.\s+(?!\d)", plain)
    for part in parts:
        candidate = _strip_action_prefix(part.strip(" ."))
        if candidate and not _is_enumeration_only(candidate):
            items.append(candidate)

    if not items:
        candidate = _strip_action_prefix(plain)
        if candidate and not _is_enumeration_only(candidate):
            items.append(candidate)

    return items[:limit]


def _action_steps(actions: str) -> list[str]:
    normalized = _normalize_action_items(actions, limit=4)
    if normalized:
        return normalized
    plain = _plain_markdown(actions)
    return [plain] if plain else []


def _html_kpi_cell(label: str, value: str) -> str:
    return (
        f'<div class="cv39-kpi-item">'
        f'<span class="cv39-kpi-label">{html.escape(label)}</span>'
        f'<strong class="cv39-kpi-value">{html.escape(value)}</strong>'
        f"</div>"
    )


def _html_impact_row(label: str, value: str, note: str) -> str:
    return (
        f'<article class="cv724-impact-cell">'
        f'<div class="cv39-impact-label">{html.escape(label)}</div>'
        f'<div class="cv39-impact-value">{html.escape(value)}</div>'
        f'<div class="cv39-impact-note">{html.escape(note)}</div>'
        f"</article>"
    )


def _html_confidence_driver(label: str, value: str, note: str) -> str:
    return (
        f'<article class="cv724-driver-cell">'
        f'<div class="cv46-driver-label">{html.escape(label)}</div>'
        f'<div class="cv46-driver-value">{html.escape(value)}</div>'
        f'<div class="cv46-driver-note">{html.escape(note)}</div>'
        f"</article>"
    )


def _html_list_row(index: int, text: str, *, variant: str) -> str:
    index_label = f"{index:02d}"
    return (
        f'<li class="cv722-{variant}-row">'
        f'<div class="cv722-list-index" aria-hidden="true">{index_label}</div>'
        f'<div class="cv722-row-body"><p>{html.escape(text)}</p></div>'
        f"</li>"
    )


def _html_evidence_metric(label: str, value: str, *, icon: str = "") -> str:
    icon_html = (
        f'<span class="cv724-evidence-icon" aria-hidden="true">{html.escape(icon)}</span>'
        if icon
        else ""
    )
    return (
        f'<div class="cv46-evidence-metric">'
        f'<div class="cv46-evidence-metric-label">{icon_html}'
        f'<span class="cv46-evidence-metric-label-text">{html.escape(label)}</span></div>'
        f'<div class="cv46-evidence-metric-value">{html.escape(value)}</div>'
        f"</div>"
    )


def _evidence_card_status(detail: str) -> str:
    lowered = str(detail or "").lower()
    if any(token in lowered for token in ("qualify immediately", "high", "obsolete", "replacement", "single-source")):
        return "Priority"
    return "Review"


def _build_single_evidence_card_html(title: str, detail: str) -> str:
    status = _evidence_card_status(detail)
    return (
        f'<article class="cv46-evidence-card">'
        f'<header class="cv46-evidence-card-header">'
        f'<div class="cv46-evidence-component">{html.escape(title)}</div>'
        f'<div class="cv46-evidence-status">{html.escape(status)}</div>'
        f"</header>"
        f'<div class="cv46-evidence-body">'
        f'<div class="cv46-evidence-label">Evidence</div>'
        f'<p class="cv46-evidence-statement cv-assistant-preline">{html.escape(detail)}</p>'
        f"</div>"
        f"</article>"
    )


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
    return internal_app_href(page, **params)


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
        st.markdown(
            f'<div class="cv46-empty-evidence cv-assistant-preline">{html.escape(message)}</div>',
            unsafe_allow_html=True,
        )
        return
    cards = [_build_single_evidence_card_html(title, detail) for title, detail in items[:8]]
    st.markdown(f'<div class="cv46-evidence-board">{"".join(cards)}</div>', unsafe_allow_html=True)


def _build_evidence_cards_html(evidence: str) -> str:
    items = _evidence_items(evidence)
    if not items:
        message = _plain_markdown(evidence) or "No structured evidence was returned. Verify that component records are saved and re-run the review."
        return f'<div class="cv46-empty-evidence cv-assistant-preline">{html.escape(message)}</div>'
    cards = [_build_single_evidence_card_html(title, detail) for title, detail in items[:8]]
    return f'<div class="cv46-evidence-board">{"".join(cards)}</div>'


def _build_decision_summary_html(
    *,
    status: str,
    tone: str,
    priority_part: str,
    confidence_score: int,
    confidence_label: str,
) -> str:
    priority_value = html.escape(priority_part or "Not identified")
    return f"""
        <section class="cv722-summary-strip cv722-summary-strip--{html.escape(tone)}" aria-label="Engineering decision summary">
          <div class="cv722-summary-item" data-field="status">
            <div class="cv722-summary-label">Status</div>
            <div class="cv722-summary-value">{html.escape(status)}</div>
          </div>
          <div class="cv722-summary-item cv722-summary-item--priority" data-field="priority">
            <div class="cv722-summary-label">Priority component</div>
            <div class="cv722-summary-value">{priority_value}</div>
          </div>
          <div class="cv722-summary-item" data-field="confidence">
            <div class="cv722-summary-label">Confidence</div>
            <div class="cv722-summary-value">{confidence_score}%</div>
            <div class="cv722-summary-note">{html.escape(confidence_label)}</div>
          </div>
        </section>
        """


def _build_concise_answer_html(
    *,
    headline: str,
    answer_text: str,
    reason_items: list[str],
    action_items: list[str],
) -> str:
    reasons_html = "".join(
        _html_list_row(index, reason, variant="reason")
        for index, reason in enumerate(reason_items[:_CONCISE_REASON_LIMIT], start=1)
    )
    actions_html = "".join(
        _html_list_row(index, action, variant="action")
        for index, action in enumerate(action_items[:_CONCISE_ACTION_LIMIT], start=1)
    )
    answer_body_html = _direct_answer_body_html(headline, answer_text)
    return f"""
            <section class="cv49-answer-card cv722-concise-answer">
              <div class="cv49-answer-kicker">Cadivor Answer</div>
              <div class="cv722-direct-answer">
                <div class="cv722-section-label">Direct answer</div>
                <div class="cv722-direct-answer-title">{html.escape(headline)}</div>
                {answer_body_html}
              </div>
              <div class="cv722-concise-block">
                <div class="cv722-section-label">Key engineering reasons</div>
                <ul class="cv722-reason-list">{reasons_html}</ul>
              </div>
              <div class="cv722-concise-block">
                <div class="cv722-section-label">Recommended actions</div>
                <ul class="cv722-action-list">{actions_html}</ul>
              </div>
            </section>
            """


def _build_engineering_assessment_html(
    *,
    question: str,
    detailed: bool,
    intent: str,
    evidence: str,
    actions: str,
    rankings: str,
    workflow_text: str,
    context: dict[str, Any],
    priority_part: str,
    confidence_detail: str,
    confidence_drivers: list[tuple[str, str, str]],
    impact: list[tuple[str, str, str]],
    complete: int,
    total: int,
    progress: int,
) -> str:
    sections: list[str] = []
    impact_html = "".join(_html_impact_row(label, value, note) for label, value, note in impact)
    if impact_html:
        sections.append(
            '<div class="cv35-section-label">Projected engineering impact</div>'
            f'<div class="cv724-impact-grid">{impact_html}</div>'
            '<p class="cv724-impact-disclaimer">Projections are directional estimates based on saved evidence, not measured outcomes.</p>'
        )

    if confidence_drivers:
        driver_html = "".join(
            _html_confidence_driver(label, value, note) for label, value, note in confidence_drivers[:6]
        )
        detail_html = (
            f'<p class="cv-assistant-preline cv722-confidence-detail">{html.escape(confidence_detail)}</p>'
            if confidence_detail
            else ""
        )
        sections.append(
            '<div class="cv35-section-label">Confidence drivers</div>'
            f'<div class="cv724-driver-grid cv722-confidence-drivers-only">{detail_html}{driver_html}</div>'
        )

    if rankings:
        ranking_items = _evidence_items(rankings)
        ranking_html = "".join(
            f'<article class="cv47-ranking-row"><div class="cv47-ranking-index">{idx}</div><div class="cv47-ranking-copy">'
            f'<div class="cv47-ranking-title">{html.escape(title)}</div>'
            f'<div class="cv47-ranking-detail">{html.escape(detail)}</div></div></article>'
            for idx, (title, detail) in enumerate(ranking_items, 1)
        )
        sections.append(
            '<div class="cv35-section-label">Engineering priority ranking</div>'
            f'<div class="cv47-ranking-board">{ranking_html}</div>'
        )

    if _evidence_items(evidence):
        sections.append(
            '<div class="cv35-section-label">Evidence breakdown</div>'
            f'{_build_evidence_cards_html(evidence)}'
        )

    show_progress = detailed or intent in {"production_readiness", "evidence_sensitivity", "evidence_gap_priority"}
    if show_progress:
        progress_label = {
            "production_readiness": "Release-readiness review",
            "procurement": "Procurement review",
            "supplier_qualification": "Supplier qualification review",
            "schedule_resilience": "Schedule-resilience review",
            "lifecycle": "Lifecycle review",
            "inventory": "Inventory review",
            "evidence_sensitivity": "Evidence-confidence review",
        }.get(intent, "Engineering review progress")
        sections.append(
            f'<div class="cv724-progress-card">'
            f'<div class="cv39-progress-header">'
            f'<div class="cv39-progress-label">{html.escape(progress_label)}</div>'
            f'<div class="cv39-progress-value">{progress}%</div>'
            f"</div>"
            f'<div class="cv39-progress"><i style="width:{progress}%"></i></div>'
            f"</div>"
        )

    if _should_render_workflow_timeline(question, detailed=detailed, workflow_text=workflow_text, context=context):
        workflow = _parse_workflow_steps(workflow_text, actions, priority_part, intent=intent)
        if workflow:
            workflow_html = "".join(
                f'<article class="cv39-timeline-step">'
                f'<div class="cv724-timeline-index">{idx}</div>'
                f'<div class="cv724-timeline-title">{html.escape(label)}</div>'
                f'<p class="cv-assistant-preline cv724-timeline-detail">{html.escape(detail)}</p>'
                f"</article>"
                for idx, (label, detail) in enumerate(workflow, start=1)
            )
            sections.append(
                '<div class="cv35-section-label">Priority timeline</div>'
                f'<div class="cv724-timeline-grid">{workflow_html}</div>'
            )

    return "".join(sections)


def _build_assessment_panel_html(assessment_html: str) -> str:
    if not str(assessment_html or "").strip():
        return ""
    return f"""
        <section class="cv727-assessment-panel">
          <div class="cv727-assessment-heading">Engineering Assessment</div>
          <div class="cv727-assessment-body">
            {assessment_html}
          </div>
        </section>
        """


def _native_badge_tone(raw: str) -> str:
    tone = str(raw or "neutral").strip().lower()
    if tone in {"ready", "success", "high"}:
        return "success"
    if tone in {"critical", "danger", "blocked"}:
        return "danger"
    if tone in {"warning", "medium", "review"}:
        return "warning"
    if tone in {"confidence", "info", "monitoring"}:
        return tone
    return "neutral"


def _build_conversation_exchange_html(*, question: str, intent: str) -> str:
    response_label, response_class = _response_type_meta(intent)
    safe_question = html.escape(_plain_markdown(str(question or "").strip()))
    return f"""
        <section class="cv50-exchange">
          <div class="cv50-exchange-top">
            <div class="cv50-you-asked">
              <div class="cv50-you-asked-label">You asked</div>
              <div class="cv50-you-asked-question">{safe_question}</div>
            </div>
            <div class="cv50-exchange-badges">
              <div class="cv50-type cv50-type--{html.escape(response_class)}">{html.escape(response_label)}</div>
              <div class="cv50-saved">✓ Review auto-saved</div>
            </div>
          </div>
        </section>
        """


def _render_native_conversation_exchange(*, question: str, intent: str) -> None:
    st.markdown(
        _build_conversation_exchange_html(question=question, intent=intent),
        unsafe_allow_html=True,
    )


def _render_native_answer_column(
    *,
    headline: str,
    answer_text: str,
    reason_items: list[str],
    action_items: list[str],
    decision: dict[str, str],
    priority_part: str,
    confidence_score: int,
    confidence_label: str,
) -> None:
    st.markdown(
        _build_concise_answer_html(
            headline=headline,
            answer_text=answer_text,
            reason_items=reason_items,
            action_items=action_items,
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        _build_decision_summary_html(
            status=str(decision.get("status") or "Review"),
            tone=str(decision.get("tone") or "neutral"),
            priority_part=priority_part,
            confidence_score=confidence_score,
            confidence_label=confidence_label,
        ),
        unsafe_allow_html=True,
    )


def _render_native_assessment_column(
    *,
    question: str,
    detailed: bool,
    intent: str,
    evidence: str,
    actions: str,
    rankings: str,
    workflow_text: str,
    context: dict[str, Any],
    priority_part: str,
    confidence_detail: str,
    confidence_drivers: list[tuple[str, str, str]],
    impact: list[tuple[str, str, str]],
    complete: int,
    total: int,
    progress: int,
) -> None:
    assessment_html = _build_engineering_assessment_html(
        question=question,
        detailed=detailed,
        intent=intent,
        evidence=evidence,
        actions=actions,
        rankings=rankings,
        workflow_text=workflow_text,
        context=context,
        priority_part=priority_part,
        confidence_detail=confidence_detail,
        confidence_drivers=confidence_drivers,
        impact=impact,
        complete=complete,
        total=total,
        progress=progress,
    )
    panel_html = _build_assessment_panel_html(assessment_html)
    if panel_html.strip():
        st.markdown(panel_html, unsafe_allow_html=True)


def _render_decision_workspace(
    *,
    question: str,
    detailed: bool,
    intent: str,
    assessment_body: str,
    priority_part: str,
    confidence_score: int,
    confidence_label: str,
    concise_reasons: list[str],
    concise_actions: list[str],
    decision: dict[str, str],
    profile: dict[str, str],
    evidence: str,
    actions: str,
    rankings: str,
    workflow_text: str,
    context: dict[str, Any],
    confidence_detail: str,
    confidence_drivers: list[tuple[str, str, str]],
    impact: list[tuple[str, str, str]],
    complete: int,
    total: int,
    progress: int,
) -> None:
    headline = _conversational_headline(intent, assessment_body, priority_part)
    answer_text = _plain_markdown(assessment_body).strip() or "The saved evidence is not sufficient for a reliable conclusion."
    _log_ask_render(
        "workspace_shell_ready",
        left_html_len=0,
        right_html_len=0,
        has_assessment_panel=True,
        has_style_tag=False,
        renderer="native_streamlit",
    )
    _log_ask_render("workspace_columns_requested", ratio="0.85,1.15")
    with st.container():
        left_col, right_col = st.columns(_DECISION_COLUMN_RATIO, gap="large")
        with left_col:
            _log_ask_render("workspace_left_column_entered")
            _render_native_answer_column(
                headline=headline,
                answer_text=answer_text,
                reason_items=concise_reasons,
                action_items=concise_actions,
                decision=decision,
                priority_part=priority_part,
                confidence_score=confidence_score,
                confidence_label=confidence_label,
            )
        with right_col:
            _log_ask_render("workspace_right_column_entered")
            _render_native_assessment_column(
                question=question,
                detailed=detailed,
                intent=intent,
                evidence=evidence,
                actions=actions,
                rankings=rankings,
                workflow_text=workflow_text,
                context=context,
                priority_part=priority_part,
                confidence_detail=confidence_detail,
                confidence_drivers=confidence_drivers,
                impact=impact,
                complete=complete,
                total=total,
                progress=progress,
            )
    _log_ask_render("workspace_render_completed")
    with st.container(border=True):
        _render_quick_actions(context, priority_part, intent=intent)


def _render_quick_actions(context: dict[str, Any], priority_part: str, *, intent: str = "general") -> None:
    analysis = context.get("analysis") or {}
    analysis_id = str(analysis.get("analysis_id") or "")
    if not analysis_id:
        return
    render_subsection_header("Continue the workflow", icon="workflow")
    part_label = priority_part or "component"
    component_url = _href("Analysis Details", analysis_id=analysis_id, tab="components", component=priority_part, focus="component-risk")
    alternative_url = alternative_finder_href(
        mpn=priority_part,
        analysis_id=analysis_id,
        source_page="engineering_intelligence",
    )
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
    primary_label, primary_url = actions[1] if len(actions) > 1 else actions[0]
    secondary_actions = [actions[0], actions[2], actions[3]] if len(actions) > 3 else actions[1:]
    with st.container(border=True):
        primary_col, secondary_col = st.columns([1.15, 2])
        with primary_col:
            if primary_url == alternative_url:
                internal_nav_button(
                    primary_label,
                    ALTERNATIVE_FINDER_PAGE,
                    key=f"ea_quick_alt_primary_{intent}_{priority_part}",
                    use_container_width=True,
                    original_part=priority_part,
                    analysis_id=analysis_id,
                    return_analysis_id=analysis_id,
                    source_page="engineering_intelligence",
                )
            else:
                primary_col.link_button(primary_label, primary_url, use_container_width=True)
        with secondary_col:
            sec_cols = secondary_col.columns(len(secondary_actions))
            for col, (label, url) in zip(sec_cols, secondary_actions):
                with col:
                    if url == alternative_url:
                        internal_nav_button(
                            label,
                            ALTERNATIVE_FINDER_PAGE,
                            key=f"ea_quick_alt_{intent}_{label}",
                            use_container_width=True,
                            original_part=priority_part,
                            analysis_id=analysis_id,
                            return_analysis_id=analysis_id,
                            source_page="engineering_intelligence",
                        )
                    else:
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
            _render_presentation_html(
                f"""
                <div class="cv36-history-turn">
                  <div class="cv36-history-number">{index}</div>
                  <div><small>Review {index}</small><strong>{question}</strong><p class="cv-assistant-preline">{assessment}</p></div>
                </div>
                """
            )


def _queue_copilot_submission(question: str, *, submission_kind: str, analysis_id: str = "") -> None:
    """Queue a copilot question behind auth snapshot protection and rerun."""
    if _block_duplicate_submission(kind=submission_kind, analysis_id=analysis_id):
        return

    clean = _normalize_submitted_question(question)
    if not clean:
        return

    _log_copilot_workflow(
        "copilot_submission_queued",
        kind=submission_kind,
        question_len=len(clean),
    )

    if submission_kind in {"manual", "suggestion"}:
        st.session_state["cv41_pending_manual"] = clean
    else:
        st.session_state["cv36_pending_followup"] = clean
        st.session_state["cv47_followup_question"] = clean

    st.session_state["cv7142_ask_inflight"] = True
    st.session_state["cv47_scroll_pending"] = True
    _pin_ask_cadivor_tab(source=f"queue_{submission_kind}", analysis_id=analysis_id)
    _log_ask_cadivor("question_queued", kind=submission_kind, question_len=len(clean))
    _arm_copilot_workflow_snapshot(reason=f"queue_{submission_kind}")
    _clear_review_state()
    _log_ask_cadivor("rerun_requested", kind=submission_kind, source="queue_copilot_submission")
    st.rerun()


def _queue_follow_up(question: str, *, analysis_id: str = "") -> None:
    _queue_copilot_submission(question, submission_kind="followup", analysis_id=analysis_id)


def _analysis_id_from_context(context: dict[str, Any]) -> str:
    analysis = context.get("analysis") or {}
    return str(context.get("analysis_id") or analysis.get("analysis_id") or "")


def _select_initial_suggestion(question: str, *, index: int, prompt_key: str, analysis_id: str = "") -> None:
    """Queue a suggested prompt through the protected copilot submission pipeline."""
    _log_ask_cadivor(
        "suggestion_clicked",
        kind="cv35",
        index=index,
        analysis_id=analysis_id or "active",
    )
    _queue_copilot_submission(question, submission_kind="suggestion", analysis_id=analysis_id)


def _apply_copilot_query_picks(*, prompt_key: str) -> None:
    """Consume legacy URL pick params once (backward compatibility for bookmarked links)."""
    try:
        query_params = st.query_params
    except Exception:
        return

    pick = str(query_params.get("cv35_pick", "") or "").strip()
    if pick.isdigit():
        idx = int(pick)
        if 0 <= idx < len(SUGGESTIONS):
            try:
                del query_params["cv35_pick"]
            except Exception:
                pass
            analysis_id = str(
                st.session_state.get("cadivor_active_analysis_id")
                or st.session_state.get("analysis_id")
                or ""
            )
            _log_ask_cadivor("suggestion_selected", kind="cv35", index=idx, source="url")
            _queue_copilot_submission(
                SUGGESTIONS[idx],
                submission_kind="suggestion",
                analysis_id=analysis_id,
            )
        return

    follow_pick = str(query_params.get("cv36_pick", "") or "").strip()
    if not follow_pick.isdigit():
        return
    options = st.session_state.get("cv36_followup_options") or []
    idx = int(follow_pick)
    if 0 <= idx < len(options):
        question = str(options[idx] or "").strip()
        if question:
            try:
                del query_params["cv36_pick"]
            except Exception:
                pass
            _log_ask_cadivor("suggestion_selected", kind="cv36", index=idx, source="url")
            _queue_follow_up(
                question,
                analysis_id=str(st.session_state.get("cv36_followup_analysis_id") or ""),
            )


def _followup_button_generation(labels: list[str]) -> str:
    import hashlib

    payload = "|".join(labels).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:10]


def _render_prompt_chip_grid(
    items: Iterable[str],
    *,
    param_key: str,
    analysis_id: str = "",
    grid_class: str = "cv35-suggestion-grid",
    prompt_key: str = "cv35_question",
    button_generation: str = "",
    disabled: bool = False,
) -> None:
    """Render suggested questions as in-app Streamlit buttons (no full-page navigation)."""
    labels = [str(raw or "").strip() for raw in items]
    labels = [label for label in labels if label]
    if not labels:
        return

    cols_per_row = 2 if "duo" in grid_class else 3
    for row_start in range(0, len(labels), cols_per_row):
        row_labels = labels[row_start : row_start + cols_per_row]
        cols = st.columns(len(row_labels))
        for col_idx, label in enumerate(row_labels):
            index = row_start + col_idx
            with cols[col_idx]:
                key_suffix = f"{button_generation}_{index}" if button_generation else str(index)
                button_key = f"{param_key}_btn_{key_suffix}"
                if st.button(label, key=button_key, use_container_width=True, disabled=disabled):
                    if param_key == "cv36_pick":
                        _log_ask_cadivor("suggestion_selected", kind="cv36", index=index)
                        _queue_follow_up(label, analysis_id=analysis_id)
                    else:
                        _select_initial_suggestion(
                            label,
                            index=index,
                            prompt_key=prompt_key,
                            analysis_id=analysis_id,
                        )


def _render_follow_ups(*, question: str, answer: str, context: dict[str, Any]) -> None:
    if not str(answer or "").strip():
        return
    suggestions = follow_up_suggestions(question, answer, context)
    valid_suggestions = [str(item or "").strip() for item in suggestions]
    valid_suggestions = [item for item in valid_suggestions if item]
    analysis_id = _analysis_id_from_context(context)
    if not valid_suggestions or not analysis_id:
        _clear_followup_ui_state()
        return

    ready_for = f"{question}|{answer[:120]}"
    if st.session_state.get("cv36_followup_ready_for") != ready_for:
        _clear_followup_ui_state()
    st.session_state["cv36_followup_options"] = valid_suggestions
    st.session_state["cv36_followup_analysis_id"] = analysis_id
    st.session_state["cv36_followup_ready_for"] = ready_for
    button_generation = _followup_button_generation(valid_suggestions)

    render_subsection_header("Continue the review", icon="messages-square")
    with st.container(border=True):
        st.caption("Suggested follow-ups")
        _render_prompt_chip_grid(
            valid_suggestions,
            param_key="cv36_pick",
            analysis_id=analysis_id,
            grid_class="cv35-suggestion-grid cv35-suggestion-grid--duo",
            button_generation=button_generation,
        )

    st.caption("Ask a different follow-up")
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
            _queue_follow_up(custom, analysis_id=analysis_id)
        else:
            st.warning("Enter a follow-up question before submitting.")
    _log_ask_render("followups_rendered")


def _first_sentence(text: str) -> str:
    plain = _plain_markdown(text).strip()
    if not plain:
        return "Cadivor completed the engineering review."
    match = re.search(r"^(.+?[.!?])(?:\s|$)", plain)
    return (match.group(1) if match else plain).strip()


def _supplementary_direct_answer_text(headline: str, answer_text: str) -> str:
    headline_clean = str(headline or "").strip()
    answer_clean = str(answer_text or "").strip()
    if not answer_clean:
        return ""
    fallback = "The saved evidence is not sufficient for a reliable conclusion."
    if answer_clean == fallback:
        return answer_clean
    if not headline_clean:
        return answer_clean

    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().rstrip(".!?")).lower()

    if _norm(answer_clean) == _norm(headline_clean):
        return ""
    headline_stem = headline_clean.rstrip(".!?")
    if answer_clean.lower().startswith(headline_stem.lower()):
        remainder = answer_clean[len(headline_stem):].lstrip(" .")
        if remainder.startswith((".", "!", "?")):
            remainder = remainder[1:].lstrip()
        return remainder
    return answer_clean


def _direct_answer_body_html(headline: str, answer_text: str) -> str:
    supplementary = _supplementary_direct_answer_text(headline, answer_text)
    if not supplementary:
        return ""
    return f'<p class="cv722-direct-answer-text cv-assistant-preline">{html.escape(supplementary)}</p>'


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
    """Scroll the real Streamlit viewport to the newest response start.

    Streamlit scrolls inside ``[data-testid="stMain"]`` on current builds rather
    than on ``window``.  Sprint 50.1 only moved ``window``, which left the visible
    app viewport unchanged.  This controller resolves the actual scroll owner,
    positions the response immediately below the sticky header, and repeats the
    placement while the answer layout stabilizes.
    """
    safe_token = html.escape(str(response_token or "response"))
    components.html(
        f"""
        <script data-cadivor-response-token="{safe_token}">
        (function(){{
          const parentWindow = window.parent;
          const doc = parentWindow.document;
          const frame = window.frameElement;
          if (!frame) return;

          const host = frame.closest('[data-testid="stElementContainer"]') || frame.parentElement || frame;
          const OFFSET = 70;
          let attempts = 0;
          let stable = 0;
          let observer = null;

          function scrollOwner(){{
            const explicit = doc.querySelector('[data-testid="stMain"]');
            if (explicit) return explicit;
            let node = host.parentElement;
            while (node && node !== doc.body) {{
              try {{
                const style = parentWindow.getComputedStyle(node);
                const overflowY = style.overflowY;
                if ((overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight > node.clientHeight + 2) return node;
              }} catch (_) {{}}
              node = node.parentElement;
            }}
            return doc.scrollingElement || doc.documentElement;
          }}

          function blurInput(){{
            try {{
              const active = doc.activeElement;
              if (active && typeof active.blur === 'function') active.blur();
            }} catch (_) {{}}
          }}

          function currentTop(owner){{
            const hostRect = host.getBoundingClientRect();
            if (owner === doc.scrollingElement || owner === doc.documentElement || owner === doc.body) return hostRect.top;
            const ownerRect = owner.getBoundingClientRect();
            return hostRect.top - ownerRect.top;
          }}

          function place(){{
            attempts += 1;
            if (!host || host.getClientRects().length === 0) {{
              if (attempts < 70) parentWindow.setTimeout(place, 90);
              return;
            }}

            blurInput();
            const owner = scrollOwner();
            const hostRect = host.getBoundingClientRect();

            try {{
              if (owner === doc.scrollingElement || owner === doc.documentElement || owner === doc.body) {{
                const desired = Math.max(0, hostRect.top + (parentWindow.pageYOffset || owner.scrollTop || 0) - OFFSET);
                parentWindow.scrollTo({{ top: desired, left: 0, behavior: attempts <= 2 ? 'smooth' : 'auto' }});
                owner.scrollTop = desired;
              }} else {{
                const ownerRect = owner.getBoundingClientRect();
                const desired = Math.max(0, owner.scrollTop + hostRect.top - ownerRect.top - OFFSET);
                owner.scrollTo({{ top: desired, left: 0, behavior: attempts <= 2 ? 'smooth' : 'auto' }});
              }}
            }} catch (_) {{
              try {{ host.scrollIntoView({{ block: 'start', inline: 'nearest', behavior: 'auto' }}); }} catch (_) {{}}
            }}

            const top = Math.round(currentTop(owner));
            stable = Math.abs(top - OFFSET) <= 16 ? stable + 1 : 0;
            if (stable >= 4 || attempts >= 70) {{
              if (observer) observer.disconnect();
              return;
            }}
            parentWindow.setTimeout(place, attempts < 16 ? 90 : 170);
          }}

          try {{
            observer = new MutationObserver(function(){{ parentWindow.requestAnimationFrame(place); }});
            observer.observe(doc.body, {{ childList: true, subtree: true, attributes: true }});
          }} catch (_) {{}}

          parentWindow.requestAnimationFrame(function(){{ parentWindow.requestAnimationFrame(place); }});
          [120, 260, 480, 800, 1250, 1900, 2800, 4000].forEach(ms => parentWindow.setTimeout(place, ms));
        }})();
        </script>
        """,
        height=0,
    )


def _render_conversation_exchange(*, question: str, intent: str) -> None:
    _render_native_conversation_exchange(question=question, intent=intent)


def _concise_reason_items(evidence: str, drivers: list[str], *, limit: int = _CONCISE_REASON_LIMIT) -> list[str]:
    """Return capped reason lines for the concise answer surface."""
    items: list[str] = []
    for title, detail in _evidence_items(evidence):
        line = f"{title}: {detail}" if title and title != "Engineering evidence" else detail
        clean = _plain_markdown(line).strip()
        if clean:
            items.append(clean)
    if not items:
        items = [_plain_markdown(item).strip() for item in drivers if str(item or "").strip()]
    return items[:limit]


def _concise_action_items(actions: str, *, limit: int = _CONCISE_ACTION_LIMIT) -> list[str]:
    """Return capped recommended actions for the concise answer surface."""
    return _normalize_action_items(actions, limit=limit)


def _should_render_workflow_timeline(
    question: str,
    *,
    detailed: bool,
    workflow_text: str,
    context: dict[str, Any],
) -> bool:
    """Render workflow/timeline only for workflow-oriented or detailed requests."""
    if detailed:
        return True
    if str(workflow_text or "").strip():
        return True
    text = str(question or "").strip().lower()
    workflow_tokens = (
        "workflow",
        "timeline",
        "implementation plan",
        "action plan",
        "step by step",
        "steps should",
        "what steps",
        "how do i implement",
        "owner action",
        "closure plan",
        "mitigation plan",
        "engineering owner",
    )
    if any(token in text for token in workflow_tokens):
        return True
    timeline = list(context.get("timeline") or [])
    decisions = list(context.get("decisions") or context.get("engineering_decisions") or [])
    if (timeline or decisions) and any(token in text for token in ("monitor", "decision", "follow through", "close out", "track")):
        return True
    return False


def _parse_workflow_steps(
    workflow_text: str,
    actions: str,
    priority_part: str,
    *,
    intent: str,
) -> list[tuple[str, str]]:
    if str(workflow_text or "").strip():
        workflow: list[tuple[str, str]] = []
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
        return workflow[:5]
    return _workflow_steps(actions, priority_part, intent=intent)


def _render_compact_decision_summary(
    *,
    label: str,
    status: str,
    tone: str,
    risk: str,
    priority_part: str,
    confidence_score: int,
    confidence_label: str,
) -> None:
    priority_value = html.escape(priority_part or "Not identified")
    _render_presentation_html(
        f"""
        <section class="cv722-summary-strip cv722-summary-strip--{html.escape(tone)}" aria-label="Engineering decision summary">
          <div class="cv722-summary-item" data-field="status">
            <div class="cv722-summary-label">Status</div>
            <div class="cv722-summary-value">{html.escape(status)}</div>
          </div>
          <div class="cv722-summary-item cv722-summary-item--priority" data-field="priority">
            <div class="cv722-summary-label">Priority component</div>
            <div class="cv722-summary-value">{priority_value}</div>
          </div>
          <div class="cv722-summary-item" data-field="confidence">
            <div class="cv722-summary-label">Confidence</div>
            <div class="cv722-summary-value">{confidence_score}%</div>
            <div class="cv722-summary-note">{html.escape(confidence_label)}</div>
          </div>
        </section>
        """
    )


def _render_expanded_engineering_assessment(
    *,
    question: str,
    detailed: bool,
    intent: str,
    evidence: str,
    actions: str,
    rankings: str,
    workflow_text: str,
    context: dict[str, Any],
    priority_part: str,
    confidence_detail: str,
    confidence_drivers: list[tuple[str, str, str]],
    impact: list[tuple[str, str, str]],
    complete: int,
    total: int,
    progress: int,
    profile: dict[str, str],
) -> None:
    assessment_html = _build_engineering_assessment_html(
        question=question,
        detailed=detailed,
        intent=intent,
        evidence=evidence,
        actions=actions,
        rankings=rankings,
        workflow_text=workflow_text,
        context=context,
        priority_part=priority_part,
        confidence_detail=confidence_detail,
        confidence_drivers=confidence_drivers,
        impact=impact,
        complete=complete,
        total=total,
        progress=progress,
    )
    if assessment_html:
        _render_presentation_html(assessment_html)
    _render_quick_actions(context, priority_part, intent=intent)


def _render_conversational_answer(*, intent: str, assessment: str, priority_part: str,
                                  confidence_score: int, drivers: list[str],
                                  actions: str, workflow_text: str,
                                  reason_items: list[str] | None = None,
                                  action_items: list[str] | None = None,
                                  concise: bool = False) -> None:
    headline = _conversational_headline(intent, assessment, priority_part)
    answer_text = _plain_markdown(assessment).strip() or "The saved evidence is not sufficient for a reliable conclusion."
    if reason_items is None:
        reason_items = [str(item).strip() for item in drivers if str(item).strip()][:4]
    if not reason_items:
        reason_items = [answer_text]
    reasons_html = "".join(
        _html_list_row(index, reason, variant="reason")
        for index, reason in enumerate(reason_items[:_CONCISE_REASON_LIMIT], start=1)
    )
    if action_items is None:
        action_items = _concise_action_items(actions)
    if concise:
        actions_html = "".join(
            _html_list_row(index, action, variant="action")
            for index, action in enumerate(action_items[:_CONCISE_ACTION_LIMIT], start=1)
        )
        _render_presentation_html(
            f"""
            <section class="cv49-answer-card cv722-concise-answer">
              <div class="cv49-answer-kicker">Cadivor Answer</div>
              <div class="cv722-direct-answer">
                <div class="cv722-section-label">Direct answer</div>
                <div class="cv722-direct-answer-title">{html.escape(headline)}</div>
                {_direct_answer_body_html(headline, answer_text)}
              </div>
              <div class="cv722-concise-block">
                <div class="cv722-section-label">Key engineering reasons</div>
                <ul class="cv722-reason-list">{reasons_html}</ul>
              </div>
              <div class="cv722-concise-block">
                <div class="cv722-section-label">Recommended actions</div>
                <ul class="cv722-action-list">{actions_html}</ul>
              </div>
            </section>
            """
        )
        return
    next_action = _next_action(actions, workflow_text)
    _render_presentation_html(
        f"""
        <section class="cv49-answer-card">
          <div class="cv49-answer-kicker">Cadivor Answer</div>
          <div class="cv49-answer-grid">
            <div class="cv49-answer-main">
              <h2>{html.escape(headline)}</h2>
              <p class="cv-assistant-preline">{html.escape(answer_text)}</p>
              <ul>{reasons_html}</ul>
            </div>
            <aside class="cv49-answer-side">
              <span class="cv49-side-label">Confidence</span><strong class="cv49-side-value">{confidence_score}%</strong>
              <div class="cv49-answer-track"><i style="width:{max(0,min(100,confidence_score))}%"></i></div>
              <span class="cv49-side-label">Recommended next action</span><p class="cv-assistant-preline">{html.escape(next_action)}</p>
            </aside>
          </div>
        </section>
        """
    )


def _render_response(*, question: str, answer: str, context: dict[str, Any], auto_scroll: bool = False) -> None:
    _log_ask_render("response_entered")
    detailed = _wants_detailed_response(question)
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
    decision = _decision_summary(context, assessment_body, confidence_score, priority_part, intent=intent, preferred_status=display_title)
    impact = _projected_impact(context, priority_part, intent=intent)
    complete, total, progress = _review_progress(context)
    _, recommendation_drivers = _recommendation_explanation(assessment_body, evidence, priority_part)
    confidence_drivers = _confidence_drivers(context, evidence)
    concise_reasons = _concise_reason_items(evidence, recommendation_drivers)
    concise_actions = _concise_action_items(actions)

    if auto_scroll:
        response_token = f"{abs(hash((question, answer))) :x}"
        _render_response_scroll_anchor(response_token=response_token)

    _render_conversation_exchange(question=question, intent=intent)
    _log_ask_render("exchange_rendered")

    _render_decision_workspace(
        question=question,
        detailed=detailed,
        intent=intent,
        assessment_body=assessment_body,
        priority_part=priority_part,
        confidence_score=confidence_score,
        confidence_label=confidence_label,
        concise_reasons=concise_reasons,
        concise_actions=concise_actions,
        decision=decision,
        profile=profile,
        evidence=evidence,
        actions=actions,
        rankings=rankings,
        workflow_text=workflow_text,
        context=context,
        confidence_detail=confidence_detail,
        confidence_drivers=confidence_drivers,
        impact=impact,
        complete=complete,
        total=total,
        progress=progress,
    )


def render_engineering_assistant(
    *,
    current_user: dict[str, Any],
    engineering_context: Any,
    selected_component: str = "",
) -> None:
    _log_ask_cadivor("script_run_started", surface="ask_cadivor")
    _restore_copilot_workflow_snapshot(st.session_state.get("cv48_copilot_snapshot"))
    _recover_stale_copilot_inflight()
    _log_ask_cadivor_state("script_run_state")
    try:
        context = (
            engineering_context.compact(max_components=15)
            if hasattr(engineering_context, "compact")
            else dict(engineering_context or {})
        )
    except Exception:
        context = {}
    status = get_ai_usage_status(st.session_state, current_user or {})

    _render_context_header(context)
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
    _apply_deferred_prompt_clear(prompt_key)
    _apply_copilot_query_picks(prompt_key=prompt_key)
    auto_execute_followup = False
    queued_question = ""
    pending_manual = st.session_state.get("cv41_pending_manual")
    pending_followup = st.session_state.get("cv36_pending_followup")
    _log_ask_cadivor(
        "pending_question_present",
        manual_present=bool(pending_manual),
        followup_present=bool(pending_followup),
        manual_len=len(str(pending_manual or "")),
    )
    _log_ask_cadivor(
        "inflight_state",
        inflight=bool(st.session_state.get("cv7142_ask_inflight")),
        followup_inflight_flag=bool(st.session_state.get("cv4801_followup_inflight")),
    )
    analysis_id = _analysis_id_from_context(context)
    _log_ask_cadivor(
        "analysis_id_restored",
        analysis_id=analysis_id or "missing",
        session_analysis_id=str(st.session_state.get("cadivor_active_analysis_id") or ""),
    )
    _log_ask_cadivor(
        "ask_tab_restored",
        active_tab=str(st.session_state.get("cadivor_active_analysis_tab") or ""),
    )
    if pending_manual:
        queued_question = str(pending_manual)
        st.session_state[prompt_key] = queued_question
        auto_execute_followup = True
        st.session_state["cv7142_ask_inflight"] = True
        _log_ask_cadivor(
            "queued_question_detected",
            kind="manual_or_suggestion",
            question_len=len(queued_question),
        )
    elif pending_followup:
        # Apply queued follow-ups before the text-area widget is instantiated.
        queued_question = str(pending_followup)
        st.session_state[prompt_key] = queued_question
        auto_execute_followup = True
        st.session_state["cv7142_ask_inflight"] = True
        _log_ask_cadivor(
            "queued_question_detected",
            kind="followup",
            question_len=len(queued_question),
        )
    elif prompt_key not in st.session_state:
        st.session_state[prompt_key] = ""

    copilot_busy = _copilot_submission_inflight()
    actions_disabled = copilot_busy or not status.can_use
    if copilot_busy and not auto_execute_followup:
        st.info(_COPILOT_PROCESSING_LABEL)

    if analysis_id:
        st.markdown(
            '<div class="cv-assistant-section-label cv35-section-label">Suggested engineering workflows</div>',
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            _render_prompt_chip_grid(
                SUGGESTIONS,
                param_key="cv35_pick",
                analysis_id=analysis_id,
                disabled=actions_disabled,
            )

    # A form submits the browser's current text-area value and the button click
    # in one transaction. This prevents pasted text from requiring a first click
    # merely to synchronize the widget before the button becomes enabled.
    with st.container(border=True):
        with st.form("cv41_engineering_question_form", clear_on_submit=False):
            question = st.text_area(
                "Your engineering question",
                key=prompt_key,
                height=88,
                placeholder="Ask Cadivor about this BOM, for example: What evidence is missing before release approval?",
            )
            component_note = f" Current component focus: {selected_component}." if selected_component else ""
            st.caption(
                "Cadivor reviews saved BOM evidence and flags uncertainty when supporting data is incomplete."
                + component_note
            )
            manual_submit = st.form_submit_button(
                "Ask Cadivor",
                type="primary",
                disabled=actions_disabled,
                use_container_width=False,
            )

    cleaned_question = _normalize_submitted_question(question)
    manual_submit_requested = bool(manual_submit and status.can_use and cleaned_question and not copilot_busy)
    if manual_submit and not cleaned_question:
        st.warning("Enter an engineering question before submitting.")
    if manual_submit and copilot_busy:
        _block_duplicate_submission(kind="manual", analysis_id=analysis_id)
    if manual_submit_requested:
        _log_copilot_workflow("manual_copilot_submission_received", question_len=len(cleaned_question))
        _queue_copilot_submission(cleaned_question, submission_kind="manual", analysis_id=analysis_id)

    submitted_question = _normalize_submitted_question(queued_question or cleaned_question)
    submit_requested = bool(
        auto_execute_followup
        and status.can_use
        and submitted_question
        and not manual_submit_requested
    )
    if auto_execute_followup and not submit_requested:
        _log_ask_cadivor(
            "execution_deferred",
            can_use=bool(status.can_use),
            submitted_question_len=len(submitted_question),
            manual_submit_requested=bool(manual_submit_requested),
        )
    if submit_requested:
        st.session_state.pop("cv41_pending_manual", None)
        st.session_state.pop("cv36_pending_followup", None)
        _pin_ask_cadivor_tab(source="execute_copilot_question", analysis_id=analysis_id)
        _arm_copilot_workflow_snapshot(reason="execute_copilot_question")
        _log_ask_cadivor(
            "submission_received",
            kind="execute",
            question_len=len(submitted_question),
            active_tab=st.session_state.get("cadivor_active_analysis_tab", ""),
        )
        api = EngineeringAI(
            api_key=_secret("OPENAI_API_KEY"),
            model=_secret("OPENAI_MODEL", "gpt-4.1-mini"),
            base_url=_secret("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        log_ai_config(api)
        provider_target = "openai" if api.configured else "cadivor-grounded"
        st.session_state.pop("cv35_last_error", None)
        st.session_state["cv35_last_question"] = submitted_question
        st.markdown('<div id="cv47-processing-anchor"></div>', unsafe_allow_html=True)
        if st.session_state.pop("cv47_scroll_pending", False):
            components.html("""<script>(function(){const d=window.parent.document,w=window.parent;function go(){const e=d.getElementById('cv47-processing-anchor');if(e){w.scrollTo({top:Math.max(0,e.getBoundingClientRect().top+w.pageYOffset-92),behavior:'auto'});}}go();setTimeout(go,80);setTimeout(go,240);</script>""", height=0)
        with st.status(_COPILOT_PROCESSING_LABEL, expanded=True) as progress:
            try:
                _log_ask_cadivor(
                    "execution_started",
                    configured=api.configured,
                    provider=provider_target,
                    question_len=len(submitted_question),
                )
                response = api.ask(question=submitted_question, context=context, history=compact_history(thread))
                response_provider = str(getattr(response, "provider", provider_target))
                _log_ask_cadivor(
                    "execution_completed",
                    configured=api.configured,
                    provider=response_provider,
                    question_len=len(submitted_question),
                )
                consume_ai_credits(st.session_state, current_user, action="question")
                st.session_state["cv35_last_answer"] = response.answer
                st.session_state["cv35_last_question"] = submitted_question
                st.session_state["cv35_provider_connected"] = response_provider == "openai"
                st.session_state["cv47_scroll_to_assessment"] = True
                if st.session_state.pop("cv47_followup_question", None):
                    st.session_state["cv47_followup_answered"] = submitted_question
                thread = append_turn(
                    st.session_state,
                    context,
                    question=submitted_question,
                    answer=response.answer,
                    provider_connected=response_provider == "openai",
                )
                # Copilot submission completed inside the authenticated workspace.
                # The recovery snapshot is no longer needed after the answer and
                # active route are safely stored.
                _clear_copilot_workflow_protection()
                st.session_state.pop("cv36_pending_followup", None)
                st.session_state.pop("cv47_followup_question", None)
                st.session_state.pop("cv41_pending_manual", None)
                _schedule_prompt_clear_on_next_run()
                _pin_ask_cadivor_tab(source="provider_complete", analysis_id=analysis_id)
                _log_ask_cadivor(
                    "response_committed",
                    active_tab=st.session_state.get("cadivor_active_analysis_tab", ""),
                    thread_len=len(thread),
                    provider=response_provider,
                )
                progress.update(label="Engineering review complete", state="complete")
            except EngineeringAIError as exc:
                _log_ask_cadivor("provider_failed", exception_type=type(exc).__name__)
                _pin_ask_cadivor_tab(source="provider_failed", analysis_id=analysis_id)
                st.session_state["cv35_last_error"] = exc
                _clear_copilot_workflow_protection()
                st.session_state.pop("cv36_pending_followup", None)
                st.session_state.pop("cv47_followup_question", None)
                st.session_state.pop("cv41_pending_manual", None)
                progress.update(label="Cadivor could not complete the review", state="error")
            except Exception as exc:
                _log_ask_cadivor("execution_failed", exception_type=type(exc).__name__)
                _pin_ask_cadivor_tab(source="execution_failed", analysis_id=analysis_id)
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
                    _clear_copilot_workflow_protection()
                    st.session_state.pop("cv36_pending_followup", None)
                    st.session_state.pop("cv47_followup_question", None)
                    st.session_state.pop("cv41_pending_manual", None)
                    progress.update(label="Engineering review complete", state="complete")
                else:
                    st.session_state["cv35_last_error"] = EngineeringAIError(
                        "Cadivor could not complete this assessment from the saved evidence. "
                        "The previous assessment remains available; refresh the BOM evidence and try again."
                    )
                    progress.update(label="Cadivor safely stopped the review", state="error")
                _clear_copilot_workflow_protection()
                st.session_state.pop("cv36_pending_followup", None)
                st.session_state.pop("cv47_followup_question", None)
                st.session_state.pop("cv41_pending_manual", None)

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
    _log_ask_cadivor(
        "last_answer_present_before_render",
        present=bool(str(answer or "").strip()),
        answer_len=len(str(answer or "")),
    )
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
