"""Authenticated Datasheet Q&A page — conversational Ask Cadivor thread."""
from __future__ import annotations

import html
import hashlib

import streamlit as st

from src.datasheet_comparison import MAX_DATASHEET_BYTES, MAX_DATASHEET_PAGES
from src.datasheet_qa import (
    DATASHEET_QA_ACTIVE_FINGERPRINT_KEY,
    DATASHEET_QA_CLEAR_QUESTION_KEY,
    DATASHEET_QA_DOC_KEY,
    DATASHEET_QA_PENDING_QUESTION_KEY,
    DATASHEET_QA_QUESTION_WIDGET_KEY,
    DATASHEET_QA_STATUS_KEY,
    DATASHEET_QA_THREAD_KEY,
    NOT_FOUND_ANSWER,
    STATUS_PROCESSING,
    STATUS_READY,
    answer_datasheet_question,
    append_thread_turn,
    apply_datasheet_question_clear,
    build_datasheet_ai_client,
    claim_datasheet_question_submit,
    clear_datasheet_document,
    compact_datasheet_history,
    document_fingerprint,
    extract_uploaded_datasheet,
    queue_datasheet_follow_up,
    resolve_datasheet_question,
    store_document_in_session,
)
from src.ui.cadivor_design_system import (
    cadivor_button_wrap,
    cadivor_button_wrap_end,
    cadivor_empty_state,
    cadivor_meta_row,
    cadivor_panel,
    cadivor_panel_end,
    cadivor_section_header,
    inject_cadivor_design_system,
    render_subsection_header,
)


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _inject_datasheet_qa_styles() -> None:
    inject_cadivor_design_system()
    if st.session_state.get("_cadivor_datasheet_qa_styles_v3"):
        return
    st.session_state["_cadivor_datasheet_qa_styles_v3"] = True
    st.markdown(
        """
        <style id="cadivor-datasheet-qa-css-v3">
        .dq-workspace{max-width:min(920px,var(--cv-canvas,1420px));margin:0 auto 28px;padding:0 4px}
        .dq-reading{max-width:var(--cv-reading-max,62ch);color:var(--cv64-text-secondary,#475569);font-size:13px;line-height:1.5;margin:0 0 16px}
        .dq-ask-hint{margin:0 0 10px;color:var(--cv64-text-muted,#64748B);font-size:12px;line-height:1.4}
        .dq-docbar{margin:0 0 14px;padding:12px 14px;border-radius:12px;border:1px solid var(--cv64-border,#E2E8F0);background:var(--cv64-surface-muted,#F8FAFC)}
        .dq-docbar-title{margin:0;font-size:14px;font-weight:800;color:var(--cv64-text,#0F172A)}
        .dq-docbar-meta{margin:4px 0 0;font-size:12px;color:var(--cv64-text-muted,#64748B);line-height:1.45}
        .dq-turn{margin:0 0 14px;padding:14px 14px 12px;border-radius:12px;border:1px solid var(--cv64-border,#EEF2F7);background:#fff}
        .dq-turn-label{font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--cv64-text-muted,#64748B)}
        .dq-turn-q{margin:4px 0 12px;font-size:14px;font-weight:750;color:var(--cv64-text,#0F172A);line-height:1.45}
        .dq-turn-a{margin:4px 0 0;font-size:14px;color:var(--cv64-text-secondary,#334155);line-height:1.55}
        .dq-turn-a.is-missing{color:var(--cv64-info,#1D4ED8)}
        .dq-primary-evidence{margin:10px 0 0;padding:10px 12px;border-radius:10px;background:var(--cv64-info-soft,#EFF6FF);border:1px solid #BFDBFE;color:#1E3A8A;font-size:12px;line-height:1.45}
        .dq-primary-evidence strong{display:block;margin-bottom:4px;font-size:11px;letter-spacing:.04em;text-transform:uppercase}
        .dq-sources{margin-top:10px;font-size:12px;font-weight:750;color:var(--cv64-info,#1D4ED8)}
        .dq-notice{margin:0 0 10px;padding:10px 12px;border-radius:10px;background:var(--cv64-warning-soft,#FFF7ED);border:1px solid var(--cv64-warning-border,#FED7AA);color:var(--cv64-warning-text,#9A3412);font-size:12px;line-height:1.45}
        .dq-progress{margin:8px 0 0;padding-left:18px;color:var(--cv64-text-secondary,#475569);font-size:13px;line-height:1.55}
        .dq-progress li{margin:4px 0}
        .dq-suggest-label{margin:12px 0 6px;font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--cv64-text-muted,#64748B)}
        section[data-testid="stMain"] .dq-workspace .stFormSubmitButton>button{
          min-width:148px!important;width:auto!important;max-width:200px!important
        }
        section[data-testid="stMain"] .dq-workspace [class*="st-key-dq_suggest_"] button{
          min-height:34px!important;border-radius:999px!important;border:1px solid #BFDBFE!important;
          background:#F8FBFF!important;color:#1D4ED8!important;font-weight:700!important;font-size:12px!important;
          box-shadow:none!important;justify-content:flex-start!important;text-align:left!important
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _run_datasheet_question(
    *,
    document: dict,
    question: str,
    thread: list,
) -> None:
    """Shared Ask Cadivor submit path for composer and suggestion chips."""
    st.session_state[DATASHEET_QA_PENDING_QUESTION_KEY] = question
    st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_PROCESSING
    try:
        history = compact_datasheet_history(thread)
        progress = st.status(
            "Ask Cadivor is working on your question…",
            expanded=True,
        )
        with progress:
            st.write("1. Retrieving relevant pages…")
            st.write("2. Ask Cadivor is analyzing the datasheet…")
            result = answer_datasheet_question(
                document,
                question,
                ai_client=build_datasheet_ai_client(),
                history=history,
            )
            st.write("3. Preparing your answer…")
        append_thread_turn(
            st.session_state,
            question=question,
            result=result,
            document=document,
        )
        if result.get("ok"):
            st.session_state[DATASHEET_QA_CLEAR_QUESTION_KEY] = True
            st.session_state.pop(DATASHEET_QA_PENDING_QUESTION_KEY, None)
        elif result.get("error"):
            st.error(str(result.get("error")))
    except Exception:
        st.error("Cadivor could not answer from this datasheet right now. Please try again.")
    finally:
        st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_READY


def _render_thread_turn(turn: dict, *, turn_index: int, fingerprint: str, disabled: bool) -> str | None:
    """Render one You/Cadivor turn; return clicked suggestion text if any."""
    clicked: str | None = None
    st.markdown('<div class="dq-turn">', unsafe_allow_html=True)
    st.markdown(
        '<div class="dq-turn-label">You</div>'
        f'<div class="dq-turn-q">{_esc(turn.get("question"))}</div>',
        unsafe_allow_html=True,
    )
    if turn.get("error") and not turn.get("ok"):
        st.error(str(turn.get("error")))
        st.markdown("</div>", unsafe_allow_html=True)
        return None
    notice = str(turn.get("notice") or "").strip()
    if notice:
        st.markdown(
            f'<div class="dq-notice">{_esc(notice)}</div>',
            unsafe_allow_html=True,
        )
    answer = str(turn.get("answer") or "")
    answer_class = " is-missing" if answer == NOT_FOUND_ANSWER else ""
    st.markdown(
        '<div class="dq-turn-label">Cadivor</div>'
        f'<div class="dq-turn-a{answer_class}">{_esc(answer)}</div>',
        unsafe_allow_html=True,
    )
    primary = turn.get("primary_evidence")
    if isinstance(primary, dict) and primary.get("citation") and primary.get("excerpt"):
        st.markdown(
            '<div class="dq-primary-evidence">'
            f"<strong>Evidence · {_esc(primary.get('citation'))}</strong>"
            f"“{_esc(primary.get('excerpt'))}”"
            "</div>",
            unsafe_allow_html=True,
        )
    citations = list(turn.get("citations") or [])
    if citations:
        st.markdown(
            '<div class="dq-sources">Page references: '
            + ", ".join(_esc(item) for item in citations)
            + "</div>",
            unsafe_allow_html=True,
        )
    evidence = list(turn.get("evidence") or [])
    extra = evidence[1:] if primary and evidence else evidence
    if extra:
        with st.expander(f"Supporting passages ({len(extra)})", expanded=False):
            for item in extra:
                page = item.get("citation") or f"Page {item.get('page')}"
                st.markdown(f"**{_esc(page)}**")
                st.markdown(
                    f'<pre style="white-space:pre-wrap;font-size:12px;line-height:1.45;'
                    f'margin:0 0 10px;padding:10px 12px;border-radius:10px;'
                    f'background:var(--cv64-surface-muted,#F8FAFC);'
                    f'border:1px solid var(--cv64-border,#E2E8F0);">'
                    f'{_esc(item.get("excerpt") or "")}</pre>',
                    unsafe_allow_html=True,
                )
    suggestions = [str(item).strip() for item in list(turn.get("suggestions") or []) if str(item).strip()]
    if suggestions:
        st.markdown(
            '<div class="dq-suggest-label">Suggested follow-ups</div>',
            unsafe_allow_html=True,
        )
        for index, suggestion in enumerate(suggestions):
            digest = hashlib.sha1(
                f"{fingerprint}:{turn_index}:{suggestion}".encode("utf-8")
            ).hexdigest()[:10]
            key = f"dq_suggest_{digest}"
            if st.button(
                suggestion,
                key=key,
                use_container_width=True,
                disabled=disabled,
            ):
                clicked = suggestion
    st.markdown("</div>", unsafe_allow_html=True)
    return clicked


def render_datasheet_qa_page() -> None:
    """Render the conversational Datasheet Q&A workspace."""
    _inject_datasheet_qa_styles()
    preclear_question = apply_datasheet_question_clear(st.session_state)

    st.markdown('<div class="cv64-page-shell"><div class="dq-workspace">', unsafe_allow_html=True)
    cadivor_section_header(
        "Ask Cadivor about your datasheet",
        eyebrow="Datasheet Q&A",
        description=(
            "Upload one text-searchable PDF, then continue an engineering conversation. "
            "Answers stay grounded in the uploaded document with page evidence."
        ),
        icon="file-text",
    )
    st.markdown(
        f'<p class="dq-reading">'
        f"Limits: {MAX_DATASHEET_BYTES // (1024 * 1024)} MB · "
        f"{MAX_DATASHEET_PAGES} pages · text-searchable PDFs only · session-private."
        f"</p>",
        unsafe_allow_html=True,
    )

    document = st.session_state.get(DATASHEET_QA_DOC_KEY)
    ready_document = isinstance(document, dict) and bool(document.get("available"))

    if not ready_document:
        cadivor_panel(
            "Upload datasheet",
            subtitle="PDF only · session-private · text-searchable pages required",
        )
        uploaded = st.file_uploader(
            "Upload datasheet PDF",
            type=["pdf"],
            key="datasheet_qa_uploader",
            help=(
                f"PDF only · up to {MAX_DATASHEET_BYTES // (1024 * 1024)} MB · "
                f"up to {MAX_DATASHEET_PAGES} pages · session-private"
            ),
            label_visibility="collapsed",
        )
        if uploaded is not None:
            payload = uploaded.getvalue()
            with st.status("Reading datasheet…", expanded=True):
                st.write("Checking the PDF and extracting searchable text…")
                extracted = extract_uploaded_datasheet(
                    payload, filename=str(uploaded.name or "")
                )
            store_document_in_session(st.session_state, extracted)
            document = extracted
            ready_document = bool(extracted.get("available"))
            if not ready_document:
                reason = str(extracted.get("reason") or "Could not read this PDF.")
                if extracted.get("scanned_unsupported"):
                    st.warning(reason)
                else:
                    st.error(reason)
        elif isinstance(document, dict) and document.get("reason"):
            st.warning(str(document.get("reason")))
        else:
            cadivor_empty_state(
                "No datasheet yet",
                "Upload a text-searchable datasheet PDF to begin. "
                "Scanned image-only PDFs are not supported yet.",
                icon="file-text",
            )
        cadivor_panel_end()
        if not ready_document:
            st.markdown("</div></div>", unsafe_allow_html=True)
            return

    fingerprint = document_fingerprint(document)
    st.session_state[DATASHEET_QA_ACTIVE_FINGERPRINT_KEY] = fingerprint
    page_count = int(document.get("page_count") or 0)
    filename = str(document.get("filename") or "Datasheet")
    short_id = fingerprint[:8] if fingerprint else "session"
    st.markdown(
        f'<div class="dq-docbar">'
        f'<p class="dq-docbar-title">{_esc(filename)}</p>'
        f'<p class="dq-docbar-meta">'
        f"Continuing conversation for this datasheet · "
        f"{page_count} page{'s' if page_count != 1 else ''} · "
        f"id {_esc(short_id)} · session-private"
        f"</p></div>",
        unsafe_allow_html=True,
    )
    cadivor_meta_row(
        [
            ("Document ready", "success"),
            (f"{page_count} page{'s' if page_count != 1 else ''}", "neutral"),
            ("Session-private", "neutral"),
        ]
    )
    cadivor_button_wrap("secondary")
    if st.button("Remove document", key="datasheet_qa_remove", use_container_width=False):
        clear_datasheet_document(st.session_state)
        st.session_state[DATASHEET_QA_CLEAR_QUESTION_KEY] = True
        st.rerun()
    cadivor_button_wrap_end()

    status = str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or STATUS_READY)
    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    processing = status == STATUS_PROCESSING

    render_subsection_header(
        "Conversation",
        description="Each answer is grounded only in retrieved pages from this datasheet.",
    )

    suggestion_clicked: str | None = None
    if not thread and not processing:
        cadivor_empty_state(
            "No questions yet",
            "Ask Cadivor a question below to start a grounded conversation with page evidence.",
            icon="message-circle",
        )
    else:
        for turn_index, turn in enumerate(thread):
            if not isinstance(turn, dict):
                continue
            clicked = _render_thread_turn(
                turn,
                turn_index=turn_index,
                fingerprint=fingerprint or "doc",
                disabled=processing,
            )
            if clicked:
                suggestion_clicked = clicked

    if processing:
        pending_q = str(
            st.session_state.get(DATASHEET_QA_PENDING_QUESTION_KEY) or ""
        ).strip()
        cadivor_panel("Working on your question")
        if pending_q:
            st.markdown(
                f'<div class="dq-turn-label">You</div>'
                f'<div class="dq-turn-q">{_esc(pending_q)}</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<ol class="dq-progress">'
            "<li><strong>Retrieving relevant pages</strong></li>"
            "<li><strong>Ask Cadivor is analyzing the datasheet</strong></li>"
            "<li>Answer appears in the conversation when ready</li>"
            "</ol>",
            unsafe_allow_html=True,
        )
        cadivor_panel_end()

    ask_hint = (
        "Continue this conversation about the active datasheet."
        if thread
        else "Ask a clear engineering question about ratings, package, limits, or device identity."
    )
    cadivor_panel("Ask Cadivor", subtitle=ask_hint)
    st.markdown(f'<p class="dq-ask-hint">{_esc(ask_hint)}</p>', unsafe_allow_html=True)
    with st.form("datasheet_qa_form", clear_on_submit=False, border=False):
        question_form = st.text_area(
            "Question",
            key=DATASHEET_QA_QUESTION_WIDGET_KEY,
            placeholder="Example: What is the absolute maximum supply voltage?",
            height=96,
            label_visibility="collapsed",
        )
        ask_cols = st.columns([1, 4])
        with ask_cols[0]:
            cadivor_button_wrap("primary")
            asked = st.form_submit_button(
                "Ask Cadivor",
                type="primary",
                use_container_width=False,
                disabled=processing,
            )
            cadivor_button_wrap_end()
    cadivor_panel_end()

    if suggestion_clicked:
        if queue_datasheet_follow_up(st.session_state, suggestion_clicked):
            _run_datasheet_question(
                document=document,
                question=suggestion_clicked,
                thread=thread,
            )
            if st.session_state.get(DATASHEET_QA_CLEAR_QUESTION_KEY):
                st.rerun()
        else:
            st.info("Cadivor is still working on the previous question.")

    if asked:
        question = resolve_datasheet_question(
            preclear_question,
            st.session_state.get(DATASHEET_QA_PENDING_QUESTION_KEY),
            st.session_state.get(DATASHEET_QA_QUESTION_WIDGET_KEY),
            question_form,
        )
        if not question:
            st.warning("Enter a question about this datasheet.")
        elif claim_datasheet_question_submit(st.session_state, question):
            _run_datasheet_question(
                document=document,
                question=question,
                thread=thread,
            )
            if st.session_state.get(DATASHEET_QA_CLEAR_QUESTION_KEY):
                st.rerun()

    st.markdown("</div></div>", unsafe_allow_html=True)
