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
from datetime import datetime, timezone
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
    label_override: str = "",
) -> str:
    label = str(label_override or row.get("action") or "")
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


def _detailed_report_analyses(
    saved_analyses: list[dict[str, Any]] | None,
    current_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return unique saved reports and keep the currently open analysis available."""
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in list(saved_analyses or []) + [current_analysis]:
        analysis_id = str(row.get("id") or "").strip()
        if analysis_id and analysis_id not in seen:
            options.append(row)
            seen.add(analysis_id)
    return options


def _detailed_report_analysis_label(analysis: dict[str, Any]) -> str:
    """Show only the saved Project/BOM name in the report selector."""
    project = str(analysis.get("project_name") or "").strip()
    bom_name = str(analysis.get("bom_name") or "").strip()
    if project:
        return project
    if bom_name:
        return bom_name
    filename = str(analysis.get("filename") or "").strip()
    if filename:
        basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        return basename.rsplit(".", 1)[0] or basename
    return "Saved BOM"


def _format_detailed_report_date(value: Any) -> str:
    """Format stored ISO timestamps as a human-readable calendar date."""
    raw = str(value or "").strip()
    if not raw or raw.casefold() in {"saved analysis", "none", "nan"}:
        return "Date unavailable"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "Date unavailable"
    months = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    return f"{months[parsed.month - 1]} {parsed.day}, {parsed.year}"


def _format_snapshot_timestamp(value: Any) -> str:
    """Show when the saved analysis snapshot was created, with an explicit timezone."""
    raw = str(value or "").strip()
    if not raw or raw.casefold() in {"none", "nan", "saved analysis"}:
        return "Date unavailable"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "Date unavailable"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    months = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    hour = parsed.hour % 12 or 12
    minute = f"{parsed.minute:02d}"
    meridiem = "AM" if parsed.hour < 12 else "PM"
    return f"{months[parsed.month - 1]} {parsed.day}, {parsed.year} at {hour}:{minute} {meridiem} UTC"


def _detailed_report_metadata_html(
    *,
    bom_name: str,
    source_filename: str,
    part_count: int,
    analyzed_on: Any,
) -> str:
    """Display report context below its title, separate from the component table."""
    file_detail = (
        f"<span><strong>File</strong> {_esc(source_filename)}</span>"
        if str(source_filename or "").strip()
        else ""
    )
    return (
        f"<p class='cv-ei-sub'>{_esc(bom_name)} · {part_count} components</p>"
        f"<div class='cv-risk-report-meta'>{file_detail}"
        f"<span><strong>Last analyzed</strong> {_esc(_format_detailed_report_date(analyzed_on))}</span>"
        f"</div>"
    )


def _navigate_to_detailed_report_analysis(current_analysis_id: str, selector_key: str) -> None:
    """Open the selected saved analysis in the same Detailed Risk Report view."""
    import streamlit as st

    selected_id = str(st.session_state.get(selector_key) or "").strip()
    if not selected_id or selected_id == str(current_analysis_id or ""):
        return

    # This key is scoped to the old analysis. Clear it so returning later starts
    # with the report that is actually open instead of the previous selection.
    st.session_state.pop(selector_key, None)
    st.session_state["cadivor_show_detailed_risk"] = True
    from src.ui.navigation import navigate_to

    navigate_to(
        "Analysis Details",
        analysis_id=selected_id,
        analysis_tab="Engineering Intelligence",
        _rerun=False,
        arm_opening=False,
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


def _supplier_evidence(part: dict[str, Any]) -> bool:
    """Whether the saved part has a distributor match, not just a coverage note."""
    count = _recorded_number(_first(part, "supplier_count", "Supplier Count"))
    if count is not None and count > 0:
        return True
    for key in ("stock_data_sources", "sources"):
        value = _first(part, key, fallback=None)
        if _source_payload_present(value):
            return True
    offers = _first(part, "supplier_offers", "Supplier Offers", fallback=None)
    return isinstance(offers, (list, tuple)) and bool(offers)


def _source_payload_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(_source_payload_present(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_source_payload_present(item) for item in value)
    text = str(value).strip().casefold()
    if text in {"", "[]", "{}", "—", "-", "not reported", "unavailable", "none", "null", "nan"}:
        return False
    return "no configured supplier returned" not in text and "no supplier match" not in text


def _stock_value(part: dict[str, Any]) -> float | None:
    value = _recorded_number(_first(part, "stock_available", "Stock Available", "stock"))
    if value == 0:
        # Legacy rows often serialized absent stock as zero. A zero is
        # reportable only when a distributor explicitly supplied it.
        sources = _first(part, "stock_data_sources", "sources", fallback=None)
        return value if _supplier_evidence(part) and _source_payload_present(sources) else None
    return value


def _display_count(value: float | None) -> str:
    return f"{value:,.0f}" if value is not None else "Not reported"


def _display_score(value: float | None) -> str:
    return f"{value:g}" if value is not None else "Not assessed"


def _first(row: dict[str, Any], *keys: str, fallback: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() not in {"", "nan", "None"}:
            return value
    return fallback


def _level(part: dict[str, Any]) -> str:
    label = str(_first(part, "risk_level", "Risk Level", fallback="") or "").strip()
    folded = label.casefold()
    if "high" in folded or "critical" in folded:
        return "High"
    if "med" in folded:
        return "Medium"
    if "low" in folded:
        return "Low"
    if any(token in folded for token in ("verif", "unassess", "not assess", "not rated", "unknown", "unrated")):
        return "Needs verification"
    raw_score = _recorded_number(_first(part, "risk_score", "Risk Score"))
    if raw_score is None or (raw_score == 0 and not _supplier_evidence(part)):
        return "Needs verification"
    score = raw_score
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def _level_class(level: str) -> str:
    return {
        "High": "high",
        "Medium": "medium",
        "Low": "low",
        "Needs verification": "verification",
    }.get(level, "verification")


def _drivers(part: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    stock = _stock_value(part)
    suppliers = _recorded_number(_first(part, "supplier_count", "Supplier Count"))
    lifecycle = str(_first(part, "lifecycle_status", "Lifecycle Status", fallback="") or "")
    lead = _first(part, "lead_time_weeks", "Lead Time Weeks")
    if not _supplier_evidence(part):
        notes.append("No configured distributor returned a matching record for this MPN")
        notes.append("Verify the full manufacturer part number and rerun the analysis")
    if any(token in lifecycle.casefold() for token in ("obsolete", "eol", "end of life", "nrnd")):
        notes.append("Product lifecycle status: " + lifecycle)
    if stock == 0:
        notes.append("No stock at approved suppliers")
    elif stock is not None and 0 < stock < 100:
        notes.append("Limited stock at approved suppliers")
    if suppliers == 1:
        notes.append("Single-source manufacturer")
    elif suppliers is not None and 1 < suppliers < 3:
        notes.append("Fewer than 3 active suppliers")
    if lead is not None and _num(lead, 0) >= 26:
        notes.append(f"Long lead time ({_num(lead)}+ weeks)")
    if not notes:
        notes.append("No material exception is recorded in the saved analysis")
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
    if level == "Needs verification":
        return (
            "Verify component data",
            "Confirm the full manufacturer part number and rerun to retrieve supplier evidence.",
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
        source_html = f"<strong>{_esc(name)}</strong>{''.join(details)}"
    elif name:
        source_html = (
            f"<strong>{_esc(name)}</strong>"
            "<small>Distributor was saved. Unit price was not saved, so this is not a comparable offer.</small>"
            + link
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
    if comparison.get("savings_per_unit") is not None:
        break_quantity = comparison.get("break_quantity") or quantity
        break_quantity_text = _esc(f"{float(break_quantity):g}")
        break_unit = "unit" if float(break_quantity) == 1 else "units"
        comparison_html = (
            f"<strong>{_esc(comparison['lower_distributor'])} is "
            f"{_esc(_money(float(comparison['savings_per_unit'])))} / unit lower</strong>"
            f"<small>Price applies from {break_quantity_text} {break_unit}; BOM quantity "
            f"{_esc(f'{quantity:g}' if quantity is not None else 'not recorded')}. "
            f"Compared with "
            f"{_esc(comparison['higher_distributor'])} at "
            f"{_esc(_money(float(comparison['higher_price'])))} "
            f"{_esc(comparison.get('currency') or '')}.</small>"
        )
        comparable = True
    elif comparison.get("currency") and comparison.get("lower_price") is not None:
        comparison_html = (
            "<strong>No lower comparable price was found</strong>"
            f"<small>{_esc(comparison.get('lower_distributor') or '')} "
            f"{_esc(_money(float(comparison['lower_price'])))} and "
            f"{_esc(comparison.get('higher_distributor') or '')} "
            f"{_esc(_money(float(comparison['higher_price'])))} "
            f"{_esc(comparison.get('currency') or '')} at the saved quantity.</small>"
        )
        comparable = True
    elif len(offers) >= 2:
        comparison_html = (
            "<strong>Offers not comparable</strong>"
            f"<small>{_esc(comparison.get('message') or 'Check the saved currency and price breaks.')}</small>"
        )
        comparable = False
    elif offers or (name and price is not None):
        comparison_html = (
            "<strong>One saved offer</strong>"
            "<small>A second distributor quote for this exact MPN and quantity is needed for a price comparison.</small>"
        )
        comparable = False
    else:
        comparison_html = (
            "<strong>No saved price offers</strong>"
            "<small>Re-run the BOM analysis to check current distributor prices.</small>"
        )
        comparable = False
    return {
        "cost_price": price_html,
        "cost_source": source_html,
        "cost_extended": extended_html,
        "cost_quantity": _esc(f"{quantity:g}") if quantity is not None else "Not recorded",
        "cost_comparison": comparison_html,
        "cost_comparable": comparable,
        "cost_has_price": price is not None,
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
                "score": _recorded_number(_first(part, "risk_score", "Risk Score")),
                "score_display": _display_score(_recorded_number(_first(part, "risk_score", "Risk Score"))),
                "stock": _stock_value(part),
                "stock_display": _display_count(_stock_value(part)),
                "suppliers": _recorded_number(_first(part, "supplier_count", "Supplier Count")),
                "suppliers_display": _display_count(_recorded_number(_first(part, "supplier_count", "Supplier Count"))),
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
    order = {"High": 0, "Medium": 1, "Needs verification": 2, "Low": 3}
    ranked.sort(key=lambda row: (order.get(row["level"], 4), -(row["score"] or 0)))
    return ranked


def report_styles() -> str:
    return """
    <style data-cadivor-layout-style="true">
      .st-key-ei_report_workspace { width:100%!important;max-width:100%!important;margin-inline:auto!important;box-sizing:border-box;min-width:0!important }
      .st-key-ei_report_workspace .cv-ei-report { color:#0f172a; font-family: Inter, "Segoe UI", sans-serif; width:100%;max-width:100%;margin:0 auto;box-sizing:border-box;min-width:0 }
      .st-key-ei_report_workspace .cv-ap { color:#0f172a; font-family:Inter, "Segoe UI", sans-serif; margin:0 0 2px; }
      .st-key-cv_ei_detailed_report_action{display:flex!important;justify-content:flex-end!important;margin:12px 0 4px}
      .st-key-cv_ei_detailed_report_action [data-testid="stButton"]{width:auto!important;margin-left:auto!important}
      .st-key-cv_ei_detailed_report_action [data-testid="stButton"]>button{background:#2563eb!important;color:#fff!important;border:1px solid #2563eb!important;border-radius:9px!important;min-height:40px!important;padding:8px 14px!important;font-weight:800!important;box-shadow:0 2px 4px rgba(37,99,235,.18)!important}
      .st-key-cv_ei_detailed_report_action [data-testid="stButton"]>button:hover{background:#1d4ed8!important;border-color:#1d4ed8!important}
      .st-key-ei_report_workspace .cv-ap-kicker { margin:0 0 6px; color:#64748b; font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
      .st-key-ei_report_workspace .cv-ap h1 { margin:0 0 6px; color:#0f172a; font-size:32px; font-weight:760; line-height:1.15; letter-spacing:-.03em; }
      .st-key-ei_report_workspace .cv-ei-title { font-size:30px; }
      .st-key-ei_report_workspace [class*="st-key-ei_detailed_report_bom_"] { width:100%!important;max-width:480px!important;margin:0 0 10px!important; }
      .st-key-ei_report_workspace [class*="st-key-ei_detailed_report_bom_"] [data-testid="stSelectbox"] { width:100%!important;max-width:100%!important; }
      .cv-risk-report-meta { display:flex;flex-wrap:wrap;gap:8px 22px;margin:-10px 0 18px;color:#64748b;font-size:12px;line-height:1.45; }
      .cv-risk-report-meta strong { color:#475569;font-weight:700;margin-right:4px; }
      .st-key-ei_report_workspace .cv-ei-section { min-width:0; margin:0 0 18px; overflow:hidden; background:#fff; border:1px solid #cbd8e8; border-radius:16px; box-shadow:0 3px 12px rgba(15,23,42,.045); }
      .cv-ei-section-heading { box-sizing:border-box; padding:18px 22px 14px; }
      .cv-ei-section-heading > h3 { margin:0!important; padding:0!important; color:#0f172a; font-size:19px!important; line-height:1.25; font-weight:750; letter-spacing:-.02em; }
      .cv-ei-section-heading > p { margin:6px 0 0!important; padding:0!important; color:#64748b; font-size:13px!important; line-height:1.5; }
      .cv-ei-section-heading > .cv-ei-data-note { margin-top:7px!important; color:#64748b; font-size:12px!important; line-height:1.4; }
      .st-key-ei_report_workspace .cv-ei-table-wrap { width:100%;max-width:100%;overflow-x:auto;border-radius:0 0 15px 15px;overscroll-behavior-inline:contain; }
      .st-key-ei_report_workspace .cv-ei-table { min-width:920px; border:0; border-radius:0; }
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
      .cv-ei-kpis { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin:0 0 22px; }
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
      .cv-pill.verification { background:#f1f5f9; color:#475569; }
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
      .cv-ei-table td small, .cv-ei-offer a { display:block; margin-top:4px; color:#64748b; font-size:12px; font-weight:500; line-height:1.35; }
      .cv-ei-offer a { color:#2563eb; font-size:12px; font-weight:650; }
      .cv-ei-cost-comparison strong { display:block; color:#0f172a; font-size:13px; font-weight:700; }
      .cv-ei-cost-comparison small { display:block; margin-top:4px; color:#64748b; font-size:12px; font-weight:500; line-height:1.4; }
      [class*="st-key-cv_risk_expand_"] button { background:transparent !important; border:0 !important; box-shadow:none !important; color:#0f172a !important; font-weight:750 !important; padding:0 !important; min-height:0 !important; height:auto !important; justify-content:flex-start !important; text-align:left !important; }
      .cv-risk-wrap { background:#fff; border:1px solid #e6edf5; border-radius:16px; overflow:hidden; }
      .cv-risk-exposure { display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:0 0 14px; }
      .cv-risk-exposure article { min-width:0;padding:13px 15px;border:1px solid #dce5ef;border-radius:12px;background:#fff; }
      .cv-risk-exposure span { display:block;margin-bottom:6px;color:#64748b;font-size:11px;font-weight:750;letter-spacing:.04em;text-transform:uppercase; }
      .cv-risk-exposure strong { display:block;color:#0f172a;font-size:17px;font-weight:760;line-height:1.3;overflow-wrap:anywhere; }
      .cv-risk-exposure small { display:block;margin-top:5px;color:#64748b;font-size:11px;line-height:1.4; }
      .cv-risk-row, .cv-risk-head { display:grid; grid-template-columns: 1.1fr 1fr .9fr .6fr .7fr .8fr .6fr .7fr; gap:8px; padding:12px 16px; align-items:center; }
      .cv-risk-head { color:#94a3b8; font-size:12px; letter-spacing:.04em; text-transform:uppercase; background:#f8fafc; }
      .cv-risk-row { border-top:1px solid #e5ebf3; font-size:14px; }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table { box-sizing:border-box;width:100%;margin:0 0 16px;padding:0;border:1px solid #cbd8e8;border-radius:14px;background:#fff;overflow:hidden }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table > [data-testid="stVerticalBlock"] { gap:0!important }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table_header { box-sizing:border-box;width:100%;padding:0 12px;background:#f7f9fc;border-bottom:1px solid #dce4ef }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table_header > [data-testid="stVerticalBlock"] { gap:0!important }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table_header [data-testid="stHorizontalBlock"] { align-items:center!important;gap:12px!important;min-height:48px }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table_header [data-testid="column"] { box-sizing:border-box;min-width:0;padding:0 4px }
      .cv-risk-grid-head { display:flex;align-items:center;box-sizing:border-box;min-height:46px;padding:0;color:#64748b;font-size:11px;font-weight:750;text-transform:uppercase;letter-spacing:.04em;line-height:1.25 }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table [class*="st-key-cv_risk_shut_"], .st-key-ei_report_workspace .st-key-cv_detailed_risk_table [class*="st-key-cv_risk_open_"] { box-sizing:border-box;margin:0;padding:8px 12px;border-bottom:0!important;box-shadow:none!important }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table [class*="st-key-cv_risk_shut_"] > [data-testid="stVerticalBlock"], .st-key-ei_report_workspace .st-key-cv_detailed_risk_table [class*="st-key-cv_risk_open_"] > [data-testid="stVerticalBlock"] { gap:0!important }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table [class*="st-key-cv_risk_"] [data-testid="stHorizontalBlock"] { align-items:center!important }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table [class*="st-key-cv_risk_"] [data-testid="column"] { min-width:0 }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table [data-testid="stElementContainer"]:has(.cv-risk-row-separator) { box-sizing:border-box;height:1px!important;min-height:1px!important;margin:0!important;padding:0!important }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table [data-testid="stElementContainer"]:has(.cv-risk-row-separator) [data-testid="stMarkdownContainer"] { line-height:0!important }
      .st-key-ei_report_workspace .st-key-cv_detailed_risk_table .cv-risk-row-separator { display:block;box-sizing:border-box;width:calc(100% - 24px);height:1px!important;min-height:1px!important;margin:0 12px!important;padding:0!important;border:0!important;background:#d5dfeb!important;opacity:1!important;line-height:0!important }
      .cv-risk-detail { display:grid; grid-template-columns:1.1fr .9fr; gap:16px; padding:14px 0 18px; }
      .st-key-ei_report_workspace .cv-part-photo { border-radius:8px!important; }
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
        .cv-risk-exposure { grid-template-columns:repeat(2,minmax(0,1fr)); }
        .cv-risk-grid-head { font-size:10px;padding:8px 5px }
      }
      @media (max-width: 600px) {
        .st-key-ei_report_workspace .cv-ap h1 { font-size:23px; }
        .st-key-ei_report_workspace .cv-ei-title { font-size:23px; }
        .st-key-ei_report_workspace .cv-ei-kpis { grid-template-columns:1fr; }
        .st-key-ei_report_workspace .cv-ei-section { border-radius:13px; }
        .cv-risk-exposure { grid-template-columns:1fr; }
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
    from src.approved_alternatives import approved_mpn_map, part_key

    approved_by_part = approved_mpn_map(approved_alternatives or [])
    approved_component_keys = {
        part_key(row.get("mpn_raw"))
        for row in rows
        if approved_by_part.get(part_key(row.get("mpn_raw")))
    }
    high = [row for row in rows if row["level"] == "High"]
    medium = [row for row in rows if row["level"] == "Medium"]
    unassessed = [row for row in rows if row["level"] == "Needs verification"]
    open_high = [
        row for row in high
        if not approved_by_part.get(part_key(row.get("mpn_raw")))
    ]
    open_medium = [
        row for row in medium
        if not approved_by_part.get(part_key(row.get("mpn_raw")))
    ]
    open_unassessed = [
        row for row in unassessed
        if not approved_by_part.get(part_key(row.get("mpn_raw")))
    ]
    no_stock = [row for row in rows if row["stock"] == 0]
    single = [row for row in rows if row["suppliers"] == 1]
    health_display = f"{_esc(health_score)}/100" if health_score is not None else "Not calculated"
    active = tab if tab in EI_TABS else "BOM Risk"
    banner = ""
    if active == "BOM Risk":
        # Keep these tags at column 0. Indented HTML becomes a Markdown code
        # block, which is what left the summary looking like an empty banner.
        if open_high:
            banner = textwrap.dedent(
                f"""
                <section class="cv-ei-banner">
                  <div class="cv-ei-icon warn">!</div>
                  <div>
                    <h2>Engineering review required</h2>
                    <p>{len(open_high)} components with high source risk still need a mitigation decision. Approved replacements are tracked separately; the original BOM rating remains in the report until the BOM is revised. {f'{len(unassessed)} additional components could not be risk-rated; verify their manufacturer part numbers and rerun.' if unassessed else ''}</p>
                  </div>
                </section>
                """
            ).strip()
        elif unassessed:
            banner = textwrap.dedent(
                f"""
                <section class="cv-ei-banner">
                  <div class="cv-ei-icon warn">!</div>
                  <div>
                    <h2>Supplier evidence incomplete</h2>
                    <p>{len(unassessed)} of {len(rows)} components could not be risk-rated. Verify the manufacturer part numbers and rerun before treating this BOM as low risk.</p>
                  </div>
                </section>
                """
            ).strip()
        elif approved_component_keys:
            banner = textwrap.dedent(
                f"""
                <section class="cv-ei-banner cv-ei-banner--clear">
                  <div class="cv-ei-icon health">✓</div>
                  <div>
                    <h2>Approved mitigation recorded</h2>
                    <p>{len(approved_component_keys)} component(s) have an approved replacement. Source BOM risk scores and original part numbers stay visible for audit; upload a revised BOM to record the physical substitution.</p>
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
              <div class="cv-ei-kpi"><div class="cv-ei-icon health">♡</div><div><span>{'Risk coverage' if unassessed else 'Health'}</span><strong>{f'{len(rows) - len(unassessed)}/{len(rows)}' if unassessed else health_display}</strong></div></div>
              <div class="cv-ei-kpi"><div class="cv-ei-icon review">▣</div><div><span>Needs review</span><strong>{len(open_high) + len(open_medium) + len(open_unassessed)}</strong></div></div>
              <div class="cv-ei-kpi"><div class="cv-ei-icon stock">▢</div><div><span>No-stock parts</span><strong>{len(no_stock)}</strong></div></div>
              <div class="cv-ei-kpi"><div class="cv-ei-icon source">⚭</div><div><span>Single-source</span><strong>{len(single)}</strong></div></div>
              <div class="cv-ei-kpi"><div class="cv-ei-icon health">✓</div><div><span>Approved alternatives</span><strong>{len(approved_component_keys)}</strong></div></div>
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
            f"<td>{row['source']}</td><td>{row['suppliers_display']}</td><td>{row['stock_display']}</td>"
            f"<td>{row['lead']}</td><td>{row['lifecycle']}</td>"
            f"<td><span class='cv-pill { _level_class(row['level']) }'>{row['level']}</span></td>"
            "</tr>"
            for row in rows[:12]
        )
        return _table(
            "Supply and availability",
            "Distributor coverage, stock, lead time, and lifecycle evidence captured when this BOM was analyzed.",
            ["Component", "Best source", "Suppliers", "Stock", "Lead time (weeks)", "Lifecycle", "Risk"],
            body,
        )
    if tab == "Alternatives":
        photos = {row["mpn_raw"]: row for row in rows}
        from src.approved_alternatives import approved_mpn_map, part_key, report_alternative

        approved_pairs = {
            (part_key(record.get("original_part")), part_key(record.get("alternative_part")))
            for record in approved_alternatives or []
            if isinstance(record, dict)
        }

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
            saved_details = []
            for label, key in (
                ("Package", "package"),
                ("Lifecycle", "lifecycle"),
                ("Stock", "stock"),
                ("Unit price", "unit_price"),
                ("Source package", "source_package"),
                ("Pin count", "candidate_pin_count"),
                ("Source pin count", "source_pin_count"),
                ("Device family", "candidate_architecture"),
            ):
                value = approved.get(key)
                if value is not None and str(value).strip() not in {"", "nan", "None"}:
                    if key == "unit_price" and approved.get("unit_price_currency"):
                        value = f"{approved.get('unit_price_currency')} {value}"
                    saved_details.append(f"{label}: {value}")
            saved_details.append(str(approved.get("compatibility_summary") or "Engineering approval recorded."))
            approved_rows.append(
                "<tr>"
                f"<td>{_component_cell({'mpn': _esc(original_raw), 'mpn_raw': original_raw, 'image': original.get('image') or '', 'description': '', 'description_raw': '', 'category_raw': '', 'category': ''}, description=False)}</td>"
                f"<td>{_component_cell({'mpn': _esc(replacement_raw), 'mpn_raw': replacement_raw, 'image': approved.get('image_url') or '', 'description': '', 'description_raw': '', 'category_raw': '', 'category': ''}, description=False)}</td>"
                f"<td>{_esc(approved.get('manufacturer') or '—')}</td>"
                f"<td>{'<br>'.join(_esc(item) for item in saved_details)}</td>"
                f"<td><span class='cv-ei-approved'>Approved</span><small>{_esc(approved.get('reason') or '')}</small></td>"
                "</tr>"
            )
        approved_section = _table(
            "Approved alternatives",
            "Saved supplier, lifecycle, package, and compatibility details travel with each approval. The original BOM row remains unchanged until a revised BOM is uploaded.",
            ["Original component", "Approved replacement", "Manufacturer", "Saved replacement details", "Approval record"],
            "".join(approved_rows) or "<tr><td colspan='5'>No approved alternative is recorded for this BOM yet.</td></tr>",
        )
        alt_rows = []
        for alt in alternatives:
            if not isinstance(alt, dict):
                continue
            original_raw = str(_first(alt, "original_part", "original_mpn", "mpn", fallback="") or "").strip()
            replacement_raw = str(_first(alt, "alternative_part", "alternative_mpn", fallback="") or "").strip()
            if not original_raw and not replacement_raw:
                continue
            if (part_key(original_raw), part_key(replacement_raw)) in approved_pairs:
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
                "<tr><td colspan='4'>No unapproved candidates were saved with this analysis. Approved Finder decisions appear in the table above.</td></tr>"
            )
        return approved_section + _table(
            "Other saved candidates",
            "Candidates suggested in the analysis run. Approved Find a replacement decisions are listed above.",
            ["Original", "Candidate", "Manufacturer", "Why it is listed"],
            "".join(alt_rows[:12]),
        )
    if tab == "Cost Insights":
        priced_count = sum(bool(row.get("cost_has_price")) for row in rows)
        comparable_count = sum(bool(row.get("cost_comparable")) for row in rows)
        summary = (
            f"{priced_count} of {len(rows)} components have a saved unit price; "
            f"{comparable_count} have comparable distributor offers at the saved BOM quantity."
        )
        if not rows:
            body = "<tr><td colspan='6'>No saved components are available for a cost decision.</td></tr>"
        else:
            body = "".join(
                "<tr>"
                f"<td>{_component_cell(row, description=False)}</td>"
                f"<td>{row['cost_quantity']}</td>"
                f"<td>{row['cost_price']}</td>"
                f"<td class='cv-ei-offer'>{row['cost_source']}</td>"
                f"<td>{row['cost_extended']}</td>"
                f"<td class='cv-ei-cost-comparison'>{row['cost_comparison']}</td>"
                "</tr>"
                for row in rows[:12]
            )
        return _table(
            "Cost insights",
            summary + " Extended cost is unit price × BOM quantity. Cadivor compares only the same MPN, currency, and applicable quantity; it does not estimate missing prices.",
            ["Component", "BOM quantity", "Unit price", "Saved distributor offer(s)", "Extended cost", "Price comparison"],
            body,
        )
    if tab == "Lifecycle":
        body = "".join(
            f"<tr><td>{_component_cell(row)}</td><td>{row['lifecycle']}</td><td>{row['manufacturer']}</td><td><span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span></td></tr>"
            for row in rows[:12]
        )
        return _table(
            "Lifecycle",
            "Lifecycle status captured during the saved analysis, with the associated risk classification.",
            ["Component", "Lifecycle", "Manufacturer", "Risk"],
            body,
        )
    from src.approved_alternatives import approved_mpn_map, part_key

    approved_by_part = approved_mpn_map(approved_alternatives or [])
    review = [
        row for row in rows
        if row["level"] in {"High", "Medium", "Needs verification"}
        or approved_by_part.get(part_key(row.get("mpn_raw")))
    ][:12]
    if not review:
        return _table(
            "Review these components first",
            "No components need follow-up based on the saved risk and supplier evidence.",
            ["#", "Component", "Risk", "Key reason(s)", "Recommended action"],
            "<tr><td colspan='5'>No components need review in this saved analysis.</td></tr>",
        )
    body = []
    for index, row in enumerate(review, start=1):
        reasons = "".join(f"<li>{driver}</li>" for driver in row["drivers"])
        approvals = approved_by_part.get(part_key(row.get("mpn_raw")), [])
        if approvals:
            approved = approvals[0]
            approved_at = _format_detailed_report_date(approved.get("approved_at"))
            approved_name = _esc(approved.get("alternative_part") or "")
            approved_by = _esc(approved.get("approved_by") or "Cadivor user")
            approval_note = (
                f"<span class='cv-ei-approved'>Alternative approved: {approved_name}</span>"
                f"<small>Approved by {approved_by} · {approved_at}</small>"
                "<small>Open the Alternatives tab for saved replacement details. Upload a revised BOM after the physical substitution.</small>"
            )
        else:
            approval_note = (
                _alternative_action_link(
                    row,
                    analysis_id=analysis_id,
                    bom_name=bom_name,
                    source_page="engineering_intelligence_review",
                )
                + f"<small>{row['action_detail']}</small>"
            )
        if approvals:
            original_risk = row["level"]
            score_note = (
                f" · score {row['score_display']}/100"
                if row["score"] is not None
                else ""
            )
            risk_cell = (
                "<span class='cv-pill low'>Mitigated</span>"
                f"<small>Original BOM risk: {original_risk}{score_note}</small>"
            )
        else:
            risk_cell = (
                f"<span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span>"
                "<small>Source BOM assessment</small>"
            )
        body.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{_component_cell(row)}</td>"
            f"<td>{risk_cell}</td>"
            f"<td><ul class='cv-ei-reasons'>{reasons}</ul></td>"
            f"<td><div class='cv-ei-action'>{approval_note}</div></td>"
            "</tr>"
        )
    return _table(
        "Review these components first",
        "The highest known risks and components that need supplier data verification appear first.",
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
      </div>
      <div class="cv-ei-table-wrap" role="region" aria-label="{_esc(title)} table" tabindex="0">
        <table class="cv-ei-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
      </div>
    </section>
    """


def _detailed_risk_expanded_markup(
    row: dict[str, Any],
    *,
    reasons: str,
    alternative_link: str,
) -> str:
    recorded_description = (
        f"<p>{row['description']}</p>"
        if str(row.get("description_raw") or "").strip()
        else ""
    )
    # Keep this HTML compact. Four-space-indented tags inside Markdown are
    # rendered as a code block by Streamlit instead of as report content.
    return (
        f'<div class="cv-risk-detail" data-expanded-mpn="{_esc(row["mpn_raw"])}">'
        f'<article class="cv-risk-card">'
        f'<div class="cv-ei-part">{_part_art(row["mpn_raw"], row["image"], part=row)}'
        f'<span class="cv-ei-part-copy"><h3>{row["mpn"]}</h3></span></div>'
        f'{recorded_description}'
        f'<p><strong>Manufacturer</strong> {row["manufacturer"]}</p>'
        f'<p><strong>Best source</strong> {row["source"]}</p>'
        f'<p><strong>Supplier count</strong> {row["suppliers_display"]}</p>'
        f'<p><strong>Stock available</strong> {row["stock_display"]}</p>'
        f'<p><strong>Lifecycle</strong> {row["lifecycle"]}</p>'
        f'<p><strong>Risk score</strong> {row["score_display"]}</p>'
        f'</article><div>'
        f'<article class="cv-risk-drivers"><h3>Risk drivers</h3>'
        f'<ul class="cv-ei-reasons">{reasons}</ul></article>'
        f'<article class="cv-risk-action"><h3>Recommended action</h3>'
        f'<p>{alternative_link}</p><p>{row["action_detail"]}</p></article>'
        f'</div></div>'
    )


def _risk_exposure_markup(
    parts: list[dict[str, Any]],
    approved_alternatives: list[dict[str, Any]] | None = None,
) -> str:
    from src.ui.detailed_risk_export import component_rows, report_exposure_summary

    exposure = report_exposure_summary(component_rows(parts, approved_alternatives))
    priced_note = (
        f"{exposure['priced_component_count']} priced line(s); "
        f"{exposure['priced_missing_currency_count']} omitted from totals because currency is not recorded."
    )
    high_exposure_note = (
        f"{exposure['high_risk_without_extended_cost_count']} line(s) need price or quantity; "
        f"{exposure['high_risk_missing_currency_count']} priced line(s) lack currency."
    )
    mitigation_note = (
        f"Gross original-BOM amount: {exposure['gross_high_risk_amount_by_currency']}. "
        f"{exposure['approved_high_risk_component_count']} high-risk line(s) have an approved alternative; "
        "the source BOM remains unchanged until a revised BOM is uploaded."
    )
    return f"""
    <section class="cv-risk-exposure" aria-label="Cost and lead-time exposure">
      <article><span>Extended BOM amount by currency</span><strong>{_esc(exposure['extended_amount_by_currency'])}</strong><small>{_esc(priced_note)} Price × BOM quantity; not inventory value or committed spend.</small></article>
      <article><span>Open high-risk / lifecycle amount</span><strong>{_esc(exposure['high_risk_amount_by_currency'])}</strong><small>{_esc(high_exposure_note)} Lines with approved alternatives are excluded from this open-action amount.</small></article>
      <article><span>Gross high-risk / lifecycle amount</span><strong>{_esc(exposure['gross_high_risk_amount_by_currency'])}</strong><small>{_esc(mitigation_note)} Both totals include only recorded currencies.</small></article>
      <article><span>Longest reported part lead time</span><strong>{_esc(exposure['longest_reported_lead_time'])}</strong><small>{exposure['components_with_lead_time_count']} component(s) have lead-time data. Possible sourcing bottleneck, not a project-delay forecast.</small></article>
    </section>
    """


def render_detailed_risk_rows(
    *,
    bom_name: str,
    analyzed_on: str,
    parts: list[dict[str, Any]],
    source_filename: str = "",
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
          {_detailed_report_metadata_html(bom_name=bom_name, source_filename=source_filename, part_count=len(rows), analyzed_on=analyzed_on)}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not rows:
        st.caption("This BOM has no saved components.")
        return
    st.markdown(
        _risk_exposure_markup(parts, approved_alternatives),
        unsafe_allow_html=True,
    )

    widths = [2.2, 1.1, 1.45, 1.15, 0.9]
    with st.container(key="cv_detailed_risk_table"):
        with st.container(key="cv_detailed_risk_table_header"):
            header = st.columns(widths, vertical_alignment="center")
            for column, label in zip(header, ("Component", "Manufacturer", "Supply", "Lifecycle", "Risk")):
                column.markdown(f"<div class='cv-risk-grid-head'>{label}</div>", unsafe_allow_html=True)

        visible_rows = rows[:12]
        for index, row in enumerate(visible_rows):
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
                    f"<div class='cv-ei-meta'>{row['suppliers_display']} supplier(s) · {row['stock_display']} stock</div>",
                    unsafe_allow_html=True,
                )
                cells[3].markdown(row["lifecycle"])
                row_approvals = approved_by_part.get(part_key(row.get("mpn_raw")), [])
                if row_approvals:
                    risk_markup = (
                        "<span class='cv-pill low'>Mitigated</span>"
                        f"<div class='cv-ei-meta'>Original BOM risk: {row['level']} · score {row['score_display']}</div>"
                    )
                else:
                    risk_markup = (
                        f"<span class='cv-pill {_level_class(row['level'])}'>{row['level']}</span>"
                        f"<div class='cv-ei-meta'>Score {row['score_display']}</div>"
                    )
                cells[4].markdown(
                    risk_markup,
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
                    detail_markup = _detailed_risk_expanded_markup(
                        row,
                        reasons=reasons,
                        alternative_link=alternative_link,
                    )
                    st.markdown(detail_markup, unsafe_allow_html=True)
            if index < len(visible_rows) - 1:
                st.markdown(
                    "<hr class='cv-risk-row-separator' aria-hidden='true'>",
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
    exposure_html = _risk_exposure_markup(parts)
    expanded = str(expanded_mpn or "").strip()
    body = [
        '<div class="cv-risk-head"><div>MPN</div><div>Manufacturer</div><div>Best source</div><div>Suppliers</div><div>Stock</div><div>Lifecycle</div><div>Risk score</div><div>Risk level</div></div>'
    ]
    for row in rows[:12]:
        body.append(
            "<div class='cv-risk-row'>"
            f"<div>{_component_cell(row, description=False)}</div><div>{row['manufacturer']}</div><div>{row['source']}</div>"
            f"<div>{row['suppliers_display']}</div><div>{row['stock_display']}</div><div>{row['lifecycle']}</div><div>{row['score_display']}</div>"
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
                    <p>Suppliers {row['suppliers_display']}</p>
                    <p>Stock (total) {row['stock_display']}</p>
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
      <p class="cv-ei-sub">{_esc(bom_name)} · {len(rows)} parts · Last analyzed {_esc(_format_detailed_report_date(analyzed_on))}</p>
      {exposure_html}
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
    saved_analyses: list[dict[str, Any]] | None = None,
) -> None:
    import streamlit as st

    st.markdown(report_styles(), unsafe_allow_html=True)
    with st.container(key="ei_report_workspace"):
        approval_flash = st.session_state.pop("cadivor_approved_alternatives_flash", "")
        if approval_flash:
            st.success(str(approval_flash))
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
                tab_panels = st.tabs(
                    list(EI_TABS),
                    key=tab_state_key,
                    on_change="rerun",
                )
                st.markdown(
                    """
                    <style data-cadivor-layout-style="true">
                    .st-key-cv_ei_report_tabs [role="tablist"] {
                      display:flex!important;
                      width:100%!important;
                      justify-content:flex-end!important;
                      flex-wrap:nowrap!important;
                    }
                    .st-key-cv_ei_report_tabs [role="tablist"] [role="tab"] {
                      flex:0 0 auto!important;
                      white-space:nowrap!important;
                    }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
            tab = str(st.session_state.get(tab_state_key) or tab)
        if st.session_state.get("cadivor_show_detailed_risk"):
            if st.button("Back to Engineering Intelligence", key="ei_back_from_detailed_risk"):
                st.session_state["cadivor_show_detailed_risk"] = False
                st.rerun()
            report_analyses = _detailed_report_analyses(saved_analyses, analysis)
            analysis_ids = [str(row.get("id") or "") for row in report_analyses]
            current_analysis_id = str(analysis.get("id") or "")
            if len(analysis_ids) > 1 and current_analysis_id in analysis_ids:
                analysis_by_id = {
                    str(row.get("id") or ""): row
                    for row in report_analyses
                    if str(row.get("id") or "")
                }
                selector_key = f"ei_detailed_report_bom_{current_analysis_id}"
                selector_col, _ = st.columns([1, 2], gap="medium")
                with selector_col:
                    st.selectbox(
                        "Project / BOM",
                        options=analysis_ids,
                        index=analysis_ids.index(current_analysis_id),
                        format_func=lambda selected_id: _detailed_report_analysis_label(
                            analysis_by_id.get(str(selected_id), {})
                        ),
                        key=selector_key,
                        help=(
                            "Switch to another saved BOM report. Each report reflects "
                            "the data from that analysis run."
                        ),
                        on_change=_navigate_to_detailed_report_analysis,
                        args=(current_analysis_id, selector_key),
                    )
            analyzed = str(analysis.get("created_at") or "saved analysis")
            render_detailed_risk_rows(
                bom_name=bom_name,
                analyzed_on=analyzed,
                parts=parts or [],
                source_filename=str(
                    _first(analysis, "filename", "file_name", "uploaded_file", fallback="") or ""
                ),
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
        with tab_panels[EI_TABS.index(tab)]:
            if approval_load_failed:
                st.warning("Saved replacement approvals could not be loaded. They may be missing from this view until the connection is restored.")
            analysis_id = str(analysis.get("id") or "")
            if tab == "BOM Risk" and approved_alternatives:
                from src.approved_alternatives import approved_mpn_map, part_key

                approved_by_part = approved_mpn_map(approved_alternatives)
                approved_count = sum(
                    bool(approved_by_part.get(part_key(
                        _first(part, "mpn", "MPN", "part_number", fallback="")
                    )))
                    for part in parts or []
                    if isinstance(part, dict)
                )
                if approved_count and st.button(
                    f"View approved alternatives ({approved_count})",
                    key=f"ei_view_approved_alternatives_{analysis_id or 'saved'}",
                    type="secondary",
                ):
                    st.session_state[tab_state_key] = "Alternatives"
                    st.rerun()
            with st.container(key="ei_refresh_saved_analysis", border=True):
                st.markdown("#### Refresh supplier data")
                st.caption(
                    f"Saved data snapshot: {_format_snapshot_timestamp(analysis.get('created_at'))}"
                )
                st.caption(
                    "Stock, lead time, prices, and lifecycle are captured when this analysis runs so this report remains traceable. "
                    "Cadivor does not poll suppliers while the report is open. Rerun the BOM to check current data; that creates a new saved analysis and leaves this report unchanged. "
                    "Approved replacement decisions are saved separately and appear in BOM Risk and Alternatives."
                )
                if st.button(
                    "Open BOM to rerun",
                    key=f"ei_open_bom_to_rerun_{analysis_id or 'saved'}",
                    type="secondary",
                    use_container_width=False,
                ):
                    from src.ui.navigation import navigate_to

                    navigate_to(
                        "BOM Settings",
                        saved_bom_id=analysis_id,
                        saved_bom_action="open",
                        arm_opening=False,
                    )
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
            with st.container(key="cv_ei_detailed_report_action"):
                if st.button(
                    "Open detailed risk report",
                    key=f"ei_open_detailed_risk_{analysis_id or 'saved'}",
                    type="primary",
                    use_container_width=False,
                ):
                    st.session_state[f"cadivor_detailed_risk_mpn_{analysis_id or bom_name}"] = ""
                    st.session_state["cadivor_show_detailed_risk"] = True
                    st.rerun()
