"""Approved Engineering Intelligence and BOM-list layouts.

Mockup #16 is the visual system for the Engineering Intelligence report.
BOM Risk is the pictured tab. Supply & Availability, Alternatives, Cost
Insights, and Lifecycle use that same page chrome with the analysis data
already loaded for the saved BOM. Mockup #15 is the expandable detailed
risk report. Mockup #2 is the BOM catalog.
"""

from __future__ import annotations

import html
from typing import Any


def _part_art(mpn: str, url: str = "", part: dict[str, Any] | None = None) -> str:
    """Supplier photo, or a category illustration that is not claimed as that MPN."""
    from src.part_images import part_image_markup

    return part_image_markup(url, mpn, size=48, part=part)


def _component_cell(row: dict[str, Any], *, description: bool = True) -> str:
    art = _part_art(
        str(row.get("mpn_raw") or row.get("mpn") or ""),
        str(row.get("image") or ""),
        part=row,
    )
    copy = f"<span class='cv-ei-part-copy'><span>{row['mpn']}</span>"
    if description:
        copy += f"<span class='cv-ei-meta'>{row['description']}</span>"
    copy += "</span>"
    return f"<div class='cv-ei-part'>{art}{copy}</div>"


EI_TABS = (
    "BOM Risk",
    "Supply & Availability",
    "Alternatives",
    "Cost Insights",
    "Lifecycle",
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


def _level(part: dict[str, Any]) -> str:
    label = str(_first(part, "risk_level", "Risk Level", fallback="Low") or "Low")
    folded = label.casefold()
    if "high" in folded or "critical" in folded:
        return "High"
    if "med" in folded:
        return "Medium"
    if "low" in folded:
        return "Low"
    score = _num(_first(part, "risk_score", "Risk Score"))
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def _level_class(level: str) -> str:
    return {"High": "high", "Medium": "medium", "Low": "low"}.get(level, "low")


def _drivers(part: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    stock = _num(_first(part, "stock_available", "Stock Available", "stock"), -1)
    suppliers = _num(_first(part, "supplier_count", "Supplier Count"), -1)
    lifecycle = str(_first(part, "lifecycle_status", "Lifecycle Status", fallback="") or "")
    lead = _first(part, "lead_time_weeks", "Lead Time Weeks")
    if any(token in lifecycle.casefold() for token in ("obsolete", "eol", "end of life", "nrnd")):
        notes.append("Product lifecycle status: " + lifecycle)
    if stock == 0:
        notes.append("No stock at approved suppliers")
    elif 0 < stock < 100:
        notes.append("Limited stock at approved suppliers")
    if suppliers == 1:
        notes.append("Single-source manufacturer")
    elif 0 <= suppliers < 3:
        notes.append("Fewer than 3 active suppliers")
    if lead is not None and _num(lead, 0) >= 26:
        notes.append(f"Long lead time ({_num(lead)}+ weeks)")
    if not notes:
        notes.append("No material supply or lifecycle exception in the saved analysis")
    return notes[:3]


def _action(level: str) -> tuple[str, str]:
    if level == "High":
        return (
            "Review alternative parts",
            "Find qualified alternatives or consider a design change.",
        )
    if level == "Medium":
        return (
            "Monitor and consider alternates",
            "Keep under review and qualify a secondary supplier.",
        )
    return (
        "No immediate action",
        "Stock, lifecycle, and supplier coverage are within the saved baseline.",
    )


def _part_rows(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        level = _level(part)
        title, detail = _action(level)
        raw_mpn = str(_first(part, "mpn", "MPN", "part_number", fallback="Part") or "Part")
        ranked.append(
            {
                "mpn_raw": raw_mpn,
                "mpn": _esc(raw_mpn),
                "description_raw": str(
                    _first(part, "description", "Description", "part_description", fallback="") or ""
                ),
                "category_raw": str(
                    _first(part, "category", "Category", "device_type", "architecture", fallback="") or ""
                ),
                "description": _esc(
                    _first(part, "description", "Description", "part_description", fallback="Component")
                ),
                "manufacturer": _esc(_first(part, "manufacturer", "Manufacturer", fallback="—")),
                "level": level,
                "score": _num(_first(part, "risk_score", "Risk Score")),
                "stock": _num(_first(part, "stock_available", "Stock Available", "stock"), 0),
                "suppliers": _num(_first(part, "supplier_count", "Supplier Count"), 0),
                "lifecycle": _esc(_first(part, "lifecycle_status", "Lifecycle Status", fallback="Unknown")),
                "lead": _esc(_first(part, "lead_time_weeks", "Lead Time Weeks", fallback="—")),
                "source": _esc(_first(part, "best_source", "Best Source", "distributor", fallback="—")),
                "price": _esc(_first(part, "unit_price", "Unit Price", "price", fallback="—")),
                "image": str(
                    _first(
                        part,
                        "image_url",
                        "photo_url",
                        "Photo",
                        "Image URL",
                        "image",
                        "PrimaryPhoto",
                        fallback="",
                    )
                    or ""
                ),
                "drivers": [_esc(item) for item in _drivers(part)],
                "action": _esc(title),
                "action_detail": _esc(detail),
            }
        )
    order = {"High": 0, "Medium": 1, "Low": 2}
    ranked.sort(key=lambda row: (order.get(row["level"], 3), -row["score"]))
    return ranked


def report_styles() -> str:
    return """
    <style>
      .cv-ei-report { color:#0f172a; font-family: Inter, "Segoe UI", sans-serif; }
      .cv-ei-kicker { color:#64748b; font-size:13px; font-weight:600; margin:0 0 6px; }
      .cv-ei-title { font-size:32px; line-height:1.15; font-weight:760; letter-spacing:-.03em; margin:0; }
      .cv-ei-sub { color:#64748b; font-size:14px; margin:6px 0 18px; }
      .cv-ei-banner { display:flex; gap:16px; align-items:flex-start; background:#fff5f5; border:1px solid #fecdd3; border-radius:16px; padding:22px 24px; margin-bottom:16px; }
      .cv-ei-icon { width:36px; height:36px; border-radius:999px; display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; font-size:16px; }
      .cv-ei-icon.warn { background:#ffe4e6; color:#e11d48; }
      .cv-ei-icon.health { background:#dcfce7; color:#16a34a; }
      .cv-ei-icon.review { background:#ffe4e6; color:#e11d48; }
      .cv-ei-icon.stock { background:#ffedd5; color:#ea580c; }
      .cv-ei-icon.source { background:#ede9fe; color:#7c3aed; }
      .cv-ei-banner h2 { margin:0 0 6px; font-size:28px; letter-spacing:-.03em; }
      .cv-ei-banner p { margin:0; color:#475569; font-size:15px; }
      .cv-ei-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:0 0 22px; }
      .cv-ei-kpi { background:#fff; border:1px solid #e6edf5; border-radius:14px; padding:16px 18px; display:flex; gap:12px; align-items:center; }
      .cv-ei-kpi strong { display:block; font-size:22px; letter-spacing:-.03em; }
      .cv-ei-kpi span { color:#64748b; font-size:13px; font-weight:650; }
      .cv-ei-section h3 { margin:0 0 4px; font-size:20px; }
      .cv-ei-section p { margin:0 0 12px; color:#64748b; font-size:14px; }
      .cv-ei-table { width:100%; border-collapse:separate; border-spacing:0; background:#fff; border:1px solid #e6edf5; border-radius:16px; overflow:hidden; }
      .cv-ei-table th { text-align:left; font-size:12px; letter-spacing:.04em; text-transform:uppercase; color:#94a3b8; padding:12px 14px; background:#f8fafc; }
      .cv-ei-table td { padding:14px; border-top:1px solid #eef2f7; vertical-align:top; font-size:14px; }
      .cv-ei-part { font-weight:750; display:flex; align-items:center; gap:10px; }
      .cv-ei-part-copy { display:flex; flex-direction:column; min-width:0; }
      .cv-ei-meta { color:#64748b; font-size:12px; margin-top:2px; }
      .cv-pill { display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:4px 10px; font-size:12px; font-weight:750; }
      .cv-pill.high { background:#ffe4e6; color:#be123c; }
      .cv-pill.medium { background:#fef3c7; color:#b45309; }
      .cv-pill.low { background:#dcfce7; color:#15803d; }
      .cv-pill.review { background:#fef3c7; color:#b45309; }
      .cv-pill.healthy { background:#dcfce7; color:#15803d; }
      .cv-pill.risk { background:#ffe4e6; color:#be123c; }
      .cv-ei-reasons { margin:0; padding-left:16px; color:#334155; }
      .cv-ei-reasons li { margin:2px 0; }
      .cv-ei-action { color:#2563eb; font-weight:750; }
      .cv-ei-action small { display:block; color:#64748b; font-weight:500; margin-top:3px; }
      .cv-risk-wrap { background:#fff; border:1px solid #e6edf5; border-radius:16px; overflow:hidden; }
      .cv-risk-row, .cv-risk-head { display:grid; grid-template-columns: 1.1fr 1fr .9fr .6fr .7fr .8fr .6fr .7fr; gap:8px; padding:12px 16px; align-items:center; }
      .cv-risk-head { color:#94a3b8; font-size:12px; letter-spacing:.04em; text-transform:uppercase; background:#f8fafc; }
      .cv-risk-row { border-top:1px solid #eef2f7; font-size:14px; }
      .cv-risk-detail { display:grid; grid-template-columns: 1.1fr .9fr; gap:16px; padding:8px 16px 18px 42px; }
      .cv-risk-card, .cv-risk-drivers, .cv-risk-action { border:1px solid #e6edf5; border-radius:14px; padding:16px; background:#fff; }
      .cv-risk-drivers { background:#fff5f5; border-color:#fecdd3; }
      .cv-risk-action { background:#eff6ff; border-color:#bfdbfe; margin-top:12px; }
      .cv-bom-toolbar { display:flex; gap:10px; margin:8px 0 14px; }
      .cv-bom-search, .cv-bom-filter { background:#fff; border:1px solid #e6edf5; border-radius:12px; padding:10px 12px; color:#64748b; font-size:14px; }
      .cv-bom-search { flex:1; }
      @media (max-width: 900px) {
        .cv-ei-kpis, .cv-risk-detail, .cv-risk-row, .cv-risk-head { display:block; }
      }
    </style>
    """


def engineering_intelligence_html(
    *,
    bom_name: str,
    part_count: int,
    tab: str,
    parts: list[dict[str, Any]],
    alternatives: list[dict[str, Any]] | None = None,
    health_score: int | None = None,
    include_heading: bool = True,
) -> str:
    rows = _part_rows(parts)
    high = [row for row in rows if row["level"] == "High"]
    no_stock = [row for row in rows if row["stock"] <= 0]
    single = [row for row in rows if row["suppliers"] <= 1]
    health = health_score if health_score is not None else max(0, 100 - len(high) * 8)
    active = tab if tab in EI_TABS else "BOM Risk"
    banner = ""
    if active == "BOM Risk":
        banner = f"""
        <section class="cv-ei-banner">
          <div class="cv-ei-icon warn">!</div>
          <div>
            <h2>Engineering review required</h2>
            <p>{len(high)} components with high risk may impact build timelines. Review the items below and consider approved alternatives.</p>
          </div>
        </section>
        <section class="cv-ei-kpis">
          <div class="cv-ei-kpi"><div class="cv-ei-icon health">♡</div><div><span>Health</span><strong>{_esc(health)}/100</strong></div></div>
          <div class="cv-ei-kpi"><div class="cv-ei-icon review">▣</div><div><span>Needs review</span><strong>{len(high)}</strong></div></div>
          <div class="cv-ei-kpi"><div class="cv-ei-icon stock">▢</div><div><span>No-stock parts</span><strong>{len(no_stock)}</strong></div></div>
          <div class="cv-ei-kpi"><div class="cv-ei-icon source">⚭</div><div><span>Single-source</span><strong>{len(single)}</strong></div></div>
        </section>
        """
    body = _tab_body(active, rows, alternatives or [])
    heading = ""
    if include_heading:
        heading = (
            f"<p class='cv-ei-kicker'>{_esc(bom_name)} · {_esc(part_count)} components</p>"
            "<h1 class='cv-ei-title'>Engineering Intelligence</h1>"
        )
    return f"""
    <div class="cv-ei-report">
      {heading}
      {banner}
      {body}
    </div>
    """


def _tab_body(tab: str, rows: list[dict[str, Any]], alternatives: list[dict[str, Any]]) -> str:
    if tab == "Supply & Availability":
        body = "".join(
            "<tr>"
            f"<td>{_component_cell(row)}</td>"
            f"<td>{row['source']}</td><td>{row['suppliers']}</td><td>{row['stock']:,}</td>"
            f"<td>{row['lead']}</td><td>{row['lifecycle']}</td>"
            f"<td><span class='cv-pill { _level_class(row['level']) }'>{row['level']}</span></td>"
            "</tr>"
            for row in rows[:12]
        )
        return _table(
            "Supply and availability",
            "Distributor coverage, stock, and lead time from the saved analysis.",
            ["Component", "Best source", "Suppliers", "Stock", "Lead time (weeks)", "Lifecycle", "Risk"],
            body,
        )
    if tab == "Alternatives":
        photos = {row["mpn"]: row for row in rows}
        alt_rows = []
        for alt in alternatives:
            if not isinstance(alt, dict):
                continue
            original_raw = str(_first(alt, "original_part", "original_mpn", "mpn", fallback="") or "").strip()
            replacement_raw = str(_first(alt, "alternative_part", "alternative_mpn", fallback="") or "").strip()
            if not original_raw and not replacement_raw:
                continue
            original = _esc(original_raw or "—")
            replacement = _esc(replacement_raw or "—")
            maker = _esc(_first(alt, "manufacturer", "alternative_manufacturer", fallback="—"))
            reason = _esc(_first(alt, "reason", "match_reason", "notes", fallback="Saved alternative"))
            source = photos.get(original) if isinstance(photos.get(original), dict) else {}
            original_photo = str(source.get("image") or "")
            replacement_photo = str(
                _first(alt, "image_url", "photo_url", "Photo", "Image URL", "image", fallback="") or ""
            )
            alt_rows.append(
                "<tr>"
                f"<td>{_component_cell({'mpn': original, 'mpn_raw': original_raw or '—', 'image': original_photo, 'description': '', 'description_raw': source.get('description_raw') or '', 'category_raw': source.get('category_raw') or '', 'category': source.get('category_raw') or ''}, description=False)}</td>"
                f"<td>{_component_cell({'mpn': replacement, 'mpn_raw': replacement_raw or '—', 'image': replacement_photo, 'description': '', 'description_raw': str(_first(alt, 'description', 'Description', fallback='') or ''), 'category_raw': str(_first(alt, 'category', 'Category', fallback='') or ''), 'category': str(_first(alt, 'category', 'Category', fallback='') or '')}, description=False)}</td>"
                f"<td>{maker}</td><td>{reason}</td></tr>"
            )
        if not alt_rows:
            alt_rows.append(
                "<tr><td colspan='4'>No approved alternative is stored for this BOM yet. Use Find a replacement to qualify one.</td></tr>"
            )
        return _table(
            "Alternatives",
            "Replacement candidates already stored for this BOM.",
            ["Original", "Alternative", "Manufacturer", "Why it is listed"],
            "".join(alt_rows[:12]),
        )
    if tab == "Cost Insights":
        body = "".join(
            f"<tr><td>{_component_cell(row, description=False)}</td><td>{row['manufacturer']}</td><td>{row['price']}</td><td>{row['source']}</td><td><span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span></td></tr>"
            for row in rows[:12]
        )
        return _table(
            "Cost insights",
            "Unit price is shown only when the saved analysis recorded one.",
            ["Component", "Manufacturer", "Unit price", "Best source", "Risk"],
            body,
        )
    if tab == "Lifecycle":
        body = "".join(
            f"<tr><td>{_component_cell(row)}</td><td>{row['lifecycle']}</td><td>{row['manufacturer']}</td><td><span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span></td></tr>"
            for row in rows[:12]
        )
        return _table(
            "Lifecycle",
            "Lifecycle status recorded for each saved component.",
            ["Component", "Lifecycle", "Manufacturer", "Risk"],
            body,
        )
    review = [row for row in rows if row["level"] in {"High", "Medium"}][:8] or rows[:8]
    body = []
    for index, row in enumerate(review, start=1):
        reasons = "".join(f"<li>{driver}</li>" for driver in row["drivers"])
        body.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{_component_cell(row)}</td>"
            f"<td><span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span></td>"
            f"<td><ul class='cv-ei-reasons'>{reasons}</ul></td>"
            f"<td><div class='cv-ei-action'>→ {row['action']}<small>{row['action_detail']}</small></div></td>"
            "</tr>"
        )
    return _table(
        "Review these components first",
        "These components have the highest risk based on availability, supply chain, and lifecycle factors.",
        ["#", "Component", "Risk", "Key reason(s)", "Recommended action"],
        "".join(body) or "<tr><td colspan='5'>This BOM has no saved components to review.</td></tr>",
    )


def _table(title: str, copy: str, headers: list[str], body: str) -> str:
    head = "".join(f"<th>{_esc(header)}</th>" for header in headers)
    return f"""
    <section class="cv-ei-section">
      <h3>{_esc(title)}</h3>
      <p>{_esc(copy)}</p>
      <table class="cv-ei-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
    </section>
    """


def render_detailed_risk_rows(
    *,
    bom_name: str,
    analyzed_on: str,
    parts: list[dict[str, Any]],
) -> None:
    """One expanded part at a time. Each row's control is a real button."""
    import streamlit as st

    rows = _part_rows(parts)
    if "cadivor_detailed_risk_mpn" not in st.session_state:
        st.session_state["cadivor_detailed_risk_mpn"] = rows[0]["mpn_raw"] if rows else ""
    selected = str(st.session_state.get("cadivor_detailed_risk_mpn") or "")
    st.markdown(
        f"""
        <div class="cv-ei-report">
          <h1 class="cv-ei-title">Detailed Risk Report</h1>
          <p class="cv-ei-sub">{_esc(bom_name)} · {len(rows)} parts · Analyzed on {_esc(analyzed_on)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not rows:
        st.caption("This BOM has no saved components.")
        return
    header = st.columns([1.5, 1.05, 0.9, 0.55, 0.6, 0.75, 0.55, 0.7])
    for column, label in zip(
        header,
        ("MPN", "Manufacturer", "Best source", "Suppliers", "Stock", "Lifecycle", "Risk score", "Risk level"),
    ):
        column.markdown(f"<div class='cv-ap-meta'>{label}</div>", unsafe_allow_html=True)
    for index, row in enumerate(rows[:12]):
        is_open = row["mpn_raw"] == selected
        state = "open" if is_open else "shut"
        verb = "Collapse" if is_open else "Expand"
        with st.container(key=f"cv_risk_{state}_{index}"):
            cells = st.columns([1.5, 1.05, 0.9, 0.55, 0.6, 0.75, 0.55, 0.7], vertical_alignment="center")
            with cells[0]:
                st.markdown(
                    f"<div class='cv-ei-part'>{_part_art(row['mpn_raw'], row['image'], part=row)}</div>",
                    unsafe_allow_html=True,
                )
                if st.button(
                    f"{verb} {row['mpn_raw']}",
                    key=f"cv_risk_expand_{index}",
                    help=(
                        f"{verb} risk drivers and recommended action for {row['mpn_raw']}. "
                        "Press Enter or Space."
                    ),
                ):
                    st.session_state["cadivor_detailed_risk_mpn"] = "" if is_open else row["mpn_raw"]
                    st.rerun()
            cells[1].markdown(row["manufacturer"])
            cells[2].markdown(row["source"])
            cells[3].markdown(str(row["suppliers"]))
            cells[4].markdown(f"{row['stock']:,}")
            cells[5].markdown(row["lifecycle"])
            cells[6].markdown(str(row["score"]))
            cells[7].markdown(
                f"<span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span>",
                unsafe_allow_html=True,
            )
            if is_open:
                reasons = "".join(f"<li>{driver}</li>" for driver in row["drivers"])
                st.markdown(
                    f"""
                    <div class="cv-risk-detail" data-expanded-mpn="{_esc(row['mpn_raw'])}">
                      <article class="cv-risk-card">
                        <div class="cv-ei-part">{_part_art(row['mpn_raw'], row['image'], part=row)}<h3>{row['mpn']}</h3></div>
                        <p>{row['description']}</p>
                        <p>Manufacturer {row['manufacturer']}</p>
                        <p>Best source {row['source']}</p>
                        <p>Suppliers {row['suppliers']}</p>
                        <p>Stock (total) {row['stock']:,}</p>
                        <p>Lifecycle {row['lifecycle']}</p>
                      </article>
                      <div>
                        <article class="cv-risk-drivers"><h3>Risk drivers</h3><ul class="cv-ei-reasons">{reasons}</ul></article>
                        <article class="cv-risk-action"><h3>Recommended action</h3><p>{row['action']}</p><p>{row['action_detail']}</p></article>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def detailed_risk_report_html(
    *,
    bom_name: str,
    analyzed_on: str,
    parts: list[dict[str, Any]],
    expanded_mpn: str | None = None,
) -> str:
    rows = _part_rows(parts)
    expanded = expanded_mpn or (rows[0]["mpn"] if rows else "")
    body = [
        '<div class="cv-risk-head"><div>MPN</div><div>Manufacturer</div><div>Best source</div><div>Suppliers</div><div>Stock</div><div>Lifecycle</div><div>Risk score</div><div>Risk level</div></div>'
    ]
    for row in rows[:12]:
        body.append(
            "<div class='cv-risk-row'>"
            f"<div>{_component_cell(row, description=False)}</div><div>{row['manufacturer']}</div><div>{row['source']}</div>"
            f"<div>{row['suppliers']}</div><div>{row['stock']:,}</div><div>{row['lifecycle']}</div><div>{row['score']}</div>"
            f"<div><span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span></div></div>"
        )
        if row["mpn"] == expanded:
            drivers = "".join(f"<li>{driver}</li>" for driver in row["drivers"])
            body.append(
                f"""
                <div class="cv-risk-detail">
                  <article class="cv-risk-card">
                    <div class="cv-ei-part">{_part_art(row['mpn_raw'], row['image'], part=row)}<h3>{row['mpn']}</h3></div>
                    <p>{row['description']}</p>
                    <p>Manufacturer {_esc(row['manufacturer'])}</p>
                    <p>Best source {_esc(row['source'])}</p>
                    <p>Suppliers {row['suppliers']}</p>
                    <p>Stock (total) {row['stock']:,}</p>
                    <p>Lifecycle {row['lifecycle']}</p>
                  </article>
                  <div>
                    <article class="cv-risk-drivers"><h3>Risk drivers</h3><ul class="cv-ei-reasons">{drivers}</ul></article>
                    <article class="cv-risk-action"><h3>Recommended action</h3><p>{row['action']}</p><p>{row['action_detail']}</p></article>
                  </div>
                </div>
                """
            )
    return f"""
    <div class="cv-ei-report">
      <h1 class="cv-ei-title">Detailed Risk Report</h1>
      <p class="cv-ei-sub">{_esc(bom_name)} · {len(rows)} parts · Analyzed on {_esc(analyzed_on)}</p>
      <div class="cv-risk-wrap">{''.join(body)}</div>
    </div>
    """


def bom_catalog_html(records: list[dict[str, Any]]) -> str:
    body = []
    for record in records[:12]:
        name = _esc(_first(record, "project_name", "name", fallback="Saved BOM"))
        filename = _esc(_first(record, "filename", "file_name", fallback="—"))
        parts = _num(_first(record, "total_parts", "parts"))
        health = _num(_first(record, "health_score"))
        high = _num(_first(record, "high_risk_count"))
        updated = _esc(_first(record, "updated_label", "created_at", fallback="—"))
        if high >= 20 or health < 55:
            pill, label = "risk", "At risk"
        elif high >= 5 or health < 80:
            pill, label = "review", "Review"
        else:
            pill, label = "healthy", "Healthy"
        body.append(
            "<tr>"
            f"<td><div class='cv-ei-part'>{name}</div></td>"
            f"<td>{filename}</td><td>{parts}</td>"
            f"<td><span class='cv-pill {pill}'>{label}</span></td>"
            f"<td>{high}</td><td>{updated}</td><td>Open</td>"
            "</tr>"
        )
    if not body:
        body.append("<tr><td colspan='7'>No saved BOMs in this workspace yet.</td></tr>")
    return f"""
    <div class="cv-ei-report">
      <h1 class="cv-ei-title">BOMs</h1>
      <div class="cv-bom-toolbar"><div class="cv-bom-search">Search BOMs, projects, or files</div><div class="cv-bom-filter">All projects</div><div class="cv-bom-filter">All health</div><div class="cv-bom-filter">Last 90 days</div></div>
      <table class="cv-ei-table"><thead><tr><th>Project</th><th>File</th><th>Parts</th><th>Health</th><th>High risk</th><th>Last analyzed</th><th></th></tr></thead><tbody>{''.join(body)}</tbody></table>
    </div>
    """


def render_engineering_intelligence_report(
    *,
    analysis: dict[str, Any],
    parts: list[dict[str, Any]],
    alternatives: list[dict[str, Any]] | None,
    health_score: int | None,
) -> None:
    import streamlit as st

    if hasattr(st, "html"):
        st.html(report_styles())
    else:
        st.markdown(report_styles(), unsafe_allow_html=True)
    bom_name = str(analysis.get("project_name") or analysis.get("filename") or "Saved BOM")
    detailed = bool(st.session_state.get("cadivor_show_detailed_risk"))
    tab = str(st.session_state.get("cadivor_ei_report_tab") or "BOM Risk")
    if not detailed:
        title_col, tab_col = st.columns([1.2, 1.4], vertical_alignment="center")
        with title_col:
            st.markdown(
                f"<div class='cv-ap'><p class='cv-ap-kicker'>{html.escape(bom_name)} · {len(parts or [])} components</p>"
                "<h1>Engineering Intelligence</h1></div>",
                unsafe_allow_html=True,
            )
        with tab_col:
            with st.container(key="cv_ei_report_tabs"):
                tab_buttons = st.columns(len(EI_TABS))
                for column, name in zip(tab_buttons, EI_TABS):
                    slug = name.casefold().replace(" ", "-").replace("&", "and")
                    if column.button(
                        name,
                        key=f"ei_tab_{slug}",
                        type="tertiary",
                    ):
                        st.session_state["cadivor_ei_report_tab"] = name
                        st.rerun()
            active_slug = str(tab or "BOM Risk").casefold().replace(" ", "-").replace("&", "and")
            st.markdown(
                f"""
                <style>
                html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs .stButton:not(.st-key-cv_foundation_navigation .stButton):not(.st-key-cv_analysis_section_nav .stButton):not(.st-key-cv_analysis_section_nav *):not([class*="st-key-cadivor_bom_tab_"]):not(.st-key-cv_saved_bom_nav_more .stButton) > button,
                html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs .stButton:not(.st-key-cv_foundation_navigation .stButton):not(.st-key-cv_analysis_section_nav .stButton):not(.st-key-cv_analysis_section_nav *):not([class*="st-key-cadivor_bom_tab_"]):not(.st-key-cv_saved_bom_nav_more .stButton) > button *{{
                  background:transparent!important;background-color:transparent!important;
                  border:0!important;border-radius:0!important;box-shadow:none!important;color:#64748b!important;min-height:0!important
                }}
                html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs [class*="st-key-ei_tab_{active_slug}"].stButton:not(.st-key-cv_foundation_navigation .stButton):not(.st-key-cv_analysis_section_nav .stButton):not(.st-key-cv_analysis_section_nav *):not([class*="st-key-cadivor_bom_tab_"]):not(.st-key-cv_saved_bom_nav_more .stButton) > button,
                html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs [class*="st-key-ei_tab_{active_slug}"].stButton:not(.st-key-cv_foundation_navigation .stButton):not(.st-key-cv_analysis_section_nav .stButton):not(.st-key-cv_analysis_section_nav *):not([class*="st-key-cadivor_bom_tab_"]):not(.st-key-cv_saved_bom_nav_more .stButton) > button *{{
                  color:#1d4ed8!important;background:transparent!important;background-color:transparent!important;
                  box-shadow:inset 0 -2px 0 #2563eb!important;border-radius:0!important
                }}
                </style>
                """,
                unsafe_allow_html=True,
            )
    if st.session_state.get("cadivor_show_detailed_risk"):
        if st.button("Back to Engineering Intelligence", key="ei_back_from_detailed_risk"):
            st.session_state["cadivor_show_detailed_risk"] = False
            st.rerun()
        analyzed = str(analysis.get("created_at") or "saved analysis")
        render_detailed_risk_rows(
            bom_name=bom_name,
            analyzed_on=analyzed,
            parts=parts or [],
        )
        try:
            from src.ui.approved_pages import excel_bytes

            st.download_button(
                "Download Excel Report",
                data=excel_bytes(parts or []),
                file_name="detailed-risk-report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="approved_detailed_risk_excel",
            )
        except Exception:
            st.caption("Excel export is unavailable for this analysis.")
        return
    st.markdown(
        engineering_intelligence_html(
            bom_name=bom_name,
            part_count=len(parts or []),
            tab=str(tab or "BOM Risk"),
            parts=parts or [],
            alternatives=alternatives or [],
            health_score=health_score,
            include_heading=False,
        ),
        unsafe_allow_html=True,
    )
    if st.button("Open detailed risk report", key="ei_open_detailed_risk"):
        st.session_state["cadivor_show_detailed_risk"] = True
        st.rerun()
