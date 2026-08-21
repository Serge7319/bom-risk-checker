"""
Cadivor Milestone 4 — Premium Design System
Place this file at: src/cadivor_design_system.py

How to use in your Streamlit app:
    from src.cadivor_design_system import apply_cadivor_design_system
    apply_cadivor_design_system()

Optional helper components:
    from src.cadivor_design_system import (
        premium_page_header,
        premium_metric_card,
        premium_section_header,
        premium_empty_state,
        premium_status_badge,
        premium_action_card,
        premium_insight_card,
        premium_kpi_grid,
    )

This file is intentionally self-contained so it can be introduced without breaking
existing Milestone 3 functionality. It upgrades the global visual language first:
typography, cards, buttons, tables, alerts, tabs, inputs, expanders, uploaders,
sidebar, top spacing, shadows, and status components.
"""

from __future__ import annotations

from html import escape
from typing import Iterable, Mapping, Sequence

import streamlit as st


CADIVOR_BLUE = "#2563eb"
CADIVOR_BLUE_DARK = "#1d4ed8"
CADIVOR_NAVY = "#0f172a"
CADIVOR_SLATE = "#64748b"
CADIVOR_MUTED = "#94a3b8"
CADIVOR_BG = "#f6f8fc"
CADIVOR_CARD = "#ffffff"
CADIVOR_BORDER = "#e2e8f0"
CADIVOR_GREEN = "#16a34a"
CADIVOR_AMBER = "#f59e0b"
CADIVOR_RED = "#dc2626"


