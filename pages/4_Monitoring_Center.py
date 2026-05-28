import streamlit as st
import pandas as pd
from supabase import create_client

st.title("📡 Monitoring Center")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)

if "user" not in st.session_state:
    st.warning("Please log in.")
    st.stop()

current_user = st.session_state["user"]

user_id = current_user.id
user_email = current_user.email


st.success(f"Monitoring dashboard loaded for {user_email}")

search_col1, search_col2 = st.columns([6, 1])

with search_col1:
    part_search_input = st.text_input(
        "Search Part Number",
        placeholder="e.g. STM32, ESP32, LM555...",
    )

with search_col2:
    st.write("")
    st.write("")

    search_clicked = st.button(
        "Search",
        use_container_width=True,
    )

if search_clicked:
    st.session_state["part_search"] = part_search_input

part_search = st.session_state.get("part_search", "")

show_acknowledged = st.checkbox(
    "Show acknowledged alerts",
    value=False,
)

alert_query = (
    supabase.table("monitor_alerts")
    .select("*")
    .eq("user_id", user_id)
)

if not show_acknowledged:
    alert_query = alert_query.eq("acknowledged", False)

alert_response = (
    alert_query
    .order("created_at", desc=True)
    .limit(100)
    .execute()
)

alerts_df = pd.DataFrame(alert_response.data or [])

history_response = (
    supabase.table("part_monitor_history")
    .select("*")
    .eq("user_id", user_id)
    .order("created_at", desc=True)
    .limit(500)
    .execute()
)

history_df = pd.DataFrame(history_response.data or [])



col1, col2, col3, col4 = st.columns(4)

with col1:
    unique_monitored_parts = (
        history_df["part_number"].nunique()
        if not history_df.empty and "part_number" in history_df.columns
        else 0
    )

    st.metric("Monitored Parts", unique_monitored_parts)

with col2:
    st.metric("Active Alerts", len(alerts_df))

with col3:
    high_alerts = (
        len(alerts_df[alerts_df["severity"] == "High"])
        if not alerts_df.empty and "severity" in alerts_df.columns
        else 0
    )

    st.metric("High Severity", high_alerts)

with col4:
    obsolete_parts = (
        len(
            history_df[
                history_df["lifecycle_status"]
                .astype(str)
                .str.contains("obsolete", case=False, na=False)
            ]
        )
        if not history_df.empty and "lifecycle_status" in history_df.columns
        else 0
    )

    st.metric("Obsolete Parts", obsolete_parts)

st.divider()

st.subheader("📊 Lifecycle Status Distribution")

if history_df.empty or "lifecycle_status" not in history_df.columns:
    st.info("No lifecycle data available yet.")
else:
    latest_parts_for_chart = (
        history_df
        .sort_values("created_at", ascending=False)
        .drop_duplicates(subset=["part_number"])
    )

    lifecycle_counts = (
        latest_parts_for_chart["lifecycle_status"]
        .fillna("Unknown")
        .replace("", "Unknown")
        .value_counts()
        .reset_index()
    )

    lifecycle_counts.columns = ["Lifecycle Status", "Part Count"]

    st.plotly_chart(
        {
            "data": [
                {
                    "labels": lifecycle_counts["Lifecycle Status"],
                    "values": lifecycle_counts["Part Count"],
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



st.divider()

st.subheader("🚨 Active Alerts")

severity_filter = st.selectbox(
    "Filter by Severity",
    ["All", "High", "Medium", "Low"],
)

if alerts_df.empty:
    st.info("No active alerts found.")
else:
    alert_columns = [
        "part_number",
        "alert_type",
        "alert_message",
        "severity",
        "created_at",
    ]

    available_columns = [
        col for col in alert_columns if col in alerts_df.columns
    ]

    filtered_alerts_df = alerts_df.copy()

    if part_search:
        filtered_alerts_df = filtered_alerts_df[
            filtered_alerts_df["part_number"]
            .astype(str)
            .str.contains(part_search, case=False, na=False)
        ]

    if severity_filter != "All":
        filtered_alerts_df = filtered_alerts_df[
            filtered_alerts_df["severity"] == severity_filter
        ]

    display_alerts_df = filtered_alerts_df[available_columns].rename(
        columns={
            "part_number": "Part Number",
            "alert_type": "Alert Type",
            "alert_message": "Alert Message",
            "severity": "Severity",
            "created_at": "Created At",
        }
    )

    display_alerts_df["Created At"] = pd.to_datetime(
        display_alerts_df["Created At"],
        errors="coerce",
    ).dt.strftime("%b %d, %Y %I:%M %p")

    styled_alerts_df = display_alerts_df.style.map(
        lambda value:
            "color: red; font-weight: bold"
            if value == "High"
            else (
                "color: orange; font-weight: bold"
                if value == "Medium"
                else (
                    "color: lightgreen; font-weight: bold"
                    if value == "Low"
                    else ""
                )
            ),
        subset=["Severity"],
    )

    st.dataframe(
        styled_alerts_df,
        use_container_width=True,
    )

    if not filtered_alerts_df.empty:
        alert_options = {
            f"{row['part_number']} — {row['alert_type']} — {row['created_at']}": row["id"]
            for _, row in filtered_alerts_df.iterrows()
            if "id" in filtered_alerts_df.columns
        }

        selected_alert = st.selectbox(
            "Select alert to acknowledge",
            ["None"] + list(alert_options.keys()),
        )

        if selected_alert != "None":
            if st.button("Acknowledge Selected Alert"):
                supabase.table("monitor_alerts").update(
                    {"acknowledged": True}
                ).eq(
                    "id", alert_options[selected_alert]
                ).execute()

                st.success("Alert acknowledged. Refreshing...")
                st.rerun()

st.divider()

st.subheader("📦 Latest Monitored Parts")

if history_df.empty:
    st.info("No monitored parts found.")
else:
    latest_parts = (
        history_df
        .sort_values("created_at", ascending=False)
        .drop_duplicates(subset=["part_number"])
    )

    if part_search:
        latest_parts = latest_parts[
            latest_parts["part_number"]
            .astype(str)
            .str.contains(part_search, case=False, na=False)
        ]

    part_columns = [
        "part_number",
        "supplier",
        "lifecycle_status",
        "stock",
        "unit_price",
        "risk_level",
        "created_at",
    ]

    available_part_columns = [
        col for col in part_columns
        if col in latest_parts.columns
    ]

    display_parts_df = latest_parts[available_part_columns].rename(
        columns={
            "part_number": "Part Number",
            "supplier": "Supplier",
            "lifecycle_status": "Lifecycle Status",
            "stock": "Stock",
            "unit_price": "Unit Price",
            "risk_level": "Risk Level",
            "created_at": "Last Checked",
        }
    )

    display_parts_df["Last Checked"] = pd.to_datetime(
        display_parts_df["Last Checked"],
        errors="coerce",
    ).dt.strftime("%b %d, %Y %I:%M %p")

    st.dataframe(
        display_parts_df,
        use_container_width=True,
    )