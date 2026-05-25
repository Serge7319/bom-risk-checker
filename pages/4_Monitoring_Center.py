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

alert_response = (
    supabase.table("monitor_alerts")
    .select("*")
    .eq("user_id", user_id)
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
    st.metric("Monitored Parts", len(history_df))

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

st.subheader("🚨 Active Alerts")

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

    st.dataframe(
        alerts_df[available_columns],
        use_container_width=True,
    )