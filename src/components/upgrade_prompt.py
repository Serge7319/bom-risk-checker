"""Contextual, non-blocking upgrade surfaces for Launch Sprint 30.0A."""
from __future__ import annotations

import html
import streamlit as st


def render_upgrade_prompt(*, plan_name: str, monthly_used: int, monthly_limit: int | None) -> None:
    plan = str(plan_name or "Starter")
    if plan.lower() not in {"starter", "free", "student"}:
        return
    limit = max(0, int(monthly_limit or 0))
    used = max(0, int(monthly_used or 0))
    remaining = max(0, limit - used) if limit else 0
    usage = int(round((used / limit) * 100)) if limit else 0
    message = f"{remaining} BOM analyses remaining this month." if limit else "Upgrade when you need higher analysis and workspace limits."
    markup = f"""
    <style id="cv30-upgrade-css">
    .cv30-upgrade{{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:center;border:1px solid #dbeafe;background:#fff;border-radius:18px;padding:15px 17px;margin:14px 0 18px}}
    .cv30-upgrade strong{{display:block;color:#0f172a!important;font-size:14px;font-weight:900}}
    .cv30-upgrade p{{color:#64748b!important;font-size:12px;font-weight:650;margin:4px 0 9px}}
    .cv30-upgrade-bar{{height:6px;border-radius:999px;background:#e2e8f0;overflow:hidden}}
    .cv30-upgrade-bar i{{display:block;width:{min(100,usage)}%;height:100%;background:#2563eb;border-radius:999px}}
    @media(max-width:760px){{.cv30-upgrade{{grid-template-columns:1fr}}}}
    </style>
    <section class="cv30-upgrade"><div><strong>{html.escape(plan)} plan usage</strong><p>{html.escape(message)}</p><div class="cv30-upgrade-bar"><i></i></div></div></section>
    """
    st.markdown(markup, unsafe_allow_html=True)
    from src.ui.navigation import navigate_to

    if st.button("Compare plans", key="cv30_compare_plans"):
        navigate_to("Pricing", arm_opening=False)
