"""Authenticated Datasheet Q&A page — cited answers from an uploaded PDF."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

from src.datasheet_comparison import MAX_DATASHEET_BYTES, MAX_DATASHEET_PAGES
from src.datasheet_qa import (
    DATASHEET_QA_DOC_KEY,
    DATASHEET_QA_STATUS_KEY,
    DATASHEET_QA_THREAD_KEY,
    STATUS_PROCESSING,
    STATUS_READY,
    answer_datasheet_question,
    claim_datasheet_question_submit,
    clear_datasheet_document,
    extract_uploaded_datasheet,
    store_document_in_session,
    append_thread_turn,
)
from src.ui.cadivor_design_system import cadivor_section_header


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def render_datasheet_qa_page() -> None:
    """Render the Datasheet Q&A workspace."""
    st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)
    cadivor_section_header(
        "Ask engineering questions against an uploaded datasheet",
        eyebrow="Datasheet Q&A",
        description=(
            f"Upload a text-based PDF (max {MAX_DATASHEET_BYTES // (1024 * 1024)} MB, "
            f"{MAX_DATASHEET_PAGES} pages). Cadivor answers only from retrieved page evidence "
            "and cites supporting pages. Scanned/OCR-only PDFs are not supported yet."
        ),
        icon="file-text",
    )

    document = st.session_state.get(DATASHEET_QA_DOC_KEY)
    if not isinstance(document, dict) or not document.get("available"):
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
            extracted = extract_uploaded_datasheet(payload, filename=str(uploaded.name or ""))
            store_document_in_session(st.session_state, extracted)
            document = extracted
            if not extracted.get("available"):
                st.error(str(extracted.get("reason") or "Could not read this PDF."))
            else:
                st.success(
                    f"Loaded {_esc(extracted.get('filename'))} · "
                    f"{extracted.get('page_count')} page(s) with extractable text."
                )
                st.rerun()
        elif isinstance(document, dict) and document.get("reason"):
            st.warning(str(document.get("reason")))
        else:
            st.info("Upload a text-based datasheet PDF to begin.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    meta_cols = st.columns([3, 1])
    with meta_cols[0]:
        st.markdown(
            f"**Document:** {_esc(document.get('filename'))} · "
            f"{int(document.get('page_count') or 0)} page(s) · session-private"
        )
        st.caption("Uploaded files stay in this browser session only. They are not shared with other users.")
    with meta_cols[1]:
        if st.button("Remove document", use_container_width=True, key="datasheet_qa_remove"):
            clear_datasheet_document(st.session_state)
            st.rerun()

    status = str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or STATUS_READY)
    if status == STATUS_PROCESSING:
        st.info("Processing your question…")

    with st.form("datasheet_qa_form", clear_on_submit=False, border=False):
        question = st.text_area(
            "Engineering question",
            key="datasheet_qa_question",
            placeholder="Example: What is the absolute maximum supply voltage?",
            height=90,
        )
        asked = st.form_submit_button("Ask datasheet →", type="primary", use_container_width=True)

    if asked:
        if claim_datasheet_question_submit(st.session_state, question):
            st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_PROCESSING
            ai_client = None
            try:
                from src.secrets import get_secret
                from src.services.engineering_ai import EngineeringAI

                ai_client = EngineeringAI(
                    api_key=str(get_secret("OPENAI_API_KEY", default="") or ""),
                    model=str(get_secret("OPENAI_MODEL", default="gpt-4.1-mini") or "gpt-4.1-mini"),
                    base_url=str(
                        get_secret("OPENAI_BASE_URL", default="https://api.openai.com/v1")
                        or "https://api.openai.com/v1"
                    ),
                )
            except Exception:
                ai_client = None
            with st.spinner("Retrieving page evidence and drafting a cited answer…"):
                result = answer_datasheet_question(
                    document,
                    question,
                    ai_client=ai_client,
                )
            append_thread_turn(st.session_state, question=question, result=result)
            st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_READY
            if not result.get("ok"):
                st.error(str(result.get("error") or "Question failed. Try again."))
            st.rerun()

    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    if not thread:
        st.caption("Ask a question to see cited answers from this datasheet.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.subheader("Answers")
    for index, turn in enumerate(reversed(thread)):
        if not isinstance(turn, dict):
            continue
        st.markdown(f"**Q:** {_esc(turn.get('question'))}")
        if turn.get("error") and not turn.get("ok"):
            st.error(str(turn.get("error")))
            continue
        st.markdown(f"**A:** {_esc(turn.get('answer'))}")
        citations = list(turn.get("citations") or [])
        if citations:
            st.caption("Citations: " + ", ".join(_esc(item) for item in citations))
        evidence = list(turn.get("evidence") or [])
        if evidence:
            with st.expander(f"Evidence excerpts ({len(evidence)})", expanded=False):
                for item in evidence:
                    page = item.get("citation") or f"Page {item.get('page')}"
                    st.markdown(f"**{_esc(page)}**")
                    st.code(str(item.get("excerpt") or ""), language=None)
        if index < len(thread) - 1:
            st.divider()

    st.markdown("</div>", unsafe_allow_html=True)
