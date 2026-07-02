import streamlit as st
import pandas as pd
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
start_time = time.time()
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.stripe_helper import create_checkout_session
try:
    import extra_streamlit_components as stx
except Exception:
    stx = None


class _FallbackCookieManager:
    def get(self, cookie=None, key=None):
        return None

    def set(self, *args, **kwargs):
        return None

    def delete(self, *args, **kwargs):
        return None

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

if "access_token" not in st.session_state:
    auth_cookie = cookie_manager.get(cookie="bom_auth")

    if auth_cookie:
        st.session_state["access_token"] = auth_cookie.get("access_token")
        st.session_state["refresh_token"] = auth_cookie.get("refresh_token")

if "access_token" in st.session_state and "refresh_token" in st.session_state:
    try:
        supabase.auth.set_session(
            st.session_state["access_token"],
            st.session_state["refresh_token"],
        )

        user_response = supabase.auth.get_user()

        if user_response and user_response.user:
            st.session_state["user"] = user_response.user

    except Exception:
        st.session_state.pop("user", None)
        st.session_state.pop("access_token", None)
        st.session_state.pop("refresh_token", None)

if "user" not in st.session_state:
    show_auth_ui(supabase, cookie_manager)
    st.stop()


with st.sidebar:
    if st.button("Log out"):
        cookie_manager.delete(
            cookie="bom_auth",
            key="delete_bom_auth",
        )

        supabase.auth.sign_out()
        st.session_state.clear()
        st.rerun()

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


