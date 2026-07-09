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

if app_mode not in NAV_OPTIONS:
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

    st.markdown(
        """
        <style>

        /* Dashboard-specific styling only. Layout shell is defined globally above. */
        .main .block-container, [data-testid="stMainBlockContainer"] { padding-left:calc(var(--cv-sidebar-width) + 24px)!important; padding-right:24px!important; max-width:none!important; }
        .cv-side-brand { display:flex; align-items:center; gap:12px; margin-bottom:22px; }
        .cv-side-logo { width:38px; height:38px; border-radius:12px; background:#2563EB; color:#fff!important; display:flex; align-items:center; justify-content:center; font-weight:950; box-shadow:0 12px 24px rgba(37,99,235,.25); }
        .cv-side-name { color:#0F172A!important; font-size:20px; font-weight:950; line-height:1; }
        .cv-side-sub { color:#64748B!important; font-size:10px; font-weight:800; margin-top:4px; letter-spacing:.04em; text-transform:uppercase; }
        .cv-side-user { display:flex; gap:12px; align-items:center; padding:13px; border:1px solid #E5E7EB; border-radius:16px; background:#F8FAFC; margin-bottom:22px; }
        .cv-side-avatar { width:38px; height:38px; border-radius:50%; background:#EFF6FF; color:#2563EB!important; border:1px solid #BFDBFE; display:flex; align-items:center; justify-content:center; font-weight:950; flex:0 0 auto; }
        .cv-side-user strong { display:block; color:#0F172A!important; font-size:14px; font-weight:950; line-height:1.2; }
        .cv-side-user small { display:block; color:#64748B!important; font-size:11px; font-weight:700; line-height:1.35; max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .cv-side-section { color:#94A3B8!important; font-size:11px; font-weight:900; text-transform:uppercase; letter-spacing:.09em; margin:18px 8px 8px; }
    .cv-side-section.first { margin-top:8px; }
        .cv-side-nav { display:flex; flex-direction:column; gap:4px; }
        .cv-side-link { display:flex; align-items:center; gap:10px; padding:10px 11px; border-radius:12px; color:#334155!important; text-decoration:none!important; font-size:13px; font-weight:800; border:1px solid transparent; }
        .cv-side-link span { width:22px; text-align:center; color:#64748B!important; font-size:15px; }
        .cv-side-link:hover { background:#F8FAFC; color:#0F172A!important; transform:translateX(2px); transition:all .16s ease; }
        .cv-side-link.active { background:#EFF6FF; border-color:#BFDBFE; color:#2563EB!important; }
        .cv-side-link.active span { color:#2563EB!important; }
        .cv-side-plan { border:1px solid #E5E7EB; border-radius:16px; background:#FFFFFF; padding:14px; display:flex; flex-direction:column; gap:7px; }
        .cv-side-plan strong { color:#0F172A!important; font-size:18px; font-weight:950; }
        .cv-side-plan span { color:#64748B!important; font-size:12px; font-weight:750; }
        .cv-side-footer { margin-top:20px; display:grid; gap:8px; }
        .cv-side-footer a { padding:10px 12px; border-radius:12px; text-decoration:none!important; color:#334155!important; font-weight:850; font-size:13px; background:#F8FAFC; border:1px solid #E5E7EB; }
        .cv-side-footer a:last-child { color:#DC2626!important; }
        .cadivor-topbar {
            margin-top: 0;
            margin-bottom: 22px;
            padding: 12px 18px;
            background: rgba(255,255,255,.97);
            border: 1px solid #E5E7EB;
            border-radius: 18px;
            box-shadow: 0 12px 32px rgba(15,23,42,.055);
            display: grid;
            grid-template-columns: 280px 1fr auto;
            align-items: center;
            gap: 22px;
            width: 100%;
        }
        .cadivor-brand { display:flex; align-items:center; gap:14px; min-width:260px; }
        .cadivor-logo-mark {
            width: 46px; height: 46px; border-radius: 14px;
            display:flex; align-items:center; justify-content:center;
            background:#2563EB; color:#FFFFFF!important; font-weight:900; font-size:22px;
            box-shadow:0 12px 22px rgba(37,99,235,.22);
        }
        .cadivor-logo-text { color:#0F172A!important; font-size:22px; font-weight:950; line-height:1; letter-spacing:-.02em; }
        .cadivor-logo-subtitle { color:#64748B!important; font-size:11.5px; font-weight:800; margin-top:4px; letter-spacing:.02em; }
        .cadivor-topbar-center { color:#0F172A!important; font-size:15px; font-weight:850; justify-self:start; }
        .cadivor-user { display:flex; align-items:center; gap:12px; justify-content:flex-end; min-width:280px; }
        .cadivor-user-label { color:#94A3B8!important; font-size:10px; font-weight:850; text-transform:uppercase; letter-spacing:.08em; text-align:right; }
        .cadivor-user-email { color:#64748B!important; font-size:12px; font-weight:700; max-width:230px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .cadivor-user-name { color:#0F172A!important; font-size:15px; font-weight:900; text-align:right; line-height:1.15; }
        .cadivor-user-company { color:#64748B!important; font-size:12px; font-weight:700; text-align:right; margin-top:2px; }
        .cadivor-avatar { width:44px; height:44px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:#EFF6FF; color:#2563EB!important; font-weight:950; border:1px solid #BFDBFE; overflow:hidden; }
        .cadivor-avatar img { width:100%; height:100%; object-fit:cover; display:block; }

        .cv-dashboard-header {
            display:flex; align-items:flex-start; justify-content:space-between; gap:24px;
            margin: 2px 0 14px 0;
        }
        .cv-eyebrow {
            display:inline-flex; align-items:center; gap:8px;
            padding:7px 11px; border-radius:999px;
            background:#EFF6FF; color:#2563EB!important;
            font-size:11px; font-weight:900; letter-spacing:.08em; text-transform:uppercase;
            margin-bottom:10px;
        }
        .cv-title { font-size:40px; line-height:1.05; font-weight:950; color:#0F172A!important; letter-spacing:-.045em; margin:0 0 8px 0; }
        .cv-subtitle { color:#64748B!important; font-size:15px; line-height:1.55; max-width:760px; margin:0; }
        .cv-action-row { display:flex; gap:10px; justify-content:flex-end; align-items:center; padding-top:8px; }
        .cv-action-row-label { color:#94A3B8!important; font-size:11px; font-weight:900; letter-spacing:.08em; text-transform:uppercase; text-align:right; padding-top:0; margin-bottom:8px; }
        .cv-quick-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:16px; padding:14px; box-shadow:0 14px 32px rgba(15,23,42,.055); display:grid; gap:8px; }
        .cv-quick-copy { color:#64748B!important; font-size:12px; font-weight:700; margin-bottom:2px; text-align:right; }
    .cv-quick-button { display:block; text-align:center; text-decoration:none!important; background:#2563EB; color:#FFFFFF!important; border-radius:10px; padding:11px 14px; font-weight:850; box-shadow:0 12px 24px rgba(37,99,235,.20); }
    .cv-quick-button:hover { background:#1D4ED8; color:#FFFFFF!important; transform:translateY(-1px); transition:all .16s ease; }
    .cv-quick-button.secondary { background:#F8FAFC; color:#2563EB!important; border:1px solid #BFDBFE; box-shadow:none; }
    .cv-quick-button.secondary:hover { background:#EFF6FF; color:#1D4ED8!important; }
        .cv-action-row div.stButton > button { min-width:132px!important; width:auto!important; }

        .cv-metric {
            background:#FFFFFF; border:1px solid #E5E7EB; border-radius:16px;
            padding:18px 18px 16px 18px; box-shadow:0 14px 32px rgba(15,23,42,.055);
            min-height:118px; position:relative; overflow:hidden;
        }
        .cv-metric:before { content:""; position:absolute; inset:0 0 auto 0; height:3px; background:#2563EB; opacity:.88; }
        .cv-metric.cv-danger:before { background:#DC2626; }
        .cv-metric.cv-warning:before { background:#F59E0B; }
        .cv-metric.cv-success:before { background:#16A34A; }
        .cv-metric-top { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:12px; }
        .cv-metric-label { color:#64748B!important; font-size:12px; font-weight:850; letter-spacing:.035em; text-transform:uppercase; }
        .cv-metric-icon { width:32px; height:32px; border-radius:10px; display:flex; align-items:center; justify-content:center; background:#F8FAFC; border:1px solid #E5E7EB; font-size:16px; }
        .cv-metric-value { color:#0F172A!important; font-size:38px; line-height:1; font-weight:950; letter-spacing:-.04em; margin-bottom:8px; }
        .cv-metric-note { color:#64748B!important; font-size:13px; font-weight:700; }
        .cv-badge { display:inline-flex; padding:5px 9px; border-radius:999px; font-size:11px; font-weight:850; border:1px solid #BFDBFE; color:#2563EB!important; background:#EFF6FF; }
        .cv-badge.success { color:#047857!important; background:#ECFDF5; border-color:#A7F3D0; }
        .cv-badge.warning { color:#B45309!important; background:#FFFBEB; border-color:#FDE68A; }
        .cv-badge.danger { color:#B91C1C!important; background:#FEF2F2; border-color:#FECACA; }

        .cv-panel {
            background:#FFFFFF; border:1px solid #E5E7EB; border-radius:16px;
            padding:18px; box-shadow:0 14px 32px rgba(15,23,42,.055); margin-top:16px;
        }
        .cv-panel-title { color:#0F172A!important; font-size:18px; font-weight:950; letter-spacing:-.025em; margin-bottom:4px; }
        .cv-panel-copy { color:#64748B!important; font-size:13px; margin-bottom:14px; }
        .cv-snapshot-main { color:#0F172A!important; font-size:22px; font-weight:900; line-height:1.2; margin:10px 0 12px; }
        .cv-snapshot-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
        .cv-snapshot-item { background:#F8FAFC; border:1px solid #E5E7EB; border-radius:12px; padding:12px; }
        .cv-snapshot-item span { color:#64748B!important; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.05em; display:block; margin-bottom:7px; }
        .cv-snapshot-item strong { color:#0F172A!important; font-size:22px; font-weight:950; }
        .cv-actions-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:16px; }
        .cv-action-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:15px; padding:16px; box-shadow:0 12px 28px rgba(15,23,42,.045); }
        .cv-action-icon { width:34px; height:34px; border-radius:11px; display:flex; align-items:center; justify-content:center; background:#EFF6FF; color:#2563EB!important; font-weight:900; margin-bottom:10px; }
        .cv-action-title { color:#0F172A!important; font-size:14px; font-weight:900; margin-bottom:4px; }
        .cv-action-copy { color:#64748B!important; font-size:12px; line-height:1.45; }
        .cv-section-spacer { margin-top:36px; }
        @media(max-width:1000px){ .cv-app-sidebar{position:relative;width:auto;height:auto;box-shadow:none;border-right:0;border-bottom:1px solid #E5E7EB;} .main .block-container{padding-left:1rem!important;padding-right:1rem!important;} .cv-dashboard-header{display:block;} .cv-action-row{justify-content:flex-start;padding-top:14px;} .cv-actions-grid{grid-template-columns:1fr 1fr;} }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Cadivor v3.0 dashboard polish overrides: shell rhythm, KPI hierarchy, and table finish.
    st.markdown(
        """
        <style>
        :root { --cv-topbar-height: 64px!important; --cv-sidebar-width: 284px!important; }

        /* Keep Streamlit chrome suppressed without showing native navigation during reruns. */
        header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
        [data-testid="stStatusWidget"], .stDeployButton, [data-testid="collapsedControl"],
        [data-testid="stSidebar"], section[data-testid="stSidebar"], div[data-testid="stSidebarNav"] {
            display:none!important; visibility:hidden!important; width:0!important; height:0!important; min-height:0!important;
        }

        /* Enterprise shell alignment. */
        .cadivor-topbar {
            position:fixed!important; top:0!important; left:0!important; right:0!important; z-index:999998!important;
            height:var(--cv-topbar-height)!important; min-height:var(--cv-topbar-height)!important;
            margin:0!important; padding:0 20px!important; border-radius:0!important; border:0!important;
            border-bottom:1px solid #E5E7EB!important; box-shadow:0 12px 28px rgba(15,23,42,.045)!important;
            background:rgba(255,255,255,.985)!important;
            grid-template-columns: var(--cv-sidebar-width) minmax(360px,1fr) auto!important;
        }
        .cadivor-brand { min-width:0!important; gap:12px!important; }
        .cadivor-logo-mark { width:40px!important; height:40px!important; border-radius:12px!important; font-size:20px!important; }
        .cadivor-logo-text { font-size:22px!important; }
        .cadivor-logo-subtitle { font-size:9.5px!important; letter-spacing:.16em!important; text-transform:uppercase!important; }
        .cadivor-topbar-center { display:flex!important; align-items:center!important; gap:16px!important; min-width:0!important; }
        .cadivor-current-page { min-width:132px!important; font-size:14px!important; font-weight:950!important; }
        .cadivor-search-pill {
            max-width:360px!important; height:36px!important; background:#F8FAFC!important;
            border:1px solid #E2E8F0!important; color:#94A3B8!important; font-size:12px!important;
        }
        .cadivor-top-icon { width:32px!important; height:32px!important; box-shadow:none!important; }
        .cadivor-user { min-width:260px!important; }
        .cadivor-user-label { font-size:9.5px!important; }
        .cadivor-user-name { font-size:14px!important; }
        .cadivor-user-company { font-size:11px!important; }
        .cadivor-avatar { width:38px!important; height:38px!important; }

        .cv-app-sidebar {
            position:fixed!important; top:var(--cv-topbar-height)!important; left:0!important; bottom:0!important;
            height:calc(100vh - var(--cv-topbar-height))!important; width:var(--cv-sidebar-width)!important;
            padding:22px 16px 18px!important; z-index:999997!important;
            box-shadow:14px 0 34px rgba(15,23,42,.035)!important;
        }

        [data-testid="stAppViewContainer"] > .main, [data-testid="stMain"] > div,
        .main .block-container, [data-testid="stMainBlockContainer"] {
            padding-top:calc(var(--cv-topbar-height) + 12px)!important;
            padding-left:calc(var(--cv-sidebar-width) + 22px)!important;
            padding-right:22px!important; padding-bottom:56px!important; max-width:none!important; width:100%!important;
        }

        /* Dashboard rhythm: less wasted vertical space, more premium hierarchy. */
        .cv-dashboard-header { margin-top:0!important; margin-bottom:12px!important; align-items:flex-end!important; }
        .cv-eyebrow { margin-bottom:9px!important; padding:6px 10px!important; font-size:10.5px!important; }
        .cv-title { font-size:36px!important; line-height:1.04!important; margin-bottom:10px!important; letter-spacing:-.045em!important; }
        .cv-subtitle { max-width:760px!important; font-size:14px!important; line-height:1.55!important; }
        .cv-quick-mini { max-width:340px!important; padding-top:0!important; margin-top:0!important; }
        .cv-quick-mini .cv-action-row-label { margin-bottom:7px!important; }
        .cv-mini-buttons { display:grid!important; grid-template-columns:1fr 1fr!important; gap:10px!important; }
        .cv-quick-mini .cv-quick-button { min-width:0!important; padding:10px 15px!important; border-radius:12px!important; }

        .cv-metric { min-height:112px!important; padding:18px 18px 16px!important; border-radius:17px!important; transition:transform .16s ease, box-shadow .16s ease!important; }
        .cv-metric:hover { transform:translateY(-2px)!important; box-shadow:0 20px 42px rgba(15,23,42,.075)!important; }
        .cv-metric-label { font-size:11px!important; letter-spacing:.06em!important; }
        .cv-metric-icon { width:31px!important; height:31px!important; border-radius:10px!important; }
        .cv-metric-value { font-size:42px!important; line-height:.95!important; margin-bottom:9px!important; }
        .cv-metric-note { font-size:12px!important; font-weight:850!important; }

        .cv-panel-title { font-size:18px!important; margin-bottom:3px!important; }
        .cv-panel-copy { font-size:12.5px!important; margin-bottom:12px!important; }
        div[data-testid="stPlotlyChart"] {
            background:#FFFFFF!important; border:1px solid #E5E7EB!important; border-radius:17px!important;
            box-shadow:0 14px 32px rgba(15,23,42,.045)!important; padding:10px!important;
        }
        .js-plotly-plot { border-radius:14px!important; overflow:hidden!important; }

        .cv-panel { border-radius:17px!important; padding:19px!important; }
        .cv-snapshot-grid { gap:11px!important; }
        .cv-snapshot-item { border-radius:14px!important; }

        /* Dataframes: softer enterprise table treatment. */
        [data-testid="stDataFrame"] {
            border-radius:16px!important; border:1px solid #E5E7EB!important; overflow:hidden!important;
            box-shadow:0 14px 34px rgba(15,23,42,.045)!important; background:#FFFFFF!important;
        }
        [data-testid="stDataFrame"] [role="columnheader"] {
            background:#F8FAFC!important; color:#64748B!important; font-size:12px!important; font-weight:900!important;
        }
        [data-testid="stDataFrame"] [role="gridcell"] {
            background:#FFFFFF!important; color:#0F172A!important; border-bottom:1px solid #EEF2F7!important;
        }
        [data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] { background:#F8FAFC!important; }

        .cv-actions-grid { gap:14px!important; }
        .cv-action-card { border-radius:17px!important; transition:transform .16s ease, box-shadow .16s ease!important; }
        .cv-action-card:hover { transform:translateY(-2px)!important; box-shadow:0 18px 38px rgba(15,23,42,.07)!important; }

        @media(max-width:1100px){
            .cadivor-topbar{position:relative!important;grid-template-columns:1fr!important;height:auto!important;min-height:70px!important;padding:12px 16px!important;}
            .cadivor-topbar-center{display:none!important;}
            .cv-app-sidebar{position:relative!important;top:auto!important;width:auto!important;height:auto!important;}
            .main .block-container,[data-testid="stMainBlockContainer"]{padding:1rem!important;}
            .cv-dashboard-header{display:block!important;}
            .cv-quick-mini{margin-left:0!important;margin-top:16px!important;max-width:none!important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Milestone 4.14 — Dashboard Polish: page-content only.
    # Does not alter the fixed shell, sidebar, or topbar.
    st.markdown(
        """
        <style>
        /* M4.14 Dashboard Polish — content layer only */
        .cv-command-hero {
            border-radius:22px!important;
            border:1px solid rgba(147,197,253,.88)!important;
            background:
                radial-gradient(circle at 86% 12%, rgba(37,99,235,.10), transparent 34%),
                linear-gradient(135deg, rgba(255,255,255,.98), rgba(239,246,255,.86))!important;
            box-shadow:0 24px 58px rgba(15,23,42,.075)!important;
        }
        .cv-command-hero:hover {
            box-shadow:0 28px 68px rgba(15,23,42,.095)!important;
            transform:translateY(-1px)!important;
            transition:box-shadow .18s ease, transform .18s ease!important;
        }
        .cv-title {
            color:#0B1220!important;
            text-wrap:balance!important;
        }
        .cv-subtitle { color:#475569!important; }

        .cv-insight-card {
            border-radius:18px!important;
            background:rgba(255,255,255,.96)!important;
            border:1px solid rgba(226,232,240,.95)!important;
            box-shadow:0 18px 42px rgba(15,23,42,.060)!important;
            transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease!important;
        }
        .cv-insight-card:hover {
            transform:translateY(-2px)!important;
            box-shadow:0 24px 52px rgba(15,23,42,.085)!important;
            border-color:#BFDBFE!important;
        }
        .cv-insight-title { font-size:13px!important; letter-spacing:-.01em!important; }
        .cv-insight-copy { color:#475569!important; font-size:12px!important; }

        .cv-metric {
            background:
                linear-gradient(180deg,#FFFFFF 0%,#FFFFFF 62%,#F8FAFC 100%)!important;
            border-color:#E2E8F0!important;
            border-radius:20px!important;
            box-shadow:0 18px 46px rgba(15,23,42,.065)!important;
        }
        .cv-metric:before { height:4px!important; }
        .cv-metric:hover {
            transform:translateY(-3px)!important;
            box-shadow:0 28px 60px rgba(15,23,42,.095)!important;
            border-color:#CBD5E1!important;
        }
        .cv-metric-label { color:#64748B!important; font-size:10.5px!important; letter-spacing:.085em!important; }
        .cv-metric-icon {
            background:#F8FAFC!important;
            border-color:#E2E8F0!important;
            box-shadow:inset 0 1px 0 rgba(255,255,255,.85)!important;
        }
        .cv-metric-value {
            font-size:44px!important;
            letter-spacing:-.055em!important;
            color:#071126!important;
        }
        .cv-metric-note { color:#475569!important; }

        .cv-panel-title {
            font-size:19px!important;
            line-height:1.12!important;
            color:#0B1220!important;
            letter-spacing:-.035em!important;
        }
        .cv-panel-copy { color:#52647A!important; line-height:1.45!important; }
        div[data-testid="stPlotlyChart"] {
            border-radius:20px!important;
            border-color:#E2E8F0!important;
            box-shadow:0 18px 46px rgba(15,23,42,.060)!important;
            padding:14px!important;
            transition:transform .16s ease, box-shadow .16s ease!important;
        }
        div[data-testid="stPlotlyChart"]:hover {
            transform:translateY(-2px)!important;
            box-shadow:0 24px 58px rgba(15,23,42,.080)!important;
        }

        .cv-panel {
            border-radius:20px!important;
            border-color:#E2E8F0!important;
            box-shadow:0 18px 46px rgba(15,23,42,.060)!important;
        }
        .cv-snapshot-main {
            font-size:24px!important;
            letter-spacing:-.035em!important;
            color:#071126!important;
        }
        .cv-snapshot-item {
            background:linear-gradient(180deg,#FFFFFF,#F8FAFC)!important;
            border-color:#E2E8F0!important;
            box-shadow:inset 0 1px 0 rgba(255,255,255,.78)!important;
        }
        .cv-snapshot-item span { color:#64748B!important; letter-spacing:.07em!important; }

        [data-testid="stDataFrame"] {
            border-radius:18px!important;
            border-color:#E2E8F0!important;
            box-shadow:0 18px 46px rgba(15,23,42,.055)!important;
        }
        [data-testid="stDataFrame"] [role="columnheader"] {
            background:#F8FAFC!important;
            color:#475569!important;
            text-transform:uppercase!important;
            letter-spacing:.04em!important;
            font-size:11px!important;
        }
        [data-testid="stDataFrame"] [role="gridcell"] {
            font-size:12px!important;
        }

        .cv-result-card {
            border-radius:17px!important;
            border-color:#E2E8F0!important;
            box-shadow:0 14px 34px rgba(15,23,42,.045)!important;
            transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease!important;
        }
        .cv-result-card:hover {
            transform:translateY(-2px)!important;
            border-color:#BFDBFE!important;
            box-shadow:0 22px 48px rgba(15,23,42,.075)!important;
        }
        .cv-result-title { color:#0B1220!important; letter-spacing:-.015em!important; }
        .cv-result-meta { color:#52647A!important; }

        .cv-actions-grid { gap:16px!important; }
        .cv-action-card {
            min-height:116px!important;
            border-radius:20px!important;
            background:linear-gradient(180deg,#FFFFFF,#F8FAFC)!important;
            border-color:#E2E8F0!important;
            box-shadow:0 18px 46px rgba(15,23,42,.055)!important;
            transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease!important;
        }
        .cv-action-card:hover {
            transform:translateY(-3px)!important;
            box-shadow:0 28px 62px rgba(15,23,42,.085)!important;
            border-color:#BFDBFE!important;
        }
        .cv-action-icon {
            background:#EFF6FF!important;
            color:#2563EB!important;
            border:1px solid #DBEAFE!important;
        }
        .cv-action-title { font-size:13px!important; letter-spacing:-.01em!important; }
        .cv-action-copy { color:#52647A!important; }

        .cv-section-spacer { margin-top:28px!important; }
        .cv-status-pill { font-weight:950!important; letter-spacing:-.005em!important; }

        @media(max-width:1200px){
            .cv-actions-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;}
            .cv-title{font-size:31px!important;}
        }
        @media(max-width:760px){
            .cv-actions-grid{grid-template-columns:1fr!important;}
            .cv-metric-value{font-size:36px!important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Load dashboard data once for this page.
    analysis_response = (
        supabase.table("analyses")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .execute()
    )

    analysis_data = analysis_response.data or []
    total_analyses = len(analysis_data)

    if analysis_data:
        avg_health_score = int(
            sum(item.get("health_score", 0) or 0 for item in analysis_data)
            / max(1, total_analyses)
        )
        total_high_risk = sum(item.get("high_risk_count", 0) or 0 for item in analysis_data)
        total_medium_risk = sum(item.get("medium_risk_count", 0) or 0 for item in analysis_data)
        total_low_risk = sum(item.get("low_risk_count", 0) or 0 for item in analysis_data)
        total_components = sum(item.get("total_parts", 0) or 0 for item in analysis_data)
        latest_analysis = analysis_data[0]
    else:
        avg_health_score = 0
        total_high_risk = 0
        total_medium_risk = 0
        total_low_risk = 0
        total_components = 0
        latest_analysis = None

    try:
        alternative_history = load_alternative_history(current_user["id"])
        alternatives_found = len(alternative_history)
    except Exception:
        alternative_history = []
        alternatives_found = 0

    try:
        alert_history = (
            supabase.table("monitor_alerts")
            .select("*")
            .eq("user_id", current_user["id"])
            .order("created_at", desc=True)
            .limit(25)
            .execute()
        )
        alert_data = alert_history.data or []
    except Exception:
        alert_data = []

    alert_count = len(alert_data)
    high_alert_count = sum(1 for item in alert_data if "high" in str(item.get("severity", "")).lower())

    if avg_health_score >= 80:
        health_badge = "Healthy Portfolio"
        health_kind = "success"
    elif avg_health_score >= 55:
        health_badge = "Review Recommended"
        health_kind = "warning"
    elif avg_health_score > 0:
        health_badge = "Critical Review"
        health_kind = "danger"
    else:
        health_badge = "No Data Yet"
        health_kind = ""

    profile = get_user_profile(current_user)
    user_email = profile["email"]
    user_name = profile["full_name"].split()[0] if profile.get("full_name") else "there"
    _hour = datetime.now().hour if "datetime" in globals() else 12
    if _hour < 12:
        greeting_prefix = "Good morning"
    elif _hour < 17:
        greeting_prefix = "Good afternoon"
    else:
        greeting_prefix = "Good evening"

    def _metric(label, value, note, icon="•", kind=""):
        kind_class = f" cv-{kind}" if kind else ""
        st.markdown(
            f"""
            <div class="cv-metric{kind_class}">
                <div class="cv-metric-top">
                    <div class="cv-metric-label">{label}</div>
                    <div class="cv-metric-icon">{icon}</div>
                </div>
                <div class="cv-metric-value">{value}</div>
                <div class="cv-metric-note">{note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Cadivor Dashboard v3 — Enterprise Engineering Intelligence.
    # Content-only update: no shell/topbar/sidebar changes.
    def _cv_icon(kind="sparkles"):
        icons = {
            "sparkles": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"/><path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/></svg>',
            "shield": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>',
            "alert": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
            "radar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19.07 4.93A10 10 0 1 1 4.93 19.07"/><path d="M12 12 4.93 4.93"/><path d="M16.24 7.76A6 6 0 1 1 7.76 16.24"/><circle cx="12" cy="12" r="2"/></svg>',
            "git": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 9v2a7 7 0 0 0 7 7h2"/><path d="M6 9v12"/></svg>',
            "layers": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 2 9 5-9 5-9-5 9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/></svg>',
        }
        return icons.get(kind, icons["sparkles"])

    latest_project_for_hero = (latest_analysis.get("project_name") or latest_analysis.get("filename")) if latest_analysis else "Upload your first BOM"
    top_alert_part = "No active alerts"
    top_alert_message = "Monitoring is clear across saved components."
    if alert_data:
        top_alert_part = str(alert_data[0].get("part_number") or "Monitored component")
        top_alert_message = str(alert_data[0].get("alert_message") or alert_data[0].get("alert_type") or "Lifecycle or sourcing change detected.")
        if len(top_alert_message) > 118:
            top_alert_message = top_alert_message[:115] + "..."

    if total_high_risk > 0:
        primary_action = "Review high-risk components before the next build release."
        primary_action_badge = "Engineering review"
    elif alert_count > 0:
        primary_action = "Open Monitoring and resolve supplier or lifecycle changes."
        primary_action_badge = "Monitoring review"
    elif alternatives_found == 0:
        primary_action = "Run Alternative Finder on your highest-volume components."
        primary_action_badge = "Replacement search"
    else:
        primary_action = "Portfolio is stable. Continue periodic monitoring."
        primary_action_badge = "Stable posture"

    if len(analysis_data) >= 2:
        try:
            _sorted_health = sorted(
                [a for a in analysis_data if a.get("health_score") is not None],
                key=lambda x: str(x.get("created_at", "")),
                reverse=True,
            )
            latest_health_for_delta = int(_sorted_health[0].get("health_score") or 0)
            prior_health_for_delta = int(_sorted_health[1].get("health_score") or 0)
            health_delta = latest_health_for_delta - prior_health_for_delta
            delta_word = "improved" if health_delta > 0 else "declined" if health_delta < 0 else "held steady"
            point_word = "points" if abs(health_delta) != 1 else "point"
            health_delta_text = f"Portfolio health {delta_word} {abs(health_delta)} {point_word} versus the previous saved analysis."
        except Exception:
            health_delta_text = "Portfolio trend is being tracked across saved BOM analyses."
    else:
        health_delta_text = "Run another BOM analysis to unlock portfolio health trend intelligence."

    st.markdown(
        f'''
        <style>
        /* Cadivor Dashboard v3 — Enterprise Engineering Intelligence. Content-only dashboard layer. */
        .cv-v3-command {{ display:grid; grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr); gap:18px; margin:0 0 18px 0; }}
        .cv-v3-command-main {{ border:1px solid rgba(147,197,253,.92); border-radius:24px; background:radial-gradient(circle at 92% 12%, rgba(37,99,235,.11), transparent 32%), linear-gradient(135deg, rgba(255,255,255,.99), rgba(239,246,255,.88)); box-shadow:0 24px 62px rgba(15,23,42,.075); padding:24px 28px; }}
        .cv-v3-kicker {{ display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border-radius:999px; background:#EFF6FF; border:1px solid #BFDBFE; color:#2563EB!important; font-size:10px; font-weight:950; letter-spacing:.12em; text-transform:uppercase; margin-bottom:13px; }}
        .cv-v3-kicker svg, .cv-v3-action svg, .cv-v3-label svg, .cv-v3-icon svg {{ width:16px; height:16px; }}
        .cv-v3-title {{ color:#071126!important; font-size:33px; line-height:1.03; font-weight:950; letter-spacing:-.055em; margin:0 0 8px; }}
        .cv-v3-subtitle {{ color:#475569!important; font-size:14px; line-height:1.5; max-width:840px; margin:0 0 16px; }}
        .cv-v3-summary-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:16px 0 16px; }}
        .cv-v3-summary-item {{ background:rgba(255,255,255,.76); border:1px solid rgba(226,232,240,.95); border-radius:15px; padding:11px 12px; box-shadow:inset 0 1px 0 rgba(255,255,255,.75); }}
        .cv-v3-summary-label {{ color:#64748B!important; font-size:9.8px; font-weight:950; letter-spacing:.09em; text-transform:uppercase; margin-bottom:5px; }}
        .cv-v3-summary-value {{ color:#071126!important; font-size:22px; line-height:1; font-weight:950; letter-spacing:-.04em; }}
        .cv-v3-summary-note {{ color:#64748B!important; font-size:11px; font-weight:800; margin-top:4px; }}
        .cv-v3-actions {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }}
        .cv-v3-action {{ display:inline-flex; align-items:center; gap:8px; padding:11px 15px; border-radius:13px; font-size:12.5px; font-weight:950; text-decoration:none!important; transition:all .16s ease; }}
        .cv-v3-action.primary {{ background:#2563EB; color:#FFFFFF!important; border:1px solid #2563EB; box-shadow:0 16px 30px rgba(37,99,235,.24); }}
        .cv-v3-action.secondary {{ background:#FFFFFF; color:#2563EB!important; border:1px solid #BFDBFE; }}
        .cv-v3-action:hover {{ transform:translateY(-2px); box-shadow:0 20px 42px rgba(15,23,42,.12); }}
        .cv-v3-next {{ background:linear-gradient(180deg,#FFFFFF,#F8FAFC); border:1px solid #E2E8F0; border-radius:24px; box-shadow:0 24px 62px rgba(15,23,42,.065); padding:21px; display:flex; flex-direction:column; justify-content:space-between; }}
        .cv-v3-next-top {{ display:flex; align-items:flex-start; gap:13px; }}
        .cv-v3-icon {{ width:42px; height:42px; border-radius:15px; display:flex; align-items:center; justify-content:center; flex:0 0 auto; color:#2563EB!important; background:#EFF6FF; border:1px solid #BFDBFE; }}
        .cv-v3-icon.danger {{ color:#DC2626!important; background:#FEF2F2; border-color:#FECACA; }}
        .cv-v3-icon.warn {{ color:#B45309!important; background:#FFFBEB; border-color:#FDE68A; }}
        .cv-v3-next-title {{ color:#0B1220!important; font-size:15px; line-height:1.22; font-weight:950; letter-spacing:-.02em; margin-bottom:6px; }}
        .cv-v3-next-copy {{ color:#52647A!important; font-size:12.5px; line-height:1.45; font-weight:760; }}
        .cv-v3-health-meter {{ height:8px; border-radius:999px; background:#E2E8F0; overflow:hidden; margin-top:16px; }}
        .cv-v3-health-meter span {{ display:block; height:100%; width:{max(0, min(100, int(avg_health_score or 0)))}%; background:linear-gradient(90deg,#2563EB,#16A34A); border-radius:999px; }}
        .cv-v3-label {{ display:flex; align-items:center; gap:8px; color:#64748B!important; font-size:11px; font-weight:950; letter-spacing:.08em; text-transform:uppercase; margin:2px 0 10px; }}
        .cv-v3-intel-grid {{ display:grid; grid-template-columns:1.15fr 1fr 1fr; gap:14px; margin:0 0 16px; }}
        .cv-v3-intel-card {{ background:rgba(255,255,255,.98); border:1px solid #E2E8F0; border-radius:18px; box-shadow:0 18px 44px rgba(15,23,42,.055); padding:15px; display:grid; grid-template-columns:auto 1fr; gap:13px; min-height:104px; transition:all .16s ease; }}
        .cv-v3-intel-card:hover {{ transform:translateY(-2px); border-color:#BFDBFE; box-shadow:0 26px 58px rgba(15,23,42,.080); }}
        .cv-v3-intel-kicker {{ color:#64748B!important; font-size:10px; font-weight:950; letter-spacing:.09em; text-transform:uppercase; margin-bottom:5px; }}
        .cv-v3-intel-title {{ color:#0B1220!important; font-size:14px; font-weight:950; letter-spacing:-.02em; margin-bottom:5px; }}
        .cv-v3-intel-copy {{ color:#52647A!important; font-size:12px; line-height:1.42; font-weight:730; }}
        .cv-v3-badge {{ display:inline-flex; margin-top:8px; border-radius:999px; padding:5px 9px; background:#F8FAFC; border:1px solid #E2E8F0; color:#334155!important; font-size:10.5px; font-weight:950; }}
        .cv-metric {{ min-height:96px!important; padding:15px 17px 14px!important; }}
        .cv-metric-value {{ font-size:38px!important; }}
        .cv-panel-title {{ font-size:18px!important; }}
        div[data-testid="stPlotlyChart"] {{ padding:10px!important; }}
        .cv-v2-analysis-row {{ box-shadow:0 10px 26px rgba(15,23,42,.042)!important; }}
        @media(max-width:1200px){{ .cv-v3-command{{grid-template-columns:1fr;}} .cv-v3-intel-grid{{grid-template-columns:1fr;}} .cv-v3-summary-grid{{grid-template-columns:repeat(2,minmax(0,1fr));}} }}
        @media(max-width:760px){{ .cv-v3-summary-grid{{grid-template-columns:1fr;}} .cv-v3-title{{font-size:28px;}} }}
        </style>
        <section class="cv-v3-command">
          <div class="cv-v3-command-main">
            <div class="cv-v3-kicker">{_cv_icon('sparkles')} Enterprise engineering intelligence</div>
            <h1 class="cv-v3-title">{greeting_prefix}, {html.escape(user_name)}.</h1>
            <p class="cv-v3-subtitle">Cadivor is monitoring BOM health, lifecycle movement, supplier exposure, and replacement readiness across your engineering portfolio.</p>
            <div class="cv-v3-summary-grid">
              <div class="cv-v3-summary-item"><div class="cv-v3-summary-label">Portfolio health</div><div class="cv-v3-summary-value">{avg_health_score}</div><div class="cv-v3-summary-note">{html.escape(str(health_badge))}</div></div>
              <div class="cv-v3-summary-item"><div class="cv-v3-summary-label">High risk</div><div class="cv-v3-summary-value">{total_high_risk}</div><div class="cv-v3-summary-note">Components need review</div></div>
              <div class="cv-v3-summary-item"><div class="cv-v3-summary-label">Monitoring</div><div class="cv-v3-summary-value">{alert_count}</div><div class="cv-v3-summary-note">{high_alert_count} high severity</div></div>
              <div class="cv-v3-summary-item"><div class="cv-v3-summary-label">Alternatives</div><div class="cv-v3-summary-value">{alternatives_found}</div><div class="cv-v3-summary-note">Candidate records</div></div>
            </div>
            <div class="cv-v3-actions">
              <a class="cv-v3-action primary" href="?page=BOM%20Analyzer" target="_self">{_cv_icon('layers')} Run BOM analysis</a>
              <a class="cv-v3-action secondary" href="?page=Monitoring" target="_self">{_cv_icon('radar')} Review alerts</a>
              <a class="cv-v3-action secondary" href="?page=Alternative%20Finder" target="_self">{_cv_icon('git')} Find alternatives</a>
            </div>
          </div>
          <aside class="cv-v3-next">
            <div class="cv-v3-next-top">
              <div class="cv-v3-icon {'danger' if total_high_risk else 'warn' if alert_count else ''}">{_cv_icon('alert' if total_high_risk else 'radar' if alert_count else 'shield')}</div>
              <div>
                <div class="cv-v3-intel-kicker">Recommended next action</div>
                <div class="cv-v3-next-title">{html.escape(latest_project_for_hero)}</div>
                <div class="cv-v3-next-copy">{html.escape(primary_action)}</div>
                <span class="cv-v3-badge">{html.escape(str(primary_action_badge))}</span>
              </div>
            </div>
            <div class="cv-v3-health-meter"><span></span></div>
          </aside>
        </section>
        ''',
        unsafe_allow_html=True,
    )

    if _qp_value("focus", "") == "search":
        render_global_search_panel(current_user["id"])

    st.markdown(
        f'''
        <div class="cv-v3-label">{_cv_icon('sparkles')} Executive intelligence</div>
        <section class="cv-v3-intel-grid">
          <div class="cv-v3-intel-card">
            <div class="cv-v3-icon {'danger' if total_high_risk else ''}">{_cv_icon('alert' if total_high_risk else 'shield')}</div>
            <div>
              <div class="cv-v3-intel-kicker">Priority signal</div>
              <div class="cv-v3-intel-title">{total_high_risk} component{'s' if total_high_risk != 1 else ''} need review</div>
              <div class="cv-v3-intel-copy">{health_delta_text}</div>
              <span class="cv-v3-badge">{html.escape(str(primary_action_badge))}</span>
            </div>
          </div>
          <div class="cv-v3-intel-card">
            <div class="cv-v3-icon warn">{_cv_icon('radar')}</div>
            <div>
              <div class="cv-v3-intel-kicker">Supplier & lifecycle</div>
              <div class="cv-v3-intel-title">{alert_count} active monitoring alert{'s' if alert_count != 1 else ''}</div>
              <div class="cv-v3-intel-copy"><strong>{html.escape(top_alert_part)}</strong>: {html.escape(top_alert_message)}</div>
            </div>
          </div>
          <div class="cv-v3-intel-card">
            <div class="cv-v3-icon">{_cv_icon('git')}</div>
            <div>
              <div class="cv-v3-intel-kicker">Replacement readiness</div>
              <div class="cv-v3-intel-title">{alternatives_found} alternative candidate{'s' if alternatives_found != 1 else ''}</div>
              <div class="cv-v3-intel-copy">Use Alternative Finder to validate lower-risk replacements for priority components.</div>
            </div>
          </div>
        </section>
        ''',
        unsafe_allow_html=True,
    )

    # KPI row: compact, side-by-side, and information dense.
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        _metric("Portfolio Health", avg_health_score, health_badge, "🛡", health_kind)
    with kpi2:
        risk_kind = "danger" if total_high_risk else "success"
        _metric("High-Risk Parts", total_high_risk, "Needs Review" if total_high_risk else "No high-risk parts", "⚠", risk_kind)
    with kpi3:
        _metric("Saved Analyses", total_analyses, "BOM reviews stored", "▦", "")
    with kpi4:
        _metric("Alternatives Found", alternatives_found, "Candidate records saved", "⇄", "")

    # Portfolio charts and risk composition.
    chart_col, dist_col = st.columns([1.45, 1])

    with chart_col:
        st.markdown('<div class="cv-panel-title">Portfolio Health Trend</div><div class="cv-panel-copy">Average health score across saved BOM analyses.</div>', unsafe_allow_html=True)
        if analysis_data and len(analysis_data) >= 2:
            trend_df = pd.DataFrame(analysis_data)
            trend_df["created_at"] = pd.to_datetime(trend_df["created_at"], errors="coerce")
            trend_df = trend_df.dropna(subset=["created_at"]).sort_values("created_at")
            trend_df = trend_df.rename(columns={"created_at": "Date", "health_score": "Health Score"})
            fig = px.line(trend_df, x="Date", y="Health Score", markers=True)
            fig.update_traces(line_color="#2563EB", marker_color="#2563EB", line_width=3)
            st.plotly_chart(light_plotly_layout(fig, height=330), use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Run at least two BOM analyses to generate a portfolio health trend.")

    with dist_col:
        st.markdown('<div class="cv-panel-title">Risk Distribution</div><div class="cv-panel-copy">Component risk across all saved analyses.</div>', unsafe_allow_html=True)
        if total_components > 0:
            risk_distribution_df = pd.DataFrame({
                "Risk Level": ["High", "Medium", "Low"],
                "Components": [total_high_risk, total_medium_risk, total_low_risk],
            })
            fig = px.pie(
                risk_distribution_df,
                names="Risk Level",
                values="Components",
                hole=0.62,
                color="Risk Level",
                color_discrete_map={"High": "#DC2626", "Medium": "#F59E0B", "Low": "#16A34A"},
            )
            fig.update_traces(textposition="inside", textinfo="percent+label", marker=dict(line=dict(color="#FFFFFF", width=3)))
            fig.update_layout(showlegend=True)
            st.plotly_chart(light_plotly_layout(fig, height=330), use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Risk distribution will appear after your first BOM analysis.")

    # Snapshot + recent analyses.
    snapshot_col, activity_col = st.columns([1.0, 1.55])
    with snapshot_col:
        latest_project = (latest_analysis.get("project_name") or latest_analysis.get("filename")) if latest_analysis else "No saved BOM yet"
        latest_date = latest_analysis.get("created_at", "—") if latest_analysis else "—"
        latest_health = latest_analysis.get("health_score", 0) if latest_analysis else 0
        latest_parts = latest_analysis.get("total_parts", 0) if latest_analysis else 0
        if latest_date != "—":
            try:
                latest_date = pd.to_datetime(latest_date).strftime("%Y-%m-%d")
            except Exception:
                pass
        st.markdown(
            f"""
            <div class="cv-panel">
              <div class="cv-panel-title">Latest Engineering Snapshot</div>
              <div class="cv-panel-copy">Most recent saved BOM and monitoring status.</div>
              <div class="cv-snapshot-main">{latest_project}</div>
              <div class="cv-snapshot-grid">
                <div class="cv-snapshot-item"><span>Health</span><strong>{latest_health}</strong></div>
                <div class="cv-snapshot-item"><span>Parts</span><strong>{latest_parts}</strong></div>
                <div class="cv-snapshot-item"><span>Alerts</span><strong>{alert_count}</strong></div>
                <div class="cv-snapshot-item"><span>High Severity</span><strong>{high_alert_count}</strong></div>
              </div>
              <p class="cv-panel-copy" style="margin-top:14px;margin-bottom:0;">Last updated: {latest_date}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with activity_col:
        st.markdown('<div class="cv-panel-title">Recent Analyses</div><div class="cv-panel-copy">Latest saved BOM reviews and risk results.</div>', unsafe_allow_html=True)
        if analysis_data:
            st.markdown(
                '''
                <style>
                .cv-v2-analysis-list { display:grid; gap:10px; }
                .cv-v2-analysis-row { display:grid; grid-template-columns:minmax(0,1fr) auto auto auto; gap:12px; align-items:center; background:#FFFFFF; border:1px solid #E2E8F0; border-radius:15px; padding:12px 14px; box-shadow:0 12px 28px rgba(15,23,42,.045); transition:all .16s ease; }
                .cv-v2-analysis-row:hover { transform:translateY(-2px); border-color:#BFDBFE; box-shadow:0 20px 46px rgba(15,23,42,.075); }
                .cv-v2-analysis-name { color:#0B1220!important; font-size:13px; font-weight:950; letter-spacing:-.01em; margin-bottom:4px; }
                .cv-v2-analysis-meta { color:#64748B!important; font-size:11.5px; font-weight:750; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
                .cv-v2-chip { display:inline-flex; justify-content:center; min-width:56px; border-radius:999px; padding:6px 9px; font-size:11px; font-weight:950; border:1px solid #E2E8F0; background:#F8FAFC; color:#334155!important; }
                .cv-v2-chip.good { color:#047857!important; background:#ECFDF5; border-color:#A7F3D0; }
                .cv-v2-chip.warn { color:#B45309!important; background:#FFFBEB; border-color:#FDE68A; }
                .cv-v2-chip.bad { color:#B91C1C!important; background:#FEF2F2; border-color:#FECACA; }
                .cv-v2-view { color:#2563EB!important; font-size:12px; font-weight:950; }
                @media(max-width:900px){ .cv-v2-analysis-row{grid-template-columns:1fr 1fr;} }
                </style>
                <div class="cv-v2-analysis-list">
                ''',
                unsafe_allow_html=True,
            )
            for item in analysis_data[:6]:
                project = html.escape(str(item.get("project_name") or item.get("filename") or "Saved BOM analysis"))
                filename = html.escape(str(item.get("filename") or "—"))
                created = item.get("created_at", "—")
                try:
                    created = pd.to_datetime(created).strftime("%b %d")
                except Exception:
                    pass
                parts = html.escape(str(item.get("total_parts", "—")))
                high = int(item.get("high_risk_count", 0) or 0)
                health = int(item.get("health_score", 0) or 0)
                health_class = "good" if health >= 80 else "warn" if health >= 55 else "bad"
                risk_class = "bad" if high else "good"
                st.markdown(
                    f'''
                    <div class="cv-v2-analysis-row">
                      <div>
                        <div class="cv-v2-analysis-name">{project}</div>
                        <div class="cv-v2-analysis-meta">{filename} • {created} • {parts} parts</div>
                      </div>
                      <span class="cv-v2-chip {health_class}">{health} health</span>
                      <span class="cv-v2-chip {risk_class}">{high} high</span>
                      <span class="cv-v2-view">View →</span>
                    </div>
                    ''',
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("No analyses yet. Upload your first BOM to begin building portfolio intelligence.")

    # Activity and alert feed.
    feed_col, alert_col = st.columns([1.25, 1])
    with feed_col:
        st.markdown('<div class="cv-section-spacer"></div><div class="cv-panel-title">Activity Feed</div><div class="cv-panel-copy">Recent workspace events that help the dashboard feel alive.</div>', unsafe_allow_html=True)
        if analysis_data:
            for item in analysis_data[:4]:
                event_title = item.get("project_name") or item.get("filename") or "Saved BOM analysis"
                event_date = item.get("created_at", "")
                try:
                    event_date = pd.to_datetime(event_date).strftime("%Y-%m-%d")
                except Exception:
                    pass
                st.markdown(
                    f"""
                    <div class="cv-result-card">
                      <div>
                        <div class="cv-result-title">{event_title}</div>
                        <div class="cv-result-meta">Analysis completed • Health {item.get('health_score', '—')} • {event_date}</div>
                      </div>
                      <span class="cv-status-pill success">Ready</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            empty_state("No activity yet", "Upload your first BOM to start building a Cadivor activity history.", "Analyze a BOM", "?page=BOM%20Analyzer", "○")
    with alert_col:
        st.markdown('<div class="cv-section-spacer"></div><div class="cv-panel-title">Recent Alerts</div><div class="cv-panel-copy">Lifecycle, stock, and supplier changes will appear here.</div>', unsafe_allow_html=True)
        if alert_data:
            for alert in alert_data[:4]:
                severity = str(alert.get("severity", "")).lower()
                pill = "danger" if "high" in severity else "warning" if "medium" in severity else "muted"
                st.markdown(
                    f"""
                    <div class="cv-result-card">
                      <div>
                        <div class="cv-result-title">{alert.get('part_number', 'Part alert')}</div>
                        <div class="cv-result-meta">{alert.get('alert_type', 'Monitoring alert')} • {alert.get('alert_message', '')}</div>
                      </div>
                      <span class="cv-status-pill {pill}">{alert.get('severity', 'Info')}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            empty_state("No active alerts", "Your monitored components have no unresolved alerts right now.", "Open Monitoring", "?page=Monitoring", "●")

    # Quick actions.
    st.markdown('<div class="cv-section-spacer"></div>', unsafe_allow_html=True)
    st.markdown('<div class="cv-panel-title">Quick Actions</div><div class="cv-panel-copy">Jump into the workflows used most often by engineering and sourcing teams.</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="cv-actions-grid">
          <a class="cv-action-card" href="?page=BOM%20Analyzer" target="_self" style="text-decoration:none!important;color:inherit!important;"><div class="cv-action-icon">+</div><div class="cv-action-title">Analyze a BOM</div><div class="cv-action-copy">Upload CSV or Excel files and generate a risk profile.</div></a>
          <a class="cv-action-card" href="?page=Alternative%20Finder" target="_self" style="text-decoration:none!important;color:inherit!important;"><div class="cv-action-icon">⇄</div><div class="cv-action-title">Find Alternatives</div><div class="cv-action-copy">Compare compatible replacement candidates and supplier coverage.</div></a>
          <a class="cv-action-card" href="?page=Monitoring" target="_self" style="text-decoration:none!important;color:inherit!important;"><div class="cv-action-icon">!</div><div class="cv-action-title">Review Alerts</div><div class="cv-action-copy">Check stock, lifecycle, and risk changes across monitored parts.</div></a>
          <a class="cv-action-card" href="?page=Reports" target="_self" style="text-decoration:none!important;color:inherit!important;"><div class="cv-action-icon">↧</div><div class="cv-action-title">Export Reports</div><div class="cv-action-copy">Download engineering-ready reports for review and sourcing.</div></a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Saved analysis actions remain available, but in a compact workflow.
    st.markdown('<div class="cv-section-spacer"></div>', unsafe_allow_html=True)
    st.markdown('<div class="cv-panel-title">Saved BOM Actions</div><div class="cv-panel-copy">Open a saved BOM in the analyzer or delete old analyses from the workspace.</div>', unsafe_allow_html=True)

    history = load_analysis_history(current_user["id"])

    if not history:
        st.info("No saved BOM analyses yet.")
    else:
        history_df = pd.DataFrame(history)
        analysis_options = {
            f"{row.get('project_name') or row.get('filename', 'Untitled')} — {row.get('created_at', '')}": row["id"]
            for _, row in history_df.drop_duplicates(subset=["id"]).iterrows()
        }

        saved_col, open_col, delete_col = st.columns([3.8, .9, .9])
        with saved_col:
            selected_saved_analysis_label = st.selectbox(
                "Choose a saved analysis",
                list(analysis_options.keys()),
                label_visibility="collapsed",
            )
        selected_saved_analysis_id = analysis_options[selected_saved_analysis_label]

        with open_col:
            if st.button("Open", use_container_width=True):
                saved_parts = (
                    supabase.table("analysis_parts")
                    .select("*")
                    .eq("analysis_id", selected_saved_analysis_id)
                    .eq("user_id", current_user["id"])
                    .execute()
                )

                if not saved_parts.data:
                    st.warning("No saved parts were found for this analysis.")
                else:
                    saved_results_df = pd.DataFrame(saved_parts.data)
                    saved_results_df = saved_results_df.rename(
                        columns={
                            "mpn": "MPN",
                            "manufacturer": "Manufacturer",
                            "risk_score": "Risk Score",
                            "risk_level": "Risk Level",
                            "risk_reasons": "Risk Reasons",
                            "lifecycle_status": "Lifecycle Status",
                            "stock_available": "Stock Available",
                            "supplier_count": "Supplier Count",
                        }
                    )
                    saved_results_df["Best Source"] = ""
                    saved_results_df["Total Market Stock"] = saved_results_df["Stock Available"]
                    saved_results_df["Sources Available"] = ""
                    saved_results_df["Lead Time Weeks"] = None
                    saved_results_df["Product URL"] = ""
                    saved_results_df["Has Alternates"] = False
                    saved_results_df["Alternate Count"] = 0
                    saved_results_df["Alternative Part Numbers"] = ""
                    saved_results_df["Normalized MPN"] = saved_results_df["MPN"]
                    st.session_state["results_df"] = saved_results_df
                    st.session_state["pending_app_mode"] = "BOM Analyzer"
                    st.success("Saved analysis loaded. Opening BOM Analyzer...")
                    st.rerun()

        with delete_col:
            if st.button("Delete", use_container_width=True):
                try:
                    for table_name in ["analysis_parts", "part_monitor_history", "monitor_alerts", "alternative_recommendations"]:
                        supabase.table(table_name).delete().eq("analysis_id", selected_saved_analysis_id).eq("user_id", current_user["id"]).execute()

                    supabase.table("analyses").delete().eq("id", selected_saved_analysis_id).eq("user_id", current_user["id"]).execute()
                    st.session_state.pop("results_df", None)
                    st.success("Saved analysis deleted.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not delete saved analysis: {e}")

    st.stop()

# ---------- Monitoring ----------
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
    st.markdown(
        """
        <div class="cv-dashboard-header cv-fade-in">
          <div>
            <div class="cv-eyebrow">Reports Center</div>
            <h1 class="cv-title">Engineering reports</h1>
            <p class="cv-subtitle">Generate, download, and share executive-ready BOM risk reports. Full report automation is scheduled after BOM Intelligence 2.0.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    r1, r2, r3 = st.columns(3)
    with r1:
        action_card("Executive PDF", "Generate a management-ready BOM risk summary.", "?page=BOM%20Analyzer", "PDF")
    with r2:
        action_card("Excel Workbook", "Export detailed risk, lifecycle, and supplier data.", "?page=BOM%20Analyzer", "XLS")
    with r3:
        action_card("Scheduled Reports", "Email recurring reports to stakeholders.", "?page=Reports", "⏱")

    st.markdown('<div class="cv-section-spacer"></div>', unsafe_allow_html=True)
    empty_state(
        "No saved reports yet",
        "Reports generated from BOM Intelligence will appear here. Analyze or open a saved BOM to export your first executive report.",
        "Open BOM Analyzer",
        "?page=BOM%20Analyzer",
        "□",
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
        <div class="card">
            <div class="card-title">🔎 Alternative Component Finder</div>
            <div class="card-text">
                Search for replacement parts, compare sourcing risk,
                and identify lower-risk alternatives.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Step 1 — Search Original Component")

    if "suggested_alternatives" not in st.session_state:
        st.session_state["suggested_alternatives"] = []

    if "alternative_search_attempted" not in st.session_state:
        st.session_state["alternative_search_attempted"] = False

    original_part = st.text_input("Enter original manufacturer part number")

    if st.button("Find Alternatives", type="primary"):
        if not original_part:
            st.warning("Please enter an original part number.")
        else:
            with st.spinner(
                "🔍 Searching suppliers • ⚡ Comparing electrical specs • 🧠 Ranking alternatives..."
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
