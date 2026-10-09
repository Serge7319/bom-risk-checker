"""Approved page bodies for the Cadivor mockups.

Live workspace records fill the layout. Sample names from the mockups are not
invented when the workspace has different BOMs.
"""

from __future__ import annotations

import html
import io
from typing import Any

import streamlit as st

from src.ui.navigation import internal_nav_button, navigate_to


PROJECT_ICON = (
    '<svg class="cv-ap-chip" width="28" height="28" viewBox="0 0 32 32" aria-hidden="true" '
    'style="width:28px;height:28px;display:inline-block;vertical-align:middle;margin-right:8px">'
    '<rect width="32" height="32" rx="8" fill="#eef2ff"/>'
    '<path d="M8 13h6l2 2h8v9H8z" fill="#fff" stroke="#2563eb" stroke-width="1.4"/>'
    '<path d="M8 13V11h5l2 2" fill="none" stroke="#2563eb" stroke-width="1.4"/>'
    "</svg>"
)


DOC = (
    '<svg class="cv-ap-chip" width="28" height="28" viewBox="0 0 32 32" aria-hidden="true" '
    'style="width:28px;height:28px;display:inline-block;vertical-align:middle;margin-right:8px">'
    '<rect width="32" height="32" rx="8" fill="#eef2ff"/>'
    '<path d="M10 8h8l4 4v12H10z" fill="#fff" stroke="#2563eb" stroke-width="1.4"/>'
    '<path d="M18 8v4h4" fill="none" stroke="#2563eb" stroke-width="1.4"/>'
    "</svg>"
)


def part_mark(seed: str = "") -> str:
    """Illustration for a live part. The workspace does not store product photos."""
    text = str(seed or "").casefold()
    if any(token in text for token in ("cap", "grm", "ceramic", "murata")):
        body = (
            '<rect x="8" y="14" width="32" height="20" rx="3" fill="#d6d3d1"/>'
            '<rect x="14" y="18" width="20" height="12" rx="1" fill="#a8a29e"/>'
            '<path d="M12 14v-6M36 14v-6" stroke="#78716c" stroke-width="2"/>'
        )
    elif any(token in text for token in ("reg", "tps", "buck", "converter")):
        body = (
            '<rect x="10" y="12" width="28" height="28" rx="4" fill="#1e293b"/>'
            '<circle cx="24" cy="26" r="6" fill="#334155"/>'
            '<path d="M16 12v-4M24 12v-4M32 12v-4M16 40v4M24 40v4M32 40v4" stroke="#94a3b8" stroke-width="2"/>'
        )
    else:
        body = (
            '<rect x="12" y="14" width="24" height="24" rx="2" fill="#0f172a"/>'
            '<path d="M16 14v-5M22 14v-5M26 14v-5M32 14v-5M16 38v5M22 38v5M26 38v5M32 38v5" stroke="#64748b" stroke-width="1.6"/>'
            '<path d="M12 20h-4M12 26h-4M12 32h-4M36 20h4M36 26h4M36 32h4" stroke="#64748b" stroke-width="1.6"/>'
        )
    return (
        '<svg class="cv-ap-chip" width="42" height="42" viewBox="0 0 48 48" aria-hidden="true" '
        'style="width:42px;height:42px;display:inline-block;vertical-align:middle;margin-right:8px">'
        f'<rect width="48" height="48" rx="10" fill="#f8fafc"/>{body}</svg>'
    )


CHIP = (
    '<svg class="cv-ap-chip" width="36" height="36" viewBox="0 0 48 48" aria-hidden="true" '
    'style="width:36px;height:36px;display:inline-block;vertical-align:middle">'
    '<rect width="48" height="48" rx="10" fill="#eef2ff"/>'
    '<rect x="16" y="16" width="16" height="16" rx="2" fill="#334155"/>'
    '<path d="M20 10v6M28 10v6M20 32v6M28 32v6M10 20h6M10 28h6M32 20h6M32 28h6" stroke="#64748b" stroke-width="2"/>'
    "</svg>"
)


