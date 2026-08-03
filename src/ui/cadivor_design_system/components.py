"""Cadivor Sprint 64 — Premium component system."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system.icons import lucide

Tone = str

_BADGE_TONES: dict[str, Tone] = {
    "approved": "success",
    "qualified": "success",
    "active": "success",
    "monitoring": "info",
    "reviewing": "info",
    "informational": "info",
    "medium": "warning",
    "nrnd": "warning",
    "warning": "warning",
    "pending": "neutral",
    "draft": "neutral",
    "blocked": "danger",
    "eol": "danger",
    "high": "danger",
    "high risk": "danger",
    "critical": "danger",
    "low": "success",
}


def inject_cadivor_design_system() -> None:
    css_path = Path(__file__).resolve().parents[2] / "assets" / "css" / "cadivor_design_system.css"
    try:
        css = css_path.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style id='cadivor-design-system-s64'>{css}</style>", unsafe_allow_html=True)


def badge_tone(raw: Any) -> Tone:
    key = str(raw or "").strip().lower()
    return _BADGE_TONES.get(key, "neutral")


def cadivor_badge(label: Any, tone: Tone | None = None) -> str:
    resolved = tone or badge_tone(label)
    return (
        f'<span class="cv64-badge cv64-badge--{escape(resolved)}">'
        f"{escape(str(label))}</span>"
    )


@dataclass(frozen=True)
class MetricCard:
    label: str
    value: str
    status: str = ""
    detail: str = ""
    trend: str = ""
    trend_label: str = ""
    tone: Tone = "info"
    icon: str = "chart"


_ALLOWED_TONES = frozenset(
    {"success", "warning", "danger", "info", "monitoring", "confidence", "neutral"}
)


def _normalize_tone(raw: Any) -> str:
    tone = str(raw or "info").strip().lower()
    return tone if tone in _ALLOWED_TONES else "info"


def _sanitize_metric(metric: MetricCard) -> MetricCard:
    value = metric.value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        value_text = "—"
    else:
        value_text = str(value)
    return MetricCard(
        label=str(metric.label or "Metric"),
        value=value_text,
        status=str(metric.status or ""),
        detail=str(metric.detail or ""),
        trend=str(metric.trend or ""),
        trend_label=str(metric.trend_label or ""),
        tone=_normalize_tone(metric.tone),
        icon=str(metric.icon or "chart"),
    )


def _render_native_metric_row(metrics: Sequence[MetricCard], *, columns: int) -> None:
    """Last-resort KPI row using Streamlit metrics — never hides data."""
    if not metrics:
        return
    count = min(max(1, columns), 4, len(metrics))
    cols = st.columns(count)
    for index, metric in enumerate(metrics):
        with cols[index % count]:
            delta = metric.trend_label or metric.status or metric.detail or None
            st.metric(metric.label, metric.value, delta=delta or None)


def _render_premium_metric_html(metrics: Sequence[MetricCard], *, columns: int) -> None:
    cards = []
    for metric in metrics:
        trend_html = ""
        if metric.trend_label:
            arrow = metric.trend or "neutral"
            cards_trend_icon = "arrow-up" if arrow == "up" else "arrow-down" if arrow == "down" else "activity"
            trend_html = (
                f'<div class="cv64-metric__trend cv64-metric__trend--{escape(arrow)}">'
                f'{lucide(cards_trend_icon, 14)}'
                f"<span>{escape(metric.trend_label)}</span></div>"
            )
        status_html = (
            f'<div class="cv64-metric__status">{escape(metric.status)}</div>'
            if metric.status
            else ""
        )
        detail_html = (
            f'<div class="cv64-metric__detail">{escape(metric.detail)}</div>'
            if metric.detail and not metric.trend_label
            else ""
        )
        cards.append(
            f'<article class="cv64-metric cv64-metric--{escape(metric.tone)}">'
            f'<div class="cv64-metric__accent"></div>'
            f'<div class="cv64-metric__head">'
            f'<span class="cv64-metric__icon">{lucide(metric.icon, 18)}</span>'
            f'<span class="cv64-metric__label">{escape(metric.label)}</span>'
            f"</div>"
            f'<div class="cv64-metric__value">{escape(metric.value)}</div>'
            f"{status_html}{detail_html}{trend_html}"
            f"</article>"
        )
    st.markdown(
        f'<div class="cv64-metric-grid" style="--cv64-cols:{max(1, columns)}">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def render_kpi_row_safe(metrics: Sequence[MetricCard], *, columns: int = 4) -> None:
    """Premium KPI row with native Streamlit fallback if HTML rendering fails."""
    cleaned = [_sanitize_metric(metric) for metric in (metrics or [])]
    if not cleaned:
        return
    try:
        _render_premium_metric_html(cleaned, columns=columns)
    except Exception:
        _render_native_metric_row(cleaned, columns=columns)


def cadivor_metric_row(metrics: Sequence[MetricCard], *, columns: int = 4) -> None:
    render_kpi_row_safe(metrics, columns=columns)


def cadivor_section_header(
    title: str,
    *,
    description: str = "",
    eyebrow: str = "",
    icon: str = "layers",
    action_html: str = "",
) -> None:
    eyebrow_block = (
        f'<div class="cv64-section__eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    )
    desc_block = (
        f'<p class="cv64-section__desc">{escape(description)}</p>' if description else ""
    )
    actions = (
        f'<div class="cv64-section__actions">{action_html}</div>' if action_html else ""
    )
    st.markdown(
        f"""
        <section class="cv64-section">
          <div class="cv64-section__icon">{lucide(icon, 22)}</div>
          <div class="cv64-section__copy">
            {eyebrow_block}
            <h1 class="cv64-section__title">{escape(title)}</h1>
            {desc_block}
          </div>
          {actions}
          <div class="cv64-section__rule"></div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def cadivor_panel(
    title: str = "",
    *,
    subtitle: str = "",
    tone: str = "default",
    interactive: bool = False,
) -> None:
    cls = f"cv64-panel cv64-panel--{escape(tone)}"
    if interactive:
        cls += " cv64-panel--interactive"
    heading = ""
    if title:
        sub = f'<p class="cv64-panel__subtitle">{escape(subtitle)}</p>' if subtitle else ""
        heading = (
            f'<div class="cv64-panel__head">'
            f'<h3 class="cv64-panel__title">{escape(title)}</h3>{sub}</div>'
        )
    st.markdown(f'<div class="{cls}">{heading}', unsafe_allow_html=True)


