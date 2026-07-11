import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from src.alternative_engine import suggest_alternatives_v2
from src.bom_parser import normalize_bom_columns, validate_bom, clean_bom_data
from src.risk_engine import calculate_risk
from src.report_generator import save_results_to_excel
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
start_time = time.time()
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.stripe_helper import create_checkout_session
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
        supabase.table("alternative_recommendations")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data if response.data else []



def load_analysis_history(user_id):
    response = (
        supabase.table("analyses")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return response.data if response.data else []

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

saved_bom_count_response = (
    supabase.table("analyses")
    .select("id", count="exact")
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

if app_mode not in NAV_OPTIONS and app_mode != "Analysis Details":
    app_mode = "Dashboard"
st.session_state["app_mode"] = app_mode

profile_for_shell = get_user_profile(current_user) if "get_user_profile" in globals() else current_user
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

_nav_icons = {
    "Dashboard":"⌂", "BOM Analyzer":"▦", "Alternative Finder":"⇄", "Monitoring":"◷",
    "Reports":"□", "Pricing":"$", "Settings":"⚙", "Workspace":"•", "Notifications":"•",
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

# ---------- Dashboard ----------
if app_mode == "Dashboard":
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
    )
    st.stop()

if app_mode == "Analysis Details":
    render_analysis_detail(
        current_user=current_user,
        supabase=supabase,
        load_analysis_history=load_analysis_history,
        light_plotly_layout=light_plotly_layout,
        _qp_value=_qp_value,
    )
    st.stop()

if app_mode == "Monitoring":
    st.subheader("Monitoring Dashboard")

    st.info(
        "Track historical stock, pricing, and lifecycle changes across monitored parts."
    )

    alert_history = (
        supabase.table("monitor_alerts")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )

    alert_df = pd.DataFrame(alert_history.data)

    monitor_history = (
        supabase.table("part_monitor_history")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )

    monitor_df = pd.DataFrame(monitor_history.data)

    alert_count = len(alert_df)

    high_alert_count = (
        alert_df["severity"]
        .astype(str)
        .str.contains("High", case=False, na=False)
        .sum()
        if not alert_df.empty
        else 0
    )

    obsolete_count = (
        monitor_df["lifecycle_status"]
        .astype(str)
        .str.contains("obsolete", case=False, na=False)
        .sum()
        if not monitor_df.empty
        else 0
    )

    no_stock_count = (
        (monitor_df["stock"] <= 0).sum()
        if not monitor_df.empty
        else 0
    )

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)

    with kpi1:
        st.metric("Active Alerts", alert_count)

    with kpi2:
        st.metric("High Severity", high_alert_count)

    with kpi3:
        st.metric("Obsolete Parts", obsolete_count)

    with kpi4:
        st.metric("No Stock Parts", no_stock_count)


    st.subheader("Recent Monitoring Alerts")

    if not alert_df.empty:
        alert_display_df = alert_df.rename(
            columns={
                "part_number": "Part Number",
                "alert_type": "Alert Type",
                "alert_message": "Alert Message",
                "severity": "Severity",
                "previous_value": "Previous Value",
                "current_value": "Current Value",
                "created_at": "Detected At",
            }
        )

        alert_display_df["Severity Display"] = (
            alert_display_df["Severity"]
            .replace(
                {
                    "High": "🔴 High",
                    "Medium": "🟡 Medium",
                    "Low": "🟢 Low",
                }
            )
        )

        st.dataframe(
            alert_display_df[
                [
                    "Part Number",
                    "Alert Type",
                    "Severity Display",
                    "Alert Message",
                    "Previous Value",
                    "Current Value",
                    "Detected At",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No monitoring alerts detected yet.")

    if not monitor_df.empty:
        monitor_display_df = monitor_df.rename(
            columns={
                "part_number": "Part Number",
                "supplier": "Supplier",
                "lifecycle_status": "Lifecycle Status",
                "stock": "Stock Available",
                "unit_price": "Unit Price",
                "risk_level": "Risk Level",
                "created_at": "Last Checked",
            }
        )

        monitor_display_df["Risk Level Display"] = (
            monitor_display_df["Risk Level"]
            .replace(
                {
                    "High": "🔴 High",
                    "Medium": "🟡 Medium",
                    "Low": "🟢 Low",
                }
            )
        )

        st.dataframe(
            monitor_display_df[
                [
                    "Part Number",
                    "Supplier",
                    "Lifecycle Status",
                    "Stock Available",
                    "Unit Price",
                    "Risk Level Display",
                    "Last Checked",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No monitoring history available yet.")


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
                supabase.table("analysis_parts")
                .select("*")
                .eq("analysis_id", analysis_id)
                .eq("user_id", current_user["id"])
                .execute()
            )
            return pd.DataFrame(response.data or [])
        except Exception:
            try:
                response = (
                    supabase.table("analysis_parts")
                    .select("*")
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
        _report_int(_report_value(row, "total_parts", "part_count", "parts_count", default=0))
        for row in report_records
    )
    total_high_risk = sum(
        _report_int(_report_value(row, "high_risk_count", "high_risk_parts", default=0))
        for row in report_records
    )
    health_values = [
        _report_int(_report_value(row, "health_score", default=0))
        for row in report_records
        if _report_value(row, "health_score", default=None) is not None
    ]
    average_health = round(sum(health_values) / len(health_values)) if health_values else 0

    st.markdown(
        """
        <style id="cadivor-reports-functional-v55">
        .cv-rpt-hero {
            border:1px solid #BFDBFE;border-radius:24px;padding:30px 32px;margin-bottom:20px;
            background:radial-gradient(circle at 90% 10%,rgba(37,99,235,.10),transparent 32%),
                       linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 65%,#EEF5FF 100%);
            box-shadow:0 22px 58px rgba(15,23,42,.07);
        }
        .cv-rpt-eyebrow {display:inline-flex;padding:7px 11px;border:1px solid #BFDBFE;border-radius:999px;
            background:#EFF6FF;color:#2563EB!important;font-size:10px;font-weight:900;letter-spacing:.12em;
            text-transform:uppercase;margin-bottom:16px;}
        .cv-rpt-title {color:#0F172A!important;font-size:38px;line-height:1.05;font-weight:950;
            letter-spacing:-.04em;margin:0 0 10px;}
        .cv-rpt-copy {color:#52647A!important;font-size:15px;line-height:1.65;font-weight:650;max-width:850px;margin:0;}
        .cv-rpt-section {color:#0F172A!important;font-size:21px;font-weight:950;letter-spacing:-.03em;margin:26px 0 4px;}
        .cv-rpt-sub {color:#64748B!important;font-size:13px;font-weight:700;margin-bottom:12px;}
        .cv-rpt-card {min-height:172px;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:20px;
            padding:21px;box-shadow:0 16px 40px rgba(15,23,42,.055);}
        .cv-rpt-icon {width:40px;height:40px;border-radius:13px;display:flex;align-items:center;justify-content:center;
            background:#EFF6FF;border:1px solid #BFDBFE;color:#2563EB!important;font-size:18px;font-weight:900;margin-bottom:14px;}
        .cv-rpt-card-title {color:#0F172A!important;font-size:15px;font-weight:950;margin-bottom:7px;}
        .cv-rpt-card-copy {color:#52647A!important;font-size:12px;line-height:1.55;font-weight:700;}
        .cv-rpt-workspace {background:#FFFFFF;border:1px solid #E2E8F0;border-radius:20px;padding:22px;
            box-shadow:0 16px 40px rgba(15,23,42,.055);margin-top:12px;}
        </style>
        <div class="cv-rpt-hero">
          <div class="cv-rpt-eyebrow">Reports Center</div>
          <h1 class="cv-rpt-title">Engineering reports</h1>
          <p class="cv-rpt-copy">Generate executive-ready BOM summaries, engineering risk reviews, and sourcing exports from saved Cadivor analyses.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metric_cols = st.columns(4)
    with metric_cols[0]:
        st.metric("Saved Analyses", total_reports)
    with metric_cols[1]:
        st.metric("Average Health", average_health)
    with metric_cols[2]:
        st.metric("High-Risk Parts", total_high_risk)
    with metric_cols[3]:
        st.metric("Tracked Parts", total_parts)

    st.markdown(
        '<div class="cv-rpt-section">Report templates</div>'
        '<div class="cv-rpt-sub">Each template now produces a real export from a saved analysis.</div>',
        unsafe_allow_html=True,
    )

    template_cols = st.columns(3)
    template_data = [
        ("Executive BOM Report", "Leadership-ready PDF with portfolio health, priority risks, and recommended actions.", "▤"),
        ("Engineering Risk Review", "Component-level CSV for engineering review and filtering.", "△"),
        ("Sourcing Summary", "Procurement-focused CSV with stock, supplier, lifecycle, and replacement fields.", "⇄"),
    ]
    for col, (title, copy, icon) in zip(template_cols, template_data):
        with col:
            st.markdown(
                f"""
                <div class="cv-rpt-card">
                  <div class="cv-rpt-icon">{icon}</div>
                  <div class="cv-rpt-card-title">{title}</div>
                  <div class="cv-rpt-card-copy">{copy}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        '<div class="cv-rpt-section">Generate a report</div>'
        '<div class="cv-rpt-sub">Select a saved BOM and download the report package you need.</div>',
        unsafe_allow_html=True,
    )

    if report_records:
        labels = [_analysis_label(row) for row in report_records]
        selected_label = st.selectbox("Saved BOM analysis", labels, key="reports_selected_analysis")
        selected_index = labels.index(selected_label)
        selected_analysis = report_records[selected_index]
        selected_analysis_id = _report_value(selected_analysis, "id", "analysis_id", default=None)
        selected_parts_df = _load_report_parts(selected_analysis_id)

        project_name = str(_report_value(selected_analysis, "project_name", "name", default="saved_bom"))
        safe_project = re.sub(r"[^A-Za-z0-9_-]+", "_", project_name).strip("_") or "saved_bom"

        download_cols = st.columns(3)

        with download_cols[0]:
            pdf_bytes = _build_executive_pdf(selected_analysis, selected_parts_df)
            st.download_button(
                "Download Executive PDF",
                data=pdf_bytes,
                file_name=f"{safe_project}_executive_report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

        with download_cols[1]:
            engineering_df = selected_parts_df.copy()
            if engineering_df.empty:
                engineering_df = pd.DataFrame(
                    [{
                        "project": project_name,
                        "health_score": _report_int(_report_value(selected_analysis, "health_score", default=0)),
                        "high_risk_parts": _report_int(_report_value(selected_analysis, "high_risk_count", "high_risk_parts", default=0)),
                        "medium_risk_parts": _report_int(_report_value(selected_analysis, "medium_risk_count", "medium_risk_parts", default=0)),
                    }]
                )
            st.download_button(
                "Download Engineering CSV",
                data=engineering_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{safe_project}_engineering_review.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with download_cols[2]:
            sourcing_candidates = [
                "mpn", "part_number", "manufacturer", "lifecycle_status",
                "stock_available", "stock", "supplier_count", "unit_price",
                "risk_level", "risk_score", "has_alternates", "alternate_count",
            ]
            if selected_parts_df.empty:
                sourcing_df = pd.DataFrame(
                    [{
                        "project": project_name,
                        "source_file": _report_value(selected_analysis, "filename", "uploaded_file", default="—"),
                        "health_score": _report_int(_report_value(selected_analysis, "health_score", default=0)),
                    }]
                )
            else:
                existing_cols = [c for c in sourcing_candidates if c in selected_parts_df.columns]
                sourcing_df = selected_parts_df[existing_cols].copy() if existing_cols else selected_parts_df.copy()

            st.download_button(
                "Download Sourcing CSV",
                data=sourcing_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{safe_project}_sourcing_summary.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.caption(
            f"Selected: {project_name} • "
            f"{_report_int(_report_value(selected_analysis, 'total_parts', 'part_count', 'parts_count', default=len(selected_parts_df)))} parts • "
            f"Health {_report_int(_report_value(selected_analysis, 'health_score', default=0))}"
        )
    else:
        st.info("No saved analyses are available yet. Analyze a BOM to create your first report source.")

    st.markdown(
        '<div class="cv-rpt-section">Recent report sources</div>'
        '<div class="cv-rpt-sub">Saved BOM analyses available for reporting and export.</div>',
        unsafe_allow_html=True,
    )

    if report_records:
        display_rows = []
        for row in report_records[:10]:
            created_at = str(_report_value(row, "created_at", "date", default=""))
            created_date = created_at.split("T")[0] if "T" in created_at else created_at[:10]
            display_rows.append(
                {
                    "Project": _report_value(row, "project_name", "name", default="Saved BOM"),
                    "Source File": _report_value(row, "filename", "uploaded_file", "file_name", default="—"),
                    "Date": created_date or "—",
                    "Health": _report_int(_report_value(row, "health_score", default=0)),
                    "High Risk": _report_int(_report_value(row, "high_risk_count", "high_risk_parts", default=0)),
                    "Medium Risk": _report_int(_report_value(row, "medium_risk_count", "medium_risk_parts", default=0)),
                    "Parts": _report_int(_report_value(row, "total_parts", "part_count", "parts_count", default=0)),
                }
            )
        report_sources_df = pd.DataFrame(display_rows)
        st.dataframe(report_sources_df, hide_index=True, use_container_width=True)

    st.markdown(
        '<div class="cv-rpt-section">Next reporting milestones</div>'
        '<div class="cv-rpt-sub">The next releases will build on this functional export foundation.</div>',
        unsafe_allow_html=True,
    )
    roadmap_cols = st.columns(4)
    roadmap = [
        ("5.6 Branded PDFs", "Cadivor logo, cover page, visual risk summary, and document metadata."),
        ("5.7 Scheduled Reports", "Weekly and monthly report delivery for monitored portfolios."),
        ("5.8 Report History", "Store generated report records with status, owner, and timestamps."),
        ("5.9 Team Sharing", "Shareable report links and controlled workspace access."),
    ]
    for col, (title, copy) in zip(roadmap_cols, roadmap):
        with col:
            st.markdown(
                f"""
                <div class="cv-rpt-card" style="min-height:135px;">
                  <div class="cv-rpt-card-title">{title}</div>
                  <div class="cv-rpt-card-copy">{copy}</div>
                </div>
                """,
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
    st.markdown(
        f"""
        <div class="cv-dashboard-header cv-fade-in">
          <div>
            <div class="cv-eyebrow">My Profile</div>
            <h1 class="cv-title">Profile settings</h1>
            <p class="cv-subtitle">Manage the personal information Cadivor displays across your workspace. Optional fields save when matching Supabase columns exist.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.0, 1.6])
    with left:
        avatar_markup = f'<img src="{profile["avatar_url"]}" alt="Profile photo" />' if profile.get("avatar_url") else profile["initials"]
        st.markdown(
            f"""
            <div class="cv-panel cv-fade-in">
              <div style="display:flex;align-items:center;gap:16px;">
                <div class="cadivor-avatar" style="width:68px;height:68px;font-size:22px;">{avatar_markup}</div>
                <div>
                  <div class="cv-panel-title" style="margin-bottom:4px;">{profile["full_name"]}</div>
                  <div class="cv-panel-copy" style="margin-bottom:0;">{profile["role_title"] or "Cadivor workspace member"}</div>
                </div>
              </div>
              <div class="cv-section-rule"></div>
              <div class="cv-snapshot-grid" style="grid-template-columns:1fr;">
                <div class="cv-snapshot-item"><span>Email</span><strong style="font-size:13px;">{profile["email"]}</strong></div>
                <div class="cv-snapshot-item"><span>Company</span><strong>{profile["company"] or "Not set"}</strong></div>
                <div class="cv-snapshot-item"><span>Plan</span><strong>{profile["plan"]}</strong></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            """
            <div class="cv-panel">
              <div class="cv-panel-title">Security</div>
              <div class="cv-panel-copy">Password changes and two-factor authentication will be added in a later security sprint.</div>
              <span class="cv-status-pill muted">Coming soon</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right:
        st.markdown('<div class="cv-panel-title">Profile information</div><div class="cv-panel-copy">Use this information to personalize Cadivor, reports, notifications, and future team workspaces.</div>', unsafe_allow_html=True)
        full_name = st.text_input("Full name", value=profile.get("full_name", ""), placeholder="Joshua Kashambala")
        company_name = st.text_input("Company / organization", value=profile.get("company", ""), placeholder="Egres Technologies")
        role_title = st.text_input("Job title", value=profile.get("role_title", ""), placeholder="Founder, Engineering Lead, Sourcing Manager")
        phone = st.text_input("Phone", value=profile.get("phone", ""), placeholder="+1 555 000 0000")
        country = st.text_input("Country", value=profile.get("country", ""), placeholder="United States")
        timezone_value = st.text_input("Time zone", value=profile.get("timezone", ""), placeholder="America/New_York")
        profile_image_url = st.text_input("Profile image URL", value=profile.get("avatar_url", ""), placeholder="https://...")

        save_col, cancel_col = st.columns([.75, .75])
        with save_col:
            if st.button("Save Changes", use_container_width=True):
                updates = {
                    "full_name": full_name.strip(),
                    "company_name": company_name.strip(),
                    "role_title": role_title.strip(),
                    "phone": phone.strip(),
                    "country": country.strip(),
                    "timezone": timezone_value.strip(),
                    "profile_image_url": profile_image_url.strip(),
                }
                try:
                    saved, skipped = update_user_profile_fields(current_user["id"], updates)
                    if saved:
                        st.success("Profile updated.")
                    if skipped:
                        st.info("Some optional profile fields need matching columns in your Supabase users table before they can be saved permanently.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Unable to update profile: {e}")
        with cancel_col:
            if st.button("Cancel", use_container_width=True):
                st.rerun()

        st.caption("Recommended optional columns: full_name, company_name, role_title, phone, country, timezone, profile_image_url.")

    st.stop()



# ---------- Workspace ----------
if app_mode == "Workspace":
    profile = get_user_profile(current_user)
    workspace_title = profile.get("workspace_name") or profile.get("company") or "Cadivor Workspace"
    st.markdown(
        f"""
        <div class="cv-dashboard-header cv-fade-in">
          <div>
            <div class="cv-eyebrow">Workspace</div>
            <h1 class="cv-title">{workspace_title}</h1>
            <p class="cv-subtitle">Manage workspace identity, subscription usage, team foundations, and billing entry points. Team collaboration expands after core product workflows are complete.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    w1, w2, w3, w4 = st.columns(4)
    with w1:
        st.markdown(f'<div class="cv-panel"><div class="cv-panel-title">Current Plan</div><div class="cv-snapshot-main">{selected_plan_name}</div><p class="cv-panel-copy">{selected_plan.get("description", "Cadivor subscription")}</p></div>', unsafe_allow_html=True)
    with w2:
        st.markdown(f'<div class="cv-panel"><div class="cv-panel-title">BOM Usage</div><div class="cv-snapshot-main">{monthly_upload_count} / {selected_plan["monthly_bom_limit"]}</div><p class="cv-panel-copy">Monthly analyses used.</p></div>', unsafe_allow_html=True)
    with w3:
        st.markdown(f'<div class="cv-panel"><div class="cv-panel-title">Saved BOMs</div><div class="cv-snapshot-main">{saved_bom_count} / {selected_plan["max_saved_boms"]}</div><p class="cv-panel-copy">Stored analyses in this workspace.</p></div>', unsafe_allow_html=True)
    with w4:
        st.markdown('<div class="cv-panel"><div class="cv-panel-title">Team Members</div><div class="cv-snapshot-main">1</div><p class="cv-panel-copy">Team workspaces coming soon.</p></div>', unsafe_allow_html=True)

    st.markdown('<div class="cv-section-spacer"></div><div class="cv-panel-title">Workspace settings</div><div class="cv-panel-copy">Workspace profile, team access, billing, and integrations will grow here as Cadivor moves toward team-ready workflows.</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([1.1, 1.4])
    with c1:
        st.markdown(
            f"""
            <div class="cv-panel">
              <div class="cv-panel-title">Workspace identity</div>
              <div class="cv-snapshot-grid" style="grid-template-columns:1fr;">
                <div class="cv-snapshot-item"><span>Workspace</span><strong>{workspace_title}</strong></div>
                <div class="cv-snapshot-item"><span>Organization</span><strong>{profile.get('company') or 'Not set'}</strong></div>
                <div class="cv-snapshot-item"><span>Owner</span><strong>{profile.get('full_name')}</strong></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            """
            <div class="cv-panel">
              <div class="cv-panel-title">Team foundation</div>
              <div class="cv-panel-copy">Cadivor is currently configured for single-user workspaces. Team roles, invitations, activity history, comments, and shared BOM ownership are planned after BOM Intelligence 2.0.</div>
              <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;">
                <span class="cv-status-pill muted">Admin role</span>
                <span class="cv-status-pill muted">Engineer role</span>
                <span class="cv-status-pill muted">Viewer role</span>
                <span class="cv-status-pill muted">Coming soon</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="cv-section-spacer"></div><div class="cv-panel-title">Workspace actions</div><div class="cv-panel-copy">Use these shortcuts to manage the current workspace experience.</div>', unsafe_allow_html=True)
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        action_card("Billing", "Review subscription and upgrade options.", "?page=Pricing", "$")
    with a2:
        action_card("Profile", "Update your display name, company, and role.", "?page=Settings", "◎")
    with a3:
        action_card("Notifications", "Prepare lifecycle, stock, and supplier alerts.", "?page=Notifications", "●")
    with a4:
        action_card("Integrations", "Supplier and API settings coming soon.", "?page=Help", "◇")
    st.stop()

# ---------- Notifications ----------
if app_mode == "Notifications":
    st.markdown(
        """
        <div class="cv-dashboard-header">
          <div>
            <div class="cv-eyebrow">Notification Center</div>
            <h1 class="cv-title">Alerts & updates</h1>
            <p class="cv-subtitle">Cadivor will surface lifecycle, stock, pricing, and monitoring changes here as your workspace grows.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    empty_state("No active notifications", "Your workspace has no unresolved alerts right now. Start monitoring parts to receive lifecycle, stock, and supplier updates.", "Open Monitoring", "?page=Monitoring", "●")
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
    st.markdown(
        """
        <style id="cadivor-alternative-finder-62a">
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
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "suggested_alternatives" not in st.session_state:
        st.session_state["suggested_alternatives"] = []

    if "alternative_search_attempted" not in st.session_state:
        st.session_state["alternative_search_attempted"] = False

    if "alternative_original_part" not in st.session_state:
        st.session_state["alternative_original_part"] = ""

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

    summary_col, tips_col = st.columns([1.35, 0.85], gap="medium")

    current_search = (original_part or "").strip()
    current_display = html.escape(current_search) if current_search else "No component entered"
    current_status = "Ready to search" if current_search else "Waiting for a part number"

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
                  <div class="af62-field"><span>Manufacturer</span><strong>—</strong></div>
                  <div class="af62-field"><span>Lifecycle</span><strong>—</strong></div>
                  <div class="af62-field"><span>Risk</span><strong>—</strong></div>
                  <div class="af62-field"><span>Package</span><strong>—</strong></div>
                  <div class="af62-field"><span>Datasheet</span><strong>—</strong></div>
                </div>
                <div class="af62-search-status">{current_status}</div>
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

    if find_alternatives_clicked:
        if not original_part:
            st.warning("Please enter an original part number.")
        else:
            with st.spinner(
                "Searching suppliers • Comparing electrical specs • Ranking alternatives..."
            ):
                st.session_state["suggested_alternatives"] = suggest_alternatives_v2(
                    original_part
                )
                st.session_state["alternative_search_attempted"] = True

    if st.session_state["suggested_alternatives"]:
        alternatives_df = pd.DataFrame(
            st.session_state["suggested_alternatives"]
        )

        st.success("Suggested alternatives found.")

        st.dataframe(
            alternatives_df,
            use_container_width=True,
            hide_index=True,
        )

        selected_alternative = st.selectbox(
            "Select alternative to compare",
            alternatives_df["Alternative Part"],
        )

        selected_row = alternatives_df[
            alternatives_df["Alternative Part"] == selected_alternative
        ].iloc[0]

        best_alternative = max(
            st.session_state["suggested_alternatives"],
            key=lambda x: x.get("Recommendation Score", 0),
        )

        st.success(
            f"""
            🏆 Best Recommended Alternative: {best_alternative['Alternative Part']}

            {best_alternative['Recommendation']}
            """
        )

        original_data = get_best_part_data(original_part)

        original_stock = float(original_data.get("stock_total", 0) or 0)
        alternative_stock = float(selected_row.get("Stock", 0) or 0)

        original_price = float(original_data.get("unit_price", 0.0) or 0.0)
        alternative_price = float(selected_row.get("Unit Price", 0.0) or 0.0)

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
            price_pct = ((alternative_price - original_price) / original_price) * 100

            if price_pct < 0:
                price_delta = f"🟢 {abs(price_pct):.1f}% lower cost"
            else:
                price_delta = f"🔴 {price_pct:.1f}% higher cost"
        else:
            price_delta = "N/A"

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
                    "Original": original_data.get("package") or "Not available from supplier data",
                    "Selected Alternative": selected_row.get("Package", ""),
                },
                {
                    "Attribute": "Pin Count",
                    "Original": original_data.get("pin_count") or "Not available from supplier data",
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
                {
                    "Attribute": "Drop-In Reasons",
                    "Original": "—",
                    "Selected Alternative": selected_row.get("Drop-In Reasons", ""),
                },
            ]
        )
        summary_points = []

        drop_in_reasons = selected_row.get("Drop-In Reasons", "")
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
            if "could not be verified" in reason.lower():
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

        st.subheader("Why this alternative?")

        st.markdown(
            f"**{selected_row.get('Alternative Part', '')}** is recommended because:"
        )

        st.markdown("**Recommended because:**")
        for point in recommendation_points:
            st.markdown(f"- {point}")

        if warning_points:
            st.markdown("**Warnings:**")
            for point in warning_points:
                st.markdown(f"- {point}")

        if advantage_points:
            st.markdown("**Advantages:**")
            for point in advantage_points:
                st.markdown(f"- {point}")

        if tradeoff_points:
            st.markdown("**Tradeoffs:**")
            for point in tradeoff_points:
                st.markdown(f"- {point}")
        
        st.subheader("Side-by-Side Comparison")

        st.dataframe(
            comparison_df,
            use_container_width=True,
            hide_index=True,
        )      

        if st.button("🔄 New Alternative Search"):
            st.session_state["suggested_alternatives"] = []
            st.session_state["alternative_search_attempted"] = False
            st.rerun()

    elif st.session_state["alternative_search_attempted"]:
        st.warning("No suggested alternatives found.")

    suggested_part_numbers = []

    if st.session_state["suggested_alternatives"]:
        suggested_part_numbers = [
            alt.get("Alternative Part", "")
            for alt in st.session_state["suggested_alternatives"]
            if isinstance(alt, dict)
        ]

    if suggested_part_numbers:
        st.divider()
        st.subheader("Step 2: Compare Alternatives")

        alternatives_input = st.text_input(
            "Enter alternative part numbers (comma-separated)",
            value=", ".join(suggested_part_numbers),
        )

        if st.button("Compare Parts", type="primary"):
            if original_part:
                alternatives = [
                    part.strip()
                    for part in alternatives_input.split(",")
                    if part.strip()
                ] if alternatives_input else []

                st.success(f"Comparing: {original_part} vs {alternatives}")

                comparison_df = compare_parts(original_part, alternatives)

                def risk_badge(level):
                    if level == "High":
                        return "🔴 High"
                    if level == "Medium":
                        return "🟡 Medium"
                    return "🟢 Low"

                comparison_df["Risk Level Display"] = comparison_df["Risk Level"].apply(
                    risk_badge
                )

                comparison_df = comparison_df.sort_values(
                    by=["Risk Score", "Total Market Stock"],
                    ascending=[True, False],
                )

                st.markdown("### Step 3 — Comparison Results")

                display_cols = [
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

                comparison_display_df = comparison_df[display_cols]

                st.dataframe(
                    comparison_display_df,
                    use_container_width=True,
                    hide_index=True,
                )

                alternatives_only = comparison_df[
                    comparison_df["Role"] == "Alternative"
                ]

                if not alternatives_only.empty:
                    best_alt = alternatives_only.sort_values(
                        by=["Risk Score", "Total Market Stock"],
                        ascending=[True, False],
                    ).iloc[0]

                    st.success(
                        f"✅ Recommended Alternative: **{best_alt['Matched MPN']}** "
                        f"(Risk: {best_alt['Risk Level']}, "
                        f"Stock: {best_alt['Total Market Stock']})"
                    )

                csv = comparison_df.to_csv(index=False).encode("utf-8")

                st.download_button(
                    "Download Comparison (CSV)",
                    data=csv,
                    file_name="alternative_comparison.csv",
                    mime="text/csv",
                )

            else:
                st.warning("Please enter a valid part number.")

    st.stop()
if app_mode == "BOM Analyzer":

    st.markdown(
    """
    <div class="card">
        <div class="card-title">📤 Upload BOM</div>
        <div class="card-text">
            Upload a CSV or Excel BOM to analyze lifecycle, sourcing, and supply chain risk.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
    )

    st.subheader("📈 Recent BOM Analyses")

    history_data = analysis_history.data

    if history_data:

        history_df = pd.DataFrame(history_data)
        if "project_name" not in history_df.columns:
            history_df["project_name"] = history_df["filename"]

        history_df["created_at"] = pd.to_datetime(
            history_df["created_at"]
        ).dt.strftime("%Y-%m-%d")

        display_history = history_df[
            [
                "project_name",
                "filename",
                "health_score",
                "high_risk_count",
                "medium_risk_count",
                "created_at",
            ]
        ].rename(
            columns={
                "project_name": "Project Name",
                "filename": "Uploaded File",
                "health_score": "Health Score",
                "high_risk_count": "High Risk Parts",
                "medium_risk_count": "Medium Risk Parts",
                "created_at": "Created At",
            }
        )

        st.dataframe(
            display_history,
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.info("No previous BOM analyses found.")


    project_name = st.text_input(
        "Project / BOM Name",
        placeholder="Example: Motor Controller Rev A"
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
    )

    st.caption(
        "Required columns: mpn and quantity. Duplicate part numbers will be merged automatically."
    )

    uploaded_file = st.file_uploader(
        "Upload your BOM file", 
        type=["csv", "xlsx"],
        key="bom_file_uploader",
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
                supabase.table("analyses")
                .select("id", count="exact")
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
                    supabase.table("part_monitor_history")
                    .select("*")
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
                )

                if latest_monitor_data:
                    new_alert_records, monitor_alerts = detect_monitor_alerts(
                        current_user["id"],
                        analysis_id,
                        row.get("MPN", ""),
                        latest_monitor_data,
                        current_snapshot,
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
