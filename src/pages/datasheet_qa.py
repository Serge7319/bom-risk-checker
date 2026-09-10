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
    VISIBLE_FOLLOW_UPS,
    answer_datasheet_question,
    append_thread_turn,
    apply_datasheet_question_clear,
    build_datasheet_ai_client,
    claim_datasheet_question_submit,
    clear_datasheet_document,
    compact_datasheet_history,
    consume_datasheet_pending_question,
    document_fingerprint,
    extract_uploaded_datasheet,
    queue_datasheet_follow_up,
    resolve_datasheet_question,
    store_document_in_session,
)
from src.ui.cadivor_design_system import (
    cadivor_button_wrap,
    cadivor_button_wrap_end,
    inject_cadivor_design_system,
)


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _inject_datasheet_qa_styles() -> None:
    inject_cadivor_design_system()
    if st.session_state.get("_cadivor_datasheet_qa_styles_v5"):
        return
    st.session_state["_cadivor_datasheet_qa_styles_v5"] = True
    st.markdown(
        """
        <style id="cadivor-datasheet-qa-css-v5">
        .dq-workspace{
          max-width:min(1040px,100%);
          margin:0 auto 24px;
          padding:0 8px 8px;
        }
        .dq-hero{margin:0 0 10px}
        .dq-hero-eyebrow{
          margin:0 0 4px;
          font-size:11px;
          font-weight:800;
          letter-spacing:.08em;
          text-transform:uppercase;
          color:var(--cv64-text-muted,#64748B);
        }
        .dq-hero-title{
          margin:0;
          font-size:22px;
          font-weight:800;
          letter-spacing:-.02em;
          color:var(--cv64-text,#0F172A);
          line-height:1.25;
        }
        .dq-hero-sub{
          margin:6px 0 0;
          max-width:62ch;
          font-size:13px;
          line-height:1.5;
          color:var(--cv64-text-secondary,#475569);
        }
        .dq-docbar{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:12px;
          margin:0 0 10px;
          padding:10px 12px;
          border-radius:12px;
          border:1px solid var(--cv64-border,#E2E8F0);
          background:linear-gradient(180deg,#FFFFFF 0%,#F8FAFC 100%);
        }
        .dq-docbar-main{min-width:0;flex:1}
        .dq-docbar-name{
          margin:0;
          font-size:14px;
          font-weight:800;
          color:var(--cv64-text,#0F172A);
          white-space:nowrap;
          overflow:hidden;
          text-overflow:ellipsis;
        }
        .dq-docbar-meta{
          margin:4px 0 0;
          display:flex;
          flex-wrap:wrap;
          gap:6px;
          align-items:center;
        }
        .dq-pill{
          display:inline-flex;
          align-items:center;
          gap:4px;
          padding:2px 8px;
          border-radius:999px;
          border:1px solid #E2E8F0;
          background:#F8FAFC;
          color:#475569;
          font-size:11px;
          font-weight:700;
          line-height:1.4;
        }
        .dq-pill.is-private{
          border-color:#BFDBFE;
          background:#EFF6FF;
          color:#1D4ED8;
        }
        .dq-section-title{
          margin:4px 0 2px;
          font-size:15px;
          font-weight:800;
          color:var(--cv64-text,#0F172A);
        }
        .dq-section-sub{
          margin:0 0 10px;
          font-size:12px;
          line-height:1.45;
          color:var(--cv64-text-muted,#64748B);
        }        .dq-empty{
          margin:0 0 16px;
          padding:18px 16px;
          border-radius:14px;
          border:1px dashed #CBD5E1;
          background:#F8FAFC;
          text-align:left;
        }
        .dq-empty h3{
          margin:0 0 6px;
          font-size:15px;
          font-weight:800;
          color:#0F172A;
        }
        .dq-empty p{
          margin:0 0 10px;
          font-size:13px;
          line-height:1.5;
          color:#475569;
        }
        .dq-empty ul{
          margin:0;
          padding-left:18px;
          color:#334155;
          font-size:13px;
          line-height:1.55;
        }
        .dq-turn-user{
          margin:0 0 10px 12%;
          padding:12px 14px;
          border-radius:14px 14px 4px 14px;
          border:1px solid #E2E8F0;
          background:#F8FAFC;
        }
        .dq-turn-cadivor{
          margin:0 12% 14px 0;
          padding:14px 14px 12px;
          border-radius:14px 14px 14px 4px;
          border:1px solid #E2E8F0;
          background:#FFFFFF;
          box-shadow:0 1px 2px rgba(15,23,42,.04);
        }
        .dq-role{
          font-size:10px;
          font-weight:800;
          letter-spacing:.07em;
          text-transform:uppercase;
          color:#64748B;
        }
        .dq-q{
          margin:4px 0 0;
          font-size:14px;
          font-weight:750;
          color:#0F172A;
          line-height:1.45;
        }
        .dq-a{
          margin:6px 0 0;
          font-size:14px;
          color:#334155;
          line-height:1.55;
        }
        .dq-a.is-missing{color:#1D4ED8}
        .dq-evidence{
          display:flex;
          gap:10px;
          align-items:flex-start;
          margin:12px 0 0;
          padding:10px 12px;
          border-radius:10px;
          background:#EFF6FF;
          border:1px solid #BFDBFE;
        }
        .dq-evidence-page{
          flex:0 0 auto;
          padding:2px 8px;
          border-radius:999px;
          background:#DBEAFE;
          color:#1E40AF;
          font-size:11px;
          font-weight:800;
          line-height:1.4;
        }
        .dq-evidence-quote{
          margin:0;
          font-size:12px;
          line-height:1.45;
          color:#1E3A8A;
        }
        .dq-notice{
          margin:8px 0 0;
          padding:8px 10px;
          border-radius:8px;
          background:#FFF7ED;
          border:1px solid #FED7AA;
          color:#9A3412;
          font-size:12px;
          line-height:1.45;
        }
        .dq-suggest-label{
          margin:12px 0 8px;
          font-size:11px;
          font-weight:800;
          letter-spacing:.06em;
          text-transform:uppercase;
          color:#64748B;
        }
        .dq-composer{
          margin:8px 0 0;
          padding:14px;
          border-radius:14px;
          border:1px solid #E2E8F0;
          background:#FFFFFF;
          box-shadow:0 1px 2px rgba(15,23,42,.04);
        }
        .dq-composer-title{
          margin:0;
          font-size:14px;
          font-weight:800;
          color:#0F172A;
        }
        .dq-composer-hint{
          margin:4px 0 10px;
          font-size:12px;
          line-height:1.4;
          color:#64748B;
        }
        .dq-progress{
          margin:8px 0 0;
          padding-left:18px;
          color:#475569;
          font-size:13px;
          line-height:1.55;
        }
        .dq-progress li{margin:4px 0}
        section[data-testid="stMain"] .dq-workspace .stFormSubmitButton>button{
          min-width:148px!important;
          width:auto!important;
          max-width:220px!important;
        }
        section[data-testid="stMain"] .dq-workspace [class*="st-key-dq_suggest_"] button,
        section[data-testid="stMain"] .dq-workspace [class*="st-key-dq_more_"] button{
          min-height:32px!important;
          width:auto!important;
          max-width:100%!important;
          border-radius:999px!important;
          border:1px solid #BFDBFE!important;
          background:#F8FBFF!important;
          color:#1D4ED8!important;
          font-weight:700!important;
          font-size:12px!important;
          box-shadow:none!important;
          white-space:normal!important;
          text-align:left!important;
          padding:6px 12px!important;
        }
        section[data-testid="stMain"] .dq-workspace [data-testid="stHorizontalBlock"]{
          gap:.4rem .55rem!important;
          flex-wrap:wrap!important;
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
        elif result.get("error"):
            st.error(str(result.get("error")))
    except Exception:
        st.error("Cadivor could not answer from this datasheet right now. Please try again.")
    finally:
        st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_READY


def _render_follow_up_chips(
    suggestions: list[str],
    *,
    turn_index: int,
    fingerprint: str,
    disabled: bool,
) -> str | None:
    """Compact chip row; returns clicked suggestion text if any."""
    clicked: str | None = None
    if not suggestions:
        return None
    visible = suggestions[:VISIBLE_FOLLOW_UPS]
    overflow = suggestions[VISIBLE_FOLLOW_UPS:]
    st.markdown(
        '<div class="dq-suggest-label">Suggested follow-ups</div>',
        unsafe_allow_html=True,
    )
    # Wrap chips in short rows (responsive horizontal feel under Streamlit).
    for start in range(0, len(visible), 3):
        row = visible[start : start + 3]
        cols = st.columns(len(row))
        for col, suggestion in zip(cols, row):
            digest = hashlib.sha1(
                f"{fingerprint}:{turn_index}:{suggestion}".encode("utf-8")
            ).hexdigest()[:10]
            with col:
                if st.button(
                    suggestion,
                    key=f"dq_suggest_{digest}",
                    use_container_width=True,
                    disabled=disabled,
                ):
                    clicked = suggestion
    if overflow:
        with st.expander("More questions", expanded=False):
            for index, suggestion in enumerate(overflow):
                digest = hashlib.sha1(
                    f"{fingerprint}:{turn_index}:more:{suggestion}".encode("utf-8")
                ).hexdigest()[:10]
                if st.button(
                    suggestion,
                    key=f"dq_more_{digest}",
                    use_container_width=True,
                    disabled=disabled,
                ):
                    clicked = suggestion
    return clicked


def _render_thread_turn(
    turn: dict,
    *,
    turn_index: int,
    fingerprint: str,
    disabled: bool,
) -> str | None:
    """Render distinct You / Cadivor cards; return clicked suggestion if any."""
    st.markdown(
        '<div class="dq-turn-user">'
        '<div class="dq-role">You</div>'
        f'<div class="dq-q">{_esc(turn.get("question"))}</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    if turn.get("error") and not turn.get("ok"):
        st.error(str(turn.get("error")))
        return None

    answer = str(turn.get("answer") or "")
    answer_class = " is-missing" if answer == NOT_FOUND_ANSWER else ""
    notice = str(turn.get("notice") or "").strip()
    notice_html = (
        f'<div class="dq-notice">{_esc(notice)}</div>' if notice else ""
    )
    primary = turn.get("primary_evidence")
    evidence_html = ""
    if isinstance(primary, dict) and primary.get("citation") and primary.get("excerpt"):
        evidence_html = (
            '<div class="dq-evidence">'
            f'<span class="dq-evidence-page">{_esc(primary.get("citation"))}</span>'
            f'<p class="dq-evidence-quote">“{_esc(primary.get("excerpt"))}”</p>'
            "</div>"
        )
    st.markdown(
        '<div class="dq-turn-cadivor">'
        '<div class="dq-role">Cadivor</div>'
        f'<div class="dq-a{answer_class}">{_esc(answer)}</div>'
        f"{notice_html}{evidence_html}"
        "</div>",
        unsafe_allow_html=True,
    )
    evidence = list(turn.get("evidence") or [])
    extra = evidence[1:] if primary and evidence else evidence
    if extra:
        with st.expander(f"View supporting passages ({len(extra)})", expanded=False):
            for item in extra:
                page = item.get("citation") or f"Page {item.get('page')}"
                st.markdown(f"**{_esc(page)}**")
                st.caption(str(item.get("excerpt") or ""))
    suggestions = [
        str(item).strip()
        for item in list(turn.get("suggestions") or [])
        if str(item).strip()
    ]
    return _render_follow_up_chips(
        suggestions,
        turn_index=turn_index,
        fingerprint=fingerprint,
        disabled=disabled,
    )

def render_datasheet_qa_page() -> None:
    """Render the conversational Datasheet Q&A workspace."""
    _inject_datasheet_qa_styles()
    # Deferred composer clear must run before the text-area widget is created.
    preclear_question = apply_datasheet_question_clear(st.session_state)
    # Chip follow-ups are consumed here — never by mutating datasheet_qa_question
    # after the composer widget exists.
    queued_follow_up = consume_datasheet_pending_question(st.session_state)

    st.markdown('<div class="cv64-page-shell"><div class="dq-workspace">', unsafe_allow_html=True)
    st.markdown(
        '<div class="dq-hero">'
        '<p class="dq-hero-eyebrow">Datasheet Q&A</p>'
        '<h1 class="dq-hero-title">Ask Cadivor about your datasheet</h1>'
        '<p class="dq-hero-sub">'
        "Upload one text-searchable PDF, then continue a grounded engineering conversation "
        "with page evidence."
        "</p></div>",
        unsafe_allow_html=True,
    )

    document = st.session_state.get(DATASHEET_QA_DOC_KEY)
    ready_document = isinstance(document, dict) and bool(document.get("available"))

    if not ready_document:
        st.markdown(
            '<div class="dq-empty">'
            "<h3>Upload a datasheet to begin</h3>"
            "<p>"
            f"PDF only · up to {MAX_DATASHEET_BYTES // (1024 * 1024)} MB · "
            f"up to {MAX_DATASHEET_PAGES} pages · text-searchable pages required · "
            "session-private. Scanned image-only PDFs are not supported yet."
            "</p>"
            "<p>Example questions once a document is loaded:</p>"
            "<ul>"
            "<li>What are the absolute maximum ratings?</li>"
            "<li>What package and pinout does this device use?</li>"
            "<li>What is the recommended operating temperature range?</li>"
            "</ul></div>",
            unsafe_allow_html=True,
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
            else:
                st.rerun()
        elif isinstance(document, dict) and document.get("reason"):
            st.warning(str(document.get("reason")))
        if not ready_document:
            st.markdown("</div></div>", unsafe_allow_html=True)
            return

    fingerprint = document_fingerprint(document)
    st.session_state[DATASHEET_QA_ACTIVE_FINGERPRINT_KEY] = fingerprint
    page_count = int(document.get("page_count") or 0)
    filename = str(document.get("filename") or "Datasheet")
    page_label = f"{page_count} page{'s' if page_count != 1 else ''}"

    doc_left, doc_right = st.columns([5, 1], gap="small")
    with doc_left:
        st.markdown(
            f'<div class="dq-docbar"><div class="dq-docbar-main">'
            f'<p class="dq-docbar-name">{_esc(filename)}</p>'
            f'<div class="dq-docbar-meta">'
            f'<span class="dq-pill">{_esc(page_label)}</span>'
            f'<span class="dq-pill is-private">Session-private</span>'
            f"</div></div></div>",
            unsafe_allow_html=True,
        )
    with doc_right:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        cadivor_button_wrap("secondary")
        if st.button("Remove", key="datasheet_qa_remove", use_container_width=True):
            clear_datasheet_document(st.session_state)
            st.session_state[DATASHEET_QA_CLEAR_QUESTION_KEY] = True
            st.rerun()
        cadivor_button_wrap_end()

    status = str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or STATUS_READY)
    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    processing = status == STATUS_PROCESSING

    # Run a queued chip follow-up before the composer widget is constructed.
    if queued_follow_up and not processing:
        _run_datasheet_question(
            document=document,
            question=queued_follow_up,
            thread=thread,
        )
        st.rerun()

    st.markdown(
        '<p class="dq-section-title">Conversation</p>'
        '<p class="dq-section-sub">'
        "Answers are grounded only in retrieved pages from this datasheet."
        "</p>",
        unsafe_allow_html=True,
    )

    suggestion_clicked: str | None = None
    if not thread and not processing:
        st.markdown(
            '<div class="dq-empty">'
            "<h3>No questions yet</h3>"
            "<p>Ask Cadivor below to start a grounded conversation with page evidence.</p>"
            "</div>",
            unsafe_allow_html=True,
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
        st.markdown(
            '<div class="dq-composer">'
            '<p class="dq-composer-title">Working on your question</p>'
            '<ol class="dq-progress">'
            "<li><strong>Retrieving relevant pages</strong></li>"
            "<li><strong>Ask Cadivor is analyzing the datasheet</strong></li>"
            "<li>Answer appears in the conversation when ready</li>"
            "</ol></div>",
            unsafe_allow_html=True,
        )

    ask_hint = (
        "Continue this conversation about the active datasheet."
        if thread
        else "Ask about ratings, package, limits, or device identity."
    )
    st.markdown(
        f'<div class="dq-composer">'
        f'<p class="dq-composer-title">Ask Cadivor</p>'
        f'<p class="dq-composer-hint">{_esc(ask_hint)}</p>',
        unsafe_allow_html=True,
    )
    with st.form("datasheet_qa_form", clear_on_submit=False, border=False):
        question_form = st.text_area(
            "Question",
            key=DATASHEET_QA_QUESTION_WIDGET_KEY,
            placeholder="Example: What are the absolute maximum ratings?",
            height=88,
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
    st.markdown("</div>", unsafe_allow_html=True)

    if suggestion_clicked:
        # Queue only — never assign datasheet_qa_question after the widget exists.
        if queue_datasheet_follow_up(st.session_state, suggestion_clicked):
            st.rerun()
        else:
            st.info("Cadivor is still working on the previous question.")

    if asked:
        question = resolve_datasheet_question(
            preclear_question,
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
