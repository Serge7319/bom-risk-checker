"""Cadivor Sprint 64 — Premium component system."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system.icons import icon_or_empty, lucide

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


def _render_html(html: str) -> None:
    """Render trusted Cadivor HTML — never return markup to callers."""
    if not html:
        return
    # Streamlit's st.html sanitizer can strip inline SVG paths; markdown preserves Lucide icons.
    st.markdown(html, unsafe_allow_html=True)


def inject_cadivor_design_system() -> None:
    css_path = Path(__file__).resolve().parents[2] / "assets" / "css" / "cadivor_design_system.css"
    try:
        css = css_path.read_text(encoding="utf-8")
    except OSError:
        return
    _render_html(f"<style id='cadivor-design-system-s64'>{css}</style>")


def badge_tone(raw: Any) -> Tone:
    key = str(raw or "").strip().lower()
    return _BADGE_TONES.get(key, "neutral")


def cadivor_badge(label: Any, tone: Tone | None = None) -> str:
    resolved = tone or badge_tone(label)
    return (
        f'<span class="cv64-badge cv64-badge--{escape(resolved)}">'
        f"{escape(str(label))}</span>"
    )


def cadivor_meta_row(badges: Sequence[tuple[str, str]]) -> None:
    """Render a row of status badges without exposing raw HTML markup."""
    if not badges:
        return
    items = "".join(cadivor_badge(label, tone) for label, tone in badges)
    _render_html(f'<div class="cv64-meta-row">{items}</div>')


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
    href: str = ""
    action_label: str = ""
    active: bool = False


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
        href=str(metric.href or ""),
        action_label=str(metric.action_label or ""),
        active=bool(metric.active),
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


def _metric_icon_html(name: str, *, compact: bool) -> str:
    size = 16 if compact else 18
    markup = lucide(name, size)
    if not markup:
        return ""
    return f'<span class="cv64-metric__icon" aria-hidden="true">{markup}</span>'


def _render_premium_metric_html(
    metrics: Sequence[MetricCard], *, columns: int, compact: bool = False
) -> None:
    density = "compact" if compact else "primary"
    cards = []
    for metric in metrics:
        trend_html = ""
        if metric.trend_label:
            arrow = metric.trend or "neutral"
            cards_trend_icon = "arrow-up" if arrow == "up" else "arrow-down" if arrow == "down" else "activity"
            trend_html = (
                f'<div class="cv64-metric__trend cv64-metric__trend--{escape(arrow)}">'
                f'{icon_or_empty(cards_trend_icon, 14)}'
                f"<span>{escape(metric.trend_label)}</span></div>"
            )
        footer_parts = []
        if metric.status:
            footer_parts.append(f'<div class="cv64-metric__status">{escape(metric.status)}</div>')
        if metric.detail and not metric.trend_label:
            footer_parts.append(f'<div class="cv64-metric__detail">{escape(metric.detail)}</div>')
        footer_html = ""
        if footer_parts or trend_html:
            inner = "".join(footer_parts)
            if trend_html:
                inner += trend_html.replace('cv64-metric__footer ', "")
            footer_html = f'<div class="cv64-metric__footer">{inner}</div>'

        icon_html = _metric_icon_html(metric.icon, compact=compact)
        header_inner = icon_html + f'<span class="cv64-metric__label">{escape(metric.label)}</span>'
        active_class = " cv64-metric--active" if metric.active else ""
        action_html = (
            f'<div class="cv64-metric__action">{escape(metric.action_label)}</div>'
            if metric.action_label
            else ""
        )
        card = (
            f'<article class="cv64-metric cv64-metric--{escape(metric.tone)} cv64-metric--{density}{active_class}">'
            f'<div class="cv64-metric__accent"></div>'
            f'<div class="cv64-metric__header">{header_inner}</div>'
            f'<div class="cv64-metric__value">{escape(metric.value)}</div>'
            f"{footer_html}"
            f"{action_html}"
        )
        card += "</article>"
        if metric.href:
            cards.append(
                f'<a class="cv64-metric-link" href="{escape(metric.href, quote=True)}" target="_self"'
                f'{" aria-current=\"page\"" if metric.active else ""}>{card}</a>'
            )
        else:
            cards.append(card)
    grid_class = f"cv64-metric-grid cv64-metric-grid--{density}"
    _render_html(
        f'<div class="{grid_class}" style="--cv64-cols:{max(1, columns)}">{"".join(cards)}</div>'
    )


def render_metric_strip(metrics: Sequence[MetricCard], *, columns: int = 3) -> None:
    """Horizontal compact metric strip for nested panels such as project summaries."""
    cleaned = [_sanitize_metric(metric) for metric in (metrics or [])]
    if not cleaned:
        return
    cells = []
    for metric in cleaned:
        icon_html = _metric_icon_html(metric.icon, compact=True)
        cells.append(
            f'<div class="cv64-metric-strip__cell cv64-metric-strip__cell--{escape(metric.tone)}">'
            f'<div class="cv64-metric-strip__head">{icon_html}'
            f'<span class="cv64-metric-strip__label">{escape(metric.label)}</span></div>'
            f'<div class="cv64-metric-strip__value">{escape(metric.value)}</div>'
            f"</div>"
        )
    _render_html(
        f'<div class="cv64-metric-strip" style="--cv64-strip-cols:{max(1, columns)}">{"".join(cells)}</div>'
    )


def render_kpi_row_safe(
    metrics: Sequence[MetricCard], *, columns: int = 4, compact: bool = False
) -> None:
    """Premium KPI row with native Streamlit fallback if HTML rendering fails."""
    cleaned = [_sanitize_metric(metric) for metric in (metrics or [])]
    if not cleaned:
        return
    try:
        _render_premium_metric_html(cleaned, columns=columns, compact=compact)
    except Exception:
        _render_native_metric_row(cleaned, columns=columns)


def cadivor_metric_row(
    metrics: Sequence[MetricCard], *, columns: int = 4, compact: bool = False
) -> None:
    render_kpi_row_safe(metrics, columns=columns, compact=compact)


def render_section_header(
    title: str,
    *,
    description: str = "",
    eyebrow: str = "",
    icon: str = "layers",
    action_html: str = "",
) -> None:
    """Render a page-level section header (single trusted HTML path)."""
    eyebrow_block = (
        f'<div class="cv64-section__eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    )
    desc_block = (
        f'<p class="cv64-section__desc">{escape(description)}</p>' if description else ""
    )
    actions = (
        f'<div class="cv64-section__actions">{action_html}</div>' if action_html else ""
    )
    icon_markup = lucide(icon, 17) if icon else ""
    icon_block = (
        f'<span class="cv64-section__icon" aria-hidden="true">{icon_markup}</span>'
        if icon_markup
        else ""
    )
    _render_html(
        f'<section class="cv64-section">'
        f"{icon_block}"
        f'<div class="cv64-section__copy">'
        f"{eyebrow_block}"
        f'<h1 class="cv64-section__title">{escape(title)}</h1>'
        f"{desc_block}"
        f"</div>"
        f"{actions}"
        f'<div class="cv64-section__rule"></div>'
        f"</section>"
    )


def cadivor_section_header(
    title: str,
    *,
    description: str = "",
    eyebrow: str = "",
    icon: str = "layers",
    action_html: str = "",
) -> None:
    render_section_header(
        title,
        description=description,
        eyebrow=eyebrow,
        icon=icon,
        action_html=action_html,
    )


def render_subsection_header(
    title: str,
    *,
    description: str = "",
    icon: str = "",
) -> None:
    """Compact in-column section title — avoids full page-header chrome."""
    icon_markup = lucide(icon, 16) if icon else ""
    icon_block = (
        f'<span class="cv64-subsection__icon" aria-hidden="true">{icon_markup}</span>'
        if icon_markup
        else ""
    )
    desc_block = (
        f'<p class="cv64-subsection__desc">{escape(description)}</p>' if description else ""
    )
    _render_html(
        f'<div class="cv64-subsection">'
        f"{icon_block}"
        f"<div>"
        f'<h2 class="cv64-subsection__title">{escape(title)}</h2>'
        f"{desc_block}"
        f"</div></div>"
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
    _render_html(f'<div class="{cls}">{heading}')


def cadivor_panel_end() -> None:
    _render_html("</div>")


def cadivor_card(title: str, body: str, *, badge: str = "", badge_tone: Tone = "info") -> None:
    badge_html = cadivor_badge(badge, badge_tone) if badge else ""
    _render_html(
        f'<article class="cv64-card">'
        f'<div class="cv64-card__top">'
        f'<h4 class="cv64-card__title">{escape(title)}</h4>'
        f"{badge_html}"
        f"</div>"
        f'<p class="cv64-card__body">{escape(body)}</p>'
        f"</article>"
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
    _render_html(
        f'<div class="cv64-empty cv71-empty-state">'
        f'<div class="cv64-empty__icon">{icon_or_empty(icon, 24)}</div>'
        f'<h3 class="cv64-empty__title">{escape(title)}</h3>'
        f'<p class="cv64-empty__body">{escape(body)}</p>'
        f"{action}"
        f"</div>"
    )


def cadivor_toolbar_start() -> None:
    """Reserved for grouped actions — Streamlit widgets cannot live inside HTML wrappers."""
    return


def cadivor_toolbar_end() -> None:
    return


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
    _render_html(
        f'<div class="cv64-table-wrap">'
        f"{cap}"
        f'<div class="cv64-table-scroll">'
        f'<table class="cv64-table">'
        f"<thead><tr>{''.join(headers)}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"</table></div></div>"
    )


def cadivor_button_wrap(variant: str = "primary") -> None:
    _render_html(f'<div class="cv64-btn-wrap cv64-btn-wrap--{escape(variant)}">')


def cadivor_button_wrap_end() -> None:
    _render_html("</div>")


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
    row_count = len(df)
    if "height" not in kwargs and row_count > 24:
        kwargs["height"] = min(520, 46 + min(row_count, 30) * 34)
    _render_html('<div class="cv64-table-host">')
    try:
        st.dataframe(df, **kwargs)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True)
    if row_count > 24 and "height" in kwargs:
        _render_html(
            f'<p class="cv71-table-note">Showing a scrollable view of {row_count:,} rows.</p>'
        )
    _render_html("</div>")


def build_dataframe_column_config(df: pd.DataFrame, overrides: Mapping[str, Any] | None = None) -> dict:
    """Infer readable column_config for common engineering table fields."""
    config: dict[str, Any] = {}
    for col in df.columns:
        name = str(col)
        lower = name.lower()
        if any(token in lower for token in ("unit price", "target price", "extended cost", "shortage value", "run savings", "savings")):
            config[name] = st.column_config.NumberColumn(format="$%.4f" if "unit" in lower else "$%.2f")
        elif "price" in lower or "cost" in lower or "value" in lower:
            config[name] = st.column_config.NumberColumn(format="$%.2f")
        elif "score" in lower or lower.endswith(" risk"):
            config[name] = st.column_config.NumberColumn(format="%d")
        elif any(token in lower for token in ("quantity", "stock", "units", "sources", "hours", "projects", "count", "build")):
            config[name] = st.column_config.NumberColumn(format="%,d")
        elif name in {"Part Number", "MPN", "Component", "Manufacturer", "Project"}:
            config[name] = st.column_config.TextColumn(width="medium")
    if overrides:
        config.update(overrides)
    return config


def cadivor_engineering_dataframe(
    df: pd.DataFrame,
    *,
    column_config: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Render a dataframe with shared engineering column formatting."""
    cfg = build_dataframe_column_config(df, column_config)
    cadivor_dataframe(df, column_config=cfg, **kwargs)


