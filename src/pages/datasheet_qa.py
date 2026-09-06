"""Authenticated Datasheet Q&A page — Ask Cadivor with cited datasheet answers."""
from __future__ import annotations

import html

import streamlit as st

from src.datasheet_comparison import MAX_DATASHEET_BYTES, MAX_DATASHEET_PAGES
from src.datasheet_qa import (
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
    extract_uploaded_datasheet,
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
    if st.session_state.get("_cadivor_datasheet_qa_styles_v2"):
        return
    st.session_state["_cadivor_datasheet_qa_styles_v2"] = True
    st.markdown(
        """
        <style id="cadivor-datasheet-qa-css-v2">
        .dq-workspace{max-width:min(920px,var(--cv-canvas,1420px));margin:0 auto 28px;padding:0 4px}
        .dq-reading{max-width:var(--cv-reading-max,62ch);color:var(--cv64-text-secondary,#475569);font-size:13px;line-height:1.5;margin:0 0 16px}
        .dq-ask-hint{margin:0 0 10px;color:var(--cv64-text-muted,#64748B);font-size:12px;line-height:1.4}
        .dq-turn-q{margin:4px 0 12px;font-size:14px;font-weight:750;color:var(--cv64-text,#0F172A);line-height:1.45}
        .dq-turn-a{margin:4px 0 0;font-size:14px;color:var(--cv64-text-secondary,#334155);line-height:1.55}
        .dq-turn-a.is-missing{color:var(--cv64-info,#1D4ED8)}
        .dq-turn-label{font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--cv64-text-muted,#64748B)}
        .dq-sources{margin-top:12px;padding-top:10px;border-top:1px solid var(--cv64-border,#EEF2F7);font-size:12px;font-weight:750;color:var(--cv64-info,#1D4ED8)}
        .dq-notice{margin:0 0 10px;padding:10px 12px;border-radius:10px;background:var(--cv64-warning-soft,#FFF7ED);border:1px solid var(--cv64-warning-border,#FED7AA);color:var(--cv64-warning-text,#9A3412);font-size:12px;line-height:1.45}
        .dq-progress{margin:8px 0 0;padding-left:18px;color:var(--cv64-text-secondary,#475569);font-size:13px;line-height:1.55}
        .dq-progress li{margin:4px 0}
        section[data-testid="stMain"] .dq-workspace .stFormSubmitButton>button{
          min-width:148px!important;width:auto!important;max-width:200px!important
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_datasheet_qa_page() -> None:
    """Render the Datasheet Q&A workspace."""
    _inject_datasheet_qa_styles()
    # Snapshot before deferred clear can wipe a same-run form submit.
    preclear_question = apply_datasheet_question_clear(st.session_state)

    st.markdown('<div class="cv64-page-shell"><div class="dq-workspace">', unsafe_allow_html=True)
    cadivor_section_header(
        "Ask Cadivor about your datasheet",
        eyebrow="Datasheet Q&A",
        description=(
            "Upload one text-searchable PDF, then ask sequential engineering questions. "
            "Answers stay grounded in the uploaded document and include page references."
        ),
        icon="file-text",
    )
    st.markdown(
        f'<p class="dq-reading">'
        f"Ask Cadivor synthesizes a concise engineering answer from the relevant pages of "
        f"your upload. Limits: {MAX_DATASHEET_BYTES // (1024 * 1024)} MB · "
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

    page_count = int(document.get("page_count") or 0)
    cadivor_panel(str(document.get("filename") or "Datasheet"))
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
        st.session_state.pop(DATASHEET_QA_PENDING_QUESTION_KEY, None)
        st.rerun()
    cadivor_button_wrap_end()
    cadivor_panel_end()

    status = str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or STATUS_READY)
    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    ask_hint = (
        "Ask another question about this datasheet."
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
                disabled=status == STATUS_PROCESSING,
            )
            cadivor_button_wrap_end()
    if status == STATUS_PROCESSING:
        pending_q = str(
            st.session_state.get(DATASHEET_QA_PENDING_QUESTION_KEY) or ""
        ).strip()
        cadivor_panel("Working on your question")
        if pending_q:
            st.markdown(
                f'<div class="dq-turn-label">Question</div>'
                f'<div class="dq-turn-q">{_esc(pending_q)}</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<ol class="dq-progress">'
            "<li><strong>Retrieving relevant pages</strong></li>"
            "<li><strong>Ask Cadivor is analyzing the datasheet</strong></li>"
            "<li>Answer card appears when ready</li>"
            "</ol>",
            unsafe_allow_html=True,
        )
        cadivor_panel_end()
    cadivor_panel_end()

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
                    st.write("3. Preparing your answer card…")
                append_thread_turn(st.session_state, question=question, result=result)
                if result.get("ok"):
                    st.session_state[DATASHEET_QA_CLEAR_QUESTION_KEY] = True
                    st.session_state.pop(DATASHEET_QA_PENDING_QUESTION_KEY, None)
                elif result.get("error"):
                    st.error(str(result.get("error")))
            except Exception:
                st.error("Cadivor could not answer from this datasheet right now. Please try again.")
            finally:
                st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_READY
            if st.session_state.get(DATASHEET_QA_CLEAR_QUESTION_KEY):
                st.rerun()

    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    if not thread:
        cadivor_empty_state(
            "No questions yet",
            "Ask Cadivor a question to see a grounded answer with page references.",
            icon="message-circle",
        )
        st.markdown("</div></div>", unsafe_allow_html=True)
        return

    render_subsection_header(
        "Conversation",
        description="Each answer is grounded only in retrieved pages from your upload.",
    )
    for turn in thread:
        if not isinstance(turn, dict):
            continue
        cadivor_panel()
        st.markdown(
            '<div class="dq-turn-label">Question</div>'
            f'<div class="dq-turn-q">{_esc(turn.get("question"))}</div>',
            unsafe_allow_html=True,
        )
        if turn.get("error") and not turn.get("ok"):
            st.error(str(turn.get("error")))
            cadivor_panel_end()
            continue
        notice = str(turn.get("notice") or "").strip()
        if notice:
            st.markdown(
                f'<div class="dq-notice">{_esc(notice)}</div>',
                unsafe_allow_html=True,
            )
        answer = str(turn.get("answer") or "")
        answer_class = " is-missing" if answer == NOT_FOUND_ANSWER else ""
        st.markdown(
            '<div class="dq-turn-label">Cadivor’s answer</div>'
            f'<div class="dq-turn-a{answer_class}">{_esc(answer)}</div>',
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
        if evidence:
            with st.expander(f"Supporting passages ({len(evidence)})", expanded=False):
                for item in evidence:
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
        cadivor_panel_end()
    st.markdown("</div></div>", unsafe_allow_html=True)
