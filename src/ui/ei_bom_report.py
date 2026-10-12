"""Approved Engineering Intelligence and BOM-list layouts.

Mockup #16 is the visual system for the Engineering Intelligence report.
BOM Risk is the pictured tab. Supply & Availability, Alternatives, Cost
Insights, and Lifecycle use that same page chrome with the analysis data
already loaded for the saved BOM. Mockup #15 is the expandable detailed
risk report. Mockup #2 is the BOM catalog.
"""

from __future__ import annotations

import html
import re
import textwrap
from typing import Any


from html.parser import HTMLParser


class _DescriptionTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style"}:
            self._skip_depth += 1
        elif tag.casefold() in {"p", "div", "li", "br"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag.casefold() in {"p", "div", "li", "br"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _description_text(value: Any) -> str:
    """Decode supplier markup safely and discard serialized analysis fields."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    # Records may have been HTML escaped more than once before they were saved.
    for _ in range(16):
        decoded = html.unescape(raw)
        if decoded == raw:
            break
        raw = decoded
    parser = _DescriptionTextParser()
    try:
        parser.feed(raw)
        text = " ".join(" ".join(parser.parts).split())
    except Exception:
        text = " ".join(re.sub(r"(?is)<[^>]*>", " ", raw).split())
    structured_labels = ("manufacturer", "best source", "supplier", "suppliers", "stock", "lifecycle")
    if sum(bool(re.search(rf"\b{label}\b", text, re.IGNORECASE)) for label in structured_labels) >= 2:
        return ""
    if re.match(r"^(?:manufacturer|best source|suppliers?|stock(?:\s+(?:total|available))?|lifecycle)\s*(?::|=|\s)", text, re.IGNORECASE):
        return ""
    return text


def _alternative_action_link(
    row: dict[str, Any],
    *,
    analysis_id: str = "",
    bom_name: str = "",
    source_page: str,
) -> str:
    label = str(row.get("action") or "")
    if row.get("level") not in {"High", "Medium"}:
        return label
    from src.ui.navigation import alternative_finder_href

    href = alternative_finder_href(
        mpn=str(row.get("mpn_raw") or ""),
        manufacturer=html.unescape(str(row.get("manufacturer") or "")),
        description=html.unescape(str(row.get("description") or "")),
        lifecycle=html.unescape(str(row.get("lifecycle") or "")),
        risk=str(row.get("level") or ""),
        analysis_id=analysis_id,
        return_analysis_id=analysis_id,
        source_page=source_page,
        project_name=bom_name,
        bom_name=bom_name,
    )
    return (
        f'<a class="cv-ei-action-link" href="{html.escape(href, quote=True)}" '
        f'target="_self">{label}</a>'
    )




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
    if description and str(row.get("description_raw") or "").strip():
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


def _select_ei_report_tab(tab: str) -> None:
    """Set the report tab in the button callback before content is rendered."""
    import streamlit as st

    if tab in EI_TABS:
        st.session_state["cadivor_ei_report_tab"] = tab


def _esc(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return fallback
    return html.escape(text)


def _ei_tab_indicator_html(tab: str) -> str:
    """Render an explicit underline at the selected Engineering Intelligence tab."""
    active = tab if tab in EI_TABS else EI_TABS[0]
    cells = "".join(
        "<span class='cv-ei-tab-indicator-cell is-active'></span>"
        if name == active
        else "<span class='cv-ei-tab-indicator-cell'></span>"
        for name in EI_TABS
    )
    return (
        "<div class='cv-ei-tab-indicator-track' role='img' "
        f"aria-label='Selected tab: {html.escape(active)}'>{cells}</div>"
    )


def _num(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _recorded_number(value: Any) -> float | None:
    """A saved number. Zero and blanks are missing defaults, not a real measurement."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _positive_price(part: dict[str, Any]) -> float | None:
    raw = _first(part, "unit_price", "Unit Price", "price", "best_price")
    number = _recorded_number(raw)
    if number is None or number <= 0:
        return None
    return number


def _positive_quantity(part: dict[str, Any]) -> float | None:
    raw = _first(part, "quantity", "Quantity", "qty", "required_quantity")
    number = _recorded_number(raw)
    if number is None or number <= 0:
        return None
    return number


def _money(amount: float) -> str:
    return f"${amount:,.4f}".rstrip("0").rstrip(".")


def _source_name(part: dict[str, Any]) -> str:
    return str(
        _first(
            part,
            "primary_supplier",
            "best_source",
            "Best Source",
            "supplier",
            "distributor",
            fallback="",
        )
        or ""
    ).strip()


def _source_url(part: dict[str, Any]) -> str:
    for key in (
        "product_url",
        "Product URL",
        "product_detail_url",
        "source_url",
        "datasheet_url",
        "Datasheet URL",
    ):
        text = str(part.get(key) or "").strip()
        if text.startswith("https://") or text.startswith("http://"):
            return text
    return ""


def _risk_reason(part: dict[str, Any]) -> str:
    return str(
        _first(part, "risk_reasons", "Risk Reasons", "risk_reason", fallback="") or ""
    ).strip()


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


def _cost_cells(part: dict[str, Any]) -> dict[str, str]:
    """Cost columns from saved fields only. A zero price is a missing default."""
    from src.saved_bom_cost import distributor_comparison, extended_cost, normalize_saved_offers

    price = _positive_price(part)
    quantity = _positive_quantity(part)
    name = _source_name(part)
    url = _source_url(part)
    stock = _recorded_number(_first(part, "stock_available", "Stock Available", "stock"))
    mpn = str(_first(part, "mpn", "MPN", "part_number", fallback="") or "")
    offers = normalize_saved_offers(
        part.get("supplier_offers") or part.get("Supplier Offers"),
        mpn=mpn,
    )
    comparison = distributor_comparison(offers, mpn=mpn, bom_quantity=quantity)
    price_html = _esc(_money(price)) if price is not None else "Not recorded"
    link = ""
    if url:
        link = (
            f'<a href="{html.escape(url, quote=True)}" rel="noopener noreferrer">'
            "Product page</a>"
        )
    elif name or price is not None:
        link = "<small>Product URL was not saved.</small>"
    savings = comparison["savings_per_unit"]
    if savings is not None:
        break_quantity = float(comparison["break_quantity"])
        savings_note = (
            f"<small>Savings of {_esc(_money(savings))} per unit versus "
            f"{_esc(comparison['higher_distributor'])} "
            f"{_esc(_money(comparison['higher_price']))} "
            f"at quantity {_esc(f'{break_quantity:g}')} "
            f"{_esc(comparison['currency'])}. "
            f"The {_esc(comparison['lower_distributor'])} price is "
            f"{_esc(_money(comparison['lower_price']))}.</small>"
        )
    elif offers:
        savings_note = f"<small>{_esc(comparison['message'])}</small>"
    elif name and price is not None:
        savings_note = "<small>A distributor comparison is unavailable.</small>"
    else:
        savings_note = ""
    refresh = (
        "<small>Re-run the BOM analysis to save a missing distributor, unit price, "
        "BOM quantity, or product URL when the supplier or the BOM file returns it.</small>"
    )
    if name and price is not None:
        details = [f"<small>{price_html}</small>"]
        if stock is not None:
            details.append(f"<small>Stock {int(stock):,}</small>")
        if link:
            details.append(link)
        details.append("<small>Recorded offer.</small>")
        for offer in offers[:8]:
            bits = [str(offer["distributor"]), _money(float(offer["unit_price"]))]
            if offer.get("currency"):
                bits.append(str(offer["currency"]))
            if offer.get("price_break_quantity") is not None:
                bits.append(f"from {float(offer['price_break_quantity']):g}")
            if offer.get("stock") is not None:
                bits.append(f"stock {int(offer['stock']):,}")
            if offer.get("retrieved_at"):
                bits.append(f"retrieved {offer['retrieved_at']}")
            line = _esc(" · ".join(bits))
            if offer.get("product_url"):
                line += (
                    f' <a href="{html.escape(offer["product_url"], quote=True)}" '
                    'rel="noopener noreferrer">Product page</a>'
                )
            details.append(f"<small>{line}</small>")
        details.append(savings_note)
        source_html = f"<strong>{_esc(name)}</strong>{''.join(details)}"
    elif name:
        source_html = (
            f"<strong>{_esc(name)}</strong>"
            "<small>Distributor was saved. Unit price was not saved, so this is not a comparable offer.</small>"
            + link
            + savings_note
            + refresh
        )
    else:
        stock_note = (
            f" Recorded stock is {int(stock):,}."
            if stock is not None
            else ""
        )
        source_html = (
            "Not recorded"
            "<small>Distributor was not saved."
            f"{html.escape(stock_note)}</small>"
            + savings_note
            + refresh
        )
    total = extended_cost(price, quantity)
    if total is not None:
        extended_html = (
            f"{_esc(_money(total))}"
            f"<small>{price_html} × {_esc(f'{quantity:g}')} recorded</small>"
        )
    else:
        missing = []
        if price is None:
            missing.append("unit price")
        if quantity is None:
            missing.append("BOM quantity")
        joined = " and ".join(missing)
        verb = "was" if len(missing) == 1 else "were"
        extended_html = (
            "Not calculated"
            f"<small>{_esc(joined)} {verb} not saved. Extended cost needs both. "
            "Re-run the BOM analysis to save a missing unit price or BOM quantity "
            "when the supplier or the BOM file returns it.</small>"
        )
    return {
        "cost_price": price_html,
        "cost_source": source_html,
        "cost_extended": extended_html,
    }


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
                "description_raw": _description_text(
                    _first(part, "description_raw", "description", "Description", "part_description", fallback="")
                ),
                "category_raw": str(
                    _first(part, "category_raw", "category", "Category", "device_type", "architecture", fallback="") or ""
                ),
                "package": str(
                    _first(
                        part, "package", "package_type", "package type", "Package",
                        "Package Type", "package_case", "case_package", "case",
                        fallback="",
                    ) or ""
                ),
                "mounting_type": str(
                    _first(part, "mounting_type", "mounting type", "mount_type", "mounting", fallback="") or ""
                ),
                "through_hole": _first(part, "through_hole", "is_through_hole", "tht", "is_tht", fallback=""),
                "surface_mount": _first(part, "surface_mount", "is_surface_mount", "smd", "smt", fallback=""),
                "description": _esc(
                    _description_text(
                        _first(part, "description_raw", "description", "Description", "part_description", fallback="Component")
                    ) or "Component"
                ),
                "manufacturer": _esc(_first(part, "manufacturer", "Manufacturer", fallback="—")),
                "level": level,
                "score": _num(_first(part, "risk_score", "Risk Score")),
                "stock": _num(_first(part, "stock_available", "Stock Available", "stock"), 0),
                "suppliers": _num(_first(part, "supplier_count", "Supplier Count"), 0),
                "lifecycle": _esc(_first(part, "lifecycle_status", "Lifecycle Status", fallback="Unknown")),
                "lead": _esc(_first(part, "lead_time_weeks", "Lead Time Weeks", fallback="—")),
                "source": _esc(
                    _first(
                        part,
                        "primary_supplier",
                        "best_source",
                        "Best Source",
                        "distributor",
                        fallback="—",
                    )
                ),
                "price": _esc(_first(part, "unit_price", "Unit Price", "price", fallback="—")),
                "risk_reason": _esc(_risk_reason(part)),
                **_cost_cells(part),
                "image": str(
                    _first(
                        part,
                        "image_url",
                        "photo_url",
                        "Photo",
                        "Image URL",
                        "image",
                        "PrimaryPhoto",
                        "PhotoUrl",
                        "photoUrl",
                        "ImageURL",
                        "ImageUrl",
                        "product_image_url",
                        "primary_image_url",
                        "supplier_image_url",
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
      .st-key-ei_report_workspace { width:100%!important;max-width:100%!important;margin-inline:auto!important;box-sizing:border-box;min-width:0!important }
      .st-key-ei_report_workspace .cv-ei-report { color:#0f172a; font-family: Inter, "Segoe UI", sans-serif; width:100%;max-width:100%;margin:0 auto;box-sizing:border-box;min-width:0 }
      .st-key-ei_report_workspace .cv-ap { color:#0f172a; font-family:Inter, "Segoe UI", sans-serif; margin:0 0 2px; }
      .st-key-ei_report_workspace .cv-ap-kicker { margin:0 0 6px; color:#64748b; font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
      .st-key-ei_report_workspace .cv-ap h1 { margin:0 0 6px; color:#0f172a; font-size:32px; font-weight:760; line-height:1.15; letter-spacing:-.03em; }
      .st-key-ei_report_workspace .cv-ei-title { font-size:30px; }
      .st-key-ei_report_workspace .cv-ei-section { min-width:0; margin:0 0 18px; overflow:hidden; background:#fff; border:1px solid #cbd8e8; border-radius:16px; box-shadow:0 3px 12px rgba(15,23,42,.045); }
      .cv-ei-section-heading { box-sizing:border-box; padding:18px 22px 14px; }
      .cv-ei-section-heading > h3 { margin:0!important; padding:0!important; color:#0f172a; font-size:19px!important; line-height:1.25; font-weight:750; letter-spacing:-.02em; }
      .cv-ei-section-heading > p { margin:6px 0 0!important; padding:0!important; color:#64748b; font-size:13px!important; line-height:1.5; }
      .cv-ei-section-heading > .cv-ei-data-note { margin-top:7px!important; color:#64748b; font-size:12px!important; line-height:1.4; }
      .st-key-ei_report_workspace .cv-ei-table-wrap { width:100%;max-width:100%;overflow-x:auto;border-radius:0 0 15px 15px;overscroll-behavior-inline:contain; }
      .st-key-ei_report_workspace .cv-ei-table { min-width:760px; border:0; border-radius:0; }
      .st-key-ei_report_workspace .cv-ei-table th { color:#64748b; background:#f7f9fc; border-top:1px solid #e5ebf3; border-bottom:1px solid #dce4ef; vertical-align:middle; }
      .st-key-ei_report_workspace .cv-ei-table td { vertical-align:middle; }
      .st-key-cv_ei_report_tabs { width:100%;max-width:100%;margin:8px 0 18px;min-width:0; }
      html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs [data-testid="stHorizontalBlock"] {
        flex-wrap:wrap!important;align-items:flex-end!important;justify-content:flex-start!important;gap:4px 10px!important;width:100%!important;
        border-bottom:1px solid #e5e7eb!important;padding-bottom:0!important
      }
      html body section[data-testid="stMain"] .st-key-cv_ei_report_tabs [data-testid="stHorizontalBlock"]>[data-testid="column"] {
        flex:0 0 auto!important;width:auto!important;min-width:0!important;max-width:100%!important
      }
      .cv-part-photo[data-illustration="generic"]{background:#f0f9ff;border-color:#bae6fd;color:#0369a1}
      .cv-ei-kicker { color:#64748b; font-size:13px; font-weight:600; margin:0 0 6px; }
      .cv-ei-title { font-size:32px; line-height:1.15; font-weight:760; letter-spacing:-.03em; margin:0; }
      .cv-ei-sub { color:#64748b; font-size:14px; margin:6px 0 18px; }
      .cv-ei-banner { display:flex; gap:16px; align-items:flex-start; background:#fff5f5; border:1px solid #fecdd3; border-radius:16px; padding:22px 24px; margin-bottom:16px; }
      .cv-ei-banner--clear { background:#f0fdf4; border-color:#bbf7d0; }
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
      .cv-ei-part { font-weight:750; display:flex; flex-direction:row; align-items:center; gap:10px; }
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
      .cv-ei-action-link{display:inline-flex;align-items:center;color:#2563eb;text-decoration:none;font-weight:800}
      .cv-ei-action-link:hover{text-decoration:underline;text-underline-offset:3px}
      .cv-ei-action small { display:block; color:#64748b; font-weight:500; margin-top:3px; }
      .cv-ei-action .cv-ei-approved,.cv-ei-approved{display:inline-flex;align-items:center;width:max-content;max-width:100%;margin-top:6px;padding:4px 8px;border:1px solid #bbf7d0;border-radius:999px;background:#f0fdf4;color:#15803d;font-size:11px;font-weight:750;line-height:1.3}
      .cv-ei-tab-indicator-track{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0;width:100%;height:4px;margin:0 0 12px;border-bottom:1px solid #e2e8f0}
      .cv-ei-tab-indicator-cell{display:block;height:3px}
      .cv-ei-tab-indicator-cell.is-active{background:#2563eb;border-radius:3px 3px 0 0}
      .cv-ei-refresh-card{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:14px 16px;margin:0 0 16px;border:1px solid #dbeafe;border-radius:14px;background:#f8fbff}
      .cv-ei-refresh-card strong{display:block;color:#1e3a8a;font-size:14px}
      .cv-ei-refresh-card p{margin:3px 0 0;color:#475569;font-size:12px;line-height:1.45}
      .cv-ei-table td small, .cv-ei-offer a { display:block; margin-top:4px; color:#64748b; font-size:12px; font-weight:500; line-height:1.35; }
      .cv-ei-offer a { color:#2563eb; font-size:12px; font-weight:650; }
      [class*="st-key-cv_risk_expand_"] button { background:transparent !important; border:0 !important; box-shadow:none !important; color:#0f172a !important; font-weight:750 !important; padding:0 !important; min-height:0 !important; height:auto !important; justify-content:flex-start !important; text-align:left !important; }
      .cv-risk-wrap { background:#fff; border:1px solid #e6edf5; border-radius:16px; overflow:hidden; }
      .cv-risk-row, .cv-risk-head { display:grid; grid-template-columns: 1.1fr 1fr .9fr .6fr .7fr .8fr .6fr .7fr; gap:8px; padding:12px 16px; align-items:center; }
      .cv-risk-head { color:#94a3b8; font-size:12px; letter-spacing:.04em; text-transform:uppercase; background:#f8fafc; }
      .cv-risk-row { border-top:1px solid #eef2f7; font-size:14px; }
      .cv-risk-grid-head { background:#f1f5f9;border:1px solid #e2e8f0;border-radius:8px;padding:9px 10px;color:#64748b;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;min-height:34px;box-sizing:border-box }
      .st-key-ei_report_workspace [class*="st-key-cv_risk_shut_"], .st-key-ei_report_workspace [class*="st-key-cv_risk_open_"] { border-bottom:1px solid #e8edf3;padding:5px 0 }
      .cv-risk-detail { display:grid; grid-template-columns:1.1fr .9fr; gap:16px; padding:14px 0 18px; }
      .cv-risk-card, .cv-risk-drivers, .cv-risk-action { border:1px solid #e6edf5; border-radius:14px; padding:16px; background:#fff; }
      .cv-risk-drivers { background:#fff5f5; border-color:#fecdd3; }
      .cv-risk-action { background:#eff6ff; border-color:#bfdbfe; margin-top:12px; }
      .cv-bom-toolbar { display:flex; gap:10px; margin:8px 0 14px; }
      .cv-bom-search, .cv-bom-filter { background:#fff; border:1px solid #e6edf5; border-radius:12px; padding:10px 12px; color:#64748b; font-size:14px; }
      .cv-bom-search { flex:1; }
      @media (max-width: 900px) {
        .st-key-ei_report_workspace .cv-ap h1 { font-size:26px; }
        .st-key-ei_report_workspace .cv-ei-title { font-size:26px; }
        .cv-ei-section-heading { padding:16px; }
        .cv-ei-section-heading > h3 { font-size:17px!important; }
        .cv-ei-section-heading > p { font-size:12px!important; }
        .cv-ei-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); }
        .cv-risk-row, .cv-risk-head { display:block; }
        .cv-risk-detail { grid-template-columns:1fr; padding:12px 0; }
        .cv-risk-grid-head { font-size:10px;padding:8px 5px }
      }
      @media (max-width: 600px) {
        .st-key-ei_report_workspace .cv-ap h1 { font-size:23px; }
        .st-key-ei_report_workspace .cv-ei-title { font-size:23px; }
        .st-key-ei_report_workspace .cv-ei-kpis { grid-template-columns:1fr; }
        .st-key-ei_report_workspace .cv-ei-section { border-radius:13px; }
        .cv-ei-section-heading { padding:14px 13px 12px; }
        .st-key-cv_ei_report_tabs button { white-space:normal!important;text-align:left!important; }
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
    analysis_id: str = "",
    approved_alternatives: list[dict[str, Any]] | None = None,
) -> str:
    rows = _part_rows(parts)
    high = [row for row in rows if row["level"] == "High"]
    no_stock = [row for row in rows if row["stock"] <= 0]
    single = [row for row in rows if row["suppliers"] <= 1]
    health = health_score if health_score is not None else max(0, 100 - len(high) * 8)
    active = tab if tab in EI_TABS else "BOM Risk"
    banner = ""
    if active == "BOM Risk":
        # Keep these tags at column 0. Indented HTML becomes a Markdown code
        # block, which is what left the summary looking like an empty banner.
        if high:
            banner = textwrap.dedent(
                f"""
                <section class="cv-ei-banner">
                  <div class="cv-ei-icon warn">!</div>
                  <div>
                    <h2>Engineering review required</h2>
                    <p>{len(high)} components with high risk may impact build timelines. Review the items below and consider approved alternatives.</p>
                  </div>
                </section>
                """
            ).strip()
        else:
            banner = textwrap.dedent(
                """
                <section class="cv-ei-banner cv-ei-banner--clear">
                  <div class="cv-ei-icon health">✓</div>
                  <div>
                    <h2>No high-risk components found</h2>
                    <p>This BOM has no components currently classified as high risk. Review the component data and monitoring signals as they change.</p>
                  </div>
                </section>
                """
            ).strip()
        banner += textwrap.dedent(
            f"""
            <section class="cv-ei-kpis">
              <div class="cv-ei-kpi"><div class="cv-ei-icon health">♡</div><div><span>Health</span><strong>{_esc(health)}/100</strong></div></div>
              <div class="cv-ei-kpi"><div class="cv-ei-icon review">▣</div><div><span>Needs review</span><strong>{len(high)}</strong></div></div>
              <div class="cv-ei-kpi"><div class="cv-ei-icon stock">▢</div><div><span>No-stock parts</span><strong>{len(no_stock)}</strong></div></div>
              <div class="cv-ei-kpi"><div class="cv-ei-icon source">⚭</div><div><span>Single-source</span><strong>{len(single)}</strong></div></div>
            </section>
            """
        ).strip()
    body = textwrap.dedent(
        _tab_body(
            active,
            rows,
            alternatives or [],
            analysis_id=analysis_id,
            bom_name=bom_name,
            approved_alternatives=approved_alternatives or [],
        )
    ).strip()
    heading = ""
    if include_heading:
        heading = (
            f"<p class='cv-ei-kicker'>{_esc(bom_name)} · {_esc(part_count)} components</p>"
            "<h1 class='cv-ei-title'>Engineering Intelligence</h1>"
        )
    return (
        '<div class="cv-ei-report">'
        + heading
        + banner
        + body
        + "</div>"
    )


def _tab_body(
    tab: str,
    rows: list[dict[str, Any]],
    alternatives: list[dict[str, Any]],
    *,
    analysis_id: str = "",
    bom_name: str = "",
    approved_alternatives: list[dict[str, Any]] | None = None,
) -> str:
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
            "Distributor coverage, stock, and lead time recorded in the saved analysis.",
            ["Component", "Best source", "Suppliers", "Stock", "Lead time (weeks)", "Lifecycle", "Risk"],
            body,
        )
    if tab == "Alternatives":
        photos = {row["mpn_raw"]: row for row in rows}
        from src.approved_alternatives import report_alternative

        approved_rows = []
        for record in approved_alternatives or []:
            if not isinstance(record, dict):
                continue
            approved = report_alternative(record)
            original_raw = str(approved.get("original_part") or "").strip()
            replacement_raw = str(approved.get("alternative_part") or "").strip()
            if not original_raw or not replacement_raw:
                continue
            original = photos.get(original_raw) or {}
            approved_rows.append(
                "<tr>"
                f"<td>{_component_cell({'mpn': _esc(original_raw), 'mpn_raw': original_raw, 'image': original.get('image') or '', 'description': '', 'description_raw': '', 'category_raw': '', 'category': ''}, description=False)}</td>"
                f"<td>{_component_cell({'mpn': _esc(replacement_raw), 'mpn_raw': replacement_raw, 'image': approved.get('image_url') or '', 'description': '', 'description_raw': '', 'category_raw': '', 'category': ''}, description=False)}</td>"
                f"<td>{_esc(approved.get('manufacturer') or '—')}</td>"
                f"<td><span class='cv-ei-approved'>Approved</span><small>{_esc(approved.get('reason') or '')}</small></td>"
                "</tr>"
            )
        approved_section = _table(
            "Approved alternatives",
            "Replacement decisions recorded by your engineering team for this BOM.",
            ["Original component", "Approved replacement", "Manufacturer", "Approval record"],
            "".join(approved_rows) or "<tr><td colspan='4'>No approved alternative is recorded for this BOM yet.</td></tr>",
        )
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
            source = photos.get(original_raw) if isinstance(photos.get(original_raw), dict) else {}
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
                "<tr><td colspan='4'>No supplier alternatives were returned in the saved analysis.</td></tr>"
            )
        return approved_section + _table(
            "Search candidates",
            "Supplier candidates returned by the saved analysis. They are not approved until your team records that decision.",
            ["Original", "Candidate", "Manufacturer", "Why it is listed"],
            "".join(alt_rows[:12]),
        )
    if tab == "Cost Insights":
        if not rows:
            body = "<tr><td colspan='6'>No saved components are available for a cost decision.</td></tr>"
        else:
            body = "".join(
                "<tr>"
                f"<td>{_component_cell(row, description=False)}</td>"
                f"<td>{row['manufacturer']}</td>"
                f"<td>{row['cost_price']}</td>"
                f"<td class='cv-ei-offer'>{row['cost_source']}</td>"
                f"<td>{row['cost_extended']}</td>"
                f"<td><span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span>"
                f"<small class='cv-ei-reason'>{row['risk_reason'] or 'No saved risk reason was stored for this rating.'}</small></td>"
                "</tr>"
                for row in rows[:12]
            )
        return _table(
            "Cost insights",
            "Values come from the saved analysis. Extended cost needs both a recorded unit price and BOM quantity; distributor savings appear only when saved offers are comparable at that quantity. Offers are evidence, not a ranked recommendation.",
            ["Component", "Manufacturer", "Unit price", "Recorded source", "Extended cost", "Risk"],
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
    from src.approved_alternatives import approved_mpn_map, part_key

    approved_by_part = approved_mpn_map(approved_alternatives or [])
    review = [row for row in rows if row["level"] in {"High", "Medium"}][:8] or rows[:8]
    body = []
    for index, row in enumerate(review, start=1):
        reasons = "".join(f"<li>{driver}</li>" for driver in row["drivers"])
        approvals = approved_by_part.get(part_key(row.get("mpn_raw")), [])
        approval_note = "".join(
            f"<small class='cv-ei-approved'>Approved alternative: {_esc(item.get('alternative_part') or '')}</small>"
            for item in approvals
        )
        body.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{_component_cell(row)}</td>"
            f"<td><span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span></td>"
            f"<td><ul class='cv-ei-reasons'>{reasons}</ul></td>"
            f"<td><div class='cv-ei-action'>{_alternative_action_link(row, analysis_id=analysis_id, bom_name=bom_name, source_page='engineering_intelligence_review')}<small>{row['action_detail']}</small>{approval_note}</div></td>"
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
      <div class="cv-ei-section-heading">
        <h3>{_esc(title)}</h3>
        <p>{_esc(copy)}</p>
        <p class="cv-ei-data-note">Saved analysis snapshot. Re-run this BOM analysis to refresh stock, lead time, and lifecycle data.</p>
      </div>
      <div class="cv-ei-table-wrap" role="region" aria-label="{_esc(title)} table" tabindex="0">
        <table class="cv-ei-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
      </div>
    </section>
    """


def render_detailed_risk_rows(
    *,
    bom_name: str,
    analyzed_on: str,
    parts: list[dict[str, Any]],
    analysis_id: str = "",
    approved_alternatives: list[dict[str, Any]] | None = None,
) -> None:
    """Render a compact risk table with user-controlled, one-row details."""
    import streamlit as st

    rows = _part_rows(parts)
    from src.approved_alternatives import approved_mpn_map, part_key

    approved_by_part = approved_mpn_map(approved_alternatives or [])
    selection_key = f"cadivor_detailed_risk_mpn_{analysis_id or bom_name}"
    if selection_key not in st.session_state:
        st.session_state[selection_key] = ""
    selected = str(st.session_state.get(selection_key) or "")
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

    widths = [2.2, 1.1, 1.45, 1.15, 0.9]
    header = st.columns(widths, vertical_alignment="center")
    for column, label in zip(header, ("Component", "Manufacturer", "Supply", "Lifecycle", "Risk")):
        column.markdown(f"<div class='cv-risk-grid-head'>{label}</div>", unsafe_allow_html=True)

    for index, row in enumerate(rows[:12]):
        is_open = row["mpn_raw"] == selected
        state = "open" if is_open else "shut"
        with st.container(key=f"cv_risk_{state}_{index}"):
            cells = st.columns(widths, vertical_alignment="center")
            with cells[0]:
                art_col, name_col = st.columns([0.38, 1.62], vertical_alignment="center")
                art_col.markdown(
                    f"<div class='cv-ei-part'>{_part_art(row['mpn_raw'], row['image'], part=row)}</div>",
                    unsafe_allow_html=True,
                )
                with name_col:
                    if st.button(
                        row["mpn_raw"],
                        key=f"cv_risk_expand_{index}",
                        help=f"Show risk drivers and the recommended action for {row['mpn_raw']}.",
                    ):
                        st.session_state[selection_key] = "" if is_open else row["mpn_raw"]
                        st.rerun()
                    if str(row.get("description_raw") or "").strip():
                        name_col.markdown(
                            f"<div class='cv-ei-meta'>{row['description']}</div>",
                            unsafe_allow_html=True,
                        )
                    for approved in approved_by_part.get(part_key(row.get("mpn_raw")), []):
                        name_col.markdown(
                            f"<span class='cv-ei-approved'>Approved alternative: {_esc(approved.get('alternative_part') or '')}</span>",
                            unsafe_allow_html=True,
                        )
            cells[1].markdown(row["manufacturer"])
            cells[2].markdown(
                f"<strong>{row['source']}</strong>"
                f"<div class='cv-ei-meta'>{row['suppliers']} supplier(s) · {row['stock']:,} in stock</div>",
                unsafe_allow_html=True,
            )
            cells[3].markdown(row["lifecycle"])
            cells[4].markdown(
                f"<span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span>"
                f"<div class='cv-ei-meta'>Score {row['score']}</div>",
                unsafe_allow_html=True,
            )
            if is_open:
                reasons = "".join(f"<li>{driver}</li>" for driver in row["drivers"])
                alternative_link = _alternative_action_link(
                    row,
                    analysis_id=analysis_id,
                    bom_name=bom_name,
                    source_page="detailed_risk_report",
                )
                recorded_description = (
                    f"<p>{row['description']}</p>"
                    if str(row.get("description_raw") or "").strip()
                    else ""
                )
                st.markdown(
                    f"""
                    <div class="cv-risk-detail" data-expanded-mpn="{_esc(row['mpn_raw'])}">
                      <article class="cv-risk-card">
                        <div class="cv-ei-part">{_part_art(row['mpn_raw'], row['image'], part=row)}<span class="cv-ei-part-copy"><h3>{row['mpn']}</h3></span></div>
                        {recorded_description}
                        <p><strong>Manufacturer</strong> {row['manufacturer']}</p>
                        <p><strong>Best source</strong> {row['source']}</p>
                        <p><strong>Supplier count</strong> {row['suppliers']}</p>
                        <p><strong>Stock available</strong> {row['stock']:,}</p>
                        <p><strong>Lifecycle</strong> {row['lifecycle']}</p>
                        <p><strong>Risk score</strong> {row['score']}</p>
                      </article>
                      <div>
                        <article class="cv-risk-drivers"><h3>Risk drivers</h3><ul class="cv-ei-reasons">{reasons}</ul></article>
                        <article class="cv-risk-action"><h3>Recommended action</h3><p>{alternative_link}</p><p>{row['action_detail']}</p></article>
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
    analysis_id: str = "",
) -> str:
    rows = _part_rows(parts)
    expanded = str(expanded_mpn or "").strip()
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
        if row["mpn_raw"] == expanded:
            drivers = "".join(f"<li>{driver}</li>" for driver in row["drivers"])
            alternative_link = _alternative_action_link(
                row,
                analysis_id=analysis_id,
                bom_name=bom_name,
                source_page="detailed_risk_report",
            )
            body.append(
                f"""
                <div class="cv-risk-detail">
                  <article class="cv-risk-card">
                    <div class="cv-ei-part">{_part_art(row['mpn_raw'], row['image'], part=row)}<span class="cv-ei-part-copy"><h3>{row['mpn']}</h3>{f"<span class='cv-ei-meta'>{row['description']}</span>" if str(row.get('description_raw') or '').strip() else ""}</span></div>
                    <p>Manufacturer {_esc(row['manufacturer'])}</p>
                    <p>Best source {_esc(row['source'])}</p>
                    <p>Suppliers {row['suppliers']}</p>
                    <p>Stock (total) {row['stock']:,}</p>
                    <p>Lifecycle {row['lifecycle']}</p>
                  </article>
                  <div>
                    <article class="cv-risk-drivers"><h3>Risk drivers</h3><ul class="cv-ei-reasons">{drivers}</ul></article>
                    <article class="cv-risk-action"><h3>Recommended action</h3><p>{alternative_link}</p><p>{row['action_detail']}</p></article>
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
    approved_alternatives: list[dict[str, Any]] | None = None,
    approval_load_failed: bool = False,
) -> None:
    import streamlit as st

    st.markdown(report_styles(), unsafe_allow_html=True)
    with st.container(key="ei_report_workspace"):
        bom_name = str(analysis.get("project_name") or analysis.get("filename") or "Saved BOM")
        detailed = bool(st.session_state.get("cadivor_show_detailed_risk"))
        tab_state_key = "cadivor_ei_report_tab"
        if st.session_state.get(tab_state_key) not in EI_TABS:
            st.session_state[tab_state_key] = "BOM Risk"
        tab = str(st.session_state.get(tab_state_key) or "BOM Risk")
        if not detailed:
            st.markdown(
                f"<div class='cv-ap'><p class='cv-ap-kicker'>{html.escape(bom_name)} · {len(parts or [])} components</p>"
                "<h1>Engineering Intelligence</h1></div>",
                unsafe_allow_html=True,
            )
            with st.container(key="cv_ei_report_tabs"):
                selected_tab = st.segmented_control(
                    "Engineering Intelligence section",
                    options=list(EI_TABS),
                    key=tab_state_key,
                    label_visibility="collapsed",
                )
                tab = str(selected_tab or tab)
                st.markdown(
                    f"""
                    <style>
                    .st-key-cv_ei_report_tabs [data-testid="stVerticalBlock"]{{gap:.25rem!important}}
                    .st-key-cv_ei_report_tabs [data-testid="stSegmentedControl"]{{
                      width:100%;background:transparent!important;border-bottom:0!important;
                      border-radius:0!important;box-shadow:none!important
                    }}
                    .st-key-cv_ei_report_tabs [data-testid="stSegmentedControl"] :is(button,[role="radio"],[role="tab"]){{ 
                      color:#64748b!important;background:transparent!important;border:0!important;
                      border-bottom:2px solid transparent!important;border-radius:0!important;
                      box-shadow:none!important;min-height:34px!important;padding:6px 10px!important;
                      white-space:nowrap!important
                    }}
                    .st-key-cv_ei_report_tabs [data-testid="stSegmentedControl"] :is(button,[role="radio"],[role="tab"])[aria-checked="true"],
                    .st-key-cv_ei_report_tabs [data-testid="stSegmentedControl"] :is(button,[role="radio"],[role="tab"])[aria-pressed="true"],
                    .st-key-cv_ei_report_tabs [data-testid="stSegmentedControl"] :is(button,[role="radio"],[role="tab"])[aria-selected="true"],
                    .st-key-cv_ei_report_tabs [data-testid="stSegmentedControl"] :is(button,[role="radio"],[role="tab"])[data-selected="true"],
                    .st-key-cv_ei_report_tabs [data-testid="stSegmentedControl"] label:has(input:checked){{
                      color:#1d4ed8!important;background:transparent!important;border:0!important;
                      border-bottom:2px solid #2563eb!important;border-radius:0!important;
                      box-shadow:none!important;font-weight:750!important
                    }}
                    .st-key-cv_ei_report_tabs [data-testid="stSegmentedControl"] button:focus:not(:focus-visible){{outline:none!important}}
                    .st-key-cv_ei_report_tabs [data-testid="stSegmentedControl"] button:focus-visible{{outline:2px solid #93c5fd!important;outline-offset:2px!important}}
                    @media(max-width:760px){{.st-key-cv_ei_report_tabs{{overflow-x:auto}}}}
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(_ei_tab_indicator_html(tab), unsafe_allow_html=True)
        if approval_load_failed:
            st.warning("Saved replacement approvals could not be loaded. They may be missing from this view until the connection is restored.")
        if st.session_state.get("cadivor_show_detailed_risk"):
            if st.button("Back to Engineering Intelligence", key="ei_back_from_detailed_risk"):
                st.session_state["cadivor_show_detailed_risk"] = False
                st.rerun()
            analyzed = str(analysis.get("created_at") or "saved analysis")
            render_detailed_risk_rows(
                bom_name=bom_name,
                analyzed_on=analyzed,
                parts=parts or [],
                analysis_id=str(analysis.get("id") or ""),
                approved_alternatives=approved_alternatives or [],
            )
            try:
                from src.ui.detailed_risk_export import (
                    detailed_risk_csv_bytes,
                    detailed_risk_excel_bytes,
                )

                report_source = str(
                    _first(analysis, "filename", "file_name", "uploaded_file", fallback="") or ""
                )
                download_cols = st.columns(2)
                with download_cols[0]:
                    st.download_button(
                        "Download Excel Report",
                        data=detailed_risk_excel_bytes(
                            parts or [],
                            bom_name=bom_name,
                            source_filename=report_source,
                            analyzed_on=analyzed,
                            approved_alternatives=approved_alternatives or [],
                        ),
                        file_name="cadivor-detailed-risk-report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="approved_detailed_risk_excel",
                        use_container_width=True,
                    )
                with download_cols[1]:
                    st.download_button(
                        "Download CSV Audit",
                        data=detailed_risk_csv_bytes(parts or [], approved_alternatives or []),
                        file_name="cadivor-detailed-risk-report.csv",
                        mime="text/csv",
                        key="approved_detailed_risk_csv",
                        use_container_width=True,
                    )
            except Exception:
                st.caption("Report downloads are unavailable for this analysis.")
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
                analysis_id=str(analysis.get("id") or ""),
                approved_alternatives=approved_alternatives or [],
            ),
            unsafe_allow_html=True,
        )
        analysis_id = str(analysis.get("id") or "")
        if tab == "BOM Risk":
            with st.container(key="ei_refresh_saved_analysis", border=True):
                refresh_copy, refresh_action = st.columns([4, 1.35], vertical_alignment="center")
                with refresh_copy:
                    st.markdown(
                        "<div class='cv-ei-refresh-card'><div><strong>Refresh supplier data</strong>"
                        "<p>This page shows the saved analysis snapshot. Open the BOM and rerun it to check current distributor stock, lead time, and lifecycle data.</p></div></div>",
                        unsafe_allow_html=True,
                    )
                with refresh_action:
                    if st.button(
                        "Open BOM to rerun",
                        key=f"ei_open_bom_to_rerun_{analysis_id or 'saved'}",
                        type="secondary",
                        use_container_width=True,
                    ):
                        from src.ui.navigation import navigate_to

                        navigate_to(
                            "BOM Settings",
                            saved_bom_id=analysis_id,
                            saved_bom_action="open",
                            arm_opening=False,
                        )
        if st.button("Open detailed risk report", key="ei_open_detailed_risk"):
            st.session_state[f"cadivor_detailed_risk_mpn_{analysis_id or bom_name}"] = ""
            st.session_state["cadivor_show_detailed_risk"] = True
            st.rerun()

