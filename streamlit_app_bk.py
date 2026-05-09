import streamlit as st
import pandas as pd

from src.bom_parser import normalize_bom_columns, validate_bom, clean_bom_data
from src.risk_engine import calculate_risk
from src.report_generator import save_results_to_excel
from integrations.supplier_aggregator import get_best_part_data
from src.health_score import calculate_bom_health_score, generate_executive_summary
from src.plans import PLANS, get_plan, validate_bom_against_plan
from src.alternative_engine import compare_parts, suggest_alternatives_v2, rank_alternatives

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

                # Risk scoring
                "Risk Score": risk_result["risk_score"],
                "Risk Level": risk_result["risk_level"],
                "Risk Reasons": "; ".join(risk_result["risk_reasons"]) or "No major risk found",               
            }
        )

    return pd.DataFrame(results)


def risk_badge(level):
    if level == "High":
        return "🔴 High"
    if level == "Medium":
        return "🟡 Medium"
    return "🟢 Low"


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
        "Reports",
        "Pricing",
        "About",
    ],
)

st.sidebar.subheader("Subscription")

# Default user plan
if "selected_plan" not in st.session_state:
    st.session_state["selected_plan"] = "Starter"

selected_plan_name = st.session_state["selected_plan"]
selected_plan = get_plan(selected_plan_name)


st.sidebar.markdown(f"### {selected_plan_name}")

if "monthly_upload_count" not in st.session_state:
    st.session_state["monthly_upload_count"] = 0
st.sidebar.write(f"**Monthly BOM limit:** {selected_plan['monthly_bom_limit']}")
st.sidebar.write(f"**Max parts per BOM:** {selected_plan['max_parts_per_bom']}")
st.sidebar.caption(selected_plan["description"])

st.sidebar.write(
    f"**BOMs used this month:** {st.session_state['monthly_upload_count']} / {selected_plan['monthly_bom_limit']}"
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

    st.info("Executive analytics dashboard coming soon.")

    st.stop()


# ---------- Reports ----------
if app_mode == "Reports":
    st.subheader("Reports")

    st.info("Saved reports and exports coming soon.")

    st.stop()


# ---------- Pricing ----------
if app_mode == "Pricing":
    st.subheader("Pricing")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### Starter")
        st.write("$29/mo")
        st.write("5 BOMs/month")
        st.write("10 parts/BOM")

    with col2:
        st.markdown("### Pro 🚀")
        st.write("$99/mo")
        st.write("10 BOMs/month")
        st.write("20 parts/BOM")

    with col3:
        st.markdown("### Business")
        st.write("$299/mo")
        st.write("25 BOMs/month")
        st.write("100 parts/BOM")

    st.stop()


# ---------- About ----------
if app_mode == "About":
    st.subheader("About BOM Risk Checker")

    st.write(
        """
        BOM Risk Checker helps engineering teams identify supply chain risk,
        lifecycle issues, and alternative components before production problems occur.
        """
    )

    st.stop()

if app_mode == "Alternative Finder":
    st.subheader("Alternative Finder")
    st.write("Search for substitute parts and compare sourcing risk.")

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

                st.subheader("Ranked Alternative Candidates")
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

                st.subheader("Comparison Results")

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

                st.dataframe(
                    comparison_df[display_cols],
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
    uploaded_file = st.file_uploader("Upload your BOM file", type=["csv", "xlsx"])

    if uploaded_file is None:
        st.info("Upload a CSV or Excel BOM to begin.")
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
            st.session_state["monthly_upload_count"],
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
            st.session_state["results_df"] = analyze_bom(bom_df)
            st.session_state["monthly_upload_count"] += 1


    if "results_df" in st.session_state:
        results_df = st.session_state["results_df"]

        results_df["Risk Level Display"] = results_df["Risk Level"].apply(risk_badge)

        high_count = len(results_df[results_df["Risk Level"] == "High"])
        medium_count = len(results_df[results_df["Risk Level"] == "Medium"])
        low_count = len(results_df[results_df["Risk Level"] == "Low"])
        total_parts = len(results_df)
        health_data = calculate_bom_health_score(results_df)
        executive_bullets = generate_executive_summary(results_df)

        st.subheader("Risk Summary")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Parts", total_parts)
        col2.metric("High Risk", high_count)
        col3.metric("Medium Risk", medium_count)
        col4.metric("Low Risk", low_count)
        
        st.subheader("BOM Health Score")

        st.metric(
            "Overall BOM Health",
            f"{health_data['health_score']} / 100",
            health_data["health_status"],
        )

        st.write(health_data["summary_message"])

        st.subheader("Executive Summary")

        for bullet in executive_bullets:
            st.write(f"• {bullet}")

        st.subheader("BOM Health Overview")
        st.write(f"🔴 {high_count} critical components need immediate attention.")
        st.write(f"🟡 {medium_count} components should be monitored.")
        st.write(f"🟢 {low_count} components are currently healthy.")

        chart_data = pd.DataFrame(
            {
                "Risk Level": ["High", "Medium", "Low"],
                "Count": [high_count, medium_count, low_count],
            }
        )

        st.bar_chart(chart_data, x="Risk Level", y="Count")

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
        "Manufacturer Part Number",
        "Best Source",
        "Supplier Count",
        "Total Market Stock",
        "Sources Available",
        "Quantity",
        "Lifecycle Status",
        "Stock Available",
        "Lead Time Weeks",
        "Risk Score",
        "Risk Level Display",
        "Risk Reasons",
        ]


        st.dataframe(
            filtered_df[display_columns],
            use_container_width=True,
            hide_index=True,
        )

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
                    st.session_state["selected_plan"] = "Pro"
                    st.session_state["monthly_upload_count"] = 0
                    st.session_state["show_upgrade_modal"] = False
                    st.success("🎉 You are now on the Pro plan!")

            with col3:
                st.markdown("### Business")
                st.write("$299/mo")
                st.write("25 BOMs/month")
                st.write("100 parts per BOM")
                if st.button("Select Business", key="select_business"):
                    st.session_state["selected_plan"] = "Business"
                    st.session_state["monthly_upload_count"] = 0
                    st.session_state["show_upgrade_modal"] = False
                    st.success("🎉 You are now on the Business plan!")