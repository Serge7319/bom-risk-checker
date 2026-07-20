"""Cadivor analysis workspace — Milestone 28.1 reliability and review refactor."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import html
import re
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from src.ui.navigation import navigate_to, internal_nav_button
from src.ai_advisor import build_engineering_supply_advisor
from src.services.engineering_context import build_engineering_context
from src.services.knowledge_graph import build_knowledge_graph
from src.components.review import (
    is_unresolved_review,
    parse_due_date,
    summarize_review_workflow,
    validate_review_decision,
)
from src.engineering_review_service import (
    complete_review_session,
    create_review_session,
    get_latest_review_session,
    list_review_events,
    list_review_items,
    list_review_comments,
    add_review_comment,
    reopen_review_session,
    save_review_item,
    set_review_lock,
    update_review_session_status,
)
from src.discussion_service import (
    add_analysis_comment,
    create_workspace_notification,
    delete_comment,
    extract_mentions,
    follow_analysis,
    is_following_analysis,
    list_analysis_comments,
    list_analysis_followers,
    resolve_mentioned_members,
    set_comment_pinned,
    unfollow_analysis,
)


def _safe(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _num(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _date(value: Any) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return str(value)[:10]


def _relative_date(value: Any) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
        if delta.days <= 0:
            hours = int(delta.total_seconds() // 3600)
            if hours <= 0:
                return f"{max(1, int(delta.total_seconds() // 60))} min ago"
            return f"{hours} hr ago"
        if delta.days == 1:
            return "Yesterday"
        if delta.days < 7:
            return f"{delta.days} days ago"
        return dt.strftime("%b %d")
    except Exception:
        return _date(value)


def _risk_class(level: Any = None, score: Any = None) -> str:
    level_text = str(level or "").lower()
    score_num = _num(score, 0)
    if "high" in level_text or score_num >= 70:
        return "bad"
    if "medium" in level_text or score_num >= 35:
        return "warn"
    return "good"


def _health_class(score: Any) -> str:
    score_num = _num(score, 0)
    if score_num >= 80:
        return "good"
    if score_num >= 55:
        return "warn"
    return "bad"


def _lucide(name: str, size: int = 18) -> str:
    icons = {
        "arrow-left": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
        "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/>',
        "shield": '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3z"/><path d="m9 12 2 2 4-4"/>',
        "alert": '<path d="m21.7 18-8.5-15a1.4 1.4 0 0 0-2.4 0L2.3 18a1.4 1.4 0 0 0 1.2 2h17a1.4 1.4 0 0 0 1.2-2Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
        "layers": '<path d="m12 2 10 5-10 5L2 7l10-5Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
        "replace": '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="m7 22-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
        "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
    }
    body = icons.get(name, icons["file"])
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def _query_table(
    supabase,
    table: str,
    *,
    user_id: str,
    analysis_id: str,
    workspace_id: str | None = None,
    order: str | None = None,
    limit: int | None = None,
):
    """Load records linked to an already-authorized analysis.

    New Cadivor rows carry user_id and workspace_id. Older rows may predate one
    or both columns. The parent analysis is verified before this helper is used,
    so progressively relaxing legacy metadata filters remains scoped to the
    selected analysis_id while restoring historical component records.
    """

    def _execute(*, include_user: bool, include_workspace: bool):
        query = supabase.table(table).select("*").eq("analysis_id", analysis_id)
        if include_user and user_id:
            query = query.eq("user_id", user_id)
        if include_workspace and workspace_id:
            query = query.eq("workspace_id", workspace_id)
        if order:
            query = query.order(order, desc=True)
        if limit:
            query = query.limit(limit)
        return query.execute().data or []

    attempts = [
        (True, bool(workspace_id)),   # Current schema.
        (True, False),                # Legacy rows without workspace_id.
        (False, False),               # Oldest rows linked only by analysis_id.
    ]
    seen = set()
    for include_user, include_workspace in attempts:
        key = (include_user, include_workspace)
        if key in seen:
            continue
        seen.add(key)
        try:
            rows = _execute(
                include_user=include_user,
                include_workspace=include_workspace,
            )
            if rows:
                return rows
        except Exception:
            continue
    return []


def _section_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">{html.escape(title)}</div>'
        f'<div class="cv-analysis-section-meta">{html.escape(subtitle)}</div></div></div>',
        unsafe_allow_html=True,
    )


def _part_value(part: dict[str, Any], *keys: str, fallback: Any = None) -> Any:
    for key in keys:
        value = part.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return fallback


def _risk_label(part: dict[str, Any]) -> str:
    return _safe(
        _part_value(part, "risk_level", "Risk Level", "risk_level_display"),
        "Low",
    )


def _monitor_url(mpn: str, analysis_id: str) -> str:
    return (
        "?page=Monitoring"
        f"&mpn={str(mpn).replace(' ', '%20')}"
        f"&analysis_id={str(analysis_id).replace(' ', '%20')}"
    )


def _alternative_url(mpn: str, analysis_id: str) -> str:
    return (
        "?page=Alternative%20Finder"
        f"&original_part={str(mpn).replace(' ', '%20')}"
        f"&analysis_id={str(analysis_id).replace(' ', '%20')}"
    )


def _health_summary(health: int, high: int, medium: int) -> tuple[str, str, int]:
    if health >= 90 and high == 0:
        return "Production Ready", "Strong portfolio health with no high-risk components.", 95
    if health >= 80 and high <= 1:
        return "Review Recommended", "A focused engineering review is recommended before release.", 84
    if health >= 60:
        return "Engineering Review Required", "Resolve risk drivers and validate sourcing before release.", 68
    return "Release Hold Recommended", "Material lifecycle or sourcing risks require remediation.", 45


def render_analysis_detail(
    *,
    current_user,
    supabase,
    load_analysis_history,
    light_plotly_layout=None,
    _qp_value=None,
    workspace_id=None,
    workspace_role="viewer",
    workspace_members=None,
):
    analysis_id = ""
    if _qp_value:
        analysis_id = _safe(_qp_value("analysis_id", ""), "")
    if not analysis_id:
        analysis_id = _safe(st.query_params.get("analysis_id", ""), "")

    requested_tab = _safe(st.query_params.get("tab", ""), "").strip().lower()
    requested_component = _safe(st.query_params.get("component", ""), "").strip()
    requested_focus = _safe(st.query_params.get("focus", ""), "").strip().lower()
    component_focus_requested = bool(
        requested_component
        or requested_tab == "components"
        or requested_focus == "component-risk"
    )

    # Sprint 34.2.6 — defer saved-BOM scroll restoration until the complete
    # Analysis Details page has rendered. Streamlit/browser scroll restoration
    # can run after an early script, which was returning users to the old lower
    # position. The final script at the end of this renderer repeatedly resets
    # the actual Streamlit main scroll container after layout stabilization.
    scroll_key = "cv28_last_open_analysis"
    saved_bom_top_requested = requested_focus == "analysis-top"
    analysis_changed = bool(
        analysis_id and st.session_state.get(scroll_key) != analysis_id
    )
    if analysis_id:
        st.session_state[scroll_key] = analysis_id

    st.markdown(
        '<div id="cv-analysis-page-top" style="height:1px;scroll-margin-top:76px"></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <style id="cadivor-analysis-tabs-v82">
        .cv-analysis-back{display:inline-flex;align-items:center;gap:8px;color:#2563EB!important;text-decoration:none!important;font-size:12px;font-weight:950;margin-bottom:10px}
        .cv-analysis-hero{background:linear-gradient(135deg,#fff 0%,#f8fbff 58%,#eaf2ff 100%);border:1px solid #bfdbfe;border-radius:26px;padding:26px 28px;box-shadow:0 24px 70px rgba(15,23,42,.075);display:grid;grid-template-columns:minmax(0,1.35fr) minmax(360px,.9fr);gap:22px;align-items:center;margin-bottom:14px}
        .cv-analysis-eyebrow{display:inline-flex;align-items:center;gap:8px;border:1px solid #bfdbfe;background:#eff6ff;color:#2563eb!important;border-radius:999px;padding:8px 12px;font-size:11px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:14px}
        .cv-analysis-title{color:#0b1220!important;font-size:38px;font-weight:980;line-height:1.02;letter-spacing:-.045em;margin:0 0 10px}
        .cv-analysis-sub{color:#475569!important;font-size:14px;font-weight:750;line-height:1.65;max-width:820px;margin:0}
        .cv-analysis-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.cv-analysis-btn{display:inline-flex;align-items:center;gap:8px;text-decoration:none!important;border-radius:12px;padding:12px 14px;font-size:12px;font-weight:950;border:1px solid #bfdbfe;background:#f8fafc;color:#2563eb!important}.cv-analysis-btn.primary{background:#2563eb;color:#fff!important;border-color:#2563eb;box-shadow:0 16px 30px rgba(37,99,235,.23)}
        .cv-analysis-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.cv-analysis-mini{background:rgba(255,255,255,.9);border:1px solid #e2e8f0;border-radius:18px;padding:15px 16px;box-shadow:0 12px 28px rgba(15,23,42,.045)}.cv-analysis-mini span{display:block;color:#64748b!important;font-size:10px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:7px}.cv-analysis-mini strong{display:block;color:#0b1220!important;font-size:25px;font-weight:980;line-height:1}.cv-analysis-mini small{display:block;color:#475569!important;font-size:11px;font-weight:800;margin-top:6px}
        .cv-analysis-section{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin:14px 0 8px}.cv-analysis-section-title{color:#0b1220!important;font-size:21px;font-weight:980;letter-spacing:-.025em}.cv-analysis-section-meta{color:#64748b!important;font-size:12px;font-weight:800;margin-top:4px}
        .cv-advisor-hero{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f5f9ff 62%,#eaf2ff);border-radius:24px;padding:22px;box-shadow:0 20px 50px rgba(37,99,235,.08);margin-bottom:14px}
        .cv-advisor-kicker{color:#2563eb!important;font-size:10px;font-weight:980;letter-spacing:.11em;text-transform:uppercase;margin-bottom:8px}.cv-advisor-title{color:#0f172a!important;font-size:26px;font-weight:980;letter-spacing:-.035em;margin:0 0 7px}.cv-advisor-copy{color:#52647a!important;font-size:12px;font-weight:760;line-height:1.55;margin:0}
        .cv-advisor-score-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px;margin:14px 0}.cv-advisor-score{border:1px solid #e2e8f0;background:#fff;border-radius:18px;padding:15px;box-shadow:0 10px 24px rgba(15,23,42,.04)}.cv-advisor-score span{display:block;color:#64748b!important;font-size:9px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:7px}.cv-advisor-score strong{display:block;color:#0f172a!important;font-size:19px;font-weight:980}.cv-advisor-score small{display:block;color:#64748b!important;font-size:10px;font-weight:750;margin-top:5px}
        .cv-advisor-action{border:1px solid #e2e8f0;background:#fff;border-radius:18px;padding:16px;margin-bottom:10px;box-shadow:0 10px 26px rgba(15,23,42,.04)}.cv-advisor-action-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.cv-advisor-rank{width:29px;height:29px;flex:0 0 29px;border-radius:10px;background:#eff6ff;color:#2563eb!important;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:980}.cv-advisor-action h4{color:#0f172a!important;font-size:14px;font-weight:980;margin:0 0 5px}.cv-advisor-action p{color:#52647a!important;font-size:11px;font-weight:720;line-height:1.5;margin:0}.cv-advisor-tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:11px}.cv-advisor-tag{display:inline-flex;border-radius:999px;padding:5px 8px;border:1px solid #dbeafe;background:#eff6ff;color:#1d4ed8!important;font-size:9px;font-weight:950}
        .cv-advisor-summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.cv-advisor-summary{border:1px solid #e2e8f0;background:#fff;border-radius:19px;padding:17px}.cv-advisor-summary span{display:block;color:#2563eb!important;font-size:9px;font-weight:980;letter-spacing:.09em;text-transform:uppercase;margin-bottom:7px}.cv-advisor-summary p{color:#334155!important;font-size:12px;font-weight:720;line-height:1.6;margin:0}
        @media(max-width:900px){.cv-advisor-score-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cv-advisor-summary-grid{grid-template-columns:1fr}}
        .cv-analysis-card,.cv-risk-compact{background:#fff;border:1px solid #e2e8f0;border-radius:22px;padding:20px;box-shadow:0 18px 44px rgba(15,23,42,.055)}.cv-analysis-card-title{display:flex;align-items:center;justify-content:space-between;gap:14px;color:#0b1220!important;font-size:16px;font-weight:980;margin-bottom:12px}.cv-analysis-icon{width:38px;height:38px;border-radius:13px;display:flex;align-items:center;justify-content:center;background:#eff6ff;border:1px solid #bfdbfe;color:#2563eb!important}
        .cv-analysis-row-list{display:grid;gap:9px}.cv-analysis-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:13px 14px}.cv-analysis-row-title{color:#0b1220!important;font-size:13px;font-weight:980;margin-bottom:4px}.cv-analysis-row-meta{color:#64748b!important;font-size:11px;font-weight:800;line-height:1.45}.cv-analysis-pills{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.cv-analysis-pill{display:inline-flex;border-radius:999px;padding:7px 9px;font-size:11px;font-weight:950;border:1px solid #bfdbfe;background:#eff6ff;color:#2563eb!important}.cv-analysis-pill.good{border-color:#a7f3d0;background:#ecfdf5;color:#047857!important}.cv-analysis-pill.warn{border-color:#fde68a;background:#fffbeb;color:#b45309!important}.cv-analysis-pill.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c!important}
        .cv-analysis-empty{border:1px dashed #cbd5e1;background:#f8fafc;border-radius:18px;padding:24px;text-align:center;color:#64748b!important;font-size:13px;font-weight:800}
        div[data-baseweb="tab-list"]{gap:8px!important;border-bottom:1px solid #dbe3ef!important;padding:0 0 8px!important}
        button[data-baseweb="tab"]{border:1px solid transparent!important;border-radius:11px!important;padding:9px 14px!important;font-weight:900!important;color:#475569!important}
        button[data-baseweb="tab"][aria-selected="true"]{background:#2563eb!important;color:#fff!important;border-color:#2563eb!important;box-shadow:0 10px 22px rgba(37,99,235,.18)!important}
        button[data-baseweb="tab"][aria-selected="true"] p{color:#fff!important}
        div[data-baseweb="tab-highlight"]{display:none!important}
        .cv-status-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:14px}
        .cv-status-card{border:1px solid #e2e8f0;background:#fff;border-radius:18px;padding:16px;box-shadow:0 12px 30px rgba(15,23,42,.045)}
        .cv-status-card span{display:block;color:#64748b!important;font-size:10px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px}
        .cv-status-card strong{display:block;color:#0f172a!important;font-size:18px;font-weight:980;line-height:1.2}
        .cv-status-card small{display:block;color:#64748b!important;font-size:11px;font-weight:750;line-height:1.45;margin-top:7px}
        .cv-status-card.good{background:#ecfdf5;border-color:#a7f3d0}.cv-status-card.warn{background:#fffbeb;border-color:#fde68a}.cv-status-card.bad{background:#fef2f2;border-color:#fecaca}
        .cv-alert-card{border:1px solid #e2e8f0;background:#fff;border-radius:18px;padding:15px 16px;margin-bottom:10px;box-shadow:0 12px 30px rgba(15,23,42,.04)}
        .cv-alert-top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}
        .cv-alert-part{font-size:14px;font-weight:980;color:#0f172a!important}.cv-alert-type{font-size:10px;font-weight:950;text-transform:uppercase;letter-spacing:.08em;color:#64748b!important}
        .cv-alert-message{font-size:11px;font-weight:750;color:#475569!important;line-height:1.5;margin-bottom:10px}
        .cv-alert-actions{display:flex;gap:8px;flex-wrap:wrap}.cv-alert-action{display:inline-flex;text-decoration:none!important;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8!important;border-radius:10px;padding:7px 10px;font-size:10px;font-weight:900}
        .cv-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px;margin-bottom:14px}.cv-kpi{border:1px solid #e2e8f0;background:#fff;border-radius:17px;padding:14px}.cv-kpi span{display:block;color:#64748b!important;font-size:9px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:7px}.cv-kpi strong{display:block;color:#0f172a!important;font-size:22px;font-weight:980}.cv-kpi small{display:block;color:#64748b!important;font-size:10px;font-weight:800;margin-top:5px}
        .cv-report-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.cv-report-card{border:1px solid #e2e8f0;background:#fff;border-radius:20px;padding:17px;box-shadow:0 14px 34px rgba(15,23,42,.045)}.cv-report-card h4{margin:0 0 6px;color:#0f172a!important;font-size:15px;font-weight:980}.cv-report-card p{margin:0 0 12px;color:#64748b!important;font-size:11px;font-weight:750;line-height:1.5}.cv-report-formats{display:flex;gap:7px;flex-wrap:wrap}.cv-format{border:1px solid #dbeafe;background:#eff6ff;color:#1d4ed8!important;border-radius:999px;padding:5px 8px;font-size:9px;font-weight:950}
        .cv-discussion-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:11px;margin-bottom:14px}
        .cv-discussion-kpi{border:1px solid #e2e8f0;background:#fff;border-radius:17px;padding:14px}.cv-discussion-kpi span{display:block;color:#64748b!important;font-size:9px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:7px}.cv-discussion-kpi strong{display:block;color:#0f172a!important;font-size:22px;font-weight:980}
        .cv-comment{border:1px solid #e2e8f0;background:#fff;border-radius:18px;padding:15px 16px;margin-bottom:11px;box-shadow:0 10px 26px rgba(15,23,42,.04)}
        .cv-comment.pinned{border-color:#fcd34d;background:#fffbeb}.cv-comment-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:9px}.cv-comment-author{color:#0f172a!important;font-size:13px;font-weight:980}.cv-comment-meta{color:#64748b!important;font-size:10px;font-weight:800;margin-top:3px}.cv-comment-body{color:#334155!important;font-size:12px;font-weight:700;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere}.cv-comment-badge{display:inline-flex;border-radius:999px;padding:5px 8px;border:1px solid #fde68a;background:#fef3c7;color:#92400e!important;font-size:9px;font-weight:950}
        .cv-follow-card{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eff6ff);border-radius:20px;padding:17px;margin-bottom:14px}
        .cv-comment-context{display:inline-flex;border-radius:999px;padding:5px 8px;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8!important;font-size:9px;font-weight:950;margin-left:6px}
        .cv-timeline{position:relative;margin:8px 0 0 10px;padding-left:24px;border-left:2px solid #dbeafe}
        .cv-timeline-item{position:relative;border:1px solid #e2e8f0;background:#fff;border-radius:17px;padding:14px 16px;margin:0 0 12px 0;box-shadow:0 8px 22px rgba(15,23,42,.04)}
        .cv-timeline-item:before{content:"";position:absolute;left:-31px;top:18px;width:12px;height:12px;border-radius:50%;background:#2563eb;border:3px solid #eff6ff;box-shadow:0 0 0 1px #93c5fd}
        .cv-timeline-item.alert:before{background:#dc2626}.cv-timeline-item.comment:before{background:#7c3aed}.cv-timeline-item.alternative:before{background:#059669}
        .cv-timeline-title{color:#0f172a!important;font-size:13px;font-weight:980;margin-bottom:4px}
        .cv-timeline-meta{color:#64748b!important;font-size:10px;font-weight:800;margin-bottom:7px}
        .cv-timeline-body{color:#334155!important;font-size:12px;font-weight:700;line-height:1.55;overflow-wrap:anywhere}
        .cv-component-detail{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eff6ff);border-radius:22px;padding:20px;box-shadow:0 18px 45px rgba(37,99,235,.08)}
        .cv-component-detail-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:14px 0}.cv-component-detail-grid div{border:1px solid #dbe3ef;background:rgba(255,255,255,.9);border-radius:14px;padding:12px}.cv-component-detail-grid span{display:block;color:#64748b!important;font-size:9px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px}.cv-component-detail-grid strong{display:block;color:#0f172a!important;font-size:13px;font-weight:950;overflow-wrap:anywhere}
        .cv-readiness-list{display:grid;gap:12px}.cv-readiness-row{border:1px solid #e2e8f0;background:#f8fafc;border-radius:16px;padding:13px}.cv-readiness-row strong{display:block;color:#0b1220!important;font-size:13px;font-weight:980;margin-bottom:4px}.cv-readiness-row span{display:block;color:#64748b!important;font-size:11px;font-weight:800}.cv-readiness-bar{height:9px;border-radius:999px;background:#e2e8f0;overflow:hidden;margin-top:10px}.cv-readiness-bar i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#2563eb,#16a34a)}.cv-readiness-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.cv-readiness-metrics div{border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:12px}.cv-readiness-metrics span{display:block;color:#64748b!important;font-size:10px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:7px}.cv-readiness-metrics strong{display:block;color:#0b1220!important;font-size:22px;font-weight:980}.cv-readiness-metrics small{display:block;color:#64748b!important;font-size:10px;font-weight:800;margin-top:6px}
        .cv-analysis-table-wrap{background:#fff;border:1px solid #e2e8f0;border-radius:22px;box-shadow:0 18px 44px rgba(15,23,42,.055);overflow:hidden}.cv-analysis-table-head{display:flex;justify-content:space-between;align-items:center;padding:18px 20px;border-bottom:1px solid #e2e8f0}.cv-analysis-component{display:grid;grid-template-columns:1.2fr 1fr .75fr .75fr auto;gap:12px;align-items:center;padding:13px 20px;border-bottom:1px solid #eef2f7;transition:background .16s ease,border-color .16s ease,box-shadow .16s ease}.cv-analysis-component .head{color:#0b1220!important;font-size:13px;font-weight:980}.cv-analysis-component .sub{color:#64748b!important;font-size:11px;font-weight:800;margin-top:3px}.cv-analysis-component.is-selected{background:linear-gradient(90deg,#dbeafe 0%,#eff6ff 45%,#f8fbff 100%);border-left:5px solid #2563eb;padding-left:15px;box-shadow:inset 0 0 0 1px #93c5fd,0 8px 22px rgba(37,99,235,.10)}.cv-analysis-component.is-selected .head{color:#1d4ed8!important}.cv-analysis-component.is-command-focus{animation:cv-command-focus-pulse .65s ease-out 1}.cv-component-detail.is-command-focus{animation:cv-command-panel-pulse .65s ease-out 1}.cv-command-origin{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #bfdbfe;background:linear-gradient(90deg,#eff6ff,#f8fbff);border-radius:14px;padding:10px 13px;margin:0 0 12px}.cv-command-origin-main{display:flex;align-items:center;gap:9px;min-width:0}.cv-command-origin-icon{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:9px;background:#2563eb;color:#fff!important;font-size:12px;font-weight:950}.cv-command-origin-copy{min-width:0}.cv-command-origin-copy strong{display:block;color:#0f172a!important;font-size:11px;font-weight:950}.cv-command-origin-copy span{display:block;color:#64748b!important;font-size:10px;font-weight:800;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.cv-command-origin-part{display:inline-flex;align-items:center;border:1px solid #93c5fd;background:#fff;color:#1d4ed8!important;border-radius:999px;padding:6px 9px;font-size:10px;font-weight:950;white-space:nowrap}@keyframes cv-command-focus-pulse{0%{transform:translateX(0);box-shadow:inset 0 0 0 1px #60a5fa,0 0 0 0 rgba(37,99,235,.35)}45%{transform:translateX(2px);box-shadow:inset 0 0 0 1px #3b82f6,0 0 0 7px rgba(37,99,235,.10)}100%{transform:translateX(0);box-shadow:inset 0 0 0 1px #93c5fd,0 8px 22px rgba(37,99,235,.10)}}@keyframes cv-command-panel-pulse{0%{box-shadow:0 18px 45px rgba(37,99,235,.08)}45%{box-shadow:0 18px 45px rgba(37,99,235,.18),0 0 0 6px rgba(37,99,235,.08)}100%{box-shadow:0 18px 45px rgba(37,99,235,.08)}}
        [data-testid="stTabs"]{margin-top:8px}[data-testid="stTabs"] [data-baseweb="tab-list"]{position:sticky;top:64px;z-index:40;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:6px;box-shadow:0 12px 28px rgba(15,23,42,.06);gap:6px}[data-testid="stTabs"] [data-baseweb="tab"]{height:42px;border-radius:11px;padding:0 18px;font-weight:900;color:#475569}[data-testid="stTabs"] [aria-selected="true"]{background:#eff6ff!important;color:#2563eb!important}
        @media(max-width:1180px){.cv-analysis-hero{grid-template-columns:1fr}.cv-analysis-component{grid-template-columns:1fr}.cv-readiness-metrics{grid-template-columns:1fr}}@media(max-width:700px){.cv-analysis-summary{grid-template-columns:1fr}.cv-analysis-title{font-size:30px}.cv-analysis-hero{padding:20px}}
        
        /* Milestone 25.0 — Engineering Intelligence Workspace */
        .cv25-intel-hero{
          display:grid;
          grid-template-columns:minmax(0,1.25fr) minmax(310px,.75fr);
          gap:14px;
          margin:0 0 14px;
        }
        .cv25-brief{
          border:1px solid #BFDBFE;
          background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 60%,#EEF5FF 100%);
          border-radius:22px;
          padding:20px;
          box-shadow:0 14px 36px rgba(37,99,235,.07);
        }
        .cv25-brief-kicker{
          color:#2563EB!important;
          font-size:10px;
          font-weight:950;
          letter-spacing:.1em;
          text-transform:uppercase;
          margin-bottom:8px;
        }
        .cv25-brief-title{
          color:#0F172A!important;
          font-size:25px;
          font-weight:980;
          letter-spacing:-.035em;
          line-height:1.08;
          margin-bottom:8px;
        }
        .cv25-brief-copy{
          color:#52647A!important;
          font-size:12px;
          font-weight:740;
          line-height:1.55;
        }
        .cv25-readiness{
          border:1px solid #E2E8F0;
          background:#FFFFFF;
          border-radius:22px;
          padding:18px;
          box-shadow:0 12px 30px rgba(15,23,42,.05);
        }
        .cv25-readiness-label{
          color:#64748B!important;
          font-size:10px;
          font-weight:950;
          letter-spacing:.08em;
          text-transform:uppercase;
        }
        .cv25-readiness-score{
          color:#0F172A!important;
          font-size:38px;
          font-weight:980;
          letter-spacing:-.05em;
          line-height:1;
          margin:10px 0 7px;
        }
        .cv25-readiness-score.good{color:#047857!important}
        .cv25-readiness-score.warn{color:#A16207!important}
        .cv25-readiness-score.bad{color:#B91C1C!important}
        .cv25-readiness-bar{
          height:8px;
          overflow:hidden;
          border-radius:999px;
          background:#E2E8F0;
          margin:12px 0 10px;
        }
        .cv25-readiness-bar i{
          display:block;
          height:100%;
          border-radius:999px;
          background:linear-gradient(90deg,#2563EB,#60A5FA);
        }
        .cv25-readiness-note{
          color:#64748B!important;
          font-size:10.5px;
          font-weight:760;
          line-height:1.4;
        }
        .cv25-matrix{
          display:grid;
          grid-template-columns:repeat(4,minmax(0,1fr));
          gap:10px;
          margin:10px 0 17px;
        }
        .cv25-matrix-card{
          position:relative;
          overflow:hidden;
          border:1px solid #E2E8F0;
          background:#FFFFFF;
          border-radius:17px;
          padding:14px;
          min-height:120px;
          box-shadow:0 8px 24px rgba(15,23,42,.045);
        }
        .cv25-matrix-card::before{
          content:"";
          position:absolute;
          left:0;top:0;bottom:0;
          width:4px;
          background:#94A3B8;
        }
        .cv25-matrix-card.bad::before{background:#DC2626}
        .cv25-matrix-card.warn::before{background:#F59E0B}
        .cv25-matrix-card.good::before{background:#16A34A}
        .cv25-matrix-label{
          color:#64748B!important;
          font-size:9.5px;
          font-weight:950;
          letter-spacing:.08em;
          text-transform:uppercase;
        }
        .cv25-matrix-value{
          color:#0F172A!important;
          font-size:28px;
          font-weight:980;
          letter-spacing:-.04em;
          margin:9px 0 4px;
        }
        .cv25-matrix-copy{
          color:#64748B!important;
          font-size:10px;
          font-weight:720;
          line-height:1.4;
        }
        .cv25-layout{
          display:grid;
          grid-template-columns:minmax(0,1.18fr) minmax(340px,.82fr);
          gap:14px;
          align-items:start;
        }
        .cv25-panel{
          border:1px solid #E2E8F0;
          background:#FFFFFF;
          border-radius:20px;
          padding:17px;
          box-shadow:0 10px 28px rgba(15,23,42,.045);
        }
        .cv25-panel-title{
          color:#0F172A!important;
          font-size:16px;
          font-weight:980;
          letter-spacing:-.02em;
          margin-bottom:4px;
        }
        .cv25-panel-meta{
          color:#64748B!important;
          font-size:10.5px;
          font-weight:740;
          margin-bottom:12px;
        }
        .cv25-priority{
          display:grid;
          grid-template-columns:38px minmax(0,1fr) auto;
          gap:11px;
          align-items:start;
          padding:13px 0;
          border-bottom:1px solid #EEF2F7;
        }
        .cv25-priority:last-child{border-bottom:0}
        .cv25-rank{
          width:34px;height:34px;
          border-radius:11px;
          display:flex;align-items:center;justify-content:center;
          background:#EFF6FF;
          border:1px solid #BFDBFE;
          color:#1D4ED8!important;
          font-size:12px;font-weight:980;
        }
        .cv25-priority strong{
          display:block;
          color:#0F172A!important;
          font-size:12.5px;
          font-weight:950;
          line-height:1.25;
        }
        .cv25-priority p{
          color:#64748B!important;
          font-size:10.5px;
          font-weight:720;
          line-height:1.45;
          margin:4px 0 0;
        }
        .cv25-score{
          border-radius:999px;
          padding:5px 8px;
          background:#FEF2F2;
          border:1px solid #FECACA;
          color:#B91C1C!important;
          font-size:9px;
          font-weight:950;
          white-space:nowrap;
        }
        .cv25-score.warn{
          background:#FFFBEB;
          border-color:#FDE68A;
          color:#A16207!important;
        }
        .cv25-score.good{
          background:#ECFDF5;
          border-color:#A7F3D0;
          color:#047857!important;
        }
        .cv25-copilot{
          border:1px solid #C4B5FD;
          background:linear-gradient(135deg,#FFFFFF,#FAF7FF);
          border-radius:20px;
          padding:17px;
          box-shadow:0 10px 28px rgba(124,58,237,.06);
        }
        .cv25-copilot-kicker{
          color:#7C3AED!important;
          font-size:9.5px;
          font-weight:950;
          letter-spacing:.09em;
          text-transform:uppercase;
        }
        .cv25-copilot-title{
          color:#0F172A!important;
          font-size:16px;
          font-weight:980;
          margin:6px 0 8px;
        }
        .cv25-copilot p{
          color:#52647A!important;
          font-size:11px;
          font-weight:730;
          line-height:1.55;
          margin:0 0 10px;
        }
        .cv25-question{
          padding:9px 10px;
          border-radius:11px;
          background:#FFFFFF;
          border:1px solid #E9D5FF;
          color:#6D28D9!important;
          font-size:10px;
          font-weight:850;
          margin-top:7px;
        }
        .cv25-source-grid{
          display:grid;
          grid-template-columns:repeat(3,minmax(0,1fr));
          gap:10px;
          margin-top:14px;
        }
        .cv25-source{
          border:1px solid #E2E8F0;
          background:#FFFFFF;
          border-radius:16px;
          padding:13px;
        }
        .cv25-source span{
          display:block;
          color:#64748B!important;
          font-size:9px;
          font-weight:950;
          letter-spacing:.08em;
          text-transform:uppercase;
          margin-bottom:7px;
        }
        .cv25-source strong{
          display:block;
          color:#0F172A!important;
          font-size:14px;
          font-weight:950;
        }
        .cv25-source small{
          display:block;
          color:#64748B!important;
          font-size:9.5px;
          font-weight:720;
          margin-top:5px;
          line-height:1.35;
        }
        @media(max-width:1050px){
          .cv25-intel-hero,.cv25-layout{grid-template-columns:1fr}
          .cv25-matrix{grid-template-columns:repeat(2,minmax(0,1fr))}
        }
        @media(max-width:700px){
          .cv25-matrix,.cv25-source-grid{grid-template-columns:1fr}
        }

        /* Milestone 26.0 — Executive Decision Cockpit */
        .cv26-summary{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f8fbff 55%,#edf5ff);border-radius:24px;padding:20px;box-shadow:0 18px 46px rgba(37,99,235,.07);margin-bottom:14px}.cv26-summary-top{display:flex;justify-content:space-between;gap:18px;margin-bottom:14px}.cv26-kicker{color:#2563eb!important;font-size:9px;font-weight:980;letter-spacing:.11em;text-transform:uppercase;margin-bottom:6px}.cv26-title{color:#0f172a!important;font-size:24px;font-weight:980;letter-spacing:-.035em}.cv26-copy{color:#64748b!important;font-size:11px;font-weight:740;line-height:1.5;margin-top:6px}.cv26-status{display:inline-flex;align-items:center;border-radius:999px;padding:8px 11px;font-size:10px;font-weight:950;white-space:nowrap}.cv26-status.good{background:#ecfdf5;border:1px solid #a7f3d0;color:#047857!important}.cv26-status.warn{background:#fffbeb;border:1px solid #fde68a;color:#a16207!important}.cv26-status.bad{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c!important}
        .cv26-kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.cv26-kpi{border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:13px;min-height:92px}.cv26-kpi span{display:block;color:#64748b!important;font-size:8.5px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:7px}.cv26-kpi strong{display:block;color:#0f172a!important;font-size:20px;font-weight:980}.cv26-kpi small{display:block;color:#64748b!important;font-size:9.5px;font-weight:730;margin-top:6px}
        .cv26-card{border:1px solid #e2e8f0;background:#fff;border-radius:20px;padding:17px;box-shadow:0 10px 28px rgba(15,23,42,.045)}.cv26-card-title{color:#0f172a!important;font-size:16px;font-weight:980;margin-bottom:4px}.cv26-card-meta{color:#64748b!important;font-size:10.5px;font-weight:730;margin-bottom:13px}.cv26-meter{height:12px;border-radius:999px;background:#e2e8f0;overflow:hidden;margin:13px 0 9px}.cv26-meter i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#2563eb,#60a5fa)}.cv26-meter.good i{background:linear-gradient(90deg,#059669,#34d399)}.cv26-meter.warn i{background:linear-gradient(90deg,#d97706,#fbbf24)}.cv26-meter.bad i{background:linear-gradient(90deg,#dc2626,#fb7185)}.cv26-readiness-line{display:flex;align-items:flex-end;justify-content:space-between;gap:12px}.cv26-readiness-score{font-size:40px;font-weight:980;color:#0f172a!important}.cv26-readiness-label{font-size:11px;font-weight:950;color:#2563eb!important}
        .cv26-checks,.cv26-bars,.cv26-actions{display:grid;gap:8px}.cv26-check{display:flex;justify-content:space-between;align-items:center;border:1px solid #eef2f7;background:#f8fafc;border-radius:13px;padding:10px}.cv26-check-left{display:flex;align-items:center;gap:9px;color:#334155!important;font-size:11px;font-weight:820}.cv26-check-icon{width:22px;height:22px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-weight:980}.cv26-check-icon.done{background:#dcfce7;color:#15803d!important}.cv26-check-icon.open{background:#fef3c7;color:#a16207!important}
        .cv26-insight{border:1px solid #c4b5fd;background:linear-gradient(135deg,#fff,#faf7ff);border-radius:20px;padding:17px}.cv26-insight-kicker{color:#7c3aed!important;font-size:9px;font-weight:980;text-transform:uppercase;letter-spacing:.1em}.cv26-insight h3{color:#0f172a!important;font-size:17px;font-weight:980;margin:7px 0}.cv26-insight p,.cv26-insight li{color:#52647a!important;font-size:11px;font-weight:730;line-height:1.55}.cv26-confidence{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.cv26-evidence{border:1px solid #e9d5ff;background:#fff;border-radius:12px;padding:10px;color:#5b21b6!important;font-size:9.5px;font-weight:850}
        .cv26-bar-row{display:grid;grid-template-columns:110px minmax(0,1fr) 42px;gap:10px;align-items:center}.cv26-bar-label{color:#334155!important;font-size:10.5px;font-weight:850}.cv26-bar-track{height:8px;border-radius:999px;background:#eef2f7;overflow:hidden}.cv26-bar-track i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#2563eb,#60a5fa)}.cv26-bar-value{color:#64748b!important;font-size:9px;font-weight:900;text-align:right}.cv26-riskdist{display:flex;height:13px;border-radius:999px;overflow:hidden;background:#e2e8f0;margin:11px 0}.cv26-riskdist i{display:block;height:100%}.cv26-riskdist .healthy{background:#22c55e}.cv26-riskdist .medium{background:#f59e0b}.cv26-riskdist .critical{background:#ef4444}.cv26-legend{display:flex;gap:14px;color:#64748b!important;font-size:9.5px;font-weight:820}
        .cv26-timeline{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.cv26-phase{border:1px solid #e2e8f0;border-radius:16px;padding:13px}.cv26-phase span{display:block;color:#2563eb!important;font-size:9px;font-weight:980;text-transform:uppercase}.cv26-phase strong{display:block;color:#0f172a!important;font-size:12px;font-weight:950;margin-top:7px}.cv26-phase small{display:block;color:#64748b!important;font-size:9.5px;font-weight:730;margin-top:5px}.cv26-action{display:grid;grid-template-columns:50px minmax(0,1fr) auto;gap:10px;align-items:center;border:1px solid #e2e8f0;border-radius:15px;padding:11px}.cv26-priority{border-radius:999px;padding:5px 7px;font-size:8px;font-weight:980;text-align:center}.cv26-priority.high{background:#fef2f2;color:#b91c1c!important}.cv26-priority.medium{background:#fffbeb;color:#a16207!important}.cv26-priority.low{background:#ecfdf5;color:#047857!important}.cv26-action strong{display:block;color:#0f172a!important;font-size:11px;font-weight:950}.cv26-action small{display:block;color:#64748b!important;font-size:9.5px;margin-top:3px}.cv26-owner{color:#2563eb!important;font-size:8.5px;font-weight:900}
        @media(max-width:1180px){.cv26-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}.cv26-timeline{grid-template-columns:1fr}}@media(max-width:700px){.cv26-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.cv26-summary-top{display:block}.cv26-status{margin-top:10px}}

        /* Milestone 26.1 — Enterprise Typography & Readability */
        .cv-analysis-section-title{font-size:24px!important;line-height:1.2}.cv-analysis-section-meta{font-size:13px!important;line-height:1.55}
        .cv26-summary{padding:24px}.cv26-summary-top{margin-bottom:18px}.cv26-kicker{font-size:11px;line-height:1.4;margin-bottom:8px}.cv26-title{font-size:30px;line-height:1.15}.cv26-copy{font-size:14px;line-height:1.65;margin-top:9px}.cv26-status{min-height:34px;padding:8px 13px;font-size:11px}
        .cv26-kpis{gap:12px}.cv26-kpi{padding:16px;min-height:112px}.cv26-kpi span{font-size:10.5px;line-height:1.35;margin-bottom:9px}.cv26-kpi strong{font-size:27px;line-height:1.1}.cv26-kpi small{font-size:12px;line-height:1.45;margin-top:8px}
        .cv26-card{padding:21px}.cv26-card-title{font-size:19px;line-height:1.3;margin-bottom:6px}.cv26-card-meta{font-size:12.5px;line-height:1.55;margin-bottom:16px}
        .cv26-readiness-score{font-size:46px;line-height:1}.cv26-readiness-label{font-size:13px;line-height:1.4;margin-top:4px}.cv26-meter{height:13px;margin:15px 0 11px}
        .cv26-checks,.cv26-bars,.cv26-actions{gap:10px}.cv26-check{padding:13px 14px;min-height:52px}.cv26-check-left{gap:10px;font-size:13.5px;line-height:1.4}.cv26-check-icon{width:25px;height:25px;border-radius:8px;font-size:13px}
        .cv26-insight{padding:21px}.cv26-insight-kicker{font-size:10.5px;line-height:1.4}.cv26-insight h3{font-size:20px;line-height:1.3;margin:9px 0 10px}.cv26-insight p,.cv26-insight li{font-size:13.5px;line-height:1.7}.cv26-insight ul{margin-top:10px;margin-bottom:14px;padding-left:22px}.cv26-insight li{margin-bottom:5px}.cv26-confidence{gap:10px}.cv26-evidence{padding:11px 12px;font-size:11px;line-height:1.4}
        .cv26-bar-row{grid-template-columns:135px minmax(0,1fr) 48px;gap:12px;min-height:28px}.cv26-bar-label{font-size:12px;line-height:1.35}.cv26-bar-track{height:9px}.cv26-bar-value{font-size:11px}.cv26-riskdist{height:15px;margin:14px 0 10px}.cv26-legend{gap:18px;font-size:11px;line-height:1.4}
        .cv26-timeline{gap:12px}.cv26-phase{padding:16px;min-height:112px}.cv26-phase span{font-size:10.5px;line-height:1.4}.cv26-phase strong{font-size:14px;line-height:1.35;margin-top:9px}.cv26-phase small{font-size:11.5px;line-height:1.5;margin-top:7px}
        .cv26-action{grid-template-columns:62px minmax(0,1fr) auto;gap:12px;padding:14px}.cv26-priority{padding:6px 9px;font-size:9.5px}.cv26-action strong{font-size:13px;line-height:1.4}.cv26-action small{font-size:11.5px;line-height:1.5;margin-top:5px}.cv26-owner{font-size:10.5px;line-height:1.35}
        @media(max-width:900px){.cv26-title{font-size:27px}.cv26-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.cv26-bar-row{grid-template-columns:120px minmax(0,1fr) 44px}}
        @media(max-width:600px){.cv26-summary,.cv26-card,.cv26-insight{padding:17px}.cv26-title{font-size:24px}.cv26-copy{font-size:13px}.cv26-kpis{grid-template-columns:1fr}.cv26-kpi{min-height:auto}.cv26-bar-row{grid-template-columns:1fr}.cv26-bar-value{text-align:left}.cv26-action{grid-template-columns:1fr}.cv26-owner{justify-self:start}}

        /* Milestone 27.0 — Interactive Engineering Review Workspace */
        .cv27-session{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#f5f9ff);border-radius:22px;padding:18px 20px;margin:0 0 16px;box-shadow:0 12px 30px rgba(37,99,235,.07)}
        .cv27-session-top{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}.cv27-session-title{font-size:20px;font-weight:900;color:#0f172a!important}.cv27-session-sub{font-size:13px;color:#64748b!important;font-weight:650;margin-top:4px}
        .cv27-session-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:14px}.cv27-session-kpi{border:1px solid #dbeafe;background:#fff;border-radius:15px;padding:13px}.cv27-session-kpi span{display:block;font-size:11px;font-weight:850;color:#64748b!important;text-transform:uppercase;letter-spacing:.05em}.cv27-session-kpi strong{display:block;font-size:22px;font-weight:950;color:#0f172a!important;margin-top:6px}
        .cv27-review-progress{height:10px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin-top:14px}.cv27-review-progress i{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:999px}
        .cv27-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}.cv27-summary-card{border:1px solid #e2e8f0;background:#fff;border-radius:15px;padding:13px;text-align:center}.cv27-summary-card span{display:block;font-size:11px;font-weight:800;color:#64748b!important}.cv27-summary-card strong{display:block;font-size:24px;font-weight:950;color:#0f172a!important;margin-top:5px}
        .cv27-rec{border:1px solid #c4b5fd;background:#faf7ff;border-radius:14px;padding:12px 14px;margin:8px 0 12px}.cv27-rec span{font-size:10px;font-weight:900;color:#7c3aed!important;text-transform:uppercase;letter-spacing:.06em}.cv27-rec strong{display:block;font-size:15px;color:#0f172a!important;margin-top:5px}.cv27-rec p{font-size:13px;color:#52647a!important;line-height:1.5;margin:6px 0 0}
        .cv27-evidence{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:10px 0}.cv27-evidence div{border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:10px}.cv27-evidence span{display:block;font-size:10px;font-weight:850;color:#64748b!important;text-transform:uppercase}.cv27-evidence strong{display:block;font-size:13px;font-weight:850;color:#0f172a!important;margin-top:4px;overflow-wrap:anywhere}
        .cv27-saved{display:inline-flex;align-items:center;border:1px solid #a7f3d0;background:#ecfdf5;color:#047857!important;border-radius:999px;padding:6px 10px;font-size:11px;font-weight:900}
        @media(max-width:900px){.cv27-session-grid,.cv27-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.cv27-evidence{grid-template-columns:1fr}}

        /* Milestone 27.2 — Collaborative Review Operations */
        .cv272-action-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:12px 0 14px}
        .cv272-action{border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:14px;box-shadow:0 8px 22px rgba(15,23,42,.04)}
        .cv272-action span{display:block;color:#64748b!important;font-size:11px;font-weight:900;margin-bottom:6px}.cv272-action strong{color:#0f172a!important;font-size:25px;font-weight:980}.cv272-action.bad strong{color:#b91c1c!important}
        .cv272-health{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eff6ff);border-radius:18px;padding:16px;margin-bottom:14px}.cv272-health-top{display:flex;justify-content:space-between;gap:12px;align-items:center}.cv272-health h4{margin:0;color:#0f172a!important;font-size:17px;font-weight:980}.cv272-health p{margin:4px 0 0;color:#64748b!important;font-size:12px;font-weight:750}
        @media(max-width:900px){.cv272-action-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}

        /* Engineering intelligence summary */
        .cv343-context{border:1px solid #bfdbfe;background:linear-gradient(135deg,#ffffff 0%,#f4f8ff 100%);border-radius:18px;padding:15px 16px;margin:0 0 14px;box-shadow:0 10px 26px rgba(37,99,235,.055)}
        .cv343-context-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:12px}.cv343-context-kicker{font-size:10px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;color:#2563eb!important}.cv343-context h3{font-size:17px;margin:4px 0 3px;color:#0f172a!important}.cv343-context p{font-size:12px;line-height:1.5;color:#64748b!important;margin:0}
        .cv343-ready{display:inline-flex;align-items:center;gap:6px;border:1px solid #a7f3d0;background:#ecfdf5;color:#047857!important;border-radius:999px;padding:6px 10px;font-size:10px;font-weight:950;white-space:nowrap}.cv343-ready.warn{border-color:#fde68a;background:#fffbeb;color:#a16207!important}
        .cv343-context-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}.cv343-context-stat{border:1px solid #dbeafe;background:rgba(255,255,255,.86);border-radius:12px;padding:10px}.cv343-context-stat span{display:block;font-size:9px;font-weight:900;letter-spacing:.05em;text-transform:uppercase;color:#64748b!important}.cv343-context-stat strong{display:block;font-size:16px;font-weight:950;color:#0f172a!important;margin-top:4px}.cv343-context-stat small{display:block;font-size:10px;color:#64748b!important;margin-top:3px}
        .cv343-context-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:11px;padding-top:10px;border-top:1px solid #dbeafe}.cv343-context-foot span{font-size:11px;font-weight:800;color:#52647a!important}.cv343-context-foot strong{color:#1d4ed8!important}
        @media(max-width:1100px){.cv343-context-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:700px){.cv343-context-head{display:block}.cv343-ready{margin-top:9px}.cv343-context-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        .cv344-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:12px;margin:0 0 14px}.cv344-card{border:1px solid #e2e8f0;background:#fff;border-radius:18px;padding:15px 16px;box-shadow:0 9px 24px rgba(15,23,42,.04)}.cv344-card h3{font-size:16px;color:#0f172a!important;margin:0 0 4px}.cv344-card>p{font-size:12px;color:#64748b!important;margin:0 0 12px}.cv344-flow{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px;align-items:stretch}.cv344-node{border:1px solid #dbeafe;background:#f8fbff;border-radius:13px;padding:10px;text-align:center}.cv344-node strong{display:block;font-size:18px;color:#0f172a!important}.cv344-node span{display:block;font-size:9px;font-weight:900;letter-spacing:.05em;text-transform:uppercase;color:#64748b!important;margin-top:4px}.cv344-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.cv344-summary div{border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:10px}.cv344-summary span{display:block;font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.05em;color:#64748b!important}.cv344-summary strong{display:block;font-size:13px;color:#0f172a!important;margin-top:5px;overflow-wrap:anywhere}.cv344-summary small{display:block;font-size:10px;color:#64748b!important;margin-top:3px}.cv344-where{margin-top:10px;border-top:1px solid #e2e8f0;padding-top:10px;font-size:11px;color:#52647a!important}.cv344-where strong{color:#1d4ed8!important}@media(max-width:1000px){.cv344-grid{grid-template-columns:1fr}.cv344-flow{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:650px){.cv344-flow,.cv344-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}


        /* Milestone 28.0 — Deep Engineering Review Workspace */
        .cv28-empty{border:1px dashed #93c5fd;background:linear-gradient(135deg,#fff,#eff6ff);border-radius:18px;padding:22px;margin:12px 0 16px;text-align:center}
        .cv28-empty h4{margin:0 0 7px;color:#0f172a!important;font-size:18px;font-weight:900}.cv28-empty p{margin:0 auto;color:#64748b!important;font-size:13px;line-height:1.55;max-width:720px}
        .cv28-review-head{display:grid;grid-template-columns:minmax(0,1.2fr) repeat(4,minmax(110px,.55fr));gap:10px;align-items:stretch;margin:10px 0 12px}
        .cv28-review-main,.cv28-review-stat{border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:13px 14px;box-shadow:0 8px 22px rgba(15,23,42,.035)}
        .cv28-review-main span,.cv28-review-stat span{display:block;color:#64748b!important;font-size:10px;font-weight:900;letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px}
        .cv28-review-main strong{display:block;color:#0f172a!important;font-size:17px;font-weight:950}.cv28-review-main p{color:#64748b!important;font-size:12px;line-height:1.45;margin:5px 0 0}
        .cv28-review-stat strong{display:block;color:#0f172a!important;font-size:18px;font-weight:950}.cv28-review-stat small{display:block;color:#64748b!important;font-size:11px;margin-top:4px;overflow-wrap:anywhere}
        .cv28-badge-row{display:flex;gap:7px;flex-wrap:wrap;margin:9px 0 3px}.cv28-badge{display:inline-flex;align-items:center;border-radius:999px;padding:5px 9px;border:1px solid #dbeafe;background:#eff6ff;color:#1d4ed8!important;font-size:10px;font-weight:900}
        .cv28-badge.good{border-color:#a7f3d0;background:#ecfdf5;color:#047857!important}.cv28-badge.warn{border-color:#fde68a;background:#fffbeb;color:#a16207!important}.cv28-badge.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c!important}
        .cv28-confidence{border:1px solid #c4b5fd;background:linear-gradient(135deg,#fff,#faf7ff);border-radius:17px;padding:15px;margin:10px 0}.cv28-confidence-top{display:flex;align-items:center;justify-content:space-between;gap:12px}.cv28-confidence span{color:#7c3aed!important;font-size:10px;font-weight:950;letter-spacing:.07em;text-transform:uppercase}.cv28-confidence strong{color:#0f172a!important;font-size:22px;font-weight:950}.cv28-confidence p{color:#52647a!important;font-size:12px;line-height:1.55;margin:8px 0 0}
        .cv28-evidence-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:10px 0}.cv28-evidence-card{border:1px solid #e2e8f0;background:#f8fafc;border-radius:14px;padding:12px}.cv28-evidence-card span{display:block;color:#64748b!important;font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}.cv28-evidence-card strong{display:block;color:#0f172a!important;font-size:13px;font-weight:900;overflow-wrap:anywhere}.cv28-evidence-card small{display:block;color:#64748b!important;font-size:11px;line-height:1.4;margin-top:5px}
        .cv28-link-row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.cv28-link{display:inline-flex;text-decoration:none!important;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8!important;border-radius:10px;padding:8px 11px;font-size:11px;font-weight:900}
        .cv28-history{display:grid;gap:8px;margin-top:8px}.cv28-history-item{border-left:3px solid #93c5fd;background:#f8fafc;border-radius:0 12px 12px 0;padding:10px 12px}.cv28-history-item strong{display:block;color:#0f172a!important;font-size:12px}.cv28-history-item span{display:block;color:#64748b!important;font-size:10px;margin-top:3px}.cv28-history-item p{color:#475569!important;font-size:11px;line-height:1.45;margin:5px 0 0}
        div[data-testid="stExpander"]{border:1px solid #dbe3ef!important;border-radius:15px!important;background:#fff!important;box-shadow:0 7px 18px rgba(15,23,42,.035)!important;margin-bottom:9px!important;overflow:hidden}
        div[data-testid="stExpander"] summary{min-height:48px!important;padding:8px 13px!important;font-size:13px!important;font-weight:850!important}
        .cv272-action{min-height:72px!important;padding:11px 13px!important}.cv272-action strong{font-size:21px!important}.cv272-health{padding:13px 15px!important;margin:10px 0!important}.cv27-summary-card{min-height:70px!important;padding:11px!important}.cv27-session-kpi{min-height:72px!important;padding:11px 13px!important}
        @media(max-width:1100px){.cv28-review-head{grid-template-columns:repeat(2,minmax(0,1fr))}.cv28-review-main{grid-column:1/-1}.cv28-evidence-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:700px){.cv28-review-head,.cv28-evidence-grid{grid-template-columns:1fr}}

</style>
        """,
        unsafe_allow_html=True,
    )

    if not analysis_id:
        st.error("No analysis was selected. Open one saved analysis from the Saved BOM Manager.")
        return

    user_id = current_user.get("id")
    try:
        analysis_query = (
            supabase.table("analyses")
            .select("*")
            .eq("user_id", user_id)
            .eq("id", analysis_id)
        )
        if workspace_id:
            analysis_query = analysis_query.eq("workspace_id", workspace_id)
        response = analysis_query.limit(1).execute()
        analysis = (response.data or [None])[0]
    except Exception as exc:
        st.error(f"Could not load this analysis: {exc}")
        return
    if not analysis:
        st.warning("This saved analysis could not be found, or you do not have access to it.")
        return

    parts = _query_table(
        supabase,
        "analysis_parts",
        user_id=user_id,
        analysis_id=analysis_id,
        workspace_id=workspace_id,
    )
    alerts = _query_table(
        supabase,
        "monitor_alerts",
        user_id=user_id,
        analysis_id=analysis_id,
        workspace_id=workspace_id,
        order="created_at",
        limit=50,
    )
    alternatives = _query_table(
        supabase,
        "alternative_recommendations",
        user_id=user_id,
        analysis_id=analysis_id,
        workspace_id=workspace_id,
        order="created_at",
        limit=50,
    )

    comments, comments_error = list_analysis_comments(
        supabase,
        workspace_id or "",
        analysis_id,
    )
    followers, followers_error = list_analysis_followers(
        supabase,
        workspace_id=workspace_id or "",
        analysis_id=analysis_id,
    )
    is_following, following_error = is_following_analysis(
        supabase,
        workspace_id=workspace_id or "",
        analysis_id=analysis_id,
        user_id=user_id,
    )
    workspace_members = workspace_members or []
    can_manage_discussion = str(workspace_role or "viewer").lower() in {
        "owner",
        "admin",
    }

    project = _safe(analysis.get("project_name") or analysis.get("filename"), "Saved BOM Analysis")
    filename = _safe(analysis.get("filename"))
    health = _num(analysis.get("health_score"))
    high = _num(analysis.get("high_risk_count"))
    medium = _num(analysis.get("medium_risk_count"))
    low = _num(analysis.get("low_risk_count"))
    total_parts = _num(analysis.get("total_parts"), len(parts)) or len(parts)
    created = analysis.get("created_at")
    risk_status = "Review Recommended" if health < 80 or high else "Healthy"
    health_cls = _health_class(health)
    advisor = build_engineering_supply_advisor(
        analysis=analysis,
        parts=parts,
        alerts=alerts,
        alternatives=alternatives,
    )
    engineering_context = build_engineering_context(
        supabase=supabase,
        analysis=analysis,
        user_id=user_id,
        workspace_id=workspace_id or "",
        parts=parts,
        alerts=alerts,
        alternatives=alternatives,
        comments=comments,
        followers=followers,
    )
    context_summary = engineering_context.summary
    context_coverage = engineering_context.coverage
    knowledge_graph = build_knowledge_graph(
        supabase=supabase,
        context=engineering_context,
        user_id=user_id,
        workspace_id=workspace_id or "",
    )
    graph_summary = knowledge_graph.summary
    graph_counts = graph_summary.get("counts") or {}

    st.markdown('<a class="cv-analysis-back" href="?page=BOM%20Analyzer" target="_self">' + _lucide("arrow-left",16) + ' Back to BOM Analyzer</a>', unsafe_allow_html=True)
    st.markdown(
        f'''<div class="cv-analysis-hero"><div><div class="cv-analysis-eyebrow">{_lucide('layers',14)} Analysis Workspace</div><h1 class="cv-analysis-title">{html.escape(project)}</h1><p class="cv-analysis-sub">A permanent engineering record for this saved BOM analysis. Use the tabs below to review one focused area at a time without losing your place.</p><div class="cv-analysis-actions"><a class="cv-analysis-btn primary" href="?page=BOM%20Analyzer&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Open in BOM Analyzer →</a><a class="cv-analysis-btn" href="?page=Alternative%20Finder&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Find Alternatives</a><a class="cv-analysis-btn" href="?page=Monitoring&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Monitor Components</a><a class="cv-analysis-btn" href="?page=Reports&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Reports Center</a></div></div><div class="cv-analysis-summary"><div class="cv-analysis-mini"><span>Health</span><strong>{health}</strong><small>{risk_status}</small></div><div class="cv-analysis-mini"><span>Parts</span><strong>{total_parts}</strong><small>{html.escape(filename)}</small></div><div class="cv-analysis-mini"><span>High Risk</span><strong>{high}</strong><small>Components needing review</small></div><div class="cv-analysis-mini"><span>Updated</span><strong>{_relative_date(created)}</strong><small>{_date(created)}</small></div></div></div>''',
        unsafe_allow_html=True,
    )

    (
        advisor_tab,
        overview_tab,
        intelligence_tab,
        components_tab,
        alternatives_tab,
        discussions_tab,
        timeline_tab,
        reports_tab,
    ) = st.tabs([
        "Engineering Intelligence",
        "Overview",
        "Intelligence",
        "Components",
        "Alternatives",
        "Discussions",
        "Timeline",
        "Reports",
    ])

    lifecycle_exposed_parts = []
    no_stock_parts = []
    limited_source_parts = []
    long_lead_parts = []
    ranked_parts = []

    for part in parts:
        lifecycle_text = _safe(
            _part_value(part, "lifecycle_status", "Lifecycle Status"),
            "Unknown",
        ).lower()
        stock_value = _num(
            _part_value(part, "stock_available", "Stock Available"),
            0,
        )
        source_count = _num(
            _part_value(part, "supplier_count", "Supplier Count"),
            0,
        )
        lead_time_value = _num(
            _part_value(part, "lead_time_weeks", "Lead Time Weeks"),
            0,
        )
        risk_score_value = _num(
            _part_value(part, "risk_score", "Risk Score"),
            0,
        )
        mpn_value = _safe(_part_value(part, "mpn", "MPN"), "Unknown MPN")
        manufacturer_value = _safe(
            _part_value(part, "manufacturer", "Manufacturer"),
            "Unknown manufacturer",
        )
        reason_value = _safe(
            _part_value(part, "risk_reasons", "Risk Reasons", "risk_reason"),
            "Recorded engineering risk requires review.",
        )

        if any(
            token in lifecycle_text
            for token in (
                "obsolete",
                "end of life",
                "eol",
                "replacement",
                "not recommended",
                "nrnd",
            )
        ):
            lifecycle_exposed_parts.append(part)
        if stock_value <= 0:
            no_stock_parts.append(part)
        if source_count <= 1:
            limited_source_parts.append(part)
        if lead_time_value >= 12:
            long_lead_parts.append(part)

        ranked_parts.append(
            {
                "mpn": mpn_value,
                "manufacturer": manufacturer_value,
                "risk_score": risk_score_value,
                "risk_level": _risk_label(part),
                "reason": reason_value,
                "stock": stock_value,
                "sources": source_count,
                "lifecycle": _safe(
                    _part_value(part, "lifecycle_status", "Lifecycle Status"),
                    "Unknown",
                ),
            }
        )

    ranked_parts.sort(
        key=lambda row: (
            _num(row.get("risk_score"), 0),
            1 if _risk_class(row.get("risk_level"), row.get("risk_score")) == "bad" else 0,
        ),
        reverse=True,
    )

    engineering_readiness = max(
        0,
        min(
            100,
            round(
                (health * 0.60)
                + (max(0, 100 - min(100, high * 12 + medium * 4)) * 0.25)
                + (_num(advisor.get("confidence"), 0) * 0.15)
            ),
        ),
    )
    readiness_class = _health_class(engineering_readiness)
    release_posture = (
        "Ready for controlled release"
        if engineering_readiness >= 85 and high == 0
        else "Focused engineering review"
        if engineering_readiness >= 65
        else "Release hold recommended"
    )
    top_ranked_part = ranked_parts[0] if ranked_parts else None

    with advisor_tab:
        _section_header("Executive Decision Cockpit", "Release readiness, risk drivers, evidence coverage, and next actions.")
        assessment = _safe(advisor.get("overall_assessment"), "Focused Review Recommended")
        confidence = _num(advisor.get("confidence"), 0)
        metrics = advisor.get("metrics") or {}
        saved_alternatives = _num(metrics.get("saved_alternatives"), len(alternatives))
        lifecycle_count, stock_count = len(lifecycle_exposed_parts), len(no_stock_parts)
        source_count, lead_count = len(limited_source_parts), len(long_lead_parts)

        if high >= 3 or health < 55:
            release_recommendation, cockpit_status, cockpit_class = "Hold Release", "Release hold recommended", "bad"
        elif high > 0 or health < 80 or lifecycle_count > 0:
            release_recommendation, cockpit_status, cockpit_class = "Focused Review", "Focused engineering review", "warn"
        else:
            release_recommendation, cockpit_status, cockpit_class = "Controlled Release", "Ready for controlled release", "good"

        engineering_readiness = max(0, min(100, round((health * .60) + (max(0, 100 - min(100, high * 12 + medium * 4)) * .25) + (confidence * .15))))
        readiness_class = _health_class(engineering_readiness)
        readiness_label = "Excellent" if engineering_readiness >= 90 else "Strong" if engineering_readiness >= 75 else "Needs attention" if engineering_readiness >= 55 else "At risk"
        lifecycle_health = max(0, round(100 - lifecycle_count / max(1, total_parts) * 100))
        inventory_coverage = max(0, round(100 - stock_count / max(1, total_parts) * 100))
        supplier_diversity = max(0, round(100 - source_count / max(1, total_parts) * 100))
        engineering_review = max(0, min(100, round((engineering_readiness + confidence) / 2)))

        checklist = [("Lifecycle validated", lifecycle_count == 0), ("Inventory reviewed", stock_count == 0), ("Alternatives reviewed", saved_alternatives > 0), ("Supplier diversity verified", source_count == 0), ("Procurement signoff", confidence >= 85 and stock_count == 0), ("Engineering approval", high == 0 and lifecycle_count == 0)]
        checklist_complete = sum(1 for _, done in checklist if done)
        checklist_percent = round(checklist_complete / len(checklist) * 100)
        top_ranked_part = ranked_parts[0] if ranked_parts else None
        primary_part = _safe(top_ranked_part.get("mpn") if top_ranked_part else None, "No critical component")
        primary_reason = _safe(top_ranked_part.get("reason") if top_ranked_part else None, "No component-level risk explanation is currently available.")

        # Milestone 27.1 — persistent, resumable engineering review workflow.
        review_key = f"cv271_review_{analysis_id}"
        reviewer_name = _safe(
            current_user.get("full_name") or current_user.get("name") or current_user.get("email"),
            "Current reviewer",
        )
        reviewer_email = _safe(current_user.get("email"), "")
        review_parts = ranked_parts[:5]
        total_review_items = len(review_parts)
        editable_roles = {"owner", "admin", "editor", "member"}
        role_text = str(workspace_role or "viewer").lower()
        can_edit_review = role_text in editable_roles or not workspace_id
        can_manage_review = role_text in {"owner", "admin"} or not workspace_id

        # Load the latest review session and its items from Supabase once per rerun.
        review_session, review_session_error = get_latest_review_session(
            supabase,
            analysis_id=analysis_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        review_items = []
        review_items_error = None
        review_events = []
        review_events_error = None
        if review_session:
            review_items, review_items_error = list_review_items(
                supabase,
                session_id=review_session.get("id"),
                user_id=user_id,
                workspace_id=workspace_id,
            )
            review_events, review_events_error = list_review_events(
                supabase,
                analysis_id=analysis_id,
                user_id=user_id,
                workspace_id=workspace_id,
                limit=250,
            )

        review_db_unavailable = bool(review_session_error and "does not exist" in review_session_error.lower())
        if review_db_unavailable:
            st.warning(
                "Engineering review persistence is not enabled yet. Run the Milestone 27.1 Supabase migration, then refresh this page."
            )
        elif review_session_error:
            st.warning(f"Engineering review data could not be loaded: {review_session_error}")

        decision_map = {
            _safe(row.get("mpn"), "Unknown MPN"): row
            for row in review_items
        }
        reviewed_count = sum(
            1
            for part in review_parts
            if decision_map.get(_safe(part.get("mpn"), "Unknown MPN"), {}).get("decision")
            in ("Approve", "Needs Investigation", "Reject")
        )
        review_percent = round(reviewed_count / max(1, total_review_items) * 100)
        session_status = _safe(review_session.get("status") if review_session else None, "not_started")
        session_locked = bool(review_session and review_session.get("is_locked"))
        session_active = bool(review_session and session_status in {"active", "completed"})

        if not session_active:
            start_col, note_col = st.columns([0.28, 0.72])
            with start_col:
                start_disabled = not can_edit_review or review_db_unavailable
                start_label = "Resume Engineering Review" if session_status == "paused" else "Start Engineering Review"
                if st.button(
                    start_label,
                    type="primary",
                    use_container_width=True,
                    key=f"cv271_start_{analysis_id}",
                    disabled=start_disabled,
                ):
                    created_session, create_error = create_review_session(
                        supabase,
                        analysis_id=analysis_id,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        reviewer_name=reviewer_name,
                        reviewer_email=reviewer_email,
                        total_items=total_review_items,
                    )
                    if create_error:
                        st.error(f"Could not start the review: {create_error}")
                    else:
                        st.session_state[review_key] = created_session
                        st.rerun()
            with note_col:
                permission_note = (
                    "You have read-only access to this engineering review."
                    if not can_edit_review
                    else (
                        f"Resume your saved review. {reviewed_count} of {total_review_items} components are already reviewed."
                        if session_status == "paused"
                        else "The session is saved to Supabase and can be resumed from another browser or device."
                    )
                )
                st.markdown(
                    f'<div class="cv27-session"><div class="cv27-session-title">Persistent Engineering Review</div>'
                    f'<div class="cv27-session-sub">{html.escape(permission_note)}</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            started_display = _relative_date(review_session.get("started_at"))
            updated_display = _relative_date(review_session.get("updated_at"))
            remaining = max(0, total_review_items - reviewed_count)
            lock_label = "Locked" if session_locked else "Saved to Supabase"
            st.markdown(
                f'''<section class="cv27-session"><div class="cv27-session-top"><div><div class="cv27-session-title">{'Completed' if session_status == 'completed' else 'Engineering'} Review Session</div><div class="cv27-session-sub">Persistent review · last updated {html.escape(updated_display)}</div></div><span class="cv27-saved">{lock_label}</span></div><div class="cv27-session-grid"><div class="cv27-session-kpi"><span>Progress</span><strong>{reviewed_count}/{total_review_items}</strong></div><div class="cv27-session-kpi"><span>Remaining</span><strong>{remaining}</strong></div><div class="cv27-session-kpi"><span>Reviewer</span><strong style="font-size:15px">{html.escape(_safe(review_session.get('reviewer_name'), reviewer_name))}</strong></div><div class="cv27-session-kpi"><span>Started</span><strong style="font-size:15px">{html.escape(started_display)}</strong></div></div><div class="cv27-review-progress"><i style="width:{review_percent}%"></i></div></section>''',
                unsafe_allow_html=True,
            )

            counts = {"Approve": 0, "Needs Investigation": 0, "Reject": 0, "Skip": 0}
            for row in review_items:
                decision_value = row.get("decision")
                if decision_value in counts:
                    counts[decision_value] += 1
            st.markdown(
                f'''<div class="cv27-summary"><div class="cv27-summary-card"><span>Approved</span><strong>{counts["Approve"]}</strong></div><div class="cv27-summary-card"><span>Investigate</span><strong>{counts["Needs Investigation"]}</strong></div><div class="cv27-summary-card"><span>Rejected</span><strong>{counts["Reject"]}</strong></div><div class="cv27-summary-card"><span>Skipped</span><strong>{counts["Skip"]}</strong></div></div>''',
                unsafe_allow_html=True,
            )

            if review_items_error:
                st.warning(f"Saved review items could not be loaded: {review_items_error}")

            # Milestone 28.1 — shared collaborative workflow rules.
            today = date.today()
            workflow = summarize_review_workflow(
                review_items,
                reviewer_email=reviewer_email,
                total_items=total_review_items,
                today=today,
            )
            open_rows = workflow["open_rows"]
            overdue_rows = workflow["overdue_rows"]
            due_week_rows = workflow["due_week_rows"]
            assigned_me_rows = workflow["assigned_me_rows"]
            waiting_rows = workflow["waiting_rows"]
            completed_today = workflow["completed_today"]
            unassigned_count = workflow["unassigned_count"]
            workflow_health = workflow["workflow_health"]
            action_html = f'<div class="cv272-action-grid"><div class="cv272-action"><span>Assigned to Me</span><strong>{len(assigned_me_rows)}</strong></div><div class="cv272-action"><span>Due This Week</span><strong>{len(due_week_rows)}</strong></div><div class="cv272-action {"bad" if overdue_rows else ""}"><span>Overdue</span><strong>{len(overdue_rows)}</strong></div><div class="cv272-action"><span>Waiting on Others</span><strong>{len(waiting_rows)}</strong></div><div class="cv272-action"><span>Completed Today</span><strong>{len(completed_today)}</strong></div></div><section class="cv272-health"><div class="cv272-health-top"><div><h4>Review Health</h4><p>{len(overdue_rows)} overdue · {unassigned_count} unassigned · {reviewed_count} completed</p></div><strong style="font-size:26px">{workflow_health}%</strong></div><div class="cv27-review-progress"><i style="width:{workflow_health}%"></i></div></section>'
            st.markdown(action_html, unsafe_allow_html=True)

            if total_review_items == 0:
                st.markdown(
                    f'''<section class="cv28-empty"><h4>No engineering review queue has been generated</h4><p>Cadivor creates review items from component-level risk, lifecycle, supplier, inventory, lead-time, and alternative evidence. Reopen this BOM in the Analyzer and rerun or save the analysis to attach component records.</p><a class="cv28-link" href="?page=BOM%20Analyzer&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Open BOM Analyzer</a></section>''',
                    unsafe_allow_html=True,
                )

            member_options = [("Unassigned", "", "")]
            for member in workspace_members:
                member_name = _safe(member.get("full_name") or member.get("name") or member.get("email"), "Workspace member")
                member_email = _safe(member.get("email"), "")
                member_id = _safe(member.get("user_id") or member.get("id"), "")
                if member_email or member_id:
                    member_options.append((member_name, member_email, member_id))
            if reviewer_email and not any(x[1].lower() == reviewer_email.lower() for x in member_options if x[1]):
                member_options.append((reviewer_name, reviewer_email, user_id))
            member_labels = [x[0] + (f" · {x[1]}" if x[1] else "") for x in member_options]

            f1,f2,f3,f4 = st.columns(4)
            status_filter = f1.selectbox("Review status", ["All", "Open", "Completed", "Overdue"], key=f"cv272_status_{analysis_id}")
            assignee_filter = f2.selectbox("Assignee", ["All", "Assigned to me", "Unassigned"] + member_labels[1:], key=f"cv272_assignee_{analysis_id}")
            priority_filter = f3.selectbox("Priority", ["All", "High", "Medium", "Low"], key=f"cv272_priority_{analysis_id}")
            decision_filter = f4.selectbox("Decision", ["All", "Approve", "Needs Investigation", "Reject", "Skip", "Not reviewed"], key=f"cv272_decision_filter_{analysis_id}")
            unresolved_only = st.checkbox(
                "Show unresolved only",
                value=False,
                key=f"cv281_unresolved_{analysis_id}",
                help="Includes open, investigation, rejected, unassigned, and overdue items.",
            )
            filtered_review_parts = []
            for candidate in review_parts:
                c_mpn = _safe(candidate.get("mpn"), "Unknown MPN")
                c_saved = decision_map.get(c_mpn, {})
                c_decision = c_saved.get("decision") or "Not reviewed"
                c_due = parse_due_date(c_saved, today=today)
                c_score = _num(candidate.get("risk_score"),0)
                c_priority = "High" if c_score >= 70 else "Medium" if c_score >= 35 else "Low"
                is_completed = c_decision in {"Approve","Reject","Skip"}
                if status_filter == "Open" and is_completed: continue
                if status_filter == "Completed" and not is_completed: continue
                if status_filter == "Overdue" and not (c_due and c_due < today and not is_completed): continue
                if assignee_filter == "Assigned to me" and str(c_saved.get("assignee_email") or "").lower() != reviewer_email.lower(): continue
                if assignee_filter == "Unassigned" and c_saved.get("assignee_name"): continue
                saved_assignee_label = _safe(c_saved.get("assignee_name"),"") + (f" · {c_saved.get('assignee_email')}" if c_saved.get("assignee_email") else "")
                if assignee_filter not in {"All","Assigned to me","Unassigned"} and assignee_filter != saved_assignee_label: continue
                if priority_filter != "All" and c_priority != priority_filter: continue
                if decision_filter != "All" and c_decision != decision_filter: continue
                if unresolved_only and not is_unresolved_review(c_saved, today=today): continue
                filtered_review_parts.append(candidate)
            st.caption(f"Showing {len(filtered_review_parts)} of {len(review_parts)} review items")
            for review_index, part in enumerate(filtered_review_parts, 1):
                mpn = _safe(part.get("mpn"), "Unknown MPN")
                saved = decision_map.get(mpn, {})
                status_label = saved.get("decision") or "Not reviewed"
                updated_label = _relative_date(saved.get("updated_at")) if saved else "Not saved"
                saved_priority = _safe(saved.get("priority"), "High" if _num(part.get("risk_score"), 0) >= 70 else "Medium" if _num(part.get("risk_score"), 0) >= 35 else "Low")
                saved_assignee = _safe(saved.get("assignee_name"), "Unassigned")
                saved_due = _safe(saved.get("due_label"), "No due date")
                with st.expander(
                    f"{review_index}. {mpn} · {status_label} · {saved_priority} · {saved_assignee} · {saved_due}",
                    expanded=(review_index == 1 and reviewed_count == 0),
                ):
                    st.caption(f"Component {review_index} of {len(filtered_review_parts)}")
                    risk_score = _num(part.get("risk_score"), 0)
                    suggested = "Needs Investigation" if risk_score >= 35 else "Approve"
                    rec_reason = _safe(
                        part.get("reason"),
                        "Review recorded engineering evidence before approval.",
                    )
                    recommendation_confidence = max(0, min(100, 100 - abs(risk_score - 50)))
                    risk_class = _risk_class(part.get("risk_level"), risk_score)
                    lifecycle_value = _safe(part.get("lifecycle"), "Unknown")
                    stock_value = _num(part.get("stock"), 0)
                    supplier_value = _num(part.get("sources"), 0)
                    due_badge_class = "bad" if saved.get("due_date") and str(saved.get("due_date"))[:10] < today.isoformat() and status_label not in {"Approve", "Reject", "Skip"} else "warn"
                    st.markdown(
                        f'''<div class="cv28-review-head"><div class="cv28-review-main"><span>Component Under Review</span><strong>{html.escape(mpn)}</strong><p>{html.escape(_safe(part.get("manufacturer"), "Unknown manufacturer"))}</p><div class="cv28-badge-row"><span class="cv28-badge {risk_class}">{html.escape(_safe(part.get("risk_level"), "Low"))} risk</span><span class="cv28-badge">{html.escape(saved_priority)} priority</span><span class="cv28-badge {"good" if status_label == "Approve" else "bad" if status_label == "Reject" else "warn"}">{html.escape(status_label)}</span></div></div><div class="cv28-review-stat"><span>Assignee</span><strong>{html.escape(saved_assignee)}</strong><small>{html.escape(_safe(saved.get("assignee_email"), "No member assigned"))}</small></div><div class="cv28-review-stat"><span>Due</span><strong>{html.escape(saved_due)}</strong><small>{html.escape(_date(saved.get("due_date"))) if saved.get("due_date") else "No calendar deadline"}</small></div><div class="cv28-review-stat"><span>Last Saved</span><strong>{html.escape(updated_label)}</strong><small>{html.escape(_safe(saved.get("reviewer_name"), "Not reviewed"))}</small></div><div class="cv28-review-stat"><span>Decision</span><strong>{html.escape(status_label)}</strong><small>Persistent audit record</small></div></div><div class="cv28-confidence"><div class="cv28-confidence-top"><div><span>Cadivor Recommendation</span><strong>{html.escape(suggested)}</strong></div><strong>{recommendation_confidence}%</strong></div><p>{html.escape(rec_reason)}</p></div><div class="cv28-evidence-grid"><div class="cv28-evidence-card"><span>Lifecycle Evidence</span><strong>{html.escape(lifecycle_value)}</strong><small>{"Lifecycle action is required." if any(x in lifecycle_value.lower() for x in ("obsolete","replacement","eol","nrnd")) else "No severe lifecycle state recorded."}</small></div><div class="cv28-evidence-card"><span>Inventory Evidence</span><strong>{stock_value:,} available</strong><small>{"No recorded stock is available." if stock_value <= 0 else "Recorded inventory is available."}</small></div><div class="cv28-evidence-card"><span>Supplier Coverage</span><strong>{supplier_value} source(s)</strong><small>{"Single-source exposure requires validation." if supplier_value <= 1 else "Multiple recorded sources improve resilience."}</small></div><div class="cv28-evidence-card"><span>Risk Score</span><strong>{risk_score}/100</strong><small>Component-level release exposure.</small></div><div class="cv28-evidence-card"><span>Alternative Evidence</span><strong>{"Available" if alternatives else "Not linked"}</strong><small>Open Alternative Finder to evaluate candidates.</small></div><div class="cv28-evidence-card"><span>Monitoring Evidence</span><strong>{len([a for a in alerts if _safe(a.get("mpn") or a.get("part_number"), "") == mpn])} alert(s)</strong><small>Recorded monitoring changes for this component.</small></div></div><div class="cv28-link-row"><a class="cv28-link" href="{html.escape(_alternative_url(mpn, analysis_id), quote=True)}" target="_self">Compare Alternatives</a><a class="cv28-link" href="{html.escape(_monitor_url(mpn, analysis_id), quote=True)}" target="_self">Open Monitoring</a></div>''',
                        unsafe_allow_html=True,
                    )
                    col_decision, col_owner, col_due = st.columns([1.15, 1, 1])
                    options = ["Approve", "Needs Investigation", "Reject", "Skip"]
                    current_decision = saved.get("decision") if saved.get("decision") in options else suggested
                    owner_options = ["Electrical", "Procurement", "Supply Chain", "Firmware", "Quality", "General Engineering"]
                    current_owner = saved.get("owner") if saved.get("owner") in owner_options else "General Engineering"
                    due_options = ["No due date", "Today", "Tomorrow", "This Week", "Next Week", "Next Sprint", "Custom"]
                    current_due = saved.get("due_label") if saved.get("due_label") in due_options else "This Week"
                    disabled = session_locked or not can_edit_review
                    with col_decision:
                        decision_value = st.selectbox(
                            "Decision",
                            options,
                            index=options.index(current_decision),
                            key=f"cv271_decision_{analysis_id}_{review_index}",
                            disabled=disabled,
                        )
                    with col_owner:
                        owner_value = st.selectbox(
                            "Owner",
                            owner_options,
                            index=owner_options.index(current_owner),
                            key=f"cv271_owner_{analysis_id}_{review_index}",
                            disabled=disabled,
                        )
                    with col_due:
                        due_value = st.selectbox(
                            "Due",
                            due_options,
                            index=due_options.index(current_due),
                            key=f"cv271_due_{analysis_id}_{review_index}",
                            disabled=disabled,
                        )
                    saved_assignee_label = _safe(saved.get("assignee_name"), "Unassigned") + (f" · {saved.get('assignee_email')}" if saved.get("assignee_email") else "")
                    assignee_index = member_labels.index(saved_assignee_label) if saved_assignee_label in member_labels else 0
                    assign_col, priority_col = st.columns([1.35, .65])
                    assignee_label = assign_col.selectbox("Assigned workspace member", member_labels, index=assignee_index, key=f"cv272_assignee_item_{analysis_id}_{review_index}", disabled=disabled)
                    selected_member = member_options[member_labels.index(assignee_label)]
                    priority_options = ["High", "Medium", "Low"]
                    default_priority = saved.get("priority") if saved.get("priority") in priority_options else ("High" if risk_score >= 70 else "Medium" if risk_score >=35 else "Low")
                    priority_value = priority_col.selectbox("Priority", priority_options, index=priority_options.index(default_priority), key=f"cv272_priority_item_{analysis_id}_{review_index}", disabled=disabled)
                    due_date_value = saved.get("due_date")
                    if due_value == "Custom":
                        default_custom = date.fromisoformat(str(due_date_value)[:10]) if due_date_value else today + timedelta(days=7)
                        due_date_value = st.date_input("Custom due date", value=default_custom, key=f"cv272_custom_due_{analysis_id}_{review_index}", disabled=disabled).isoformat()
                    elif due_value == "No due date":
                        due_date_value = None
                    else:
                        due_date_value = {"Today":today,"Tomorrow":today+timedelta(days=1),"This Week":today+timedelta(days=7),"Next Week":today+timedelta(days=14),"Next Sprint":today+timedelta(days=21)}[due_value].isoformat()
                    note_value = st.text_area(
                        "Engineering Notes",
                        value=_safe(saved.get("notes"), "") if saved else "",
                        placeholder="Record validation evidence, assumptions, and follow-up actions.",
                        key=f"cv271_notes_{analysis_id}_{review_index}",
                        disabled=disabled,
                    )

                    # Streamlit reruns after widget changes. Persist only when values differ.
                    changed = (
                        decision_value != saved.get("decision")
                        or owner_value != saved.get("owner")
                        or due_value != saved.get("due_label")
                        or note_value.strip() != _safe(saved.get("notes"), "").strip()
                        or selected_member[1] != _safe(saved.get("assignee_email"), "")
                        or priority_value != _safe(saved.get("priority"), default_priority)
                        or (due_date_value or "") != _safe(saved.get("due_date"), "")
                    )
                    selected_assignee_name = selected_member[0] if selected_member[0] != "Unassigned" else ""
                    can_save_decision, validation_error, validation_warning = validate_review_decision(
                        decision=decision_value,
                        notes=note_value,
                        assignee_name=selected_assignee_name,
                        risk_score=risk_score,
                        lifecycle=lifecycle_value,
                    )
                    if validation_error and changed and not disabled:
                        st.warning(validation_error)
                    elif validation_warning and changed and not disabled:
                        st.warning(validation_warning)

                    if changed and not disabled and can_save_decision:
                        st.caption("Saving…")
                        saved_item, save_error = save_review_item(
                            supabase,
                            session_id=review_session.get("id"),
                            analysis_id=analysis_id,
                            user_id=user_id,
                            workspace_id=workspace_id,
                            mpn=mpn,
                            manufacturer=_safe(part.get("manufacturer"), ""),
                            decision=decision_value,
                            owner=owner_value,
                            due_label=due_value,
                            due_date=due_date_value,
                            assignee_name=selected_assignee_name,
                            assignee_email=selected_member[1],
                            assignee_user_id=selected_member[2],
                            priority=priority_value,
                            notes=note_value.strip(),
                            reviewer_name=reviewer_name,
                            reviewer_email=reviewer_email,
                            recommendation=suggested,
                            recommendation_confidence=max(0, min(100, 100 - abs(risk_score - 50))),
                            evidence={
                                "risk_score": risk_score,
                                "lifecycle": _safe(part.get("lifecycle"), "Unknown"),
                                "stock": _num(part.get("stock"), 0),
                                "supplier_sources": _num(part.get("sources"), 0),
                                "reason": rec_reason,
                            },
                        )
                        if save_error:
                            st.error(f"Save failed for {mpn}: {save_error}")
                        elif saved_item:
                            st.caption("Saved just now")
                            st.rerun()
                    elif saved:
                        st.caption(f"Saved by {_safe(saved.get('reviewer_name'), reviewer_name)} · {updated_label}")

                    component_history = [
                        event for event in review_events
                        if mpn.lower() in (
                            _safe(event.get("title"), "") + " " + _safe(event.get("body"), "")
                        ).lower()
                    ][:6]
                    if component_history:
                        history_html = []
                        for event in component_history:
                            history_html.append(
                                f'<div class="cv28-history-item"><strong>{html.escape(_safe(event.get("title"), "Engineering review activity"))}</strong>'
                                f'<span>{html.escape(_safe(event.get("actor_name"), "Cadivor user"))} · {html.escape(_relative_date(event.get("created_at")))}</span>'
                                f'<p>{html.escape(_safe(event.get("body"), ""))}</p></div>'
                            )
                        with st.expander("Decision history", expanded=False):
                            st.markdown('<div class="cv28-history">' + "".join(history_html) + '</div>', unsafe_allow_html=True)

                    if saved.get("id"):
                        with st.expander("Component discussion", expanded=False):
                            review_comments, comment_error = list_review_comments(supabase, review_item_id=saved.get("id"), user_id=user_id, workspace_id=workspace_id)
                            if comment_error:
                                st.warning(f"Comments unavailable: {comment_error}")
                            for comment in review_comments:
                                st.markdown(f"**{html.escape(_safe(comment.get('author_name'),'Reviewer'))}** · {_relative_date(comment.get('created_at'))}")
                                st.write(_safe(comment.get("body"), ""))
                            with st.form(f"cv272_comment_form_{analysis_id}_{review_index}", clear_on_submit=True):
                                comment_body = st.text_area("Add comment", placeholder="Ask a question, add evidence, or explain the decision.", disabled=disabled)
                                submitted_comment = st.form_submit_button("Post comment", disabled=disabled)
                                if submitted_comment:
                                    if not comment_body.strip():
                                        st.error("Enter a comment before posting.")
                                    else:
                                        _, comment_save_error = add_review_comment(supabase, review_item_id=saved.get("id"), session_id=review_session.get("id"), analysis_id=analysis_id, user_id=user_id, workspace_id=workspace_id, body=comment_body.strip(), author_name=reviewer_name, author_email=reviewer_email)
                                        if comment_save_error: st.error(comment_save_error)
                                        else: st.rerun()

            finish_col, reset_col = st.columns(2)
            confirm_key = f"cv281_confirm_complete_{analysis_id}"
            with finish_col:
                if session_status != "completed":
                    if st.button(
                        "Complete and Lock Review",
                        type="primary",
                        use_container_width=True,
                        key=f"cv271_lock_{analysis_id}",
                        disabled=(not can_manage_review or session_locked or reviewed_count == 0 or total_review_items == 0),
                    ):
                        st.session_state[confirm_key] = True
                else:
                    st.success("Engineering review completed and locked.")

            if st.session_state.get(confirm_key):
                unresolved_count = max(0, total_review_items - reviewed_count)
                st.warning(
                    f"Confirm review completion: {reviewed_count} reviewed, "
                    f"{counts['Approve']} approved, {counts['Needs Investigation']} investigating, "
                    f"{counts['Reject']} rejected, {counts['Skip']} skipped, and {unresolved_count} unresolved."
                )
                confirm_complete_col, cancel_complete_col = st.columns(2)
                with confirm_complete_col:
                    if st.button("Confirm and Lock", type="primary", use_container_width=True, key=f"cv281_confirm_lock_{analysis_id}"):
                        completed, complete_error = complete_review_session(
                            supabase,
                            session_id=review_session.get("id"),
                            user_id=user_id,
                            workspace_id=workspace_id,
                            reviewed_items=reviewed_count,
                            decision_counts=counts,
                        )
                        if complete_error:
                            st.error(f"Could not complete the review: {complete_error}")
                        else:
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                with cancel_complete_col:
                    if st.button("Cancel", use_container_width=True, key=f"cv281_cancel_lock_{analysis_id}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()

            with reset_col:
                if session_locked:
                    with st.form(f"cv272_reopen_{analysis_id}"):
                        reopen_reason = st.text_input("Reason for reopening", placeholder="Example: Supplier PCN received")
                        reopen_submit = st.form_submit_button("Reopen Review", use_container_width=True, disabled=not can_manage_review)
                        if reopen_submit:
                            if not reopen_reason.strip():
                                st.error("Enter a reason before reopening the review.")
                            else:
                                _, unlock_error = reopen_review_session(supabase, session_id=review_session.get("id"), user_id=user_id, workspace_id=workspace_id, reason=reopen_reason.strip(), actor_name=reviewer_name, actor_email=reviewer_email)
                                if unlock_error: st.error(f"Could not reopen the review: {unlock_error}")
                                else: st.rerun()
                elif session_status == "active" and st.button(
                    "Pause Review Session",
                    use_container_width=True,
                    key=f"cv271_pause_{analysis_id}",
                    disabled=not can_edit_review,
                ):
                    _, pause_error = update_review_session_status(
                        supabase,
                        session_id=review_session.get("id"),
                        user_id=user_id,
                        workspace_id=workspace_id,
                        status="paused",
                    )
                    if pause_error:
                        st.error(f"Could not pause the review: {pause_error}")
                    else:
                        st.rerun()
        st.markdown(f'''<section class="cv26-summary"><div class="cv26-summary-top"><div><div class="cv26-kicker">Cadivor Executive BOM Summary</div><div class="cv26-title">{html.escape(cockpit_status)}</div><div class="cv26-copy">Cadivor combined BOM health, lifecycle, inventory, supplier coverage, monitoring, and replacement evidence to produce this release recommendation.</div></div><span class="cv26-status {cockpit_class}">{html.escape(release_recommendation)}</span></div><div class="cv26-kpis"><div class="cv26-kpi"><span>Overall Health</span><strong>{health}/100</strong><small>{html.escape(risk_status)}</small></div><div class="cv26-kpi"><span>Readiness</span><strong>{engineering_readiness}%</strong><small>{readiness_label}</small></div><div class="cv26-kpi"><span>Critical Components</span><strong>{high}</strong><small>{medium} medium-risk parts</small></div><div class="cv26-kpi"><span>Qualified Alternatives</span><strong>{saved_alternatives}</strong><small>Saved replacement evidence</small></div><div class="cv26-kpi"><span>Monitoring Alerts</span><strong>{len(alerts)}</strong><small>Recorded alerts</small></div><div class="cv26-kpi"><span>Decision Confidence</span><strong>{confidence}%</strong><small>Evidence coverage</small></div></div></section>''', unsafe_allow_html=True)

        left, right = st.columns([1.03, .97])
        with left:
            st.markdown(f'''<section class="cv26-card"><div class="cv26-card-title">Release Readiness</div><div class="cv26-card-meta">Directional readiness based on BOM health, severity, and evidence coverage.</div><div class="cv26-readiness-line"><div><div class="cv26-readiness-score">{engineering_readiness}%</div><div class="cv26-readiness-label">{readiness_label}</div></div><span class="cv26-status {cockpit_class}">{release_recommendation}</span></div><div class="cv26-meter {readiness_class}"><i style="width:{engineering_readiness}%"></i></div><div class="cv26-copy"><strong>Top recommendation:</strong> validate {html.escape(primary_part)}. {html.escape(primary_reason)}</div></section>''', unsafe_allow_html=True)
            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            checks_html = "".join(f'<div class="cv26-check"><div class="cv26-check-left"><span class="cv26-check-icon {"done" if done else "open"}">{"✓" if done else "!"}</span>{html.escape(label)}</div><span class="cv26-status {"good" if done else "warn"}">{"Complete" if done else "Open"}</span></div>' for label, done in checklist)
            st.markdown(f'''<section class="cv26-card"><div class="cv26-card-title">Release Checklist</div><div class="cv26-card-meta">{checklist_complete} of {len(checklist)} release controls are satisfied.</div><div class="cv26-checks">{checks_html}</div><div class="cv26-meter {"good" if checklist_percent >= 80 else "warn"}"><i style="width:{checklist_percent}%"></i></div><div class="cv26-copy">Completion: <strong>{checklist_percent}%</strong></div></section>''', unsafe_allow_html=True)
        with right:
            issues=[]
            if lead_count: issues.append(f"{lead_count} component(s) have elevated lead-time exposure.")
            if source_count: issues.append(f"{source_count} component(s) have limited supplier coverage.")
            if lifecycle_count: issues.append(f"{lifecycle_count} component(s) require lifecycle validation.")
            if stock_count: issues.append(f"{stock_count} component(s) have no recorded stock.")
            if not issues: issues.append("No major exposure is currently recorded.")
            issue_html="".join(f"<li>{html.escape(x)}</li>" for x in issues)
            evidence=[("Lifecycle data", lifecycle_count==0),("Inventory coverage",stock_count==0),("Supplier coverage",source_count==0),("Alternative evidence",saved_alternatives>0),("Monitoring evidence",len(alerts)>0),("Engineering confidence",confidence>=80)]
            evidence_html="".join(f'<div class="cv26-evidence">{"✓" if ok else "⚠"} {html.escape(label)}</div>' for label,ok in evidence)
            st.markdown(f'''<section class="cv26-insight"><div class="cv26-insight-kicker">Cadivor Executive Insight</div><h3>{html.escape(assessment)}</h3><p>This BOM is assessed as <strong>{html.escape(release_recommendation.lower())}</strong>.</p><ul>{issue_html}</ul><p><strong>Suggested action:</strong> close the remaining checklist items before final approval.</p><div class="cv26-confidence">{evidence_html}</div></section>''', unsafe_allow_html=True)
            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            risk_rows=[("Lead Time",min(100,lead_count*28)),("Lifecycle",min(100,lifecycle_count*32)),("Inventory",min(100,stock_count*30)),("Supplier",min(100,source_count*25))]
            risk_html="".join(f'<div class="cv26-bar-row"><div class="cv26-bar-label">{label}</div><div class="cv26-bar-track"><i style="width:{value}%"></i></div><div class="cv26-bar-value">{value}</div></div>' for label,value in risk_rows)
            st.markdown(f'''<section class="cv26-card"><div class="cv26-card-title">Top Risk Drivers</div><div class="cv26-card-meta">Relative exposure derived from recorded evidence.</div><div class="cv26-bars">{risk_html}</div></section>''', unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        progress=[("Engineering Review",engineering_review),("Supplier Diversity",supplier_diversity),("Lifecycle Health",lifecycle_health),("Inventory Coverage",inventory_coverage)]
        progress_html="".join(f'<div class="cv26-bar-row"><div class="cv26-bar-label">{label}</div><div class="cv26-bar-track"><i style="width:{value}%"></i></div><div class="cv26-bar-value">{value}%</div></div>' for label,value in progress)
        healthy_count=max(0,total_parts-high-medium); healthy_pct=round(healthy_count/max(1,total_parts)*100); medium_pct=round(medium/max(1,total_parts)*100); critical_pct=max(0,100-healthy_pct-medium_pct)
        c1,c2=st.columns(2)
        with c1: st.markdown(f'''<section class="cv26-card"><div class="cv26-card-title">Review Progress</div><div class="cv26-card-meta">Cross-functional completion inferred from evidence.</div><div class="cv26-bars">{progress_html}</div></section>''', unsafe_allow_html=True)
        with c2: st.markdown(f'''<section class="cv26-card"><div class="cv26-card-title">Component Health Distribution</div><div class="cv26-card-meta">Healthy, medium-risk, and critical components.</div><div class="cv26-riskdist"><i class="healthy" style="width:{healthy_pct}%"></i><i class="medium" style="width:{medium_pct}%"></i><i class="critical" style="width:{critical_pct}%"></i></div><div class="cv26-legend"><span>Healthy {healthy_count}</span><span>Medium {medium}</span><span>Critical {high}</span></div></section>''', unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        phases=[]
        for period,idx,copy in [("Immediate",0,"Resolve the highest-priority risk."),("This Week",1,"Validate supplier and lifecycle evidence."),("Next Sprint",2,"Complete replacement or second-source qualification.")]:
            if len(ranked_parts)>idx: phases.append((period,_safe(ranked_parts[idx].get("mpn")),copy))
            else: phases.append((period,"No urgent component action","Continue controlled monitoring; no elevated component evidence is currently recorded."))
        phase_html="".join(f'<div class="cv26-phase"><span>{p}</span><strong>{html.escape(t)}</strong><small>{html.escape(c)}</small></div>' for p,t,c in phases)
        st.markdown(f'''<section class="cv26-card"><div class="cv26-card-title">Priority Timeline</div><div class="cv26-card-meta">A practical sequence for closing release risk.</div><div class="cv26-timeline">{phase_html}</div></section>''', unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        action_html=[]
        for index,action in enumerate((advisor.get("priority_actions") or [])[:6],1):
            urgency=_safe(action.get("urgency"),"Medium"); pc="high" if urgency.lower() in ("immediate","high") or index<=2 else "medium" if index<=4 else "low"
            action_html.append(f'<div class="cv26-action"><span class="cv26-priority {pc}">{pc.upper()}</span><div><strong>{html.escape(_safe(action.get("title"),"Review BOM risk"))}</strong><small>{html.escape(_safe(action.get("reason"),"Risk signal detected."))}</small></div><span class="cv26-owner">{html.escape(_safe(action.get("owner"),"Engineering"))}</span></div>')
        if not action_html: action_html.append('<div class="cv-analysis-empty">No priority actions are currently available.</div>')
        st.markdown(f'''<section class="cv26-card"><div class="cv26-card-title">Action Priority Matrix</div><div class="cv26-card-meta">Actions ordered by urgency and release impact.</div><div class="cv26-actions">{"".join(action_html)}</div></section>''', unsafe_allow_html=True)

    with overview_tab:
        _section_header("Decision Brief", "The most important engineering signals for this saved BOM.")
        context_score = context_coverage.score
        context_badge_class = "" if context_score >= 65 else " warn"
        context_badge = "Strong Evidence" if context_score >= 65 else "Evidence Developing"
        top_context_risks = context_summary.get("top_risks") or []
        top_context_part = _safe((top_context_risks[0] if top_context_risks else {}).get("part_number"), "No elevated part")
        st.markdown(
            f'''<section class="cv343-context">
              <div class="cv343-context-head">
                <div><div class="cv343-context-kicker">Engineering Intelligence Summary</div><h3>Engineering evidence for this BOM</h3><p>Cadivor combines component risk, lifecycle, inventory, supplier coverage, monitoring, replacement, and decision evidence to support release planning.</p></div>
                <span class="cv343-ready{context_badge_class}">{context_badge} · {context_score}%</span>
              </div>
              <div class="cv343-context-grid">
                <div class="cv343-context-stat"><span>Components</span><strong>{len(engineering_context.components)}</strong><small>parts assessed</small></div>
                <div class="cv343-context-stat"><span>Monitoring</span><strong>{len(engineering_context.monitoring)}</strong><small>active evidence</small></div>
                <div class="cv343-context-stat"><span>Alternatives</span><strong>{len(engineering_context.alternatives)}</strong><small>saved candidates</small></div>
                <div class="cv343-context-stat"><span>Decisions</span><strong>{len(engineering_context.decisions)}</strong><small>recorded outcomes</small></div>
                <div class="cv343-context-stat"><span>Timeline</span><strong>{len(engineering_context.timeline)}</strong><small>review history</small></div>
                <div class="cv343-context-stat"><span>Release Posture</span><strong>{html.escape(_safe(context_summary.get("release_posture"), "Review"))}</strong><small>recommended stance</small></div>
              </div>
              <div class="cv343-context-foot"><span>Top engineering concern: <strong>{html.escape(top_context_part)}</strong></span><span>Evidence coverage indicates how much supporting data is available for this assessment.</span></div>
            </section>''',
            unsafe_allow_html=True,
        )
        relationship_count = int(graph_summary.get("relationship_count") or 0)
        reused_component = _safe(graph_summary.get("most_reused_component"), "No cross-BOM reuse found")
        reused_count = int(graph_summary.get("most_reused_component_count") or 0)
        where_used_note = (
            f"{html.escape(reused_component)} appears in {reused_count} saved BOMs."
            if reused_count > 1 else
            "No component reuse across saved BOMs has been detected yet."
        )
        st.markdown(
            f'''<div class="cv344-grid">
              <section class="cv344-card">
                <h3>Engineering Relationships</h3><p>How components connect to manufacturers, suppliers, alternatives, monitoring evidence, and decisions.</p>
                <div class="cv344-flow">
                  <div class="cv344-node"><strong>{graph_counts.get("component", 0)}</strong><span>Components</span></div>
                  <div class="cv344-node"><strong>{graph_counts.get("manufacturer", 0)}</strong><span>Manufacturers</span></div>
                  <div class="cv344-node"><strong>{graph_counts.get("supplier", 0)}</strong><span>Suppliers</span></div>
                  <div class="cv344-node"><strong>{graph_counts.get("alternative", 0)}</strong><span>Alternatives</span></div>
                  <div class="cv344-node"><strong>{relationship_count}</strong><span>Relationships</span></div>
                </div>
                <div class="cv344-where">Where used: <strong>{where_used_note}</strong></div>
              </section>
              <section class="cv344-card">
                <h3>Knowledge Summary</h3><p>Portfolio-level signals derived from the relationships in your saved engineering records.</p>
                <div class="cv344-summary">
                  <div><span>Most Connected Supplier</span><strong>{html.escape(_safe(graph_summary.get("most_connected_supplier"), "Not recorded"))}</strong><small>Based on current BOM sourcing</small></div>
                  <div><span>Most Reused Component</span><strong>{html.escape(reused_component)}</strong><small>{reused_count} saved BOM(s)</small></div>
                  <div><span>Without Alternatives</span><strong>{int(graph_summary.get("components_without_alternatives") or 0)}</strong><small>Qualification candidates</small></div>
                  <div><span>Require Review</span><strong>{int(graph_summary.get("components_requiring_review") or 0)}</strong><small>Medium or high risk</small></div>
                </div>
              </section>
            </div>''',
            unsafe_allow_html=True,
        )
        overall_status, engineering_recommendation, decision_confidence = _health_summary(
            health,
            high,
            medium,
        )
        status_class = _health_class(health)
        st.markdown(
            f"""
            <div class="cv-status-grid">
              <div class="cv-status-card {status_class}">
                <span>Overall BOM Status</span>
                <strong>{html.escape(overall_status)}</strong>
                <small>{html.escape(engineering_recommendation)}</small>
              </div>
              <div class="cv-status-card {'bad' if high else 'good'}">
                <span>Engineering Recommendation</span>
                <strong>{'Resolve high-risk parts' if high else 'Continue controlled release review'}</strong>
                <small>{high} high-risk and {medium} medium-risk components identified.</small>
              </div>
              <div class="cv-status-card {'good' if decision_confidence >= 80 else 'warn'}">
                <span>Decision Confidence</span>
                <strong>{decision_confidence}%</strong>
                <small>Confidence based on health, risk coverage, lifecycle, and saved sourcing data.</small>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        summary_col, risk_col = st.columns([1.05, 1])
        with summary_col:
            action_text = "Review high-risk components before release." if high else "Continue periodic monitoring for supplier and lifecycle changes."
            st.markdown(f'''<div class="cv-analysis-card"><div class="cv-analysis-card-title"><span>Recommended Next Action</span><div class="cv-analysis-icon">{_lucide('shield',18)}</div></div><div class="cv-analysis-row-list"><div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{html.escape(action_text)}</div><div class="cv-analysis-row-meta">{high} high-risk components • {len(alerts)} saved alerts • {len(alternatives)} replacement records</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill {health_cls}">{health} health</span></div></div><div class="cv-analysis-row"><div><div class="cv-analysis-row-title">Source file</div><div class="cv-analysis-row-meta">{html.escape(filename)} • saved {_relative_date(created)}</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill">Saved</span></div></div></div></div>''', unsafe_allow_html=True)
        with risk_col:
            risk_html = "".join(f'<div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{label}</div><div class="cv-analysis-row-meta">Component count in this analysis</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill {cls}">{value}</span></div></div>' for label,value,cls in [("High Risk",high,"bad" if high else "good"),("Medium Risk",medium,"warn" if medium else "good"),("Low Risk",low,"good")])
            st.markdown(f'<div class="cv-analysis-card"><div class="cv-analysis-card-title"><span>Risk Breakdown</span><div class="cv-analysis-icon">{_lucide("alert",18)}</div></div><div class="cv-analysis-row-list">{risk_html}</div></div>', unsafe_allow_html=True)

    with intelligence_tab:
        _section_header("Lifecycle & Replacement Intelligence", "Operational readiness, stock health, supplier alerts, and replacement signals.")
        total = max(1, total_parts)
        active_count = sum(1 for p in parts if "active" in str(p.get("lifecycle_status") or p.get("Lifecycle Status") or "").lower())
        no_stock = sum(1 for p in parts if _num(p.get("stock_available") or p.get("Stock Available"), 0) <= 0)
        active_pct = round((active_count / total) * 100) if parts else 0
        stock_health = max(0, total_parts - no_stock)
        stock_pct = round((stock_health / total) * 100) if parts else 0
        intel_col, alerts_col = st.columns([1.05,1])
        with intel_col:
            st.markdown(f'''<div class="cv-risk-compact"><div class="cv-readiness-list"><div class="cv-readiness-row"><div><strong>Lifecycle Coverage</strong><span>{active_count} active components · {active_pct}% of BOM</span></div><div class="cv-readiness-bar"><i style="width:{active_pct}%"></i></div></div><div class="cv-readiness-row"><div><strong>Stock Health</strong><span>{stock_health} parts with available stock · {no_stock} no-stock risk</span></div><div class="cv-readiness-bar"><i style="width:{stock_pct}%"></i></div></div><div class="cv-readiness-metrics"><div><span>Supplier Alerts</span><strong>{len(alerts)}</strong><small>attached to analysis</small></div><div><span>Validated Alternatives</span><strong>{len(alternatives)}</strong><small>linked to analysis</small></div><div><span>High-Risk Parts</span><strong>{high}</strong><small>need review</small></div></div></div></div>''', unsafe_allow_html=True)
        with alerts_col:
            if alerts:
                rows = []
                for alert in alerts[:8]:
                    raw_part = _safe(
                        alert.get("part_number") or alert.get("mpn"),
                        "Component",
                    )
                    part = html.escape(raw_part)
                    msg = html.escape(
                        _safe(
                            alert.get("alert_message"),
                            "Supplier or lifecycle change detected.",
                        )
                    )
                    severity = html.escape(_safe(alert.get("severity"), "High"))
                    alert_type = html.escape(
                        _safe(alert.get("alert_type") or alert.get("type"), "Lifecycle Alert")
                    )
                    rows.append(
                        f"""
                        <div class="cv-alert-card">
                          <div class="cv-alert-top">
                            <div>
                              <div class="cv-alert-type">{alert_type}</div>
                              <div class="cv-alert-part">{part}</div>
                            </div>
                            <span class="cv-analysis-pill bad">{severity}</span>
                          </div>
                          <div class="cv-alert-message">{msg}</div>
                          <div class="cv-alert-actions">
                            <a class="cv-alert-action" href="{_monitor_url(raw_part, analysis_id)}" target="_self">Review in Monitoring</a>
                            <a class="cv-alert-action" href="{_alternative_url(raw_part, analysis_id)}" target="_self">Find Replacement</a>
                          </div>
                        </div>
                        """
                    )
                st.markdown("".join(rows), unsafe_allow_html=True)
            else:
                st.markdown('<div class="cv-analysis-empty">No saved supplier or lifecycle alerts are attached to this analysis.</div>', unsafe_allow_html=True)

    with components_tab:
        st.markdown('<div id="component-risk-report"></div>', unsafe_allow_html=True)
        _section_header(
            "Component Risk Report",
            "Search, filter, and inspect the saved component intelligence for this analysis.",
        )
        if component_focus_requested and requested_component:
            st.markdown(
                '<div class="cv-command-origin">'
                '<div class="cv-command-origin-main">'
                '<span class="cv-command-origin-icon">K</span>'
                '<div class="cv-command-origin-copy">'
                '<strong>Opened from Command Center</strong>'
                '<span>Cadivor focused this analysis on the component you selected.</span>'
                '</div></div>'
                f'<span class="cv-command-origin-part">{html.escape(requested_component)}</span>'
                '</div>',
                unsafe_allow_html=True,
            )

        # Sprint 34.2.4 — component results from Command Center should land on
        # the Components tab instead of restoring an unrelated browser position.
        focus_token = f"{analysis_id}:{requested_component.lower()}:{requested_focus}"
        focus_state_key = "cv3424_component_focus_token"
        should_apply_component_focus = (
            component_focus_requested
            and st.session_state.get(focus_state_key) != focus_token
        )
        if should_apply_component_focus:
            st.session_state[focus_state_key] = focus_token
            components.html(
                """
                <script>
                (function(){
                  const doc = window.parent.document;
                  const activateAndScroll = () => {
                    const tabs = Array.from(doc.querySelectorAll('button[data-baseweb="tab"]'));
                    const componentTab = tabs.find((tab) =>
                      (tab.innerText || tab.textContent || '').trim().toLowerCase() === 'components'
                    );
                    if (componentTab && componentTab.getAttribute('aria-selected') !== 'true') {
                      componentTab.click();
                    }
                    window.setTimeout(() => {
                      const target = doc.getElementById('component-risk-report');
                      const root = doc.querySelector('[data-testid="stAppViewContainer"]');
                      if (target) {
                        target.scrollIntoView({behavior:'smooth', block:'start'});
                        window.setTimeout(() => {
                          const selectedRow = doc.querySelector('.cv-analysis-component.is-selected');
                          const intelligence = doc.querySelector('.cv-component-detail');
                          if (selectedRow) selectedRow.scrollIntoView({behavior:'smooth', block:'center'});
                          if (intelligence) intelligence.setAttribute('tabindex', '-1');
                        }, 260);
                      } else if (root) {
                        root.scrollTo({top:0, left:0, behavior:'smooth'});
                      }
                    }, 180);
                  };
                  window.setTimeout(activateAndScroll, 120);
                  window.setTimeout(activateAndScroll, 520);
                })();
                </script>
                """,
                height=0,
                width=0,
            )
        if parts:
            normalized_parts = sorted(
                parts,
                key=lambda x: _num(
                    _part_value(x, "risk_score", "Risk Score"),
                    0,
                ),
                reverse=True,
            )

            search_col, risk_filter_col, lifecycle_filter_col = st.columns(
                [0.48, 0.24, 0.28],
                gap="medium",
            )
            with search_col:
                component_search = st.text_input(
                    "Search components",
                    placeholder="Search MPN or manufacturer",
                    key=f"analysis_component_search_{analysis_id}",
                )
            risk_options = ["All"] + sorted(
                {
                    _risk_label(part)
                    for part in normalized_parts
                    if _risk_label(part)
                }
            )
            lifecycle_options = ["All"] + sorted(
                {
                    _safe(
                        _part_value(
                            part,
                            "lifecycle_status",
                            "Lifecycle Status",
                        ),
                        "Unknown",
                    )
                    for part in normalized_parts
                }
            )
            with risk_filter_col:
                selected_risk = st.selectbox(
                    "Risk",
                    risk_options,
                    key=f"analysis_component_risk_{analysis_id}",
                )
            with lifecycle_filter_col:
                selected_lifecycle = st.selectbox(
                    "Lifecycle",
                    lifecycle_options,
                    key=f"analysis_component_lifecycle_{analysis_id}",
                )

            filtered_parts = []
            search_text = component_search.strip().lower()
            for part in normalized_parts:
                mpn_text = _safe(
                    _part_value(part, "mpn", "MPN"),
                    "Unknown MPN",
                )
                manufacturer_text = _safe(
                    _part_value(part, "manufacturer", "Manufacturer"),
                    "Unknown manufacturer",
                )
                lifecycle_text = _safe(
                    _part_value(
                        part,
                        "lifecycle_status",
                        "Lifecycle Status",
                    ),
                    "Unknown",
                )
                risk_text = _risk_label(part)

                if search_text and search_text not in (
                    f"{mpn_text} {manufacturer_text}".lower()
                ):
                    continue
                if selected_risk != "All" and risk_text != selected_risk:
                    continue
                if (
                    selected_lifecycle != "All"
                    and lifecycle_text != selected_lifecycle
                ):
                    continue
                filtered_parts.append(part)

            st.caption(
                f"Showing {len(filtered_parts)} of {len(parts)} saved components."
            )

            if filtered_parts:
                part_labels = {}
                for part in filtered_parts:
                    mpn_value = _safe(
                        _part_value(part, "mpn", "MPN"),
                        "Unknown MPN",
                    )
                    manufacturer_value = _safe(
                        _part_value(part, "manufacturer", "Manufacturer"),
                        "Unknown manufacturer",
                    )
                    label = f"{mpn_value} — {manufacturer_value}"
                    part_labels[label] = part

                selector_key = f"analysis_component_selector_{analysis_id}"
                requested_label = None
                if requested_component:
                    requested_component_key = requested_component.strip().lower()
                    requested_label = next(
                        (
                            label
                            for label, part in part_labels.items()
                            if _safe(_part_value(part, "mpn", "MPN"), "").strip().lower()
                            == requested_component_key
                        ),
                        None,
                    )

                selection_token_key = f"cv3424_selected_component_{analysis_id}"
                selection_token = f"{analysis_id}:{requested_component.lower()}"
                if (
                    requested_label
                    and st.session_state.get(selection_token_key) != selection_token
                ):
                    st.session_state[selector_key] = requested_label
                    st.session_state[selection_token_key] = selection_token

                available_labels = list(part_labels.keys())
                if st.session_state.get(selector_key) not in available_labels:
                    st.session_state[selector_key] = requested_label or available_labels[0]

                selected_label = st.selectbox(
                    "Select a component to inspect",
                    options=available_labels,
                    key=selector_key,
                )
                selected_part = part_labels[selected_label]
                selected_mpn_for_row = _safe(
                    _part_value(selected_part, "mpn", "MPN"),
                    "",
                ).strip().lower()

                table_col, detail_col = st.columns([1.25, 0.75], gap="medium")
                with table_col:
                    rows = []
                    for part in filtered_parts:
                        mpn_value = _safe(
                            _part_value(part, "mpn", "MPN"),
                            "Unknown MPN",
                        )
                        mfg_value = _safe(
                            _part_value(part, "manufacturer", "Manufacturer"),
                            "Unknown manufacturer",
                        )
                        status_value = _safe(
                            _part_value(
                                part,
                                "lifecycle_status",
                                "Lifecycle Status",
                            ),
                            "Unknown",
                        )
                        stock_value = _num(
                            _part_value(
                                part,
                                "stock_available",
                                "Stock Available",
                            ),
                            0,
                        )
                        score_value = _num(
                            _part_value(part, "risk_score", "Risk Score"),
                            0,
                        )
                        level_value = _risk_label(part)
                        class_value = _risk_class(level_value, score_value)
                        supplier_count = _num(
                            _part_value(
                                part,
                                "supplier_count",
                                "Supplier Count",
                            ),
                            0,
                        )
                        rows.append(
                            (
                                f'<div class="cv-analysis-component{" is-selected" if mpn_value.strip().lower() == selected_mpn_for_row else ""}{" is-command-focus" if component_focus_requested and requested_component and mpn_value.strip().lower() == requested_component.strip().lower() else ""}" data-component="{html.escape(mpn_value, quote=True)}">'
                                '<div>'
                                f'<div class="head">{html.escape(mpn_value)}</div>'
                                f'<div class="sub">{html.escape(mfg_value)}</div>'
                                '</div>'
                                '<div>'
                                f'<div class="head">{html.escape(status_value)}</div>'
                                '<div class="sub">Lifecycle</div>'
                                '</div>'
                                '<div>'
                                f'<div class="head">{stock_value:,}</div>'
                                '<div class="sub">Stock</div>'
                                '</div>'
                                '<div>'
                                f'<div class="head">{supplier_count}</div>'
                                '<div class="sub">Suppliers</div>'
                                '</div>'
                                '<div class="cv-analysis-pills">'
                                f'<span class="cv-analysis-pill {class_value}">'
                                f'{html.escape(level_value)}'
                                '</span>'
                                '</div>'
                                '</div>'
                            )
                        )
                    component_table_html = (
                        '<div class="cv-analysis-table-wrap">'
                        '<div class="cv-analysis-table-head">'
                        '<strong>Filtered Components</strong>'
                        f'<span>{len(filtered_parts)} records</span>'
                        '</div>'
                        + "".join(rows)
                        + '</div>'
                    )
                    st.markdown(
                        component_table_html,
                        unsafe_allow_html=True,
                    )

                with detail_col:
                    selected_mpn = _safe(
                        _part_value(selected_part, "mpn", "MPN"),
                        "Unknown MPN",
                    )
                    selected_mfg = _safe(
                        _part_value(
                            selected_part,
                            "manufacturer",
                            "Manufacturer",
                        ),
                        "Unknown manufacturer",
                    )
                    selected_lifecycle_value = _safe(
                        _part_value(
                            selected_part,
                            "lifecycle_status",
                            "Lifecycle Status",
                        ),
                        "Unknown",
                    )
                    selected_stock = _num(
                        _part_value(
                            selected_part,
                            "stock_available",
                            "Stock Available",
                        ),
                        0,
                    )
                    selected_suppliers = _num(
                        _part_value(
                            selected_part,
                            "supplier_count",
                            "Supplier Count",
                        ),
                        0,
                    )
                    selected_score = _num(
                        _part_value(
                            selected_part,
                            "risk_score",
                            "Risk Score",
                        ),
                        0,
                    )
                    selected_level = _risk_label(selected_part)
                    selected_lead_time = _safe(
                        _part_value(
                            selected_part,
                            "lead_time_weeks",
                            "Lead Time Weeks",
                        ),
                        "Not available",
                    )
                    selected_source = _safe(
                        _part_value(
                            selected_part,
                            "best_source",
                            "Best Source",
                            "supplier",
                        ),
                        "Not available",
                    )
                    selected_url = _safe(
                        _part_value(
                            selected_part,
                            "product_url",
                            "Product URL",
                            "datasheet_url",
                        ),
                        "",
                    )
                    selected_reason = _safe(
                        _part_value(
                            selected_part,
                            "risk_reasons",
                            "Risk Reasons",
                            "risk_reason",
                        ),
                        "No detailed risk explanation was stored.",
                    )

                    st.markdown(
                        f"""
                        <div class="cv-component-detail{' is-command-focus' if component_focus_requested and requested_component and selected_mpn.strip().lower() == requested_component.strip().lower() else ''}">
                          <div class="cv-analysis-card-title">
                            <span>{'Selected Component' if component_focus_requested and requested_component else 'Component Intelligence'}</span>
                            <span class="cv-analysis-pill {_risk_class(selected_level, selected_score)}">
                              {html.escape(selected_level)} · {selected_score}
                            </span>
                          </div>
                          <div class="cv-analysis-row-title">{html.escape(selected_mpn)}</div>
                          <div class="cv-analysis-row-meta">{html.escape(selected_mfg)}</div>
                          <div class="cv-component-detail-grid">
                            <div><span>Lifecycle</span><strong>{html.escape(selected_lifecycle_value)}</strong></div>
                            <div><span>Available Stock</span><strong>{selected_stock:,}</strong></div>
                            <div><span>Suppliers</span><strong>{selected_suppliers}</strong></div>
                            <div><span>Lead Time</span><strong>{html.escape(selected_lead_time)} weeks</strong></div>
                            <div><span>Best Source</span><strong>{html.escape(selected_source)}</strong></div>
                            <div><span>Risk Score</span><strong>{selected_score}/100</strong></div>
                          </div>
                          <div class="cv-analysis-row-meta"><b>Risk explanation:</b> {html.escape(selected_reason)}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    internal_nav_button(
                        "Find Alternatives",
                        "Alternative Finder",
                        key=f"analysis_find_alternative_{analysis_id}_{selected_mpn}",
                        use_container_width=True,
                        original_part=selected_mpn,
                        analysis_id=analysis_id,
                    )
                    internal_nav_button(
                        "Monitor Component",
                        "Monitoring",
                        key=f"analysis_monitor_component_{analysis_id}_{selected_mpn}",
                        use_container_width=True,
                        mpn=selected_mpn,
                        analysis_id=analysis_id,
                    )
                    if selected_url:
                        st.link_button(
                            "Open Datasheet / Source",
                            selected_url,
                            use_container_width=True,
                        )
            else:
                st.info("No components match the selected filters.")
        else:
            st.markdown(
                '<div class="cv-analysis-empty">No saved component rows were found for this analysis.</div>',
                unsafe_allow_html=True,
            )

    with alternatives_tab:
        _section_header(
            "Replacement Readiness",
            "Review linked alternatives, pending validation, and components that still need replacement work.",
        )

        validated_count = len(alternatives)
        components_needing_alternatives = sum(
            1
            for part in parts
            if _risk_class(
                _risk_label(part),
                _num(_part_value(part, "risk_score", "Risk Score"), 0),
            )
            in {"bad", "warn"}
        )
        pending_review = max(0, components_needing_alternatives - validated_count)
        compatibility_values = [
            _num(
                alt.get("compatibility_confidence")
                or alt.get("drop_in_confidence")
                or alt.get("score"),
                0,
            )
            for alt in alternatives
        ]
        average_compatibility = (
            round(sum(compatibility_values) / len(compatibility_values))
            if compatibility_values
            else 0
        )

        st.markdown(
            f"""
            <div class="cv-kpi-grid">
              <div class="cv-kpi">
                <span>Validated Alternatives</span>
                <strong>{validated_count}</strong>
                <small>Linked engineering decision records</small>
              </div>
              <div class="cv-kpi">
                <span>Pending Review</span>
                <strong>{pending_review}</strong>
                <small>Replacement investigations still open</small>
              </div>
              <div class="cv-kpi">
                <span>Components Needing Alternatives</span>
                <strong>{components_needing_alternatives}</strong>
                <small>Medium- or high-risk components</small>
              </div>
              <div class="cv-kpi">
                <span>Average Compatibility</span>
                <strong>{average_compatibility if compatibility_values else '—'}</strong>
                <small>{'Average confidence score' if compatibility_values else 'No validated scores yet'}</small>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if alternatives:
            rows = []
            for alt in alternatives:
                original = html.escape(
                    _safe(
                        alt.get("original_mpn")
                        or alt.get("mpn")
                        or alt.get("part_number"),
                        "Original component",
                    )
                )
                recommendation = html.escape(
                    _safe(
                        alt.get("alternative_mpn")
                        or alt.get("recommended_mpn")
                        or alt.get("candidate_mpn")
                        or alt.get("replacement_mpn"),
                        "Candidate available",
                    )
                )
                supplier = html.escape(
                    _safe(
                        alt.get("supplier") or alt.get("source"),
                        "Supplier review",
                    )
                )
                decision = html.escape(
                    _safe(
                        alt.get("decision_status")
                        or alt.get("status"),
                        "Saved candidate",
                    )
                )
                rows.append(
                    f"""
                    <div class="cv-analysis-row">
                      <div>
                        <div class="cv-analysis-row-title">{original} → {recommendation}</div>
                        <div class="cv-analysis-row-meta">{supplier} · {decision}</div>
                      </div>
                      <span class="cv-analysis-pill good">Validated</span>
                    </div>
                    """
                )
            st.markdown(
                '<div class="cv-analysis-row-list">' + "".join(rows) + "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="cv-analysis-empty">
                  <b>No validated alternatives are linked yet.</b><br>
                  Start with the medium- and high-risk components, compare candidates,
                  then save the engineering decision back to this BOM workspace.
                </div>
                """,
                unsafe_allow_html=True,
            )

        action_a, action_b = st.columns(2)
        with action_a:
            internal_nav_button(
                "Open Alternative Finder",
                "Alternative Finder",
                key=f"analysis_open_alternatives_{analysis_id}",
                use_container_width=True,
                analysis_id=analysis_id,
            )
        with action_b:
            internal_nav_button(
                "Review Components",
                "Analysis Details",
                key=f"analysis_review_components_{analysis_id}",
                use_container_width=True,
                analysis_id=analysis_id,
            )

    with discussions_tab:
        _section_header(
            "Engineering Discussions",
            "Keep review notes, mentions, and permanent engineering context attached to this saved BOM.",
        )

        pinned_count = sum(1 for row in comments if row.get("is_pinned"))
        st.markdown(
            f"""
            <div class="cv-discussion-summary">
              <div class="cv-discussion-kpi"><span>Comments</span><strong>{len(comments)}</strong></div>
              <div class="cv-discussion-kpi"><span>Pinned Notes</span><strong>{pinned_count}</strong></div>
              <div class="cv-discussion-kpi"><span>Followers</span><strong>{len(followers)}</strong></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="cv-follow-card">
              <div class="cv-analysis-card-title">
                <span>Follow this BOM</span>
                <span class="cv-analysis-pill {'good' if is_following else ''}">
                  {'Following' if is_following else 'Not following'}
                </span>
              </div>
              <div class="cv-analysis-row-meta">
                Followers receive collaboration notifications when new comments or mentions are added.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        follow_left, follow_right = st.columns([0.25, 0.75])
        with follow_left:
            if is_following:
                if st.button(
                    "Unfollow BOM",
                    key=f"analysis_unfollow_{analysis_id}",
                    use_container_width=True,
                ):
                    error = unfollow_analysis(
                        supabase,
                        workspace_id=workspace_id or "",
                        analysis_id=analysis_id,
                        user_id=user_id,
                    )
                    if error:
                        st.error(error)
                    else:
                        st.success("You are no longer following this BOM.")
                        st.rerun()
            else:
                if st.button(
                    "Follow BOM",
                    type="primary",
                    key=f"analysis_follow_{analysis_id}",
                    use_container_width=True,
                ):
                    error = follow_analysis(
                        supabase,
                        workspace_id=workspace_id or "",
                        analysis_id=analysis_id,
                        user_id=user_id,
                    )
                    if error:
                        st.error(error)
                    else:
                        st.success("You are now following this BOM.")
                        st.rerun()

        st.markdown("#### Add an engineering comment")
        comment_kind = st.selectbox(
            "Comment type",
            ["Discussion", "Engineering Note", "Decision Rationale", "Procurement Note"],
            key=f"analysis_comment_type_{analysis_id}",
        )

        component_mpns = sorted(
            {
                _safe(row.get("mpn"), "").strip()
                for row in parts
                if _safe(row.get("mpn"), "").strip()
            }
        )
        comment_context_options = ["General BOM discussion"] + [
            f"Component: {mpn}" for mpn in component_mpns
        ]
        comment_context = st.selectbox(
            "Discussion context",
            comment_context_options,
            key=f"analysis_comment_context_{analysis_id}",
            help="Attach the comment to the entire BOM or to one specific component.",
        )
        selected_component_mpn = (
            comment_context.replace("Component: ", "", 1)
            if comment_context.startswith("Component: ")
            else ""
        )

        comment_body_key = f"analysis_comment_body_{analysis_id}"
        comment_reset_key = f"analysis_comment_reset_{analysis_id}"

        if st.session_state.pop(comment_reset_key, False):
            st.session_state[comment_body_key] = ""

        comment_text = st.text_area(
            "Comment",
            placeholder=(
                "Record engineering context or mention a teammate with "
                "@emailhandle or @firstname."
            ),
            height=120,
            key=comment_body_key,
        )
        if workspace_members:
            mention_examples = []
            for member in workspace_members[:8]:
                email_value = _safe(member.get("email"), "")
                name_value = _safe(member.get("display_name"), "")
                handle = email_value.split("@", 1)[0] if "@" in email_value else ""
                if handle:
                    mention_examples.append(f"@{handle}")
                elif name_value:
                    mention_examples.append(
                        "@" + re.sub(r"[^A-Za-z0-9._+-]+", ".", name_value).strip(".")
                    )
            if mention_examples:
                st.caption("Mention examples: " + ", ".join(mention_examples))

        if st.button(
            "Post Comment",
            type="primary",
            key=f"analysis_post_comment_{analysis_id}",
        ):
            created_comment, comment_error = add_analysis_comment(
                supabase,
                workspace_id=workspace_id or "",
                analysis_id=analysis_id,
                user_id=user_id,
                author_name=_safe(
                    current_user.get("full_name"),
                    current_user.get("email") or "Cadivor user",
                ),
                author_email=_safe(current_user.get("email"), ""),
                body=comment_text,
                comment_type=comment_kind.lower().replace(" ", "_"),
                component_mpn=selected_component_mpn,
            )
            if comment_error:
                st.error(comment_error)
            else:
                mentions = extract_mentions(comment_text)
                mentioned_members = resolve_mentioned_members(
                    workspace_members,
                    mentions,
                )
                notified_ids = set()
                for member in mentioned_members:
                    mentioned_user_id = _safe(member.get("user_id"), "")
                    if mentioned_user_id and mentioned_user_id != user_id:
                        create_workspace_notification(
                            supabase,
                            workspace_id=workspace_id or "",
                            user_id=mentioned_user_id,
                            title=f"You were mentioned in {project}",
                            message=(
                                f"{_safe(current_user.get('full_name'), 'A teammate')} "
                                f"mentioned you in an engineering discussion."
                            ),
                            notification_type="analysis_mention",
                        )
                        notified_ids.add(mentioned_user_id)

                for follower in followers:
                    follower_id = _safe(follower.get("user_id"), "")
                    if (
                        follower_id
                        and follower_id != user_id
                        and follower_id not in notified_ids
                    ):
                        create_workspace_notification(
                            supabase,
                            workspace_id=workspace_id or "",
                            user_id=follower_id,
                            title=f"New comment on {project}",
                            message=(
                                f"{_safe(current_user.get('full_name'), 'A teammate')} "
                                f"added an engineering comment."
                            ),
                            notification_type="analysis_comment",
                        )
                st.success("Engineering comment posted.")
                st.session_state[comment_reset_key] = True
                st.rerun()

        st.markdown("#### Discussion history")

        history_context_options = ["All discussions", "General BOM discussion"] + [
            f"Component: {mpn}" for mpn in component_mpns
        ]
        history_filter_col, history_search_col = st.columns([0.42, 0.58])
        with history_filter_col:
            history_context = st.selectbox(
                "Filter by context",
                history_context_options,
                key=f"analysis_comment_history_context_{analysis_id}",
            )
        with history_search_col:
            history_search = st.text_input(
                "Search discussion history",
                placeholder="Search author, type, component, or comment text",
                key=f"analysis_comment_history_search_{analysis_id}",
            ).strip().lower()

        filtered_comments = list(comments)
        if history_context == "General BOM discussion":
            filtered_comments = [
                row for row in filtered_comments
                if not _safe(row.get("component_mpn"), "").strip()
            ]
        elif history_context.startswith("Component: "):
            selected_history_mpn = history_context.replace("Component: ", "", 1)
            filtered_comments = [
                row for row in filtered_comments
                if _safe(row.get("component_mpn"), "").strip() == selected_history_mpn
            ]

        if history_search:
            filtered_comments = [
                row for row in filtered_comments
                if history_search in " ".join(
                    [
                        _safe(row.get("author_name"), ""),
                        _safe(row.get("author_email"), ""),
                        _safe(row.get("comment_type"), ""),
                        _safe(row.get("component_mpn"), ""),
                        _safe(row.get("body"), ""),
                    ]
                ).lower()
            ]

        def _clear_comment_history_filters() -> None:
            st.session_state[f"analysis_comment_history_context_{analysis_id}"] = "All discussions"
            st.session_state[f"analysis_comment_history_search_{analysis_id}"] = ""

        result_col, clear_col = st.columns([0.82, 0.18])
        with result_col:
            st.caption(
                f"Showing {len(filtered_comments)} of {len(comments)} engineering comments."
            )
        with clear_col:
            st.button(
                "Clear Filters",
                key=f"analysis_comment_clear_filters_{analysis_id}",
                use_container_width=True,
                disabled=(history_context == "All discussions" and not history_search),
                on_click=_clear_comment_history_filters,
            )

        if comments_error:
            st.error(f"Discussions could not be loaded: {comments_error}")
        elif not filtered_comments:
            empty_message = (
                "No engineering comments have been recorded for this BOM yet."
                if not comments
                else "No comments match the current search or context filter."
            )
            st.markdown(
                f'<div class="cv-analysis-empty">{html.escape(empty_message)}</div>',
                unsafe_allow_html=True,
            )
        else:
            for comment in filtered_comments:
                comment_id = _safe(comment.get("id"), "")
                pinned = bool(comment.get("is_pinned"))
                author_id = _safe(comment.get("user_id"), "")
                can_delete = can_manage_discussion or author_id == user_id
                created_at = _safe(comment.get("created_at"), "")[:19].replace("T", " ")
                comment_type_value = _safe(comment.get("comment_type"), "discussion").replace("_", " ").title()
                st.markdown(
                    f"""
                    <div class="cv-comment {'pinned' if pinned else ''}">
                      <div class="cv-comment-top">
                        <div>
                          <div class="cv-comment-author">{html.escape(_safe(comment.get('author_name'), comment.get('author_email') or 'Cadivor user'))}</div>
                          <div class="cv-comment-meta">
                            {html.escape(comment_type_value)} · {html.escape(created_at)} UTC
                            {
                                '<span class="cv-comment-context">Component: ' +
                                html.escape(_safe(comment.get("component_mpn"), "")) +
                                '</span>'
                                if _safe(comment.get("component_mpn"), "").strip()
                                else '<span class="cv-comment-context">General BOM</span>'
                            }
                          </div>
                        </div>
                        {'<span class="cv-comment-badge">Pinned</span>' if pinned else ''}
                      </div>
                      <div class="cv-comment-body">{html.escape(_safe(comment.get('body'), ''))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                action_columns = st.columns([0.18, 0.18, 0.64])
                if can_manage_discussion:
                    with action_columns[0]:
                        if st.button(
                            "Unpin" if pinned else "Pin",
                            key=f"analysis_pin_comment_{comment_id}",
                            use_container_width=True,
                        ):
                            error = set_comment_pinned(
                                supabase,
                                workspace_id=workspace_id or "",
                                comment_id=comment_id,
                                is_pinned=not pinned,
                            )
                            if error:
                                st.error(error)
                            else:
                                st.rerun()
                if can_delete:
                    with action_columns[1]:
                        if st.button(
                            "Delete",
                            key=f"analysis_delete_comment_{comment_id}",
                            use_container_width=True,
                        ):
                            st.session_state[
                                f"confirm_delete_comment_{comment_id}"
                            ] = True

                if st.session_state.get(
                    f"confirm_delete_comment_{comment_id}",
                    False,
                ):
                    st.warning(
                        "Delete this comment? This removes it from the visible engineering record."
                    )
                    confirm_delete, cancel_delete = st.columns(2)
                    with confirm_delete:
                        if st.button(
                            "Yes, Delete Comment",
                            type="primary",
                            key=f"analysis_confirm_delete_comment_{comment_id}",
                        ):
                            error = delete_comment(
                                supabase,
                                workspace_id=workspace_id or "",
                                comment_id=comment_id,
                                user_id=user_id,
                                can_manage=can_manage_discussion,
                            )
                            if error:
                                st.error(error)
                            else:
                                st.session_state.pop(
                                    f"confirm_delete_comment_{comment_id}",
                                    None,
                                )
                                st.rerun()
                    with cancel_delete:
                        if st.button(
                            "Cancel",
                            key=f"analysis_cancel_delete_comment_{comment_id}",
                        ):
                            st.session_state.pop(
                                f"confirm_delete_comment_{comment_id}",
                                None,
                            )
                            st.rerun()

    with timeline_tab:
        _section_header(
            "Engineering Timeline",
            "Review the chronological engineering history of this saved BOM without leaving the analysis workspace.",
        )

        timeline_events = []

        if analysis.get("created_at"):
            timeline_events.append(
                {
                    "timestamp": _safe(analysis.get("created_at"), ""),
                    "kind": "analysis",
                    "title": "BOM analysis created",
                    "meta": _safe(current_user.get("full_name"), current_user.get("email") or "Cadivor user"),
                    "body": f"{project} was saved as a permanent engineering analysis.",
                }
            )

        for row in alerts:
            timeline_events.append(
                {
                    "timestamp": _safe(row.get("created_at") or row.get("detected_at"), ""),
                    "kind": "alert",
                    "title": f"Monitoring alert · {_safe(row.get('part_number') or row.get('mpn'), 'Component')}",
                    "meta": _safe(row.get("alert_type"), "Monitoring"),
                    "body": _safe(row.get("alert_message") or row.get("message"), "A monitored component changed."),
                }
            )

        for row in alternatives:
            timeline_events.append(
                {
                    "timestamp": _safe(row.get("created_at"), ""),
                    "kind": "alternative",
                    "title": f"Alternative reviewed · {_safe(row.get('alternative_part'), 'Candidate')}",
                    "meta": f"Original: {_safe(row.get('original_part'), 'Unknown')}",
                    "body": (
                        f"Recommendation score {_num(row.get('recommendation_score'))}/100 · "
                        f"Estimated risk {_safe(row.get('estimated_risk'), 'Not recorded')}."
                    ),
                }
            )

        review_events, review_events_error = list_review_events(
            supabase,
            analysis_id=analysis_id,
            user_id=user_id,
            workspace_id=workspace_id,
            limit=100,
        )
        for row in review_events:
            timeline_events.append(
                {
                    "timestamp": _safe(row.get("created_at"), ""),
                    "kind": "review",
                    "title": _safe(row.get("title"), "Engineering review activity"),
                    "meta": _safe(row.get("actor_name"), row.get("actor_email") or "Cadivor reviewer"),
                    "body": _safe(row.get("body"), "A review record was updated."),
                }
            )

        for row in comments:
            component_label = _safe(row.get("component_mpn"), "").strip()
            timeline_events.append(
                {
                    "timestamp": _safe(row.get("created_at"), ""),
                    "kind": "comment",
                    "title": (
                        f"{_safe(row.get('comment_type'), 'discussion').replace('_', ' ').title()}"
                        + (f" · {component_label}" if component_label else "")
                    ),
                    "meta": _safe(row.get("author_name"), row.get("author_email") or "Cadivor user"),
                    "body": _safe(row.get("body"), ""),
                }
            )

        timeline_events.sort(
            key=lambda row: _safe(row.get("timestamp"), ""),
            reverse=True,
        )

        timeline_kind = st.selectbox(
            "Filter timeline",
            ["All activity", "Analysis", "Monitoring alerts", "Alternative reviews", "Engineering reviews", "Comments & notes"],
            key=f"analysis_timeline_kind_{analysis_id}",
        )
        timeline_search = st.text_input(
            "Search timeline",
            placeholder="Search component, person, event, or note",
            key=f"analysis_timeline_search_{analysis_id}",
        ).strip().lower()

        kind_map = {
            "Analysis": "analysis",
            "Monitoring alerts": "alert",
            "Alternative reviews": "alternative",
            "Comments & notes": "comment",
        }
        filtered_timeline = list(timeline_events)
        if timeline_kind in kind_map:
            filtered_timeline = [
                row for row in filtered_timeline
                if row.get("kind") == kind_map[timeline_kind]
            ]
        if timeline_search:
            filtered_timeline = [
                row for row in filtered_timeline
                if timeline_search in " ".join(
                    [
                        _safe(row.get("title"), ""),
                        _safe(row.get("meta"), ""),
                        _safe(row.get("body"), ""),
                    ]
                ).lower()
            ]

        timeline_metric_cols = st.columns(4)
        timeline_metric_cols[0].metric("Timeline Events", len(timeline_events))
        timeline_metric_cols[1].metric(
            "Comments & Notes",
            sum(1 for row in timeline_events if row.get("kind") == "comment"),
        )
        timeline_metric_cols[2].metric(
            "Monitoring Alerts",
            sum(1 for row in timeline_events if row.get("kind") == "alert"),
        )
        timeline_metric_cols[3].metric(
            "Alternative Reviews",
            sum(1 for row in timeline_events if row.get("kind") == "alternative"),
        )

        def _clear_timeline_filters() -> None:
            st.session_state[f"analysis_timeline_kind_{analysis_id}"] = "All activity"
            st.session_state[f"analysis_timeline_search_{analysis_id}"] = ""

        timeline_result_col, timeline_clear_col = st.columns([0.82, 0.18])
        with timeline_result_col:
            st.caption(f"Showing {len(filtered_timeline)} of {len(timeline_events)} timeline events.")
        with timeline_clear_col:
            st.button(
                "Clear Filters",
                key=f"analysis_timeline_clear_filters_{analysis_id}",
                use_container_width=True,
                disabled=(timeline_kind == "All activity" and not timeline_search),
                on_click=_clear_timeline_filters,
            )

        if not filtered_timeline:
            st.markdown(
                """
                <div class="cv-analysis-empty">
                  No timeline events match the selected filters.
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            # Keep the HTML flush-left. Markdown interprets indented HTML blocks as
            # code, which caused later timeline cards to display their raw tags.
            timeline_items = []
            for event in filtered_timeline[:250]:
                timestamp = _safe(event.get("timestamp"), "")[:19].replace("T", " ")
                kind = html.escape(_safe(event.get("kind"), "analysis"), quote=True)
                title = html.escape(_safe(event.get("title"), "Engineering event"))
                meta = html.escape(_safe(event.get("meta"), ""))
                body = html.escape(_safe(event.get("body"), ""))
                timeline_items.append(
                    f'<div class="cv-timeline-item {kind}">'
                    f'<div class="cv-timeline-title">{title}</div>'
                    f'<div class="cv-timeline-meta">{meta} · {html.escape(timestamp)} UTC</div>'
                    f'<div class="cv-timeline-body">{body}</div>'
                    f'</div>'
                )

            timeline_markup = '<div class="cv-timeline">' + "".join(timeline_items) + '</div>'
            st.markdown(timeline_markup, unsafe_allow_html=True)

    with reports_tab:
        _section_header(
            "Report Library",
            "Generate focused deliverables for engineering, sourcing, management, and audit workflows.",
        )
        st.markdown(
            f"""
            <div class="cv-report-grid">
              <div class="cv-report-card">
                <h4>Executive Engineering Summary</h4>
                <p>Health, risk distribution, decision brief, and recommended next actions for {html.escape(project)}.</p>
                <div class="cv-report-formats"><span class="cv-format">PDF</span><span class="cv-format">Excel</span></div>
              </div>
              <div class="cv-report-card">
                <h4>Detailed Component Risk Report</h4>
                <p>Component-level lifecycle, stock, supplier diversity, lead-time, and risk explanations.</p>
                <div class="cv-report-formats"><span class="cv-format">PDF</span><span class="cv-format">Excel</span><span class="cv-format">CSV</span></div>
              </div>
              <div class="cv-report-card">
                <h4>Procurement & Sourcing Report</h4>
                <p>Supplier concentration, stock exposure, sourcing gaps, and parts requiring secondary sources.</p>
                <div class="cv-report-formats"><span class="cv-format">Excel</span><span class="cv-format">CSV</span></div>
              </div>
              <div class="cv-report-card">
                <h4>Lifecycle & Alternative Report</h4>
                <p>Lifecycle alerts, replacement readiness, candidate decisions, and unresolved engineering verification.</p>
                <div class="cv-report-formats"><span class="cv-format">PDF</span><span class="cv-format">Excel</span></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        report_col, bom_col = st.columns(2)
        with report_col:
            internal_nav_button(
                "Open Reports Center",
                "Reports",
                key=f"analysis_open_reports_{analysis_id}",
                use_container_width=True,
                analysis_id=analysis_id,
            )
        with bom_col:
            internal_nav_button(
                "Open Full BOM Workspace",
                "BOM Analyzer",
                key=f"analysis_open_bom_{analysis_id}",
                use_container_width=True,
                analysis_id=analysis_id,
            )

    # Sprint 34.2.6 — run after every tab and section has rendered. This timing is
    # essential: browsers may restore the previous scroll position after the
    # initial Streamlit DOM is mounted. Only saved-BOM navigation receives this
    # top reset; component-focused navigation keeps its targeted section jump.
    if saved_bom_top_requested or (analysis_changed and not component_focus_requested):
        components.html(
            """
            <script>
            (function () {
              const parentWindow = window.parent;
              const doc = parentWindow.document;

              try { parentWindow.history.scrollRestoration = 'manual'; } catch (error) {}

              const resetAnalysisTop = () => {
                const target = doc.getElementById('cv-analysis-page-top');
                const candidates = [
                  doc.querySelector('[data-testid="stMain"]'),
                  doc.querySelector('section.main'),
                  doc.querySelector('[data-testid="stAppViewContainer"]'),
                  doc.scrollingElement,
                  doc.documentElement,
                  doc.body
                ].filter(Boolean);

                for (const element of candidates) {
                  try {
                    element.scrollTop = 0;
                    if (typeof element.scrollTo === 'function') {
                      element.scrollTo({ top: 0, left: 0, behavior: 'auto' });
                    }
                  } catch (error) {}
                }

                try { parentWindow.scrollTo({ top: 0, left: 0, behavior: 'auto' }); } catch (error) {}
                if (target) {
                  try { target.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'auto' }); } catch (error) {}
                }
              };

              [0, 60, 160, 320, 650, 1100, 1700, 2400].forEach((delay) => {
                parentWindow.setTimeout(resetAnalysisTop, delay);
              });

              // Keep the focus token long enough for the delayed resets to win
              // over browser restoration, then remove it without rerunning the app.
              parentWindow.setTimeout(() => {
                try {
                  const url = new URL(parentWindow.location.href);
                  if (url.searchParams.get('focus') === 'analysis-top') {
                    url.searchParams.delete('focus');
                    parentWindow.history.replaceState({}, '', url.toString());
                  }
                } catch (error) {}
              }, 2600);
            })();
            </script>
            """,
            height=0,
            width=0,
        )

