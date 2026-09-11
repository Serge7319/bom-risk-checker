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
    clean_evidence_excerpt,
    clear_datasheet_document,
    compact_datasheet_history,
    consume_datasheet_pending_question,
    document_fingerprint,
    extract_uploaded_datasheet,
    format_datasheet_answer_blocks,
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


def _html(markup: str) -> None:
    """Render trusted local HTML without Markdown class sanitization."""
    st.html(markup)


def _inject_datasheet_qa_styles() -> None:
    inject_cadivor_design_system()
    # Re-inject every run so navigation/reruns cannot drop page-local CSS.
    st.markdown(
        """
        <style id="cadivor-datasheet-qa-css-v7">
        /* Narrow the conversation canvas without touching global shell CSS files. */
        section[data-testid="stMain"] [data-testid="stMainBlockContainer"] > div:has(.dq-marker){
          max-width:1120px!important;
          width:min(100%,1120px)!important;
          margin-left:auto!important;
          margin-right:auto!important;
        }
        .dq-marker{display:none!important}
        .dq-hero{margin:0 0 12px}
        .dq-kicker{
          margin:0 0 4px;font-size:11px;font-weight:800;letter-spacing:.08em;
          text-transform:uppercase;color:#64748B
        }
        .dq-title{
          margin:0;font-size:22px;font-weight:800;letter-spacing:-.02em;
          color:#0F172A;line-height:1.25
        }
        .dq-sub{
          margin:6px 0 0;max-width:62ch;font-size:13px;line-height:1.5;color:#475569
        }
        .dq-docbar{
          display:flex;align-items:center;gap:12px;margin:0 0 14px;padding:12px 14px;
          border:1px solid #E2E8F0;border-radius:14px;
          background:linear-gradient(180deg,#FFF 0%,#F8FAFC 100%)
        }
        .dq-doc-icon{
          flex:0 0 auto;width:36px;height:36px;border-radius:10px;background:#EFF6FF;
          color:#1D4ED8;display:flex;align-items:center;justify-content:center;
          font-size:16px;font-weight:800
        }
        .dq-doc-main{min-width:0;flex:1}
        .dq-doc-name{
          margin:0;font-size:14px;font-weight:800;color:#0F172A;
          white-space:nowrap;overflow:hidden;text-overflow:ellipsis
        }
        .dq-doc-meta{
          margin:6px 0 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center
        }
        .dq-chip{
          display:inline-flex!important;align-items:center!important;
          padding:3px 10px!important;border-radius:999px!important;
          border:1px solid #E2E8F0!important;background:#F8FAFC!important;color:#475569!important;
          font-size:11px!important;font-weight:700!important;line-height:1.35!important;
          white-space:nowrap!important;margin:0!important
        }
        .dq-chip.is-private{
          border-color:#BFDBFE!important;background:#EFF6FF!important;color:#1D4ED8!important
        }
        .dq-chip.is-page{
          border-color:#BFDBFE!important;background:#DBEAFE!important;color:#1E40AF!important
        }
        .dq-section-label{
          margin:0 0 4px;font-size:15px;font-weight:800;color:#0F172A
        }
        .dq-section-help{margin:0 0 12px;font-size:12px;line-height:1.45;color:#64748B}
        .dq-empty{
          margin:0 0 14px;padding:18px 16px;border-radius:14px;border:1px dashed #CBD5E1;
          background:#F8FAFC
        }
        .dq-empty h3{margin:0 0 6px;font-size:15px;font-weight:800;color:#0F172A}
        .dq-empty p{margin:0 0 8px;font-size:13px;line-height:1.5;color:#475569}
        .dq-empty ul{margin:0;padding-left:18px;color:#334155;font-size:13px;line-height:1.55}
        .dq-user{
          margin:0 0 8px 8%;padding:12px 14px;border-radius:14px 14px 4px 14px;
          border:1px solid #E2E8F0;background:#F8FAFC
        }
        .dq-assistant{
          margin:0 0 14px;padding:14px;border-radius:14px;border:1px solid #E2E8F0;
          background:#FFF;box-shadow:0 1px 2px rgba(15,23,42,.04)
        }
        .dq-role{
          font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:#64748B
        }
        .dq-q{margin:4px 0 0;font-size:14px;font-weight:750;color:#0F172A;line-height:1.45}
        .dq-a{margin:8px 0 0;font-size:14px;color:#334155;line-height:1.55}
        .dq-a.is-missing{color:#1D4ED8}
        .dq-a p{margin:0}
        .dq-a ul{margin:8px 0 0;padding-left:18px}
        .dq-a li{margin:4px 0}
        .dq-notice{
          margin:10px 0 0;padding:8px 10px;border-radius:8px;background:#FFF7ED;
          border:1px solid #FED7AA;color:#9A3412;font-size:12px;line-height:1.45
        }
        .dq-evidence-wrap{margin:12px 0 0;padding-top:10px;border-top:1px solid #EEF2F7}
        .dq-evidence-label{
          margin:0 0 8px;font-size:11px;font-weight:800;letter-spacing:.06em;
          text-transform:uppercase;color:#64748B
        }
        .dq-evidence-row{
          display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start
        }
        .dq-evidence-quote{
          margin:0;flex:1 1 220px;font-size:12px;line-height:1.45;color:#1E3A8A;
          background:#EFF6FF;border:1px solid #BFDBFE;border-radius:10px;padding:8px 10px
        }
        .dq-ask-next{
          margin:12px 0 0;padding-top:10px;border-top:1px solid #EEF2F7
        }
        .dq-ask-next-label{
          margin:0 0 8px;font-size:11px;font-weight:800;letter-spacing:.06em;
          text-transform:uppercase;color:#64748B
        }
        .dq-progress-card{
          margin:0 0 14px;padding:14px;border-radius:14px;border:1px solid #BFDBFE;
          background:#EFF6FF;color:#1E3A8A
        }
        .dq-progress-card strong{display:block;margin-bottom:4px;font-size:14px}
        .dq-progress-card p{margin:0;font-size:13px;line-height:1.45}
        .dq-composer{
          margin:8px 0 0;padding:14px;border-radius:14px;border:1px solid #E2E8F0;
          background:#FFF;box-shadow:0 1px 2px rgba(15,23,42,.04)
        }
        .dq-composer-title{margin:0;font-size:14px;font-weight:800;color:#0F172A}
        .dq-composer-hint{margin:4px 0 10px;font-size:12px;line-height:1.4;color:#64748B}
        section[data-testid="stMain"] [class*="st-key-dq_chip_"] button{
          min-height:32px!important;width:auto!important;max-width:100%!important;
          border-radius:999px!important;border:1px solid #BFDBFE!important;
          background:#F8FBFF!important;color:#1D4ED8!important;font-weight:700!important;
          font-size:12px!important;box-shadow:none!important;white-space:normal!important;
          text-align:left!important;padding:6px 12px!important;justify-content:flex-start!important
        }
        section[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has([class*="st-key-dq_chip_"]){
          gap:.45rem .55rem!important;flex-wrap:wrap!important
        }
        section[data-testid="stMain"] .stFormSubmitButton>button{
          min-width:148px!important;width:auto!important;max-width:220px!important
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _execute_datasheet_question(
    *,
    document: dict,
    question: str,
    thread: list,
) -> None:
    """Shared submit path for typed composer and suggestion chips."""
    st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_PROCESSING
    try:
        history = compact_datasheet_history(thread)
        progress = st.status(
            "Cadivor is reviewing the datasheet evidence…",
            expanded=True,
        )
        with progress:
            st.write("Retrieving relevant pages…")
            result = answer_datasheet_question(
                document,
                question,
                ai_client=build_datasheet_ai_client(),
                history=history,
            )
            st.write("Preparing your answer…")
            try:
                progress.update(
                    label="Answer ready",
                    state="complete",
                    expanded=False,
                )
            except Exception:
                # Status update is cosmetic; never block the answer turn.
                pass
        append_thread_turn(
            st.session_state,
            question=question,
            result=result,
            document=document,
        )
        if result.get("ok"):
            st.session_state[DATASHEET_QA_CLEAR_QUESTION_KEY] = True
            # Safe: composer widget has not been constructed yet on chip path.
            st.session_state[DATASHEET_QA_QUESTION_WIDGET_KEY] = ""
        elif result.get("error"):
            st.error(str(result.get("error")))
    except Exception:
        st.error("Cadivor could not answer from this datasheet right now. Please try again.")
    finally:
        st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_READY
        st.session_state.pop(DATASHEET_QA_PENDING_QUESTION_KEY, None)


def _chip_click(suggestion: str) -> None:
    """Streamlit on_click callback — runs before the script body."""
    queue_datasheet_follow_up(st.session_state, suggestion)


def _answer_html(answer: str) -> str:
    blocks = format_datasheet_answer_blocks(answer)
    if not blocks:
        return ""
    missing = " is-missing" if answer == NOT_FOUND_ANSWER else ""
    if len(blocks) == 1:
        return f'<div class="dq-a{missing}">{_esc(blocks[0])}</div>'
    lead, *rest = blocks
    items = "".join(f"<li>{_esc(block)}</li>" for block in rest)
    bullets = f"<ul>{items}</ul>" if items else ""
    return f'<div class="dq-a{missing}"><p>{_esc(lead)}</p>{bullets}</div>'


def _render_ask_next_chips(
    suggestions: list[str],
    *,
    turn_index: int,
    fingerprint: str,
    disabled: bool,
) -> None:
    if not suggestions:
        return
    visible = suggestions[:VISIBLE_FOLLOW_UPS]
    overflow = suggestions[VISIBLE_FOLLOW_UPS:]
    _html(
        '<div class="dq-ask-next">'
        '<div class="dq-ask-next-label">Ask next</div>'
        "</div>"
    )
    for start in range(0, len(visible), 3):
        row = visible[start : start + 3]
        cols = st.columns(len(row))
        for col, suggestion in zip(cols, row):
            digest = hashlib.sha1(
                f"{fingerprint}:{turn_index}:{suggestion}".encode("utf-8")
            ).hexdigest()[:12]
            with col:
                st.button(
                    suggestion,
                    key=f"dq_chip_{digest}",
                    use_container_width=True,
                    disabled=disabled,
                    on_click=_chip_click,
                    args=(suggestion,),
                )
    if overflow:
        with st.expander("More questions", expanded=False):
            for suggestion in overflow:
                digest = hashlib.sha1(
                    f"{fingerprint}:{turn_index}:more:{suggestion}".encode("utf-8")
                ).hexdigest()[:12]
                st.button(
                    suggestion,
                    key=f"dq_chip_more_{digest}",
                    use_container_width=True,
                    disabled=disabled,
                    on_click=_chip_click,
                    args=(suggestion,),
                )


def _render_thread_turn(
    turn: dict,
    *,
    turn_index: int,
    fingerprint: str,
    disabled: bool,
    show_follow_ups: bool,
) -> None:
    _html(
        '<div class="dq-user">'
        '<div class="dq-role">You</div>'
        f'<div class="dq-q">{_esc(turn.get("question"))}</div>'
        "</div>"
    )
    if turn.get("error") and not turn.get("ok"):
        st.error(str(turn.get("error")))
        return

    answer = str(turn.get("answer") or "")
    notice = str(turn.get("notice") or "").strip()
    notice_html = f'<div class="dq-notice">{_esc(notice)}</div>' if notice else ""

    citations = [str(item).strip() for item in list(turn.get("citations") or []) if str(item).strip()]
    primary = turn.get("primary_evidence") if isinstance(turn.get("primary_evidence"), dict) else None
    if primary and primary.get("citation") and primary.get("citation") not in citations:
        citations = [str(primary.get("citation")), *citations]

    # Explicit gaps so page labels never mash even if CSS fails.
    page_chips = " ".join(
        f'<span class="dq-chip is-page">{_esc(citation)}</span>' for citation in citations[:4]
    )
    quote = ""
    if primary and primary.get("excerpt"):
        quote = (
            f'<p class="dq-evidence-quote">“{_esc(clean_evidence_excerpt(str(primary.get("excerpt"))))}”</p>'
        )
    evidence_html = ""
    if page_chips or quote:
        evidence_html = (
            '<div class="dq-evidence-wrap">'
            '<div class="dq-evidence-label">Evidence</div>'
            f'<div class="dq-evidence-row">{page_chips}{quote}</div>'
            "</div>"
        )

    _html(
        '<div class="dq-assistant">'
        '<div class="dq-role">Cadivor</div>'
        f"{_answer_html(answer)}"
        f"{notice_html}"
        f"{evidence_html}"
        "</div>"
    )

    evidence = list(turn.get("evidence") or [])
    extra = evidence[1:] if primary and evidence else evidence
    if extra:
        with st.expander(f"View supporting passages ({len(extra)})", expanded=False):
            for item in extra:
                page = item.get("citation") or f"Page {item.get('page')}"
                st.markdown(f"**{_esc(page)}**")
                st.caption(clean_evidence_excerpt(str(item.get("excerpt") or ""), limit=280))

    if show_follow_ups:
        suggestions = [
            str(item).strip()
            for item in list(turn.get("suggestions") or [])
            if str(item).strip()
        ]
        _render_ask_next_chips(
            suggestions,
            turn_index=turn_index,
            fingerprint=fingerprint,
            disabled=disabled,
        )


def render_datasheet_qa_page() -> None:
    """Render the conversational Datasheet Q&A workspace."""
    _inject_datasheet_qa_styles()
    # Composer clear must run before the text-area widget is constructed.
    preclear_question = apply_datasheet_question_clear(st.session_state)

    document = st.session_state.get(DATASHEET_QA_DOC_KEY)
    ready_document = isinstance(document, dict) and bool(document.get("available"))

    # Chip on_click queues pending before this body runs. Execute once here,
    # before any composer widget exists — never mutate datasheet_qa_question after.
    if ready_document:
        pending_question = consume_datasheet_pending_question(st.session_state)
        if pending_question:
            thread_before = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
            _execute_datasheet_question(
                document=document,
                question=pending_question,
                thread=thread_before,
            )

    # Marker enables page-scoped max-width via :has(.dq-marker).
    _html('<div class="dq-marker dq-shell" aria-hidden="true"></div>')
    _html(
        '<div class="dq-hero">'
        '<p class="dq-kicker">Datasheet Q&A</p>'
        '<h1 class="dq-title">Ask Cadivor about your datasheet</h1>'
        '<p class="dq-sub">'
        "Upload one text-searchable PDF, then continue a grounded engineering conversation "
        "with page evidence."
        "</p></div>"
    )

    document = st.session_state.get(DATASHEET_QA_DOC_KEY)
    ready_document = isinstance(document, dict) and bool(document.get("available"))

    if not ready_document:
        _html(
            '<div class="dq-empty">'
            "<h3>Upload a datasheet to begin</h3>"
            "<p>"
            f"PDF only · up to {MAX_DATASHEET_BYTES // (1024 * 1024)} MB · "
            f"up to {MAX_DATASHEET_PAGES} pages · text-searchable pages required · "
            "private session. Scanned image-only PDFs are not supported yet."
            "</p>"
            "<p>Example questions once a document is loaded:</p>"
            "<ul>"
            "<li>What are the absolute maximum ratings?</li>"
            "<li>What package and pinout does this device use?</li>"
            "<li>What is the recommended operating temperature range?</li>"
            "</ul></div>"
        )
        uploaded = st.file_uploader(
            "Upload datasheet PDF",
            type=["pdf"],
            key="datasheet_qa_uploader",
            help=(
                f"PDF only · up to {MAX_DATASHEET_BYTES // (1024 * 1024)} MB · "
                f"up to {MAX_DATASHEET_PAGES} pages · private session"
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
            if extracted.get("available"):
                st.rerun()
            reason = str(extracted.get("reason") or "Could not read this PDF.")
            if extracted.get("scanned_unsupported"):
                st.warning(reason)
            else:
                st.error(reason)
        elif isinstance(document, dict) and document.get("reason"):
            st.warning(str(document.get("reason")))
        return

    fingerprint = document_fingerprint(document)
    st.session_state[DATASHEET_QA_ACTIVE_FINGERPRINT_KEY] = fingerprint
    page_count = int(document.get("page_count") or 0)
    filename = str(document.get("filename") or "Datasheet")
    page_label = f"{page_count} page{'s' if page_count != 1 else ''}"

    doc_cols = st.columns([6.2, 1.1], gap="small")
    with doc_cols[0]:
        _html(
            '<div class="dq-docbar">'
            '<div class="dq-doc-icon" aria-hidden="true">PDF</div>'
            '<div class="dq-doc-main">'
            f'<p class="dq-doc-name">{_esc(filename)}</p>'
            '<div class="dq-doc-meta">'
            f'<span class="dq-chip">{_esc(page_label)}</span>'
            " "
            '<span class="dq-chip is-private">Private session</span>'
            "</div></div></div>"
        )
    with doc_cols[1]:
        cadivor_button_wrap("secondary")
        if st.button("Remove", key="datasheet_qa_remove", use_container_width=True):
            clear_datasheet_document(st.session_state)
            st.session_state[DATASHEET_QA_CLEAR_QUESTION_KEY] = True
            st.rerun()
        cadivor_button_wrap_end()

    status = str(st.session_state.get(DATASHEET_QA_STATUS_KEY) or STATUS_READY)
    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    processing = status == STATUS_PROCESSING
    pending_display = str(st.session_state.get(DATASHEET_QA_PENDING_QUESTION_KEY) or "").strip()

    _html(
        '<p class="dq-section-label">Conversation</p>'
        '<p class="dq-section-help">'
        "Answers are grounded only in retrieved pages from this datasheet."
        "</p>"
    )

    if not thread and not processing:
        _html(
            '<div class="dq-empty">'
            "<h3>No questions yet</h3>"
            "<p>Ask Cadivor below, or use a suggested follow-up after your first answer.</p>"
            "</div>"
        )
    else:
        last_index = len(thread) - 1
        for turn_index, turn in enumerate(thread):
            if not isinstance(turn, dict):
                continue
            _render_thread_turn(
                turn,
                turn_index=turn_index,
                fingerprint=fingerprint or "doc",
                disabled=processing,
                show_follow_ups=(turn_index == last_index and not processing),
            )

    if processing or pending_display:
        _html(
            '<div class="dq-progress-card">'
            "<strong>Cadivor is reviewing the datasheet evidence…</strong>"
            "<p>Your answer will appear in this conversation when ready.</p>"
            "</div>"
        )

    ask_hint = (
        "Continue this conversation about the active datasheet."
        if thread
        else "Ask about ratings, package, limits, or device identity."
    )
    _html(
        '<div class="dq-composer">'
        '<p class="dq-composer-title">Ask Cadivor</p>'
        f'<p class="dq-composer-hint">{_esc(ask_hint)}</p>'
        "</div>"
    )
    with st.form("datasheet_qa_form", clear_on_submit=False, border=False):
        question_form = st.text_area(
            "Question",
            key=DATASHEET_QA_QUESTION_WIDGET_KEY,
            placeholder="Example: What are the absolute maximum ratings?",
            height=84,
            label_visibility="collapsed",
            disabled=processing,
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

    if asked and not processing:
        question = resolve_datasheet_question(
            preclear_question,
            st.session_state.get(DATASHEET_QA_QUESTION_WIDGET_KEY),
            question_form,
        )
        if not question:
            st.warning("Enter a question about this datasheet.")
        elif claim_datasheet_question_submit(st.session_state, question):
            # Typed path: widgets already exist, so queue + rerun to execute
            # on the next run before the composer is constructed again.
            st.session_state[DATASHEET_QA_PENDING_QUESTION_KEY] = question
            st.session_state[DATASHEET_QA_STATUS_KEY] = STATUS_PROCESSING
            st.rerun()