def apply_cadivor_design_system() -> None:
    """Inject the Milestone 4 global premium design system."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

        :root {{
            --cadivor-blue: {CADIVOR_BLUE};
            --cadivor-blue-dark: {CADIVOR_BLUE_DARK};
            --cadivor-navy: {CADIVOR_NAVY};
            --cadivor-slate: {CADIVOR_SLATE};
            --cadivor-muted: {CADIVOR_MUTED};
            --cadivor-bg: {CADIVOR_BG};
            --cadivor-card: {CADIVOR_CARD};
            --cadivor-border: {CADIVOR_BORDER};
            --cadivor-green: {CADIVOR_GREEN};
            --cadivor-amber: {CADIVOR_AMBER};
            --cadivor-red: {CADIVOR_RED};
            --cadivor-radius: 18px;
            --cadivor-radius-sm: 12px;
            --cadivor-shadow: 0 18px 55px rgba(15, 23, 42, 0.08);
            --cadivor-shadow-sm: 0 10px 30px rgba(15, 23, 42, 0.06);
        }}

        html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
        }}

        .stApp {{
            background:
                radial-gradient(circle at 18% 8%, rgba(37, 99, 235, 0.10), transparent 28%),
                radial-gradient(circle at 85% 18%, rgba(59, 130, 246, 0.08), transparent 30%),
                linear-gradient(180deg, #f9fbff 0%, var(--cadivor-bg) 45%, #f8fafc 100%);
            color: var(--cadivor-navy);
        }}

        .block-container {{
            padding-top: 2.0rem !important;
            padding-bottom: 5rem !important;
            max-width: 1500px !important;
        }}

        h1, h2, h3, h4 {{
            color: var(--cadivor-navy) !important;
            letter-spacing: -0.04em !important;
            font-weight: 850 !important;
        }}

        h1 {{ font-size: clamp(2.15rem, 4vw, 4.2rem) !important; line-height: 0.98 !important; }}
        h2 {{ font-size: clamp(1.65rem, 2.4vw, 2.65rem) !important; line-height: 1.05 !important; }}
        h3 {{ font-size: 1.35rem !important; }}
        p, li, label, span, div {{ text-rendering: geometricPrecision; }}

        [data-testid="stSidebar"] {{
            background: rgba(255,255,255,0.82) !important;
            backdrop-filter: blur(18px);
            border-right: 1px solid rgba(226, 232, 240, 0.95);
            box-shadow: 10px 0 35px rgba(15, 23, 42, 0.04);
        }}

        [data-testid="stSidebar"] * {{
            font-family: 'Inter', sans-serif !important;
        }}

        [data-testid="stSidebar"] a,
        [data-testid="stSidebar"] button,
        [data-testid="stSidebar"] [role="button"] {{
            border-radius: 14px !important;
            transition: all 180ms ease !important;
        }}

        [data-testid="stSidebar"] a:hover,
        [data-testid="stSidebar"] button:hover,
        [data-testid="stSidebar"] [role="button"]:hover {{
            transform: translateX(2px);
            background: rgba(37, 99, 235, 0.08) !important;
        }}

        div[data-testid="stMetric"] {{
            background: rgba(255,255,255,0.86);
            border: 1px solid rgba(226, 232, 240, 0.96);
            box-shadow: var(--cadivor-shadow-sm);
            border-radius: var(--cadivor-radius);
            padding: 1.15rem 1.2rem;
        }}

        div[data-testid="stMetric"] label {{
            color: var(--cadivor-slate) !important;
            font-weight: 750 !important;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            font-size: 0.72rem !important;
        }}

        div[data-testid="stMetricValue"] {{
            color: var(--cadivor-navy) !important;
            font-weight: 900 !important;
            letter-spacing: -0.055em;
        }}

        .stButton > button,
        .stDownloadButton > button,
        button[kind="primary"] {{
            background: linear-gradient(135deg, var(--cadivor-blue), #3b82f6) !important;
            color: white !important;
            border: 0 !important;
            border-radius: 14px !important;
            font-weight: 800 !important;
            letter-spacing: -0.015em;
            padding: 0.75rem 1.2rem !important;
            box-shadow: 0 14px 30px rgba(37, 99, 235, 0.22) !important;
            transition: transform 160ms ease, box-shadow 160ms ease, filter 160ms ease !important;
        }}

        .stButton > button:hover,
        .stDownloadButton > button:hover {{
            transform: translateY(-1px);
            filter: brightness(1.03);
            box-shadow: 0 18px 42px rgba(37, 99, 235, 0.30) !important;
        }}

        .stButton > button:active,
        .stDownloadButton > button:active {{ transform: translateY(0); }}

        input, textarea, [data-baseweb="select"] > div {{
            border-radius: 14px !important;
            border-color: #d7dfeb !important;
            background: rgba(255,255,255,0.92) !important;
            box-shadow: 0 1px 0 rgba(15,23,42,0.03) !important;
        }}

        input:focus, textarea:focus {{
            border-color: var(--cadivor-blue) !important;
            box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.12) !important;
        }}

        [data-testid="stFileUploader"] section {{
            border: 1.5px dashed #bfd2f5 !important;
            background: linear-gradient(180deg, rgba(239,246,255,0.76), rgba(255,255,255,0.86)) !important;
            border-radius: 20px !important;
            padding: 1.2rem !important;
        }}

        [data-testid="stFileUploader"] section:hover {{
            border-color: var(--cadivor-blue) !important;
            box-shadow: 0 18px 45px rgba(37, 99, 235, 0.10);
        }}

        .stDataFrame, [data-testid="stDataFrame"], div[data-testid="stTable"] {{
            border-radius: 18px !important;
            overflow: hidden !important;
            border: 1px solid rgba(226,232,240,0.96) !important;
            box-shadow: var(--cadivor-shadow-sm) !important;
            background: white !important;
        }}

        div[data-testid="stExpander"] {{
            border: 1px solid rgba(226, 232, 240, 0.96) !important;
            border-radius: 16px !important;
            background: rgba(255,255,255,0.90) !important;
            box-shadow: 0 8px 24px rgba(15,23,42,0.045) !important;
            overflow: hidden;
        }}

        div[data-testid="stExpander"] details summary {{
            font-weight: 750 !important;
            color: var(--cadivor-navy) !important;
        }}

        [data-testid="stAlert"] {{
            border-radius: 16px !important;
            border: 1px solid rgba(191, 219, 254, 0.9) !important;
            box-shadow: 0 12px 35px rgba(15,23,42,0.045);
        }}

        .stTabs [data-baseweb="tab-list"] {{
            gap: 0.45rem;
            background: rgba(255,255,255,0.76);
            border: 1px solid rgba(226,232,240,0.9);
            border-radius: 18px;
            padding: 0.4rem;
        }}

        .stTabs [data-baseweb="tab"] {{
            border-radius: 14px;
            font-weight: 800;
            color: var(--cadivor-slate);
        }}

        .stTabs [aria-selected="true"] {{
            background: #eff6ff;
            color: var(--cadivor-blue) !important;
        }}

        div[data-testid="stHorizontalBlock"] {{
            gap: 1.05rem;
        }}

        .cadivor-hero {{
            position: relative;
            overflow: hidden;
            background:
                linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 64, 175, 0.94)),
                radial-gradient(circle at top right, rgba(96, 165, 250, 0.55), transparent 38%);
            border: 1px solid rgba(147, 197, 253, 0.35);
            border-radius: 30px;
            box-shadow: 0 24px 80px rgba(15, 23, 42, 0.18);
            padding: 2.1rem 2.2rem;
            margin-bottom: 1.3rem;
            color: white;
        }}

        .cadivor-hero::after {{
            content: "";
            position: absolute;
            width: 340px;
            height: 340px;
            right: -90px;
            top: -140px;
            background: radial-gradient(circle, rgba(255,255,255,0.20), transparent 67%);
            pointer-events: none;
        }}

        .cadivor-eyebrow {{
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.34rem 0.68rem;
            border-radius: 999px;
            background: rgba(255,255,255,0.12);
            border: 1px solid rgba(255,255,255,0.17);
            color: #dbeafe;
            font-weight: 900;
            font-size: 0.72rem;
            letter-spacing: 0.13em;
            text-transform: uppercase;
            margin-bottom: 1rem;
        }}

        .cadivor-hero h1 {{
            color: white !important;
            max-width: 850px;
            margin: 0 !important;
        }}

        .cadivor-hero p {{
            color: #cbd5e1;
            max-width: 880px;
            font-size: 1.02rem;
            line-height: 1.7;
            margin-top: 0.8rem;
            margin-bottom: 0;
        }}

        .cadivor-card {{
            background: rgba(255,255,255,0.90);
            border: 1px solid rgba(226,232,240,0.96);
            border-radius: var(--cadivor-radius);
            box-shadow: var(--cadivor-shadow-sm);
            padding: 1.15rem 1.2rem;
            transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
        }}

        .cadivor-card:hover {{
            transform: translateY(-2px);
            box-shadow: var(--cadivor-shadow);
            border-color: rgba(147, 197, 253, 0.85);
        }}

        .cadivor-card-title {{
            font-weight: 900;
            font-size: 0.78rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--cadivor-slate);
            margin-bottom: 0.65rem;
        }}

        .cadivor-card-value {{
            font-weight: 950;
            color: var(--cadivor-navy);
            font-size: 2.1rem;
            letter-spacing: -0.06em;
            line-height: 1;
            margin-bottom: 0.55rem;
        }}

        .cadivor-card-caption {{
            color: var(--cadivor-slate);
            font-size: 0.88rem;
            line-height: 1.55;
            font-weight: 550;
        }}

        .cadivor-section {{
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1rem;
            margin: 2rem 0 0.85rem;
        }}

        .cadivor-section h2 {{
            margin: 0 !important;
            font-size: 1.55rem !important;
        }}

        .cadivor-section p {{
            margin: 0.28rem 0 0;
            color: var(--cadivor-slate);
            font-size: 0.94rem;
        }}

        .cadivor-badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            padding: 0.35rem 0.65rem;
            font-size: 0.78rem;
            font-weight: 850;
            border: 1px solid transparent;
            white-space: nowrap;
        }}

        .cadivor-badge-low {{ background: #ecfdf5; color: #047857; border-color: #bbf7d0; }}
        .cadivor-badge-medium {{ background: #fffbeb; color: #b45309; border-color: #fde68a; }}
        .cadivor-badge-high {{ background: #fef2f2; color: #b91c1c; border-color: #fecaca; }}
        .cadivor-badge-blue {{ background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }}
        .cadivor-badge-dark {{ background: #f1f5f9; color: #0f172a; border-color: #e2e8f0; }}

        .cadivor-empty {{
            border-radius: 24px;
            border: 1px solid rgba(226,232,240,0.96);
            background: rgba(255,255,255,0.88);
            box-shadow: var(--cadivor-shadow-sm);
            padding: 3rem 1.25rem;
            text-align: center;
        }}

        .cadivor-empty-icon {{
            width: 54px;
            height: 54px;
            border-radius: 18px;
            background: #eff6ff;
            color: var(--cadivor-blue);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 1.35rem;
            font-weight: 900;
            margin-bottom: 0.8rem;
        }}

        .cadivor-empty h3 {{ margin: 0.2rem 0 0.3rem !important; }}
        .cadivor-empty p {{ color: var(--cadivor-slate); margin: 0 auto; max-width: 600px; line-height: 1.65; }}

        .cadivor-action-card {{
            min-height: 150px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}

        .cadivor-action-icon {{
            width: 42px;
            height: 42px;
            border-radius: 14px;
            background: #eff6ff;
            color: var(--cadivor-blue);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 900;
            margin-bottom: 0.8rem;
        }}

        .cadivor-action-title {{
            font-size: 1rem;
            font-weight: 900;
            color: var(--cadivor-navy);
            margin-bottom: 0.3rem;
        }}

        .cadivor-action-copy {{
            color: var(--cadivor-slate);
            font-size: 0.9rem;
            line-height: 1.55;
        }}

        .cadivor-insight {{
            border-left: 4px solid var(--cadivor-blue);
            background: linear-gradient(90deg, rgba(239,246,255,0.88), rgba(255,255,255,0.90));
        }}

        .cadivor-divider {{
            height: 1px;
            width: 100%;
            background: linear-gradient(90deg, transparent, rgba(148,163,184,0.45), transparent);
            margin: 1.6rem 0;
        }}

        @media (max-width: 900px) {{
            .block-container {{ padding-left: 1rem !important; padding-right: 1rem !important; }}
            .cadivor-hero {{ padding: 1.45rem; border-radius: 22px; }}
            .cadivor-section {{ display: block; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _safe(value: object) -> str:
    return escape(str(value))


def premium_page_header(
    title: str,
    subtitle: str = "",
    eyebrow: str = "Cadivor Intelligence",
    right_html: str | None = None,
) -> None:
    """Render a premium hero header for major pages."""
    right = f"<div>{right_html}</div>" if right_html else ""
    st.markdown(
        f"""
        <div class="cadivor-hero">
            <div class="cadivor-eyebrow">{_safe(eyebrow)}</div>
            <h1>{_safe(title)}</h1>
            <p>{_safe(subtitle)}</p>
            {right}
        </div>
        """,
        unsafe_allow_html=True,
    )


def premium_section_header(title: str, subtitle: str = "", action_html: str | None = None) -> None:
    action = action_html or ""
    st.markdown(
        f"""
        <div class="cadivor-section">
            <div>
                <h2>{_safe(title)}</h2>
                <p>{_safe(subtitle)}</p>
            </div>
            <div>{action}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def premium_metric_card(
    title: str,
    value: object,
    caption: str = "",
    status: str | None = None,
    accent: str = "blue",
) -> None:
    badge = premium_status_badge(status, accent=accent, return_html=True) if status else ""
    st.markdown(
        f"""
        <div class="cadivor-card">
            <div class="cadivor-card-title">{_safe(title)}</div>
            <div class="cadivor-card-value">{_safe(value)}</div>
            <div class="cadivor-card-caption">{_safe(caption)}</div>
            <div style="margin-top: .7rem;">{badge}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def premium_kpi_grid(cards: Sequence[Mapping[str, object]], columns: int = 4) -> None:
    """Render a responsive KPI row using premium metric cards."""
    cols = st.columns(columns)
    for idx, card in enumerate(cards):
        with cols[idx % columns]:
            premium_metric_card(
                title=str(card.get("title", "Metric")),
                value=card.get("value", "—"),
                caption=str(card.get("caption", "")),
                status=str(card.get("status")) if card.get("status") is not None else None,
                accent=str(card.get("accent", "blue")),
            )


def premium_status_badge(status: str, accent: str = "blue", return_html: bool = False) -> str | None:
    normalized = (accent or status or "blue").lower()
    if normalized in {"low", "healthy", "excellent", "success", "green"}:
        css = "cadivor-badge-low"
        dot = "●"
    elif normalized in {"medium", "warning", "amber", "review"}:
        css = "cadivor-badge-medium"
        dot = "●"
    elif normalized in {"high", "critical", "error", "red"}:
        css = "cadivor-badge-high"
        dot = "●"
    elif normalized in {"dark", "neutral", "gray", "grey"}:
        css = "cadivor-badge-dark"
        dot = "•"
    else:
        css = "cadivor-badge-blue"
        dot = "●"

    html = f'<span class="cadivor-badge {css}">{dot} {_safe(status)}</span>'
    if return_html:
        return html
    st.markdown(html, unsafe_allow_html=True)
    return None


def premium_empty_state(
    title: str,
    message: str,
    icon: str = "□",
) -> None:
    st.markdown(
        f"""
        <div class="cadivor-empty">
            <div class="cadivor-empty-icon">{_safe(icon)}</div>
            <h3>{_safe(title)}</h3>
            <p>{_safe(message)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def premium_action_card(title: str, copy: str, icon: str = "→") -> None:
    st.markdown(
        f"""
        <div class="cadivor-card cadivor-action-card">
            <div>
                <div class="cadivor-action-icon">{_safe(icon)}</div>
                <div class="cadivor-action-title">{_safe(title)}</div>
                <div class="cadivor-action-copy">{_safe(copy)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def premium_insight_card(title: str, message: str, status: str = "Insight") -> None:
    badge = premium_status_badge(status, accent="blue", return_html=True)
    st.markdown(
        f"""
        <div class="cadivor-card cadivor-insight">
            <div style="display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:.55rem;">
                <div class="cadivor-action-title">{_safe(title)}</div>
                {badge}
            </div>
            <div class="cadivor-action-copy">{_safe(message)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def premium_divider() -> None:
    st.markdown('<div class="cadivor-divider"></div>', unsafe_allow_html=True)


def render_dashboard_premium_intro(
    user_name: str = "Serge",
    portfolio_health: int | float | str = "—",
    high_risk_parts: int | float | str = "—",
    saved_analyses: int | float | str = "—",
    alternatives_found: int | float | str = "—",
) -> None:
    """Optional drop-in section for Dashboard 3.0 phase."""
    premium_page_header(
        title=f"Good afternoon, {user_name}.",
        subtitle="Monitor BOM health, supplier exposure, lifecycle movement, and recommended engineering actions from one Cadivor workspace.",
        eyebrow="Workspace Intelligence",
    )
    premium_kpi_grid(
        [
            {"title": "Portfolio Health", "value": portfolio_health, "caption": "Average BOM health score", "status": "Review", "accent": "medium"},
            {"title": "High-Risk Parts", "value": high_risk_parts, "caption": "Components needing review", "status": "Priority", "accent": "high"},
            {"title": "Saved Analyses", "value": saved_analyses, "caption": "BOM reviews stored", "status": "Ready", "accent": "green"},
            {"title": "Alternatives Found", "value": alternatives_found, "caption": "Candidate records saved", "status": "Sourcing", "accent": "blue"},
        ],
        columns=4,
    )


def render_quick_actions() -> None:
    premium_section_header(
        "Quick Actions",
        "Jump into the workflows engineering and sourcing teams use most often.",
    )
    cols = st.columns(4)
    actions = [
        ("Analyze a BOM", "Upload CSV or Excel files and generate a risk profile.", "+"),
        ("Find Alternatives", "Compare compatible replacement candidates and supplier coverage.", "⇄"),
        ("Review Alerts", "Check stock, lifecycle, and sourcing changes across monitored parts.", "!"),
        ("Export Reports", "Download engineering-ready reports for review and sourcing.", "↧"),
    ]
    for col, (title, copy, icon) in zip(cols, actions):
        with col:
            premium_action_card(title, copy, icon)


__all__ = [
    "apply_cadivor_design_system",
    "premium_page_header",
    "premium_section_header",
    "premium_metric_card",
    "premium_kpi_grid",
    "premium_status_badge",
    "premium_empty_state",
    "premium_action_card",
    "premium_insight_card",
    "premium_divider",
    "render_dashboard_premium_intro",
    "render_quick_actions",
]
