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


def _render_evidence_cards(evidence: str) -> None:
    items = _evidence_items(evidence)
    if not items:
        st.markdown(evidence)
        return
    columns = st.columns(2)
    for index, (title, detail) in enumerate(items[:6]):
        columns[index % 2].markdown(
            f"""
            <div class="cv35-evidence-card">
              <div class="cv35-evidence-part">{html.escape(title)}</div>
              <div class="cv35-evidence-detail">{html.escape(detail)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


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
    cols[0].link_button("Open component", component_url, use_container_width=True)
    cols[1].link_button("Find alternative", alternative_url, use_container_width=True)
    cols[2].link_button("Monitor part", monitoring_url, use_container_width=True)
    cols[3].link_button("Record decision", decision_url, use_container_width=True)




def _render_conversation_history(thread: list[dict[str, Any]], *, exclude_latest: bool = False) -> None:
    turns = thread[:-1] if exclude_latest and thread else thread
    if not turns:
        return
    with st.expander(f"Conversation history · {len(turns)} review{'s' if len(turns) != 1 else ''}", expanded=False):
        for index, turn in enumerate(reversed(turns), start=1):
            question = html.escape(str(turn.get("question") or "Engineering question"))
            answer_sections = _parse_report(str(turn.get("answer") or ""))
            assessment = html.escape(_plain_markdown(_section(answer_sections, "Engineering Assessment", "Assessment")))
            st.markdown(
                f"""
                <div class="cv36-history-turn">
                  <div class="cv36-history-number">{index}</div>
                  <div><small>Engineering question</small><strong>{question}</strong><p>{assessment}</p></div>
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
    assessment = _section(sections, "Engineering Assessment", "Assessment")
    evidence = _section(sections, "Supporting Evidence", "Evidence")
    actions = _section(sections, "Recommended Actions", "Recommended action")
    confidence = _section(sections, "Confidence")
    priority_part = _priority_component(context, evidence)
    confidence_label, confidence_score, confidence_detail = _confidence_data(confidence, context)
    confidence_class = "high" if confidence_score >= 75 else "medium" if confidence_score >= 45 else "low"

    st.markdown(
        f"""
        <div class="cv35-review-shell">
          <div class="cv35-question"><small>Engineering question</small>{html.escape(question)}</div>
          <div class="cv35-review-heading">
            <div><div class="cv35-answer-label">Cadivor Engineering Review</div><h2>Engineering Assessment</h2></div>
            <div class="cv35-review-status">Review complete</div>
          </div>
          <div class="cv35-assessment-copy">{html.escape(_plain_markdown(assessment))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="cv35-section-label">Supporting evidence</div>', unsafe_allow_html=True)
    _render_evidence_cards(evidence)

    left, right = st.columns([1.45, 1])
    with left:
        st.markdown(
            f"""
            <div class="cv35-action-card">
              <div class="cv35-card-kicker">Recommended actions</div>
              <div class="cv35-action-copy">{html.escape(_plain_markdown(actions))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
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
        <style id="cadivor-engineering-assistant-352">
        .cv35-hero{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f6f9ff 62%,#eaf2ff);border-radius:24px;padding:22px;margin:2px 0 14px;box-shadow:0 18px 50px rgba(37,99,235,.08)}
        .cv35-kicker,.cv35-answer-label,.cv35-section-label,.cv35-card-kicker{font-size:10px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#2563eb!important}.cv35-hero h2{font-size:27px;line-height:1.1;letter-spacing:-.035em;color:#0f172a!important;margin:0 0 8px}.cv35-hero p{font-size:13px;line-height:1.6;color:#52647a!important;font-weight:700;margin:0;max-width:900px}
        .cv35-usage{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:11px 13px;margin:0 0 12px}.cv35-usage strong{font-size:11px;color:#0f172a!important}.cv35-usage span{font-size:10px;color:#52647a!important;font-weight:800}.cv35-usage.high,.cv35-usage.critical{border-color:#fde68a;background:#fffbeb}.cv35-usage.reached{border-color:#fecaca;background:#fef2f2}
        .cv35-message{display:flex;align-items:flex-start;gap:12px;border-radius:16px;padding:14px 15px;margin-top:14px}.cv35-message-error{border:1px solid #fecaca;background:#fff7f7}.cv35-message-icon{display:grid;place-items:center;width:24px;height:24px;border-radius:999px;background:#fee2e2;color:#b91c1c;font-weight:950;flex:0 0 auto}.cv35-message strong{display:block;color:#7f1d1d!important;font-size:13px;margin-bottom:3px}.cv35-message p{margin:0;color:#7f1d1d!important;font-size:12px;line-height:1.5}
        .cv35-review-shell{border:1px solid #bfdbfe;background:linear-gradient(145deg,#fff,#f8fbff);border-radius:22px;padding:20px 21px;margin:18px 0 16px;box-shadow:0 16px 42px rgba(15,23,42,.06)}
        .cv35-question{border-left:4px solid #60a5fa;background:#f3f8ff;border-radius:12px;padding:12px 14px;margin-bottom:18px;color:#0f172a;font-size:13px;font-weight:800}.cv35-question small{display:block;color:#64748b;font-size:9px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px}.cv35-review-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.cv35-review-heading h2{font-size:24px;letter-spacing:-.035em;color:#0f172a!important;margin:7px 0 8px}.cv35-review-status{border:1px solid #bbf7d0;background:#ecfdf5;color:#047857;border-radius:999px;padding:7px 10px;font-size:10px;font-weight:900;white-space:nowrap}.cv35-assessment-copy{font-size:14px;line-height:1.7;color:#334155;font-weight:650;max-width:1100px}
        .cv35-section-label{margin:18px 0 9px}.cv35-evidence-card{min-height:126px;border:1px solid #dbeafe;background:#fff;border-radius:17px;padding:15px 16px;margin-bottom:10px;box-shadow:0 9px 24px rgba(15,23,42,.04)}.cv35-evidence-card:hover{border-color:#93c5fd;transform:translateY(-1px)}.cv35-evidence-part{font-size:14px;font-weight:950;color:#0f172a;margin-bottom:7px}.cv35-evidence-detail{font-size:12px;line-height:1.58;color:#52647a;font-weight:650}
        .cv35-action-card,.cv35-confidence-card{height:100%;min-height:165px;border:1px solid #dbeafe;background:#fff;border-radius:19px;padding:17px 18px;margin-top:10px}.cv35-action-copy{font-size:13px;line-height:1.65;color:#334155;font-weight:680;margin-top:10px}.cv35-confidence-top{display:flex;align-items:center;justify-content:space-between;color:#475569;font-size:11px;font-weight:900}.cv35-confidence-top strong{font-size:24px;color:#0f172a}.cv35-confidence-track{height:9px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin:13px 0 10px}.cv35-confidence-track div{height:100%;border-radius:999px;background:linear-gradient(90deg,#2563eb,#60a5fa)}.cv35-confidence-card.high .cv35-confidence-track div{background:linear-gradient(90deg,#059669,#34d399)}.cv35-confidence-card.low .cv35-confidence-track div{background:linear-gradient(90deg,#d97706,#fbbf24)}.cv35-confidence-label{font-size:15px;font-weight:950;color:#0f172a;margin-bottom:6px}.cv35-confidence-detail{font-size:11px;line-height:1.5;color:#64748b;font-weight:650}
        .cv35-mode-note{border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:11px 13px;margin-top:12px;color:#52647a;font-size:11px;font-weight:700}
        .cv36-history-turn{display:flex;gap:12px;border-bottom:1px solid #e2e8f0;padding:13px 2px}.cv36-history-turn:last-child{border-bottom:0}.cv36-history-number{display:grid;place-items:center;width:25px;height:25px;border-radius:999px;background:#eff6ff;color:#2563eb;font-size:10px;font-weight:950;flex:0 0 auto}.cv36-history-turn small{display:block;color:#64748b;font-size:9px;text-transform:uppercase;letter-spacing:.08em}.cv36-history-turn strong{display:block;color:#0f172a;font-size:12px;margin:3px 0 5px}.cv36-history-turn p{color:#52647a;font-size:11px;line-height:1.5;margin:0}.cv36-followup-note{border:1px solid #bfdbfe;background:#eff6ff;border-radius:14px;padding:11px 13px;margin:10px 0;color:#1e40af;font-size:11px;font-weight:800}
        @media(max-width:900px){.cv35-review-heading{display:block}.cv35-review-status{display:inline-block;margin-top:6px}.cv35-evidence-card{min-height:auto}}
        </style>
        <div class="cv35-hero"><div class="cv35-kicker">Engineering Copilot</div><h2>Ask Cadivor about this BOM</h2><p>Receive an evidence-backed assessment, prioritized engineering actions, and direct links into the workflows needed to close the risk.</p></div>
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
    pending_followup = st.session_state.pop("cv36_pending_followup", None)
    if pending_followup:
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

    question = st.text_area(
        "Engineering question",
        key=prompt_key,
        height=110,
        placeholder="Example: What should I review first before releasing this BOM?",
    )
    component_note = f" Current component focus: {selected_component}." if selected_component else ""
    st.caption("Cadivor uses the saved evidence in this analysis and identifies uncertainty when supporting data is incomplete." + component_note)
    can_submit = status.can_use and bool(str(question or "").strip())
    manual_submit = st.button(
        "Ask Engineering Copilot",
        type="primary",
        disabled=not can_submit,
        use_container_width=False,
    )
    submit_requested = bool(manual_submit or (auto_execute_followup and can_submit))
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
