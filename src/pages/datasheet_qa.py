"""Authenticated Datasheet Q&A page — Ask Cadivor with cited datasheet answers."""
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
        .dq-workspace{max-width:920px;margin:0 auto 28px;padding:0 4px}
        .dq-hero-note{margin:0 0 16px;padding:12px 14px;border:1px solid #DCE5F0;border-radius:12px;background:linear-gradient(180deg,#F8FBFF 0%,#F3F7FC 100%);color:#334155;font-size:13px;line-height:1.5}
        .dq-doc-card{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin:0 0 14px;padding:16px 18px;border:1px solid #E2E8F0;border-radius:16px;background:#FFFFFF;box-shadow:0 10px 24px rgba(15,23,42,.04)}
        .dq-doc-card__title{font-size:15px;font-weight:850;color:#0F172A;letter-spacing:-.01em}
        .dq-doc-card__meta{margin-top:6px;color:#475569;font-size:13px;line-height:1.45}
        .dq-doc-card__status{display:inline-flex;align-items:center;gap:6px;margin-top:10px;padding:4px 10px;border-radius:999px;background:#ECFDF5;color:#047857;font-size:12px;font-weight:750}
        .dq-doc-card__status i{width:7px;height:7px;border-radius:999px;background:#10B981}
        .dq-ask-card{margin:0 0 18px;padding:18px 18px 14px;border:1px solid #E2E8F0;border-radius:16px;background:#FFFFFF;box-shadow:0 10px 24px rgba(15,23,42,.04)}
        .dq-ask-card__label{margin:0 0 10px;font-size:14px;font-weight:850;color:#0F172A}
        .dq-ask-card__hint{margin:0 0 12px;color:#64748B;font-size:12px;line-height:1.4}
        .dq-thread{display:flex;flex-direction:column;gap:12px}
        .dq-thread-card{padding:16px 18px;border:1px solid #E2E8F0;border-radius:16px;background:#FFFFFF;box-shadow:0 8px 18px rgba(15,23,42,.03)}
        .dq-thread-card__q-label,.dq-thread-card__a-label{font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#64748B}
        .dq-thread-card__q{margin:4px 0 12px;font-size:14px;font-weight:750;color:#0F172A;line-height:1.45}
        .dq-thread-card__a{margin:4px 0 0;font-size:14px;color:#334155;line-height:1.55}
        .dq-thread-card__a.is-missing{color:#1D4ED8}
        .dq-sources{margin-top:12px;padding-top:10px;border-top:1px solid #EEF2F7;font-size:12px;font-weight:750;color:#1D4ED8}
        .dq-notice{margin:0 0 10px;padding:10px 12px;border-radius:10px;background:#FFF7ED;border:1px solid #FED7AA;color:#9A3412;font-size:12px;line-height:1.45}
        .dq-empty{margin:0;padding:20px 18px;border:1px dashed #CBD5E1;border-radius:14px;background:#F8FAFC;color:#64748B;font-size:13px;line-height:1.5}
        section[data-testid="stMain"] .dq-ask-card .stFormSubmitButton>button{
          min-width:132px!important;width:auto!important;max-width:180px!important
        }
        @media(max-width:720px){
          .dq-doc-card{flex-direction:column}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_datasheet_qa_page() -> None:
    """Render the Datasheet Q&A workspace."""
    _inject_datasheet_qa_styles()
    if st.session_state.pop(DATASHEET_QA_CLEAR_QUESTION_KEY, False):
        st.session_state[DATASHEET_QA_QUESTION_WIDGET_KEY] = ""

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
        '<div class="dq-hero-note">'
        "Ask Cadivor synthesizes a concise engineering answer from the relevant pages of "
        f"your upload. Limits: {MAX_DATASHEET_BYTES // (1024 * 1024)} MB · "
        f"{MAX_DATASHEET_PAGES} pages · text-searchable PDFs only · session-private."
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
            st.markdown("</div></div>", unsafe_allow_html=True)
            return

    page_count = int(document.get("page_count") or 0)
    st.markdown(
        f"""
        <div class="dq-doc-card">
          <div>
            <div class="dq-doc-card__title">{_esc(document.get("filename") or "Datasheet")}</div>
            <div class="dq-doc-card__meta">
              {page_count} page{"s" if page_count != 1 else ""} with searchable text · Session-private
            </div>
            <div class="dq-doc-card__status"><i></i>Document ready</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    remove_cols = st.columns([1, 4])
    with remove_cols[0]:
        cadivor_button_wrap("secondary")
        if st.button("Remove document", key="datasheet_qa_remove", use_container_width=False):
            clear_datasheet_document(st.session_state)
            st.session_state[DATASHEET_QA_CLEAR_QUESTION_KEY] = True
            st.rerun()
        cadivor_button_wrap_end()

    status = str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or STATUS_READY)
    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    ask_hint = (
        "Ask another question about this datasheet."
        if thread
        else "Ask a clear engineering question about ratings, package, limits, or device identity."
    )

    st.markdown('<div class="dq-ask-card">', unsafe_allow_html=True)
    st.markdown('<div class="dq-ask-card__label">Ask Cadivor</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="dq-ask-card__hint">{_esc(ask_hint)}</div>', unsafe_allow_html=True)
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
                with st.status("Ask Cadivor is reviewing the datasheet…", expanded=True):
                    st.write("Finding relevant pages and preparing a grounded answer…")
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
            if st.session_state.get(DATASHEET_QA_CLEAR_QUESTION_KEY):
                st.rerun()

    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    if not thread:
        st.markdown(
            '<div class="dq-empty">'
            "Ask Cadivor a question to see a grounded answer with page references."
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown("</div></div>", unsafe_allow_html=True)
        return

    st.markdown('<div class="dq-thread">', unsafe_allow_html=True)
    for turn in thread:
        if not isinstance(turn, dict):
            continue
        st.markdown('<div class="dq-thread-card">', unsafe_allow_html=True)
        st.markdown(
            '<div class="dq-thread-card__q-label">Question</div>'
            f'<div class="dq-thread-card__q">{_esc(turn.get("question"))}</div>',
            unsafe_allow_html=True,
        )
        if turn.get("error") and not turn.get("ok"):
            st.error(str(turn.get("error")))
            st.markdown("</div>", unsafe_allow_html=True)
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
            '<div class="dq-thread-card__a-label">Answer</div>'
            f'<div class="dq-thread-card__a{answer_class}">{_esc(answer)}</div>',
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
            with st.expander(f"Supporting passages ({len(evidence)})", expanded=False):
                for item in evidence:
                    page = item.get("citation") or f"Page {item.get('page')}"
                    st.markdown(f"**{_esc(page)}**")
                    st.code(str(item.get("excerpt") or ""), language=None)
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div></div></div>", unsafe_allow_html=True)
