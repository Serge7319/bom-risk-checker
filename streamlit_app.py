import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from src.alternative_engine import suggest_alternatives_v2
from src.bom_parser import normalize_bom_columns, validate_bom, clean_bom_data
from src.risk_engine import calculate_risk
from src.report_generator import save_results_to_excel
from src.ai_report_intelligence import (
    build_ai_report_intelligence,
    build_ai_executive_pdf,
    build_ai_procurement_pdf,
)
from src.role_report_generator import build_role_report_pdf
from src.alternative_reasoning import build_alternative_reasoning
from src.monitoring_intelligence import build_monitoring_action_center
from src.decision_engine import build_decision_center, STATUSES
from src.decision_dashboard import decision_card_html, packet_header_html
from src.decision_repository import (
    load_decision_state,
    save_decision_workflow,
    add_decision_note,
)
from src.procurement_advisor import build_procurement_advisor
from src.engineering_overview import build_engineering_overview
from src.readability_system import readability_css
from src.living_workspace import render_living_workspace
from src.portfolio_intelligence import build_portfolio_intelligence, render_portfolio_intelligence
from src.design_impact_analyzer import build_design_impact, render_design_impact
from src.cost_optimization import build_cost_optimization, render_cost_optimization
from integrations.supplier_aggregator import get_best_part_data
from src.health_score import calculate_bom_health_score, generate_executive_summary
from src.plans import PLANS, get_plan, validate_bom_against_plan
from src.alternative_engine import compare_parts, suggest_alternatives_v2, rank_alternatives
from src.auth import show_auth_ui
from supabase import create_client
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import resend
from src.monitoring_engine import build_monitor_record
from src.monitoring_engine import build_monitor_record, build_alert_record
from src.monitoring_engine import (
    build_monitor_record,
    build_alert_record,
    detect_monitor_alerts,
)
import time
import html
import re
import json
from datetime import datetime, timezone

start_time = time.time()
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.stripe_helper import create_checkout_session
from src.ui.milestone10a import apply_milestone10a_design_system
from src.ui.framework import (
    inject_premium_css,
    inject_v32_ux_css,
    render_topbar,
    page_header,
    metric_card,
    light_plotly_layout,
    empty_state,
    action_card,
    dashboard_command_center,
    dashboard_insight_card,
)
from src.pages.dashboard import render_dashboard
from src.pages.analysis_detail import render_analysis_detail
from src.pages.reports import render_reports_center
from src.ui.navigation import navigate_to, internal_nav_button
from src.onboarding_service import (
    ensure_onboarding_progress,
    update_onboarding_progress,
    completion_count,
)
from src.customer_profile_service import (
    ensure_customer_profile,
    update_customer_profile,
    ensure_user_preferences,
    update_user_preferences,
)
from src.event_labels import (
    action_label,
    category_label,
    display_time,
    event_category,
    friendly_summary,
)
from src.collaboration_service import (
    touch_workspace_presence,
    list_workspace_presence,
    list_audit_log,
    mark_all_notifications_read,
)
from src.workspace_service import (
    ensure_personal_workspace,
    list_members,
    list_invites,
    create_invite,
    cancel_invite,
    update_member_role,
    remove_member,
    update_workspace,
    list_activity,
    list_notifications,
    mark_notification_read,
    list_user_workspaces,
    get_workspace_by_id,
    get_active_workspace_preference,
    set_active_workspace_preference,
    create_organization_workspace,
)
try:
    import extra_streamlit_components as stx
except Exception:
    stx = None

# Streamlit must receive page config before any other UI/state rendering.
# Keep native Streamlit chrome hidden as early as possible to prevent page-nav flash.
st.set_page_config(
    page_title="Cadivor",
    page_icon="C",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    """
    <style>
    header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stSidebar"], [data-testid="collapsedControl"],
    section[data-testid="stSidebar"], div[data-testid="stSidebarNav"] {
        display: none !important; visibility: hidden !important; width: 0 !important; min-width: 0 !important;
    }
    .stApp { background: #F6F8FB !important; }
    .main .block-container, [data-testid="stAppViewContainer"] .main .block-container {
        padding-top: 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)




def load_user_data():
    user = st.session_state["user"]
    user_id = user.id

    response = (
        supabase.table("users")
        .select("*")
        .eq("id", user_id)
        .execute()
    )

    if response.data:
        return response.data[0]

    st.error("User profile not found. Please log out and create a new account.")
    st.stop()



def _safe_text(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def get_user_profile(current_user):
    """Return user-facing profile fields without assuming optional DB columns exist."""
    if not isinstance(current_user, dict):
        current_user = {}
    auth_user = st.session_state.get("user")
    metadata = getattr(auth_user, "user_metadata", {}) or {}

    email = _safe_text(current_user.get("email"), _safe_text(getattr(auth_user, "email", "")))
    full_name = _safe_text(
        current_user.get("full_name"),
        _safe_text(
            current_user.get("name"),
            _safe_text(metadata.get("full_name"), _safe_text(metadata.get("name"), "")),
        ),
    )
    first_name = _safe_text(current_user.get("first_name"), _safe_text(metadata.get("first_name"), ""))
    last_name = _safe_text(current_user.get("last_name"), _safe_text(metadata.get("last_name"), ""))
    if not full_name and (first_name or last_name):
        full_name = f"{first_name} {last_name}".strip()
    if not full_name and email:
        full_name = email.split("@")[0].replace(".", " ").replace("_", " ").title()

    company = _safe_text(
        current_user.get("company_name"),
        _safe_text(current_user.get("company"), _safe_text(metadata.get("company_name"), _safe_text(metadata.get("company"), ""))),
    )
    role_title = _safe_text(current_user.get("role_title"), _safe_text(current_user.get("job_title"), _safe_text(metadata.get("role_title"), "")))
    avatar_url = _safe_text(current_user.get("profile_image_url"), _safe_text(current_user.get("avatar_url"), _safe_text(metadata.get("avatar_url"), "")))
    phone = _safe_text(current_user.get("phone"), _safe_text(metadata.get("phone"), ""))
    country = _safe_text(current_user.get("country"), _safe_text(metadata.get("country"), ""))
    timezone = _safe_text(current_user.get("timezone"), _safe_text(metadata.get("timezone"), ""))
    workspace_name = _safe_text(current_user.get("workspace_name"), _safe_text(company, "Cadivor Workspace"))
    plan = _safe_text(current_user.get("plan"), "Starter")

    # Milestone 11A.1: overlay persistent customer profile fields when
    # the new profile migration is available.
    user_id = _safe_text(
        current_user.get("id"),
        _safe_text(getattr(auth_user, "id", "")),
    )
    if user_id:
        try:
            customer_profile, customer_profile_error = ensure_customer_profile(
                supabase,
                user_id,
                email,
                full_name,
            )
            if customer_profile and not customer_profile_error:
                full_name = _safe_text(
                    customer_profile.get("full_name"),
                    full_name,
                )
                company = _safe_text(
                    customer_profile.get("company_name"),
                    company,
                )
                role_title = _safe_text(
                    customer_profile.get("job_title"),
                    role_title,
                )
                avatar_url = _safe_text(
                    customer_profile.get("avatar_url"),
                    avatar_url,
                )
                phone = _safe_text(
                    customer_profile.get("phone"),
                    phone,
                )
                country = _safe_text(
                    customer_profile.get("country"),
                    country,
                )
                timezone = _safe_text(
                    customer_profile.get("timezone"),
                    timezone,
                )
        except Exception:
            pass

    initials_source = full_name or email or "Cadivor"
    initials = "".join([part[0] for part in initials_source.replace("@", " ").split()[:2]]).upper()[:2] or "C"
    return {
        "email": email,
        "full_name": full_name or "Cadivor user",
        "company": company,
        "role_title": role_title,
        "avatar_url": avatar_url,
        "phone": phone,
        "country": country,
        "timezone": timezone,
        "workspace_name": workspace_name,
        "plan": plan,
        "initials": initials,
    }


def update_user_profile_fields(user_id, updates):
    """Update only optional profile columns that already exist in the users table."""
    existing = set(current_user.keys()) if isinstance(current_user, dict) else set()
    allowed = {k: v for k, v in updates.items() if k in existing}
    skipped = [k for k in updates.keys() if k not in existing]
    if allowed:
        supabase.table("users").update(allowed).eq("id", user_id).execute()
    return allowed, skipped

def load_alternative_history(user_id):
    response = (
        _workspace_query(
            supabase.table("alternative_recommendations")
            .select("*")
        )
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data if response.data else []



def load_analysis_history(user_id):
    response = (
        _workspace_query(
            supabase.table("analyses")
            .select("*")
        )
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data if response.data else []


def _decision_context_key(analysis_id=None):
    """Return a stable decision scope for saved analyses or standalone searches."""
    if analysis_id is None:
        return "standalone"

    analysis_value = str(analysis_id).strip()
    return analysis_value if analysis_value else "standalone"


def _make_json_safe(value, _seen=None):
    """Convert nested supplier and pandas values into JSON-safe data.

    Circular references are replaced with a readable marker so Supabase's
    JSON encoder cannot fail while saving source/comparison snapshots.
    """
    if _seen is None:
        _seen = set()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    value_id = id(value)
    if value_id in _seen:
        return "[circular reference omitted]"

    if isinstance(value, dict):
        _seen.add(value_id)
        try:
            return {
                str(key): _make_json_safe(item, _seen)
                for key, item in value.items()
            }
        finally:
            _seen.discard(value_id)

    if isinstance(value, (list, tuple, set)):
        _seen.add(value_id)
        try:
            return [_make_json_safe(item, _seen) for item in value]
        finally:
            _seen.discard(value_id)

    if hasattr(value, "to_dict"):
        try:
            return _make_json_safe(value.to_dict(), _seen)
        except Exception:
            pass

    if hasattr(value, "item"):
        try:
            return _make_json_safe(value.item(), _seen)
        except Exception:
            pass

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass

    return str(value)


def save_analysis_decision(user_id, payload):
    """Insert or update a persistent Alternative Finder engineering decision."""
    if not user_id:
        raise ValueError("A signed-in user is required to save a decision.")

    original_part = str(payload.get("original_part", "")).strip()
    alternative_part = str(payload.get("alternative_part", "")).strip()
    analysis_id = payload.get("analysis_id")
    context_key = _decision_context_key(analysis_id)

    if not original_part or not alternative_part:
        raise ValueError("Original and alternative part numbers are required.")

    record = {
        "user_id": user_id,
        "workspace_id": active_workspace_id or None,
        "analysis_id": str(analysis_id).strip() if analysis_id else None,
        "context_key": context_key,
        "project_name": str(payload.get("project_name", "")).strip(),
        "engineer_name": str(payload.get("engineer_name", "")).strip(),
        "original_part": original_part,
        "alternative_part": alternative_part,
        "decision": str(payload.get("decision", "Saved")).strip() or "Saved",
        "engineering_note": str(payload.get("engineering_note", "")).strip(),
        "recommendation_score": int(payload.get("recommendation_score", 0) or 0),
        "recommendation_rating": str(payload.get("recommendation_rating", "")),
        "compatibility_confidence": int(
            payload.get("compatibility_confidence", 0) or 0
        ),
        "compatibility_rating": str(payload.get("compatibility_rating", "")),
        "lifecycle": str(payload.get("lifecycle", "")),
        "risk": str(payload.get("risk", "")),
        "supplier": str(payload.get("supplier", "")),
        "stock": int(float(payload.get("stock", 0) or 0)),
        "unit_price": float(payload.get("unit_price", 0) or 0),
        "package": str(payload.get("package", "")),
        "stock_delta": str(payload.get("stock_delta", "")),
        "price_delta": str(payload.get("price_delta", "")),
        "source_snapshot": _make_json_safe(
            payload.get("source_snapshot", {}) or {}
        ),
        "comparison_snapshot": _make_json_safe(
            payload.get("comparison_snapshot", {}) or {}
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    existing = (
        _workspace_query(
            supabase.table("analysis_decisions")
            .select("id")
        )
        .eq("user_id", user_id)
        .eq("context_key", context_key)
        .eq("original_part", original_part)
        .eq("alternative_part", alternative_part)
        .limit(1)
        .execute()
    )

    if existing.data:
        decision_id = existing.data[0]["id"]
        response = (
            supabase.table("analysis_decisions")
            .update(record)
            .eq("id", decision_id)
            .eq("user_id", user_id)
            .execute()
        )
    else:
        record["created_at"] = datetime.now(timezone.utc).isoformat()
        response = (
            supabase.table("analysis_decisions")
            .insert(record)
            .execute()
        )

    if not response.data:
        raise RuntimeError("Supabase did not return the saved decision.")

    return response.data[0]


def load_analysis_decisions(
    user_id,
    original_part=None,
    analysis_id=None,
    limit=25,
    include_all_contexts=False,
):
    """Load active engineering decisions, with optional cross-context history."""
    context_key = _decision_context_key(analysis_id)

    query = (
        _workspace_query(
            supabase.table("analysis_decisions")
            .select("*")
        )
        .eq("user_id", user_id)
        .is_("archived_at", "null")
    )

    if not include_all_contexts:
        query = query.eq("context_key", context_key)

    if original_part:
        query = query.eq("original_part", str(original_part).strip())

    response = (
        query.order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data if response.data else []


def archive_analysis_decision(user_id, decision_id):
    response = (
        _workspace_query(
            supabase.table("analysis_decisions")
            .update(
                {
                    "archived_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        .eq("id", decision_id)
        .eq("user_id", user_id)
        .execute()
    )
    return response.data if response.data else []


def generate_engineering_change_package_pdf(
    *,
    original_part,
    alternative_part,
    decision,
    engineering_note,
    recommendation_score,
    compatibility_confidence,
    lifecycle,
    risk,
    supplier,
    stock,
    unit_price,
    package,
    stock_delta,
    price_delta,
    engineer_name,
    project_name,
    comparison_snapshot=None,
):
    """Generate a wrapped, ECO-ready engineering change package PDF."""
    buffer = BytesIO()
    generated_at = datetime.now(timezone.utc)
    comparison_snapshot = comparison_snapshot or {}

    def _safe_list(value):
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        if value in (None, "", {}):
            return []
        return [str(value).strip()]

    matches = _safe_list(comparison_snapshot.get("engineering_matches", []))
    warnings = _safe_list(comparison_snapshot.get("warnings", []))
    advantages = _safe_list(comparison_snapshot.get("advantages", []))
    tradeoffs = _safe_list(comparison_snapshot.get("tradeoffs", []))

    combined_warnings = " ".join(warnings).lower()
    next_steps = []
    if any(word in combined_warnings for word in ("package", "mounting", "footprint")):
        next_steps.append("Verify PCB footprint, land pattern, and mounting constraints.")
    if "voltage" in combined_warnings:
        next_steps.append("Confirm voltage ratings against the circuit operating limits.")
    if any(word in combined_warnings for word in ("architecture", "channel")):
        next_steps.append("Validate the electrical architecture and functional behavior.")
    if "pin" in combined_warnings:
        next_steps.append("Confirm pin mapping before schematic or PCB release.")
    if any(word in combined_warnings for word in ("thermal", "power", "current")):
        next_steps.append("Review current, power dissipation, and thermal margins.")
    if compatibility_confidence < 70:
        next_steps.append("Complete bench validation before production approval.")
    if str(decision).lower() == "approved":
        next_steps.append("Update the BOM revision and retain this package with the change record.")
    elif str(decision).lower() == "rejected":
        next_steps.append("Document the rejection rationale and continue candidate review.")
    else:
        next_steps.append("Record an approval or rejection after engineering review.")

    unique_steps = []
    for step in next_steps:
        if step not in unique_steps:
            unique_steps.append(step)
    next_steps = unique_steps[:7]

    def _header_footer(canvas, doc):
        canvas.saveState()
        width, height = letter
        canvas.setFillColor(colors.HexColor("#2563EB"))
        canvas.rect(0, height - 12, width, 12, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#0F172A"))
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(42, height - 28, "CADIVOR")
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(42, height - 38, "ENGINEERING INTELLIGENCE")
        canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
        canvas.line(42, 31, width - 42, 31)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(
            42,
            19,
            f"{original_part} -> {alternative_part} - Engineering Change Package",
        )
        canvas.drawRightString(width - 42, 19, f"Page {doc.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=52,
        bottomMargin=42,
        title=f"Cadivor Engineering Change Package: {original_part} to {alternative_part}",
        author=str(engineer_name or "Cadivor"),
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("cadivor_pdf_title")
    title_style.fontName = "Helvetica-Bold"
    title_style.fontSize = 22
    title_style.leading = 26
    title_style.textColor = colors.HexColor("#0B1220")
    title_style.alignment = 0

    subtitle_style = styles["BodyText"].clone("cadivor_pdf_subtitle")
    subtitle_style.fontName = "Helvetica"
    subtitle_style.fontSize = 9.5
    subtitle_style.leading = 14
    subtitle_style.textColor = colors.HexColor("#475569")

    section_style = styles["Heading2"].clone("cadivor_pdf_section")
    section_style.fontName = "Helvetica-Bold"
    section_style.fontSize = 12
    section_style.leading = 15
    section_style.textColor = colors.HexColor("#0F172A")
    section_style.spaceBefore = 14
    section_style.spaceAfter = 8

    body_style = styles["BodyText"].clone("cadivor_pdf_body")
    body_style.fontName = "Helvetica"
    body_style.fontSize = 8.2
    body_style.leading = 10.4
    body_style.textColor = colors.HexColor("#334155")
    body_style.wordWrap = "CJK"

    compact_style = styles["BodyText"].clone("cadivor_pdf_compact")
    compact_style.fontName = "Helvetica"
    compact_style.fontSize = 7.4
    compact_style.leading = 9.2
    compact_style.textColor = colors.HexColor("#334155")
    compact_style.wordWrap = "CJK"

    small_style = styles["BodyText"].clone("cadivor_pdf_small")
    small_style.fontName = "Helvetica"
    small_style.fontSize = 7.2
    small_style.leading = 9
    small_style.textColor = colors.HexColor("#475569")
    small_style.wordWrap = "CJK"

    label_style = styles["BodyText"].clone("cadivor_pdf_label")
    label_style.fontName = "Helvetica-Bold"
    label_style.fontSize = 7.2
    label_style.leading = 9
    label_style.textColor = colors.HexColor("#0F172A")
    label_style.wordWrap = "CJK"

    header_cell_style = styles["BodyText"].clone("cadivor_pdf_header_cell")
    header_cell_style.fontName = "Helvetica-Bold"
    header_cell_style.fontSize = 7.5
    header_cell_style.leading = 9
    header_cell_style.textColor = colors.white
    header_cell_style.wordWrap = "CJK"

    def _clean_text(value):
        text_value = str(value if value is not None else "-")
        replacements = {
            "✓": "",
            "⚠": "",
            "ℹ": "",
            "●": "",
            "🔴": "",
            "🟢": "",
            "🟡": "",
            "■": "",
            "▪": "",
            "□": "-",
            "→": "to",
            "•": "-",
        }
        for old, new in replacements.items():
            text_value = text_value.replace(old, new)

        text_value = re.sub(
            r"^\s*(warning|match|advantage|trade[- ]?off)\s*:\s*",
            "",
            text_value,
            flags=re.IGNORECASE,
        )
        text_value = re.sub(r"\s+", " ", text_value).strip()
        return html.escape(text_value)

    def _p(value, style=body_style, bold=False, color=None):
        content = _clean_text(value)
        if bold:
            content = f"<b>{content}</b>"
        if color:
            content = f'<font color="{color}">{content}</font>'
        return Paragraph(content, style)

    def _bullet_block(items, prefix, empty_message, color, style=compact_style):
        if not items:
            return _p(empty_message, style)

        lines = []
        for item in items:
            cleaned_item = re.sub(
                r"^\s*(warning|match|advantage|trade[- ]?off)\s*:\s*",
                "",
                str(item),
                flags=re.IGNORECASE,
            )
            cleaned_item = cleaned_item.replace("■", "").replace("▪", "").strip()

            if prefix == "ADVANTAGE:":
                stock_match = re.search(
                    r"([0-9]+(?:\.[0-9]+)?)\s*[x×]\s*more stock",
                    cleaned_item,
                    flags=re.IGNORECASE,
                )
                cost_match = re.search(
                    r"([0-9]+(?:\.[0-9]+)?)%\s*lower cost",
                    cleaned_item,
                    flags=re.IGNORECASE,
                )
                if stock_match:
                    cleaned_item = (
                        f"Approximately {stock_match.group(1)}x greater supplier inventory"
                    )
                elif cost_match:
                    cleaned_item = (
                        f"Estimated unit cost reduced by {cost_match.group(1)}%"
                    )

            lines.append(
                f'<font color="{color}"><b>{html.escape(prefix)}</b></font> '
                f'{_clean_text(cleaned_item)}'
            )

        return Paragraph("<br/><br/>".join(lines), style)

    decision_upper = str(decision or "Pending review").upper()
    decision_color = {
        "APPROVED": "#059669",
        "REJECTED": "#DC2626",
        "SAVED": "#2563EB",
    }.get(decision_upper, "#D97706")

    story = [
        Spacer(1, 4),
        Paragraph("Engineering Change Package", title_style),
        Spacer(1, 4),
        Paragraph(
            "Formal component replacement review for design, sourcing, quality, "
            "and change-control documentation.",
            subtitle_style,
        ),
        Spacer(1, 16),
    ]

    summary = Table(
        [
            [
                _p("PROJECT", label_style),
                _p("ENGINEER", label_style),
                _p("DECISION DATE", label_style),
                _p("STATUS", label_style),
            ],
            [
                _p(project_name or "Standalone Alternative Finder", compact_style),
                _p(engineer_name or "Cadivor user", compact_style),
                _p(generated_at.strftime("%b %d, %Y - %H:%M UTC"), compact_style),
                _p(decision_upper, compact_style, bold=True, color=decision_color),
            ],
        ],
        colWidths=[145, 125, 145, 85],
    )
    summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(summary)

    story.append(Paragraph("Executive Decision Summary", section_style))
    decision_summary = Table(
        [
            [_p("Original Component", label_style), _p(original_part)],
            [_p("Selected Replacement", label_style), _p(alternative_part)],
            [_p("Recommendation Score", label_style), _p(f"{int(recommendation_score)}/100")],
            [_p("Compatibility Confidence", label_style), _p(f"{int(compatibility_confidence)}%")],
            [_p("Engineering Risk", label_style), _p(risk)],
            [_p("Lifecycle", label_style), _p(lifecycle)],
            [_p("Decision", label_style), _p(decision)],
        ],
        colWidths=[180, 320],
    )
    decision_summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(decision_summary)

    story.append(Paragraph("Sourcing and Package Impact", section_style))
    sourcing = Table(
        [
            [
                _p("Supplier", header_cell_style),
                _p("Available Stock", header_cell_style),
                _p("Unit Price", header_cell_style),
                _p("Package", header_cell_style),
            ],
            [
                _p(supplier, compact_style),
                _p(f"{int(stock):,}", compact_style),
                _p(f"${float(unit_price):.4g}", compact_style),
                _p(package, compact_style),
            ],
            [
                _p("Stock Impact", label_style),
                _p(stock_delta, compact_style),
                _p("Cost Impact", label_style),
                _p(price_delta, compact_style),
            ],
        ],
        colWidths=[120, 130, 120, 130],
    )
    sourcing.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
                ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                    colors.white,
                    colors.HexColor("#F8FAFC"),
                ]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(sourcing)

    story.append(Paragraph("Engineering Evidence", section_style))
    evidence = Table(
        [
            [_p("ENGINEERING MATCHES", label_style), _p("WARNINGS", label_style)],
            [
                _bullet_block(
                    matches,
                    "MATCH:",
                    "No confirmed engineering matches were recorded.",
                    "#059669",
                ),
                _bullet_block(
                    warnings,
                    "WARNING:",
                    "No material warnings were recorded.",
                    "#D97706",
                ),
            ],
            [_p("SOURCING ADVANTAGES", label_style), _p("TRADE-OFFS", label_style)],
            [
                _bullet_block(
                    advantages,
                    "ADVANTAGE:",
                    "No sourcing advantage was calculated.",
                    "#059669",
                ),
                _bullet_block(
                    tradeoffs,
                    "TRADE-OFF:",
                    "No significant trade-offs identified.",
                    "#DC2626",
                ),
            ],
        ],
        colWidths=[250, 250],
    )
    evidence.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 1), colors.HexColor("#ECFDF5")),
                ("BACKGROUND", (1, 0), (1, 1), colors.HexColor("#FFFBEB")),
                ("BACKGROUND", (0, 2), (0, 3), colors.HexColor("#ECFDF5")),
                ("BACKGROUND", (1, 2), (1, 3), colors.HexColor("#FEF2F2")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(evidence)

    comparison_rows = comparison_snapshot.get("comparison_table", [])
    if isinstance(comparison_rows, list) and comparison_rows:
        clean_rows = [
            [
                _p("Attribute", header_cell_style),
                _p("Original", header_cell_style),
                _p("Selected Alternative", header_cell_style),
            ]
        ]
        for row in comparison_rows[:18]:
            if isinstance(row, dict):
                clean_rows.append(
                    [
                        _p(row.get("Attribute", row.get("attribute", "")), compact_style, bold=True),
                        _p(row.get("Original", row.get("original", "")), compact_style),
                        _p(
                            row.get(
                                "Selected Alternative",
                                row.get("selected_alternative", ""),
                            ),
                            compact_style,
                        ),
                    ]
                )
        if len(clean_rows) > 1:
            story.append(Paragraph("Side-by-Side Comparison", section_style))
            comparison = Table(clean_rows, colWidths=[160, 165, 175], repeatRows=1)
            comparison.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                            colors.white,
                            colors.HexColor("#F8FAFC"),
                        ]),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.append(comparison)

    story.append(Paragraph("Engineering Review Notes", section_style))
    note_box = Table(
        [[_p(engineering_note or "No engineering review notes were recorded.", body_style)]],
        colWidths=[500],
    )
    note_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(note_box)

    story.append(Paragraph("Recommended Next Actions", section_style))
    actions = Table(
        [[_p(f"- {step}", body_style)] for step in next_steps],
        colWidths=[500],
    )
    actions.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#BFDBFE")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DBEAFE")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(actions)

    story.extend(
        [
            Spacer(1, 14),
            Paragraph(
                "This package documents the engineering review state at the time "
                "of generation. Final production release remains subject to the "
                "organization's approved change-control process.",
                small_style,
            ),
        ]
    )

    document.build(
        story,
        onFirstPage=_header_footer,
        onLaterPages=_header_footer,
    )
    buffer.seek(0)
    return buffer.getvalue()


def run_global_search(user_id, query, limit=8):
    """Search saved analyses, analysis parts, and alternative history for the dashboard command palette foundation."""
    query = (query or "").strip()
    if not query:
        return []

    q = query.lower()
    results = []

    try:
        analyses = load_analysis_history(user_id)
        for item in analyses:
            haystack = " ".join([
                str(item.get("project_name", "")),
                str(item.get("filename", "")),
                str(item.get("created_at", "")),
            ]).lower()
            if q in haystack:
                results.append({
                    "type": "BOM Analysis",
                    "title": item.get("project_name") or item.get("filename") or "Saved analysis",
                    "meta": f"{item.get('total_parts', 0)} parts • Health {item.get('health_score', '—')} • {item.get('created_at', '')}",
                    "page": "Dashboard",
                })
    except Exception:
        pass

    try:
        parts_response = (
            supabase.table("analysis_parts")
            .select("mpn,manufacturer,risk_level,lifecycle_status,analysis_id")
            .eq("user_id", user_id)
            .limit(100)
            .execute()
        )
        for part in parts_response.data or []:
            haystack = " ".join([
                str(part.get("mpn", "")),
                str(part.get("manufacturer", "")),
                str(part.get("risk_level", "")),
                str(part.get("lifecycle_status", "")),
            ]).lower()
            if q in haystack:
                results.append({
                    "type": "Component",
                    "title": part.get("mpn") or "Component",
                    "meta": f"{part.get('manufacturer', 'Unknown manufacturer')} • {part.get('risk_level', 'Unknown risk')} • {part.get('lifecycle_status', 'Unknown lifecycle')}",
                    "page": "BOM Analyzer",
                })
    except Exception:
        pass

    try:
        alternatives = load_alternative_history(user_id)
        for alt in alternatives:
            haystack = " ".join([
                str(alt.get("original_part", "")),
                str(alt.get("alternative_part", "")),
                str(alt.get("supplier", "")),
                str(alt.get("estimated_risk", "")),
            ]).lower()
            if q in haystack:
                results.append({
                    "type": "Alternative",
                    "title": f"{alt.get('original_part', '')} → {alt.get('alternative_part', '')}",
                    "meta": f"{alt.get('supplier', 'Unknown supplier')} • Score {alt.get('recommendation_score', '—')} • Stock {alt.get('stock', '—')}",
                    "page": "Alternative Finder",
                })
    except Exception:
        pass

    deduped = []
    seen = set()
    for result in results:
        key = (result.get("type"), result.get("title"), result.get("meta"))
        if key not in seen:
            deduped.append(result)
            seen.add(key)
    return deduped[:limit]


def render_global_search_panel(user_id):
    st.markdown(
        """
        <div class="cv-command-card cv-fade-in">
          <div class="cv-command-header">
            <div>
              <div class="cv-command-title">Global Search</div>
              <div class="cv-command-copy">Search BOMs, saved analyses, part numbers, suppliers, and alternatives. Command palette shortcut foundation: <span class="cv-kbd-inline">Ctrl</span> + <span class="cv-kbd-inline">K</span>.</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    search_query = st.text_input(
        "Search Cadivor workspace",
        value=st.session_state.get("global_search_query", ""),
        placeholder="Try a project name, part number, supplier, or risk level...",
        label_visibility="collapsed",
        key="global_search_query",
    )

    if search_query:
        results = run_global_search(user_id, search_query)
        if not results:
            empty_state(
                "No matching results",
                "Cadivor searched saved analyses, parts, alternatives, and suppliers but did not find a match.",
                "Analyze a BOM",
                "?page=BOM%20Analyzer",
                "⌕",
            )
        else:
            for result in results:
                page_href = str(result.get("page", "Dashboard")).replace(" ", "%20")
                st.markdown(
                    f"""
                    <div class="cv-result-card">
                      <div>
                        <div class="cv-result-title">{result.get('title', '')}</div>
                        <div class="cv-result-meta">{result.get('type', '')} • {result.get('meta', '')}</div>
                      </div>
                      <a class="cv-status-pill" href="?page={page_href}" target="_self">Open</a>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def generate_bom_pdf_report(project_name, selected_parts, attention_parts, bom_health_score, alternative_history=None):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Executive BOM Risk Report", styles["Title"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"Project: {project_name}", styles["Heading2"]))
    risk_status = "Low Risk"

    if bom_health_score < 50:
        risk_status = "High Risk"
    elif bom_health_score < 80:
        risk_status = "Moderate Risk"

    story.append(
        Paragraph(
            f"BOM Health Score: {bom_health_score} / 100",
            styles["Heading2"]
        )
    )

    story.append(
        Paragraph(
            f"Overall Status: {risk_status}",
            styles["Normal"]
        )
    )

    story.append(Spacer(1, 12))

    executive_summary = (
    "This BOM shows moderate supply-chain risk due to obsolete "
    "components, replacement-suggested parts, and limited supplier "
    "availability. Priority should be given to obsolete and high-risk "
    "components before production release."
    )

    
    if risk_status == "High Risk":
        executive_summary = (
            "This BOM contains significant supply-chain and lifecycle risk. "
            "Immediate review of obsolete, high-risk, and low-availability "
            "components is strongly recommended before manufacturing."
        )

    elif risk_status == "Low Risk":
        executive_summary = (
            "This BOM currently demonstrates healthy lifecycle and sourcing "
            "status with relatively low supply-chain risk exposure."
        )

    story.append(
        Paragraph(
            f"<b>Executive Summary:</b> {executive_summary}",
            styles["BodyText"]
        )
    )

    story.append(
        Paragraph(
            (
                "<b>AI Recommendation Insight:</b> "
                "The strongest replacement path identified was ATMEGA328P-AU due to "
                "architecture compatibility, similar pin count, strong supplier availability, "
                "and minimal migration complexity."
            ),
            styles["BodyText"],
        )
    )

    story.append(Spacer(1, 16))

    story.append(
        Paragraph(
            f"Total Parts: {len(selected_parts)}",
            styles["Normal"]
        )
    )

    story.append(
        Paragraph(
            f"High-Risk Parts: {(selected_parts['risk_level'] == 'High').sum()}",
            styles["Normal"]
        )
    )

    story.append(Spacer(1, 16))

    story.append(
        Paragraph("Parts Requiring Attention", styles["Heading2"])
    )

    if attention_parts.empty:
        story.append(
            Paragraph("No critical parts detected.", styles["Normal"])
        )

    else:
        table_data = [
            [
                "Part Number",
                "Manufacturer",
                "Risk Level",
                "Lifecycle Status",
            ]
        ]

        for _, row in attention_parts.head(10).iterrows():
            table_data.append(
                [
                    str(row.get("mpn", "")),
                    str(row.get("manufacturer", "")),
                    str(row.get("risk_level", "")),
                    str(row.get("lifecycle_status", "")),
                ]
            )

        table = Table(table_data)

        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )

        story.append(table)
    story.append(Spacer(1, 16))

    if alternative_history is None or alternative_history.empty:
        story.append(Paragraph("Supplier Verification", styles["Heading2"]))
        story.append(Paragraph("No saved supplier verification or alternative recommendations for this BOM.", styles["Normal"]))

    else:
        verification_history = alternative_history[
            alternative_history["original_part"] == alternative_history["alternative_part"]
        ]
        verification_history = verification_history.drop_duplicates(
            subset=["original_part", "supplier", "stock", "unit_price"]
        )

        true_alternative_history = alternative_history[
            alternative_history["original_part"] != alternative_history["alternative_part"]
        ]
        true_alternative_history = true_alternative_history.drop_duplicates(
            subset=["original_part", "alternative_part", "supplier", "stock", "unit_price"]
        )

        story.append(Paragraph("Supplier Verification", styles["Heading2"]))

        if verification_history.empty:
            story.append(Paragraph("No supplier verification records saved for this BOM.", styles["Normal"]))

        else:
            verification_table_data = [
                [
                    "Part Number",
                    "Supplier",
                    "Risk",
                    "Stock",
                    "Unit Price",
                ]
            ]

            for _, row in verification_history.head(10).iterrows():
                verification_table_data.append(
                    [
                        str(row.get("original_part", "")),
                        str(row.get("supplier", "")),
                        str(row.get("estimated_risk", "")),
                        str(row.get("stock", "")),
                        f"${float(row.get('unit_price', 0)):.2f}",
                    ]
                )

            verification_table = Table(verification_table_data)

            verification_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ]
                )
            )

            story.append(verification_table)

        story.append(Spacer(1, 16))
        story.append(Paragraph("Suggested Alternatives", styles["Heading2"]))

        if true_alternative_history.empty:
            story.append(Paragraph("No true alternative recommendations saved for this BOM.", styles["Normal"]))

        else:
            for original_part, group_df in true_alternative_history.groupby("original_part"):
                story.append(Paragraph(f"Alternatives for {original_part}", styles["Heading3"]))

                alt_table_data = [
                    [
                        "Alternative Part",
                        "Score",
                        "Risk",
                        "Supplier",
                        "Stock",
                        "Unit Price",
                    ]
                ]

                for _, row in group_df.head(5).iterrows():
                    alt_table_data.append(
                        [
                            str(row.get("alternative_part", "")),
                            str(row.get("recommendation_score", "")),
                            str(row.get("estimated_risk", "")),
                            str(row.get("supplier", "")),
                            str(row.get("stock", "")),
                            f"${float(row.get('unit_price', 0)):.2f}",

                        ]
                    )

                alt_table = Table(alt_table_data)

                alt_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ]
                    )
                )

                story.append(alt_table)
                story.append(Spacer(1, 10))

                for _, row in group_df.head(5).iterrows():
                    engineering_text = (
                        f"<b>{row.get('alternative_part', '')}</b><br/>"
                        f"Architecture: {row.get('architecture', '')}<br/>"
                        f"Package: {row.get('package', '')}<br/>"
                        f"Pin Count: {int(float(row.get('pin_count', 0) or 0))}<br/>"
                        f"Voltage Range: {row.get('voltage_range', '')}<br/>"
                        f"Compatibility Notes: {row.get('compatibility_notes', '')}<br/>"
                        f"Score Reasons: {row.get('score_reasons', '')}"
                    )

                    story.append(
                        Paragraph(
                            engineering_text,
                            styles["BodyText"],
                        )
                    )

                    story.append(Spacer(1, 8))

                best_engineering_row = group_df.loc[
                    group_df["recommendation_score"].astype(float).idxmax()
                ]

                story.append(
                    Paragraph(
                        (
                            f"<b>Best Engineering Recommendation:</b> "
                            f"{best_engineering_row['alternative_part']} "
                            f"with recommendation score of "
                            f"{best_engineering_row['recommendation_score']}."
                        ),
                        styles["BodyText"],
                    )
                )

                value_candidates = group_df[
                    group_df["stock"] > 0
                ]

                if not value_candidates.empty:
                    best_value_row = value_candidates.loc[
                        value_candidates["unit_price"].astype(float).idxmin()
                    ]

                    story.append(
                        Paragraph(
                            (
                                f"<b>Best Value Alternative:</b> "
                                f"{best_value_row['alternative_part']} "
                                f"— ${float(best_value_row['unit_price']):.2f} "
                                f"with available stock of {best_value_row['stock']} units."
                            ),
                            styles["BodyText"],
                        )
                    )

                story.append(Spacer(1, 14))

           
    doc.build(story)

    buffer.seek(0)

    return buffer

cookie_manager = stx.CookieManager(key="bom_cookie_manager") if stx else _FallbackCookieManager()

# -----------------------------------------------------------------------------
# Cadivor auth/session recovery
# -----------------------------------------------------------------------------
# Navigation uses query-string page changes. On Streamlit Cloud, those can create
# a fresh frontend session. Therefore the Supabase tokens MUST be persisted into
# the Cadivor auth cookie immediately after login, and restored before routing.
# This block is intentionally placed before app routing and before any page UI.


def _coerce_auth_cookie(raw_cookie):
    """Return a cookie dict whether CookieManager gives us dict, JSON, or None."""
    if not raw_cookie:
        return None
    if isinstance(raw_cookie, dict):
        return raw_cookie
    if isinstance(raw_cookie, str):
        try:
            import json
            parsed = json.loads(raw_cookie)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _persist_auth_cookie():
    """Persist current Supabase tokens so page navigation/refresh does not log out."""
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if not cookie_manager or not access_token or not refresh_token:
        return
    try:
        from datetime import datetime, timedelta
        cookie_manager.set(
            cookie="bom_auth",
            val={"access_token": access_token, "refresh_token": refresh_token},
            expires_at=datetime.utcnow() + timedelta(days=7),
            key="persist_bom_auth_cookie",
        )
    except TypeError:
        try:
            cookie_manager.set(
                cookie="bom_auth",
                val={"access_token": access_token, "refresh_token": refresh_token},
                key="persist_bom_auth_cookie",
            )
        except Exception:
            pass
    except Exception:
        pass




def _qp_value(name, default=""):
    """Safe query-param reader available before auth routing renders anything."""
    try:
        value = st.query_params.get(name, default)
        if isinstance(value, list):
            return value[0] if value else default
        return value or default
    except Exception:
        return default

# 1) Restore tokens from cookie only if this Streamlit session does not have them.
if "access_token" not in st.session_state or "refresh_token" not in st.session_state:
    raw_auth_cookie = cookie_manager.get(cookie="bom_auth") if cookie_manager else None
    auth_cookie = _coerce_auth_cookie(raw_auth_cookie)
    if auth_cookie and auth_cookie.get("access_token") and auth_cookie.get("refresh_token"):
        st.session_state["access_token"] = auth_cookie.get("access_token")
        st.session_state["refresh_token"] = auth_cookie.get("refresh_token")

# 2) Validate tokens with Supabase before deciding whether to show landing/auth.
if st.session_state.get("access_token") and st.session_state.get("refresh_token"):
    try:
        supabase.auth.set_session(
            st.session_state["access_token"],
            st.session_state["refresh_token"],
        )
        user_response = supabase.auth.get_user()
        if user_response and user_response.user:
            st.session_state["user"] = user_response.user
            st.session_state["cadivor_auth_restore_checked"] = True
            # Do not mark restore attempts as exhausted. If Streamlit creates a brief
            # fresh frontend session during navigation, we still want the neutral
            # loader to appear while CookieManager hydrates instead of flashing the
            # public landing/auth page.
            st.session_state["cadivor_auth_restore_attempts"] = 0
            _persist_auth_cookie()
    except Exception:
        # Tokens are invalid/expired. Remove them from session, but do not delete
        # the cookie here; the login/logout handlers own cookie deletion.
        st.session_state.pop("user", None)
        st.session_state.pop("access_token", None)
        st.session_state.pop("refresh_token", None)

# 3) If auth.py just logged in and set session_state tokens, persist them before
# any navigation link can create a fresh frontend session.
if st.session_state.get("user") and st.session_state.get("access_token") and st.session_state.get("refresh_token"):
    _persist_auth_cookie()

if "user" not in st.session_state:

    # CookieManager can hydrate several reruns late on Streamlit Cloud, especially
    # after query-string navigation or browser Back. During that window we must
    # NEVER render the public landing page because it creates the visible flash.
    # Instead, keep a neutral loader until either auth restores or we decide the
    # visitor is genuinely signed out.
    current_route = _qp_value("page", "") if "_qp_value" in globals() else ""
    recovery_key = f"{current_route}|{_qp_value('action', '') if '_qp_value' in globals() else ''}"
    if st.session_state.get("cadivor_auth_recovery_key") != recovery_key:
        st.session_state["cadivor_auth_recovery_key"] = recovery_key
        st.session_state["cadivor_auth_restore_attempts"] = 0

    attempts = int(st.session_state.get("cadivor_auth_restore_attempts", 0))
    should_buffer = bool(cookie_manager) and attempts < 8

    if should_buffer:
        st.session_state["cadivor_auth_restore_attempts"] = attempts + 1
        st.markdown(
            """
            <style>
            #MainMenu, footer, header, [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
            [data-testid="stStatusWidget"], .stDeployButton, [data-testid="stSidebar"], [data-testid="collapsedControl"],
            section[data-testid="stSidebar"], div[data-testid="stSidebarNav"] {
                display:none!important; visibility:hidden!important; width:0!important; min-width:0!important; height:0!important; min-height:0!important;
            }
            .stApp, [data-testid="stAppViewContainer"] { background:#F6F8FB!important; }
            .main .block-container, [data-testid="stMainBlockContainer"] { padding:0!important; margin:0!important; max-width:100%!important; }
            .cadivor-restore { min-height:100vh; display:flex; align-items:center; justify-content:center; color:#64748B; font-weight:800; }
            .cadivor-restore-card { background:#fff; border:1px solid #E5E7EB; border-radius:20px; padding:24px 28px; box-shadow:0 24px 70px rgba(15,23,42,.08); }
            </style>
            <div class="cadivor-restore"><div class="cadivor-restore-card">Loading Cadivor workspace…</div></div>
            """,
            unsafe_allow_html=True,
        )
        time.sleep(0.22)
        st.rerun()

    # If recovery did not restore a user, show auth only after the buffer. This
    # preserves public access for signed-out visitors while preventing navigation
    # flicker for signed-in users.
    try:
        show_auth_ui(supabase, cookie_manager)
    except TypeError:
        show_auth_ui(supabase)
    st.stop()



current_user = load_user_data()

is_admin = current_user.get("role") == "admin"



analysis_history = (
    supabase.table("analyses")
    .select("*")
    .eq("user_id", current_user["id"])
    .order("created_at", desc=True)
    .limit(10)
    .execute()
)


@st.cache_data(ttl=3600, show_spinner=False)
def get_part_data(row):
    part_number = row["mpn_normalized"]

    try:
        part_data = get_best_part_data(part_number)

    except Exception as e:
        part_data = {
            "mpn": part_number,
            "lifecycle_status": "Unknown",
            "stock_available": 0,
            "supplier_count": 0,
            "risk_score": 100,
            "risk_level": "High",
            "risk_reasons": f"Supplier lookup failed: {e}",
        }

    part_data["quantity"] = row.get("quantity", 0)

    try:
       alternative_part_numbers = suggest_alternatives_v2(part_number)

    except Exception:
        alternative_part_numbers = []

    part_data["has_alternates"] = len(alternative_part_numbers) > 0
    part_data["alternate_count"] = len(alternative_part_numbers)
    part_data["alternative_part_numbers"] = ", ".join(
        [
            alt.get("Alternative Part", str(alt))
            if isinstance(alt, dict)
            else str(alt)
            for alt in alternative_part_numbers
        ]
    )

    return part_data

def send_monitor_alert_email(to_email: str, subject: str, message: str):
    resend.api_key = st.secrets.get("RESEND_API_KEY")
    from_email = st.secrets.get(
        "ALERT_FROM_EMAIL",
        "Cadivor <onboarding@resend.dev>",
    )

    if not resend.api_key:
        raise ValueError("Missing RESEND_API_KEY in Streamlit secrets")

    return resend.Emails.send(
        {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": f"<p>{message}</p>",
        }
    )
def analyze_single_part(row):
    part_data = get_part_data(row)
    risk_result = calculate_risk(part_data)

    return {
        "MPN": row["mpn"],
        "Normalized MPN": row["mpn_normalized"],
        "Manufacturer": part_data.get("manufacturer", ""),
        "Manufacturer Part Number": part_data.get("manufacturer_part_number", ""),
        "Description": part_data.get("description", ""),
        "Quantity": row.get("quantity", 0),
        "Best Source": part_data.get("source", ""),
        "Supplier Count": part_data.get("supplier_count", 0),
        "Total Market Stock": part_data.get("total_market_stock", 0),
        "Sources Available": part_data.get("sources_available", ""),
        "Stock Available": part_data.get("stock_total", 0),
        "Lead Time Weeks": part_data.get("lead_time_weeks", None),
        "Lifecycle Status": part_data.get("lifecycle_status", "Unknown"),
        "Product URL": part_data.get("product_detail_url", ""),
        "Has Alternates": part_data.get("has_alternates", False),
        "Alternate Count": part_data.get("alternate_count", 0),
        "Alternative Part Numbers": part_data.get("alternative_part_numbers", ""),
        "Risk Score": risk_result["risk_score"],
        "Risk Level": risk_result["risk_level"],
        "Risk Reasons": "; ".join(risk_result["risk_reasons"]) or "No major risk found",
    }

def analyze_bom(df, progress_status=None, progress_bar=None):
    df = normalize_bom_columns(df)
    df = validate_bom(df)
    df = clean_bom_data(df)

    results = []
    total_parts = len(df)

    rows = [row for _, row in df.iterrows()]
    completed = 0

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_row = {
            executor.submit(analyze_single_part, row): row
            for row in rows
        }

        for future in as_completed(future_to_row):
            row = future_to_row[future]
            completed += 1

            if progress_status:
                progress_status.info(
                    f"Completed {completed} of {total_parts}: {row.get('mpn', '')}"
                )

            if progress_bar:
                progress_bar.progress(completed / total_parts)

            try:
                results.append(future.result(timeout=30))

            except Exception as e:
                results.append(
                    {
                        "MPN": row.get("mpn", ""),
                        "Normalized MPN": row.get("mpn_normalized", ""),
                        "Manufacturer": "",
                        "Manufacturer Part Number": "",
                        "Description": "",
                        "Quantity": row.get("quantity", 0),
                        "Best Source": "",
                        "Supplier Count": 0,
                        "Total Market Stock": 0,
                        "Sources Available": "",
                        "Stock Available": 0,
                        "Lead Time Weeks": None,
                        "Lifecycle Status": "Unknown",
                        "Product URL": "",
                        "Has Alternates": False,
                        "Alternate Count": 0,
                        "Alternative Part Numbers": "",
                        "Risk Score": 100,
                        "Risk Level": "High",
                        "Risk Reasons": f"Part analysis failed: {e}",
                    }
                )

    return pd.DataFrame(results)

def show_dashboard_summary(results_df):
    st.subheader("📊 BOM Risk Dashboard")

    total_parts = len(results_df)
    high_risk = (results_df["Risk Level"] == "High").sum()
    medium_risk = (results_df["Risk Level"] == "Medium").sum()
    low_risk = (results_df["Risk Level"] == "Low").sum()

    avg_risk_score = results_df["Risk Score"].mean()
    bom_health_score = max(0, round(100 - avg_risk_score))

    health_score = bom_health_score

    if health_score >= 90:
        health_status = "🟢 Excellent"
    elif health_score >= 75:
        health_status = "🟢 Healthy"
    elif health_score >= 60:
        health_status = "🟡 Moderate Risk"
    elif health_score >= 40:
        health_status = "🟠 High Risk"
    else:
        health_status = "🔴 Critical"

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "BOM Health Score",
        f"{health_score}/100",
        health_status,
    )
    col2.metric("Total Parts", total_parts)
    col3.metric("High Risk", high_risk)
    col4.metric("Medium Risk", medium_risk)

    

    st.divider()

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Risk Breakdown")
        risk_counts = results_df["Risk Level"].value_counts()
        st.bar_chart(risk_counts)

    with col_b:
        st.subheader("Lifecycle Breakdown")
        lifecycle_counts = results_df["Lifecycle Status"].value_counts()
        st.bar_chart(lifecycle_counts)

    st.divider()

    st.subheader("🚨 Top Critical Parts")

    top_risks = results_df.sort_values(
        by="Risk Score",
        ascending=False
    ).head(5)

    st.dataframe(
        top_risks[
            [
                "MPN",
                "Manufacturer",
                "Risk Score",
                "Risk Level",
                "Stock Available",
                "Supplier Count",
                "Risk Reasons",
            ]
        ].reset_index(drop=True),
        use_container_width=True,
    )
    st.divider()

    st.subheader("✅ Recommended Actions")

    recommended_actions = []

    single_source_count = len(
        results_df[results_df["Supplier Count"] <= 1]
    )

    no_stock_count = len(
        results_df[results_df["Stock Available"] == 0]
    )

    unknown_lifecycle_count = len(
        results_df[
            results_df["Lifecycle Status"]
            .astype(str)
            .str.contains("unknown", case=False, na=False)
        ]
    )

    replacement_suggested_count = len(
        results_df[
            results_df["Lifecycle Status"]
            .astype(str)
            .str.contains("replacement", case=False, na=False)
        ]
    )

    if high_risk > 0:
        recommended_actions.append(
            f"🔴 Immediate review required for {high_risk} high-risk parts before production release."
        )

    if no_stock_count > 0:
        recommended_actions.append(
            f"📦 {no_stock_count} parts currently have no available stock. Procurement escalation recommended."
        )

    if single_source_count > 0:
        recommended_actions.append(
            f"⚠️ {single_source_count} parts rely on a single supplier. Evaluate secondary sourcing options."
        )

    if unknown_lifecycle_count > 0:
        recommended_actions.append(
            f"❓ {unknown_lifecycle_count} parts have unknown lifecycle status and require manufacturer verification."
        )

    if replacement_suggested_count > 0:
        recommended_actions.append(
            f"🔄 Replacement candidates were identified for {replacement_suggested_count} components."
        )

    if not recommended_actions:
        recommended_actions.append(
            "✅ No immediate sourcing risks detected. Continue periodic monitoring of lifecycle and stock availability."
        )

    for action in recommended_actions:
        st.write(f"• {action}")
    
    st.subheader("🧾 Executive Summary")

    summary_parts = []

    summary_parts.append(
        f"This BOM contains {total_parts} components with an overall health score of {health_score}/100, classified as {health_status}."
    )

    if high_risk > 0:
        summary_parts.append(
            f"{high_risk} high-risk components require immediate review before production release."
        )

    if no_stock_count > 0:
        summary_parts.append(
            f"{no_stock_count} components currently show no available stock, which may create procurement delays."
        )

    if single_source_count > 0:
        summary_parts.append(
            f"{single_source_count} components appear to rely on a single supplier, increasing sourcing risk."
        )

    if unknown_lifecycle_count > 0:
        summary_parts.append(
            f"{unknown_lifecycle_count} components have unknown lifecycle status and should be verified with the manufacturer or distributor."
        )

    if not recommended_actions:
        summary_parts.append(
            "No immediate sourcing risks were detected, but periodic monitoring is still recommended."
        )

    st.info(" ".join(summary_parts))


def risk_badge(level):
    if level == "High":
        return "🔴 High"
    elif level == "Medium":
        return "🟡 Medium"
    elif level == "Low":
        return "🟢 Low"
    return "⚪ Unknown"


def use_chart_dark_layout(fig, height=360):
    # Kept function name for compatibility, but use a premium light chart style.
    fig.update_layout(
        height=height,
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#FFFFFF",
        font=dict(color="#0F172A"),
        margin=dict(l=40, r=25, t=30, b=40),
    )
    fig.update_xaxes(gridcolor="#E5E7EB", zerolinecolor="#E5E7EB")
    fig.update_yaxes(gridcolor="#E5E7EB", zerolinecolor="#E5E7EB")
    return fig


def brc_page_hero(title="Welcome back", subtitle="Monitor BOM risk, review recent analyses, and keep sourcing decisions moving from one executive dashboard."):
    st.markdown(
        f'<div class="brc-hero"><div class="brc-eyebrow">BOM Risk Intelligence</div><div class="brc-hero-title">{title}</div><p class="brc-hero-subtitle">{subtitle}</p></div>',
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <style>
    :root {
        --brc-bg:#F5F7FB; --brc-surface:#FFFFFF; --brc-navy:#0F172A; --brc-muted:#64748B;
        --brc-border:#E2E8F0; --brc-blue:#2563EB; --brc-blue-soft:#EFF6FF;
        --brc-green:#2563EB; --brc-red:#EF4444; --brc-orange:#F59E0B;
        --brc-shadow:0 18px 45px rgba(15,23,42,.08);
    }
    html, body, [data-testid="stAppViewContainer"] { background:var(--brc-bg)!important; color:var(--brc-navy)!important; }
    [data-testid="stHeader"] { background:rgba(255,255,255,.88)!important; border-bottom:1px solid var(--brc-border)!important; }
    [data-testid="stSidebar"] { display:none!important; }
    [data-testid="collapsedControl"] { display:none!important; }
    .block-container { max-width:100%!important; padding-top:1.25rem!important; padding-left:1.15rem!important; padding-right:1.15rem!important; }
    h1,h2,h3,h4,h5,h6 { color:var(--brc-navy)!important; letter-spacing:-.03em; }
    p,label,span,div,.stMarkdown,.stCaptionContainer { color:var(--brc-muted); }

    .brc-hero { background:linear-gradient(135deg,#fff 0%,#EEF6FF 100%); border:1px solid var(--brc-border); border-radius:18px; box-shadow:var(--brc-shadow); padding:26px 30px; margin:0 0 18px 0; }
    .brc-eyebrow { display:inline-flex; background:var(--brc-blue-soft); color:var(--brc-blue)!important; font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; border-radius:999px; padding:7px 12px; margin-bottom:22px; }
    .brc-hero-title { color:var(--brc-navy)!important; font-size:34px; font-weight:850; line-height:1.05; margin:0 0 14px 0; }
    .brc-hero-subtitle { color:#52647A!important; font-size:17px; line-height:1.7; max-width:780px; margin:0; }

    .card,.kpi-card,.brc-card { background:#fff!important; border:1px solid var(--brc-border)!important; border-radius:16px!important; box-shadow:var(--brc-shadow)!important; padding:22px!important; margin-top:8px; margin-bottom:14px; }
    .card-title,.kpi-label { font-size:12px!important; font-weight:800!important; letter-spacing:.07em!important; text-transform:uppercase!important; color:#64748B!important; margin-bottom:12px!important; }
    .card-text,.kpi-note { font-size:13px!important; color:#334155!important; font-weight:700!important; }
    .kpi-value { font-size:32px!important; font-weight:850!important; color:var(--brc-navy)!important; margin-bottom:8px!important; line-height:1.05!important; }

    div.stButton > button, div.stDownloadButton > button { background:var(--brc-blue)!important; color:#FFFFFF!important; border:1px solid var(--brc-blue)!important; border-radius:10px!important; min-height:42px!important; padding:.55rem 1.05rem!important; font-weight:750!important; box-shadow:0 12px 24px rgba(37,99,235,.20)!important; width:auto!important; min-width:150px!important; }
    div.stButton > button:hover, div.stDownloadButton > button:hover { background:#1D4ED8!important; border-color:#1D4ED8!important; color:#FFFFFF!important; }
    div.stButton > button *, div.stDownloadButton > button * { color:#FFFFFF!important; }
    div.stButton > button:disabled,
    div.stDownloadButton > button:disabled {
        background:#E2E8F0!important;
        border-color:#CBD5E1!important;
        color:#94A3B8!important;
        box-shadow:none!important;
        cursor:not-allowed!important;
        opacity:1!important;
    }
    div.stButton > button:disabled *,
    div.stDownloadButton > button:disabled * {
        color:#94A3B8!important;
    }
    [data-testid="stSidebar"] div.stButton > button { width:100%!important; min-width:0!important; }

    div[data-testid="stTextInput"] input, div[data-testid="stSelectbox"] div[data-baseweb="select"], div[data-testid="stFileUploader"] section { background:#fff!important; border:1px solid #CBD5E1!important; border-radius:10px!important; color:var(--brc-navy)!important; }
    

    .stDataFrame,[data-testid="stDataFrame"] { border:1px solid var(--brc-border)!important; border-radius:8px!important; overflow:hidden!important; box-shadow:0 12px 30px rgba(15,23,42,.06)!important; background:#fff!important; }
    [data-testid="stDataFrame"] * { color:var(--brc-navy)!important; }
    [data-testid="stDataFrame"] [role="columnheader"], [data-testid="stDataFrame"] thead tr th { background:#F6F8FA!important; color:#475569!important; border-bottom:1px solid var(--brc-border)!important; font-weight:750!important; }
    [data-testid="stDataFrame"] [role="gridcell"], [data-testid="stDataFrame"] tbody tr td { background:#fff!important; color:var(--brc-navy)!important; border-bottom:1px solid #EEF2F7!important; }
    div[data-testid="stAlert"] { border-radius:12px!important; border:1px solid var(--brc-border)!important; }
    /* Cadivor v2.5 polished tables */
    [data-testid="stDataFrame"] { border-radius:14px!important; border:1px solid #E2E8F0!important; box-shadow:0 12px 30px rgba(15,23,42,.045)!important; }
    [data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] { background:#F8FAFC!important; }

    @media(max-width:900px){ .block-container{padding-left:1.1rem!important;padding-right:1.1rem!important;} .brc-hero-title{font-size:32px;} }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- Cadivor App Navigation / Workspace Shell ----------
NAV_OPTIONS = [
    "Dashboard",
    "BOM Analyzer",
    "Alternative Finder",
    "Monitoring",
    "Engineering Decisions",
    "Procurement Advisor",
    "Portfolio Intelligence",
    "Design Impact Analyzer",
    "Cost Optimization",
    "Reports",
    "Pricing",
    "Settings",
    "Workspace",
    "Notifications",
    "Help",
    "About",
]

if _qp_value("action") == "logout":
    if cookie_manager:
        cookie_manager.delete(cookie="bom_auth", key="delete_bom_auth_from_shell")
    supabase.auth.sign_out()
    st.session_state.clear()
    try:
        st.query_params.clear()
    except Exception:
        pass
    st.rerun()

if _qp_value("action") == "clear":
    st.session_state.pop("results_df", None)
    st.session_state.pop("uploaded_filename", None)
    try:
        st.query_params["page"] = _qp_value("page", "Dashboard")
        del st.query_params["action"]
    except Exception:
        pass

# Default user plan
selected_plan_name = current_user["plan"]
selected_plan = get_plan(selected_plan_name)
monthly_upload_count = current_user["monthly_upload_count"]

# Milestone 11B.2 — active organization data context.
_context_user_id = _safe_text(current_user.get("id"), "")
_context_email = _safe_text(current_user.get("email"), "")
_context_name = _safe_text(
    current_user.get("full_name"),
    _context_email or "Cadivor user",
)
_context_company = (
    _safe_text(current_user.get("company"), "")
    or _safe_text(current_user.get("company_name"), "")
    or "Cadivor"
)
_context_workspace_name = (
    _context_company
    if _context_company.lower().endswith("workspace")
    else f"{_context_company} Workspace"
)

_default_context_workspace, _default_context_error = ensure_personal_workspace(
    supabase,
    _context_user_id,
    _context_email,
    _context_name,
    _context_workspace_name,
    selected_plan_name,
)

_context_workspaces, _context_workspaces_error = list_user_workspaces(
    supabase,
    _context_user_id,
)
_preferred_context_workspace_id, _context_preference_error = (
    get_active_workspace_preference(
        supabase,
        _context_user_id,
    )
)

_context_available_ids = {
    str(item.get("id"))
    for item in (_context_workspaces or [])
    if item.get("id")
}
_context_requested_id = str(
    st.session_state.get("active_workspace_id")
    or _preferred_context_workspace_id
    or ""
)

if _context_requested_id in _context_available_ids:
    active_workspace, _active_workspace_error = get_workspace_by_id(
        supabase,
        _context_user_id,
        _context_requested_id,
    )
else:
    active_workspace = _default_context_workspace or (
        _context_workspaces[0] if _context_workspaces else {}
    )

active_workspace = active_workspace or {}
active_workspace_id = str(active_workspace.get("id") or "")
active_workspace_name = _safe_text(
    active_workspace.get("name"),
    "Cadivor Workspace",
)
active_workspace_role = _safe_text(
    active_workspace.get("current_role"),
    "owner",
).lower()

if active_workspace_id:
    st.session_state["active_workspace_id"] = active_workspace_id
    st.session_state["active_workspace_name"] = active_workspace_name
    st.session_state["active_workspace_role"] = active_workspace_role


def _workspace_query(query):
    if active_workspace_id:
        return query.eq("workspace_id", active_workspace_id)
    return query


def _workspace_payload(payload):
    result = dict(payload or {})
    if active_workspace_id:
        result["workspace_id"] = active_workspace_id
    return result


saved_bom_count_response = (
    _workspace_query(
        supabase.table("analyses")
        .select("id", count="exact")
    )
    .eq("user_id", current_user["id"])
    .execute()
)
saved_bom_count = saved_bom_count_response.count or 0

if "pending_app_mode" in st.session_state:
    app_mode = st.session_state.pop("pending_app_mode")
    try:
        st.query_params["page"] = app_mode
    except Exception:
        pass
else:
    app_mode = _qp_value("page", st.session_state.get("app_mode", "Dashboard"))

if app_mode not in NAV_OPTIONS and app_mode not in {"Analysis Details", "Onboarding"}:
    app_mode = "Dashboard"
st.session_state["app_mode"] = app_mode

profile_for_shell = get_user_profile(current_user) if "get_user_profile" in globals() else current_user

auth_user_for_onboarding = st.session_state.get("user")
onboarding_user_id = _safe_text(
    getattr(auth_user_for_onboarding, "id", ""),
    _safe_text(current_user.get("id"), ""),
)
onboarding_progress = {}
onboarding_error = None
if onboarding_user_id:
    onboarding_progress, onboarding_error = ensure_onboarding_progress(
        supabase,
        onboarding_user_id,
    )
    onboarding_progress = onboarding_progress or {}

    # Synchronize steps that can be inferred from existing Cadivor data.
    inferred_profile_complete = bool(
        profile_for_shell.get("full_name")
        and (
            profile_for_shell.get("company")
            or profile_for_shell.get("company_name")
            or profile_for_shell.get("role_title")
        )
    )
    inferred_workspace_complete = False
    try:
        inferred_workspace_complete = bool(
            supabase.table("workspace_members")
            .select("workspace_id")
            .eq("user_id", onboarding_user_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        pass

    inferred_alternative_complete = False
    try:
        inferred_alternative_complete = bool(
            _workspace_query(
                supabase.table("analysis_decisions")
                .select("id")
            )
            .eq("user_id", onboarding_user_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        pass

    sync_updates = {
        "profile_completed": inferred_profile_complete,
        "workspace_completed": inferred_workspace_complete,
        "first_bom_completed": saved_bom_count > 0,
        "first_alternative_completed": inferred_alternative_complete,
        "first_report_completed": bool(
            st.session_state.get("reports_session_history")
        ),
    }
    if any(
        bool(onboarding_progress.get(key)) != bool(value)
        for key, value in sync_updates.items()
    ):
        synced, sync_error = update_onboarding_progress(
            supabase,
            onboarding_user_id,
            sync_updates,
        )
        if synced and not sync_error:
            onboarding_progress = synced
shell_name = profile_for_shell.get("full_name") or profile_for_shell.get("email", "Cadivor User").split("@")[0].title()
shell_company = profile_for_shell.get("company_name") or profile_for_shell.get("company") or selected_plan_name
shell_email = profile_for_shell.get("email") or current_user.get("email", "")
shell_initials = "".join([part[0] for part in shell_name.split()[:2]]).upper()[:2] or "C"

import urllib.parse as _urlparse

# ---------- Cadivor Stable Shell ----------
# Single shell authority: load one CSS system, render fixed topbar/sidebar, then page content.
# Previous Milestone 4 patches stacked multiple CSS/JS shell blocks here, creating the large top gap.
inject_premium_css()
inject_v32_ux_css()
st.markdown(readability_css(), unsafe_allow_html=True)
apply_milestone10a_design_system()

_nav_icons = {
    "Dashboard":"⌂", "BOM Analyzer":"▦", "Alternative Finder":"⇄", "Monitoring":"◷",
    "Engineering Decisions":"◆", "Procurement Advisor":"$", "Portfolio Intelligence":"◈", "Design Impact Analyzer":"◇", "Cost Optimization":"$", "Reports":"□", "Pricing":"$", "Settings":"⚙", "Workspace":"•", "Notifications":"•",
    "Help":"?", "About":"?"
}
_nav_html = []
for _nav in NAV_OPTIONS:
    _active = " active" if _nav == app_mode else ""
    _href = "?page=" + _urlparse.quote(_nav)
    _nav_html.append(f'<a class="cv-side-link{_active}" href="{_href}" target="_self"><span>{_nav_icons.get(_nav,"•")}</span>{_nav}</a>')

render_topbar(profile_for_shell, app_mode)

st.markdown(
    f"""
    <div id="cadivor-sidebar-root" class="cv-app-sidebar">
      <div class="cv-side-brand"><div class="cv-side-logo">C</div><div><div class="cv-side-name">Cadivor</div><div class="cv-side-sub">Engineering Intelligence</div></div></div>
      <div class="cv-side-section first">Navigation</div>
      <nav class="cv-side-nav">{''.join(_nav_html)}</nav>
      <div class="cv-side-section">Workspace</div>
      <div class="cv-side-plan"><strong>{selected_plan_name}</strong><span>{monthly_upload_count} / {selected_plan['monthly_bom_limit']} BOMs this month</span><span>{saved_bom_count} / {selected_plan['max_saved_boms']} saved BOMs</span></div>
      <div class="cv-side-footer"><a href="?action=clear&page={_urlparse.quote(app_mode)}" target="_self">Clear Analysis</a><a href="?action=logout" target="_self">Log out</a></div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Final deterministic shell rule. Do not add JavaScript layout patches above this line.
st.markdown(
    """
    <style id="cadivor-shell-gap-deterministic-fix">
    :root { --cv-topbar-height:64px!important; --cv-sidebar-width:284px!important; }

    /* Shell HTML is fixed-position chrome. Its Streamlit wrapper rows must not take page space. */
    .element-container:has(#cadivor-topbar-root),
    .element-container:has(#cadivor-sidebar-root),
    div[data-testid="stMarkdownContainer"]:has(#cadivor-topbar-root),
    div[data-testid="stMarkdownContainer"]:has(#cadivor-sidebar-root) {
        display:contents!important;
        height:0!important;
        min-height:0!important;
        margin:0!important;
        padding:0!important;
    }

    header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stStatusWidget"], .stDeployButton, [data-testid="collapsedControl"],
    [data-testid="stSidebar"], section[data-testid="stSidebar"], div[data-testid="stSidebarNav"] {
        display:none!important; visibility:hidden!important; width:0!important; height:0!important; min-height:0!important;
    }

    [data-testid="stAppViewContainer"], [data-testid="stMain"], section.main, .main {
        margin:0!important; padding:0!important; width:100vw!important; max-width:100vw!important; background:#F6F8FB!important;
    }

    .main .block-container, [data-testid="stMainBlockContainer"] {
        max-width:none!important;
        width:100%!important;
        box-sizing:border-box!important;
        margin:0!important;
        padding-top:84px!important;
        padding-left:306px!important;
        padding-right:24px!important;
        padding-bottom:48px!important;
    }

    .cv-command-hero:first-child { margin-top:0!important; }

    @media(max-width:1100px){
        .cadivor-topbar, #cadivor-topbar-root, .cv-app-sidebar, #cadivor-sidebar-root{
            position:relative!important; top:auto!important; left:auto!important; right:auto!important; width:auto!important; height:auto!important;
        }
        .main .block-container, [data-testid="stMainBlockContainer"]{padding:16px!important;}
        .element-container:has(#cadivor-topbar-root), .element-container:has(#cadivor-sidebar-root){display:block!important;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# Milestone 11A.3 — universal Streamlit button contrast repair.
st.markdown(
    """
    <style id="cadivor-button-contrast-v11a3">
    /* Primary buttons */
    button[data-testid="stBaseButton-primary"],
    div.stButton > button[kind="primary"],
    div.stDownloadButton > button {
        background:#2563EB !important;
        border:1px solid #2563EB !important;
        color:#FFFFFF !important;
        -webkit-text-fill-color:#FFFFFF !important;
        opacity:1 !important;
        box-shadow:0 10px 24px rgba(37,99,235,.20) !important;
    }

    button[data-testid="stBaseButton-primary"] *,
    div.stButton > button[kind="primary"] *,
    div.stDownloadButton > button * {
        color:#FFFFFF !important;
        -webkit-text-fill-color:#FFFFFF !important;
        opacity:1 !important;
    }

    /* Secondary/internal navigation buttons */
    button[data-testid="stBaseButton-secondary"],
    div.stButton > button[kind="secondary"] {
        background:#FFFFFF !important;
        border:1px solid #93C5FD !important;
        color:#1D4ED8 !important;
        -webkit-text-fill-color:#1D4ED8 !important;
        opacity:1 !important;
        box-shadow:0 8px 18px rgba(37,99,235,.08) !important;
    }

    button[data-testid="stBaseButton-secondary"] *,
    div.stButton > button[kind="secondary"] * {
        color:#1D4ED8 !important;
        -webkit-text-fill-color:#1D4ED8 !important;
        opacity:1 !important;
    }

    button[data-testid="stBaseButton-secondary"]:hover,
    div.stButton > button[kind="secondary"]:hover {
        background:#EFF6FF !important;
        border-color:#2563EB !important;
        color:#1D4ED8 !important;
    }

    /* Disabled controls remain readable. */
    button:disabled,
    button[disabled] {
        background:#E2E8F0 !important;
        border-color:#CBD5E1 !important;
        color:#64748B !important;
        -webkit-text-fill-color:#64748B !important;
        opacity:1 !important;
        box-shadow:none !important;
    }

    button:disabled *,
    button[disabled] * {
        color:#64748B !important;
        -webkit-text-fill-color:#64748B !important;
        opacity:1 !important;
    }

    /* Explicit protection for the new customer-experience controls. */
    [class*="st-key-onboarding_"] button,
    .st-key-settings_open_onboarding button,
    .st-key-settings_open_workspace button,
    .st-key-settings_view_plans button,
    [class*="st-key-reports_open_"] button,
    [class*="st-key-analysis_open_"] button,
    [class*="st-key-analysis_find_"] button,
    [class*="st-key-analysis_monitor_"] button {
        min-height:42px !important;
        font-weight:850 !important;
    }

    [class*="st-key-onboarding_"] button p,
    .st-key-settings_open_onboarding button p,
    .st-key-settings_open_workspace button p,
    .st-key-settings_view_plans button p,
    [class*="st-key-reports_open_"] button p,
    [class*="st-key-analysis_open_"] button p,
    [class*="st-key-analysis_find_"] button p,
    [class*="st-key-analysis_monitor_"] button p {
        visibility:visible !important;
        opacity:1 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- Customer Onboarding ----------
if app_mode == "Onboarding":
    progress = onboarding_progress or {}
    completed_steps = completion_count(progress)
    total_steps = 5
    percent_complete = int((completed_steps / total_steps) * 100)

    st.markdown(
        """
        <style id="cadivor-onboarding-v11a2">
        .cv-onboard-hero{
            border:1px solid #BFDBFE;
            border-radius:26px;
            padding:30px 32px;
            background:
                radial-gradient(circle at 92% 8%,rgba(37,99,235,.14),transparent 34%),
                linear-gradient(135deg,#FFFFFF 0%,#F7FAFF 100%);
            box-shadow:0 22px 54px rgba(15,23,42,.07);
            margin-bottom:18px;
        }
        .cv-onboard-kicker{
            color:#2563EB;font-size:10px;font-weight:950;
            letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px;
        }
        .cv-onboard-title{
            color:#0F172A;font-size:36px;line-height:1.06;font-weight:950;
            letter-spacing:-.045em;margin:0 0 10px;
        }
        .cv-onboard-copy{
            color:#52647A;font-size:14px;line-height:1.6;font-weight:690;
            max-width:860px;margin:0;
        }
        .cv-onboard-progress{
            height:10px;border-radius:999px;background:#E2E8F0;
            overflow:hidden;margin-top:20px;
        }
        .cv-onboard-progress i{
            display:block;height:100%;border-radius:999px;background:#2563EB;
        }
        .cv-onboard-progress-copy{
            color:#475569;font-size:11px;font-weight:850;margin-top:8px;
        }
        .cv-onboard-grid{
            display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
            gap:14px;margin:18px 0;
        }
        .cv-onboard-card{
            border:1px solid #E2E8F0;border-radius:19px;background:#FFFFFF;
            padding:18px;box-shadow:0 13px 34px rgba(15,23,42,.05);
        }
        .cv-onboard-card.done{border-color:#A7F3D0;background:#F0FDF4}
        .cv-onboard-step{
            color:#2563EB;font-size:9px;font-weight:950;letter-spacing:.1em;
            text-transform:uppercase;margin-bottom:7px;
        }
        .cv-onboard-card h3{
            color:#0F172A;font-size:16px;font-weight:950;margin:0 0 7px;
        }
        .cv-onboard-card p{
            color:#64748B;font-size:11px;line-height:1.5;font-weight:720;margin:0;
        }
        .cv-onboard-status{
            display:inline-flex;margin-top:12px;border-radius:999px;padding:5px 8px;
            font-size:9px;font-weight:950;background:#EFF6FF;color:#1D4ED8;
            border:1px solid #BFDBFE;
        }
        .cv-onboard-card.done .cv-onboard-status{
            background:#ECFDF5;color:#047857;border-color:#A7F3D0;
        }
        @media(max-width:760px){.cv-onboard-grid{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <section class="cv-onboard-hero">
          <div class="cv-onboard-kicker">Welcome to Cadivor</div>
          <h1 class="cv-onboard-title">Set up your engineering workspace.</h1>
          <p class="cv-onboard-copy">
            Complete these guided steps to personalize Cadivor, establish your
            workspace, analyze a BOM, review a replacement, and generate a report.
          </p>
          <div class="cv-onboard-progress"><i style="width:{percent_complete}%"></i></div>
          <div class="cv-onboard-progress-copy">
            {completed_steps} of {total_steps} steps complete · {percent_complete}%
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    steps = [
        (
            "1",
            "Complete your profile",
            "Add your company, title, time zone, and customer preferences.",
            bool(progress.get("profile_completed")),
        ),
        (
            "2",
            "Configure the workspace",
            "Confirm the workspace identity, settings, and collaboration foundation.",
            bool(progress.get("workspace_completed")),
        ),
        (
            "3",
            "Analyze your first BOM",
            "Upload a CSV or Excel BOM and save its engineering risk analysis.",
            bool(progress.get("first_bom_completed")),
        ),
        (
            "4",
            "Review a replacement",
            "Compare an alternative component and save an engineering decision.",
            bool(progress.get("first_alternative_completed")),
        ),
        (
            "5",
            "Generate a report",
            "Create an executive or engineering report for a saved BOM.",
            bool(progress.get("first_report_completed")),
        ),
    ]

    cards = []
    for number, title, copy, done in steps:
        cards.append(
            f'<div class="cv-onboard-card {"done" if done else ""}">'
            f'<div class="cv-onboard-step">Step {number}</div>'
            f'<h3>{html.escape(title)}</h3>'
            f'<p>{html.escape(copy)}</p>'
            f'<span class="cv-onboard-status">{"Complete" if done else "Next action"}</span>'
            f'</div>'
        )
    st.markdown(
        '<div class="cv-onboard-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )

    next_incomplete_step = next(
        (
            index
            for index, key in enumerate(
                (
                    "profile_completed",
                    "workspace_completed",
                    "first_bom_completed",
                    "first_alternative_completed",
                    "first_report_completed",
                )
            )
            if not bool(progress.get(key))
        ),
        None,
    )

    onboarding_actions = [
        ("Edit Profile", "Settings", "onboarding_open_profile"),
        ("Open Workspace", "Workspace", "onboarding_open_workspace"),
        ("Analyze a BOM", "BOM Analyzer", "onboarding_open_bom"),
        ("Review Alternatives", "Alternative Finder", "onboarding_open_alternatives"),
        ("Generate a Report", "Reports", "onboarding_open_reports"),
    ]

    action_cols = st.columns(5)
    for index, (label, destination, key) in enumerate(onboarding_actions):
        with action_cols[index]:
            internal_nav_button(
                label,
                destination,
                key=key,
                use_container_width=True,
                type="primary" if index == next_incomplete_step else "secondary",
            )

    finish_col, skip_col = st.columns(2)
    with finish_col:
        if st.button(
            "Mark Setup Complete",
            type="primary",
            use_container_width=True,
            disabled=completed_steps < total_steps,
            key="onboarding_complete",
        ):
            update_onboarding_progress(
                supabase,
                onboarding_user_id,
                {
                    "welcome_seen": True,
                    "dismissed": False,
                    "completed_at": pd.Timestamp.utcnow().isoformat(),
                },
            )
            st.success("Cadivor setup completed.")
            navigate_to("Dashboard")

    with skip_col:
        if st.button(
            "Skip for Now",
            type="secondary",
            use_container_width=True,
            key="onboarding_skip",
        ):
            update_onboarding_progress(
                supabase,
                onboarding_user_id,
                {
                    "welcome_seen": True,
                    "dismissed": True,
                },
            )
            navigate_to("Dashboard")

    st.stop()


# ---------- Dashboard ----------
if app_mode == "Dashboard":
    if (
        onboarding_progress
        and not onboarding_progress.get("dismissed")
        and completion_count(onboarding_progress) < 5
    ):
        onboarding_done = completion_count(onboarding_progress)
        onboarding_percent = int((onboarding_done / 5) * 100)
        st.markdown(
            f"""
            <style id="cadivor-dashboard-setup-v11a3">
            .cv-setup-reminder{{
                border:1px solid #BFDBFE;border-radius:20px;background:#FFFFFF;
                box-shadow:0 16px 38px rgba(15,23,42,.06);padding:18px 20px;
                margin:0 0 18px;
            }}
            .cv-setup-reminder-top{{
                display:flex;align-items:center;justify-content:space-between;
                gap:14px;margin-bottom:10px;
            }}
            .cv-setup-reminder h3{{
                color:#0F172A!important;font-size:16px;font-weight:950;margin:0;
            }}
            .cv-setup-reminder strong{{
                color:#2563EB!important;font-size:12px;font-weight:950;
            }}
            .cv-setup-reminder p{{
                color:#64748B!important;font-size:11px;line-height:1.5;
                font-weight:720;margin:0 0 12px;
            }}
            .cv-setup-reminder-bar{{
                height:8px;border-radius:999px;background:#E2E8F0;overflow:hidden;
            }}
            .cv-setup-reminder-bar i{{
                display:block;height:100%;width:{onboarding_percent}%;
                background:#2563EB;border-radius:999px;
            }}
            </style>
            <section class="cv-setup-reminder">
              <div class="cv-setup-reminder-top">
                <h3>Complete your Cadivor setup</h3>
                <strong>{onboarding_done}/5 complete</strong>
              </div>
              <p>
                Finish customer setup to complete your profile, workspace,
                first BOM, replacement review, and first report.
              </p>
              <div class="cv-setup-reminder-bar"><i></i></div>
            </section>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Continue Customer Setup",
            type="primary",
            key="dashboard_continue_onboarding",
        ):
            navigate_to("Onboarding")

    try:
        overview_analyses = load_analysis_history(current_user["id"]) or []
    except Exception:
        overview_analyses = []
    try:
        overview_parts_response = (
            _workspace_query(supabase.table("analysis_parts").select("*"))
            .eq("user_id", current_user["id"])
            .limit(5000)
            .execute()
        )
        overview_parts = overview_parts_response.data or []
    except Exception:
        overview_parts = []
    try:
        overview_alert_response = (
            _workspace_query(supabase.table("monitor_alerts").select("*"))
            .eq("user_id", current_user["id"])
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        overview_alerts = overview_alert_response.data or []
    except Exception:
        overview_alerts = []
    try:
        overview_state, _ = load_decision_state(
            supabase,
            user_id=current_user["id"],
            workspace_id=active_workspace_id or None,
        )
    except Exception:
        overview_state = {}

    overview_decisions = build_decision_center(
        alert_df=pd.DataFrame(overview_alerts),
        analyses=overview_analyses,
        saved_state=overview_state,
    )["decisions"]
    overview_procurement = build_procurement_advisor(
        analyses=overview_analyses,
        parts=overview_parts,
        alerts=overview_alerts,
    )
    overview = build_engineering_overview(
        analyses=overview_analyses,
        parts=overview_parts,
        alerts=overview_alerts,
        decisions=overview_decisions,
        procurement=overview_procurement,
    )

    overview_tab, portfolio_tab = st.tabs(
        ["Engineering Overview", "Portfolio Dashboard"]
    )

    with overview_tab:
        render_living_workspace(
            overview=overview,
            parts=overview_parts,
            internal_nav_button=internal_nav_button,
        )

    with portfolio_tab:
        render_dashboard(
            current_user=current_user,
            supabase=supabase,
            load_analysis_history=load_analysis_history,
            load_alternative_history=load_alternative_history,
            render_global_search_panel=render_global_search_panel,
            light_plotly_layout=light_plotly_layout,
            empty_state=empty_state,
            get_user_profile=get_user_profile,
            _qp_value=_qp_value,
            workspace_id=active_workspace_id,
            workspace_name=active_workspace_name,
        )
    st.stop()

if app_mode == "Analysis Details":
    render_analysis_detail(
        current_user=current_user,
        supabase=supabase,
        load_analysis_history=load_analysis_history,
        light_plotly_layout=light_plotly_layout,
        _qp_value=_qp_value,
        workspace_id=active_workspace_id,
        workspace_role=active_workspace_role,
        workspace_members=(
            list_members(supabase, active_workspace_id)[0]
            if active_workspace_id
            else []
        ),
    )
    st.stop()

st.markdown(
    """
    <style>
      .cv130-hero{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eef5ff);border-radius:24px;padding:21px;margin-bottom:14px;box-shadow:0 16px 42px rgba(37,99,235,.07)}
      .cv130-eyebrow{font-size:9px;font-weight:950;letter-spacing:.09em;text-transform:uppercase;color:#2563eb;margin-bottom:7px}.cv130-title{font-size:27px;font-weight:950;color:#0f172a;letter-spacing:-.04em;margin-bottom:7px}.cv130-copy{font-size:11px;font-weight:720;color:#52647a;line-height:1.6;max-width:920px}
      .cv130-decision-card,.cv130-packet{border:1px solid #dbe3ef;background:#fff;border-radius:20px;padding:16px;margin-bottom:11px;box-shadow:0 12px 30px rgba(15,23,42,.05)}.cv130-decision-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}.cv130-decision-title{font-size:16px;font-weight:950;color:#0f172a;letter-spacing:-.02em}.cv130-packet-title{font-size:23px;font-weight:950;color:#0f172a;letter-spacing:-.035em}.cv130-reason{font-size:10px;font-weight:720;color:#52647a;line-height:1.5;margin-top:5px}
      .cv130-badge{border-radius:999px;padding:7px 10px;font-size:9px;font-weight:950;white-space:nowrap;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8}.cv130-badge.good{border-color:#a7f3d0;background:#ecfdf5;color:#047857}.cv130-badge.warn{border-color:#fde68a;background:#fffbeb;color:#b45309}.cv130-badge.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
      .cv130-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}.cv130-meta span{border:1px solid #dbeafe;background:#eff6ff;border-radius:999px;padding:5px 8px;font-size:8px;font-weight:900;color:#1d4ed8}
      .cv130-impact{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:12px 0}.cv130-impact div{border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:11px}.cv130-impact span{display:block;font-size:8px;font-weight:950;text-transform:uppercase;letter-spacing:.07em;color:#64748b;margin-bottom:5px}.cv130-impact strong{font-size:13px;font-weight:950;color:#0f172a}
      .cv131-compact{padding:13px 15px;margin-bottom:7px}.cv131-card-main{min-width:0}.cv131-card-badges{display:flex;gap:7px;align-items:flex-start;flex-wrap:wrap;justify-content:flex-end}.cv131-age{border-radius:999px;padding:6px 9px;font-size:8px;font-weight:950;border:1px solid #dbeafe;background:#eff6ff;color:#1d4ed8;white-space:nowrap}.cv131-age.watch{border-color:#fde68a;background:#fffbeb;color:#a16207}.cv131-age.warn{border-color:#fdba74;background:#fff7ed;color:#c2410c}.cv131-age.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
      .cv131-summary-grid{display:grid;grid-template-columns:1.2fr 1fr 1fr .7fr .8fr;gap:8px;margin-top:10px}.cv131-summary-grid div{border-left:2px solid #dbeafe;padding-left:8px}.cv131-summary-grid span{display:block;font-size:7px;font-weight:950;letter-spacing:.07em;text-transform:uppercase;color:#64748b}.cv131-summary-grid strong{font-size:10px;font-weight:900;color:#0f172a;line-height:1.3}.cv131-progress{height:6px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin-top:10px}.cv131-progress div{height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:999px}.cv131-progress.packet{height:8px;margin-top:14px}.cv131-next{font-size:9px;font-weight:750;color:#52647a;margin-top:6px}.cv131-breakdown{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.cv131-breakdown div{border:1px solid #e2e8f0;border-radius:12px;padding:10px;background:#fff}.cv131-breakdown span{display:block;font-size:8px;font-weight:950;color:#64748b;text-transform:uppercase}.cv131-breakdown strong{font-size:16px;font-weight:950;color:#0f172a}
      @media(max-width:900px){.cv130-decision-head{display:block}.cv130-impact,.cv131-breakdown{grid-template-columns:1fr 1fr}.cv131-summary-grid{grid-template-columns:1fr 1fr}.cv130-badge{display:inline-block;margin-top:10px}}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <style>
      .cv123-monitor-hero{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eef5ff);border-radius:24px;padding:20px;margin-bottom:14px;box-shadow:0 16px 42px rgba(37,99,235,.07)}
      .cv123-monitor-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.cv123-monitor-eyebrow{font-size:9px;font-weight:950;letter-spacing:.09em;text-transform:uppercase;color:#2563eb;margin-bottom:7px}.cv123-monitor-title{font-size:25px;font-weight:950;color:#0f172a;letter-spacing:-.035em;margin-bottom:6px}.cv123-monitor-copy{font-size:11px;font-weight:720;color:#52647a;line-height:1.55;max-width:900px}
      .cv123-monitor-badge{border:1px solid #bfdbfe;border-radius:999px;padding:7px 10px;font-size:9px;font-weight:950;white-space:nowrap;background:#eff6ff;color:#1d4ed8}.cv123-monitor-badge.good{border-color:#a7f3d0;background:#ecfdf5;color:#047857}.cv123-monitor-badge.warn{border-color:#fde68a;background:#fffbeb;color:#b45309}.cv123-monitor-badge.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
      .cv123-alert-card{border:1px solid #dbe3ef;background:#fff;border-radius:18px;padding:15px;margin-bottom:10px;box-shadow:0 10px 28px rgba(15,23,42,.045)}.cv123-alert-head{display:flex;justify-content:space-between;gap:12px}.cv123-alert-part{font-size:14px;font-weight:950;color:#0f172a}.cv123-alert-type{font-size:9px;font-weight:950;color:#2563eb;text-transform:uppercase;letter-spacing:.07em}.cv123-alert-message{font-size:11px;font-weight:720;color:#475569;line-height:1.5;margin:8px 0}.cv123-alert-meta{display:flex;gap:7px;flex-wrap:wrap}.cv123-alert-pill{border:1px solid #dbeafe;background:#eff6ff;border-radius:999px;padding:5px 8px;font-size:8px;font-weight:900;color:#1d4ed8}.cv123-alert-action{border-top:1px solid #e2e8f0;margin-top:11px;padding-top:11px;font-size:11px;font-weight:780;color:#0f172a}
      @media(max-width:900px){.cv123-monitor-top{display:block}.cv123-monitor-badge{display:inline-block;margin-top:10px}}
    </style>
    """,
    unsafe_allow_html=True,
)

if app_mode == "Monitoring":
    return_analysis_id = _qp_value("return_analysis_id")
    if return_analysis_id:
        if st.button(
            "← Back to Saved BOM",
            key="monitoring_back_to_saved_bom",
            type="secondary",
        ):
            navigate_to("Analysis Details", analysis_id=return_analysis_id)

    alert_history = (
        _workspace_query(
            supabase.table("monitor_alerts").select("*")
        )
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    alert_df = pd.DataFrame(alert_history.data)

    monitor_history = (
        _workspace_query(
            supabase.table("part_monitor_history").select("*")
        )
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .limit(250)
        .execute()
    )
    monitor_df = pd.DataFrame(monitor_history.data)

    monitoring_center = build_monitoring_action_center(
        alert_df,
        monitor_df,
    )

    st.markdown(
        f"""
        <section class="cv123-monitor-hero">
          <div class="cv123-monitor-top">
            <div>
              <div class="cv123-monitor-eyebrow">AI Monitoring & Action Center</div>
              <div class="cv123-monitor-title">{html.escape(monitoring_center['posture'])}</div>
              <div class="cv123-monitor-copy">{html.escape(monitoring_center['summary'])}</div>
            </div>
            <span class="cv123-monitor-badge {html.escape(monitoring_center['posture_tone'])}">
              {monitoring_center['active_alerts']} active alert(s)
            </span>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Active Alerts", monitoring_center["active_alerts"])
    kpi2.metric("Immediate Actions", monitoring_center["immediate_actions"])
    kpi3.metric("Engineering Actions", monitoring_center["engineering_actions"])
    kpi4.metric("Procurement Actions", monitoring_center["procurement_actions"])

    action_tab, alert_table_tab, component_tab = st.tabs(
        [
            "Requires Attention",
            "Recent Changes",
            "Watching",
        ]
    )

    with action_tab:
        st.caption(
            "Cadivor converts raw monitoring changes into prioritized engineering and "
            "procurement actions with owners, deadlines, and expected impact."
        )

        prioritized = monitoring_center["prioritized_alerts"]
        if prioritized.empty:
            st.success(
                "No active exception requires action. Continue scheduled monitoring."
            )
        else:
            severity_filter = st.selectbox(
                "Filter by severity",
                ["All", "Critical", "High", "Medium", "Low"],
                key="monitor_action_severity_filter",
            )
            owner_filter = st.selectbox(
                "Filter by owner",
                [
                    "All",
                    "Engineering",
                    "Component Engineering",
                    "Procurement",
                    "Supply Chain",
                    "Engineering & Supply Chain",
                ],
                key="monitor_action_owner_filter",
            )

            filtered = prioritized.copy()
            if severity_filter != "All":
                filtered = filtered[
                    filtered["Severity"].astype(str).str.lower()
                    == severity_filter.lower()
                ]
            if owner_filter != "All":
                filtered = filtered[
                    filtered["Owner"].astype(str).str.lower()
                    == owner_filter.lower()
                ]

            st.caption(
                f"Showing {len(filtered)} of {len(prioritized)} prioritized monitoring action(s)."
            )

            for index, row in filtered.head(20).iterrows():
                tone = (
                    "bad"
                    if int(row["Priority"]) >= 75
                    else "warn"
                    if int(row["Priority"]) >= 45
                    else "good"
                )
                st.markdown(
                    f"""
                    <section class="cv123-alert-card">
                      <div class="cv123-alert-head">
                        <div>
                          <div class="cv123-alert-type">{html.escape(str(row['Alert Type']))}</div>
                          <div class="cv123-alert-part">{html.escape(str(row['Part Number']))}</div>
                        </div>
                        <span class="cv123-monitor-badge {tone}">
                          Priority {int(row['Priority'])}/100
                        </span>
                      </div>
                      <div class="cv123-alert-message">{html.escape(str(row['Change']))}</div>
                      <div class="cv123-alert-meta">
                        <span class="cv123-alert-pill">Owner: {html.escape(str(row['Owner']))}</span>
                        <span class="cv123-alert-pill">Deadline: {html.escape(str(row['Deadline']))}</span>
                        <span class="cv123-alert-pill">Severity: {html.escape(str(row['Severity']))}</span>
                        <span class="cv123-alert-pill">Current: {html.escape(str(row['Current Value']))}</span>
                      </div>
                      <div class="cv123-alert-action">
                        Recommended action: {html.escape(str(row['Recommended Action']))}<br>
                        Expected impact: {html.escape(str(row['Expected Impact']))}
                      </div>
                    </section>
                    """,
                    unsafe_allow_html=True,
                )

                action_cols = st.columns(4)
                with action_cols[0]:
                    if st.button(
                        "Find Alternative",
                        key=f"monitor_alt_{index}_{row['Part Number']}",
                        use_container_width=True,
                        type="primary",
                    ):
                        navigate_to(
                            "Alternative Finder",
                            original_part=str(row["Part Number"]),
                            return_analysis_id=return_analysis_id,
                        )
                with action_cols[1]:
                    st.download_button(
                        "Export Action",
                        data=pd.DataFrame([row]).to_csv(index=False).encode("utf-8"),
                        file_name=f"{str(row['Part Number']).replace('/', '_')}_monitoring_action.csv",
                        mime="text/csv",
                        key=f"monitor_export_{index}_{row['Part Number']}",
                        use_container_width=True,
                    )
                with action_cols[2]:
                    if st.button(
                        "Review Decision",
                        key=f"monitor_decision_{index}_{row['Part Number']}",
                        use_container_width=True,
                    ):
                        navigate_to(
                            "Engineering Decisions",
                            focus_part=str(row["Part Number"]),
                        )
                with action_cols[3]:
                    st.caption(f"Detected: {row['Detected At']}")

    with alert_table_tab:
        prioritized = monitoring_center["prioritized_alerts"]
        if prioritized.empty:
            st.info("No monitoring alerts are available.")
        else:
            alert_columns = [
                "Part Number",
                "Priority",
                "Severity",
                "Alert Type",
                "Change",
                "Previous Value",
                "Current Value",
                "Owner",
                "Deadline",
                "Detected At",
            ]
            st.dataframe(
                prioritized[alert_columns],
                hide_index=True,
                use_container_width=True,
            )
            st.download_button(
                "Download Monitoring Action Queue CSV",
                data=prioritized.to_csv(index=False).encode("utf-8"),
                file_name="cadivor_monitoring_action_queue.csv",
                mime="text/csv",
                key="monitor_action_queue_csv",
                type="primary",
            )

    with component_tab:
        latest_components = monitoring_center["latest_components"]
        if latest_components.empty:
            st.info("No monitoring history is available yet.")
        else:
            search_component = st.text_input(
                "Search monitored components",
                placeholder="Part number or supplier",
                key="monitor_component_search",
            )
            visible_components = latest_components.copy()
            if search_component.strip():
                query = search_component.strip().lower()
                mask = visible_components.astype(str).apply(
                    lambda column: column.str.lower().str.contains(
                        query,
                        na=False,
                        regex=False,
                    )
                ).any(axis=1)
                visible_components = visible_components[mask]

            st.caption(
                f"Showing {len(visible_components)} monitored component record(s)."
            )
            st.dataframe(
                visible_components,
                hide_index=True,
                use_container_width=True,
            )


# ---------- Cost Optimization ----------
if app_mode == "Cost Optimization":
    try:
        cost_analyses = load_analysis_history(current_user["id"]) or []
    except Exception:
        cost_analyses = []

    try:
        cost_parts_response = (
            _workspace_query(supabase.table("analysis_parts").select("*"))
            .eq("user_id", current_user["id"])
            .limit(10000)
            .execute()
        )
        cost_parts = cost_parts_response.data or []
    except Exception:
        cost_parts = []

    st.markdown("### Production scenario")
    build_quantity = st.number_input(
        "Number of builds to model",
        min_value=1,
        max_value=1_000_000,
        value=int(st.session_state.get("cost_build_quantity", 100)),
        step=10,
        key="cost_build_quantity",
        help="Cadivor multiplies recorded BOM quantities and unit prices by this production quantity.",
    )

    cost_intelligence = build_cost_optimization(
        cost_analyses,
        cost_parts,
        int(build_quantity),
    )
    render_cost_optimization(
        intelligence=cost_intelligence,
        internal_nav_button=internal_nav_button,
    )
    st.stop()


# ---------- Design Impact Analyzer ----------
if app_mode == "Design Impact Analyzer":
    try:
        impact_analyses = load_analysis_history(current_user["id"]) or []
    except Exception:
        impact_analyses = []

    try:
        impact_parts_response = (
            _workspace_query(supabase.table("analysis_parts").select("*"))
            .eq("user_id", current_user["id"])
            .limit(10000)
            .execute()
        )
        impact_parts = impact_parts_response.data or []
    except Exception:
        impact_parts = []

    requested_impact_mpn = (
        st.session_state.get("design_impact_mpn")
        or _qp_value("part")
        or _qp_value("mpn")
        or ""
    )

    impact_intelligence = build_design_impact(
        impact_analyses,
        impact_parts,
        requested_impact_mpn,
    )
    render_design_impact(
        intelligence=impact_intelligence,
        internal_nav_button=internal_nav_button,
    )
    st.stop()


# ---------- Portfolio Intelligence ----------
if app_mode == "Portfolio Intelligence":
    try:
        portfolio_analyses = load_analysis_history(current_user["id"]) or []
    except Exception:
        portfolio_analyses = []

    try:
        portfolio_parts_response = (
            _workspace_query(supabase.table("analysis_parts").select("*"))
            .eq("user_id", current_user["id"])
            .limit(10000)
            .execute()
        )
        portfolio_parts = portfolio_parts_response.data or []
    except Exception:
        portfolio_parts = []

    try:
        portfolio_alert_response = (
            _workspace_query(supabase.table("monitor_alerts").select("*"))
            .eq("user_id", current_user["id"])
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        portfolio_alerts = portfolio_alert_response.data or []
    except Exception:
        portfolio_alerts = []

    portfolio_intelligence = build_portfolio_intelligence(
        portfolio_analyses,
        portfolio_parts,
        portfolio_alerts,
    )
    render_portfolio_intelligence(
        intelligence=portfolio_intelligence,
        internal_nav_button=internal_nav_button,
    )
    st.stop()


# ---------- Procurement Advisor ----------
if app_mode == "Procurement Advisor":
    try:
        pa_analyses = load_analysis_history(current_user["id"]) or []
        pa_parts_response = (
            _workspace_query(supabase.table("analysis_parts").select("*"))
            .eq("user_id", current_user["id"])
            .limit(5000)
            .execute()
        )
        pa_parts = pa_parts_response.data or []
    except Exception:
        pa_analyses, pa_parts = [], []

    advisor = build_procurement_advisor(
        analyses=pa_analyses,
        parts=pa_parts,
        alerts=[],
    )
    st.markdown(
        f"""
        <section class="cv151-hero">
          <div class="cv151-title">Procurement Advisor</div>
          <div class="cv151-subtitle">{html.escape(advisor['summary'])}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Action Needed", advisor["urgent_count"])
    p2.metric("Monitor", advisor["monitor_count"])
    p3.metric("Need Second Source", advisor["second_source_count"])
    p4.metric("Replacement Needed", advisor["replace_count"])

    priority_tab, details_tab = st.tabs(
        ["Action Needed", "All Components"]
    )
    with priority_tab:
        urgent_rows = [
            row for row in advisor["recommendations"]
            if row["Recommendation"] != "No immediate action"
        ][:10]
        if not urgent_rows:
            st.success("No immediate purchasing action is required.")
        for index, row in enumerate(urgent_rows):
            st.markdown(
                f"""
                <section class="cv151-card">
                  <div class="cv151-card-title">{html.escape(row['Part Number'])}</div>
                  <div class="cv151-card-copy">
                    <b>Recommended action: {html.escape(row['Recommendation'])}</b><br>
                    {html.escape(row['Next Step'])}
                  </div>
                  <div class="cv151-meta">
                    <span>Priority {row['Priority Score']}/100</span>
                    <span>Stock {row['Available Stock']:,}</span>
                    <span>{row['Supplier Sources']} supplier(s)</span>
                  </div>
                </section>
                """,
                unsafe_allow_html=True,
            )
            cols = st.columns(2)
            with cols[0]:
                internal_nav_button(
                    "Find Alternative",
                    "Alternative Finder",
                    key=f"pa_alt_{index}",
                    use_container_width=True,
                    original_part=row["Part Number"],
                )
            with cols[1]:
                internal_nav_button(
                    "Open Monitoring",
                    "Monitoring",
                    key=f"pa_monitor_{index}",
                    use_container_width=True,
                    mpn=row["Part Number"],
                )

    with details_tab:
        if advisor["recommendation_df"].empty:
            st.info("No component purchasing data is available.")
        else:
            st.dataframe(
                advisor["recommendation_df"],
                hide_index=True,
                use_container_width=True,
            )
            st.download_button(
                "Download Procurement Details",
                advisor["recommendation_df"].to_csv(index=False).encode("utf-8"),
                file_name="cadivor_procurement_details.csv",
                mime="text/csv",
                key="pa_export",
            )


# ---------- Engineering Decision Center ----------
if app_mode == "Engineering Decisions":
    try:
        decision_alert_response = (
            _workspace_query(
                supabase.table("monitor_alerts").select("*")
            )
            .eq("user_id", current_user["id"])
            .order("created_at", desc=True)
            .limit(150)
            .execute()
        )
        decision_alert_df = pd.DataFrame(decision_alert_response.data or [])
    except Exception:
        decision_alert_df = pd.DataFrame()

    try:
        decision_analyses = load_analysis_history(current_user["id"]) or []
    except Exception:
        decision_analyses = []

    decision_scope_key = active_workspace_id or "personal"
    decision_cache_key = (
        f"engineering_decision_state_{current_user['id']}_{decision_scope_key}"
    )

    if decision_cache_key not in st.session_state:
        persistent_decision_state, decision_load_error = load_decision_state(
            supabase,
            user_id=current_user["id"],
            workspace_id=active_workspace_id or None,
        )
        st.session_state[decision_cache_key] = persistent_decision_state
        st.session_state[
            f"{decision_cache_key}_load_error"
        ] = decision_load_error

    decision_state = st.session_state[decision_cache_key]

    decision_center = build_decision_center(
        alert_df=decision_alert_df,
        analyses=decision_analyses,
        saved_state=decision_state,
    )
    all_decisions = decision_center["decisions"]

    focus_decision_id = _qp_value("decision_id")
    focus_part = _qp_value("focus_part")
    selected_decision = None

    if focus_decision_id:
        selected_decision = next(
            (
                decision
                for decision in all_decisions
                if decision["decision_id"] == focus_decision_id
            ),
            None,
        )
    elif focus_part:
        selected_decision = next(
            (
                decision
                for decision in all_decisions
                if str(decision["part_number"]).upper() == str(focus_part).upper()
            ),
            None,
        )

    st.markdown(
        """
        <section class="cv130-hero">
          <div class="cv130-eyebrow">Cadivor Engineering Decision Center</div>
          <div class="cv130-title">Turn component intelligence into approved engineering action.</div>
          <div class="cv130-copy">
            Review prioritized decisions, assign ownership, simulate expected impact,
            document engineering notes, and move work from open review to production readiness.
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    decision_load_error = st.session_state.get(
        f"{decision_cache_key}_load_error"
    )
    if decision_load_error:
        st.warning(
            "Persistent decision storage is not available yet. "
            "Run the Milestone 13.2 SQL, then refresh this page."
        )
    else:
        st.caption(
            "Decision workflow, notes, and history are saved to your Cadivor account."
        )

    if selected_decision:
        if st.button(
            "← Back to Engineering Decisions",
            key="decision_packet_back",
            type="secondary",
        ):
            navigate_to("Engineering Decisions")

        st.markdown(
            packet_header_html(selected_decision),
            unsafe_allow_html=True,
        )

        summary_tab, evidence_tab, notes_tab, history_tab = st.tabs(
            ["Decision Summary", "Evidence", "Engineering Notes", "Decision History"]
        )

        decision_id = selected_decision["decision_id"]
        state_record = decision_state.setdefault(
            decision_id,
            {
                "status": (
                    "New"
                    if selected_decision["status"] == "Open"
                    else selected_decision["status"]
                ),
                "owner": selected_decision["assigned_owner"],
                "notes": selected_decision.get("notes", []),
                "history": [
                    {
                        "event": "Decision created",
                        "time": selected_decision["detected_at"],
                    }
                ],
            },
        )

        with summary_tab:
            overview_cols = st.columns(4)
            overview_cols[0].metric("Component / BOM", selected_decision["part_number"])
            overview_cols[1].metric("Priority", f"{selected_decision['priority_score']}/100")
            overview_cols[2].metric("Confidence", f"{selected_decision['confidence']}%")
            overview_cols[3].metric("Estimated Effort", f"{selected_decision['estimated_effort_hours']} hrs")

            st.markdown("### Cadivor Recommendation")
            st.info(selected_decision["recommended_action"])
            st.caption(selected_decision["expected_impact"])

            st.markdown("### Decision Priority Matrix")
            priority_breakdown = selected_decision.get("priority_breakdown", {})
            st.markdown(
                """
                <div class="cv131-breakdown">
                """
                + "".join(
                    f"<div><span>{html.escape(str(label))}</span><strong>{int(value)}</strong></div>"
                    for label, value in priority_breakdown.items()
                )
                + "</div>",
                unsafe_allow_html=True,
            )

            st.markdown("### AI Confidence")
            confidence_cols = st.columns([1, 3])
            confidence_cols[0].metric(
                "Decision Confidence",
                f"{selected_decision['confidence']}%",
            )
            with confidence_cols[1]:
                for reason in selected_decision.get("confidence_reasons", []):
                    st.markdown(f"✓ {reason}")

            impact = selected_decision
            st.markdown(
                f"""
                <div class="cv130-impact">
                  <div><span>Current Health</span><strong>{impact['current_health']}/100</strong></div>
                  <div><span>Projected Health</span><strong>{impact['projected_health']}/100</strong></div>
                  <div><span>Health Improvement</span><strong>+{impact['health_gain']}</strong></div>
                  <div><span>Supply Risk Reduction</span><strong>-{impact['supply_risk_reduction']}</strong></div>
                  <div><span>Lifecycle Issues Removed</span><strong>{impact['lifecycle_exposure_reduction']}</strong></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            workflow_cols = st.columns(3)
            with workflow_cols[0]:
                current_workflow_status = state_record.get("status", "New")
                if current_workflow_status == "Open":
                    current_workflow_status = "New"
                elif current_workflow_status == "Awaiting Approval":
                    current_workflow_status = "Manager Approval"
                elif current_workflow_status in ("Approved", "Production Ready"):
                    current_workflow_status = "Production Approved"
                status_index = (
                    STATUSES.index(current_workflow_status)
                    if current_workflow_status in STATUSES
                    else 0
                )
                new_status = st.selectbox(
                    "Decision status",
                    STATUSES,
                    index=status_index,
                    key=f"decision_status_{decision_id}",
                )
            with workflow_cols[1]:
                new_owner = st.text_input(
                    "Assigned owner",
                    value=state_record.get("owner", selected_decision["owner"]),
                    key=f"decision_owner_{decision_id}",
                )
            with workflow_cols[2]:
                st.text_input(
                    "Target date",
                    value=selected_decision["due_date"],
                    key=f"decision_due_{decision_id}",
                    disabled=True,
                )

            if st.button(
                "Save Decision Workflow",
                key=f"save_decision_{decision_id}",
                type="primary",
            ):
                previous_status = state_record.get("status", "New")
                saved_owner = (
                    new_owner.strip()
                    or selected_decision["owner"]
                )
                save_error = save_decision_workflow(
                    supabase,
                    user_id=current_user["id"],
                    workspace_id=active_workspace_id or None,
                    decision=selected_decision,
                    status=new_status,
                    assigned_owner=saved_owner,
                    due_date=selected_decision.get("due_date"),
                    actor_name=(
                        profile_for_shell.get("full_name")
                        or shell_name
                    ),
                    previous_status=previous_status,
                )

                if save_error:
                    st.error(
                        "The decision could not be saved. "
                        "Confirm the Milestone 13.2 SQL was applied."
                    )
                else:
                    refreshed_state, refresh_error = load_decision_state(
                        supabase,
                        user_id=current_user["id"],
                        workspace_id=active_workspace_id or None,
                    )
                    if refresh_error:
                        state_record["status"] = new_status
                        state_record["owner"] = saved_owner
                    else:
                        st.session_state[decision_cache_key] = refreshed_state
                    st.success("Decision workflow saved.")
                    st.rerun()

            navigation_cols = st.columns(4)
            with navigation_cols[0]:
                internal_nav_button(
                    "Find Alternative",
                    "Alternative Finder",
                    key=f"decision_find_alt_{decision_id}",
                    use_container_width=True,
                    original_part=selected_decision["part_number"],
                )
            with navigation_cols[1]:
                internal_nav_button(
                    "Open Monitoring",
                    "Monitoring",
                    key=f"decision_monitor_{decision_id}",
                    use_container_width=True,
                )
            with navigation_cols[2]:
                internal_nav_button(
                    "Generate Report",
                    "Reports",
                    key=f"decision_report_{decision_id}",
                    use_container_width=True,
                )
            with navigation_cols[3]:
                if selected_decision.get("analysis_id"):
                    internal_nav_button(
                        "Open Saved BOM",
                        "Analysis Details",
                        key=f"decision_analysis_{decision_id}",
                        use_container_width=True,
                        analysis_id=selected_decision["analysis_id"],
                    )
                else:
                    st.caption("No saved BOM is linked to this decision.")

        with evidence_tab:
            st.markdown("### Evidence used by Cadivor")
            for evidence in selected_decision.get("evidence", []):
                st.markdown(f"- {evidence}")
            st.markdown("### Decision context")
            context_df = pd.DataFrame(
                [
                    {
                        "Field": "Source",
                        "Value": selected_decision["source"],
                    },
                    {
                        "Field": "Decision Type",
                        "Value": selected_decision["decision_type"],
                    },
                    {
                        "Field": "Supporting Team",
                        "Value": selected_decision["supporting_team"],
                    },
                    {
                        "Field": "Estimated Cost Impact",
                        "Value": selected_decision["estimated_cost_impact"],
                    },
                ]
            )
            st.dataframe(context_df, hide_index=True, use_container_width=True)

        with notes_tab:
            note = st.text_area(
                "Add an engineering note",
                placeholder="Record validation findings, supplier feedback, approval conditions, or next steps.",
                key=f"decision_note_{decision_id}",
            )
            if st.button(
                "Add Note",
                key=f"decision_add_note_{decision_id}",
                type="primary",
            ):
                if not note.strip():
                    st.warning("Enter a note before saving.")
                else:
                    note_author = (
                        profile_for_shell.get("full_name")
                        or shell_name
                    )
                    note_error = add_decision_note(
                        supabase,
                        user_id=current_user["id"],
                        workspace_id=active_workspace_id or None,
                        decision={
                            **selected_decision,
                            "status": state_record.get("status", "New"),
                            "assigned_owner": state_record.get(
                                "owner",
                                selected_decision["owner"],
                            ),
                        },
                        author_name=note_author,
                        note_text=note.strip(),
                    )

                    if note_error:
                        st.error(
                            "The note could not be saved. "
                            "Confirm the Milestone 13.2 SQL was applied."
                        )
                    else:
                        refreshed_state, refresh_error = load_decision_state(
                            supabase,
                            user_id=current_user["id"],
                            workspace_id=active_workspace_id or None,
                        )
                        if not refresh_error:
                            st.session_state[
                                decision_cache_key
                            ] = refreshed_state
                        st.success("Engineering note saved.")
                        st.rerun()

            notes = state_record.get("notes", [])
            if not notes:
                st.info("No engineering notes have been added yet.")
            else:
                for item in reversed(notes):
                    with st.container(border=True):
                        st.markdown(f"**{item.get('author', 'Engineer')}**")
                        st.caption(item.get("time", ""))
                        st.write(item.get("text", ""))

        with history_tab:
            history = state_record.get("history", [])
            if not history:
                st.info("No decision history is available.")
            else:
                history_df = pd.DataFrame(history).rename(
                    columns={"event": "Event", "time": "Time"}
                )
                st.dataframe(
                    history_df.iloc[::-1],
                    hide_index=True,
                    use_container_width=True,
                )

    else:
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Open Decisions", decision_center["open_count"])
        k2.metric("Critical", decision_center["critical_count"])
        k3.metric("Manager Approval", decision_center["awaiting_approval_count"])
        k4.metric("Production Approved", decision_center["production_ready_count"])
        k5.metric("Engineering Hours", f"{decision_center['estimated_hours']} hrs")
        k6.metric("Average Age", f"{decision_center['average_age_days']} days")

        refresh_decision_col, persistence_scope_col = st.columns(
            [1, 3]
        )
        with refresh_decision_col:
            if st.button(
                "Refresh Decisions",
                key="refresh_persistent_decisions",
                use_container_width=True,
            ):
                st.session_state.pop(decision_cache_key, None)
                st.session_state.pop(
                    f"{decision_cache_key}_load_error",
                    None,
                )
                st.rerun()
        with persistence_scope_col:
            st.caption(
                f"Persistent scope: {active_workspace_name or 'Personal workspace'}"
            )

        queue_tab, workload_tab, analytics_tab, archive_tab = st.tabs(
            [
                "Needs Review",
                "Team Workload",
                "Decision Analytics",
                "Completed",
            ]
        )

        with queue_tab:
            filter_cols = st.columns(3)
            with filter_cols[0]:
                priority_filter = st.selectbox(
                    "Priority",
                    ["All", "Critical", "High", "Medium", "Routine"],
                    key="decision_priority_filter",
                )
            with filter_cols[1]:
                status_filter = st.selectbox(
                    "Status",
                    ["All"] + STATUSES,
                    key="decision_status_filter",
                )
            with filter_cols[2]:
                search_decisions = st.text_input(
                    "Search decisions",
                    placeholder="Component, project, owner, or action",
                    key="decision_search",
                )

            visible = all_decisions
            if priority_filter != "All":
                visible = [
                    decision
                    for decision in visible
                    if decision["priority"] == priority_filter
                ]
            if status_filter != "All":
                visible = [
                    decision
                    for decision in visible
                    if decision["status"] == status_filter
                ]
            if search_decisions.strip():
                query = search_decisions.strip().lower()
                visible = [
                    decision
                    for decision in visible
                    if query
                    in " ".join(
                        [
                            str(decision["part_number"]),
                            str(decision["title"]),
                            str(decision["assigned_owner"]),
                            str(decision["reason"]),
                        ]
                    ).lower()
                ]

            st.caption(f"Showing {len(visible)} of {len(all_decisions)} engineering decision(s).")

            if not visible:
                st.info("No engineering decisions match the selected filters.")
            else:
                for decision in visible[:40]:
                    st.markdown(
                        decision_card_html(decision),
                        unsafe_allow_html=True,
                    )
                    card_cols = st.columns(4)
                    with card_cols[0]:
                        if st.button(
                            "Review Decision",
                            key=f"review_decision_{decision['decision_id']}",
                            type="primary",
                            use_container_width=True,
                        ):
                            navigate_to(
                                "Engineering Decisions",
                                decision_id=decision["decision_id"],
                            )
                    with card_cols[1]:
                        internal_nav_button(
                            "Alternative",
                            "Alternative Finder",
                            key=f"queue_alt_{decision['decision_id']}",
                            use_container_width=True,
                            original_part=decision["part_number"],
                        )
                    with card_cols[2]:
                        internal_nav_button(
                            "Monitoring",
                            "Monitoring",
                            key=f"queue_monitor_{decision['decision_id']}",
                            use_container_width=True,
                        )
                    with card_cols[3]:
                        if decision.get("analysis_id"):
                            internal_nav_button(
                                "Saved BOM",
                                "Analysis Details",
                                key=f"queue_analysis_{decision['decision_id']}",
                                use_container_width=True,
                                analysis_id=decision["analysis_id"],
                            )
                        else:
                            st.caption("Monitoring decision")

        with workload_tab:
            st.markdown("### Team Workload")
            active = [
                decision
                for decision in all_decisions
                if decision["status"] not in ("Closed", "Rejected")
            ]
            if not active:
                st.success("No open engineering workload remains.")
            else:
                workload_rows = []
                owners = sorted(set(decision["assigned_owner"] for decision in active))
                for owner in owners:
                    owner_decisions = [
                        decision for decision in active if decision["assigned_owner"] == owner
                    ]
                    workload_rows.append(
                        {
                            "Owner": owner,
                            "Open Decisions": len(owner_decisions),
                            "Critical": sum(
                                1 for decision in owner_decisions
                                if decision["priority_score"] >= 85
                            ),
                            "Estimated Hours": sum(
                                decision["estimated_effort_hours"]
                                for decision in owner_decisions
                            ),
                            "Average Confidence": round(
                                sum(decision["confidence"] for decision in owner_decisions)
                                / len(owner_decisions)
                            ),
                        }
                    )
                st.dataframe(
                    pd.DataFrame(workload_rows),
                    hide_index=True,
                    use_container_width=True,
                )

        with analytics_tab:
            st.markdown("### Decision Analytics")
            analytics_cols = st.columns(4)
            analytics_cols[0].metric(
                "Projected Health Gain",
                f"+{decision_center['projected_health_gain']}",
            )
            analytics_cols[1].metric(
                "Projected Supply Risk Reduction",
                f"-{decision_center['projected_risk_reduction']}",
            )
            analytics_cols[2].metric(
                "Closed / Rejected",
                decision_center["closed_count"],
            )
            analytics_cols[3].metric(
                "Average Open Age",
                f"{decision_center['average_age_days']} days",
            )

            if all_decisions:
                status_counts = (
                    pd.DataFrame(all_decisions)["status"]
                    .value_counts()
                    .rename_axis("Workflow Stage")
                    .reset_index(name="Decisions")
                )
                owner_hours = (
                    pd.DataFrame(
                        [
                            {
                                "Owner": decision["assigned_owner"],
                                "Estimated Hours": decision["estimated_effort_hours"],
                                "Priority Score": decision["priority_score"],
                            }
                            for decision in all_decisions
                            if decision["status"] not in ("Closed", "Rejected")
                        ]
                    )
                    .groupby("Owner", as_index=False)
                    .agg(
                        {
                            "Estimated Hours": "sum",
                            "Priority Score": "mean",
                        }
                    )
                    .rename(columns={"Priority Score": "Average Priority"})
                )
                analytics_left, analytics_right = st.columns(2)
                with analytics_left:
                    st.markdown("#### Decisions by Workflow Stage")
                    st.dataframe(status_counts, hide_index=True, use_container_width=True)
                with analytics_right:
                    st.markdown("#### Open Workload Impact")
                    st.dataframe(owner_hours, hide_index=True, use_container_width=True)

        with archive_tab:
            st.markdown("### Searchable Decision Archive")
            archive_search = st.text_input(
                "Search archived decisions",
                placeholder="Project, component, owner, type, or outcome",
                key="decision_archive_search",
            )
            archived = [
                decision
                for decision in all_decisions
                if decision["status"] in ("Closed", "Rejected", "Production Approved")
            ]
            if archive_search.strip():
                archive_query = archive_search.strip().lower()
                archived = [
                    decision
                    for decision in archived
                    if archive_query
                    in " ".join(
                        [
                            str(decision["title"]),
                            str(decision["part_number"]),
                            str(decision["assigned_owner"]),
                            str(decision["decision_type"]),
                            str(decision["status"]),
                        ]
                    ).lower()
                ]

            if not archived:
                st.info("No archived or production-approved decisions match the search.")
            else:
                archive_df = pd.DataFrame(
                    [
                        {
                            "Updated": decision["updated_at"],
                            "Project / Component": decision["part_number"],
                            "Decision": decision["title"],
                            "Owner": decision["assigned_owner"],
                            "Decision Type": decision["decision_type"],
                            "Outcome": decision["status"],
                            "Confidence": f"{decision['confidence']}%",
                        }
                        for decision in archived
                    ]
                )
                st.dataframe(
                    archive_df,
                    hide_index=True,
                    use_container_width=True,
                )
                st.download_button(
                    "Export Decision Archive CSV",
                    data=archive_df.to_csv(index=False).encode("utf-8"),
                    file_name="cadivor_decision_archive.csv",
                    mime="text/csv",
                    key="decision_archive_csv",
                    type="primary",
                )


def _mark_first_report_complete() -> None:
    """Persist the first-report onboarding step as soon as a download is used."""
    if not onboarding_user_id:
        return
    updated, error = update_onboarding_progress(
        supabase,
        onboarding_user_id,
        {"first_report_completed": True, "welcome_seen": True},
    )
    if updated and not error:
        st.session_state["onboarding_report_completed"] = True


# ---------- Reports ----------
if app_mode == "Reports":
    # Milestone 5.5 — Functional Reports Center
    try:
        report_records = load_analysis_history(current_user["id"]) or []
    except Exception:
        report_records = []

    def _report_int(value, default=0):
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return default
            return int(float(value))
        except Exception:
            return default

    def _report_float(value, default=0.0):
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return default
            return float(value)
        except Exception:
            return default

    def _report_value(row, *keys, default=None):
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip() not in ("", "nan", "None"):
                return value
        return default

    def _analysis_label(row):
        project = _report_value(row, "project_name", "name", default="Saved BOM")
        created = str(_report_value(row, "created_at", "date", default=""))
        created_date = created.split("T")[0] if "T" in created else created[:10]
        return f"{project} — {created_date or 'undated'}"

    def _load_report_parts(analysis_id):
        if not analysis_id:
            return pd.DataFrame()
        try:
            response = (
                _workspace_query(
                    supabase.table("analysis_parts")
                    .select("*")
                )
                .eq("analysis_id", analysis_id)
                .eq("user_id", current_user["id"])
                .execute()
            )
            return pd.DataFrame(response.data or [])
        except Exception:
            try:
                response = (
                    _workspace_query(
                        supabase.table("analysis_parts")
                        .select("*")
                    )
                    .eq("analysis_id", analysis_id)
                    .execute()
                )
                return pd.DataFrame(response.data or [])
            except Exception:
                return pd.DataFrame()

    def _build_executive_pdf(analysis_row, parts_df):
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=42,
            leftMargin=42,
            topMargin=42,
            bottomMargin=42,
        )
        styles = getSampleStyleSheet()
        story = []

        project = _report_value(analysis_row, "project_name", "name", default="Saved BOM")
        filename = _report_value(analysis_row, "filename", "uploaded_file", "file_name", default="—")
        health = _report_int(_report_value(analysis_row, "health_score", default=0))
        high_risk = _report_int(_report_value(analysis_row, "high_risk_count", "high_risk_parts", default=0))
        medium_risk = _report_int(_report_value(analysis_row, "medium_risk_count", "medium_risk_parts", default=0))
        total_parts = _report_int(_report_value(analysis_row, "total_parts", "part_count", "parts_count", default=len(parts_df)))

        story.append(Paragraph("Cadivor Executive BOM Report", styles["Title"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"Project: {html.escape(str(project))}", styles["Heading2"]))
        story.append(Paragraph(f"Source file: {html.escape(str(filename))}", styles["BodyText"]))
        story.append(Spacer(1, 12))

        summary_table = Table(
            [
                ["Health Score", "Total Parts", "High Risk", "Medium Risk"],
                [str(health), str(total_parts), str(high_risk), str(medium_risk)],
            ],
            colWidths=[115, 115, 115, 115],
        )
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(summary_table)
        story.append(Spacer(1, 16))

        if health >= 80:
            recommendation = "Portfolio health is strong. Continue lifecycle and supplier monitoring."
        elif health >= 60:
            recommendation = "Review elevated-risk parts and validate supplier coverage before release."
        else:
            recommendation = "Immediate engineering and sourcing review is recommended before production release."

        story.append(Paragraph("Recommended action", styles["Heading2"]))
        story.append(Paragraph(recommendation, styles["BodyText"]))
        story.append(Spacer(1, 16))

        story.append(Paragraph("Priority component review", styles["Heading2"]))
        if parts_df.empty:
            story.append(Paragraph("No component-level records were available for this saved analysis.", styles["BodyText"]))
        else:
            work = parts_df.copy()
            risk_col = next((c for c in ["risk_level", "Risk Level", "risk"] if c in work.columns), None)
            score_col = next((c for c in ["risk_score", "Risk Score"] if c in work.columns), None)

            if score_col:
                work["_sort_score"] = pd.to_numeric(work[score_col], errors="coerce").fillna(0)
                work = work.sort_values("_sort_score", ascending=False)
            elif risk_col:
                rank = {"High": 3, "Medium": 2, "Low": 1}
                work["_risk_rank"] = work[risk_col].astype(str).map(rank).fillna(0)
                work = work.sort_values("_risk_rank", ascending=False)

            def first_col(candidates):
                return next((c for c in candidates if c in work.columns), None)

            mpn_col = first_col(["mpn", "MPN", "part_number", "manufacturer_part_number"])
            manufacturer_col = first_col(["manufacturer", "Manufacturer"])
            lifecycle_col = first_col(["lifecycle_status", "Lifecycle Status"])
            stock_col = first_col(["stock_available", "stock", "Stock Available", "total_market_stock"])

            table_data = [["Part", "Manufacturer", "Risk", "Lifecycle", "Stock"]]
            for _, row in work.head(12).iterrows():
                table_data.append(
                    [
                        str(row.get(mpn_col, "—")) if mpn_col else "—",
                        str(row.get(manufacturer_col, "—")) if manufacturer_col else "—",
                        str(row.get(risk_col, "—")) if risk_col else "—",
                        str(row.get(lifecycle_col, "—")) if lifecycle_col else "—",
                        str(row.get(stock_col, "—")) if stock_col else "—",
                    ]
                )

            parts_table = Table(table_data, repeatRows=1, colWidths=[105, 110, 65, 110, 70])
            parts_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.append(parts_table)

        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()

    total_reports = len(report_records)
    total_parts = sum(
        _report_int(
            _report_value(
                row,
                "total_parts",
                "part_count",
                "parts_count",
                default=0,
            )
        )
        for row in report_records
    )
    total_high_risk = sum(
        _report_int(
            _report_value(
                row,
                "high_risk_count",
                "high_risk_parts",
                default=0,
            )
        )
        for row in report_records
    )
    health_values = [
        _report_int(_report_value(row, "health_score", default=0))
        for row in report_records
        if _report_value(row, "health_score", default=None) is not None
    ]
    average_health = (
        round(sum(health_values) / len(health_values))
        if health_values
        else 0
    )

    st.markdown(
        """
        <style id="cadivor-reports-professional-v9a">
        .cv-r9-hero{
            border:1px solid #BFDBFE;border-radius:26px;padding:30px 32px;
            background:
                radial-gradient(circle at 88% 8%,rgba(37,99,235,.13),transparent 34%),
                linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 62%,#EEF5FF 100%);
            box-shadow:0 22px 58px rgba(15,23,42,.07);margin-bottom:18px;
        }
        .cv-r9-eyebrow{
            display:inline-flex;align-items:center;gap:7px;padding:7px 11px;
            border:1px solid #BFDBFE;border-radius:999px;background:#EFF6FF;
            color:#2563EB!important;font-size:10px;font-weight:950;
            letter-spacing:.12em;text-transform:uppercase;margin-bottom:15px;
        }
        .cv-r9-title{
            color:#0F172A!important;font-size:38px;line-height:1.05;font-weight:980;
            letter-spacing:-.045em;margin:0 0 11px;
        }
        .cv-r9-copy{
            color:#52647A!important;font-size:15px;line-height:1.62;font-weight:680;
            max-width:880px;margin:0;
        }
        .cv-r9-metrics{
            display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
            gap:12px;margin:18px 0 24px;
        }
        .cv-r9-metric{
            border:1px solid #E2E8F0;background:#FFFFFF;border-radius:19px;padding:17px;
            box-shadow:0 14px 34px rgba(15,23,42,.05);
        }
        .cv-r9-metric span{
            display:block;color:#64748B!important;font-size:9px;font-weight:950;
            letter-spacing:.09em;text-transform:uppercase;margin-bottom:7px;
        }
        .cv-r9-metric strong{
            display:block;color:#0F172A!important;font-size:27px;font-weight:980;
            letter-spacing:-.03em;
        }
        .cv-r9-metric small{
            display:block;color:#64748B!important;font-size:10px;font-weight:760;
            margin-top:6px;line-height:1.4;
        }
        .cv-r9-section{
            color:#0F172A!important;font-size:22px;font-weight:980;
            letter-spacing:-.03em;margin:25px 0 5px;
        }
        .cv-r9-sub{
            color:#64748B!important;font-size:12px;font-weight:740;margin-bottom:12px;
        }
        .cv-r9-template-grid{
            display:grid;
            gap:16px;
            align-items:stretch;
            width:100%;
            margin:0 0 16px;
        }
        .cv-r9-template-grid.three{
            grid-template-columns:repeat(3,minmax(0,1fr));
        }
        .cv-r9-template-grid.two{
            grid-template-columns:repeat(2,minmax(0,1fr));
        }
        .cv-r9-template{
            box-sizing:border-box;
            width:100%;
            min-width:0;
            min-height:195px;
            height:100%;
            border:1px solid #E2E8F0;
            background:#FFFFFF;
            border-radius:21px;
            padding:19px;
            box-shadow:0 15px 38px rgba(15,23,42,.05);
        }
        .cv-r9-template-icon{
            width:42px;height:42px;border-radius:13px;display:flex;
            align-items:center;justify-content:center;background:#EFF6FF;
            border:1px solid #BFDBFE;color:#2563EB!important;font-size:19px;
            font-weight:950;margin-bottom:13px;
        }
        .cv-r9-template h4{
            margin:0 0 7px;color:#0F172A!important;font-size:15px;font-weight:970;
        }
        .cv-r9-template p{
            margin:0;color:#52647A!important;font-size:11px;font-weight:720;
            line-height:1.52;min-height:50px;
        }
        .cv-r9-formats{display:flex;gap:6px;flex-wrap:wrap;margin-top:13px}
        .cv-r9-format{
            display:inline-flex;border:1px solid #DBEAFE;background:#EFF6FF;
            color:#1D4ED8!important;border-radius:999px;padding:5px 8px;
            font-size:9px;font-weight:950;
        }
        .cv-r9-selected{
            border:1px solid #BFDBFE;background:linear-gradient(135deg,#FFFFFF,#EFF6FF);
            border-radius:22px;padding:20px;box-shadow:0 17px 42px rgba(37,99,235,.07);
            margin:12px 0 15px;
        }
        .cv-r9-selected-grid{
            display:grid;grid-template-columns:1.35fr repeat(4,minmax(0,1fr));
            gap:10px;
        }
        .cv-r9-selected-cell{
            border:1px solid #DCE5F1;background:rgba(255,255,255,.9);
            border-radius:14px;padding:12px;min-width:0;
        }
        .cv-r9-selected-cell span{
            display:block;color:#64748B!important;font-size:8px;font-weight:950;
            letter-spacing:.09em;text-transform:uppercase;margin-bottom:6px;
        }
        .cv-r9-selected-cell strong{
            display:block;color:#0F172A!important;font-size:13px;font-weight:950;
            overflow-wrap:anywhere;
        }
        .cv-r9-preview-card{
            border:1px solid #E2E8F0;background:#FFFFFF;border-radius:19px;
            padding:17px;box-shadow:0 14px 34px rgba(15,23,42,.04);margin-bottom:12px;
        }
        .cv-r9-preview-title{
            color:#0F172A!important;font-size:14px;font-weight:970;margin-bottom:7px;
        }
        .cv-r9-preview-copy{
            color:#52647A!important;font-size:11px;font-weight:720;line-height:1.55;
        }
        .cv-r9-history{
            border:1px solid #E2E8F0;background:#FFFFFF;border-radius:19px;padding:16px;
        }
        .cv-r9-empty{
            border:1px dashed #CBD5E1;background:#F8FAFC;border-radius:18px;
            padding:22px;text-align:center;color:#64748B!important;font-size:12px;
            font-weight:760;
        }
        @media(max-width:1050px){
            .cv-r9-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
            .cv-r9-selected-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
            .cv-r9-template-grid.three{grid-template-columns:repeat(2,minmax(0,1fr))}
        }
        @media(max-width:760px){
            .cv-r9-template-grid.three,
            .cv-r9-template-grid.two{grid-template-columns:1fr}
        }
        @media(max-width:650px){
            .cv-r9-metrics,.cv-r9-selected-grid{grid-template-columns:1fr}
            .cv-r9-title{font-size:31px}
        }
        </style>
        <div class="cv-r9-hero">
          <div class="cv-r9-eyebrow">▤ Cadivor Report Library</div>
          <h1 class="cv-r9-title">Turn BOM intelligence into decisions.</h1>
          <p class="cv-r9-copy">
            Select a saved BOM, preview the engineering story, and generate the right
            deliverable for leadership, design review, sourcing, lifecycle management,
            or replacement planning.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="cv-r9-metrics">
          <div class="cv-r9-metric">
            <span>Saved Analyses</span>
            <strong>{total_reports}</strong>
            <small>Report-ready BOM engineering records</small>
          </div>
          <div class="cv-r9-metric">
            <span>Average Health</span>
            <strong>{average_health}</strong>
            <small>Across all saved BOM analyses</small>
          </div>
          <div class="cv-r9-metric">
            <span>High-Risk Findings</span>
            <strong>{total_high_risk}</strong>
            <small>Components requiring engineering review</small>
          </div>
          <div class="cv-r9-metric">
            <span>Tracked Components</span>
            <strong>{total_parts}</strong>
            <small>Saved component intelligence records</small>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="cv-r9-section">Professional report library</div>'
        '<div class="cv-r9-sub">Portfolio context above shows the scale and overall risk behind the available report packages.</div>',
        unsafe_allow_html=True,
    )

    first_template_data = [
        (
            "Executive BOM Summary",
            "Leadership-ready health, priority risks, decision brief, and recommended actions.",
            "▤",
            ["PDF", "Excel"],
        ),
        (
            "Engineering Risk Review",
            "Component-level lifecycle, stock, supplier diversity, lead-time, and risk evidence.",
            "△",
            ["PDF", "CSV"],
        ),
        (
            "Procurement & Sourcing",
            "Supplier concentration, market stock, cost exposure, and secondary-source priorities.",
            "⇄",
            ["Excel", "CSV"],
        ),
    ]

    first_template_cards = []
    for title, copy, icon, formats in first_template_data:
        format_html = "".join(
            f'<span class="cv-r9-format">{fmt}</span>'
            for fmt in formats
        )
        first_template_cards.append(
            (
                f'<div class="cv-r9-template">'
                f'<div class="cv-r9-template-icon">{icon}</div>'
                f'<h4>{title}</h4>'
                f'<p>{copy}</p>'
                f'<div class="cv-r9-formats">{format_html}</div>'
                f'</div>'
            )
        )

    st.markdown(
        '<div class="cv-r9-template-grid three">'
        + "".join(first_template_cards)
        + "</div>",
        unsafe_allow_html=True,
    )

    second_template_data = [
        (
            "Lifecycle Exposure Report",
            "Lifecycle states, obsolete or replacement-suggested components, and alert-oriented review data.",
            "◷",
            ["PDF", "Excel", "CSV"],
        ),
        (
            "Alternative Replacement Report",
            "Components requiring alternatives, candidate availability, and saved replacement-readiness fields.",
            "↔",
            ["PDF", "Excel", "CSV"],
        ),
    ]

    second_template_cards = []
    for title, copy, icon, formats in second_template_data:
        format_html = "".join(
            f'<span class="cv-r9-format">{fmt}</span>'
            for fmt in formats
        )
        second_template_cards.append(
            (
                f'<div class="cv-r9-template">'
                f'<div class="cv-r9-template-icon">{icon}</div>'
                f'<h4>{title}</h4>'
                f'<p>{copy}</p>'
                f'<div class="cv-r9-formats">{format_html}</div>'
                f'</div>'
            )
        )

    st.markdown(
        '<div class="cv-r9-template-grid two">'
        + "".join(second_template_cards)
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="cv-r9-section">Build a report package</div>'
        '<div class="cv-r9-sub">Search for a saved BOM, confirm the selected engineering record, preview the content, and download the required files.</div>',
        unsafe_allow_html=True,
    )

    if report_records:
        labels = [_analysis_label(row) for row in report_records]

        incoming_report_analysis_id = str(
            st.query_params.get("analysis_id", "") or ""
        ).strip()
        report_route_token = (
            f"reports::{incoming_report_analysis_id}"
            if incoming_report_analysis_id
            else ""
        )

        if (
            incoming_report_analysis_id
            and st.session_state.get("reports_route_token") != report_route_token
        ):
            matching_label = None
            for row, label in zip(report_records, labels):
                row_id = str(
                    _report_value(
                        row,
                        "id",
                        "analysis_id",
                        default="",
                    )
                    or ""
                ).strip()
                if row_id == incoming_report_analysis_id:
                    matching_label = label
                    break

            if matching_label:
                st.session_state["reports_selected_analysis"] = matching_label
                st.session_state["reports_route_token"] = report_route_token

        search_col, select_col = st.columns([0.34, 0.66], gap="medium")
        with search_col:
            report_search = st.text_input(
                "Search saved analyses",
                placeholder="Project or source filename",
                key="reports_analysis_search",
            )

        filtered_labels = labels
        if report_search.strip():
            needle = report_search.strip().lower()
            filtered_labels = [
                label
                for label in labels
                if needle in label.lower()
            ]

        if not filtered_labels:
            st.warning("No saved analyses match that search.")
            filtered_labels = labels

        current_selected = st.session_state.get("reports_selected_analysis")
        if current_selected not in filtered_labels:
            st.session_state["reports_selected_analysis"] = filtered_labels[0]

        with select_col:
            selected_label = st.selectbox(
                "Saved BOM analysis",
                filtered_labels,
                key="reports_selected_analysis",
            )

        selected_index = labels.index(selected_label)
        selected_analysis = report_records[selected_index]
        selected_analysis_id = _report_value(
            selected_analysis,
            "id",
            "analysis_id",
            default=None,
        )
        selected_parts_df = _load_report_parts(selected_analysis_id)

        project_name = str(
            _report_value(
                selected_analysis,
                "project_name",
                "name",
                default="Saved BOM",
            )
        )
        source_file = str(
            _report_value(
                selected_analysis,
                "filename",
                "uploaded_file",
                "file_name",
                default="—",
            )
        )
        health_score = _report_int(
            _report_value(selected_analysis, "health_score", default=0)
        )
        high_risk = _report_int(
            _report_value(
                selected_analysis,
                "high_risk_count",
                "high_risk_parts",
                default=0,
            )
        )
        medium_risk = _report_int(
            _report_value(
                selected_analysis,
                "medium_risk_count",
                "medium_risk_parts",
                default=0,
            )
        )
        part_count = _report_int(
            _report_value(
                selected_analysis,
                "total_parts",
                "part_count",
                "parts_count",
                default=len(selected_parts_df),
            )
        )
        created_at = str(
            _report_value(
                selected_analysis,
                "created_at",
                "updated_at",
                "date",
                default="",
            )
        )
        created_date = (
            created_at.split("T")[0]
            if "T" in created_at
            else created_at[:10]
        ) or "—"

        safe_project = (
            re.sub(r"[^A-Za-z0-9_-]+", "_", project_name).strip("_")
            or "saved_bom"
        )

        st.markdown(
            f"""
            <div class="cv-r9-selected">
              <div class="cv-r9-selected-grid">
                <div class="cv-r9-selected-cell">
                  <span>Selected BOM</span>
                  <strong>{html.escape(project_name)}</strong>
                </div>
                <div class="cv-r9-selected-cell">
                  <span>Health</span>
                  <strong>{health_score}/100</strong>
                </div>
                <div class="cv-r9-selected-cell">
                  <span>Parts</span>
                  <strong>{part_count}</strong>
                </div>
                <div class="cv-r9-selected-cell">
                  <span>High / Medium Risk</span>
                  <strong>{high_risk} / {medium_risk}</strong>
                </div>
                <div class="cv-r9-selected-cell">
                  <span>Saved</span>
                  <strong>{html.escape(created_date)}</strong>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        def _customer_report_table(
            frame: pd.DataFrame,
            preferred_columns: list[str] | None = None,
        ) -> pd.DataFrame:
            """Return a customer-facing report preview without database fields."""
            if frame is None or frame.empty:
                return pd.DataFrame()

            cleaned = frame.copy()

            hidden_columns = {
                "id",
                "user_id",
                "analysis_id",
                "workspace_id",
                "organization_id",
                "created_at",
                "updated_at",
                "raw_data",
                "metadata",
            }
            cleaned = cleaned[
                [
                    column
                    for column in cleaned.columns
                    if str(column).strip().lower() not in hidden_columns
                ]
            ]

            if preferred_columns:
                existing = [
                    column
                    for column in preferred_columns
                    if column in cleaned.columns
                ]
                if existing:
                    cleaned = cleaned[existing]

            human_labels = {
                "project": "Project",
                "project_name": "Project",
                "source_file": "Source File",
                "filename": "Source File",
                "mpn": "Manufacturer Part Number",
                "MPN": "Manufacturer Part Number",
                "part_number": "Part Number",
                "manufacturer": "Manufacturer",
                "risk_score": "Risk Score",
                "risk_level": "Risk Level",
                "risk_reasons": "Risk Explanation",
                "lifecycle_status": "Lifecycle Status",
                "stock_available": "Available Stock",
                "stock": "Available Stock",
                "supplier_count": "Supplier Sources",
                "unit_price": "Unit Price",
                "lead_time": "Lead Time",
                "lead_time_weeks": "Lead Time (Weeks)",
                "has_alternates": "Alternatives Available",
                "alternate_count": "Alternative Count",
                "alternate_part_numbers": "Alternative Part Numbers",
                "health_score": "Health Score",
                "high_risk_parts": "High-Risk Components",
                "medium_risk_parts": "Medium-Risk Components",
                "message": "Status",
            }

            cleaned = cleaned.rename(
                columns={
                    column: human_labels.get(
                        column,
                        str(column).replace("_", " ").strip().title(),
                    )
                    for column in cleaned.columns
                }
            )
            return cleaned

        def _first_existing(frame: pd.DataFrame, names: list[str], default=None):
            for name in names:
                if name in frame.columns:
                    return frame[name]
            return pd.Series([default] * len(frame), index=frame.index)

        def _risk_action(row: pd.Series) -> str:
            lifecycle = str(row.get("lifecycle_status", "")).lower()
            stock = float(pd.to_numeric(row.get("stock_available", 0), errors="coerce") or 0)
            suppliers = float(pd.to_numeric(row.get("supplier_count", 0), errors="coerce") or 0)
            score = float(pd.to_numeric(row.get("risk_score", 0), errors="coerce") or 0)
            if any(term in lifecycle for term in ("obsolete", "eol", "replacement", "nrnd", "not recommended")):
                return "Qualify a replacement before production"
            if stock <= 0:
                return "Resolve supply gap or approve substitute"
            if suppliers <= 1:
                return "Approve a second source"
            if score >= 60:
                return "Complete engineering review before release"
            if score >= 30:
                return "Review during current design revision"
            return "Continue controlled monitoring"

        def _procurement_status(row: pd.Series) -> str:
            stock = float(pd.to_numeric(row.get("stock_available", 0), errors="coerce") or 0)
            suppliers = float(pd.to_numeric(row.get("supplier_count", 0), errors="coerce") or 0)
            lead = float(pd.to_numeric(row.get("lead_time_weeks", 0), errors="coerce") or 0)
            if stock <= 0:
                return "Immediate sourcing action"
            if suppliers <= 1:
                return "Single-source exposure"
            if lead >= 16:
                return "Long lead time"
            if stock < 500:
                return "Low stock coverage"
            return "Purchasing ready"

        def _lifecycle_priority(status: str) -> str:
            value = str(status or "").lower()
            if any(term in value for term in ("obsolete", "eol", "end of life")):
                return "Immediate replacement"
            if any(term in value for term in ("replacement", "nrnd", "not recommended")):
                return "Qualification required"
            if value in ("active", "new at mouser", "new"):
                return "Routine monitoring"
            return "Status verification required"

        lifecycle_columns = [
            column
            for column in [
                "mpn",
                "MPN",
                "part_number",
                "manufacturer",
                "lifecycle_status",
                "Lifecycle Status",
                "risk_level",
                "risk_score",
                "stock_available",
                "supplier_count",
            ]
            if column in selected_parts_df.columns
        ]
        lifecycle_df = (
            selected_parts_df[lifecycle_columns].copy()
            if lifecycle_columns
            else selected_parts_df.copy()
        )

        alternative_columns = [
            column
            for column in [
                "mpn",
                "MPN",
                "part_number",
                "manufacturer",
                "risk_level",
                "risk_score",
                "has_alternates",
                "alternate_count",
                "alternate_part_numbers",
                "lifecycle_status",
                "stock_available",
            ]
            if column in selected_parts_df.columns
        ]
        alternative_df = (
            selected_parts_df[alternative_columns].copy()
            if alternative_columns
            else selected_parts_df.copy()
        )

        sourcing_candidates = [
            "mpn",
            "part_number",
            "manufacturer",
            "lifecycle_status",
            "stock_available",
            "stock",
            "supplier_count",
            "unit_price",
            "risk_level",
            "risk_score",
            "has_alternates",
            "alternate_count",
        ]
        if selected_parts_df.empty:
            engineering_df = pd.DataFrame()
            sourcing_df = pd.DataFrame()
            lifecycle_df = pd.DataFrame()
            alternative_df = pd.DataFrame()
        else:
            role_source = selected_parts_df.copy()

            role_source["mpn"] = _first_existing(
                role_source,
                ["mpn", "MPN", "part_number"],
                "Unknown",
            )
            role_source["manufacturer"] = _first_existing(
                role_source,
                ["manufacturer", "Manufacturer"],
                "Unknown",
            )
            role_source["risk_level"] = _first_existing(
                role_source,
                ["risk_level", "Risk Level"],
                "Unknown",
            )
            role_source["risk_score"] = pd.to_numeric(
                _first_existing(role_source, ["risk_score", "Risk Score"], 0),
                errors="coerce",
            ).fillna(0)
            role_source["risk_reasons"] = _first_existing(
                role_source,
                ["risk_reasons", "Risk Explanation"],
                "No specific exception recorded",
            )
            role_source["lifecycle_status"] = _first_existing(
                role_source,
                ["lifecycle_status", "Lifecycle Status"],
                "Unknown",
            )
            role_source["stock_available"] = pd.to_numeric(
                _first_existing(
                    role_source,
                    ["stock_available", "Stock Available", "stock"],
                    0,
                ),
                errors="coerce",
            ).fillna(0)
            role_source["supplier_count"] = pd.to_numeric(
                _first_existing(
                    role_source,
                    ["supplier_count", "Supplier Count"],
                    0,
                ),
                errors="coerce",
            ).fillna(0)
            role_source["primary_supplier"] = _first_existing(
                role_source,
                ["supplier", "primary_supplier", "best_source", "Supplier"],
                "Not recorded",
            )
            role_source["unit_price"] = pd.to_numeric(
                _first_existing(
                    role_source,
                    ["unit_price", "Unit Price"],
                    0,
                ),
                errors="coerce",
            ).fillna(0)
            role_source["lead_time_weeks"] = pd.to_numeric(
                _first_existing(
                    role_source,
                    ["lead_time_weeks", "Lead Time Weeks", "lead_time"],
                    0,
                ),
                errors="coerce",
            ).fillna(0)

            role_source["Engineering Priority"] = role_source["risk_score"].apply(
                lambda value: (
                    "Immediate"
                    if value >= 75
                    else "High"
                    if value >= 50
                    else "Moderate"
                    if value >= 25
                    else "Routine"
                )
            )
            role_source["Recommended Action"] = role_source.apply(
                _risk_action,
                axis=1,
            )

            engineering_df = pd.DataFrame(
                {
                    "Manufacturer Part Number": role_source["mpn"],
                    "Manufacturer": role_source["manufacturer"],
                    "Risk Level": role_source["risk_level"],
                    "Risk Score": role_source["risk_score"],
                    "Risk Explanation": role_source["risk_reasons"],
                    "Engineering Priority": role_source["Engineering Priority"],
                    "Recommended Action": role_source["Recommended Action"],
                    "_sort_risk_score": role_source["risk_score"],
                }
            ).sort_values(
                by="_sort_risk_score",
                ascending=False,
                kind="stable",
            ).drop(columns=["_sort_risk_score"])

            role_source["Procurement Status"] = role_source.apply(
                _procurement_status,
                axis=1,
            )
            sourcing_df = pd.DataFrame(
                {
                    "Manufacturer Part Number": role_source["mpn"],
                    "Manufacturer": role_source["manufacturer"],
                    "Primary Supplier": role_source["primary_supplier"],
                    "Available Stock": role_source["stock_available"],
                    "Unit Price": role_source["unit_price"],
                    "Lead Time (Weeks)": role_source["lead_time_weeks"],
                    "Supplier Sources": role_source["supplier_count"],
                    "Procurement Status": role_source["Procurement Status"],
                    "_sort_stock": role_source["stock_available"],
                    "_sort_sources": role_source["supplier_count"],
                }
            ).sort_values(
                by=["_sort_stock", "_sort_sources"],
                ascending=[True, True],
                kind="stable",
            ).drop(columns=["_sort_stock", "_sort_sources"])

            role_source["Future Availability"] = role_source[
                "lifecycle_status"
            ].apply(
                lambda status: (
                    "At risk"
                    if any(
                        term in str(status).lower()
                        for term in (
                            "obsolete",
                            "eol",
                            "end of life",
                            "replacement",
                            "nrnd",
                            "not recommended",
                        )
                    )
                    else "Expected to continue"
                    if str(status).lower() == "active"
                    else "Needs verification"
                )
            )
            role_source["Replacement Readiness"] = role_source[
                "lifecycle_status"
            ].apply(
                lambda status: (
                    "Replacement required"
                    if any(
                        term in str(status).lower()
                        for term in ("obsolete", "eol", "end of life")
                    )
                    else "Successor qualification advised"
                    if any(
                        term in str(status).lower()
                        for term in ("replacement", "nrnd", "not recommended")
                    )
                    else "No immediate replacement"
                )
            )
            role_source["Review Priority"] = role_source[
                "lifecycle_status"
            ].apply(_lifecycle_priority)

            lifecycle_rank = {
                "Immediate replacement": 0,
                "Qualification required": 1,
                "Status verification required": 2,
                "Routine monitoring": 3,
            }
            role_source["_lifecycle_rank"] = role_source[
                "Review Priority"
            ].map(lifecycle_rank).fillna(4)

            lifecycle_df = pd.DataFrame(
                {
                    "Manufacturer Part Number": role_source["mpn"],
                    "Manufacturer": role_source["manufacturer"],
                    "Lifecycle Status": role_source["lifecycle_status"],
                    "Future Availability": role_source["Future Availability"],
                    "Replacement Readiness": role_source["Replacement Readiness"],
                    "Review Priority": role_source["Review Priority"],
                    "_sort_lifecycle_rank": role_source["_lifecycle_rank"],
                }
            ).sort_values(
                by="_sort_lifecycle_rank",
                ascending=True,
                kind="stable",
            ).drop(columns=["_sort_lifecycle_rank"])

            has_alternates = _first_existing(
                role_source,
                ["has_alternates", "alternatives_available"],
                False,
            )
            alternate_count = pd.to_numeric(
                _first_existing(
                    role_source,
                    ["alternate_count", "alternatives_count"],
                    0,
                ),
                errors="coerce",
            ).fillna(0)
            alternate_parts = _first_existing(
                role_source,
                [
                    "alternate_part_numbers",
                    "recommended_alternative",
                    "alternative_part",
                ],
                "Not yet qualified",
            )

            role_source["Replacement Status"] = [
                (
                    "Candidates available"
                    if bool(available) or count > 0
                    else "Alternative search required"
                )
                for available, count in zip(has_alternates, alternate_count)
            ]
            role_source["Recommended Replacement"] = alternate_parts
            role_source["Alternative Count"] = alternate_count.astype(int)
            role_source["Next Engineering Step"] = role_source[
                "Replacement Status"
            ].apply(
                lambda status: (
                    "Review compatibility and approve candidate"
                    if status == "Candidates available"
                    else "Run Alternative Finder"
                )
            )

            alternative_df = pd.DataFrame(
                {
                    "Original Component": role_source["mpn"],
                    "Manufacturer": role_source["manufacturer"],
                    "Current Lifecycle": role_source["lifecycle_status"],
                    "Replacement Status": role_source["Replacement Status"],
                    "Recommended Replacement": role_source["Recommended Replacement"],
                    "Alternative Count": role_source["Alternative Count"],
                    "Next Engineering Step": role_source["Next Engineering Step"],
                    "_sort_alternative_count": role_source["Alternative Count"],
                    "_sort_risk_score": role_source["risk_score"],
                }
            ).sort_values(
                by=["_sort_alternative_count", "_sort_risk_score"],
                ascending=[False, False],
                kind="stable",
            )

            alternative_df = alternative_df.drop(
                columns=["_sort_alternative_count", "_sort_risk_score"]
            )

        pdf_bytes = _build_executive_pdf(
            selected_analysis,
            selected_parts_df,
        )
        ai_report = build_ai_report_intelligence(
            selected_analysis,
            selected_parts_df,
        )
        ai_executive_pdf = build_ai_executive_pdf(ai_report)
        ai_procurement_pdf = build_ai_procurement_pdf(ai_report)
        risk_report_pdf = build_role_report_pdf(
            title="Cadivor Engineering Risk Review",
            subtitle="Components ranked by technical risk requiring engineering attention.",
            project_name=project_name,
            dataframe=engineering_df,
            summary_lines=[
                f"High-risk components: {high_risk}",
                f"Medium-risk components: {medium_risk}",
            ],
        )
        sourcing_report_pdf = build_role_report_pdf(
            title="Cadivor Procurement & Sourcing Review",
            subtitle="Components ranked by purchasing availability and sourcing difficulty.",
            project_name=project_name,
            dataframe=sourcing_df,
            summary_lines=[
                ai_report["procurement_summary"],
            ],
        )
        lifecycle_report_pdf = build_role_report_pdf(
            title="Cadivor Lifecycle Readiness Review",
            subtitle="Manufacturer lifecycle status and future availability assessment.",
            project_name=project_name,
            dataframe=lifecycle_df,
            summary_lines=[
                f"Lifecycle concerns identified: {ai_report['lifecycle_concerns']}",
            ],
        )
        alternatives_report_pdf = build_role_report_pdf(
            title="Cadivor Alternative Readiness Review",
            subtitle="Replacement readiness and next qualification actions.",
            project_name=project_name,
            dataframe=alternative_df,
            summary_lines=[
                "Use this report to identify components requiring an Alternative Finder review.",
            ],
        )

        risk_report_csv = engineering_df.to_csv(index=False).encode("utf-8")
        sourcing_report_csv = sourcing_df.to_csv(index=False).encode("utf-8")
        lifecycle_report_csv = lifecycle_df.to_csv(index=False).encode("utf-8")
        alternatives_report_csv = alternative_df.to_csv(index=False).encode("utf-8")
        executive_csv = pd.DataFrame(
            [
                {
                    "project": project_name,
                    "source_file": source_file,
                    "health_score": health_score,
                    "part_count": part_count,
                    "high_risk_parts": high_risk,
                    "medium_risk_parts": medium_risk,
                    "saved_date": created_date,
                }
            ]
        ).to_csv(index=False).encode("utf-8")

        preview_tabs = st.tabs(
            [
                "AI Executive Brief",
                "AI Procurement Brief",
                "Engineering Risk Review",
                "Procurement & Sourcing Review",
                "Lifecycle Readiness Review",
                "Alternative Readiness Review",
            ]
        )

        with preview_tabs[0]:
            st.markdown(
                f"""
                <div class="cv-r9-preview-card">
                  <div class="cv-r9-preview-title">AI Executive Decision Brief</div>
                  <div class="cv-r9-preview-copy">
                    <b>Production readiness:</b> {html.escape(ai_report['readiness'])}
                    <br><br>{html.escape(ai_report['executive_summary'])}
                    <br><br><b>Management decision:</b>
                    {html.escape(ai_report['executive_decision'])}
                    <br><br><b>Projected health:</b>
                    {ai_report['health']}/100 → {ai_report['projected_health']}/100
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with preview_tabs[1]:
            procurement_items = "".join(
                f"<li>{html.escape(item)}</li>"
                for item in ai_report["procurement_actions"]
            )
            st.markdown(
                f"""
                <div class="cv-r9-preview-card">
                  <div class="cv-r9-preview-title">AI Procurement Brief</div>
                  <div class="cv-r9-preview-copy">
                    {html.escape(ai_report['procurement_summary'])}
                    <br><br><b>Priority actions</b>
                    <ul>{procurement_items}</ul>
                    <b>Estimated procurement effort:</b>
                    {ai_report['procurement_hours']} hour(s)
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with preview_tabs[2]:
            st.markdown("### Engineering Risk Review")
            st.caption(
                "For design and component engineers: components ranked by technical risk, "
                "with the reason and recommended engineering action."
            )
            if engineering_df.empty:
                st.info("No component-level risk data is available.")
            else:
                st.dataframe(
                    engineering_df,
                    hide_index=True,
                    use_container_width=True,
                )
                risk_pdf_col, risk_csv_col = st.columns(2)
                with risk_pdf_col:
                    st.download_button(
                        "Download Risk Review PDF",
                        data=risk_report_pdf,
                        key=f"tab_risk_pdf_{selected_analysis_id}",
                        file_name=f"{safe_project}_engineering_risk_review.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                with risk_csv_col:
                    st.download_button(
                        "Download Risk Review CSV",
                        data=risk_report_csv,
                        key=f"tab_risk_csv_{selected_analysis_id}",
                        file_name=f"{safe_project}_engineering_risk_review.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

        with preview_tabs[3]:
            st.markdown("### Procurement & Sourcing Review")
            st.caption(
                "For procurement and supply chain: purchasing availability, supplier coverage, "
                "lead time, pricing, and the required sourcing response."
            )
            if sourcing_df.empty:
                st.info("No sourcing fields are available for this analysis.")
            else:
                st.dataframe(
                    sourcing_df,
                    hide_index=True,
                    use_container_width=True,
                )
                sourcing_pdf_col, sourcing_csv_col = st.columns(2)
                with sourcing_pdf_col:
                    st.download_button(
                        "Download Sourcing Review PDF",
                        data=sourcing_report_pdf,
                        key=f"tab_sourcing_pdf_{selected_analysis_id}",
                        file_name=f"{safe_project}_procurement_sourcing_review.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                with sourcing_csv_col:
                    st.download_button(
                        "Download Sourcing Review CSV",
                        data=sourcing_report_csv,
                        key=f"tab_sourcing_csv_{selected_analysis_id}",
                        file_name=f"{safe_project}_procurement_sourcing_review.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

        with preview_tabs[4]:
            st.markdown("### Lifecycle Readiness Review")
            st.caption(
                "For component engineering: lifecycle continuity, future availability, "
                "replacement readiness, and review priority."
            )
            if lifecycle_df.empty:
                st.info("No lifecycle fields are available for this analysis.")
            else:
                st.dataframe(
                    lifecycle_df,
                    hide_index=True,
                    use_container_width=True,
                )
                lifecycle_pdf_col, lifecycle_csv_col = st.columns(2)
                with lifecycle_pdf_col:
                    st.download_button(
                        "Download Lifecycle Review PDF",
                        data=lifecycle_report_pdf,
                        key=f"tab_lifecycle_pdf_{selected_analysis_id}",
                        file_name=f"{safe_project}_lifecycle_readiness_review.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                with lifecycle_csv_col:
                    st.download_button(
                        "Download Lifecycle Review CSV",
                        data=lifecycle_report_csv,
                        key=f"tab_lifecycle_csv_{selected_analysis_id}",
                        file_name=f"{safe_project}_lifecycle_readiness_review.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

        with preview_tabs[5]:
            st.markdown("### Alternative Readiness Review")
            st.caption(
                "For replacement qualification: which components already have candidates "
                "and which require an Alternative Finder search."
            )
            if alternative_df.empty:
                st.info("No alternative-readiness fields are available for this analysis.")
            else:
                st.dataframe(
                    alternative_df,
                    hide_index=True,
                    use_container_width=True,
                )
                alt_pdf_col, alt_csv_col = st.columns(2)
                with alt_pdf_col:
                    st.download_button(
                        "Download Alternatives Review PDF",
                        data=alternatives_report_pdf,
                        key=f"tab_alternatives_pdf_{selected_analysis_id}",
                        file_name=f"{safe_project}_alternative_readiness_review.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                with alt_csv_col:
                    st.download_button(
                        "Download Alternatives Review CSV",
                        data=alternatives_report_csv,
                        key=f"tab_alternatives_csv_{selected_analysis_id}",
                        file_name=f"{safe_project}_alternative_readiness_review.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

        st.markdown(
            '<div class="cv-r9-section">Report packages</div>'
            '<div class="cv-r9-sub">Downloads are generated from the selected saved BOM analysis.</div>',
            unsafe_allow_html=True,
        )

        if "reports_session_history" not in st.session_state:
            st.session_state["reports_session_history"] = []

        def _record_session_report(report_type: str, file_name: str) -> None:
            st.session_state["reports_session_history"].insert(
                0,
                {
                    "Project": project_name,
                    "Report": report_type,
                    "File": file_name,
                    "Generated": pd.Timestamp.utcnow().strftime(
                        "%Y-%m-%d %H:%M UTC"
                    ),
                },
            )
            st.session_state["reports_session_history"] = (
                st.session_state["reports_session_history"][:12]
            )

        with st.expander("Executive reports", expanded=True):
            st.caption("Leadership-ready summaries for release, risk, and management review.")
            ai_exec_col, executive_pdf_col, executive_csv_col = st.columns(3)
            with ai_exec_col:
                ai_exec_name = f"{safe_project}_ai_executive_brief.pdf"
                if st.download_button(
                    "AI Executive Brief · PDF",
                    key=f"shared_ai_executive_pdf_{selected_analysis_id}",
                    data=ai_executive_pdf,
                    file_name=ai_exec_name,
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                    on_click=_mark_first_report_complete,
                ):
                    _record_session_report("AI Executive Brief", ai_exec_name)
            with executive_pdf_col:
                executive_pdf_name = f"{safe_project}_executive_summary.pdf"
                if st.download_button(
                    "Executive Summary · PDF",
                    key=f"shared_executive_pdf_{selected_analysis_id}",
                    data=pdf_bytes,
                    file_name=executive_pdf_name,
                    mime="application/pdf",
                    use_container_width=True,
                    on_click=_mark_first_report_complete,
                ):
                    _record_session_report("Executive BOM Summary", executive_pdf_name)
            with executive_csv_col:
                executive_csv_name = f"{safe_project}_executive_summary.csv"
                if st.download_button(
                    "Executive Data · CSV",
                    key=f"shared_executive_csv_{selected_analysis_id}",
                    data=executive_csv,
                    file_name=executive_csv_name,
                    mime="text/csv",
                    use_container_width=True,
                    on_click=_mark_first_report_complete,
                ):
                    _record_session_report("Executive BOM Summary", executive_csv_name)

        with st.expander("Engineering reports", expanded=False):
            st.caption("Technical reviews for component risk, lifecycle readiness, and alternatives.")
            risk_col, lifecycle_col, alternatives_col = st.columns(3)
            with risk_col:
                risk_csv_name = f"{safe_project}_engineering_risk_review.csv"
                if st.download_button(
                    "Risk Review · CSV",
                    key=f"shared_risk_csv_{selected_analysis_id}",
                    data=engineering_df.to_csv(index=False).encode("utf-8"),
                    file_name=risk_csv_name,
                    mime="text/csv",
                    use_container_width=True,
                    on_click=_mark_first_report_complete,
                ):
                    _record_session_report("Engineering Risk Review", risk_csv_name)
            with lifecycle_col:
                lifecycle_csv_name = f"{safe_project}_lifecycle_exposure.csv"
                if st.download_button(
                    "Lifecycle Review · CSV",
                    key=f"shared_lifecycle_csv_{selected_analysis_id}",
                    data=lifecycle_df.to_csv(index=False).encode("utf-8"),
                    file_name=lifecycle_csv_name,
                    mime="text/csv",
                    use_container_width=True,
                    on_click=_mark_first_report_complete,
                ):
                    _record_session_report("Lifecycle Exposure Report", lifecycle_csv_name)
            with alternatives_col:
                alternatives_csv_name = f"{safe_project}_alternative_readiness.csv"
                if st.download_button(
                    "Alternatives Review · CSV",
                    key=f"shared_alternatives_csv_{selected_analysis_id}",
                    data=alternative_df.to_csv(index=False).encode("utf-8"),
                    file_name=alternatives_csv_name,
                    mime="text/csv",
                    use_container_width=True,
                    on_click=_mark_first_report_complete,
                ):
                    _record_session_report("Alternative Replacement Report", alternatives_csv_name)

        with st.expander("Procurement reports", expanded=False):
            st.caption("Purchasing and sourcing packages for procurement and supplier review.")
            ai_proc_col, sourcing_col = st.columns(2)
            with ai_proc_col:
                ai_proc_name = f"{safe_project}_ai_procurement_brief.pdf"
                if st.download_button(
                    "AI Procurement Brief · PDF",
                    key=f"shared_ai_procurement_pdf_{selected_analysis_id}",
                    data=ai_procurement_pdf,
                    file_name=ai_proc_name,
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                    on_click=_mark_first_report_complete,
                ):
                    _record_session_report("AI Procurement Brief", ai_proc_name)
            with sourcing_col:
                sourcing_csv_name = f"{safe_project}_sourcing_summary.csv"
                if st.download_button(
                    "Sourcing Review · CSV",
                    key=f"shared_sourcing_csv_{selected_analysis_id}",
                    data=sourcing_df.to_csv(index=False).encode("utf-8"),
                    file_name=sourcing_csv_name,
                    mime="text/csv",
                    use_container_width=True,
                    on_click=_mark_first_report_complete,
                ):
                    _record_session_report("Procurement & Sourcing", sourcing_csv_name)

        action_cols = st.columns(3)
        with action_cols[0]:
            internal_nav_button(
                "Open Analysis Details",
                "Analysis Details",
                key="reports_open_analysis_details",
                use_container_width=True,
                analysis_id=selected_analysis_id,
            )
        with action_cols[1]:
            internal_nav_button(
                "Open in BOM Analyzer",
                "BOM Analyzer",
                key="reports_open_bom_analyzer",
                use_container_width=True,
                analysis_id=selected_analysis_id,
            )
        with action_cols[2]:
            internal_nav_button(
                "Open Alternative Finder",
                "Alternative Finder",
                key="reports_open_alternative_finder",
                use_container_width=True,
                analysis_id=selected_analysis_id,
            )

        st.markdown(
            '<div class="cv-r9-section">Recent generated reports</div>'
            '<div class="cv-r9-sub">Milestone 9A keeps a current-session download history. Persistent history arrives in Milestone 9B.</div>',
            unsafe_allow_html=True,
        )

        session_history = st.session_state.get(
            "reports_session_history",
            [],
        )
        if session_history:
            st.dataframe(
                pd.DataFrame(session_history),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.markdown(
                '<div class="cv-r9-empty">No reports have been downloaded during this session yet.</div>',
                unsafe_allow_html=True,
            )

        with st.expander(
            f"Browse all {len(report_records)} report-ready analyses",
            expanded=False,
        ):
            display_rows = []
            for row in report_records:
                row_created_at = str(
                    _report_value(
                        row,
                        "created_at",
                        "date",
                        default="",
                    )
                )
                row_created_date = (
                    row_created_at.split("T")[0]
                    if "T" in row_created_at
                    else row_created_at[:10]
                )
                display_rows.append(
                    {
                        "Project": _report_value(
                            row,
                            "project_name",
                            "name",
                            default="Saved BOM",
                        ),
                        "Source File": _report_value(
                            row,
                            "filename",
                            "uploaded_file",
                            "file_name",
                            default="—",
                        ),
                        "Date": row_created_date or "—",
                        "Health": _report_int(
                            _report_value(
                                row,
                                "health_score",
                                default=0,
                            )
                        ),
                        "High Risk": _report_int(
                            _report_value(
                                row,
                                "high_risk_count",
                                "high_risk_parts",
                                default=0,
                            )
                        ),
                        "Medium Risk": _report_int(
                            _report_value(
                                row,
                                "medium_risk_count",
                                "medium_risk_parts",
                                default=0,
                            )
                        ),
                        "Parts": _report_int(
                            _report_value(
                                row,
                                "total_parts",
                                "part_count",
                                "parts_count",
                                default=0,
                            )
                        ),
                    }
                )
            st.dataframe(
                pd.DataFrame(display_rows),
                hide_index=True,
                use_container_width=True,
            )
    else:
        st.markdown(
            '<div class="cv-r9-empty">No saved BOM analyses are available. Analyze and save a BOM before generating reports.</div>',
            unsafe_allow_html=True,
        )

    st.stop()


# ---------- Pricing ----------
if app_mode == "Pricing":
    st.subheader("Pricing")
    st.caption("Choose the plan that fits your BOM review workflow.")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            """
            <div class="card">
                <div class="card-title">Starter</div>
                <h2>$29/mo</h2>
                <div class="card-text">
                    ✓ 5 BOMs/month<br>
                    ✓ 10 parts per BOM<br>
                    ✓ Basic risk report<br>
                    ✓ CSV/XLSX export
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            """
            <div class="card" style="border: 2px solid #2563EB;">
                <div class="card-title">Pro 🚀</div>
                <h2>$99/mo</h2>
                <div class="card-text">
                    ✓ 10 BOMs/month<br>
                    ✓ 20 parts per BOM<br>
                    ✓ Multi-supplier intelligence<br>
                    ✓ Alternative finder
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Upgrade to Pro"):
            try:
                checkout_url = create_checkout_session(
                    st.secrets["STRIPE_PRO_PRICE_ID"],
                    current_user["email"],
                    current_user["id"],
                    success_url="https://bom-risk-checker-j9co3yumwgvqjumut24fxm.streamlit.app/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
                    cancel_url="https://bom-risk-checker-j9co3yumwgvqjumut24fxm.streamlit.app/?checkout=cancel",
                )
                st.link_button("Continue to Stripe Checkout", checkout_url)
            except Exception as e:
                st.error(f"Unable to create checkout session: {e}")
                

    with col3:
        st.markdown(
            """
            <div class="card">
                <div class="card-title">Business</div>
                <h2>$299/mo</h2>
                <div class="card-text">
                    ✓ 25 BOMs/month<br>
                    ✓ 100 parts per BOM<br>
                    ✓ Advanced reports<br>
                    ✓ Team-ready workflows
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Upgrade to Business"):
            try:
                checkout_url = create_checkout_session(
                    st.secrets["STRIPE_BUSINESS_PRICE_ID"],
                    current_user["email"],
                    current_user["id"],
                    success_url="https://bom-risk-checker-j9co3yumwgvqjumut24fxm.streamlit.app/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
                    cancel_url="https://bom-risk-checker-j9co3yumwgvqjumut24fxm.streamlit.app/?checkout=cancel",
                )
                st.link_button("Continue to Stripe Checkout", checkout_url)
            except Exception as e:
                st.error(f"Unable to create checkout session: {e}")

    st.stop()


# ---------- Settings ----------
if app_mode == "Settings":
    profile = get_user_profile(current_user)
    auth_user = st.session_state.get("user")
    user_id = _safe_text(
        getattr(auth_user, "id", ""),
        _safe_text(current_user.get("id"), ""),
    )
    auth_email = _safe_text(
        getattr(auth_user, "email", ""),
        profile.get("email", ""),
    )

    customer_profile, profile_error = ensure_customer_profile(
        supabase,
        user_id,
        auth_email,
        profile.get("full_name", ""),
    )
    preferences, preferences_error = ensure_user_preferences(
        supabase,
        user_id,
    )

    customer_profile = customer_profile or {}
    preferences = preferences or {}

    st.markdown(
        """
        <style id="cadivor-customer-settings-v11a1">
        .cv-customer-hero{
            border:1px solid #BFDBFE;
            border-radius:24px;
            padding:26px 28px;
            margin-bottom:18px;
            background:
                radial-gradient(circle at 95% 5%,rgba(37,99,235,.13),transparent 34%),
                linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 100%);
            box-shadow:0 18px 46px rgba(15,23,42,.065);
        }
        .cv-customer-kicker{
            color:#2563EB;
            font-size:10px;
            font-weight:950;
            letter-spacing:.11em;
            text-transform:uppercase;
            margin-bottom:9px;
        }
        .cv-customer-title{
            color:#0F172A;
            font-size:31px;
            line-height:1.08;
            font-weight:950;
            letter-spacing:-.04em;
            margin:0 0 8px;
        }
        .cv-customer-copy{
            color:#52647A;
            font-size:14px;
            line-height:1.55;
            font-weight:680;
            margin:0;
            max-width:900px;
        }
        .cv-profile-card{
            border:1px solid #E2E8F0;
            border-radius:20px;
            background:#FFFFFF;
            padding:20px;
            box-shadow:0 14px 36px rgba(15,23,42,.05);
        }
        .cv-profile-top{
            display:flex;
            align-items:center;
            gap:15px;
            margin-bottom:16px;
        }
        .cv-profile-avatar{
            width:72px;
            height:72px;
            flex:0 0 72px;
            border-radius:20px;
            display:flex;
            align-items:center;
            justify-content:center;
            overflow:hidden;
            border:1px solid #BFDBFE;
            background:#EFF6FF;
            color:#1D4ED8;
            font-size:22px;
            font-weight:950;
        }
        .cv-profile-avatar img{
            width:100%;
            height:100%;
            object-fit:cover;
        }
        .cv-profile-name{
            color:#0F172A;
            font-size:18px;
            font-weight:950;
            margin-bottom:4px;
        }
        .cv-profile-role{
            color:#64748B;
            font-size:12px;
            font-weight:720;
        }
        .cv-profile-facts{
            display:grid;
            grid-template-columns:1fr;
            gap:9px;
        }
        .cv-profile-fact{
            border:1px solid #E2E8F0;
            border-radius:13px;
            padding:11px 12px;
            background:#F8FAFC;
        }
        .cv-profile-fact span{
            display:block;
            color:#64748B;
            font-size:9px;
            font-weight:950;
            letter-spacing:.09em;
            text-transform:uppercase;
            margin-bottom:5px;
        }
        .cv-profile-fact strong{
            display:block;
            color:#0F172A;
            font-size:12px;
            font-weight:900;
            overflow-wrap:anywhere;
        }
        .cv-settings-note{
            border:1px solid #DBEAFE;
            border-radius:15px;
            padding:13px 15px;
            background:#EFF6FF;
            color:#1E3A8A;
            font-size:11px;
            line-height:1.5;
            font-weight:700;
        }
        .cv-security-row{
            border:1px solid #E2E8F0;
            border-radius:15px;
            padding:14px;
            background:#FFFFFF;
            margin-bottom:10px;
        }
        .cv-security-row strong{
            display:block;
            color:#0F172A;
            font-size:13px;
            margin-bottom:4px;
        }
        .cv-security-row span{
            display:block;
            color:#64748B;
            font-size:11px;
            line-height:1.45;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <section class="cv-customer-hero">
          <div class="cv-customer-kicker">Customer account</div>
          <h1 class="cv-customer-title">Profile & preferences</h1>
          <p class="cv-customer-copy">
            Manage the personal identity, display defaults, and notification
            preferences Cadivor uses across engineering workspaces and reports.
          </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    settings_setup_done = completion_count(onboarding_progress or {})
    settings_setup_percent = int((settings_setup_done / 5) * 100)
    st.markdown(
        f"""
        <style id="cadivor-settings-setup-v11a3">
        .cv-settings-setup{{
            display:grid;grid-template-columns:1fr auto;gap:16px;align-items:center;
            border:1px solid #DBEAFE;border-radius:17px;background:#FFFFFF;
            padding:15px 17px;margin:0 0 14px;
            box-shadow:0 12px 28px rgba(15,23,42,.05);
        }}
        .cv-settings-setup strong{{
            display:block;color:#0F172A!important;font-size:13px;font-weight:950;
            margin-bottom:4px;
        }}
        .cv-settings-setup span{{
            color:#64748B!important;font-size:10px;font-weight:750;
        }}
        .cv-settings-setup b{{
            color:#2563EB!important;font-size:12px;font-weight:950;
        }}
        .cv-settings-setup-bar{{
            grid-column:1/-1;height:7px;border-radius:999px;background:#E2E8F0;
            overflow:hidden;
        }}
        .cv-settings-setup-bar i{{
            display:block;height:100%;width:{settings_setup_percent}%;
            background:#2563EB;border-radius:999px;
        }}
        </style>
        <section class="cv-settings-setup">
          <div>
            <strong>Customer setup</strong>
            <span>Profile, workspace, BOM, replacement, and reporting readiness</span>
          </div>
          <b>{settings_setup_done}/5 complete</b>
          <div class="cv-settings-setup-bar"><i></i></div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    internal_nav_button(
        "Continue Customer Setup",
        "Onboarding",
        key="settings_open_onboarding",
        type="primary",
    )

    migration_required = (
        profile_error == "migration_required"
        or preferences_error == "migration_required"
    )
    if migration_required:
        st.error(
            "Milestone 11A.1 database tables are not available yet. "
            "Run the included Supabase migration, then refresh this page."
        )

    profile_tab, preferences_tab, workspace_tab, security_tab, billing_tab = st.tabs(
        ["Profile", "Preferences", "Workspace", "Security", "Billing"]
    )

    with profile_tab:
        summary_col, form_col = st.columns([0.36, 0.64], gap="large")

        with summary_col:
            avatar_url_value = _safe_text(
                customer_profile.get("avatar_url"),
                profile.get("avatar_url", ""),
            )
            initials_value = profile.get("initials", "C")
            avatar_markup = (
                f'<img src="{html.escape(avatar_url_value, quote=True)}" alt="Profile photo">'
                if avatar_url_value
                else html.escape(initials_value)
            )
            display_name = _safe_text(
                customer_profile.get("full_name"),
                profile.get("full_name", "Cadivor user"),
            )
            display_job = _safe_text(
                customer_profile.get("job_title"),
                profile.get("role_title", "Cadivor workspace member"),
            )
            display_company = _safe_text(
                customer_profile.get("company_name"),
                profile.get("company", "Not set"),
            )

            st.markdown(
                f"""
                <div class="cv-profile-card">
                  <div class="cv-profile-top">
                    <div class="cv-profile-avatar">{avatar_markup}</div>
                    <div>
                      <div class="cv-profile-name">{html.escape(display_name)}</div>
                      <div class="cv-profile-role">{html.escape(display_job)}</div>
                    </div>
                  </div>
                  <div class="cv-profile-facts">
                    <div class="cv-profile-fact">
                      <span>Email</span>
                      <strong>{html.escape(auth_email)}</strong>
                    </div>
                    <div class="cv-profile-fact">
                      <span>Company</span>
                      <strong>{html.escape(display_company)}</strong>
                    </div>
                    <div class="cv-profile-fact">
                      <span>Plan</span>
                      <strong>{html.escape(profile.get("plan", "Starter"))}</strong>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with form_col:
            st.subheader("Profile information")
            st.caption(
                "This information personalizes your account, team presence, "
                "workspace records, and future report attribution."
            )

            full_name_value = st.text_input(
                "Full name",
                value=_safe_text(
                    customer_profile.get("full_name"),
                    profile.get("full_name", ""),
                ),
                placeholder="Joshua Kashambala",
                key="customer_profile_full_name",
            )
            company_value = st.text_input(
                "Company / organization",
                value=_safe_text(
                    customer_profile.get("company_name"),
                    profile.get("company", ""),
                ),
                placeholder="Egres Technologies",
                key="customer_profile_company",
            )
            job_title_value = st.text_input(
                "Job title",
                value=_safe_text(
                    customer_profile.get("job_title"),
                    profile.get("role_title", ""),
                ),
                placeholder="Founder, Engineering Lead, Sourcing Manager",
                key="customer_profile_job_title",
            )

            phone_col, country_col = st.columns(2)
            with phone_col:
                phone_value = st.text_input(
                    "Phone",
                    value=_safe_text(
                        customer_profile.get("phone"),
                        profile.get("phone", ""),
                    ),
                    placeholder="+1 555 000 0000",
                    key="customer_profile_phone",
                )
            with country_col:
                country_value = st.text_input(
                    "Country",
                    value=_safe_text(
                        customer_profile.get("country"),
                        profile.get("country", ""),
                    ),
                    placeholder="United States",
                    key="customer_profile_country",
                )

            timezone_value = st.text_input(
                "Time zone",
                value=_safe_text(
                    customer_profile.get("timezone"),
                    profile.get("timezone", ""),
                ),
                placeholder="America/New_York",
                key="customer_profile_timezone",
            )
            avatar_value = st.text_input(
                "Profile image URL",
                value=_safe_text(
                    customer_profile.get("avatar_url"),
                    profile.get("avatar_url", ""),
                ),
                placeholder="https://example.com/profile.jpg",
                key="customer_profile_avatar",
            )
            bio_value = st.text_area(
                "Professional bio",
                value=_safe_text(customer_profile.get("bio"), ""),
                placeholder=(
                    "Optional short description shown in future collaboration "
                    "and approval workflows."
                ),
                height=110,
                key="customer_profile_bio",
            )

            if st.button(
                "Save Profile",
                type="primary",
                use_container_width=True,
                disabled=migration_required,
                key="save_customer_profile",
            ):
                saved_profile, save_error = update_customer_profile(
                    supabase,
                    user_id,
                    {
                        "full_name": full_name_value.strip(),
                        "company_name": company_value.strip(),
                        "job_title": job_title_value.strip(),
                        "phone": phone_value.strip(),
                        "country": country_value.strip(),
                        "timezone": timezone_value.strip(),
                        "avatar_url": avatar_value.strip(),
                        "bio": bio_value.strip(),
                    },
                )
                if save_error:
                    st.error(f"Unable to save profile: {save_error}")
                else:
                    st.success("Customer profile saved.")
                    st.rerun()

    with preferences_tab:
        st.subheader("Application preferences")
        st.caption(
            "Set the defaults Cadivor should use when presenting engineering "
            "information and sending product notifications."
        )

        appearance_options = ["System", "Light", "Dark"]
        saved_appearance = _safe_text(
            preferences.get("appearance"),
            "system",
        ).title()
        if saved_appearance not in appearance_options:
            saved_appearance = "System"

        density_options = ["Comfortable", "Compact"]
        saved_density = _safe_text(
            preferences.get("density"),
            "comfortable",
        ).title()
        if saved_density not in density_options:
            saved_density = "Comfortable"

        units_options = ["Metric", "Imperial"]
        saved_units = _safe_text(
            preferences.get("default_units"),
            "metric",
        ).title()
        if saved_units not in units_options:
            saved_units = "Metric"

        currency_options = ["USD", "EUR", "GBP", "CAD"]
        saved_currency = _safe_text(
            preferences.get("default_currency"),
            "USD",
        ).upper()
        if saved_currency not in currency_options:
            saved_currency = "USD"

        display_col, default_col = st.columns(2, gap="large")
        with display_col:
            appearance_value = st.selectbox(
                "Appearance",
                appearance_options,
                index=appearance_options.index(saved_appearance),
                key="customer_preference_appearance",
                help="Theme selection is stored now; full dark-theme support arrives in a later UI milestone.",
            )
            density_value = st.selectbox(
                "Interface density",
                density_options,
                index=density_options.index(saved_density),
                key="customer_preference_density",
            )

        with default_col:
            units_value = st.selectbox(
                "Default units",
                units_options,
                index=units_options.index(saved_units),
                key="customer_preference_units",
            )
            currency_value = st.selectbox(
                "Default currency",
                currency_options,
                index=currency_options.index(saved_currency),
                key="customer_preference_currency",
            )

        st.subheader("Notification preferences")
        email_notifications = st.toggle(
            "Account and product email",
            value=bool(preferences.get("email_notifications", True)),
            key="customer_pref_email",
        )
        workspace_notifications = st.toggle(
            "Workspace collaboration updates",
            value=bool(preferences.get("workspace_notifications", True)),
            key="customer_pref_workspace",
        )
        monitoring_notifications = st.toggle(
            "Monitoring and lifecycle alerts",
            value=bool(preferences.get("monitoring_notifications", True)),
            key="customer_pref_monitoring",
        )
        report_notifications = st.toggle(
            "Report generation updates",
            value=bool(preferences.get("report_notifications", True)),
            key="customer_pref_reports",
        )

        if st.button(
            "Save Preferences",
            type="primary",
            use_container_width=True,
            disabled=migration_required,
            key="save_customer_preferences",
        ):
            saved_preferences, save_error = update_user_preferences(
                supabase,
                user_id,
                {
                    "appearance": appearance_value.lower(),
                    "density": density_value.lower(),
                    "default_units": units_value.lower(),
                    "default_currency": currency_value,
                    "email_notifications": email_notifications,
                    "workspace_notifications": workspace_notifications,
                    "monitoring_notifications": monitoring_notifications,
                    "report_notifications": report_notifications,
                },
            )
            if save_error:
                st.error(f"Unable to save preferences: {save_error}")
            else:
                st.success("Preferences saved.")
                st.rerun()

        st.markdown(
            """
            <div class="cv-settings-note">
              Appearance and density preferences are now stored persistently.
              Their full application across every page will be introduced after
              the customer-settings foundation is stable.
            </div>
            """,
            unsafe_allow_html=True,
        )

    with workspace_tab:
        st.subheader("Workspace settings")
        st.caption(
            "Workspace identity, members, invitations, and engineering defaults "
            "are managed from the collaboration workspace."
        )
        internal_nav_button(
            "Open Workspace",
            "Workspace",
            key="settings_open_workspace",
            use_container_width=True,
        )

    with security_tab:
        st.subheader("Security")
        st.markdown(
            f"""
            <div class="cv-security-row">
              <strong>Authenticated email</strong>
              <span>{html.escape(auth_email)}</span>
            </div>
            <div class="cv-security-row">
              <strong>Password management</strong>
              <span>Password reset and change-password controls will be connected
              in Milestone 11C using Supabase Auth.</span>
            </div>
            <div class="cv-security-row">
              <strong>Two-factor authentication</strong>
              <span>Planned for the security and authentication phase.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with billing_tab:
        st.subheader("Plan & billing")
        st.caption(
            "Review Cadivor plans and upgrade the current account when the team "
            "requires higher BOM, monitoring, report, or member limits."
        )
        st.markdown(
            f"""
            <div class="cv-profile-card">
              <div class="cv-profile-fact">
                <span>Current plan</span>
                <strong>{html.escape(profile.get("plan", "Starter"))}</strong>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        internal_nav_button(
            "View Plans",
            "Pricing",
            key="settings_view_plans",
            use_container_width=True,
        )

    st.stop()


# ---------- Workspace ----------
if app_mode == "Workspace":
    profile = get_user_profile(current_user)
    auth_user = st.session_state.get("user")
    user_id = str(getattr(auth_user, "id", current_user.get("id", "")))
    owner_email = profile.get("email") or _safe_text(current_user.get("email"), "")
    owner_name = profile.get("full_name") or "Cadivor user"
    proposed_workspace_name = profile.get("workspace_name") or profile.get("company") or "Cadivor Workspace"

    default_workspace, workspace_error = ensure_personal_workspace(
        supabase,
        user_id,
        owner_email,
        owner_name,
        proposed_workspace_name,
        selected_plan_name,
    )

    available_workspaces, organizations_error = list_user_workspaces(supabase, user_id)
    preferred_workspace_id, preference_error = get_active_workspace_preference(
        supabase,
        user_id,
    )

    session_workspace_id = str(st.session_state.get("active_workspace_id") or "")
    requested_workspace_id = session_workspace_id or str(preferred_workspace_id or "")
    available_ids = {str(item.get("id")) for item in available_workspaces}

    if requested_workspace_id and requested_workspace_id in available_ids:
        workspace, active_workspace_error = get_workspace_by_id(
            supabase,
            user_id,
            requested_workspace_id,
        )
        workspace_error = active_workspace_error
    else:
        workspace = default_workspace
        if workspace and workspace.get("id"):
            st.session_state["active_workspace_id"] = str(workspace.get("id"))

    if not available_workspaces and workspace:
        available_workspaces = [workspace]

    st.markdown(
        """
        <style>
        .cv-ws-hero{border:1px solid #BFDBFE;border-radius:24px;padding:26px 28px;background:linear-gradient(135deg,#FFFFFF 0%,#EFF6FF 100%);box-shadow:0 18px 45px rgba(15,23,42,.06);margin-bottom:18px}
        .cv-ws-kicker{font-size:11px;font-weight:800;letter-spacing:.13em;text-transform:uppercase;color:#2563EB;margin-bottom:9px}
        .cv-ws-hero h1{font-size:34px;line-height:1.05;margin:0 0 9px;color:#0F172A}
        .cv-ws-hero p{max-width:780px;margin:0;color:#52647D;font-weight:600}
        .cv-ws-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin:0 0 20px}
        .cv-ws-metric,.cv-ws-card{box-sizing:border-box;border:1px solid #E2E8F0;border-radius:18px;background:#FFFFFF;box-shadow:0 12px 30px rgba(15,23,42,.045)}
        .cv-ws-metric{padding:16px 18px;min-height:112px}
        .cv-ws-label{font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#64748B}
        .cv-ws-value{font-size:27px;font-weight:850;color:#0F172A;margin:7px 0 2px}
        .cv-ws-note{font-size:12px;color:#64748B;font-weight:600}
        .cv-ws-card{padding:20px;margin-bottom:14px}
        .cv-ws-card h3{margin:0 0 6px;font-size:18px;color:#0F172A}
        .cv-ws-card p{margin:0;color:#64748B}
        .cv-ws-member{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(100px,.6fr) minmax(110px,.6fr);gap:12px;align-items:center;border:1px solid #E2E8F0;border-radius:15px;padding:13px 15px;margin:9px 0;background:#FBFDFF}
        .cv-ws-member strong{display:block;color:#0F172A}.cv-ws-member span{display:block;color:#64748B;font-size:12px;margin-top:2px}
        .cv-ws-role{display:inline-flex!important;width:max-content;padding:5px 10px;border-radius:999px;background:#EFF6FF;color:#1D4ED8!important;font-weight:800;text-transform:capitalize}
        .cv-ws-status{display:inline-flex!important;width:max-content;padding:5px 10px;border-radius:999px;background:#ECFDF5;color:#047857!important;font-weight:800;text-transform:capitalize}
        .cv-ws-activity{border-left:3px solid #BFDBFE;padding:2px 0 16px 16px;margin-left:6px}
        .cv-ws-activity strong{color:#0F172A}.cv-ws-activity span{display:block;color:#64748B;font-size:12px;margin-top:4px}
        .cv-ws-warning{border:1px solid #FDE68A;background:#FFFBEB;border-radius:18px;padding:18px;color:#92400E;margin:16px 0}
        .cv-org-card{border:1px solid #DBEAFE;border-radius:18px;background:#FFFFFF;padding:18px;box-shadow:0 12px 28px rgba(15,23,42,.045);margin-bottom:12px}
        .cv-org-card strong{display:block;color:#0F172A;font-size:15px}.cv-org-card span{display:block;color:#64748B;font-size:11px;margin-top:4px}
        .cv-org-active{display:inline-flex!important;width:max-content!important;margin-top:10px!important;padding:5px 9px;border-radius:999px;background:#ECFDF5;color:#047857!important;font-weight:850}
        .cv-collab-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:14px;margin-bottom:14px}
        .cv-presence-row{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #E2E8F0;border-radius:14px;padding:12px 13px;margin:8px 0;background:#FBFDFF}
        .cv-presence-person{display:flex;align-items:center;gap:10px;min-width:0}
        .cv-presence-dot{width:10px;height:10px;border-radius:999px;background:#22C55E;box-shadow:0 0 0 4px #DCFCE7}
        .cv-presence-dot.idle{background:#F59E0B;box-shadow:0 0 0 4px #FEF3C7}
        .cv-presence-dot.offline{background:#94A3B8;box-shadow:0 0 0 4px #F1F5F9}
        .cv-presence-row strong{display:block;color:#0F172A;font-size:12px}.cv-presence-row span{display:block;color:#64748B;font-size:10px;margin-top:2px}
        .cv-audit-row{display:grid;grid-template-columns:150px minmax(120px,.7fr) minmax(160px,1fr) minmax(0,1.7fr);gap:12px;align-items:center;border-bottom:1px solid #EEF2F7;padding:11px 4px}
        .cv-audit-row.header{background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;padding:10px 12px;color:#64748B;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.06em}
        .cv-audit-row strong{color:#0F172A;font-size:11px}.cv-audit-row span{color:#64748B;font-size:10px;overflow-wrap:anywhere}
        @media(max-width:900px){.cv-collab-grid{grid-template-columns:1fr}.cv-audit-row{grid-template-columns:1fr 1fr}}
        @media(max-width:900px){.cv-ws-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:620px){.cv-ws-metrics{grid-template-columns:1fr}.cv-ws-member{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    if workspace_error == "migration_required":
        st.markdown(
            f"""
            <div class="cv-ws-hero">
              <div class="cv-ws-kicker">Workspace & Team Collaboration</div>
              <h1>{html.escape(proposed_workspace_name)}</h1>
              <p>The collaboration interface is installed. Apply the included Milestone 10B Supabase migration to activate persistent members, invitations, activity, and notifications.</p>
            </div>
            <div class="cv-ws-warning"><strong>Database setup required.</strong><br>Run <code>supabase_migrations/20260712_milestone_10b_workspace_collaboration.sql</code> in the Supabase SQL Editor, then reload this page.</div>
            """,
            unsafe_allow_html=True,
        )
        st.info("Your existing BOM analyses and engineering decisions are not changed by this migration.")
        st.stop()
    if workspace_error or not workspace:
        st.error(f"Unable to load the workspace: {workspace_error or 'Unknown workspace error'}")
        st.stop()

    workspace_id = str(workspace.get("id"))
    current_role = str(workspace.get("current_role") or "viewer").lower()

    presence_error = touch_workspace_presence(
        supabase,
        workspace_id,
        user_id,
        owner_name,
        owner_email,
        "Workspace",
        workspace.get("name") or proposed_workspace_name,
    )
    can_administer = current_role in {"owner", "admin"}
    is_owner = current_role == "owner"

    members, members_error = list_members(supabase, workspace_id)
    invites, invites_error = list_invites(supabase, workspace_id)
    activity_rows, activity_error = list_activity(supabase, workspace_id, 75)
    presence_rows, presence_list_error = list_workspace_presence(
        supabase,
        workspace_id,
        25,
    )
    audit_rows, audit_error = list_audit_log(
        supabase,
        workspace_id,
        limit=250,
    )
    active_members = [row for row in members if row.get("status") == "active"]
    pending_invites = [row for row in invites if row.get("status") == "pending"]

    workspace_name = _safe_text(workspace.get("name"), proposed_workspace_name)
    st.markdown(
        f"""
        <div class="cv-ws-hero">
          <div class="cv-ws-kicker">Team Engineering Workspace</div>
          <h1>{html.escape(workspace_name)}</h1>
          <p>Manage workspace identity, engineering access, team invitations, collaboration activity, and notification readiness from one controlled workspace.</p>
        </div>
        <div class="cv-ws-metrics">
          <div class="cv-ws-metric"><div class="cv-ws-label">Plan</div><div class="cv-ws-value">{html.escape(selected_plan_name)}</div><div class="cv-ws-note">Current subscription</div></div>
          <div class="cv-ws-metric"><div class="cv-ws-label">Members</div><div class="cv-ws-value">{len(active_members)}</div><div class="cv-ws-note">Active workspace users</div></div>
          <div class="cv-ws-metric"><div class="cv-ws-label">Pending Invites</div><div class="cv-ws-value">{len(pending_invites)}</div><div class="cv-ws-note">Awaiting acceptance</div></div>
          <div class="cv-ws-metric"><div class="cv-ws-label">Saved Analyses</div><div class="cv-ws-value">{saved_bom_count}</div><div class="cv-ws-note">Shared engineering records</div></div>
          <div class="cv-ws-metric"><div class="cv-ws-label">Organizations</div><div class="cv-ws-value">{len(available_workspaces)}</div><div class="cv-ws-note">Accessible workspaces</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    (
        overview_tab,
        collaboration_tab,
        organizations_tab,
        members_tab,
        invitations_tab,
        activity_tab,
        audit_tab,
        settings_tab,
    ) = st.tabs(
        [
            "Overview",
            "Team Activity",
            "Organizations",
            "Members",
            "Invitations",
            "Workspace History",
            "Audit Log",
            "Settings",
        ]
    )

    with overview_tab:
        left, right = st.columns([1.25, .75], gap="large")
        with left:
            st.markdown(
                f"""
                <div class="cv-ws-card">
                  <h3>Workspace information</h3>
                  <p>Persistent identity and collaboration boundaries for your engineering records.</p>
                  <div class="cv-snapshot-grid" style="grid-template-columns:1fr 1fr;margin-top:15px">
                    <div class="cv-snapshot-item"><span>Workspace</span><strong>{html.escape(workspace_name)}</strong></div>
                    <div class="cv-snapshot-item"><span>Your role</span><strong>{html.escape(current_role.title())}</strong></div>
                    <div class="cv-snapshot-item"><span>Owner</span><strong>{html.escape(owner_name)}</strong></div>
                    <div class="cv-snapshot-item"><span>Created</span><strong>{html.escape(str(workspace.get('created_at',''))[:10] or 'Today')}</strong></div>
                    <div class="cv-snapshot-item"><span>Time zone</span><strong>{html.escape(_safe_text(workspace.get('timezone'),'UTC'))}</strong></div>
                    <div class="cv-snapshot-item"><span>Units</span><strong>{html.escape(_safe_text(workspace.get('unit_system'),'metric').title())}</strong></div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="cv-ws-card"><h3>Recent workspace activity</h3><p>Activity is collapsed by default so the overview remains compact. The complete audit timeline remains available in the Activity tab.</p></div>',
                unsafe_allow_html=True,
            )
            if activity_error:
                st.warning(f"Activity could not be loaded: {activity_error}")
            elif not activity_rows:
                st.info("No workspace activity has been recorded yet.")
            else:
                latest_activity = activity_rows[0]
                st.markdown(
                    f'<div class="cv-ws-activity"><strong>{html.escape(_safe_text(latest_activity.get("summary"), "Workspace activity"))}</strong><span>{html.escape(_safe_text(latest_activity.get("actor_name"), "Cadivor"))} · {html.escape(str(latest_activity.get("created_at", ""))[:19].replace("T", " "))} UTC</span></div>',
                    unsafe_allow_html=True,
                )
                with st.expander(f"View recent activity ({min(len(activity_rows), 6)} events)", expanded=False):
                    for item in activity_rows[:6]:
                        st.markdown(
                            f'<div class="cv-ws-activity"><strong>{html.escape(_safe_text(item.get("summary"), "Workspace activity"))}</strong><span>{html.escape(_safe_text(item.get("actor_name"), "Cadivor"))} · {html.escape(str(item.get("created_at", ""))[:19].replace("T", " "))} UTC</span></div>',
                            unsafe_allow_html=True,
                        )
                    st.caption("Open the Activity tab for the complete workspace audit timeline.")
        with right:
            st.markdown(
                f"""
                <div class="cv-ws-card">
                  <h3>Collaboration readiness</h3>
                  <p>Organization switching, member boundaries, invitations, and role controls are active.</p>
                  <div class="cv-snapshot-grid" style="grid-template-columns:1fr;margin-top:15px">
                    <div class="cv-snapshot-item"><span>Member directory</span><strong>Active</strong></div>
                    <div class="cv-snapshot-item"><span>Invitation records</span><strong>Active</strong></div>
                    <div class="cv-snapshot-item"><span>Role controls</span><strong>{'Owner enabled' if is_owner else 'Permission controlled'}</strong></div>
                    <div class="cv-snapshot-item"><span>Email delivery</span><strong>Not connected yet</strong></div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption("Organization membership is persistent. Saved BOM scoping and invitation acceptance links arrive in Milestone 11B.2.")

    with collaboration_tab:
        st.subheader("Team collaboration")
        st.caption(
            "See who is active, what the engineering team changed, and the "
            "latest organization events without leaving the workspace."
        )

        if presence_error == "migration_required" or presence_list_error == "migration_required":
            st.info(
                "Run the Milestone 11C.1 migration to activate team presence "
                "and the searchable audit log."
            )
        elif presence_list_error:
            st.error(f"Team presence could not be loaded: {presence_list_error}")

        now_utc = pd.Timestamp.utcnow()
        online_members = []
        idle_members = []
        offline_members = []
        for row in presence_rows:
            seen = pd.to_datetime(row.get("last_seen_at"), utc=True, errors="coerce")
            age_minutes = (
                (now_utc - seen).total_seconds() / 60
                if not pd.isna(seen)
                else 999999
            )
            if age_minutes <= 10:
                online_members.append(row)
            elif age_minutes <= 60:
                idle_members.append(row)
            else:
                offline_members.append(row)

        collaboration_left, collaboration_right = st.columns([1.15, 0.85], gap="medium")
        with collaboration_left:
            st.markdown("#### Live team presence")
            presence_display = online_members + idle_members + offline_members
            if not presence_display:
                st.markdown(
                    '<div class="cv-analysis-empty">No team presence has been recorded yet.</div>',
                    unsafe_allow_html=True,
                )
            else:
                presence_html = []
                online_ids = {str(row.get("id")) for row in online_members}
                idle_ids = {str(row.get("id")) for row in idle_members}
                for row in presence_display[:12]:
                    row_id = str(row.get("id"))
                    state_class = "" if row_id in online_ids else "idle" if row_id in idle_ids else "offline"
                    state_label = "Online" if row_id in online_ids else "Idle" if row_id in idle_ids else "Offline"
                    presence_html.append(
                        f'<div class="cv-presence-row">'
                        f'<div class="cv-presence-person">'
                        f'<i class="cv-presence-dot {state_class}"></i>'
                        f'<div><strong>{html.escape(_safe_text(row.get("display_name"), row.get("email") or "Member"))}</strong>'
                        f'<span>{html.escape(_safe_text(row.get("page_name"), "Cadivor"))}'
                        f'{" · " + html.escape(_safe_text(row.get("object_label"), "")) if row.get("object_label") else ""}</span></div>'
                        f'</div><span>{state_label}</span></div>'
                    )
                st.markdown("".join(presence_html), unsafe_allow_html=True)

        with collaboration_right:
            st.markdown("#### Collaboration snapshot")
            c1, c2 = st.columns(2)
            c1.metric("Online now", len(online_members))
            c2.metric("Active this hour", len(online_members) + len(idle_members))
            c3, c4 = st.columns(2)
            c3.metric("Activity events", len(activity_rows))
            c4.metric("Audit records", len(audit_rows))

            st.markdown("#### Latest team events")
            if not activity_rows:
                st.caption("No collaboration activity has been recorded.")
            else:
                for row in activity_rows[:5]:
                    st.markdown(
                        f"""
                        <div class="cv-ws-activity">
                          <strong>{html.escape(_safe_text(row.get('actor_name'), 'Cadivor'))}</strong>
                          <span>{html.escape(_safe_text(row.get('summary'), row.get('action_type') or 'Workspace event'))}</span>
                          <span>{html.escape(str(row.get('created_at',''))[:19].replace('T',' '))} UTC</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

    with organizations_tab:
        st.subheader("Organizations")
        st.caption(
            "Switch between engineering organizations without signing out. "
            "Each organization has its own members, invitations, activity, and settings."
        )

        if organizations_error:
            st.error(f"Organizations could not be loaded: {organizations_error}")
        else:
            organization_lookup = {
                f"{_safe_text(item.get('name'), 'Cadivor Workspace')} — {_safe_text(item.get('current_role'), 'viewer').title()}": item
                for item in available_workspaces
            }
            current_label = next(
                (
                    label
                    for label, item in organization_lookup.items()
                    if str(item.get("id")) == workspace_id
                ),
                next(iter(organization_lookup), ""),
            )

            if organization_lookup:
                selected_organization_label = st.selectbox(
                    "Active organization",
                    list(organization_lookup.keys()),
                    index=list(organization_lookup.keys()).index(current_label)
                    if current_label in organization_lookup
                    else 0,
                    key="workspace_organization_switcher",
                )
                selected_organization = organization_lookup[selected_organization_label]
                selected_organization_id = str(selected_organization.get("id"))

                switch_col, status_col = st.columns([0.35, 0.65])
                with switch_col:
                    switch_disabled = selected_organization_id == workspace_id
                    if st.button(
                        "Switch Organization",
                        type="primary",
                        disabled=switch_disabled,
                        use_container_width=True,
                        key="switch_active_organization",
                    ):
                        preference_save_error = set_active_workspace_preference(
                            supabase,
                            user_id,
                            selected_organization_id,
                        )
                        if preference_save_error:
                            st.error(preference_save_error)
                        else:
                            st.session_state["active_workspace_id"] = selected_organization_id
                            st.success("Active organization changed.")
                            st.rerun()
                with status_col:
                    if selected_organization_id == workspace_id:
                        st.success(f"{workspace_name} is currently active.")
                    else:
                        st.info(
                            "Switching changes the member directory, invitations, "
                            "activity, and organization settings shown on this page."
                        )

            st.markdown("#### Organization directory")
            org_columns = st.columns(2)
            for index, item in enumerate(available_workspaces):
                with org_columns[index % 2]:
                    is_active_org = str(item.get("id")) == workspace_id
                    st.markdown(
                        f"""
                        <div class="cv-org-card">
                          <strong>{html.escape(_safe_text(item.get('name'), 'Cadivor Workspace'))}</strong>
                          <span>{html.escape(_safe_text(item.get('current_role'), 'viewer').title())} access · {html.escape(_safe_text(item.get('plan'), 'starter').title())} plan</span>
                          {'<span class="cv-org-active">Active organization</span>' if is_active_org else ''}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        st.markdown("#### Create another organization")
        st.caption(
            "Use a separate organization for another company, business unit, "
            "client environment, or engineering team."
        )
        new_org_name = st.text_input(
            "Organization name",
            placeholder="Example: Egres Engineering",
            key="new_organization_name",
        )
        if st.button(
            "Create Organization",
            type="primary",
            key="create_organization_workspace",
        ):
            created_org, create_org_error = create_organization_workspace(
                supabase,
                user_id,
                owner_email,
                owner_name,
                new_org_name,
                selected_plan_name,
            )
            if create_org_error:
                st.error(create_org_error)
            elif created_org:
                created_id = str(created_org.get("id"))
                set_active_workspace_preference(supabase, user_id, created_id)
                st.session_state["active_workspace_id"] = created_id
                st.success(f"{_safe_text(created_org.get('name'), 'Organization')} was created.")
                st.rerun()

        st.info(
            "Milestone 11B.1 establishes organization switching and membership boundaries. "
            "Saved BOM records will be assigned to organizations in Milestone 11B.2."
        )

    with members_tab:
        st.subheader("Workspace members")
        st.caption("Owners and admins manage access. Only the owner can change member roles in this foundation release.")
        if members_error:
            st.error(f"Members could not be loaded: {members_error}")
        elif not active_members:
            st.info("No active workspace members were found.")
        else:
            for member in active_members:
                member_name = _safe_text(member.get("display_name"), _safe_text(member.get("email"), "Workspace member"))
                member_email = _safe_text(member.get("email"), "")
                member_role = _safe_text(member.get("role"), "viewer").lower()
                st.markdown(
                    f'<div class="cv-ws-member"><div><strong>{html.escape(member_name)}</strong><span>{html.escape(member_email)}</span></div><div><span class="cv-ws-role">{html.escape(member_role)}</span></div><div><span class="cv-ws-status">{html.escape(_safe_text(member.get("status"),"active"))}</span></div></div>',
                    unsafe_allow_html=True,
                )
                if is_owner and member_role != "owner":
                    c1, c2, c3 = st.columns([1.1, .7, 2.2])
                    role_options = ["admin", "engineer", "viewer"]
                    with c1:
                        selected_role = st.selectbox(
                            "Role",
                            role_options,
                            index=role_options.index(member_role) if member_role in role_options else 2,
                            key=f"member_role_{member.get('id')}",
                            label_visibility="collapsed",
                        )
                    with c2:
                        if st.button("Update role", key=f"update_member_{member.get('id')}", use_container_width=True):
                            error = update_member_role(supabase, workspace_id, str(member.get("id")), selected_role, user_id, owner_name, member_email)
                            if error:
                                st.error(error)
                            else:
                                st.success(f"{member_email} is now {selected_role}.")
                                st.rerun()
                    with c3:
                        if st.button("Remove member", key=f"remove_member_{member.get('id')}"):
                            st.session_state["workspace_remove_member"] = str(member.get("id"))
                    if st.session_state.get("workspace_remove_member") == str(member.get("id")):
                        st.warning(f"Remove {member_email} from this workspace? Their account will not be deleted.")
                        yes_col, no_col = st.columns(2)
                        with yes_col:
                            if st.button("Yes, remove member", key=f"confirm_remove_{member.get('id')}", type="primary"):
                                error = remove_member(supabase, workspace_id, str(member.get("id")), user_id, owner_name, member_email)
                                st.session_state.pop("workspace_remove_member", None)
                                if error:
                                    st.error(error)
                                else:
                                    st.success("Member removed.")
                                    st.rerun()
                        with no_col:
                            if st.button("Cancel", key=f"cancel_remove_{member.get('id')}"):
                                st.session_state.pop("workspace_remove_member", None)
                                st.rerun()

    with invitations_tab:
        st.subheader("Invite team members")
        st.caption("Create persistent invitations for admins, engineers, or viewers. Email delivery is not connected in this release.")
        if can_administer:
            invite_email = st.text_input("Email address", placeholder="engineer@company.com", key="workspace_invite_email")
            invite_role = st.selectbox("Workspace role", ["Engineer", "Viewer", "Admin"], key="workspace_invite_role")
            if st.button("Create Invitation", type="primary", key="create_workspace_invite"):
                created, error = create_invite(supabase, workspace_id, invite_email, invite_role.lower(), user_id, owner_name)
                if error:
                    st.error(error)
                else:
                    st.success("Workspace invitation created. Email delivery will be connected in a later capability.")
                    st.rerun()
        else:
            st.info("Only workspace owners and admins can create invitations.")

        st.markdown("#### Pending invitations")
        if invites_error:
            st.error(f"Invitations could not be loaded: {invites_error}")
        elif not pending_invites:
            st.info("No invitations are waiting for acceptance.")
        else:
            invite_df = pd.DataFrame(
                [
                    {
                        "Email": row.get("email"),
                        "Role": _safe_text(row.get("role"), "engineer").title(),
                        "Status": _safe_text(row.get("status"), "pending").title(),
                        "Invited By": _safe_text(row.get("invited_by_name"), owner_name),
                        "Created": str(row.get("created_at", ""))[:10],
                        "Expires": str(row.get("expires_at", ""))[:10],
                    }
                    for row in pending_invites
                ]
            )
            st.dataframe(invite_df, use_container_width=True, hide_index=True)
            if can_administer:
                invite_lookup = {f"{row.get('email')} — {str(row.get('created_at',''))[:10]}": row for row in pending_invites}
                selected_invite_label = st.selectbox("Select an invitation to cancel", list(invite_lookup.keys()))
                if st.button(
                    "Cancel Selected Invitation",
                    type="primary",
                    use_container_width=False,
                    key="cancel_selected_workspace_invitation",
                ):
                    selected_invite = invite_lookup[selected_invite_label]
                    error = cancel_invite(supabase, workspace_id, str(selected_invite.get("id")), user_id, owner_name, _safe_text(selected_invite.get("email"), ""))
                    if error:
                        st.error(error)
                    else:
                        st.success("Invitation cancelled.")
                        st.rerun()

    with activity_tab:
        st.subheader("Workspace history")
        st.caption(
            "Review human-readable team and workspace administration events. "
            "Technical database action names are intentionally hidden from this view."
        )
        if activity_error:
            st.error(f"Workspace history could not be loaded: {activity_error}")
        elif not activity_rows:
            st.info("No workspace history has been recorded yet.")
        else:
            history_categories = sorted(
                {category_label(event_category(row.get("action"), row.get("object_type"))) for row in activity_rows}
            )
            hist_a, hist_b, hist_c = st.columns([0.28, 0.52, 0.20])
            with hist_a:
                selected_history_category = st.selectbox(
                    "Event category",
                    ["All categories"] + history_categories,
                    key="workspace_history_category",
                )
            with hist_b:
                history_search = st.text_input(
                    "Search workspace history",
                    placeholder="Search person, action, or summary",
                    key="workspace_history_search",
                ).strip().lower()
            with hist_c:
                history_limit = st.selectbox(
                    "Rows",
                    [25, 50, 75],
                    index=1,
                    key="workspace_history_limit",
                )

            filtered_history = []
            for row in activity_rows:
                category = category_label(event_category(row.get("action"), row.get("object_type")))
                title = action_label(row.get("action"))
                summary = friendly_summary(row)
                actor = _safe_text(row.get("actor_name"), "Cadivor user")
                if selected_history_category != "All categories" and category != selected_history_category:
                    continue
                if history_search and history_search not in " ".join([category, title, summary, actor]).lower():
                    continue
                filtered_history.append(
                    {
                        "Date": display_time(row.get("created_at")),
                        "Actor": actor,
                        "Category": category,
                        "Action": title,
                        "Summary": summary,
                    }
                )

            st.caption(f"Showing {min(len(filtered_history), history_limit)} of {len(filtered_history)} matching events.")
            if not filtered_history:
                st.info("No workspace events match the current filters.")
            else:
                st.dataframe(
                    pd.DataFrame(filtered_history[:history_limit]),
                    use_container_width=True,
                    hide_index=True,
                    height=min(520, 75 + 36 * min(len(filtered_history), history_limit)),
                )

    with audit_tab:
        st.subheader("Engineering audit log")
        st.caption(
            "Search customer-friendly engineering events. Raw backend actions remain "
            "available only inside the technical-details expander and CSV export."
        )

        if audit_error == "migration_required":
            st.info("Run the Milestone 11C.1 migration to activate the audit log.")
        elif audit_error:
            st.error(f"Audit log could not be loaded: {audit_error}")
        else:
            categories = sorted(
                {category_label(event_category(row.get("action_type"), row.get("object_type"))) for row in audit_rows}
            )
            actor_names = sorted(
                {
                    _safe_text(row.get("actor_name"), row.get("actor_email") or "System")
                    for row in audit_rows
                }
            )
            filter_a, filter_b, filter_c, filter_d = st.columns([0.22, 0.22, 0.36, 0.20])
            with filter_a:
                selected_category = st.selectbox(
                    "Category",
                    ["All categories"] + categories,
                    key="audit_category_filter",
                )
            with filter_b:
                selected_actor_label = st.selectbox(
                    "Actor",
                    ["All people"] + actor_names,
                    key="audit_actor_filter_friendly",
                )
            with filter_c:
                audit_search = st.text_input(
                    "Search audit records",
                    placeholder="BOM, component, report, teammate, or action",
                    key="audit_search_filter_friendly",
                ).strip().lower()
            with filter_d:
                audit_limit = st.selectbox(
                    "Rows",
                    [25, 50, 100],
                    index=1,
                    key="audit_display_limit",
                )

            friendly_audit = []
            for row in audit_rows:
                category = category_label(event_category(row.get("action_type"), row.get("object_type")))
                actor = _safe_text(row.get("actor_name"), row.get("actor_email") or "System")
                action_title = action_label(row.get("action_type"))
                summary = friendly_summary(row)
                searchable = " ".join(
                    [category, actor, action_title, summary, _safe_text(row.get("object_label"), "")]
                ).lower()
                if selected_category != "All categories" and category != selected_category:
                    continue
                if selected_actor_label != "All people" and actor != selected_actor_label:
                    continue
                if audit_search and audit_search not in searchable:
                    continue
                friendly_audit.append(
                    {
                        "Time": display_time(row.get("created_at")),
                        "Actor": actor,
                        "Category": category,
                        "Action": action_title,
                        "Details": summary,
                        "Raw Action": _safe_text(row.get("action_type"), ""),
                        "Object Type": _safe_text(row.get("object_type"), ""),
                        "Object ID": _safe_text(row.get("object_id"), ""),
                        "Object Label": _safe_text(row.get("object_label"), ""),
                        "Raw Summary": _safe_text(row.get("summary"), ""),
                    }
                )

            st.caption(f"Showing {min(len(friendly_audit), audit_limit)} of {len(friendly_audit)} matching audit records.")
            if not friendly_audit:
                st.info("No audit records match the current filters.")
            else:
                display_columns = ["Time", "Actor", "Category", "Action", "Details"]
                st.dataframe(
                    pd.DataFrame(friendly_audit[:audit_limit])[display_columns],
                    use_container_width=True,
                    hide_index=True,
                    height=min(560, 75 + 36 * min(len(friendly_audit), audit_limit)),
                )

                record_options = {
                    f"{row['Time']} — {row['Action']} — {row['Actor']}": row
                    for row in friendly_audit[:audit_limit]
                }
                with st.expander("View technical details", expanded=False):
                    selected_record_label = st.selectbox(
                        "Audit record",
                        list(record_options.keys()),
                        key="audit_technical_record",
                    )
                    selected_record = record_options[selected_record_label]
                    st.caption(
                        "These identifiers are intended for support, troubleshooting, and API integrations."
                    )
                    technical_cols = st.columns(2)
                    technical_cols[0].code(
                        f"Raw action: {selected_record['Raw Action']}\n"
                        f"Object type: {selected_record['Object Type']}"
                    )
                    technical_cols[1].code(
                        f"Object ID: {selected_record['Object ID']}\n"
                        f"Object label: {selected_record['Object Label']}"
                    )

                audit_export = pd.DataFrame(friendly_audit).to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Export Audit Log CSV",
                    data=audit_export,
                    file_name=f"{re.sub(r'[^A-Za-z0-9_-]+', '_', workspace_name)}_audit_log.csv",
                    mime="text/csv",
                    type="primary",
                )

    with settings_tab:
        st.subheader("Workspace settings")
        st.caption("Workspace owners and admins control the shared identity and engineering defaults.")
        if can_administer:
            settings_name = st.text_input("Workspace name", value=workspace_name, key="workspace_settings_name")
            settings_timezone = st.text_input("Time zone", value=_safe_text(workspace.get("timezone"), profile.get("timezone") or "UTC"), key="workspace_settings_timezone")
            settings_units = st.selectbox("Default unit system", ["metric", "imperial"], index=0 if _safe_text(workspace.get("unit_system"), "metric") == "metric" else 1, key="workspace_settings_units")
            if st.button("Save Workspace Settings", type="primary"):
                error = update_workspace(supabase, workspace_id, settings_name, settings_timezone, settings_units, user_id, owner_name)
                if error:
                    st.error(error)
                else:
                    st.success("Workspace settings saved.")
                    st.rerun()
        else:
            st.info("Only workspace owners and admins can update workspace settings.")
        st.markdown(
            f"""
            <div class="cv-ws-card">
              <h3>Workspace identifiers</h3>
              <p>Use these values when support or future API integrations need to identify this workspace.</p>
              <div class="cv-snapshot-grid" style="grid-template-columns:1fr;margin-top:15px">
                <div class="cv-snapshot-item"><span>Workspace ID</span><strong>{html.escape(workspace_id)}</strong></div>
                <div class="cv-snapshot-item"><span>Owner ID</span><strong>{html.escape(_safe_text(workspace.get('owner_id'), user_id))}</strong></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.stop()

# ---------- Notifications ----------
if app_mode == "Notifications":
    profile = get_user_profile(current_user)
    auth_user = st.session_state.get("user")
    user_id = str(getattr(auth_user, "id", current_user.get("id", "")))
    workspace = active_workspace
    workspace_error = None if workspace else "Workspace unavailable"
    st.markdown(
        """
        <div class="cv-dashboard-header">
          <div>
            <div class="cv-eyebrow">Notification Center</div>
            <h1 class="cv-title">Workspace updates</h1>
            <p class="cv-subtitle">Review collaboration events and workspace notifications alongside Cadivor monitoring alerts.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if workspace_error == "migration_required":
        st.info("Apply the Milestone 10B Supabase migration to activate workspace notifications.")
        st.stop()
    if workspace_error or not workspace:
        st.error(f"Unable to load notifications: {workspace_error or 'Workspace unavailable'}")
        st.stop()

    notification_rows, notification_error = list_notifications(supabase, str(workspace.get("id")), user_id, 75)
    unread_rows = [row for row in notification_rows if not row.get("is_read")]
    n1, n2, n3 = st.columns(3)
    n1.metric("Unread", len(unread_rows))
    n2.metric("Workspace Updates", len(notification_rows))
    n3.metric("Monitoring Alerts", int(active_alert_count if 'active_alert_count' in globals() else 0))

    if unread_rows:
        if st.button(
            "Mark All Workspace Notifications Read",
            type="primary",
            key="mark_all_workspace_notifications_read",
        ):
            mark_all_error = mark_all_notifications_read(
                supabase,
                str(workspace.get("id")),
                user_id,
            )
            if mark_all_error:
                st.error(mark_all_error)
            else:
                st.success("All workspace notifications were marked as read.")
                st.rerun()

    workspace_updates_tab, monitoring_tab = st.tabs(["Workspace Updates", "Monitoring Alerts"])
    with workspace_updates_tab:
        if notification_error:
            st.error(f"Notifications could not be loaded: {notification_error}")
        elif not notification_rows:
            empty_state("No workspace notifications", "Invitations, role changes, generated reports, and collaboration updates will appear here.", "Open Workspace", "?page=Workspace", "●")
        else:
            for row in notification_rows:
                state = "Unread" if not row.get("is_read") else "Read"
                st.markdown(
                    f"""
                    <div class="cv-panel" style="margin-bottom:10px">
                      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
                        <div><div class="cv-panel-title">{html.escape(_safe_text(row.get('title'),'Workspace update'))}</div><div class="cv-panel-copy">{html.escape(_safe_text(row.get('message'),''))}</div></div>
                        <span class="cv-status-pill {'success' if state == 'Read' else 'warning'}">{state}</span>
                      </div>
                      <div class="cv-panel-copy" style="margin-top:8px">{html.escape(str(row.get('created_at',''))[:19].replace('T',' '))} UTC</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if not row.get("is_read") and st.button("Mark as read", key=f"read_notification_{row.get('id')}"):
                    error = mark_notification_read(supabase, str(row.get("id")))
                    if error:
                        st.error(error)
                    else:
                        st.rerun()
    with monitoring_tab:
        st.info("Lifecycle, stock, and supplier events remain available in the Monitoring dashboard. Milestone 10B keeps them separate from team collaboration notifications to avoid duplicate records.")
        if st.button("Open Monitoring Dashboard", type="primary"):
            st.query_params["page"] = "Monitoring"
            st.rerun()
    st.stop()

# ---------- Help ----------
if app_mode == "Help":
    st.markdown(
        """
        <div class="cv-dashboard-header">
          <div>
            <div class="cv-eyebrow">Help Center</div>
            <h1 class="cv-title">Cadivor support</h1>
            <p class="cv-subtitle">Guides, templates, and answers for engineering teams using Cadivor BOM intelligence.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    h1, h2, h3 = st.columns(3)
    with h1:
        action_card("BOM upload guide", "CSV and Excel formatting recommendations.", "?page=BOM%20Analyzer", "▦")
    with h2:
        action_card("Alternative search", "How to review replacement candidates.", "?page=Alternative%20Finder", "⇄")
    with h3:
        action_card("Contact support", "Support workflow coming soon.", "?page=About", "?")
    st.markdown('<div class="cv-section-spacer"></div>', unsafe_allow_html=True)
    empty_state("Documentation is being prepared", "Cadivor documentation, API notes, and engineering guides will be added as the product matures.", None, None, "◇")
    st.stop()

# ---------- About ----------
if app_mode == "About":
    st.subheader("About Cadivor")
    st.caption("Engineering intelligence for electronics teams.")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown(
            """
            <div class="card">
                <div class="card-title">What We Do</div>
                <div class="card-text">
                    Cadivor helps engineering and supply chain teams identify obsolete,
                    unavailable, single-source, and high-risk components before they create production delays.
                    <br><br>
                    The platform combines supplier data, lifecycle signals, sourcing risk, and alternative
                    component recommendations into one workflow.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            """
            <div class="card">
                <div class="card-title">Core Capabilities</div>
                <div class="card-text">
                    ✓ BOM risk analysis<br>
                    ✓ Multi-supplier availability checks<br>
                    ✓ Alternative component ranking<br>
                    ✓ Executive-ready reports<br>
                    ✓ Subscription-based usage controls
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            """
            <div class="card">
                <div class="card-title">Built For</div>
                <div class="card-text">
                    • Electrical engineers<br>
                    • Manufacturing engineers<br>
                    • Supply chain teams<br>
                    • Hardware startups<br>
                    • Engineering managers
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.stop()

if app_mode == "Admin":
    st.subheader("Admin Dashboard")
    st.caption("Platform usage, customer activity, and subscription oversight.")

    users_response = (
        supabase.table("users")
        .select("*")
        .execute()
    )

    users_data = users_response.data
    total_users = len(users_data)

    active_subscriptions = len(
        [user for user in users_data if user.get("plan") != "Starter"]
    )

    analyses_response = (
        supabase.table("analyses")
        .select("*")
        .execute()
    )

    analyses_data = analyses_response.data
    total_boms_analyzed = len(analyses_data)

    starter_count = len(
        [user for user in users_data if user.get("plan") == "Starter"]
    )
    pro_count = len(
        [user for user in users_data if user.get("plan") == "Pro"]
    )
    business_count = len(
        [user for user in users_data if user.get("plan") == "Business"]
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Total Users</div>
                <div class="kpi-value">{total_users}</div>
                <div class="kpi-note">+12 this month</div>
            </div>
            """,
            unsafe_allow_html=True,
    )

    with col2:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Active Subscriptions</div>
                <div class="kpi-value">{active_subscriptions}</div>
                <div class="kpi-note">82% retention</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">BOMs Analyzed</div>
                <div class="kpi-value">{total_boms_analyzed}</div>
                <div class="kpi-note">↑ 18% growth</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        st.markdown(
            """
            <div class="kpi-card">
                <div class="kpi-label">Revenue</div>
                <div class="kpi-value">$4,920</div>
                <div class="kpi-note">Monthly recurring revenue</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    st.subheader("Plan Distribution")

    plan_df = pd.DataFrame(
        {
            "Plan": ["Starter", "Pro", "Business"],
            "Users": [starter_count, pro_count, business_count],
        }
    )

    st.bar_chart(plan_df, x="Plan", y="Users")

    st.subheader("Recent User Activity")

    activity_df = pd.DataFrame(users_data)

    if not activity_df.empty:
        activity_df = activity_df.rename(
            columns={
                "email": "User",
                "plan": "Plan",
                "monthly_upload_count": "BOMs Used",
                "created_at": "Created At",
            }
        )

        display_cols = [
            "User",
            "Plan",
            "BOMs Used",
            "Created At",
        ]

        activity_display_df = activity_df[display_cols].rename(
            columns={
                "project_name": "Project Name",
                "health_score": "Health Score",
                "high_risk_count": "High Risk Parts",
                "medium_risk_count": "Medium Risk Parts",
                "low_risk_count": "Low Risk Parts",
                "created_at": "Created At",
            }
        )

        st.dataframe(
            activity_display_df,
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.info("No users found.")

    st.dataframe(activity_df, use_container_width=True, hide_index=True)

    st.stop()

if app_mode == "Alternative Finder":
    return_analysis_id = _qp_value("return_analysis_id")
    if return_analysis_id:
        if st.button(
            "← Back to Saved BOM",
            key="alternative_back_to_saved_bom",
            type="secondary",
        ):
            navigate_to("Analysis Details", analysis_id=return_analysis_id)

    st.markdown(
        """
        <style id="cadivor-alternative-finder-62a1">
        /* Milestone 6.2C.3 — safe Supabase snapshot serialization */
        .st-key-af62_hero,
        .st-key-af62_search,
        .st-key-af62_summary,
        .st-key-af62_tips {
            background:#FFFFFF!important;
            border:1px solid #E2E8F0!important;
            border-radius:22px!important;
            box-shadow:0 18px 46px rgba(15,23,42,.055)!important;
        }

        .st-key-af62_hero {
            padding:28px 30px!important;
            margin-bottom:18px!important;
            background:
                radial-gradient(circle at 92% 10%,rgba(37,99,235,.10),transparent 30%),
                linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 65%,#EEF5FF 100%)!important;
            border-color:#BFDBFE!important;
        }

        .st-key-af62_search,
        .st-key-af62_summary,
        .st-key-af62_tips {
            padding:22px!important;
        }

        .st-key-af62_search {
            margin-bottom:18px!important;
        }

        .af62-eyebrow {
            display:inline-flex;
            align-items:center;
            gap:8px;
            padding:7px 11px;
            border-radius:999px;
            background:#EFF6FF;
            border:1px solid #BFDBFE;
            color:#2563EB!important;
            font-size:10px;
            font-weight:950;
            letter-spacing:.11em;
            text-transform:uppercase;
            margin-bottom:16px;
        }

        .af62-title {
            color:#0B1220!important;
            font-size:36px;
            line-height:1.05;
            font-weight:980;
            letter-spacing:-.045em;
            margin:0 0 10px;
        }

        .af62-copy {
            color:#52647A!important;
            font-size:15px;
            line-height:1.65;
            font-weight:680;
            max-width:850px;
            margin:0;
        }

        .af62-card-head {
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:14px;
            margin-bottom:16px;
        }

        .af62-card-title {
            color:#0B1220!important;
            font-size:19px;
            line-height:1.15;
            font-weight:960;
            letter-spacing:-.035em;
            margin:0;
        }

        .af62-card-subtitle {
            color:#64748B!important;
            font-size:12px;
            line-height:1.45;
            font-weight:720;
            margin-top:5px;
        }

        .af62-icon {
            width:42px;
            height:42px;
            border-radius:14px;
            display:flex;
            align-items:center;
            justify-content:center;
            flex:0 0 auto;
            background:#EFF6FF;
            border:1px solid #BFDBFE;
            color:#2563EB!important;
        }

        .af62-icon.green {
            background:#ECFDF5;
            border-color:#A7F3D0;
            color:#059669!important;
        }

        .af62-icon.amber {
            background:#FFFBEB;
            border-color:#FDE68A;
            color:#D97706!important;
        }

        .af62-search-label {
            color:#334155!important;
            font-size:12px;
            font-weight:850;
            margin-bottom:7px;
        }

        .st-key-af62_search [data-testid="stTextInput"] input {
            min-height:50px!important;
            border-radius:13px!important;
            border:1px solid #CBD5E1!important;
            background:#FFFFFF!important;
            color:#0F172A!important;
            font-size:14px!important;
            font-weight:720!important;
            padding-left:15px!important;
        }

        .st-key-af62_search [data-testid="stTextInput"] input:focus {
            border-color:#60A5FA!important;
            box-shadow:0 0 0 4px rgba(37,99,235,.12)!important;
        }

        .st-key-af62_search div.stButton > button {
            width:100%!important;
            min-height:50px!important;
            border-radius:13px!important;
            font-size:13px!important;
            font-weight:900!important;
        }

        .af62-summary-grid {
            display:grid;
            grid-template-columns:repeat(2,minmax(0,1fr));
            gap:10px;
            margin-top:4px;
        }

        .af62-field {
            padding:12px;
            border-radius:14px;
            background:#F8FAFC;
            border:1px solid #E2E8F0;
            min-height:72px;
        }

        .af62-field span {
            display:block;
            color:#64748B!important;
            font-size:9px;
            font-weight:950;
            text-transform:uppercase;
            letter-spacing:.09em;
            margin-bottom:7px;
        }

        .af62-field strong {
            display:block;
            color:#0B1220!important;
            font-size:13px;
            font-weight:900;
            line-height:1.35;
            overflow-wrap:anywhere;
        }

        .af62-search-status {
            display:inline-flex;
            align-items:center;
            gap:7px;
            margin-top:14px;
            padding:7px 10px;
            border-radius:999px;
            background:#EFF6FF;
            border:1px solid #BFDBFE;
            color:#2563EB!important;
            font-size:10px;
            font-weight:900;
        }

        .af62-search-status:before {
            content:"";
            width:7px;
            height:7px;
            border-radius:50%;
            background:#2563EB;
            box-shadow:0 0 0 3px rgba(37,99,235,.12);
        }

        .af62-search-status.success {
            background:#ECFDF5;
            border-color:#A7F3D0;
            color:#047857!important;
        }

        .af62-search-status.success:before {
            background:#10B981;
            box-shadow:0 0 0 3px rgba(16,185,129,.12);
        }

        .af62-search-status.warning {
            background:#FFFBEB;
            border-color:#FDE68A;
            color:#B45309!important;
        }

        .af62-search-status.warning:before {
            background:#F59E0B;
            box-shadow:0 0 0 3px rgba(245,158,11,.12);
        }

        .af62-data-link {
            color:#2563EB!important;
            text-decoration:none!important;
            font-weight:900!important;
        }

        .af62-data-link:hover {
            text-decoration:underline!important;
        }

        .af62-field.risk-low {
            background:#F0FDF4;
            border-color:#BBF7D0;
        }

        .af62-field.risk-medium {
            background:#FFFBEB;
            border-color:#FDE68A;
        }

        .af62-field.risk-high {
            background:#FEF2F2;
            border-color:#FECACA;
        }

        .af62-tips {
            display:grid;
            gap:11px;
        }

        .af62-tip {
            display:grid;
            grid-template-columns:28px minmax(0,1fr);
            gap:10px;
            align-items:start;
            color:#52647A!important;
            font-size:12px;
            line-height:1.5;
            font-weight:720;
        }

        .af62-tip-num {
            width:26px;
            height:26px;
            display:flex;
            align-items:center;
            justify-content:center;
            border-radius:9px;
            background:#EFF6FF;
            border:1px solid #BFDBFE;
            color:#2563EB!important;
            font-size:10px;
            font-weight:950;
        }

        .af62-examples {
            display:flex;
            flex-wrap:wrap;
            gap:8px;
            margin-top:14px;
        }

        .af62-chip {
            display:inline-flex;
            align-items:center;
            padding:7px 9px;
            border-radius:999px;
            background:#F8FAFC;
            border:1px solid #E2E8F0;
            color:#334155!important;
            font-size:10px;
            font-weight:850;
        }

        @media(max-width:900px){
            .af62-title{font-size:30px;}
            .af62-summary-grid{grid-template-columns:1fr;}
        }

        /* Milestone 6.2B — Best Recommendation Experience */
        .af62b-section-head{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:16px;
            margin:28px 0 12px;
        }

        .af62b-section-title{
            color:#0B1220!important;
            font-size:22px;
            font-weight:980;
            letter-spacing:-.04em;
            line-height:1.1;
        }

        .af62b-section-meta{
            color:#64748B!important;
            font-size:12px;
            font-weight:760;
            line-height:1.45;
            margin-top:5px;
        }

        .af62b-found-pill{
            display:inline-flex;
            align-items:center;
            gap:7px;
            padding:7px 10px;
            border-radius:999px;
            background:#ECFDF5;
            border:1px solid #A7F3D0;
            color:#047857!important;
            font-size:10px;
            font-weight:950;
            white-space:nowrap;
        }

        .af62b-found-pill:before{
            content:"";
            width:7px;
            height:7px;
            border-radius:50%;
            background:#10B981;
            box-shadow:0 0 0 3px rgba(16,185,129,.12);
        }

        .st-key-af62b_best_card{
            padding:22px!important;
            border:1px solid #BFDBFE!important;
            border-radius:22px!important;
            background:
                radial-gradient(circle at 95% 0%, rgba(37,99,235,.12), transparent 32%),
                linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 100%)!important;
            box-shadow:0 20px 52px rgba(37,99,235,.10)!important;
        }

        .af62b-best-top{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:18px;
            margin-bottom:18px;
        }

        .af62b-eyebrow{
            display:inline-flex;
            align-items:center;
            gap:7px;
            padding:7px 10px;
            border-radius:999px;
            background:#EFF6FF;
            border:1px solid #BFDBFE;
            color:#2563EB!important;
            font-size:10px;
            font-weight:950;
            letter-spacing:.08em;
            text-transform:uppercase;
            margin-bottom:11px;
        }

        .af62b-best-part{
            color:#0B1220!important;
            font-size:30px;
            font-weight:980;
            line-height:1;
            letter-spacing:-.05em;
            margin-bottom:9px;
        }

        .af62b-best-copy{
            color:#52647A!important;
            font-size:13px;
            line-height:1.55;
            font-weight:750;
            max-width:720px;
        }

        .af62b-score{
            width:112px;
            min-width:112px;
            height:112px;
            border-radius:24px;
            display:flex;
            flex-direction:column;
            align-items:center;
            justify-content:center;
            background:#FFFFFF;
            border:1px solid #BFDBFE;
            box-shadow:0 14px 34px rgba(37,99,235,.10);
        }

        .af62b-score strong{
            color:#2563EB!important;
            font-size:31px;
            line-height:1;
            font-weight:980;
        }

        .af62b-score span{
            color:#64748B!important;
            font-size:9px;
            font-weight:950;
            text-transform:uppercase;
            letter-spacing:.08em;
            margin-top:7px;
            text-align:center;
        }

        .af62b-metrics{
            display:grid;
            grid-template-columns:repeat(5,minmax(0,1fr));
            gap:10px;
            margin-top:4px;
        }

        .af62b-metric{
            min-width:0;
            padding:14px;
            border-radius:16px;
            background:#FFFFFF;
            border:1px solid #E2E8F0;
        }

        .af62b-metric span{
            display:block;
            color:#64748B!important;
            font-size:9px;
            font-weight:950;
            letter-spacing:.08em;
            text-transform:uppercase;
            margin-bottom:7px;
        }

        .af62b-metric strong{
            display:block;
            color:#0B1220!important;
            font-size:16px;
            line-height:1.25;
            font-weight:950;
            overflow-wrap:anywhere;
        }

        .af62b-metric.good{
            background:#F0FDF4;
            border-color:#BBF7D0;
        }

        .af62b-metric.warn{
            background:#FFFBEB;
            border-color:#FDE68A;
        }

        .af7-intelligence-card{
            border:1px solid #cbdcfb;
            border-radius:22px;
            padding:22px 24px;
            margin:18px 0 16px;
            background:
                radial-gradient(circle at 100% 0%, rgba(37,99,235,.12), transparent 35%),
                linear-gradient(135deg,#ffffff 0%,#f8fbff 100%);
            box-shadow:0 18px 42px rgba(15,23,42,.07);
        }
        .af7-intelligence-top{
            display:flex;
            justify-content:space-between;
            gap:18px;
            align-items:flex-start;
            margin-bottom:14px;
        }
        .af7-intelligence-eyebrow{
            color:#2563eb;
            font-size:11px;
            font-weight:900;
            letter-spacing:.11em;
            text-transform:uppercase;
            margin-bottom:7px;
        }
        .af7-intelligence-title{
            color:#0f172a;
            font-size:22px;
            line-height:1.15;
            font-weight:900;
            margin-bottom:6px;
        }
        .af7-intelligence-summary{
            color:#475569;
            font-size:14px;
            line-height:1.55;
            max-width:980px;
        }
        .af7-confidence-badge{
            flex:0 0 auto;
            border:1px solid #bfdbfe;
            border-radius:999px;
            background:#eff6ff;
            color:#1d4ed8;
            padding:8px 12px;
            font-size:12px;
            font-weight:850;
            white-space:nowrap;
        }
        .af7-factor-grid{
            display:grid;
            grid-template-columns:repeat(5,minmax(0,1fr));
            gap:10px;
            margin-top:16px;
        }
        .af7-factor{
            border:1px solid #dbe3ef;
            border-radius:16px;
            background:rgba(255,255,255,.88);
            padding:13px 14px;
            min-height:104px;
        }
        .af7-factor span{
            display:block;
            color:#64748b;
            font-size:9px;
            font-weight:900;
            letter-spacing:.10em;
            text-transform:uppercase;
            margin-bottom:7px;
        }
        .af7-factor strong{
            display:block;
            color:#0f172a;
            font-size:16px;
            line-height:1.25;
            margin-bottom:8px;
        }
        .af7-factor p{
            color:#64748b;
            font-size:11px;
            line-height:1.38;
            margin:0;
        }
        .af7-meter{
            height:6px;
            border-radius:999px;
            background:#e2e8f0;
            overflow:hidden;
            margin-top:10px;
        }
        .af7-meter > i{
            display:block;
            height:100%;
            border-radius:999px;
            background:#2563eb;
        }
        .af7-meter.good > i{background:#10b981;}
        .af7-meter.warn > i{background:#f59e0b;}
        .af7-meter.bad > i{background:#ef4444;}
        .af122-decision{border:1px solid #bfdbfe;background:linear-gradient(135deg,#ffffff,#eff6ff);border-radius:22px;padding:18px;margin:14px 0;box-shadow:0 14px 36px rgba(37,99,235,.07)}
        .af122-decision-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.af122-eyebrow{font-size:9px;font-weight:950;letter-spacing:.09em;text-transform:uppercase;color:#2563eb;margin-bottom:6px}.af122-title{font-size:20px;font-weight:950;color:#0f172a;letter-spacing:-.025em}.af122-copy{font-size:11px;font-weight:700;color:#52647a;line-height:1.55;margin-top:5px}
        .af122-badge{border-radius:999px;padding:7px 10px;font-size:9px;font-weight:950;white-space:nowrap;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8}.af122-badge.good{border-color:#a7f3d0;background:#ecfdf5;color:#047857}.af122-badge.warn{border-color:#fde68a;background:#fffbeb;color:#b45309}.af122-badge.bad{border-color:#fecaca;background:#fef2f2;color:#b91c1c}
        .af122-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:14px}.af122-metric{border:1px solid #dbe3ef;background:#fff;border-radius:14px;padding:11px}.af122-metric span{display:block;font-size:8px;font-weight:950;text-transform:uppercase;letter-spacing:.07em;color:#64748b;margin-bottom:5px}.af122-metric strong{font-size:12px;font-weight:900;color:#0f172a;line-height:1.35}
        .af122-lists{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.af122-list{border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:13px}.af122-list.good{border-color:#bbf7d0;background:#f0fdf4}.af122-list.warn{border-color:#fde68a;background:#fffbeb}.af122-list.bad{border-color:#fecaca;background:#fef2f2}.af122-list h4{font-size:10px;font-weight:950;text-transform:uppercase;letter-spacing:.07em;color:#0f172a;margin:0 0 8px}.af122-list div{font-size:10px;font-weight:700;color:#475569;line-height:1.5;margin:5px 0;padding-left:12px;position:relative}.af122-list div:before{content:"•";position:absolute;left:0;color:#2563eb}
        @media(max-width:900px){.af122-grid,.af122-lists{grid-template-columns:1fr}.af122-decision-top{display:block}.af122-badge{display:inline-block;margin-top:10px}}
        .af7-explain-note{
            color:#64748b;
            font-size:11px;
            line-height:1.45;
            margin-top:12px;
        }

        .af62b-analysis-grid{
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:12px;
            margin:16px 0 6px;
        }

        .af62b-analysis-card{
            min-height:126px;
            padding:15px;
            border-radius:17px;
            background:#FFFFFF;
            border:1px solid #E2E8F0;
            box-shadow:0 10px 26px rgba(15,23,42,.035);
        }

        .af62b-analysis-card.good{
            background:#F0FDF4;
            border-color:#BBF7D0;
        }

        .af62b-analysis-card.warning{
            background:#FFFBEB;
            border-color:#FDE68A;
        }

        .af62b-analysis-card.tradeoff{
            background:#FEF2F2;
            border-color:#FECACA;
        }

        .af62b-analysis-title{
            color:#0B1220!important;
            font-size:12px;
            font-weight:950;
            margin-bottom:10px;
        }

        .af62b-analysis-list{
            display:grid;
            gap:7px;
        }

        .af62b-analysis-item{
            color:#52647A!important;
            font-size:11px;
            font-weight:740;
            line-height:1.4;
        }

        .af62b-analysis-empty{
            color:#94A3B8!important;
            font-size:11px;
            font-weight:740;
        }

        .af62b-compare-head{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:14px;
            margin:18px 0 10px;
        }

        .af62b-compare-title{
            color:#0B1220!important;
            font-size:17px;
            font-weight:970;
            letter-spacing:-.025em;
        }

        .af62b-compare-sub{
            color:#64748B!important;
            font-size:11px;
            font-weight:740;
            margin-top:3px;
        }

        .af62b-compact-table [data-testid="stDataFrame"]{
            border:1px solid #E2E8F0;
            border-radius:16px;
            overflow:hidden;
        }

        .af62b-reset-note{
            color:#64748B!important;
            font-size:11px;
            font-weight:740;
            margin-top:8px;
        }

        @media(max-width:1100px){
            .af62b-metrics{grid-template-columns:repeat(2,minmax(0,1fr));}
            .af62b-analysis-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
            .af7-factor-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
        }

        @media(max-width:760px){
            .af62b-best-top{flex-direction:column;}
            .af62b-score{width:100%;height:auto;min-height:88px;}
            .af62b-metrics{grid-template-columns:1fr;}
            .af62b-analysis-grid{grid-template-columns:1fr;}
            .af7-factor-grid{grid-template-columns:1fr;}
        }

        /* Milestone 6.2B.1 — results cleanup and focused actions */
        .af62b-action-note{
            color:#64748B!important;
            font-size:11px;
            font-weight:760;
            line-height:1.45;
            padding-top:8px;
        }
        .af62b-shortlist-pill{
            display:inline-flex;
            align-items:center;
            gap:7px;
            padding:7px 10px;
            border-radius:999px;
            background:#ECFDF5;
            border:1px solid #A7F3D0;
            color:#047857!important;
            font-size:10px;
            font-weight:950;
        }
        .af62b-shortlist-pill:before{
            content:"";
            width:7px;
            height:7px;
            border-radius:50%;
            background:#10B981;
        }
        .af62b-advanced-copy{
            color:#64748B!important;
            font-size:12px;
            font-weight:740;
            line-height:1.5;
            margin:0 0 12px;
        }
        .st-key-af62b_compact_table [data-testid="stDataFrame"]{
            max-height:430px!important;
            overflow:auto!important;
        }
        .st-key-af62b_save_candidate button,
        .st-key-af62b_advanced_compare button{
            border-radius:12px!important;
            font-weight:900!important;
        }
        @media(max-width:760px){
            .af62b-action-note{padding-top:0;}
        }

        /* Milestone 6.3A — Engineering Decision Workspace */
        .af63-score-label{
            display:inline-flex;
            align-items:center;
            gap:6px;
            margin-top:8px;
            padding:5px 8px;
            border-radius:999px;
            background:#ECFDF5;
            border:1px solid #A7F3D0;
            color:#047857!important;
            font-size:9px;
            font-weight:950;
            text-transform:uppercase;
            letter-spacing:.06em;
        }

        .af63-score-label.medium{
            background:#FFFBEB;
            border-color:#FDE68A;
            color:#B45309!important;
        }

        .af63-score-label.low{
            background:#FEF2F2;
            border-color:#FECACA;
            color:#B91C1C!important;
        }

        .af63-decision-shell{
            margin:18px 0 14px;
            padding:18px;
            border-radius:20px;
            background:#FFFFFF;
            border:1px solid #E2E8F0;
            box-shadow:0 14px 34px rgba(15,23,42,.045);
        }

        .af63-decision-head{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:16px;
            margin-bottom:15px;
        }

        .af63-decision-title{
            color:#0B1220!important;
            font-size:18px;
            font-weight:980;
            letter-spacing:-.035em;
            line-height:1.1;
        }

        .af63-decision-copy{
            color:#64748B!important;
            font-size:11px;
            font-weight:760;
            line-height:1.45;
            margin-top:5px;
        }

        .af63-decision-status{
            display:inline-flex;
            align-items:center;
            gap:7px;
            padding:7px 10px;
            border-radius:999px;
            background:#F8FAFC;
            border:1px solid #CBD5E1;
            color:#475569!important;
            font-size:10px;
            font-weight:950;
            white-space:nowrap;
        }

        .af63-decision-status.approved{
            background:#ECFDF5;
            border-color:#A7F3D0;
            color:#047857!important;
        }

        .af63-decision-status.rejected{
            background:#FEF2F2;
            border-color:#FECACA;
            color:#B91C1C!important;
        }

        .af63-decision-status.saved{
            background:#EFF6FF;
            border-color:#BFDBFE;
            color:#1D4ED8!important;
        }

        .af63-decision-grid{
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:10px;
            margin-bottom:14px;
        }

        .af63-decision-metric{
            padding:13px 14px;
            border-radius:15px;
            background:#F8FAFC;
            border:1px solid #E2E8F0;
        }

        .af63-decision-metric span{
            display:block;
            color:#64748B!important;
            font-size:9px;
            font-weight:950;
            letter-spacing:.08em;
            text-transform:uppercase;
            margin-bottom:7px;
        }

        .af63-decision-metric strong{
            display:block;
            color:#0B1220!important;
            font-size:15px;
            font-weight:950;
            line-height:1.25;
        }

        .af63-action-help{
            color:#64748B!important;
            font-size:10px;
            line-height:1.45;
            font-weight:740;
            padding-top:5px;
        }

        .st-key-af63_approve button{
            background:#16A34A!important;
            border-color:#16A34A!important;
            color:#FFFFFF!important;
            border-radius:12px!important;
            font-weight:900!important;
        }

        .st-key-af63_reject button{
            background:#FFFFFF!important;
            border-color:#FCA5A5!important;
            color:#B91C1C!important;
            border-radius:12px!important;
            font-weight:900!important;
        }

        .st-key-af63_save button,
        .st-key-af63_download button{
            border-radius:12px!important;
            font-weight:900!important;
        }

        .af63-saved-message{
            display:inline-flex;
            align-items:center;
            gap:7px;
            min-height:42px;
            padding:0 12px;
            border-radius:12px;
            background:#ECFDF5;
            border:1px solid #A7F3D0;
            color:#047857!important;
            font-size:11px;
            font-weight:950;
        }

        @media(max-width:1000px){
            .af63-decision-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
        }

        @media(max-width:700px){
            .af63-decision-head{flex-direction:column;}
            .af63-decision-grid{grid-template-columns:1fr;}
        }

        /* Milestone 6.2C — Persistent Engineering Decision Records */
        .af62c-persist-note{
            display:flex;
            align-items:flex-start;
            gap:9px;
            padding:11px 12px;
            border-radius:14px;
            background:#EFF6FF;
            border:1px solid #BFDBFE;
            color:#1E40AF!important;
            font-size:10px;
            line-height:1.45;
            font-weight:800;
            margin:10px 0 0;
        }

        .af62c-persist-note:before{
            content:"";
            width:8px;
            height:8px;
            min-width:8px;
            margin-top:3px;
            border-radius:50%;
            background:#2563EB;
            box-shadow:0 0 0 3px rgba(37,99,235,.12);
        }

        .af62c-history-head{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            margin-bottom:10px;
        }

        .af62c-history-count{
            display:inline-flex;
            align-items:center;
            padding:6px 9px;
            border-radius:999px;
            background:#F8FAFC;
            border:1px solid #CBD5E1;
            color:#475569!important;
            font-size:9px;
            font-weight:950;
        }

        .af62c-db-success{
            display:inline-flex;
            align-items:center;
            gap:7px;
            min-height:42px;
            padding:0 12px;
            border-radius:12px;
            background:#ECFDF5;
            border:1px solid #A7F3D0;
            color:#047857!important;
            font-size:11px;
            font-weight:950;
        }

        .af62c-db-warning{
            padding:10px 12px;
            border-radius:12px;
            background:#FFFBEB;
            border:1px solid #FDE68A;
            color:#92400E!important;
            font-size:10px;
            line-height:1.45;
            font-weight:800;
        }

        .st-key-af62c_archive button{
            border-radius:10px!important;
            border-color:#FCA5A5!important;
            color:#B91C1C!important;
            font-weight:900!important;
        }

        .st-key-af63_change_package button,
        .st-key-af63_download button{
            min-height:44px!important;
            border-radius:12px!important;
            font-weight:900!important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "suggested_alternatives" not in st.session_state:
        st.session_state["suggested_alternatives"] = []

    if "alternative_search_attempted" not in st.session_state:
        st.session_state["alternative_search_attempted"] = False

    incoming_original_part = str(
        st.query_params.get("original_part", "") or ""
    ).strip()
    incoming_analysis_id = str(
        st.query_params.get("analysis_id", "") or ""
    ).strip()
    incoming_prefill_token = (
        f"{incoming_analysis_id}::{incoming_original_part.upper()}"
        if incoming_original_part
        else ""
    )

    if "alternative_original_part" not in st.session_state:
        st.session_state["alternative_original_part"] = ""

    if (
        incoming_original_part
        and st.session_state.get("alternative_prefill_token") != incoming_prefill_token
    ):
        st.session_state["alternative_original_part"] = incoming_original_part
        st.session_state["alternative_prefill_token"] = incoming_prefill_token
        st.session_state["alternative_search_attempted"] = False
        st.session_state["suggested_alternatives"] = []
        st.session_state["alternative_original_data"] = {}
        st.session_state["alternative_original_risk"] = {}
        st.session_state["alternative_original_lookup_part"] = ""
        st.session_state["alternative_original_lookup_error"] = ""

    if "alternative_original_data" not in st.session_state:
        st.session_state["alternative_original_data"] = {}

    if "alternative_original_risk" not in st.session_state:
        st.session_state["alternative_original_risk"] = {}

    if "alternative_original_lookup_part" not in st.session_state:
        st.session_state["alternative_original_lookup_part"] = ""

    if "alternative_original_lookup_error" not in st.session_state:
        st.session_state["alternative_original_lookup_error"] = ""

    if "alternative_candidate_shortlist" not in st.session_state:
        st.session_state["alternative_candidate_shortlist"] = []

    if "alternative_engineering_decisions" not in st.session_state:
        st.session_state["alternative_engineering_decisions"] = {}

    if "alternative_decision_notes" not in st.session_state:
        st.session_state["alternative_decision_notes"] = {}

    if "alternative_decision_db_status" not in st.session_state:
        st.session_state["alternative_decision_db_status"] = ""

    if "alternative_decision_db_error" not in st.session_state:
        st.session_state["alternative_decision_db_error"] = ""

    if "alternative_decision_flash" not in st.session_state:
        st.session_state["alternative_decision_flash"] = ""

    with st.container(border=True, key="af62_hero"):
        st.markdown(
            """
            <div class="af62-eyebrow">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.3-4.3"></path></svg>
              Alternative Component Finder
            </div>
            <div class="af62-title">Find a stronger replacement path.</div>
            <p class="af62-copy">Search a manufacturer part number, compare sourcing intelligence, and prepare an engineering-compatible replacement workflow without leaving the Cadivor workspace.</p>
            """,
            unsafe_allow_html=True,
        )

    with st.container(border=True, key="af62_search"):
        st.markdown(
            """
            <div class="af62-card-head">
              <div>
                <div class="af62-card-title">Search original component</div>
                <div class="af62-card-subtitle">Start with the complete manufacturer part number used in your design.</div>
              </div>
              <div class="af62-icon">
                <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.3-4.3"></path></svg>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        search_input_col, search_button_col = st.columns([4.5, 1.25], gap="medium")
        with search_input_col:
            original_part = st.text_input(
                "Manufacturer part number",
                key="alternative_original_part",
                placeholder="Example: ATMEGA328P-PU",
            )
        with search_button_col:
            st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
            find_alternatives_clicked = st.button(
                "Find Alternatives →",
                type="primary",
                use_container_width=True,
                key="alternative_find_button_62a",
            )

    if find_alternatives_clicked:
        searched_part = (original_part or "").strip()

        if not searched_part:
            st.warning("Please enter an original part number.")
        else:
            with st.spinner(
                "Searching suppliers • Loading original component intelligence • "
                "Comparing electrical specs • Ranking alternatives..."
            ):
                try:
                    original_lookup = get_best_part_data(searched_part) or {}
                    if not isinstance(original_lookup, dict):
                        original_lookup = {}

                    try:
                        original_risk = calculate_risk(original_lookup) or {}
                    except Exception:
                        original_risk = {}

                    st.session_state["alternative_original_data"] = original_lookup
                    st.session_state["alternative_original_risk"] = original_risk
                    st.session_state["alternative_original_lookup_part"] = searched_part
                    st.session_state["alternative_original_lookup_error"] = ""

                except Exception as lookup_error:
                    st.session_state["alternative_original_data"] = {}
                    st.session_state["alternative_original_risk"] = {}
                    st.session_state["alternative_original_lookup_part"] = searched_part
                    st.session_state["alternative_original_lookup_error"] = str(
                        lookup_error
                    )

                st.session_state["suggested_alternatives"] = suggest_alternatives_v2(
                    searched_part
                )
                st.session_state["alternative_search_attempted"] = True

    summary_col, tips_col = st.columns([1.35, 0.85], gap="medium")

    current_search = (original_part or "").strip()
    current_display = (
        html.escape(current_search) if current_search else "No component entered"
    )

    lookup_part = st.session_state.get("alternative_original_lookup_part", "")
    lookup_matches_input = bool(
        current_search
        and lookup_part
        and current_search.strip().upper() == lookup_part.strip().upper()
    )

    original_summary_data = (
        st.session_state.get("alternative_original_data", {})
        if lookup_matches_input
        else {}
    )
    original_summary_risk = (
        st.session_state.get("alternative_original_risk", {})
        if lookup_matches_input
        else {}
    )
    original_lookup_error = (
        st.session_state.get("alternative_original_lookup_error", "")
        if lookup_matches_input
        else ""
    )

    def _af62_first(data, keys, fallback="—"):
        if not isinstance(data, dict):
            return fallback
        for key in keys:
            value = data.get(key)
            if value is not None and str(value).strip() not in {"", "None", "nan"}:
                return str(value).strip()
        return fallback

    manufacturer_display = html.escape(
        _af62_first(
            original_summary_data,
            [
                "manufacturer",
                "Manufacturer",
                "manufacturer_name",
                "brand",
            ],
        )
    )

    lifecycle_display = html.escape(
        _af62_first(
            original_summary_data,
            [
                "lifecycle_status",
                "Lifecycle Status",
                "lifecycle",
                "status",
            ],
        )
    )

    package_display = html.escape(
        _af62_first(
            original_summary_data,
            [
                "package",
                "Package",
                "package_type",
                "case_package",
            ],
        )
    )

    risk_display_raw = _af62_first(
        original_summary_risk,
        ["risk_level", "Risk Level"],
        fallback=_af62_first(
            original_summary_data,
            ["risk_level", "Risk Level", "estimated_risk"],
        ),
    )
    risk_display = html.escape(risk_display_raw)

    risk_class = ""
    if risk_display_raw.lower() == "low":
        risk_class = "risk-low"
    elif risk_display_raw.lower() == "medium":
        risk_class = "risk-medium"
    elif risk_display_raw.lower() == "high":
        risk_class = "risk-high"

    datasheet_url = _af62_first(
        original_summary_data,
        [
            "datasheet_url",
            "datasheet",
            "Datasheet URL",
            "product_detail_url",
            "product_url",
            "url",
        ],
        fallback="",
    )

    if datasheet_url.startswith(("https://", "http://")):
        safe_datasheet_url = html.escape(datasheet_url, quote=True)
        datasheet_display = (
            f'<a class="af62-data-link" href="{safe_datasheet_url}" '
            f'target="_blank" rel="noopener noreferrer">Open source page →</a>'
        )
    else:
        datasheet_display = "Not available"

    if original_lookup_error:
        current_status = "Supplier lookup unavailable"
        current_status_class = "warning"
    elif lookup_matches_input and original_summary_data:
        current_status = "Component intelligence loaded"
        current_status_class = "success"
    elif current_search:
        current_status = "Ready to search"
        current_status_class = ""
    else:
        current_status = "Waiting for a part number"
        current_status_class = ""

    with summary_col:
        with st.container(border=True, key="af62_summary"):
            st.markdown(
                f"""
                <div class="af62-card-head">
                  <div>
                    <div class="af62-card-title">Current search</div>
                    <div class="af62-card-subtitle">The original component Cadivor will use as the comparison baseline.</div>
                  </div>
                  <div class="af62-icon green">
                    <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m7.5 4.27 9 5.15"></path><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"></path><path d="m3.3 7 8.7 5 8.7-5"></path><path d="M12 22V12"></path></svg>
                  </div>
                </div>
                <div class="af62-summary-grid">
                  <div class="af62-field"><span>Part Number</span><strong>{current_display}</strong></div>
                  <div class="af62-field"><span>Manufacturer</span><strong>{manufacturer_display}</strong></div>
                  <div class="af62-field"><span>Lifecycle</span><strong>{lifecycle_display}</strong></div>
                  <div class="af62-field {risk_class}"><span>Risk</span><strong>{risk_display}</strong></div>
                  <div class="af62-field"><span>Package</span><strong>{package_display}</strong></div>
                  <div class="af62-field"><span>Datasheet / Source</span><strong>{datasheet_display}</strong></div>
                </div>
                <div class="af62-search-status {current_status_class}">{current_status}</div>
                """,
                unsafe_allow_html=True,
            )

    with tips_col:
        with st.container(border=True, key="af62_tips"):
            st.markdown(
                """
                <div class="af62-card-head">
                  <div>
                    <div class="af62-card-title">Search tips</div>
                    <div class="af62-card-subtitle">A precise part number produces the strongest comparison set.</div>
                  </div>
                  <div class="af62-icon amber">
                    <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"></path><path d="M10 22h4"></path><path d="M15.09 14c.18-.69.66-1.19 1.15-1.75A6 6 0 1 0 7.76 12.25c.48.55.97 1.05 1.15 1.75"></path></svg>
                  </div>
                </div>
                <div class="af62-tips">
                  <div class="af62-tip"><div class="af62-tip-num">1</div><div>Enter the complete manufacturer part number, including package or suffix details.</div></div>
                  <div class="af62-tip"><div class="af62-tip-num">2</div><div>Use the exact part used in the BOM so electrical and package comparisons remain meaningful.</div></div>
                  <div class="af62-tip"><div class="af62-tip-num">3</div><div>Cadivor will rank candidates using compatibility, lifecycle, stock, supplier, and cost signals.</div></div>
                </div>
                <div class="af62-examples">
                  <span class="af62-chip">ATMEGA328P-PU</span>
                  <span class="af62-chip">STM32F103C8T6</span>
                  <span class="af62-chip">TPS54331DR</span>
                  <span class="af62-chip">LM358N</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
    if st.session_state["suggested_alternatives"]:
        alternatives_df = pd.DataFrame(
            st.session_state["suggested_alternatives"]
        )

        best_alternative = max(
            st.session_state["suggested_alternatives"],
            key=lambda x: x.get("Recommendation Score", 0),
        )

        best_part_number = str(best_alternative.get("Alternative Part", "") or "")
        alternative_options = alternatives_df["Alternative Part"].astype(str).tolist()
        best_index = (
            alternative_options.index(best_part_number)
            if best_part_number in alternative_options
            else 0
        )

        st.markdown(
            f"""
            <div class="af62b-section-head">
              <div>
                <div class="af62b-section-title">Replacement intelligence</div>
                <div class="af62b-section-meta">Cadivor ranked the strongest candidates using engineering compatibility, lifecycle, stock, supplier, and cost signals.</div>
              </div>
              <div class="af62b-found-pill">{len(alternatives_df)} candidates found</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        selected_alternative = st.selectbox(
            "Recommended candidate",
            alternative_options,
            index=best_index,
            key="alternative_selected_candidate_62b",
            help="Choose another candidate to refresh the recommendation and comparison workspace.",
        )

        selected_row = alternatives_df[
            alternatives_df["Alternative Part"].astype(str) == selected_alternative
        ].iloc[0]

        stored_original_data = st.session_state.get(
            "alternative_original_data", {}
        )
        stored_lookup_part = st.session_state.get(
            "alternative_original_lookup_part", ""
        )

        if (
            isinstance(stored_original_data, dict)
            and stored_original_data
            and str(stored_lookup_part).strip().upper()
            == str(original_part).strip().upper()
        ):
            original_data = stored_original_data
        else:
            original_data = get_best_part_data(original_part) or {}
            st.session_state["alternative_original_data"] = original_data
            st.session_state["alternative_original_lookup_part"] = original_part

        def _af62b_value(row, keys, fallback="—"):
            for key in keys:
                try:
                    value = row.get(key)
                except Exception:
                    value = None
                if value is not None and str(value).strip() not in {"", "None", "nan"}:
                    return str(value).strip()
            return fallback

        recommendation_score = int(float(selected_row.get("Recommendation Score", 0) or 0))
        drop_in_confidence = int(float(selected_row.get("Drop-In Confidence", 0) or 0))
        lifecycle_value = _af62b_value(selected_row, ["Lifecycle"], "Unknown")
        risk_value = _af62b_value(selected_row, ["Estimated Risk"], "Unknown")
        supplier_value = _af62b_value(
            selected_row,
            ["Supplier", "Best Source", "Source"],
            "Supplier not listed",
        )
        stock_value = float(selected_row.get("Stock", 0) or 0)
        price_value = float(selected_row.get("Unit Price", 0) or 0)
        package_value = _af62b_value(selected_row, ["Package"], "Not verified")
        recommendation_copy = _af62b_value(
            selected_row,
            ["Recommendation"],
            "Candidate identified from available engineering and sourcing signals.",
        )

        original_stock = float(original_data.get("stock_total", 0) or 0)
        alternative_stock = stock_value

        original_price = float(original_data.get("unit_price", 0.0) or 0.0)
        alternative_price = price_value

        if original_stock > 0 and alternative_stock > 0:
            stock_ratio = alternative_stock / original_stock
            if stock_ratio > 1:
                stock_delta = f"🟢 {stock_ratio:.0f}× more stock available"
            else:
                stock_delta = f"🔴 {(1 / stock_ratio):.1f}× less stock available"
        elif original_stock > 0 and alternative_stock == 0:
            stock_delta = "🔴 No stock available"
        else:
            stock_delta = "N/A"

        if original_price > 0:
            price_pct = (
                (alternative_price - original_price) / original_price
            ) * 100
            if price_pct < 0:
                price_delta = f"🟢 {abs(price_pct):.1f}% lower cost"
            else:
                price_delta = f"🔴 {price_pct:.1f}% higher cost"
        else:
            price_delta = "N/A"

        drop_in_reasons = str(
            selected_row.get("Drop-In Reasons", "") or ""
        )
        reason_list = [
            reason.strip()
            for reason in drop_in_reasons.split(";")
            if reason.strip()
        ]

        recommendation_points = []
        warning_points = []
        advantage_points = []
        tradeoff_points = []

        for reason in reason_list:
            lowered = reason.lower()
            if "could not be verified" in lowered:
                warning_points.append(reason)
            elif reason.startswith("⚠") or reason.startswith("ℹ"):
                warning_points.append(reason)
            else:
                recommendation_points.append(reason)

        if stock_delta != "N/A":
            if "more stock" in stock_delta.lower():
                advantage_points.append(stock_delta)
            else:
                tradeoff_points.append(stock_delta)

        if price_delta != "N/A":
            if "lower cost" in price_delta.lower():
                advantage_points.append(price_delta)
            else:
                tradeoff_points.append(price_delta)

        confidence_label = (
            "High" if drop_in_confidence >= 75
            else "Medium" if drop_in_confidence >= 50
            else "Low"
        )

        recommendation_label = (
            "Strong" if recommendation_score >= 75
            else "Review" if recommendation_score >= 55
            else "Weak"
        )
        recommendation_label_class = (
            "" if recommendation_score >= 75
            else "medium" if recommendation_score >= 55
            else "low"
        )
        confidence_class = (
            "good" if confidence_label == "High"
            else "warn" if confidence_label == "Medium"
            else ""
        )
        lifecycle_class = "good" if lifecycle_value.lower() == "active" else "warn"
        risk_class_62b = "good" if risk_value.lower() == "low" else "warn"

        alternative_reasoning = build_alternative_reasoning(
            original_part=original_part,
            original_data=original_data,
            candidate=selected_row.to_dict(),
            recommendation_score=recommendation_score,
            compatibility_confidence=drop_in_confidence,
            engineering_matches=recommendation_points,
            warnings=warning_points,
            stock_delta=stock_delta,
            price_delta=price_delta,
        )

        with st.container(border=True, key="af62b_best_card"):
            st.markdown(
                f"""
                <div class="af62b-best-top">
                  <div>
                    <div class="af62b-eyebrow">★ Recommended replacement</div>
                    <div class="af62b-best-part">{html.escape(selected_alternative)}</div>
                    <div class="af62b-best-copy">{html.escape(recommendation_copy)}</div>
                  </div>
                  <div class="af62b-score">
                    <strong>{recommendation_score}/100</strong>
                    <span>Recommendation score</span>
                    <div class="af63-score-label {recommendation_label_class}">{recommendation_label}</div>
                  </div>
                </div>

                <div class="af62b-metrics">
                  <div class="af62b-metric {lifecycle_class}">
                    <span>Lifecycle</span>
                    <strong>{html.escape(lifecycle_value)}</strong>
                  </div>
                  <div class="af62b-metric {risk_class_62b}">
                    <span>Estimated Risk</span>
                    <strong>{html.escape(risk_value)}</strong>
                  </div>
                  <div class="af62b-metric">
                    <span>Available Stock</span>
                    <strong>{int(stock_value):,}</strong>
                  </div>
                  <div class="af62b-metric">
                    <span>Supplier</span>
                    <strong>{html.escape(supplier_value)}</strong>
                  </div>
                  <div class="af62b-metric {confidence_class}">
                    <span>Compatibility Confidence</span>
                    <strong>{drop_in_confidence}% · {confidence_label}</strong>
                  </div>
                </div>

                <div class="af62b-metrics" style="margin-top:10px;grid-template-columns:repeat(3,minmax(0,1fr));">
                  <div class="af62b-metric">
                    <span>Package</span>
                    <strong>{html.escape(package_value)}</strong>
                  </div>
                  <div class="af62b-metric">
                    <span>Unit Price</span>
                    <strong>{"$" + format(price_value, ".4g") if price_value > 0 else "Not available"}</strong>
                  </div>
                  <div class="af62b-metric">
                    <span>Recommendation Rank</span>
                    <strong>{"Best match" if selected_alternative == best_part_number else "Alternative candidate"}</strong>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        # Milestone 7.0 — Explainable Engineering Intelligence
        lifecycle_strength = (
            100 if lifecycle_value.lower() == "active"
            else 55 if lifecycle_value.lower() in {"nrnd", "not recommended for new designs"}
            else 25
        )
        risk_strength = (
            92 if risk_value.lower() == "low"
            else 58 if risk_value.lower() == "medium"
            else 24
        )
        supply_strength = (
            96 if stock_value >= 50000
            else 82 if stock_value >= 10000
            else 62 if stock_value >= 1000
            else 30
        )

        if original_price > 0 and alternative_price > 0:
            cost_strength = max(
                10,
                min(
                    100,
                    int(
                        70
                        + ((original_price - alternative_price) / original_price) * 55
                    ),
                ),
            )
        else:
            cost_strength = 50

        warning_count = len(warning_points)
        if drop_in_confidence >= 75:
            intelligence_summary = (
                f"{selected_alternative} shows strong compatibility with the original "
                f"component and is suitable for focused engineering validation."
            )
        elif drop_in_confidence >= 50:
            intelligence_summary = (
                f"{selected_alternative} is a plausible replacement, but Cadivor identified "
                f"{warning_count} verification item{'s' if warning_count != 1 else ''} "
                f"that should be resolved before production release."
            )
        else:
            intelligence_summary = (
                f"{selected_alternative} should not be treated as a drop-in replacement. "
                f"The available evidence supports comparison and testing only, with "
                f"additional electrical and package verification required."
            )

        if "lower cost" in price_delta.lower():
            intelligence_summary += " The candidate also improves estimated unit cost."
        elif "higher cost" in price_delta.lower():
            intelligence_summary += " The candidate introduces a sourcing cost increase."

        if "more stock" in stock_delta.lower():
            intelligence_summary += " Current supplier inventory is stronger than the original."

        compatibility_detail = (
            f"{drop_in_confidence}% confidence"
            if drop_in_confidence > 0
            else "Not verified"
        )
        lifecycle_detail = (
            "Active lifecycle supports continued sourcing."
            if lifecycle_value.lower() == "active"
            else f"Lifecycle status: {lifecycle_value}."
        )
        risk_detail = (
            "Few material engineering risks detected."
            if risk_value.lower() == "low"
            else "Requires additional engineering review."
        )
        supply_detail = (
            f"{int(stock_value):,} units currently identified."
            if stock_value > 0
            else "Inventory was not confirmed."
        )
        cost_detail = (
            price_delta.replace("🟢", "").replace("🔴", "").strip()
            if price_delta != "N/A"
            else "Cost comparison unavailable."
        )

        def _af7_meter_class(value):
            if value >= 75:
                return "good"
            if value >= 50:
                return "warn"
            return "bad"

        st.markdown(
            f"""
            <div class="af7-intelligence-card">
              <div class="af7-intelligence-top">
                <div>
                  <div class="af7-intelligence-eyebrow">Cadivor engineering intelligence</div>
                  <div class="af7-intelligence-title">Why this recommendation?</div>
                  <div class="af7-intelligence-summary">{html.escape(intelligence_summary)}</div>
                </div>
                <div class="af7-confidence-badge">{recommendation_score}/100 recommendation</div>
              </div>

              <div class="af7-factor-grid">
                <div class="af7-factor">
                  <span>Compatibility</span>
                  <strong>{html.escape(compatibility_detail)}</strong>
                  <p>{len(recommendation_points)} verified match signal{'s' if len(recommendation_points) != 1 else ''}; {warning_count} warning{'s' if warning_count != 1 else ''}.</p>
                  <div class="af7-meter {_af7_meter_class(drop_in_confidence)}"><i style="width:{max(2, min(100, drop_in_confidence))}%"></i></div>
                </div>
                <div class="af7-factor">
                  <span>Lifecycle</span>
                  <strong>{html.escape(lifecycle_value)}</strong>
                  <p>{html.escape(lifecycle_detail)}</p>
                  <div class="af7-meter {_af7_meter_class(lifecycle_strength)}"><i style="width:{lifecycle_strength}%"></i></div>
                </div>
                <div class="af7-factor">
                  <span>Engineering Risk</span>
                  <strong>{html.escape(risk_value)}</strong>
                  <p>{html.escape(risk_detail)}</p>
                  <div class="af7-meter {_af7_meter_class(risk_strength)}"><i style="width:{risk_strength}%"></i></div>
                </div>
                <div class="af7-factor">
                  <span>Supply Position</span>
                  <strong>{int(stock_value):,} units</strong>
                  <p>{html.escape(supply_detail)}</p>
                  <div class="af7-meter {_af7_meter_class(supply_strength)}"><i style="width:{supply_strength}%"></i></div>
                </div>
                <div class="af7-factor">
                  <span>Cost Impact</span>
                  <strong>{"$" + format(price_value, ".4g") if price_value > 0 else "Not available"}</strong>
                  <p>{html.escape(cost_detail)}</p>
                  <div class="af7-meter {_af7_meter_class(cost_strength)}"><i style="width:{cost_strength}%"></i></div>
                </div>
              </div>

              <div class="af7-explain-note">
                These factor bars explain the evidence supporting Cadivor's recommendation.
                The official recommendation score remains the output of the ranking engine.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        def _af122_items(items, empty_text):
            values = list(items or [])
            if not values:
                return f"<div>{html.escape(empty_text)}</div>"
            return "".join(
                f"<div>{html.escape(str(item))}</div>"
                for item in values[:6]
            )

        st.markdown(
            f"""
            <section class="af122-decision">
              <div class="af122-decision-top">
                <div>
                  <div class="af122-eyebrow">Cadivor replacement decision</div>
                  <div class="af122-title">{html.escape(alternative_reasoning['disposition'])}</div>
                  <div class="af122-copy">{html.escape(alternative_reasoning['approval_guidance'])}</div>
                </div>
                <div class="af122-badge {html.escape(alternative_reasoning['disposition_tone'])}">
                  {alternative_reasoning['decision_confidence']}% decision confidence
                </div>
              </div>

              <div class="af122-grid">
                <div class="af122-metric">
                  <span>Recommended Use</span>
                  <strong>{html.escape(alternative_reasoning['use_case'])}</strong>
                </div>
                <div class="af122-metric">
                  <span>Estimated Engineering Effort</span>
                  <strong>{alternative_reasoning['estimated_effort_hours']} hours</strong>
                </div>
                <div class="af122-metric">
                  <span>Open Verification Items</span>
                  <strong>{alternative_reasoning['verification_count'] + alternative_reasoning['hard_blocker_count']}</strong>
                </div>
              </div>
            </section>

            <div class="af122-lists">
              <div class="af122-list good">
                <h4>Confirmed Evidence</h4>
                {_af122_items(alternative_reasoning['confirmed_matches'], 'No compatibility evidence has been confirmed.')}
              </div>
              <div class="af122-list warn">
                <h4>Verification Required</h4>
                {_af122_items(alternative_reasoning['verification_required'], 'No additional verification items were identified.')}
              </div>
              <div class="af122-list bad">
                <h4>Approval Blockers</h4>
                {_af122_items(alternative_reasoning['blockers'], 'No hard approval blockers were identified.')}
              </div>
            </div>

            <div class="af122-lists">
              <div class="af122-list good">
                <h4>Business Value</h4>
                {_af122_items(alternative_reasoning['business_value'], 'No confirmed commercial benefit was calculated.')}
              </div>
              <div class="af122-list warn">
                <h4>Expected Engineering Work</h4>
                {_af122_items(alternative_reasoning['expected_work'], 'No additional engineering work was calculated.')}
              </div>
              <div class="af122-list">
                <h4>Decision Rule</h4>
                <div>Qualification approval requires compatibility evidence, no unresolved hard blockers, and a completed engineering review record.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        def _af62b_items(points, empty_text):
            if not points:
                return f'<div class="af62b-analysis-empty">{html.escape(empty_text)}</div>'
            return '<div class="af62b-analysis-list">' + ''.join(
                f'<div class="af62b-analysis-item">{html.escape(str(point))}</div>'
                for point in points[:5]
            ) + '</div>'

        st.markdown(
            f"""
            <div class="af62b-analysis-grid">
              <div class="af62b-analysis-card good">
                <div class="af62b-analysis-title">Engineering Matches</div>
                {_af62b_items(recommendation_points, "No verified compatibility matches were returned.")}
              </div>
              <div class="af62b-analysis-card warning">
                <div class="af62b-analysis-title">Warnings</div>
                {_af62b_items(warning_points, "No engineering warnings were identified.")}
              </div>
              <div class="af62b-analysis-card good">
                <div class="af62b-analysis-title">Sourcing Advantages</div>
                {_af62b_items(advantage_points, "No sourcing advantage was calculated.")}
              </div>
              <div class="af62b-analysis-card tradeoff">
                <div class="af62b-analysis-title">Trade-offs</div>
                {_af62b_items(tradeoff_points, "No significant trade-offs identified.")}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        comparison_df = pd.DataFrame(
            [
                {
                    "Attribute": "Part Number",
                    "Original": original_part,
                    "Selected Alternative": selected_row.get("Alternative Part", ""),
                },
                {
                    "Attribute": "Lifecycle",
                    "Original": original_data.get("lifecycle_status", "Unknown"),
                    "Selected Alternative": selected_row.get("Lifecycle", "Unknown"),
                },
                {
                    "Attribute": "Supplier",
                    "Original": original_data.get("source", ""),
                    "Selected Alternative": selected_row.get("Supplier", ""),
                },
                {
                    "Attribute": "Stock",
                    "Original": original_data.get("stock_total", 0),
                    "Selected Alternative": selected_row.get("Stock", 0),
                },
                {
                    "Attribute": "Unit Price",
                    "Original": original_data.get("unit_price", 0.0),
                    "Selected Alternative": selected_row.get("Unit Price", 0.0),
                },
                {
                    "Attribute": "Stock Delta",
                    "Original": "—",
                    "Selected Alternative": stock_delta,
                },
                {
                    "Attribute": "Price Delta",
                    "Original": "—",
                    "Selected Alternative": price_delta,
                },
                {
                    "Attribute": "Package",
                    "Original": original_data.get("package")
                    or "Not available from supplier data",
                    "Selected Alternative": selected_row.get("Package", ""),
                },
                {
                    "Attribute": "Pin Count",
                    "Original": original_data.get("pin_count")
                    or "Not available from supplier data",
                    "Selected Alternative": selected_row.get("Pin Count", ""),
                },
                {
                    "Attribute": "Architecture",
                    "Original": original_data.get("architecture")
                    or original_data.get("Architecture")
                    or "Not available from supplier data",
                    "Selected Alternative": selected_row.get("Architecture", ""),
                },
                {
                    "Attribute": "Drop-In Confidence",
                    "Original": "—",
                    "Selected Alternative": selected_row.get("Drop-In Confidence", ""),
                },
                {
                    "Attribute": "Drop-In Rating",
                    "Original": "—",
                    "Selected Alternative": selected_row.get("Drop-In Rating", ""),
                },
            ]
        )

        st.markdown(
            """
            <div class="af62b-compare-head">
              <div>
                <div class="af62b-compare-title">Side-by-side engineering comparison</div>
                <div class="af62b-compare-sub">Review the selected recommendation against the original component.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.container(key="af62b_compact_table"):
            st.dataframe(
                comparison_df,
                use_container_width=True,
                hide_index=True,
            )

        st.markdown(
            """
            <div style="margin:22px 0 10px;">
              <div class="af62b-compare-title">Engineering Review &amp; Approval</div>
              <div class="af62b-compare-sub">Record the final disposition after reviewing compatibility evidence and the side-by-side comparison.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        candidate_key = (
            f"{str(original_part).strip().upper()}::"
            f"{str(selected_alternative).strip().upper()}"
        )

        shortlist = st.session_state.get("alternative_candidate_shortlist", [])
        decisions = st.session_state.get("alternative_engineering_decisions", {})
        decision_notes = st.session_state.get("alternative_decision_notes", {})

        already_saved = any(
            isinstance(item, dict) and item.get("candidate_key") == candidate_key
            for item in shortlist
        )
        persistent_candidate_record = None
        try:
            existing_candidate_records = load_analysis_decisions(
                current_user["id"],
                original_part=str(original_part),
                analysis_id=st.session_state.get("analysis_id"),
                limit=50,
            )
            if not existing_candidate_records:
                existing_candidate_records = load_analysis_decisions(
                    current_user["id"],
                    original_part=str(original_part),
                    limit=50,
                    include_all_contexts=True,
                )
            persistent_candidate_record = next(
                (
                    record
                    for record in existing_candidate_records
                    if str(record.get("alternative_part", "")).strip().upper()
                    == str(selected_alternative).strip().upper()
                ),
                None,
            )
        except Exception:
            existing_candidate_records = []

        if persistent_candidate_record:
            persisted_decision = str(
                persistent_candidate_record.get("decision", "Saved")
            )
            decisions[candidate_key] = persisted_decision
            st.session_state["alternative_engineering_decisions"] = decisions

            persisted_note = str(
                persistent_candidate_record.get("engineering_note", "") or ""
            )
            if candidate_key not in decision_notes and persisted_note:
                decision_notes[candidate_key] = persisted_note
                st.session_state["alternative_decision_notes"] = decision_notes

            already_saved = True

        current_decision = decisions.get(candidate_key, "Pending review")
        decision_status_class = (
            "approved" if current_decision == "Approved"
            else "rejected" if current_decision == "Rejected"
            else "saved" if already_saved
            else ""
        )

        st.markdown(
            f"""
            <div class="af63-decision-shell">
              <div class="af63-decision-head" style="justify-content:flex-end; margin-bottom:12px;">
                <div class="af63-decision-status {decision_status_class}">
                  {html.escape(current_decision if current_decision != "Pending review" else "Pending engineering review")}
                </div>
              </div>

              <div class="af63-decision-grid">
                <div class="af63-decision-metric">
                  <span>Candidate</span>
                  <strong>{html.escape(str(selected_alternative))}</strong>
                </div>
                <div class="af63-decision-metric">
                  <span>Compatibility</span>
                  <strong>{drop_in_confidence}% · {confidence_label}</strong>
                </div>
                <div class="af63-decision-metric">
                  <span>Engineering Risk</span>
                  <strong>{html.escape(risk_value)}</strong>
                </div>
                <div class="af63-decision-metric">
                  <span>Cost Impact</span>
                  <strong>{html.escape(price_delta)}</strong>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        note_value = decision_notes.get(candidate_key, "")
        engineering_note = st.text_area(
            "Decision note",
            value=note_value,
            placeholder=(
                "Example: Approve for prototype only. Package change requires PCB "
                "footprint revision before production release."
            ),
            height=88,
            key=f"af63_note_{candidate_key}",
        )
        st.session_state["alternative_decision_notes"][candidate_key] = engineering_note

        approve_col, reject_col, save_col = st.columns(
            [1, 1, 1],
            gap="medium",
        )

        active_analysis_id = st.session_state.get("analysis_id")
        active_project_name = (
            st.session_state.get("project_name")
            or st.session_state.get("current_project_name")
            or ""
        )

        decision_engineer_name = (
            profile_for_shell.get("full_name")
            or profile_for_shell.get("name")
            or current_user.get("full_name")
            or current_user.get("name")
            or current_user.get("email")
            or "Cadivor user"
        )

        decision_payload = {
            "analysis_id": active_analysis_id,
            "project_name": str(active_project_name),
            "engineer_name": str(decision_engineer_name),
            "original_part": str(original_part),
            "alternative_part": str(selected_alternative),
            "decision": current_decision,
            "engineering_note": engineering_note,
            "recommendation_score": recommendation_score,
            "recommendation_rating": recommendation_label,
            "compatibility_confidence": drop_in_confidence,
            "compatibility_rating": confidence_label,
            "copilot_disposition": alternative_reasoning.get("disposition"),
            "copilot_decision_confidence": alternative_reasoning.get("decision_confidence"),
            "copilot_approval_blockers": alternative_reasoning.get("blockers"),
            "copilot_verification_required": alternative_reasoning.get("verification_required"),
            "copilot_estimated_effort_hours": alternative_reasoning.get("estimated_effort_hours"),
            "lifecycle": lifecycle_value,
            "risk": risk_value,
            "supplier": supplier_value,
            "stock": int(stock_value),
            "unit_price": price_value,
            "package": package_value,
            "stock_delta": stock_delta,
            "price_delta": price_delta,
            "source_snapshot": {
                "original": original_data,
                "selected_alternative": selected_row.to_dict(),
            },
            "comparison_snapshot": {
                "engineering_matches": recommendation_points,
                "warnings": warning_points,
                "advantages": advantage_points,
                "tradeoffs": tradeoff_points,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        def _persist_decision(decision_value):
            persistent_payload = dict(decision_payload)
            persistent_payload["decision"] = decision_value
            persistent_payload["engineering_note"] = engineering_note

            try:
                saved_record = save_analysis_decision(
                    current_user["id"],
                    persistent_payload,
                )
                st.session_state["alternative_engineering_decisions"][
                    candidate_key
                ] = decision_value
                st.session_state["alternative_decision_db_status"] = ""
                st.session_state["alternative_decision_flash"] = (
                    "Engineering Decision Record created"
                )
                st.session_state["alternative_decision_db_error"] = ""
                return saved_record
            except Exception as save_error:
                st.session_state["alternative_decision_db_status"] = ""
                st.session_state["alternative_decision_db_error"] = str(save_error)
                return None

        with approve_col:
            if st.button(
                "Approve",
                use_container_width=True,
                key="af63_approve",
            ):
                if _persist_decision("Approved"):
                    st.rerun()

        with reject_col:
            if st.button(
                "Reject",
                use_container_width=True,
                key="af63_reject",
            ):
                if _persist_decision("Rejected"):
                    st.rerun()

        with save_col:
            if already_saved:
                st.markdown(
                    '<div class="af62c-db-success">✓ Saved permanently</div>',
                    unsafe_allow_html=True,
                )
            elif st.button(
                "Save Review",
                type="primary",
                use_container_width=True,
                key="af63_save",
            ):
                if _persist_decision("Saved"):
                    shortlist.append(
                        {
                            "candidate_key": candidate_key,
                            **decision_payload,
                        }
                    )
                    st.session_state["alternative_candidate_shortlist"] = shortlist
                    st.rerun()

        st.markdown(
            """
            <div style="margin:16px 0 8px;">
              <div class="af62b-analysis-title">Decision Outputs</div>
              <div class="af62b-compare-sub">Generate formal records after the engineering disposition has been recorded.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        package_output_col, json_output_col = st.columns([1, 1], gap="medium")

        with json_output_col:
            export_payload = dict(decision_payload)
            export_payload["decision"] = st.session_state.get(
                "alternative_engineering_decisions", {}
            ).get(candidate_key, "Pending review")
            safe_export_payload = {
                "original_part": export_payload.get("original_part"),
                "alternative_part": export_payload.get("alternative_part"),
                "decision": export_payload.get("decision"),
                "engineering_note": export_payload.get("engineering_note"),
                "recommendation_score": export_payload.get(
                    "recommendation_score"
                ),
                "recommendation_rating": export_payload.get(
                    "recommendation_rating"
                ),
                "compatibility_confidence": export_payload.get(
                    "compatibility_confidence"
                ),
                "compatibility_rating": export_payload.get(
                    "compatibility_rating"
                ),
                "lifecycle": export_payload.get("lifecycle"),
                "risk": export_payload.get("risk"),
                "supplier": export_payload.get("supplier"),
                "stock": export_payload.get("stock"),
                "unit_price": export_payload.get("unit_price"),
                "package": export_payload.get("package"),
                "stock_delta": export_payload.get("stock_delta"),
                "price_delta": export_payload.get("price_delta"),
                "generated_at": export_payload.get("generated_at"),
                "comparison_snapshot": export_payload.get(
                    "comparison_snapshot", {}
                ),
            }

            export_bytes = json.dumps(
                _make_json_safe(safe_export_payload),
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            st.download_button(
                "Export Decision Record",
                data=export_bytes,
                file_name=(
                    f"{str(original_part).strip()}_to_"
                    f"{str(selected_alternative).strip()}_decision.json"
                ),
                mime="application/json",
                use_container_width=True,
                key="af63_download",
            )

            st.caption("Download a structured copy of this engineering review.")

        pdf_package = generate_engineering_change_package_pdf(
            original_part=str(original_part),
            alternative_part=str(selected_alternative),
            decision=st.session_state.get(
                "alternative_engineering_decisions", {}
            ).get(candidate_key, "Pending review"),
            engineering_note=engineering_note,
            recommendation_score=recommendation_score,
            compatibility_confidence=drop_in_confidence,
            lifecycle=lifecycle_value,
            risk=risk_value,
            supplier=supplier_value,
            stock=stock_value,
            unit_price=price_value,
            package=package_value,
            stock_delta=stock_delta,
            price_delta=price_delta,
            engineer_name=decision_engineer_name,
            project_name=active_project_name,
            comparison_snapshot=decision_payload.get(
                "comparison_snapshot", {}
            ),
        )

        with package_output_col:
            st.download_button(
                "Generate Professional Change Package",
                data=pdf_package,
                file_name=(
                    f"{str(original_part).strip()}_to_"
                    f"{str(selected_alternative).strip()}_change_package.pdf"
                ),
                mime="application/pdf",
                use_container_width=True,
                key="af63_change_package",
            )
            st.caption(
                "Create a polished ECO-ready PDF with wrapped evidence, notes, sourcing impact, and next actions."
            )

        db_error = st.session_state.get("alternative_decision_db_error", "")
        decision_flash = st.session_state.get("alternative_decision_flash", "")

        if decision_flash:
            st.toast(decision_flash, icon="✅")
            st.session_state["alternative_decision_flash"] = ""

        if db_error:
            st.error(
                "The decision could not be saved to Supabase. Apply the included "
                "analysis_decisions migration, then try again. "
                f"Database message: {db_error}"
            )

        try:
            part_decision_history = load_analysis_decisions(
                current_user["id"],
                original_part=str(original_part),
                analysis_id=st.session_state.get("analysis_id"),
                limit=25,
                include_all_contexts=True,
            )
        except Exception:
            part_decision_history = []

        with st.expander(
            f"Engineering decision history for {str(original_part).strip()}",
            expanded=False,
        ):
            st.markdown(
                f"""
                <div class="af62c-history-head">
                  <div class="af62b-compare-sub">
                    Previous saved reviews for this original component.
                  </div>
                  <div class="af62c-history-count">
                    {len(part_decision_history)} records
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if not part_decision_history:
                st.info(
                    "No persistent engineering decisions have been saved for "
                    "this component yet."
                )
            else:
                history_rows = []
                for record in part_decision_history:
                    history_rows.append(
                        {
                            "Date": record.get("updated_at")
                            or record.get("created_at", ""),
                            "Decision": record.get("decision", ""),
                            "Engineer": record.get("engineer_name", "")
                            or "Cadivor user",
                            "Candidate": record.get("alternative_part", ""),
                            "Project": record.get("project_name", "")
                            or (
                                "Standalone Alternative Finder"
                                if record.get("context_key") == "standalone"
                                else record.get("context_key", "")
                            ),
                            "Original": record.get("original_part", ""),
                            "Score": record.get("recommendation_score", 0),
                            "Compatibility": record.get(
                                "compatibility_confidence", 0
                            ),
                            "Risk": record.get("risk", ""),
                            "Supplier": record.get("supplier", ""),
                            "Note": record.get("engineering_note", ""),
                        }
                    )

                st.dataframe(
                    pd.DataFrame(history_rows),
                    use_container_width=True,
                    hide_index=True,
                )

                decision_options = {
                    (
                        f'{record.get("alternative_part", "Unknown")} — '
                        f'{record.get("decision", "Saved")} — '
                        f'{record.get("updated_at") or record.get("created_at", "")}'
                    ): record.get("id")
                    for record in part_decision_history
                    if record.get("id")
                }

                if decision_options:
                    archive_label = st.selectbox(
                        "Select a decision record to archive",
                        list(decision_options.keys()),
                        key="af62c_archive_select",
                    )
                    if st.button(
                        "Archive Decision",
                        type="secondary",
                        key="af62c_archive",
                    ):
                        try:
                            archive_analysis_decision(
                                current_user["id"],
                                decision_options[archive_label],
                            )
                            st.session_state["alternative_decision_flash"] = (
                                "Engineering Decision Record archived"
                            )
                            st.session_state["alternative_decision_db_error"] = ""
                            st.rerun()
                        except Exception as archive_error:
                            st.error(
                                f"Could not archive the decision: {archive_error}"
                            )

        with st.expander(
            f"View all {len(alternatives_df)} ranked alternatives",
            expanded=False,
        ):
            st.dataframe(
                alternatives_df,
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("Advanced multi-part comparison", expanded=False):
            st.markdown(
                '<div class="af62b-advanced-copy">'
                'Compare the original component against multiple candidates when the '
                'ranked recommendation needs a broader sourcing or engineering review.'
                '</div>',
                unsafe_allow_html=True,
            )

            advanced_input = st.text_input(
                "Alternative part numbers",
                value=", ".join(alternative_options),
                help="Enter comma-separated manufacturer part numbers.",
                key="af62b_advanced_input",
            )

            if st.button(
                "Run Advanced Comparison",
                type="secondary",
                key="af62b_advanced_compare",
            ):
                advanced_parts = [
                    part.strip()
                    for part in advanced_input.split(",")
                    if part.strip()
                ]

                if not advanced_parts:
                    st.warning("Enter at least one alternative part number.")
                elif not original_part:
                    st.warning("Enter a valid original part number.")
                else:
                    with st.spinner(
                        "Comparing supplier, lifecycle, stock, and risk signals..."
                    ):
                        advanced_df = compare_parts(
                            original_part,
                            advanced_parts,
                        )

                    if advanced_df is None or advanced_df.empty:
                        st.warning("No comparison data was returned.")
                    else:
                        def _af62b_risk_badge(level):
                            if level == "High":
                                return "🔴 High"
                            if level == "Medium":
                                return "🟡 Medium"
                            return "🟢 Low"

                        if "Risk Level" in advanced_df.columns:
                            advanced_df["Risk Level Display"] = (
                                advanced_df["Risk Level"].apply(
                                    _af62b_risk_badge
                                )
                            )

                        sort_columns = [
                            column
                            for column in [
                                "Risk Score",
                                "Total Market Stock",
                            ]
                            if column in advanced_df.columns
                        ]
                        if sort_columns:
                            ascending = [
                                column == "Risk Score"
                                for column in sort_columns
                            ]
                            advanced_df = advanced_df.sort_values(
                                by=sort_columns,
                                ascending=ascending,
                            )

                        preferred_columns = [
                            "Role",
                            "MPN Searched",
                            "Manufacturer",
                            "Best Source",
                            "Supplier Count",
                            "Total Market Stock",
                            "Lifecycle Status",
                            "Risk Score",
                            "Risk Level Display",
                            "Product URL",
                        ]
                        display_columns = [
                            column
                            for column in preferred_columns
                            if column in advanced_df.columns
                        ]

                        st.dataframe(
                            advanced_df[display_columns]
                            if display_columns
                            else advanced_df,
                            use_container_width=True,
                            hide_index=True,
                        )

                        csv = advanced_df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "Download Advanced Comparison CSV",
                            data=csv,
                            file_name="alternative_comparison.csv",
                            mime="text/csv",
                            key="af62b_advanced_download",
                        )

        # Milestone 7.0.1 — safe Alternative Finder reset callback
        def _reset_alternative_search():
            """Clear the Alternative Finder before its widgets are recreated."""
            st.session_state["suggested_alternatives"] = []
            st.session_state["alternative_search_attempted"] = False
            st.session_state["alternative_original_data"] = {}
            st.session_state["alternative_original_risk"] = {}
            st.session_state["alternative_original_lookup_part"] = ""
            st.session_state["alternative_original_lookup_error"] = ""
            st.session_state["alternative_original_part"] = ""
            st.session_state["alternative_engineering_decisions"] = {}
            st.session_state["alternative_decision_notes"] = {}

            # Clear selection and comparison state from the previous result set.
            for state_key in (
                "alternative_selected_candidate",
                "alternative_compare_parts",
                "alternative_advanced_parts",
                "alternative_decision_db_status",
                "alternative_decision_db_error",
                "alternative_decision_flash",
            ):
                st.session_state.pop(state_key, None)

        reset_col, note_col = st.columns([0.28, 0.72], gap="medium")
        with reset_col:
            st.button(
                "New Alternative Search",
                type="secondary",
                use_container_width=True,
                key="alternative_reset_62b",
                on_click=_reset_alternative_search,
            )
        with note_col:
            st.markdown(
                '<div class="af62b-reset-note">The detailed alternative library is collapsed by default so engineers can focus on the strongest recommendation first.</div>',
                unsafe_allow_html=True,
            )

    elif st.session_state["alternative_search_attempted"]:
        st.warning("No suggested alternatives found.")

    st.stop()
if app_mode == "BOM Analyzer":

    st.markdown(
        """
        <style id="cadivor-bom-intelligence-v1">
        .bom8-hero{
            border:1px solid #b9d4ff;
            border-radius:24px;
            padding:26px 28px;
            margin-bottom:22px;
            background:
                radial-gradient(circle at 95% 5%,rgba(37,99,235,.15),transparent 34%),
                linear-gradient(135deg,#ffffff 0%,#f8fbff 100%);
            box-shadow:0 18px 46px rgba(15,23,42,.07);
        }
        .bom8-eyebrow{
            display:inline-flex;
            align-items:center;
            gap:8px;
            border:1px solid #bfdbfe;
            border-radius:999px;
            padding:7px 11px;
            color:#2563eb;
            background:#eff6ff;
            font-size:10px;
            font-weight:900;
            letter-spacing:.11em;
            text-transform:uppercase;
            margin-bottom:14px;
        }
        .bom8-hero h1{
            color:#0f172a;
            font-size:34px;
            line-height:1.08;
            letter-spacing:-.035em;
            margin:0 0 10px;
            font-weight:900;
        }
        .bom8-hero p{
            color:#52647c;
            font-size:15px;
            line-height:1.58;
            margin:0;
            max-width:900px;
            font-weight:600;
        }
        .bom8-kpis{
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:12px;
            margin:0 0 24px;
        }
        .bom8-kpi{
            border:1px solid #dbe3ef;
            border-radius:18px;
            background:#fff;
            padding:17px 18px;
            min-height:112px;
            box-shadow:0 12px 30px rgba(15,23,42,.045);
        }
        .bom8-kpi-label{
            color:#64748b;
            font-size:9px;
            font-weight:900;
            letter-spacing:.10em;
            text-transform:uppercase;
            margin-bottom:8px;
        }
        .bom8-kpi-value{
            color:#0f172a;
            font-size:29px;
            line-height:1;
            font-weight:900;
            margin-bottom:8px;
        }
        .bom8-kpi-note{
            color:#64748b;
            font-size:11px;
            line-height:1.4;
            font-weight:650;
        }
        .bom8-section-head{
            display:flex;
            align-items:flex-end;
            justify-content:space-between;
            gap:18px;
            margin:4px 0 12px;
        }
        .bom8-section-head h2{
            color:#0f172a;
            font-size:22px;
            margin:0 0 4px;
            letter-spacing:-.025em;
        }
        .bom8-section-head p{
            color:#64748b;
            font-size:12px;
            margin:0;
            font-weight:650;
        }
        .bom8-upload-card{
            border:1px solid #d8e1ed;
            border-radius:22px;
            background:#fff;
            padding:22px 24px;
            box-shadow:0 16px 38px rgba(15,23,42,.055);
            min-height:100%;
        }
        .bom8-upload-title{
            color:#0f172a;
            font-size:20px;
            font-weight:900;
            margin-bottom:5px;
        }
        .bom8-upload-copy{
            color:#64748b;
            font-size:12px;
            line-height:1.5;
            margin-bottom:14px;
            font-weight:600;
        }
        .bom8-checklist{
            display:grid;
            gap:10px;
            margin-top:10px;
        }
        .bom8-check{
            display:flex;
            gap:10px;
            align-items:flex-start;
            border:1px solid #e2e8f0;
            border-radius:14px;
            padding:12px 13px;
            background:#f8fafc;
        }
        .bom8-check-icon{
            flex:0 0 24px;
            width:24px;
            height:24px;
            border-radius:8px;
            display:flex;
            align-items:center;
            justify-content:center;
            background:#ecfdf5;
            border:1px solid #a7f3d0;
            color:#059669;
            font-size:12px;
            font-weight:900;
        }
        .bom8-check strong{
            display:block;
            color:#0f172a;
            font-size:12px;
            margin-bottom:2px;
        }
        .bom8-check span{
            display:block;
            color:#64748b;
            font-size:10.5px;
            line-height:1.4;
        }
        .bom8-trust-strip{
            display:grid;
            grid-template-columns:repeat(3,minmax(0,1fr));
            gap:10px;
            margin-top:14px;
        }
        .bom8-trust{
            border:1px solid #dbeafe;
            border-radius:13px;
            background:#eff6ff;
            padding:10px 11px;
            color:#1e3a8a;
            font-size:10px;
            font-weight:800;
            text-align:center;
        }
        .bom8-history-note{
            border:1px solid #dbe3ef;
            border-radius:16px;
            background:#fff;
            padding:13px 15px;
            color:#52647c;
            font-size:11px;
            line-height:1.45;
            margin-top:8px;
        }
        .st-key-bom8_saved_history{
            margin-top:18px;
            margin-bottom:8px;
        }
        .st-key-bom8_saved_history details{
            border:1px solid #dbe3ef!important;
            border-radius:16px!important;
            background:#ffffff!important;
            box-shadow:0 10px 26px rgba(15,23,42,.04);
        }
        .st-key-bom8_saved_history summary{
            color:#1d4ed8!important;
            font-weight:850!important;
        }
        .bom8-saved-summary{
            display:grid;
            grid-template-columns:1.2fr 1.2fr .55fr .75fr;
            gap:10px;
            margin:14px 0;
        }
        .bom8-saved-summary > div{
            border:1px solid #dbe3ef;
            border-radius:14px;
            background:#f8fafc;
            padding:12px 13px;
        }
        .bom8-saved-summary span{
            display:block;
            color:#64748b;
            font-size:9px;
            font-weight:900;
            letter-spacing:.09em;
            text-transform:uppercase;
            margin-bottom:6px;
        }
        .bom8-saved-summary strong{
            display:block;
            color:#0f172a;
            font-size:12px;
            line-height:1.35;
            overflow-wrap:anywhere;
        }
        .st-key-bom8_delete_saved_analysis button{
            border:1px solid #fecaca!important;
            background:#fff!important;
            color:#b91c1c!important;
            font-weight:850!important;
        }
        .bom8-delete-confirmation{
            display:flex;
            gap:12px;
            align-items:flex-start;
            border:1px solid #fecaca;
            border-radius:16px;
            background:#fff7f7;
            padding:14px 15px;
            margin:14px 0 10px;
        }
        .bom8-delete-icon{
            flex:0 0 28px;
            width:28px;
            height:28px;
            border-radius:9px;
            display:flex;
            align-items:center;
            justify-content:center;
            background:#fee2e2;
            border:1px solid #fecaca;
            color:#b91c1c;
            font-weight:900;
        }
        .bom8-delete-confirmation strong{
            display:block;
            color:#991b1b;
            font-size:13px;
            margin-bottom:4px;
        }
        .bom8-delete-confirmation p{
            margin:0;
            color:#7f1d1d;
            font-size:11px;
            line-height:1.5;
        }
        .st-key-bom8_confirm_permanent_delete button{
            border:1px solid #dc2626!important;
            background:#dc2626!important;
            color:#fff!important;
            font-weight:850!important;
        }
        .st-key-bom8_cancel_delete_analysis button{
            border:1px solid #cbd5e1!important;
            background:#fff!important;
            color:#334155!important;
            font-weight:800!important;
        }
        .st-key-bom81_saved_manager{
            margin-top:18px;
            margin-bottom:10px;
        }
        .st-key-bom81_saved_manager details{
            border:1px solid #dbe3ef!important;
            border-radius:18px!important;
            background:#fff!important;
            box-shadow:0 12px 30px rgba(15,23,42,.045);
        }
        .st-key-bom81_saved_manager summary{
            color:#1d4ed8!important;
            font-weight:900!important;
        }
        .bom81-selection-status{
            display:inline-flex;
            align-items:center;
            gap:6px;
            margin:10px 0 12px;
            border:1px solid #bfdbfe;
            background:#eff6ff;
            color:#1e40af;
            border-radius:999px;
            padding:7px 11px;
            font-size:11px;
            font-weight:800;
        }
        .bom81-selection-status strong{
            font-size:13px;
        }
        .bom81-selection-status span{
            color:#475569;
            font-size:10.5px;
            font-weight:750;
            margin-left:3px;
        }
        .st-key-bom81_request_bulk_delete button{
            border:1px solid #fecaca!important;
            background:#fff!important;
            color:#b91c1c!important;
            font-weight:850!important;
        }
        .bom81-delete-confirmation{
            display:flex;
            gap:13px;
            align-items:flex-start;
            border:1px solid #fecaca;
            border-radius:17px;
            background:#fff7f7;
            padding:15px 16px;
            margin:15px 0 11px;
        }
        .bom81-delete-icon{
            flex:0 0 30px;
            width:30px;
            height:30px;
            border-radius:9px;
            display:flex;
            align-items:center;
            justify-content:center;
            background:#fee2e2;
            border:1px solid #fecaca;
            color:#b91c1c;
            font-weight:900;
        }
        .bom81-delete-confirmation strong{
            display:block;
            color:#991b1b;
            font-size:13px;
            margin-bottom:5px;
        }
        .bom81-delete-confirmation p,
        .bom81-delete-confirmation li{
            color:#7f1d1d;
            font-size:11px;
            line-height:1.5;
        }
        .bom81-delete-confirmation p{
            margin:0 0 6px;
        }
        .bom81-delete-confirmation ul{
            margin:4px 0 0 18px;
            padding:0;
        }
        .st-key-bom81_confirm_bulk_delete button{
            border:1px solid #dc2626!important;
            background:#dc2626!important;
            color:#fff!important;
            font-weight:850!important;
        }
        .st-key-bom81_cancel_bulk_delete button,
        .st-key-bom81_clear_selection button{
            border:1px solid #cbd5e1!important;
            background:#fff!important;
            color:#334155!important;
            font-weight:800!important;
        }
        @media(max-width:900px){
            .bom8-saved-summary{grid-template-columns:1fr 1fr;}
        }
        @media(max-width:620px){
            .bom8-saved-summary{grid-template-columns:1fr;}
        }
        .st-key-bom8_sample button{
            border:1px solid #bfdbfe!important;
            background:#eff6ff!important;
            color:#1d4ed8!important;
            font-weight:800!important;
        }
        .st-key-bom_file_uploader [data-testid="stFileUploader"]{
            border-radius:16px!important;
        }
        @media(max-width:1100px){
            .bom8-kpis{grid-template-columns:repeat(2,minmax(0,1fr));}
        }
        @media(max-width:720px){
            .bom8-kpis,.bom8-trust-strip{grid-template-columns:1fr;}
            .bom8-hero{padding:22px 20px;}
            .bom8-hero h1{font-size:28px;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    history_data = load_analysis_history(current_user["id"]) or []
    history_df = pd.DataFrame(history_data)

    if not history_df.empty:
        if "project_name" not in history_df.columns:
            history_df["project_name"] = history_df.get("filename", "Saved analysis")

        numeric_defaults = {
            "health_score": 0,
            "high_risk_count": 0,
            "medium_risk_count": 0,
        }
        for column_name, default_value in numeric_defaults.items():
            if column_name not in history_df.columns:
                history_df[column_name] = default_value
            history_df[column_name] = pd.to_numeric(
                history_df[column_name], errors="coerce"
            ).fillna(default_value)

        saved_analysis_count = int(len(history_df))
        average_health = int(round(history_df["health_score"].mean()))
        total_high_risk = int(history_df["high_risk_count"].sum())
        best_health = int(history_df["health_score"].max())
    else:
        saved_analysis_count = 0
        average_health = 0
        total_high_risk = 0
        best_health = 0

    st.markdown(
        f"""
        <section class="bom8-hero">
          <div class="bom8-eyebrow">BOM intelligence workspace</div>
          <h1>Turn a parts list into an engineering risk decision.</h1>
          <p>
            Upload a CSV or Excel BOM to evaluate lifecycle exposure, sourcing risk,
            component availability, and portfolio health. Cadivor converts the file
            into a prioritized engineering review rather than another raw spreadsheet.
          </p>
        </section>

        <section class="bom8-kpis">
          <div class="bom8-kpi">
            <div class="bom8-kpi-label">Saved analyses</div>
            <div class="bom8-kpi-value">{saved_analysis_count}</div>
            <div class="bom8-kpi-note">Previous BOM engineering reviews</div>
          </div>
          <div class="bom8-kpi">
            <div class="bom8-kpi-label">Average health</div>
            <div class="bom8-kpi-value">{average_health}</div>
            <div class="bom8-kpi-note">Across all saved analyses</div>
          </div>
          <div class="bom8-kpi">
            <div class="bom8-kpi-label">High-risk findings</div>
            <div class="bom8-kpi-value">{total_high_risk}</div>
            <div class="bom8-kpi-note">Components requiring engineering review</div>
          </div>
          <div class="bom8-kpi">
            <div class="bom8-kpi-label">Best recorded health</div>
            <div class="bom8-kpi-value">{best_health}</div>
            <div class="bom8-kpi-note">Highest-performing saved BOM</div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="bom8-section-head">
          <div>
            <h2>Start a new BOM analysis</h2>
            <p>Prepare the project, confirm the expected columns, and upload the source file.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    input_col, guidance_col = st.columns([0.64, 0.36], gap="large")

    with input_col:
        st.markdown(
            """
            <div class="bom8-upload-card">
              <div class="bom8-upload-title">Upload engineering BOM</div>
              <div class="bom8-upload-copy">
                Give the analysis a recognizable project or revision name, then select
                the CSV or Excel file used by your engineering or sourcing team.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        project_name = st.text_input(
            "Project / BOM Name",
            placeholder="Example: Motor Controller Rev A",
            key="bom8_project_name",
        )

        sample_bom = pd.DataFrame(
            {
                "mpn": ["TPS5430DDAR", "LM555CN/NOPB"],
                "quantity": [5, 2],
            }
        )
        sample_csv = sample_bom.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Download Sample BOM Template",
            data=sample_csv,
            file_name="sample_bom_template.csv",
            mime="text/csv",
            key="bom8_sample",
        )

        uploaded_file = st.file_uploader(
            "Upload your BOM file",
            type=["csv", "xlsx"],
            key="bom_file_uploader",
            help="Cadivor accepts CSV and XLSX files up to the Streamlit upload limit.",
        )

        st.markdown(
            """
            <div class="bom8-trust-strip">
              <div class="bom8-trust">CSV/XLSX files accepted</div>
              <div class="bom8-trust">Duplicate part numbers combined</div>
              <div class="bom8-trust">Lifecycle and sourcing risk scored</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with guidance_col:
        st.markdown(
            """
            <div class="bom8-upload-card">
              <div class="bom8-upload-title">File readiness</div>
              <div class="bom8-upload-copy">
                A clean source file creates a stronger and more defensible analysis.
              </div>
              <div class="bom8-checklist">
                <div class="bom8-check">
                  <div class="bom8-check-icon">1</div>
                  <div>
                    <strong>Manufacturer part number</strong>
                    <span>Include an <b>mpn</b> column or a recognized part-number equivalent.</span>
                  </div>
                </div>
                <div class="bom8-check">
                  <div class="bom8-check-icon">2</div>
                  <div>
                    <strong>Quantity</strong>
                    <span>Include a numeric <b>quantity</b> or <b>qty</b> column.</span>
                  </div>
                </div>
                <div class="bom8-check">
                  <div class="bom8-check-icon">3</div>
                  <div>
                    <strong>One BOM revision</strong>
                    <span>Use a project name that identifies the board and revision.</span>
                  </div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Milestone 8.1 — Saved BOM Manager
    with st.container(key="bom81_saved_manager"):
        with st.expander(
            f"Saved BOM Manager ({saved_analysis_count})",
            expanded=False,
        ):
            st.caption(
                "Search, sort, open, or select multiple analyses for bulk deletion. "
                "Check the box in the first column to select a record."
            )

            if history_data:
                manager_df = pd.DataFrame(history_data).copy()

                required_defaults = {
                    "id": "",
                    "project_name": "Saved BOM analysis",
                    "filename": "—",
                    "health_score": 0,
                    "high_risk_count": 0,
                    "medium_risk_count": 0,
                    "created_at": pd.NaT,
                }
                for column_name, default_value in required_defaults.items():
                    if column_name not in manager_df.columns:
                        manager_df[column_name] = default_value

                manager_df["project_name"] = manager_df["project_name"].fillna(
                    manager_df["filename"]
                )
                manager_df["project_name"] = manager_df["project_name"].fillna(
                    "Saved BOM analysis"
                )
                manager_df["filename"] = manager_df["filename"].fillna("—")

                for numeric_column in (
                    "health_score",
                    "high_risk_count",
                    "medium_risk_count",
                ):
                    manager_df[numeric_column] = pd.to_numeric(
                        manager_df[numeric_column],
                        errors="coerce",
                    ).fillna(0).astype(int)

                manager_df["created_at_sort"] = pd.to_datetime(
                    manager_df["created_at"],
                    errors="coerce",
                    utc=True,
                )
                manager_df["Date"] = manager_df["created_at_sort"].dt.strftime(
                    "%Y-%m-%d"
                ).fillna("—")

                filter_col, sort_col = st.columns([0.68, 0.32], gap="medium")

                with filter_col:
                    manager_search = st.text_input(
                        "Search saved analyses",
                        placeholder="Search by project or source filename",
                        key="bom81_manager_search",
                    )

                with sort_col:
                    manager_sort = st.selectbox(
                        "Sort analyses",
                        options=[
                            "Newest first",
                            "Oldest first",
                            "Health: high to low",
                            "Health: low to high",
                            "High risk: high to low",
                            "Project name",
                        ],
                        key="bom81_manager_sort",
                    )

                if manager_search.strip():
                    search_value = manager_search.strip().lower()
                    manager_df = manager_df[
                        manager_df["project_name"]
                        .astype(str)
                        .str.lower()
                        .str.contains(search_value, na=False)
                        | manager_df["filename"]
                        .astype(str)
                        .str.lower()
                        .str.contains(search_value, na=False)
                    ]

                if manager_sort == "Newest first":
                    manager_df = manager_df.sort_values(
                        "created_at_sort",
                        ascending=False,
                        na_position="last",
                    )
                elif manager_sort == "Oldest first":
                    manager_df = manager_df.sort_values(
                        "created_at_sort",
                        ascending=True,
                        na_position="last",
                    )
                elif manager_sort == "Health: high to low":
                    manager_df = manager_df.sort_values(
                        "health_score",
                        ascending=False,
                    )
                elif manager_sort == "Health: low to high":
                    manager_df = manager_df.sort_values(
                        "health_score",
                        ascending=True,
                    )
                elif manager_sort == "High risk: high to low":
                    manager_df = manager_df.sort_values(
                        "high_risk_count",
                        ascending=False,
                    )
                else:
                    manager_df = manager_df.sort_values(
                        "project_name",
                        ascending=True,
                    )

                if manager_df.empty:
                    st.info("No saved analyses match the current search.")
                else:
                    current_selection = set(
                        st.session_state.get("bom81_selected_analysis_ids", [])
                    )

                    editor_df = pd.DataFrame(
                        {
                            "Select": manager_df["id"]
                            .astype(str)
                            .isin(current_selection),
                            "Project": manager_df["project_name"].astype(str),
                            "Source File": manager_df["filename"].astype(str),
                            "Health": manager_df["health_score"],
                            "High Risk": manager_df["high_risk_count"],
                            "Medium Risk": manager_df["medium_risk_count"],
                            "Date": manager_df["Date"],
                            "_analysis_id": manager_df["id"].astype(str),
                        }
                    ).reset_index(drop=True)

                    edited_manager = st.data_editor(
                        editor_df,
                        use_container_width=True,
                        hide_index=True,
                        height=min(520, 70 + len(editor_df) * 35),
                        disabled=[
                            "Project",
                            "Source File",
                            "Health",
                            "High Risk",
                            "Medium Risk",
                            "Date",
                            "_analysis_id",
                        ],
                        column_config={
                            "Select": st.column_config.CheckboxColumn(
                                "Select",
                                help="Select one analysis to open or several analyses to delete.",
                                width="small",
                            ),
                            "Project": st.column_config.TextColumn(
                                "Project",
                                width="large",
                            ),
                            "Source File": st.column_config.TextColumn(
                                "Source File",
                                width="medium",
                            ),
                            "Health": st.column_config.NumberColumn(
                                "Health",
                                min_value=0,
                                max_value=100,
                                format="%d",
                                width="small",
                            ),
                            "High Risk": st.column_config.NumberColumn(
                                "High Risk",
                                format="%d",
                                width="small",
                            ),
                            "Medium Risk": st.column_config.NumberColumn(
                                "Medium Risk",
                                format="%d",
                                width="small",
                            ),
                            "Date": st.column_config.TextColumn(
                                "Date",
                                width="small",
                            ),
                            "_analysis_id": None,
                        },
                        key="bom81_saved_analysis_editor",
                    )

                    selected_rows = edited_manager[
                        edited_manager["Select"] == True
                    ]
                    selected_ids = selected_rows["_analysis_id"].astype(str).tolist()
                    st.session_state["bom81_selected_analysis_ids"] = selected_ids

                    selected_count = len(selected_ids)

                    selection_copy = (
                        "Select one checkbox to enable Open Analysis."
                        if selected_count == 0
                        else "One analysis selected. Open Analysis is ready."
                        if selected_count == 1
                        else "Multiple analyses selected. Use bulk delete or clear the selection; analyses open one at a time."
                    )
                    st.markdown(
                        f"""
                        <div class="bom81-selection-status">
                          <strong>{selected_count}</strong>
                          analysis{"es" if selected_count != 1 else ""} selected
                          <span>{html.escape(selection_copy)}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    open_col, delete_col, clear_col = st.columns(
                        [0.34, 0.34, 0.32],
                        gap="medium",
                    )

                    with open_col:
                        if st.button(
                            "Open Selected Analysis" if selected_count == 1 else "Open Analysis (select 1)",
                            type="primary",
                            use_container_width=True,
                            disabled=selected_count != 1,
                            key="bom81_open_selected",
                        ):
                            selected_saved_id = selected_ids[0]
                            st.query_params["page"] = "Analysis Details"
                            st.query_params["analysis_id"] = selected_saved_id
                            st.session_state["pending_app_mode"] = "Analysis Details"
                            st.rerun()

                    with delete_col:
                        if st.button(
                            f"Delete Selected ({selected_count})",
                            type="secondary",
                            use_container_width=True,
                            disabled=selected_count == 0,
                            key="bom81_request_bulk_delete",
                        ):
                            st.session_state["bom81_pending_delete_ids"] = selected_ids
                            st.rerun()

                    with clear_col:
                        if st.button(
                            "Clear Selection",
                            use_container_width=True,
                            disabled=selected_count == 0,
                            key="bom81_clear_selection",
                        ):
                            st.session_state["bom81_selected_analysis_ids"] = []
                            st.session_state.pop("bom81_pending_delete_ids", None)
                            st.rerun()

                    pending_delete_ids = [
                        str(value)
                        for value in st.session_state.get(
                            "bom81_pending_delete_ids",
                            [],
                        )
                        if str(value).strip()
                    ]

                    if pending_delete_ids:
                        delete_records = manager_df[
                            manager_df["id"].astype(str).isin(pending_delete_ids)
                        ]
                        delete_names = delete_records["project_name"].astype(str).tolist()
                        preview_names = delete_names[:5]
                        remaining_names = max(0, len(delete_names) - len(preview_names))

                        name_lines = "".join(
                            f"<li>{html.escape(name)}</li>"
                            for name in preview_names
                        )
                        if remaining_names:
                            name_lines += (
                                f"<li>and {remaining_names} more "
                                f"analysis{'es' if remaining_names != 1 else ''}</li>"
                            )

                        st.markdown(
                            f"""
                            <div class="bom81-delete-confirmation">
                              <div class="bom81-delete-icon">!</div>
                              <div>
                                <strong>Permanently delete {len(pending_delete_ids)}
                                saved BOM analysis{"es" if len(pending_delete_ids) != 1 else ""}?</strong>
                                <p>
                                  All saved component records associated with these
                                  analyses will also be removed. This action cannot be undone.
                                </p>
                                <ul>{name_lines}</ul>
                              </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        confirm_col, cancel_col = st.columns(
                            [0.5, 0.5],
                            gap="medium",
                        )

                        with confirm_col:
                            if st.button(
                                f"Yes, Delete {len(pending_delete_ids)} Permanently",
                                type="primary",
                                use_container_width=True,
                                key="bom81_confirm_bulk_delete",
                            ):
                                deletion_errors = []

                                for analysis_id_value in pending_delete_ids:
                                    try:
                                        supabase.table("analysis_parts").delete().eq(
                                            "analysis_id",
                                            analysis_id_value,
                                        ).execute()

                                        try:
                                            supabase.table(
                                                "part_monitor_history"
                                            ).delete().eq(
                                                "analysis_id",
                                                analysis_id_value,
                                            ).execute()
                                        except Exception:
                                            pass

                                        supabase.table("analyses").delete().eq(
                                            "id",
                                            analysis_id_value,
                                        ).eq(
                                            "user_id",
                                            current_user["id"],
                                        ).execute()
                                    except Exception as deletion_error:
                                        deletion_errors.append(
                                            f"{analysis_id_value}: {deletion_error}"
                                        )

                                st.session_state["bom81_selected_analysis_ids"] = []
                                st.session_state.pop(
                                    "bom81_pending_delete_ids",
                                    None,
                                )

                                if deletion_errors:
                                    st.error(
                                        "Some analyses could not be deleted. "
                                        + " | ".join(deletion_errors[:3])
                                    )
                                else:
                                    st.success(
                                        f"{len(pending_delete_ids)} saved BOM "
                                        f"analysis{'es' if len(pending_delete_ids) != 1 else ''} "
                                        "permanently deleted."
                                    )
                                    st.rerun()

                        with cancel_col:
                            if st.button(
                                "Cancel",
                                use_container_width=True,
                                key="bom81_cancel_bulk_delete",
                            ):
                                st.session_state.pop(
                                    "bom81_pending_delete_ids",
                                    None,
                                )
                                st.rerun()

                    st.caption(
                        "Opening is a single-analysis action. Select exactly one row to open it. "
                        "Selecting two or more rows does not open them together; it enables bulk deletion. "
                        "The table is read-only except for the selection checkboxes."
                    )
            else:
                st.markdown(
                    """
                    <div class="bom8-history-note">
                      No saved analyses yet. Your first completed BOM review will
                      appear here with its health score and risk distribution.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )



    if uploaded_file is None:
        st.info("Upload a CSV or Excel BOM to begin.")
        st.stop()

    if not project_name.strip():
        st.warning("Please enter a Project / BOM Name before analyzing")
        st.stop()

    try:
        if uploaded_file.name.endswith(".csv"):
            bom_df = pd.read_csv(uploaded_file)
        else:
            bom_df = pd.read_excel(uploaded_file)

    except Exception as e:
        st.error(
            f"Could not read the uploaded BOM file: {e}"
        )
        st.stop()

    column_rename_map = {
        "part number": "mpn",
        "part_number": "mpn",
        "manufacturer part number": "mpn",
        "manufacturer_part_number": "mpn",
        "qty": "quantity",
    }

    bom_df.columns = [
        col.strip().lower()
        for col in bom_df.columns
    ]

    bom_df.rename(
        columns=column_rename_map,
        inplace=True,
    )

    required_columns = ["mpn", "quantity"]

    normalized_columns = [
        col.strip().lower().replace(" ", "_")
        for col in bom_df.columns
    ]

    missing_columns = [
        col for col in required_columns
        if col not in normalized_columns
    ]

    if missing_columns:
        st.error(
            "Your BOM is missing required columns: "
            + ", ".join(missing_columns)
            + ". Please include at least MPN and Quantity columns."
        )
        st.stop()

    if bom_df.empty:
        st.error("The uploaded BOM file is empty.")
        st.stop()

    if len(bom_df) == 0:
        st.error("No BOM rows were detected in the uploaded file.")
        st.stop()

    


    if st.session_state.get("uploaded_filename") != uploaded_file.name:
        st.session_state.pop("results_df", None)
        st.session_state["uploaded_filename"] = uploaded_file.name

    
    original_row_count = len(bom_df)

    bom_df["mpn"] = bom_df["mpn"].astype(str).str.strip()

    bom_df = (
        bom_df.groupby("mpn", as_index=False)
        .agg({
            "quantity": "sum"
        })
    )

    deduped_row_count = len(bom_df)

    if deduped_row_count < original_row_count:
        st.info(
            f"Duplicate part numbers were merged: {original_row_count} rows reduced to {deduped_row_count} unique parts."
        )

    bom_df["quantity"] = pd.to_numeric(
        bom_df["quantity"],
        errors="coerce",
    )

    if bom_df["quantity"].isna().any():
        st.error("Some quantity values are missing or invalid. Please use numeric quantities only.")
        st.stop()

    if (bom_df["quantity"] <= 0).any():
        st.error("Quantity values must be greater than zero.")
        st.stop()

    st.subheader("Uploaded BOM Preview")
    st.data_editor(
        bom_df,
        use_container_width=True,
        hide_index=True,
    )


    if st.button("Analyze BOM", type="primary"):
        with st.spinner("Analyzing BOM and checking supplier risk..."):
            # A new analysis should be saved as a new database record.
            # These flags prevent old session state from blocking the new save.
            st.session_state.pop("analysis_saved", None)
            st.session_state.pop("analysis_id", None)
            st.session_state.pop("health_score", None)
            st.session_state.pop("health_status", None)

            if is_admin:
                allowed = True
                message = "Admin account: plan limits bypassed."
            else:
                allowed, message = validate_bom_against_plan(
                    bom_df,
                    selected_plan,
                    monthly_upload_count,
                )

            if not allowed:
                upgrade_plan = selected_plan.get("upgrade_to")

                st.session_state["show_upgrade_checkout"] = True
                st.session_state["upgrade_message"] = message
                st.session_state["upgrade_plan_name"] = upgrade_plan

                # Rerun so the persistent upgrade checkout section below can render.
                # Using st.stop() here would show the text but prevent the button from appearing.
                st.rerun()

            saved_analysis_count = (
                _workspace_query(
                    supabase.table("analyses")
                    .select("id", count="exact")
                )
                .eq("user_id", current_user["id"])
                .execute()
            )

            saved_analysis_total = saved_analysis_count.count or 0
            max_saved_boms = selected_plan.get("max_saved_boms", 0)

            if not is_admin and saved_analysis_total >= max_saved_boms:
                st.error(
                    f"You have reached your saved BOM limit ({max_saved_boms}) for the {selected_plan_name} plan. "
                    "Please delete an existing BOM analysis or upgrade your plan."
                )
                st.stop()

            st.success(message)

            try:
                progress_status = st.empty()
                progress_bar = st.progress(0)

                st.session_state["results_df"] = analyze_bom(
                    bom_df,
                    progress_status=progress_status,
                    progress_bar=progress_bar,
                )

                progress_status.success("BOM analysis completed successfully.")
                progress_bar.progress(1.0)

                # If analysis succeeds, hide any old checkout prompt from a previous blocked attempt.
                st.session_state.pop("show_upgrade_checkout", None)
                st.session_state.pop("checkout_url", None)
                st.session_state.pop("upgrade_message", None)
                st.session_state.pop("upgrade_plan_name", None)

            except Exception as e:
                st.error(f"BOM analysis failed unexpectedly: {e}")
                st.stop()

            results_df = st.session_state["results_df"]

    if st.session_state.get("show_upgrade_checkout"):
        upgrade_message = st.session_state.get(
            "upgrade_message",
            "Your current plan limit has been reached.",
        )

        upgrade_plan = st.session_state.get("upgrade_plan_name")
        next_plan = get_plan(upgrade_plan) if upgrade_plan else None

        st.error(upgrade_message)

        if upgrade_plan and next_plan:
            st.markdown(
                f"""
---
### 🚀 Upgrade to **{upgrade_plan}** ({next_plan['price']})

Unlock more power:

- 🔍 Analyze up to **{next_plan['monthly_bom_limit']} BOMs/month**
- 📦 Handle up to **{next_plan['max_parts_per_bom']} parts per BOM**
- 🌐 Multi-supplier intelligence (Mouser + DigiKey)
- ⚡ Faster sourcing decisions

👉 Upgrade now to continue your analysis
---
"""
            )

            if st.button(f"🚀 Upgrade to {upgrade_plan}", key="upgrade_button_main"):
                try:
                    checkout_url = create_checkout_session(
                        st.secrets["STRIPE_PRO_PRICE_ID"],
                        current_user["email"],
                        current_user["id"],
                        success_url="https://bom-risk-checker-j9co3yumwgvqjumut24fxm.streamlit.app/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
                        cancel_url="https://bom-risk-checker-j9co3yumwgvqjumut24fxm.streamlit.app/?checkout=cancel",
                    )

                    st.session_state["checkout_url"] = checkout_url

                except Exception as e:
                    st.error(f"Unable to create checkout session: {e}")

            if "checkout_url" in st.session_state:
                st.link_button(
                    "Continue to Stripe Checkout",
                    st.session_state["checkout_url"],
                )

        else:
            st.info("No upgrade plan is configured for your current subscription.")

    if "results_df" in st.session_state:
        results_df = st.session_state["results_df"]

        if not st.session_state.get("analysis_saved", False):
            high_count = len(results_df[results_df["Risk Level"] == "High"])
            medium_count = len(results_df[results_df["Risk Level"] == "Medium"])
            low_count = len(results_df[results_df["Risk Level"] == "Low"])
            total_parts = len(results_df)

            health_data = calculate_bom_health_score(results_df)
            health_score = health_data["health_score"]

            if health_score >= 90:
                health_status = "🟢 Excellent"
            elif health_score >= 75:
                health_status = "🟢 Healthy"
            elif health_score >= 60:
                health_status = "🟡 Moderate Risk"
            elif health_score >= 40:
                health_status = "🟠 High Risk"
            else:
                health_status = "🔴 Critical"

            st.session_state["health_score"] = health_score
            st.session_state["health_status"] = health_status

            try:
                analysis_response = supabase.table("analyses").insert(
                    _workspace_payload(
                        {
                            "user_id": current_user["id"],
                            "project_name": project_name or uploaded_file.name,
                            "filename": uploaded_file.name,
                            "total_parts": total_parts,
                            "high_risk_count": high_count,
                            "medium_risk_count": medium_count,
                            "low_risk_count": low_count,
                            "health_score": health_score,
                        }
                    )
                ).execute()

                analysis_id = analysis_response.data[0]["id"]
                st.session_state["analysis_id"] = analysis_id

            except Exception as e:
                st.error(f"Could not save analysis summary: {e}")
                st.stop()

            part_records = []

            for _, part_row in results_df.iterrows():
                part_records.append(
                    {
                        "analysis_id": analysis_id,
                        "user_id": current_user["id"],
                        "workspace_id": active_workspace_id,
                        "project_name": project_name or uploaded_file.name,
                        "mpn": part_row.get("MPN", ""),
                        "manufacturer": part_row.get("Manufacturer", ""),
                        "risk_score": part_row.get("Risk Score", 0),
                        "risk_level": part_row.get("Risk Level", ""),
                        "risk_reasons": part_row.get("Risk Reasons", ""),
                        "lifecycle_status": part_row.get("Lifecycle Status", ""),
                        "stock_available": part_row.get("Stock Available", 0),
                        "supplier_count": part_row.get("Supplier Count", 0),
                    }
                )

            if part_records:
                try:
                    supabase.table("analysis_parts").insert(part_records).execute()
                except Exception as e:
                    st.error(f"Could not save BOM parts: {e}")
                    st.stop()

            monitor_records = []
            alert_records = []

            for _, row in results_df.iterrows():
                latest_monitor = (
                    _workspace_query(
                        supabase.table("part_monitor_history")
                        .select("*")
                    )
                    .eq("user_id", current_user["id"])
                    .eq("part_number", row.get("MPN", ""))
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )

                latest_monitor_data = (
                    latest_monitor.data[0]
                    if latest_monitor.data
                    else None
                )

                monitor_alerts = []

                current_snapshot = build_monitor_record(
                    current_user["id"],
                    analysis_id,
                    row,
                    workspace_id=active_workspace_id,
                )

                if latest_monitor_data:
                    new_alert_records, monitor_alerts = detect_monitor_alerts(
                        current_user["id"],
                        analysis_id,
                        row.get("MPN", ""),
                        latest_monitor_data,
                        current_snapshot,
                        workspace_id=active_workspace_id,
                    )

                    alert_records.extend(new_alert_records)

                    for alert in new_alert_records:
                        if (
                            alert.get("severity") == "High"
                            and alert.get("alert_type") == "Stock Drop"
                        ):
                            pass  # Email disabled until Resend domain is verified

                if monitor_alerts:
                    st.warning(
                        f"{row.get('MPN', '')}: "
                        + " | ".join(monitor_alerts)
                    )

                monitor_records.append(current_snapshot)

            if monitor_records:
                try:
                    supabase.table("part_monitor_history").insert(
                        monitor_records
                    ).execute()
                except Exception as e:
                    st.error(f"Could not save monitoring history: {e}")

            if alert_records:
                try:
                    supabase.table("monitor_alerts").insert(
                        alert_records
                    ).execute()
                except Exception as e:
                    st.error(f"Could not save monitor alerts: {e}")

            new_upload_count = monthly_upload_count + 1

            try:
                supabase.table("users").update(
                    {
                        "monthly_upload_count": new_upload_count
                    }
                ).eq(
                    "id",
                    current_user["id"]
                ).execute()

                monthly_upload_count = new_upload_count

            except Exception as e:
                st.warning(f"Analysis completed, but upload count could not be updated: {e}")

            st.session_state["analysis_saved"] = True
    if "results_df" in st.session_state:
        results_df = st.session_state["results_df"]

        show_dashboard_summary(results_df)

        results_df["Risk Level Display"] = results_df["Risk Level"].apply(risk_badge)

        
        st.subheader("Detailed Risk Report")

        risk_filter = st.selectbox(
            "Filter by risk level",
            ["All", "High", "Medium", "Low"],
        )

        search_term = st.text_input("Search by part number")

        filtered_df = results_df.copy()

        if risk_filter != "All":
            filtered_df = filtered_df[filtered_df["Risk Level"] == risk_filter]

        if search_term:
            filtered_df = filtered_df[
                filtered_df["MPN"].astype(str).str.contains(search_term, case=False, na=False)
                | filtered_df["Normalized MPN"].astype(str).str.contains(search_term, case=False, na=False)
            ]

        filtered_df = filtered_df.sort_values(by="Risk Score", ascending=False)

        display_columns = [
            "MPN",
            "Manufacturer",
            "Best Source",
            "Supplier Count",
            "Stock Available",
            "Lifecycle Status",
            "Risk Score",
            "Risk Level Display",

        ]

        filtered_df["Risk Level Display"] = filtered_df["Risk Level"].replace(
            {
                "High": "🔴 High",
                "Medium": "🟡 Medium",
                "Low": "🟢 Low",
            }
        )

        st.dataframe(
            filtered_df[display_columns],
            use_container_width=True,
            hide_index=True,
            column_config={
                "MPN": st.column_config.TextColumn(width="medium"),
                "Manufacturer": st.column_config.TextColumn(width="medium"),
                "Best Source": st.column_config.TextColumn(width="small"),
                "Supplier Count": st.column_config.NumberColumn(width="small"),
                "Stock Available": st.column_config.NumberColumn(width="small"),
                "Lifecycle Status": st.column_config.TextColumn(width="medium"),
                "Has Alternates": st.column_config.CheckboxColumn(width="small"),
                "Risk Score": st.column_config.NumberColumn(width="small"),
                "Risk Level Display": st.column_config.TextColumn(width="small"),
                "Risk Reasons": st.column_config.TextColumn(
                    "Risk Reasons",
                    width="large",
                ),
            },
        )


        st.subheader("Part Details")

        for _, row in filtered_df.iterrows():

            risk_reasons = []

            if row["Stock Available"] == 0:
                risk_reasons.append("No stock available")

            if row["Supplier Count"] <= 1:
                risk_reasons.append("Single-source supplier")

            lifecycle_text = str(row["Lifecycle Status"]).lower()

            if "obsolete" in lifecycle_text:
                risk_reasons.append("Component marked obsolete")

            if "unknown" in lifecycle_text:
                risk_reasons.append("Unknown lifecycle status")

            if "replacement" in lifecycle_text:
                risk_reasons.append("Replacement suggested")

            with st.expander(
                f"{row['MPN']} — {row['Risk Level']} Risk"
            ):

                if risk_reasons:
                    st.markdown("### ⚠️ Risk Drivers")

                    for reason in risk_reasons:
                        st.write(f"• {reason}")


                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**Manufacturer:** {row.get('Manufacturer', '')}")
                    st.write(f"**Lifecycle Status:** {row.get('Lifecycle Status', '')}")
                    st.write(f"**Stock Available:** {row.get('Stock Available', 0)}")
                    st.write(f"**Supplier Count:** {row.get('Supplier Count', 0)}")

                with col2:
                    st.write(f"**Risk Score:** {row.get('Risk Score', 0)}")
                    st.write(f"**Risk Level:** {row.get('Risk Level', '')}")
                    has_alternates = row.get("Has Alternates", False)
                    st.write(
                        f"**Has Alternates:** {'✅ Yes' if has_alternates else '❌ No'}"
                    )

                st.write("**Risk Reasons:**")
                st.info(row.get("Risk Reasons", ""))

                if row.get("Has Alternates", False):
                    st.write("**Candidate Alternatives:**")
                    st.success(row.get("Alternative Part Numbers", ""))
                else:
                    st.write("**Candidate Alternatives:** None found")

                if row.get("Product URL", ""):
                    st.markdown(f"[🔗 Open supplier product page]({row.get('Product URL')})")


        output_path = "reports/bom_risk_report.xlsx"

        save_results_to_excel(
            results_df.drop(columns=["Risk Level Display"]).to_dict("records"),
            output_path,
        )

        with open(output_path, "rb") as file:
            st.download_button(
                label="Download Excel Report",
                data=file,
                file_name="bom_risk_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        if st.session_state.get("show_upgrade_modal"):
            st.divider()
            st.subheader("Upgrade Your Plan")

            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("### Starter")
                st.write("$29/mo")
                st.write("5 BOMs/month")
                st.write("10 parts per BOM")

            with col2:
                st.markdown("### Pro 🚀")
                st.write("$99/mo")
                st.write("10 BOMs/month")
                st.write("20 parts per BOM")
                if st.button("Select Pro", key="select_pro"):

                    supabase.table("users").update(
                        {
                            "plan": "Pro",
                            "monthly_upload_count": 0,
                        }
                    ).eq(
                        "id",
                        current_user["id"]
                    ).execute()

                    st.session_state["show_upgrade_modal"] = False

                    st.success("🎉 You are now on the Pro plan!")

                    st.rerun()

            with col3:
                st.markdown("### Business")
                st.write("$299/mo")
                st.write("25 BOMs/month")
                st.write("100 parts per BOM")
                if st.button("Select Business", key="select_business"):

                    supabase.table("users").update(
                        {
                            "plan": "Business",
                            "monthly_upload_count": 0,
                        }
                    ).eq(
                        "id",
                        current_user["id"]
                    ).execute()

                    st.session_state["show_upgrade_modal"] = False

                    st.success("🎉 You are now on the Business plan!")

                    st.rerun()


# Cadivor M4.6 — final visual gap compression.
# This targets the remaining empty Streamlit wrapper space before the first real page section.
components.html(
    """
    <script>
    function cadivorCompressTopGap(){
      const doc = window.parent.document;
      const desiredTop = 76;
      const firstContent = doc.querySelector('.cv-command-hero, .brc-hero, .cadivor-page-header, .cv-page-title, .cv-panel-title, h1, h2');
      if (!firstContent) return;

      let firstRow = firstContent.closest('.element-container');
      if (!firstRow) {
        let el = firstContent.parentElement;
        for (let i = 0; i < 10 && el; i++) {
          const cls = el.className ? String(el.className) : '';
          if (cls.includes('element-container')) { firstRow = el; break; }
          el = el.parentElement;
        }
      }
      if (!firstRow) return;

      const currentTop = firstContent.getBoundingClientRect().top;
      const delta = Math.round(currentTop - desiredTop);

      // Only compress excessive whitespace; never push content upward into the top bar.
      if (delta > 28) {
        firstRow.style.marginTop = `-${delta}px`;
      }
    }
    cadivorCompressTopGap();
    setTimeout(cadivorCompressTopGap, 100);
    setTimeout(cadivorCompressTopGap, 350);
    setTimeout(cadivorCompressTopGap, 800);
    setTimeout(cadivorCompressTopGap, 1400);
    window.addEventListener('resize', cadivorCompressTopGap);
    </script>
    """,
    height=0,
)