def cadivor_panel_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def cadivor_card(title: str, body: str, *, badge: str = "", badge_tone: Tone = "info") -> None:
    badge_html = cadivor_badge(badge, badge_tone) if badge else ""
    st.markdown(
        f"""
        <article class="cv64-card">
          <div class="cv64-card__top">
            <h4 class="cv64-card__title">{escape(title)}</h4>
            {badge_html}
          </div>
          <p class="cv64-card__body">{escape(body)}</p>
        </article>
        """,
        unsafe_allow_html=True,
    )


def cadivor_empty_state(
    title: str,
    body: str,
    *,
    icon: str = "layers",
    action_label: str = "",
) -> None:
    action = (
        f'<div class="cv64-empty__action">{escape(action_label)}</div>'
        if action_label
        else ""
    )
    st.markdown(
        f"""
        <div class="cv64-empty">
          <div class="cv64-empty__icon">{lucide(icon, 28)}</div>
          <h3 class="cv64-empty__title">{escape(title)}</h3>
          <p class="cv64-empty__body">{escape(body)}</p>
          {action}
        </div>
        """,
        unsafe_allow_html=True,
    )


def cadivor_toolbar_start() -> None:
    st.markdown('<div class="cv64-toolbar">', unsafe_allow_html=True)


def cadivor_toolbar_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def _format_cell(value: Any, *, numeric: bool, monospace: bool, badge: bool) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        text = "—"
    else:
        text = str(value)
    if badge:
        return cadivor_badge(text)
    if numeric:
        return f'<span class="cv64-table__num">{escape(text)}</span>'
    if monospace:
        return f'<span class="cv64-table__mono">{escape(text)}</span>'
    return escape(text)


