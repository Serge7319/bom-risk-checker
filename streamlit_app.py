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
        supabase.table("analysis_parts")
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

if "user" not in st.session_state:
    show_auth_ui(supabase)
    st.stop()

if "access_token" in st.session_state and "refresh_token" in st.session_state:
    supabase.auth.set_session(
        st.session_state["access_token"],
        st.session_state["refresh_token"]
    )

with st.sidebar:
    if st.button("Log out"):
        supabase.auth.sign_out()
        st.session_state.clear()
        st.rerun()

current_user = load_user_data()



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




def get_part_data(row):
    part_number = row["mpn_normalized"]

    part_data = get_best_part_data(part_number)
    part_data["quantity"] = row.get("quantity", 0)

    alternative_part_numbers = suggest_alternatives_v2(part_number)

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



def analyze_bom(df):
    df = normalize_bom_columns(df)
    df = validate_bom(df)
    df = clean_bom_data(df)

    results = []

    for _, row in df.iterrows():
        part_data = get_part_data(row)
        risk_result = calculate_risk(part_data)

        results.append(
            {
                "MPN": row["mpn"],
                "Normalized MPN": row["mpn_normalized"],

                # Supplier / part identity
                "Manufacturer": part_data.get("manufacturer", ""),
                "Manufacturer Part Number": part_data.get("manufacturer_part_number", ""),
                "Description": part_data.get("description", ""),

                # BOM input quantity
                "Quantity": row.get("quantity", 0),

                # Market data
                "Best Source": part_data.get("source", ""),
                "Supplier Count": part_data.get("supplier_count", 0),
                "Total Market Stock": part_data.get("total_market_stock", 0),
                "Sources Available": part_data.get("sources_available", ""),               
                "Stock Available": part_data.get("stock_total", 0), 
                "Lead Time Weeks": part_data.get("lead_time_weeks", None),

                # Lifecycle / links
                "Lifecycle Status": part_data.get("lifecycle_status", "Unknown"),
                "Product URL": part_data.get("product_detail_url", ""),

                # Alternatives
                "Has Alternates": part_data.get("has_alternates", False),
                "Alternate Count": part_data.get("alternate_count", 0),
                "Alternative Part Numbers": part_data.get("alternative_part_numbers", ""),

                # Risk scoring
                "Risk Score": risk_result["risk_score"],
                "Risk Level": risk_result["risk_level"],
                "Risk Reasons": "; ".join(risk_result["risk_reasons"]) or "No major risk found",               
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

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("BOM Health Score", f"{bom_health_score}/100")
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

    if high_risk > 0:
        recommended_actions.append(
            "Review high-risk parts immediately and confirm whether they are acceptable for production."
        )

    single_source_count = len(results_df[results_df["Supplier Count"] <= 1])
    if single_source_count > 0:
        recommended_actions.append(
            f"Investigate {single_source_count} single-source parts and identify secondary suppliers or alternates."
        )

    no_stock_count = len(results_df[results_df["Stock Available"] == 0])
    if no_stock_count > 0:
        recommended_actions.append(
            f"Prioritize sourcing review for {no_stock_count} parts with no available stock."
        )

    unknown_lifecycle_count = len(results_df[results_df["Lifecycle Status"] == "Unknown"])
    if unknown_lifecycle_count > 0:
        recommended_actions.append(
            f"Verify lifecycle status for {unknown_lifecycle_count} parts marked as Unknown."
        )

    if not recommended_actions:
        recommended_actions.append(
            "No immediate sourcing risks detected. Continue monitoring lifecycle and stock availability."
        )

    for action in recommended_actions:
        st.write(f"• {action}")


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

st.sidebar.write(
    f"**BOMs used this month:** "
    f"{monthly_upload_count} / "
    f"{selected_plan['monthly_bom_limit']}"
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

        risk_distribution = (
            history_df["risk_level"]
            .value_counts()
            .reset_index()
        )

        risk_distribution.columns = ["Risk Level", "Part Count"]

        lifecycle_distribution = (
            history_df["lifecycle_status"]
            .value_counts()
            .reset_index()
        )

        lifecycle_distribution.columns = ["Lifecycle Status", "Part Count"]

        top_manufacturer = (
            history_df["manufacturer"]
            .value_counts()
            .idxmax()
        )

        high_risk_count = (
            history_df["risk_level"] == "High"
        ).sum()

        obsolete_count = (
            history_df["lifecycle_status"]
            .astype(str)
            .str.contains("obsolete", case=False, na=False)
        ).sum()

        top_risk_parts = (
            history_df.sort_values("risk_score", ascending=False)
            .head(5)
        )

        top_risk_display = top_risk_parts[
            [
                "mpn",
                "manufacturer",
                "risk_score",
                "risk_level",
                "risk_reasons",
                "lifecycle_status",
            ]
        ].rename(
            columns={
                "mpn": "Part Number",
                "manufacturer": "Manufacturer",
                "risk_score": "Risk Score",
                "risk_level": "Risk Level",
                "risk_reasons": "Risk Reasons",
                "lifecycle_status": "Lifecycle Status",
            }
        )

        top_risk_display["Risk Level"] = (
            top_risk_display["Risk Level"]
            .replace(
                {
                    "High": "🔴 High",
                    "Medium": "🟠 Medium",
                    "Low": "🟢 Low",
                }
            )
        )

        summary_df = (
            history_df.groupby(
                ["analysis_id", "project_name", "created_at"]
            )
            .agg(
                total_parts=("mpn", "count"),
                high_risk_parts=("risk_level", lambda x: (x == "High").sum()),
                medium_risk_parts=("risk_level", lambda x: (x == "Medium").sum()),
                low_risk_parts=("risk_level", lambda x: (x == "Low").sum()),
            )
            .reset_index()
            .sort_values("created_at", ascending=False)
        )

        summary_df["created_at"] = pd.to_datetime(
            summary_df["created_at"]
        ).dt.strftime("%Y-%m-%d")

        summary_display_df = summary_df[
            [
                "project_name",
                "created_at",
                "total_parts",
                "high_risk_parts",
                "medium_risk_parts",
                "low_risk_parts",
            ]
        ].rename(
            columns={
                "project_name": "Project Name",
                "created_at": "Created At",
                "total_parts": "Total Parts",
                "high_risk_parts": "High Risk Parts",
                "medium_risk_parts": "Medium Risk Parts",
                "low_risk_parts": "Low Risk Parts",
            }
        )

        st.dataframe(
            summary_display_df,
            use_container_width=True,
        )

        st.divider()

        st.subheader("Top 5 Critical Parts")

        st.dataframe(
            top_risk_display,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.subheader("Risk Level Distribution")

            st.bar_chart(
                risk_distribution,
                x="Risk Level",
                y="Part Count",
            )
            st.subheader("Risk Composition")

            risk_pie_data = risk_distribution.set_index("Risk Level")

            fig = risk_pie_data.plot.pie(
                y="Part Count",
                autopct="%1.1f%%",
                legend=False,
                ylabel="",
                figsize=(2, 2),
            ).figure

            st.pyplot(fig, use_container_width=False)

        with chart_col2:
            st.subheader("Lifecycle Status Distribution")

            st.bar_chart(
                lifecycle_distribution,
                x="Lifecycle Status",
                y="Part Count",
            )

        st.subheader("Executive Insights")

        insight_col1, insight_col2, insight_col3, insight_col4 = st.columns(4)

        with insight_col1:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-label">High-Risk Parts</div>
                    <div class="kpi-value">{high_risk_count}</div>
                    <div class="kpi-note">Across saved analyses</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with insight_col2:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-label">Top Manufacturer</div>
                    <div class="kpi-value">{top_manufacturer}</div>
                    <div class="kpi-note">Most analyzed supplier</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with insight_col3:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-label">Obsolete / EOL</div>
                    <div class="kpi-value">{obsolete_count}</div>
                    <div class="kpi-note">Potential redesign targets</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with insight_col4:
            st.markdown(
                """
                <div class="kpi-card">
                    <div class="kpi-label">Recommended Action</div>
                    <div class="kpi-value">Review</div>
                    <div class="kpi-note">Mitigate sourcing risks</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.divider()

        st.subheader("View Saved Analysis Details")



        analysis_options = {
            f"{row['project_name']} — {row['created_at']}": row["analysis_id"]
            for _, row in summary_df.iterrows()
        }

        selected_analysis_label = st.selectbox(
            "Choose an analysis to view",
            list(analysis_options.keys())
        )

        selected_analysis_id = analysis_options[selected_analysis_label]

        selected_parts = history_df[
            history_df["analysis_id"] == selected_analysis_id
        ]

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
                                st.metric("Lowest Unit Price", f"${lowest_unit_price:.2f}")

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
            supabase.table("analysis_parts").delete().eq(
                "analysis_id",
                selected_analysis_id
            ).eq(
                "user_id",
                current_user["id"]
            ).execute()

            st.success("Saved analysis deleted.")
            st.rerun()

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

    with chart_col2:
        st.subheader("Manufacturer Concentration")

        if history:
            manufacturer_chart_data = (
                history_df["manufacturer"]
                .value_counts()
                .reset_index()
            )

            manufacturer_chart_data.columns = ["Manufacturer", "Part Count"]

            manufacturer_chart_data["Portfolio %"] = (
                manufacturer_chart_data["Part Count"]
                / manufacturer_chart_data["Part Count"].sum()
                * 100
            ).round(1)

            st.bar_chart(
                manufacturer_chart_data,
                x="Manufacturer",
                y="Part Count",
            )

            st.subheader("Top Manufacturers")

            st.dataframe(
                manufacturer_chart_data.head(5),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No manufacturer data yet.")

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

    monitor_history = (
        supabase.table("part_monitor_history")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )

    monitor_df = pd.DataFrame(monitor_history.data)

    if not monitor_df.empty:
        st.dataframe(monitor_df, use_container_width=True)
    else:
        st.info("No monitoring history available yet.")

    st.stop()
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
    if original_part:
        suggested_alternatives = suggest_alternatives_v2(original_part)

        if suggested_alternatives:
            st.info(
                "Suggested alternatives found: "
                + ", ".join(suggested_alternatives)
            )

            st.caption("Click 'Compare Parts' to evaluate alternatives.")

            ranked_df = rank_alternatives(suggested_alternatives)

            if not ranked_df.empty:
                suggested_alternatives = ranked_df["MPN"].head(3).tolist()

                st.markdown("### Step 2 — Ranked Alternative Candidates")
                st.dataframe(ranked_df, use_container_width=True, hide_index=True)

                best_candidate = ranked_df.iloc[0]

                st.success(
                    f"🏆 Recommended Alternative: **{best_candidate['Matched MPN']}** "
                    f"(Risk: {best_candidate['Risk Level']}, "
                    f"Stock: {best_candidate['Total Market Stock']})"
                )
                st.warning(
                    "Recommendations are based on sourcing and availability. "
                    "Engineers must verify form, fit, function, and datasheet compatibility."
                )
        else:
            st.warning("No suggested alternatives found. You can still enter alternatives manually.")
    else:
        suggested_alternatives = []

    if suggested_alternatives:
        st.divider()
        st.subheader("Step 2: Compare Alternatives")

        alternatives_input = st.text_input(
            "Enter alternative part numbers (comma-separated)",
            value=", ".join(suggested_alternatives),
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

    if uploaded_file.name.endswith(".csv"):
        bom_df = pd.read_csv(uploaded_file)
    else:
        bom_df = pd.read_excel(uploaded_file)


    if st.session_state.get("uploaded_filename") != uploaded_file.name:
        st.session_state.pop("results_df", None)
        st.session_state["uploaded_filename"] = uploaded_file.name


    st.subheader("Uploaded BOM Preview")
    st.dataframe(bom_df, use_container_width=True)


    if st.button("Analyze BOM", type="primary"):
        allowed, message = validate_bom_against_plan(
            bom_df,
            selected_plan,
            monthly_upload_count,
        )

        if not allowed:
            st.error(message)
            upgrade_plan = selected_plan.get("upgrade_to")

            if upgrade_plan:
                next_plan = get_plan(upgrade_plan)

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
                if st.button("🚀 Upgrade Now", key="upgrade_button_main"):
                    st.session_state["show_upgrade_modal"] = True
        else:
            st.success(message)

            with st.spinner("Analyzing BOM... fetching supplier data, checking lifecycle status, and calculating risk scores."):
                st.session_state["results_df"] = analyze_bom(bom_df)

            results_df = st.session_state["results_df"]

            

            high_count = len(results_df[results_df["Risk Level"] == "High"])
            medium_count = len(results_df[results_df["Risk Level"] == "Medium"])
            low_count = len(results_df[results_df["Risk Level"] == "Low"])
            total_parts = len(results_df)

            high_count = len(results_df[results_df["Risk Level"] == "High"])
            medium_count = len(results_df[results_df["Risk Level"] == "Medium"])
            low_count = len(results_df[results_df["Risk Level"] == "Low"])
            total_parts = len(results_df)

            health_data = calculate_bom_health_score(results_df)

            analysis_response = supabase.table("analyses").insert(
                {
                    "user_id": current_user["id"],
                    "project_name": project_name or uploaded_file.name,
                    "filename": uploaded_file.name,
                    "total_parts": total_parts,
                    "high_risk_count": high_count,
                    "medium_risk_count": medium_count,
                    "low_risk_count": low_count,
                    "health_score": health_data["health_score"],
                }
            ).execute()

            analysis_id = analysis_response.data[0]["id"]

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

            for _, row in results_df.iterrows():
                latest_monitor = (
                    supabase.table("part_monitor_history")
                    .select("*")
                    .eq("user_id", current_user["id"])
                    .eq("part_number", row.get("part_number", ""))
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

                if latest_monitor_data:

                    previous_stock = latest_monitor_data.get("stock", 0) or 0
                    current_stock = row.get("stock", 0) or 0

                    previous_price = float(latest_monitor_data.get("unit_price", 0) or 0)
                    current_price = float(row.get("unit_price", 0) or 0)

                    previous_lifecycle = str(
                        latest_monitor_data.get("lifecycle_status", "")
                    ).lower()

                    current_lifecycle = str(
                        row.get("lifecycle_status", "")
                    ).lower()

                    # Stock drop detection
                    if previous_stock > 0 and current_stock < previous_stock * 0.5:
                        monitor_alerts.append(
                            f"⚠ Stock dropped from {previous_stock} to {current_stock}"
                        )

                    # Price increase detection
                    if previous_price > 0 and current_price > previous_price * 1.5:
                        monitor_alerts.append(
                            f"⚠ Unit price increased from ${previous_price:.2f} to ${current_price:.2f}"
                        )

                    # Lifecycle deterioration detection
                    if previous_lifecycle != current_lifecycle:
                        monitor_alerts.append(
                            f"⚠ Lifecycle changed from {previous_lifecycle} to {current_lifecycle}"
                        )
                    if monitor_alerts:
                        st.warning(
                            f"{row.get('part_number', '')}: "
                            + " | ".join(monitor_alerts)
                        )

                monitor_records.append(
                    {
                        "user_id": current_user["id"],
                        "part_number": row.get("Part Number", ""),
                        "supplier": row.get("Supplier", ""),
                        "lifecycle_status": row.get("Lifecycle Status", ""),
                        "stock": row.get("Stock Available", 0),
                        "unit_price": row.get("Unit Price", 0.0),
                        "risk_level": row.get("Risk Level", ""),
                    }
                )

            if monitor_records:
                try:
                    supabase.table("part_monitor_history").insert(
                        monitor_records
                    ).execute()

                except Exception as e:
                    st.error(f"Could not save monitoring history: {e}")

            new_upload_count = monthly_upload_count + 1

            supabase.table("users").update(
                {
                    "monthly_upload_count": new_upload_count
                }
            ).eq(
                "id",
                current_user["id"]
            ).execute()

            monthly_upload_count = new_upload_count


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
            with st.expander(f"{row['MPN']} — {row['Risk Level']} Risk"):

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