def _esc(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return fallback
    return html.escape(text)


def _num(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _first(row: dict[str, Any], *keys: str, fallback: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() not in {"", "nan", "None"}:
            return value
    return fallback


def _candidate_mpn(row: dict[str, Any]) -> str:
    """Read the supplier candidate part number. Blank means the row is not a part."""
    for key in (
        "Alternative Part",
        "mpn",
        "MPN",
        "alternative_mpn",
        "manufacturer_part_number",
        "part_number",
        "Part Number",
    ):
        text = str(row.get(key) or "").strip()
        if text and text.casefold() not in {"nan", "none", "—", "-"}:
            return text
    return ""


def _candidate_field(row: dict[str, Any], *keys: str, fallback: str = "—") -> str:
    for key in keys:
        if key not in row or row.get(key) is None:
            continue
        text = str(row.get(key)).strip()
        if not text or text.casefold() in {"nan", "none"}:
            continue
        return html.escape(text)
    return fallback


def _candidate_stock(row: dict[str, Any]) -> int:
    for key in ("Stock", "stock_total", "stock_available"):
        if key in row and row.get(key) not in (None, ""):
            return _num(row.get(key))
    return 0


def begin_approved_page() -> None:
    st.markdown(
        """
        <style>
        .cv-ap{color:#0f172a;font-family:Inter,"Segoe UI",sans-serif}
        .cv-ap-kicker{margin:0 0 6px;color:#64748b;font-size:12px;font-weight:700;letter-spacing:.08em}
        .cv-ap h1{margin:0 0 6px;font-size:32px;line-height:1.15;letter-spacing:-.03em}
        .cv-ap-sub{margin:0 0 18px;color:#64748b;font-size:14px}
        .cv-ap-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 18px}
        .cv-ap-kpis.three{grid-template-columns:repeat(3,minmax(0,1fr))}
        .cv-ap-kpis.five{grid-template-columns:repeat(5,minmax(0,1fr))}
        .cv-ap-kpi{background:#fff;border:1px solid #e6edf5;border-radius:16px;padding:12px 14px;min-height:92px}
        .cv-ap-kpi-top{display:flex;align-items:center;gap:8px}
        .cv-ap-kpi-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
        .cv-ap-ico{width:28px;height:28px;border-radius:9px;display:inline-flex;align-items:center;justify-content:center;background:#eff6ff;flex:0 0 28px}
        .cv-ap-ico svg{width:16px;height:16px;display:block}
        [class*="st-key-approved_home_menu_"] button,[class*="st-key-approved_bom_menu_"] button,[class*="st-key-approved_report_menu_"] button,[class*="st-key-approved_decision_menu_"] button{width:32px!important;min-width:32px!important;max-width:32px!important;height:32px!important;min-height:32px!important;padding:0!important;border-radius:8px!important}
        [class*="st-key-approved_home_menu_"] button svg,[class*="st-key-approved_bom_menu_"] button svg,[class*="st-key-approved_report_menu_"] button svg,[class*="st-key-approved_decision_menu_"] button svg{display:none!important}
        [class*="st-key-approved_home_row_"],[class*="st-key-approved_bom_row_"],[class*="st-key-approved_report_row_"]{border-top:1px solid #eef2f7;padding:0;margin:0}
        [class*="st-key-approved_settings_screen"] h1{font-size:28px;margin:0 0 8px}
        [class*="st-key-approved_settings_screen"] [data-testid="stForm"]{border:0;padding:0}
        [class*="st-key-approved_settings_screen"] [data-testid="stVerticalBlock"]{gap:0.4rem}
        .cv-ap-kpi span{display:block;color:#64748b;font-size:13px;font-weight:650}
        .cv-ap-kpi strong{display:block;margin-top:8px;font-size:28px;letter-spacing:-.03em}
        .cv-ap-kpi em{display:block;margin-top:4px;font-style:normal;font-size:12px;color:#16a34a}
        .cv-ap-kpi em.down{color:#e11d48}
        .cv-ap-kpi em.muted{color:#94a3b8}
        .cv-ap-card{background:#fff;border:1px solid #e6edf5;border-radius:16px;padding:8px 8px 4px;margin-bottom:12px}
        .cv-ap-table{width:100%;border-collapse:separate;border-spacing:0}
        .cv-ap-table th{text-align:left;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#94a3b8;padding:8px 10px}
        .cv-ap-table td{padding:8px 10px;border-top:1px solid #eef2f7;font-size:13px;vertical-align:middle}
        .cv-part-photo{width:72px;height:72px;border-radius:12px;background:#f1f5f9;border:1px solid #e2e8f0;display:inline-block;object-fit:cover;vertical-align:middle;margin-right:10px}
        .cv-map{display:grid;grid-template-columns:180px 1fr;gap:18px;align-items:center;padding:8px 8px 16px}
        .cv-map-part{border:1px solid #bfdbfe;background:#eff6ff;border-radius:12px;padding:12px}
        .cv-map-branches{display:grid;gap:10px;border-left:2px solid #cbd5e1;padding-left:16px}
        .cv-map-branch{display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:#fff;border:1px solid #e6edf5;border-radius:12px;padding:8px 10px}
        .cv-set-grid{display:grid;grid-template-columns:1.1fr .9fr;gap:14px}
        .cv-security-row{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid #eef2f7}
        .cv-plan-card{background:#eff6ff;border:1px solid #dbeafe;border-radius:16px;padding:16px 18px}
        .cv-ap-name{font-weight:750}
        .cv-ap-meta{color:#64748b;font-size:12px}
        .cv-pill{display:inline-flex;border-radius:999px;padding:3px 8px;font-size:12px;font-weight:750}
        .cv-pill.high{background:#ffe4e6;color:#be123c}
        .cv-pill.medium{background:#fef3c7;color:#b45309}
        .cv-pill.low{background:#dcfce7;color:#15803d}
        .cv-pill.open{background:#dbeafe;color:#1d4ed8}
        .cv-ap-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:22px}
        .cv-ap-template{background:#f8fafc;border:1px solid #e6edf5;border-radius:16px;padding:18px}
        .cv-ap-template h3{margin:8px 0 6px;font-size:16px}
        .cv-ap-template p{margin:0 0 12px;color:#64748b;font-size:13px}
        .cv-ap-chip{display:inline-flex;margin-right:6px;padding:2px 8px;border-radius:999px;background:#e0e7ff;color:#3730a3;font-size:11px;font-weight:750}
        .cv-ap-chip-icon{width:36px;height:36px;vertical-align:middle;margin-right:8px}
        .cv-ap-banner{background:#eff6ff;border:1px solid #dbeafe;border-radius:16px;padding:18px 20px;margin-bottom:14px}
        .cv-ap-split{display:grid;grid-template-columns:1.4fr .8fr;gap:14px}
        .cv-ap-chart{background:#fff;border:1px solid #e6edf5;border-radius:16px;padding:14px 16px 8px;margin:0 0 14px}
        .cv-ap-chart h3{margin:0 0 8px;font-size:14px}
        .cv-ap-charts{display:grid;grid-template-columns:1.4fr .8fr;gap:14px;margin-bottom:14px}
        @media(max-width:900px){.cv-ap-kpis,.cv-ap-cards,.cv-ap-split{display:block}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def end_approved_page() -> None:
    """Stop the script so the previous workspace renderer does not run."""
    from src.authenticated_runtime import (
        reveal_authenticated_page_body,
        stop_authenticated_page,
    )

    route = str(st.session_state.get("cadivor_route") or st.session_state.get("app_mode") or "")
    reveal_authenticated_page_body(route)
    stop_authenticated_page()


def legacy_tools_open(page: str) -> bool:
    return st.session_state.get("cadivor_show_legacy_tools") == page


def _open_legacy(page: str) -> None:
    st.session_state["cadivor_show_legacy_tools"] = page


def render_legacy_back(page: str) -> None:
    if st.button("Back to approved view", key=f"approved_back_{page}"):
        st.session_state.pop("cadivor_show_legacy_tools", None)
        st.rerun()


def _health_pill(score: int) -> str:
    if score >= 80:
        kind = "low"
    elif score >= 70:
        kind = "medium"
    else:
        kind = "high"
    return f'<span class="cv-pill {kind}">{score}/100</span>'


def _records(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [row for row in rows or [] if isinstance(row, dict)]


def live_bar_chart(title: str, points: list[tuple[str, float]], color: str = "#2563eb") -> str:
    """Bar chart of live numeric records. Empty input renders nothing."""
    clean = [(str(label), float(value)) for label, value in points if label]
    if not clean:
        return ""
    peak = max(value for _, value in clean) or 1.0
    width = 560
    slot = width / len(clean[:8])
    marks = []
    for index, (label, value) in enumerate(clean[:8]):
        height = 112 * (value / peak)
        x = 12 + index * slot
        bar = max(10.0, slot - 22)
        marks.append(
            f'<rect x="{x:.1f}" y="{132 - height:.1f}" width="{bar:.1f}" height="{max(height, 2):.1f}" rx="5" fill="{color}"/>'
            f'<text x="{x:.1f}" y="154" font-size="11" fill="#64748b">{html.escape(label[:12])}</text>'
        )
    return (
        f'<article class="cv-ap-chart"><h3>{html.escape(title)}</h3>'
        f'<svg viewBox="0 0 {width} 168" width="100%" height="168" role="img" aria-label="{html.escape(title)}">'
        f'{"".join(marks)}</svg></article>'
    )


def series_chart(title: str, series: list[tuple[str, str, list[tuple[str, float]]]]) -> str:
    """Line chart. Each series is (name, color, points). Missing points stay off the line."""
    prepared = []
    for name, color, points in series:
        clean = [(str(label), float(value)) for label, value in points if label]
        if clean:
            prepared.append((name, color, clean))
    if not prepared:
        return (
            f'<article class="cv-ap-chart"><h3>{html.escape(title)}</h3>'
            '<p class="cv-ap-meta">No supply or demand values are recorded for this scenario.</p></article>'
        )
    labels = [label for label, _value in prepared[0][2]]
    peak = max(value for _name, _color, points in prepared for _label, value in points) or 1.0
    width = 640
    slot = width / max(len(labels), 1)

    def _point(index: int, value: float) -> str:
        x = 28 + index * slot
        y = 128 - (108 * (value / peak))
        return f"{x:.1f},{y:.1f}"

    lines = []
    legend = []
    for name, color, points in prepared:
        coords = " ".join(_point(index, value) for index, (_label, value) in enumerate(points))
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{coords}"/>')
        legend.append(f'<span style="color:{color}">{html.escape(name)}</span>')
    axis = "".join(
        f'<text x="{28 + index * slot:.1f}" y="150" font-size="11" fill="#64748b">{html.escape(label[:10])}</text>'
        for index, label in enumerate(labels[:8])
    )
    return (
        f'<article class="cv-ap-chart"><h3>{html.escape(title)}</h3>'
        f'<svg viewBox="0 0 {width} 168" width="100%" height="168" role="img" aria-label="{html.escape(title)}">'
        f'{"".join(lines)}{axis}</svg><p class="cv-ap-meta">{" · ".join(legend)}</p></article>'
    )


def sparkline(values: list[float], color: str = "#2563eb") -> str:
    """Small trend line from recorded values. A single value draws one point, not a made-up history."""
    if not values:
        return '<svg class="cv-ap-spark" viewBox="0 0 88 28" width="88" height="28" aria-hidden="true"></svg>'
    peak = max(values) or 1.0
    slot = 80 / max(len(values) - 1, 1)
    coords = []
    for index, value in enumerate(values[:12]):
        x = 4 + index * slot
        y = 24 - (18 * (value / peak))
        coords.append(f"{x:.1f},{y:.1f}")
    marks = f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(coords)}"/>'
    if len(coords) == 1:
        marks += f'<circle cx="{coords[0].split(",")[0]}" cy="{coords[0].split(",")[1]}" r="2.5" fill="{color}"/>'
    return f'<svg class="cv-ap-spark" viewBox="0 0 88 28" width="88" height="28" aria-hidden="true">{marks}</svg>'


def risk_mix_chart(parts: list[dict[str, Any]] | None) -> str:
    counts = {"High": 0, "Medium": 0, "Low": 0}
    for part in _records(parts):
        level = str(_first(part, "risk_level", "severity", fallback="")).casefold()
        if "high" in level:
            counts["High"] += 1
        elif "med" in level:
            counts["Medium"] += 1
        elif "low" in level:
            counts["Low"] += 1
    total = sum(counts.values())
    if not total:
        return ""
    colors = {"High": "#e11d48", "Medium": "#d97706", "Low": "#16a34a"}
    start = 0.0
    slices = []
    for label, count in counts.items():
        if not count:
            continue
        end = start + (count / total) * 100
        slices.append(
            f'<circle cx="70" cy="70" r="42" fill="none" stroke="{colors[label]}" stroke-width="18" '
            f'pathLength="100" stroke-dasharray="{count / total * 100:.2f} {100 - count / total * 100:.2f}" '
            f'stroke-dashoffset="{-start:.2f}"/>'
        )
        start = end
    legend = "".join(
        f'<div><span class="cv-pill {"high" if label=="High" else "medium" if label=="Medium" else "low"}">{label}</span> {count}</div>'
        for label, count in counts.items()
        if count
    )
    return (
        '<article class="cv-ap-chart"><h3>Risk distribution</h3>'
        f'<svg viewBox="0 0 140 140" width="140" height="140" role="img" aria-label="Risk distribution">{"".join(slices)}</svg>'
        f'<div class="cv-ap-meta">{legend}</div></article>'
    )


def render_home(
    *,
    name: str,
    analyses: list[dict[str, Any]] | None,
    plan_notice: str = "",
    pause_new_analyses: bool = False,
) -> None:
    begin_approved_page()
    rows = _records(analyses)
    high = sum(_num(_first(row, "high_risk_count")) for row in rows)
    review = sum(1 for row in rows if _num(_first(row, "high_risk_count")) or _num(_first(row, "health_score"), 100) < 80)
    health_values = [_num(_first(row, "health_score")) for row in rows]
    average = round(sum(health_values) / len(health_values)) if health_values else 0
    greeting = name or "there"
    notice = f"<p class='cv-ap-sub'>{_esc(plan_notice)}</p>" if plan_notice else ""
    title_col, action_col = st.columns([5.2, 1.5], vertical_alignment="center")
    with title_col:
        st.markdown(
            f"""
            <div class="cv-ap">
              <p class="cv-ap-kicker">HOME</p>
              <h1>Good afternoon, {_esc(greeting)}</h1>
              <p class="cv-ap-sub">Here's what's happening with your BOMs today.</p>
              {notice}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with action_col:
        if pause_new_analyses:
            if st.button("Open reports", key="approved_home_open_reports", type="primary"):
                navigate_to("Reports")
        elif st.button("+ New BOM analysis", key="approved_home_new_bom", type="primary"):
            st.session_state["cadivor_bom_upload_open"] = True
            navigate_to("BOM Analyzer")
    saved_delta = _prior_delta(rows, "prior_bom_count", "previous_bom_count")
    review_delta = _prior_delta(rows, "prior_needs_review", "previous_needs_review")
    risk_delta = _prior_delta(rows, "prior_high_risk_count", "previous_high_risk_count")
    health_delta = _prior_delta(rows, "prior_health_score", "previous_health_score")
    st.markdown(
        f"""
        <div class="cv-ap">
          <section class="cv-ap-kpis">
            <article class="cv-ap-kpi"><div class="cv-ap-kpi-top"><span class="cv-ap-ico">{ICO_DOC}</span><span>Saved BOMs</span></div><strong>{len(rows)}</strong>{saved_delta}</article>
            <article class="cv-ap-kpi"><div class="cv-ap-kpi-top"><span class="cv-ap-ico">{ICO_WARN}</span><span>Needs review</span></div><strong>{review}</strong>{review_delta}</article>
            <article class="cv-ap-kpi"><div class="cv-ap-kpi-top"><span class="cv-ap-ico">{ICO_RISK}</span><span>High-risk parts</span></div><strong>{high}</strong>{risk_delta}</article>
            <article class="cv-ap-kpi"><div class="cv-ap-kpi-top"><span class="cv-ap-ico">{ICO_HEALTH}</span><span>Average health</span></div><strong>{average}/100</strong>{health_delta}</article>
          </section>
          <section class="cv-ap-card">
            <h2>Recent BOMs</h2>
            <p class="cv-ap-sub">Your latest analyses and their current status.</p>
          </section>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="approved_home_head"):
        header = st.columns([2.3, 1.5, 0.9, 1, 1.1, 1.2, 0.7])
        for column, label in zip(header, ("Name", "Project", "Part count", "Health", "High-risk parts", "Last analyzed", "Actions")):
            column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
    if not rows:
        st.caption("No saved BOMs yet. Start a new BOM analysis to fill this workspace.")
    for index, row in enumerate(rows[:6]):
        title = _esc(_first(row, "project_name", "name", fallback="Saved BOM"))
        filename = _esc(_first(row, "filename", fallback=""))
        project = _esc(_first(row, "project", "customer_name", fallback="") or title)
        parts = _num(_first(row, "total_parts"))
        score = _num(_first(row, "health_score"))
        risk = _num(_first(row, "high_risk_count"))
        updated = _esc(str(_first(row, "created_at", fallback=""))[:10])
        with st.container(key=f"approved_home_row_{index}"):
            cells = st.columns([2.3, 1.5, 0.9, 1, 1.1, 1.2, 0.7], vertical_alignment="center")
            cells[0].markdown(f"{DOC}<span class='cv-ap-name'>{title}</span><div class='cv-ap-meta'>{filename}</div>", unsafe_allow_html=True)
            cells[1].markdown(project, unsafe_allow_html=True)
            cells[2].markdown(str(parts))
            cells[3].markdown(_health_pill(score), unsafe_allow_html=True)
            cells[4].markdown(f"<span class='cv-pill high'>{risk}</span>", unsafe_allow_html=True)
            cells[5].markdown(updated)
            analysis_id = str(row.get("id") or "")
            with cells[6]:
                _row_actions(
                    index,
                    menu_key=f"approved_home_menu_{index}",
                    open_key=f"approved_home_open_{index}",
                    destination="Analysis Details",
                    analysis_id=analysis_id,
                )
    if plan_notice and st.button("Compare plans", key="approved_home_compare_plans"):
        navigate_to("Pricing")
    end_approved_page()


def render_bom_catalog(records: list[dict[str, Any]] | None) -> None:
    begin_approved_page()
    rows = _records(records)
    with st.container(key="approved_bom_title"):
        title_col, action_col = st.columns([5.2, 1.6], vertical_alignment="center")
        with title_col:
            st.markdown(
                """
                <div class="cv-ap">
                  <h1>BOMs</h1>
                  <p class="cv-ap-sub">Saved analyses in this workspace.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with action_col:
            if st.button("+ New BOM analysis", key="approved_bom_new", type="primary"):
                st.session_state["cadivor_bom_upload_open"] = True
                st.rerun()
    query = st.text_input("Search BOMs, projects, or files", key="approved_bom_search")
    project, health, dates = st.columns(3)
    with project:
        st.selectbox("Project", ["All projects"], key="approved_bom_project")
    with health:
        health_filter = st.selectbox("Health", ["All health", "Healthy", "Review", "At risk"], key="approved_bom_health")
    with dates:
        st.selectbox("Date range", ["Last 90 days", "All time"], key="approved_bom_dates")
    needle = query.strip().casefold()
    visible = []
    for row in rows:
        name = str(_first(row, "project_name", "name", fallback=""))
        filename = str(_first(row, "filename", fallback=""))
        if needle and needle not in f"{name} {filename}".casefold():
            continue
        score = _num(_first(row, "health_score"))
        high = _num(_first(row, "high_risk_count"))
        if high >= 20 or score < 55:
            label = "At risk"
        elif high >= 5 or score < 80:
            label = "Review"
        else:
            label = "Healthy"
        if health_filter != "All health" and label != health_filter:
            continue
        visible.append((row, label))
    with st.container(key="approved_bom_head"):
        header = st.columns([1.7, 1.5, 0.6, 0.8, 0.7, 1.0, 1.3])
        for column, label in zip(header, ("Project", "File", "Parts", "Health", "High risk", "Last analyzed", "Actions")):
            column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
    if not visible:
        st.caption("No BOMs match these filters.")
    for index, (row, label) in enumerate(visible[:12]):
        kind = {"Healthy": "low", "Review": "medium", "At risk": "high"}[label]
        project_name = _esc(_first(row, "project_name", "name", fallback="Saved BOM"))
        filename = str(_first(row, "filename", fallback="") or "").strip()
        analysis_id = str(row.get("id") or "")
        with st.container(key=f"approved_bom_row_{index}"):
            cells = st.columns([1.7, 1.5, 0.6, 0.8, 0.7, 1.0, 1.3], vertical_alignment="center")
            cells[0].markdown(f"{PROJECT_ICON}<span class='cv-ap-name'>{project_name}</span>", unsafe_allow_html=True)
            with cells[1]:
                if filename and analysis_id:
                    internal_nav_button(
                        filename,
                        "Analysis Details",
                        key=f"approved_bom_file_{index}",
                        type="tertiary",
                        analysis_id=analysis_id,
                    )
                else:
                    st.markdown(_esc(filename or "—"))
            cells[2].markdown(str(_num(_first(row, "total_parts"))))
            cells[3].markdown(f"<span class='cv-pill {kind}'>{label}</span>", unsafe_allow_html=True)
            cells[4].markdown(str(_num(_first(row, "high_risk_count"))))
            cells[5].markdown(_esc(str(_first(row, "created_at", fallback=""))[:10]))
            with cells[6]:
                open_col, menu_col = st.columns([1.6, 0.7], vertical_alignment="center")
                with open_col:
                    if analysis_id:
                        internal_nav_button(
                            "Open",
                            "Analysis Details",
                            key=f"approved_bom_row_open_{index}",
                            type="primary",
                            analysis_id=analysis_id,
                        )
                with menu_col:
                    _row_actions(
                        index,
                        menu_key=f"approved_bom_menu_{index}",
                        open_key=f"approved_bom_open_{index}",
                        destination="Analysis Details",
                        analysis_id=analysis_id,
                    )
    if st.session_state.get("cadivor_bom_upload_open"):
        project_name = st.text_input("Project name", key="approved_bom_project_name")
        bom_name = st.text_input("BOM name", key="approved_bom_name")
        uploaded = st.file_uploader(
            "Upload your BOM file",
            type=["csv", "xlsx"],
            key="bom_file_uploader",
            help="CSV or Excel with MPN and Quantity columns.",
        )
        if st.button("Analyze BOM", key="approved_bom_analyze", type="primary") and uploaded is not None:
            st.session_state["cadivor_bom_analysis_ready"] = True
            st.session_state["cadivor_pending_upload"] = uploaded
            st.session_state["cadivor_pending_project"] = project_name
            st.session_state["cadivor_pending_bom_name"] = bom_name
            return
        if uploaded is None:
            st.caption("Choose a CSV or Excel file to run the existing BOM analysis.")
    if st.button("Manage saved BOMs", key="approved_bom_manage"):
        st.session_state["cadivor_manage_saved_boms"] = True
    if st.session_state.get("cadivor_manage_saved_boms"):
        st.caption("Open a saved analysis below. New files use Analyze BOM.")
    if st.session_state.get("cadivor_bom_analysis_ready"):
        return
    end_approved_page()


def render_decision_queue(records: list[dict[str, Any]] | None) -> None:
    begin_approved_page()
    source = _records(records)
    query = st.text_input("Search components, decisions or owners", key="approved_decision_search")
    filter_col, sort_col = st.columns(2)
    with filter_col:
        status_filter = st.selectbox("Filter", ["All statuses", "Open", "Overdue", "Resolved"], key="approved_decision_filter")
    with sort_col:
        sort_by = st.selectbox("Sort", ["Due date", "Risk level", "Component"], key="approved_decision_sort")
    needle = query.strip().casefold()
    rows = []
    for row in source:
        status = str(_first(row, "status", "decision_status", fallback="Open"))
        blob = " ".join(
            str(_first(row, key, fallback="") or "")
            for key in ("mpn", "part_number", "title", "summary", "alert_message", "owner", "assignee")
        ).casefold()
        if needle and needle not in blob:
            continue
        if status_filter != "All statuses" and status_filter.casefold() not in status.casefold():
            continue
        rows.append(row)
    if sort_by == "Component":
        rows.sort(key=lambda row: str(_first(row, "mpn", "part_number", fallback="")))
    elif sort_by == "Risk level":
        rows.sort(key=lambda row: str(_first(row, "risk_level", "severity", fallback="")))
    else:
        rows.sort(key=lambda row: str(_first(row, "due_date", "created_at", fallback="")))
    rows = rows[:8]
    open_count = len(rows)
    overdue = sum(1 for row in rows if "over" in str(_first(row, "status", "decision_status", fallback="")).casefold())
    resolved = sum(1 for row in rows if "resolv" in str(_first(row, "status", "decision_status", fallback="")).casefold())
    affected = len({str(_first(row, "analysis_id", fallback="")) for row in rows if _first(row, "analysis_id")})
    st.markdown(
        f"""
        <div class="cv-ap">
          <p class="cv-ap-kicker">ENGINEERING</p>
          <h1>Engineering decisions</h1>
          <p class="cv-ap-sub">Track and resolve key engineering decisions that impact your products, BOMs and supply chain.</p>
          <section class="cv-ap-kpis">
            <article class="cv-ap-kpi"><div class="cv-ap-kpi-top"><span class="cv-ap-ico">☰</span><span>Open decisions</span></div><strong>{open_count}</strong></article>
            <article class="cv-ap-kpi"><div class="cv-ap-kpi-top"><span class="cv-ap-ico">!</span><span>Overdue</span></div><strong>{overdue}</strong></article>
            <article class="cv-ap-kpi"><div class="cv-ap-kpi-top"><span class="cv-ap-ico">✓</span><span>Resolved this month</span></div><strong>{resolved}</strong><em class="muted">From the loaded queue</em></article>
            <article class="cv-ap-kpi"><div class="cv-ap-kpi-top"><span class="cv-ap-ico">▣</span><span>BOMs affected</span></div><strong>{affected}</strong></article>
          </section>
          <h2>Decision queue ({open_count})</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )
    header = st.columns([1.6, 1.8, 0.8, 0.9, 0.9, 0.8, 1.1])
    for column, label in zip(header, ("Component", "Title", "Risk level", "Decision status", "Owner", "Due date", "Actions")):
        column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
    if not rows:
        st.caption("No open engineering decisions in this workspace.")
    for index, row in enumerate(rows):
        level = str(_first(row, "risk_level", "severity", fallback="Medium"))
        kind = "high" if "high" in level.casefold() else ("low" if "low" in level.casefold() else "medium")
        status = str(_first(row, "status", "decision_status", fallback="Open"))
        owner = _first(row, "owner", "assignee", fallback=None)
        owner_label = "Unassigned" if owner is None else _esc(owner)
        mpn = str(_first(row, "mpn", "part_number", "component", fallback="Component"))
        detail = _first(row, "description", "part_description", fallback=None)
        subtitle = f"<div class='cv-ap-meta'>{_esc(detail)}</div>" if detail else ""
        due = _first(row, "due_date", fallback=None)
        due_label = _esc(str(due)[:10]) if due else "Not recorded"
        photo = part_photo(str(_first(row, "image_url", "photo_url", "image", fallback="") or ""), size=48, part=row)
        cells = st.columns([1.7, 1.8, 0.8, 0.9, 0.9, 0.9, 1.3], vertical_alignment="center")
        cells[0].markdown(f"{photo}<span class='cv-ap-name'>{_esc(mpn)}</span>{subtitle}", unsafe_allow_html=True)
        cells[1].markdown(_esc(_first(row, "title", "summary", "alert_message", fallback="Engineering decision")))
        cells[2].markdown(f"<span class='cv-pill {kind}'>{_esc(level)}</span>", unsafe_allow_html=True)
        cells[3].markdown(f"<span class='cv-pill open'>{_esc(status)}</span>", unsafe_allow_html=True)
        cells[4].markdown(owner_label)
        cells[5].markdown(due_label)
        analysis_id = str(row.get("analysis_id") or "")
        with cells[6]:
            review, menu = st.columns([2.2, 0.8])
            with review:
                if st.button("Review", key=f"approved_decision_review_{index}", type="primary"):
                    if analysis_id:
                        st.session_state["cadivor_active_analysis_id"] = analysis_id
                        navigate_to("Analysis Details")
                    else:
                        st.session_state["cadivor_decision_focus_mpn"] = mpn
            with menu:
                _row_actions(
                    index,
                    menu_key=f"approved_decision_menu_{index}",
                    open_key=f"approved_decision_open_{index}",
                    destination="Analysis Details",
                    analysis_id=analysis_id,
                )
    end_approved_page()


def _alert_slots(source: list[dict[str, Any]], predicate) -> list[float | None]:
    counts: dict[str, int] = {}
    for item in source:
        if not predicate(item):
            continue
        day = str(_first(item, "created_at", fallback=""))[:10]
        if not day:
            continue
        counts[day] = counts.get(day, 0) + 1
    slots: list[float | None] = [None] * 12
    for index, day in enumerate(sorted(counts)[:12]):
        slots[index] = float(counts[day])
    return slots


def _alert_category(row: dict[str, Any]) -> str:
    text = f"{_first(row, 'alert_type', fallback='')} {_first(row, 'alert_message', fallback='')}".casefold()
    if "life" in text:
        return "Lifecycle"
    if "price" in text or "cost" in text:
        return "Price movement"
    if "stock" in text or "invent" in text:
        return "Stock & supply"
    if "supplier" in text:
        return "Supplier"
    if "qual" in text:
        return "Quality"
    if "regulat" in text or "compliance" in text:
        return "Regulatory"
    return "Other"


def _next_action(row: dict[str, Any]) -> tuple[str, str]:
    category = _alert_category(row)
    if category == "Lifecycle":
        return "Review alternatives", "Alternative Finder"
    if category == "Stock & supply":
        return "View suppliers", "Procurement Advisor"
    if category == "Price movement":
        return "View pricing", "Cost Optimization"
    return "View details", "Monitoring"


def render_monitoring(alerts: list[dict[str, Any]] | None) -> None:
    begin_approved_page()
    source = _records(alerts)
    selected = st.segmented_control(
        "Show",
        ["All alerts", "Stock & supply", "Lifecycle", "Price movement", "Supplier", "Quality", "Regulatory"],
        default="All alerts",
        key="approved_alert_category",
    )
    period = st.selectbox("Time period", ["All recorded", "Last 30 days"], key="approved_alert_period")
    rows = source
    if selected and selected != "All alerts":
        rows = [row for row in rows if _alert_category(row) == selected]
    if period == "Last 30 days":
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        rows = [row for row in rows if str(_first(row, "created_at", fallback=""))[:10] >= cutoff]
    rows = rows[:8]
    high = sum(1 for row in source if "high" in str(_first(row, "severity", fallback="")).casefold())
    lifecycle_count = sum(1 for row in source if _alert_category(row) == "Lifecycle")
    inventory_count = sum(1 for row in source if _alert_category(row) == "Stock & supply")
    active_spark = spark_slots(_alert_slots(source, lambda _row: True), "#2563eb")
    high_spark = spark_slots(_alert_slots(source, lambda row: "high" in str(_first(row, "severity", fallback="")).casefold()), "#e11d48")
    life_spark = spark_slots(_alert_slots(source, lambda row: _alert_category(row) == "Lifecycle"), "#d97706")
    stock_spark = spark_slots(_alert_slots(source, lambda row: _alert_category(row) == "Stock & supply"), "#16a34a")
    st.markdown(
        f"""
        <div class="cv-ap">
          <h1>Alerts & monitoring</h1>
          <p class="cv-ap-sub">Stay ahead of changes in component availability, lifecycle status, pricing and supplier activity.</p>
          <section class="cv-ap-kpis">
            <article class="cv-ap-kpi cv-ap-kpi-row"><div><span>Active alerts</span><strong>{len(source)}</strong></div>{active_spark}</article>
            <article class="cv-ap-kpi cv-ap-kpi-row"><div><span>High priority</span><strong>{high}</strong></div>{high_spark}</article>
            <article class="cv-ap-kpi cv-ap-kpi-row"><div><span>Lifecycle changes</span><strong>{lifecycle_count}</strong></div>{life_spark}</article>
            <article class="cv-ap-kpi cv-ap-kpi-row"><div><span>Inventory updates</span><strong>{inventory_count}</strong></div>{stock_spark}</article>
          </section>
          <p class="cv-ap-meta">Each sparkline is a 12-bucket frame. Only recorded alert dates are drawn. Empty buckets are a data limitation: no alert history is stored for those periods.</p>
          <h2>Recent alerts</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )
    header = st.columns([0.8, 1.3, 1.6, 0.9, 1.2])
    for column, label in zip(header, ("Severity", "Component", "Signal", "Detected", "Next action")):
        column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
    if not rows:
        st.caption("No alerts in the selected period.")
    for index, row in enumerate(rows):
        severity = str(_first(row, "severity", fallback="Low"))
        kind = "high" if "high" in severity.casefold() else ("medium" if "med" in severity.casefold() else "low")
        action_label, destination = _next_action(row)
        cells = st.columns([0.8, 1.3, 1.6, 0.9, 1.2], vertical_alignment="center")
        cells[0].markdown(f"<span class='cv-pill {kind}'>{_esc(severity)}</span>", unsafe_allow_html=True)
        cells[1].markdown(f"<div class='cv-ap-name'>{_esc(_first(row, 'mpn', 'part_number', fallback='Component'))}</div>", unsafe_allow_html=True)
        cells[2].markdown(
            f"<div class='cv-ap-name'>{_esc(_first(row, 'alert_type', fallback='Update'))}</div><div class='cv-ap-meta'>{_esc(_first(row, 'alert_message', fallback=''))}</div>",
            unsafe_allow_html=True,
        )
        cells[3].markdown(_esc(str(_first(row, "created_at", fallback=""))[:10]))
        with cells[4]:
            if st.button(action_label, key=f"approved_alert_action_{index}"):
                navigate_to(destination)
    end_approved_page()


def render_reports_list(records: list[dict[str, Any]] | None) -> None:
    begin_approved_page()
    rows = _records(records)[:8]
    templates = (
        ("Executive BOM Report", "High-level summary of cost, supply risk and key insights for stakeholders.", ("DOCX", "XLSX", "PPTX")),
        ("Engineering Risk Review", "Detailed assessment of supply, obsolescence and compliance risks across your BOM.", ("DOCX", "XLSX")),
        ("Sourcing Summary", "Supplier options, cost comparison and recommended sourcing strategies.", ("XLSX", "PPTX")),
    )
    cards = []
    for title, copy, formats in templates:
        chips = "".join(f"<span class='cv-ap-chip'>{fmt}</span>" for fmt in formats)
        cards.append(f"<article class='cv-ap-template'><h3>{title}</h3><p>{copy}</p><div>Formats {chips}</div></article>")
    st.markdown(
        f"""
        <div class="cv-ap">
          <p class="cv-ap-kicker">REPORTS</p>
          <h1>Engineering reports</h1>
          <p class="cv-ap-sub">Create tailored reports from your engineering data and analysis results.</p>
          <h2>Report templates</h2>
          <section class="cv-ap-cards">{''.join(cards)}</section>
          <h2>Recent report sources</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="approved_report_head"):
        header = st.columns([1.8, 1.4, 1.1, 0.9, 1, 0.6])
        for column, label in zip(header, ("Name", "Source", "Last updated", "Health score", "High-risk parts", "Actions")):
            column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
    if not rows:
        st.caption("Upload a BOM analysis to populate recent report sources.")
    for index, row in enumerate(rows):
        score = _num(_first(row, "health_score"))
        with st.container(key=f"approved_report_row_{index}"):
            cells = st.columns([1.8, 1.4, 1.1, 0.9, 1, 0.6], vertical_alignment="center")
            cells[0].markdown(
                f"<div class='cv-ap-name'>{_esc(_first(row, 'project_name', 'name', fallback='Saved BOM'))}</div><div class='cv-ap-meta'>BOM Analysis</div>",
                unsafe_allow_html=True,
            )
            cells[1].markdown(_esc(_first(row, "filename", fallback="—")))
            cells[2].markdown(_esc(str(_first(row, "created_at", fallback=""))[:10]))
            cells[3].markdown(str(score))
            cells[4].markdown(str(_num(_first(row, "high_risk_count"))))
            analysis_id = str(row.get("id") or "")
            with cells[5]:
                _row_actions(
                    index,
                    menu_key=f"approved_report_menu_{index}",
                    open_key=f"approved_report_open_{index}",
                    destination="Analysis Details",
                    analysis_id=analysis_id,
                )
    end_approved_page()


def render_simple_workspace(
    *,
    kicker: str,
    title: str,
    subtitle: str,
    kpis: list[tuple[str, str]],
    headers: list[str],
    table_rows: list[list[str]],
    legacy_page: str = "",
    legacy_label: str = "Open workspace tools",
    chart_html: str = "",
    lead_html: str = "",
    control=None,
) -> None:
    begin_approved_page()
    kpi_html = "".join(
        f"<article class='cv-ap-kpi'><span>{_esc(label)}</span><strong>{_esc(value)}</strong></article>"
        for label, value in kpis
    )
    head = "".join(f"<th>{_esc(header)}</th>" for header in headers)
    body = []
    for row in table_rows[:8]:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append(f"<tr><td colspan='{max(1, len(headers))}'>No saved records for this workspace yet.</td></tr>")
    if len(kpis) == 5:
        columns = "five"
    elif len(kpis) == 3:
        columns = "three"
    else:
        columns = "four"
    charts = f'<div class="cv-ap-charts">{chart_html}</div>' if chart_html else ""
    st.markdown(
        f"""
        <div class="cv-ap">
          <p class="cv-ap-kicker">{_esc(kicker)}</p>
          <h1>{_esc(title)}</h1>
          <p class="cv-ap-sub">{_esc(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if control is not None:
        control()
    st.markdown(
        f"""
        <div class="cv-ap">
          {lead_html}
          <section class="cv-ap-kpis {columns}">{kpi_html}</section>
          {charts}
          <section class="cv-ap-card"><table class="cv-ap-table"><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></section>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if legacy_page and st.button(legacy_label, key=f"approved_legacy_{legacy_page}"):
        _open_legacy(legacy_page)
        st.rerun()
    end_approved_page()


def part_photo(url: str = "", size: int = 72, part: dict[str, Any] | None = None) -> str:
    """Supplier photo, or a category illustration labeled as artwork."""
    from src.part_images import part_image_markup

    return part_image_markup(url, "", size=size, part=part)


def part_thumbnail(seed: str = "", url: str = "") -> str:
    return part_photo(url)


def _row_actions(index: int, *, menu_key: str, open_key: str, destination: str, analysis_id: str) -> None:
    """Open the row menu first. Navigation runs only after Open is chosen."""
    with st.container(key=menu_key):
        with st.popover("⋯", use_container_width=False):
            internal_nav_button(
                "Open",
                destination,
                key=open_key,
                type="secondary",
                analysis_id=analysis_id,
            )


def _prior_delta(rows: list[dict[str, Any]], *prior_keys: str) -> str:
    values = []
    for row in rows:
        raw = _first(row, *prior_keys, fallback=None)
        if raw is None:
            continue
        values.append(_num(raw))
    if not values:
        return "<em class='muted'>Not recorded</em>"
    return f"<em>{sum(values)}</em>"


def spark_slots(values: list[float | None], color: str = "#2563eb") -> str:
    """Twelve-bucket sparkline frame. None leaves that period empty; it is not drawn as zero."""
    buckets = 12
    slots = list(values[:buckets])
    while len(slots) < buckets:
        slots.append(None)
    recorded = [value for value in slots if value is not None]
    peak = max(recorded) if recorded else 1.0
    marks = [
        '<rect x="0" y="0" width="84" height="36" rx="8" fill="#f8fafc"/>',
        '<line x1="4" y1="30" x2="80" y2="30" stroke="#e2e8f0" stroke-width="1"/>',
    ]
    for index, value in enumerate(slots):
        x = 4 + index * 6.5
        if value is None:
            continue
        height = max(8.0, 22.0 * (float(value) / (peak or 1.0)))
        marks.append(
            f'<rect x="{x:.1f}" y="{30 - height:.1f}" width="3" height="{height:.1f}" rx="1" fill="{color}"/>'
        )
    return (
        f'<svg class="cv-ap-spark" viewBox="0 0 84 36" width="84" height="36" aria-hidden="true">{"".join(marks)}</svg>'
    )


ICO_DOC = '<svg viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="1.8"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/></svg>'
ICO_WARN = '<svg viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="1.8"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>'
ICO_RISK = '<svg viewBox="0 0 24 24" fill="none" stroke="#e11d48" stroke-width="1.8"><path d="M12 3l7 3v6c0 5-3 8-7 9-4-1-7-4-7-9V6z"/></svg>'
ICO_HEALTH = '<svg viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="1.8"><path d="M3 12h4l2-5 4 10 2-5h6"/></svg>'


def impact_map_html(
    *,
    part: str,
    projects: list[tuple[str, str]],
    supplier: str = "",
    supplier_count: str = "",
    lifecycle: str = "",
) -> str:
    """Node diagram. Connectors join only the live part, project, BOM, supplier, and lifecycle."""
    nodes = []
    y = 24
    for project, bom in projects[:4]:
        nodes.append((220, y, project or "Project not recorded", "#eef2ff", "#6366f1"))
        nodes.append((460, y, bom or "BOM file not recorded", "#f5f3ff", "#7c3aed"))
        y += 64
    supplier_label = supplier or ("Supplier name not recorded" if supplier_count else "Not recorded")
    if supplier or supplier_count:
        nodes.append((220, y, supplier_label, "#ecfdf5", "#059669"))
        y += 64
    if lifecycle:
        nodes.append((220, y, lifecycle, "#fff7ed", "#ea580c"))
        y += 64
    height = max(180, y + 20)
    paths = []
    boxes = [
        f'<rect x="16" y="{(height/2)-28:.0f}" width="150" height="56" rx="12" fill="#eff6ff" stroke="#2563eb"/>'
        f'<text x="28" y="{(height/2)-6:.0f}" font-size="11" fill="#64748b">Component</text>'
        f'<text x="28" y="{(height/2)+12:.0f}" font-size="13" font-weight="700" fill="#0f172a">{html.escape(part or "Component")[:22]}</text>'
    ]
    part_y = height / 2
    for index, (x, node_y, label, fill, stroke) in enumerate(nodes):
        paths.append(
            f'<path d="M166 {part_y:.0f} C 190 {part_y:.0f}, 190 {node_y+22}, {x} {node_y+22}" fill="none" stroke="{stroke}" stroke-width="2"/>'
        )
        if x > 300 and index:
            paths.append(
                f'<path d="M370 {node_y+22} H {x}" fill="none" stroke="{stroke}" stroke-width="2"/>'
            )
        boxes.append(
            f'<rect x="{x}" y="{node_y}" width="180" height="44" rx="10" fill="{fill}" stroke="{stroke}"/>'
            f'<text x="{x+12}" y="{node_y+27}" font-size="12" fill="#0f172a">{html.escape(label)[:26]}</text>'
        )
    return (
        "<section class='cv-ap-card'><h2>Impact map</h2>"
        f'<svg viewBox="0 0 680 {height}" width="100%" height="{height}" role="img" aria-label="Impact map">'
        f'{"".join(paths)}{"".join(boxes)}</svg></section>'
    )


def procurement_header_html(part: dict[str, Any]) -> str:
    """Specification strip. Missing price and savings stay unavailable."""
    mpn = html.escape(str(part.get("mpn") or part.get("part_number") or "Part"))
    maker = html.escape(str(part.get("manufacturer") or "Not recorded"))
    description = html.escape(str(part.get("description") or "Not recorded"))
    lifecycle = html.escape(str(part.get("lifecycle_status") or "Not recorded"))
    category = html.escape(str(part.get("category") or "Not recorded"))
    price = part.get("unit_price")
    price_label = "Not recorded" if price in (None, "") else html.escape(str(price))
    photo = part_photo(str(part.get("image_url") or part.get("photo_url") or ""), part=part)
    savings = "Not recorded" if price in (None, "") else "Recorded price has no savings comparison"
    fields = (
        ("MPN", mpn),
        ("Manufacturer", maker),
        ("Description", description),
        ("Lifecycle", lifecycle),
        ("Category", category),
        ("Unit price", price_label),
        ("Last updated", "Not recorded"),
    )
    cells = "".join(
        f"<div><p class='cv-ap-meta'>{label}</p><strong>{value}</strong></div>"
        for label, value in fields
    )
    return (
        "<section class='cv-part-head' style='display:flex;gap:16px;align-items:center;background:#fff;border:1px solid #e6edf5;border-radius:16px;padding:16px 18px;margin-bottom:12px'>"
        f"{photo}<div style='display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:12px;flex:1'>{cells}</div></section>"
        "<section class='cv-ap-banner'><p class='cv-ap-meta'>Recommendation</p><h2>Review supplier coverage</h2>"
        f"<p>Savings {savings}. No second-source price is stored for this part.</p></section>"
    )


def portfolio_charts_html(parts: list[dict[str, Any]] | None) -> str:
    """Trend frame stays empty without monthly history. The donut uses live risk counts."""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    ticks = "".join(
        f'<text x="{24 + index * 46}" y="132" font-size="10" fill="#94a3b8">{label}</text>'
        for index, label in enumerate(months)
    )
    trend = (
        '<article class="cv-ap-chart"><h3>Portfolio risk trend</h3>'
        '<svg viewBox="0 0 580 148" width="100%" height="148" role="img" aria-label="Portfolio risk trend">'
        '<line x1="20" y1="16" x2="20" y2="112" stroke="#e2e8f0"/>'
        '<line x1="20" y1="112" x2="560" y2="112" stroke="#e2e8f0"/>'
        f'{ticks}</svg><p class="cv-ap-meta">Monthly history is not recorded.</p></article>'
    )
    mix = risk_mix_chart(parts) or (
        '<article class="cv-ap-chart"><h3>Risk distribution</h3><p class="cv-ap-meta">Not recorded</p></article>'
    )
    return f'<div class="cv-ap-charts">{trend}{mix}</div>'


def _dual_scale_supply_chart(
    labels: list[str],
    *,
    baseline: float,
    disrupted_values: list[float] | None,
    demand: float,
    disrupted_label: str,
    demand_label: str,
) -> str:
    """Stock stays on the left axis. Demand uses a labeled index scale so it stays visible."""
    width = 640
    slot = (width - 70) / max(len(labels) - 1, 1)
    stock_peak = max([baseline, * (disrupted_values or [baseline])]) or 1.0
    stock_peak = stock_peak * 1.15

    def stock_y(value: float) -> float:
        return 118 - (96 * (value / stock_peak))

    demand_y = 78.0
    stock_line = " ".join(f"{36 + index * slot:.1f},{stock_y(baseline):.1f}" for index in range(len(labels)))
    lines = [f'<polyline fill="none" stroke="#2563eb" stroke-width="2.5" points="{stock_line}"/>']
    if disrupted_values:
        disrupted_line = " ".join(
            f"{36 + index * slot:.1f},{stock_y(value):.1f}" for index, value in enumerate(disrupted_values)
        )
        lines.append(f'<polyline fill="none" stroke="#e11d48" stroke-width="2.5" points="{disrupted_line}"/>')
    demand_line = " ".join(f"{36 + index * slot:.1f},{demand_y:.1f}" for index in range(len(labels)))
    lines.append(
        f'<polyline fill="none" stroke="#64748b" stroke-width="2.5" stroke-dasharray="6 4" points="{demand_line}"/>'
    )
    grid = []
    for fraction, label in ((0, "0"), (0.5, _compact_units(stock_peak * 0.5)), (1, _compact_units(stock_peak))):
        y = 118 - (96 * fraction)
        grid.append(f'<line x1="36" y1="{y:.1f}" x2="610" y2="{y:.1f}" stroke="#e2e8f0"/>')
        grid.append(f'<text x="2" y="{y + 4:.1f}" font-size="10" fill="#64748b">{label}</text>')
    grid.append(f'<text x="612" y="{demand_y + 4:.1f}" font-size="10" fill="#64748b">{_compact_units(demand)}</text>')
    grid.append('<text x="36" y="14" font-size="10" fill="#64748b">Recorded stock (units)</text>')
    grid.append('<text x="430" y="14" font-size="10" fill="#64748b">Required units (index scale)</text>')
    axis = "".join(
        f'<text x="{36 + index * slot:.1f}" y="138" font-size="11" fill="#64748b">{html.escape(label)}</text>'
        for index, label in enumerate(labels)
    )
    legend = (
        '<p class="cv-ap-meta">'
        '<span style="color:#2563eb">Baseline supply (modeled)</span> · '
        f'<span style="color:#e11d48">{html.escape(disrupted_label)}</span> · '
        f'<span style="color:#64748b">{html.escape(demand_label)}</span>'
        "</p>"
    )
    return (
        '<article class="cv-ap-chart"><h3>Projected supply vs. demand</h3>'
        f'<svg viewBox="0 0 {width} 150" width="100%" height="168" role="img" aria-label="Projected supply vs. demand">'
        f'{"".join(grid)}{"".join(lines)}{axis}</svg>{legend}</article>'
    )


def _compact_units(value: float) -> str:
    number = float(value)
    if abs(number) >= 1000:
        return f"{number / 1000:.1f}k"
    if abs(number - round(number)) < 0.05:
        return str(int(round(number)))
    return f"{number:.1f}"


def modeled_supply_chart(
    *,
    baseline: float | None,
    disrupted: float | None,
    demand: float | None,
    stock_reduction_percent: int = 0,
    demand_growth_percent: int = 0,
    disrupted_label: str = "",
    assumption: str = "",
) -> str:
    """90-day scenario lines. These are modeled projections, not observed history."""
    labels = ["Day 0", "Day 15", "Day 30", "Day 45", "Day 60", "Day 75", "Day 90"]
    series = []
    if baseline is not None:
        series.append(("Baseline supply (modeled)", "#2563eb", [(label, baseline) for label in labels]))
    if disrupted is not None and baseline is not None:
        points = []
        for index, label in enumerate(labels):
            points.append((label, baseline if index < 3 else disrupted))
        series.append((disrupted_label or f"Disrupted supply (modeled, {stock_reduction_percent}% stock cut)", "#e11d48", points))
    if demand is not None:
        series.append(
            (
                "Demand forecast (modeled, required units held flat)" if demand_growth_percent == 0 else f"Demand forecast (modeled, {demand_growth_percent}% growth)",
                "#64748b",
                [(label, demand) for label in labels],
            )
        )
    if demand is not None and baseline is not None:
        disrupted_values = [baseline if index < 3 else disrupted for index in range(len(labels))]
        chart = _dual_scale_supply_chart(
            labels,
            baseline=baseline,
            disrupted_values=disrupted_values if disrupted is not None else None,
            demand=demand,
            disrupted_label=disrupted_label or "Disrupted supply (modeled)",
            demand_label="Demand forecast (modeled, required units)",
        )
    else:
        chart = series_chart("Projected supply vs. demand", series)
    detail = assumption or (
        "Baseline holds recorded stock flat for 90 days. "
        f"Disrupted supply applies the {stock_reduction_percent}% stock-reduction slider after day 45. "
        f"Demand holds required units flat, including the {demand_growth_percent}% demand-growth slider."
    )
    note = (
        "<p class='cv-ap-meta'>Modeled scenario, not observed history. "
        f"{detail} Demand is plotted on a labeled index scale so required units stay visible beside recorded stock. "
        "The quantities themselves are unchanged. Days without a recorded input stay off the line.</p>"
    )
    return chart + note


def supply_scenario_chart(parts: list[dict[str, Any]] | None, scenario: dict[str, Any] | None, choice: str) -> str:
    """90-day lines for the reference scenario control. Disruption uses recorded supplier counts."""
    baseline_total = 0.0
    disrupted_total = 0.0
    have_stock = False
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        raw = part.get("stock_available")
        if raw is None or str(raw).strip() == "":
            continue
        try:
            stock = float(raw)
        except (TypeError, ValueError):
            continue
        have_stock = True
        baseline_total += stock
        count = None
        suppliers = part.get("supplier_count")
        try:
            if suppliers not in (None, ""):
                count = int(float(suppliers))
        except (TypeError, ValueError):
            count = None
        if choice == "Primary supplier disruption" and count and count > 0:
            disrupted_total += stock * max(count - 1, 0) / count
        else:
            disrupted_total += stock
    demand = None
    rows = (scenario or {}).get("rows") or []
    if rows:
        try:
            demand = sum(float(row.get("Required Units") or 0) for row in rows if isinstance(row, dict))
        except (TypeError, ValueError):
            demand = None
    if choice == "Primary supplier disruption":
        assumption = (
            "Primary supplier disruption, 90-day horizon. "
            "After day 45, each part with a recorded supplier count loses one supplier's even share of recorded stock. "
            "Parts without a supplier count keep recorded stock. Demand is required units, held flat."
        )
        disrupted_label = "Disrupted supply (modeled, one supplier share removed)"
    else:
        assumption = "No disruption selected. Disrupted supply matches recorded stock across the 90-day horizon. Demand is required units, held flat."
        disrupted_label = "Disrupted supply (modeled, no disruption)"
    return modeled_supply_chart(
        baseline=baseline_total if have_stock else None,
        disrupted=disrupted_total if have_stock else None,
        demand=demand,
        disrupted_label=disrupted_label,
        assumption=assumption,
    )


def excel_bytes(rows: list[dict[str, Any]]) -> bytes:
    import pandas as pd

    frame = pd.DataFrame(rows)
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False)
    return buffer.getvalue()


def render_replacement_search() -> None:
    """Find-a-replacement layout wired to the live alternative search."""
    begin_approved_page()
    st.session_state.setdefault(
        "approved_replacement_query",
        str(st.session_state.get("cadivor_replacement_query") or ""),
    )
    search_col, button_col = st.columns([4, 1], vertical_alignment="bottom")
    with search_col:
        query = st.text_input("Search MPN", key="approved_replacement_query")
    with button_col:
        run = st.button("Search", key="approved_replacement_search", type="primary")
    result = st.session_state.get("alternative_finder_result")
    if run and query.strip():
        from src.alternative_finder_search import run_alternative_finder_search

        run_alternative_finder_search(st.session_state, query.strip())
        result = st.session_state.get("alternative_finder_result")
    original = {}
    candidates: list[dict[str, Any]] = []
    if isinstance(result, dict):
        original = result.get("original_data") if isinstance(result.get("original_data"), dict) else {}
        raw_candidates = result.get("candidates") or result.get("alternative_candidates") or []
        candidates = [row for row in raw_candidates if isinstance(row, dict)]
    fit_filter, life_filter, stock_filter, risk_filter, sort_by = st.columns(5)
    with fit_filter:
        fit_choice = st.selectbox("Parametric fit", ["All"], key="approved_fit_filter")
    with life_filter:
        life_choice = st.selectbox("Lifecycle", ["All", "Active", "NRND", "Obsolete"], key="approved_life_filter")
    with stock_filter:
        stock_choice = st.selectbox("Stock", ["All", "In stock", "No stock"], key="approved_stock_filter")
    with risk_filter:
        risk_choice = st.selectbox("Risk", ["All", "High", "Medium", "Low"], key="approved_risk_filter")
    with sort_by:
        sort_choice = st.selectbox("Sort by", ["Overall match", "Stock", "Risk"], key="approved_replacement_sort")
    filtered = []
    for row in candidates:
        level = str(row.get("Estimated Risk") or row.get("risk_level") or row.get("risk") or "")
        lifecycle = str(row.get("Lifecycle") or row.get("lifecycle_status") or row.get("lifecycle") or "")
        stock_value = _candidate_stock(row)
        if life_choice != "All" and life_choice.casefold() not in lifecycle.casefold():
            continue
        if risk_choice != "All" and risk_choice.casefold() not in level.casefold():
            continue
        if stock_choice == "In stock" and stock_value <= 0:
            continue
        if stock_choice == "No stock" and stock_value > 0:
            continue
        filtered.append(row)
    if sort_choice == "Stock":
        filtered.sort(key=_candidate_stock, reverse=True)
    elif sort_choice == "Risk":
        filtered.sort(key=lambda row: str(row.get("Estimated Risk") or row.get("risk_level") or ""))
    named = [row for row in filtered if _candidate_mpn(row)]
    dropped = len(filtered) - len(named)
    candidates = named
    del fit_choice
    mpn = _esc(original.get("manufacturer_part_number") or original.get("mpn") or (query or "Search an MPN"))
    manufacturer = _esc(original.get("manufacturer") or original.get("Manufacturer") or original.get("manufacturer_name") or "—")
    description = _esc(original.get("description") or original.get("category") or "")
    notice = ""
    if isinstance(result, dict):
        notice = str(result.get("search_error") or result.get("lookup_error") or "").strip()
    if query.strip() and isinstance(result, dict) and not candidates and not notice:
        notice = "No supplier alternatives were returned for this part."
    elif dropped and not notice:
        notice = f"{dropped} supplier row{'s' if dropped != 1 else ''} had no part number and {'were' if dropped != 1 else 'was'} left out."
    shown = candidates[:25]
    body = []
    from src.part_images import part_image_markup

    for row in shown:
        level = _candidate_field(row, "Estimated Risk", "risk_level", "risk")
        kind = ""
        if "high" in level.casefold():
            kind = "high"
        elif "low" in level.casefold():
            kind = "low"
        elif "medium" in level.casefold():
            kind = "medium"
        level_html = f"<span class='cv-pill {kind}'>{level}</span>" if kind else level
        candidate = _esc(_candidate_mpn(row))
        discovery = row.get("_discovery_row") if isinstance(row.get("_discovery_row"), dict) else {}
        image = str(
            row.get("image_url")
            or row.get("photo_url")
            or row.get("Image URL")
            or discovery.get("image_url")
            or discovery.get("photo_url")
            or ""
        )
        body.append(
            "<tr>"
            f"<td>{part_image_markup(image, _candidate_mpn(row), size=48, part=row)}<span class='cv-ap-name'>{candidate}</span></td>"
            f"<td>{_candidate_field(row, 'Manufacturer', 'manufacturer')}</td>"
            f"<td>{_candidate_field(row, 'Classification', 'Category', 'fit', 'parametric_fit')}</td>"
            f"<td>{_candidate_field(row, 'Lifecycle', 'lifecycle_status', 'lifecycle')}</td>"
            f"<td>{_candidate_field(row, 'Stock', 'stock_total', 'stock_available')}</td>"
            f"<td>{_candidate_field(row, 'Supplier', 'supplier_count', 'supplier')}</td>"
            f"<td>{level_html}</td>"
            "</tr>"
        )
    if len(candidates) > len(shown) and not notice:
        notice = f"Showing {len(shown)} of {len(candidates)} supplier alternatives."
    notice_html = f"<p class='cv-ap-sub'>{_esc(notice)}</p>" if notice and body else ""
    if not body:
        empty = _esc(notice or "Search a manufacturer part number. Results come from the live supplier search.")
        body.append(f"<tr><td colspan='7'>{empty}</td></tr>")
        notice_html = ""
    st.markdown(
        f"""
        <div class="cv-ap">
          <h1>Find a replacement</h1>
          <p class="cv-ap-sub">Search for a part to find compatible alternatives across suppliers.</p>
          <section class="cv-ap-card">
            <div class="cv-ap-meta">Source part</div>
            <div>{part_photo(str(original.get('image_url') or original.get('photo_url') or ''), part=original)}<span class="cv-ap-name">{mpn}</span></div>
            <p class="cv-ap-meta">{description}</p>
            <p>Manufacturer {manufacturer}</p>
          </section>
          {notice_html}
          <h2>Replacement options ({len(candidates)})</h2>
          <section class="cv-ap-card"><table class="cv-ap-table"><thead><tr>
            <th>Candidate MPN</th><th>Manufacturer</th><th>Parametric fit</th><th>Lifecycle</th><th>Stock</th><th>Suppliers</th><th>Risk</th>
          </tr></thead><tbody>{''.join(body)}</tbody></table></section>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for index, row in enumerate(candidates[:5]):
        candidate = _candidate_mpn(row)
        if candidate and st.button(f"Compare {candidate}", key=f"approved_replacement_compare_{index}"):
            st.session_state["cadivor_compare_part_a"] = str(original.get("manufacturer_part_number") or query or "")
            st.session_state["cadivor_compare_part_b"] = candidate
            navigate_to("Compare Parts")
    end_approved_page()


def render_compare_live() -> None:
    """Compare-parts layout wired to the live two-part comparison."""
    begin_approved_page()
    from src.parts_compare import run_compare_parts

    st.session_state.setdefault("approved_compare_a", str(st.session_state.get("cadivor_compare_part_a") or ""))
    st.session_state.setdefault("approved_compare_b", str(st.session_state.get("cadivor_compare_part_b") or ""))
    left, right = st.columns(2)
    with left:
        part_a = st.text_input("Part A", key="approved_compare_a")
    with right:
        part_b = st.text_input("Part B", key="approved_compare_b")
    if st.button("Compare parts", key="approved_compare_run", type="primary") and part_a.strip() and part_b.strip():
        st.session_state["cadivor_compare_result"] = run_compare_parts(part_a.strip(), part_b.strip())
    result = st.session_state.get("cadivor_compare_result")
    comparison = result.get("comparison") if isinstance(result, dict) else {}
    if not isinstance(comparison, dict):
        comparison = {}
    counts = comparison.get("counts") if isinstance(comparison.get("counts"), dict) else {}
    card_a = comparison.get("part_a") if isinstance(comparison.get("part_a"), dict) else {}
    card_b = comparison.get("part_b") if isinstance(comparison.get("part_b"), dict) else {}
    rows = comparison.get("rows") if isinstance(comparison.get("rows"), list) else []
    body = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        label = _esc(row.get("label") or row.get("parameter") or row.get("field") or "Parameter")
        raw_a = str(row.get("part_a") or row.get("a") or row.get("value_a") or "—")
        raw_b = str(row.get("part_b") or row.get("b") or row.get("value_b") or "—")
        value_a = _esc(raw_a)
        value_b = _esc(raw_b)
        highlight = " style='background:#eff6ff'" if raw_a.strip() != raw_b.strip() else ""
        body.append(f"<tr><td>{label}</td><td{highlight}>{value_a}</td><td{highlight}>{value_b}</td><td></td></tr>")
    if not body:
        body.append("<tr><td colspan='4'>Enter two manufacturer part numbers. The third column stays empty until another part is added.</td></tr>")
    name_a = _esc(card_a.get("mpn") or part_a or "Part A")
    name_b = _esc(card_b.get("mpn") or part_b or "Part B")
    error = _esc(result.get("error") if isinstance(result, dict) else "")
    notice = f"<p class='cv-ap-sub'>{error}</p>" if error and error != "—" else ""
    st.markdown(
        f"""
        <div class="cv-ap">
          <p class="cv-ap-kicker">PARTS</p>
          <h1>Compare parts</h1>
          <p class="cv-ap-sub">Compare key parameters, identify differences, and find the best fit for your design.</p>
          {notice}
          <section class="cv-ap-kpis three">
            <article class="cv-ap-kpi"><span>Compatible fields</span><strong>{_esc(counts.get('compatible', '—'))}</strong></article>
            <article class="cv-ap-kpi"><span>Material differences</span><strong>{_esc(counts.get('material_difference', '—'))}</strong></article>
            <article class="cv-ap-kpi"><span>Needs validation</span><strong>{_esc(counts.get('needs_data', '—'))}</strong></article>
          </section>
          <section class="cv-ap-cards">
            <article class="cv-ap-template">{part_photo(str(card_a.get('image_url') or card_a.get('photo_url') or ''), part=card_a)}<h3>{name_a}</h3><p>{_esc(card_a.get('description') or card_a.get('manufacturer') or 'Not recorded')}</p></article>
            <article class="cv-ap-template">{part_photo(str(card_b.get('image_url') or card_b.get('photo_url') or ''), part=card_b)}<h3>{name_b}</h3><p>{_esc(card_b.get('description') or card_b.get('manufacturer') or 'Not recorded')}</p></article>
            <article class="cv-ap-template">{part_photo('')}<h3>Add part</h3><p>No third candidate is selected.</p></article>
          </section>
          <section class="cv-ap-card"><table class="cv-ap-table"><thead><tr>
            <th>Parameter</th><th>{name_a}</th><th>{name_b}</th><th>Part C</th>
          </tr></thead><tbody>{''.join(body)}</tbody></table></section>
        </div>
        """,
        unsafe_allow_html=True,
    )
    end_approved_page()


def render_datasheet_live() -> None:
    """Datasheet Q&A layout wired to the existing PDF question flow."""
    from src.datasheet_qa import (
        DATASHEET_QA_DOC_KEY,
        DATASHEET_QA_THREAD_KEY,
        extract_uploaded_datasheet,
        store_document_in_session,
    )
    from src.pages.datasheet_qa import _execute_datasheet_question

    begin_approved_page()
    document = st.session_state.get(DATASHEET_QA_DOC_KEY)
    ready = isinstance(document, dict) and bool(document.get("available"))
    uploaded = st.file_uploader("Change document", type=["pdf"], key="datasheet_qa_uploader")
    if uploaded is not None and not ready:
        extracted = extract_uploaded_datasheet(uploaded.getvalue(), filename=str(uploaded.name or ""))
        store_document_in_session(st.session_state, extracted)
        document = st.session_state.get(DATASHEET_QA_DOC_KEY)
        ready = isinstance(document, dict) and bool(document.get("available"))
        if not ready:
            st.warning(str((extracted or {}).get("reason") or "Could not read this PDF."))
    question = st.text_input("Your question", key="approved_datasheet_question", disabled=not ready)
    if st.button("Ask", key="approved_datasheet_ask", type="primary", disabled=not ready) and question.strip() and ready:
        thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
        _execute_datasheet_question(document=document, question=question.strip(), thread=thread)
    thread = list(st.session_state.get(DATASHEET_QA_THREAD_KEY) or [])
    latest = thread[-1] if thread and isinstance(thread[-1], dict) else {}
    answer = _esc(latest.get("answer") or latest.get("text") or "")
    filename = _esc((document or {}).get("filename") if isinstance(document, dict) else "No document selected")
    evidence = latest.get("evidence") or latest.get("sources") or []
    evidence_rows = []
    if isinstance(evidence, list):
        for item in evidence[:6]:
            if isinstance(item, dict):
                evidence_rows.append(
                    "<tr>"
                    f"<td>{_esc(item.get('parameter') or item.get('label') or item.get('text') or 'Source')}</td>"
                    f"<td>{_esc(item.get('value') or item.get('excerpt') or '')}</td>"
                    f"<td>{_esc(item.get('page') or '')}</td>"
                    "</tr>"
                )
    if not evidence_rows:
        evidence_rows.append("<tr><td colspan='3'>Upload a text-searchable PDF and ask a question to see cited evidence.</td></tr>")
    answer_block = (
        f"<section class='cv-ap-banner'><h2>Answer</h2><p>{answer}</p></section>"
        if answer and answer != "—"
        else ""
    )
    st.markdown(
        f"""
        <div class="cv-ap">
          <p class="cv-ap-kicker">DATASHEET Q&A</p>
          <h1>Ask a datasheet</h1>
          <p class="cv-ap-sub">Get precise answers from technical documents, with source citations.</p>
          <section class="cv-ap-card"><div class="cv-ap-meta">Selected document</div><div class="cv-ap-name">{filename}</div></section>
          {answer_block}
          <section class="cv-ap-card"><table class="cv-ap-table"><thead><tr>
            <th>Source</th><th>Evidence</th><th>Page</th>
          </tr></thead><tbody>{''.join(evidence_rows)}</tbody></table></section>
        </div>
        """,
        unsafe_allow_html=True,
    )
    end_approved_page()


def render_settings_workspace(profile: dict[str, Any], plan_name: str) -> None:
    """Profile, notifications, security, and billing on one screen."""
    begin_approved_page()
    profile = profile if isinstance(profile, dict) else {}
    name = _esc(profile.get("full_name") or profile.get("email") or "Account")
    email = _esc(profile.get("email") or "")
    company = _esc(profile.get("company") or profile.get("company_name") or "Not recorded")
    role = _esc(profile.get("role_title") or profile.get("role") or "Not recorded")
    timezone = _esc(profile.get("timezone") or "Not recorded")
    workspace = _esc(profile.get("workspace_name") or company)
    plan = _esc(plan_name or profile.get("plan") or "Not recorded")
    with st.container(key="approved_settings_screen"):
        _render_settings_panels(profile, name, email, company, role, timezone, workspace, plan)
    end_approved_page()


def _render_settings_panels(profile, name, email, company, role, timezone, workspace, plan) -> None:
    st.markdown("<div class='cv-ap'><h1>Settings</h1></div>", unsafe_allow_html=True)
    left, right = st.columns(2)
    with left:
        st.markdown(
            f"""
            <div class="cv-ap"><section class="cv-ap-card"><h2>Profile</h2>
            <p class="cv-ap-name">{name}</p><p>{email}</p>
            <div class="cv-security-row"><span>Organization</span><strong>{company}</strong></div>
            <div class="cv-security-row"><span>Role</span><strong>{role}</strong></div>
            <div class="cv-security-row"><span>Workspace</span><strong>{workspace}</strong></div>
            </section></div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("approved_profile_form"):
            name_col, company_col, role_col = st.columns(3)
            full_name = name_col.text_input("Full name", value=str(profile.get("full_name") or ""))
            company_input = company_col.text_input("Organization", value=str(profile.get("company") or profile.get("company_name") or ""))
            role_input = role_col.text_input("Role", value=str(profile.get("role_title") or ""))
            submitted = st.form_submit_button("Save profile")
        if submitted:
            from src.authenticated_runtime import update_user_profile_fields

            user_id = str(profile.get("id") or st.session_state.get("user_id") or "")
            allowed, skipped = update_user_profile_fields(
                user_id,
                {"full_name": full_name, "company": company_input, "role_title": role_input},
            )
            if allowed:
                st.success("Profile updated.")
            elif skipped:
                st.info("Those profile fields are not stored on this account.")
        st.markdown(
            """
            <div class="cv-ap"><section class="cv-ap-card"><h2>Security</h2>
            <div class="cv-security-row"><span>Password</span><strong>Managed by your sign-in provider</strong></div>
            <div class="cv-security-row"><span>Two-factor authentication</span><strong>Not recorded</strong></div>
            <div class="cv-security-row"><span>Active sessions</span><strong>This browser session</strong></div>
            <div class="cv-security-row"><span>Connected accounts</span><strong>Not recorded</strong></div>
            </section></div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"""
            <div class="cv-ap"><section class="cv-ap-card"><h2>Account preferences</h2>
            <p class="cv-ap-meta">Email notifications use this account. Timezone {timezone}</p>
            </section></div>
            """,
            unsafe_allow_html=True,
        )
        st.toggle("Project activity", key="approved_notify_project")
        st.toggle("Simulation results", key="approved_notify_simulation")
        st.toggle("Team activity", key="approved_notify_team")
        st.toggle("Product updates", key="approved_notify_product")
        st.toggle("Marketing emails", key="approved_notify_marketing")
        st.text_input("Timezone", key="approved_settings_timezone", placeholder=str(profile.get("timezone") or "Not recorded"))
        st.markdown(
            f"""
            <div class="cv-ap"><section class="cv-plan-card"><p class="cv-ap-meta">Current plan</p>
            <h2>{plan}</h2>
            <p>Plan limits come from the signed-in subscription. Features that are not on this account stay blank.</p>
            </section></div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Manage plan", key="approved_settings_manage_plan", type="primary"):
            navigate_to("Pricing")
