"""Cadivor Design System v1 reusable authenticated-workspace components."""
from __future__ import annotations
from html import escape
from typing import Iterable, Mapping, Sequence
import streamlit as st

from src.ui.cadivor_design_system import (
    MetricCard,
    cadivor_dataframe,
    cadivor_empty_state,
    cadivor_metric_row,
    cadivor_section_header,
    render_kpi_card,
)


def page_header(title: str, subtitle: str = "", eyebrow: str = "", actions: Sequence[tuple[str, str]] = ()) -> None:
    action_html = "".join(
        f'<span class="cv64-badge cv64-badge--info">{escape(label)}</span>'
        for label, _kind in actions
    )
    cadivor_section_header(
        title,
        description=subtitle,
        eyebrow=eyebrow,
        action_html=action_html,
    )


def kpi_grid(items: Sequence[Mapping[str, object]], columns: int = 4) -> None:
    metrics = []
    for item in items:
        metrics.append(
            MetricCard(
                label=str(item.get("label", "")),
                value=str(item.get("value", "—")),
                detail=str(item.get("note", "")),
                status=str(item.get("status", "")),
                tone=str(item.get("tone", "info")),
                icon=str(item.get("icon", "chart")),
            )
        )
    cadivor_metric_row(metrics, columns=columns)


def section_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    cadivor_section_header(title, description=subtitle, eyebrow=eyebrow)


def content_card(title: str = "", subtitle: str = "", tone: str = "default") -> None:
    from src.ui.cadivor_design_system import cadivor_panel

    cadivor_panel(title=title, subtitle=subtitle, tone="soft" if tone == "default" else tone)


def end_card() -> None:
    from src.ui.cadivor_design_system import cadivor_panel_end

    cadivor_panel_end()


def empty_state(title: str, body: str, action: str = "", icon: str = "◇") -> None:
    cadivor_empty_state(title, body, icon=icon, action_label=action)


def status_badge(label: str, tone: str = "neutral") -> str:
    from src.ui.cadivor_design_system import cadivor_badge, badge_tone

    return cadivor_badge(label, badge_tone(label) if tone == "neutral" else tone)
