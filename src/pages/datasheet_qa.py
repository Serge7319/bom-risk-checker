"""Authenticated Datasheet Q&A page. Not the saved-BOM assistant."""
from __future__ import annotations

import html
import hashlib

import streamlit as st

from src.datasheet_comparison import MAX_DATASHEET_BYTES, MAX_DATASHEET_PAGES
from src.datasheet_qa import (
    DATASHEET_QA_ACTIVE_FINGERPRINT_KEY,
    DATASHEET_QA_CLEAR_QUESTION_KEY,
    DATASHEET_QA_DOC_KEY,
    DATASHEET_QA_EMPTY_ASK_KEY,
    DATASHEET_QA_FOLLOW_UP_WIDGET_KEY,
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
        <style id="cadivor-datasheet-qa-css-v7" data-cadivor-layout-style="true">
        /* Keep the datasheet workspace the same width as Cadivor Home. */
        section[data-testid="stMain"] [data-testid="stMainBlockContainer"] > div:has(.dq-marker){
          max-width:1440px!important;
          width:min(100%,1440px)!important;
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
        .dq-breadcrumb{margin:0 0 8px;color:#8291a7;font-size:11px;font-weight:700}
        .st-key-approved_datasheet_workspace .dq-title{font-size:28px;font-weight:700;letter-spacing:-.025em;line-height:1.2}
        .st-key-approved_datasheet_workspace .dq-sub{max-width:none;font-size:13px;color:#71829b}
        .st-key-approved_datasheet_workspace .dq-hero{margin:0 0 18px}
        .dq-answer-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
        .dq-answer-badge{display:inline-flex;align-items:center;padding:4px 9px;border-radius:999px;background:#eef5ff;color:#2865ed;font-size:10px;font-weight:800;letter-spacing:.03em}
        .dq-citation-count{color:#8795a8;font-size:10px;font-weight:650}
        .dq-question-reference{margin:0 0 12px;color:#435875;font-size:12px;line-height:1.45}
        .dq-evidence-wrap{margin-top:14px}
        .dq-evidence-label{font-size:10px}
        .dq-evidence-row{align-items:stretch}
        .dq-evidence-quote{flex-basis:100%;background:#f7faff;color:#334d70}
        .st-key-approved_datasheet_workspace .dq-assistant{padding:16px;border-radius:12px;background:#f9fbff;box-shadow:none}
        .dq-chip{font-size:10px!important;padding:3px 8px!important}
        .dq-ask-next{margin:14px 0 12px;padding:0;border:0}
        .dq-ask-next-label{margin:0 0 8px;font-size:9px;letter-spacing:.04em}
        .st-key-approved_datasheet_workspace .dq-empty{border-style:solid;background:#fff}
        .cv-dq-page-preview{display:block;width:100%;max-height:460px;object-fit:contain;background:#fff}
        .cv-dq-page-preview-frame{display:flex;align-items:center;justify-content:center;min-height:420px;padding:16px;background:#f5f8fc;border:1px solid #e3eaf3;border-radius:10px;overflow:hidden}
        .cv-dq-page-preview-frame img{width:auto;max-width:100%;max-height:460px;object-fit:contain;box-shadow:0 1px 4px rgba(15,23,42,.12)}
        .cv-dq-page-fallback{min-height:420px;padding:24px;background:#fff;color:#425874;white-space:pre-wrap;font-size:12px;line-height:1.55}
        .cv-dq-doc-link{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:0 14px;border:1px solid #d6e0ee;border-radius:9px;background:#fff;color:#344a68!important;font-size:12px;font-weight:700;text-decoration:none!important;white-space:nowrap}
        .cv-dq-doc-link:hover{border-color:#9ab6eb;background:#f8fbff}
        .cv-dq-source-nav{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:12px}
        .cv-dq-source-nav span{color:#2463e8;font-size:11px}
        .st-key-approved_datasheet_change_document button{min-height:40px!important;height:40px!important;border:1px solid #d6e0ee!important;border-radius:9px!important;background:#fff!important;color:#344a68!important;font-size:11px!important;font-weight:700!important;box-shadow:none!important}
        .st-key-approved_datasheet_previous_page,.st-key-approved_datasheet_next_page{display:flex!important;min-width:0!important}
        .st-key-approved_datasheet_previous_page button,.st-key-approved_datasheet_next_page button{box-sizing:border-box!important;min-width:0!important;min-height:34px!important;height:34px!important;padding:0 9px!important;border:1px solid #d6e0ee!important;border-radius:8px!important;background:#f8fbff!important;color:#2463e8!important;font-size:10px!important;font-weight:700!important;white-space:nowrap!important;box-shadow:none!important}
        .st-key-approved_datasheet_previous_page button *, .st-key-approved_datasheet_next_page button *{color:#2463e8!important;white-space:nowrap!important}
        .st-key-approved_datasheet_previous_page button:disabled,.st-key-approved_datasheet_next_page button:disabled{background:#f8fafc!important;color:#94a3b8!important;opacity:1!important}
        .st-key-approved_datasheet_previous_page button:disabled *,.st-key-approved_datasheet_next_page button:disabled *{color:#94a3b8!important}
        .st-key-approved_datasheet_next_page{justify-content:flex-start!important}
        .st-key-approved_datasheet_workspace{box-sizing:border-box!important;width:100%!important;max-width:1440px!important;margin:0 auto!important}
        .st-key-approved_datasheet_workspace>[data-testid="stVerticalBlock"]{gap:14px!important}
        .st-key-approved_datasheet_upload_card{box-sizing:border-box!important;width:100%!important;margin:0 0 14px!important;padding:20px 22px!important;border:1px solid #dfe7f1!important;border-radius:13px!important;background:#fff!important}
        .cv-dq-upload-heading{display:flex;align-items:center;gap:14px;margin:0 0 16px}
        .cv-dq-upload-heading p{margin:0 0 4px;color:#7e8da2;font-size:9px;font-weight:800;letter-spacing:.06em}
        .cv-dq-upload-heading h2{margin:0 0 4px;color:#172942;font-size:17px;font-weight:740}
        .cv-dq-upload-heading span:not(.cv-dq-document-icon){color:#75849a;font-size:11px}
        .cv-dq-document{min-height:66px;padding:10px 14px!important;border-radius:12px!important;background:#fff!important}
        .cv-dq-document-icon{flex-basis:44px!important;width:44px!important;height:44px!important;border-radius:10px!important;background:#eff5ff!important;color:#2865ed!important}
        .cv-dq-document-icon svg{width:22px;height:22px}
        .cv-dq-document-copy small{display:block;margin-bottom:3px;color:#8291a7;font-size:8px;font-weight:800;letter-spacing:.06em}
        .cv-dq-document-copy strong{font-size:12px!important}
        .cv-dq-document-copy span{font-size:10px!important}
        .cv-dq-private{padding:6px 10px!important;font-size:9px!important}
        .cv-dq-doc-link.is-disabled{opacity:.55;cursor:not-allowed}
        .cv-dq-picker-label{margin:0 0 8px;color:#5f718b;font-size:11px}
        .cv-dq-field-label{margin:8px 0 6px;color:#7d8ca1;font-size:9px;font-weight:800;letter-spacing:.05em}
        .st-key-approved_datasheet_question_panel,.st-key-approved_datasheet_source_panel{box-sizing:border-box!important;width:100%!important;min-width:0!important;min-height:610px!important;margin:0!important;padding:20px 21px 18px!important;border:1px solid #dfe7f1!important;border-radius:13px!important;background:#fff!important}
        .st-key-approved_datasheet_question_panel>[data-testid="stVerticalBlock"],.st-key-approved_datasheet_source_panel>[data-testid="stVerticalBlock"]{gap:.45rem!important}
        .cv-dq-question-head{margin:0 0 14px!important}
        .cv-dq-question-head h2{margin:0 0 5px!important;font-size:16px!important;font-weight:700!important}
        .cv-dq-question-head p{font-size:10px!important}
        .st-key-approved_datasheet_question_panel [data-testid="stTextArea"] textarea{min-height:64px!important;height:64px!important;padding:11px 13px!important;border:1px solid #d6e0ee!important;border-radius:9px!important;background:#fff!important;font-size:11px!important}
        .st-key-approved_datasheet_question_panel [data-testid="stTextArea"] textarea::placeholder{color:#8a98aa!important;opacity:1!important}
        .st-key-approved_datasheet_question_panel .st-key-datasheet_qa_follow_up [data-baseweb="input"]{min-height:40px!important;border:1px solid #d6e0ee!important;border-radius:9px!important;background:#fff!important}
        .st-key-approved_datasheet_question_panel .st-key-datasheet_qa_follow_up input{height:38px!important;color:#344a68!important;font-size:11px!important}
        .st-key-approved_datasheet_question_panel .st-key-datasheet_qa_follow_up input::placeholder{color:#8a98aa!important;opacity:1!important}
        .st-key-approved_datasheet_question_panel [data-testid="stWidgetLabel"]{display:none!important}
        .st-key-approved_datasheet_question_panel .st-key-approved_datasheet_ask{box-sizing:border-box!important;width:100%!important;min-width:0!important}
        .st-key-approved_datasheet_question_panel .st-key-approved_datasheet_ask [data-testid="stElementContainer"]{display:flex!important;justify-content:flex-end!important;width:100%!important;min-width:0!important}
        .st-key-approved_datasheet_question_panel .st-key-approved_datasheet_ask button{box-sizing:border-box!important;width:100%!important;max-width:136px!important;min-width:0!important;min-height:40px!important;height:40px!important;padding:0 9px!important;border-radius:8px!important;font-size:10px!important;white-space:nowrap!important}
        .st-key-approved_datasheet_question_panel [class*="st-key-dq_chip_"] button{min-height:28px!important;margin:0!important;padding:5px 10px!important;border:1px solid #e0e8f3!important;background:#f4f7fb!important;color:#4d627f!important;font-size:10px!important}
        .st-key-approved_datasheet_question_panel [data-testid="stHorizontalBlock"]:has([class*="st-key-dq_chip_"]){gap:.35rem!important;flex-wrap:wrap!important}
        .cv-dq-answer-empty{display:flex;flex-direction:column;gap:6px;margin-top:16px;padding:18px;border:1px solid #e5ecf5;border-radius:11px;background:#f9fbff;color:#7889a1;font-size:11px;line-height:1.45}
        .cv-dq-answer-empty strong{color:#314865;font-size:12px}
        .cv-dq-answer-caution{margin:14px 0 0;color:#8a97aa;font-size:9px;line-height:1.45}
        .st-key-approved_datasheet_source_panel .cv-dq-source-head{margin-bottom:14px!important}
        .cv-dq-source-head h2{margin:0!important;color:#172942;font-size:16px;font-weight:700}
        .cv-dq-source-head p{margin:4px 0 0!important;color:#8190a6;font-size:10px}
        .cv-dq-page-badge{padding:6px 10px;border-radius:999px;background:#f1f5f9;color:#5e718c;font-size:9px;font-weight:800;white-space:nowrap}
        .cv-dq-page-preview-frame{min-height:460px!important;padding:16px!important}
        .cv-dq-page-preview-frame img{max-height:490px!important}
        .cv-dq-page-fallback{box-sizing:border-box;width:100%;min-height:460px!important;max-height:490px;overflow:auto;border:1px solid #e4eaf3;border-radius:9px;white-space:normal!important}
        .cv-dq-source-nav{margin-top:12px}
        .cv-dq-source-nav button{border:0!important;background:transparent!important;color:#2463e8!important;font-size:10px!important;box-shadow:none!important}
        .st-key-datasheet_qa_uploader{margin:0!important}
        section[data-testid="stMain"]:has(.dq-hide-picker) .st-key-datasheet_qa_uploader{display:none!important}
        section[data-testid="stMain"]:has(.dq-picker-open) .st-key-datasheet_qa_uploader{display:block!important}
        section[data-testid="stMain"] .st-key-datasheet_qa_uploader [data-testid="stFileUploaderDropzone"]{min-height:72px!important;padding:10px 14px!important;border:1px dashed #b9c8dc!important;border-radius:10px!important;background:#fafcff!important}
        section[data-testid="stMain"] .st-key-datasheet_qa_uploader [data-testid="stFileUploaderDropzoneInstructions"] p{font-size:10px!important}
        @media(max-width:900px){.st-key-approved_datasheet_question_panel,.st-key-approved_datasheet_source_panel{min-height:0!important}.cv-dq-page-preview-frame,.cv-dq-page-fallback{min-height:320px!important}}
        @media(max-width:850px){.st-key-approved_datasheet_workspace .dq-title{font-size:24px}.cv-dq-page-preview-frame,.cv-dq-page-fallback{min-height:300px}}
        /* Production hotfix: bare st.text_area (outside st.form) collapses under
           Emotion layout — stTextArea / RootElement hit height 0–2px with
           overflow:hidden, so Ask Cadivor shows with no visible composer.
           Same pattern as analysis_detail form textarea un-collapse. */
        section[data-testid="stMain"] .st-key-datasheet_qa_question,
        section[data-testid="stMain"] .st-key-datasheet_qa_question[data-testid="stElementContainer"],
        section[data-testid="stMain"] .st-key-datasheet_qa_question [data-testid="stTextArea"],
        section[data-testid="stMain"] .st-key-datasheet_qa_question [data-testid="stTextAreaRootElement"],
        section[data-testid="stMain"] .st-key-datasheet_qa_question [data-baseweb="textarea"],
        section[data-testid="stMain"] [data-testid="stForm"] .st-key-datasheet_qa_question,
        section[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextArea"],
        section[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextAreaRootElement"]{
          display:flex!important;flex-direction:column!important;
          visibility:visible!important;opacity:1!important;
          height:auto!important;min-height:84px!important;max-height:none!important;
          overflow:visible!important;flex:1 1 auto!important;align-self:stretch!important
        }
        section[data-testid="stMain"] .st-key-datasheet_qa_question textarea,
        section[data-testid="stMain"] [data-testid="stForm"] .st-key-datasheet_qa_question textarea,
        section[data-testid="stMain"] [data-testid="stForm"] [data-testid="stTextArea"] textarea{
          display:block!important;visibility:visible!important;opacity:1!important;
          width:100%!important;min-height:84px!important;height:84px!important;
          overflow:auto!important;resize:vertical!important;pointer-events:auto!important
        }
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
        section[data-testid="stMain"] .st-key-datasheet_qa_ask_button button,
        section[data-testid="stMain"] .stFormSubmitButton>button{
          min-width:148px!important;width:auto!important;max-width:220px!important
        }
        section[data-testid="stMain"] .st-key-approved_datasheet_question_panel .st-key-datasheet_qa_question [data-testid="stTextAreaRootElement"]{min-height:64px!important;height:auto!important}
        section[data-testid="stMain"] .st-key-approved_datasheet_question_panel .st-key-datasheet_qa_question textarea{min-height:64px!important;height:64px!important;resize:none!important}
        section[data-testid="stMain"] .st-key-approved_datasheet_question_panel [class*="st-key-dq_chip_"] button{min-height:28px!important;padding:5px 10px!important;font-size:10px!important}
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
        with st.spinner("Cadivor is reviewing the datasheet…"):
            result = answer_datasheet_question(
                document,
                question,
                ai_client=build_datasheet_ai_client(),
                history=history,
            )
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


def _typed_ask_click() -> None:
    """Queue a typed Ask Cadivor click on the shared pending path.

    Runs as a Streamlit ``on_click`` callback after widget values are written to
    session state and before the script body — same lifecycle as suggestion chips.
    Never mutates the composer widget key here.
    """
    question = resolve_datasheet_question(
        st.session_state.get(DATASHEET_QA_QUESTION_WIDGET_KEY),
    )
    if not question:
        st.session_state[DATASHEET_QA_EMPTY_ASK_KEY] = True
        return
    st.session_state.pop(DATASHEET_QA_EMPTY_ASK_KEY, None)
    queue_datasheet_follow_up(st.session_state, question)


def _typed_follow_up_click() -> None:
    """Queue the bottom-of-answer follow-up composer through the same path."""
    question = resolve_datasheet_question(
        st.session_state.get(DATASHEET_QA_FOLLOW_UP_WIDGET_KEY),
    )
    if not question:
        st.session_state[DATASHEET_QA_EMPTY_ASK_KEY] = True
        return
    st.session_state.pop(DATASHEET_QA_EMPTY_ASK_KEY, None)
    queue_datasheet_follow_up(st.session_state, question)


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
    title: str = "Ask next",
) -> None:
    if not suggestions:
        return
    visible = suggestions[:VISIBLE_FOLLOW_UPS]
    overflow = suggestions[VISIBLE_FOLLOW_UPS:]
    _html(
        '<div class="dq-ask-next">'
        f'<div class="dq-ask-next-label">{_esc(title)}</div>'
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
                    use_container_width=False,
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
                    use_container_width=False,
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
    show_question: bool = True,
    show_question_reference: bool = True,
) -> None:
    if show_question:
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

    question_reference = (
        f'<p class="dq-question-reference">{_esc(turn.get("question"))}</p>'
        if show_question_reference
        else ""
    )
    _html(
        '<div class="dq-assistant">'
        '<div class="dq-answer-head">'
        '<span class="dq-answer-badge">ANSWER</span>'
        f'<span class="dq-citation-count">{len(citations)} citation{"s" if len(citations) != 1 else ""}</span>'
        '</div>'
        f"{question_reference}"
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
    apply_datasheet_question_clear(st.session_state)

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
        '<h1 class="dq-title">Ask a datasheet</h1>'
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
            "<p>Ask about this datasheet below, or use a suggested follow-up after your first answer.</p>"
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
    # Use markdown (not a preceding st.html card) so the composer chrome cannot
    # overlap the textarea and swallow the first Ask click.
    st.markdown(
        '<p class="dq-composer-title">Ask this datasheet</p>'
        f'<p class="dq-composer-hint">{_esc(ask_hint)}</p>',
        unsafe_allow_html=True,
    )
    # Non-form composer: button on_click shares the chip queue path. Forms were
    # losing the first typed submit (empty form return / delayed session sync).
    st.text_area(
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
        st.button(
            "Ask datasheet",
            key="datasheet_qa_ask_button",
            type="primary",
            use_container_width=False,
            disabled=processing,
            on_click=_typed_ask_click,
        )
        cadivor_button_wrap_end()

    if st.session_state.pop(DATASHEET_QA_EMPTY_ASK_KEY, False):
        st.warning("Enter a question about this datasheet.")