def render_decision_card_actions(
    decision: Mapping[str, Any],
    *,
    navigate_to: Callable[..., Any],
    internal_nav_button: Callable[..., Any],
    key_prefix: str,
) -> None:
    """Compact primary/secondary toolbar for a decision card."""
    _render_html('<div class="cv64-decision-toolbar">')
    action_cols = st.columns([1.25, 1, 1, 1], gap="small")
    with action_cols[0]:
        cadivor_button_wrap("primary")
        if st.button(
            "Review Decision",
            key=f"{key_prefix}_review",
            type="primary",
            use_container_width=True,
        ):
            navigate_to("Engineering Decisions", decision_id=decision["decision_id"])
        cadivor_button_wrap_end()
    with action_cols[1]:
        cadivor_button_wrap("secondary")
        internal_nav_button(
            "View Alternative",
            "Alternative Finder",
            key=f"{key_prefix}_alt",
            use_container_width=True,
            original_part=decision["part_number"],
            analysis_id=str(decision.get("analysis_id") or ""),
            source_page="engineering_decisions",
        )
        cadivor_button_wrap_end()
    with action_cols[2]:
        cadivor_button_wrap("secondary")
        internal_nav_button(
            "Open Monitoring",
            "Monitoring",
            key=f"{key_prefix}_monitor",
            use_container_width=True,
        )
        cadivor_button_wrap_end()
    with action_cols[3]:
        cadivor_button_wrap("secondary")
        if decision.get("analysis_id"):
            internal_nav_button(
                "Open Saved BOM",
                "Analysis Details",
                key=f"{key_prefix}_analysis",
                use_container_width=True,
                analysis_id=decision["analysis_id"],
            )
        else:
            st.caption("No saved BOM linked")
        cadivor_button_wrap_end()
    _render_html("</div>")


# Aliases requested in sprint brief
CadivorCard = cadivor_card
CadivorMetricCard = MetricCard
CadivorBadge = cadivor_badge
CadivorPanel = cadivor_panel
CadivorToolbar = cadivor_toolbar_start
CadivorTable = cadivor_table
CadivorSectionHeader = cadivor_section_header
CadivorEmptyState = cadivor_empty_state
