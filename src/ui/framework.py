from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st


ASSET_CSS_PATH = Path(__file__).resolve().parents[2] / "assets" / "css" / "premium.css"


def inject_premium_css() -> None:
    """Inject the shared premium CSS file once per run."""
    try:
        css = ASSET_CSS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        css = ""
    if css:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value)


def user_initials(email: str | None) -> str:
    if not email:
        return "U"
    local = email.split("@")[0].replace(".", " ").replace("_", " ").strip()
    parts = [p for p in local.split() if p]
    if not parts:
        return email[:1].upper()
    return "".join(p[0].upper() for p in parts[:2])


def render_topbar(current_user: Optional[dict] = None, active_page: str = "Dashboard") -> None:
    """Render compact top navigation with logo left and user info right."""
    email = ""
    name = "Workspace"
    if current_user:
        email = _safe_text(current_user.get("email", ""))
        name = _safe_text(current_user.get("full_name") or current_user.get("name") or "Workspace")
    initials = user_initials(email)
    st.markdown(
        f"""
        <div class="brc-topbar">
          <div class="brc-topbar-left">
            <div class="brc-logo-mark">B</div>
            <div>
              <div class="brc-topbar-title">BOM Risk Checker</div>
              <div class="brc-topbar-subtitle">{active_page} · Engineering sourcing intelligence</div>
            </div>
          </div>
          <div class="brc-topbar-right">
            <div class="brc-user-chip">
              <div class="brc-user-avatar">{initials}</div>
              <div class="brc-user-meta">
                <div class="brc-user-name">{name}</div>
                <div class="brc-user-email">{email}</div>
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_badge(label: str, kind: str = "info") -> str:
    class_name = {
        "success": "brc-badge-success",
        "warning": "brc-badge-warning",
        "danger": "brc-badge-danger",
        "info": "brc-badge-info",
    }.get(kind, "")
    return f'<span class="brc-badge {class_name}">{label}</span>'


def metric_card(label: str, value: Any, badge: str = "", badge_kind: str = "info") -> None:
    badge_html = status_badge(badge, badge_kind) if badge else ""
    st.markdown(
        f"""
        <div class="kpi-card">
          <div class="kpi-label">{label}</div>
          <div class="kpi-value">{value}</div>
          <div class="kpi-note">{badge_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    eyebrow_html = f'<div class="brc-eyebrow">{eyebrow}</div>' if eyebrow else ""
    st.markdown(
        f"""
        <div class="brc-hero">
          {eyebrow_html}
          <div class="brc-hero-title">{title}</div>
          <p class="brc-hero-subtitle">{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def light_plotly_layout(fig: Any, height: int = 360) -> Any:
    """Apply the shared light Plotly theme."""
    fig.update_layout(
        height=height,
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        font=dict(color="#0F172A", family="Inter, Segoe UI, sans-serif"),
        margin=dict(l=40, r=24, t=28, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(gridcolor="#E5E7EB", zerolinecolor="#E5E7EB", linecolor="#CBD5E1")
    fig.update_yaxes(gridcolor="#E5E7EB", zerolinecolor="#E5E7EB", linecolor="#CBD5E1")
    return fig


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy suitable for display without mutating business data."""
    if df is None:
        return pd.DataFrame()
    return df.copy()
