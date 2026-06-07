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
    show_auth_ui(supabase)
    st.stop()

with st.sidebar:
    if st.button("Log out"):
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
    .main-title {
        font-size: 42px;
        font-weight: 800;
        margin-bottom: 0px;
    }
    .subtitle {
        font-size: 18px;
        color: #666;
        margin-bottom: 30px;
    }
    .card {
    background-color: #111827;
    border: 1px solid #374151;
    border-radius: 16px;
    padding: 20px;
    margin-top: 20px;
    margin-bottom: 20px;
    }

    .card-title {
        font-size: 18px;
        font-weight: 700;
        color: #F9FAFB;
        margin-bottom: 8px;
    }

    .card-text {
        font-size: 14px;
        color: #D1D5DB;
    }
        .kpi-card {
        background-color: #111827;
        border: 1px solid #374151;
        border-radius: 14px;
        padding: 18px;
        min-height: 120px;
    }

    .kpi-label {
        font-size: 13px;
        color: #9CA3AF;
        margin-bottom: 8px;
    }

    .kpi-value {
        font-size: 32px;
        font-weight: 800;
        color: #F9FAFB;
        margin-bottom: 6px;
    }

    .kpi-note {
        font-size: 13px;
        color: #34D399;
    }

    </style>
    """,
    
    unsafe_allow_html=True,
    
)


st.sidebar.title("BOM Risk Checker")
if "user" in st.session_state:
    st.sidebar.success(
        f"Logged in as:\n{st.session_state['user'].email}"
    )

    
st.sidebar.write("Component lifecycle and supply chain risk analysis.")
st.sidebar.divider()
st.sidebar.write("Supported files: CSV, XLSX")
st.sidebar.write("Required field: Part Number / MPN")

st.sidebar.divider()

st.sidebar.subheader("Navigation")

app_mode = st.sidebar.radio(
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
)

st.sidebar.subheader("Subscription")

# Default user plan
selected_plan_name = current_user["plan"]
selected_plan = get_plan(selected_plan_name)

monthly_upload_count = current_user["monthly_upload_count"]

st.sidebar.markdown(f"### {selected_plan_name}")

st.sidebar.write(
    f"**Monthly BOM limit:** {selected_plan['monthly_bom_limit']}"
)

st.sidebar.write(
    f"**Max parts per BOM:** {selected_plan['max_parts_per_bom']}"
)

st.sidebar.caption(selected_plan["description"])
if is_admin:
    st.sidebar.success("🛠 Admin access enabled")

st.sidebar.write(
    f"**BOM analyses used this month:** "
    f"{monthly_upload_count} / "
    f"{selected_plan['monthly_bom_limit']}"
)

saved_bom_count_response = (
    supabase.table("analyses")
    .select("id", count="exact")
    .eq("user_id", current_user["id"])
    .execute()
)

saved_bom_count = saved_bom_count_response.count or 0

st.sidebar.write(
    f"**Saved BOMs:** "
    f"{saved_bom_count} / "
    f"{selected_plan['max_saved_boms']}"
)

if st.sidebar.button("Clear Analysis"):
    st.session_state.pop("results_df", None)
    st.session_state.pop("uploaded_filename", None)
    st.rerun()


st.markdown(
    """
    <div class="card">
        <h1 style="font-size: 3rem; margin-bottom: 0;">
            📦 BOM Risk Checker
        </h1>
        <p class="card-text" style="font-size: 1.2rem;">
            Supply chain risk intelligence and alternative component analysis for engineering teams.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        """
        <div class="kpi-card">
            <div class="kpi-label">Suppliers Integrated</div>
            <div class="kpi-value">2</div>
            <div class="kpi-note">+1 coming soon</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        """
        <div class="kpi-card">
            <div class="kpi-label">Risk Engine</div>
            <div class="kpi-value">Active</div>
            <div class="kpi-note">Live scoring enabled</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col3:
    st.markdown(
        """
        <div class="kpi-card">
            <div class="kpi-label">Alternative Finder</div>
            <div class="kpi-value">Enabled</div>
            <div class="kpi-note">Ranked candidates</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col4:
    st.markdown(
        """
        <div class="kpi-card">
            <div class="kpi-label">Export Support</div>
            <div class="kpi-value">CSV/XLSX</div>
            <div class="kpi-note">Reports ready</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------- Dashboard ----------
if app_mode == "Dashboard":

    st.subheader("Executive Dashboard")
    st.caption("Overview of BOM risk activity and sourcing intelligence.")

    analysis_response = (
        supabase.table("analyses")
        .select("*")
        .eq("user_id", current_user["id"])
        .execute()
    )

    analysis_data = analysis_response.data

    total_analyses = len(analysis_data)

    if analysis_data:

        avg_health_score = int(
            sum(item["health_score"] for item in analysis_data)
            / total_analyses
        )

        total_high_risk = sum(
            item["high_risk_count"] for item in analysis_data
        )

    else:
        avg_health_score = 0
        total_high_risk = 0

    action_col1, action_col2, action_col3 = st.columns([1, 1, 4])

    with action_col1:
        if st.button("➕ New BOM Analysis"):
            st.session_state["go_to_bom_analyzer"] = True

    with action_col2:
        if st.button("🔎 Find Alternatives"):
            st.session_state["go_to_alternative_finder"] = True

    if st.session_state.get("go_to_bom_analyzer"):
        st.session_state["go_to_bom_analyzer"] = False
        st.info("Use the sidebar to open BOM Analyzer.")

    if st.session_state.get("go_to_alternative_finder"):
        st.session_state["go_to_alternative_finder"] = False
        st.info("Use the sidebar to open Alternative Finder.")

    # ---------- KPI ROW ----------
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Analyses This Month</div>
                <div class="kpi-value">{total_analyses}</div>
                <div class="kpi-note">Real analyses completed</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Average BOM Risk</div>
                <div class="kpi-value">{avg_health_score}</div>
                <div class="kpi-note">Average health score</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">High Risk Components</div>
                <div class="kpi-value">{total_high_risk}</div>
                <div class="kpi-note">Detected across analyses</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        st.markdown(
            """
            <div class="kpi-card">
                <div class="kpi-label">Alternatives Found</div>
                <div class="kpi-value">78</div>
                <div class="kpi-note">↑ 15 vs last month</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

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

                                true_alternatives = [
                                    alt for alt in alternatives
                                    if alt.get("Alternative Part", "") != selected_attention_part
                                ]

                                if true_alternatives:
                                    best_alternative = max(
                                        true_alternatives,
                                        key=lambda x: x.get("Recommendation Score", 0)
                                    )

                                    st.success(
                                        f"""
                                        🏆 Best Recommended Alternative: {best_alternative['Alternative Part']}

                                        Recommendation Score: {best_alternative['Recommendation Score']}

                                        Recommendation: {best_alternative['Recommendation']}
                                        """
                                    )

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
                                        st.info(
                                            f"""
                                            💰 Best Value Alternative: {best_value_alternative['Alternative Part']}

                                            Unit Price: ${float(best_value_alternative.get('Unit Price', 0.0)):.2f}

                                            Available Stock: {best_value_alternative.get('Stock', 0)}
                                            """
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

    original_part = st.text_input("Enter original manufacturer part number")

    if "suggested_alternatives" not in st.session_state:
        st.session_state["suggested_alternatives"] = []

    if st.button("Find Alternatives", type="primary"):
        if not original_part:
            st.warning("Please enter an original part number.")
        else:
            with st.spinner("Searching suppliers and finding alternatives..."):
                st.session_state["suggested_alternatives"] = suggest_alternatives_v2(
                    original_part
                )

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

                else:
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

                comparison_df["Risk Level Display"] = comparison_df["Risk Level"].apply(risk_badge)

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

                comparison_display_df = comparison_df[display_cols].rename(
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

                st.dataframe(
                    comparison_display_df,
                    use_container_width=True,
                    hide_index=True,
                )

                alternatives_only = comparison_df[comparison_df["Role"] == "Alternative"]

                if not alternatives_only.empty:
                    best_alt = alternatives_only.sort_values(
                        by=["Risk Score", "Total Market Stock"],
                        ascending=[True, False],
                    ).iloc[0]

                    st.success(
                        f"✅ Recommended Alternative: **{best_alt['Matched MPN']}** "
                        f"(Risk: {best_alt['Risk Level']}, Stock: {best_alt['Total Market Stock']})"
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
