"""Cadivor saved-analysis workspace with persistent tab navigation."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import re
from typing import Any

import pandas as pd
import streamlit as st
from src.ui.navigation import navigate_to, internal_nav_button
from src.ai_advisor import build_engineering_supply_advisor
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
    try:
        query = (
            supabase.table(table)
            .select("*")
            .eq("user_id", user_id)
            .eq("analysis_id", analysis_id)
        )
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        if order:
            query = query.order(order, desc=True)
        if limit:
            query = query.limit(limit)
        return query.execute().data or []
    except Exception:
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
        .cv-copilot-readiness{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff 0%,#f3f8ff 65%,#e8f1ff 100%);border-radius:24px;padding:22px;box-shadow:0 20px 50px rgba(37,99,235,.08);margin-bottom:14px}
        .cv-copilot-readiness-top{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}.cv-copilot-readiness h2{color:#0f172a!important;font-size:25px;font-weight:980;letter-spacing:-.035em;margin:0 0 6px}.cv-copilot-readiness p{color:#52647a!important;font-size:12px;font-weight:740;line-height:1.55;margin:0}
        .cv-copilot-action{border:1px solid #dbe3ef;background:#fff;border-radius:22px;padding:19px;margin-bottom:13px;box-shadow:0 14px 36px rgba(15,23,42,.055)}.cv-copilot-action-head{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:flex-start}.cv-copilot-action h3{color:#0f172a!important;font-size:16px;font-weight:980;margin:0 0 5px}.cv-copilot-action-sub{color:#64748b!important;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.07em}
        .cv-copilot-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px;margin:13px 0}.cv-copilot-panel{border:1px solid #e2e8f0;background:#f8fafc;border-radius:15px;padding:13px}.cv-copilot-panel span{display:block;color:#2563eb!important;font-size:9px;font-weight:980;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}.cv-copilot-panel p{color:#334155!important;font-size:11px;font-weight:720;line-height:1.55;margin:0}
        .cv-impact-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:12px 0}.cv-impact-box{border:1px solid #e2e8f0;border-radius:13px;padding:10px;background:#fff}.cv-impact-box span{display:block;color:#64748b!important;font-size:8px;font-weight:950;text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px}.cv-impact-meter{font-size:12px;letter-spacing:1px;color:#2563eb!important;white-space:nowrap}
        .cv-improvement{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:12px}.cv-improvement div{border:1px solid #dbeafe;background:#eff6ff;border-radius:13px;padding:10px}.cv-improvement span{display:block;color:#64748b!important;font-size:8px;font-weight:950;text-transform:uppercase;letter-spacing:.07em;margin-bottom:5px}.cv-improvement strong{color:#0f172a!important;font-size:13px;font-weight:980}
        .cv-copilot-exec{border:1px solid #c7d2fe;background:linear-gradient(135deg,#eef2ff,#fff);border-radius:20px;padding:18px;margin:14px 0}.cv-copilot-exec span{display:block;color:#4f46e5!important;font-size:9px;font-weight:980;text-transform:uppercase;letter-spacing:.09em;margin-bottom:7px}.cv-copilot-exec p{color:#1e293b!important;font-size:12px;font-weight:760;line-height:1.65;margin:0}
        @media(max-width:900px){.cv-copilot-two,.cv-impact-grid,.cv-improvement{grid-template-columns:1fr 1fr}.cv-copilot-action-head{grid-template-columns:auto 1fr}}
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
        .cv-analysis-table-wrap{background:#fff;border:1px solid #e2e8f0;border-radius:22px;box-shadow:0 18px 44px rgba(15,23,42,.055);overflow:hidden}.cv-analysis-table-head{display:flex;justify-content:space-between;align-items:center;padding:18px 20px;border-bottom:1px solid #e2e8f0}.cv-analysis-component{display:grid;grid-template-columns:1.2fr 1fr .75fr .75fr auto;gap:12px;align-items:center;padding:13px 20px;border-bottom:1px solid #eef2f7}.cv-analysis-component .head{color:#0b1220!important;font-size:13px;font-weight:980}.cv-analysis-component .sub{color:#64748b!important;font-size:11px;font-weight:800;margin-top:3px}
        [data-testid="stTabs"]{margin-top:8px}[data-testid="stTabs"] [data-baseweb="tab-list"]{position:sticky;top:64px;z-index:40;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:6px;box-shadow:0 12px 28px rgba(15,23,42,.06);gap:6px}[data-testid="stTabs"] [data-baseweb="tab"]{height:42px;border-radius:11px;padding:0 18px;font-weight:900;color:#475569}[data-testid="stTabs"] [aria-selected="true"]{background:#eff6ff!important;color:#2563eb!important}
        @media(max-width:1180px){.cv-analysis-hero{grid-template-columns:1fr}.cv-analysis-component{grid-template-columns:1fr}.cv-readiness-metrics{grid-template-columns:1fr}}@media(max-width:700px){.cv-analysis-summary{grid-template-columns:1fr}.cv-analysis-title{font-size:30px}.cv-analysis-hero{padding:20px}}
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

    focused_component_mpn = _safe(_qp_value("focus_mpn"), "")
    focused_component = None
    if focused_component_mpn:
        focused_component = next(
            (
                row
                for row in parts
                if _safe(row.get("mpn") or row.get("part_number")).upper()
                == focused_component_mpn.upper()
            ),
            None,
        )

    st.markdown('<a class="cv-analysis-back" href="?page=BOM%20Analyzer" target="_self">' + _lucide("arrow-left",16) + ' Back to BOM Analyzer</a>', unsafe_allow_html=True)
    st.markdown(
        f'''<div class="cv-analysis-hero"><div><div class="cv-analysis-eyebrow">{_lucide('layers',14)} Analysis Workspace</div><h1 class="cv-analysis-title">{html.escape(project)}</h1><p class="cv-analysis-sub">A permanent engineering record for this saved BOM analysis. Use the tabs below to review one focused area at a time without losing your place.</p><div class="cv-analysis-actions"><a class="cv-analysis-btn primary" href="?page=BOM%20Analyzer&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Open in BOM Analyzer →</a><a class="cv-analysis-btn" href="?page=Alternative%20Finder&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Find Alternatives</a><a class="cv-analysis-btn" href="?page=Monitoring&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Monitor Components</a><a class="cv-analysis-btn" href="?page=Reports&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Reports Center</a></div></div><div class="cv-analysis-summary"><div class="cv-analysis-mini"><span>Health</span><strong>{health}</strong><small>{risk_status}</small></div><div class="cv-analysis-mini"><span>Parts</span><strong>{total_parts}</strong><small>{html.escape(filename)}</small></div><div class="cv-analysis-mini"><span>High Risk</span><strong>{high}</strong><small>Components needing review</small></div><div class="cv-analysis-mini"><span>Updated</span><strong>{_relative_date(created)}</strong><small>{_date(created)}</small></div></div></div>''',
        unsafe_allow_html=True,
    )

    if focused_component:
        focused_risk = _safe(
            focused_component.get("risk_level")
            or focused_component.get("risk_level_display"),
            "Unknown",
        )
        focused_lifecycle = _safe(
            focused_component.get("lifecycle_status"),
            "Unknown",
        )
        focused_stock = _num(focused_component.get("stock_available"), 0)
        focused_suppliers = _num(focused_component.get("supplier_count"), 0)
        focused_reasons = _safe(
            focused_component.get("risk_reasons"),
            "No detailed risk explanation is available.",
        )

        st.markdown(
            f"""
            <section class="cv-copilot-readiness">
              <div class="cv-copilot-readiness-top">
                <div>
                  <div class="cv-advisor-kicker">Focused Component Review</div>
                  <h2>{html.escape(focused_component_mpn)}</h2>
                  <p>{html.escape(focused_reasons)}</p>
                </div>
                <span class="cv-analysis-pill {'bad' if focused_risk.lower() == 'high' else 'warn' if focused_risk.lower() == 'medium' else 'good'}">
                  {html.escape(focused_risk)}
                </span>
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

        focus_cols = st.columns(4)
        focus_cols[0].metric("Lifecycle", focused_lifecycle)
        focus_cols[1].metric("Available Stock", f"{focused_stock:,}")
        focus_cols[2].metric("Supplier Sources", focused_suppliers)
        focus_cols[3].metric(
            "Risk Score",
            f"{_num(focused_component.get('risk_score'), 0)}/100",
        )

        action_cols = st.columns(3)
        with action_cols[0]:
            internal_nav_button(
                "Back to Engineering Copilot",
                "Analysis Details",
                key=f"focus_back_{analysis_id}_{focused_component_mpn}",
                use_container_width=True,
                analysis_id=analysis_id,
            )
        with action_cols[1]:
            internal_nav_button(
                "Find Alternatives",
                "Alternative Finder",
                key=f"focus_alt_{analysis_id}_{focused_component_mpn}",
                use_container_width=True,
                analysis_id=analysis_id,
                original_part=focused_component_mpn,
                return_analysis_id=analysis_id,
            )
        with action_cols[2]:
            internal_nav_button(
                "Open Monitoring",
                "Monitoring",
                key=f"focus_monitor_{analysis_id}_{focused_component_mpn}",
                use_container_width=True,
                analysis_id=analysis_id,
                mpn=focused_component_mpn,
                return_analysis_id=analysis_id,
            )

        st.divider()

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
        "AI Advisor",
        "Overview",
        "Intelligence",
        "Components",
        "Alternatives",
        "Discussions",
        "Timeline",
        "Reports",
    ])

    with advisor_tab:
        _section_header(
            "Engineering Copilot",
            "Production-readiness guidance with engineering, procurement, and supply-chain reasoning.",
        )

        readiness = _safe(
            advisor.get("production_readiness"),
            "Prototype Ready — Production Review Needed",
        )
        readiness_tone = _safe(advisor.get("readiness_tone"), "warn")
        st.markdown(
            f"""
            <section class="cv-copilot-readiness">
              <div class="cv-copilot-readiness-top">
                <div>
                  <div class="cv-advisor-kicker">Cadivor Engineering Copilot Assessment</div>
                  <h2>{html.escape(readiness)}</h2>
                  <p>{html.escape(_safe(advisor.get('readiness_reason'), 'Focused review is recommended.'))}</p>
                </div>
                <span class="cv-analysis-pill {html.escape(readiness_tone)}">
                  {_num(advisor.get('confidence'), 0)}% confidence
                </span>
              </div>
            </section>

            <div class="cv-advisor-score-grid">
              <div class="cv-advisor-score">
                <span>Production Readiness</span>
                <strong>{html.escape(readiness)}</strong>
                <small>Current release posture</small>
              </div>
              <div class="cv-advisor-score">
                <span>Engineering Exposure</span>
                <strong>{_num(advisor.get('engineering_exposure_score'), 0)}/100</strong>
                <small>Lifecycle and design exposure</small>
              </div>
              <div class="cv-advisor-score">
                <span>Supply Chain Exposure</span>
                <strong>{_num(advisor.get('supply_exposure_score'), 0)}/100</strong>
                <small>Availability, sourcing, and lead-time exposure</small>
              </div>
              <div class="cv-advisor-score">
                <span>Estimated Resolution Effort</span>
                <strong>{_num(advisor.get('estimated_total_effort'), 0)} hrs</strong>
                <small>Across the recommended actions</small>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="cv-copilot-exec">
              <span>Executive Recommendation</span>
              <p>{html.escape(_safe(advisor.get('executive_recommendation'), 'No executive recommendation available.'))}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("#### Engineering Copilot Recommendations")

        for index, action in enumerate(advisor.get("priority_actions") or [], start=1):
            urgency = _safe(action.get("business_priority"), "Moderate")
            urgency_class = "bad" if urgency.lower() in {"critical", "high"} else "warn"
            impacts = action.get("impacts") or {}
            improvement = action.get("improvement") or {}

            def _meter(value):
                level = max(1, min(5, _num(value, 1)))
                return "■" * level + "□" * (5 - level)

            st.markdown(
                f"""
                <section class="cv-copilot-action">
                  <div class="cv-copilot-action-head">
                    <div class="cv-advisor-rank">{index}</div>
                    <div>
                      <div class="cv-copilot-action-sub">{html.escape(_safe(action.get('category'), 'Recommendation'))}</div>
                      <h3>{html.escape(_safe(action.get('title'), 'Review component risk'))}</h3>
                    </div>
                    <span class="cv-analysis-pill {urgency_class}">
                      {html.escape(urgency)}
                    </span>
                  </div>

                  <div class="cv-copilot-two">
                    <div class="cv-copilot-panel">
                      <span>Recommended Action</span>
                      <p>{html.escape(_safe(action.get('recommendation'), 'Review this component.'))}</p>
                    </div>
                    <div class="cv-copilot-panel">
                      <span>Why Cadivor Recommended This</span>
                      <p>{html.escape(_safe(action.get('why'), 'A risk signal was detected.'))}</p>
                    </div>
                    <div class="cv-copilot-panel">
                      <span>If Ignored</span>
                      <p>{html.escape(_safe(action.get('if_ignored'), 'The risk may increase closer to release.'))}</p>
                    </div>
                    <div class="cv-copilot-panel">
                      <span>Recommended Team</span>
                      <p><b>{html.escape(_safe(action.get('owner'), 'Engineering'))}</b><br>
                      Support: {html.escape(_safe(action.get('support_owner'), 'Procurement'))}<br>
                      Target: {html.escape(_safe(action.get('schedule'), 'Before release'))}</p>
                    </div>
                  </div>

                  <div class="cv-impact-grid">
                    <div class="cv-impact-box"><span>Engineering</span><div class="cv-impact-meter">{_meter(impacts.get('engineering'))}</div></div>
                    <div class="cv-impact-box"><span>Procurement</span><div class="cv-impact-meter">{_meter(impacts.get('procurement'))}</div></div>
                    <div class="cv-impact-box"><span>Production</span><div class="cv-impact-meter">{_meter(impacts.get('production'))}</div></div>
                    <div class="cv-impact-box"><span>Schedule</span><div class="cv-impact-meter">{_meter(impacts.get('schedule'))}</div></div>
                    <div class="cv-impact-box"><span>Cost</span><div class="cv-impact-meter">{_meter(impacts.get('cost'))}</div></div>
                  </div>

                  <div class="cv-advisor-tags">
                    <span class="cv-advisor-tag">Effort: {html.escape(_safe(action.get('effort'), '1 hour'))}</span>
                    <span class="cv-advisor-tag">Confidence: {_num(action.get('confidence'), 0)}%</span>
                    <span class="cv-advisor-tag">Signals used: {_num(action.get('signal_count'), 0)}</span>
                    <span class="cv-advisor-tag">Priority score: {_num(action.get('score'), 0)}/100</span>
                  </div>

                  <div class="cv-improvement">
                    <div><span>BOM Health</span><strong>{_num(improvement.get('health_before'), health)} → {_num(improvement.get('health_after'), health)}</strong></div>
                    <div><span>Health Gain</span><strong>+{_num(improvement.get('health_gain'), 0)}</strong></div>
                    <div><span>Supply Risk Reduction</span><strong>-{_num(improvement.get('supply_risk_reduction'), 0)}</strong></div>
                    <div><span>Issues Resolved</span><strong>{_num(improvement.get('lifecycle_issues_removed'), 0) + _num(improvement.get('sourcing_issues_removed'), 0)}</strong></div>
                  </div>
                </section>
                """,
                unsafe_allow_html=True,
            )

            with st.expander(
                f"Evidence used for recommendation {index}",
                expanded=False,
            ):
                signals = action.get("signals") or []
                if not signals:
                    st.caption("No detailed signal record is available.")
                else:
                    for signal in signals:
                        status = "Available" if signal.get("available") else "Missing"
                        st.markdown(
                            f"**{_safe(signal.get('name'), 'Signal')} — {status}**  \n"
                            f"{_safe(signal.get('detail'), 'No detail available.')}"
                        )

            button_cols = st.columns(3)
            route = _safe(action.get("action_route"), "component")
            mpn = _safe(action.get("part_number"), "")
            with button_cols[0]:
                internal_nav_button(
                    "Review Component",
                    "Analysis Details",
                    key=f"copilot_review_{analysis_id}_{index}",
                    use_container_width=True,
                    analysis_id=analysis_id,
                    focus_mpn=mpn,
                )
            with button_cols[1]:
                internal_nav_button(
                    "Find Alternative",
                    "Alternative Finder",
                    key=f"copilot_alternative_{analysis_id}_{index}",
                    use_container_width=True,
                    analysis_id=analysis_id,
                    original_part=mpn,
                    return_analysis_id=analysis_id,
                )
            with button_cols[2]:
                internal_nav_button(
                    "Open Monitoring",
                    "Monitoring",
                    key=f"copilot_monitor_{analysis_id}_{index}",
                    use_container_width=True,
                    analysis_id=analysis_id,
                    mpn=mpn,
                    return_analysis_id=analysis_id,
                )

        st.markdown("#### Cross-Functional Brief")
        brief_cols = st.columns(3)
        with brief_cols[0]:
            st.info(_safe(advisor.get("engineering_summary"), "No engineering summary available."))
        with brief_cols[1]:
            st.info(_safe(advisor.get("procurement_summary"), "No procurement summary available."))
        with brief_cols[2]:
            st.info(_safe(advisor.get("supply_chain_summary"), "No supply-chain summary available."))

        metrics = advisor.get("metrics") or {}
        st.markdown("#### Decision Signals")
        signal_cols = st.columns(6)
        signal_cols[0].metric("Lifecycle Concerns", _num(metrics.get("lifecycle_concerns"), 0))
        signal_cols[1].metric("No-Stock Parts", _num(metrics.get("no_stock"), 0))
        signal_cols[2].metric("Limited Sources", _num(metrics.get("limited_sources"), 0))
        signal_cols[3].metric("Long-Lead Parts", _num(metrics.get("long_lead"), 0))
        signal_cols[4].metric("Active Alerts", _num(metrics.get("active_alerts"), 0))
        signal_cols[5].metric("Saved Alternatives", _num(metrics.get("saved_alternatives"), 0))

    with overview_tab:
        _section_header("Decision Brief", "The most important engineering signals for this saved BOM.")
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
        _section_header(
            "Component Risk Report",
            "Search, filter, and inspect the saved component intelligence for this analysis.",
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

                selected_label = st.selectbox(
                    "Select a component to inspect",
                    options=list(part_labels.keys()),
                    key=f"analysis_component_selector_{analysis_id}",
                )
                selected_part = part_labels[selected_label]

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
                                '<div class="cv-analysis-component">'
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
                        <div class="cv-component-detail">
                          <div class="cv-analysis-card-title">
                            <span>Component Intelligence</span>
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
            ["All activity", "Analysis", "Monitoring alerts", "Alternative reviews", "Comments & notes"],
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
            timeline_html = ['<div class="cv-timeline">']
            for event in filtered_timeline[:250]:
                timestamp = _safe(event.get("timestamp"), "")[:19].replace("T", " ")
                kind = _safe(event.get("kind"), "analysis")
                timeline_html.append(
                    f"""
                    <div class="cv-timeline-item {html.escape(kind)}">
                      <div class="cv-timeline-title">{html.escape(_safe(event.get('title'), 'Engineering event'))}</div>
                      <div class="cv-timeline-meta">{html.escape(_safe(event.get('meta'), ''))} · {html.escape(timestamp)} UTC</div>
                      <div class="cv-timeline-body">{html.escape(_safe(event.get('body'), ''))}</div>
                    </div>
                    """
                )
            timeline_html.append("</div>")
            st.markdown("".join(timeline_html), unsafe_allow_html=True)

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

