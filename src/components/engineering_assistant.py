"""User-facing Engineering Assistant panel."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

from src.services.ai_entitlements import consume_ai_credits, get_ai_usage_status
from src.services.engineering_ai import EngineeringAI, EngineeringAIError

SUGGESTIONS = [
    "What should I review first in this BOM?",
    "Explain the highest component risks.",
    "Is this BOM ready for production release?",
    "Which components need alternative qualification?",
    "Summarize the supplier and lifecycle exposure.",
]


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
        st.info(f"You have used {status.percent_used}% of this month's AI allowance. Compare plans before your allowance is exhausted.")
    elif status.warning_level == "reached":
        st.warning("Your monthly AI allowance has been reached. Your saved engineering data is safe. Upgrade your plan to continue using the Engineering Assistant now.")
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
        <style id="cadivor-engineering-assistant-3501">
        .cv35-hero{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f6f9ff 62%,#eaf2ff);border-radius:24px;padding:22px;margin:2px 0 14px;box-shadow:0 18px 50px rgba(37,99,235,.08)}
        .cv35-kicker{font-size:10px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#2563eb!important;margin-bottom:8px}.cv35-hero h2{font-size:27px;line-height:1.1;letter-spacing:-.035em;color:#0f172a!important;margin:0 0 8px}.cv35-hero p{font-size:13px;line-height:1.6;color:#52647a!important;font-weight:700;margin:0;max-width:900px}
        .cv35-usage{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:11px 13px;margin:0 0 12px}.cv35-usage strong{font-size:11px;color:#0f172a!important}.cv35-usage span{font-size:10px;color:#52647a!important;font-weight:800}.cv35-usage.high,.cv35-usage.critical{border-color:#fde68a;background:#fffbeb}.cv35-usage.reached{border-color:#fecaca;background:#fef2f2}
        .cv35-conversation{border:1px solid #dbeafe;background:#fff;border-radius:22px;padding:20px 21px;margin-top:16px;box-shadow:0 14px 36px rgba(15,23,42,.055)}
        .cv35-question{border-left:4px solid #93c5fd;background:#f8fbff;border-radius:12px;padding:12px 14px;margin-bottom:14px;color:#334155;font-size:13px;font-weight:750}.cv35-question small{display:block;color:#64748b;font-size:9px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px}
        .cv35-answer-label{font-size:10px;font-weight:950;letter-spacing:.09em;text-transform:uppercase;color:#2563eb!important;margin:0 0 10px}
        .cv35-message{display:flex;align-items:flex-start;gap:12px;border-radius:16px;padding:14px 15px;margin-top:14px}.cv35-message-error{border:1px solid #fecaca;background:#fff7f7}.cv35-message-icon{display:grid;place-items:center;width:24px;height:24px;border-radius:999px;background:#fee2e2;color:#b91c1c;font-weight:950;flex:0 0 auto}.cv35-message strong{display:block;color:#7f1d1d!important;font-size:13px;margin-bottom:3px}.cv35-message p{margin:0;color:#7f1d1d!important;font-size:12px;line-height:1.5}
        .cv35-mode-note{border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:11px 13px;margin-top:11px;color:#52647a;font-size:11px;font-weight:700}
        </style>
        <div class="cv35-hero"><div class="cv35-kicker">Engineering Assistant</div><h2>Ask Cadivor about this BOM</h2><p>Receive recommendations grounded in the saved component, lifecycle, supplier, inventory, monitoring, replacement, and decision evidence for this analysis.</p></div>
        """,
        unsafe_allow_html=True,
    )
    _usage_banner(status)

    prompt_key = "cv35_question"
    if prompt_key not in st.session_state:
        st.session_state[prompt_key] = ""
    suggestion_cols = st.columns(3)
    for idx, suggestion in enumerate(SUGGESTIONS):
        if suggestion_cols[idx % 3].button(suggestion, key=f"cv35_suggestion_{idx}", use_container_width=True):
            st.session_state[prompt_key] = suggestion

    question = st.text_area(
        "Engineering question",
        key=prompt_key,
        height=110,
        placeholder="Example: What should I review first before releasing this BOM?",
    )
    component_note = f" Current component focus: {selected_component}." if selected_component else ""
    st.caption("Cadivor uses the saved evidence in this analysis and identifies uncertainty when supporting data is incomplete." + component_note)

    can_submit = status.can_use and bool(str(question or "").strip())
    if st.button("Ask Engineering Assistant", type="primary", disabled=not can_submit, use_container_width=False):
        api = EngineeringAI(
            api_key=_secret("OPENAI_API_KEY"),
            model=_secret("OPENAI_MODEL", "gpt-4.1-mini"),
            base_url=_secret("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        st.session_state.pop("cv35_last_error", None)
        with st.status("Cadivor is analyzing the saved engineering evidence...", expanded=False) as progress:
            try:
                response = api.ask(question=question, context=context)
                consume_ai_credits(st.session_state, current_user, action="question")
                st.session_state["cv35_last_answer"] = response.answer
                st.session_state["cv35_last_question"] = question
                st.session_state["cv35_provider_connected"] = api.configured
                st.session_state["cv35_configuration_state"] = api.configuration_state
                progress.update(label="Engineering review complete", state="complete")
            except EngineeringAIError as exc:
                st.session_state["cv35_last_error"] = exc
                progress.update(label="Cadivor could not complete the review", state="error")

    error_message = st.session_state.get("cv35_last_error")
    if isinstance(error_message, EngineeringAIError):
        _render_error(error_message)

    answer = st.session_state.get("cv35_last_answer")
    if answer:
        last_question = str(st.session_state.get("cv35_last_question") or "Engineering review")
        st.markdown('<div class="cv35-conversation">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="cv35-question"><small>Your question</small>{html.escape(last_question)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="cv35-answer-label">Cadivor recommendation</div>', unsafe_allow_html=True)
        st.markdown(answer)
        st.markdown('</div>', unsafe_allow_html=True)
        if not st.session_state.get("cv35_provider_connected", False):
            state = st.session_state.get("cv35_configuration_state", "missing")
            admin_note = "A placeholder key was detected." if state == "placeholder" else "The connected AI service has not been configured yet."
            st.markdown(
                f'<div class="cv35-mode-note">Cadivor provided a grounded advisory summary using the saved BOM evidence. {html.escape(admin_note)}</div>',
                unsafe_allow_html=True,
            )