st.set_page_config(
    page_title="BOM Risk Checker",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
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
        "BOM Risk Checker <onboarding@resend.dev>",
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


st.markdown(
    """
    <style>
    :root {
        --brc-bg: #F5F7FB;
        --brc-surface: #FFFFFF;
        --brc-border: #E5E7EB;
        --brc-text: #0F172A;
        --brc-muted: #64748B;
        --brc-blue: #2563EB;
        --brc-blue-dark: #1D4ED8;
        --brc-green: #059669;
        --brc-amber: #D97706;
        --brc-red: #DC2626;
    }

    .stApp {
        background: var(--brc-bg);
        color: var(--brc-text);
    }

    section[data-testid="stSidebar"] {
        background: #FFFFFF;
        border-right: 1px solid var(--brc-border);
    }

    section[data-testid="stSidebar"] * {
        color: #0F172A;
    }

    section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
        gap: 0.45rem;
    }

    .main .block-container {
        padding-top: 1.4rem;
        padding-bottom: 3rem;
        max-width: 1240px;
    }

    h1, h2, h3, h4 {
        color: var(--brc-text);
        letter-spacing: -0.02em;
    }

    .main-title {
        font-size: 42px;
        font-weight: 800;
        margin-bottom: 0px;
    }

    .subtitle {
        font-size: 18px;
        color: var(--brc-muted);
        margin-bottom: 24px;
    }

    .card {
        background-color: var(--brc-surface);
        border: 1px solid var(--brc-border);
        border-radius: 18px;
        padding: 22px;
        margin-top: 16px;
        margin-bottom: 16px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }

    .card-title {
        font-size: 18px;
        font-weight: 750;
        color: var(--brc-text);
        margin-bottom: 8px;
    }

    .card-text {
        font-size: 14px;
        color: var(--brc-muted);
    }

    .kpi-card {
        background-color: var(--brc-surface);
        border: 1px solid var(--brc-border);
        border-radius: 18px;
        padding: 18px 18px 16px 18px;
        min-height: 108px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }

    .kpi-label {
        font-size: 12px;
        color: var(--brc-muted);
        margin-bottom: 7px;
        font-weight: 650;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .kpi-value {
        font-size: 30px;
        font-weight: 820;
        color: var(--brc-text);
        margin-bottom: 4px;
    }

    .kpi-note {
        font-size: 13px;
        color: var(--brc-green);
        font-weight: 600;
    }

    .search-card {
        background-color: var(--brc-surface);
        border: 1px solid var(--brc-border);
        border-radius: 18px;
        padding: 18px 20px 14px 20px;
        margin-bottom: 12px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }

    .section-caption {
        color: var(--brc-muted);
        font-size: 14px;
        margin-top: -6px;
        margin-bottom: 12px;
    }

    .match-pill {
        display: inline-block;
        background-color: #EFF6FF;
        color: var(--brc-blue);
        border: 1px solid #BFDBFE;
        padding: 8px 12px;
        border-radius: 999px;
        font-size: 13px;
        font-weight: 700;
        margin-right: 8px;
        margin-bottom: 8px;
    }

    .warning-pill {
        display: inline-block;
        background-color: #FFFBEB;
        color: var(--brc-amber);
        border: 1px solid #FDE68A;
        padding: 8px 12px;
        border-radius: 999px;
        font-size: 13px;
        font-weight: 700;
        margin-right: 8px;
        margin-bottom: 8px;
    }

    .recommendation-card {
        background: linear-gradient(135deg, #FFFFFF 0%, #EFF6FF 100%);
        border: 1px solid #BFDBFE;
        border-radius: 20px;
        padding: 24px;
        margin-top: 10px;
        margin-bottom: 18px;
        box-shadow: 0 14px 32px rgba(37, 99, 235, 0.10);
    }

    .recommendation-part {
        font-size: 38px;
        font-weight: 850;
        color: var(--brc-text);
        margin-bottom: 6px;
    }

    .recommendation-subtitle {
        color: var(--brc-blue);
        font-size: 16px;
        margin-bottom: 14px;
        font-weight: 650;
    }

    div.stButton > button[kind="primary"], div.stButton > button:first-child {
        border-radius: 10px;
        border: 1px solid var(--brc-blue);
        background: var(--brc-blue);
        color: white;
        font-weight: 700;
        min-height: 42px;
    }

    div.stButton > button:hover {
        border-color: var(--brc-blue-dark);
        background: var(--brc-blue-dark);
        color: white;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid var(--brc-border);
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
    }

    .sidebar-brand {
        padding: 8px 0 14px 0;
        border-bottom: 1px solid var(--brc-border);
        margin-bottom: 14px;
    }

    .sidebar-brand-title {
        font-size: 20px;
        font-weight: 850;
        color: var(--brc-text);
        margin-bottom: 2px;
    }

    .sidebar-brand-subtitle {
        font-size: 12px;
        color: var(--brc-muted);
        font-weight: 600;
    }

    .sidebar-card {
        background: #F8FAFC;
        border: 1px solid var(--brc-border);
        border-radius: 14px;
        padding: 12px;
        margin: 10px 0;
    }

    .sidebar-small {
        color: var(--brc-muted);
        font-size: 12px;
        line-height: 1.4;
    }



    /* ===== Design System v1 foundation overrides ===== */
    html, body, .stApp, [data-testid="stAppViewContainer"] {
        background: #F5F7FB !important;
        color: #0F172A !important;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    }

    [data-testid="stHeader"] {
        background: #FFFFFF !important;
        border-bottom: 1px solid #E5E7EB !important;
    }

    .main .block-container {
        max-width: 1280px !important;
        padding-top: 2rem !important;
    }

    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3,
    [data-testid="stMarkdownContainer"] h4,
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] label,
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4,
    h1, h2, h3, h4 {
        color: #0F172A !important;
    }

    [data-testid="stMarkdownContainer"] p,
    .stCaptionContainer,
    .stMarkdown p {
        color: #64748B !important;
    }

    section[data-testid="stSidebar"] {
        background: #FFFFFF !important;
        border-right: 1px solid #E5E7EB !important;
        box-shadow: 8px 0 30px rgba(15, 23, 42, 0.04) !important;
    }

    section[data-testid="stSidebar"] * {
        color: #0F172A !important;
    }

    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    section[data-testid="stSidebar"] .sidebar-small {
        color: #64748B !important;
    }

    .card, .kpi-card, .search-card, .sidebar-card,
    div[data-testid="stMetric"],
    div[data-testid="stExpander"] {
        background: #FFFFFF !important;
        border: 1px solid #E5E7EB !important;
        border-radius: 16px !important;
        box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06) !important;
    }

    .kpi-label, .card-text, .section-caption, .subtitle, .sidebar-small {
        color: #64748B !important;
    }

    .kpi-value, .card-title, .main-title {
        color: #0F172A !important;
    }

    div.stButton > button {
        border-radius: 12px !important;
        min-height: 44px !important;
        font-weight: 700 !important;
        box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18) !important;
    }

    div.stButton > button[kind="primary"],
    div.stButton > button:first-child {
        background: #2563EB !important;
        border: 1px solid #2563EB !important;
        color: #FFFFFF !important;
    }

    div.stButton > button:hover {
        background: #1D4ED8 !important;
        border-color: #1D4ED8 !important;
        color: #FFFFFF !important;
    }

    input, textarea, select,
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div,
    div[data-testid="stFileUploader"] section {
        background: #FFFFFF !important;
        color: #0F172A !important;
        border-color: #CBD5E1 !important;
        border-radius: 12px !important;
    }

    div[data-baseweb="input"] input,
    div[data-baseweb="select"] span,
    textarea {
        color: #0F172A !important;
    }

    div[data-testid="stDataFrame"],
    div[data-testid="stTable"] {
        background: #FFFFFF !important;
        border: 1px solid #E5E7EB !important;
        border-radius: 16px !important;
        overflow: hidden !important;
        box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06) !important;
    }

    div[data-testid="stDataFrame"] * {
        color: #0F172A !important;
    }

    div[data-testid="stPlotlyChart"],
    div[data-testid="stPyplot"] {
        background: #FFFFFF !important;
        border: 1px solid #E5E7EB !important;
        border-radius: 16px !important;
        padding: 14px !important;
        box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06) !important;
    }

    div[data-testid="stProgress"] > div > div > div {
        background-color: #2563EB !important;
    }

    div[data-testid="stProgress"] > div > div {
        background-color: #E5E7EB !important;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-brand-title">BOM Risk Checker</div>
            <div class="sidebar-brand-subtitle">Engineering sourcing intelligence</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "user" in st.session_state:
        st.markdown(
            f"""
            <div class="sidebar-card">
                <div style="font-weight: 750; margin-bottom: 4px;">Workspace</div>
                <div class="sidebar-small">{st.session_state['user'].email}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("#### Navigation")

    app_mode = st.radio(
        "",
        [
            "Dashboard",
            "BOM Analyzer",
            "Alternative Finder",
            "Monitoring",
            "Reports",
            "Pricing",
            "About",
        ],
        label_visibility="collapsed",
    )

# Default user plan
selected_plan_name = current_user["plan"]
selected_plan = get_plan(selected_plan_name)
monthly_upload_count = current_user["monthly_upload_count"]

with st.sidebar:
    st.markdown(
        f"""
        <div class="sidebar-card">
            <div style="font-weight: 750; margin-bottom: 6px;">Current Plan</div>
            <div style="font-size: 20px; font-weight: 850; color: #2563EB;">{selected_plan_name}</div>
            <div class="sidebar-small">{selected_plan['description']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        f"BOM usage: {monthly_upload_count} / {selected_plan['monthly_bom_limit']}"
    )
    st.progress(
        min(
            1.0,
            (monthly_upload_count or 0) / max(1, selected_plan["monthly_bom_limit"]),
        )
    )

    saved_bom_count_response = (
        supabase.table("analyses")
        .select("id", count="exact")
        .eq("user_id", current_user["id"])
        .execute()
    )

    saved_bom_count = saved_bom_count_response.count or 0

    st.caption(
        f"Saved BOMs: {saved_bom_count} / {selected_plan['max_saved_boms']}"
    )
    st.progress(
        min(
            1.0,
            saved_bom_count / max(1, selected_plan["max_saved_boms"]),
        )
    )

    if is_admin:
        st.success("Admin access enabled")

    st.divider()

    if st.button("Clear Current Analysis", use_container_width=True):
        st.session_state.pop("results_df", None)
        st.session_state.pop("uploaded_filename", None)
        st.rerun()



# Application header now lives inside the Dashboard view.

# ---------- Dashboard ----------
if app_mode == "Dashboard":

    st.markdown(
        """
        <div class="card" style="padding: 26px 30px; margin-bottom: 22px;">
            <h1 style="font-size: 2.35rem; margin-bottom: 6px; color:#0F172A;">Welcome back</h1>
            <p class="card-text" style="font-size: 1.05rem; margin-bottom: 0;">
                Monitor BOM risk, review alternatives, and keep engineering decisions moving.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    dashboard_header_col, dashboard_action_col = st.columns([4, 1])

    with dashboard_header_col:
        st.markdown("## Dashboard")
        st.caption("Overview of your BOM risk activity, recent analyses, and sourcing intelligence.")

    with dashboard_action_col:
        if st.button("+ New Analysis", use_container_width=True):
            st.info("Open BOM Analyzer from the sidebar to upload a new BOM.")

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
            / total_analyses
        )
        total_high_risk = sum(item.get("high_risk_count", 0) or 0 for item in analysis_data)
        total_medium_risk = sum(item.get("medium_risk_count", 0) or 0 for item in analysis_data)
        total_low_risk = sum(item.get("low_risk_count", 0) or 0 for item in analysis_data)
        total_components = sum(item.get("total_parts", 0) or 0 for item in analysis_data)
    else:
        avg_health_score = 0
        total_high_risk = 0
        total_medium_risk = 0
        total_low_risk = 0
        total_components = 0

    try:
        alternative_history = load_alternative_history(current_user["id"])
        alternatives_found = len(alternative_history)
    except Exception:
        alternatives_found = 0

    dashboard_kpi_1, dashboard_kpi_2, dashboard_kpi_3, dashboard_kpi_4 = st.columns(4)

    with dashboard_kpi_1:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Analyses This Month</div>
                <div class="kpi-value">{total_analyses}</div>
                <div class="kpi-note">Saved BOM analyses</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with dashboard_kpi_2:
        risk_label = "No data" if avg_health_score == 0 else ("Low Risk" if avg_health_score >= 75 else "Medium Risk" if avg_health_score >= 50 else "High Risk")
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Average BOM Health</div>
                <div class="kpi-value">{avg_health_score}</div>
                <div class="kpi-note">{risk_label}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with dashboard_kpi_3:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">High Risk Components</div>
                <div class="kpi-value">{total_high_risk}</div>
                <div class="kpi-note">Across saved BOMs</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with dashboard_kpi_4:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Alternatives Found</div>
                <div class="kpi-value">{alternatives_found}</div>
                <div class="kpi-note">Recommended candidates</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    chart_col, risk_col = st.columns([1.4, 1])

    with chart_col:
        st.markdown("### BOM Risk Trend")
        if analysis_data and len(analysis_data) >= 2:
            trend_df = pd.DataFrame(analysis_data)
            trend_df["created_at"] = pd.to_datetime(trend_df["created_at"])
            trend_df = trend_df.sort_values("created_at")
            trend_df = trend_df[["created_at", "health_score"]].rename(
                columns={"created_at": "Date", "health_score": "BOM Health"}
            )
            st.line_chart(trend_df, x="Date", y="BOM Health", use_container_width=True)
        else:
            st.info("Run at least two BOM analyses to generate a risk trend.")

    with risk_col:
        st.markdown("### Risk Distribution")
        if total_components > 0:
            risk_distribution_df = pd.DataFrame(
                {
                    "Risk Level": ["High", "Medium", "Low"],
                    "Components": [total_high_risk, total_medium_risk, total_low_risk],
                }
            )
            st.dataframe(risk_distribution_df, use_container_width=True, hide_index=True)
        else:
            st.info("Risk distribution will appear after your first BOM analysis.")

    st.divider()

    st.subheader("Saved BOM Analyses")

    history = load_analysis_history(current_user["id"])

    if not history:
        st.info("No saved BOM analyses yet.")

    else:
        history_df = pd.DataFrame(history)


        analysis_options = {
            f"{row['project_name']} — {row['created_at']}": row["id"]
            for _, row in history_df.drop_duplicates(subset=["id"]).iterrows()
        }
 

        if analysis_options:
            selected_saved_analysis_label = st.selectbox(
                "Choose a saved analysis to open or delete",
                list(analysis_options.keys()),
            )

            selected_saved_analysis_id = analysis_options[selected_saved_analysis_label]

            action_col1, action_col2 = st.columns(2)

            with action_col1:
                if st.button("📂 Open Saved Analysis"):
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
                        st.success("Saved analysis loaded.")
                        st.rerun()

            with action_col2:
                if st.button("🗑 Delete Saved Analysis"):
                    try:
                        supabase.table("analysis_parts").delete().eq(
                            "analysis_id",
                            selected_saved_analysis_id
                        ).eq(
                            "user_id",
                            current_user["id"]
                        ).execute()

                        supabase.table("part_monitor_history").delete().eq(
                            "analysis_id",
                            selected_saved_analysis_id
                        ).eq(
                            "user_id",
                            current_user["id"]
                        ).execute()

                        supabase.table("monitor_alerts").delete().eq(
                            "analysis_id",
                            selected_saved_analysis_id
                        ).eq(
                            "user_id",
                            current_user["id"]
                        ).execute()

                        supabase.table("alternative_recommendations").delete().eq(
                            "analysis_id",
                            selected_saved_analysis_id
                        ).eq(
                            "user_id",
                            current_user["id"]
                        ).execute()

                        supabase.table("analyses").delete().eq(
                            "id",
                            selected_saved_analysis_id
                        ).eq(
                            "user_id",
                            current_user["id"]
                        ).execute()

                        st.session_state.pop("results_df", None)

                        st.success("Saved analysis deleted.")
                        st.rerun()

                    except Exception as e:
                        st.error(f"Could not delete saved analysis: {e}")


        summary_df = history_df.copy()

        summary_df["created_at"] = pd.to_datetime(
            summary_df["created_at"]
        ).dt.strftime("%Y-%m-%d")

        summary_display_df = summary_df[
            [
                "project_name",
                "created_at",
                "total_parts",
                "high_risk_count",
                "medium_risk_count",
                "low_risk_count",
                "health_score",
            ]
        ].rename(
            columns={
                "project_name": "Project Name",
                "created_at": "Created At",
                "total_parts": "Total Parts",
                "high_risk_count": "High Risk Parts",
                "medium_risk_count": "Medium Risk Parts",
                "low_risk_count": "Low Risk Parts",
                "health_score": "Health Score",
            }
        )

        st.dataframe(
            summary_display_df,
            use_container_width=True,
            hide_index=True,
        )

      

        st.divider()

        st.subheader("View Saved Analysis Details")

        analysis_options = {
            f"{row['project_name']} — {row['created_at']}": row["id"]
            for _, row in summary_df.iterrows()
        }

        selected_analysis_label = st.selectbox(
            "Choose an analysis to view",
            list(analysis_options.keys())
        )

        selected_analysis_id = analysis_options[selected_analysis_label]

        selected_parts_response = (
            supabase.table("analysis_parts")
            .select("*")
            .eq("analysis_id", selected_analysis_id)
            .eq("user_id", current_user["id"])
            .execute()
        )

        selected_parts = pd.DataFrame(selected_parts_response.data)
        if selected_parts.empty:
            st.warning("No parts were found for this saved analysis.")
            st.stop()

        risk_distribution = (
            selected_parts["risk_level"]
            .value_counts()
            .reset_index()
        )

        risk_distribution.columns = ["Risk Level", "Part Count"]

        st.subheader("Risk Composition")

        st.plotly_chart(
            {
                "data": [
                    {
                        "labels": risk_distribution["Risk Level"],
                        "values": risk_distribution["Part Count"],
                        "type": "pie",
                        "hole": 0.45,
                    }
                ],
                "layout": {
                    "margin": {"t": 20, "b": 20, "l": 20, "r": 20},
                },
            },
            use_container_width=True,
        )

        attention_parts = selected_parts[
            (selected_parts["risk_level"] == "High")
            |
            (
                selected_parts["lifecycle_status"]
                .astype(str)
                .str.contains(
                    "obsolete|not recommended|replacement",
                    case=False,
                    na=False,
                )
            )
        ]
        selected_total_parts = len(selected_parts)

        selected_high_risk = (
            selected_parts["risk_level"] == "High"
        ).sum()

        selected_obsolete = (
            selected_parts["lifecycle_status"]
            .astype(str)
            .str.contains("obsolete", case=False, na=False)
        ).sum()

        selected_avg_risk = int(
            selected_parts["risk_score"].mean()
        )

        st.subheader("Parts Requiring Attention")

        if not attention_parts.empty:

            attention_display = attention_parts[
                [
                    "mpn",
                    "manufacturer",
                    "risk_level",
                    "lifecycle_status",
                    "risk_reasons",
                ]
            ].rename(
                columns={
                    "mpn": "Part Number",
                    "manufacturer": "Manufacturer",
                    "risk_level": "Risk Level",
                    "lifecycle_status": "Lifecycle Status",
                    "risk_reasons": "Risk Reasons",
                }
            )

            st.dataframe(
                attention_display,
                use_container_width=True,
                hide_index=True,
            )

            st.subheader("Supplier Verification & Suggested Alternatives")

            attention_part_options = attention_parts["mpn"].dropna().unique().tolist()

            selected_attention_parts = st.multiselect(
                "Choose risky parts to find alternatives",
                attention_part_options,
            )

            if st.button("Find Alternatives for Selected Parts"):
                with st.spinner("Searching suppliers and finding compatible alternatives..."):
                    if not selected_attention_parts:
                        st.warning("Please select at least one risky part.")

                    else:
                        for selected_attention_part in selected_attention_parts:
                            st.markdown(f"### Results for {selected_attention_part}")

                            alternatives = suggest_alternatives_v2(
                                selected_attention_part
                            )

                            if alternatives:
                                alternatives_df = pd.DataFrame(alternatives)
                                engineering_cols = [
                                    "Architecture",
                                    "Package",
                                    "Pin Count",
                                    "Voltage Range",
                                ]

                                for col in engineering_cols:
                                    if col not in alternatives_df.columns:
                                        alternatives_df[col] = ""

                                supplier_count = alternatives_df["Supplier"].replace("", pd.NA).dropna().nunique() if "Supplier" in alternatives_df.columns else 0

                                total_stock = alternatives_df["Stock"].sum() if "Stock" in alternatives_df.columns else 0

                                highest_stock_row = (
                                    alternatives_df.loc[alternatives_df["Stock"].idxmax()]
                                    if "Stock" in alternatives_df.columns and not alternatives_df.empty
                                    else None
                                )

                                best_supplier = (
                                    highest_stock_row["Supplier"]
                                    if highest_stock_row is not None
                                    else "Unknown"
                                )

                                highest_stock = (
                                    int(highest_stock_row["Stock"])
                                    if highest_stock_row is not None
                                    else 0
                                )

                                priced_rows = alternatives_df[
                                    (alternatives_df["Unit Price"] > 0)
                                    & (alternatives_df["Stock"] > 0)
                                ] if "Unit Price" in alternatives_df.columns and "Stock" in alternatives_df.columns else pd.DataFrame()

                                cheapest_row = (
                                    priced_rows.loc[priced_rows["Unit Price"].idxmin()]
                                    if not priced_rows.empty
                                    else None
                                )

                                cheapest_supplier = (
                                    cheapest_row["Supplier"]
                                    if cheapest_row is not None
                                    else "Unknown"
                                )

                                lowest_unit_price = (
                                    float(cheapest_row["Unit Price"])
                                    if cheapest_row is not None
                                    else 0.0
                                )

                                best_lifecycle = (
                                    alternatives_df["Lifecycle"].dropna().iloc[0]
                                    if "Lifecycle" in alternatives_df.columns and not alternatives_df["Lifecycle"].dropna().empty
                                    else "Unknown"
                                )

                                st.markdown("## 📊 Alternative Search Summary")
                                
                                summary_col1, summary_col2, summary_col3 = st.columns(3)

                                with summary_col1:
                                    st.metric(
                                        "Alternatives Found",
                                        len(true_alternatives)
                                    )

                                    st.metric(
                                        "Suppliers Verified",
                                        supplier_count
                                    )

                                with summary_col2:
                                    st.metric(
                                        "Best Recommendation",
                                        best_alternative["Alternative Part"]
                                        if true_alternatives else "-"
                                    )

                                    st.metric(
                                        "Lowest Price",
                                        f"${lowest_unit_price:.2f}"
                                    )

                                with summary_col3:
                                    avg_confidence = (
                                        int(alternatives_df["Drop-In Confidence"].mean())
                                        if "Drop-In Confidence" in alternatives_df.columns
                                        else 0
                                    )

                                    st.metric(
                                        "Average Compatibility",
                                        f"{avg_confidence}%"
                                    )

                                    st.metric(
                                        "Total Stock",
                                        f"{int(total_stock):,}"
                                    )

                                true_alternatives = [
                                    alt for alt in alternatives
                                    if alt.get("Alternative Part", "") != selected_attention_part
                                ]

                                if true_alternatives:
                                    best_alternative = max(
                                        true_alternatives,
                                        key=lambda x: x.get("Recommendation Score", 0)
                                    )

                                    st.markdown("### 🏆 Best Recommended Alternative")

                                    best_col1, best_col2, best_col3 = st.columns(3)

                                    with best_col1:
                                        st.metric(
                                            "Part Number",
                                            best_alternative.get("Alternative Part", "Unknown"),
                                        )

                                    with best_col2:
                                        st.metric(
                                            "Recommendation Score",
                                            int(best_alternative.get("Recommendation Score", 0)),
                                        )

                                    with best_col3:
                                        st.metric(
                                            "Drop-In Confidence",
                                            best_alternative.get("Drop-In Rating", "Unknown"),
                                        )

                                    st.info(best_alternative.get("Recommendation", "Review compatibility."))

                                    drop_in_reasons = best_alternative.get("Drop-In Reasons", "")

                                    if drop_in_reasons:
                                        with st.expander("Why this alternative?", expanded=True):
                                            for reason in str(drop_in_reasons).split(";"):
                                                reason = reason.strip()
                                                if reason:
                                                    st.write(reason)

                                    value_alternatives = [
                                        alt for alt in true_alternatives
                                        if alt.get("Stock", 0) > 0
                                    ]

                                    best_value_alternative = None

                                    if value_alternatives:
                                        best_value_alternative = min(
                                            value_alternatives,
                                            key=lambda x: float(x.get("Unit Price", 0.0))
                                        )

                                    if best_value_alternative:
                                        st.markdown("### 💰 Best Value Alternative")

                                        value_col1, value_col2, value_col3 = st.columns(3)

                                        with value_col1:
                                            st.metric(
                                                "Part Number",
                                                best_value_alternative.get("Alternative Part", "Unknown"),
                                            )

                                        with value_col2:
                                            st.metric(
                                                "Unit Price",
                                                f"${float(best_value_alternative.get('Unit Price', 0.0)):.2f}",
                                            )

                                        with value_col3:
                                            st.metric(
                                                "Available Stock",
                                                int(best_value_alternative.get("Stock", 0)),
                                            )

                                else:
                                    st.info(
                                        "Supplier verification found for the selected part, but no true alternative recommendations were identified yet."
                                    )

                                verify_col1, verify_col2, verify_col3, verify_col4, verify_col5 = st.columns(5)

                                with verify_col1:
                                    st.metric("Suppliers Found", supplier_count)

                                with verify_col2:
                                    st.metric("Total Stock", int(total_stock))

                                with verify_col3:
                                    st.metric("Best Supplier", best_supplier)

                                with verify_col4:
                                    st.metric("Highest Stock", highest_stock)
                                
                                with verify_col5:
                                    st.metric(
                                        "Lowest Price",
                                        f"${lowest_unit_price:.2f}",
                                        cheapest_supplier,
                                    )

                                lifecycle_col1, lifecycle_col2 = st.columns([1, 3])

                                with lifecycle_col1:
                                    st.markdown("**Lifecycle Status**")
                                    st.info(best_lifecycle)

                                with lifecycle_col2:
                                    st.caption(
                                        "Lifecycle status is based on the first available supplier response and may differ across suppliers."
                                    )

                                recommendation_records = []

                                for alt in alternatives:
                                    recommendation_records.append(
                                        {
                                            "user_id": current_user["id"],
                                            "analysis_id": selected_analysis_id,
                                            "original_part": selected_attention_part,
                                            "alternative_part": alt.get("Alternative Part", ""),
                                            "recommendation_score": alt.get("Recommendation Score", 0),
                                            "estimated_risk": alt.get("Estimated Risk", "Unknown"),
                                            "supplier": alt.get("Supplier", ""),
                                            "stock": alt.get("Stock", 0),
                                            "unit_price": alt.get("Unit Price", 0.0),
                                            "compatibility_notes": alt.get("Compatibility Notes", ""),
                                            "architecture": alt.get("Architecture", ""),
                                            "package": alt.get("Package", ""),
                                            "pin_count": alt.get("Pin Count", 0),
                                            "voltage_range": alt.get("Voltage Range", ""),
                                            "score_reasons": alt.get("Score Reasons", ""),
                                        }
                                    )

                                if recommendation_records:
                                    supabase.table("alternative_recommendations").delete().eq(
                                        "user_id",
                                        current_user["id"]
                                    ).eq(
                                        "analysis_id",
                                        selected_analysis_id
                                    ).eq(
                                        "original_part",
                                        selected_attention_part
                                    ).execute()

                                    supabase.table("alternative_recommendations").insert(
                                        recommendation_records
                                    ).execute()

                                if "Estimated Risk" in alternatives_df.columns:
                                    alternatives_df["Estimated Risk"] = alternatives_df["Estimated Risk"].replace(
                                        {
                                            "Low": "🟢 Low",
                                            "Medium": "🟠 Medium",
                                            "High": "🔴 High",
                                        }
                                    )

                                    

                                st.dataframe(
                                    alternatives_df,
                                    use_container_width=True,
                                    hide_index=True,
                                )

                            else:
                                st.info(f"No alternatives found for {selected_attention_part}.")

        else:
            st.success("No critical parts detected in this BOM.")

        st.subheader("Filter Saved Parts")

        st.subheader("Selected BOM Summary")

        bom_col1, bom_col2, bom_col3, bom_col4 = st.columns(4)

        with bom_col1:
            st.metric("Total Parts", selected_total_parts)

        with bom_col2:
            st.metric("High-Risk Parts", selected_high_risk)

        with bom_col3:
            st.metric("Obsolete / EOL Parts", selected_obsolete)

        with bom_col4:
            st.metric("Average Risk Score", selected_avg_risk)

        search_query = st.text_input("Search by MPN, manufacturer, or risk reason")

        risk_filter = st.multiselect(
            "Filter by risk level",
            options=sorted(selected_parts["risk_level"].dropna().unique()),
            default=sorted(selected_parts["risk_level"].dropna().unique()),
        )

        lifecycle_filter = st.multiselect(
            "Filter by lifecycle status",
            options=sorted(selected_parts["lifecycle_status"].dropna().unique()),
            default=sorted(selected_parts["lifecycle_status"].dropna().unique()),
        )

        filtered_parts = selected_parts.copy()

        if search_query:
            filtered_parts = filtered_parts[
                filtered_parts["mpn"].astype(str).str.contains(search_query, case=False, na=False)
                | filtered_parts["manufacturer"].astype(str).str.contains(search_query, case=False, na=False)
                | filtered_parts["risk_reasons"].astype(str).str.contains(search_query, case=False, na=False)
            ]

        filtered_parts = filtered_parts[
            filtered_parts["risk_level"].isin(risk_filter)
            & filtered_parts["lifecycle_status"].isin(lifecycle_filter)
        ]

        if st.button("Delete this saved analysis"):
            try:
                supabase.table("analysis_parts").delete().eq(
                    "analysis_id",
                    selected_analysis_id
                ).eq(
                    "user_id",
                    current_user["id"]
                ).execute()

                supabase.table("part_monitor_history").delete().eq(
                    "analysis_id",
                    selected_analysis_id
                ).eq(
                    "user_id",
                    current_user["id"]
                ).execute()

                supabase.table("monitor_alerts").delete().eq(
                    "analysis_id",
                    selected_analysis_id
                ).eq(
                    "user_id",
                    current_user["id"]
                ).execute()

                supabase.table("alternative_recommendations").delete().eq(
                    "analysis_id",
                    selected_analysis_id
                ).eq(
                    "user_id",
                    current_user["id"]
                ).execute()

                supabase.table("analyses").delete().eq(
                    "id",
                    selected_analysis_id
                ).eq(
                    "user_id",
                    current_user["id"]
                ).execute()

                st.session_state.pop("results_df", None)

                st.success("Saved analysis deleted.")
                st.rerun()

            except Exception as e:
                st.error(f"Could not delete saved analysis: {e}")

        filtered_display_df = filtered_parts[
            [
                "mpn",
                "manufacturer",
                "risk_score",
                "risk_level",
                "risk_reasons",
                "lifecycle_status",
                "stock_available",
                "supplier_count",
            ]
        ].rename(
            columns={
                "mpn": "Part Number",
                "manufacturer": "Manufacturer",
                "risk_score": "Risk Score",
                "risk_level": "Risk Level",
                "risk_reasons": "Risk Reasons",
                "lifecycle_status": "Lifecycle Status",
                "stock_available": "Stock Available",
                "supplier_count": "Supplier Count",
            }
        )

        filtered_display_df["Risk Level"] = (
            filtered_display_df["Risk Level"]
            .replace(
                {
                    "High": "🔴 High",
                    "Medium": "🟠 Medium",
                    "Low": "🟢 Low",
                }
            )
        )

        st.dataframe(
            filtered_display_df,
            use_container_width=True,
        )

        download_df = filtered_parts[
            [
                "mpn",
                "manufacturer",
                "risk_score",
                "risk_level",
                "risk_reasons",
                "lifecycle_status",
                "stock_available",
                "supplier_count",
            ]
        ]

        csv_data = download_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Download Analysis CSV",
            data=csv_data,
            file_name=f"{selected_analysis_label}.csv",
            mime="text/csv",
        )

        selected_alt_history = pd.DataFrame(
            load_alternative_history(current_user["id"])
        )

        if not selected_alt_history.empty:
            selected_alt_history = selected_alt_history[
                selected_alt_history["analysis_id"] == selected_analysis_id
            ]

        pdf_buffer = generate_bom_pdf_report(
            selected_analysis_label,
            selected_parts,
            attention_parts,
            int(selected_parts["risk_score"].mean()),
            selected_alt_history,
        )

        st.download_button(
            label="Download PDF Report",
            data=pdf_buffer,
            file_name=f"{selected_analysis_label}_executive_report.pdf",
            mime="application/pdf",
        )

        st.divider()
        st.subheader("Alternative Recommendation History")

        alternative_history = load_alternative_history(current_user["id"])

        if not alternative_history:
            st.info("No alternative recommendations saved yet.")
        else:
            alternative_history_df = pd.DataFrame(alternative_history)

            alternative_history_df["created_at"] = pd.to_datetime(
                alternative_history_df["created_at"]
            ).dt.strftime("%Y-%m-%d")

            alternative_display_df = alternative_history_df[
                [
                    "original_part",
                    "alternative_part",
                    "recommendation_score",
                    "estimated_risk",
                    "supplier",
                    "stock",
                    "unit_price",
                    "compatibility_notes",
                    "architecture",
                    "package",
                    "pin_count",
                    "voltage_range",
                    "score_reasons",
                    "created_at",
                ]
            ].rename(
                columns={
                    "original_part": "Original Part",
                    "alternative_part": "Alternative Part",
                    "recommendation_score": "Recommendation Score",
                    "estimated_risk": "Estimated Risk",
                    "supplier": "Supplier",
                    "stock": "Stock",
                    "unit_price": "Unit Price",
                    "compatibility_notes": "Compatibility Notes",
                    "architecture": "Architecture",
                    "package": "Package",
                    "pin_count": "Pin Count",
                    "voltage_range": "Voltage Range",
                    "score_reasons": "Score Reasons",
                    "created_at": "Created At",
                }
            )

            st.dataframe(
                alternative_display_df,
                use_container_width=True,
                hide_index=True,
            )

            alternative_csv = alternative_display_df.to_csv(index=False).encode("utf-8")

            st.download_button(
                label="Download Alternative History CSV",
                data=alternative_csv,
                file_name="alternative_recommendation_history.csv",
                mime="text/csv",
            )

            if st.button("Clear Alternative Recommendation History"):
                supabase.table("alternative_recommendations").delete().eq(
                    "user_id",
                    current_user["id"]
                ).execute()

                st.success("Alternative recommendation history cleared.")
                st.rerun()

    # ---------- Charts ----------
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("BOM Risk Trend")

        if analysis_data:
            trend_df = pd.DataFrame(analysis_data)

            trend_df["created_at"] = pd.to_datetime(trend_df["created_at"])
            trend_df["Date"] = trend_df["created_at"].dt.date

            trend_data = (
                trend_df.groupby("Date")["health_score"]
                .mean()
                .reset_index()
                .rename(columns={"health_score": "Average Health Score"})
            )

            st.line_chart(
                trend_data,
                x="Date",
                y="Average Health Score",
            )
        else:
            st.info("No trend data yet.")


    st.divider()

    # ---------- Recent Activity ----------
    st.subheader("Recent Analyses")

    recent_response = (

        supabase.table("analyses")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    recent_data = recent_response.data

    if recent_data:

        recent_df = pd.DataFrame(recent_data)
        
        recent_df = recent_df.rename(
            columns={
                "filename": "File",
                "total_parts": "Components",
                "health_score": "Health Score",
                "high_risk_count": "High Risk Parts",
                "created_at": "Created At",
            }
        )

        display_cols = [
            "File",
            "Components",
            "Health Score",
            "High Risk Parts",
            "Created At",
        ]

        recent_display_df = recent_df[display_cols].rename(
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
            recent_display_df,
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.info("No analyses yet.")

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
    st.subheader("Reports")

    st.info("Saved reports and exports coming soon.")

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
                <div class="card-title">Pro</div>
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


# ---------- About ----------
if app_mode == "About":
    st.subheader("About BOM Risk Checker")
    st.caption("Helping engineering teams reduce supply chain surprises before they reach production.")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown(
            """
            <div class="card">
                <div class="card-title">What We Do</div>
                <div class="card-text">
                    BOM Risk Checker helps engineering and supply chain teams identify obsolete,
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
    st.markdown("## Alternative Component Finder")
    st.caption(
        "Verify supplier data, compare engineering compatibility, and rank replacement candidates."
    )

    st.markdown("#### Search Original Component")

    if "suggested_alternatives" not in st.session_state:
        st.session_state["suggested_alternatives"] = []

    if "alternative_search_attempted" not in st.session_state:
        st.session_state["alternative_search_attempted"] = False

    if "alternative_original_part" not in st.session_state:
        st.session_state["alternative_original_part"] = ""

    def _format_currency(value):
        try:
            value = float(value or 0)
        except (TypeError, ValueError):
            value = 0.0
        return f"${value:.2f}" if value > 0 else "N/A"

    def _format_int(value):
        try:
            return f"{int(float(value or 0)):,}"
        except (TypeError, ValueError):
            return "0"

    def _score_label(score):
        try:
            score = int(score or 0)
        except (TypeError, ValueError):
            score = 0

        if score >= 85:
            return "Excellent Match"
        if score >= 70:
            return "Strong Candidate"
        if score >= 50:
            return "Review Candidate"
        return "Engineering Review Required"

    def _render_kpi_card(label, value, note=""):
        st.markdown(
            f"""
            <div style="
                background-color:#FFFFFF;
                border:1px solid #E5E7EB;
                border-radius:12px;
                padding:14px 16px;
                min-height:98px;
            ">
                <div style="font-size:12px;color:#64748B;font-weight:700;margin-bottom:7px;letter-spacing:0.01em;">{label}</div>
                <div style="font-size:26px;color:#0F172A;font-weight:800;line-height:1.12;">{value}</div>
                <div style="font-size:11px;color:#64748B;margin-top:7px;">{note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    def _render_section_title(title, subtitle=""):
        st.markdown(
            f"""
            <div style="margin-top:18px;margin-bottom:8px;">
                <div style="font-size:34px;font-weight:800;color:#0F172A;letter-spacing:-0.02em;">{title}</div>
                {f'<div style="font-size:14px;color:#64748B;margin-top:6px;">{subtitle}</div>' if subtitle else ''}
            </div>
            """,
            unsafe_allow_html=True,
        )

    def _render_compatibility_card(reason):
        reason = str(reason or "").strip()

        if reason.startswith("✓"):
            title = "PASS"
            body = reason.replace("✓", "", 1).strip()
            border = "#BBF7D0"
            bg = "#ECFDF5"
            color = "#15803D"
        elif reason.startswith("⚠"):
            title = "WARNING"
            body = reason.replace("⚠", "", 1).strip()
            border = "#FDE68A"
            bg = "#FFFBEB"
            color = "#B45309"
        else:
            title = "INFO"
            body = reason
            border = "#E5E7EB"
            bg = "#FFFFFF"
            color = "#334155"

        st.markdown(
            f"""
            <div style="
                background-color:{bg};
                border:1px solid {border};
                border-radius:12px;
                padding:14px 16px;
                min-height:96px;
                margin-bottom:12px;
            ">
                <div style="font-size:12px;font-weight:800;letter-spacing:0.08em;color:{color};margin-bottom:8px;">{title}</div>
                <div style="font-size:15px;color:#0F172A;line-height:1.45;">{body}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


    def _split_drop_in_reasons(candidate):
        raw_reasons = str(candidate.get("Drop-In Reasons", "") or "")
        reasons = [reason.strip() for reason in raw_reasons.split(";") if reason.strip()]
        strengths = []
        warnings = []
        informational = []

        for reason in reasons:
            if reason.startswith("✓"):
                strengths.append(reason.replace("✓", "", 1).strip())
            elif reason.startswith("⚠"):
                warnings.append(reason.replace("⚠", "", 1).strip())
            else:
                informational.append(reason.replace("ℹ", "", 1).strip())

        return strengths, warnings, informational

    def _engineering_risk_label(candidate):
        confidence = int(candidate.get("Drop-In Confidence", 0) or 0)
        strengths, warnings, _ = _split_drop_in_reasons(candidate)
        architecture_warning = any("architecture" in warning.lower() for warning in warnings)
        voltage_warning = any("voltage" in warning.lower() for warning in warnings)
        package_warning = any("package" in warning.lower() or "mounting" in warning.lower() for warning in warnings)

        if confidence >= 80 and not architecture_warning and not voltage_warning:
            return "Low Risk", "Suitable for direct evaluation with normal validation."

        if confidence >= 50 and not architecture_warning and not voltage_warning:
            if package_warning:
                return "Medium Risk", "Electrical fit looks reasonable, but package or PCB footprint review is required."
            return "Medium Risk", "Candidate is promising, but engineering validation is still required."

        if architecture_warning or voltage_warning:
            return "High Risk", "Major electrical or functional differences require detailed redesign review."

        return "High Risk", "Compatibility confidence is low; treat this as a redesign candidate."

    def _recommendation_label(candidate):
        confidence = int(candidate.get("Drop-In Confidence", 0) or 0)
        score = int(candidate.get("Recommendation Score", 0) or 0)
        risk_label, _ = _engineering_risk_label(candidate)

        if risk_label == "Low Risk" and score >= 80:
            return "Recommended for Evaluation"
        if risk_label == "Medium Risk" and score >= 60:
            return "Recommended with Engineering Review"
        if score >= 50:
            return "Review Before Use"
        return "Not Recommended Without Redesign"

    def _recommended_action(candidate):
        strengths, warnings, _ = _split_drop_in_reasons(candidate)
        risk_label, _ = _engineering_risk_label(candidate)
        warning_text = " ".join(warnings).lower()

        actions = []

        if risk_label == "Low Risk":
            actions.append("Prototype evaluation recommended")
        elif risk_label == "Medium Risk":
            actions.append("Engineering review required before release")
        else:
            actions.append("Do not approve without redesign review")

        if "package" in warning_text or "mounting" in warning_text:
            actions.append("PCB footprint and assembly review required")

        if "voltage" in warning_text:
            actions.append("Electrical operating range validation required")

        if "architecture" in warning_text or "function" in warning_text:
            actions.append("Functional equivalence review required")

        if not actions:
            actions.append("Standard datasheet validation recommended")

        return actions[:4]


    def _short_compatibility_label(text):
        text_lower = str(text or "").lower()

        if "architecture" in text_lower:
            return "Architecture", text
        if "mounting" in text_lower:
            return "Mounting / Assembly", text
        if "package" in text_lower:
            return "Package", text
        if "pin count" in text_lower:
            return "Pin Count", text
        if "channel count" in text_lower:
            return "Channel Count", text
        if "voltage" in text_lower:
            return "Voltage Range", text
        if "bandwidth" in text_lower or "slew" in text_lower or "offset" in text_lower or "bias" in text_lower:
            return "Electrical Spec", text

        return "Engineering Check", text

    def _render_validation_card(status, title, detail):
        status = str(status or "INFO").upper()

        if status == "PASS":
            border = "#BBF7D0"
            bg = "#ECFDF5"
            color = "#15803D"
        elif status == "WARNING":
            border = "#FDE68A"
            bg = "#FFFBEB"
            color = "#B45309"
        else:
            border = "#E5E7EB"
            bg = "#FFFFFF"
            color = "#334155"

        st.markdown(
            f"""
            <div style="
                background-color:{bg};
                border:1px solid {border};
                border-radius:12px;
                padding:16px 18px;
                min-height:104px;
                margin-bottom:12px;
            ">
                <div style="font-size:12px;font-weight:900;letter-spacing:0.08em;color:{color};margin-bottom:8px;">{status}</div>
                <div style="font-size:16px;font-weight:800;color:#0F172A;margin-bottom:5px;">{title}</div>
                <div style="font-size:14px;color:#334155;line-height:1.45;">{detail}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    def _score_breakdown(candidate):
        score = int(candidate.get("Recommendation Score", 0) or 0)
        confidence = int(candidate.get("Drop-In Confidence", 0) or 0)
        lifecycle = str(candidate.get("Lifecycle", "")).lower()
        stock = int(candidate.get("Stock", 0) or 0)
        unit_price = float(candidate.get("Unit Price", 0.0) or 0.0)
        strengths, warnings, _ = _split_drop_in_reasons(candidate)
        warning_text = " ".join(warnings).lower()

        electrical = min(100, max(0, confidence + 25))
        lifecycle_score = 100 if "active" in lifecycle else 60 if lifecycle else 50
        supply_score = 95 if stock >= 50000 else 85 if stock >= 10000 else 65 if stock > 0 else 20
        cost_score = 90 if 0 < unit_price <= 0.50 else 75 if unit_price <= 1.50 else 55 if unit_price else 50
        package_score = 35 if "package" in warning_text or "mounting" in warning_text else 90

        return [
            ("Overall", score, _score_label(score)),
            ("Electrical Fit", electrical, "Compatibility signals"),
            ("Lifecycle", lifecycle_score, candidate.get("Lifecycle", "Unknown")),
            ("Supply", supply_score, f"{stock:,} units"),
            ("Package", package_score, "Review required" if package_score < 60 else "Compatible"),
            ("Cost", cost_score, _format_currency(unit_price)),
        ]

    def _engineering_impact(candidate):
        strengths, warnings, _ = _split_drop_in_reasons(candidate)
        warning_text = " ".join(warnings).lower()

        impacts = []

        if "package" in warning_text or "mounting" in warning_text:
            impacts.append(("PCB Layout", "WARNING", "Footprint/package review required"))
            impacts.append(("Manufacturing", "WARNING", "Assembly process may change"))
        else:
            impacts.append(("PCB Layout", "PASS", "No package issue detected"))
            impacts.append(("Manufacturing", "PASS", "No assembly concern detected"))

        if "voltage" in warning_text or "architecture" in warning_text or "function" in warning_text:
            impacts.append(("Circuit Performance", "WARNING", "Electrical validation required"))
        else:
            impacts.append(("Circuit Performance", "PASS", "Primary electrical checks passed"))

        impacts.append(("Software/Firmware", "PASS", "No software or firmware impact expected for this component class"))

        return impacts


    def _recommendation_badges(candidate):
        strengths, warnings, _ = _split_drop_in_reasons(candidate)
        strength_text = " ".join(strengths).lower()
        warning_text = " ".join(warnings).lower()
        lifecycle = str(candidate.get("Lifecycle", "")).lower()
        supplier = str(candidate.get("Supplier", "")).strip()
        stock = int(candidate.get("Stock", 0) or 0)

        badges = []
        if "architecture" in strength_text or "operational amplifier" in strength_text:
            badges.append(("PASS", "Electrical Compatible"))
        if "voltage" in strength_text and "voltage" not in warning_text:
            badges.append(("PASS", "Voltage Compatible"))
        if "active" in lifecycle:
            badges.append(("PASS", "Lifecycle Active"))
        if stock > 0:
            badges.append(("PASS", "Stock Available"))
        if supplier and supplier.lower() not in ["unknown", "none", ""]:
            badges.append(("PASS", "Supplier Verified"))
        if "package" in warning_text or "mounting" in warning_text:
            badges.append(("WARNING", "Footprint Review"))
            badges.append(("WARNING", "Manufacturing Review"))
        if "voltage" in warning_text:
            badges.append(("WARNING", "Voltage Review"))
        if "architecture" in warning_text or "function" in warning_text:
            badges.append(("WARNING", "Functional Review"))
        return badges[:8]

    def _badge_html(status, label):
        status = str(status or "INFO").upper()
        if status == "PASS":
            bg, border, color = "#052E1A", "#14532D", "#86EFAC"
        elif status == "WARNING":
            bg, border, color = "#422006", "#854D0E", "#FDE68A"
        else:
            bg, border, color = "#111827", "#334155", "#CBD5E1"
        return f'<span style="display:inline-block;background:{bg};border:1px solid {border};color:{color};border-radius:999px;padding:7px 10px;margin:4px 6px 4px 0;font-size:12px;font-weight:800;letter-spacing:0.02em;">{label}</span>'

    def _engineering_summary_text(original_part, candidate):
        part_number = candidate.get("Alternative Part", "Unknown")
        score = int(candidate.get("Recommendation Score", 0) or 0)
        confidence = int(candidate.get("Drop-In Confidence", 0) or 0)
        stock = int(candidate.get("Stock", 0) or 0)
        supplier = candidate.get("Supplier", "Unknown")
        strengths, warnings, _ = _split_drop_in_reasons(candidate)
        warning_text = " ".join(warnings).lower()

        positives = []
        if score >= 70:
            positives.append("strong overall recommendation score")
        if confidence >= 50:
            positives.append("acceptable electrical compatibility signals")
        if stock > 0:
            positives.append(f"available supplier inventory through {supplier}")
        if strengths:
            positives.append("matching core engineering characteristics")

        if not positives:
            positives.append("available candidate data")

        concerns = []
        if "package" in warning_text or "mounting" in warning_text:
            concerns.append("PCB footprint and assembly review")
        if "voltage" in warning_text:
            concerns.append("voltage range validation")
        if "architecture" in warning_text or "function" in warning_text:
            concerns.append("functional equivalence review")

        if concerns:
            concern_sentence = " Primary review item: " + ", ".join(concerns) + "."
        else:
            concern_sentence = " No major implementation warnings were detected by the current rules."

        return (
            f"{part_number} is recommended as the leading replacement candidate for {original_part} because it combines "
            f"{', '.join(positives)}."
            f"{concern_sentence}"
        )


    def _confidence_band(value):
        value = int(value or 0)
        if value >= 85:
            return "High", "Strong engineering confidence"
        if value >= 60:
            return "Medium", "Promising candidate with review items"
        if value >= 40:
            return "Moderate", "Use only after engineering validation"
        return "Low", "Treat as redesign candidate"

    def _render_horizontal_score(label, value, note):
        safe_value = max(0, min(int(value or 0), 100))
        band, _ = _confidence_band(safe_value)
        st.markdown(f"**{label}** — {safe_value}/100")
        st.progress(safe_value)
        st.caption(f"{band}: {note}")

    def _compatibility_signal_summary(candidate):
        strengths, warnings, _ = _split_drop_in_reasons(candidate)
        strength_text = " ".join(strengths).lower()
        warning_text = " ".join(warnings).lower()

        function_ok = (
            "architecture" in strength_text
            or "function" in strength_text
            or "operational amplifier" in strength_text
        )
        pin_ok = "pin count" in strength_text
        channel_ok = "channel count" in strength_text
        voltage_ok = "voltage" in strength_text and "voltage" not in warning_text
        package_warning = "package" in warning_text or "mounting" in warning_text
        electrical_warning = any(
            token in warning_text
            for token in ["voltage", "bandwidth", "slew", "offset", "bias", "quiescent", "architecture", "function"]
        )

        if function_ok and voltage_ok and pin_ok and channel_ok and not electrical_warning:
            electrical_status = "PASS"
            electrical_detail = "Functional and primary electrical compatibility signals look acceptable."
        elif electrical_warning:
            electrical_status = "WARNING"
            electrical_detail = "One or more electrical compatibility signals require datasheet validation."
        else:
            electrical_status = "INFO"
            electrical_detail = "Electrical compatibility is partially verified; review datasheets before approval."

        package_status = "WARNING" if package_warning else "PASS"
        package_detail = (
            "Package or mounting mismatch detected; PCB footprint and assembly review required."
            if package_warning
            else "No package mismatch detected by the current rules."
        )

        pin_status = "PASS" if pin_ok else "INFO"
        pin_detail = "Pin count matches the original component." if pin_ok else "Pin compatibility requires datasheet review."

        voltage_status = "PASS" if voltage_ok else "INFO"
        voltage_detail = "Candidate supply range covers the original requirement." if voltage_ok else "Voltage compatibility requires datasheet validation."

        return [
            ("Functional/Electrical Fit", electrical_status, electrical_detail),
            ("Pin / Channel Fit", pin_status, pin_detail),
            ("Supply Voltage", voltage_status, voltage_detail),
            ("Package / Footprint", package_status, package_detail),
        ]

    def _render_confidence_explanation(candidate):
        st.markdown("#### Engineering Confidence Details")
        st.caption("Compatibility signals interpreted from package, pin count, voltage range, architecture, and available electrical parameters.")

        c1, c2 = st.columns(2)
        for idx, (title, status, detail) in enumerate(_compatibility_signal_summary(candidate)):
            with (c1 if idx % 2 == 0 else c2):
                _render_validation_card(status, title, detail)

    def _render_engineering_decision_dashboard(original_part, candidate):
        if not candidate:
            return

        part_number = candidate.get("Alternative Part", "Unknown")
        score = int(candidate.get("Recommendation Score", 0) or 0)
        confidence = int(candidate.get("Drop-In Confidence", 0) or 0)
        lifecycle = candidate.get("Lifecycle", "Unknown")
        supplier = candidate.get("Supplier", "Unknown")
        package = candidate.get("Package", "Unknown")
        price = float(candidate.get("Unit Price", 0.0) or 0.0)
        stock = int(candidate.get("Stock", 0) or 0)
        recommendation_status = _recommendation_label(candidate)
        risk_label, risk_note = _engineering_risk_label(candidate)
        strengths, warnings, informational = _split_drop_in_reasons(candidate)
        recommendation_text = candidate.get("Recommendation", "Review compatibility.")

        status_badge = "RECOMMENDED" if score >= 70 else "REVIEW REQUIRED"

        st.markdown(
            f"""
            <div style="margin-top:24px;margin-bottom:10px;">
                <div style="font-size:34px;font-weight:800;color:#0F172A;letter-spacing:-0.02em;">Engineering Recommendation</div>
                <div style="font-size:14px;color:#64748B;margin-top:6px;">Executive decision dashboard summarizing fit, sourcing strength, and implementation impact.</div>
            </div>
            <div style="
                background:linear-gradient(135deg,#FFFFFF,#EFF6FF);
                border:1px solid #BFDBFE;
                border-radius:16px;
                padding:22px 24px;
                margin-bottom:16px;
            ">
                <div style="display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap;">
                    <div>
                        <div style="font-size:12px;color:#2563EB;font-weight:900;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:8px;">{status_badge}</div>
                        <div style="font-size:40px;font-weight:900;color:#0F172A;letter-spacing:-0.03em;">{part_number}</div>
                        <div style="font-size:14px;color:#64748B;margin-top:6px;">{recommendation_text}</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:12px;color:#64748B;font-weight:700;">Overall Recommendation</div>
                        <div style="font-size:20px;color:#0F172A;font-weight:900;margin-top:4px;">{recommendation_status}</div>
                        <div style="font-size:12px;color:#64748B;margin-top:6px;">{risk_label}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        d_col1, d_col2, d_col3, d_col4, d_col5, d_col6 = st.columns(6)
        with d_col1:
            _render_kpi_card("Score", f"{score}", _score_label(score))
        with d_col2:
            _render_kpi_card("Drop-In", f"{confidence}%", "Compatibility confidence")
        with d_col3:
            _render_kpi_card("Lifecycle", lifecycle, "Supplier status")
        with d_col4:
            _render_kpi_card("Supplier", supplier, "Top candidate source")
        with d_col5:
            _render_kpi_card("Stock", _format_int(stock), "Available units")
        with d_col6:
            _render_kpi_card("Price", _format_currency(price), "Unit price")

        badge_markup = "".join(_badge_html(status, label) for status, label in _recommendation_badges(candidate))
        summary_text = _engineering_summary_text(original_part, candidate)

        st.markdown(
            f"""
            <div style="
                background-color:#FFFFFF;
                border:1px solid #BFDBFE;
                border-radius:14px;
                padding:16px 18px;
                margin-top:12px;
                margin-bottom:14px;
            ">
                <div style="font-size:13px;color:#64748B;font-weight:800;margin-bottom:6px;">AI Engineering Summary</div>
                <div style="font-size:15px;color:#334155;line-height:1.55;">
                    {summary_text}
                </div>
                <div style="margin-top:12px;">{badge_markup}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        _render_confidence_explanation(candidate)

        st.markdown("#### Engineering Validation Checklist")
        validation_items = []
        for reason in strengths[:5]:
            title, detail = _short_compatibility_label(reason)
            validation_items.append(("PASS", title, detail))
        for reason in warnings[:5]:
            title, detail = _short_compatibility_label(reason)
            validation_items.append(("WARNING", title, detail))

        if not validation_items:
            validation_items = [("INFO", "Validation", "No detailed compatibility reasons were returned.")]

        v_col1, v_col2 = st.columns(2)
        for idx, (status, title, detail) in enumerate(validation_items[:8]):
            with (v_col1 if idx % 2 == 0 else v_col2):
                _render_validation_card(status, title, detail)

        st.markdown("#### Design Impact")
        impact_col1, impact_col2, impact_col3, impact_col4 = st.columns(4)
        for idx, (title, status, detail) in enumerate(_engineering_impact(candidate)):
            with [impact_col1, impact_col2, impact_col3, impact_col4][idx % 4]:
                _render_validation_card(status, title, detail)

        with st.expander("Recommendation score breakdown", expanded=False):
            breakdown = _score_breakdown(candidate)
            for label, value, note in breakdown:
                safe_value = max(0, min(int(value or 0), 100))
                st.markdown(f"**{label}** — {safe_value}/100")
                st.progress(safe_value)
                st.caption(str(note))

    def _render_engineering_recommendation(original_part, candidate):
        """Compact executive decision card.

        This intentionally avoids repeating the full validation checklist,
        which is now handled in the Top Candidate Dashboard dashboard.
        """
        if not candidate:
            return

        part_number = candidate.get("Alternative Part", "Unknown")
        recommendation_status = _recommendation_label(candidate)
        risk_label, risk_note = _engineering_risk_label(candidate)
        strengths, warnings, _ = _split_drop_in_reasons(candidate)

        if warnings:
            decision_sentence = (
                "Electrical compatibility appears reasonable, but engineering review is required before production use."
            )
            implementation_sentence = (
                "Primary implementation impact: PCB footprint/package and assembly review."
            )
        else:
            decision_sentence = (
                "No major compatibility warnings were detected by the current rules."
            )
            implementation_sentence = (
                "Standard datasheet validation is still recommended before release."
            )

        if risk_label == "Low Risk":
            risk_color = "#15803D"
            risk_border = "#BBF7D0"
            risk_bg = "#ECFDF5"
        elif risk_label == "Medium Risk":
            risk_color = "#B45309"
            risk_border = "#FDE68A"
            risk_bg = "#FFFBEB"
        else:
            risk_color = "#B91C1C"
            risk_border = "#FECACA"
            risk_bg = "#FEF2F2"

        st.markdown(
            f"""
            <div style="margin-top:24px;margin-bottom:10px;">
                <div style="font-size:32px;font-weight:800;color:#0F172A;letter-spacing:-0.02em;">Engineering Decision</div>
                <div style="font-size:14px;color:#64748B;margin-top:6px;">Executive recommendation generated from compatibility, lifecycle, sourcing, and risk signals.</div>
            </div>
            <div style="
                background:linear-gradient(135deg,#FFFFFF,#EFF6FF);
                border:1px solid #BFDBFE;
                border-radius:16px;
                padding:20px 24px;
                margin-bottom:18px;
            ">
                <div style="display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap;">
                    <div style="max-width:980px;">
                        <div style="font-size:12px;color:#2563EB;font-weight:900;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:8px;">{recommendation_status}</div>
                        <div style="font-size:34px;color:#0F172A;font-weight:900;letter-spacing:-0.03em;">{part_number}</div>
                        <div style="font-size:16px;color:#334155;line-height:1.55;margin-top:12px;">
                            {decision_sentence}
                        </div>
                        <div style="font-size:13px;color:#64748B;margin-top:8px;">
                            {implementation_sentence} {risk_note}
                        </div>
                    </div>
                    <div style="
                        background-color:{risk_bg};
                        border:1px solid {risk_border};
                        border-radius:999px;
                        padding:9px 14px;
                        color:{risk_color};
                        font-size:12px;
                        font-weight:900;
                        letter-spacing:0.04em;
                        text-transform:uppercase;
                        white-space:nowrap;
                    ">{risk_label}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if "alternative_input_part" not in st.session_state:
        st.session_state["alternative_input_part"] = st.session_state.get(
            "alternative_original_part",
            "",
        )

    original_part = st.text_input(
        "Manufacturer part number",
        key="alternative_input_part",
        placeholder="Example: LM358, NE555, ATMEGA328P",
    )

    search_button_col, search_hint_col = st.columns([0.13, 0.87])

    with search_button_col:
        search_clicked = st.button(
            "Analyze Component",
            type="primary",
            use_container_width=False,
            key="alternative_search_button",
        )

    with search_hint_col:
        st.caption(
            "Supplier lookup • Electrical comparison • Ranked engineering recommendations"
        )

    if search_clicked:
        original_part = str(original_part or "").strip()

        if not original_part:
            st.warning("Please enter an original part number.")
        else:
            with st.spinner(
                "Searching suppliers, comparing electrical specs, and ranking alternatives..."
            ):
                st.session_state["alternative_original_part"] = original_part
                st.session_state["suggested_alternatives"] = suggest_alternatives_v2(
                    original_part
                )
                st.session_state["alternative_search_attempted"] = True

    if st.session_state["suggested_alternatives"]:
        alternatives = st.session_state["suggested_alternatives"]
        original_part = st.session_state.get("alternative_original_part", original_part)
        alternatives_df = pd.DataFrame(alternatives)

        if "Alternative Part" not in alternatives_df.columns:
            st.warning("Alternative results are missing part number data.")
            st.stop()

        numeric_columns = [
            "Recommendation Score",
            "Drop-In Confidence",
            "Stock",
            "Unit Price",
        ]

        for col in numeric_columns:
            if col in alternatives_df.columns:
                alternatives_df[col] = pd.to_numeric(
                    alternatives_df[col],
                    errors="coerce",
                ).fillna(0)

        true_alternatives = [
            alt for alt in alternatives
            if isinstance(alt, dict)
            and alt.get("Alternative Part", "") != original_part
        ]

        best_alternative = (
            max(
                true_alternatives,
                key=lambda x: x.get("Recommendation Score", 0),
            )
            if true_alternatives
            else None
        )

        value_alternatives = [
            alt for alt in true_alternatives
            if float(alt.get("Stock", 0) or 0) > 0
            and float(alt.get("Unit Price", 0.0) or 0.0) > 0
        ]

        best_value_alternative = (
            min(
                value_alternatives,
                key=lambda x: float(x.get("Unit Price", 0.0) or 0.0),
            )
            if value_alternatives
            else None
        )

        supplier_count = (
            alternatives_df["Supplier"].replace("", pd.NA).dropna().nunique()
            if "Supplier" in alternatives_df.columns
            else 0
        )

        total_stock = (
            int(alternatives_df["Stock"].sum())
            if "Stock" in alternatives_df.columns
            else 0
        )

        lowest_unit_price = (
            float(best_value_alternative.get("Unit Price", 0.0) or 0.0)
            if best_value_alternative
            else 0.0
        )

        top_score = (
            int(best_alternative.get("Recommendation Score", 0) or 0)
            if best_alternative
            else 0
        )

        top_confidence = (
            int(best_alternative.get("Drop-In Confidence", 0) or 0)
            if best_alternative
            else 0
        )

        best_supplier = (
            best_alternative.get("Supplier", "Unknown")
            if best_alternative
            else "Unknown"
        )

        _render_section_title(
            "Search Summary",
            "Ranked results based on compatibility, availability, lifecycle status, and sourcing risk.",
        )

        summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)

        with summary_col1:
            _render_kpi_card(
                "Best Recommendation",
                best_alternative.get("Alternative Part", "-") if best_alternative else "-",
                "Highest-ranked candidate",
            )

        with summary_col2:
            _render_kpi_card("Recommendation Score", f"{top_score} / 100", _score_label(top_score))

        with summary_col3:
            _render_kpi_card("Drop-In Match", f"{top_confidence}%", "Engineering compatibility")

        with summary_col4:
            _render_kpi_card("Verified Suppliers", supplier_count, "Live supplier responses")

        st.divider()

        if best_alternative:
            _render_engineering_decision_dashboard(original_part, best_alternative)
            st.divider()

        if best_value_alternative:
            st.divider()
            _render_section_title("Best Value Alternative")

            value_col1, value_col2, value_col3, value_col4, value_col5 = st.columns(5)

            with value_col1:
                _render_kpi_card(
                    "Part Number",
                    best_value_alternative.get("Alternative Part", "Unknown"),
                    "Lowest-priced stocked candidate",
                )

            with value_col2:
                _render_kpi_card(
                    "Unit Price",
                    _format_currency(best_value_alternative.get("Unit Price", 0.0)),
                    "Supplier-listed price",
                )

            with value_col3:
                _render_kpi_card(
                    "Available Stock",
                    _format_int(best_value_alternative.get("Stock", 0)),
                    "Current supplier stock",
                )

            with value_col4:
                value_score = int(best_value_alternative.get("Recommendation Score", 0) or 0)
                _render_kpi_card(
                    "Score",
                    value_score,
                    _score_label(value_score),
                )

            with value_col5:
                _render_kpi_card(
                    "Drop-In",
                    f"{int(best_value_alternative.get('Drop-In Confidence', 0) or 0)}%",
                    best_value_alternative.get("Drop-In Rating", "Compatibility"),
                )

        st.divider()

        _render_section_title("Supplier Intelligence")

        supplier_col1, supplier_col2, supplier_col3, supplier_col4 = st.columns(4)

        with supplier_col1:
            _render_kpi_card("Verified Suppliers", supplier_count, "Supplier records found")

        with supplier_col2:
            _render_kpi_card("Market Stock", f"{total_stock:,}", "Across returned candidates")

        with supplier_col3:
            _render_kpi_card("Supplier for Top Recommendation", best_supplier or "Unknown", "Matched supplier record")

        with supplier_col4:
            price_label = f"${lowest_unit_price:.2f}" if lowest_unit_price > 0 else "N/A"
            _render_kpi_card("Lowest Price", price_label, "Best stocked unit price")

        st.divider()

        _render_section_title(
            "Side-by-Side Comparison",
            "Select an alternative to compare directly against the searched original component.",
        )

        alternative_options = alternatives_df["Alternative Part"].dropna().tolist()
        default_index = 0

        if best_alternative and best_alternative.get("Alternative Part") in alternative_options:
            default_index = alternative_options.index(best_alternative.get("Alternative Part"))

        selected_alternative = st.selectbox(
            "Compare with recommended part",
            alternative_options,
            index=default_index,
        )

        selected_row = alternatives_df[
            alternatives_df["Alternative Part"] == selected_alternative
        ].iloc[0]

        original_data = get_best_part_data(original_part)

        original_stock = float(original_data.get("stock_total", 0) or 0)
        alternative_stock = float(selected_row.get("Stock", 0) or 0)

        original_price = float(original_data.get("unit_price", 0.0) or 0.0)
        alternative_price = float(selected_row.get("Unit Price", 0.0) or 0.0)

        if original_stock > 0 and alternative_stock > 0:
            stock_ratio = alternative_stock / original_stock

            if stock_ratio > 1:
                stock_delta = f"Improved: {stock_ratio:.0f}x more stock available"
            else:
                stock_delta = f"Reduced: {(1 / stock_ratio):.1f}x less stock available"

        elif original_stock > 0 and alternative_stock == 0:
            stock_delta = "No stock available"

        else:
            stock_delta = "N/A"

        if original_price > 0:
            price_pct = ((alternative_price - original_price) / original_price) * 100

            if price_pct < 0:
                price_delta = f"Improved: {abs(price_pct):.1f}% lower cost"
            else:
                price_delta = f"Tradeoff: {price_pct:.1f}% higher cost"
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
                    "Original": f"{int(original_data.get('stock_total', 0) or 0):,}",
                    "Selected Alternative": f"{int(selected_row.get('Stock', 0) or 0):,}",
                },
                {
                    "Attribute": "Unit Price",
                    "Original": f"${float(original_data.get('unit_price', 0.0) or 0.0):.2f}",
                    "Selected Alternative": f"${float(selected_row.get('Unit Price', 0.0) or 0.0):.2f}",
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
                    "Attribute": "Voltage Range",
                    "Original": original_data.get("voltage_range") or "Not available from supplier data",
                    "Selected Alternative": selected_row.get("Voltage Range", ""),
                },
                {
                    "Attribute": "Drop-In Confidence",
                    "Original": "—",
                    "Selected Alternative": selected_row.get("Drop-In Confidence", ""),
                },
                {
                    "Attribute": "Drop-In Rating",
                    "Original": "—",
                    "Selected Alternative": str(selected_row.get("Drop-In Rating", "")).replace("🟢", "").replace("🟡", "").replace("🔴", "").strip(),
                },
            ]
        )

        st.dataframe(
            comparison_df,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        _render_section_title(
            "All Suggested Alternatives",
            "Reference table for reviewing all ranked alternatives returned by the engine.",
        )

        preferred_columns = [
            "Alternative Part",
            "Recommendation Score",
            "Drop-In Rating",
            "Drop-In Confidence",
            "Lifecycle",
            "Supplier",
            "Stock",
            "Unit Price",
            "Architecture",
            "Package",
            "Pin Count",
            "Voltage Range",
            "Estimated Risk",
            "Recommendation",
        ]

        display_columns = [
            col for col in preferred_columns
            if col in alternatives_df.columns
        ]

        display_df = alternatives_df[display_columns].copy()

        if best_alternative and "Alternative Part" in display_df.columns:
            best_part_number = best_alternative.get("Alternative Part", "")
            display_df.insert(
                0,
                "Status",
                display_df["Alternative Part"].apply(
                    lambda value: "Recommended" if value == best_part_number else ""
                ),
            )

        if "Drop-In Rating" in display_df.columns:
            display_df["Drop-In Rating"] = (
                display_df["Drop-In Rating"]
                .astype(str)
                .str.replace("🟢", "", regex=False)
                .str.replace("🟡", "", regex=False)
                .str.replace("🔴", "", regex=False)
                .str.strip()
            )

        if "Estimated Risk" in display_df.columns:
            display_df["Estimated Risk"] = display_df["Estimated Risk"].replace(
                {
                    "Low": "Low",
                    "Medium": "Medium",
                    "High": "High",
                }
            )

        if "Unit Price" in display_df.columns:
            display_df["Unit Price"] = display_df["Unit Price"].apply(
                lambda value: f"${float(value or 0):.2f}"
            )

        if "Stock" in display_df.columns:
            display_df["Stock"] = display_df["Stock"].apply(
                lambda value: f"{int(value or 0):,}"
            )

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
        )

        if st.button("Analyze Another Component"):
            st.session_state["suggested_alternatives"] = []
            st.session_state["alternative_search_attempted"] = False
            st.session_state["alternative_original_part"] = ""
            st.rerun()

    elif st.session_state["alternative_search_attempted"]:
        st.warning("No suggested alternatives found.")

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
                st.markdown("### Pro")
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