def cadivor_table(
    df: pd.DataFrame,
    *,
    caption: str = "",
    numeric_columns: Iterable[str] | None = None,
    monospace_columns: Iterable[str] | None = None,
    badge_columns: Iterable[str] | None = None,
    align: Mapping[str, str] | None = None,
) -> None:
    if df is None or df.empty:
        cadivor_empty_state("No records", "Nothing matches the current filters.", icon="search")
        return

    numeric = {str(c) for c in (numeric_columns or [])}
    mono = {str(c) for c in (monospace_columns or [])}
    badges = {str(c) for c in (badge_columns or [])}
    align_map = {str(k): v for k, v in (align or {}).items()}

    headers = []
    for col in df.columns:
        cls = align_map.get(str(col), "left")
        headers.append(f'<th class="cv64-table__th cv64-align-{cls}">{escape(str(col))}</th>')
    rows = []
    for row_idx, (_, row) in enumerate(df.iterrows()):
        cells = []
        for col in df.columns:
            col_name = str(col)
            cls = align_map.get(col_name, "right" if col_name in numeric else "left")
            cell = _format_cell(
                row[col],
                numeric=col_name in numeric,
                monospace=col_name in mono,
                badge=col_name in badges,
            )
            cells.append(f'<td class="cv64-table__td cv64-align-{cls}">{cell}</td>')
        zebra = " cv64-table__row--alt" if row_idx % 2 else ""
        rows.append(f'<tr class="cv64-table__row{zebra}">{"".join(cells)}</tr>')

    cap = f'<div class="cv64-table__caption">{escape(caption)}</div>' if caption else ""
    st.markdown(
        f"""
        <div class="cv64-table-wrap">
          {cap}
          <div class="cv64-table-scroll">
            <table class="cv64-table">
              <thead><tr>{"".join(headers)}</tr></thead>
              <tbody>{"".join(rows)}</tbody>
            </table>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def cadivor_button_wrap(variant: str = "primary") -> None:
    st.markdown(f'<div class="cv64-btn-wrap cv64-btn-wrap--{escape(variant)}">', unsafe_allow_html=True)


def cadivor_button_wrap_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def render_kpi_card(
    label: str,
    value: str,
    *,
    detail: str = "",
    status: str = "",
    tone: Tone = "info",
    icon: str = "activity",
    trend: str = "",
    trend_label: str = "",
) -> MetricCard:
    """Build a single KPI card definition for use with cadivor_metric_row."""
    return MetricCard(
        label=label,
        value=value,
        detail=detail,
        status=status,
        tone=tone,
        icon=icon,
        trend=trend,
        trend_label=trend_label,
    )


def cadivor_dataframe(df: pd.DataFrame, **kwargs: Any) -> None:
    """Render a Streamlit dataframe inside the Cadivor table host shell."""
    if df is None or getattr(df, "empty", True):
        cadivor_empty_state("No records", "Nothing matches the current filters.", icon="search")
        return
    kwargs.setdefault("use_container_width", True)
    kwargs.setdefault("hide_index", True)
    st.markdown('<div class="cv64-table-host">', unsafe_allow_html=True)
    try:
        st.dataframe(df, **kwargs)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


# Aliases requested in sprint brief
CadivorCard = cadivor_card
CadivorMetricCard = MetricCard
CadivorBadge = cadivor_badge
CadivorPanel = cadivor_panel
CadivorToolbar = cadivor_toolbar_start
CadivorTable = cadivor_table
CadivorSectionHeader = cadivor_section_header
CadivorEmptyState = cadivor_empty_state
