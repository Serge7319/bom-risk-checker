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

st.write("Alerts loaded:", len(alerts_df))
st.write("Monitoring records loaded:", len(history_df))