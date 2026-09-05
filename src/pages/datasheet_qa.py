"""Authenticated Datasheet Q&A page — cited answers from an uploaded PDF."""
from __future__ import annotations

import html

import streamlit as st

from src.datasheet_comparison import MAX_DATASHEET_BYTES, MAX_DATASHEET_PAGES
from src.datasheet_qa import (
    DATASHEET_QA_CLEAR_QUESTION_KEY,
    DATASHEET_QA_DOC_KEY,
    DATASHEET_QA_QUESTION_WIDGET_KEY,
    DATASHEET_QA_STATUS_KEY,
    DATASHEET_QA_THREAD_KEY,
    NOT_FOUND_ANSWER,
    STATUS_PROCESSING,
    STATUS_READY,
    answer_datasheet_question,
    append_thread_turn,
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
    cadivor_section_header,
)


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _inject_datasheet_qa_styles() -> None:
    if st.session_state.get("_cadivor_datasheet_qa_styles"):
        return
    st.session_state["_cadivor_datasheet_qa_styles"] = True
    st.markdown(
        """
        <style id="cadivor-datasheet-qa-css">
        .dq-hero-note{margin:0 0 14px;padding:10px 14px;border:1px solid #DCE5F0;border-radius:12px;background:#F8FBFF;color:#334155;font-size:13px;line-height:1.45}
        .dq-doc-card{margin:0 0 16px;padding:16px 18px;border:1px solid #E2E8F0;border-radius:16px;background:#FFFFFF;box-shadow:0 10px 24px rgba(15,23,42,.04)}
        .dq-doc-card__title{font-size:15px;font-weight:850;color:#0F172A}
        .dq-doc-card__meta{margin-top:6px;color:#475569;font-size:13px;line-height:1.45}
        .dq-ask-card{margin:0 0 18px;padding:16px 18px 12px;border:1px solid #E2E8F0;border-radius:16px;background:#FFFFFF}
        .dq-thread-card{margin:0 0 12px;padding:14px 16px;border:1px solid #E2E8F0;border-radius:14px;background:#FFFFFF}
        .dq-thread-card__q{font-size:13px;font-weight:800;color:#0F172A;margin-bottom:8px}
        .dq-thread-card__a{font-size:13px;color:#334155;line-height:1.5}
        .dq-sources{margin-top:8px;font-size:12px;font-weight:750;color:#1D4ED8}
        .dq-empty{margin:8px 0 0;padding:18px;border:1px dashed #CBD5E1;border-radius:14px;background:#F8FAFC;color:#64748B;font-size:13px}
        section[data-testid="stMain"] .dq-ask-card .stFormSubmitButton>button{
          min-width:120px!important;width:auto!important;max-width:180px!important
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_datasheet_qa_page() -> None:
    """Render the Datasheet Q&A workspace."""
    _inject_datasheet_qa_styles()
    # Deferred clear so the question field resets after a successful answer
    # without fighting an already-mounted widget.
    if st.session_state.pop(DATASHEET_QA_CLEAR_QUESTION_KEY, False):
        st.session_state[DATASHEET_QA_QUESTION_WIDGET_KEY] = ""

    st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)
    cadivor_section_header(
        "Ask about an uploaded datasheet",
        eyebrow="Datasheet Q&A",
        description=(
            "Upload one text-searchable PDF, ask as many questions as you need, and review "
            "answers with page references. Files stay private to this session."
        ),
        icon="file-text",
    )
    st.markdown(
        '<div class="dq-hero-note">'
        f"Answers are grounded only in the uploaded datasheet and include page references when "
        f"evidence is found. Limits: {MAX_DATASHEET_BYTES // (1024 * 1024)} MB · "
        f"{MAX_DATASHEET_PAGES} pages · text-searchable PDFs only."
        "</div>",
        unsafe_allow_html=True,
    )

    document = st.session_state.get(DATASHEET_QA_DOC_KEY)
    ready_document = isinstance(document, dict) and bool(document.get("available"))

    if not ready_document:
        uploaded = st.file_uploader(
            "Upload datasheet PDF",
            type=["pdf"],
            key="datasheet_qa_uploader",
            help=(
                f"PDF only · up to {MAX_DATASHEET_BYTES // (1024 * 1024)} MB · "
                f"up to {MAX_DATASHEET_PAGES} pages · session-private"
            ),
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
            # Fall through into the ready workspace when extraction succeeds
            # (no post-upload rerun required).
        elif isinstance(document, dict) and document.get("reason"):
            st.warning(str(document.get("reason")))
        else:
            st.markdown(
                '<div class="dq-empty">'
                "Upload a text-searchable datasheet PDF to begin. Scanned image-only PDFs "
                "are not supported yet."
                "</div>",
                unsafe_allow_html=True,
            )
        if not ready_document:
            st.markdown("</div>", unsafe_allow_html=True)
            return

    # Document status card
    st.markdown(
        f"""
        <div class="dq-doc-card">
          <div class="dq-doc-card__title">{_esc(document.get("filename") or "Datasheet")}</div>
          <div class="dq-doc-card__meta">
            {int(document.get("page_count") or 0)} page(s) with searchable text · Ready · Session-private
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    remove_cols = st.columns([1, 3])
    with remove_cols[0]:
        cadivor_button_wrap("secondary")
        if st.button("Remove document", key="datasheet_qa_remove", use_container_width=False):
            clear_datasheet_document(st.session_state)
            st.session_state[DATASHEET_QA_CLEAR_QUESTION_KEY] = True
            st.rerun()
        cadivor_button_wrap_end()

    status = str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or STATUS_READY)
    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    ask_label = "Ask another question" if thread else "Ask about this datasheet"

    st.markdown('<div class="dq-ask-card">', unsafe_allow_html=True)
    st.markdown(f"**{ask_label}**")
    with st.form("datasheet_qa_form", clear_on_submit=False, border=False):
        question_form = st.text_area(
            "Question",
            key=DATASHEET_QA_QUESTION_WIDGET_KEY,
            placeholder="Example: What is the absolute maximum supply voltage?",
            height=90,
            label_visibility="collapsed",
        )
        ask_cols = st.columns([1, 3])
        with ask_cols[0]:
            cadivor_button_wrap("primary")
            asked = st.form_submit_button(
                "Ask",
                type="primary",
                use_container_width=False,
                disabled=status == STATUS_PROCESSING,
            )
            cadivor_button_wrap_end()
    st.markdown("</div>", unsafe_allow_html=True)

    if asked:
        question = resolve_datasheet_question(
            question_form,
            st.session_state.get(DATASHEET_QA_QUESTION_WIDGET_KEY),
        )
        if not question:
            st.warning("Enter a question about this datasheet.")
        elif claim_datasheet_question_submit(st.session_state, question):
            st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_PROCESSING
            try:
                history = compact_datasheet_history(thread)
                with st.status("Looking up page evidence…", expanded=True):
                    st.write("Finding relevant pages in the uploaded datasheet…")
                    result = answer_datasheet_question(
                        document,
                        question,
                        ai_client=build_datasheet_ai_client(),
                        history=history,
                    )
                append_thread_turn(st.session_state, question=question, result=result)
                if result.get("ok"):
                    st.session_state[DATASHEET_QA_CLEAR_QUESTION_KEY] = True
                elif result.get("error"):
                    st.error(str(result.get("error")))
            except Exception:
                st.error("Cadivor could not answer from this datasheet right now. Please try again.")
            finally:
                st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_READY
            # Same-run paint of the updated thread; clear the question on the next run.
            if st.session_state.get(DATASHEET_QA_CLEAR_QUESTION_KEY):
                st.rerun()

    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    if not thread:
        st.markdown(
            '<div class="dq-empty">Ask a question to see answers with page references from this datasheet.</div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.subheader("Conversation")
    # Chronological order: oldest first.
    for turn in thread:
        if not isinstance(turn, dict):
            continue
        st.markdown('<div class="dq-thread-card">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="dq-thread-card__q">Q: {_esc(turn.get("question"))}</div>',
            unsafe_allow_html=True,
        )
        if turn.get("error") and not turn.get("ok"):
            st.error(str(turn.get("error")))
            st.markdown("</div>", unsafe_allow_html=True)
            continue
        answer = str(turn.get("answer") or "")
        if answer == NOT_FOUND_ANSWER:
            st.info(NOT_FOUND_ANSWER)
        else:
            st.markdown(
                f'<div class="dq-thread-card__a">{_esc(answer)}</div>',
                unsafe_allow_html=True,
            )
        citations = list(turn.get("citations") or [])
        if citations:
            st.markdown(
                '<div class="dq-sources">Sources: '
                + ", ".join(_esc(item) for item in citations)
                + "</div>",
                unsafe_allow_html=True,
            )
        evidence = list(turn.get("evidence") or [])
        if evidence:
            with st.expander(f"Supporting excerpts ({len(evidence)})", expanded=False):
                for item in evidence:
                    page = item.get("citation") or f"Page {item.get('page')}"
                    st.markdown(f"**{_esc(page)}**")
                    st.code(str(item.get("excerpt") or ""), language=None)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
